"""L1/L2 layout classification and fixed-coordinate fallback decisions."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from src.app.services.rendering.layout_infer import (
    infer_container,
    uniform_gap,
)


REPORT_SCHEMA = "dom-layout-quality/1.0"


def evaluate_layout_tree(
    dom: Sequence[Mapping[str, Any]],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    del thresholds  # frozen acceptance tolerance is applied by L3/reporting.
    children_table = _children_table(dom)
    decisions: list[dict[str, Any]] = []
    for index, node in enumerate(dom):
        child_indexes = children_table[index]
        if len(child_indexes) < 2:
            continue
        children = [dom[child] for child in child_indexes]
        parent = _parent_of(dom, index)
        inferred = infer_container(dict(node), list(children), parent)
        decisions.append(_decision(index, node, children, inferred))
    return {
        "schema_version": REPORT_SCHEMA,
        "composite_score_used": False,
        "container_count": len(decisions),
        "levels": _summarize_levels(decisions),
        "fallback_reasons": dict(
            sorted(
                Counter(
                    item["fixed_fallback"]["reason"]
                    for item in decisions
                    if item["fixed_fallback"]["required"]
                ).items()
            )
        ),
        "decisions": decisions,
    }


def classify_fallback_reason(detail: Any) -> str | None:
    value = str(detail or "").lower()
    mappings = (
        ("grid-unsupported", "grid"),
        ("wrap-unsupported", "wrap"),
        ("order-not-zero", "order"),
        ("reverse-unsupported", "reverse"),
        ("float-child", "float"),
        ("inline-flow-child", "inline-flow"),
        ("content-overflows-frame", "content-overflow"),
        ("non-uniform-gap", "non-uniform-gap"),
        ("geometry-mismatch", "geometry-mismatch"),
        ("display-not-layout-container", "unsupported-display"),
        ("only-absolute-children", "only-absolute-children"),
        ("no-children", "no-children"),
        ("geometry-not-a-line", "geometry-not-line"),
    )
    for needle, reason in mappings:
        if needle in value:
            return reason
    return "container-bail" if value else None


def _decision(
    index: int,
    node: Mapping[str, Any],
    children: Sequence[Mapping[str, Any]],
    inferred: Mapping[str, Any],
) -> dict[str, Any]:
    layout = inferred.get("layout")
    detail = inferred.get("detail") or inferred.get("bail")
    flow_count, absolute_count = _flow_counts(children)
    if isinstance(layout, Mapping):
        source = str(layout.get("source") or "unknown")
        l2_pass, l2_reason = _l2_static_replay(node, children, layout)
        flow_children = [
            child
            for child in children
            if str(child.get("position") or "static") not in {"absolute", "fixed"}
        ]
        l3 = (
            simulate_l3_local_growth(
                layout,
                _relative_rects(node, flow_children),
                growth_px=24.0,
            )
            if l2_pass
            else {
                "status": "not-evaluated",
                "reason": "l2-not-replayable",
                "parent_propagation": "not-evaluated",
            }
        )
        fixed_required = False
        fallback_reason = None
    else:
        source = None
        l2_pass = False
        l2_reason = "not-l1"
        l3 = {
            "status": "not-evaluated",
            "reason": "not-l1",
            "parent_propagation": "not-evaluated",
        }
        fixed_required = True
        fallback_reason = classify_fallback_reason(detail) or "container-bail"
    return {
        "dom_index": index,
        "tag": str(node.get("tag") or ""),
        "display": str(node.get("display") or "block"),
        "child_count": len(children),
        "flow_child_count": flow_count,
        "absolute_child_count": absolute_count,
        "l1": {
            "pass": isinstance(layout, Mapping),
            "mode": layout.get("mode") if isinstance(layout, Mapping) else None,
            "source": source,
            "css_bail": inferred.get("css_bail"),
            "detail": detail,
        },
        "l2": {
            "pass": l2_pass,
            "status": "static-replay-pass" if l2_pass else "not-replayable",
            "reason": l2_reason,
        },
        "l3": l3,
        "fixed_fallback": {
            "required": fixed_required,
            "reason": fallback_reason,
            "action": "fixed-coordinate" if fixed_required else None,
        },
    }


def simulate_l3_local_growth(
    layout: Mapping[str, Any] | None,
    child_rects: Sequence[Sequence[float]],
    *,
    growth_px: float,
    tolerance_px: float = 2.0,
) -> dict[str, Any]:
    if (
        not isinstance(layout, Mapping)
        or layout.get("source") != "css"
        or layout.get("mode") not in {"VERTICAL", "HORIZONTAL"}
        or len(child_rects) < 2
    ):
        return {
            "status": "not-evaluated",
            "reason": "requires-css-l2-candidate-with-two-children",
            "parent_propagation": "not-evaluated",
            "figma_runtime": "not-executed",
        }
    if str(layout.get("primaryAlign") or "MIN") != "MIN":
        return {
            "status": "not-evaluated",
            "reason": "non-min-primary-align",
            "parent_propagation": "not-evaluated",
            "figma_runtime": "not-executed",
        }
    if str(layout.get("counterAlign") or "MIN") != "MIN":
        return {
            "status": "not-evaluated",
            "reason": "non-min-counter-align",
            "parent_propagation": "not-evaluated",
            "figma_runtime": "not-executed",
        }
    is_row = layout["mode"] == "HORIZONTAL"
    main_index = 0 if is_row else 1
    cross_index = 1 if is_row else 0
    size_index = 2 if is_row else 3
    first = [float(value) for value in child_rects[0]]
    spacing = float(layout.get("itemSpacing") or 0.0)
    cursor = first[main_index] + first[size_index] + float(growth_px) + spacing
    following_positions: list[float] = []
    expected_positions: list[float] = []
    cross_axis_unchanged = True
    max_deviation = 0.0
    for raw in child_rects[1:]:
        rect = [float(value) for value in raw]
        following_positions.append(round(cursor, 2))
        expected_positions.append(round(rect[main_index] + growth_px, 2))
        max_deviation = max(
            max_deviation,
            abs(cursor - (rect[main_index] + growth_px)),
        )
        cross_axis_unchanged = cross_axis_unchanged and (
            abs(rect[cross_index] - float(raw[cross_index])) <= tolerance_px
        )
        cursor += rect[size_index] + spacing
    return {
        "status": "contract-pass" if max_deviation <= tolerance_px else "contract-fail",
        "mutation": "grow-first-main-axis",
        "growth_px": float(growth_px),
        "following_positions": following_positions,
        "expected_positions": expected_positions,
        "max_deviation_px": max_deviation,
        "cross_axis_unchanged": cross_axis_unchanged,
        "source_behavior": "not-evaluated",
        "parent_propagation": "not-evaluated",
        "figma_runtime": "not-executed",
    }


def _l2_static_replay(
    node: Mapping[str, Any],
    children: Sequence[Mapping[str, Any]],
    layout: Mapping[str, Any],
) -> tuple[bool, str | None]:
    source = str(layout.get("source") or "")
    if source == "css":
        return True, None
    if source != "geometry":
        return False, "unknown-layout-source"
    flow = [
        child
        for child in children
        if str(child.get("position") or "static") not in {"absolute", "fixed"}
    ]
    rects = _relative_rects(node, flow)
    is_row = layout.get("mode") == "HORIZONTAL"
    if uniform_gap(rects, is_row) is None:
        return False, "non-uniform-gap"
    return True, None


def _relative_rects(
    node: Mapping[str, Any],
    children: Sequence[Mapping[str, Any]],
) -> list[tuple[float, float, float, float]]:
    node_x = float(node.get("x") or 0)
    node_y = float(node.get("y") or 0)
    return [
        (
            float(child.get("x") or 0) - node_x,
            float(child.get("y") or 0) - node_y,
            float(child.get("w") or 0),
            float(child.get("h") or 0),
        )
        for child in children
    ]


def _flow_counts(
    children: Sequence[Mapping[str, Any]],
) -> tuple[int, int]:
    absolute = sum(
        str(child.get("position") or "static") in {"absolute", "fixed"}
        for child in children
    )
    return len(children) - absolute, absolute


def _children_table(
    dom: Sequence[Mapping[str, Any]],
) -> list[list[int]]:
    children: list[list[int]] = [[] for _ in dom]
    for index, node in enumerate(dom):
        parent = node.get("pIdx")
        if isinstance(parent, int) and 0 <= parent < len(dom) and parent != index:
            children[parent].append(index)
    return children


def _parent_of(
    dom: Sequence[Mapping[str, Any]],
    index: int,
) -> Mapping[str, Any] | None:
    parent = dom[index].get("pIdx")
    if isinstance(parent, int) and 0 <= parent < len(dom) and parent != index:
        return dom[parent]
    return None


def _summarize_levels(
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    l1 = sum(bool(item["l1"]["pass"]) for item in decisions)
    l2 = sum(bool(item["l2"]["pass"]) for item in decisions)
    l3 = sum(item["l3"]["status"] == "contract-pass" for item in decisions)
    return {
        "l1": {"pass_count": l1, "coverage": l1 / len(decisions) if decisions else 0.0},
        "l2": {"pass_count": l2, "coverage": l2 / len(decisions) if decisions else 0.0},
        "l3": {"pass_count": l3, "coverage": l3 / len(decisions) if decisions else 0.0},
    }
