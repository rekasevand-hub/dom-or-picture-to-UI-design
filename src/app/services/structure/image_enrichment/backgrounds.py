"""Deterministic background crops, masks and edge-blend candidates."""

from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from src.app.services.structure.image_enrichment.repair import (
    create_edge_blend_patch,
)


def _bbox(value: Any, width: int, height: int) -> list[int] | None:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != 4
    ):
        return None
    try:
        x, y, box_width, box_height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    left = max(0, min(width, x))
    top = max(0, min(height, y))
    right = max(left, min(width, x + box_width))
    bottom = max(top, min(height, y + box_height))
    if right - left < 2 or bottom - top < 2:
        return None
    return [left, top, right - left, bottom - top]


def _clamp_to_background(
    bbox: list[int],
    background: list[int],
) -> list[int] | None:
    background_right = background[0] + background[2]
    background_bottom = background[1] + background[3]
    left = max(bbox[0], background[0])
    top = max(bbox[1], background[1])
    right = min(bbox[0] + bbox[2], background_right)
    bottom = min(bbox[1] + bbox[3], background_bottom)
    if right - left < 1 or bottom - top < 1:
        return None
    return [left, top, right - left, bottom - top]


def _normalized_overlays(
    overlays: Sequence[Mapping[str, Any]],
    background: list[int],
    size: tuple[int, int],
) -> list[dict[str, Any]]:
    normalized = []
    for index, overlay in enumerate(overlays):
        if not isinstance(overlay, Mapping):
            continue
        box = _bbox(overlay.get("bbox"), size[0], size[1])
        if box is None:
            continue
        clipped = _clamp_to_background(box, background)
        if clipped is None:
            continue
        normalized.append(
            {
                **dict(overlay),
                "id": str(overlay.get("id") or f"overlay_{index + 1:02d}"),
                "bbox": clipped,
            }
        )
    return normalized


def build_background_mask(
    background: dict,
    overlays: list[dict],
    size: tuple[int, int],
) -> bytes:
    """Build a full-page L-mode PNG mask with white selected overlay pixels."""

    if not isinstance(background, Mapping):
        raise ValueError("background must be an object")
    if isinstance(overlays, (str, bytes)) or not isinstance(overlays, Sequence):
        raise ValueError("overlays must be an array")
    try:
        width, height = (int(size[0]), int(size[1]))
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("size must contain width and height") from exc
    if width <= 0 or height <= 0:
        raise ValueError("size must be positive")
    background_box = _bbox(background.get("bbox"), width, height)
    if background_box is None:
        raise ValueError("background.bbox must be a valid image rectangle")
    selected = _normalized_overlays(
        overlays,
        background_box,
        (width, height),
    )
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for overlay in selected:
        x, y, box_width, box_height = overlay["bbox"]
        draw.rectangle(
            (x, y, x + box_width - 1, y + box_height - 1),
            fill=255,
        )
    output = io.BytesIO()
    mask.save(output, format="PNG")
    return output.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _slug(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return (normalized or fallback)[:64]


def create_background_candidates(
    image: Image.Image,
    background: dict,
    overlays: list[dict],
    work_dir: Path,
) -> dict[str, Any]:
    """Write an observed crop, selection mask and local edge-blend candidate."""

    if not isinstance(image, Image.Image):
        raise ValueError("image must be a PIL Image")
    if not isinstance(background, Mapping):
        raise ValueError("background must be an object")
    if isinstance(overlays, (str, bytes)) or not isinstance(overlays, Sequence):
        raise ValueError("overlays must be an array")
    source = image.convert("RGB")
    background_box = _bbox(background.get("bbox"), source.width, source.height)
    if background_box is None:
        raise ValueError("background.bbox must be a valid image rectangle")
    selected = _normalized_overlays(
        overlays,
        background_box,
        (source.width, source.height),
    )
    background_id = str(background.get("id") or "background")
    output_dir = Path(work_dir) / "backgrounds" / _slug(
        background_id, "background"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    x, y, width, height = background_box
    source_crop = source.crop((x, y, x + width, y + height))
    source_path = output_dir / "source_crop.png"
    source_crop.save(source_path, format="PNG")
    source_bytes = source_path.read_bytes()

    mask_bytes = build_background_mask(
        {**dict(background), "bbox": background_box},
        selected,
        (source.width, source.height),
    )
    mask_path = output_dir / "overlay_mask.png"
    mask_path.write_bytes(mask_bytes)

    clean = source_crop.copy()
    for overlay in selected:
        overlay_x, overlay_y, overlay_width, overlay_height = overlay["bbox"]
        patch = create_edge_blend_patch(
            source,
            {
                "x": overlay_x,
                "y": overlay_y,
                "width": overlay_width,
                "height": overlay_height,
            },
        )
        clean.paste(
            patch,
            (
                overlay_x - x,
                overlay_y - y,
            ),
        )
    clean_path = output_dir / "edge_blend_candidate.png"
    clean.save(clean_path, format="PNG")
    clean_bytes = clean_path.read_bytes()
    return {
        "schema_version": "image-enrichment-background/1.0",
        "id": background_id,
        "name": str(background.get("name") or background_id),
        "bbox": background_box,
        "overlays": selected,
        "overlayCount": len(selected),
        "status": "candidate",
        "sourceCrop": {
            "path": str(source_path),
            "payload_sha256": _sha256(source_bytes),
            "source_rect": background_box,
            "size": [width, height],
            "observed_source": True,
            "original": False,
        },
        "mask": {
            "path": str(mask_path),
            "payload_sha256": _sha256(mask_bytes),
            "size": [source.width, source.height],
            "semantics": "white-selected-region",
            "original": False,
        },
        "cleanCandidate": {
            "path": str(clean_path),
            "payload_sha256": _sha256(clean_bytes),
            "size": [width, height],
            "method": "edge-blend",
            "generated": False,
            "review_status": "candidate",
            "original": False,
        },
    }
