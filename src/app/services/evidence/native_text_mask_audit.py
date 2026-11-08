"""Audit screenshot-derived text masks without changing gate decisions."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .native_text_quality import (
    _contrast_mask,
    _edge_f1,
    _halo_bbox,
    _ink_bbox,
    _normalized_bbox,
)


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str) -> str:
    name = re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("._")
    return name or "owner"


def _clip_bbox(
    bbox: list[int],
    image_shape: tuple[int, int],
) -> list[int] | None:
    height, width = image_shape
    x, y, box_width, box_height = bbox
    left = max(0, x)
    top = max(0, y)
    right = min(width, x + box_width)
    bottom = min(height, y + box_height)
    if right <= left or bottom <= top:
        return None
    return [left, top, right - left, bottom - top]


def _measure_variant(
    reference: Any,
    rendered: Any,
    bbox: list[int],
) -> dict[str, Any]:
    x, y, width, height = bbox
    reference_crop = reference[y : y + height, x : x + width]
    rendered_crop = rendered[y : y + height, x : x + width]
    reference_mask = _contrast_mask(reference_crop)
    rendered_mask = _contrast_mask(rendered_crop)
    reference_ink = _ink_bbox(reference_mask, bbox)
    rendered_ink = _ink_bbox(rendered_mask, bbox)
    reference_pixels = int(reference_mask.sum())
    rendered_pixels = int(rendered_mask.sum())
    coverage = (
        float(rendered_pixels) / float(reference_pixels)
        if reference_pixels
        else None
    )
    edge_f1 = None
    if reference_ink is not None and rendered_ink is not None:
        union_x = min(reference_ink[0], rendered_ink[0])
        union_y = min(reference_ink[1], rendered_ink[1])
        union_right = max(
            reference_ink[0] + reference_ink[2],
            rendered_ink[0] + rendered_ink[2],
        )
        union_bottom = max(
            reference_ink[1] + reference_ink[3],
            rendered_ink[1] + rendered_ink[3],
        )
        edge_f1 = _edge_f1(
            reference_mask[
                union_y - y : union_bottom - y,
                union_x - x : union_right - x,
            ],
            rendered_mask[
                union_y - y : union_bottom - y,
                union_x - x : union_right - x,
            ],
        )
    return {
        "bbox": bbox,
        "referenceMaskPixels": reference_pixels,
        "renderedMaskPixels": rendered_pixels,
        "coverage": coverage,
        "referenceInkBBox": reference_ink,
        "renderedInkBBox": rendered_ink,
        "edgeF1": edge_f1,
        "_referenceCrop": reference_crop,
        "_renderedCrop": rendered_crop,
        "_referenceMask": reference_mask,
        "_renderedMask": rendered_mask,
    }


def _write_variant(output: Path, name: str, metrics: dict[str, Any]) -> None:
    from PIL import Image

    Image.fromarray(metrics["_referenceCrop"].astype("uint8")).save(
        output / f"reference_{name}.png"
    )
    Image.fromarray(metrics["_renderedCrop"].astype("uint8")).save(
        output / f"rendered_{name}.png"
    )
    Image.fromarray(
        (metrics["_referenceMask"].astype("uint8") * 255),
        mode="L",
    ).save(output / f"reference_{name}_mask.png")
    Image.fromarray(
        (metrics["_renderedMask"].astype("uint8") * 255),
        mode="L",
    ).save(output / f"rendered_{name}_mask.png")


def audit_native_text_masks(
    design: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
    *,
    owner_refs: Sequence[str] | None = None,
    output_dir: str | None = None,
    halo_px: int = 2,
) -> dict[str, Any]:
    """Measure the same owner under multiple text-support ROIs.

    The output is diagnostic evidence. It never changes native-text acceptance.
    """
    from PIL import Image
    import numpy as np

    if halo_px < 0:
        raise ValueError("halo_px must be non-negative")
    selected = (
        {str(value) for value in owner_refs if str(value).strip()}
        if owner_refs is not None
        else None
    )
    with Image.open(reference_path) as source:
        reference = np.asarray(source.convert("RGB"))
    with Image.open(rendered_path) as source:
        rendered = np.asarray(source.convert("RGB"))
    if reference.shape != rendered.shape:
        raise ValueError("reference and rendered image sizes must match")

    output_root = Path(output_dir) if output_dir else None
    owners: list[dict[str, Any]] = []
    found_refs: set[str] = set()
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        owner_ref = str(element.get("contentRef") or element.get("id") or "")
        if not owner_ref or (selected is not None and owner_ref not in selected):
            continue
        evidence = element.get("styleEvidence")
        values = evidence.get("evidence") if isinstance(evidence, Mapping) else None
        if not isinstance(values, Mapping):
            continue
        raw_source_bbox = _normalized_bbox(values.get("source_bbox"))
        raw_ink_bbox = _normalized_bbox(values.get("ink_bbox"))
        source_bbox = (
            _clip_bbox(raw_source_bbox, reference.shape[:2])
            if raw_source_bbox is not None
            else None
        )
        ink_bbox = (
            _clip_bbox(raw_ink_bbox, reference.shape[:2])
            if raw_ink_bbox is not None
            else None
        )
        if source_bbox is None or ink_bbox is None:
            continue
        boxes = {
            "source-bbox": source_bbox,
            "ink-bbox": ink_bbox,
            "ink-halo": _halo_bbox(ink_bbox, halo_px, reference.shape[:2]),
        }
        variants = {
            name: _measure_variant(reference, rendered, bbox)
            for name, bbox in boxes.items()
            if bbox is not None
        }
        if output_root is not None:
            owner_output = output_root / _safe_name(owner_ref)
            owner_output.mkdir(parents=True, exist_ok=True)
            for name, metrics in variants.items():
                _write_variant(owner_output, name, metrics)
        public_variants = {}
        for name, metrics in variants.items():
            public_variants[name] = {
                key: value
                for key, value in metrics.items()
                if not key.startswith("_")
            }
        owners.append(
            {
                "contentRef": owner_ref,
                "text": str(element.get("text") or element.get("controlValue") or ""),
                "type": element.get("type"),
                "variants": public_variants,
            }
        )
        found_refs.add(owner_ref)

    return {
        "schema_version": "grounding-native-text-mask-audit/1.0",
        "status": "measured",
        "acceptanceEffect": "none",
        "haloPx": halo_px,
        "referencePath": str(Path(reference_path).resolve()),
        "referenceSha256": _sha256_file(reference_path),
        "renderedPath": str(Path(rendered_path).resolve()),
        "renderedSha256": _sha256_file(rendered_path),
        "ownerCount": len(owners),
        "missingOwnerRefs": sorted((selected or set()) - found_refs),
        "owners": owners,
        "limitations": [
            "Reference ink masks are screenshot-derived candidates, not original glyph outlines.",
            "Variant metrics are diagnostic and never change native-text gate decisions.",
            "No ROI variant is authoritative until reviewed on representative owners.",
        ],
    }
