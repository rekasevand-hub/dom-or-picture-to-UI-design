from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _finite_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result else default


def _normalized_align(value: Any) -> str:
    align = str(value or "").strip().lower()
    if align in {"center", "middle"}:
        return "center"
    if align in {"end", "right"}:
        return "end"
    if align in {"justify", "start", "left"}:
        return align
    return "start"


def _normalize_measured(
    measured_lines: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[str], list[list[int]], list[dict[str, Any]]]:
    lines: list[str] = []
    boxes: list[list[int]] = []
    normalized: list[dict[str, Any]] = []
    for source in measured_lines or []:
        if not isinstance(source, Mapping):
            continue
        text = str(source.get("text") or "")
        if not text:
            continue
        item = dict(source)
        box = source.get("box")
        if isinstance(box, (list, tuple)) and len(box) == 4:
            try:
                normalized_box = [
                    int(round(float(value)))
                    for value in box
                ]
            except (TypeError, ValueError):
                normalized_box = []
            if normalized_box and normalized_box[2] > 0 and normalized_box[3] > 0:
                item["box"] = normalized_box
                boxes.append(normalized_box)
        lines.append(text)
        normalized.append(item)
    return lines, boxes, normalized


def _estimated_lines(spec: Mapping[str, Any]) -> tuple[list[str], str]:
    from src.app.services.rendering import text_wrap

    text = str(spec.get("text") or "")
    if not text:
        return [], "estimated"
    width = _finite_float(spec.get("width"), 0.0)
    font_size = text_wrap.font_size_of(dict(spec))
    letter_spacing = text_wrap.letter_spacing_of(dict(spec))
    line_height = text_wrap.line_height_of(dict(spec), font_size)
    max_lines = text_wrap.max_lines_of(dict(spec), line_height)
    try:
        height = float(spec.get("height") or 0)
        explicit_max_lines = int(spec.get("maxLines") or 0)
    except (TypeError, ValueError):
        height = 0.0
        explicit_max_lines = 0
    if height <= 0 and explicit_max_lines < 1:
        max_lines = text_wrap._MAX_LINES_CAP
    wrapped = None
    if width > 0 and str(spec.get("whiteSpace") or "").lower() != "nowrap":
        wrapped = text_wrap.wrap_lines(
            text,
            width,
            font_size,
            max_lines=max_lines,
            letter_spacing=letter_spacing,
        )
    return (wrapped or [text]), ("estimated-wrap" if wrapped else "estimated")


def layout_text(
    spec: Mapping[str, Any],
    *,
    measured_lines: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    from src.app.services.rendering.text_wrap import (
        font_size_of,
        line_height_of,
    )

    source_lines = measured_lines
    if source_lines is None:
        candidate = spec.get("measuredLines")
        if isinstance(candidate, (list, tuple)):
            source_lines = candidate
    lines, line_boxes, normalized = _normalize_measured(source_lines)
    font_size = font_size_of(dict(spec))
    line_height = line_height_of(dict(spec), font_size)
    text_align = _normalized_align(spec.get("textAlign"))
    baseline = spec.get("textBaseline")
    baseline_source = "browser-measured" if isinstance(baseline, Mapping) else ""

    if lines:
        if line_boxes:
            line_height = max(box[3] for box in line_boxes)
        elif isinstance(baseline, Mapping) and baseline.get("lineCount"):
            line_height = line_height
        return {
            "lines": lines,
            "lineBoxes": line_boxes,
            "lineHeight": int(round(line_height)),
            "textAlign": text_align,
            "source": "browser-range",
            "baselineSource": baseline_source or "browser-measured",
            "confidence": 1.0,
            "measuredLines": normalized,
        }

    string_lines = [
        str(line)
        for line in (spec.get("lines") or [])
        if str(line)
    ]
    if string_lines:
        return {
            "lines": string_lines,
            "lineBoxes": [],
            "lineHeight": int(round(line_height)),
            "textAlign": text_align,
            "source": "browser-range",
            "baselineSource": baseline_source or "browser-measured",
            "confidence": 0.95,
            "measuredLines": [],
        }

    estimated_lines, estimated_source = _estimated_lines(spec)
    boxes = [
        [0, int(round(index * line_height)), 0, int(round(line_height))]
        for index in range(len(estimated_lines))
    ]
    return {
        "lines": estimated_lines,
        "lineBoxes": boxes,
        "lineHeight": int(round(line_height)),
        "textAlign": text_align,
        "source": "estimated",
        "baselineSource": "estimated",
        "confidence": 0.45 if estimated_source == "estimated-wrap" else 0.6,
        "estimatedSource": estimated_source,
        "measuredLines": [],
    }
