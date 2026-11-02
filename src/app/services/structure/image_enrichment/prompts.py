"""Prompts for tiled Grounding and background restoration.

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
from collections.abc import Mapping, Sequence
from typing import Any


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _source_rect(tile: Mapping[str, Any]) -> tuple[int, int, int, int]:
    value = tile.get("source_rect")
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != 4
    ):
        raise ValueError("tile.source_rect must contain four integers")
    values = tuple(_integer(item, "tile.source_rect") for item in value)
    if values[2] <= 0 or values[3] <= 0:
        raise ValueError("tile.source_rect must have positive size")
    return values  # type: ignore[return-value]


def _page_size(
    page_context: Mapping[str, Any], source_rect: tuple[int, int, int, int]
) -> tuple[int, int]:
    value = page_context.get("image_size")
    if value is not None:
        if (
            isinstance(value, (str, bytes))
            or not isinstance(value, Sequence)
            or len(value) != 2
        ):
            raise ValueError("page_context.image_size must contain width and height")
        width = _integer(value[0], "page_context.image_size")
        height = _integer(value[1], "page_context.image_size")
        if width <= 0 or height <= 0:
            raise ValueError("page_context.image_size must be positive")
        return width, height
    return source_rect[2], source_rect[1] + source_rect[3]


def _context_text(page_context: Mapping[str, Any]) -> str:
    text = json.dumps(
        page_context,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return text[:4000]


def build_grounding_tile_prompt(tile: dict, page_context: dict) -> str:
    """Build the candidate prompt for one source-pixel tile."""

    if not isinstance(tile, Mapping):
        raise ValueError("tile must be an object")
    if not isinstance(page_context, Mapping):
        raise ValueError("page_context must be an object")
    source_rect = _source_rect(tile)
    page_width, page_height = _page_size(page_context, source_rect)
    tile_id = str(tile.get("id") or "tile")
    origin_x, origin_y, tile_width, tile_height = source_rect
    context_text = _context_text(page_context)

    return "\n".join(
        [
            "Analyze the attached UI tile and return enrichment candidates as one JSON object.",
            f"Tile id: {tile_id}.",
            f"Original page size: {page_width}x{page_height} pixels.",
            f"Tile image size: {tile_width}x{tile_height} pixels.",
            f"Tile source origin on page: ({origin_x}, {origin_y}).",
            "All bbox values must use pixel coordinates relative to this tile's top-left. Do not use percentages or coordinates relative to the full page.",
            "Use bbox objects shaped as {x, y, width, height} in source-image pixels.",
            "Allowed asset kinds: icon, avatar, illustration, photo, product-image, complex-decoration, complex-chart, logo.",
            "Return an asset only when its exact raster appearance cannot be reliably rebuilt as ordinary text or simple CSS shapes.",
            "Do not return ordinary UI text, button backgrounds, cards, dividers, simple rectangles, circles, or layout containers as assets.",
            "A logo, badge, illustration, or chart containing inseparable artistic content may be returned as one complete crop.",
            "Do not merge visually independent assets merely because their boxes overlap. Preserve source reading order.",
            "Every asset and background name must be specific English snake_case. Never use Chinese, spaces, hyphens, file extensions, or generic labels except when content is truly unidentifiable.",
            "Find continuous illustrated, photographic, textured, or decorated background regions partially covered by foreground UI.",
            "Classify obvious foreground interface controls and ordinary text as code-overlay.",
            "Use raster-overlay only for a visually independent foreground bitmap that cannot be rebuilt as text, CSS, or a simple vector icon.",
            "Preserve baked visual content inside a background, including illustrations, scenery, products, decorative frames, artistic text, and integrated branding.",
            f"Page context: {context_text}",
            'Return {"assets":[{"name":"specific_name","kind":"icon","bbox":{"x":0,"y":0,"width":8,"height":8},"confidence":0.0,"containsEmbeddedText":false,"reason":"why"}],"backgrounds":[{"id":"background_01","name":"specific_background","bbox":{"x":0,"y":0,"width":100,"height":100},"confidence":0.0,"reason":"why","bakedVisuals":[],"overlays":[{"id":"overlay_01","name":"overlay","kind":"code-overlay","bbox":{"x":0,"y":0,"width":20,"height":20},"confidence":0.0,"reason":"why"}]}]}',
            "Return empty arrays when no candidate exists. Return JSON only, with no Markdown or explanation.",
        ]
    )


def build_background_mask_prompt(background: dict, overlays: list[dict]) -> str:
    """Build the restoration prompt for a background and its selected overlays."""

    if not isinstance(background, Mapping):
        raise ValueError("background must be an object")
    if isinstance(overlays, (str, bytes)) or not isinstance(overlays, Sequence):
        raise ValueError("overlays must be an array")
    background_id = str(background.get("id") or "background")
    background_name = str(background.get("name") or background_id)
    background_bbox = background.get("bbox")
    if (
        isinstance(background_bbox, (str, bytes))
        or not isinstance(background_bbox, Sequence)
        or len(background_bbox) != 4
    ):
        raise ValueError("background.bbox must contain four integers")
    bbox_values = [_integer(value, "background.bbox") for value in background_bbox]

    normalized_overlays = []
    for index, overlay in enumerate(overlays):
        if not isinstance(overlay, Mapping):
            raise ValueError(f"overlays[{index}] must be an object")
        overlay_bbox = overlay.get("bbox")
        if (
            isinstance(overlay_bbox, (str, bytes))
            or not isinstance(overlay_bbox, Sequence)
            or len(overlay_bbox) != 4
        ):
            raise ValueError(f"overlays[{index}].bbox must contain four integers")
        normalized_overlays.append(
            {
                "id": str(overlay.get("id") or f"overlay_{index + 1:02d}"),
                "name": str(overlay.get("name") or ""),
                "kind": str(overlay.get("kind") or ""),
                "bbox": [
                    _integer(value, f"overlays[{index}].bbox")
                    for value in overlay_bbox
                ],
            }
        )

    return "\n".join(
        [
            f"Reconstruct the clean background behind {background_id} ({background_name}).",
            f"Background page-pixel bbox: {bbox_values}.",
            "Preserve baked visual content that belongs to the background, including scenery, products, textures, decorative frames, artistic text, and integrated branding.",
            "Remove only the selected foreground overlays listed below.",
            "Do not invent new brands, text, products, or interface content that is not visible in the source.",
            "Native mask convention: selected/editable overlay regions must be transparent; protected context outside those regions must remain opaque.",
            f"Selected overlays: {json.dumps(normalized_overlays, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}",
            "Keep reconstruction inside the background bounds and preserve the source aspect ratio and visual hierarchy.",
            "Return a clean background candidate, not a full UI screenshot and not a newly composed interface.",
        ]
    )
