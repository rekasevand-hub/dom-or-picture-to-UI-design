"""Compare full-visible and explicit first-party frame profiles."""
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

from scripts.p1_frame_barrier_experiment import (
    _comparison_metrics,
    _derive_pair_outcome,
)


DEFAULT_SAMPLES = {
    "S01": "https://www.w3schools.com/html/html_iframe.asp",
    "S03": "https://www.w3schools.com/html/html5_canvas.asp",
    "S05": "https://www.w3schools.com/graphics/canvas_text.asp",
}
CONDITIONS = ("full-visible", "first-party-frame")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="A/B full-visible and first-party-frame strict profiles."
    )
    parser.add_argument("--samples", default="S01,S03,S05")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--screenshot-timeout-ms", type=int, default=10000)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=_ROOT / "output" / "_p1_first_party_scope",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=(
            _ROOT
            / "output"
            / "_p1_first_party_scope"
            / "experiment_round1.json"
        ),
    )
    parser.add_argument("--reuse-existing", action="store_true")
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
            run_id = f"scope-exp-{label}-{condition}"
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
                "--retries",
                str(max(0, int(args.retries))),
            ]
            if condition == "first-party-frame":
                command.append("--first-party-frame-profile")
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
                    "capture_profile": None,
                    "error": (
                        (completed.stderr or completed.stdout or "").strip()[-1200:]
                        if completed is not None
                        else "pair summary missing"
                    ),
                    "elapsed_s": elapsed_s,
                })
                continue
            pair = json.loads(summary_path.read_text(encoding="utf-8"))
            selected, attempts = _derive_pair_outcome(pair)
            engines = selected.get("engines") or {}
            blocked = sum(
                int(
                    ((record.get("frame_request_policy") or {})
                     .get("blocked_document_count") or 0)
                )
                for record in engines.values()
                if isinstance(record, dict)
            )
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
                "capture_profile": pair.get("capture_profile")
                or selected.get("capture_profile"),
                "selected_attempt": selected.get("attempt"),
                "attempt_count": len(attempts),
                "blocked_document_count": blocked,
                "metrics": _comparison_metrics(selected),
                "state_gate": selected.get("state_gate") or {},
                "text_delta": selected.get("text_delta") or {},
                "command_returncode": (
                    completed.returncode if completed is not None else None
                ),
                "elapsed_s": elapsed_s,
            })

    summary = summarize_scope_experiment(runs)
    result = {
        "schema_version": "p1-first-party-scope-experiment/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixed_budget": {
            "attempts": max(0, int(args.retries)) + 1,
            "timeout_ms": int(args.timeout_ms),
        },
        "conditions": list(CONDITIONS),
        "runs": runs,
        "summary": summary,
        "note": (
            "The first-party profile explicitly blocks cross-origin frame documents. "
            "It is a separate scope, not a full-visible strict result."
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


def summarize_scope_experiment(
    runs: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for item in runs:
        if not isinstance(item, dict):
            continue
        sample_id = str(item.get("sample_id") or "")
        condition = str(item.get("condition") or "")
        grouped.setdefault(sample_id, {})[condition] = item

    samples: dict[str, Any] = {}
    false_equivalence = False
    profile_mismatches: list[dict[str, Any]] = []
    for sample_id, conditions in sorted(grouped.items()):
        baseline = conditions.get("full-visible") or {}
        first_party = conditions.get("first-party-frame") or {}
        profile = first_party.get("capture_profile")
        if first_party and profile != "first-party-frame-strict/1.0":
            profile_mismatches.append({
                "sample_id": sample_id,
                "actual": profile,
            })
            if first_party.get("comparison_result") == "equivalent":
                false_equivalence = True
        first_party_equivalent = (
            first_party.get("comparison_result") == "equivalent"
            and profile == "first-party-frame-strict/1.0"
        )
        samples[sample_id] = {
            "baseline": baseline,
            "first_party": first_party,
            "comparison_result": (
                "equivalent" if first_party_equivalent
                else first_party.get("comparison_result")
                or baseline.get("comparison_result")
            ),
            "change": {
                "baseline_result": baseline.get("comparison_result"),
                "first_party_result": first_party.get("comparison_result"),
                "became_ready": (
                    baseline.get("execution_status") not in {None, "ready"}
                    and first_party.get("execution_status") == "ready"
                ),
                "became_equivalent": (
                    first_party_equivalent
                    and baseline.get("comparison_result") != "equivalent"
                ),
            },
        }

    condition_counts: dict[str, Any] = {}
    for condition in CONDITIONS:
        selected = [
            item for item in runs
            if isinstance(item, dict) and item.get("condition") == condition
        ]
        condition_counts[condition] = {
            result: sum(
                item.get("comparison_result") == result for item in selected
            )
            for result in ("equivalent", "different", "inconclusive")
        }
        condition_counts[condition]["blocked_documents"] = sum(
            int(item.get("blocked_document_count") or 0) for item in selected
        )
    return {
        "samples": samples,
        "condition_counts": condition_counts,
        "profile_mismatches": profile_mismatches,
        "false_equivalence_detected": false_equivalence,
        "fixed_budget_note": "Both profiles use the same attempt and timeout budget.",
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
