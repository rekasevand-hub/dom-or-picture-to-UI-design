"""Exercise BridgeHub write pacing with an auto-responding fake plugin."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.bridge_server import BridgeHub  # noqa: E402


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * ratio) - 1)
    return round(ordered[index], 3)


def build_write_pacing_report(
    *,
    requested: int,
    completed: int,
    safe_rejections: int,
    retries: int,
    failed: int,
    unknown: int,
    duration_seconds: float,
    latencies_ms: list[float],
    max_plugin_write_inflight: int,
    min_dispatch_gap_ms: float | None,
    max_write_queue: int,
    min_write_interval_ms: float,
    write_queue_timeout_seconds: float,
    errors: list[str] | None = None,
    pending: int = 0,
    scope_pending: int = 0,
    journal_events: int = 0,
    unique_request_ids: int | None = None,
) -> dict[str, Any]:
    checks = {
        "all_requests_completed": (
            requested > 0 and completed == requested and failed == 0
        ),
        "no_unknown_outcomes": unknown == 0,
        "single_plugin_write_inflight": max_plugin_write_inflight <= 1,
        "safe_rejections_were_retried": safe_rejections == retries,
        "pending_maps_drained": pending == 0 and scope_pending == 0,
        "throughput_positive": (
            duration_seconds > 0 and completed / duration_seconds > 0
        ),
    }
    if unique_request_ids is not None:
        checks["unique_request_ids"] = unique_request_ids == requested
    if min_write_interval_ms > 0:
        checks["minimum_dispatch_gap_observed"] = (
            min_dispatch_gap_ms is not None
            and min_dispatch_gap_ms >= min_write_interval_ms * 0.9
        )
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "p4-write-backpressure-soak/1.0",
        "experiment": "P4-BRIDGE-WRITE-BACKPRESSURE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested": requested,
        "completed": completed,
        "safe_rejections": safe_rejections,
        "retries": retries,
        "failed": failed,
        "unknown": unknown,
        "pending": pending,
        "scope_pending": scope_pending,
        "journal_events": journal_events,
        "unique_request_ids": unique_request_ids,
        "duration_seconds": round(duration_seconds, 3),
        "requests_per_second": round(
            completed / duration_seconds if duration_seconds > 0 else 0.0,
            3,
        ),
        "latency": {
            "count": len(latencies_ms),
            "min_ms": round(min(latencies_ms), 3) if latencies_ms else None,
            "p50_ms": _percentile(latencies_ms, 0.50),
            "p95_ms": _percentile(latencies_ms, 0.95),
            "p99_ms": _percentile(latencies_ms, 0.99),
            "max_ms": round(max(latencies_ms), 3) if latencies_ms else None,
        },
        "policy": {
            "max_write_queue": max_write_queue,
            "min_write_interval_ms": round(min_write_interval_ms, 3),
            "write_queue_timeout_seconds": write_queue_timeout_seconds,
        },
        "observed": {
            "max_plugin_write_inflight": max_plugin_write_inflight,
            "min_dispatch_gap_ms": (
                round(min_dispatch_gap_ms, 3)
                if min_dispatch_gap_ms is not None
                else None
            ),
        },
        "errors": (errors or [])[:20],
        **checks,
        "failed_checks": failed_checks,
        "status": "pass" if not failed_checks else "fail",
    }


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


class TracingBridgeHub(BridgeHub):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.write_gate_events: list[dict[str, float]] = []

    async def _wait_for_write_dispatch(self) -> None:
        entered = time.monotonic()
        not_before = self._write_not_before
        await super()._wait_for_write_dispatch()
        self.write_gate_events.append(
            {
                "entered": entered,
                "not_before": not_before,
                "returned": time.monotonic(),
            }
        )


class AutoRespondingPlugin:
    def __init__(
        self,
        hub: BridgeHub,
        *,
        latency_seconds: float,
    ) -> None:
        self.hub = hub
        self.latency_seconds = latency_seconds
        self.sent: list[dict[str, Any]] = []
        self.sent_at: list[float] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.write_inflight = 0
        self.max_write_inflight = 0

    async def send(self, message: str) -> None:
        payload = json.loads(message)
        self.sent.append(payload)
        self.sent_at.append(time.monotonic())
        if payload.get("action") != "get_node_tree":
            self.write_inflight += 1
            self.max_write_inflight = max(
                self.max_write_inflight,
                self.write_inflight,
            )
        self.tasks.append(asyncio.create_task(self._respond(payload)))

    async def _respond(self, payload: dict[str, Any]) -> None:
        is_write = payload.get("action") != "get_node_tree"
        try:
            await asyncio.sleep(self.latency_seconds)
            response = {
                "type": "response",
                "requestId": payload["requestId"],
                "result": (
                    {
                        "status": "committed",
                        "committed": [{"index": 0}],
                    }
                    if is_write
                    else {"id": payload["params"]["nodeId"]}
                ),
            }
            await self.hub.plugin_message(json.dumps(response))
        finally:
            if is_write:
                self.write_inflight -= 1


async def run_write_pacing_soak(
    *,
    requests: int,
    workers: int,
    max_write_queue: int,
    min_write_interval_ms: float,
    write_queue_timeout: float,
    plugin_latency_ms: float,
    journal_path: Path,
) -> dict[str, Any]:
    if requests <= 0:
        raise ValueError("requests must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")
    hub = TracingBridgeHub(
        timeout=10,
        journal_path=journal_path,
        write_min_interval=min_write_interval_ms / 1000,
        write_queue_timeout=write_queue_timeout,
        max_write_queue=max_write_queue,
    )
    plugin = AutoRespondingPlugin(
        hub,
        latency_seconds=max(0.0, plugin_latency_ms / 1000),
    )
    await hub.attach_plugin(plugin)
    sequence_queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(requests):
        sequence_queue.put_nowait(index)

    started = time.perf_counter()
    worker_results = await asyncio.gather(
        *(
            _run_worker(
                hub,
                sequence_queue,
                worker_index,
            )
            for worker_index in range(workers)
        )
    )
    if plugin.tasks:
        await asyncio.gather(*plugin.tasks)
    duration = time.perf_counter() - started

    latencies = [
        value
        for result in worker_results
        for value in result["latencies_ms"]
    ]
    errors = [
        value
        for result in worker_results
        for value in result["errors"]
    ]
    gaps = [
        plugin.sent_at[index] - plugin.sent_at[index - 1]
        for index in range(1, len(plugin.sent_at))
    ]
    journal_events = (
        len(
            [
                line
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        )
        if journal_path.exists()
        else 0
    )
    report = build_write_pacing_report(
        requested=requests,
        completed=sum(item["completed"] for item in worker_results),
        safe_rejections=sum(
            item["safe_rejections"] for item in worker_results
        ),
        retries=sum(item["retries"] for item in worker_results),
        failed=sum(item["failed"] for item in worker_results),
        unknown=sum(item["unknown"] for item in worker_results),
        duration_seconds=duration,
        latencies_ms=latencies,
        max_plugin_write_inflight=plugin.max_write_inflight,
        min_dispatch_gap_ms=min(gaps) * 1000 if gaps else None,
        max_write_queue=max_write_queue,
        min_write_interval_ms=min_write_interval_ms,
        write_queue_timeout_seconds=write_queue_timeout,
        errors=errors,
        pending=len(hub.pending),
        scope_pending=len(hub.scope_pending),
        journal_events=journal_events,
        unique_request_ids=len({item["requestId"] for item in plugin.sent}),
    )
    report["observed"]["dispatch_count"] = len(plugin.sent_at)
    report["observed"]["dispatch_gap_samples_ms"] = [
        round(gap * 1000, 3) for gap in gaps[:20]
    ]
    gate_gaps = [
        hub.write_gate_events[index]["returned"]
        - hub.write_gate_events[index - 1]["returned"]
        for index in range(1, len(hub.write_gate_events))
    ]
    report["observed"]["gate_return_gap_samples_ms"] = [
        round(gap * 1000, 3) for gap in gate_gaps[:20]
    ]
    report["observed"]["gate_wait_samples_ms"] = [
        round(
            (event["returned"] - event["entered"]) * 1000,
            3,
        )
        for event in hub.write_gate_events[:20]
    ]
    report["observed"]["gate_lateness_samples_ms"] = [
        round(
            (event["returned"] - event["not_before"]) * 1000,
            3,
        )
        for event in hub.write_gate_events
        if event["not_before"] > 0
    ][:20]
    report["boundary"] = {
        "real_figma": False,
        "production_bridge_hub": True,
        "deterministic_fake_plugin": True,
        "same_request_id_safe_retry": True,
        "long_duration_claim": False,
    }
    return report


async def _run_worker(
    hub: BridgeHub,
    sequence_queue: asyncio.Queue[int],
    worker_index: int,
) -> dict[str, Any]:
    client = FakeClient()
    latencies: list[float] = []
    errors: list[str] = []
    completed = 0
    failed = 0
    unknown = 0
    retries = 0
    safe_rejections = 0
    while not sequence_queue.empty():
        try:
            sequence = sequence_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        request_id = f"write-pacing-{worker_index}-{sequence}"
        started = time.perf_counter()
        attempts = 0
        while True:
            attempts += 1
            await hub.command(
                client,
                json.dumps(
                    {
                        "action": "apply_edit_batch",
                        "params": {
                            "transactionId": request_id,
                            "actions": [
                                {
                                    "action": "set_text",
                                    "params": {
                                        "nodeId": "1:1",
                                        "text": f"write {sequence}",
                                    },
                                }
                            ],
                        },
                        "clientId": f"write-pacing-worker-{worker_index}",
                        "requestId": request_id,
                    }
                ),
            )
            response = client.sent[-1]
            if response.get("code") == "BRIDGE_WRITE_BACKPRESSURE":
                if response.get("outcome") != "not-applied":
                    failed += 1
                    unknown += 1
                    errors.append(
                        f"{request_id}: unsafe backpressure outcome "
                        f"{response.get('outcome')}"
                    )
                    break
                safe_rejections += 1
                retries += 1
                retry_after_ms = response.get("retryAfterMs", 2)
                await asyncio.sleep(max(0.001, float(retry_after_ms) / 1000))
                continue
            if response.get("error"):
                failed += 1
                if response.get("outcome") == "unknown":
                    unknown += 1
                errors.append(
                    f"{request_id}: {response.get('code')} "
                    f"{response.get('outcome')}"
                )
                break
            latencies.append((time.perf_counter() - started) * 1000)
            completed += 1
            break
    return {
        "completed": completed,
        "failed": failed,
        "unknown": unknown,
        "retries": retries,
        "safe_rejections": safe_rejections,
        "latencies_ms": latencies,
        "errors": errors,
    }


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
    parser.add_argument("--requests", type=int, default=240)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--max-write-queue", type=int, default=4)
    parser.add_argument("--min-write-interval-ms", type=float, default=5)
    parser.add_argument("--write-queue-timeout", type=float, default=0.5)
    parser.add_argument("--plugin-latency-ms", type=float, default=2)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        journal_path = Path(temp_dir) / "bridge-journal.jsonl"
        report = asyncio.run(
            run_write_pacing_soak(
                requests=args.requests,
                workers=args.workers,
                max_write_queue=args.max_write_queue,
                min_write_interval_ms=args.min_write_interval_ms,
                write_queue_timeout=args.write_queue_timeout,
                plugin_latency_ms=args.plugin_latency_ms,
                journal_path=journal_path,
            )
        )
    _write_report(out / "write_backpressure_soak.json", report)
    print(
        f"[write-pacing] {report['status']} "
        f"completed={report['completed']}/{report['requested']} "
        f"safe_rejections={report['safe_rejections']} "
        f"unknown={report['unknown']}"
    )
    print(f"[out ] {out / 'write_backpressure_soak.json'}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
