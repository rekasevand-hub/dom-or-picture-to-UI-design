"""Real Figma R5-P3 controlled-timeout and resume probe.

The probe runs a short-timeout bridge to force an unknown create outcome, then
restarts the bridge with the normal timeout so ownership markers can be read
back. It never resends the unknown write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.bridge_config import load_bridge_config  # noqa: E402
from src.app.services.job_namespace import build_job_namespace  # noqa: E402
from src.app.services.rendering.figma_adapter import (  # noqa: E402
    FigmaBridgeAdapter,
    FigmaBridgeError,
)
from src.app.services.rendering.write_job_ledger import (  # noqa: E402
    OwnedBatchCoordinator,
    WriteJobLedger,
    WriteJobState,
)


def build_real_resume_report(
    *,
    job_id: str,
    bridge_state: str,
    ownership_classification: str,
    resume_action: str,
    resend_allowed: bool,
    cleanup_removed: int,
    post_cleanup_matched: int,
    unknown_count: int,
    duplicate_side_effects: int,
) -> dict[str, Any]:
    checks = {
        "unknown_behaviour_observed": bridge_state == "unknown",
        "ownership_markers_complete": ownership_classification == "matches-intended",
        "resume_is_reconcile_no_resend": resume_action == "reconcile-no-resend",
        "no_resend_or_duplicate_side_effect": (
            not resend_allowed and duplicate_side_effects == 0
        ),
        "unknown_was_retained": unknown_count >= 1,
        "cleanup_complete": cleanup_removed > 0 and post_cleanup_matched == 0,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "r5-p3-real-resume/1.0",
        "experiment": "R5-P3-REAL-RESUME",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "bridge_state": bridge_state,
        "ownership_classification": ownership_classification,
        "resume_action": resume_action,
        "resend_allowed": resend_allowed,
        "cleanup_removed": cleanup_removed,
        "post_cleanup_matched": post_cleanup_matched,
        "unknown_count": unknown_count,
        "duplicate_side_effects": duplicate_side_effects,
        **checks,
        "failed_checks": failed_checks,
        "status": "pass" if not failed_checks else "fail",
    }


class BridgeProcess:
    def __init__(
        self,
        *,
        out: Path,
        journal: Path,
        timeout: float,
        log_name: str,
    ) -> None:
        self.out = out
        self.journal = journal
        self.timeout = timeout
        self.log_name = log_name
        self.process: subprocess.Popen[bytes] | None = None
        self.stdout_handle: Any | None = None
        self.stderr_handle: Any | None = None
        self.stderr_path = self.out / f"{self.log_name}.stderr.log"
        self.config_path = self.out / f"{self.log_name}.config.json"

    def start(self) -> None:
        if self.process is not None:
            return
        stdout_path = self.out / f"{self.log_name}.stdout.log"
        self.stdout_handle = stdout_path.open("wb")
        self.stderr_handle = self.stderr_path.open("wb")
        template = json.loads(
            load_bridge_config().config_path.read_text(encoding="utf-8")
        )
        template["allow_env_overrides"] = False
        template["server"]["timeout"] = self.timeout
        template["server"]["journal_path"] = str(self.journal)
        template["server"]["exclusive_journal_lock"] = True
        template["server"]["auth_token"] = ""
        template["server"]["client_tokens"] = {}
        template["client"]["auth_token"] = ""
        template["client"]["client_token"] = ""
        template["client"]["client_id"] = ""
        self.config_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["FIGMA_BRIDGE_CONFIG"] = str(self.config_path)
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        )
        self.process = subprocess.Popen(
            [sys.executable, "-m", "src.app.services.bridge_server"],
            cwd=str(Path(__file__).resolve().parents[1]),
            env=env,
            stdout=self.stdout_handle,
            stderr=self.stderr_handle,
            creationflags=creationflags,
        )
        self._wait_for_server()

    def _wait_for_server(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stderr_path.exists():
                text = self.stderr_path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
                if "server listening" in text:
                    return
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"bridge exited during startup: {self.process.returncode}"
                )
            time.sleep(0.05)
        raise RuntimeError("bridge server did not become ready")

    def wait_for_plugin_connection(self, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stderr_path.exists():
                text = self.stderr_path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
                if "connection open" in text:
                    return
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"bridge exited before plugin connection: {self.process.returncode}"
                )
            time.sleep(0.1)
        raise RuntimeError("Figma plugin did not reconnect to bridge")

    def stop(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.process = None
        for handle in (self.stdout_handle, self.stderr_handle):
            if handle is not None:
                handle.flush()
                handle.close()
        self.stdout_handle = None
        self.stderr_handle = None

    def __enter__(self) -> "BridgeProcess":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


def _wait_ownership_readback(
    adapter: FigmaBridgeAdapter,
    job_id: str,
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            latest = adapter.transaction_status(job_id)
            transaction = latest.get("transaction")
            payload = transaction if isinstance(transaction, dict) else latest
            if isinstance(payload.get("ownershipReadback"), dict):
                return payload
        except (OSError, RuntimeError, FigmaBridgeError):
            pass
        time.sleep(0.1)
    raise RuntimeError(f"ownership readback did not arrive: {latest}")


def run_probe(
    *,
    out: Path,
    job_id: str,
    bridge_url: str,
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    journal = out / "bridge-journal.jsonl"
    ledger_path = out / "write-jobs.jsonl"
    ledger = WriteJobLedger(ledger_path)
    client_id = "r5-p3-real-resume"
    namespaced_job_id = build_job_namespace(client_id, job_id)
    report: dict[str, Any] = {
        "schema_version": "r5-p3-real-resume/1.1",
        "experiment": "R5-P3-REAL-RESUME",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "namespaced_job_id": namespaced_job_id,
        "client_id": client_id,
        "status": "failed",
    }
    normal_bridge: BridgeProcess | None = None
    short_bridge: BridgeProcess | None = None
    adapter: FigmaBridgeAdapter | None = None
    try:
        if journal.exists():
            raise RuntimeError(
                f"journal already exists; use a fresh output directory: {journal}"
            )
        # Normal bridge for a scoped pre-cleanup.
        normal_bridge = BridgeProcess(
            out=out,
            journal=journal,
            timeout=30,
            log_name="bridge-preclean",
        )
        normal_bridge.start()
        normal_bridge.wait_for_plugin_connection()
        adapter = FigmaBridgeAdapter(
            bridge_url,
            timeout=5,
            client_id=client_id,
        )
        adapter.connect()
        report["preclean"] = adapter.cleanup_owned_job(namespaced_job_id)
        adapter.disconnect()
        normal_bridge.stop()
        normal_bridge = None

        # Force a real unknown after the plugin is known to be connected.
        short_bridge = BridgeProcess(
            out=out,
            journal=journal,
            timeout=0.001,
            log_name="bridge-short-timeout",
        )
        short_bridge.start()
        short_bridge.wait_for_plugin_connection()
        adapter = FigmaBridgeAdapter(
            bridge_url,
            timeout=5,
            client_id=client_id,
        )
        adapter.connect()
        coordinator = OwnedBatchCoordinator(adapter, ledger)
        created = coordinator.create_owned_batch(
            job_id,
            [
                {
                    "action": "create_frame",
                    "params": {
                        "name": f"R5 Resume Probe {job_id}",
                        "width": 120,
                        "height": 80,
                        "fillColor": "#ffffff",
                    },
                }
            ],
            request_id=f"{job_id}-request",
        )
        report["created_record"] = created.to_dict()
        if created.state is not WriteJobState.UNKNOWN:
            raise RuntimeError(f"expected unknown create, got {created.state}")
        # Let the plugin finish the already-sent action; do not reconnect or
        # dispatch another write on the short-timeout bridge.
        time.sleep(1.0)
        adapter.disconnect()
        short_bridge.stop()
        short_bridge = None

        # Normal bridge replays the durable intent and reads ownership markers.
        normal_bridge = BridgeProcess(
            out=out,
            journal=journal,
            timeout=30,
            log_name="bridge-normal-resume",
        )
        normal_bridge.start()
        normal_bridge.wait_for_plugin_connection()
        adapter = FigmaBridgeAdapter(
            bridge_url,
            timeout=30,
            client_id=client_id,
        )
        adapter.connect()
        status = _wait_ownership_readback(adapter, namespaced_job_id)
        report["resume_status"] = status
        coordinator = OwnedBatchCoordinator(adapter, ledger)
        decision = coordinator.resume_job(namespaced_job_id)
        report["resume_decision"] = decision.to_dict()
        record = ledger.load(namespaced_job_id)
        if record is None:
            raise RuntimeError("ledger lost the resume job")
        report["final_record"] = record.to_dict()
        cleanup = adapter.cleanup_owned_job(namespaced_job_id)
        report["cleanup"] = cleanup
        post_cleanup = adapter.ownership_report(namespaced_job_id)
        report["post_cleanup_readback"] = post_cleanup
        bridge_state = str(status.get("state") or "")
        ownership = status.get("ownershipReconciliation")
        classification = (
            str(ownership.get("classification") or "")
            if isinstance(ownership, dict)
            else ""
        )
        journal_events = [
            json.loads(line)
            for line in journal.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        apply_batch_intents = [
            event
            for event in journal_events
            if event.get("event") == "intent"
            and event.get("action") == "apply_batch"
        ]
        unknown_transactions = {
            str(event.get("transactionId") or "")
            for event in journal_events
            if event.get("event") == "terminal"
            and event.get("transactionState") == "unknown"
            and str(event.get("transactionId") or "")
        }
        duplicate_side_effects = max(0, len(apply_batch_intents) - 1)
        result = build_real_resume_report(
            job_id=job_id,
            bridge_state=bridge_state,
            ownership_classification=classification,
            resume_action=decision.action.value,
            resend_allowed=decision.resend_allowed,
            cleanup_removed=int(cleanup.get("removed") or 0),
            post_cleanup_matched=int(post_cleanup.get("matched") or 0),
            unknown_count=len(unknown_transactions),
            duplicate_side_effects=duplicate_side_effects,
        )
        report.update(result)
        report["journal_apply_batch_intents"] = len(apply_batch_intents)
        report["journal_unknown_transactions"] = sorted(unknown_transactions)
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if adapter is not None:
            adapter.disconnect()
        if short_bridge is not None:
            short_bridge.stop()
        if normal_bridge is not None:
            normal_bridge.stop()
        _write_report(out / "figma_r5_p3_resume.json", report)
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
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--bridge-url", default="ws://localhost:8765")
    args = parser.parse_args(argv)
    report = run_probe(
        out=Path(args.out).resolve(),
        job_id=args.job_id,
        bridge_url=args.bridge_url,
    )
    print(f"[r5-p3-real] {report['status']} job={args.job_id}")
    print(f"[out ] {Path(args.out).resolve() / 'figma_r5_p3_resume.json'}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
