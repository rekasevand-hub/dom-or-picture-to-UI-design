"""Resolve text style evidence from source screenshot pixels."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.app.services.structure.fidelity.contracts import normalize_bbox
from src.app.services.structure.fidelity.pixel_probe import ink_line_bands, line_metrics

SCHEMA_VERSION = "grounding-text-style-evidence/1.0"

_CJK_FAMILY = "Noto Sans SC"
_LATIN_FAMILY = "Open Sans"


def _hex_color(values: Sequence[float]) -> str:
    red, green, blue = (
        max(0, min(255, int(round(float(value))))) for value in values[:3]
    )
    return f"#{red:02x}{green:02x}{blue:02x}"


def _has_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def _alignment(
    ink_bbox: list[int],
    parent_bbox: Sequence[int] | None,
    role: str,
) -> tuple[str, float | None]:
    if parent_bbox is None:
        return ("center" if role == "table-header" else "left"), None
    try:
        parent_x, _parent_y, parent_width, _parent_height = (
            int(round(float(value))) for value in parent_bbox
        )
    except (TypeError, ValueError, OverflowError):
        return "left", None
    if parent_width <= 0:
        return "left", None
    ink_center = ink_bbox[0] + ink_bbox[2] / 2
    parent_center = parent_x + parent_width / 2
    delta = abs(ink_center - parent_center)
    if role == "table-header":
        return "center", delta
    tolerance = max(4.0, parent_width * 0.06)
    if delta <= tolerance:
        return "center", delta
    if ink_center < parent_center:
        return "left", delta
    return "right", delta


def _supports_multiline(text: str, bands: list[tuple[int, int]]) -> bool:
    """Whether the projection bands really are separate text lines.

    CJK glyphs are made of disjoint horizontal strokes, so a single 28px label
    splits into several thin bands whose heights differ by a lot.  Real lines
    of one paragraph share a type scale (near-equal band heights) and carry
    enough characters to need wrapping; short labels never wrap.
    """
    if len(text.strip()) < 8:
        return False
    heights = [end - start for start, end in bands]
    if len(heights) < 2 or min(heights) <= 0:
        return False
    return max(heights) / min(heights) <= 1.6


def resolve_text_style(
    image_path: str | Path,
    text: str,
    bbox: Sequence[int],
    *,
    parent_bbox: Sequence[int] | None = None,
    role: str = "",
) -> dict[str, Any]:
    """Infer a fixed-canvas text style while retaining pixel evidence."""
    import numpy as np
    from PIL import Image

    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with Image.open(path) as source:
        image = np.asarray(source.convert("RGB"), dtype=np.int16)
    height, width = image.shape[:2]
    normalized = normalize_bbox(bbox, width, height)
    if normalized is None:
        raise ValueError("text bbox must be a positive source-pixel bbox")
    x, y, box_width, box_height = normalized
    crop = image[y : y + box_height, x : x + box_width]
    if crop.size == 0:
        raise ValueError("text bbox does not intersect the source image")

    inset = 2 if min(box_width, box_height) >= 8 else 1
    inner = crop[
        inset : max(inset + 1, box_height - inset),
        inset : max(inset + 1, box_width - inset),
    ]
    border = np.concatenate(
        [
            inner[0, :, :],
            inner[-1, :, :],
            inner[:, 0, :],
            inner[:, -1, :],
        ],
        axis=0,
    )
    background_rgb = np.median(border, axis=0)
    distance = np.abs(crop - background_rgb.reshape(1, 1, 3)).max(axis=2)
    mask = distance >= 24
    mask[
        mask.sum(axis=1) >= max(4, int(round(box_width * 0.75))),
        :,
    ] = False
    mask[
        :,
        mask.sum(axis=0) >= max(4, int(round(box_height * 0.75))),
    ] = False
    ink_count = int(mask.sum())
    if ink_count < 2:
        align, center_delta = _alignment(normalized, parent_bbox, role)
        family = _CJK_FAMILY if _has_cjk(text) else _LATIN_FAMILY
        return {
            "schema_version": SCHEMA_VERSION,
            "fontFamily": family,
            "fontFallbacks": [
                "Microsoft YaHei" if _has_cjk(text) else "Arial",
                "sans-serif",
            ],
            # A box can only justify type it can hold.  Deriving the size from
            # height alone gave a 25x73 table cell 55px type, which then wrapped
            # one glyph per line; no single glyph may be wider than the box.
            "fontSize": max(
                8.0, round(min(box_height * 0.75, max(8.0, box_width)) * 4) / 4
            ),
            "fontWeight": "bold" if role == "table-header" else "normal",
            "textColor": "#555555",
            "textAlign": align,
            "lineHeightPolicy": "auto",
            "confidence": 0.2,
            "evidence": {
                "status": "low-confidence",
                "reason": "text-ink-not-found",
                "source_bbox": normalized,
                "background": _hex_color(background_rgb),
                "foreground": "#555555",
                "script": "cjk" if _has_cjk(text) else "latin",
                "parent_center_delta": center_delta,
            },
        }

    bands = ink_line_bands(mask)
    metrics = line_metrics(bands)
    line_count = int(metrics.get("lineCount") or 0)
    if line_count >= 2 and not _supports_multiline(text, bands):
        line_count = 1

    ys, xs = np.where(mask)
    ink_left = int(xs.min())
    ink_top = int(ys.min())
    ink_right = int(xs.max()) + 1
    ink_bottom = int(ys.max()) + 1
    ink_box = [
        x + ink_left,
        y + ink_top,
        ink_right - ink_left,
        ink_bottom - ink_top,
    ]
    strong_threshold = float(np.percentile(distance[mask], 80))
    strong_mask = mask & (distance >= max(32.0, strong_threshold))
    low_contrast = not strong_mask.any()
    if low_contrast:
        strong_mask = mask
    foreground_rgb = np.median(crop[strong_mask], axis=0)
    contrast = float(distance[strong_mask].mean()) if strong_mask.any() else 0.0
    align, center_delta = _alignment(ink_box, parent_bbox, role)
    cjk = _has_cjk(text)
    family = _CJK_FAMILY if cjk else _LATIN_FAMILY
    estimated_size = max(
        8.0,
        min(96.0, round((ink_box[3] * 0.95) * 4) / 4),
    )
    line_height: float | None = None
    line_height_policy = "auto"
    if line_count >= 2:
        # The bbox of a paragraph spans every visual line, so scaling the whole
        # ink height inflates the type by the line count (24px reported for a
        # real 14px body).  Use the median single-line ink height instead, and
        # keep the measured pitch so the text cannot grow past its box.
        median_height = float(metrics.get("medianLineHeight") or 0)
        if median_height >= 2:
            estimated_size = max(
                8.0,
                min(96.0, round(median_height * 0.95 * 4) / 4),
            )
        pitch = float(metrics.get("linePitch") or 0)
        if estimated_size * 1.02 <= pitch <= estimated_size * 3.0:
            line_height = round(pitch * 4) / 4
            line_height_policy = "observed"
    weight = "bold" if role == "table-header" else "normal"
    confidence = min(0.95, 0.6 + min(0.25, contrast / 255))
    if low_contrast:
        confidence = min(confidence, 0.65)
    result = {
        "schema_version": SCHEMA_VERSION,
        "fontFamily": family,
        "fontFallbacks": [
            "Microsoft YaHei" if cjk else "Arial",
            "sans-serif",
        ],
        "fontSize": estimated_size,
        "fontWeight": weight,
        "textColor": _hex_color(foreground_rgb),
        "textAlign": align,
        "lineHeightPolicy": line_height_policy,
        "confidence": confidence,
        "evidence": {
            "status": "low-contrast" if low_contrast else "observed",
            "source_bbox": normalized,
            "ink_bbox": ink_box,
            "background": _hex_color(background_rgb),
            "foreground": _hex_color(foreground_rgb),
            "contrast_delta": round(contrast, 3),
            "ink_pixel_count": ink_count,
            "script": "cjk" if cjk else "latin",
            "parent_center_delta": center_delta,
            "line_count": line_count,
            "line_bands": [list(band) for band in bands],
        },
    }
    if line_height is not None:
        result["lineHeight"] = line_height
    return result
