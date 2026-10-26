"""Independent acceptance checks for real Figma readback and render evidence."""

from __future__ import annotations

import base64
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from dataclasses import asdict
from typing import Any, Iterable, Iterator

from src.app.services.rendering.adapter_base import paint_order
from src.app.services.rendering.text_wrap import TextAcceptance
from src.app.services.structure.asset_metadata import resolve_asset_identity
from src.app.services.structure.font_provenance import evaluate_font_face


SCHEMA_VERSION = "p1-figma-acceptance/1.0"
DEFAULT_POLICY = {
    "policy_id": "p1-figma-structure/1.0",
    "position_tolerance_px": 1.0,
    "size_tolerance_px": 2.0,
    "font_size_tolerance_px": 0.1,
}
GENERIC_FONT_FAMILIES = {
    "serif",
    "sans-serif",
    "monospace",
    "cursive",
    "fantasy",
    "system-ui",
    "ui-serif",
    "ui-sans-serif",
    "ui-monospace",
}
EDIT_PROBE_CHECKS = (
    "node_type_preserved",
    "characters_updated",
    "font_preserved",
    "geometry_updated",
    "restored",
)
ASSET_PROBE_CHECKS = (
    "node_type_preserved",
    "image_hash_changed",
    "scale_mode_preserved",
    "restored",
)


@dataclass(frozen=True, slots=True)
class FourDimensionDecision:
    profile: str
    status: str
    dimensions: dict[str, dict[str, Any]]
    blocking_dimensions: tuple[str, ...]
    blockers: tuple[str, ...]
    text: dict[str, Any]
    assets: dict[str, Any]
    fonts: dict[str, Any]
    export_allowed: bool
    acceptance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def accept_output(
    bundle: dict[str, Any],
    profile: str,
) -> FourDimensionDecision:
    """Apply the independent visual/structure/edit/asset hard gates."""
    if not str(profile or "").strip():
        raise ValueError("accept_output requires a non-empty profile")
    acceptance = evaluate_figma_acceptance(
        bundle["design"],
        bundle.get("truth") or {},
        bundle["readback_tree"],
        font_report=bundle.get("font_report"),
        visual_metrics=bundle.get("visual_metrics"),
        visual_policy=bundle.get("visual_policy"),
        edit_probe=bundle.get("edit_probe"),
        asset_probe=bundle.get("asset_probe"),
        image_report=bundle.get("image_report"),
        text_dimensions=bundle.get("text_dimensions"),
        policy=bundle.get("policy"),
    )
    text = _text_acceptance(
        bundle.get("text_components"),
        acceptance,
    )
    fonts = _font_acceptance(acceptance)
    assets = _asset_acceptance(bundle["design"], acceptance)
    dimensions = {
        name: dict(value)
        for name, value in (acceptance.get("dimensions") or {}).items()
    }
    blockers: list[str] = []

    edit_status = str((dimensions.get("edit") or {}).get("status") or "not-evaluated")
    edit_status = _merge_gate_status(edit_status, _font_gate(fonts))
    dimensions["edit"] = {**dimensions.get("edit", {}), "status": edit_status}
    if edit_status not in {"pass", "not-required"}:
        blockers.append(f"edit:{edit_status}")

    asset_status = str((dimensions.get("asset") or {}).get("status") or "not-evaluated")
    asset_status = _merge_gate_status(asset_status, assets["overall_status"])
    dimensions["asset"] = {**dimensions.get("asset", {}), "status": asset_status}
    if asset_status not in {"pass", "not-required"}:
        blockers.append(f"asset:{asset_status}")

    text_status = str(text["overall"])
    if text_status != "pass":
        blockers.append(f"text:{text_status}")

    for dimension in ("visual", "structure"):
        status = str((dimensions.get(dimension) or {}).get("status") or "not-evaluated")
        if status not in {"pass", "not-required"}:
            blockers.append(f"{dimension}:{status}")

    statuses = {
        str((value or {}).get("status") or "not-evaluated")
        for value in dimensions.values()
    }
    statuses.add(_text_gate_status(text_status))
    if "fail" in statuses or any(blocker.endswith(":fail") for blocker in blockers):
        status = "blocked-fail"
    elif statuses & {"not-evaluated", "unknown"}:
        status = "blocked-unknown"
    elif statuses & {"partial"}:
        status = "blocked-partial"
    else:
        status = "pass"
    blocking_dimensions = tuple(
        dict.fromkeys(
            name
            for name, value in dimensions.items()
            if str((value or {}).get("status") or "") not in {"pass", "not-required"}
        )
    )
    return FourDimensionDecision(
        profile=str(profile),
        status=status,
        dimensions=dimensions,
        blocking_dimensions=blocking_dimensions,
        blockers=tuple(blockers),
        text=text,
        assets=assets,
        fonts=fonts,
        export_allowed=status == "pass",
        acceptance=acceptance,
    )


def _text_gate_status(status: str) -> str:
    return {
        "blocked-fail": "fail",
        "blocked-partial": "partial",
        "blocked-unknown": "not-evaluated",
    }.get(status, "pass")


