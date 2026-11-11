"""Calibrate control typography from rendered Figma text bounds."""

from __future__ import annotations

import copy
import math
import statistics
from collections.abc import Mapping
from pathlib import Path
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
    contrast: bool = False,
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
    if contrast:
        background = np.median(region.reshape(-1, 3), axis=0)
        mask = np.max(np.abs(region - background), axis=2) > 50
    else:
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


def _contrast_ink_pixel_count(image_path: str, bbox: list[int]) -> int:
    import numpy as np
    from PIL import Image

    x, y, width, height = (int(value) for value in bbox)
    inset = 3
    left = x + inset
    top = y + inset
    right = x + width - inset
    bottom = y + height - inset
    if right <= left or bottom <= top:
        return 0
    with Image.open(image_path) as source:
        image = np.asarray(source.convert("RGB"), dtype=np.int16)
    region = image[top:bottom, left:right]
    background = np.median(region.reshape(-1, 3), axis=0)
    return int((np.max(np.abs(region - background), axis=2) > 50).sum())


def _color_luminance(value: Any) -> float | None:
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        red, green, blue = (
            int(text[index : index + 2], 16) for index in (0, 2, 4)
        )
    except ValueError:
        return None
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _is_low_contrast_evidence(values: Mapping[str, Any]) -> bool:
    try:
        contrast_delta = float(values.get("contrast_delta") or 999)
    except (TypeError, ValueError):
        return False
    background_luminance = _color_luminance(values.get("background"))
    foreground_luminance = _color_luminance(values.get("foreground"))
    return bool(
        contrast_delta <= 110
        and background_luminance is not None
        and background_luminance >= 200
        and foreground_luminance is not None
        and 100 <= foreground_luminance <= 200
    )


def _looks_like_search_control(element: Mapping[str, Any]) -> bool:
    markers = (
        element.get("text"),
        element.get("controlValue"),
        element.get("name"),
        element.get("ariaLabel"),
    )
    normalized = " ".join(normalize_match_text(value) for value in markers)
    return "搜索" in normalized or "search" in normalized


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
        normalized_text_length = len(normalize_match_text(item["text"]))
        if (
            content_ref.startswith("table-header:")
            and normalized_text_length >= 2
        ):
            header_items.append((element, item))
        elif previous <= 12.5 and normalized_text_length >= 4:
            body_items.append((element, item))
        elif normalized_text_length <= 2:
            # Tiny ink samples are too unstable for independent width scaling.
            # These owners inherit the table group size when one is available.
            continue
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
        for element, _item in header_items:
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


