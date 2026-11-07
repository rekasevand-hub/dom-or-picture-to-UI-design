"""Measure native text and chrome separately without changing acceptance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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


def _normalized_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, width, height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    return [x, y, width, height] if width > 0 and height > 0 else None


def _contrast_mask(region: Any) -> Any:
    import numpy as np

    values = region.reshape(-1, 3)
    background = np.median(values, axis=0)
    return np.max(np.abs(region - background), axis=2) > 50


def _ink_bbox(mask: Any, bbox: list[int]) -> list[int] | None:
    import numpy as np

    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    x, y, _width, _height = bbox
    return [
        x + int(xs.min()),
        y + int(ys.min()),
        int(xs.max()) - int(xs.min()) + 1,
        int(ys.max()) - int(ys.min()) + 1,
    ]


def _edge_mask(mask: Any) -> Any:
    import numpy as np

    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    eroded = np.ones_like(mask, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            eroded &= padded[
                1 + dy : 1 + dy + mask.shape[0],
                1 + dx : 1 + dx + mask.shape[1],
            ]
    return mask & ~eroded


def _dilate(mask: Any) -> Any:
    import numpy as np

    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    output = np.zeros_like(mask, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            output |= padded[
                1 + dy : 1 + dy + mask.shape[0],
                1 + dx : 1 + dx + mask.shape[1],
            ]
    return output


def _edge_f1(reference_mask: Any, rendered_mask: Any) -> float | None:
    reference_edge = _edge_mask(reference_mask)
    rendered_edge = _edge_mask(rendered_mask)
    if not reference_edge.any() and not rendered_edge.any():
        return 1.0
    if not reference_edge.any() or not rendered_edge.any():
        return 0.0
    matched_reference = reference_edge & _dilate(rendered_edge)
    matched_rendered = rendered_edge & _dilate(reference_edge)
    precision = float(matched_rendered.sum()) / float(rendered_edge.sum())
    recall = float(matched_reference.sum()) / float(reference_edge.sum())
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _region_mask(shape: tuple[int, int], bbox: list[int]) -> Any:
    import numpy as np

    mask = np.zeros(shape, dtype=bool)
    x, y, width, height = bbox
    mask[
        max(0, y) : min(shape[0], y + height),
        max(0, x) : min(shape[1], x + width),
    ] = True
    return mask


def build_native_text_quality(
    design: Mapping[str, Any],
    readback_tree: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
    regions: list[Mapping[str, Any]],
    *,
    halo_px: int = 2,
    bad_pixel_threshold: int = 30,
) -> dict[str, Any]:
    """Build diagnostic text/chrome metrics; never changes acceptance status."""
    import numpy as np
    from PIL import Image

    with Image.open(reference_path) as source:
        reference = np.asarray(source.convert("RGB"), dtype=np.int16)
    with Image.open(rendered_path) as source:
        rendered = np.asarray(source.convert("RGB"), dtype=np.int16)
    if reference.shape != rendered.shape:
        raise ValueError("reference and rendered image sizes must match")
    height, width = reference.shape[:2]
    bad = np.max(np.abs(reference - rendered), axis=2) > bad_pixel_threshold
    native_characters = {
        str(node.get("characters") or "") for node in _text_nodes(readback_tree)
    }
    text_mask = np.zeros((height, width), dtype=bool)
    owners: list[dict[str, Any]] = []
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        text = str(element.get("text") or element.get("controlValue") or "")
        if not text or str(element.get("type") or "") == "image":
            continue
        evidence = element.get("styleEvidence")
        values = evidence.get("evidence") if isinstance(evidence, Mapping) else None
        if not isinstance(values, Mapping):
            continue
        source_bbox = _normalized_bbox(values.get("source_bbox"))
        reference_ink = _normalized_bbox(values.get("ink_bbox"))
        if source_bbox is None or reference_ink is None:
            continue
        x, y, box_width, box_height = source_bbox
        source_region = rendered[y : y + box_height, x : x + box_width]
        reference_region = reference[y : y + box_height, x : x + box_width]
        rendered_mask = _contrast_mask(source_region)
        reference_mask = _contrast_mask(reference_region)
        rendered_ink = _ink_bbox(rendered_mask, source_bbox)
        if rendered_ink is None:
            owners.append(
                {
                    "contentRef": element.get("contentRef"),
                    "text": text,
                    "nativeText": text in native_characters,
                    "status": "failed-missing-rendered-ink",
                }
            )
            continue
        delta_x = rendered_ink[0] - reference_ink[0]
        delta_y = rendered_ink[1] - reference_ink[1]
        width_tolerance = max(2, int(round(reference_ink[2] * 0.02)))
        height_tolerance = max(2, int(round(reference_ink[3] * 0.02)))
        height_delta = rendered_ink[3] - reference_ink[3]
        width_delta = rendered_ink[2] - reference_ink[2]
        reference_pixels = int(reference_mask.sum())
        rendered_pixels = int(rendered_mask.sum())
        coverage = (
            float(rendered_pixels) / float(reference_pixels)
            if reference_pixels
            else None
        )
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
        ref_crop = reference_mask[
            union_y - y : union_bottom - y,
            union_x - x : union_right - x,
        ]
        render_crop = rendered_mask[
            union_y - y : union_bottom - y,
            union_x - x : union_right - x,
        ]
        edge_f1 = _edge_f1(ref_crop, render_crop)
        geometry_checks = {
            "position": abs(delta_x) <= 1 and abs(delta_y) <= 1,
            "size": abs(width_delta) <= width_tolerance
            and abs(height_delta) <= height_tolerance,
            "coverage": coverage is not None and 0.90 <= coverage <= 1.10,
            "edgeF1": edge_f1 is not None and edge_f1 >= 0.95,
        }
        owners.append(
            {
                "contentRef": element.get("contentRef"),
                "text": text,
                "type": element.get("type"),
                "nativeText": text in native_characters,
                "referenceInkBBox": reference_ink,
                "renderedInkBBox": rendered_ink,
                "deltaX": delta_x,
                "deltaY": delta_y,
                "widthDelta": width_delta,
                "heightDelta": height_delta,
                "widthTolerance": width_tolerance,
                "heightTolerance": height_tolerance,
                "inkCoverageRatio": coverage,
                "edgeF1": edge_f1,
                "baseline": "unknown",
                "checks": geometry_checks,
                "geometryStatus": ("pass" if all(geometry_checks.values()) else "fail"),
                "status": (
                    "pass"
                    if text in native_characters
                    and geometry_checks["position"]
                    and geometry_checks["size"]
                    and geometry_checks["coverage"]
                    and geometry_checks["edgeF1"]
                    else "fail"
                ),
            }
        )
        mask_x = max(0, reference_ink[0] - halo_px)
        mask_y = max(0, reference_ink[1] - halo_px)
        mask_right = min(width, reference_ink[0] + reference_ink[2] + halo_px)
        mask_bottom = min(height, reference_ink[1] + reference_ink[3] + halo_px)
        text_mask[mask_y:mask_bottom, mask_x:mask_right] = True
    chrome_regions = []
    for region in regions:
        bbox = _normalized_bbox(region.get("bbox"))
        if bbox is None:
            continue
        region_mask = _region_mask((height, width), bbox)
        chrome_mask = region_mask & ~text_mask
        pixel_count = int(chrome_mask.sum())
        bad_count = int((bad & chrome_mask).sum())
        chrome_regions.append(
            {
                "id": str(region.get("id") or region.get("role") or ""),
                "role": str(region.get("role") or ""),
                "bbox": bbox,
                "chromePixelCount": pixel_count,
                "chromeBadPixelCount": bad_count,
                "chromeBadPixelRatio": (
                    float(bad_count) / float(pixel_count) if pixel_count else None
                ),
                "status": (
                    "pass"
                    if pixel_count and float(bad_count) / float(pixel_count) <= 0.05
                    else "fail"
                ),
            }
        )
    measured = [owner for owner in owners if "checks" in owner]
    summary = {
        "ownerCount": len(owners),
        "nativeTextCount": sum(bool(owner.get("nativeText")) for owner in owners),
        "positionPassCount": sum(
            bool(owner.get("checks", {}).get("position")) for owner in owners
        ),
        "sizePassCount": sum(
            bool(owner.get("checks", {}).get("size")) for owner in owners
        ),
        "coveragePassCount": sum(
            bool(owner.get("checks", {}).get("coverage")) for owner in owners
        ),
        "edgeF1PassCount": sum(
            bool(owner.get("checks", {}).get("edgeF1")) for owner in owners
        ),
        "baselineEvidenceCount": 0,
        "measuredOwnerCount": len(measured),
    }
    return {
        "schema_version": "grounding-native-text-quality/1.0",
        "status": "measured-diagnostic-only",
        "acceptance_effect": "none",
        "haloPx": halo_px,
        "badPixelThreshold": bad_pixel_threshold,
        "summary": summary,
        "owners": owners,
        "chromeRegions": chrome_regions,
        "proposedTextGate": {
            "positionPxMax": 1,
            "widthErrorPxMax": "max(2, 2% reference width)",
            "heightErrorPxMax": "max(2, 2% reference height)",
            "inkCoverageRatioMin": 0.90,
            "inkCoverageRatioMax": 1.10,
            "edgeF1Min": 0.95,
            "baselinePxMax": 1,
        },
        "limitations": [
            "Baseline evidence is unavailable for every owner in this diagnostic.",
            "Native text/chrome split metrics do not change the frozen raw acceptance.",
            "Reference ink masks are screenshot-derived candidates, not original glyph outlines.",
        ],
    }
