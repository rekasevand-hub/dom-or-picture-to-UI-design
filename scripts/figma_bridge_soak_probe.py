"""Run sustained read-only commands against the real Figma bridge."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.job_namespace import build_job_namespace  # noqa: E402
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.config.settings import load_config  # noqa: E402


ROOT_NAME = "P5 Real Bridge Soak"


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
    run_id: str | None = None,
    setup_cleanup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latency = summarize_latencies(latencies_ms)
    setup_cleanup = setup_cleanup or {}
    checks = {
        "all_requests_succeeded": (
            requested > 0 and succeeded == requested and failed == 0
        ),
        "latency_samples_present": latency["count"] > 0,
        "throughput_positive": (
            duration_seconds > 0 and requested / duration_seconds > 0
        ),
        "owned_setup_verified": setup_cleanup.get("setup_verified") is True,
        "exact_cleanup_verified": setup_cleanup.get("cleanup_verified") is True,
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
        "run_id": run_id,
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
        "setup_cleanup": setup_cleanup,
        **checks,
        "failed_checks": failed_checks,
        "status": "pass" if not failed_checks else "fail",
    }


def apply_journal_bound(
    report: dict[str, Any],
    *,
    journal_events: int,
    max_journal_events: int,
) -> dict[str, Any]:
    if max_journal_events <= 0:
        raise ValueError("max_journal_events must be positive")
    bounded = dict(report)
    failed_checks = list(bounded.get("failed_checks") or [])
    journal_bounded = 0 <= journal_events <= max_journal_events
    bounded["journal_events"] = journal_events
    bounded["max_journal_events"] = max_journal_events
    bounded["journal_bounded"] = journal_bounded
    if not journal_bounded and "journal_bounded" not in failed_checks:
        failed_checks.append("journal_bounded")
    bounded["failed_checks"] = failed_checks
    bounded["status"] = "pass" if not failed_checks else "fail"
    return bounded


def _batch_node_id(response: dict[str, Any]) -> str:
    if response.get("status") != "committed":
        raise RuntimeError(f"owned batch was not committed: {response!r}")
    for item in response.get("committed") or []:
        if not isinstance(item, dict):
            continue
        node_id = item.get("result")
        if isinstance(node_id, str) and node_id:
            return node_id
    raise RuntimeError("owned batch did not return a node id")


def _report_contains_node(report: dict[str, Any], node_id: str) -> bool:
    return any(
        isinstance(item, dict) and item.get("nodeId") == node_id
        for item in report.get("nodes") or []
    )


def _setup_owned_soak_nodes(
    admin: FigmaBridgeAdapter,
    run_id: str,
    *,
    mode: str,
) -> dict[str, Any]:
    client_id = str(admin.client_id)
    root_job = build_job_namespace(client_id, f"p5-soak-root-{run_id}")
    text_job = build_job_namespace(client_id, f"p5-soak-text-{run_id}")
    setup: dict[str, Any] = {
        "run_id": run_id,
        "root_job": root_job,
        "root_id": "",
        "text_job": "",
        "text_id": "",
        "verified": False,
        "failed_checks": [],
    }
    try:
        root_response = admin.apply_batch(
            [
                {
                    "action": "create_frame",
                    "params": {
                        "name": ROOT_NAME,
                        "width": 160,
                        "height": 100,
                        "fillColor": "#ffffff",
                    },
                }
            ],
            transaction_id=root_job,
        )
        setup["root_response"] = root_response
        setup["root_id"] = _batch_node_id(root_response)
        if mode == "write":
            setup["text_job"] = text_job
            text_response = admin.apply_batch(
                [
                    {
                        "action": "create_text",
                        "params": {
                            "name": f"{ROOT_NAME} Text",
                            "parentId": setup["root_id"],
                            "width": 150,
                            "height": 40,
                            "text": "write soak 0",
                            "fontFamily": "Arial",
                            "fontSize": 14,
                            "textColor": "#111827",
                        },
                    }
                ],
                transaction_id=text_job,
            )
            setup["text_response"] = text_response
            setup["text_id"] = _batch_node_id(text_response)

        root_report = admin.ownership_report(root_job)
        setup["root_ownership"] = root_report
        checks = {
            "root_owned": (
                root_report.get("matched", 0) >= 1
                and _report_contains_node(root_report, setup["root_id"])
            )
        }
        if mode == "write":
            text_report = admin.ownership_report(text_job)
            setup["text_ownership"] = text_report
            checks["text_owned"] = (
                text_report.get("matched", 0) >= 1
                and _report_contains_node(text_report, setup["text_id"])
            )
        setup["checks"] = checks
        setup["failed_checks"] = [
            name for name, passed in checks.items() if not passed
        ]
        setup["verified"] = all(checks.values())
    except Exception as exc:  # noqa: BLE001 - cleanup still needs partial ids
        setup["error"] = f"{type(exc).__name__}: {exc}"
        setup["failed_checks"].append("setup_error")
    return setup


def _collect_tree_nodes(node: Any) -> list[dict[str, Any]]:
    if not isinstance(node, dict):
        return []
    found = [node]
    for child in node.get("children") or []:
        found.extend(_collect_tree_nodes(child))
    return found


def _cleanup_owned_soak_nodes(
    admin: FigmaBridgeAdapter,
    setup: dict[str, Any],
) -> dict[str, Any]:
    cleanup: dict[str, Any] = {
        "verified": False,
        "failed_checks": [],
        "cleanup_results": [],
        "ownership_reports": [],
        "attempts": 0,
        "attempt_errors": [],
    }
    jobs = [
        job
        for job in (setup.get("text_job"), setup.get("root_job"))
        if isinstance(job, str) and job
    ]
    for attempt in range(1, 3):
        cleanup["attempts"] = attempt
        cleanup["failed_checks"] = []
        cleanup["cleanup_results"] = []
        cleanup["ownership_reports"] = []
        try:
            _reconnect_admin(admin)
            for job in jobs:
                result = admin.cleanup_owned_job(job)
                report = admin.ownership_report(job)
                cleanup["cleanup_results"].append(result)
                cleanup["ownership_reports"].append(report)
                if result.get("status") != "cleaned" or result.get("failed"):
                    cleanup["failed_checks"].append(f"cleanup_status:{job}")
                if report.get("matched") != 0:
                    cleanup["failed_checks"].append(
                        f"ownership_remaining:{job}"
                    )

            page_tree = admin._send("get_node_tree", {"depth": 4})
            cleanup["page_tree_readback"] = page_tree
            probe_ids = {
                node_id
                for node_id in (setup.get("root_id"), setup.get("text_id"))
                if isinstance(node_id, str) and node_id
            }
            residual = [
                node
                for node in _collect_tree_nodes(page_tree)
                if node.get("id") in probe_ids
                or str(node.get("name") or "").startswith(ROOT_NAME)
            ]
            cleanup["residual_nodes"] = residual
            if residual:
                cleanup["failed_checks"].append(
                    "page_tree_residual_probe_nodes"
                )
            if not cleanup["failed_checks"]:
                cleanup["verified"] = True
            return cleanup
        except OSError as exc:
            cleanup["attempt_errors"].append(
                f"attempt={attempt} {type(exc).__name__}: {exc}"
            )
            if attempt == 2:
                cleanup["error"] = f"{type(exc).__name__}: {exc}"
                cleanup["failed_checks"].append("cleanup_error")
        except Exception as exc:  # noqa: BLE001 - preserve failure evidence
            cleanup["error"] = f"{type(exc).__name__}: {exc}"
            cleanup["failed_checks"].append("cleanup_error")
            break
    return cleanup


def _reconnect_admin(admin: FigmaBridgeAdapter) -> None:
    try:
        admin.disconnect()
    except Exception:  # noqa: BLE001 - replacement socket is the recovery path
        pass
    admin.connect()


async def run_real_soak(
    *,
    bridge_url: str,
    duration_seconds: float,
    concurrency: int,
    reconnect_every: int,
    mode: str,
    sleep_seconds: float,
    run_id: str | None = None,
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
    run_id = str(run_id or uuid.uuid4().hex[:12]).strip()
    admin.connect()
    setup: dict[str, Any] | None = None
    cleanup: dict[str, Any] | None = None
    results: list[dict[str, Any]] = []
    elapsed = 0.0
    workflow_error = ""
    try:
        setup = _setup_owned_soak_nodes(admin, run_id, mode=mode)
        if setup["verified"]:
            deadline = time.perf_counter() + duration_seconds
            started = time.perf_counter()
            results = await asyncio.gather(
                *(
                    asyncio.to_thread(
                        _run_worker,
                        bridge_url,
                        str(setup["root_id"]),
                        str(setup["text_id"]),
                        index,
                        deadline,
                        reconnect_every,
                        mode,
                        sleep_seconds,
                        run_id,
                    )
                    for index in range(concurrency)
                )
            )
            elapsed = time.perf_counter() - started
        else:
            workflow_error = "owned soak setup verification failed"
    finally:
        if setup is not None:
            cleanup = _cleanup_owned_soak_nodes(admin, setup)
        admin.disconnect()

    requested = sum(item["requested"] for item in results)
    succeeded = sum(item["succeeded"] for item in results)
    failed = sum(item["failed"] for item in results)
    latencies = [latency for item in results for latency in item["latencies_ms"]]
    errors = [error for item in results for error in item["errors"]]
    connections = sum(item["connections_opened"] for item in results)
    if workflow_error:
        errors.insert(0, workflow_error)
    setup_cleanup = {
        "setup_verified": bool(setup and setup.get("verified")),
        "cleanup_verified": bool(cleanup and cleanup.get("verified")),
        "setup": setup,
        "cleanup": cleanup,
    }
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
        run_id=run_id,
        setup_cleanup=setup_cleanup,
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
    run_id: str,
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
                request_id = f"p4-real-soak-{run_id}-{index}-{sequence}"
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
    parser.add_argument("--max-journal-events", type=int, default=4096)
    parser.add_argument("--run-id", default=None)
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
                run_id=args.run_id,
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
            report = apply_journal_bound(
                report,
                journal_events=len(
                    [
                        line
                        for line in journal_path.read_text(
                            encoding="utf-8"
                        ).splitlines()
                        if line.strip()
                    ]
                ),
                max_journal_events=args.max_journal_events,
            )
            report["journal_path"] = str(journal_path)
        else:
            report["journal_path"] = str(journal_path)
            report["status"] = "fail"
            report.setdefault("failed_checks", []).append("journal_missing")
    report["boundary"] = {
        "real_figma_readback": bool(
            report.get("setup_cleanup", {}).get("setup_verified")
            and report.get("setup_cleanup", {}).get("cleanup_verified")
        ),
        "owned_probe_node_only": bool(
            report.get("setup_cleanup", {}).get("setup_verified")
            and report.get("setup_cleanup", {}).get("cleanup_verified")
        ),
        "source_mutation": False,
        "measurement_commands": (
            "get_node_tree" if args.mode == "readback" else "apply_edit_batch(set_text)"
        ),
        "measurement_mode": args.mode,
        "sleep_ms": args.sleep_ms,
        "setup_and_cleanup_write": bool(
            report.get("setup_cleanup", {}).get("setup_verified")
            and report.get("setup_cleanup", {}).get("cleanup_verified")
        ),
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
