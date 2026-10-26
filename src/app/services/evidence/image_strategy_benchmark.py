"""Independent three-way image strategy comparison and hybrid decision gates."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image


COMPARISON_SCHEMA_VERSION = "image-strategy-comparison/1.0"
REQUIRED_STRATEGIES = (
    "grounding-only",
    "cv-fallback",
    "grounding-cv-hybrid",
)


def plan_strategy_attempts(
    strategy: str,
    *,
    grounding_available: bool,
) -> dict[str, Any]:
    """Declare ordered strategy attempts without inferring availability silently."""
    if strategy == "grounding-only":
        if not grounding_available:
            raise ValueError("Grounding-only requires an available Grounding VLM")
        attempts = [{"strategy": "grounding", "status": "selected"}]
        selected = "grounding"
        fallback_used = False
    elif strategy == "cv-fallback":
        if grounding_available:
            raise ValueError(
                "cv-fallback benchmark requires verified Grounding unavailability"
            )
        attempts = [
            {
                "strategy": "grounding",
                "status": "unavailable",
                "reason": "grounding-config-missing",
            },
            {"strategy": "cv", "status": "selected"},
        ]
        selected = "cv"
        fallback_used = True
    elif strategy == "grounding-cv-hybrid":
        if not grounding_available:
            raise ValueError("hybrid benchmark requires an available Grounding VLM")
        attempts = [
            {"strategy": "grounding", "status": "selected"},
            {"strategy": "cv", "status": "supplemented"},
        ]
        selected = "hybrid"
        fallback_used = False
    else:
        raise ValueError(f"unknown benchmark strategy: {strategy}")
    return {
        "requested": "auto",
        "selected": selected,
        "attempts": attempts,
        "fallback_used": fallback_used,
        "policy": "grounding-default-cv-only-when-unavailable",
        "hidden_route_switch": False,
    }


def describe_grounding_execution(
    strategy: str,
    *,
    shared_graph_available: bool,
) -> dict[str, Any]:
    """Separate logical Grounding cost from provider replay in the benchmark."""
    if strategy == "cv-fallback":
        return {
            "logical_grounding_calls": 0,
            "provider_grounding_calls": 0,
            "grounding_replay": False,
        }
    if strategy not in {"grounding-only", "grounding-cv-hybrid"}:
        raise ValueError(f"unknown benchmark strategy: {strategy}")
    return {
        "logical_grounding_calls": 1,
        "provider_grounding_calls": 0 if shared_graph_available else 1,
        "grounding_replay": shared_graph_available,
    }


def describe_cv_execution(
    strategy: str,
    *,
    shared_graph_available: bool,
) -> dict[str, Any]:
    """Separate logical CV cost from provider replay in the benchmark."""
    if strategy == "grounding-only":
        return {
            "logical_cv_executions": 0,
            "provider_cv_executions": 0,
            "cv_replay": False,
        }
    if strategy not in {"cv-fallback", "grounding-cv-hybrid"}:
        raise ValueError(f"unknown benchmark strategy: {strategy}")
    return {
        "logical_cv_executions": 1,
        "provider_cv_executions": 0 if shared_graph_available else 1,
        "cv_replay": shared_graph_available,
    }


def validate_benchmark_manifest(
    manifest: Mapping[str, Any],
    *,
    root: str | Path,
) -> dict[str, Any]:
    """Fail closed when corpus hashes, dimensions or strategy scope drift."""
    value = copy.deepcopy(dict(manifest))
    if value.get("schema_version") != "image-strategy-benchmark/1.0":
        raise ValueError("unexpected benchmark manifest schema")
    if not bool(value.get("frozen")):
        raise ValueError("benchmark manifest must be frozen")
    strategies = list(value.get("strategies") or [])
    if strategies != list(REQUIRED_STRATEGIES):
        raise ValueError(
            f"benchmark strategies must be {list(REQUIRED_STRATEGIES)}, got {strategies}"
        )
    decision_policy = value.get("decision_policy") or {}
    if bool(decision_policy.get("composite_score_allowed")):
        raise ValueError("composite score is not allowed")
    base = Path(root)
    for sample in value.get("samples") or []:
        image_path = base / str(sample.get("image") or "")
        truth_path = base / str(sample.get("truth") or "")
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        if not truth_path.is_file():
            raise FileNotFoundError(truth_path)
        if _file_sha256(image_path) != sample.get("image_sha256"):
            raise ValueError(f"image SHA-256 drift: {image_path}")
        if _file_sha256(truth_path) != sample.get("truth_sha256"):
            raise ValueError(f"truth SHA-256 drift: {truth_path}")
        with Image.open(image_path) as image:
            if list(image.size) != list(sample.get("image_size") or []):
                raise ValueError(f"image size drift: {image_path}")
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        if truth.get("sample_id") != sample.get("sample_id"):
            raise ValueError(f"truth sample_id drift: {truth_path}")
        if len(truth.get("critical_texts") or []) != int(
            sample.get("critical_text_count") or 0
        ):
            raise ValueError(f"critical text count drift: {truth_path}")
    return value


def build_strategy_row(
    *,
    strategy: str,
    acceptance: Mapping[str, Any],
    readback_tree: Mapping[str, Any],
    pipeline: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    """Project acceptance and runtime artifacts into independent benchmark fields."""
    nodes = list(_iter_nodes(readback_tree))
    text_nodes = [node for node in nodes if node.get("type") == "TEXT"]
    image_nodes = [
        node
        for node in nodes
        if any(
            isinstance(fill, Mapping) and fill.get("type") == "IMAGE"
            for fill in node.get("fills") or []
        )
    ]
    critical = acceptance.get("critical_text") or {}
    dimensions = acceptance.get("dimensions") or {}
    visual = acceptance.get("visual") or {}
    image_ir = pipeline.get("image_ir") or {}
    counts = image_ir.get("counts") or {}
    provenance_in = pipeline.get("provenance") or {}
    attempts = list(provenance_in.get("attempts") or [])
    assets = [
        asset for asset in image_ir.get("assets") or [] if isinstance(asset, Mapping)
    ]
    reference_only_count = sum(bool(asset.get("reference_only")) for asset in assets)
    asset_claims = acceptance.get("asset_claims") or {}
    return {
        "strategy": strategy,
        "figma_runtime": acceptance.get("figma_runtime"),
        "critical_text": {
            "matched": int(critical.get("matched_count") or 0),
            "required": int(critical.get("required_count") or 0),
            "status": critical.get("status"),
        },
        "native_text": {
            "node_count": len(text_nodes),
            "edit_restore": (dimensions.get("edit") or {}).get("status"),
        },
        "asset": {
            "image_node_count": len(image_nodes),
            "reference_only_count": reference_only_count,
            "replace_restore": (dimensions.get("asset") or {}).get("status"),
            "original_claim": bool(asset_claims.get("original_asset")),
        },
        "structure": {
            "node_count": int(counts.get("nodes") or 0),
            "text_candidates": int(counts.get("text_candidates") or 0),
            "image_candidates": int(counts.get("image_candidates") or 0),
            "ambiguity_count": int(provenance_in.get("ambiguity_count") or 0),
            "duplicate_suppressed_count": int(
                provenance_in.get("duplicate_suppressed_count") or 0
            ),
            "status": (dimensions.get("structure") or {}).get("status"),
        },
        "visual": {
            "size_match": bool(visual.get("size_match")),
            "within30_pct": float(visual.get("within30_pct") or 0.0),
            "mean_channel_delta": float(visual.get("mean") or 0.0),
            "ink_mean_delta": float(visual.get("ink_mean") or 0.0),
            "over30_pct": float(visual.get("over30_pct") or 0.0),
        },
        "runtime": dict(runtime),
        "provenance": {
            "requested_route": provenance_in.get("requested_route"),
            "ordered_attempts": bool(attempts),
            "selected_strategy": bool(pipeline.get("route")),
            "all_candidate_sources": bool(
                provenance_in.get("all_candidate_sources", True)
            ),
            "ambiguity_retained": bool(provenance_in.get("ambiguity_retained", True)),
            "hidden_route_switch": bool(provenance_in.get("hidden_route_switch")),
        },
        "non_claims": {
            "original_asset": bool(asset_claims.get("original_asset")),
            "adaptive_flow": bool(
                provenance_in.get("adaptive_flow_claim")
                or (pipeline.get("design") or {}).get("_meta", {}).get("adaptive_flow")
            ),
        },
    }


def evaluate_hybrid_decision(
    rows: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate every adoption gate independently without a composite score."""
    by_strategy = {str(row.get("strategy") or ""): row for row in rows}
    missing = [name for name in REQUIRED_STRATEGIES if name not in by_strategy]
    if missing:
        raise ValueError(f"comparison is missing strategies: {missing}")
    baseline = by_strategy["grounding-only"]
    hybrid = by_strategy["grounding-cv-hybrid"]

    gates = {
        "figma-runtime": _gate(
            all(row.get("figma_runtime") == "observed" for row in by_strategy.values()),
            observed={
                name: row.get("figma_runtime") for name, row in by_strategy.items()
            },
            expected="all strategies observed real Figma runtime",
        ),
        "critical-text": _critical_text_gate(baseline, hybrid),
        "native-text": _native_text_gate(baseline, hybrid),
        "asset-editability": _asset_gate(baseline, hybrid),
        "independent-improvement": _improvement_gate(baseline, hybrid),
        "visual-quality": _visual_gate(baseline, hybrid, policy),
        "provenance": _provenance_gate(hybrid),
        "routing-safety": _routing_gate(hybrid),
        "latency-bound": _latency_gate(baseline, hybrid, policy),
        "cost-bound": _cost_gate(hybrid, policy),
        "non-claims": _non_claim_gate(hybrid),
    }
    reasons = [name for name, gate in gates.items() if not gate["pass"]]
    return {
        "schema_version": "image-hybrid-decision/1.0",
        "decision": "adopt-hybrid" if not reasons else "reject-hybrid",
        "reasons": reasons,
        "gates": gates,
        "no_composite_score": True,
        "adopt_only_if_all_gates_pass": True,
        "default_on_reject": "grounding-default-cv-fallback-only",
    }


