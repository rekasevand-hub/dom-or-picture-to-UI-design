"""Run a fixed-budget frame-barrier A/B experiment on selected P1 samples."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure.capture_outcome import classify_capture_outcome
from src.app.services.structure.capture_state import evaluate_state_gate


DEFAULT_SAMPLES = {
    "S01": "https://www.w3schools.com/html/html_iframe.asp",
    "S03": "https://www.w3schools.com/html/html5_canvas.asp",
}
CONDITIONS = ("without-frame-barrier", "with-frame-barrier")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare paired capture with and without a frame-tree barrier."
    )
    parser.add_argument(
        "--samples",
        default="S01,S03",
        help="comma-separated default sample labels",
    )
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--screenshot-timeout-ms", type=int, default=10000)
    parser.add_argument("--snapshot-sync-timeout-ms", type=int, default=3000)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=_ROOT / "output" / "_p1_frame_barrier",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=(
            _ROOT
            / "output"
            / "_p1_frame_barrier"
            / "experiment_round1.json"
        ),
    )
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="reuse existing pair summaries at the same paths",
    )
    args = parser.parse_args(argv)
    labels = [
        item.strip().upper()
        for item in str(args.samples).split(",")
        if item.strip()
    ]
    unknown = [item for item in labels if item not in DEFAULT_SAMPLES]
    if unknown:
        raise SystemExit(f"unknown samples: {unknown}")

    capture_root = args.out_root / "captures"
    sidecar_root = args.out_root / "sidecars"
    previous_runs: dict[str, dict[str, Any]] = {}
    if args.out.is_file():
        try:
            previous = json.loads(args.out.read_text(encoding="utf-8"))
            previous_runs = {
                str(item.get("run_id")): item
                for item in previous.get("runs") or []
                if isinstance(item, dict) and item.get("run_id")
            }
        except (OSError, ValueError):
            previous_runs = {}
    runs: list[dict[str, Any]] = []
    for label in labels:
        for condition in CONDITIONS:
            run_id = f"barrier-exp-{label}-{condition}"
            command = [
                sys.executable,
                str(_ROOT / "scripts" / "p1_dual_browser_capture.py"),
                "--url",
                DEFAULT_SAMPLES[label],
                "--sample-id",
                run_id,
                "--out-root",
                str(capture_root),
                "--sidecar-root",
                str(sidecar_root),
                "--timeout-ms",
                str(args.timeout_ms),
                "--screenshot-timeout-ms",
                str(args.screenshot_timeout_ms),
                "--snapshot-sync-timeout-ms",
                str(args.snapshot_sync_timeout_ms),
                "--retries",
                str(max(0, int(args.retries))),
            ]
            if condition == "with-frame-barrier":
                command.append("--frame-barrier")
            summary_path = sidecar_root / run_id / "pair_summary.json"
            completed = None
            if args.reuse_existing and summary_path.is_file():
                elapsed_s = float(
                    (previous_runs.get(run_id) or {}).get("elapsed_s") or 0
                )
            else:
                started = time.monotonic()
                completed = subprocess.run(
                    command,
                    cwd=str(_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=max(120, (int(args.retries) + 1) * 180),
                    check=False,
                )
                elapsed_s = round(time.monotonic() - started, 3)
            if not summary_path.is_file():
                runs.append({
                    "sample_id": label,
                    "condition": condition,
                    "run_id": run_id,
                    "execution_status": "capture-failed",
                    "comparison_result": "inconclusive",
                    "error": (
                        (
                            completed.stderr or completed.stdout or ""
                        ).strip()[-1200:]
                        if completed is not None
                        else "pair summary missing"
                    ),
                    "command_returncode": (
                        completed.returncode if completed is not None else None
                    ),
                    "elapsed_s": elapsed_s,
                })
                continue
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            selected, attempts = _derive_pair_outcome(summary)
            barriers = []
            for engine, record in (selected.get("engines") or {}).items():
                barrier = record.get("frame_barrier") or (
                    (record.get("page_state") or {})
                    .get("capture_stability", {})
                    .get("frame_barrier")
                )
                if isinstance(barrier, dict):
                    barriers.append({
                        "engine": engine,
                        "synchronized": bool(barrier.get("synchronized")),
                        "frame_tree_match": bool(barrier.get("frame_tree_match")),
                        "reasons": list(barrier.get("reasons") or []),
                    })
            runs.append({
                "sample_id": label,
                "condition": condition,
                "run_id": run_id,
                "pair_summary": str(summary_path),
                "execution_status": selected.get("execution_status"),
                "comparison_result": selected.get("comparison_result"),
                "execution_reasons": list(selected.get("execution_reasons") or []),
                "comparison_reasons": list(selected.get("comparison_reasons") or []),
                "comparison_scope": selected.get("comparison_scope"),
                "selected_attempt": selected.get("attempt"),
                "attempt_count": len(attempts),
                "state_gate": selected.get("state_gate") or {},
                "text_delta": selected.get("text_delta") or {},
                "text_alignment": selected.get("text_alignment") or {},
                "command_returncode": (
                    completed.returncode if completed is not None else None
                ),
                "barrier": {
                    "attempted": any(
                        item["synchronized"]
                        or "peer-timeout" in item["reasons"]
                        for item in barriers
                    ),
                    "synchronized": bool(barriers)
                    and all(item["synchronized"] for item in barriers),
                    "frame_tree_match": bool(barriers)
                    and all(item["frame_tree_match"] for item in barriers),
                    "engines": barriers,
                },
                "elapsed_s": elapsed_s,
            })

    summary = summarize_ab(runs)
    result = {
        "schema_version": "p1-frame-barrier-experiment/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixed_budget": {
            "attempts": max(0, int(args.retries)) + 1,
            "timeout_ms": int(args.timeout_ms),
            "snapshot_sync_timeout_ms": int(args.snapshot_sync_timeout_ms),
        },
        "conditions": list(CONDITIONS),
        "runs": runs,
        "summary": summary,
        "note": (
            "Limited A/B only. A barrier can remove sampling-order artifacts; it "
            "cannot synchronize ad delivery or prove opaque frame internals stable."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "samples": sorted(summary["samples"]),
        "false_equivalence_detected": summary["false_equivalence_detected"],
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0


def summarize_ab(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_sample: dict[str, dict[str, Any]] = {}
    for item in runs:
        if not isinstance(item, dict):
            continue
        sample_id = str(item.get("sample_id") or "")
        condition = str(item.get("condition") or "")
        by_sample.setdefault(sample_id, {})[condition] = item

    samples: dict[str, Any] = {}
    false_equivalence = False
    for sample_id, conditions in sorted(by_sample.items()):
        baseline = conditions.get("without-frame-barrier") or {}
        barrier = conditions.get("with-frame-barrier") or {}
        baseline_result = baseline.get("comparison_result")
        barrier_result = barrier.get("comparison_result")
        change = {
            "from": baseline_result or barrier_result,
            "to": barrier_result or baseline_result,
            "became_ready": (
                baseline.get("execution_status") not in {None, "ready"}
                and barrier.get("execution_status") == "ready"
            ),
            "changed": (
                bool(baseline)
                and bool(barrier)
                and (
                    baseline.get("execution_status") != barrier.get("execution_status")
                    or baseline_result != barrier_result
                )
            ),
        }
        barrier_info = barrier.get("barrier") or {}
        if (
            barrier_result == "equivalent"
            and barrier_info.get("attempted")
            and not barrier_info.get("frame_tree_match")
        ):
            false_equivalence = True
        samples[sample_id] = {
            "execution_status": barrier.get("execution_status")
            or baseline.get("execution_status"),
            "comparison_result": barrier_result or baseline_result,
            "baseline": baseline,
            "barrier": barrier,
            "change": change,
            "drift": _drift_metrics(baseline, barrier),
        }

    counts = {}
    for condition in CONDITIONS:
        condition_runs = [
            item
            for item in runs
            if isinstance(item, dict) and item.get("condition") == condition
        ]
        counts[condition] = {
            result: sum(item.get("comparison_result") == result for item in condition_runs)
            for result in ("equivalent", "different", "inconclusive")
        }
        counts[condition]["capture_failed"] = sum(
            item.get("execution_status") == "capture-failed"
            for item in condition_runs
        )
    return {
        "samples": samples,
        "condition_counts": counts,
        "false_equivalence_detected": false_equivalence,
        "fixed_budget_note": "All conditions use the same attempt and timeout budget.",
    }


def _drift_metrics(
    baseline: dict[str, Any],
    barrier: dict[str, Any],
) -> dict[str, Any]:
    before = _comparison_metrics(baseline)
    after = _comparison_metrics(barrier)
    return {
        "baseline": before,
        "barrier": after,
        "text_drift_reduced": (
            before["text_count_delta"] is not None
            and after["text_count_delta"] is not None
            and after["text_count_delta"] < before["text_count_delta"]
        ),
        "coverage_increased": (
            before["coverage"] is not None
            and after["coverage"] is not None
            and after["coverage"] > before["coverage"]
        ),
        "text_count_delta_after": after["text_count_delta"],
        "elapsed_s_delta": _float_delta(
            after["elapsed_s"],
            before["elapsed_s"],
        ),
    }


def _comparison_metrics(run: dict[str, Any]) -> dict[str, Any]:
    gate = run.get("state_gate") or {}
    chromium = gate.get("chromium") or {}
    webkit = gate.get("webkit") or {}
    chromium_text = _optional_int(chromium.get("text_count"))
    webkit_text = _optional_int(webkit.get("text_count"))
    chromium_nodes = _optional_int(chromium.get("node_count"))
    webkit_nodes = _optional_int(webkit.get("node_count"))
    coverage = (run.get("text_alignment") or {}).get("coverage")
    return {
        "text_count_delta": (
            abs(chromium_text - webkit_text)
            if chromium_text is not None and webkit_text is not None
            else None
        ),
        "node_count_delta": (
            abs(chromium_nodes - webkit_nodes)
            if chromium_nodes is not None and webkit_nodes is not None
            else None
        ),
        "coverage": _optional_float(coverage),
        "elapsed_s": _optional_float(run.get("elapsed_s")),
    }


def _derive_pair_outcome(
    summary: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for item in summary.get("state_attempts") or []:
        if not isinstance(item, dict):
            continue
        gate = _recompute_attempt_gate(item)
        outcome = classify_capture_outcome(
            gate,
            item.get("engines") or {},
            item.get("text_delta") or {},
            content_comparable=bool(item.get("content_comparable")),
        )
        record = {
            **item,
            "state_gate": gate,
            **outcome,
        }
        attempts.append(record)
        if selected is None and outcome["execution_status"] == "ready":
            selected = record
    if selected is None and attempts:
        selected = attempts[0]
    if selected is None:
        selected = {
            "attempt": summary.get("selected_state_attempt"),
            "execution_status": summary.get("execution_status") or "capture-failed",
            "comparison_result": summary.get("comparison_result") or "inconclusive",
            "execution_reasons": list(summary.get("execution_reasons") or []),
            "comparison_reasons": list(summary.get("comparison_reasons") or []),
            "comparison_scope": summary.get("comparison_scope"),
            "engines": summary.get("engines") or {},
            "content_comparable": bool(summary.get("content_comparable")),
        }
    return selected, attempts


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_delta(after: float | None, before: float | None) -> float | None:
    if after is None or before is None:
        return None
    return round(after - before, 3)


def _recompute_attempt_gate(item: dict[str, Any]) -> dict[str, Any]:
    engines = item.get("engines") or {}
    paths = {
        engine: {
            "dom": Path(str((record or {}).get("capture_dir") or "")) / "00_dom.json",
            "state": Path(str((record or {}).get("capture_dir") or ""))
            / "00_page_state.json",
        }
        for engine, record in engines.items()
        if isinstance(record, dict)
    }
    if not all(
        files["dom"].is_file() and files["state"].is_file()
        for files in paths.values()
    ) or not {"chromium", "webkit"}.issubset(paths):
        return item.get("state_gate") or {}
    gate = evaluate_state_gate(
        json.loads(paths["chromium"]["dom"].read_text(encoding="utf-8")),
        json.loads(paths["chromium"]["state"].read_text(encoding="utf-8")),
        json.loads(paths["webkit"]["dom"].read_text(encoding="utf-8")),
        json.loads(paths["webkit"]["state"].read_text(encoding="utf-8")),
        require_stability=True,
    )
    return {
        "comparable": gate["comparable"],
        "reasons": gate["reasons"],
        "chromium": gate["left"],
        "webkit": gate["right"],
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
