"""Deterministic R5-P3 ledger migration and compaction evidence probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.job_namespace import build_job_namespace  # noqa: E402
from src.app.services.rendering.write_job_ledger import (  # noqa: E402
    WriteJobLedger,
    WriteJobState,
    migrate_legacy_write_job_ledger,
)

_NOW = 1_000_000.0
_SENSITIVE_SENTINELS = ("MUST_NOT_LEAK", "action-payload-sentinel")


def _event(
    job_id: str,
    *,
    client_id: str,
    state: str,
    updated_at: float,
    fingerprint: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "version": 2,
        "event": "state",
        "job_id": job_id,
        "transaction_id": job_id,
        "client_id": client_id,
        "request_id": f"request-{state}",
        "fingerprint": fingerprint,
        "expected_created_nodes": 2,
        "state": state,
        "node_ids": ["FRAME:1", "RECTANGLE:2"],
        "bridge_state": state,
        "ownership_classification": "",
        "resume_action": "",
        "resume_requires_human": state in {"unknown", "resume-required"},
        "cleanup_status": "",
        "cleanup_matched": 0,
        "cleanup_removed": 0,
        "cleanup_failed_count": 0,
        "reason": "",
        "updated_at": updated_at,
        "raw_job_id": "",
        "namespace_version": "",
        **extra,
    }


def _legacy_events() -> list[dict[str, Any]]:
    shared = "shared-legacy-job"
    events = [
        _event(
            shared,
            client_id="legacy-a",
            state="planned",
            updated_at=10.0,
            fingerprint="a" * 64,
        ),
        _event(
            shared,
            client_id="legacy-b",
            state="planned",
            updated_at=11.0,
            fingerprint="b" * 64,
            action="create_text",
            text="MUST_NOT_LEAK",
            secret="MUST_NOT_LEAK",
        ),
        _event(
            shared,
            client_id="legacy-a",
            state="committed",
            updated_at=12.0,
            fingerprint="a" * 64,
            cleanup_status="cleaned",
            cleanup_matched=2,
            cleanup_removed=2,
            reason="owned cleanup complete",
        ),
        _event(
            shared,
            client_id="legacy-b",
            state="unknown",
            updated_at=13.0,
            fingerprint="b" * 64,
            reason="unknown must never resend",
        ),
    ]
    protected_states = (
        "planned",
        "inflight",
        "resume-required",
        "rollback-incomplete",
    )
    for index, state in enumerate(protected_states, start=1):
        events.append(
            _event(
                f"protected-{index}",
                client_id="legacy-a",
                state=state,
                updated_at=20.0 + index,
                fingerprint=hashlib.sha256(state.encode("utf-8")).hexdigest(),
            )
        )
    return events


def _write_jsonl(path: Path, events: list[Mapping[str, Any]]) -> None:
    path.write_text(
        "\n".join(
            json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for event in events
        )
        + "\n",
        encoding="utf-8",
    )


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report_hash(report: Mapping[str, Any]) -> str:
    payload = {
        key: value
        for key, value in report.items()
        if key not in {"content_hash", "report_sha256"}
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def run_probe(out: str | Path) -> dict[str, Any]:
    output = Path(out).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    migrated_path = output / "migrated-ledger.jsonl"
    compacted_path = output / "compacted-ledger.jsonl"

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "legacy-ledger.jsonl"
        dry_run_target = root / "dry-run-target.jsonl"
        _write_jsonl(source, _legacy_events())
        mapping = {
            "legacy-a": "client-a",
            "legacy-b": "client-b",
        }
        dry_run = migrate_legacy_write_job_ledger(
            source,
            dry_run_target,
            client_mapping=mapping,
            dry_run=True,
        ).to_dict()
        dry_run_no_target = not dry_run_target.exists()
        applied = migrate_legacy_write_job_ledger(
            source,
            migrated_path,
            client_mapping=mapping,
            dry_run=False,
            overwrite=True,
        ).to_dict()

    shutil.copyfile(migrated_path, compacted_path)
    ledger = WriteJobLedger(
        compacted_path,
        max_events=8,
        terminal_retention_days=1,
        compact_min_events=2,
    )
    compaction = ledger.compact(now=_NOW, force=True)
    if compaction.status != "compacted":
        raise RuntimeError("ledger compaction did not run")

    first_id = build_job_namespace("client-a", "shared-legacy-job")
    second_id = build_job_namespace("client-b", "shared-legacy-job")
    first = ledger.load(first_id)
    second = ledger.load(second_id)
    protected = [
        ledger.load(build_job_namespace("client-a", f"protected-{index}")).state.value
        for index in range(1, 5)
    ]
    fingerprint_conflict = False
    before_bytes = compacted_path.read_bytes()
    try:
        ledger.begin_job(
            job_id=first_id,
            transaction_id=first_id,
            client_id="client-a",
            request_id="request-conflict",
            expected_created_nodes=2,
            fingerprint="f" * 64,
        )
    except ValueError:
        fingerprint_conflict = True
    duplicate_preserved = compacted_path.read_bytes() == before_bytes

    migration_dry_path = output / "migration-dry-run.json"
    migration_apply_path = output / "migration-apply.json"
    compaction_path = output / "compaction.json"
    _atomic_write_json(migration_dry_path, dry_run)
    _atomic_write_json(migration_apply_path, applied)
    _atomic_write_json(
        compaction_path,
        {
            "compaction": compaction.to_dict(),
            "reconstructed_states": {
                "first_state": first.state.value,
                "second_state": second.state.value,
                "protected_states": protected,
            },
            "cleanup": {
                "status": first.cleanup_status,
                "matched": first.cleanup_matched,
                "removed": first.cleanup_removed,
                "failed": first.cleanup_failed_count,
            },
        },
    )

    checks = {
        "migration_dry_run_no_target": dry_run_no_target,
        "cross_client_same_raw_distinct": (
            first is not None
            and second is not None
            and first.job_id != second.job_id
            and first.state is WriteJobState.COMMITTED
            and second.state is WriteJobState.UNKNOWN
        ),
        "nonterminal_states_preserved": protected
        == [
            "planned",
            "inflight",
            "resume-required",
            "rollback-incomplete",
        ],
        "cleanup_receipt_preserved": (
            first.cleanup_status == "cleaned"
            and first.cleanup_matched == 2
            and first.cleanup_removed == 2
            and first.cleanup_failed_count == 0
        ),
        "duplicate_fingerprint_conflict_preserved": (
            fingerprint_conflict and duplicate_preserved
        ),
        "migration_report_sanitized": all(
            sentinel not in json.dumps(dry_run, sort_keys=True)
            and sentinel not in json.dumps(applied, sort_keys=True)
            for sentinel in (
                *_SENSITIVE_SENTINELS,
                "shared-legacy-job",
                "legacy-a",
                "legacy-b",
            )
        ),
    }
    report: dict[str, Any] = {
        "schema_version": "r5-p3-ledger-lifecycle/1.0",
        "experiment": "R5-P3-LEDGER-RETENTION-MIGRATION",
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "counts": {
            "migration_source_events": applied["counts"]["source_events"],
            "migrated_jobs": applied["counts"]["output_jobs"],
            "compaction_source_events": compaction.source_events,
            "compaction_output_events": compaction.output_events,
            "compaction_removed_events": compaction.removed_events,
            "compacted_jobs": compaction.compacted_jobs,
            "protected_jobs": compaction.protected_jobs,
        },
        "hashes": {
            "migration_source_sha256": dry_run["source_sha256"],
            "migration_candidate_sha256": applied["candidate_sha256"],
            "compaction_source_sha256": compaction.source_sha256,
            "compaction_output_sha256": compaction.output_sha256,
        },
        "boundary": {
            "deterministic": True,
            "real_figma": False,
            "production_admission": False,
        },
    }
    hashes_path = output / "hashes.json"
    _atomic_write_json(
        hashes_path,
        {
            "migration-dry-run.json": _sha256(migration_dry_path),
            "migration-apply.json": _sha256(migration_apply_path),
            "compaction.json": _sha256(compaction_path),
            "migrated-ledger.jsonl": _sha256(migrated_path),
            "compacted-ledger.jsonl": _sha256(compacted_path),
        },
    )
    report["hashes"]["evidence_sha256"] = _sha256(hashes_path)
    report_hash = _report_hash(report)
    report["report_sha256"] = report_hash
    report["content_hash"] = report_hash
    _atomic_write_json(output / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report = run_probe(args.out)
    print(f"[r5-p3-ledger-lifecycle] {report['status']}")
    print(f"[hash] {report['content_hash']}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
