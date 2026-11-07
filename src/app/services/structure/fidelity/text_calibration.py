"""Calibrate control typography from rendered Figma text bounds."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


def _text_nodes(readback: Any) -> list[Mapping[str, Any]]:
    nodes: list[Mapping[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            if value.get("type") == "TEXT" and value.get("characters"):
                nodes.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(readback)
    return nodes


def _bounds(node: Mapping[str, Any]) -> Mapping[str, Any]:
    bounds = node.get("bounds")
    if isinstance(bounds, Mapping):
        return bounds
    absolute = node.get("absolute")
    return absolute if isinstance(absolute, Mapping) else {}


def calibrate_control_fonts(
    design: Mapping[str, Any],
    readback: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scale only control text whose rendered width differs from source ink."""
    calibrated = copy.deepcopy(dict(design))
    candidates = _text_nodes(readback)
    used: set[int] = set()
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        if str(element.get("type") or "") not in {"button", "input"}:
            continue
        text = str(element.get("text") or "")
        evidence = element.get("styleEvidence")
        ink_bbox = (
            evidence.get("evidence", {}).get("ink_bbox")
            if isinstance(evidence, Mapping)
            else None
        )
        if not text or not isinstance(ink_bbox, list) or len(ink_bbox) != 4:
            continue
        text_box = element.get("textBox")
        expected_x = (
            float(text_box[0])
            if isinstance(text_box, list) and len(text_box) == 4
            else float(element.get("x") or 0) + 8
        )
        expected_y = (
            float(text_box[1])
            if isinstance(text_box, list) and len(text_box) == 4
            else float(element.get("y") or 0) + 8
        )
        matches: list[tuple[float, int, Mapping[str, Any]]] = []
        for index, node in enumerate(candidates):
            if index in used or str(node.get("characters") or "") != text:
                continue
            bounds = _bounds(node)
            distance = abs(float(bounds.get("x") or 0) - expected_x) + abs(
                float(bounds.get("y") or 0) - expected_y
            )
            matches.append((distance, index, node))
        if not matches:
            continue
        _distance, index, node = min(matches, key=lambda item: item[0])
        used.add(index)
        rendered_width = float(_bounds(node).get("width") or 0)
        target_width = float(ink_bbox[2])
        if rendered_width <= 0 or target_width <= 0:
            continue
        ratio = target_width / rendered_width
        if 0.92 <= ratio <= 1.08:
            continue
        ratio = max(0.85, min(1.25, ratio))
        style = element.setdefault("style", {})
        previous = float(style.get("fontSize") or 12)
        updated = max(8.0, min(18.0, round(previous * ratio * 4) / 4))
        if updated == previous:
            continue
        style["fontSize"] = updated
        adjustments.append(
            {
                "contentRef": element.get("contentRef"),
                "text": text,
                "previous": previous,
                "updated": updated,
                "rendered_width": rendered_width,
                "target_width": target_width,
            }
        )
    return calibrated, {
        "schema_version": "grounding-control-font-calibration/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "adjustments": adjustments,
    }


def calibrate_table_positions(
    design: Mapping[str, Any],
    readback: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Align table-cell frames to source ink positions without changing type."""
    calibrated = copy.deepcopy(dict(design))
    candidates = _text_nodes(readback)
    used: set[int] = set()
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        if str(element.get("type") or "") != "text":
            continue
        if not str(element.get("contentRef") or "").startswith("table-cell:"):
            continue
        text = str(element.get("text") or "")
        evidence = element.get("styleEvidence")
        ink_bbox = (
            evidence.get("evidence", {}).get("ink_bbox")
            if isinstance(evidence, Mapping)
            else None
        )
        if not text or not isinstance(ink_bbox, list) or len(ink_bbox) != 4:
            continue
        expected_x = float(element.get("x") or 0)
        expected_y = float(element.get("y") or 0)
        matches: list[tuple[float, int, Mapping[str, Any]]] = []
        for index, node in enumerate(candidates):
            if index in used or str(node.get("characters") or "") != text:
                continue
            bounds = _bounds(node)
            distance = abs(float(bounds.get("x") or 0) - expected_x) + abs(
                float(bounds.get("y") or 0) - expected_y
            )
            matches.append((distance, index, node))
        if not matches:
            continue
        _distance, index, node = min(matches, key=lambda item: item[0])
        used.add(index)
        bounds = _bounds(node)
        delta_x = float(ink_bbox[0]) - float(bounds.get("x") or 0)
        delta_y = float(ink_bbox[1]) - float(bounds.get("y") or 0)
        if abs(delta_x) < 0.25 and abs(delta_y) < 0.25:
            continue
        element["x"] = round(float(element.get("x") or 0) + delta_x, 2)
        element["y"] = round(float(element.get("y") or 0) + delta_y, 2)
        adjustments.append(
            {
                "contentRef": element.get("contentRef"),
                "text": text,
                "x_delta": round(delta_x, 2),
                "y_delta": round(delta_y, 2),
            }
        )
    return calibrated, {
        "schema_version": "grounding-table-position-calibration/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "adjustments": adjustments,
    }


def calibrate_form_text_positions(
    design: Mapping[str, Any],
    readback: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Align form labels and status text to source ink without retypesetting."""
    calibrated = copy.deepcopy(dict(design))
    candidates = _text_nodes(readback)
    used: set[int] = set()
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        image_mvp = element.get("imageMVP")
        role = (
            str(image_mvp.get("role") or "") if isinstance(image_mvp, Mapping) else ""
        )
        if role not in {"form-label", "form-status"}:
            continue
        text = str(element.get("text") or "")
        evidence = element.get("styleEvidence")
        ink_bbox = (
            evidence.get("evidence", {}).get("ink_bbox")
            if isinstance(evidence, Mapping)
            else None
        )
        if not text or not isinstance(ink_bbox, list) or len(ink_bbox) != 4:
            continue
        expected_x = float(element.get("x") or 0)
        expected_y = float(element.get("y") or 0)
        matches: list[tuple[float, int, Mapping[str, Any]]] = []
        for index, node in enumerate(candidates):
            if index in used or str(node.get("characters") or "") != text:
                continue
            bounds = _bounds(node)
            distance = abs(float(bounds.get("x") or 0) - expected_x) + abs(
                float(bounds.get("y") or 0) - expected_y
            )
            matches.append((distance, index, node))
        if not matches:
            continue
        _distance, index, node = min(matches, key=lambda item: item[0])
        used.add(index)
        bounds = _bounds(node)
        delta_x = float(ink_bbox[0]) - float(bounds.get("x") or 0)
        delta_y = float(ink_bbox[1]) - float(bounds.get("y") or 0)
        if abs(delta_x) < 0.25 and abs(delta_y) < 0.25:
            continue
        element["x"] = round(float(element.get("x") or 0) + delta_x, 2)
        element["y"] = round(float(element.get("y") or 0) + delta_y, 2)
        adjustments.append(
            {
                "contentRef": element.get("contentRef"),
                "text": text,
                "role": role,
                "x_delta": round(delta_x, 2),
                "y_delta": round(delta_y, 2),
            }
        )
    return calibrated, {
        "schema_version": "grounding-form-text-position-calibration/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "adjustments": adjustments,
    }
