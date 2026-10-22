"""Run authored holdout cases for the rendered frame boundary comparator."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure.frame_boundary import (
    RENDERED_FRAME_BOUNDARY_SCOPE,
    compare_rendered_frame_boundaries,
)


DEFAULT_FIXTURE = (
    _ROOT
    / "tests"
    / "fixtures"
    / "p1"
    / "frame_boundary_holdout.json"
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic authored frame-boundary holdouts."
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--out",
        type=Path,
        default=(
            _ROOT
            / "output"
            / "_p1_frame_boundary_holdout"
            / "result.json"
        ),
    )
    args = parser.parse_args(argv)
    result = run_frame_boundary_holdout(args.fixture)
    payload = {
        "schema_version": "p1-frame-boundary-holdout-result/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixture": str(args.fixture),
        **result,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "passed_count": result["summary"]["passed_count"],
        "failed_count": result["summary"]["failed_count"],
        "false_equivalence_detected": result["summary"][
            "false_equivalence_detected"
        ],
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0 if result["summary"]["failed_count"] == 0 else 1


def run_frame_boundary_holdout(fixture_path: Path) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    cases = [
        _run_case(item)
        for item in (fixture.get("cases") or [])
        if isinstance(item, dict)
    ]
    false_equivalence = any(item["false_equivalence"] for item in cases)
    payload = {
        "fixture_schema_version": fixture.get("schema_version"),
        "cases": cases,
    }
    summary = {
        "case_count": len(cases),
        "passed_count": sum(item["passed"] for item in cases),
        "failed_count": sum(not item["passed"] for item in cases),
        "false_equivalence_detected": false_equivalence,
        "page_equivalence_claimed": False,
        "content_changed_boundary_equivalent_count": sum(
            bool(item.get("content_changed"))
            and item["actual"]["comparable"]
            and item["actual"]["claims"]
            == ["rendered-frame-boundary-equivalent"]
            for item in cases
        ),
    }
    canonical = json.dumps(
        {"cases": cases, "summary": summary},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        **payload,
        "summary": summary,
        "result_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    actual = compare_rendered_frame_boundaries(
        _page_state(case.get("left") or []),
        _page_state(case.get("right") or []),
    )
    expected = case.get("expected") or {}
    reasons = set(actual["reasons"])
    checks = {
        "comparable": actual["comparable"] is expected.get("comparable"),
        "reason_includes": set(expected.get("reason_includes") or []).issubset(
            reasons
        ),
        "reason_excludes": not reasons.intersection(
            expected.get("reason_excludes") or []
        ),
        "claims": actual["claims"] == list(expected.get("claims") or []),
        "claim_scope": (
            set(actual["claims"]).issubset(
                {"rendered-frame-boundary-equivalent"}
            )
        ),
    }
    if "opaque_contents_observable" in expected:
        checks["opaque_contents_observable"] = (
            actual["opaque_contents_observable"]
            is expected["opaque_contents_observable"]
        )
    if "unobservable_count" in expected:
        checks["unobservable_count"] = (
            len(actual["unobservable"]) == int(expected["unobservable_count"])
        )
    false_equivalence = bool(
        actual["comparable"]
        and expected.get("comparable") is False
        or actual["claims"]
        and actual["claims"] != ["rendered-frame-boundary-equivalent"]
        or actual["claims"] and actual.get("opaque_contents_observable") is not False
    )
    return {
        "case_id": str(case.get("case_id") or ""),
        "description": str(case.get("description") or ""),
        "content_changed": bool(case.get("content_changed")),
        "profile_id": RENDERED_FRAME_BOUNDARY_SCOPE,
        "expected": expected,
        "actual": {
            "comparable": actual["comparable"],
            "reasons": list(actual["reasons"]),
            "claims": list(actual["claims"]),
            "identity_match_count": actual["identity_match_count"],
            "boundary_observation_complete": actual[
                "boundary_observation_complete"
            ],
            "opaque_contents_observable": actual[
                "opaque_contents_observable"
            ],
            "unobservable": list(actual["unobservable"]),
        },
        "checks": checks,
        "passed": all(checks.values()),
        "false_equivalence": false_equivalence,
    }


def _page_state(inventory: list[Any]) -> dict[str, Any]:
    return {
        "final_url": "https://example.com/host",
        "capture_stability": {"stable": True},
        "frame_inventory": inventory,
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
