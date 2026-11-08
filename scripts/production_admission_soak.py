# -*- coding: utf-8 -*-
"""Controlled production-admission soak; never represents real Figma."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import psutil
except ImportError:  # pragma: no cover - optional local dependency
    psutil = None

from src.app.services.bridge_server import BridgeHub  # noqa: E402
from src.app.services.contracts import canonical_hash  # noqa: E402
from src.app.services.job_namespace import build_job_namespace  # noqa: E402
from src.app.services.rendering.write_job_ledger import (  # noqa: E402
    WriteJobLedger,
    plan_resume,
)
from src.app.services.structure.backends.grounding_reliability import (  # noqa: E402
    GroundingReliability,
)
from src.app.services.write_lease import WriterLeaseStore  # noqa: E402


REQUIRED_DURATION_SECONDS = 3600.0
REQUIRED_CHECKPOINTS = (300.0, 900.0, 1800.0)


def _reconnect_interval(duration_seconds: float) -> float:
    if duration_seconds <= 5.0:
        return max(0.05, duration_seconds / 3.0)
    return min(300.0, max(60.0, duration_seconds / 12.0))


def _lease_ttl_seconds(duration_seconds: float) -> float:
    if duration_seconds <= 60.0:
        return 300.0
    return duration_seconds + 300.0


class _Client:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


class _FaultState:
    def __init__(self, fault_every: int) -> None:
        self.fault_every = max(0, int(fault_every))
        self.dispatch_count = 0
        self.rate_limits = 0
        self.server_errors = 0


class _SoakPlugin:
    def __init__(
        self,
        hub: BridgeHub,
        state: _FaultState,
        *,
        drop_apply_batch: bool = False,
        latency_seconds: float = 0.002,
    ) -> None:
        self.hub = hub
        self.state = state
        self.drop_apply_batch = drop_apply_batch
        self.latency_seconds = latency_seconds
        self.sent: list[dict[str, Any]] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.closed = False
        self.max_write_inflight = 0
        self._write_inflight = 0

    async def send(self, message: str) -> None:
        payload = json.loads(message)
        self.sent.append(payload)
        action = str(payload.get("action") or "")
        if self.drop_apply_batch and action == "apply_batch":
            return
        if action in {"apply_batch", "apply_edit_batch"}:
            self._write_inflight += 1
            self.max_write_inflight = max(
                self.max_write_inflight,
                self._write_inflight,
            )
        self.tasks.append(asyncio.create_task(self._respond(payload)))

    async def _respond(self, payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "")
        params = payload.get("params") or {}
        is_write = action in {"apply_batch", "apply_edit_batch"}
        try:
            if self.latency_seconds:
                await asyncio.sleep(self.latency_seconds)
            if is_write:
                self.state.dispatch_count += 1
                if (
                    self.state.fault_every > 0
                    and self.state.dispatch_count % self.state.fault_every == 0
                ):
                    if self.state.dispatch_count % (self.state.fault_every * 2) == 0:
                        self.state.rate_limits += 1
                        await self._send_error(
                            payload,
                            "PLUGIN_RATE_LIMITED",
                            "PLUGIN 429 rate limited",
                            retry_after_ms=5,
                        )
                    else:
                        self.state.server_errors += 1
                        await self._send_error(
                            payload,
                            "PLUGIN_SERVER_ERROR",
                            "PLUGIN 503 service unavailable",
                        )
                    return
            if action == "ownership_report":
                result = {
                    "status": "reported",
                    "jobId": params.get("jobId"),
                    "matched": 1,
                    "removed": 0,
                }
            elif action == "get_node_tree":
                result = {
                    "id": "soak-node",
                    "type": "FRAME",
                    "children": [],
                }
            else:
                result = {
                    "status": "committed",
                    "committed": [{"nodeId": "soak-node"}],
                    "ownership": {"marked": 1},
                }
            await self.hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": payload.get("requestId"),
                        "result": result,
                    }
                )
            )
        finally:
            if is_write:
                self._write_inflight -= 1

    async def _send_error(
        self,
        payload: dict[str, Any],
        code: str,
        message: str,
        *,
        retry_after_ms: int | None = None,
    ) -> None:
        response: dict[str, Any] = {
            "type": "response",
            "requestId": payload.get("requestId"),
            "error": message,
            "code": code,
            "outcome": "not-applied",
        }
        if retry_after_ms is not None:
            response["retryAfterMs"] = retry_after_ms
        await self.hub.plugin_message(json.dumps(response))

    async def close(self, code=None, reason=None) -> None:
        self.closed = True

    async def drain(self) -> None:
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * ratio) - 1)
    return round(ordered[index], 3)


def build_soak_report(
    *,
    duration_seconds: float,
    checkpoints: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    latency = [float(item) for item in summary.get("latency_ms") or []]
    latency_p50 = _percentile(latency, 0.50)
    latency_p95 = _percentile(latency, 0.95)
    latency_p99 = _percentile(latency, 0.99)
    resources = summary.get("resources") or {}
    start = resources.get("start") or {}
    end = resources.get("end") or {}
    rss_growth = _delta(start.get("rss_bytes"), end.get("rss_bytes"))
    handle_growth = _delta(start.get("handles"), end.get("handles"))
    requests = int(summary.get("requests") or 0)
    committed = int(summary.get("committed") or 0)
    safe_rejections = int(summary.get("safe_rejections") or 0)
    failed = int(summary.get("failed") or 0)
    required_times = (*REQUIRED_CHECKPOINTS, REQUIRED_DURATION_SECONDS)
    available_times = [float(item.get("at_seconds") or 0.0) for item in checkpoints]
    core_checks = {
        "requests-positive": requests > 0,
        "all-requests-classified": requests == committed + safe_rejections + failed,
        "zero-unexplained-failures": failed == 0,
        "service-faults-covered": (
            int(summary.get("server_errors") or 0) > 0
            and int(summary.get("rate_limits") or 0) > 0
        ),
        "reconnect-covered": int(summary.get("reconnects") or 0) > 0,
        "controlled-unknown-reconciled": (
            int(summary.get("controlled_unknowns") or 0) == 1
            and int(summary.get("unreconciled_unknowns") or 0) == 0
        ),
        "queues-drained": (
            int(summary.get("pending") or 0) == 0
            and int(summary.get("scope_pending") or 0) == 0
        ),
        "latency-slo": latency_p99 <= 5000.0,
        "resource-bound": (
            (rss_growth is None or rss_growth <= 256 * 1024 * 1024)
            and (handle_growth is None or handle_growth <= 256)
        ),
        "journal-bounded": int(summary.get("journal_events") or 0) <= 4096,
        "ledger-bounded": int(summary.get("ledger_events") or 0) <= 4096,
    }
    long_checks = {
        "duration-at-least-3600": duration_seconds >= REQUIRED_DURATION_SECONDS,
        "required-checkpoints": all(
            any(abs(value - required) <= 5.0 for value in available_times)
            for required in required_times
        ),
    }
    all_checks = {**core_checks, **long_checks}
    failed_core = [name for name, passed in core_checks.items() if not passed]
    failed_long = [name for name, passed in long_checks.items() if not passed]
    one_hour = duration_seconds >= REQUIRED_DURATION_SECONDS
    if failed_core:
        status = "blocked"
    elif not one_hour:
        status = "rehearsal-pass"
    elif failed_long:
        status = "blocked"
    else:
        status = "pass-current-scope"
    report = {
        "schema_version": "production-admission-soak/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code_revision": _code_revision(),
        "plugin_code_sha256": _sha256(ROOT / "figma_bridge" / "code.js"),
        "status": status,
        "one_hour_soak": one_hour,
        "required_duration_seconds": REQUIRED_DURATION_SECONDS,
        "duration_seconds": round(duration_seconds, 3),
        "checkpoints": checkpoints,
        "summary": {
            **summary,
            "latency": {
                "count": len(latency),
                "p50_ms": latency_p50,
                "p95_ms": latency_p95,
                "p99_ms": latency_p99,
                "max_ms": round(max(latency), 3) if latency else 0.0,
            },
            "resource_growth": {
                "rss_bytes": rss_growth,
                "handles": handle_growth,
            },
        },
        "checks": [
            {"name": name, "passed": passed} for name, passed in all_checks.items()
        ],
        "failed_checks": failed_core + failed_long,
        "slo": {
            "write_p99_ms_max": 5000,
            "rss_growth_bytes_max": 256 * 1024 * 1024,
            "handle_growth_max": 256,
            "unreconciled_unknown_max": 0,
        },
        "boundary": {
            "real_figma": False,
            "production_bridge_hub": True,
            "transport": "in-process-fault-injecting-plugin",
            "real_collaborators": False,
            "production_secret_manager": False,
            "local_24h_or_7d_started": False,
        },
        "non_claims": [
            "real-figma-soak",
            "production-long-soak",
            "real-network-outage",
            "real-figma-429-or-5xx",
            "production-admission",
        ],
        "limitations": [
            "The plugin transport is in-process and deterministic.",
            "A short run is a rehearsal and never a one-hour soak pass.",
            "24-hour and seven-day stages were not started.",
            "Grounding endpoint faults are controlled callback failures.",
        ],
    }
    report["content_hash"] = canonical_hash(report)
    return report


async def _run_soak_async(
    *,
    duration_seconds: float,
    checkpoint_every_seconds: float,
    workers: int,
    target_rps: float,
    fault_every: int,
    journal_max_events: int,
    checkpoint_path: Path,
    reconnect_interval_seconds: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if duration_seconds <= 0:
        raise ValueError("duration must be positive")
    if checkpoint_every_seconds <= 0:
        raise ValueError("checkpoint interval must be positive")
    if workers <= 0 or target_rps <= 0:
        raise ValueError("workers and target_rps must be positive")
    run_root = checkpoint_path.parent
    journal_path = run_root / "bridge-journal.jsonl"
    ledger_path = run_root / "write-jobs.jsonl"
    lease_store = WriterLeaseStore(
        run_root / "writer-lease.json",
        owner_id="production-admission-soak-writer",
        ttl_seconds=_lease_ttl_seconds(duration_seconds),
    )
    hub = BridgeHub(
        timeout=0.15,
        journal_path=journal_path,
        max_journal_events=journal_max_events,
        writer_lease_store=lease_store,
        write_min_interval=0,
        max_write_queue=max(8, workers * 4),
    )
    ledger = WriteJobLedger(
        ledger_path,
        max_events=4096,
        terminal_retention_days=30,
        compact_min_events=256,
    )
    state = _FaultState(fault_every)
    checkpoints: list[dict[str, Any]] = []
    latencies: list[float] = []
    summary = {
        "requests": 0,
        "committed": 0,
        "safe_rejections": 0,
        "failed": 0,
        "server_errors": 0,
        "rate_limits": 0,
        "reconnects": 0,
        "controlled_unknowns": 0,
        "unreconciled_unknowns": 0,
        "error_codes": {},
    }
    start_resources = _resource_snapshot()
    started = time.perf_counter()
    active_plugin: _SoakPlugin | None = None

    async def attach(
        *,
        drop_apply_batch: bool = False,
        wait_for_write_turn: bool = False,
    ) -> _SoakPlugin:
        nonlocal active_plugin

        async def replace() -> _SoakPlugin:
            plugin = _SoakPlugin(
                hub,
                state,
                drop_apply_batch=drop_apply_batch,
            )
            await hub.attach_plugin(plugin)
            return plugin

        if wait_for_write_turn:
            async with hub._write_turn_lock:
                plugin = await replace()
        else:
            plugin = await replace()
        active_plugin = plugin
        return plugin

    try:
        controlled = await _controlled_unknown(
            hub,
            ledger,
            state,
            attach,
        )
        summary.update(
            {
                "controlled_unknowns": 1 if controlled["state"] == "unknown" else 0,
                "unreconciled_unknowns": controlled["unreconciled_unknowns"],
            }
        )
        await attach()
        reconnect_interval = (
            float(reconnect_interval_seconds)
            if reconnect_interval_seconds is not None
            else _reconnect_interval(duration_seconds)
        )
        if reconnect_interval <= 0:
            raise ValueError("reconnect interval must be positive")
        reconnect_stop = asyncio.Event()

        async def reconnect_loop() -> None:
            while not reconnect_stop.is_set():
                try:
                    await asyncio.wait_for(
                        reconnect_stop.wait(),
                        timeout=reconnect_interval,
                    )
                except asyncio.TimeoutError:
                    await attach(wait_for_write_turn=True)
                    summary["reconnects"] += 1

        reconnect_task = asyncio.create_task(reconnect_loop())

        async def checkpoint_loop() -> None:
            while True:
                await asyncio.sleep(checkpoint_every_seconds)
                checkpoint = _checkpoint(
                    hub,
                    ledger_path,
                    started,
                    latencies,
                )
                checkpoints.append(checkpoint)
                _write_json(
                    checkpoint_path,
                    {
                        "schema_version": "production-admission-soak-partial/1.0",
                        "status": "in-progress",
                        "checkpoints": checkpoints,
                    },
                )

        checkpoint_task = asyncio.create_task(checkpoint_loop())
        deadline = time.perf_counter() + duration_seconds
        worker_period = workers / target_rps

        async def worker(index: int) -> None:
            sequence = 0
            client = _Client()
            while time.perf_counter() < deadline:
                sequence += 1
                transaction_id = build_job_namespace(
                    f"soak-client-{index}",
                    f"soak-{index}-{sequence}",
                )
                request_id = f"soak-request-{index}-{sequence}"
                command = json.dumps(
                    {
                        "action": "apply_edit_batch",
                        "params": {
                            "transactionId": transaction_id,
                            "actions": [],
                        },
                        "clientId": f"soak-client-{index}",
                        "requestId": request_id,
                    }
                )
                attempt_started = time.perf_counter()
                await hub.command(client, command)
                latency_ms = (time.perf_counter() - attempt_started) * 1000
                latencies.append(latency_ms)
                summary["requests"] += 1
                response = client.sent[-1]
                code = str(response.get("code") or "")
                error_code = code or str(response.get("error") or "")
                if error_code:
                    summary["error_codes"][error_code] = (
                        int(summary["error_codes"].get(error_code) or 0) + 1
                    )
                if not response.get("error"):
                    summary["committed"] += 1
                elif (
                    code
                    in {
                        "PLUGIN_RATE_LIMITED",
                        "PLUGIN_SERVER_ERROR",
                        "BRIDGE_WRITE_BACKPRESSURE",
                        "BRIDGE_CLIENT_RATE_LIMITED",
                    }
                    and response.get("outcome") == "not-applied"
                ):
                    summary["safe_rejections"] += 1
                else:
                    summary["failed"] += 1
                remaining = worker_period - (time.perf_counter() - attempt_started)
                if remaining > 0:
                    await asyncio.sleep(remaining)

        await asyncio.gather(*(worker(index) for index in range(workers)))
        reconnect_stop.set()
        await reconnect_task
        checkpoint_task.cancel()
        try:
            await checkpoint_task
        except asyncio.CancelledError:
            pass
        if active_plugin is not None:
            await active_plugin.drain()
    finally:
        hub.close()

    elapsed = time.perf_counter() - started
    end_resources = _resource_snapshot()
    final_checkpoint = _checkpoint(
        hub,
        ledger_path,
        started,
        latencies,
        elapsed_override=elapsed,
    )
    checkpoints.append(final_checkpoint)
    summary.update(
        {
            "elapsed_seconds": elapsed,
            "server_errors": state.server_errors,
            "rate_limits": state.rate_limits,
            "pending": len(hub.pending),
            "scope_pending": len(hub.scope_pending),
            "journal_events": hub._journal_event_count,
            "ledger_events": _line_count(ledger_path),
            "latency_ms": latencies,
            "resources": {
                "start": start_resources,
                "end": end_resources,
            },
            "grounding": _controlled_grounding_failover(),
        }
    )
    _write_json(
        checkpoint_path,
        {
            "schema_version": "production-admission-soak-checkpoints/1.0",
            "checkpoints": checkpoints,
        },
    )
    return checkpoints, summary


async def _controlled_unknown(
    hub: BridgeHub,
    ledger: WriteJobLedger,
    state: _FaultState,
    attach,
) -> dict[str, Any]:
    client_id = "soak-control-client"
    job_id = build_job_namespace(client_id, "controlled-unknown")
    fingerprint = hashlib.sha256(job_id.encode("utf-8")).hexdigest()
    ledger.begin_job(
        job_id=job_id,
        transaction_id=job_id,
        client_id=client_id,
        request_id="controlled-unknown",
        expected_created_nodes=1,
        fingerprint=fingerprint,
    )
    ledger.mark_inflight(job_id)
    dropping = await attach(drop_apply_batch=True)
    client = _Client()
    task = asyncio.create_task(
        hub.command(
            client,
            json.dumps(
                {
                    "action": "apply_batch",
                    "params": {
                        "transactionId": job_id,
                        "actions": [
                            {
                                "action": "create_text",
                                "params": {"text": "controlled unknown"},
                            }
                        ],
                    },
                    "clientId": client_id,
                    "requestId": "controlled-unknown",
                }
            ),
        )
    )
    await asyncio.sleep(0.01)
    await attach()
    await task
    transaction = hub.transactions[job_id]
    ledger.record_bridge_outcome(
        job_id,
        "unknown",
        {"status": "unknown"},
    )
    await asyncio.sleep(0.02)
    await attach()
    await asyncio.sleep(0.1)
    transaction = hub.transactions[job_id]
    readback = transaction.ownership_readback
    classification = (transaction.ownership_reconciliation or {}).get(
        "classification", "indeterminate"
    )
    if isinstance(readback, dict):
        ledger.record_ownership(job_id, readback, classification)
        record = ledger.load(job_id)
        if record is not None:
            ledger.record_resume_decision(job_id, plan_resume(record, readback))
    await dropping.drain()
    return {
        "state": transaction.state,
        "unreconciled_unknowns": (
            0
            if isinstance(readback, dict) and classification == "matches-intended"
            else 1
        ),
    }


def _controlled_grounding_failover() -> dict[str, Any]:
    runtime = GroundingReliability(
        endpoints=("https://primary.test/v1", "https://backup.test/v1"),
        model="vision-soak",
        max_attempts=3,
        retry_base_ms=1,
        max_backoff_ms=2,
        breaker_failure_threshold=3,
        breaker_cooldown_seconds=1,
        sleeper=lambda _seconds: None,
        random_value=lambda: 0.5,
    )
    rows: list[dict[str, Any]] = []

    class _Unavailable503(RuntimeError):
        status_code = 503

    class _Unavailable429(RuntimeError):
        status_code = 429

    for index, error_type in enumerate(
        (_Unavailable503, _Unavailable429, TimeoutError),
        start=1,
    ):

        def invoke(endpoint: str) -> dict[str, Any]:
            if endpoint.startswith("https://primary"):
                raise error_type("controlled Grounding outage")
            return {"containers": [], "elements": [], "index": index}

        result = runtime.run(
            image_bytes=f"grounding-{index}".encode("utf-8"),
            prompt="controlled prompt",
            invoke=invoke,
        )
        rows.append(result.report.to_dict())
    return {
        "requests": len(rows),
        "failovers": sum(report["final_endpoint_index"] == 1 for report in rows),
        "retries": sum(report["retry_count"] for report in rows),
        "max_attempts_observed": max(report["attempt_count"] for report in rows),
        "reports": rows,
    }


def _checkpoint(
    hub: BridgeHub,
    ledger_path: Path,
    started: float,
    latencies: list[float],
    *,
    elapsed_override: float | None = None,
) -> dict[str, Any]:
    resources = _resource_snapshot()
    elapsed = (
        elapsed_override
        if elapsed_override is not None
        else time.perf_counter() - started
    )
    recent = latencies[-1000:]
    return {
        "at_seconds": round(elapsed, 3),
        "rss_bytes": resources.get("rss_bytes"),
        "handles": resources.get("handles"),
        "pending": len(hub.pending),
        "scope_pending": len(hub.scope_pending),
        "journal_events": hub._journal_event_count,
        "ledger_events": _line_count(ledger_path),
        "latency_p50_ms": _percentile(recent, 0.50),
        "latency_p95_ms": _percentile(recent, 0.95),
        "latency_p99_ms": _percentile(recent, 0.99),
    }


def run_soak(
    output: str | Path,
    *,
    duration_seconds: float,
    checkpoint_every_seconds: float,
    workers: int,
    target_rps: float,
    fault_every: int,
    journal_max_events: int = 4096,
    reconnect_interval_seconds: float | None = None,
) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    checkpoint_path = destination / "checkpoints.json"
    try:
        checkpoints, summary = asyncio.run(
            _run_soak_async(
                duration_seconds=duration_seconds,
                checkpoint_every_seconds=checkpoint_every_seconds,
                workers=workers,
                target_rps=target_rps,
                fault_every=fault_every,
                journal_max_events=journal_max_events,
                checkpoint_path=checkpoint_path,
                reconnect_interval_seconds=reconnect_interval_seconds,
            )
        )
    except KeyboardInterrupt:
        partial = {
            "schema_version": "production-admission-soak/1.0",
            "status": "blocked",
            "one_hour_soak": duration_seconds >= REQUIRED_DURATION_SECONDS,
            "reason": "interrupted",
            "checkpoints": _read_json(checkpoint_path).get("checkpoints", []),
            "non_claims": ["production-admission", "soak-pass"],
        }
        partial["content_hash"] = canonical_hash(partial)
        _write_json(destination / "result.json", partial)
        return partial
    report = build_soak_report(
        duration_seconds=summary.get("elapsed_seconds", duration_seconds),
        checkpoints=checkpoints,
        summary=summary,
    )
    report["environment"] = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
    }
    report["source_hashes"] = {
        "soak_script": _sha256(Path(__file__).resolve()),
        "bridge_server": _sha256(ROOT / "src/app/services/bridge_server.py"),
        "write_lease": _sha256(ROOT / "src/app/services/write_lease.py"),
        "write_job_ledger": _sha256(
            ROOT / "src/app/services/rendering/write_job_ledger.py"
        ),
        "grounding_reliability": _sha256(
            ROOT / "src/app/services/structure/backends/grounding_reliability.py"
        ),
    }
    report["content_hash"] = canonical_hash(
        {key: value for key, value in report.items() if key != "content_hash"}
    )
    _write_json(destination / "result.json", report)
    return report


def _resource_snapshot() -> dict[str, int | None]:
    if psutil is None:
        return {"rss_bytes": None, "handles": None}
    process = psutil.Process()
    memory = process.memory_info()
    return {
        "rss_bytes": int(memory.rss),
        "handles": (
            int(process.num_handles()) if hasattr(process, "num_handles") else None
        ),
    }


def _delta(start: Any, end: Any) -> int | None:
    if start is None or end is None:
        return None
    return int(end) - int(start)


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    staging.write_text(payload, encoding="utf-8")
    os.replace(staging, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=float, default=REQUIRED_DURATION_SECONDS)
    parser.add_argument("--checkpoint-every", type=float, default=300.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--target-rps", type=float, default=10.0)
    parser.add_argument("--fault-every", type=int, default=25)
    parser.add_argument("--journal-max-events", type=int, default=4096)
    parser.add_argument("--reconnect-interval", type=float, default=None)
    args = parser.parse_args(argv)
    result = run_soak(
        args.out,
        duration_seconds=args.duration,
        checkpoint_every_seconds=args.checkpoint_every,
        workers=args.workers,
        target_rps=args.target_rps,
        fault_every=args.fault_every,
        journal_max_events=args.journal_max_events,
        reconnect_interval_seconds=args.reconnect_interval,
    )
    print("status=" + result["status"])
    print("one_hour_soak=" + str(result["one_hour_soak"]).lower())
    print("content_hash=" + result.get("content_hash", "unavailable"))
    return 0 if result["status"] in {"pass-current-scope", "rehearsal-pass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
