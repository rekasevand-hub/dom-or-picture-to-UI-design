"""Execution and comparison outcome contract for paired captures."""
from __future__ import annotations

from typing import Any


OUTCOME_SCHEMA = "p1-capture-outcome/1.0"
STRICT_SCOPE = "rendered-frame-state-strict/1.0"
BOUNDARY_SCOPE = "rendered-frame-boundary-strict/1.0"


def classify_capture_outcome(
    state_gate: dict[str, Any],
    engines: dict[str, dict[str, Any]],
    delta: dict[str, Any] | None,
    *,
    content_comparable: bool,
    profile_id: str = STRICT_SCOPE,
) -> dict[str, Any]:
    """Separate capture execution from the eventual comparison result."""
    execution_reasons: list[str] = []
    limitations: list[str] = []
    records = [item for item in engines.values() if isinstance(item, dict)]

    if (
        not records
        or any(item.get("status") != "ok" for item in records)
        or "capture-artifacts-missing" in (state_gate.get("reasons") or [])
    ):
        execution_reasons.append("capture-failed")

    navigation_failed = any(
        (item.get("navigation") or {}).get("status")
        in {"browser-navigation-failed", "navigation-failed"}
        for item in records
    )
    if navigation_failed:
        execution_reasons.append("navigation-failed")

    state_unstable = (
        "state-unstable" in (state_gate.get("reasons") or [])
        or "frame-barrier-mismatch" in (state_gate.get("reasons") or [])
        or state_gate.get("boundary_observation_complete") is False
        or any(
            not _capture_is_stable(item.get("page_state") or {})
            for item in records
        )
    )
    if state_unstable:
        execution_reasons.append("state-unstable")

    if any(
        _positive_int((item.get("frame_summary") or {}).get("opaque_frame_count"))
        for item in records
    ):
        limitations.append("observation-opaque")
    if "frame-barrier-divergence" in (state_gate.get("reasons") or []):
        limitations.append("frame-tree-divergence-observed")

    if "capture-failed" in execution_reasons:
        execution_status = "capture-failed"
    elif "navigation-failed" in execution_reasons:
        execution_status = "navigation-failed"
    elif "state-unstable" in execution_reasons:
        execution_status = "state-unstable"
    else:
        execution_status = "ready"

    comparison_reasons = _comparison_reasons(
        state_gate,
        delta,
        execution_status=execution_status,
    )
    if execution_status != "ready":
        comparison_result = "inconclusive"
    elif state_gate.get("comparable"):
        comparison_result = "equivalent"
    else:
        comparison_result = "different"

    scope = str(profile_id or STRICT_SCOPE)
    if scope == BOUNDARY_SCOPE:
        claim = "rendered-frame-boundary-equivalent"
        limitations.append("boundary-scope-only")
        note = (
            "Equivalent means rendered frame boundaries only. URL is an observed "
            "attribute, and opaque-frame internals remain not observable."
        )
    else:
        claim = "rendered-frame-state-equivalent"
        note = (
            "An observed difference is different, not inconclusive. "
            "Opaque boundaries do not prove opaque-frame contents equal."
        )
    claims = [claim] if comparison_result == "equivalent" else []
    return {
        "schema_version": OUTCOME_SCHEMA,
        "scope": scope,
        "execution_status": execution_status,
        "execution_reasons": execution_reasons,
        "comparison_result": comparison_result,
        "comparison_reasons": comparison_reasons,
        "limitations": limitations,
        "claims": claims,
        "content_comparable": bool(content_comparable),
        "note": note,
    }


def _comparison_reasons(
    state_gate: dict[str, Any],
    delta: dict[str, Any] | None,
    *,
    execution_status: str,
) -> list[str]:
    reasons: list[str] = []
    gate_reasons = list(state_gate.get("reasons") or [])
    if execution_status == "navigation-failed":
        reasons.append("navigation-failed")
    if (
        "state-unstable" in gate_reasons
        or "frame-barrier-mismatch" in gate_reasons
        or state_gate.get("boundary_observation_complete") is False
    ):
        reasons.append("state-unmatched")
    if execution_status != "ready":
        return _dedupe(reasons)
    if any(
        reason in gate_reasons
        for reason in (
            "url-mismatch",
            "frame-url-observation-difference",
            "frame-src-observation-difference",
        )
    ):
        reasons.append("observed-navigation-divergence")
    if "text-mismatch" in gate_reasons:
        reasons.append("observed-content-divergence")
    if any(
        item in gate_reasons
        for item in (
            "node-count-mismatch",
            "structure-mismatch",
            "frame-inventory-mismatch",
            "frame-barrier-divergence",
            "frame-topology-difference",
            "frame-parent-chain-difference",
            "frame-host-geometry-difference",
            "frame-visibility-difference",
            "frame-sandbox-opaque-boundary-difference",
            "frame-document-generation-difference",
            "frame-navigation-phase-difference",
        )
    ):
        reasons.append("observed-structure-divergence")
    if (delta or {}).get("classification") == "dynamic-glyph":
        reasons.append("dynamic-glyph")
    return _dedupe(reasons)


def _capture_is_stable(page_state: dict[str, Any]) -> bool:
    stability = page_state.get("capture_stability")
    return isinstance(stability, dict) and stability.get("stable") is True


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
