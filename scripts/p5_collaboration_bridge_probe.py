# -*- coding: utf-8 -*-
"""Exercise BridgeHub collaboration, takeover, and recovery contracts."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.bridge_server import BridgeHub  # noqa: E402
from src.app.services.contracts import canonical_hash  # noqa: E402
from src.app.services.job_namespace import build_job_namespace  # noqa: E402
from src.app.services.write_lease import WriterLeaseStore  # noqa: E402


class ProbeClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


class ProbePlugin:
    def __init__(
        self,
        hub: BridgeHub,
        *,
        drop_action: str | None = None,
        latency_seconds: float = 0.01,
    ) -> None:
        self.hub = hub
        self.drop_action = drop_action
        self.latency_seconds = latency_seconds
        self.sent: list[dict[str, Any]] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.closed_code: int | None = None
        self.closed_reason: str | None = None
        self.write_inflight = 0
        self.max_write_inflight = 0

    async def send(self, message: str) -> None:
        payload = json.loads(message)
        self.sent.append(payload)
        action = str(payload.get("action") or "")
        if self.drop_action == action:
            return
        is_write = action in {"apply_batch", "apply_edit_batch"}
        if is_write:
            self.write_inflight += 1
            self.max_write_inflight = max(
                self.max_write_inflight,
                self.write_inflight,
            )
        self.tasks.append(asyncio.create_task(self._respond(payload, is_write)))

    async def _respond(self, payload: dict[str, Any], is_write: bool) -> None:
        try:
            if self.latency_seconds:
                await asyncio.sleep(self.latency_seconds)
            action = payload.get("action")
            params = payload.get("params") or {}
            if action == "ownership_report":
                result = {
                    "status": "reported",
                    "jobId": params.get("jobId"),
                    "matched": 1,
                    "removed": 0,
                    "nodes": [{"nodeId": "probe-owned-node"}],
                }
            elif action == "cleanup_owned_job":
                result = {
                    "status": "cleaned",
                    "jobId": params.get("jobId"),
                    "matched": 1,
                    "removed": 1,
                    "failed": [],
                }
            elif is_write:
                result = {
                    "status": "committed",
                    "committed": [{"nodeId": "probe-owned-node"}],
                    "ownership": {"marked": 1},
                }
            else:
                result = {"id": "probe-readback"}
            await self.hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": payload.get("requestId"),
                        "result": result,
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            if is_write:
                self.write_inflight -= 1

    async def close(self, code=None, reason=None) -> None:
        self.closed_code = code
        self.closed_reason = reason


def _write_command(
    client_id: str,
    request_id: str,
    transaction_id: str,
    text: str,
) -> str:
    return json.dumps(
        {
            "action": "apply_edit_batch",
            "params": {
                "transactionId": transaction_id,
                "actions": [
                    {
                        "action": "set_text",
                        "params": {"nodeId": "1:1", "text": text},
                    }
                ],
            },
            "clientId": client_id,
            "requestId": request_id,
        },
        ensure_ascii=False,
    )


def _owned_batch_command(client_id: str, request_id: str, job_id: str) -> str:
    return json.dumps(
        {
            "action": "apply_batch",
            "params": {
                "transactionId": job_id,
                "actions": [
                    {
                        "action": "create_text",
                        "params": {"parentId": "59:2", "text": "probe"},
                    }
                ],
            },
            "clientId": client_id,
            "requestId": request_id,
        },
        ensure_ascii=False,
    )


async def _run_probe(journal: Path) -> dict[str, Any]:
    lease = WriterLeaseStore(
        journal.with_name("writer-lease.json"),
        owner_id="collaboration-probe-writer",
        ttl_seconds=60,
    )
    hub = BridgeHub(
        timeout=0.15,
        journal_path=journal,
        writer_lease_store=lease,
        write_min_interval=0,
        max_write_queue=8,
    )
    plugin = ProbePlugin(hub)
    await hub.attach_plugin(plugin)
    client_a = ProbeClient()
    client_b = ProbeClient()
    shared_request = "shared-request"
    try:
        await asyncio.gather(
            hub.command(
                client_a,
                _write_command(
                    "client-a",
                    shared_request,
                    build_job_namespace("client-a", "concurrent-a"),
                    "client a",
                ),
            ),
            hub.command(
                client_b,
                _write_command(
                    "client-b",
                    shared_request,
                    build_job_namespace("client-b", "concurrent-b"),
                    "client b",
                ),
            ),
        )
        two_clients_committed = not client_a.sent[-1].get(
            "error"
        ) and not client_b.sent[-1].get("error")
        dispatch_before_retry = sum(
            payload.get("action") == "apply_edit_batch" for payload in plugin.sent
        )
        await hub.command(
            client_a,
            _write_command(
                "client-a",
                shared_request,
                build_job_namespace("client-a", "concurrent-a"),
                "client a",
            ),
        )
        dispatch_after_retry = sum(
            payload.get("action") == "apply_edit_batch" for payload in plugin.sent
        )
        duplicate_single_dispatch = (
            dispatch_before_retry == 2 and dispatch_after_retry == 2
        )

        takeover_plugin = ProbePlugin(
            hub,
            drop_action="apply_batch",
            latency_seconds=0.01,
        )
        await hub.attach_plugin(takeover_plugin)
        takeover_job = build_job_namespace("client-a", "takeover-job")
        unknown_client = ProbeClient()
        unknown_task = asyncio.create_task(
            hub.command(
                unknown_client,
                _owned_batch_command(
                    "client-a",
                    "takeover-request",
                    takeover_job,
                ),
            )
        )
        await asyncio.sleep(0.02)
        replacement = ProbePlugin(hub)
        await hub.attach_plugin(replacement)
        await unknown_task
        await asyncio.sleep(0.02)

        reconnect = ProbePlugin(hub)
        await hub.attach_plugin(reconnect)
        await asyncio.sleep(0.15)
        transaction = hub.transactions[takeover_job]
        unknown_send_count = sum(
            payload.get("action") == "apply_batch"
            and (payload.get("params") or {}).get("transactionId") == takeover_job
            for payload in (takeover_plugin.sent + replacement.sent + reconnect.sent)
        )
        reconciliation_sends_before = len(reconnect.sent)
        resend_client = ProbeClient()
        await hub.command(
            resend_client,
            _owned_batch_command(
                "client-a",
                "takeover-request",
                takeover_job,
            ),
        )
        reconciliation_sends_after = len(reconnect.sent)
        unknown_not_resent = (
            unknown_send_count == 1
            and reconciliation_sends_before == reconciliation_sends_after
        )
        ownership_reconciled = (
            transaction.state == "unknown"
            and isinstance(transaction.ownership_readback, dict)
            and transaction.ownership_readback.get("matched") == 1
            and isinstance(transaction.ownership_reconciliation, dict)
            and transaction.ownership_reconciliation.get("classification")
            == "matches-intended"
        )
        takeover_closed = takeover_plugin.closed_code == 4002 and "newer plugin" in str(
            takeover_plugin.closed_reason or ""
        )
        if plugin.tasks:
            await asyncio.gather(*plugin.tasks)
        if takeover_plugin.tasks:
            await asyncio.gather(*takeover_plugin.tasks)
        if replacement.tasks:
            await asyncio.gather(*replacement.tasks)
        if reconnect.tasks:
            await asyncio.gather(*reconnect.tasks)
        max_inflight = max(
            plugin.max_write_inflight,
            takeover_plugin.max_write_inflight,
            replacement.max_write_inflight,
            reconnect.max_write_inflight,
        )
    finally:
        hub.close()

    restored_lease = WriterLeaseStore(
        journal.with_name("writer-lease.json"),
        owner_id="collaboration-probe-restorer",
        ttl_seconds=60,
    )
    restored = BridgeHub(
        timeout=30,
        journal_path=journal,
        writer_lease_store=restored_lease,
    )
    try:
        restored_transaction = restored.transactions.get(takeover_job)
        journal_preserved = (
            restored_transaction is not None
            and restored_transaction.state == "unknown"
            and restored_transaction.ownership_readback is not None
        )
    finally:
        restored.close()

    return {
        "two_clients_committed": two_clients_committed,
        "duplicate_request_single_dispatch": duplicate_single_dispatch,
        "max_plugin_write_inflight": max_inflight,
        "takeover_closes_old_plugin": takeover_closed,
        "unknown_send_count": unknown_send_count,
        "unknown_not_resent": unknown_not_resent,
        "ownership_readback_reconciled": ownership_reconciled,
        "journal_preserved": journal_preserved,
        "journal_events": len(journal.read_text(encoding="utf-8").splitlines()),
    }


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as raw_dir:
        journal = Path(raw_dir) / "bridge-journal.jsonl"
        observations = asyncio.run(_run_probe(journal))
    checks = [
        {
            "name": "two-clients-committed",
            "description": "Two clients with one shared request id both complete.",
            "passed": observations["two_clients_committed"],
        },
        {
            "name": "serialized-plugin-writes",
            "description": "Plugin write transport never sees concurrent writes.",
            "passed": observations["max_plugin_write_inflight"] <= 1,
        },
        {
            "name": "duplicate-request-single-dispatch",
            "description": "An idempotent retry returns cache without plugin dispatch.",
            "passed": observations["duplicate_request_single_dispatch"],
        },
        {
            "name": "takeover-closes-old-plugin",
            "description": "A newer plugin takes over code 4002.",
            "passed": observations["takeover_closes_old_plugin"],
        },
        {
            "name": "unknown-not-resent",
            "description": "Unknown write readback/resume does not dispatch again.",
            "passed": observations["unknown_not_resent"],
        },
        {
            "name": "ownership-readback-reconciled",
            "description": "Reconnect ownership readback remains explicit and complete.",
            "passed": observations["ownership_readback_reconciled"],
        },
        {
            "name": "journal-preserved",
            "description": "Unknown and ownership readback survive hub recreation.",
            "passed": observations["journal_preserved"],
        },
    ]
    report = {
        "schema_version": "p5-collaboration-bridge-probe/1.0",
        "status": (
            "pass-current-scope"
            if all(item["passed"] for item in checks)
            else "blocked"
        ),
        "scope": "controlled local BridgeHub with deterministic fake plugin",
        "code_revision": _code_revision(),
        "plugin_code_sha256": _sha256(ROOT / "figma_bridge" / "code.js"),
        "plugin_manifest_sha256": _sha256(ROOT / "figma_bridge" / "manifest.json"),
        "source_hashes": {
            "bridge_server": _sha256(ROOT / "src/app/services/bridge_server.py"),
            "write_lease": _sha256(ROOT / "src/app/services/write_lease.py"),
            "write_job_ledger": _sha256(
                ROOT / "src/app/services/rendering/write_job_ledger.py"
            ),
        },
        "observed": observations,
        "checks": checks,
        "boundary": {
            "real_figma": False,
            "transport": "deterministic-fake-plugin",
            "real_collaborators": False,
            "production_bridge_hub": True,
            "writer_lease_enforced": True,
            "journal_persistent": True,
        },
        "non_claims": [
            "real-figma-collaboration",
            "real-collaborator-attribution",
            "production-multi-tenant-isolation",
            "production-admission",
        ],
        "limitations": [
            "The plugin API is simulated by an in-process transport.",
            "No actor or Figma revision is inferred from matching state.",
            "The probe does not mutate or inspect a real Figma document.",
        ],
    }
    report["content_hash"] = canonical_hash(report)
    _write_json(destination / "result.json", report)
    return report


def _code_revision() -> str:
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    staging.write_text(payload, encoding="utf-8")
    os.replace(staging, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    result = run_probe(args.out)
    print("status=" + result["status"])
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] == "pass-current-scope" else 1


if __name__ == "__main__":
    raise SystemExit(main())