def build_strategy_comparison(
    rows: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    *,
    corpus_id: str,
) -> dict[str, Any]:
    """Return per-strategy rows plus the explicit hybrid decision."""
    normalized = [dict(row) for row in rows]
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "corpus_id": corpus_id,
        "policy": dict(policy),
        "strategies": normalized,
        "decision": evaluate_hybrid_decision(normalized, policy),
        "composite_score_used": False,
        "limitations": [
            "Per-strategy dimensions are reported independently.",
            "A decision on one owned sample does not establish general quality.",
        ],
    }


def _critical_text_gate(
    baseline: Mapping[str, Any],
    hybrid: Mapping[str, Any],
) -> dict[str, Any]:
    base = baseline.get("critical_text") or {}
    candidate = hybrid.get("critical_text") or {}
    observed = {
        "baseline_matched": base.get("matched"),
        "hybrid_matched": candidate.get("matched"),
        "required": candidate.get("required"),
        "status": candidate.get("status"),
    }
    passed = (
        candidate.get("status") == "pass"
        and int(candidate.get("matched") or 0) >= int(candidate.get("required") or 1)
        and int(candidate.get("matched") or 0) >= int(base.get("matched") or 0)
        and int(candidate.get("required") or 0) == int(base.get("required") or 0)
    )
    return _gate(passed, observed=observed, expected="no critical-text regression")


