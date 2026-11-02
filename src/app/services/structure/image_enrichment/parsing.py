"""Parse candidate assets and background plans from model JSON.

Ported and adapted from:
https://github.com/50kg/image-to-slice
commit ecc184c982a000c815796864ecce034fc0030c31

MIT License
Copyright (c) 2026 liu chao

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

ALLOWED_SLICE_ASSET_KINDS = {
    "icon",
    "avatar",
    "illustration",
    "photo",
    "product-image",
    "complex-decoration",
    "complex-chart",
    "logo",
}
ALLOWED_BACKGROUND_OVERLAY_KINDS = {"code-overlay", "raster-overlay"}
MIN_SLICE_ASSET_SIZE = 8
MAX_BACKGROUND_CANDIDATES = 6
MAX_BACKGROUND_OVERLAYS = 48
MIN_BACKGROUND_SIZE = 24
MIN_OVERLAY_SIZE = 4
NAME_PATTERN = re.compile(r"[^a-z0-9]+")


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型没有返回 JSON 对象")
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def _normalize_slice_name(value: Any) -> str:
    normalized = str(value or "").strip()
    normalized = re.sub(
        r"\.(?:png|jpe?g|webp|gif|svg|avif)$", "", normalized, flags=re.IGNORECASE
    )
    normalized = unicodedata.normalize("NFKD", normalized).lower()
    normalized = NAME_PATTERN.sub("_", normalized).strip("_")[:64].rstrip("_")
    return normalized if re.search(r"[a-z]", normalized) else ""


def _reserve_name(value: Any, index: int, used: set[str]) -> str:
    normalized = _normalize_slice_name(value)
    if not normalized:
        candidate_index = index + 1
        while True:
            fallback = f"slice_{candidate_index:02d}"
            if fallback not in used:
                used.add(fallback)
                return fallback
            candidate_index += 1
    candidate = normalized
    suffix = 2
    while candidate in used:
        candidate = f"{normalized}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _confidence(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return min(1.0, max(0.0, number))


def _js_round(value: float) -> int:
    return math.floor(value + 0.5)


def _normalize_box(
    value: Any,
    bounds: tuple[int, int, int, int],
    minimum_size: int,
) -> tuple[list[int] | None, str | None]:
    if not isinstance(value, Mapping):
        return None, "invalid_bbox"
    x = _number(value.get("x"))
    y = _number(value.get("y"))
    width = _number(value.get("width"))
    height = _number(value.get("height"))
    if x is None or y is None or width is None or height is None:
        return None, "invalid_bbox"

    bound_x, bound_y, bound_width, bound_height = bounds
    raw_left = min(x, x + width)
    raw_top = min(y, y + height)
    raw_right = max(x, x + width)
    raw_bottom = max(y, y + height)
    left = _js_round(min(max(raw_left, bound_x), bound_x + bound_width))
    top = _js_round(min(max(raw_top, bound_y), bound_y + bound_height))
    right = _js_round(min(max(raw_right, bound_x), bound_x + bound_width))
    bottom = _js_round(min(max(raw_bottom, bound_y), bound_y + bound_height))
    if right - left < minimum_size or bottom - top < minimum_size:
        return None, "too_small"
    return [left, top, right - left, bottom - top], None


def _diagnostic(
    code: str,
    path: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "code": code,
        "path": path,
        "message": message,
        **details,
    }


def _parse_assets(value: Any, width: int, height: int) -> tuple[list[dict], list]:
    if value is None:
        return [], []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return [], [
            _diagnostic("invalid_assets", "assets", "assets must be an array")
        ]

    assets: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for index, raw_asset in enumerate(value):
        path = f"assets[{index}]"
        if not isinstance(raw_asset, Mapping):
            diagnostics.append(
                _diagnostic("invalid_asset", path, "asset must be an object")
            )
            continue
        kind = str(raw_asset.get("kind") or "").strip()
        if kind not in ALLOWED_SLICE_ASSET_KINDS:
            diagnostics.append(
                _diagnostic(
                    "unsupported_asset_kind",
                    f"{path}.kind",
                    f"unsupported asset kind: {kind or '<empty>'}",
                    kind=kind,
                )
            )
            continue
        bbox, bbox_error = _normalize_box(
            raw_asset.get("bbox"),
            (0, 0, width, height),
            MIN_SLICE_ASSET_SIZE,
        )
        if bbox_error:
            code = (
                "invalid_asset_bbox"
                if bbox_error == "invalid_bbox"
                else "asset_too_small"
            )
            diagnostics.append(
                _diagnostic(
                    code,
                    f"{path}.bbox",
                    "asset bbox is invalid or too small",
                )
            )
            continue
        assert bbox is not None
        assets.append(
            {
                "name": _reserve_name(raw_asset.get("name"), index, used_names),
                "kind": kind,
                "bbox": bbox,
                "confidence": _confidence(raw_asset.get("confidence")),
                "containsEmbeddedText": raw_asset.get("containsEmbeddedText")
                is True,
                "reason": str(raw_asset.get("reason") or "").strip()[:300],
            }
        )
    return assets, diagnostics


def _parse_overlays(
    value: Any,
    background_bbox: list[int],
    background_path: str,
) -> tuple[list[dict], list[dict]]:
    if value is None:
        return [], []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return [], [
            _diagnostic(
                "invalid_overlays",
                f"{background_path}.overlays",
                "overlays must be an array",
            )
        ]

    diagnostics: list[dict[str, Any]] = []
    if len(value) > MAX_BACKGROUND_OVERLAYS:
        diagnostics.append(
            _diagnostic(
                "overlay_limit_truncated",
                f"{background_path}.overlays",
                "overlay list exceeds the approved limit",
                actual=len(value),
                limit=MAX_BACKGROUND_OVERLAYS,
            )
        )
    overlays: list[dict[str, Any]] = []
    bounds = tuple(background_bbox)
    for index, raw_overlay in enumerate(value[:MAX_BACKGROUND_OVERLAYS]):
        path = f"{background_path}.overlays[{index}]"
        if not isinstance(raw_overlay, Mapping):
            diagnostics.append(
                _diagnostic("invalid_overlay", path, "overlay must be an object")
            )
            continue
        kind = str(raw_overlay.get("kind") or "").strip()
        if kind not in ALLOWED_BACKGROUND_OVERLAY_KINDS:
            diagnostics.append(
                _diagnostic(
                    "unsupported_overlay_kind",
                    f"{path}.kind",
                    f"unsupported overlay kind: {kind or '<empty>'}",
                    kind=kind,
                )
            )
            continue
        bbox, bbox_error = _normalize_box(
            raw_overlay.get("bbox"), bounds, MIN_OVERLAY_SIZE
        )
        if bbox_error:
            code = (
                "invalid_overlay_bbox"
                if bbox_error == "invalid_bbox"
                else "overlay_too_small"
            )
            diagnostics.append(
                _diagnostic(
                    code,
                    f"{path}.bbox",
                    "overlay bbox is invalid or outside its background",
                )
            )
            continue
        assert bbox is not None
        overlays.append(
            {
                "id": str(raw_overlay.get("id") or "").strip()[:120]
                or f"overlay_{index + 1:02d}",
                "name": str(raw_overlay.get("name") or "").strip()[:120]
                or f"overlay_{index + 1:02d}",
                "kind": kind,
                "bbox": bbox,
                "confidence": _confidence(raw_overlay.get("confidence")),
                "reason": str(raw_overlay.get("reason") or "").strip()[:300],
            }
        )
    return overlays, diagnostics


def _parse_backgrounds(
    value: Any, width: int, height: int
) -> tuple[list[dict], list[dict]]:
    if value is None:
        return [], []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return [], [
            _diagnostic(
                "invalid_backgrounds", "backgrounds", "backgrounds must be an array"
            )
        ]

    diagnostics: list[dict[str, Any]] = []
    if len(value) > MAX_BACKGROUND_CANDIDATES:
        diagnostics.append(
            _diagnostic(
                "background_limit_truncated",
                "backgrounds",
                "background list exceeds the approved limit",
                actual=len(value),
                limit=MAX_BACKGROUND_CANDIDATES,
            )
        )
    backgrounds: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for index, raw_background in enumerate(value[:MAX_BACKGROUND_CANDIDATES]):
        path = f"backgrounds[{index}]"
        if not isinstance(raw_background, Mapping):
            diagnostics.append(
                _diagnostic(
                    "invalid_background", path, "background must be an object"
                )
            )
            continue
        bbox, bbox_error = _normalize_box(
            raw_background.get("bbox"),
            (0, 0, width, height),
            MIN_BACKGROUND_SIZE,
        )
        if bbox_error:
            code = (
                "invalid_background_bbox"
                if bbox_error == "invalid_bbox"
                else "background_too_small"
            )
            diagnostics.append(
                _diagnostic(
                    code,
                    f"{path}.bbox",
                    "background bbox is invalid or too small",
                )
            )
            continue
        assert bbox is not None
        overlays, overlay_diagnostics = _parse_overlays(
            raw_background.get("overlays"), bbox, path
        )
        diagnostics.extend(overlay_diagnostics)
        baked_visuals = []
        if isinstance(raw_background.get("bakedVisuals"), Sequence) and not isinstance(
            raw_background.get("bakedVisuals"), (str, bytes)
        ):
            for entry in raw_background["bakedVisuals"][:24]:
                text = str(entry or "").strip()[:120]
                if text:
                    baked_visuals.append(text)
        backgrounds.append(
            {
                "id": str(raw_background.get("id") or "").strip()[:120]
                or f"background_{index + 1:02d}",
                "name": _reserve_name(
                    raw_background.get("name"), index, used_names
                ),
                "bbox": bbox,
                "confidence": _confidence(raw_background.get("confidence")),
                "reason": str(raw_background.get("reason") or "").strip()[:300],
                "bakedVisuals": baked_visuals,
                "overlays": overlays,
            }
        )
    return backgrounds, diagnostics


def parse_enrichment_response(
    raw: str,
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    """Parse one enrichment response and normalize all retained candidates."""

    width = _positive_int(image_width, "image size width")
    height = _positive_int(image_height, "image size height")
    value = _extract_json_object(raw)
    assets, asset_diagnostics = _parse_assets(value.get("assets"), width, height)
    backgrounds, background_diagnostics = _parse_backgrounds(
        value.get("backgrounds"), width, height
    )
    return {
        "assets": assets,
        "backgrounds": backgrounds,
        "diagnostics": asset_diagnostics + background_diagnostics,
    }