def calibrate_table_letter_spacing_from_render(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Correct long table-cell width while preserving font size and height."""
    calibrated = copy.deepcopy(dict(design))
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        content_ref = str(element.get("contentRef") or "")
        if not content_ref.startswith(("table-cell:", "table-header:")):
            continue
        text = str(element.get("text") or "")
        if len(normalize_match_text(text)) < 3:
            continue
        source = _table_source_ink(element)
        if source is None:
            continue
        source_bbox, target_ink = source
        current_ink = _render_ink_bbox(
            rendered_path,
            source_bbox,
            contrast=True,
        )
        if current_ink is None or current_ink[2] <= 0:
            continue
        width_delta = int(target_ink[2] - current_ink[2])
        width_tolerance = max(2, int(round(target_ink[2] * 0.02)))
        height_delta = int(target_ink[3] - current_ink[3])
        height_tolerance = max(2, int(round(target_ink[3] * 0.02)))
        if abs(width_delta) <= width_tolerance or abs(height_delta) > height_tolerance:
            continue
        gaps = max(1, len(text) - 1)
        previous = float(element.setdefault("style", {}).get("letterSpacing") or 0)
        updated = round((previous + width_delta / gaps) * 4) / 4
        updated = max(-1.0, min(2.0, updated))
        if updated == previous:
            continue
        element["style"]["letterSpacing"] = updated
        adjustments.append(
            {
                "contentRef": content_ref,
                "text": text,
                "previous": previous,
                "updated": updated,
                "referenceWidth": target_ink[2],
                "renderedWidth": current_ink[2],
                "widthDelta": width_delta,
                "referenceHeight": target_ink[3],
                "renderedHeight": current_ink[3],
                "heightDelta": height_delta,
            }
        )
    return calibrated, {
        "schema_version": "grounding-table-letter-spacing/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "adjustments": adjustments,
    }


def calibrate_low_contrast_placeholder_from_render(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
    *,
    ocr_supplement: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fit light-on-white placeholder text whose glyph ink is underweighted.

    Table cells are excluded.  Their size comes from the table's own scale
    (``clamp_table_cell_font_outliers``); when this strategy also processed
    them it rewrote the fallback ``15.25 / 700`` onto every cell placeholder,
    which measured ``style_mm 14/105 -> 30/105`` on light-table -- sixteen
    Regular placeholders rendered Bold.  The fixed fallback is a form-control
    constant; table cells are not form controls.
    """
    calibrated = copy.deepcopy(dict(design))
    skipped_table_cells = 0
    ocr_by_text: dict[str, list[dict[str, Any]]] = {}
    for observation in (ocr_supplement or {}).get("observations") or []:
        if not isinstance(observation, Mapping):
            continue
        text = normalize_match_text(observation.get("text"))
        bbox = observation.get("bbox")
        confidence = float(observation.get("confidence") or 0)
        if (
            not text
            or not isinstance(bbox, list)
            or len(bbox) != 4
            or confidence < 0.80
        ):
            continue
        try:
            normalized_bbox = [int(round(float(value))) for value in bbox]
        except (TypeError, ValueError):
            continue
        if normalized_bbox[2] <= 0 or normalized_bbox[3] <= 0:
            continue
        ocr_by_text.setdefault(text, []).append(
            {
                "bbox": normalized_bbox,
                "confidence": confidence,
                "engine": str(observation.get("engine") or ""),
            }
        )
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        element_type = str(element.get("type") or "")
        if element_type not in {"text", "input", "button"}:
            continue
        role = str((element.get("imageMVP") or {}).get("role") or "")
        if role in {"table-cell", "table-header"}:
            skipped_table_cells += 1
            continue
        style = element.setdefault("style", {})
        previous_size = float(style.get("fontSize") or 0)
        minimum_size = 15.75 if element_type == "text" else 8.0
        if not minimum_size <= previous_size <= 24.25:
            continue
        evidence = element.get("styleEvidence")
        values = evidence.get("evidence") if isinstance(evidence, Mapping) else None
        if not isinstance(values, Mapping):
            continue
        if not _is_low_contrast_evidence(values):
            continue
        contrast_delta = float(values.get("contrast_delta") or 999)
        source_bbox = values.get("source_bbox")
        target_ink = values.get("ink_bbox")
        if (
            not isinstance(source_bbox, list)
            or len(source_bbox) != 4
            or not isinstance(target_ink, list)
            or len(target_ink) != 4
        ):
            continue
        selected_ocr = None
        candidates = ocr_by_text.get(normalize_match_text(element.get("text"))) or []
        if candidates:
            source_center_x = float(source_bbox[0]) + float(source_bbox[2]) / 2
            source_center_y = float(source_bbox[1]) + float(source_bbox[3]) / 2
            selected_ocr = min(
                candidates,
                key=lambda item: (
                    (
                        item["bbox"][0]
                        + item["bbox"][2] / 2
                        - source_center_x
                    )
                    ** 2
                    + (
                        item["bbox"][1]
                        + item["bbox"][3] / 2
                        - source_center_y
                    )
                    ** 2
                ),
            )
            source_bbox = list(selected_ocr["bbox"])
            target_ink = _render_ink_bbox(
                reference_path,
                source_bbox,
                contrast=True,
            ) or list(source_bbox)
            values["source_bbox"] = list(source_bbox)
            values["ink_bbox"] = list(target_ink)
            values["ocr_bbox"] = list(source_bbox)
            values["ocr_confidence"] = selected_ocr["confidence"]
        current_ink = _render_ink_bbox(
            rendered_path,
            source_bbox,
            contrast=True,
        )
        if current_ink is None:
            continue
        delta_x = int(target_ink[0] - current_ink[0])
        delta_y = int(target_ink[1] - current_ink[1])
        width_delta = int(current_ink[2] - target_ink[2])
        height_delta = int(current_ink[3] - target_ink[3])
        reference_pixels = _contrast_ink_pixel_count(reference_path, source_bbox)
        rendered_pixels = _contrast_ink_pixel_count(rendered_path, source_bbox)
        coverage = (
            float(rendered_pixels) / float(reference_pixels)
            if reference_pixels
            else None
        )
        width_tolerance = max(2, int(round(target_ink[2] * 0.02)))
        height_tolerance = max(2, int(round(target_ink[3] * 0.02)))
        if (
            abs(delta_x) <= 1
            and abs(delta_y) <= 1
            and abs(width_delta) <= width_tolerance
            and abs(height_delta) <= height_tolerance
            and coverage is not None
            and 0.90 <= coverage <= 1.10
        ):
            continue
        style["fontSize"] = 15.25
        style["fontWeight"] = 700
        if element_type == "text":
            element["x"] = float(source_bbox[0])
        else:
            element["textBox"] = list(source_bbox)
        adjustments.append(
            {
                "contentRef": element.get("contentRef"),
                "text": str(element.get("text") or ""),
                "previousSize": previous_size,
                "updatedSize": 15.25,
                "updatedWeight": 700,
                "xDelta": delta_x,
                "yDelta": delta_y,
                "widthDelta": width_delta,
                "heightDelta": height_delta,
                "inkCoverageRatio": coverage,
                "contrastDelta": contrast_delta,
                "ocrBBox": list(source_bbox) if selected_ocr is not None else None,
                "ocrConfidence": (
                    selected_ocr["confidence"] if selected_ocr is not None else None
                ),
            }
        )
    return calibrated, {
        "schema_version": "grounding-low-contrast-placeholder/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "skipped_table_cells": skipped_table_cells,
        "adjustments": adjustments,
    }


def calibrate_search_control_from_render(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bring low-contrast search text into tolerance without moving its shell."""
    del reference_path
    calibrated = copy.deepcopy(dict(design))
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        if str(element.get("type") or "") not in {"button", "input"}:
            continue
        if not _looks_like_search_control(element):
            continue
        evidence = element.get("styleEvidence")
        values = evidence.get("evidence") if isinstance(evidence, Mapping) else None
        if not isinstance(values, Mapping) or not _is_low_contrast_evidence(values):
            continue
        source_bbox = values.get("source_bbox")
        reference_ink = values.get("ink_bbox")
        text_box = element.get("textBox")
        if (
            not isinstance(source_bbox, list)
            or len(source_bbox) != 4
            or not isinstance(reference_ink, list)
            or len(reference_ink) != 4
            or not isinstance(text_box, list)
            or len(text_box) != 4
        ):
            continue
        try:
            normalized_source = [int(round(float(value))) for value in source_bbox]
            normalized_reference_ink = [
                int(round(float(value))) for value in reference_ink
            ]
            current_text_box = [int(round(float(value))) for value in text_box]
        except (TypeError, ValueError):
            continue
        if normalized_reference_ink[2] <= 0 or normalized_reference_ink[3] <= 0:
            continue
        support_bbox = [
            normalized_source[0] - 4,
            normalized_source[1] - 4,
            normalized_source[2] + 8,
            normalized_source[3] + 8,
        ]
        rendered_ink = _render_ink_bbox(
            rendered_path,
            support_bbox,
            contrast=True,
        )
        if rendered_ink is None:
            continue
        x_delta = int(normalized_reference_ink[0] - rendered_ink[0])
        y_delta = int(normalized_reference_ink[1] - rendered_ink[1])
        width_delta = int(normalized_reference_ink[2] - rendered_ink[2])
        height_delta = int(normalized_reference_ink[3] - rendered_ink[3])
        width_tolerance = max(2, int(round(normalized_reference_ink[2] * 0.02)))
        if (
            abs(x_delta) <= 1
            and abs(y_delta) <= 1
            and abs(width_delta) <= width_tolerance
        ):
            continue
        if abs(x_delta) > 4 or abs(y_delta) > 4 or abs(width_delta) > 4:
            continue
        position_x = 0
        if abs(x_delta) > 1:
            position_x = x_delta - 1 if x_delta > 0 else x_delta + 1
        position_y = 0
        if abs(y_delta) > 1:
            position_y = y_delta - 1 if y_delta > 0 else y_delta + 1
        rendered_width = rendered_ink[2]
        width_low = normalized_reference_ink[2] - width_tolerance
        width_high = normalized_reference_ink[2] + width_tolerance
        width_correction = 0
        if rendered_width > width_high:
            width_correction = width_high - rendered_width
        elif rendered_width < width_low:
            width_correction = width_low - rendered_width
        gaps = max(1, len(str(element.get("text") or "")) - 1)
        spacing_delta = round((width_correction / gaps) * 4) / 4
        spacing_delta = max(-1.0, min(2.0, spacing_delta))
        style = element.setdefault("style", {})
        previous_spacing = float(style.get("letterSpacing") or 0)
        updated_spacing = round(
            max(-1.0, min(2.0, previous_spacing + spacing_delta)) * 4
        ) / 4
        updated_text_box = [
            current_text_box[0] + position_x,
            current_text_box[1] + position_y,
            current_text_box[2],
            current_text_box[3],
        ]
        if position_x == 0 and position_y == 0 and updated_spacing == previous_spacing:
            continue
        element["textBox"] = updated_text_box
        if updated_spacing:
            style["letterSpacing"] = updated_spacing
        elif "letterSpacing" in style:
            style.pop("letterSpacing", None)
        adjustments.append(
            {
                "contentRef": element.get("contentRef"),
                "text": str(element.get("text") or ""),
                "previousTextBox": current_text_box,
                "updatedTextBox": updated_text_box,
                "referenceInkBBox": normalized_reference_ink,
                "renderedInkBBox": rendered_ink,
                "xDelta": x_delta,
                "yDelta": y_delta,
                "widthDelta": width_delta,
                "heightDelta": height_delta,
                "positionCorrectionX": position_x,
                "positionCorrectionY": position_y,
                "widthCorrectionPx": width_correction,
                "previousLetterSpacing": previous_spacing,
                "updatedLetterSpacing": updated_spacing,
            }
        )
    return calibrated, {
        "schema_version": "grounding-search-control-post-calibration/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "adjustments": adjustments,
    }


def _form_bounds(design: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
    form = next(
        (
            element
            for element in design.get("elements") or []
            if isinstance(element, Mapping) and element.get("role") == "form-section"
        ),
        None,
    )
    if form is None:
        return None
    left = int(float(form.get("x") or 0))
    top = int(float(form.get("y") or 0))
    right = left + int(float(form.get("width") or 0))
    bottom = top + int(float(form.get("height") or 0))
    for role in ("table-section", "table-header-controls", "toolbar"):
        for element in design.get("elements") or []:
            if not isinstance(element, Mapping) or element.get("role") != role:
                continue
            candidate_top = int(float(element.get("y") or 0))
            if candidate_top > top:
                bottom = min(
                    bottom, candidate_top - (8 if role != "table-section" else 0)
                )
            break
    return left, top, right, bottom


def _toolbar_bounds(
    design: Mapping[str, Any],
) -> tuple[float, float, float, float] | None:
    toolbar = next(
        (
            element
            for element in design.get("elements") or []
            if isinstance(element, Mapping)
            and element.get("role") == "table-header-controls"
        ),
        None,
    )
    if toolbar is not None:
        left = float(toolbar.get("x") or 0)
        top = float(toolbar.get("y") or 0)
        return (
            left,
            top,
            left + float(toolbar.get("width") or 0),
            top + float(toolbar.get("height") or 0),
        )

    buttons = [
        element
        for element in design.get("elements") or []
        if isinstance(element, Mapping) and element.get("type") == "button"
    ]
    markers = [
        element
        for element in buttons
        if isinstance(element.get("imageMVP"), Mapping)
        and element["imageMVP"].get("role") == "toolbar-control"
    ]
    if not markers:
        return None
    marker = min(markers, key=lambda element: float(element.get("x") or 0))
    marker_top = float(marker.get("y") or 0)
    marker_bottom = marker_top + float(marker.get("height") or 0)
    cluster = []
    for element in buttons:
        top = float(element.get("y") or 0)
        bottom = top + float(element.get("height") or 0)
        overlap = max(0.0, min(bottom, marker_bottom) - max(top, marker_top))
        if overlap > 0:
            cluster.append(element)
    left = min(float(element.get("x") or 0) for element in cluster)
    top = min(float(element.get("y") or 0) for element in cluster)
    right = max(
        float(element.get("x") or 0) + float(element.get("width") or 0)
        for element in cluster
    )
    bottom = max(
        float(element.get("y") or 0) + float(element.get("height") or 0)
        for element in cluster
    )
    return left, top, right, bottom


def _form_source_ink(
    element: Mapping[str, Any],
    bounds: tuple[int, int, int, int],
) -> tuple[list[int], list[int]] | None:
    source = _table_source_ink(element)
    if source is None:
        return None
    source_bbox, ink_bbox = source
    center_x = source_bbox[0] + source_bbox[2] / 2
    center_y = source_bbox[1] + source_bbox[3] / 2
    left, top, right, bottom = bounds
    if not (left <= center_x <= right and top <= center_y < bottom):
        return None
    return source_bbox, ink_bbox


def calibrate_form_fonts_from_render(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fit form typography after table and toolbar calibration is complete."""
    del reference_path
    calibrated = copy.deepcopy(dict(design))
    bounds = _form_bounds(calibrated)
    if bounds is None:
        return calibrated, {
            "schema_version": "grounding-form-font-render-calibration/1.0",
            "status": "not-needed",
            "adjusted_count": 0,
            "adjustments": [],
        }

    groups: dict[tuple[str, float, str], list[tuple[dict[str, Any], float]]] = {}
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        if str(element.get("type") or "") not in {"text", "input", "button"}:
            continue
        if str(element.get("controlType") or "").lower() == "textarea":
            # A textarea line is a bounded run, not a reusable width sample.
            # Scaling to the full string width worsens its screenshot residual.
            continue
        source = _form_source_ink(element, bounds)
        if source is None:
            continue
        source_bbox, target_ink = source
        current_ink = _render_ink_bbox(
            rendered_path,
            source_bbox,
            contrast=True,
        )
        if current_ink is None or current_ink[2] <= 0 or target_ink[2] <= 0:
            continue
        style = element.setdefault("style", {})
        evidence = element.get("styleEvidence")
        values = evidence.get("evidence") if isinstance(evidence, Mapping) else {}
        key = (
            str(element.get("type") or ""),
            float(style.get("fontSize") or 12),
            str((values or {}).get("script") or ""),
        )
        groups.setdefault(key, []).append((element, target_ink[2] / current_ink[2]))

    adjustments: list[dict[str, Any]] = []
    for (element_type, previous, script), items in groups.items():
        ratio = statistics.median([item_ratio for _element, item_ratio in items])
        if not 0.9 <= ratio <= 1.6:
            continue
        updated = max(8.0, min(24.0, round(previous * ratio * 4) / 4))
        if updated == previous:
            continue
        for element, _item_ratio in items:
            element.setdefault("style", {})["fontSize"] = updated
            adjustments.append(
                {
                    "contentRef": element.get("contentRef"),
                    "text": str(element.get("text") or ""),
                    "type": element_type,
                    "previous": previous,
                    "updated": updated,
                    "script": script,
                }
            )
    return calibrated, {
        "schema_version": "grounding-form-font-render-calibration/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "adjustments": adjustments,
    }


def calibrate_form_text_weight_from_render(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use form ink coverage to select Light for consistently over-ink text."""
    calibrated = copy.deepcopy(dict(design))
    bounds = _form_bounds(calibrated)
    if bounds is None:
        return calibrated, {
            "schema_version": "grounding-form-text-weight/1.0",
            "status": "not-needed",
            "adjusted_count": 0,
            "adjustments": [],
        }
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict) or element.get("type") != "text":
            continue
        if str(element.get("contentRef") or "").startswith("table-header:"):
            continue
        source = _form_source_ink(element, bounds)
        if source is None:
            continue
        source_bbox, _target_ink = source
        style = element.setdefault("style", {})
        previous = style.get("fontWeight")
        if previous in {300, "300", "light"}:
            continue
        luminance = _color_luminance(style.get("textColor"))
        if luminance is not None and luminance >= 128:
            continue
        rendered_pixels = _contrast_ink_pixel_count(rendered_path, source_bbox)
        target_pixels = _contrast_ink_pixel_count(reference_path, source_bbox)
        if target_pixels <= 0 or rendered_pixels <= 0:
            continue
        coverage = float(rendered_pixels) / float(target_pixels)
        if coverage < 1.18:
            continue
        style["fontWeight"] = 300
        adjustments.append(
            {
                "contentRef": element.get("contentRef"),
                "text": str(element.get("text") or ""),
                "previous": previous,
                "updated": 300,
                "inkCoverageRatio": coverage,
            }
        )
    return calibrated, {
        "schema_version": "grounding-form-text-weight/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "adjustments": adjustments,
    }


def calibrate_form_text_shape_from_render(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reduce only form text whose size or ink is not already matched."""
    calibrated = copy.deepcopy(dict(design))
    bounds = _form_bounds(calibrated)
    if bounds is None:
        return calibrated, {
            "schema_version": "grounding-form-text-shape/1.0",
            "status": "not-needed",
            "adjusted_count": 0,
            "adjustments": [],
        }
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict) or element.get("type") != "text":
            continue
        style = element.setdefault("style", {})
        previous_size = float(style.get("fontSize") or 0)
        if not 17.75 <= previous_size <= 18.25:
            continue
        source = _form_source_ink(element, bounds)
        if source is None:
            continue
        source_bbox, target_ink = source
        current_ink = _render_ink_bbox(
            rendered_path,
            source_bbox,
            contrast=True,
        )
        if current_ink is None or current_ink[2] <= 0 or current_ink[3] <= 0:
            continue
        reference_pixels = _contrast_ink_pixel_count(reference_path, source_bbox)
        rendered_pixels = _contrast_ink_pixel_count(rendered_path, source_bbox)
        if reference_pixels <= 0 or rendered_pixels <= 0:
            continue
        coverage = float(rendered_pixels) / float(reference_pixels)
        width_tolerance = max(2, int(round(target_ink[2] * 0.02)))
        height_tolerance = max(2, int(round(target_ink[3] * 0.02)))
        width_delta = int(current_ink[2] - target_ink[2])
        height_delta = int(current_ink[3] - target_ink[3])
        if (
            abs(width_delta) <= width_tolerance
            and abs(height_delta) <= height_tolerance
            and 0.90 <= coverage <= 1.10
        ):
            continue
        previous_weight = style.get("fontWeight")
        style["fontSize"] = 17.5
        style["fontWeight"] = 300
        adjustments.append(
            {
                "contentRef": element.get("contentRef"),
                "text": str(element.get("text") or ""),
                "previousSize": previous_size,
                "updatedSize": 17.5,
                "previousWeight": previous_weight,
                "updatedWeight": 300,
                "widthDelta": width_delta,
                "heightDelta": height_delta,
                "inkCoverageRatio": coverage,
            }
        )
    return calibrated, {
        "schema_version": "grounding-form-text-shape/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "adjustments": adjustments,
    }


def calibrate_form_positions_from_render(
    design: Mapping[str, Any],
    readback: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Correct form ink after typography changes; control shells stay fixed."""
    del reference_path
    calibrated = copy.deepcopy(dict(design))
    bounds = _form_bounds(calibrated)
    if bounds is None:
        return calibrated, {
            "schema_version": "grounding-form-render-position-calibration/1.0",
            "status": "not-needed",
            "adjusted_count": 0,
            "adjustments": [],
        }
    text_nodes = _text_nodes(readback)
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        source = _form_source_ink(element, bounds)
        if source is None:
            continue
        source_bbox, target_ink = source
        current_ink = _render_ink_bbox(
            rendered_path,
            source_bbox,
            contrast=True,
        )
        if current_ink is None:
            continue
        delta_x = float(target_ink[0] - current_ink[0])
        delta_y = float(target_ink[1] - current_ink[1])
        if abs(delta_x) < 0.5 and abs(delta_y) < 0.5:
            continue
        element_type = str(element.get("type") or "")
        text = str(element.get("text") or "")
        if element_type == "text":
            element["x"] = round(float(element.get("x") or 0) + delta_x, 2)
            element["y"] = round(float(element.get("y") or 0) + delta_y, 2)
        elif element_type in {"input", "button"} and text:
            expected_box = element.get("textBox")
            expected_x = (
                float(expected_box[0])
                if isinstance(expected_box, list) and len(expected_box) == 4
                else float(element.get("x") or 0)
            )
            expected_y = (
                float(expected_box[1])
                if isinstance(expected_box, list) and len(expected_box) == 4
                else float(element.get("y") or 0)
            )
            matches = []
            for node in text_nodes:
                if str(node.get("characters") or "") != text:
                    continue
                node_bounds = _bounds(node)
                distance = abs(float(node_bounds.get("x") or 0) - expected_x) + abs(
                    float(node_bounds.get("y") or 0) - expected_y
                )
                matches.append((distance, node_bounds))
            if not matches:
                continue
            _distance, node_bounds = min(matches, key=lambda item: item[0])
            element["textBox"] = [
                round(float(node_bounds.get("x") or 0) + delta_x, 2),
                round(float(node_bounds.get("y") or 0) + delta_y, 2),
                float(node_bounds.get("width") or 0),
                float(node_bounds.get("height") or 0),
            ]
        else:
            continue
        adjustments.append(
            {
                "contentRef": element.get("contentRef"),
                "text": text,
                "type": element_type,
                "x_delta": round(delta_x, 2),
                "y_delta": round(delta_y, 2),
            }
        )
    return calibrated, {
        "schema_version": "grounding-form-render-position-calibration/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "adjustments": adjustments,
    }


def calibrate_toolbar_letter_spacing_from_render(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fit toolbar letter spacing without changing font size or shells."""
    del reference_path
    calibrated = copy.deepcopy(dict(design))
    toolbar_bounds = _toolbar_bounds(calibrated)
    if toolbar_bounds is None:
        return calibrated, {
            "schema_version": "grounding-toolbar-letter-spacing/1.0",
            "status": "not-needed",
            "adjusted_count": 0,
            "adjustments": [],
        }
    left, top, right, bottom = toolbar_bounds
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        if str(element.get("type") or "") not in {"input", "button"}:
            continue
        text = str(element.get("text") or "")
        if len(text) < 2:
            continue
        source = _table_source_ink(element)
        if source is None:
            continue
        source_bbox, target_ink = source
        center_x = source_bbox[0] + source_bbox[2] / 2
        center_y = source_bbox[1] + source_bbox[3] / 2
        if not (left <= center_x <= right and top <= center_y <= bottom):
            continue
        current_ink = _render_ink_bbox(
            rendered_path,
            source_bbox,
            contrast=True,
        )
        if current_ink is None:
            continue
        width_delta = target_ink[2] - current_ink[2]
        if abs(width_delta) <= 1:
            continue
        gaps = max(1, len(text) - 1)
        spacing = max(-1.0, min(2.0, width_delta / gaps))
        spacing = round(spacing * 4) / 4
        style = element.setdefault("style", {})
        previous = float(style.get("letterSpacing") or 0)
        if spacing == previous:
            continue
        style["letterSpacing"] = spacing
        adjustments.append(
            {
                "contentRef": element.get("contentRef"),
                "text": text,
                "previous": previous,
                "updated": spacing,
                "referenceWidth": target_ink[2],
                "renderedWidth": current_ink[2],
            }
        )
    return calibrated, {
        "schema_version": "grounding-toolbar-letter-spacing/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "adjustments": adjustments,
    }


#: Ladder the image pipeline emits on.  Kept in sync with ``WEIGHT_LADDER`` in
#: ``figma_bridge/code.js`` so a value chosen here resolves to the same face.
_WEIGHT_LADDER: tuple[int, ...] = (300, 400, 500, 700, 900)

#: Ink multiplier per ladder step, measured from the gold answer keys of the
#: three benchmark families (Noto Sans SC CJK stroke-width ratios):
#: 300->400 = 1.33, 400->500 = 1.11, 500->700 = 1.23, 700->900 = 1.15.
#: Ink scales with stroke width, so these convert an ink ratio into a weight.
_INK_STEP_MULTIPLIER: dict[tuple[int, int], float] = {
    (300, 400): 1.33,
    (400, 500): 1.11,
    (500, 700): 1.23,
    (700, 900): 1.15,
}


def _normalize_font_weight(value: Any) -> int | None:
    """Map a design weight (``"normal"`` / ``"bold"`` / ``300`` / ``"700"``).

    Returns:
        The nearest ladder value, or ``None`` when the value is unreadable.
    """
    if isinstance(value, (int, float)):
        numeric = float(value)
    else:
        text = str(value or "").strip().lower()
        if not text:
            return None
        if text in {"normal", "regular"}:
            return 400
        if text in {"bold", "bolder"}:
            return 700
        if text in {"lighter", "light"}:
            return 300
        try:
            numeric = float(text)
        except ValueError:
            return None
    return min(_WEIGHT_LADDER, key=lambda step: abs(step - numeric))


def measure_element_rotation(
    image: Any,
    bbox: Any,
    *,
    pad: int = 8,
    search: float = 15.0,
    step: float = 0.25,
    dead_zone: float = 2.5,
    threshold: int = 60,
) -> dict[str, Any] | None:
    """Measure how far a text block is tilted, in degrees counter-clockwise.

    Deskew by projection profile: rotate the ink mask over a range of angles
    and keep the one whose row sums are the most uneven.  Text lines become
    sharp peaks exactly when their baselines are horizontal, so the peak
    variance sits at the correction angle.  The reported tilt is the negation
    of that correction, which also puts it in the sign convention Figma's
    ``rotation`` property uses -- so a rotated node can be written without
    flipping the sign again.

    Why not the obvious estimators, both measured on dark-card-grid:

    * ``cv2.minAreaRect`` over the ink returns **0.0°** for ``5.8折`` (truth
      6.0°): that element spans two tilted lines, and the union of two
      parallel tilted lines is nearly square, so the minimum-area rectangle
      locks onto the axis-aligned hull.
    * The ink's second moments have the same problem -- the cross-line spread
      dominates the along-line spread at this aspect ratio.

    The dead zone matters more than the precision: upright text scores a
    best angle of 1-2° from anti-aliasing alone.  On 218 measured texts across
    the three families, only the two tilted badges clear 2.5°, so the zone is
    where the noise floor actually is, not a tuned constant.

    Args:
        image: ``(h, w, 3)`` RGB array.
        bbox: ``[x, y, width, height]`` in source pixels.
        pad: Pixels searched around the box; the box itself may clip glyphs.
        search: Half-width of the angle sweep, in degrees.
        step: Sweep resolution, in degrees.
        dead_zone: Tilts below this are reported as ``0.0``.
        threshold: Channel distance from the local background that counts as
            ink.

    Returns:
        ``{"angle", "raw", "gain", "ink"}`` -- ``angle`` after the dead zone,
        ``raw`` before it, ``gain`` the variance improvement of the best angle
        over zero, ``ink`` the ink pixel count.  ``None`` when the box holds
        too little ink to measure.
    """
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    x, y, box_w, box_h = (float(value) for value in list(bbox)[:4])
    left, top = max(0, int(x) - pad), max(0, int(y) - pad)
    right = min(width, int(x + box_w) + pad)
    bottom = min(height, int(y + box_h) + pad)
    if right - left < 8 or bottom - top < 8:
        return None
    window = image[top:bottom, left:right]
    colors, counts = np.unique(window.reshape(-1, 3), axis=0, return_counts=True)
    background = colors[int(counts.argmax())].astype(np.int16)
    ink = (np.abs(window - background).max(axis=2) > threshold).astype(np.float32)
    ink_count = int(ink.sum())
    if ink_count < 30:
        return None

    rows, columns = ink.shape
    centre = (columns / 2.0, rows / 2.0)

    def _score(angle: float) -> float:
        matrix = cv2.getRotationMatrix2D(centre, angle, 1.0)
        rotated = cv2.warpAffine(
            ink, matrix, (columns, rows), flags=cv2.INTER_LINEAR, borderValue=0
        )
        return float(rotated.sum(axis=1).var())

    zero = _score(0.0)
    best = (-1.0, 0.0)
    angle = -search
    while angle <= search + 1e-9:
        score = _score(angle)
        if score > best[0]:
            best = (score, angle)
        angle += step
    # cv2's sweep angle is the rotation that *levels* the block, so the block's
    # own tilt is its negation.
    raw = -round(best[1], 2)
    return {
        "angle": 0.0 if abs(raw) < dead_zone else raw,
        "raw": raw,
        "gain": round(best[0] / zero, 3) if zero > 0 else 0.0,
        "ink": ink_count,
    }


def _ink_stats(
    image: Any,
    bbox: Any,
    *,
    inset: int = 3,
    threshold: int = 50,
) -> dict[str, int] | None:
    """Ink count and ink extent inside ``bbox``, theme agnostic.

    Unlike :func:`_contrast_ink_pixel_count` this takes a preloaded array: a
    page-wide pass over every text owner would otherwise re-decode the PNG
    hundreds of times.

    Args:
        image: ``(h, w, 3)`` RGB array.
        bbox: ``[x, y, width, height]`` in source pixels.
        inset: Border skip, so a box edge never counts as ink.
        threshold: Channel distance from the local background median.

    Returns:
        ``{count, width, height}`` or ``None`` when the box has no ink.
    """
    import numpy as np

    height, width = image.shape[:2]
    x, y, box_w, box_h = (int(round(float(value))) for value in list(bbox)[:4])
    left, top = max(0, x + inset), max(0, y + inset)
    right, bottom = min(width, x + box_w - inset), min(height, y + box_h - inset)
    if right <= left or bottom <= top:
        return None
    region = image[top:bottom, left:right]
    if region.size == 0:
        return None
    background = np.median(region.reshape(-1, 3), axis=0)
    mask = np.max(np.abs(region - background), axis=2) > threshold
    count = int(mask.sum())
    if count == 0:
        return None
    rows, columns = np.where(mask)
    return {
        "count": count,
        "width": int(columns.max() - columns.min() + 1),
        "height": int(rows.max() - rows.min() + 1),
    }


def _weight_for_ink_ratio(current: int, ratio: float) -> int:
    """Ladder weight whose predicted ink best matches ``ratio`` (rendered/source).

    The mapping is deliberately not "one step per round": calibration applies
    once per run, so a 400-weight owner whose source is Bold must be able to
    jump two steps instead of converging over multiple runs.

    Args:
        current: Current ladder weight.
        ratio: ``rendered_ink / source_ink`` (>1 means the render is too heavy).

    Returns:
        The ladder weight minimising the log-distance between predicted and
        required ink multiplier.
    """
    import math

    if ratio <= 0:
        return current
    needed = 1.0 / ratio
    best, best_cost = current, abs(math.log(needed))
    index = _WEIGHT_LADDER.index(current)

    cumulative = 1.0
    for position in range(index, len(_WEIGHT_LADDER) - 1):
        step = (_WEIGHT_LADDER[position], _WEIGHT_LADDER[position + 1])
        cumulative *= _INK_STEP_MULTIPLIER.get(step, 1.2)
        cost = abs(math.log(cumulative / needed))
        if cost < best_cost:
            best, best_cost = _WEIGHT_LADDER[position + 1], cost

    cumulative = 1.0
    for position in range(index, 0, -1):
        step = (_WEIGHT_LADDER[position - 1], _WEIGHT_LADDER[position])
        cumulative /= _INK_STEP_MULTIPLIER.get(step, 1.2)
        cost = abs(math.log(cumulative / needed))
        if cost < best_cost:
            best, best_cost = _WEIGHT_LADDER[position - 1], cost
    return best


def _element_source_bbox(element: Mapping[str, Any]) -> list[float] | None:
    """Source-pixel bbox of an element, preferring the style evidence.

    ``styleEvidence.evidence.source_bbox`` is measured on the screenshot, so it
    is always in source pixels.  The fallback (``x``/``y``/``width``/``height``)
    is the design canvas, which is in the same space for the fixed-canvas path
    but should not be trusted when evidence exists.
    """
    evidence = element.get("styleEvidence")
    values = evidence.get("evidence") if isinstance(evidence, Mapping) else None
    if isinstance(values, Mapping):
        candidate = values.get("source_bbox")
        if isinstance(candidate, (list, tuple)) and len(candidate) == 4:
            return [float(value) for value in candidate]
    if all(isinstance(element.get(key), (int, float)) for key in ("x", "y", "width", "height")):
        return [
            float(element["x"]),
            float(element["y"]),
            float(element["width"]),
            float(element["height"]),
        ]
    return None


def apply_display_weight_by_scale(
    design: Mapping[str, Any],
    *,
    display_threshold: float = 1.8,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Promote display-scale text to Bold, using only the page's own size system.

    Why this exists: both pixel routes to weight were measured dead ends
    (``docs/v2_mentor/20261110_font_weight_evidence.md`` §2-§5) -- a static
    stroke index drifts ±55 % with box geometry, and rendered-vs-source ink
    density carries font substitution more strongly than weight.  What remains
    is typography: a page states its hierarchy in *relative* size, and body
    text is the modal size by definition.

    The rule reads nothing but the design itself -- no text matching, no
    per-sample constants:

    * ``body`` = the modal font size across the page's text owners;
    * a text at ``>= display_threshold x body`` is display-scale (by the usual
      type-scale convention h1 ~ 2x, h2 ~ 1.5x body) and is promoted to Bold;
    * only owners currently at 400 are promoted, so an explicit Light decision
      from another strategy is never overridden.

    ``display_threshold`` is deliberately conservative, and the free-text
    filter is what makes it safe.  Measured on the three families
    (perception-frozen rerun, style_mm mismatches): without the filter, 1.8
    still promoted the light-table placeholders ``(选填)`` / ``请输入0~``
    (their ``fontSize`` is inflated from the input-box height, 48.5-78.75) and
    regressed within30 94.07 -> 93.68.  With the filter, light-table and
    light-form have **zero** candidates and stay neutral, while dark moves
    24/39 -> 19/39.

    The threshold is a type-scale convention, but its exact value is fitted on
    three samples -- treat a new families' result as unproven until it has its
    own gold frame.

    Args:
        design: Image design with ``elements`` carrying ``style.fontSize``.
        display_threshold: Multiple of the page's body size to count as display.

    Returns:
        ``(calibrated_design, report)``.
    """
    from collections import Counter

    calibrated = copy.deepcopy(dict(design))
    elements = [
        element
        for element in calibrated.get("elements") or []
        if isinstance(element, dict) and element.get("type") == "text"
    ]

    def _is_free_text(element: Mapping[str, Any]) -> bool:
        """Table cells inherit table geometry; they are not display type."""
        content_ref = str(element.get("contentRef") or "")
        role = str((element.get("imageMVP") or {}).get("role") or "")
        return not (
            content_ref.startswith(("table-cell:", "table-header:"))
            or role in {"table-cell", "table-header", "control"}
        )

    free_text = [element for element in elements if _is_free_text(element)]
    sizes = [
        round(float(element["style"]["fontSize"]), 1)
        for element in free_text
        if isinstance(element.get("style"), Mapping)
        and isinstance(element["style"].get("fontSize"), (int, float))
        and float(element["style"]["fontSize"]) > 0
    ]
    if len(sizes) < 3:
        return calibrated, {
            "schema_version": "grounding-display-weight/1.0",
            "status": "not-needed",
            "adjusted_count": 0,
            "adjustments": [],
        }
    body_size = Counter(sizes).most_common(1)[0][0]
    adjustments: list[dict[str, Any]] = []
    skipped_roles = 0
    for element in elements:
        style = element.get("style")
        if not isinstance(style, dict):
            continue
        # Only free text can be display type.  Table cells inherit table
        # geometry -- on light-table the placeholders "(选填)" / "请输入0~"
        # carry an inflated fontSize (48.5, 77, 78.75) derived from the input
        # box height, and promoting them regressed within30 (93.68 < 94.07).
        # The role is structural evidence, not a text pattern.
        content_ref = str(element.get("contentRef") or "")
        role = str((element.get("imageMVP") or {}).get("role") or "")
        if content_ref.startswith(("table-cell:", "table-header:")) or role in {
            "table-cell",
            "table-header",
            "control",
        }:
            skipped_roles += 1
            continue
        size = style.get("fontSize")
        if not isinstance(size, (int, float)) or body_size <= 0:
            continue
        ratio = float(size) / body_size
        if ratio < display_threshold:
            continue
        if _normalize_font_weight(style.get("fontWeight")) != 400:
            continue
        style["fontWeight"] = 700
        adjustments.append(
            {
                "contentRef": element.get("contentRef") or None,
                "text": str(element.get("text") or "")[:48],
                "fontSize": round(float(size), 2),
                "bodySize": body_size,
                "scale": round(ratio, 3),
                "previous": 400,
                "updated": 700,
            }
        )
    return calibrated, {
        "schema_version": "grounding-display-weight/1.0",
        "status": "applied" if adjustments else "not-needed",
        "body_size": body_size,
        "display_threshold": display_threshold,
        "adjusted_count": len(adjustments),
        "skipped_non_free_text": skipped_roles,
        "adjustments": adjustments,
    }



def drop_text_fragment_images(
    design: Mapping[str, Any],
    *,
    overlap_ratio: float = 0.3,
    height_band: tuple[float, float] = (0.5, 1.6),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Remove small crops that are fragments of the text beside them.

    The asset pass crops what the detector box surrounds, and the box does not
    know about glyphs: a 102x43 crop of a logo carries the first letters of the
    label next to it.  The label is emitted as text too, so the two copies stack
    and the render reads ``QweQwen3.8 Flash``, ``Kimii`` or ``勾行成功``.

    A crop is a fragment of a text run when all of these hold:

    * it is narrower than the run and its right edge falls inside the run's
      horizontal span -- a badge or button background surrounds its label, so
      it ends past the text, and a full-bleed image is wider than any label;
    * the boxes overlap by at least ``overlap_ratio`` of the smaller one;
    * both sit on the same line, i.e. their height ratio stays inside
      ``height_band`` (a 43 px crop of a 20 px price is not the same run).

    Dropping keeps the complete text and costs any icon the same crop carried.
    No structural signal separates "icon" from "icon plus three letters" inside
    one crop, and doubled glyphs read far worse than a missing mark.

    Returns:
        ``(calibrated_design, report)``.
    """
    calibrated = copy.deepcopy(dict(design))
    elements = [
        element
        for element in calibrated.get("elements") or []
        if isinstance(element, dict)
    ]
    texts = [
        element
        for element in elements
        if str(element.get("type") or "") in {"text", "button", "input"}
        and str(element.get("text") or "").strip()
        and float(element.get("width") or 0) > 0
        and float(element.get("height") or 0) > 0
    ]
    dropped: list[dict[str, Any]] = []
    remove_ids: set[int] = set()
    for element in elements:
        if str(element.get("type") or "") != "image":
            continue
        try:
            image_box = _box_of(element)
        except (TypeError, ValueError):
            continue
        image_w = image_box[2] - image_box[0]
        image_h = image_box[3] - image_box[1]
        if image_w <= 0 or image_h <= 0:
            continue
        best: tuple[float, dict[str, Any]] | None = None
        for text in texts:
            if id(text) in remove_ids:
                continue
            try:
                text_box = _box_of(text)
            except (TypeError, ValueError):
                continue
            text_w = text_box[2] - text_box[0]
            text_h = text_box[3] - text_box[1]
            if text_w <= 0 or text_h <= 0:
                continue
            if image_w >= text_w or image_box[2] >= text_box[2]:
                continue
            ratio = max(image_h / text_h, text_h / image_h)
            if ratio < height_band[0] or ratio > height_band[1]:
                continue
            overlap_w = min(image_box[2], text_box[2]) - max(image_box[0], text_box[0])
            overlap_h = min(image_box[3], text_box[3]) - max(image_box[1], text_box[1])
            if overlap_w <= 0 or overlap_h <= 0:
                continue
            overlap = overlap_w * overlap_h
            smaller = min(image_w * image_h, text_w * text_h)
            covered = overlap / smaller
            if covered < overlap_ratio:
                continue
            if best is None or covered > best[0]:
                best = (covered, text)
        if best is None:
            continue
        covered, text = best
        remove_ids.add(id(element))
        dropped.append(
            {
                "contentRef": element.get("contentRef") or None,
                "bbox": [round(value, 1) for value in image_box],
                "overlapped_text": str(text.get("text") or "")[:48],
                "overlap_ratio": round(covered, 3),
            }
        )
    if dropped:
        calibrated["elements"] = [
            element for element in elements if id(element) not in remove_ids
        ]
    return calibrated, {
        "schema_version": "grounding-fragment-image/1.0",
        "status": "applied" if dropped else "not-needed",
        "adjusted_count": len(dropped),
        "dropped": dropped,
    }


def _box_of(element: Mapping[str, Any]) -> tuple[float, float, float, float]:
    """``(left, top, right, bottom)`` of a design element."""
    x = float(element.get("x") or 0)
    y = float(element.get("y") or 0)
    return (x, y, x + float(element.get("width") or 0), y + float(element.get("height") or 0))


def synthesize_badge_outline(
    design: Mapping[str, Any],
    image_path: str | Path,
    *,
    pad: int = 24,
    max_area_ratio: float = 3.0,
    saturation_threshold: int = 60,
    background_distance: int = 60,
    label_ink_share: float = 0.03,
    margin_ratio: float = 0.9,
    min_label_coverage: float = 0.5,
    min_badge_tilt: float = 2.5,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Swap a badge crop that carries its own label for a drawn outline.

    ``6.6折`` / ``8.5折`` on dark-card-grid are red rounded outlines, and the
    detector box around one is 153x43 while the outline is 105x44: the box is
    wider than the label but *shorter* than the badge, so the crop clips the
    top and bottom edges and bakes the glyphs in.  The label is emitted natively
    too, so the render stacks two copies 2 px apart -- the ghosting the pixel
    gates cannot see because both copies sit inside the tolerance.

    ``drop_text_fragment_images`` cannot fire here: it requires the crop to be
    *narrower* than the label, on the reasoning that a badge surrounds its
    label.  That assumption breaks exactly when the crop overshoots sideways
    and undershoots vertically.

    What separates "badge with baked label" from any other crop is pixel
    evidence, not geometry:

    * one accent colour draws a **thin closed outline** around the label --
      measured as a vertical run left of the label, a vertical run right of it,
      and a horizontal run above it, all the same colour;
    * that same accent colour also shows up **inside** the label box, i.e. the
      glyphs were baked into the crop.

    Both must hold.  A filled plate (``控制台``) has no thin outline; a card
    photo has no accent inside the label; an icon beside a label has no
    outline around it.

    The replacement keeps what the crop was carrying -- outline colour, stroke
    width, corner radius and interior fill -- and loses what it was faking
    (the baked glyphs).  Gradients and inner shadows are *not* reproduced:
    none of the measured badges have them, and inventing them would be a
    constant rather than an inference.  A badge whose interior is the accent
    colour (white text on a solid pill) is refused and recorded: that shape has
    no evidence yet, so it has no rule.

    Every refused candidate lands in the report with the check that refused it,
    so a run can answer "why was this one left alone" without a re-run.

    Args:
        design: Image design with ``elements`` and ``canvas``.
        image_path: Source screenshot the outline colours are read from.  The
            crop itself is not used: it is clipped, so its own pixels cannot
            recover the missing edges.
        pad: Minimum pixels searched around the label box on each side.
        max_area_ratio: Largest crop-to-label area ratio still treated as "a
            frame around the label".  light-form's 1744x448 container holds a
            whole table (ratio > 50) and must never be replaced.
        saturation_threshold: ``max(rgb) - min(rgb)`` above which a pixel
            counts as coloured rather than neutral.
        background_distance: Per-channel distance from the window's background
            that counts as "not background".
        label_ink_share: Share of the label box that must be accent-coloured
            for the glyphs to count as baked into the crop.  Measured 0.27.
        margin_ratio: How far the outline may sit from the label, relative to
            the label's longer side.  Stops a card border enclosing the badge
            from being mistaken for the badge.
        min_label_coverage: Share of the label's box the crop must contain.
            A tilted badge's crop clips the block it surrounds, so enclosure is
            too strong a requirement (measured: 74 % coverage on 5.8折).
        min_badge_tilt: Tilt below which the replacement is left axis-aligned.
            Same dead zone as ``text-rotation``: upright outlines measure 0.00
            degrees, the tilted ones 6.02.

    Returns:
        ``(calibrated_design, report)``.  Each applied badge is replaced in
        place, so the element keeps its id and its paint order.
    """
    import numpy as np
    from PIL import Image

    calibrated = copy.deepcopy(dict(design))
    report: dict[str, Any] = {
        "schema_version": "grounding-badge-outline/1.0",
        "status": "not-needed",
        "adjusted_count": 0,
        "badges": [],
        "skipped": [],
    }
    elements = [
        element
        for element in calibrated.get("elements") or []
        if isinstance(element, dict)
    ]
    labels = [
        element
        for element in elements
        if str(element.get("type") or "") in {"text", "button"}
        and str(element.get("text") or "").strip()
        and float(element.get("width") or 0) > 0
        and float(element.get("height") or 0) > 0
    ]
    if not labels:
        return calibrated, report
    try:
        with Image.open(image_path) as handle:
            pixels = np.asarray(handle.convert("RGB")).astype(np.int16)
    except (OSError, ValueError):
        return calibrated, report
    additions: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for element in elements:
        if str(element.get("type") or "") != "image":
            continue
        try:
            crop = _box_of(element)
        except (TypeError, ValueError):
            continue
        crop_w = crop[2] - crop[0]
        crop_h = crop[3] - crop[1]
        if crop_w <= 0 or crop_h <= 0:
            continue
        for label in labels:
            try:
                label_box = _box_of(label)
            except (TypeError, ValueError):
                continue
            label_w = label_box[2] - label_box[0]
            label_h = label_box[3] - label_box[1]
            if label_w <= 0 or label_h <= 0:
                continue
            # Coverage, not enclosure: the detector box around a tilted badge
            # clips the block it surrounds -- 5.8折's crop stops 27 px above the
            # label box's bottom -- so requiring the whole label inside leaves
            # out exactly the badge that needs this most.  What the rule needs
            # is that the crop carries most of the label (half its area and its
            # centre), which a neighbouring element's box never does.
            overlap_w = min(crop[2], label_box[2]) - max(crop[0], label_box[0])
            overlap_h = min(crop[3], label_box[3]) - max(crop[1], label_box[1])
            if overlap_w <= 0 or overlap_h <= 0:
                continue
            if overlap_w * overlap_h < min_label_coverage * label_w * label_h:
                continue
            if not (
                crop[0] <= (label_box[0] + label_box[2]) / 2 <= crop[2]
                and crop[1] <= (label_box[1] + label_box[3]) / 2 <= crop[3]
            ):
                continue
            # From here the crop does hold the label, so a refusal is worth a
            # record: these are the candidates a reader would expect to see.
            if crop_w <= label_w:
                # fragment-image's case, not this one: this rule is for a badge
                # that surrounds the label but is clipped vertically.
                report["skipped"].append(
                    {
                        "text": str(label.get("text") or "")[:24],
                        "crop_bbox": [round(value, 1) for value in crop],
                        "reason": "crop is not wider than the label",
                    }
                )
                continue
            if crop_w * crop_h / (label_w * label_h) > max_area_ratio:
                # Coarse shape filter, not a judgement: a container holding a
                # whole table would otherwise add one entry per label inside it
                # (20 on light-form) without telling anyone anything.
                continue
            ring, reason = _badge_ring(
                pixels,
                label_box,
                # The window has to hold the badge, which is wider than its own
                # label by a margin no fixed constant covers (46 px above the
                # label box here).  The scan may go further: it only follows
                # pixels of the outline's own colour, so an unrelated element
                # cannot be reached by accident.
                window_pad=max(pad, int(0.6 * max(label_w, label_h))),
                scan_limit=max(pad, int(margin_ratio * max(label_w, label_h))),
                saturation_threshold=saturation_threshold,
                background_distance=background_distance,
                label_ink_share=label_ink_share,
                margin_ratio=margin_ratio,
            )
            if ring is None:
                report["skipped"].append(
                    {
                        "text": str(label.get("text") or "")[:24],
                        "crop_bbox": [round(value, 1) for value in crop],
                        "reason": reason,
                    }
                )
                continue
            element["type"] = "rectangle"
            element.pop("imageBase64", None)
            element["text"] = ""
            element["role"] = "badge-outline"
            element["name"] = "badge-outline"
            element["contentRef"] = None
            element["paintDepth"] = 0
            # The ring scan reports where the strokes cross the label's centre
            # row and column, i.e. the outline's *own* box -- on a tilted badge
            # that is the badge, not its bounding box, so the measured size goes
            # straight into width/height and `rotation` puts it back in place.
            # (Undoing the rotation arithmetically, as an earlier attempt did,
            # shrinks a box that was never inflated: 152 px became 136.)
            tilt = float(ring["tilt"])
            if abs(tilt) < min_badge_tilt:
                tilt = 0.0
            shapes = ring["rings"]
            extras: list[dict[str, Any]] = []
            for index, shape in enumerate(shapes):
                if index == 0:
                    target = element
                else:
                    # A second concentric stroke is part of the badge itself,
                    # so it becomes its own vector node instead of being lost.
                    target = {
                        "id": f"{element.get('id')}:ring{index}",
                        "type": "rectangle",
                        "text": "",
                        "role": "badge-outline",
                        "name": "badge-outline",
                        "contentRef": None,
                        "paintDepth": 0,
                    }
                    extras.append(target)
                left, top, right, bottom = (float(value) for value in shape["bbox"])
                target["x"] = left
                target["y"] = top
                target["width"] = right - left
                target["height"] = bottom - top
                target["style"] = {
                    "fillColor": ring["fill"],
                    "borderColor": ring["accent"],
                    "borderWidth": shape["stroke"],
                    "borderRadius": shape["radius"],
                }
                if tilt:
                    target["rotation"] = tilt
                else:
                    target.pop("rotation", None)
            if extras:
                additions.append((element, extras))
            report["badges"].append(
                {
                    "id": element.get("id"),
                    "text": str(label.get("text") or "")[:24],
                    "crop_bbox": [round(value, 1) for value in crop],
                    "bbox": [float(value) for value in shapes[0]["bbox"]],
                    "stroke": shapes[0]["stroke"],
                    "radius": shapes[0]["radius"],
                    "rings": [
                        {
                            "bbox": [float(value) for value in shape["bbox"]],
                            "stroke": shape["stroke"],
                            "radius": shape["radius"],
                        }
                        for shape in shapes
                    ],
                    "fillColor": ring["fill"],
                    "borderColor": ring["accent"],
                    "rotation": round(tilt, 2),
                    "deskewed": bool(ring.get("deskewed")),
                    "ring_fill_ratio": round(float(ring["ring_fill_ratio"]), 3),
                    "label_ink_share": round(float(ring["label_ink_share"]), 3),
                }
            )
            break
    # Inserted after the pass, by identity, because splicing during the loop
    # would make it visit the elements it just created.
    for anchor, extras in reversed(additions):
        position = elements.index(anchor) + 1
        elements[position:position] = extras
    if report["badges"]:
        calibrated["elements"] = elements
        report["status"] = "applied"
        report["adjusted_count"] = len(report["badges"])
    return calibrated, report


def _run_near(line: Any, start: int, step: int, limit: int) -> tuple[int, int] | None:
    """First ``True`` run in ``line`` from ``start`` stepping by ``step``.

    Args:
        line: One-dimensional boolean row or column of the accent mask.
        start: Index to begin at; it may already be ``True``.
        step: ``-1`` to scan left/up, ``+1`` to scan right/down.
        limit: How many pixels to step before giving up.

    Returns:
        Inclusive ``(low, high)`` index range of the run, or ``None``.
    """
    position = start
    for _ in range(limit + 1):
        if not 0 <= position < line.size:
            return None
        if line[position]:
            inner = position
            following = position + step
            while 0 <= following < line.size and line[following]:
                inner = following
                following += step
            return (min(position, inner), max(position, inner))
        position += step
    return None


def _run_through(line: Any, anchor: int) -> tuple[int, int] | None:
    """Inclusive range of the ``True`` run of ``line`` containing ``anchor``."""
    if not 0 <= anchor < line.size or not line[anchor]:
        return None
    low = anchor
    while low - 1 >= 0 and line[low - 1]:
        low -= 1
    high = anchor
    while high + 1 < line.size and line[high + 1]:
        high += 1
    return (low, high)


def _median_int(values: list[int]) -> int:
    """Median of a small integer list, always rounded to an ``int``."""
    ordered = sorted(values)
    return int(ordered[len(ordered) // 2])


def _hex_colour(value: Any) -> str:
    """``#RRGGBB`` for an ``(r, g, b)`` triple."""
    red, green, blue = (int(channel) for channel in value[:3])
    return f"#{red:02X}{green:02X}{blue:02X}"


def _runs_outward(line: Any, start: int, step: int, limit: int) -> list[tuple[int, int]]:
    """Every ``True`` run found walking outward from ``start``, nearest first.

    ``_run_near`` stops at the first run it meets.  That is right for a single
    stroke and wrong for a badge drawn with two concentric ones: it returns the
    inner frame, so a box built from "nearest on each axis" mixes the inner
    frame's width with the outer frame's height -- measured 132x152 on a badge
    that is 152x152, with a 61 px corner radius instead of 15.

    Args:
        line: One-dimensional boolean row or column.
        start: Index to begin at; it may already be ``True``.
        step: ``-1`` to walk left/up, ``+1`` to walk right/down.
        limit: How many pixels to cover before giving up.

    Returns:
        Inclusive ``(low, high)`` runs, nearest first.
    """
    runs: list[tuple[int, int]] = []
    position = start
    for _ in range(limit + 1):
        if not 0 <= position < line.size:
            break
        if line[position]:
            run = _run_through(line, position)
            runs.append(run)
            position = run[0] - 1 if step < 0 else run[1] + 1
        else:
            position += step
    return runs


def _neighbour_gap(runs: list[tuple[int, int]]) -> int | None:
    """Largest gap between neighbouring runs, or ``None`` when they overlap."""
    ordered = sorted(runs)
    widest = 0
    for near, far in zip(ordered, ordered[1:]):
        gap = far[0] - near[1] - 1
        if gap < 0:
            return None
        widest = max(widest, gap)
    return widest


def _span_length(line: Any, anchor: int, fallback: tuple[int, int]) -> int:
    """Length of the run of ``line`` containing ``anchor``, else ``fallback``'s."""
    run = _run_through(line, anchor) if 0 <= anchor < line.size else None
    if run is None:
        run = fallback
    return int(run[1] - run[0] + 1)


def _rotate_point(
    x: float, y: float, centre_x: float, centre_y: float, degrees: float
) -> tuple[float, float]:
    """Rotate a point about a pivot; positive ``degrees`` is counter-clockwise.

    Screen coordinates, so y grows downward and the sine term flips: this is the
    same convention as ``rotation`` in the design and in Figma.
    """
    radians = math.radians(degrees)
    cos_t, sin_t = math.cos(radians), math.sin(radians)
    dx, dy = x - centre_x, y - centre_y
    return (centre_x + dx * cos_t + dy * sin_t, centre_y - dx * sin_t + dy * cos_t)


def _deskew_frame(
    window: Any, label_local: Any, tilt: float, background: Any, pad: int
) -> tuple[Any, tuple[float, float, float, float], tuple[float, float]]:
    """Rotate a window level, carrying the label box into the rotated frame.

    Measuring a tilted outline in axis-aligned coordinates fails in a way that
    looks like a geometry bug: the topmost row of a rotated rounded rectangle
    touches one corner, so "where does the straight edge begin on this row"
    answers with half the width (61 px on a 15 px corner).  Levelling first is
    the only way to read the radius, the stroke and the own size off the shape.

    Args:
        window: ``(h, w, 3)`` pixels around the badge.
        label_local: Label box in ``window`` coordinates.
        tilt: The frame's tilt in degrees, counter-clockwise positive.
        background: Fill colour for the padded border.
        pad: Pixels added on every side so the rotated corners are not clipped.

    Returns:
        ``(pixels, label_box, pivot)`` where ``pivot`` is the rotation centre in
        the padded frame (needed to map measurements back).
    """
    import numpy as np
    from PIL import Image

    canvas = np.empty(
        (window.shape[0] + 2 * pad, window.shape[1] + 2 * pad, 3), dtype=np.int16
    )
    canvas[:, :] = background
    canvas[pad : pad + window.shape[0], pad : pad + window.shape[1]] = window
    height, width = canvas.shape[:2]
    pivot = (width / 2, height / 2)
    rotated = Image.fromarray(canvas.astype(np.uint8)).rotate(
        -tilt,
        resample=Image.BICUBIC,
        center=pivot,
        fillcolor=tuple(int(channel) for channel in background),
    )
    box = (
        label_local[0] + pad,
        label_local[1] + pad,
        label_local[2] + pad,
        label_local[3] + pad,
    )
    corners = [
        (box[0], box[1]),
        (box[2], box[1]),
        (box[2], box[3]),
        (box[0], box[3]),
    ]
    moved = [_rotate_point(x, y, pivot[0], pivot[1], -tilt) for x, y in corners]
    return (
        np.asarray(rotated).astype(np.int16),
        (
            min(x for x, _ in moved),
            min(y for _, y in moved),
            max(x for x, _ in moved),
            max(y for _, y in moved),
        ),
        pivot,
    )


def _ring_tilt(same: Any, top: int, left: int, right: int) -> float:
    """Tilt of an outline's top edge in degrees, counter-clockwise positive.

    Fitted on the middle of the edge, away from the rounded corners.  This is
    the measurement a badge needs: the row-variance estimator scores the *text*
    inside the frame and reads 6.75 degrees on a badge tilted 6.00, while the
    frame's own edge reproduces 6.02 on both tilted badges and 0.00 on the
    upright ones.

    Args:
        same: Boolean mask of pixels matching the outline's colour.
        top: Row the outline's top edge sits on, in ``same`` coordinates.
        left: Left edge column, in ``same`` coordinates.
        right: Right edge column, in ``same`` coordinates.

    Returns:
        Degrees, or ``0.0`` when the edge is too short to fit or touches
        something above it (a clipped edge has no slope to measure).
    """
    import numpy as np

    span = right - left
    if span < 24:
        return 0.0
    inset = int(round(0.2 * span))
    band_top = max(0, top - 4)
    band_bottom = min(same.shape[0], top + max(16, int(0.2 * span)))
    columns: list[int] = []
    rows: list[int] = []
    for column in range(max(0, left + inset), min(same.shape[1], right - inset + 1)):
        starts = np.flatnonzero(same[band_top:band_bottom, column])
        if starts.size == 0 or int(starts[0]) == 0:
            # Either nothing here or something accent-coloured above the edge:
            # both mean this column cannot report where the edge starts.
            continue
        columns.append(column)
        rows.append(band_top + int(starts[0]))
    if len(columns) < 12:
        return 0.0
    slope = float(
        np.polyfit(
            np.asarray(columns, dtype=float), np.asarray(rows, dtype=float), 1
        )[0]
    )
    return round(math.degrees(math.atan(-slope)), 2)


def _badge_ring(
    pixels: Any,
    label_box: tuple[float, float, float, float],
    *,
    window_pad: int,
    scan_limit: int,
    saturation_threshold: int,
    background_distance: int,
    label_ink_share: float,
    margin_ratio: float,
    min_deskew_tilt: float = 1.5,
    _deskewed: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    """Measure the thin outline(s) drawn around ``label_box``, if there is one.

    Scans outward from the label instead of labelling connected components:
    ``scipy`` is not a declared dependency, and the directional evidence -- a
    vertical bar left of the label, one right of it, a horizontal bar above it,
    all one colour -- is what "closed outline" means anyway.

    **The outline is the outermost stroke.**  These badges are drawn with two
    concentric frames (dark-card-grid's large one: 6 px outside, 4 px gap, 3 px
    inside), so ``_run_near``'s nearest-run answer measures the *inner* frame
    while the top/bottom scan measures the *outer* one.  That mixed box is the
    132x152 reading that made a previous attempt draw an ellipse.  Rings are
    returned outer-first and each one is measured consistently.

    Frames a few pixels apart are one badge; frames tens of pixels apart are
    two elements.  The gap between neighbouring strokes must therefore stay of
    the same order as the strokes themselves, which is what keeps a card border
    or a sibling badge from being absorbed into this one.

    The vertical extent comes from the middle column, not from the left bar.
    Scanning the left bar's own column looks like the better ruler -- a bar
    should span the full height -- but that column sits inside the rounded
    corner, so it starts one radius below the real top edge (measured 1298
    against a true 1292, i.e. 6 px short of a 44 px badge).  The label box is
    also not tight around its glyphs: on these badges the box bottom is the
    page bottom while the outline's bottom edge sits above it, so scanning
    below the label finds nothing at all.

    Every rejection carries a reason.  A rule that only answers "applied / not
    applied" cannot be reviewed afterwards, which is the failure this repo
    already paid for once (the OCR merge that silently swallowed 模型广场).

    Returns:
        ``(ring, reason)``.  ``ring`` is ``None`` when nothing was measured and
        ``reason`` says which check refused it; when ``ring`` is not ``None``
        the reason is empty.  ``ring`` holds ``rings`` (outer first, each with
        ``bbox`` in source pixels with right/bottom exclusive, ``stroke`` and
        ``radius``), ``tilt``, ``fill``, ``accent``, ``ring_fill_ratio`` and
        ``label_ink_share``.
    """
    import numpy as np

    lx0, ly0, lx1, ly1 = (float(value) for value in label_box)
    label_w = lx1 - lx0
    label_h = ly1 - ly0
    image_h, image_w = pixels.shape[:2]
    x0 = max(0, int(lx0) - window_pad)
    y0 = max(0, int(ly0) - window_pad)
    x1 = min(image_w, int(lx1) + window_pad)
    y1 = min(image_h, int(ly1) + window_pad)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None, "window too small"
    window = pixels[y0:y1, x0:x1]
    colors, counts = np.unique(window.reshape(-1, 3), axis=0, return_counts=True)
    background = colors[int(counts.argmax())].astype(np.int16)
    saturation = window.max(axis=2) - window.min(axis=2)
    distance = np.abs(window - background).max(axis=2)
    accent = (saturation > saturation_threshold) & (distance > background_distance)
    if accent.mean() < 0.01:
        return None, "no accent colour around the label"

    # The label's glyphs and the outline share one colour -- that is what makes
    # the label "baked in".  A crop with a coloured border but neutral glyphs
    # keeps failing here, which is why 控制台 (a filled light plate) is skipped.
    ink = accent[
        max(0, int(ly0) - y0) : max(1, int(ly1) - y0),
        max(0, int(lx0) - x0) : max(1, int(lx1) - x0),
    ]
    ink_share = float(ink.mean()) if ink.size else 0.0
    if ink_share < label_ink_share:
        return None, "label glyphs are not baked into the crop"

    colour = np.median(window[accent], axis=0).astype(np.int16)
    same = np.abs(window - colour).max(axis=2) <= 24
    # Which pixels count as "the stroke" depends on the frame.  On the source
    # screenshot a stroke's edge is one anti-aliased pixel wide, and matching the
    # colour within 24 finds the drawn width exactly (3 px for the small badges).
    # After the frame has been rotated for measurement the anti-aliased band is
    # wider, so the same tolerance eats a pixel off each side -- a 6 px stroke
    # reads 4, a 3 px stroke reads 1.  There the width is read at half coverage
    # instead, which is what a stroke's edge means geometrically rather than a
    # constant fitted to either case.
    measure = same
    if _deskewed:
        half = max(1, int(np.abs(colour - background).max()))
        measure = (np.abs(window - background).max(axis=2) * 2) >= half

    mid_row = min(same.shape[0] - 1, max(0, int((ly0 + ly1) / 2) - y0))
    left_runs = _runs_outward(same[mid_row], int(lx0) - x0 - 1, -1, scan_limit)
    if not left_runs:
        return None, "no bar left of the label"
    right_runs = _runs_outward(same[mid_row], int(lx1) - x0, 1, scan_limit)
    if not right_runs:
        return None, "no bar right of the label"
    for runs in (left_runs, right_runs):
        if len(runs) > 3:
            return None, "more than three accent bars on one side"
    gap_limit = max(6, 2 * max(high - low + 1 for low, high in left_runs + right_runs))
    for runs in (left_runs, right_runs):
        gap = _neighbour_gap(runs)
        if gap is None or gap > gap_limit:
            return None, "accent bars are too far apart to be one outline"

    left_ordered = sorted(left_runs)
    right_ordered = sorted(right_runs)
    # Count rings on the narrower side: a second bar on one side only is a
    # neighbour that happens to share the colour, not a second frame.
    ring_count = min(len(left_ordered), len(right_ordered))
    left_outer, left_inner = left_ordered[0]
    right_inner, right_outer = right_ordered[-1]
    if left_outer >= int(lx0) - x0 or right_outer <= int(lx1) - x0:
        return None, "bars do not straddle the label"

    middle_column = (left_outer + right_outer) // 2
    height = same.shape[0]
    column_runs = _runs_outward(same[:, middle_column], 0, 1, height - 1)
    if ring_count >= 2 and len(column_runs) >= 2 * ring_count:
        tops = [run[0] for run in column_runs[:ring_count]]
        bottoms = [run[1] for run in reversed(column_runs[-ring_count:])]
    else:
        if not column_runs:
            return None, "no top edge above the label"
        ring_count = 1
        tops = [column_runs[0][0]]
        # The bottom edge may be *outside* the screenshot: these badges sit on
        # the last row of the page, so their bottom border is clipped away and
        # the lowest run on the middle column is a glyph, not an edge (measured:
        # no bar at all below 1331, page bottom at 1336).  Taking the furthest
        # extent of either column handles both the clipped badge and the
        # ordinary one, where the middle column reaches the real bottom edge.
        bar_column = (left_outer + left_inner) // 2
        bottoms = [
            max(
                int(np.flatnonzero(same[:, bar_column]).max()),
                int(np.flatnonzero(same[:, middle_column]).max()),
            )
        ]

    if not tops[0] < mid_row < bottoms[0]:
        return None, "outline does not enclose the label"

    shapes: list[dict[str, Any]] = []
    for index in range(ring_count):
        left_low, left_high = left_ordered[index]
        right_low, right_high = right_ordered[-1 - index]
        top = tops[index]
        bottom = bottoms[index]
        ring_w = right_high - left_low + 1
        ring_h = bottom - top + 1
        if ring_w <= 0 or ring_h <= 0:
            return None, "empty outline box"
        thickness = [
            _span_length(measure[mid_row], left_low, (left_low, left_high)),
            _span_length(measure[mid_row], right_low, (right_low, right_high)),
        ]
        if index < len(column_runs) and column_runs[index][0] == top:
            thickness.append(
                _span_length(
                    measure[:, middle_column],
                    top,
                    (column_runs[index][0], column_runs[index][1]),
                )
            )
        stroke = _median_int(thickness)
        # A blob is rejected by its stroke, not by its fill ratio: scanning
        # outward from the label through a solid area returns a run as deep as
        # the blob, so a "stroke" wider than a quarter of the badge cannot be
        # an outline.
        if stroke > max(4, int(0.25 * min(ring_w, ring_h))):
            return None, "accent area too thick to be an outline"
        top_run = _run_through(same[top], middle_column)
        radius = max(0, top_run[0] - left_low) if top_run is not None else 0
        shapes.append(
            {
                "bbox": (
                    left_low + x0,
                    top + y0,
                    right_high + x0 + 1,
                    bottom + y0 + 1,
                ),
                "stroke": max(1, int(stroke)),
                "radius": int(min(radius, max(0, min(ring_w, ring_h) // 2))),
            }
        )

    outer = shapes[0]
    span_h = outer["bbox"][3] - outer["bbox"][1]
    if not 0.5 * label_h <= span_h <= 2.5 * label_h:
        return None, "outline height is not a badge height"
    label_centre = (ly0 + ly1) / 2 - y0
    if abs((tops[0] + bottoms[0]) / 2 - label_centre) > 0.6 * label_h:
        return None, "outline is not centred on the label"
    margin_limit = max(20.0, margin_ratio * max(label_w, label_h))
    margins = (
        int(lx0) - x0 - left_outer,
        right_outer - (int(lx1) - x0),
        int(ly0) - y0 - tops[0],
        bottoms[0] - (int(ly1) - y0),
    )
    if max(abs(value) for value in margins) > margin_limit:
        return None, "outline sits too far from the label"

    interior = window[
        tops[0] + outer["stroke"] + 2 : bottoms[0] - outer["stroke"] - 1,
        left_outer + outer["stroke"] + 2 : right_outer - outer["stroke"] - 1,
    ]
    if interior.size < 30:
        return None, "no interior to sample"
    fill_colors, fill_counts = np.unique(
        interior.reshape(-1, 3), axis=0, return_counts=True
    )
    fill = fill_colors[int(fill_counts.argmax())]
    if np.abs(fill.astype(np.int16) - colour).max() <= 24:
        # Interior is the accent colour: a solid pill, not an outline.  There is
        # no rule for that shape yet, so leave the crop alone rather than guess.
        return None, "interior is filled with the accent colour"
    tilt = _ring_tilt(same, tops[0], left_outer, right_outer)
    if not _deskewed and abs(tilt) >= min_deskew_tilt:
        # Measure the levelled frame instead of this one.  Everything above was
        # a yes/no screen (is this a thin closed outline at all); the numbers
        # that go into the drawing have to come from the shape's own axes.
        pad = int(math.ceil(0.25 * max(right_outer - left_outer, bottoms[0] - tops[0]))) + 4
        levelled, levelled_label, pivot = _deskew_frame(
            window,
            (lx0 - x0, ly0 - y0, lx1 - x0, ly1 - y0),
            tilt,
            background,
            pad,
        )
        refined, refusal = _badge_ring(
            levelled,
            levelled_label,
            window_pad=window_pad,
            scan_limit=scan_limit,
            saturation_threshold=saturation_threshold,
            background_distance=background_distance,
            label_ink_share=label_ink_share,
            margin_ratio=margin_ratio,
            min_deskew_tilt=min_deskew_tilt,
            _deskewed=True,
        )
        if refined is None:
            return None, refusal
        offset_x = x0 - pad
        offset_y = y0 - pad
        mapped = []
        for shape in refined["rings"]:
            left, top, right, bottom = shape["bbox"]
            centre_x, centre_y = _rotate_point(
                (left + right) / 2, (top + bottom) / 2, pivot[0], pivot[1], tilt
            )
            half_w = (right - left) / 2
            half_h = (bottom - top) / 2
            mapped.append(
                {
                    "bbox": (
                        centre_x - half_w + offset_x,
                        centre_y - half_h + offset_y,
                        centre_x + half_w + offset_x,
                        centre_y + half_h + offset_y,
                    ),
                    "stroke": shape["stroke"],
                    "radius": shape["radius"],
                }
            )
        return (
            {
                "rings": mapped,
                "tilt": tilt,
                "deskewed": True,
                "fill": refined["fill"],
                "accent": refined["accent"],
                "ring_fill_ratio": refined["ring_fill_ratio"],
                "label_ink_share": refined["label_ink_share"],
            },
            "",
        )

    ring_pixels = same[tops[0] : bottoms[0] + 1, left_outer : right_outer + 1]
    return (
        {
            "rings": shapes,
            "tilt": tilt,
            "deskewed": False,
            "fill": _hex_colour(fill),
            "accent": _hex_colour(colour),
            # Diagnostic only, and deliberately not a threshold: on a badge
            # carrying its own glyphs the outline and the glyphs share one
            # colour, so this ratio mixes "thin outline" with "how much text is
            # inside".  The exact separation is the interior check above.
            "ring_fill_ratio": float(ring_pixels.mean()),
            "label_ink_share": ink_share,
        },
        "",
    )


def apply_adjudicated_conflicts(
    design: Mapping[str, Any],
    decisions: list[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply frozen VLM conflict decisions (only entries marked ``apply``).

    The adjudicator refuses to drop a unique label, so every entry here names a
    string that occurs more than once on the page; removing the instance that
    sits in the conflict box loses nothing.  Decisions are read from disk, never
    recomputed inside the pipeline, so a run stays reproducible.
    """
    calibrated = copy.deepcopy(dict(design))
    elements = [
        element
        for element in calibrated.get("elements") or []
        if isinstance(element, dict)
    ]
    dropped: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    remove_ids: set[int] = set()
    for decision in decisions:
        status = str(decision.get("status") or "")
        box = decision.get("bbox") or [0, 0, 1, 1]
        if status == "move":
            text = str(
                decision.get("move_text")
                or decision.get("conflict")
                or decision.get("kept")
                or ""
            )
            target = decision.get("move_to") or []
            if not text or len(target) != 4:
                continue
            bx, by, bw, bh = (float(value) for value in box[:4])
            for element in elements:
                if id(element) in remove_ids:
                    continue
                if str(element.get("text") or "").strip() != text:
                    continue
                cx = float(element.get("x") or 0) + float(element.get("width") or 0) / 2
                cy = float(element.get("y") or 0) + float(element.get("height") or 0) / 2
                if not (bx - 8 <= cx <= bx + bw + 8 and by - 8 <= cy <= by + bh + 8):
                    continue
                previous = [float(element.get("x") or 0), float(element.get("y") or 0)]
                element["x"] = float(target[0])
                element["y"] = float(target[1])
                moved.append(
                    {
                        "text": text[:48],
                        "from": [round(previous[0], 1), round(previous[1], 1)],
                        "to": [round(float(target[0]), 1), round(float(target[1]), 1)],
                    }
                )
                break
            continue
        if status != "apply":
            continue
        text = str(decision.get("drop") or "")
        if not text:
            continue
        bx, by, bw, bh = (float(value) for value in box[:4])
        best = None
        for element in elements:
            if id(element) in remove_ids:
                continue
            if str(element.get("text") or "").strip() != text:
                continue
            cx = float(element.get("x") or 0) + float(element.get("width") or 0) / 2
            cy = float(element.get("y") or 0) + float(element.get("height") or 0) / 2
            if bx - 8 <= cx <= bx + bw + 8 and by - 8 <= cy <= by + bh + 8:
                best = element
                break
        if best is None:
            continue
        remove_ids.add(id(best))
        dropped.append(
            {
                "text": text[:48],
                "bbox": [
                    round(float(best.get(key) or 0), 1)
                    for key in ("x", "y", "width", "height")
                ],
            }
        )
    if dropped:
        calibrated["elements"] = [
            element for element in elements if id(element) not in remove_ids
        ]
    return calibrated, {
        "schema_version": "grounding-adjudicated-conflict/1.0",
        "status": "applied" if (dropped or moved) else "not-needed",
        "adjusted_count": len(dropped) + len(moved),
        "dropped": dropped,
        "moved": moved,
    }


def resolve_same_slot_conflicts(
    design: Mapping[str, Any],
    *,
    overlap_ratio: float = 0.9,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve the provable half of "two different texts in one slot".

    light-table has seven pairs of different strings sharing a slot.  Six are
    genuine semantic conflicts (``未确认(0)`` vs ``个人信息``, ``工时管理`` vs a
    search placeholder): both readings are plausible, and a geometry rule that
    picks one would silently delete real content.  Only one shape is provable:

    * an OCR concatenation -- the longer string is the shorter one plus at most
      two non-CJK characters glued on (``Q搜索`` = icon glyph ``Q`` + ``搜索``).
      The extra prefix is an icon that OCR read as a letter, not content.

    Everything else is recorded under ``unresolved`` with its geometry so the
    VLM judge (or a human) can arbitrate; nothing is dropped on a guess.

    Args:
        design: Image design with ``elements``.
        overlap_ratio: Share of the smaller box that must be covered.

    Returns:
        ``(calibrated_design, report)``.
    """
    import re

    calibrated = copy.deepcopy(dict(design))
    elements = [
        element
        for element in calibrated.get("elements") or []
        if isinstance(element, dict)
    ]
    owners: list[dict[str, Any]] = []
    for element in elements:
        if str(element.get("type") or "").lower() not in {
            "text",
            "button",
            "input",
            "link",
        }:
            continue
        text = str(element.get("text") or "").strip()
        if not text:
            continue
        try:
            x = float(element.get("x") or 0)
            y = float(element.get("y") or 0)
            width = float(element.get("width") or 0)
            height = float(element.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        owners.append(
            {
                "element": element,
                "text": text,
                "normalized": re.sub(r"[\s\W_]+", "", text).lower(),
                "rect": (x, y, x + width, y + height),
                "area": width * height,
            }
        )

    def _intersection(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
        return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
            0.0, min(a[3], b[3]) - max(a[1], b[1])
        )

    dropped: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    dropped_ids: set[int] = set()
    for index, left in enumerate(owners):
        if id(left["element"]) in dropped_ids:
            continue
        for right in owners[index + 1 :]:
            if id(right["element"]) in dropped_ids:
                continue
            area = _intersection(left["rect"], right["rect"])
            if area <= 0:
                continue
            smaller = min(left["area"], right["area"])
            if smaller <= 0 or area / smaller < overlap_ratio:
                continue
            short, long = sorted((left, right), key=lambda item: len(item["normalized"]))
            shorter = short["normalized"]
            longer = long["normalized"]
            if shorter == longer:
                # Identical strings are not this rule's business: the
                # duplicate-owner pass owns them.
                continue
            clipped = (
                len(longer) - len(shorter) <= 2
                and shorter
                and shorter in longer
                and not any(ord(char) > 0x2E80 for char in longer.replace(shorter, ""))
            )
            record = {
                "kept": short["text"][:32],
                "conflict": long["text"][:32],
                "bbox": [round(value, 1) for value in long["rect"]],
                "kept_bbox": [round(value, 1) for value in short["rect"]],
                "overlap": round(area / smaller, 3),
            }
            if clipped:
                dropped_ids.add(id(long["element"]))
                dropped.append({**record, "reason": "ocr-concatenation"})
            else:
                unresolved.append(record)

    if dropped:
        calibrated["elements"] = [
            element for element in elements if id(element) not in dropped_ids
        ]
    return calibrated, {
        "schema_version": "grounding-same-slot-conflict/1.0",
        "status": "applied" if dropped else "not-needed",
        "overlap_ratio": overlap_ratio,
        "adjusted_count": len(dropped),
        "dropped": dropped,
        "unresolved": unresolved,
    }


def clamp_table_cell_font_outliers(
    design: Mapping[str, Any],
    *,
    factor: float = 1.6,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Clamp table-cell font sizes that were inflated from the cell box height.

    light-table measures ``(选填)`` / ``请输入0~...`` at 48.5 pt inside 55 px
    cells while every neighbouring cell sits at 20-21 pt.  The size came from
    the *box*, not from the type scale: a taller cell inflates the estimate, and
    the placeholder then paints across the column line.  The table itself
    states the right size -- its cells' median -- so the outlier is clamped to
    it instead of being inferred again from ink.

    Scope is deliberately narrow: only ``table-cell`` owners (role or
    ``contentRef``), and only when the page has enough cells for a median to
    mean something.  Display type, headers and free text are untouched, so a
    KPI card or a hero number can keep its 48 pt.

    Args:
        design: Image design with ``elements``.
        factor: Multiple of the cells' median above which a size is an outlier.

    Returns:
        ``(calibrated_design, report)``.
    """
    calibrated = copy.deepcopy(dict(design))
    elements = [
        element
        for element in calibrated.get("elements") or []
        if isinstance(element, dict)
    ]

    def _is_cell(element: Mapping[str, Any]) -> bool:
        role = str((element.get("imageMVP") or {}).get("role") or "")
        content_ref = str(element.get("contentRef") or "")
        return role == "table-cell" or content_ref.startswith("table-cell:")

    cells: list[tuple[dict[str, Any], float]] = []
    for element in elements:
        if not _is_cell(element):
            continue
        style = element.get("style")
        if not isinstance(style, dict):
            continue
        size = style.get("fontSize")
        if isinstance(size, (int, float)) and float(size) > 0:
            cells.append((element, float(size)))
    report: dict[str, Any] = {
        "schema_version": "grounding-table-cell-scale/1.0",
        "status": "not-needed",
        "factor": factor,
        "cell_count": len(cells),
        "median_size": None,
        "adjusted_count": 0,
        "adjustments": [],
    }
    if len(cells) < 4:
        return calibrated, report
    ordered = sorted(size for _element, size in cells)
    median = ordered[len(ordered) // 2]
    report["median_size"] = round(median, 2)
    for element, size in cells:
        if size <= factor * median:
            continue
        style = element["style"]
        style["fontSize"] = median
        report["adjustments"].append(
            {
                "contentRef": element.get("contentRef") or None,
                "text": str(element.get("text") or "")[:32],
                "previous": round(size, 2),
                "updated": round(median, 2),
                "ratio": round(size / median, 2),
            }
        )
    report["adjusted_count"] = len(report["adjustments"])
    if report["adjusted_count"]:
        report["status"] = "applied"
    return calibrated, report


def drop_implausible_duplicate_owners(
    design: Mapping[str, Any],
    *,
    overflow_ratio: float = 2.0,
    similarity: float = 0.85,
    roomy_ratio: float = 0.8,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drop a text owner that repeats another one from a box that cannot hold it.

    dark-card-grid carries a search placeholder twice: the real control in the
    hero ``[1706, 297, 442, ...]`` and a phantom ``[1084, 42, 58, 29]`` in the
    nav row.  The phantom's box is 4.2x narrower than the glyph run, so its text
    paints across ``社区`` and ``接入文档`` -- the occlusion the VLM judge
    reported.  Two independent signals make the drop safe:

    * the string already exists elsewhere with a box that can hold it
      (fuzzy match, because OCR noise differs by a character or two);
    * this owner's box is too narrow for its own text by ``overflow_ratio``,
      i.e. the detection that produced it is not trustworthy.

    A legitimate repeat (a header CTA also present in the footer) has a box
    that fits its text, so it never matches the second condition.

    The surviving owner keeps its geometry but takes the cleaner reading: on
    dark-card-grid the implausible box carries ``…或厂商，例如 deepseek`` while
    the roomy one carries ``…或「商。例如 deepseek`` (two OCR artefacts).  Merging
    text instead of dropping it keeps the critical string alive -- a plain drop
    measured ``critical 26/27`` on the family gate.

    Args:
        design: Image design with ``elements``.
        overflow_ratio: Expected-width / box-width above which a box is
            implausible.
        similarity: Fuzzy match ratio for "the same string".
        roomy_ratio: The surviving owner's box must fit at least this share of
            the text.

    Returns:
        ``(calibrated_design, report)``.
    """
    import difflib
    import re

    calibrated = copy.deepcopy(dict(design))
    elements = [
        element
        for element in calibrated.get("elements") or []
        if isinstance(element, dict)
    ]

    def _normalized(text: str) -> str:
        return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)

    def _expected(text: str, size: float) -> float:
        total = sum(1.0 if ord(char) > 0x2E80 else 0.55 for char in text)
        return total * size

    def _noise_score(text: str) -> int:
        """Count OCR artefacts, not ordinary punctuation.

        ``搜索模型或「商。例如 deepseek`` carries two artefacts (``「``, ``。``
        mid-string) while the clean reading has none, so the merge below keeps
        the clean string even though it lives on the implausible box.
        """
        artefacts = set("「」『』【】〔〕[]{}〈〉《》*□■◇◆")
        return sum(1 for char in text if char in artefacts)

    owners: list[dict[str, Any]] = []
    for element in elements:
        if str(element.get("type") or "").lower() not in {
            "text",
            "button",
            "input",
            "link",
        }:
            continue
        text = str(element.get("text") or "").strip()
        style = element.get("style")
        if not text or not isinstance(style, Mapping):
            continue
        size = style.get("fontSize")
        if not isinstance(size, (int, float)) or float(size) <= 0:
            continue
        width = float(element.get("width") or 0)
        if width <= 0:
            continue
        expected = _expected(text, float(size))
        if expected <= 0:
            continue
        owners.append(
            {
                "element": element,
                "raw": text,
                "normalized": _normalized(text),
                "expected": expected,
                "width": width,
                "center": (
                    float(element.get("x") or 0) + width / 2,
                    float(element.get("y") or 0) + float(element.get("height") or 0) / 2,
                ),
            }
        )

    dropped: list[dict[str, Any]] = []
    dropped_ids: set[int] = set()
    for owner in owners:
        if owner["expected"] / owner["width"] < overflow_ratio:
            continue
        if not owner["normalized"]:
            continue
        match = None
        for other in owners:
            if other is owner or id(other["element"]) in dropped_ids:
                continue
            if other["width"] < roomy_ratio * other["expected"]:
                continue
            distance = abs(other["center"][0] - owner["center"][0]) + abs(
                other["center"][1] - owner["center"][1]
            )
            if distance < 0.5 * max(other["width"], owner["width"]):
                continue
            ratio = difflib.SequenceMatcher(
                None, owner["normalized"], other["normalized"]
            ).ratio()
            if ratio >= similarity:
                match = (other, ratio)
                break
        if match is None:
            continue
        other, ratio = match
        element = owner["element"]
        dropped_ids.add(id(element))
        merged_text = None
        survivor = other["element"]
        survivor_style = survivor.get("style")
        if (
            isinstance(survivor_style, dict)
            and _noise_score(owner["raw"]) < _noise_score(other["raw"])
        ):
            # Same string, cleaner reading on the implausible box: keep the
            # survivor's geometry but its text, so no content disappears.
            merged_text = owner["raw"]
            survivor["text"] = merged_text
            evidence = survivor.get("styleEvidence")
            if isinstance(evidence, dict):
                evidence["textSource"] = "merged-owner"
        dropped.append(
            {
                "contentRef": element.get("contentRef") or None,
                "text": owner["raw"][:48],
                "bbox": [
                    round(float(element.get(key) or 0), 1)
                    for key in ("x", "y", "width", "height")
                ],
                "overflow_ratio": round(owner["expected"] / owner["width"], 2),
                "duplicate_of": {
                    "text": other["raw"][:48],
                    "bbox": [
                        round(float(other["element"].get(key) or 0), 1)
                        for key in ("x", "y", "width", "height")
                    ],
                },
                "similarity": round(ratio, 3),
                "text_merged": bool(merged_text),
                "merged_text": merged_text,
            }
        )

    if dropped:
        calibrated["elements"] = [
            element
            for element in elements
            if id(element) not in dropped_ids
        ]

    return calibrated, {
        "schema_version": "grounding-duplicate-owner/1.0",
        "status": "applied" if dropped else "not-needed",
        "overflow_ratio": overflow_ratio,
        "similarity": similarity,
        "adjusted_count": len(dropped),
        "dropped": dropped,
    }


def measure_text_block_lines(
    image: Any,
    bbox: Any,
    *,
    rotation: float | None = None,
    gap: int = 2,
    min_band_height: int = 5,
) -> dict[str, Any] | None:
    """Split a text block into its lines, deskewing first.

    A tilted multi-line block cannot be split by rows as it stands: the ink of
    two lines leaning the same way overlaps vertically, so ``5.8折`` measures
    as **one** connected band (155 px of ink in a 105 px box) and any row-gap
    test finds nothing.  Levelling the block first is what makes the lines
    separate again -- measured on dark-card-grid, two bands come back at
    89x47 and 30x29, matching the gold nodes ``5.8`` (62 pt, 95x70) and ``折``
    (30 pt, 30x34).

    The window is the element box itself, not a padded one: a padded window
    reaches the badge outline and the outline's stroke makes every row
    non-empty, which is the same failure in a different disguise.  Rotation
    happens on a zero-padded canvas so the corners are not clipped.

    Args:
        image: ``(h, w, 3)`` RGB array.
        bbox: ``[x, y, width, height]`` of the block in source pixels.
        rotation: Tilt in degrees; measured when omitted.
        gap: Empty rows needed between two lines.
        min_band_height: Bands thinner than this are noise, not text.

    Returns:
        ``{"tilt", "line_count", "bands", "block"}`` where each band carries
        ``top``/``height``/``left``/``width`` in the deskewed frame, relative
        to the block's own top-left.  ``None`` when the box holds no ink.
    """
    import cv2
    import numpy as np

    x, y, box_w, box_h = (int(round(float(value))) for value in list(bbox)[:4])
    if box_w < 8 or box_h < 8:
        return None
    height, width = image.shape[:2]
    x, y = max(0, x), max(0, y)
    box_w, box_h = min(box_w, width - x), min(box_h, height - y)
    if box_w < 8 or box_h < 8:
        return None
    window = image[y : y + box_h, x : x + box_w]
    colors, counts = np.unique(window.reshape(-1, 3), axis=0, return_counts=True)
    background = colors[int(counts.argmax())].astype(np.int16)
    ink = (np.abs(window - background).max(axis=2) > 60).astype(np.float32)
    if ink.sum() < 30:
        return None
    tilt = float(rotation or 0.0)
    if rotation is None:
        measured = measure_element_rotation(image, [x, y, box_w, box_h])
        tilt = float(measured["angle"]) if measured else 0.0

    margin = int(np.ceil(max(box_w, box_h) * abs(np.sin(np.radians(tilt))))) + 6
    canvas = np.zeros((box_h + 2 * margin, box_w + 2 * margin), dtype=np.float32)
    canvas[margin : margin + box_h, margin : margin + box_w] = ink
    rows, columns = canvas.shape
    matrix = cv2.getRotationMatrix2D((columns / 2, rows / 2), -tilt, 1.0)
    flat = cv2.warpAffine(
        canvas, matrix, (columns, rows), flags=cv2.INTER_LINEAR, borderValue=0
    )

    profile = (flat > 0.3).sum(axis=1)
    spans: list[tuple[int, int]] = []
    start: int | None = None
    blank = 0
    for index, value in enumerate(profile):
        if value > 0:
            if start is None:
                start = index
            blank = 0
        elif start is not None:
            blank += 1
            if blank >= gap:
                spans.append((start, index - blank + 1))
                start = None
                blank = 0
    if start is not None:
        spans.append((start, len(profile)))
    spans = [span for span in spans if span[1] - span[0] >= min_band_height]
    if not spans:
        return None

    bands: list[dict[str, int]] = []
    for top, bottom in spans:
        columns_hit = np.flatnonzero((flat[top:bottom] > 0.3).any(axis=0))
        if not columns_hit.size:
            continue
        bands.append(
            {
                "top": int(top - margin),
                "height": int(bottom - top),
                "left": int(columns_hit.min() - margin),
                "width": int(columns_hit.max() - columns_hit.min() + 1),
            }
        )
    if not bands:
        return None
    block_top = min(band["top"] for band in bands)
    block_bottom = max(band["top"] + band["height"] for band in bands)
    block_left = min(band["left"] for band in bands)
    block_right = max(band["left"] + band["width"] for band in bands)
    return {
        "tilt": round(tilt, 2),
        "line_count": len(bands),
        "bands": bands,
        "block": {
            "left": block_left,
            "top": block_top,
            "width": block_right - block_left,
            "height": block_bottom - block_top,
        },
    }


# 每个字符占多少 em：只用来**分配**字符串与**估**字号，不参与任何几何判定。
# 数字/标点取常见无衬线体的前进宽度，CJK 取全角。
_ADVANCE_EM = {"digit": 0.55, "punct": 0.28, "cjk": 1.0, "other": 0.62}


def _char_advance(character: str) -> float:
    """Estimated advance of one character, in em."""
    if "\u4e00" <= character <= "\u9fff":
        return _ADVANCE_EM["cjk"]
    if character.isdigit():
        return _ADVANCE_EM["digit"]
    if character in ".,:;'\u00b7":
        return _ADVANCE_EM["punct"]
    return _ADVANCE_EM["other"]


# 墨高 / 字号：CJK 几乎填满 em，数字只占 x-height 到 cap-height 之间。
# 这是**字体度量**，不是从这两处样本拟出来的阈值——它只用来判断"这个切法
# 能不能同时解释宽度和高度"，不参与任何几何输出。
_INK_HEIGHT_EM = {"cjk": 0.90, "latin": 0.72}


def _ink_height_em(part: str) -> float:
    """Expected ink height for ``part``, in em, from its dominant script."""
    if any("\u4e00" <= character <= "\u9fff" for character in part):
        return _INK_HEIGHT_EM["cjk"]
    return _INK_HEIGHT_EM["latin"]


def _split_block_lines(
    text: str, bands: list[dict[str, int]]
) -> tuple[list[str], float] | None:
    """Cut ``text`` into one part per band, judged by width *and* height.

    Comparing width shares is wrong here: the two lines have different font
    sizes, so a share of the total width says nothing about which characters
    belong together.  What does hold is that one cut has to explain **two
    independent measurements at once** -- each band's width gives a size, and
    that size has to predict the band's ink height.

    Measured on dark-card-grid (bands 89x47 and 30x29, text ``5.8折``):
    cutting after ``5.8`` predicts 46.4 px and 27.6 px against 47 and 29
    (about 3 % error); cutting after ``5.`` predicts 77 px for the first line
    against 47, so it is rejected by a factor of twenty.

    Returns:
        ``(parts, error)`` with ``error`` the mean relative height error, or
        ``None`` when the text cannot be cut into that many parts.
    """
    import itertools

    total = len(bands)
    if total < 2 or len(text) < total:
        return None
    advances = [_char_advance(character) for character in text]
    best: tuple[float, list[str]] | None = None
    for cuts in itertools.combinations(range(1, len(text)), total - 1):
        bounds = (0, *cuts, len(text))
        error = 0.0
        feasible = True
        for index in range(total):
            part = text[bounds[index] : bounds[index + 1]]
            advance = sum(advances[bounds[index] : bounds[index + 1]])
            band_height = bands[index]["height"]
            if advance <= 0 or band_height <= 0:
                feasible = False
                break
            size = bands[index]["width"] / advance
            predicted = size * _ink_height_em(part)
            error += abs(predicted - band_height) / band_height
        if not feasible:
            continue
        score = error / total
        if best is None or score < best[0]:
            best = (score, [text[bounds[i] : bounds[i + 1]] for i in range(total)])
    return (best[1], best[0]) if best else None


def restructure_tilted_text_block(
    design: Mapping[str, Any],
    image_path: str | Path,
    *,
    min_angle: float = 2.5,
    line_box_ratio: float = 1.13,
    max_split_error: float = 0.15,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rebuild a tilted multi-line block as one node with per-line sizes.

    The design merges ``5.8`` and ``折`` into a single ``5.8折`` element and
    sizes it from the *block* height, which is how it ends up at 86.5 pt in a
    105 px box: bigger than either real line, and spilling out of the badge.
    The two real lines sit 62 pt and 30 pt (gold nodes), so one size can never
    fit -- that is why ``lineSizes`` exists.

    Only tilted blocks are touched: a paragraph is upright, and rewriting its
    line structure from ink bands would be guessing.  The tilt is the structural
    signal that says "this is a sticker with a price and a unit".

    Sizes come from each band's ink width divided by its estimated advance
    width, not from its ink height: height-to-size depends on the script (a
    CJK glyph fills nearly the whole em, a digit about 0.7), so one ratio
    cannot serve both lines.  Measured: 89 px of ``5.8`` -> 64.5 pt against a
    gold 62, and 30 px of ``折`` -> 30.0 pt against a gold 30.

    Args:
        design: Image design with ``elements``; ``rotation`` must already be set
            (``text-rotation`` runs before this).
        image_path: Source screenshot the bands are measured on.
        min_angle: Blocks tilted less than this are left alone.
        line_box_ratio: Line box height over font size, measured on this
            family's gold (70/62 and 34/30).
        max_split_error: Refuse to cut when the best cut does not explain the
            band widths well; a wrong cut would rewrite the visible string.

    Returns:
        ``(calibrated_design, report)``.
    """
    import numpy as np
    from PIL import Image

    calibrated = copy.deepcopy(dict(design))
    report: dict[str, Any] = {
        "schema_version": "grounding-text-block-lines/1.0",
        "status": "not-needed",
        "adjusted_count": 0,
        "blocks": [],
        "skipped": [],
    }
    elements = [
        element
        for element in calibrated.get("elements") or []
        if isinstance(element, dict)
    ]
    targets = [
        element
        for element in elements
        if str(element.get("type") or "") in {"text", "button"}
        and len(str(element.get("text") or "").strip()) >= 2
        and isinstance(element.get("rotation"), (int, float))
        and abs(float(element["rotation"])) >= min_angle
    ]
    if not targets:
        return calibrated, report
    try:
        with Image.open(image_path) as handle:
            pixels = np.asarray(handle.convert("RGB")).astype(np.int16)
    except (OSError, ValueError):
        return calibrated, report
    for element in targets:
        text = str(element.get("text") or "").strip()
        box = [
            float(element.get("x") or 0),
            float(element.get("y") or 0),
            float(element.get("width") or 0),
            float(element.get("height") or 0),
        ]
        measured = measure_text_block_lines(
            pixels, box, rotation=float(element["rotation"])
        )
        if measured is None or measured["line_count"] < 2:
            continue
        bands = measured["bands"]
        if len(bands) > 4:
            report["skipped"].append(
                {"text": text[:24], "reason": "more than four lines"}
            )
            continue
        split = _split_block_lines(text, bands)
        if split is None or split[1] > max_split_error:
            report["skipped"].append(
                {
                    "text": text[:24],
                    "reason": "no cut explains the band widths and heights",
                    "error": None if split is None else round(split[1], 3),
                }
            )
            continue
        parts = split[0]
        sizes: list[int] = []
        for part, band in zip(parts, bands):
            advance = sum(_char_advance(character) for character in part)
            sizes.append(max(1, int(round(band["width"] / advance))) if advance else 1)
        block_height = sum(max(1, int(round(size * line_box_ratio))) for size in sizes)
        # The box has to be wide enough that the renderer will not wrap a line
        # again on its own metrics.  A band's width is its *ink*, which is
        # narrower than the advance width the layout needs: 5.8 measures 89 px
        # of ink and Figma still broke it after "5." in an 89 px box.  The
        # estimate below is the same advance model used to split the string, and
        # the margin covers a font whose digits are wider than the model's.  The
        # extra room is invisible because the block is centred, not left-aligned.
        estimated = max(
            sizes[index] * sum(_char_advance(character) for character in part)
            for index, part in enumerate(parts)
        )
        block_width = max(max(band["width"] for band in bands), estimated * 1.3)
        centre_x = box[0] + box[2] / 2
        centre_y = box[1] + box[3] / 2
        element["lines"] = parts
        element["lineSizes"] = sizes
        element["fontSize"] = float(sizes[0])
        element["lineHeight"] = float(round(sizes[0] * line_box_ratio))
        style = element.get("style")
        if isinstance(style, dict):
            # The renderers merge ``{**element, **style}``, so a stale
            # ``style.fontSize`` silently wins over the line sizes and every
            # line box is derived from the *block* size -- which is how 折 ended
            # up drawn on top of 5.8.  Both keys must carry the same number.
            style["fontSize"] = element["fontSize"]
            style["lineHeight"] = element["lineHeight"]
            # Two different sizes cannot share one line box, and we no longer
            # know where each line's left edge sits (the design merged two gold
            # nodes into one string).  Centring is the neutral answer: it keeps
            # the ink inside the box wherever the box has to grow.
            style["textAlign"] = "center"
        element["width"] = float(block_width)
        element["height"] = float(block_height)
        element["x"] = centre_x - block_width / 2
        element["y"] = centre_y - block_height / 2
        report["blocks"].append(
            {
                "text": text[:24],
                "lines": parts,
                "lineSizes": sizes,
                "band_boxes": [[b["left"], b["top"], b["width"], b["height"]] for b in bands],
                "block": [round(element["x"], 1), round(element["y"], 1), block_width, block_height],
                "split_error": round(split[1], 3),
                "rotation": round(float(element["rotation"]), 2),
            }
        )
    if report["blocks"]:
        calibrated["elements"] = elements
        report["status"] = "applied"
        report["adjusted_count"] = len(report["blocks"])
    return calibrated, report


def _enclosing_outline(
    outlines: list[Mapping[str, Any]], box: list[float]
) -> Mapping[str, Any] | None:
    """The drawn outline whose own box holds this element's centre.

    A badge drawn with two concentric strokes exposes two candidates; the outer
    one is the badge, so the larger box wins.

    Args:
        outlines: Elements carrying ``role == "badge-outline"``.
        box: ``[x, y, width, height]`` of the element being measured.

    Returns:
        The enclosing outline, or ``None`` when the element stands alone.
    """
    centre_x = box[0] + box[2] / 2
    centre_y = box[1] + box[3] / 2
    best: tuple[float, Mapping[str, Any]] | None = None
    for outline in outlines:
        left = float(outline.get("x") or 0)
        top = float(outline.get("y") or 0)
        width = float(outline.get("width") or 0)
        height = float(outline.get("height") or 0)
        if not (left <= centre_x <= left + width and top <= centre_y <= top + height):
            continue
        area = width * height
        if best is None or area > best[0]:
            best = (area, outline)
    return best[1] if best else None


def apply_text_rotation(
    design: Mapping[str, Any],
    image_path: str | Path,
    *,
    dead_zone: float = 2.5,
    min_ink: int = 30,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write the measured tilt onto every text block that has one.

    Rotation is a first-class field downstream (SVG wraps the element in
    ``<g transform="rotate">``, the Figma bridge sets ``node.rotation``), but
    nothing upstream produces it: the design schema has no such key, so a
    tilted sticker arrives axis-aligned and the bitmap beside it is the only
    thing that still looks tilted.

    The angle comes from :func:`measure_element_rotation`, not from the node's
    own size: that oracle only exists for Figma nodes, and it cannot give the
    sign anyway.  ``dead_zone`` is the measured noise floor -- upright text
    reaches 2.0 degrees from anti-aliasing alone across three families.

    Args:
        design: Image design with ``elements``.
        image_path: Source screenshot the tilt is measured on.
        dead_zone: Tilts below this are treated as upright and cleared.
        min_ink: Ink pixels needed before a box is measurable.

    Returns:
        ``(calibrated_design, report)``.  ``rotation`` is removed from elements
        that measure upright, so a second pass is a no-op.
    """
    import numpy as np
    from PIL import Image

    calibrated = copy.deepcopy(dict(design))
    report: dict[str, Any] = {
        "schema_version": "grounding-text-rotation/1.0",
        "status": "not-needed",
        "adjusted_count": 0,
        "measured_count": 0,
        "rotations": [],
        "cleared": [],
    }
    elements = [
        element
        for element in calibrated.get("elements") or []
        if isinstance(element, dict)
    ]
    targets = [
        element
        for element in elements
        if str(element.get("type") or "") in {"text", "button"}
        and str(element.get("text") or "").strip()
        and float(element.get("width") or 0) >= 8
        and float(element.get("height") or 0) >= 8
    ]
    if not targets:
        return calibrated, report
    try:
        with Image.open(image_path) as handle:
            pixels = np.asarray(handle.convert("RGB")).astype(np.int16)
    except (OSError, ValueError):
        return calibrated, report
    # Text inside a drawn outline is rotated *with* the outline, and the outline
    # states its angle exactly (fitted on its own edge: 5.98 against a gold
    # 6.00, where row variance on the two merged text lines reads 6.8).
    outlines = [
        element
        for element in elements
        if str(element.get("role") or "") == "badge-outline"
        and isinstance(element.get("rotation"), (int, float))
    ]
    for element in targets:
        # ``_box_of`` returns corners; the measurement wants [x, y, w, h].
        box = [
            float(element.get("x") or 0),
            float(element.get("y") or 0),
            float(element.get("width") or 0),
            float(element.get("height") or 0),
        ]
        outline = _enclosing_outline(outlines, box)
        if outline is not None:
            angle = float(outline["rotation"])
            element["rotation"] = angle
            report["rotations"].append(
                {
                    "text": str(element.get("text") or "")[:24],
                    "angle": angle,
                    "source": "outline",
                    "bbox": [round(value, 1) for value in box],
                }
            )
            continue
        measured = measure_element_rotation(pixels, box, dead_zone=dead_zone)
        if measured is None or measured["ink"] < min_ink:
            continue
        report["measured_count"] += 1
        angle = float(measured["angle"])
        if abs(angle) < 0.01:
            if "rotation" in element:
                element.pop("rotation", None)
                report["cleared"].append(str(element.get("text") or "")[:24])
            continue
        element["rotation"] = angle
        report["rotations"].append(
            {
                "text": str(element.get("text") or "")[:24],
                "angle": angle,
                "source": "measured",
                "raw": measured["raw"],
                "gain": measured["gain"],
                "ink": measured["ink"],
                "bbox": [round(value, 1) for value in box],
            }
        )
    if report["rotations"]:
        calibrated["elements"] = elements
        report["status"] = "applied"
        report["adjusted_count"] = len(report["rotations"])
    return calibrated, report


def apply_nav_row_weight(
    design: Mapping[str, Any],
    *,
    top_band_ratio: float = 0.10,
    min_row_items: int = 3,
    size_tolerance: float = 0.25,
    max_label_chars: int = 12,
    nav_weight: int = 500,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Promote a header menu row to Medium, using row structure as the evidence.

    Why this exists: on dark-card-grid the six remaining Medium mismatches sit
    in one row at the top of the page (``首页``/``创作``/``价格``/``Agent 优惠``/
    ``社区``/``接入文档``, y ~= 38 of 1336 = 4.2 % of canvas height).  A menu bar
    is chrome, not content: it is a single horizontal row of short labels,
    rendered at one size, above everything else.  That is a shape, so it can be
    read off the design without matching a single string.

    "Equally spaced" is **not** used, and that is a measured decision: on this
    very row the gaps between perception boxes range from 12 px to 230 px
    (``ACCTOKEN``'s box overlaps ``首页`` by 10 px, ``首页``->``创作`` is 230 px
    because the selected tab is not emitted as a label).  Box padding, not
    layout, dominates the gap, so an equidistance test would never fire on the
    page it was written for.  What remains measurable is the row itself:

    * one vertical band (centre-y within ``max(4 px, 0.3 x median height)``);
    * at least ``min_row_items`` members, all short labels;
    * one shared size, within ``size_tolerance`` of the row's modal size
      (``Agent 优惠`` measures 32.25 against a 27.5 mode, +17 %);
    * the band lies in the top ``top_band_ratio`` of the canvas;
    * ``table-cell`` / ``table-header`` owners are excluded, and so is every
      ``control`` **except** ``controlType == "navigation"`` -- the search
      placeholder shares this band on dark-card-grid, while the ``社区`` menu
      label is itself a control whose control type says it is navigation.

    Only owners currently at 400 are promoted, so an explicit Light decision
    from another strategy survives.  Runs as part of ``font-initial`` after the
    display-scale rule.

    Args:
        design: Image design with ``elements`` (``x``/``y``/``width``/
            ``height``, ``style.fontSize``/``fontWeight``) and ``canvas``.
        top_band_ratio: Fraction of canvas height that counts as the header.
        min_row_items: Members a row needs before it is a menu.
        size_tolerance: Relative distance from the row's modal size.
        max_label_chars: Longest text still read as a label.
        nav_weight: Weight written for promoted owners.

    Returns:
        ``(calibrated_design, report)``.
    """
    from collections import Counter

    calibrated = copy.deepcopy(dict(design))
    report: dict[str, Any] = {
        "schema_version": "grounding-nav-row-weight/1.0",
        "status": "not-needed",
        "canvas_height": None,
        "top_band_ratio": top_band_ratio,
        "rows": [],
        "adjusted_count": 0,
        "adjustments": [],
        "skipped_non_free_text": 0,
    }
    elements = [
        element
        for element in calibrated.get("elements") or []
        if isinstance(element, dict)
    ]
    canvas = calibrated.get("canvas")
    height = None
    if isinstance(canvas, Mapping):
        raw_height = canvas.get("height")
        if isinstance(raw_height, (int, float)) and float(raw_height) > 0:
            height = float(raw_height)
    if height is None:
        bottoms = [
            float(element.get("y") or 0) + float(element.get("height") or 0)
            for element in elements
        ]
        height = max(bottoms) if bottoms else 0.0
    if height <= 0:
        return calibrated, report

    candidates: list[dict[str, Any]] = []
    heights: list[float] = []
    for element in elements:
        text = str(element.get("text") or "").strip()
        if not text or element.get("type") not in {"text", "button"}:
            continue
        style = element.get("style")
        if not isinstance(style, Mapping):
            continue
        role = str((element.get("imageMVP") or {}).get("role") or "")
        content_ref = str(element.get("contentRef") or "")
        control_type = str(element.get("controlType") or "")
        # A menu item is written as a control, so ``role`` alone would drop the
        # very labels this rule is for.  ``controlType == "navigation"`` is the
        # structural discriminator: on dark-card-grid the header label ``社区``
        # carries it while the neighbouring button (``控制台``) and the search
        # input do not.
        if role in {"table-cell", "table-header", "control"} and control_type != "navigation":
            report["skipped_non_free_text"] += 1
            continue
        if content_ref.startswith(("table-cell:", "table-header:")):
            report["skipped_non_free_text"] += 1
            continue
        size = style.get("fontSize")
        if not isinstance(size, (int, float)) or float(size) <= 0:
            continue
        box = [
            float(element.get(key) or 0) for key in ("x", "y", "width", "height")
        ]
        if box[2] <= 0:
            continue
        candidates.append(
            {
                "element": element,
                "text": text,
                "size": float(size),
                "x": box[0],
                "width": box[2],
                "height": box[3],
                "center": box[1] + box[3] / 2.0,
            }
        )
        heights.append(box[3])
    if len(candidates) < min_row_items:
        return calibrated, report

    heights.sort()
    median_height = heights[len(heights) // 2] or 1.0
    band = max(4.0, 0.3 * median_height)
    candidates.sort(key=lambda item: item["center"])
    groups: list[list[dict[str, Any]]] = []
    for item in candidates:
        if groups and abs(item["center"] - groups[-1][-1]["center"]) <= band:
            groups[-1].append(item)
        else:
            groups.append([item])

    for group in groups:
        labels = [
            item for item in group if len(item["text"]) <= max_label_chars
        ]
        if len(labels) < min_row_items:
            continue
        row_center = sorted(item["center"] for item in labels)[len(labels) // 2]
        if row_center > top_band_ratio * height:
            continue
        sizes = [round(item["size"], 1) for item in labels]
        modal = Counter(sizes).most_common(1)[0][0]
        members = [
            item
            for item in labels
            if abs(item["size"] - modal) / modal <= size_tolerance
        ]
        if len(members) < min_row_items:
            continue
        promoted: list[dict[str, Any]] = []
        for item in sorted(members, key=lambda entry: entry["x"]):
            style = item["element"].get("style")
            if not isinstance(style, dict):
                continue
            if _normalize_font_weight(style.get("fontWeight")) != 400:
                continue
            style["fontWeight"] = nav_weight
            promoted.append(
                {
                    "contentRef": item["element"].get("contentRef") or None,
                    "text": item["text"][:48],
                    "fontSize": round(item["size"], 2),
                    "y": round(item["center"], 1),
                    "previous": 400,
                    "updated": nav_weight,
                }
            )
        if not promoted:
            continue
        report["adjusted_count"] += len(promoted)
        report["adjustments"].extend(promoted)
        report["rows"].append(
            {
                "y": round(row_center, 1),
                "modal_font_size": modal,
                "member_count": len(members),
                "promoted_count": len(promoted),
                "labels": [item["text"][:24] for item in members],
            }
        )

    report["canvas_height"] = round(height, 1)
    if report["adjusted_count"]:
        report["status"] = "applied"
    return calibrated, report


def calibrate_text_weight_from_render(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
    *,
    skip_content_refs: Mapping[str, Any] | set[str] | None = None,
    min_ink_pixels: int = 40,
    step_up_below: float = 0.82,
    step_down_above: float = 1.22,
    width_tolerance: float = 0.18,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Choose font weight by comparing rendered ink against source ink.

    **Not wired into the calibration pipeline.**  Measured on dark-card-grid
    (2026-11-10, perception-frozen rerun), this rule changed 19 owners and got
    4 right: ``style_mm`` went 24/39 -> 25/39.  The reason is visible once the
    page-median systematic bias is divided out -- the per-weight density ratios
    collapse to Regular 1.000, Medium 0.905, Bold 1.027, Black 0.894, i.e. no
    usable separation.  Ink density carries font-family substitution and
    anti-aliasing at least as strongly as it carries weight.

    It stays in the module, with tests, as the reproduction of that negative
    result: anyone proposing a render-compare weight rule should start by
    re-running it rather than re-deriving the same dead end.

    Why render comparison was attempted: the Phase 1 evidence probe showed a
    static ``stroke / ink_height`` index shifting up to ±55 % between a gold
    box and a perception box, larger than the +35 % step between Regular and
    Bold.  Rendering the candidate into the *same* box was supposed to cancel
    that geometry dependence -- and it does, but the remaining signal is not
    weight.

    Guards, all measured rather than tuned:

    * ``width_tolerance``: when the rendered line is already 18 % off in width,
      the residual is a size/shape problem (other strategies own it) and a
      weight change would only make things worse.
    * ``min_ink_pixels``: boxes with almost no ink carry no ratio.
    * Deadband ``[step_up_below, step_down_above]``: below 18 % deviation the
      ratio is indistinguishable from anti-aliasing noise at 1x.

    Args:
        design: Image design (``elements`` with ``style``/``bbox``).
        reference_path: Source screenshot.
        rendered_path: Current Figma export of the same canvas.
        skip_content_refs: Owners another strategy already owns this round.
        min_ink_pixels: Floor for a usable ink count.
        step_up_below: Ratio under which the render is too light.
        step_down_above: Ratio above which the render is too heavy.
        width_tolerance: Relative line-width mismatch that disqualifies weight.

    Returns:
        ``(calibrated_design, report)``.
    """
    import numpy as np
    from PIL import Image

    calibrated = copy.deepcopy(dict(design))
    skip = set(skip_content_refs or ())
    with Image.open(reference_path) as source_image:
        reference = np.asarray(source_image.convert("RGB"), dtype=np.int16)
    with Image.open(rendered_path) as rendered_image:
        rendered = np.asarray(rendered_image.convert("RGB"), dtype=np.int16)

    adjustments: list[dict[str, Any]] = []
    skipped = {"unmeasurable": 0, "width-mismatch": 0, "deadband": 0, "no-weight": 0}
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict) or element.get("type") != "text":
            continue
        content_ref = str(element.get("contentRef") or "")
        if content_ref.startswith("table-header:") or content_ref in skip:
            continue
        bbox = _element_source_bbox(element)
        if bbox is None:
            continue
        style = element.setdefault("style", {})
        previous = _normalize_font_weight(style.get("fontWeight"))
        if previous is None:
            skipped["no-weight"] += 1
            continue
        source_stats = _ink_stats(reference, bbox)
        rendered_stats = _ink_stats(rendered, bbox)
        if (
            source_stats is None
            or rendered_stats is None
            or source_stats["count"] < min_ink_pixels
            or rendered_stats["count"] < min_ink_pixels
            or min(source_stats["width"], source_stats["height"]) < 3
            or min(rendered_stats["width"], rendered_stats["height"]) < 3
        ):
            skipped["unmeasurable"] += 1
            continue
        width_ratio = rendered_stats["width"] / max(1, source_stats["width"])
        if abs(width_ratio - 1.0) > width_tolerance:
            skipped["width-mismatch"] += 1
            continue
        # Density, not raw ink count.  Ink area scales with size^2 while stroke
        # scales with size, so a 10 % size deficit already reads as a 20 % ink
        # deficit and would be mistaken for "too light" (the failure that made
        # the first dry run jump 14 owners from 400 straight to 900).
        # Dividing by each side's own ink extent cancels size and leaves the
        # stroke ratio, which is what weight actually changes.
        source_density = source_stats["count"] / float(
            source_stats["width"] * source_stats["height"]
        )
        rendered_density = rendered_stats["count"] / float(
            rendered_stats["width"] * rendered_stats["height"]
        )
        if source_density <= 0:
            skipped["unmeasurable"] += 1
            continue
        ratio = rendered_density / source_density
        if step_up_below <= ratio <= step_down_above:
            skipped["deadband"] += 1
            continue
        target = _weight_for_ink_ratio(previous, ratio)
        if target == previous:
            skipped["deadband"] += 1
            continue
        style["fontWeight"] = target
        adjustments.append(
            {
                "contentRef": content_ref or None,
                "text": str(element.get("text") or "")[:48],
                "previous": previous,
                "updated": target,
                "densityRatio": round(ratio, 3),
                "widthRatio": round(width_ratio, 3),
                "sourceInk": source_stats["count"],
                "renderedInk": rendered_stats["count"],
            }
        )
    return calibrated, {
        "schema_version": "grounding-text-weight-convergence/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "skipped": skipped,
        "adjustments": adjustments,
    }


def calibrate_toolbar_font_weight_from_render(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Choose Light/Medium toolbar faces from rendered ink coverage."""
    calibrated = copy.deepcopy(dict(design))
    toolbar_bounds = _toolbar_bounds(calibrated)
    if toolbar_bounds is None:
        return calibrated, {
            "schema_version": "grounding-toolbar-font-weight/1.0",
            "status": "not-needed",
            "adjusted_count": 0,
            "adjustments": [],
        }
    left, top, right, bottom = toolbar_bounds
    adjustments: list[dict[str, Any]] = []
    for element in calibrated.get("elements") or []:
        if not isinstance(element, dict):
            continue
        if str(element.get("type") or "") not in {"input", "button"}:
            continue
        text = str(element.get("text") or "")
        if not text:
            continue
        source = _table_source_ink(element)
        if source is None:
            continue
        source_bbox, _target_ink = source
        center_x = source_bbox[0] + source_bbox[2] / 2
        center_y = source_bbox[1] + source_bbox[3] / 2
        if not (left <= center_x <= right and top <= center_y <= bottom):
            continue
        reference_pixels = _contrast_ink_pixel_count(reference_path, source_bbox)
        if reference_pixels <= 0:
            continue
        rendered_pixels = _contrast_ink_pixel_count(rendered_path, source_bbox)
        if rendered_pixels <= 0:
            continue
        coverage = float(rendered_pixels) / float(reference_pixels)
        style = element.setdefault("style", {})
        previous = style.get("fontWeight")
        evidence = element.get("styleEvidence")
        evidence_values = (
            evidence.get("evidence") if isinstance(evidence, Mapping) else {}
        )
        text_luminance = _color_luminance(
            style.get("textColor") or (evidence_values or {}).get("foreground")
        )
        selection_basis = "coverage"
        if text_luminance is not None and text_luminance < 128:
            if coverage > 1.9 and previous not in {300, "300", "light"}:
                updated = 300
                selection_basis = "dark-text-heavy-over-ink"
            elif previous not in {
                350,
                "350",
                "semilight",
                "semi light",
                "demilight",
            }:
                updated = 350
                selection_basis = "dark-text-demi-light"
            else:
                continue
        elif (
            text_luminance is not None
            and text_luminance > 200
            and previous not in {500, "500", "medium"}
        ):
            updated = 500
            selection_basis = "light-text"
        elif coverage > 1.9 and previous not in {300, "300", "light"}:
            updated = 300
            selection_basis = "heavy-over-ink"
        elif coverage > 1.18 and previous not in {
            350,
            "350",
            "semilight",
            "semi light",
            "demilight",
        }:
            updated = 350
            selection_basis = "over-ink-demi-light"
        elif coverage < 0.92 and previous not in {500, "500", "medium"}:
            updated = 500
            selection_basis = "under-ink-medium"
        else:
            continue
        style["fontWeight"] = updated
        adjustments.append(
            {
                "contentRef": element.get("contentRef"),
                "text": text,
                "previous": previous,
                "updated": updated,
                "inkCoverageRatio": coverage,
                "referenceInkPixels": reference_pixels,
                "renderedInkPixels": rendered_pixels,
                "selectionBasis": selection_basis,
            }
        )
    return calibrated, {
        "schema_version": "grounding-toolbar-font-weight/1.0",
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


def _ink_convergence_gray(path: str):
    import numpy as np
    from PIL import Image

    with Image.open(path) as handle:
        return np.asarray(handle.convert("L"), dtype=np.int16)


def _ink_height(gray, box, pad: int = 4) -> int | None:
    """Ink extent inside ``box`` expanded by ``pad`` on every side.

    Polarity-agnostic contrast mask: the background is the median of the
    window border, ink is any pixel further than 40 away.  The padding
    recovers strokes clipped by a tight measurement box.
    """
    import numpy as np

    height, width = gray.shape
    x, y, w, h = (int(v) for v in box)
    left = max(0, x - pad)
    top = max(0, y - pad)
    right = min(width, x + w + pad)
    bottom = min(height, y + h + pad)
    if right - left < 3 or bottom - top < 3:
        return None
    crop = gray[top:bottom, left:right]
    border = np.concatenate([crop[0, :], crop[-1, :], crop[:, 0], crop[:, -1]])
    background = float(np.median(border))
    mask = np.abs(crop.astype(np.int16) - background) > 40
    if int(mask.sum()) < 3:
        return None
    rows, _cols = np.where(mask)
    return int(rows.max() - rows.min() + 1)


def calibrate_ink_convergence_from_render(
    design: dict[str, Any],
    image: str,
    export_path: str,
    readback: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Converge every text fontSize until rendered ink matches source ink.

    One-shot measurement (style resolver) is bounded by the tightness of the
    element box: a 20px box cannot yield a 24px ink height, and a loose box
    may measure chrome.  This pass closes the loop instead: it re-measures
    both sides at render time — the reference ink in a padded window of the
    element's own evidence box, the rendered ink in a padded window of the
    actual readback node bounds — and scales fontSize by their ratio.

    Two bands decide what a ratio means:

    Skip band [0.85, 1.175]: owners already matching are untouched.  A single
    ratio step is clamped to [0.7, 1.5] so one pass moves at most ~50%, and
    repeated calibration iterations converge geometrically.

    Both numbers were re-tested on 2026-11-10 and are load-bearing:

    * tightening the band to the roadmap's 1 +/- 0.05 moved dark's font_ratio
      only 0.906 -> 0.919 and regressed light-table (94.07 -> 93.33), because
      there a 0.90 ink ratio is a font-metric difference, not a size error;
    * discarding the clamp-saturated ratios (the "obviously wrong" 0.7 / 1.5
      edits) regressed light-table further (93.44) -- those edits were
      correcting genuinely oversized text.

    See ``docs/v2_mentor/20261110_font_weight_evidence.md`` §5.2.
    """
    reference = _ink_convergence_gray(image)
    rendered = _ink_convergence_gray(export_path)

    readback_nodes: list[dict[str, Any]] = []

    def _walk(node: dict[str, Any]) -> None:
        if node.get("type") == "TEXT":
            readback_nodes.append(
                {
                    "key": "".join(
                        str(node.get("characters") or "").split()
                    ).casefold(),
                    "x": float(node.get("x") or 0),
                    "y": float(node.get("y") or 0),
                    "width": float(node.get("width") or 0),
                    "height": float(node.get("height") or 0),
                }
            )
        for child in node.get("children") or []:
            _walk(child)

    root = dict(readback)
    root["x"], root["y"] = 0, 0
    _walk(root)

    used: set[int] = set()
    adjustments: list[dict[str, Any]] = []
    skipped = 0
    unmatched = 0
    for element in design.get("elements") or []:
        if element.get("type") != "text":
            continue
        evidence = (element.get("styleEvidence") or {}).get("evidence") or {}
        ink_bbox = evidence.get("ink_bbox")
        style = element.get("style") or {}
        size = style.get("fontSize")
        if not ink_bbox or not isinstance(size, (int, float)):
            continue
        key = "".join(str(element.get("text") or "").split()).casefold()
        candidates = [
            (index, node)
            for index, node in enumerate(readback_nodes)
            if node["key"] == key and index not in used
        ]
        if not candidates:
            unmatched += 1
            continue
        try:
            ex, ey = float(element.get("x") or 0), float(element.get("y") or 0)
        except (TypeError, ValueError):
            unmatched += 1
            continue
        index, node = min(
            candidates,
            key=lambda pair: abs(pair[1]["x"] - ex) + abs(pair[1]["y"] - ey),
        )
        used.add(index)
        reference_height = _ink_height(reference, ink_bbox)
        rendered_height = _ink_height(
            rendered, (node["x"], node["y"], node["width"], node["height"])
        )
        if not reference_height or not rendered_height or rendered_height < 3:
            skipped += 1
            continue
        ratio = reference_height / float(rendered_height)
        if 0.85 <= ratio <= 1.175:
            skipped += 1
            continue
        ratio = max(0.7, min(1.5, ratio))
        new_size = max(8.0, min(96.0, round(float(size) * ratio * 4) / 4))
        if abs(new_size - float(size)) < 0.25:
            skipped += 1
            continue
        element.setdefault("style", {})["fontSize"] = new_size
        if isinstance(element.get("styleEvidence"), dict):
            element["styleEvidence"]["fontSize"] = new_size
        adjustments.append(
            {
                "text": str(element.get("text") or "")[:20],
                "from": float(size),
                "to": new_size,
                "ratio": round(ratio, 3),
                "reference_ink": reference_height,
                "rendered_ink": rendered_height,
            }
        )
    report = {
        "schema_version": "grounding-ink-convergence-calibration/1.0",
        "status": "applied" if adjustments else "not-needed",
        "adjusted_count": len(adjustments),
        "skipped_count": skipped,
        "unmatched_count": unmatched,
        "adjustments": adjustments,
    }
    return design, report


def synthesize_selection_plate(
    design: Mapping[str, Any],
    image_path: str | Path,
    *,
    top_band_ratio: float = 0.10,
    pad: int = 22,
    color_distance: float = 40.0,
    min_fill_ratio: float = 0.45,
    radius: int = 10,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Emit the coloured plate behind a selected header tab.

    A selected tab is a filled shape, and the asset pass does not see it: on
    dark-card-grid the red pill behind ``模型广场`` (x 544-711, y 23-86) is not
    one of the nine assets, so the label renders as plain text on the page
    background.  The header is also the region with the worst chrome error, so
    the missing plate is measurable, not cosmetic.

    The plate is recoverable from pixels without detecting a component: for a
    label in the header band, take a window around its box, drop the page
    background, and look at what is left.  A plate fills most of that window
    with one colour and shows on both sides of the label; an icon beside the
    label does neither.  The plate's own bounding box comes from the connected
    run of that colour, so rounded corners and padding are kept as drawn.

    Emitted as a ``rectangle`` with ``paintDepth = 0``, inserted just before the
    label so every renderer paints it underneath.

    Args:
        design: Image design with ``elements`` and ``canvas``.
        image_path: Source screenshot the crop colours are read from.
        top_band_ratio: Fraction of canvas height that counts as the header.
        pad: Pixels searched around the label box on each side.
        color_distance: Per-channel distance from the background that counts as
            "not background".
        min_fill_ratio: Share of the window one colour must cover.
        radius: Corner radius written on the emitted plate.

    Returns:
        ``(calibrated_design, report)``.
    """
    import numpy as np
    from PIL import Image

    calibrated = copy.deepcopy(dict(design))
    report: dict[str, Any] = {
        "schema_version": "grounding-selection-plate/1.0",
        "status": "not-needed",
        "adjusted_count": 0,
        "plates": [],
        "skipped": [],
    }
    elements = [
        element
        for element in calibrated.get("elements") or []
        if isinstance(element, dict)
    ]
    canvas = calibrated.get("canvas")
    height = 0.0
    if isinstance(canvas, Mapping):
        raw = canvas.get("height")
        if isinstance(raw, (int, float)):
            height = float(raw)
    if height <= 0:
        return calibrated, report
    try:
        with Image.open(image_path) as handle:
            pixels = np.asarray(handle.convert("RGB")).astype(np.int16)
    except (OSError, ValueError):
        return calibrated, report
    image_h, image_w = pixels.shape[:2]
    band_bottom = int(min(image_h, max(1.0, height * top_band_ratio)))

    band = pixels[:band_bottom]
    colors, counts = np.unique(band.reshape(-1, 3), axis=0, return_counts=True)
    background = colors[int(counts.argmax())].astype(np.int16)

    def _component_box(
        window: np.ndarray, colour: np.ndarray, origin: tuple[int, int]
    ) -> tuple[int, int, int, int] | None:
        mask = np.abs(window - colour).max(axis=2) <= 20
        if mask.sum() < 200:
            return None
        rows = np.flatnonzero(mask.any(axis=1))
        cols = np.flatnonzero(mask.any(axis=0))
        return (
            origin[0] + int(cols[0]),
            origin[1] + int(rows[0]),
            origin[0] + int(cols[-1]) + 1,
            origin[1] + int(rows[-1]) + 1,
        )

    prepared: list[dict[str, Any]] = []
    for element in elements:
        if str(element.get("type") or "") not in {"text", "button"}:
            continue
        text = str(element.get("text") or "").strip()
        if not text:
            continue
        try:
            left, top, right, bottom = _box_of(element)
        except (TypeError, ValueError):
            continue
        if right <= left or bottom <= top:
            continue
        if (top + bottom) / 2.0 > band_bottom:
            continue
        x0 = max(0, int(left) - pad)
        y0 = max(0, int(top) - pad)
        x1 = min(image_w, int(right) + pad)
        y1 = min(image_h, int(bottom) + pad)
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        window = pixels[y0:y1, x0:x1]
        distance = np.abs(window - background).max(axis=2)
        painted = distance > color_distance
        if painted.mean() < min_fill_ratio:
            report["skipped"].append({"text": text[:24], "reason": "no filled area"})
            continue
        colour = np.median(window[painted], axis=0).astype(np.int16)
        same = np.abs(window - colour).max(axis=2) <= 20
        if same.mean() < min_fill_ratio:
            report["skipped"].append({"text": text[:24], "reason": "colour not dominant"})
            continue
        # A plate surrounds its label: sample a strip left of and right of it.
        left_strip = pixels[y0:y1, max(0, int(left) - pad) : max(1, int(left) - 2)]
        right_strip = pixels[y0:y1, min(image_w - 1, int(right) + 2) : x1]
        edges = 0
        for strip in (left_strip, right_strip):
            if strip.size and (np.abs(strip - colour).max(axis=2) <= 20).mean() >= 0.3:
                edges += 1
        if edges < 2:
            report["skipped"].append({"text": text[:24], "reason": "label not inside plate"})
            continue
        box = _component_box(window, colour, (x0, y0))
        if box is None:
            continue
        plate_w = box[2] - box[0]
        plate_h = box[3] - box[1]
        if plate_w * plate_h < 1.5 * (right - left) * (bottom - top):
            report["skipped"].append({"text": text[:24], "reason": "plate smaller than label"})
            continue
        if box[0] > left + 2 or box[2] < right - 2:
            report["skipped"].append({"text": text[:24], "reason": "plate does not cover label"})
            continue
        prepared.append(
            {
                "element": element,
                "text": text,
                "box": box,
                "colour": "#%02X%02X%02X"
                % (int(colour[0]), int(colour[1]), int(colour[2])),
            }
        )

    if not prepared:
        return calibrated, report

    existing_boxes = [
        _box_of(element)
        for element in elements
        if str(element.get("type") or "") in {"image", "rectangle"}
    ]
    for item in prepared:
        box = item["box"]
        covered = False
        for other in existing_boxes:
            width = min(box[2], other[2]) - max(box[0], other[0])
            height_ = min(box[3], other[3]) - max(box[1], other[1])
            if width <= 0 or height_ <= 0:
                continue
            if width * height_ / ((box[2] - box[0]) * (box[3] - box[1])) >= 0.8:
                covered = True
                break
        if covered:
            report["skipped"].append({"text": item["text"][:24], "reason": "already emitted"})
            continue
        element = item["element"]
        plate = {
            "type": "rectangle",
            "x": float(box[0]),
            "y": float(box[1]),
            "width": float(box[2] - box[0]),
            "height": float(box[3] - box[1]),
            "text": "",
            "style": {
                "fillColor": item["colour"],
                "borderRadius": int(min(radius, (box[3] - box[1]) // 2)),
            },
            "role": "selection-plate",
            "name": "selection-plate",
            "contentRef": None,
            "paintDepth": 0,
        }
        if element.get("sceneOwnerId"):
            plate["sceneOwnerId"] = element["sceneOwnerId"]
        index = elements.index(element)
        elements.insert(index, plate)
        report["plates"].append(
            {
                "text": item["text"][:24],
                "bbox": [float(value) for value in box],
                "fillColor": item["colour"],
            }
        )
    if report["plates"]:
        calibrated["elements"] = elements
        report["status"] = "applied"
        report["adjusted_count"] = len(report["plates"])
    return calibrated, report
