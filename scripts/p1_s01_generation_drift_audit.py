"""Audit existing S01 attempts for execution stability and frame generation drift."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


DEFAULT_EXPERIMENT = (
    _ROOT
    / "output"
    / "_p1_rendered_frame_boundary"
    / "experiment_round1.json"
)
NAVIGATION_FAILED = {"browser-navigation-failed", "navigation-failed"}
CLASSIFICATIONS = (
    "capture-failure",
    "navigation-failure",
    "execution-instability",
    "frame-generation-drift",
    "frame-generation-unobservable",
    "boundary-difference",
    "stable-comparable",
    "inconclusive-other",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only S01 execution and frame-generation audit."
    )
    parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    parser.add_argument(
        "--out",
        type=Path,
        default=(
            _ROOT
            / "output"
            / "_p1_s01_generation_drift"
            / "s01_round1.json"
        ),
    )
    args = parser.parse_args(argv)
    experiment = json.loads(args.experiment.read_text(encoding="utf-8"))
    scopes: list[dict[str, Any]] = []
    for run in experiment.get("runs") or []:
        if not isinstance(run, dict) or run.get("sample_id") != "S01":
            continue
        pair_path = Path(str(run.get("pair_summary") or ""))
        if not pair_path.is_file():
            scopes.append({
                "condition": run.get("condition"),
                "run_id": run.get("run_id"),
                "pair_summary": str(pair_path),
                "error": "pair-summary-missing",
            })
            continue
        pair = json.loads(pair_path.read_text(encoding="utf-8"))
        summary = summarize_s01_attempts(
            list(pair.get("state_attempts") or []),
            selected_attempt=pair.get("selected_state_attempt"),
        )
        scopes.append({
            "condition": run.get("condition"),
            "run_id": run.get("run_id"),
            "pair_summary": str(pair_path),
            "selected_attempt": pair.get("selected_state_attempt"),
            "execution_status": pair.get("execution_status"),
            "comparison_result": pair.get("comparison_result"),
            **summary,
        })

    aggregate_counts: Counter[str] = Counter()
    for scope in scopes:
        aggregate_counts.update(scope.get("classification_counts") or {})
    result = {
        "schema_version": "p1-s01-generation-drift-audit/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_id": "P1-S01-R1",
        "source_experiment": str(args.experiment),
        "scope_count": len(scopes),
        "scopes": scopes,
        "aggregate_attempt_classification_counts": {
            key: aggregate_counts[key] for key in CLASSIFICATIONS
        },
        "note": (
            "Read-only audit of existing attempts. The source contract's selected "
            "attempt remains primary; later generation drift is supplementary."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "scope_count": len(scopes),
        "primary_classes": {
            item.get("condition"): item.get("primary_classification")
            for item in scopes
        },
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0


def summarize_s01_attempts(
    attempts: Sequence[dict[str, Any]],
    *,
    selected_attempt: int | None,
) -> dict[str, Any]:
    records = [
        _audit_attempt(item)
        for item in attempts
        if isinstance(item, dict) and _optional_int(item.get("attempt")) is not None
    ]
    counts = Counter(item["classification"] for item in records)
    primary = next(
        (
            item for item in records
            if item["attempt"] == _optional_int(selected_attempt)
        ),
        records[0] if records else None,
    )
    return {
        "primary_attempt": primary["attempt"] if primary else None,
        "primary_classification": (
            primary["classification"] if primary else "capture-failure"
        ),
        "attempt_count": len(records),
        "classification_counts": {
            key: counts[key] for key in CLASSIFICATIONS
        },
        "generation_drift_attempt_count": sum(
            bool(item["generation_drift_paths"]) for item in records
        ),
        "attempts": records,
    }


def _audit_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    engines = {
        str(engine): record
        for engine, record in (attempt.get("engines") or {}).items()
        if isinstance(record, dict)
    }
    expected = {"chromium", "webkit"}
    missing = expected.difference(engines)
    invalid = missing or any(
        record.get("status") != "ok"
        or not isinstance(
            (record.get("page_state") or {}).get("frame_inventory"),
            list,
        )
        for record in engines.values()
    )
    navigation_failed = any(
        ((record.get("navigation") or {}).get("status") in NAVIGATION_FAILED)
        for record in engines.values()
    )
    stability = {
        engine: _stability(record)
        for engine, record in engines.items()
    }
    stable_both = all(
        stability.get(engine, {}).get("stable") is True
        for engine in expected
    )
    generation = {
        engine: _generation_map(record)
        for engine, record in engines.items()
    }
    drift_paths = _generation_drift_paths(
        generation.get("chromium") or {},
        generation.get("webkit") or {},
    )
    timeline = {
        engine: _timeline_summary(record)
        for engine, record in engines.items()
    }
    reasons = list((attempt.get("state_gate") or {}).get("reasons") or [])
    classification = _classify(
        invalid=bool(invalid),
        navigation_failed=navigation_failed,
        stable_both=stable_both,
        reasons=reasons,
    )
    return {
        "attempt": _optional_int(attempt.get("attempt")),
        "classification": classification,
        "state_gate_reasons": reasons,
        "stable_both": stable_both,
        "stability": stability,
        "navigation_failed": navigation_failed,
        "missing_engines": sorted(missing),
        "generation_by_engine": generation,
        "generation_drift_paths": drift_paths,
        "timeline": timeline,
    }


def _classify(
    *,
    invalid: bool,
    navigation_failed: bool,
    stable_both: bool,
    reasons: list[str],
) -> str:
    if invalid:
        return "capture-failure"
    if navigation_failed:
        return "navigation-failure"
    if not stable_both:
        return "execution-instability"
    if "frame-document-generation-difference" in reasons:
        return "frame-generation-drift"
    if "frame-document-generation-unobservable" in reasons:
        return "frame-generation-unobservable"
    if any(reason.startswith("frame-") for reason in reasons):
        return "boundary-difference"
    if "state-unstable" in reasons:
        return "execution-instability"
    if not reasons:
        return "stable-comparable"
    return "inconclusive-other"


def _stability(record: dict[str, Any]) -> dict[str, Any]:
    stability = (record.get("page_state") or {}).get("capture_stability") or {}
    return {
        "stable": stability.get("stable") is True,
        "samples": _optional_int(stability.get("samples")),
        "waited_ms": _optional_int(stability.get("waited_ms")),
        "probe_errors": _optional_int(stability.get("probe_errors")),
    }


def _generation_map(record: dict[str, Any]) -> dict[str, int | None]:
    inventory = (record.get("page_state") or {}).get("frame_inventory") or []
    result: dict[str, int | None] = {}
    for frame in inventory:
        if not isinstance(frame, dict) or frame.get("rendered") is not True:
            continue
        path = str(frame.get("scope_path") or frame.get("path") or "")
        if path:
            result[path] = _optional_int(frame.get("document_generation"))
    return dict(sorted(result.items()))


def _generation_drift_paths(
    left: dict[str, int | None],
    right: dict[str, int | None],
) -> list[str]:
    return sorted(
        path
        for path in set(left) & set(right)
        if left[path] != right[path]
    )


def _timeline_summary(record: dict[str, Any]) -> dict[str, Any]:
    timeline = (
        (record.get("page_state") or {}).get("navigation_timeline") or {}
    )
    events = [
        item for item in (timeline.get("events") or [])
        if isinstance(item, dict)
    ]
    return {
        "event_count": len(events),
        "truncated": bool(timeline.get("truncated")),
        "request_failed_count": sum(
            item.get("kind") == "document-request-failed"
            for item in events
        ),
        "response_count": sum(
            item.get("kind") == "document-response"
            for item in events
        ),
        "commit_count": sum(
            item.get("kind") == "document-commit"
            for item in events
        ),
    }


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
