"""Calibrate control typography from rendered Figma text bounds."""

from __future__ import annotations

import copy
import statistics
from collections.abc import Mapping
from typing import Any

from src.app.services.structure.fidelity.contracts import normalize_match_text


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


def _render_ink_bbox(
    image_path: str,
    bbox: list[int],
    *,
    inset: int = 3,
    threshold: int = 190,
) -> list[int] | None:
    import numpy as np
    from PIL import Image

    x, y, width, height = (int(value) for value in bbox)
    left = x + inset
    top = y + inset
    right = x + width - inset
    bottom = y + height - inset
    if right <= left or bottom <= top:
        return None
    with Image.open(image_path) as source:
        image = np.asarray(source.convert("RGB"), dtype=np.int16)
    region = image[top:bottom, left:right]
    mask = np.max(region, axis=2) < threshold
    rows, columns = np.where(mask)
    if len(rows) == 0:
        return None
    return [
        left + int(columns.min()),
        top + int(rows.min()),
        int(columns.max()) - int(columns.min()) + 1,
        int(rows.max()) - int(rows.min()) + 1,
    ]


def _table_source_ink(
    element: Mapping[str, Any],
) -> tuple[list[int], list[int]] | None:
    evidence = element.get("styleEvidence")
    values = evidence.get("evidence") if isinstance(evidence, Mapping) else None
    if not isinstance(values, Mapping):
        return None
    source_bbox = values.get("source_bbox")
    ink_bbox = values.get("ink_bbox")
    if (
        not isinstance(source_bbox, list)
        or len(source_bbox) != 4
        or not isinstance(ink_bbox, list)
        or len(ink_bbox) != 4
    ):
        return None
    return list(source_bbox), list(ink_bbox)


def calibrate_table_fonts_from_render(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fit table typography from independent reference and render ink widths."""
    calibrated = copy.deepcopy(dict(design))
    header_items: list[tuple[dict[str, Any], dict[str, Any]]] = []
    body_items: list[tuple[dict[str, Any], dict[str, Any]]] = []
    individual_items: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        content_ref = str(element.get("contentRef") or "")
        if not content_ref.startswith(("table-cell:", "table-header:")):
            continue
        source = _table_source_ink(element)
        if source is None:
            continue
        source_bbox, target_ink = source
        current_ink = _render_ink_bbox(rendered_path, source_bbox)
        if current_ink is None or current_ink[2] <= 0 or target_ink[2] <= 0:
            continue
        ratio = target_ink[2] / current_ink[2]
        style = element.setdefault("style", {})
        previous = float(style.get("fontSize") or 12)
        item = {
            "contentRef": content_ref,
            "text": str(element.get("text") or ""),
            "previous": previous,
            "candidate": max(8.0, min(24.0, round(previous * ratio * 4) / 4)),
            "referenceInk": target_ink,
            "renderedInk": current_ink,
            "ratio": ratio,
        }
        if (
            content_ref.startswith("table-header:")
            and len(normalize_match_text(item["text"])) >= 2
        ):
            header_items.append((element, item))
        elif previous <= 12.5 and len(normalize_match_text(item["text"])) >= 4:
            body_items.append((element, item))
        else:
            individual_items.append((element, item))

    def group_font_size(items: list[tuple[dict[str, Any], dict[str, Any]]]) -> float:
        samples = [
            item["previous"] * item["ratio"]
            for _element, item in items
            if 0.75 <= item["ratio"] <= 2.0
        ]
        if not samples:
            return 0.0
        return max(8.0, min(24.0, round(statistics.median(samples) * 4) / 4))

    adjustments: list[dict[str, Any]] = []
    header_size = group_font_size(header_items)
    if header_size:
        for element, _item in header_items + [
            pair
            for pair in individual_items
            if str(pair[0].get("contentRef") or "").startswith("table-header:")
        ]:
            style = element.setdefault("style", {})
            previous = float(style.get("fontSize") or 12)
            if header_size == previous:
                continue
            style["fontSize"] = header_size
            adjustments.append(
                {
                    "contentRef": element.get("contentRef"),
                    "text": str(element.get("text") or ""),
                    "previous": previous,
                    "updated": header_size,
                    "group": "table-header",
                }
            )
    body_size = group_font_size(body_items)
    if body_size:
        for element in calibrated.get("elements") or []:
            if not isinstance(element, dict):
                continue
            content_ref = str(element.get("contentRef") or "")
            style = element.setdefault("style", {})
            previous = float(style.get("fontSize") or 12)
            if (
                not content_ref.startswith("table-cell:")
                or previous > 12.5
                or body_size == previous
            ):
                continue
            style["fontSize"] = body_size
            adjustments.append(
                {
                    "contentRef": content_ref,
                    "text": str(element.get("text") or ""),
                    "previous": previous,
                    "updated": body_size,
                    "group": "table-body",
                }
            )
    for element, item in individual_items:
        if str(element.get("contentRef") or "").startswith("table-header:"):
            continue
        if 0.92 <= item["ratio"] <= 1.08 or item["candidate"] == item["previous"]:
            continue
        element.setdefault("style", {})["fontSize"] = item["candidate"]
        adjustments.append(
            {
                "contentRef": item["contentRef"],
                "text": item["text"],
                "previous": item["previous"],
                "updated": item["candidate"],
                "referenceInk": item["referenceInk"],
                "renderedInk": item["renderedInk"],
            }
        )
    return calibrated, {
        "schema_version": "grounding-table-font-render-calibration/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "adjustments": adjustments,
    }


def calibrate_table_positions_from_render(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Align table text using independent render ink, never TEXT bounds."""
    del reference_path
    calibrated = copy.deepcopy(dict(design))
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        content_ref = str(element.get("contentRef") or "")
        if not content_ref.startswith(("table-cell:", "table-header:")):
            continue
        source = _table_source_ink(element)
        if source is None:
            continue
        source_bbox, target_ink = source
        current_ink = _render_ink_bbox(rendered_path, source_bbox)
        if current_ink is None:
            continue
        delta_x = float(target_ink[0] - current_ink[0])
        delta_y = float(target_ink[1] - current_ink[1])
        if abs(delta_x) < 0.25 and abs(delta_y) < 0.25:
            continue
        element["x"] = round(float(element.get("x") or 0) + delta_x, 2)
        element["y"] = round(float(element.get("y") or 0) + delta_y, 2)
        adjustments.append(
            {
                "contentRef": content_ref,
                "text": str(element.get("text") or ""),
                "x_delta": round(delta_x, 2),
                "y_delta": round(delta_y, 2),
                "referenceInk": target_ink,
                "renderedInk": current_ink,
            }
        )
    return calibrated, {
        "schema_version": "grounding-table-render-position-calibration/1.0",
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
