"""Replay frozen D-006 asset uses through the production fusion policy."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from src.app.services.structure.asset_fusion import fuse_asset_record


def build_fusion_report(asset_report: Mapping[str, Any]) -> dict[str, Any]:
    details = asset_report.get("details") or {}
    assets = [
        dict(item)
        for item in details.get("assets") or []
        if isinstance(item, Mapping) and item.get("asset_id")
    ]
    uses = [
        dict(item)
        for item in details.get("uses") or []
        if isinstance(item, Mapping) and item.get("use_id")
    ]
    use_ids = [str(item.get("use_id")) for item in uses]
    if len(use_ids) != len(set(use_ids)):
        raise ValueError("D-006 asset report contains duplicate use IDs")
    asset_map = {str(item["asset_id"]): item for item in assets}
    generated_map = _generated_candidates_map(asset_report)
    decisions: list[dict[str, Any]] = []
    for use in uses:
        asset_id = str(use.get("asset_id") or "")
        asset = asset_map.get(asset_id, {})
        record = {
            "asset_id": asset_id,
            "source_identity": dict(asset.get("source_identity") or {}),
            "display_payload": dict(use.get("display_payload") or {}),
            "replacement": dict(asset.get("replacement") or {}),
            "missing": dict(use.get("missing") or {}),
            "use": {
                key: use.get(key)
                for key in ("use_id", "node_index", "source_kind", "display_box")
            },
        }
        decisions.append(
            fuse_asset_record(
                record,
                generated_candidates=generated_map.get(str(use.get("use_id")), ()),
            )
        )

    source_counts = Counter()
    source_tier_counts = Counter()
    display_counts = Counter()
    status_counts = Counter()
    chain_counts = Counter()
    candidate_kind_counts = Counter()
    candidate_status_counts = Counter()
    generated_requested_uses = 0
    generated_selected = 0
    generated_rejected = 0
    generated_blocked = 0
    captured_over_generated = 0
    for decision in decisions:
        identity = decision.get("identity") or {}
        display = decision.get("display") or {}
        source_selected = str(identity.get("selected") or "unknown")
        if source_selected == "verified-source":
            source_counts["verified_source_uses"] += 1
        else:
            source_counts[f"{source_selected.replace('-', '_')}_uses"] += 1
        source_tier_counts[str(identity.get("source_tier") or "none")] += 1
        display_selected = str(display.get("selected") or "missing")
        display_counts[f"{display_selected.replace('-', '_')}_uses"] += 1
        status_counts[str(decision.get("status") or "unknown")] += 1
        chain_counts[">".join(decision.get("fallback_chain") or [])] += 1
        for candidate in decision.get("candidates") or []:
            candidate_kind_counts[str(candidate.get("kind") or "unknown")] += 1
            candidate_status_counts[str(candidate.get("status") or "unknown")] += 1
            if candidate.get("kind") == "generated-approximation":
                if candidate.get("status") == "selected":
                    generated_selected += 1
                elif candidate.get("status") == "blocked":
                    generated_blocked += 1
                elif candidate.get("status") == "rejected":
                    generated_rejected += 1
                if candidate.get("reason") == "higher-priority-capture-available":
                    captured_over_generated += 1
        if generated_map.get(str(decision.get("use_id"))):
            generated_requested_uses += 1

    screenshot_uses = display_counts.get("screenshot_crop_uses", 0)
    missing_display_uses = display_counts.get("missing_uses", 0)
    generated_display_uses = display_counts.get("generated_approximation_uses", 0)
    use_count = len(uses)
    decision_count = len(decisions)
    return {
        "schema_version": "dom-strategy-fusion-report/1.0",
        "status": "partial",
        "corpus_id": asset_report.get("corpus_id"),
        "corpus_sha256": asset_report.get("corpus_sha256"),
        "thresholds_sha256": asset_report.get("thresholds_sha256"),
        "use_count": use_count,
        "decision_count": decision_count,
        "all_uses_accounted": use_count == decision_count,
        "source_identity": {
            "verified_source_uses": source_counts.get("verified_source_uses", 0),
            "reference_only_uses": source_counts.get("reference_only_uses", 0),
            "unavailable_uses": source_counts.get("unavailable_uses", 0),
            "missing_uses": source_counts.get("missing_uses", 0),
            "blocked_incomplete_identity_uses": source_counts.get(
                "blocked_incomplete_identity_uses", 0
            ),
            "tier_counts": dict(sorted(source_tier_counts.items())),
        },
        "display_payload": {
            "screenshot_crop_uses": screenshot_uses,
            "generated_approximation_uses": generated_display_uses,
            "missing_display_uses": missing_display_uses,
        },
        "generated_approximation": {
            "requested_uses": generated_requested_uses,
            "selected_uses": generated_selected,
            "rejected_candidates": generated_rejected,
            "blocked_candidates": generated_blocked,
            "original_uses": 0,
            "replaceable_uses": 0,
        },
        "fallback": {
            "screenshot_capture_uses": screenshot_uses,
            "generated_fallback_uses": generated_display_uses,
            "missing_display_uses": missing_display_uses,
            "captured_over_generated_candidates": captured_over_generated,
            "chain_counts": dict(sorted(chain_counts.items())),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "candidates": {
            "kind_counts": dict(sorted(candidate_kind_counts.items())),
            "status_counts": dict(sorted(candidate_status_counts.items())),
        },
        "decisions": decisions,
        "figma_runtime": "not-evaluated",
        "composite_score_used": False,
        "non_claims": [
            "This report replays the frozen D-006 contract without network access.",
            "Generated display candidates are never original or replaceable.",
            "No real Figma write/readback is performed.",
            "No candidate is synthesized by this report.",
        ],
    }


def _generated_candidates_map(
    asset_report: Mapping[str, Any],
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    value = asset_report.get("generated_candidates")
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for use_id, candidates in value.items():
        if not isinstance(candidates, list):
            continue
        result[str(use_id)] = tuple(
            candidate for candidate in candidates if isinstance(candidate, Mapping)
        )
    return result
