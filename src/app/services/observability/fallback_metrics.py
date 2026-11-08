"""Fallback decision evidence that is emitted before design or write work."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def build_fallback_observation(
    *,
    requested_route: str,
    selected_route: str | None,
    attempts: Sequence[Mapping[str, Any]],
    grounding_report: Mapping[str, Any] | None = None,
    write_before_decision: bool = False,
) -> dict[str, Any]:
    unavailable = next(
        (
            dict(attempt)
            for attempt in attempts
            if attempt.get("strategy") == "grounding"
            and attempt.get("status") == "unavailable"
        ),
        None,
    )
    report = dict(grounding_report or {})
    trigger = (
        str(unavailable.get("reason") or "grounding-service-unavailable")
        if unavailable is not None
        else None
    )
    fallback_triggered = trigger is not None
    selection_accepted = bool(fallback_triggered and selected_route == "cv")
    usage = report.get("usage")
    token_usage = dict(usage) if isinstance(usage, Mapping) else {}
    latency = report.get("latency_ms")
    return {
        "schema_version": "fallback-observability/1.0",
        "requested_route": requested_route,
        "selected_route": selected_route,
        "attempts": [dict(attempt) for attempt in attempts],
        "grounding_unavailable": fallback_triggered,
        "fallback_triggered": fallback_triggered,
        "fallback_trigger": trigger,
        "fallback_trigger_stage": "before-design-and-write",
        "fallback_selection_accepted": selection_accepted,
        "fallback_quality_acceptance": "not-evaluated",
        "fallback_latency_ms": (
            round(float(latency), 3) if isinstance(latency, (int, float)) else None
        ),
        "token_usage": token_usage,
        "estimated_cost_usd": None,
        "cost_status": "unavailable-no-pricing-table",
        "write_before_decision": bool(write_before_decision),
        "write_before_block_total": 1 if write_before_decision else 0,
        "cache_status": report.get("cache_status"),
        "attempt_count": report.get("attempt_count"),
        "retry_count": report.get("retry_count"),
        "limitations": [
            "Selection acceptance is not product or visual quality acceptance.",
            "Cost remains unknown until a versioned pricing table is configured.",
            "CV fallback quality is not generalized from this routing observation.",
        ],
    }
