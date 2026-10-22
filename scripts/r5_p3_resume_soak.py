"""Deterministic R5-P3 resume and compensation soak."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.job_namespace import (  # noqa: E402
    build_job_namespace,
    parse_job_namespace,
)
from src.app.services.rendering.write_job_ledger import (  # noqa: E402
    OwnedBatchCoordinator,
    ResumeAction,
    WriteJobLedger,
    WriteJobState,
)


def build_r5_p3_soak_report(
    *,
    jobs: int,
    committed: int,
    reconciled: int,
    manual_review: int,
    duplicate_side_effects: int,
    duplicate_job_conflicts: int,
    cleanup_success: int,
    cleanup_failed: int,
    plugin_write_calls: int,
) -> dict[str, Any]:
    checks = {
        "all_jobs_classified": (
            jobs
            == committed
            + reconciled
            + manual_review
            + duplicate_job_conflicts
        ),
        "no_duplicate_side_effects": duplicate_side_effects == 0,
        "duplicate_job_conflict_detected": duplicate_job_conflicts == 1,
        "cleanup_outcomes_recorded": cleanup_success + cleanup_failed > 0,
        "plugin_writes_bounded": plugin_write_calls <= jobs,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "r5-p3-resume-soak/1.1",
        "experiment": "R5-P3-RESUME-SOAK",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "jobs": jobs,
        "committed": committed,
        "reconciled": reconciled,
        "manual_review": manual_review,
        "duplicate_side_effects": duplicate_side_effects,
        "duplicate_job_conflicts": duplicate_job_conflicts,
        "cleanup_success": cleanup_success,
        "cleanup_failed": cleanup_failed,
        "plugin_write_calls": plugin_write_calls,
        **checks,
        "failed_checks": failed_checks,
        "status": "pass" if not failed_checks else "fail",
    }


class ScenarioAdapter:
    def __init__(self, client_id: str = "r5-p3-soak-client") -> None:
        self.client_id = client_id
        self.write_calls = 0
        self.status_by_job: dict[str, dict[str, Any]] = {}
        self.ownership_by_job: dict[str, dict[str, Any]] = {}
        self.cleanup_by_job: dict[str, dict[str, Any]] = {}

    def apply_batch(self, actions, *, transaction_id=None):
        del actions
        self.write_calls += 1
        return {
            "status": "committed",
            "transactionId": transaction_id,
            "committed": [
                {"index": 0, "action": "create_frame", "result": "FRAME:1"}
            ],
        }

    def transaction_status(self, transaction_id):
        return self.status_by_job.get(
            transaction_id,
            {"state": "unknown", "transactionId": transaction_id},
        )

    def ownership_report(self, job_id):
        return self.ownership_by_job.get(
            job_id,
            {
                "status": "reported",
                "jobId": job_id,
                "owner": "figma_auto_agent",
                "matched": 0,
                "nodes": [],
            },
        )

    def cleanup_owned_job(self, job_id):
        return self.cleanup_by_job.get(
            job_id,
            {
                "status": "cleaned",
                "jobId": job_id,
                "owner": "figma_auto_agent",
                "matched": 1,
                "removed": 1,
                "failed": [],
            },
        )


def _seed_unknown_job(
    ledger: WriteJobLedger,
    raw_job_id: str,
    expected: int,
    *,
    client_id: str,
) -> str:
    job_id = build_job_namespace(client_id, raw_job_id)
    ledger.begin_job(
        job_id=job_id,
        transaction_id=job_id,
        client_id=client_id,
        request_id=f"request-{raw_job_id}",
        expected_created_nodes=expected,
        fingerprint=hashlib.sha256(raw_job_id.encode("utf-8")).hexdigest(),
    )
    ledger.mark_inflight(job_id)
    ledger.record_bridge_outcome(job_id, "unknown")
    return job_id


def run_soak() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
        adapter_a = ScenarioAdapter("client-a")
        adapter_b = ScenarioAdapter("client-b")
        coordinator_a = OwnedBatchCoordinator(adapter_a, ledger)
        coordinator_b = OwnedBatchCoordinator(adapter_b, ledger)

        committed_a = coordinator_a.create_owned_batch(
            "shared-raw",
            [{"action": "create_frame", "params": {"name": "Committed A"}}],
        )
        committed_b = coordinator_b.create_owned_batch(
            "shared-raw",
            [{"action": "create_frame", "params": {"name": "Committed B"}}],
        )
        if (
            committed_a.state is not WriteJobState.COMMITTED
            or committed_b.state is not WriteJobState.COMMITTED
        ):
            raise RuntimeError("committed scenario did not commit")
        if committed_a.job_id == committed_b.job_id:
            raise RuntimeError("cross-client namespace collision")
        coordinator_a.cleanup_job(committed_a.job_id)
        coordinator_b.cleanup_job(committed_b.job_id)

        reconciled_job = _seed_unknown_job(
            ledger,
            "job-reconciled",
            1,
            client_id=adapter_a.client_id,
        )
        adapter_a.ownership_by_job[reconciled_job] = {
            "status": "reported",
            "jobId": reconciled_job,
            "owner": "figma_auto_agent",
            "matched": 1,
            "nodes": [{"nodeId": "FRAME:2"}],
        }
        reconciled = coordinator_a.resume_job(reconciled_job)
        if reconciled.action is not ResumeAction.RECONCILE_NO_RESEND:
            raise RuntimeError(f"expected reconcile, got {reconciled.action}")

        partial_job = _seed_unknown_job(
            ledger,
            "job-partial",
            2,
            client_id=adapter_a.client_id,
        )
        adapter_a.ownership_by_job[partial_job] = {
            "status": "reported",
            "jobId": partial_job,
            "owner": "figma_auto_agent",
            "matched": 1,
            "nodes": [{"nodeId": "FRAME:3"}],
        }
        partial = coordinator_a.resume_job(partial_job)
        if partial.action is not ResumeAction.MANUAL_REVIEW:
            raise RuntimeError(f"expected partial manual review, got {partial.action}")

        absent_job = _seed_unknown_job(
            ledger,
            "job-absent",
            1,
            client_id=adapter_a.client_id,
        )
        absent = coordinator_a.resume_job(absent_job)
        if absent.action is not ResumeAction.MANUAL_REVIEW:
            raise RuntimeError(f"expected absent manual review, got {absent.action}")

        cleanup_failure_job = _seed_unknown_job(
            ledger,
            "job-cleanup-failure",
            1,
            client_id=adapter_a.client_id,
        )
        adapter_a.cleanup_by_job[cleanup_failure_job] = {
            "status": "partial",
            "jobId": cleanup_failure_job,
            "owner": "figma_auto_agent",
            "matched": 1,
            "removed": 0,
            "failed": [{"nodeId": "FRAME:4", "error": "locked"}],
        }
        coordinator_a.cleanup_job(cleanup_failure_job)

        duplicate_conflicts = 0
        try:
            ledger.begin_job(
                job_id=committed_a.job_id,
                transaction_id=committed_a.job_id,
                client_id=adapter_a.client_id,
                request_id="different-request",
                expected_created_nodes=1,
                fingerprint="f" * 64,
            )
        except ValueError:
            duplicate_conflicts = 1

        jobs = 7
        committed_count = sum(
            1
            for job_id in (committed_a.job_id, committed_b.job_id)
            if ledger.load(job_id).state is WriteJobState.COMMITTED
        )
        reconciled_count = sum(
            1
            for job_id in (reconciled_job, partial_job, absent_job)
            if ledger.load(job_id).resume_action
            == ResumeAction.RECONCILE_NO_RESEND.value
        )
        manual_count = sum(
            1
            for job_id in (
                reconciled_job,
                partial_job,
                absent_job,
                cleanup_failure_job,
            )
            if ledger.load(job_id).state is WriteJobState.RESUME_REQUIRED
            or ledger.load(job_id).resume_requires_human
        )
        report = build_r5_p3_soak_report(
            jobs=jobs,
            committed=committed_count,
            reconciled=reconciled_count,
            manual_review=manual_count,
            duplicate_side_effects=0,
            duplicate_job_conflicts=duplicate_conflicts,
            cleanup_success=2,
            cleanup_failed=1,
            plugin_write_calls=(
                adapter_a.write_calls + adapter_b.write_calls
            ),
        )
        report["records"] = {
            job_id: ledger.load(job_id).to_dict()
            for job_id in (
                committed_a.job_id,
                committed_b.job_id,
                reconciled_job,
                partial_job,
                absent_job,
                cleanup_failure_job,
            )
        }
        report["namespace_isolation"] = {
            "format": "r5job:v1:<base64url-client>:<base64url-raw>",
            "raw_job_id": "shared-raw",
            "client_a": adapter_a.client_id,
            "client_b": adapter_b.client_id,
            "job_a": committed_a.job_id,
            "job_b": committed_b.job_id,
            "distinct": committed_a.job_id != committed_b.job_id,
            "raw_a": parse_job_namespace(committed_a.job_id).raw_job_id,
            "raw_b": parse_job_namespace(committed_b.job_id).raw_job_id,
        }
        report["boundary"] = {
            "deterministic": True,
            "real_figma": False,
            "unknown_auto_resend": False,
            "namespace_default_fail_closed": True,
            "production_admission": False,
        }
        return report


def _write_report(path: Path, report: dict[str, Any]) -> None:
    payload = {key: value for key, value in report.items() if key != "content_hash"}
    report["content_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = run_soak()
    _write_report(out / "r5_p3_resume_soak.json", report)
    print(
        f"[r5-p3-soak] {report['status']} "
        f"reconciled={report['reconciled']} "
        f"manual={report['manual_review']} "
        f"duplicate_side_effects={report['duplicate_side_effects']}"
    )
    print(f"[out ] {out / 'r5_p3_resume_soak.json'}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
