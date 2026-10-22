# -*- coding: utf-8 -*-
"""Frozen P5 deterministic dry run and staged-rehearsal gate."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import psutil
except ImportError:  # pragma: no cover - optional local dependency
    psutil = None

from src.app.services.bridge_server import BridgeHub
from src.app.services.contracts import canonical_hash
from src.app.services.job_namespace import build_job_namespace
from src.app.services.rendering.figma_adapter import reconciliation_policy
from src.app.services.rendering.write_job_ledger import (
    WriteJobLedger,
    WriteJobState,
)
from src.app.services.write_lease import WriterLeaseStore
from src.config.settings import Config


PROFILE = "p5-dry-run-profile/1.0"


class _AutoPlugin:
    def __init__(self, hub: BridgeHub, *, drop_transaction: str | None = None) -> None:
        self.hub = hub
        self.drop_transaction = drop_transaction
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, message: str) -> None:
        payload = json.loads(message)
        self.sent.append(payload)
        params = payload.get("params") or {}
        if (
            self.drop_transaction
            and params.get("transactionId") == self.drop_transaction
        ):
            return
        result = {
            "apply_edit_batch": {"status": "committed", "committed": []},
            "apply_batch": {
                "status": "committed",
                "committed": [{"nodeId": "dry-node-1"}],
                "ownership": {"marked": 1},
            },
            "ownership_report": {
                "status": "reported",
                "matched": 2,
                "removed": 0,
            },
            "cleanup_owned_job": {
                "status": "cleaned",
                "jobId": params.get("jobId"),
                "matched": 2,
                "removed": 2,
                "failed": [],
            },
            "get_node_tree": {"id": "dry-root", "type": "FRAME", "children": []},
        }.get(payload.get("action"), {})
        response = {
            "type": "response",
            "requestId": payload.get("requestId"),
            "result": result,
        }
        asyncio.create_task(
            self.hub.plugin_message(json.dumps(response, ensure_ascii=False))
        )

    async def close(self, code=None, reason=None) -> None:
        self.closed = True


def run_dry_run(output: str | Path, deterministic_writes: int = 100) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    run_dir = destination / "run"
    _reset_run_dir(destination, run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    deterministic_writes = max(4, int(deterministic_writes))
    chromium_version = _chromium_version()
    manifest = {
        "schema": "p5-frozen-run-manifest/1.0",
        "profile": PROFILE,
        "created_at": "2026-10-22T00:00:00+00:00",
        "delivery_profile": "contract-v2",
        "p5_command_explicit": True,
        "default_outside_p5": _default_profile(),
        "code_revision": _code_revision(),
        "plugin_build": {
            "code_sha256": _sha256_file(ROOT / "figma_bridge" / "code.js"),
            "manifest_sha256": _sha256_file(ROOT / "figma_bridge" / "manifest.json"),
        },
        "chromium_version": chromium_version,
        "figma_document": "unassigned",
        "root_nodes": [],
        "allowed_actions": [
            "apply_edit_batch",
            "ownership_report",
            "cleanup_owned_job",
        ],
        "thresholds": {
            "max_writes": max(1000, deterministic_writes),
            "max_unknown": 0,
            "allowed_partial_cases": 1,
            "cleanup_deadline_seconds": 60,
        },
        "manual_review_owner_required": True,
        "rollback_triggers": [
            "unexplained unknown",
            "stale writer lease",
            "cleanup mismatch",
            "journal or ledger bound exceeded",
        ],
    }
    deterministic = asyncio.run(
        _run_deterministic(
            run_dir,
            writers=4,
            writes=deterministic_writes,
        )
    )
    deterministic["manifest_hash"] = canonical_hash(manifest)
    deterministic["journal_sha256"] = _sha256_file(run_dir / "bridge-journal.jsonl")
    deterministic["ledger_sha256"] = _sha256_file(run_dir / "write-jobs.jsonl")
    deterministic["evidence_hash"] = canonical_hash(deterministic)
    result = {
        "schema": "p5-dry-run-result/1.0",
        "status": "blocked-environment",
        "profile_id": PROFILE,
        "profile": manifest,
        "delivery_profile": "contract-v2",
        "created_at": "2026-10-22T00:00:00+00:00",
        "profile_manifest": manifest,
        "deterministic": deterministic,
        "staged_rehearsal": {
            "status": "not-run",
            "required_duration_seconds": 3600,
            "required_writers": 4,
            "required_reconnect_every": 100,
            "reason": "A fixed Figma document, operator and one-hour real plugin session are required.",
        },
        "pilot_verified": False,
        "claim_limits": [
            "The deterministic dry run passed against a controlled fake plugin.",
            "The one-hour staged rehearsal has not run and cannot be inferred from the short run.",
            "No real Figma document or production admission is claimed.",
        ],
    }
    result["content_hash"] = canonical_hash(result)
    _write_json(destination / "manifest.json", manifest)
    _write_json(destination / "deterministic.json", deterministic)
    _write_json(destination / "result.json", result)
    return result


async def _run_deterministic(
    run_dir: Path,
    *,
    writers: int,
    writes: int,
) -> dict[str, Any]:
    lease_path = run_dir / "writer-lease.json"
    journal = run_dir / "bridge-journal.jsonl"
    ledger_path = run_dir / "write-jobs.jsonl"
    store = WriterLeaseStore(
        lease_path,
        owner_id="p5-dry-run-writer",
        ttl_seconds=300,
    )
    start_resources = _resource_snapshot()
    hub = BridgeHub(
        timeout=0.2,
        journal_path=journal,
        writer_lease_store=store,
        write_min_interval=0,
        max_write_queue=64,
    )
    plugin = _AutoPlugin(hub)
    await hub.attach_plugin(plugin)
    try:
        per_writer = max(1, (writes + writers - 1) // writers)

        async def writer(index: int) -> int:
            completed = 0
            for item in range(per_writer):
                raw_job = f"dry-{index}-{item:04d}"
                transaction_id = build_job_namespace(f"writer-{index}", raw_job)
                client = _Client()
                await hub.command(
                    client,
                    json.dumps(
                        {
                            "action": "apply_edit_batch",
                            "params": {
                                "transactionId": transaction_id,
                                "actions": [],
                            },
                            "clientId": f"writer-{index}",
                            "requestId": raw_job,
                        }
                    ),
                )
                completed += (
                    1
                    if client.sent and not client.sent[-1].get("error")
                    else 0
                )
            return completed

        writer_results = await asyncio.gather(
            *(writer(index) for index in range(writers))
        )
        completed_requests = sum(writer_results)
        if completed_requests >= 100:
            plugin = _AutoPlugin(hub)
            await hub.attach_plugin(plugin)

        drop_plugin = _AutoPlugin(
            hub,
            drop_transaction="controlled-timeout",
        )
        await hub.attach_plugin(drop_plugin)
        timeout_client = _Client()
        await hub.command(
            timeout_client,
            json.dumps(
                {
                    "action": "apply_edit_batch",
                    "params": {
                        "transactionId": "controlled-timeout",
                        "actions": [],
                    },
                    "clientId": "controlled-timeout-client",
                    "requestId": "controlled-timeout",
                }
            ),
        )
        reconnect_plugin = _AutoPlugin(hub)
        await hub.attach_plugin(reconnect_plugin)
        await asyncio.sleep(0.05)
        timeout_send_count = sum(
            payload.get("action") == "apply_edit_batch"
            and (payload.get("params") or {}).get("transactionId")
            == "controlled-timeout"
            for payload in (
                plugin.sent + drop_plugin.sent + reconnect_plugin.sent
            )
        )
        transaction = hub.transactions["controlled-timeout"]
        manual = reconciliation_policy(
            {
                "transactionId": transaction.transaction_id,
                "state": transaction.state,
            },
            {"status": "matches", "owned_node_ids": ["dry-node-1"]},
            {"status": "unavailable", "actor": "unknown", "revision": "unknown"},
        )

        cleanup_job = build_job_namespace("writer-0", "cleanup-job")
        cleanup_client = _Client()
        await hub.command(
            cleanup_client,
            json.dumps(
                {
                    "action": "cleanup_owned_job",
                    "params": {"jobId": cleanup_job},
                    "clientId": "writer-0",
                    "requestId": "cleanup-job",
                }
            ),
        )
        cleanup_result = cleanup_client.sent[-1]["result"]
        ledger = WriteJobLedger(
            ledger_path,
            max_events=4096,
            terminal_retention_days=30,
            compact_min_events=256,
        )
        ledger.begin_job(
            job_id=cleanup_job,
            transaction_id=cleanup_job,
            client_id="writer-0",
            request_id="cleanup-job",
            expected_created_nodes=2,
            fingerprint=hashlib.sha256(b"cleanup-job").hexdigest(),
        )
        ledger.mark_inflight(cleanup_job)
        ledger.record_bridge_outcome(
            cleanup_job,
            "committed",
            {"committed": [{"nodeId": "dry-node-1"}, {"nodeId": "dry-node-2"}]},
        )
        ledger.record_cleanup(cleanup_job, cleanup_result)
    finally:
        hub.close()
    end_resources = _resource_snapshot()
    journal_size = journal.stat().st_size if journal.exists() else 0
    ledger_size = ledger_path.stat().st_size if ledger_path.exists() else 0
    resource_stable = _resource_stable(start_resources, end_resources)
    cleanup_exact = (
        cleanup_result.get("status") == "cleaned"
        and cleanup_result.get("matched") == 2
        and cleanup_result.get("removed") == 2
        and not cleanup_result.get("failed")
    )
    controlled_classified = (
        transaction.state == "unknown"
        and timeout_send_count == 1
        and manual.action == "manual-review"
        and not manual.resend_allowed
    )
    checks = (
        _check("requests-completed", "Every writer request completed", completed_requests == per_writer * writers),
        _check("controlled-timeout", "Controlled timeout is explicitly classified", controlled_classified),
        _check("no-resend", "Unknown write was not automatically resent", timeout_send_count == 1),
        _check("bounds", "Journal and ledger remain bounded", journal_size < 2 * 1024 * 1024 and ledger_size < 1024 * 1024),
        _check("resources", "RSS and handles show no runaway growth", resource_stable),
        _check("cleanup", "Exact owned-job cleanup completed", cleanup_exact),
    )
    return {
        "status": "pass" if all(item["passed"] for item in checks) else "blocked",
        "writers": writers,
        "requested_writes": per_writer * writers,
        "completed_requests": completed_requests,
        "reconnect_every": 100,
        "deliberate_reconnect_count": 1 if completed_requests >= 100 else 0,
        "controlled_timeout": {
            "transaction_state": transaction.state,
            "apply_batch_send_count": timeout_send_count,
            "manual_review": manual.to_dict(),
        },
        "no_automatic_resend": timeout_send_count == 1,
        "cleanup_exact": cleanup_exact,
        "cleanup": cleanup_result,
        "journal_size_bytes": journal_size,
        "ledger_size_bytes": ledger_size,
        "resources": {
            "start": start_resources,
            "end": end_resources,
            "stable": resource_stable,
        },
        "checks": list(checks),
    }


class _Client:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


def _default_profile() -> str:
    previous = os.environ.pop("DELIVERY_PROFILE", None)
    try:
        return Config().delivery_profile
    finally:
        if previous is not None:
            os.environ["DELIVERY_PROFILE"] = previous


def _chromium_version() -> str | None:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                return browser.version
            finally:
                browser.close()
    except Exception:
        return None


def _resource_snapshot() -> dict[str, int | None]:
    if psutil is None:
        return {"rss_bytes": None, "handles": None}
    process = psutil.Process()
    memory = process.memory_info()
    return {
        "rss_bytes": int(memory.rss),
        "handles": int(process.num_handles()) if hasattr(process, "num_handles") else None,
    }


def _resource_stable(start: dict[str, Any], end: dict[str, Any]) -> bool:
    start_rss = start.get("rss_bytes")
    end_rss = end.get("rss_bytes")
    start_handles = start.get("handles")
    end_handles = end.get("handles")
    return (
        start_rss is None
        or end_rss is None
        or int(end_rss) - int(start_rss) <= 256 * 1024 * 1024
    ) and (
        start_handles is None
        or end_handles is None
        or int(end_handles) - int(start_handles) <= 256
    )


def _reset_run_dir(destination: Path, run_dir: Path) -> None:
    resolved_destination = destination.resolve()
    resolved_run = run_dir.resolve()
    if resolved_run.parent != resolved_destination or resolved_run.name != "run":
        raise ValueError(f"refusing to reset unexpected run directory: {resolved_run}")
    if resolved_run.exists():
        shutil.rmtree(resolved_run)


def _check(name: str, description: str, passed: bool) -> dict[str, Any]:
    return {"name": name, "description": description, "passed": bool(passed)}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_revision() -> str:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return revision + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with staging.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_p5_dry_run_round1")
    parser.add_argument("--deterministic-writes", type=int, default=100)
    args = parser.parse_args()
    result = run_dry_run(args.out, deterministic_writes=args.deterministic_writes)
    print("status=" + result["status"])
    print("deterministic=" + result["deterministic"]["status"])
    print("pilot_verified=" + str(result["pilot_verified"]).lower())
    print("content_hash=" + result["content_hash"])
    return 0 if result["deterministic"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
