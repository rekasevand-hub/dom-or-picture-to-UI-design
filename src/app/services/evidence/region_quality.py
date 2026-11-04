"""Region-level same-size visual metrics for reconstruction gates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

BAD_PIXEL_THRESHOLD = 30
SCHEMA_VERSION = "grounding-region-quality/1.0"


def _clamp_bbox(
    value: Any,
    width: int,
    height: int,
) -> list[int] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    if len(value) != 4 or any(isinstance(item, bool) for item in value):
        return None
    try:
        x, y, box_width, box_height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError, OverflowError):
        return None
    if box_width <= 0 or box_height <= 0:
        return None
    left = max(0, x)
    top = max(0, y)
    right = min(width, x + box_width)
    bottom = min(height, y + box_height)
    if right <= left or bottom <= top:
        return None
    return [left, top, right - left, bottom - top]


def _invalid_region(region: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "id": str(region.get("id") or ""),
        "bbox": list(region.get("bbox") or []),
        "reason": reason,
    }


def _region_metrics(
    reference: Any,
    render: Any,
    bbox: list[int],
    *,
    role: str,
) -> dict[str, Any]:
    import cv2
    import numpy as np

    x, y, width, height = bbox
    reference_region = reference[y : y + height, x : x + width]
    render_region = render[y : y + height, x : x + width]
    gray_reference = cv2.cvtColor(reference_region, cv2.COLOR_BGR2GRAY)
    gray_render = cv2.cvtColor(render_region, cv2.COLOR_BGR2GRAY)
    mae = float(
        np.abs(gray_render.astype(np.int16) - gray_reference.astype(np.int16)).mean()
    )
    max_delta = np.abs(
        render_region.astype(np.int16) - reference_region.astype(np.int16)
    ).max(axis=2)
    bad_pixel_count = int((max_delta > BAD_PIXEL_THRESHOLD).sum())
    pixel_count = int(width * height)
    return {
        "bbox": bbox,
        "role": role,
        "pixel_count": pixel_count,
        "mae": mae,
        "bad_pixel_threshold": BAD_PIXEL_THRESHOLD,
        "bad_pixel_count": bad_pixel_count,
        "bad_pixel_ratio": (
            float(bad_pixel_count / pixel_count) if pixel_count else 0.0
        ),
    }


def evaluate_region_quality(
    reference_path: str | Path,
    render_path: str | Path,
    regions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Measure identical regions in source pixels without resizing the render."""
    import cv2

    reference_value = Path(reference_path)
    render_value = Path(render_path)
    reference = cv2.imread(str(reference_value))
    render = cv2.imread(str(render_value))
    if reference is None or render is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "size_match": False,
            "reference_size": (
                [int(reference.shape[1]), int(reference.shape[0])]
                if reference is not None
                else None
            ),
            "render_size": (
                [int(render.shape[1]), int(render.shape[0])]
                if render is not None
                else None
            ),
            "bad_pixel_threshold": BAD_PIXEL_THRESHOLD,
            "regions": {},
            "invalid_regions": [
                {
                    "id": "",
                    "bbox": [],
                    "reason": "image-unreadable",
                }
            ],
        }
    reference_size = [int(reference.shape[1]), int(reference.shape[0])]
    render_size = [int(render.shape[1]), int(render.shape[0])]
    size_match = reference_size == render_size
    if not size_match:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "size_match": False,
            "reference_size": reference_size,
            "render_size": render_size,
            "bad_pixel_threshold": BAD_PIXEL_THRESHOLD,
            "regions": {},
            "invalid_regions": [
                {
                    "id": "",
                    "bbox": [],
                    "reason": "fixed-canvas-size-mismatch",
                }
            ],
        }

    width, height = reference_size
    measured: dict[str, dict[str, Any]] = {}
    invalid: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    if not isinstance(regions, Sequence) or isinstance(
        regions, (str, bytes, bytearray)
    ):
        raise ValueError("regions must be a sequence")
    for region in regions:
        if not isinstance(region, Mapping):
            invalid.append(
                {
                    "id": "",
                    "bbox": [],
                    "reason": "region-must-be-an-object",
                }
            )
            continue
        region_id = str(region.get("id") or "").strip()
        if not region_id:
            invalid.append(_invalid_region(region, "region-id-missing"))
            continue
        if region_id in seen_ids:
            invalid.append(_invalid_region(region, "duplicate-region-id"))
            continue
        seen_ids.add(region_id)
        bbox = _clamp_bbox(region.get("bbox"), width, height)
        if bbox is None:
            invalid.append(_invalid_region(region, "invalid-or-empty-bbox"))
            continue
        measured[region_id] = _region_metrics(
            reference,
            render,
            bbox,
            role=str(region.get("role") or ""),
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked" if invalid else "measured",
        "size_match": True,
        "reference_size": reference_size,
        "render_size": render_size,
        "bad_pixel_threshold": BAD_PIXEL_THRESHOLD,
        "regions": measured,
        "invalid_regions": invalid,
    }
