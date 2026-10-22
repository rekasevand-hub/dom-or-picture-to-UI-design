"""Run sustained read-only commands against the real Figma bridge."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.config.settings import load_config  # noqa: E402


ROOT_NAME = "P4 Real Bridge Soak"


def summarize_latencies(latencies_ms: list[float]) -> dict[str, Any]:
    if not latencies_ms:
        return {
            "count": 0,
            "min_ms": None,
            "mean_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "max_ms": None,
        }
    ordered = sorted(float(value) for value in latencies_ms)

    def percentile(ratio: float) -> float:
        index = max(0, math.ceil(len(ordered) * ratio) - 1)
        return ordered[index]

    return {
        "count": len(ordered),
        "min_ms": round(ordered[0], 3),
        "mean_ms": round(sum(ordered) / len(ordered), 3),
        "p50_ms": round(percentile(0.50), 3),
        "p95_ms": round(percentile(0.95), 3),
        "p99_ms": round(percentile(0.99), 3),
        "max_ms": round(ordered[-1], 3),
    }


def build_real_soak_report(
    *,
    requested: int,
    succeeded: int,
    failed: int,
    duration_seconds: float,
    concurrency: int,
    latencies_ms: list[float],
    errors: list[str],
    connections_opened: int = 0,
    mode: str = "readback",
    sleep_ms: float = 0.0,
) -> dict[str, Any]:
    latency = summarize_latencies(latencies_ms)
    checks = {
        "all_requests_succeeded": (
            requested > 0 and succeeded == requested and failed == 0
        ),
        "latency_samples_present": latency["count"] > 0,
        "throughput_positive": (
            duration_seconds > 0 and requested / duration_seconds > 0
        ),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "p4-figma-real-bridge-soak/1.0",
        "experiment": "P4-FIGMA-REAL-BRIDGE-SOAK",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "duration_seconds": round(duration_seconds, 3),
        "concurrency": concurrency,
        "mode": mode,
        "sleep_ms": round(sleep_ms, 3),
        "connections_opened": connections_opened,
        "requests_per_second": round(
            requested / duration_seconds if duration_seconds > 0 else 0.0,
            3,
        ),
        "latency": latency,
        "errors": errors[:20],
        **checks,
        "failed_checks": failed_checks,
        "status": "pass" if not failed_checks else "fail",
    }


async def run_real_soak(
    *,
    bridge_url: str,
    duration_seconds: float,
    concurrency: int,
    reconnect_every: int,
    mode: str,
    sleep_seconds: float,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("duration must be positive")
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    if reconnect_every <= 0:
        raise ValueError("reconnect-every must be positive")
    if mode not in {"readback", "write"}:
        raise ValueError("mode must be readback or write")

    admin = FigmaBridgeAdapter(
        bridge_url,
        client_id="p4-real-soak-admin",
    )
    admin.connect()
    root_id = ""
    try:
        admin._send(
            "remove_nodes_by_name",
            {"name": ROOT_NAME, "prefix": True},
        )
        root_id = (
            admin.create_frame(
                {
                    "name": ROOT_NAME,
                    "width": 160,
                    "height": 100,
                    "fillColor": "#ffffff",
                }
            )
            or ""
        )
        if not root_id:
            raise RuntimeError("soak root did not return a node id")
        write_node_id = ""
        if mode == "write":
            write_node_id = (
                admin.create_text(
                    {
                        "name": f"{ROOT_NAME} Text",
                        "parentId": root_id,
                        "width": 150,
                        "height": 40,
                        "text": "write soak 0",
                        "fontFamily": "Arial",
                        "fontSize": 14,
                        "textColor": "#111827",
                    }
                )
                or ""
            )
            if not write_node_id:
                raise RuntimeError("soak text did not return a node id")
        deadline = time.perf_counter() + duration_seconds
        started = time.perf_counter()
        results = await asyncio.gather(
            *(
                asyncio.to_thread(
                    _run_worker,
                    bridge_url,
                    root_id,
                    write_node_id,
                    index,
                    deadline,
                    reconnect_every,
                    mode,
                    sleep_seconds,
                )
                for index in range(concurrency)
            )
        )
        elapsed = time.perf_counter() - started
    finally:
        try:
            admin._send(
                "remove_nodes_by_name",
                {"name": ROOT_NAME, "prefix": True},
            )
        except Exception:  # noqa: BLE001
            pass
        admin.disconnect()

    requested = sum(item["requested"] for item in results)
    succeeded = sum(item["succeeded"] for item in results)
    failed = sum(item["failed"] for item in results)
    latencies = [latency for item in results for latency in item["latencies_ms"]]
    errors = [error for item in results for error in item["errors"]]
    connections = sum(item["connections_opened"] for item in results)
    return build_real_soak_report(
        requested=requested,
        succeeded=succeeded,
        failed=failed,
        duration_seconds=elapsed,
        concurrency=concurrency,
        latencies_ms=latencies,
        errors=errors,
        connections_opened=connections,
        mode=mode,
        sleep_ms=sleep_seconds * 1000,
    )


def _run_worker(
    bridge_url: str,
    root_id: str,
    write_node_id: str,
    index: int,
    deadline: float,
    reconnect_every: int,
    mode: str,
    sleep_seconds: float,
) -> dict[str, Any]:
    adapter = FigmaBridgeAdapter(
        bridge_url,
        client_id=f"p4-real-soak-worker-{index}",
    )
    adapter.connect()
    connections = 1
    requested = 0
    succeeded = 0
    failed = 0
    latencies: list[float] = []
    errors: list[str] = []
    sequence = 0
    try:
        while time.perf_counter() < deadline:
            if sequence and sequence % reconnect_every == 0:
                adapter.disconnect()
                adapter.connect()
                connections += 1
            sequence += 1
            requested += 1
            started = time.perf_counter()
            try:
                request_id = f"p4-real-soak-{index}-{sequence}"
                if mode == "readback":
                    result = adapter._send(
                        "get_node_tree",
                        {"nodeId": root_id, "depth": 1},
                        request_id=request_id,
                    )
                else:
                    result = adapter.apply_edit_batch(
                        [
                            {
                                "action": "set_text",
                                "params": {
                                    "nodeId": write_node_id,
                                    "text": (
                                        f"write soak worker {index} "
                                        f"iteration {sequence}"
                                    ),
                                },
                            }
                        ],
                        transaction_id=request_id,
                    )
                latency = (time.perf_counter() - started) * 1000
                if mode == "readback":
                    if not isinstance(result, dict) or result.get("id") != root_id:
                        raise RuntimeError("unexpected get_node_tree result")
                elif (
                    not isinstance(result, dict)
                    or result.get("status") != "committed"
                    or len(result.get("committed") or []) != 1
                ):
                    raise RuntimeError("unexpected edit transaction result")
                latencies.append(latency)
                succeeded += 1
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                errors.append(
                    f"worker={index} sequence={sequence} "
                    f"{type(exc).__name__}: {exc}"
                )
                break
    finally:
        adapter.disconnect()
    return {
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "latencies_ms": latencies,
        "errors": errors,
        "connections_opened": connections,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--bridge-url", default=None)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--reconnect-every", type=int, default=100)
    parser.add_argument(
        "--mode",
        choices=("readback", "write"),
        default="readback",
    )
    parser.add_argument("--sleep-ms", type=float, default=0.0)
    parser.add_argument("--journal", default=None)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        report = asyncio.run(
            run_real_soak(
                bridge_url=args.bridge_url or load_config().figma_bridge_url,
                duration_seconds=args.duration,
                concurrency=args.concurrency,
                reconnect_every=args.reconnect_every,
                mode=args.mode,
                sleep_seconds=max(0.0, args.sleep_ms / 1000),
            )
        )
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": "p4-figma-real-bridge-soak/1.0",
            "experiment": "P4-FIGMA-REAL-BRIDGE-SOAK",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    if args.journal:
        journal_path = Path(args.journal).resolve()
        if journal_path.exists():
            report["journal_events"] = len(
                [
                    line
                    for line in journal_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            )
            report["journal_path"] = str(journal_path)
    report["boundary"] = {
        "real_figma_readback": True,
        "owned_probe_node_only": True,
        "source_mutation": False,
        "measurement_commands": (
            "get_node_tree" if args.mode == "readback" else "apply_edit_batch(set_text)"
        ),
        "measurement_mode": args.mode,
        "sleep_ms": args.sleep_ms,
        "setup_and_cleanup_write": True,
        "long_duration_claim": False,
    }
    _write_report(out / "figma_bridge_soak.json", report)
    print(
        f"[real-soak] {report['status']} "
        f"rps={report.get('requests_per_second', 0)} "
        f"failed={report.get('failed', '-')}"
    )
    print(f"[out ] {out / 'figma_bridge_soak.json'}")
    return 0 if report["status"] == "pass" else 1


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


if __name__ == "__main__":
    raise SystemExit(main())
