"""Deterministic source-pixel tiling for Grounding image inputs."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from PIL import Image


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _source_rect(tile: Mapping[str, Any]) -> tuple[int, int, int, int]:
    value = tile.get("source_rect")
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise ValueError("tile.source_rect must contain four integers")
    x, y, width, height = (int(item) for item in value)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(
            "tile.source_rect must use non-negative origin and positive size"
        )
    return x, y, width, height


def _normalized_break_ys(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("break_y must be a list of integers")
    normalized: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError("break_y must be a list of integers")
        normalized.append(item)
    return sorted(set(normalized))


def _nearest_boundary(
    candidates: list[int], default_y: int, window_end: int, height: int
) -> int | None:
    eligible = [
        candidate
        for candidate in candidates
        if default_y <= candidate <= window_end and candidate < height
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda candidate: (abs(candidate - default_y), candidate))


def plan_image_tiles(
    width: int,
    height: int,
    *,
    max_tile_height: int = 4096,
    overlap: int = 256,
    break_y: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Plan vertical source-pixel tiles without resizing the original image."""

    page_width = _positive_int(width, "width")
    page_height = _positive_int(height, "height")
    max_height = _positive_int(max_tile_height, "max_tile_height")
    requested_overlap = _non_negative_int(overlap, "overlap")
    boundaries = _normalized_break_ys(break_y)

    tile_height = min(max_height, page_height)
    effective_overlap = min(requested_overlap, tile_height - 1)
    step = tile_height - effective_overlap
    if step <= 0:
        raise ValueError("tile plan cannot progress")

    tiles: list[dict[str, Any]] = []
    y = 0
    previous_end = 0
    reason = "single-tile" if tile_height == page_height else "page-start"

    while y < page_height:
        current_height = min(tile_height, page_height - y)
        end = y + current_height
        overlap_with_previous = max(0, previous_end - y) if tiles else 0
        index = len(tiles)
        tile_reason = reason
        if end >= page_height and index > 0 and reason == "configured-height":
            tile_reason = "page-end"
        tiles.append(
            {
                "id": f"tile-{index:04d}",
                "index": index,
                "source_rect": [0, y, page_width, current_height],
                "page_origin": [0, y],
                "overlap_with_previous": overlap_with_previous,
                "reason": tile_reason,
            }
        )
        if end >= page_height:
            break

        default_next_y = end - effective_overlap
        boundary = _nearest_boundary(boundaries, default_next_y, end, page_height)
        if boundary is None:
            y = default_next_y
            reason = "configured-height"
        else:
            y = boundary
            reason = "section-boundary"
        previous_end = end

    return tiles


def crop_image_tile(image: Image.Image, tile: dict[str, Any]) -> Image.Image:
    """Crop one tile from source pixels without resizing or recoloring."""

    x, y, width, height = _source_rect(tile)
    if x + width > image.width or y + height > image.height:
        raise ValueError("tile.source_rect is outside image bounds")
    return image.crop((x, y, x + width, y + height))


def _normalized_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"bbox {field} must be a normalized number")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError(f"bbox {field} must be a normalized number")
    return number


def _scale(value: float, size: int) -> int:
    return math.floor(value * size + 0.5)


def translate_bbox_to_page(
    bbox: list[float], tile: dict[str, Any]
) -> list[int]:
    """Translate a normalized tile bbox to original page-pixel coordinates."""

    if (
        isinstance(bbox, (str, bytes))
        or not isinstance(bbox, Sequence)
        or len(bbox) != 4
    ):
        raise ValueError("bbox must contain four normalized numbers")
    x = _normalized_number(bbox[0], "x")
    y = _normalized_number(bbox[1], "y")
    width = _normalized_number(bbox[2], "width")
    height = _normalized_number(bbox[3], "height")
    if width <= 0 or height <= 0:
        raise ValueError("bbox must have positive normalized size")

    tile_x, tile_y, tile_width, tile_height = _source_rect(tile)
    page_bbox = [
        tile_x + _scale(x, tile_width),
        tile_y + _scale(y, tile_height),
        _scale(width, tile_width),
        _scale(height, tile_height),
    ]
    if page_bbox[2] <= 0 or page_bbox[3] <= 0:
        raise ValueError("bbox is too small to produce a page-pixel rectangle")
    return page_bbox
