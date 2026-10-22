"""Aggregate the seven real Chromium/WebKit pair summaries into one matrix."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.p1_dual_browser_capture import _classify_failure
from src.app.services.structure.capture_outcome import classify_capture_outcome


DEFAULT_RUNS = {
    "P1-S01-R1": "dual-P1-S01-R1-outcome-round1",
    "P1-S02-R1": "dual-P1-S02-R1-outcome-round1",
    "P1-S03-R1": "dual-P1-S03-R1-outcome-round1",
    "P1-S04-R1": "dual-P1-S04-R1-outcome-round1",
    "P1-S05-R1": "dual-P1-S05-R1-outcome-round1",
    "P1-S06-R1": "dual-P1-S06-R1-outcome-round1",
    "P1-S07-R1": "dual-P1-S07-R1-outcome-round1",
}
CONDITION_PROBES = {
    "P1-S07-R1": (
        _ROOT
        / "output"
        / "_p1_engine_conditions"
        / "s07_condition_probe.json"
    ),
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate real Chromium/WebKit pair summaries."
    )
    parser.add_argument(
        "--sidecar-root",
        type=Path,
        default=_ROOT / "output" / "_p1_dual_sidecars",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=(
            _ROOT
            / "output"
            / "_p1_dual_sidecars"
            / "real_pair_matrix_outcome_round1.json"
        ),
    )
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        metavar="SAMPLE_ID=RUN_ID",
        help="Override one default sample-to-run mapping.",
    )
    args = parser.parse_args(argv)
    runs = dict(DEFAULT_RUNS)
    for override in args.run:
        sample_id, separator, run_id = str(override).partition("=")
        if not separator or not sample_id or not run_id:
            raise SystemExit(f"invalid --run value: {override!r}")
        runs[sample_id] = run_id
    matrix = build_matrix(args.sidecar_root, runs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(matrix, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "strict_count": matrix["strict_count"],
        "content_count": matrix["content_count"],
        "blocked_count": matrix["blocked_count"],
        "equivalent_count": matrix["equivalent_count"],
        "different_count": matrix["different_count"],
        "inconclusive_count": matrix["inconclusive_count"],
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0


def build_matrix(
    sidecar_root: Path,
    runs: dict[str, str],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for sample_id in sorted(runs):
        run_id = runs[sample_id]
        summary_path = sidecar_root / run_id / "pair_summary.json"
        if not summary_path.is_file():
            raise FileNotFoundError(f"pair summary is missing: {summary_path}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        engines: dict[str, dict[str, Any]] = {}
        for engine, record in (summary.get("engines") or {}).items():
            if not isinstance(record, dict):
                continue
            engines[engine] = {
                "capture_dir": record.get("capture_dir"),
                "sidecar_dir": record.get("sidecar_dir"),
                "status": record.get("status"),
                "navigation": record.get("navigation") or {},
                "frame_summary": record.get("frame_summary") or {},
                "page_state": record.get("page_state") or {},
            }
        attempts = []
        for item in summary.get("state_attempts") or []:
            if not isinstance(item, dict):
                continue
            attempt_outcome = classify_capture_outcome(
                item.get("state_gate") or {},
                item.get("engines") or {},
                item.get("text_delta") or {},
                content_comparable=bool(item.get("content_comparable")),
            )
            attempt = {
                "attempt": item.get("attempt"),
                "legacy_scope": item.get("comparison_scope"),
                **attempt_outcome,
                "failure_classification": _classify_failure(
                    item.get("state_gate") or {},
                    item.get("engines") or {},
                    item.get("text_delta") or {},
                ),
                "reasons": list((item.get("state_gate") or {}).get("reasons") or []),
            }
            attempts.append(attempt)
        failure_classification = _classify_failure(
            summary.get("state_gate") or {},
            engines,
            summary.get("text_delta") or {},
        )
        outcome = classify_capture_outcome(
            summary.get("state_gate") or {},
            engines,
            summary.get("text_delta") or {},
            content_comparable=bool(summary.get("content_comparable")),
        )
        rows.append({
            "sample_id": sample_id,
            "run": run_id,
            "pair_summary": str(summary_path),
            "comparison_scope": summary.get("comparison_scope"),
            "execution_status": outcome["execution_status"],
            "execution_reasons": outcome["execution_reasons"],
            "comparison_result": outcome["comparison_result"],
            "comparison_reasons": outcome["comparison_reasons"],
            "limitations": outcome["limitations"],
            "outcome": outcome,
            "failure_classification": failure_classification,
            "selected_attempt": summary.get("selected_state_attempt"),
            "selection_rule": summary.get("selection_rule"),
            "attempt_scopes": attempts,
            "state_gate": summary.get("state_gate") or {},
            "text_delta": summary.get("text_delta") or {},
            "text_alignment": summary.get("text_alignment") or {},
            "geometry": summary.get("geometry") or {},
            "engines": engines,
            "condition_probe": _condition_probe_summary(sample_id),
        })
    strict_count = sum(row["comparison_scope"] == "strict" for row in rows)
    content_count = sum(
        row["comparison_scope"] in {"strict", "content"} for row in rows
    )
    return {
        "schema_version": "p1-dual-real-state-matrix/1.2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gate_contract": matrix_gate_contract(),
        "sample_count": len(rows),
        "strict_count": strict_count,
        "content_count": content_count,
        "blocked_count": sum(
            row["comparison_scope"] == "blocked" for row in rows
        ),
        "equivalent_count": sum(
            row["comparison_result"] == "equivalent" for row in rows
        ),
        "different_count": sum(
            row["comparison_result"] == "different" for row in rows
        ),
        "inconclusive_count": sum(
            row["comparison_result"] == "inconclusive" for row in rows
        ),
        "note": (
            "The first execution-ready pair is accepted without selecting a later "
            "easier round. strict/content/blocked remains the legacy scope summary; "
            "live strict/content counts are diagnostic observations, not the current "
            "product hard gate. The product target is canonical-output-fidelity under "
            "a fixed Chromium environment. Content is text-only, never whole-page "
            "equivalence."
        ),
        "rows": rows,
    }


def matrix_gate_contract() -> dict[str, Any]:
    return {
        "canonical_engine": "chromium",
        "product_primary_goal": "canonical-output-fidelity",
        "legacy_full_visible_strict": {
            "definition_frozen": True,
            "history_preserved": True,
            "live_count_role": "diagnostic-observation",
            "live_count_hard_gate": False,
            "product_primary_metric": False,
        },
        "controlled_legacy_strict": {
            "hard_regression_gate": True,
            "status": "planned",
        },
        "cross_browser_auxiliary_scope": "rendered-frame-boundary-strict/1.0",
        "first_party_role": "diagnostic-slice",
    }


def _condition_probe_summary(sample_id: str) -> dict[str, Any] | None:
    path = CONDITION_PROBES.get(sample_id)
    if path is None or not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary") or {}
    return {
        "path": str(path),
        "confirmed_root_cause": bool(summary.get("confirmed_root_cause")),
        "attribution_candidates": list(
            summary.get("attribution_candidates") or []
        ),
        "targets": summary.get("targets") or {},
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