def _native_text_gate(
    baseline: Mapping[str, Any],
    hybrid: Mapping[str, Any],
) -> dict[str, Any]:
    base = baseline.get("native_text") or {}
    candidate = hybrid.get("native_text") or {}
    observed = {
        "baseline_node_count": base.get("node_count"),
        "hybrid_node_count": candidate.get("node_count"),
        "edit_restore": candidate.get("edit_restore"),
    }
    passed = candidate.get("edit_restore") == "pass" and int(
        candidate.get("node_count") or 0
    ) >= int(base.get("node_count") or 1)
    return _gate(passed, observed=observed, expected="native text remains editable")


def _asset_gate(
    baseline: Mapping[str, Any],
    hybrid: Mapping[str, Any],
) -> dict[str, Any]:
    base = baseline.get("asset") or {}
    candidate = hybrid.get("asset") or {}
    observed = {
        "baseline_image_nodes": base.get("image_node_count"),
        "hybrid_image_nodes": candidate.get("image_node_count"),
        "reference_only_count": candidate.get("reference_only_count"),
        "replace_restore": candidate.get("replace_restore"),
        "original_claim": candidate.get("original_claim"),
    }
    passed = (
        candidate.get("replace_restore") == "pass"
        and not bool(candidate.get("original_claim"))
        and int(candidate.get("image_node_count") or 0)
        >= int(base.get("image_node_count") or 0)
        and int(candidate.get("reference_only_count") or 0)
        >= int(candidate.get("image_node_count") or 0)
    )
    return _gate(
        passed,
        observed=observed,
        expected="reference-only asset replacement remains passing",
    )


def _improvement_gate(
    baseline: Mapping[str, Any],
    hybrid: Mapping[str, Any],
) -> dict[str, Any]:
    base = baseline.get("structure") or {}
    candidate = hybrid.get("structure") or {}
    improvements = {
        "text_candidates": int(candidate.get("text_candidates") or 0)
        > int(base.get("text_candidates") or 0),
        "image_candidates": int(candidate.get("image_candidates") or 0)
        > int(base.get("image_candidates") or 0),
        "node_count": int(candidate.get("node_count") or 0)
        > int(base.get("node_count") or 0),
    }
    return _gate(
        any(improvements.values()),
        observed={
            "baseline": dict(base),
            "hybrid": dict(candidate),
            "improvements": improvements,
        },
        expected="at least one independent structure or editability improvement",
    )


