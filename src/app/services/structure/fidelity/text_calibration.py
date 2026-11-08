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
    """Fit light-on-white placeholder text whose glyph ink is underweighted."""
    calibrated = copy.deepcopy(dict(design))
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