def _text_acceptance(
    value: TextAcceptance | dict[str, Any] | None,
    acceptance: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(value, TextAcceptance):
        return value.to_dict()
    if isinstance(value, dict):
        return TextAcceptance(
            **{
                key: str(value.get(key) or "not-evaluated")
                for key in ("content", "linebreak", "box", "baseline", "glyph")
            }
        ).to_dict()
    content = str(
        (acceptance.get("checks", {}).get("content") or {}).get("status")
        or "not-evaluated"
    )
    geometry = str(
        (acceptance.get("checks", {}).get("geometry") or {}).get("status")
        or "not-evaluated"
    )
    text_check = acceptance.get("checks", {}).get("text") or {}
    text_dimensions = text_check.get("dimensions") or {}
    linebreak = str(
        (text_dimensions.get("linebreak") or {}).get("status") or "not-evaluated"
    )
    baseline = str(
        (text_dimensions.get("baseline") or {}).get("status") or "not-evaluated"
    )
    glyph_data = text_dimensions.get("glyph") or {}
    glyph = str(glyph_data.get("status") or "not-evaluated")
    if (
        glyph == "not-evaluated"
        and str(glyph_data.get("policy_status") or "") == "explicit-not-evaluated"
    ):
        glyph = "not-required"
    return TextAcceptance(
        content="pass" if content == "pass" else "fail",
        linebreak=linebreak,
        box="pass" if geometry == "pass" else "fail",
        baseline=baseline,
        glyph=glyph,
    ).to_dict()


def _font_acceptance(acceptance: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for row in (acceptance.get("checks", {}).get("font") or {}).get("rows") or []:
        face = evaluate_font_face(
            declared_family=row.get("requested_family"),
            resolved_family=row.get("resolved_family"),
            actual_family=row.get("actual_family"),
            resolution=row.get("font_resolution"),
        )
        rows.append(face.to_dict())
    statuses = [row["gate_status"] for row in rows]
    if not rows:
        overall = "not-required"
    elif any(status.startswith("blocked-font/fail") for status in statuses):
        overall = "blocked-font/fail"
    elif any(status == "blocked-font/partial" for status in statuses):
        overall = "blocked-font/partial"
    else:
        overall = "pass"
    return {"overall_status": overall, "rows": rows}


def _font_gate(fonts: dict[str, Any]) -> str:
    status = str(fonts.get("overall_status") or "not-required")
    if status == "blocked-font/fail":
        return "fail"
    if status == "blocked-font/partial":
        return "partial"
    return "pass" if status == "pass" else "not-required"


def _asset_acceptance(
    design: dict[str, Any],
    acceptance: dict[str, Any],
) -> dict[str, Any]:
    identities = []
    for element in _design_elements(design):
        if _element_type(element) not in {"image", "avatar"}:
            continue
        identity = element.get("assetIdentity") or {}
        fusion = element.get("sourceResolution")
        if isinstance(fusion, dict):
            record = identity.get("asset_record") or {}
            use = record.get("use") or {}
            source_kind = str(use.get("source_kind") or "unknown")
            requires_original = source_kind != "icon-crop"
            fusion_status = str(fusion.get("status") or "unknown")
            identity_selection = fusion.get("identity") or {}
            display_selection = fusion.get("display") or {}
            display_kind = str(display_selection.get("selected") or "missing")
            display_generated = bool(display_selection.get("generated"))
            generated_icon_scoped = (
                not requires_original
                and fusion_status == "generated-icon-display"
                and display_generated
                and display_kind != "missing"
            )
            identities.append(
                {
                    "element_id": element.get("id"),
                    "status": (
                        "not-required"
                        if generated_icon_scoped
                        else "pass"
                        if fusion_status == "resolved-source-and-capture"
                        else "partial"
                        if fusion_status
                        in {
                            "partial-unresolved-identity",
                            "partial-generated-display",
                        }
                        else "fail"
                    ),
                    "source_kind": source_kind,
                    "requires_original": requires_original,
                    "source_status": identity_selection.get("selected"),
                    "source_is_original": bool(identity_selection.get("original")),
                    "display_payload_status": (
                        "missing" if display_kind == "missing" else "available"
                    ),
                    "display_payload_kind": display_kind,
                    "display_payload_original": bool(display_selection.get("original")),
                    "display_payload_reference_only": bool(
                        display_selection.get("reference_only")
                    ),
                    "replacement_allowed": bool(identity_selection.get("replaceable")),
                    "fusion_status": fusion_status,
                    "display_selected": display_kind,
                    "display_generated": display_generated,
                    "display_original": bool(display_selection.get("original")),
                    "display_fallback_used": bool(
                        display_selection.get("fallback_used")
                    ),
                    "missing": display_kind == "missing",
                }
            )
            continue
        record = identity.get("asset_record")
        if isinstance(record, dict):
            source = record.get("source_identity") or {}
            display = (
                element.get("displayPayload") or record.get("display_payload") or {}
            )
            replacement = element.get("replacement") or record.get("replacement") or {}
            missing = record.get("missing") or {}
            identities.append(
                {
                    "element_id": element.get("id"),
                    "status": source.get("status"),
                    "source_status": source.get("status"),
                    "source_is_original": source.get("status") == "verified-original",
                    "display_payload_status": display.get("status"),
                    "display_payload_kind": display.get("kind"),
                    "display_payload_original": bool(display.get("original")),
                    "display_payload_reference_only": bool(
                        display.get("reference_only")
                    ),
                    "replacement_allowed": bool(replacement.get("allowed")),
                    "replacement_mode": replacement.get("mode"),
                    "replacement_runtime": replacement.get("figma_runtime"),
                    "missing": bool(missing.get("is_missing")),
                    "missing_outcome": missing.get("outcome"),
                }
            )
            continue
        payload_sha = identity.get("payload_sha256") or identity.get("content_sha256")
        if not payload_sha and element.get("imageBase64"):
            payload_sha = _base64_payload_sha(element.get("imageBase64"))
        natural = identity.get("natural_size") or identity.get("naturalSize")
        resolved = resolve_asset_identity(
            source_url=identity.get("source_url") or identity.get("source"),
            payload_sha256=payload_sha,
            natural_size=natural,
            url_expired=bool(identity.get("url_expired")),
            retained_bytes_present=bool(
                identity.get("retained_bytes_present") or element.get("imageBase64")
            ),
        )
        identities.append({"element_id": element.get("id"), **resolved.to_dict()})
    if not identities:
        overall = str(
            (acceptance.get("dimensions", {}).get("asset") or {}).get("status")
            or "not-required"
        )
    elif any(
        str(item.get("status") or "").startswith("blocked-")
        or item.get("status") == "fail"
        or bool(item.get("missing"))
        for item in identities
    ):
        overall = "fail"
    elif any(item.get("status") == "partial" for item in identities):
        overall = "partial"
    elif any(
        (
            bool(item.get("requires_original", True))
            and item.get("status") in {"reference-only", "unavailable"}
        )
        or item.get("display_payload_status") != "available"
        for item in identities
    ):
        overall = "partial"
    else:
        overall = "pass"
    return {"overall_status": overall, "identities": identities}


def _merge_gate_status(base: str, gate: str) -> str:
    values = {base, gate}
    if "fail" in values:
        return "fail"
    if "partial" in values:
        return "partial"
    if base in {"not-evaluated", "unknown"}:
        return base
    if base == "not-required" and gate == "pass":
        return "not-required"
    return "pass"


def evaluate_figma_acceptance(
    design: dict[str, Any],
    truth: dict[str, Any],
    readback_tree: dict[str, Any],
    *,
    font_report: dict[str, Any] | None = None,
    visual_metrics: dict[str, Any] | None = None,
    visual_policy: dict[str, Any] | None = None,
    edit_probe: dict[str, Any] | None = None,
    asset_probe: dict[str, Any] | None = None,
    image_report: dict[str, Any] | None = None,
    text_dimensions: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate one Figma sample without allowing one dimension to mask another."""
    policy = {**DEFAULT_POLICY, **(policy or {})}
    nodes = list(_iter_nodes(readback_tree))
    root_origin = _root_origin(readback_tree)

    content = _evaluate_content(design, truth, nodes)
    geometry = _evaluate_geometry(
        design,
        nodes,
        root_origin=root_origin,
        policy=policy,
    )
    font = _evaluate_fonts(
        design,
        nodes,
        root_origin=root_origin,
        font_report=font_report,
        policy=policy,
    )
    native_text = _evaluate_native_text(design, truth, nodes, edit_probe)
    assets = _evaluate_assets(
        design,
        truth,
        nodes,
        root_origin,
        asset_probe,
        image_report,
        policy,
    )
    visual = _evaluate_visual(visual_metrics, visual_policy)

    dimensions = {
        "visual": _dimension(visual["status"], ["visual"]),
        "structure": _dimension(
            _combine_statuses([content["status"], geometry["status"]]),
            ["content", "geometry"],
        ),
        "edit": _dimension(
            _combine_statuses([font["status"], native_text["status"]]),
            ["font", "native_text"],
        ),
        "asset": _dimension(assets["status"], ["assets"]),
    }
    blocking = [
        name
        for name, item in dimensions.items()
        if item["status"] not in {"pass", "not-required"}
    ]
    failed = [name for name in blocking if dimensions[name]["status"] == "fail"]
    partial = [name for name in blocking if dimensions[name]["status"] == "partial"]
    acceptance_passed = not blocking
    if acceptance_passed:
        acceptance_status = "pass"
    elif failed:
        acceptance_status = "blocked-fail"
    elif str(truth.get("expected_output_status") or "") == "partial" and partial == [
        "asset"
    ]:
        acceptance_status = "partial"
        acceptance_passed = True
    elif partial:
        acceptance_status = "blocked-partial"
    else:
        acceptance_status = "blocked-unknown"

    limitations = [
        "Thresholds are provisional and cover only the supplied canonical scope.",
        "Font checks compare resolved family, style and size; glyph identity is not proven.",
    ]
    if visual["status"] == "measured-not-gated":
        limitations.append(
            "Visual metrics were measured without a frozen Figma policy."
        )
    if native_text["status"] == "not-evaluated":
        limitations.append("Native text edit propagation has not been exercised.")
    elif native_text.get("parent_layout_propagation") != "pass":
        limitations.append(
            "Native text local bbox propagation is checked; parent Auto Layout propagation is not."
        )
    if assets["status"] not in {"not-required", "pass"}:
        limitations.append("Asset replacement capability is not fully evidenced.")
    limitations.append(
        "Antialiasing remains in the visual metric and is not attributed to a font engine without glyph masks."
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "real-figma-readback-and-export",
        "policy": policy,
        "checks": {
            "content": content,
            "geometry": geometry,
            "font": font,
            "native_text": native_text,
            "assets": assets,
            "visual": visual,
            "text": text_dimensions,
        },
        "dimensions": dimensions,
        "acceptance_status": acceptance_status,
        "acceptance_passed": acceptance_passed,
        "blocking_dimensions": blocking,
        "figma_attempted_count": 1,
        "figma_evaluated_count": 1 if acceptance_passed else 0,
        "composite_score_used": False,
        "limitations": limitations,
    }


def _evaluate_content(
    design: dict[str, Any],
    truth: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    design_texts = [
        _content_key(item.get("text"))
        for item in _design_elements(design)
        if _content_key(item.get("text"))
    ]
    truth_texts = [
        _content_key(item)
        for item in (truth.get("expected_texts") or [])
        if _content_key(item)
    ]
    expected_counts = Counter(design_texts)
    for text in truth_texts:
        if expected_counts[text] == 0:
            expected_counts[text] = 1
    expected_texts = list(expected_counts.elements())
    actual_entries = [
        (_content_key(node.get("characters")), node)
        for node in nodes
        if node.get("type") == "TEXT" and _content_key(node.get("characters"))
    ]
    expected_counts = Counter(expected_texts)
    actual_counts = Counter(text for text, _node in actual_entries)
    missing_texts = list((expected_counts - actual_counts).elements())
    unexpected_texts = list((actual_counts - expected_counts).elements())
    forbidden_present = [
        _content_key(item)
        for item in (truth.get("expected_absent_texts") or [])
        if any(_content_key(item) in text for text, _node in actual_entries)
    ]
    matched_count = sum((expected_counts & actual_counts).values())
    coverage = matched_count / len(expected_texts) if expected_texts else 1.0
    passed = not missing_texts and not unexpected_texts and not forbidden_present
    return {
        "status": "pass" if passed else "fail",
        "expected_text_count": len(expected_texts),
        "matched_text_count": matched_count,
        "actual_text_count": len(actual_entries),
        "text_coverage": coverage,
        "missing_texts": missing_texts,
        "unexpected_texts": unexpected_texts,
        "forbidden_present": forbidden_present,
        "evidence_node_ids": [node.get("id") for _text, node in actual_entries],
    }


def _evaluate_geometry(
    design: dict[str, Any],
    nodes: list[dict[str, Any]],
    *,
    root_origin: tuple[float, float],
    policy: dict[str, Any],
) -> dict[str, Any]:
    position_tolerance = float(policy["position_tolerance_px"])
    size_tolerance = float(policy["size_tolerance_px"])
    canvas = design.get("canvas") or {}
    root = nodes[0]
    root_box = _global_box(root, root_origin)
    expected_canvas = {
        "x": 0.0,
        "y": 0.0,
        "width": float(canvas.get("width") or 0.0),
        "height": float(canvas.get("height") or 0.0),
    }
    canvas_passed = (
        expected_canvas["width"] > 0
        and expected_canvas["height"] > 0
        and abs(root_box["width"] - expected_canvas["width"]) <= size_tolerance
        and abs(root_box["height"] - expected_canvas["height"]) <= size_tolerance
    )
    rows = [
        {
            "kind": "canvas",
            "node_id": root.get("id"),
            "expected": expected_canvas,
            "actual": root_box,
            "passed": canvas_passed,
        }
    ]
    candidates = nodes[1:]
    used: set[int] = set()
    matched_pairs: list[tuple[int, dict[str, Any]]] = []
    elements = _design_elements(design)
    paint_ranks = {
        id(element): rank
        for rank, (_index, element) in enumerate(paint_order(elements))
    }
    for element_index, element in enumerate(elements):
        kind = _element_type(element)
        if kind not in {"text", "container", "image", "rectangle", "ellipse"}:
            continue
        expected_box = _numeric_box(element)
        if expected_box is None:
            continue
        candidate_index, candidate = _match_element_candidate(
            element,
            candidates,
            used,
            root_origin,
        )
        row = {
            "kind": kind,
            "element_id": element.get("id"),
            "expected": expected_box,
            "actual": None,
            "node_id": None,
            "passed": False,
        }
        if candidate is None:
            row["reason"] = "node-not-found"
            rows.append(row)
            continue
        used.add(candidate_index)
        matched_pairs.append((element_index, candidate))
        actual_box = _global_box(candidate, root_origin)
        row["actual"] = actual_box
        row["node_id"] = candidate.get("id")
        if kind == "text":
            horizontal_alignment = str(
                (element.get("style") or {}).get("textAlign") or "left"
            ).lower()
            if horizontal_alignment == "center":
                x_delta = abs(
                    (actual_box["x"] + actual_box["width"] / 2)
                    - (expected_box["x"] + expected_box["width"] / 2)
                )
            elif horizontal_alignment in {"right", "end"}:
                x_delta = abs(
                    (actual_box["x"] + actual_box["width"])
                    - (expected_box["x"] + expected_box["width"])
                )
            else:
                horizontal_alignment = "left"
                x_delta = abs(actual_box["x"] - expected_box["x"])
            y_delta = abs(actual_box["y"] - expected_box["y"])
            y_tolerance = _text_vertical_tolerance(
                element,
                expected_box,
                actual_box,
                base_tolerance=position_tolerance,
            )
            comparison_box = _text_comparison_box(element, expected_box)
            contained = (
                actual_box["width"] > 0
                and actual_box["height"] > 0
                and actual_box["width"] <= comparison_box["width"] + size_tolerance
                and actual_box["height"] <= comparison_box["height"] + size_tolerance
                and actual_box["x"] + actual_box["width"]
                <= comparison_box["x"] + comparison_box["width"] + position_tolerance
                and actual_box["y"] + actual_box["height"]
                <= comparison_box["y"] + comparison_box["height"] + size_tolerance
            )
            row.update(
                {
                    "position_delta_px": {"x": x_delta, "y": y_delta},
                    "horizontal_alignment": horizontal_alignment,
                    "vertical_tolerance_px": y_tolerance,
                    "contained": contained,
                    "passed": (
                        x_delta <= position_tolerance
                        and y_delta <= y_tolerance
                        and contained
                    ),
                }
            )
        else:
            max_delta = max(
                abs(actual_box[key] - expected_box[key])
                for key in ("x", "y", "width", "height")
            )
            row["max_delta_px"] = max_delta
            row["passed"] = max_delta <= size_tolerance
        rows.append(row)

    node_positions = {id(node): index for index, node in enumerate(nodes)}
    parent_by_node = _node_parent_map(nodes[0])
    semantic_rows = rows[1:]
    matched_count = sum(row["node_id"] is not None for row in semantic_rows)
    node_count = {
        "status": "pass" if matched_count == len(semantic_rows) else "fail",
        "expected_semantic_node_count": len(semantic_rows),
        "matched_semantic_node_count": matched_count,
    }
    hierarchy = {
        "status": "pass" if matched_count == len(semantic_rows) else "fail",
        "scope": "root-descendant-membership-not-full-parent-map",
        "root_node_id": root.get("id"),
    }
    checked_order_pairs = 0
    order_inversions = []
    ordered_pairs = sorted(
        matched_pairs,
        key=lambda pair: paint_ranks[id(elements[pair[0]])],
    )
    for left_index in range(len(ordered_pairs)):
        left_element_index, left_node = ordered_pairs[left_index]
        left_box = _global_box(left_node, root_origin)
        for right_index in range(left_index + 1, len(ordered_pairs)):
            right_element_index, right_node = ordered_pairs[right_index]
            if parent_by_node.get(id(left_node)) != parent_by_node.get(id(right_node)):
                continue
            right_box = _global_box(right_node, root_origin)
            if not _boxes_overlap(left_box, right_box):
                continue
            checked_order_pairs += 1
            if node_positions[id(left_node)] > node_positions[id(right_node)]:
                order_inversions.append(
                    {
                        "earlier_element_index": left_element_index,
                        "earlier_node_id": left_node.get("id"),
                        "later_element_index": right_element_index,
                        "later_node_id": right_node.get("id"),
                    }
                )
    order = {
        "status": "pass" if not order_inversions else "fail",
        "scope": "overlapping-semantic-pairs-only",
        "checked_pair_count": checked_order_pairs,
        "expected_node_ids": [node.get("id") for _element_index, node in ordered_pairs],
        "readback_positions": [
            node_positions[id(node)] for _element_index, node in ordered_pairs
        ],
        "inversions": order_inversions,
    }
    invisible_node_ids = [
        node.get("id")
        for _element_index, node in matched_pairs
        if node.get("visible") is False or float(node.get("opacity", 1) or 0) <= 0
    ]
    visibility = {
        "status": "pass" if not invisible_node_ids else "fail",
        "invisible_node_ids": invisible_node_ids,
    }
    passed = (
        all(item["passed"] for item in rows)
        and node_count["status"] == "pass"
        and hierarchy["status"] == "pass"
        and order["status"] == "pass"
        and visibility["status"] == "pass"
    )
    return {
        "status": "pass" if passed else "fail",
        "policy_id": str(policy.get("policy_id") or ""),
        "position_tolerance_px": position_tolerance,
        "size_tolerance_px": size_tolerance,
        "row_count": len(rows),
        "failed_count": sum(not item["passed"] for item in rows),
        "rows": rows,
        "node_count": node_count,
        "hierarchy": hierarchy,
        "order": order,
        "visibility": visibility,
    }


def _evaluate_fonts(
    design: dict[str, Any],
    nodes: list[dict[str, Any]],
    *,
    root_origin: tuple[float, float],
    font_report: dict[str, Any] | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    text_elements = [
        item for item in _design_elements(design) if _element_type(item) == "text"
    ]
    if not text_elements:
        return {
            "status": "not-required",
            "row_count": 0,
            "rows": [],
            "scope": "resolved-family-style-size",
        }
    text_nodes = [node for node in nodes if node.get("type") == "TEXT"]
    used: set[int] = set()
    rows = []
    tolerance = float(policy["font_size_tolerance_px"])
    for element in text_elements:
        expected_text = _normalize_text(element.get("text"))
        index, node = _nearest_text_match(
            text_nodes,
            expected_text,
            element,
            used,
            root_origin,
        )
        style = element.get("style") or {}
        requested_family = str(
            style.get("fontFamilyRequested") or style.get("fontFamily") or ""
        )
        resolved_family = str(style.get("fontFamily") or requested_family)
        candidates = _font_families(resolved_family)
        actual_font = node.get("fontName") if node else None
        actual_family = str((actual_font or {}).get("family") or "")
        actual_style = str((actual_font or {}).get("style") or "")
        family_passed, family_reason = _font_family_status(
            candidates,
            actual_family,
        )
        requested_weight = str(
            style.get("fontWeightValue") or style.get("fontWeight") or "normal"
        )
        weight_passed = _font_weight_status(
            requested_weight,
            actual_style,
            actual_font=actual_font,
        )
        requested_font_style = str(style.get("fontStyle") or "normal").strip().lower()
        requested_italic = requested_font_style in {"italic", "oblique"}
        actual_italic = any(
            token in actual_style.lower() for token in ("italic", "oblique")
        )
        style_passed = requested_italic == actual_italic
        expected_size = float(style.get("fontSize") or 0.0)
        actual_size = float((node or {}).get("fontSize") or 0.0)
        size_passed = (
            expected_size > 0
            and actual_size > 0
            and abs(actual_size - expected_size) <= tolerance
        )
        probe = _matching_font_probe(font_report, resolved_family, requested_weight)
        fallback = bool((probe or {}).get("fallback"))
        expected_box = _numeric_box(element) or {
            "x": 0.0,
            "y": 0.0,
            "width": 0.0,
            "height": 0.0,
        }
        actual_box = _global_box(node, root_origin) if node is not None else None
        bbox_delta = None
        bottom_delta = None
        center_y_delta = None
        if actual_box is not None:
            bbox_delta = {
                key: round(actual_box[key] - expected_box[key], 6)
                for key in ("x", "y", "width", "height")
            }
            bottom_delta = round(
                (actual_box["y"] + actual_box["height"])
                - (expected_box["y"] + expected_box["height"]),
                6,
            )
            center_y_delta = round(
                (actual_box["y"] + actual_box["height"] / 2)
                - (expected_box["y"] + expected_box["height"] / 2),
                6,
            )
        if node is not None:
            used.add(index)
        rows.append(
            {
                "element_id": element.get("id"),
                "text": expected_text,
                "node_id": (node or {}).get("id"),
                "requested_family": requested_family,
                "resolved_family": resolved_family,
                "font_resolution": str(
                    style.get("fontFamilyResolution") or "legacy-design-family"
                ),
                "platform_fonts": [
                    dict(item)
                    for item in style.get("platformFonts") or []
                    if isinstance(item, dict)
                ],
                "requested_candidates": candidates,
                "requested_weight": requested_weight,
                "requested_font_style": requested_font_style,
                "expected_size": expected_size,
                "actual_family": actual_family,
                "actual_style": actual_style,
                "actual_size": actual_size,
                "family_passed": family_passed,
                "weight_passed": weight_passed,
                "style_passed": style_passed,
                "size_passed": size_passed,
                "fallback_observed": fallback,
                "expected_bbox": expected_box,
                "actual_bbox": actual_box,
                "bbox_delta_px": bbox_delta,
                "bottom_delta_px": bottom_delta,
                "center_y_delta_px": center_y_delta,
                "metric_scope": "readback-bbox-not-font-engine-metrics",
                "reason": family_reason,
                "passed": (
                    family_passed and weight_passed and style_passed and size_passed
                ),
            }
        )
    return {
        "status": "pass" if all(item["passed"] for item in rows) else "fail",
        "row_count": len(rows),
        "failed_count": sum(not item["passed"] for item in rows),
        "font_size_tolerance_px": tolerance,
        "scope": "resolved-family-style-size-not-glyph-identity",
        "rows": rows,
    }


def _evaluate_native_text(
    design: dict[str, Any],
    truth: dict[str, Any],
    nodes: list[dict[str, Any]],
    edit_probe: dict[str, Any] | None,
) -> dict[str, Any]:
    required = bool(truth.get("native_text_required"))
    expected_count = sum(
        bool(_normalize_text(item.get("text"))) for item in _design_elements(design)
    )
    native_nodes = [
        node
        for node in nodes
        if node.get("type") == "TEXT" and bool(_normalize_text(node.get("characters")))
    ]
    if not required:
        return {
            "status": "not-required",
            "scope": "native-text-editability-and-local-bbox",
            "expected_native_text_count": expected_count,
            "actual_native_text_count": len(native_nodes),
            "edit_probe_present": edit_probe is not None,
        }
    if len(native_nodes) != expected_count:
        return {
            "status": "fail",
            "scope": "native-text-editability-and-local-bbox",
            "expected_native_text_count": expected_count,
            "actual_native_text_count": len(native_nodes),
            "failed_checks": ["native-node-count"],
            "edit_probe_present": edit_probe is not None,
        }
    if edit_probe is None:
        return {
            "status": "not-evaluated",
            "scope": "native-text-editability-and-local-bbox",
            "expected_native_text_count": expected_count,
            "actual_native_text_count": len(native_nodes),
            "reason": "edit-probe-not-provided",
        }
    missing = [name for name in EDIT_PROBE_CHECKS if name not in edit_probe]
    if missing:
        return {
            "status": "not-evaluated",
            "scope": "native-text-editability-and-local-bbox",
            "expected_native_text_count": expected_count,
            "actual_native_text_count": len(native_nodes),
            "reason": "edit-probe-evidence-missing",
            "missing_checks": missing,
        }
    failed_checks = [
        name for name in EDIT_PROBE_CHECKS if edit_probe.get(name) is not True
    ]
    if str(edit_probe.get("status") or "").lower() == "fail":
        failed_checks.append("probe-status")
    return {
        "status": "pass" if not failed_checks else "fail",
        "scope": "native-text-editability-and-local-bbox",
        "expected_native_text_count": expected_count,
        "actual_native_text_count": len(native_nodes),
        "failed_checks": list(dict.fromkeys(failed_checks)),
        "edit_probe_present": True,
        "parent_layout_propagation": _probe_substatus(
            edit_probe.get("parent_layout_propagation")
        ),
        "evidence": edit_probe,
    }


def _evaluate_assets(
    design: dict[str, Any],
    truth: dict[str, Any],
    nodes: list[dict[str, Any]],
    root_origin: tuple[float, float],
    asset_probe: dict[str, Any] | None,
    image_report: dict[str, Any] | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    expected_elements = [
        item for item in _design_elements(design) if _element_type(item) == "image"
    ]
    expected_count = int(truth.get("expected_asset_count") or len(expected_elements))
    if expected_count == 0 and not expected_elements:
        return {
            "status": "not-required",
            "expected_asset_count": 0,
            "actual_image_node_count": sum(_is_image_node(node) for node in nodes),
            "scope": "image-fill-and-replacement",
        }
    image_nodes = [node for node in nodes if _is_image_node(node)]
    report_rows = {
        (str(row.get("nodeId") or ""), int(row.get("fillIndex") or 0)): row
        for row in (image_report or {}).get("fills") or []
        if isinstance(row, dict)
    }
    used: set[int] = set()
    rows = []
    tolerance = float(policy["size_tolerance_px"])
    for element in expected_elements:
        expected_box = _numeric_box(element)
        index, node = _nearest_image_match(
            image_nodes,
            expected_box,
            used,
            root_origin,
        )
        if node is not None:
            used.add(index)
        actual_box = _global_box(node, root_origin) if node is not None else None
        max_delta = None
        if node is not None and expected_box is not None:
            max_delta = max(
                abs(actual_box[key] - expected_box[key])
                for key in ("x", "y", "width", "height")
            )
        image_fill = _first_image_fill(node or {})
        expected_payload_sha = _base64_payload_sha(element.get("imageBase64"))
        report_row = report_rows.get((str((node or {}).get("id") or ""), 0))
        actual_payload_sha = _base64_payload_sha((report_row or {}).get("byteBase64"))
        payload_sha_passed = (
            expected_payload_sha is None or actual_payload_sha == expected_payload_sha
        )
        rows.append(
            {
                "element_id": element.get("id"),
                "node_id": (node or {}).get("id"),
                "expected": expected_box,
                "actual": actual_box,
                "max_delta_px": max_delta,
                "scale_mode": (image_fill or {}).get("scaleMode"),
                "image_hash": (image_fill or {}).get("imageHash"),
                "expected_payload_sha256": expected_payload_sha,
                "actual_payload_sha256": actual_payload_sha,
                "payload_sha256_passed": payload_sha_passed,
                "passed": (
                    node is not None
                    and image_fill is not None
                    and bool(image_fill.get("imageHash"))
                    and max_delta is not None
                    and max_delta <= tolerance
                ),
            }
        )
    minimum = int(truth.get("minimum_asset_count") or expected_count)
    expected_partial = str(truth.get("expected_output_status") or "pass") == "partial"
    if expected_partial and len(image_nodes) < expected_count:
        structure_status = "partial" if len(image_nodes) >= minimum else "fail"
    elif rows and all(row["passed"] for row in rows):
        structure_status = "pass"
    elif expected_partial and len(image_nodes) >= minimum:
        structure_status = "partial"
    else:
        structure_status = "fail"

    payload_required = any(
        bool(element.get("imageBase64")) for element in expected_elements
    )
    if not payload_required:
        payload_status = "not-required"
    elif image_report is None:
        payload_status = "not-evaluated"
    else:
        payload_status = (
            "pass" if all(row["payload_sha256_passed"] for row in rows) else "fail"
        )

    probe_result = {
        "present": asset_probe is not None,
        "status": "not-evaluated",
        "failed_checks": [],
    }
    if asset_probe is not None:
        missing = [name for name in ASSET_PROBE_CHECKS if name not in asset_probe]
        failed = [
            name for name in ASSET_PROBE_CHECKS if asset_probe.get(name) is not True
        ]
        if str(asset_probe.get("status") or "").lower() == "fail":
            failed.append("probe-status")
        if missing:
            probe_result = {
                "present": True,
                "status": "not-evaluated",
                "missing_checks": missing,
            }
        else:
            probe_result = {
                "present": True,
                "status": "pass" if not failed else "fail",
                "failed_checks": list(dict.fromkeys(failed)),
                "evidence": asset_probe,
            }
    status = _combine_statuses(
        [
            structure_status,
            payload_status,
            probe_result["status"],
        ]
    )
    return {
        "status": status,
        "expected_asset_count": expected_count,
        "minimum_asset_count": minimum,
        "actual_image_node_count": len(image_nodes),
        "scope": "image-fill-and-replacement",
        "structure_status": structure_status,
        "payload_sha256_status": payload_status,
        "replacement_probe": probe_result,
        "rows": rows,
    }


def _evaluate_visual(
    metrics: dict[str, Any] | None,
    policy: dict[str, Any] | None,
) -> dict[str, Any]:
    if not metrics:
        return {
            "status": "not-evaluated",
            "reason": "visual-metrics-not-provided",
            "composite_score_used": False,
        }
    if not policy:
        return {
            "status": "measured-not-gated",
            "metrics": dict(metrics),
            "threshold_state": "not-calibrated",
            "composite_score_used": False,
        }
    gate_bad_pixel_count = bool(policy.get("gate_bad_pixel_count", True))
    checks = {
        "mean": float(metrics.get("mean") or 0.0)
        <= float(policy.get("max_mean", float("inf"))),
        "ink_mean": float(metrics.get("ink_mean") or 0.0)
        <= float(policy.get("max_ink_mean", float("inf"))),
        "over30_pct": float(metrics.get("over30_pct") or 0.0)
        <= float(policy.get("max_over30_pct", float("inf"))),
    }
    if gate_bad_pixel_count:
        checks["bad_pixel_count"] = int(metrics.get("bad_pixel_count") or 0) <= int(
            policy.get("max_bad_pixel_count", 2**63 - 1)
        )
    if policy.get("require_size_match"):
        checks["size_match"] = bool(metrics.get("size_match"))
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "status": "pass" if not failed else "fail",
        "policy_id": str(policy.get("policy_id") or ""),
        "metrics": dict(metrics),
        "checks": checks,
        "gate_bad_pixel_count": gate_bad_pixel_count,
        "failed_metrics": failed,
        "composite_score_used": False,
    }


def _dimension(status: str, source_checks: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "source_checks": source_checks,
        "passed": status in {"pass", "not-required"},
    }


def _combine_statuses(statuses: Iterable[str]) -> str:
    values = list(statuses)
    if any(value == "fail" for value in values):
        return "fail"
    if any(
        value
        in {
            "not-evaluated",
            "unknown",
            "no-ground-truth",
            "not-sampled",
            "measured-not-gated",
        }
        for value in values
    ):
        return "not-evaluated"
    if any(value == "partial" for value in values):
        return "partial"
    if values and all(value == "not-required" for value in values):
        return "not-required"
    return "pass"


def _iter_nodes(root: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if not isinstance(root, dict):
        return
    yield root
    children = root.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                yield from _iter_nodes(child)


def _node_parent_map(root: dict[str, Any]) -> dict[int, str | None]:
    parents: dict[int, str | None] = {}

    def visit(node: dict[str, Any], parent_id: str | None) -> None:
        parents[id(node)] = parent_id
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child, str(node.get("id") or ""))

    visit(root, None)
    return parents


def _root_origin(root: dict[str, Any]) -> tuple[float, float]:
    box = _global_box(root, (0.0, 0.0))
    return box["x"], box["y"]


def _global_box(
    node: dict[str, Any],
    root_origin: tuple[float, float],
) -> dict[str, float]:
    absolute = node.get("absolute")
    if isinstance(absolute, dict):
        try:
            return {
                "x": float(absolute.get("x") or 0.0) - root_origin[0],
                "y": float(absolute.get("y") or 0.0) - root_origin[1],
                "width": float(absolute.get("width") or 0.0),
                "height": float(absolute.get("height") or 0.0),
            }
        except (TypeError, ValueError):
            pass
    return {
        "x": float(node.get("x") or 0.0) - root_origin[0],
        "y": float(node.get("y") or 0.0) - root_origin[1],
        "width": float(node.get("width") or 0.0),
        "height": float(node.get("height") or 0.0),
    }


def _text_comparison_box(
    element: dict[str, Any],
    expected_box: dict[str, float],
) -> dict[str, float]:
    """Allow measured text-run glyph boxes to occupy their full Figma line box."""
    box = dict(expected_box)
    measured_run = bool(element.get("textLineBox") or element.get("textEmBox"))
    if not measured_run:
        return box
    style = element.get("style") or {}
    try:
        line_height = float(style.get("lineHeight") or 0.0)
    except (TypeError, ValueError):
        line_height = 0.0
    try:
        line_count = max(1, int(element.get("textEmLines") or 1))
    except (TypeError, ValueError):
        line_count = 1
    total_line_height = line_height * line_count
    if total_line_height > box["height"]:
        box["height"] = total_line_height
    return box


def _text_vertical_tolerance(
    element: dict[str, Any],
    expected_box: dict[str, float],
    actual_box: dict[str, float],
    *,
    base_tolerance: float,
) -> float:
    if _element_type(element) != "text":
        return base_tolerance
    slack = max(
        0.0,
        (
            float(expected_box.get("height") or 0.0)
            - float(actual_box.get("height") or 0.0)
        )
        / 2,
    )
    return base_tolerance + slack


def _numeric_box(item: dict[str, Any]) -> dict[str, float] | None:
    try:
        return {
            key: float(item.get(key) or 0.0) for key in ("x", "y", "width", "height")
        }
    except (TypeError, ValueError):
        return None


def _boxes_overlap(left: dict[str, float], right: dict[str, float]) -> bool:
    return (
        left["x"] < right["x"] + right["width"]
        and right["x"] < left["x"] + left["width"]
        and left["y"] < right["y"] + right["height"]
        and right["y"] < left["y"] + left["height"]
    )


def _base64_payload_sha(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        payload = base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        return None
    return hashlib.sha256(payload).hexdigest()


def _design_elements(design: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (design.get("elements") or []) if isinstance(item, dict)]


def _element_type(element: dict[str, Any]) -> str:
    return str(element.get("type") or "").lower()


def _is_image_node(node: dict[str, Any]) -> bool:
    return _first_image_fill(node) is not None


def _first_image_fill(node: dict[str, Any]) -> dict[str, Any] | None:
    for fill in node.get("fills") or []:
        if isinstance(fill, dict) and fill.get("type") == "IMAGE":
            return fill
    return None


def _match_element_candidate(
    element: dict[str, Any],
    candidates: list[dict[str, Any]],
    used: set[int],
    root_origin: tuple[float, float],
) -> tuple[int | None, dict[str, Any] | None]:
    kind = _element_type(element)
    expected_text = _normalize_text(element.get("text"))
    expected_box = _numeric_box(element)
    choices = []
    for index, node in enumerate(candidates):
        if index in used:
            continue
        if kind == "text":
            if node.get("type") != "TEXT":
                continue
            if _content_key(node.get("characters")) != _content_key(expected_text):
                continue
        elif kind == "container":
            if node.get("type") not in {
                "FRAME",
                "RECTANGLE",
                "ELLIPSE",
            } or _is_image_node(node):
                continue
        elif kind == "image":
            missing_display = (
                str(
                    ((element.get("sourceResolution") or {}).get("display") or {}).get(
                        "selected"
                    )
                    or ""
                )
                == "missing"
            )
            if not _is_image_node(node) and not (
                missing_display
                and node.get("type") == "RECTANGLE"
                and not _is_image_node(node)
            ):
                continue
        elif kind == "rectangle":
            if node.get("type") != "RECTANGLE" or _is_image_node(node):
                continue
        elif kind == "ellipse":
            if node.get("type") != "ELLIPSE":
                continue
        box = _global_box(node, root_origin)
        distance = 0.0
        if expected_box is not None:
            distance = abs(box["x"] - expected_box["x"]) + abs(
                box["y"] - expected_box["y"]
            )
        choices.append((distance, index, node))
    if not choices:
        return None, None
    _distance, index, node = min(choices, key=lambda item: item[:2])
    return index, node


def _nearest_text_match(
    nodes: list[dict[str, Any]],
    text: str,
    element: dict[str, Any],
    used: set[int],
    root_origin: tuple[float, float],
) -> tuple[int | None, dict[str, Any] | None]:
    expected = _numeric_box(element) or {"x": 0.0, "y": 0.0}
    choices = []
    for index, node in enumerate(nodes):
        if index in used or _content_key(node.get("characters")) != _content_key(text):
            continue
        box = _global_box(node, root_origin)
        distance = abs(box["x"] - expected["x"]) + abs(box["y"] - expected["y"])
        choices.append((distance, index, node))
    if not choices:
        return None, None
    _distance, index, node = min(choices, key=lambda item: item[:2])
    return index, node


def _nearest_image_match(
    nodes: list[dict[str, Any]],
    expected_box: dict[str, float] | None,
    used: set[int],
    root_origin: tuple[float, float],
) -> tuple[int | None, dict[str, Any] | None]:
    if expected_box is None:
        return None, None
    choices = []
    for index, node in enumerate(nodes):
        if index in used:
            continue
        box = _global_box(node, root_origin)
        distance = sum(
            abs(box[key] - expected_box[key]) for key in ("x", "y", "width", "height")
        )
        choices.append((distance, index, node))
    if not choices:
        return None, None
    _distance, index, node = min(choices, key=lambda item: item[:2])
    return index, node


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _content_key(value: Any) -> str:
    """Ignore layout-inserted whitespace while preserving visible characters."""
    return re.sub(r"\s+", "", str(value or ""))


def _font_families(value: str) -> list[str]:
    return [
        _normalize_family(item)
        for item in re.split(r"\s*,\s*", value)
        if _normalize_family(item)
    ]


def _normalize_family(value: str) -> str:
    return str(value or "").strip().strip("\"'").strip()


def _font_family_status(
    candidates: list[str],
    actual_family: str,
) -> tuple[bool, str]:
    actual = _normalize_family(actual_family)
    if not candidates or not actual:
        return False, "font-family-not-observed"
    if any(
        _normalize_family(item).casefold() == actual.casefold() for item in candidates
    ):
        return True, ""
    if all(item.casefold() in GENERIC_FONT_FAMILIES for item in candidates):
        return False, "generic-family-resolved-to-concrete-font"
    return False, "font-family-fallback"


def _font_weight_status(
    requested: str,
    actual_style: str,
    *,
    actual_font: dict[str, Any] | None = None,
) -> bool:
    requested_weight = _requested_weight_value(requested)
    if requested_weight is None:
        return False
    variation = (actual_font or {}).get("variationSettings")
    if isinstance(variation, dict):
        try:
            variation_weight = int(float(variation.get("wght")))
        except (TypeError, ValueError):
            variation_weight = None
        if variation_weight is not None:
            return variation_weight == requested_weight
    return _style_weight_value(actual_style) == requested_weight


def _requested_weight_value(value: str) -> int | None:
    raw = str(value or "normal").strip().lower()
    if raw in {"normal", "regular"}:
        return 400
    if raw == "bold":
        return 700
    try:
        return int(float(raw))
    except ValueError:
        return None


def _style_weight_value(style: str) -> int | None:
    value = " ".join(str(style or "").lower().replace("-", " ").split())
    if not value:
        return None
    if re.search(r"\b(black|heavy)\b", value):
        return 900
    if re.search(r"\b(extra|ultra) bold\b|\b(extrabold|ultrabold)\b", value):
        return 800
    if re.search(r"\b(semi|demi) bold\b|\b(semibold|demibold)\b", value):
        return 600
    if re.search(r"\b(extra|ultra) light\b|\b(extralight|ultralight)\b", value):
        return 200
    if re.search(r"\bthin\b|\bhairline\b", value):
        return 100
    if re.search(r"\blight\b", value):
        return 300
    if re.search(r"\b(regular|normal|book|roman)\b", value):
        return 400
    if re.search(r"\bsemilight\b|\bsemi light\b", value):
        return 350
    if re.search(r"\bmedium\b", value):
        return 500
    if re.search(r"\bbold\b", value):
        return 700
    if re.search(r"\b(italic|oblique)\b", value):
        return 400
    return None


def _matching_font_probe(
    font_report: dict[str, Any] | None,
    requested_family: str,
    requested_weight: str,
) -> dict[str, Any] | None:
    requested = _font_families(requested_family)
    if not requested or not font_report:
        return None
    for row in font_report.get("probes") or []:
        request = row.get("request") or {}
        family = _normalize_family(request.get("fontFamily"))
        weight = str(request.get("fontWeight") or "normal")
        if family.casefold() == requested[0].casefold() and weight == requested_weight:
            return row
    return None


def _probe_substatus(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("status") or "not-evaluated")
    if value is True:
        return "pass"
    if value is False:
        return "fail"
    return "not-evaluated"