def _visual_gate(
    baseline: Mapping[str, Any],
    hybrid: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    base = baseline.get("visual") or {}
    candidate = hybrid.get("visual") or {}
    threshold = float(policy.get("visual_within30_min_pct") or 90.0)
    base_score = float(base.get("within30_pct") or 0.0)
    hybrid_score = float(candidate.get("within30_pct") or 0.0)
    passed = (
        bool(candidate.get("size_match"))
        and hybrid_score >= threshold
        and hybrid_score >= base_score
    )
    return _gate(
        passed,
        observed={
            "baseline_within30_pct": base_score,
            "hybrid_within30_pct": hybrid_score,
            "threshold_pct": threshold,
            "size_match": candidate.get("size_match"),
            "mean_channel_delta": candidate.get("mean_channel_delta"),
            "ink_mean_delta": candidate.get("ink_mean_delta"),
            "over30_pct": candidate.get("over30_pct"),
        },
        expected="visual score does not decrease and stays above threshold",
    )


def _provenance_gate(hybrid: Mapping[str, Any]) -> dict[str, Any]:
    provenance = hybrid.get("provenance") or {}
    required = (
        "requested_route",
        "ordered_attempts",
        "selected_strategy",
        "all_candidate_sources",
        "ambiguity_retained",
    )
    passed = all(provenance.get(name) for name in required)
    return _gate(
        passed,
        observed={name: provenance.get(name) for name in required},
        expected="request, attempts, sources and ambiguity are retained",
    )


def _routing_gate(hybrid: Mapping[str, Any]) -> dict[str, Any]:
    provenance = hybrid.get("provenance") or {}
    passed = not bool(provenance.get("hidden_route_switch"))
    return _gate(
        passed,
        observed={
            "hidden_route_switch": provenance.get("hidden_route_switch"),
            "requested_route": provenance.get("requested_route"),
        },
        expected="no hidden route switch",
    )


def _latency_gate(
    baseline: Mapping[str, Any],
    hybrid: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    base_runtime = baseline.get("runtime") or {}
    runtime = hybrid.get("runtime") or {}
    wall_time = float(runtime.get("wall_time_seconds") or float("inf"))
    base_wall_time = float(base_runtime.get("wall_time_seconds") or float("inf"))
    max_seconds = float(policy.get("hybrid_wall_time_max_seconds") or 180.0)
    max_ratio = float(policy.get("hybrid_max_grounding_ratio") or 2.0)
    passed = wall_time <= max_seconds and wall_time <= base_wall_time * max_ratio
    return _gate(
        passed,
        observed={
            "baseline_seconds": base_wall_time,
            "hybrid_seconds": wall_time,
            "max_seconds": max_seconds,
            "max_grounding_ratio": max_ratio,
        },
        expected="latency is inside the frozen absolute and relative bounds",
    )


def _cost_gate(
    hybrid: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    runtime = hybrid.get("runtime") or {}
    calls = int(runtime.get("grounding_vlm_calls") or 0)
    max_calls = int(policy.get("hybrid_grounding_calls_max") or 1)
    telemetry = str(runtime.get("cost_telemetry_status") or "")
    passed = calls <= max_calls and telemetry in {
        "observed",
        "bounded-by-request-count",
    }
    return _gate(
        passed,
        observed={
            "grounding_vlm_calls": calls,
            "max_calls": max_calls,
            "cost_telemetry_status": telemetry,
        },
        expected="Grounding cost is observed or bounded by request count",
    )


def _non_claim_gate(hybrid: Mapping[str, Any]) -> dict[str, Any]:
    claims = hybrid.get("non_claims") or {}
    passed = not bool(claims.get("original_asset")) and not bool(
        claims.get("adaptive_flow")
    )
    return _gate(
        passed,
        observed={
            "original_asset": claims.get("original_asset"),
            "adaptive_flow": claims.get("adaptive_flow"),
        },
        expected="no original-asset or adaptive-flow claim",
    )


def _gate(
    passed: bool,
    *,
    observed: Any,
    expected: Any,
) -> dict[str, Any]:
    return {
        "pass": bool(passed),
        "observed": observed,
        "expected": expected,
    }


def _iter_nodes(root: Mapping[str, Any]):
    if not isinstance(root, Mapping):
        return
    yield root
    for child in root.get("children") or []:
        if isinstance(child, Mapping):
            yield from _iter_nodes(child)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
