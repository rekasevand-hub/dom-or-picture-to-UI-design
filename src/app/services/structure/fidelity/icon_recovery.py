"""Recover small standalone visual regions (icons, logos, badges).

Grounding reliably reports large photos and avatars but drops 16-64px glyph
icons and pill badges — the toolbar icons and Star/like affordances simply do
not survive normalisation.  The older recovery helper returned early as soon
as one image existed, so on a real marketplace screenshot every small icon was
missing from the Figma file.

This pass is deliberately conservative: it only emits regions that sit outside
every already-explained element, are roughly square, are solid enough to be a
glyph, and are not a flat colour block.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MIN_SIDE = 12
MAX_SIDE = 64
MIN_FILL_RATIO = 0.25
MAX_COLORS_DOMINANCE = 0.92
MAX_OVERLAP_WITH_KNOWN = 0.25
MAX_OVERLAP_BETWEEN_CANDIDATES = 0.45
BACKGROUND_TOLERANCE = 22
EDGE_MARGIN = 2

# Anything already accounted for by structure or text — an icon inside these
# is either covered by the owner or already explained.
_EXCLUDED_TYPES = {
    "text",
    "link",
    "button",
    "input",
    "control",
    "icon-button",
    "image",
    "avatar",
    "checkbox",
    "radio",
    "select",
    "navigation",
    "pagination",
}


def _box_overlap(left: Sequence[int], right: Sequence[int]) -> float:
    ax, ay, aw, ah = (float(v) for v in left)
    bx, by, bw, bh = (float(v) for v in right)
    overlap_width = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    overlap_height = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    intersection = overlap_width * overlap_height
    if intersection <= 0:
        return 0.0
    return intersection / max(1.0, min(aw * ah, bw * bh))


def _pixel_bbox(item: Mapping[str, Any], width: int, height: int) -> list[int] | None:
    bbox = item.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        values = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    if max(values) <= 1.0 and min(values) >= 0.0:
        values = [
            values[0] * width,
            values[1] * height,
            values[2] * width,
            values[3] * height,
        ]
    x, y, box_width, box_height = (int(round(value)) for value in values)
    if box_width <= 0 or box_height <= 0:
        return None
    return [x, y, box_width, box_height]


def recover_small_icon_regions(
    graph: Mapping[str, Any],
    image_path: str | Path,
    *,
    max_regions: int = 12,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Append ``image`` elements for small visual regions nobody explained."""
    import cv2
    import numpy as np

    recovered = copy.deepcopy(dict(graph))
    schema = "image-icon-recovery/1.0"
    image = cv2.imread(str(image_path))
    if image is None:
        return recovered, {
            "schema_version": schema,
            "status": "unreadable",
            "added_count": 0,
            "added": [],
        }
    height, width = image.shape[:2]
    elements = recovered.get("elements") or []

    border_pixels = np.concatenate(
        [
            image[0:2, :, :].reshape(-1, 3),
            image[max(0, height - 2) : height, :, :].reshape(-1, 3),
            image[:, 0:2, :].reshape(-1, 3),
            image[:, max(0, width - 2) : width, :].reshape(-1, 3),
        ],
        axis=0,
    )
    background = np.median(border_pixels, axis=0).astype(np.int16)
    difference = np.abs(image.astype(np.int16) - background.reshape(1, 1, 3)).max(axis=2)
    mask = (difference >= BACKGROUND_TOLERANCE).astype(np.uint8)

    known: list[list[int]] = []
    for item in elements:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("type") or "").lower() not in _EXCLUDED_TYPES:
            continue
        bbox = _pixel_bbox(item, width, height)
        if bbox is None:
            continue
        known.append(bbox)
        pad = 2
        x, y, box_width, box_height = bbox
        mask[
            max(0, y - pad) : min(height, y + box_height + pad),
            max(0, x - pad) : min(width, x + box_width + pad),
        ] = 0

    closed = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8)
    )
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(closed, 8)

    candidates: list[tuple[int, list[int]]] = []
    for index in range(1, count):
        x, y, box_width, box_height, area = (
            int(value) for value in stats[index, :5]
        )
        if box_width < MIN_SIDE or box_height < MIN_SIDE:
            continue
        if box_width > MAX_SIDE or box_height > MAX_SIDE:
            continue
        ratio = box_width / box_height if box_height else 0.0
        if ratio < 0.45 or ratio > 2.2:
            continue
        if area / max(1, box_width * box_height) < MIN_FILL_RATIO:
            continue
        if (
            x <= EDGE_MARGIN
            or y <= EDGE_MARGIN
            or x + box_width >= width - EDGE_MARGIN
            or y + box_height >= height - EDGE_MARGIN
        ):
            continue
        box = [x, y, box_width, box_height]
        if any(_box_overlap(box, other) > MAX_OVERLAP_WITH_KNOWN for other in known):
            continue
        patch = image[y : y + box_height, x : x + box_width].reshape(-1, 3)
        _colors, counts = np.unique(patch, axis=0, return_counts=True)
        if counts.size and counts.max() / max(1, len(patch)) >= MAX_COLORS_DOMINANCE:
            continue  # flat block, not glyph pixels
        candidates.append((int(area), box))

    candidates.sort(key=lambda item: item[0], reverse=True)
    accepted: list[list[int]] = []
    for _area, box in candidates:
        if len(accepted) >= max_regions:
            break
        if any(
            _box_overlap(box, other) > MAX_OVERLAP_BETWEEN_CANDIDATES
            for other in accepted
        ):
            continue
        accepted.append(box)

    if not accepted:
        return recovered, {
            "schema_version": schema,
            "status": "not-found",
            "source": "icon-recovery:non-text-component",
            "added_count": 0,
            "added": [],
        }

    next_id = (
        max(
            [
                int(item.get("id"))
                for item in elements
                if str(item.get("id") or "").isdigit()
            ]
            or [0]
        )
        + 1
    )
    added: list[dict[str, Any]] = []
    for offset, box in enumerate(accepted):
        element = {
            "id": next_id + offset,
            "bbox": list(box),
            "type": "image",
            "text": "",
            "role": "icon",
            "assetKind": "icon",
            "source": "icon-recovery:non-text-component",
            "authority": "source-pixels",
            "verified": False,
            "container": None,
        }
        added.append(element)
        recovered.setdefault("elements", []).append(element)
    return recovered, {
        "schema_version": schema,
        "status": "applied",
        "source": "icon-recovery:non-text-component",
        "added_count": len(added),
        "added": added,
        "limitations": [
            "Only 12-64px near-square regions outside known elements are recovered.",
            "Recovered bytes are reference-only screenshot crops, not original assets.",
        ],
    }
