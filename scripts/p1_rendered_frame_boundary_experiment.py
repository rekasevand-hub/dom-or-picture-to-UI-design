"""Compare full-visible, first-party, and rendered-frame-boundary scopes."""
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


DEFAULT_SAMPLES = {
    "S01": "https://www.w3schools.com/html/html_iframe.asp",
    "S03": "https://www.w3schools.com/html/html5_canvas.asp",
    "S05": "https://www.w3schools.com/graphics/canvas_text.asp",
}
CONDITIONS = ("full-visible", "first-party-frame", "rendered-frame-boundary")
BOUNDARY_PROFILE = "rendered-frame-boundary-strict/1.0"
FIRST_PARTY_PROFILE = "first-party-frame-strict/1.0"
STRICT_PROFILE = "rendered-frame-state-strict/1.0"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run fixed-budget P1 frame scope A/B."
    )
    parser.add_argument("--samples", default="S01,S03,S05")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--screenshot-timeout-ms", type=int, default=10000)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=_ROOT / "output" / "_p1_rendered_frame_boundary",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=(
            _ROOT
            / "output"
            / "_p1_rendered_frame_boundary"
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
    previous_runs = _load_previous_runs(args.out)
    runs: list[dict[str, Any]] = []
    for label in labels:
        for condition in CONDITIONS:
            run_id = f"boundary-exp-{label}-{condition}"
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
                str(max(1000, int(args.timeout_ms))),
                "--screenshot-timeout-ms",
                str(max(1000, int(args.screenshot_timeout_ms))),
                "--retries",
                str(max(0, int(args.retries))),
            ]
            if condition == "first-party-frame":
                command.append("--first-party-frame-profile")
            elif condition == "rendered-frame-boundary":
                command.append("--rendered-frame-boundary-profile")
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
                    "comparison_profile": None,
                    "command_returncode": (
                        completed.returncode if completed is not None else None
                    ),
                    "error": (
                        (completed.stderr or completed.stdout or "").strip()[-1600:]
                        if completed is not None
                        else "pair summary missing"
                    ),
                    "elapsed_s": elapsed_s,
                })
                continue
            pair = json.loads(summary_path.read_text(encoding="utf-8"))
            boundary_gate = pair.get("rendered_frame_boundary") or {}
            boundary = _boundary_result(boundary_gate)
            selected_attempt = _selected_attempt_record(pair)
            runs.append({
                "sample_id": label,
                "condition": condition,
                "run_id": run_id,
                "pair_summary": str(summary_path),
                "execution_status": pair.get("execution_status"),
                "comparison_result": pair.get("comparison_result"),
                "execution_reasons": list(pair.get("execution_reasons") or []),
                "comparison_reasons": list(pair.get("comparison_reasons") or []),
                "comparison_scope": pair.get("comparison_scope"),
                "capture_profile": pair.get("capture_profile"),
                "comparison_profile": pair.get("comparison_profile"),
                "legacy_comparison_result": pair.get("legacy_comparison_result"),
                "legacy_comparison_reasons": list(
                    pair.get("legacy_comparison_reasons") or []
                ),
                "selected_attempt": pair.get("selected_state_attempt"),
                "selection_rule": pair.get("selection_rule"),
                "selected_attempt_reasons": list(
                    (selected_attempt.get("comparison_reasons") or [])
                ),
                "blocked_document_count": _blocked_document_count(pair),
                "excluded_frame_count": _excluded_frame_count(boundary),
                "unobservable_frame_count": len(
                    boundary.get("unobservable") or []
                ),
                "rendered_frame_boundary_gate": boundary_gate or None,
                "rendered_frame_boundary": boundary or None,
                "text_alignment": pair.get("text_alignment") or {},
                "state_gate": pair.get("state_gate") or {},
                "command_returncode": (
                    completed.returncode if completed is not None else None
                ),
                "elapsed_s": elapsed_s,
            })

    summary = summarize_boundary_experiment(runs)
    result = {
        "schema_version": "p1-rendered-frame-boundary-experiment/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixed_budget": {
            "attempts": max(0, int(args.retries)) + 1,
            "timeout_ms": int(args.timeout_ms),
            "screenshot_timeout_ms": int(args.screenshot_timeout_ms),
        },
        "conditions": list(CONDITIONS),
        "runs": runs,
        "summary": summary,
        "note": (
            "The rendered-frame-boundary scope compares frame boundaries only. "
            "It is not whole-page equivalence and does not observe opaque internals."
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


def summarize_boundary_experiment(
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
    profile_mismatches: list[dict[str, Any]] = []
    false_equivalence = False
    for sample_id, conditions in sorted(grouped.items()):
        full = conditions.get("full-visible") or {}
        first_party = conditions.get("first-party-frame") or {}
        boundary = conditions.get("rendered-frame-boundary") or {}
        _check_scope_profile(
            sample_id,
            full,
            expected_profile=STRICT_PROFILE,
            profile_mismatches=profile_mismatches,
        )
        _check_scope_profile(
            sample_id,
            first_party,
            expected_profile=FIRST_PARTY_PROFILE,
            profile_mismatches=profile_mismatches,
        )
        boundary_claims = list(
            (boundary.get("rendered_frame_boundary") or {}).get("claims") or []
        )
        boundary_equivalence_valid = (
            boundary.get("comparison_result") != "equivalent"
            or (
                boundary.get("comparison_profile") == BOUNDARY_PROFILE
                and boundary_claims == ["rendered-frame-boundary-equivalent"]
                and (boundary.get("rendered_frame_boundary") or {}).get(
                    "comparable"
                ) is True
                and (boundary.get("rendered_frame_boundary") or {}).get(
                    "opaque_contents_observable"
                ) is False
            )
        )
        if not boundary_equivalence_valid:
            profile_mismatches.append({
                "sample_id": sample_id,
                "condition": "rendered-frame-boundary",
                "actual": boundary.get("comparison_profile"),
                "claims": boundary_claims,
            })
            false_equivalence = True
        if any(
            item.get("sample_id") == sample_id
            and item.get("comparison_result") == "equivalent"
            for item in profile_mismatches
        ):
            false_equivalence = True

        samples[sample_id] = {
            "legacy_full_visible": full,
            "first_party_scope": first_party,
            "rendered_boundary_scope": boundary,
            "side_by_side": {
                "legacy_full_visible": full.get("comparison_result"),
                "first_party": first_party.get("comparison_result"),
                "rendered_boundary": boundary.get("comparison_result"),
                "boundary_baseline_strict": boundary.get(
                    "legacy_comparison_result"
                ),
            },
            "exclusions": {
                "first_party_blocked_documents": first_party.get(
                    "blocked_document_count", 0
                ),
                "boundary_excluded_frames": boundary.get(
                    "excluded_frame_count", 0
                ),
            },
            "unobservable": boundary.get("unobservable_frame_count", 0),
        }

    condition_counts = {}
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
        condition_counts[condition]["elapsed_s"] = round(
            sum(float(item.get("elapsed_s") or 0) for item in selected),
            3,
        )
        condition_counts[condition]["blocked_documents"] = sum(
            int(item.get("blocked_document_count") or 0) for item in selected
        )
        condition_counts[condition]["unobservable_frames"] = sum(
            int(item.get("unobservable_frame_count") or 0) for item in selected
        )
    return {
        "samples": samples,
        "condition_counts": condition_counts,
        "profile_mismatches": profile_mismatches,
        "false_equivalence_detected": false_equivalence,
        "page_equivalence_claimed": False,
        "fixed_budget_note": (
            "All three conditions use the same attempts and timeout budget. "
            "Each scope keeps its own denominator."
        ),
    }


def _check_scope_profile(
    sample_id: str,
    run: dict[str, Any],
    *,
    expected_profile: str,
    profile_mismatches: list[dict[str, Any]],
) -> None:
    if not run:
        return
    actual = (
        run.get("comparison_profile")
        if expected_profile == BOUNDARY_PROFILE
        else run.get("capture_profile")
    )
    if actual == expected_profile:
        return
    profile_mismatches.append({
        "sample_id": sample_id,
        "condition": run.get("condition"),
        "actual": actual,
        "expected": expected_profile,
        "comparison_result": run.get("comparison_result"),
    })


def _load_previous_runs(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        str(item.get("run_id")): item
        for item in (value.get("runs") or [])
        if isinstance(item, dict) and item.get("run_id")
    }


def _selected_attempt_record(pair: dict[str, Any]) -> dict[str, Any]:
    selected = pair.get("selected_state_attempt")
    for item in pair.get("state_attempts") or []:
        if isinstance(item, dict) and item.get("attempt") == selected:
            return item
    return {}


def _blocked_document_count(pair: dict[str, Any]) -> int:
    return sum(
        int(
            ((record.get("frame_request_policy") or {})
             .get("blocked_document_count") or 0)
        )
        for record in (pair.get("engines") or {}).values()
        if isinstance(record, dict)
    )


def _excluded_frame_count(boundary: dict[str, Any]) -> int:
    excluded = boundary.get("excluded") or {}
    return len(excluded.get("left") or []) + len(excluded.get("right") or [])


def _boundary_result(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    nested = value.get("boundary")
    return nested if isinstance(nested, dict) else value


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
