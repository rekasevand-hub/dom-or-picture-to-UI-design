"""Recover visible asset crops without claiming original asset identity."""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

REFINABLE_KINDS = {
    "icon",
    "logo",
    "illustration",
    "complex-decoration",
    "complex-chart",
}
UI_REGION_TYPES = {
    "button",
    "checkbox",
    "input",
    "link",
    "select",
    "text",
    "textarea",
}


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


def _intersection_area(first: list[int], second: list[int]) -> int:
    width = max(
        0,
        min(first[0] + first[2], second[0] + second[2])
        - max(first[0], second[0]),
    )
    height = max(
        0,
        min(first[1] + first[3], second[1] + second[3])
        - max(first[1], second[1]),
    )
    return width * height


def _iou(first: list[int], second: list[int]) -> float:
    intersection = _intersection_area(first, second)
    union = first[2] * first[3] + second[2] * second[3] - intersection
    return intersection / union if union > 0 else 0.0


def _contains_box(outer: list[int], inner: list[int]) -> bool:
    area = inner[2] * inner[3]
    return bool(area and _intersection_area(outer, inner) / area >= 0.90)


def _is_background_asset(asset: Mapping[str, Any]) -> bool:
    return (
        str(asset.get("kind") or "").lower() == "background"
        or str(asset.get("role") or "").lower() == "background"
        or asset.get("background") is True
    )


def classify_full_screenshot_underlay(
    asset: dict,
    graph: dict,
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Classify a crop that reconstructs the UI instead of one visible asset."""

    if not isinstance(asset, Mapping):
        raise ValueError("asset must be an object")
    box = _bbox(asset.get("bbox"), width, height)
    if box is None:
        raise ValueError("asset.bbox must be a valid page-pixel rectangle")
    if _is_background_asset(asset):
        return {
            "is_underlay": False,
            "reason": "explicit-background-asset",
            "bbox": box,
            "regions": [],
        }

    page_area = width * height
    if box[2] * box[3] / page_area >= 0.95:
        return {
            "is_underlay": True,
            "reason": "spans-page",
            "bbox": box,
            "regions": [],
        }

    regions: list[dict[str, Any]] = []
    for item in graph.get("elements") or []:
        if not isinstance(item, Mapping):
            continue
        element_type = str(item.get("type") or "").lower()
        if element_type not in UI_REGION_TYPES or item.get("critical") is False:
            continue
        region_box = _bbox(item.get("bbox"), width, height)
        if region_box is None or not _contains_box(box, region_box):
            continue
        text = str(item.get("text") or "")
        if not text and element_type == "text":
            continue
        regions.append(
            {
                "id": item.get("id"),
                "type": element_type,
                "bbox": region_box,
                "text": text,
            }
        )

    unique_regions: list[dict[str, Any]] = []
    for region in regions:
        if all(region["bbox"] != existing["bbox"] for existing in unique_regions):
            unique_regions.append(region)
    if len(unique_regions) >= 2:
        return {
            "is_underlay": True,
            "reason": "multiple-unrelated-ui-regions",
            "bbox": box,
            "regions": unique_regions,
        }
    return {
        "is_underlay": False,
        "reason": "isolated-visible-asset",
        "bbox": box,
        "regions": unique_regions,
    }


def _dominant_rgb(image: np.ndarray) -> np.ndarray:
    pixels = image.reshape(-1, image.shape[2])
    colors, counts = np.unique(pixels, axis=0, return_counts=True)
    return colors[int(np.argmax(counts))]


def _refine_visible_box(
    image: Image.Image,
    requested: list[int],
    kind: str,
) -> tuple[list[int], str]:
    if kind not in REFINABLE_KINDS:
        return list(requested), "requested-bbox-fallback"
    x, y, box_width, box_height = requested
    array = np.asarray(image.convert("RGB"))
    crop = array[y : y + box_height, x : x + box_width]
    if crop.size == 0:
        return list(requested), "requested-bbox-fallback"
    if kind == "logo":
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        ink = ((gray < 253) | (hsv[..., 1] >= 25)).astype(np.uint8) * 255
        ink = cv2.morphologyEx(
            ink,
            cv2.MORPH_CLOSE,
            np.ones((3, 3), dtype=np.uint8),
        )
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            ink,
            8,
        )
        marks = []
        border = max(1, min(box_width, box_height) // 20)
        for index in range(1, count):
            left, top, width, height, area = (
                int(value) for value in stats[index, :5]
            )
            if (
                area < max(8, box_width * box_height * 0.002)
                or left < border
                or top < border
                or left + width > box_width - border
                or top + height > box_height - border
            ):
                continue
            marks.append((left, top, width, height))
        if marks:
            left = min(mark[0] for mark in marks)
            top = min(mark[1] for mark in marks)
            right = max(mark[0] + mark[2] for mark in marks)
            bottom = max(mark[1] + mark[3] for mark in marks)
            return [
                x + left,
                y + top,
                right - left,
                bottom - top,
            ], "connected-component-union"
    background = _dominant_rgb(crop)
    distance = np.linalg.norm(crop.astype(np.int16) - background, axis=2)
    channel_range = crop.max(axis=2).astype(np.int16) - crop.min(axis=2).astype(
        np.int16
    )
    mask = ((distance >= 38) | (channel_range >= 30)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        np.ones((5, 5), dtype=np.uint8),
    )
    border = 1 if min(box_width, box_height) < 24 else 2
    mask[:border, :] = 0
    mask[-border:, :] = 0
    mask[:, :border] = 0
    mask[:, -border:] = 0
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    candidates = []
    for index in range(1, count):
        left, top, width, height, area = (
            int(value) for value in stats[index, :5]
        )
        if width < 8 or height < 8:
            continue
        candidates.append((area, left, top, width, height))
    if not candidates:
        return list(requested), "requested-bbox-fallback"
    total_area = box_width * box_height
    meaningful = [
        candidate
        for candidate in candidates
        if candidate[0] >= max(8, total_area * 0.002)
    ]
    if not meaningful:
        return list(requested), "requested-bbox-fallback"
    left = min(candidate[1] for candidate in meaningful)
    top = min(candidate[2] for candidate in meaningful)
    right = max(candidate[1] + candidate[3] for candidate in meaningful)
    bottom = max(candidate[2] + candidate[4] for candidate in meaningful)
    width = right - left
    height = bottom - top
    if width * height >= total_area * 0.92:
        return list(requested), "requested-bbox-fallback"
    return [x + left, y + top, width, height], "connected-component-union"


def _slug(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return (normalized or fallback)[:64]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_asset_crop_request(
    asset: dict,
    source_image: Path,
    display_box: list[int],
) -> dict[str, Any]:
    """Describe one exact screenshot crop request for an asset candidate."""

    if not isinstance(asset, Mapping):
        raise ValueError("asset must be an object")
    source_path = Path(source_image)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    with Image.open(source_path) as image:
        width, height = image.size
    source_rect = _bbox(asset.get("bbox"), width, height)
    normalized_display = _bbox(display_box, width, height)
    if source_rect is None or normalized_display is None:
        raise ValueError("asset.bbox and display_box must be valid image rectangles")
    return {
        "asset_name": _slug(asset.get("name"), "asset"),
        "kind": str(asset.get("kind") or ""),
        "source_image": str(source_path),
        "source_sha256": _file_sha256(source_path),
        "source_rect": source_rect,
        "display_box": normalized_display,
        "mime": "image/png",
        "reference_only": True,
        "original": False,
    }


def _existing_image_index(graph: dict, name: str) -> int | None:
    for index, item in enumerate(graph.get("elements") or []):
        if isinstance(item, Mapping) and str(item.get("assetName") or "") == name:
            return index
    return None


def recover_visible_assets(
    graph: dict,
    image_path: Path,
    *,
    work_dir: Path,
) -> tuple[dict, dict]:
    """Recover exact visible screenshot crops and candidate asset provenance."""

    if not isinstance(graph, Mapping):
        raise ValueError("graph must be an object")
    source_path = Path(image_path)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    output_root = Path(work_dir) / "assets"
    output_root.mkdir(parents=True, exist_ok=True)

    recovered = copy.deepcopy(dict(graph))
    enrichment = recovered.setdefault("imageEnrichment", {})
    if not isinstance(enrichment, dict):
        enrichment = {}
        recovered["imageEnrichment"] = enrichment
    candidates = enrichment.get("assets")
    if not isinstance(candidates, list):
        candidates = (recovered.get("sliceAnalysis") or {}).get("assets") or []

    with Image.open(source_path) as source_image:
        image = source_image.convert("RGB")
    width, height = image.size
    screenshot_sha = _file_sha256(source_path)
    assets: list[dict[str, Any]] = []
    underlays: list[dict[str, Any]] = []
    deduplicated: list[dict[str, Any]] = []
    next_id = (
        max(
            [
                int(item.get("id"))
                for item in recovered.get("elements") or []
                if str(item.get("id") or "").isdigit()
            ]
            or [0]
        )
        + 1
    )

    for index, raw_asset in enumerate(candidates):
        if not isinstance(raw_asset, Mapping):
            continue
        asset = copy.deepcopy(dict(raw_asset))
        requested = _bbox(asset.get("bbox"), width, height)
        if requested is None:
            continue
        name = _slug(asset.get("name"), f"asset_{index + 1:02d}")
        kind = str(asset.get("kind") or "image")
        duplicate = next(
            (
                existing
                for existing in assets
                if str(existing.get("kind") or "") == kind
                and _iou(existing["bbox"], requested) >= 0.90
            ),
            None,
        )
        if duplicate is not None:
            deduplicated.append(
                {
                    "name": name,
                    "reason": "duplicate-asset",
                    "kept": duplicate["name"],
                    "bbox": requested,
                }
            )
            continue

        visible_box, refinement = _refine_visible_box(image, requested, kind)
        output_path = output_root / f"{index + 1:02d}_{name}.png"
        image.crop(
            (
                visible_box[0],
                visible_box[1],
                visible_box[0] + visible_box[2],
                visible_box[1] + visible_box[3],
            )
        ).save(output_path)
        digest = _file_sha256(output_path)
        occluded = bool(asset.get("occluded")) or str(
            asset.get("visibility") or ""
        ).lower() in {"occluded", "partial", "missing"}
        generated = (
            {
                "status": "candidate-missing",
                "candidate": True,
                "generated": False,
                "reason": "visible pixels are occluded and generation has not run",
            }
            if occluded
            else {
                "status": "not-needed",
                "candidate": False,
                "generated": False,
                "reason": "",
            }
        )
        visible_crop = {
            "status": "available",
            "path": str(output_path),
            "payload_sha256": digest,
            "screenshot_sha256": screenshot_sha,
            "source_rect": visible_box,
            "display_box": visible_box,
            "size": [visible_box[2], visible_box[3]],
            "requested_bbox": requested,
            "refinement": refinement,
            "reference_only": True,
            "original": False,
        }
        asset_identity = {
            "status": "unavailable-from-flat-image",
            "name": name,
            "kind": kind,
            "source": "screenshot-crop",
            "screenshot_sha256": screenshot_sha,
            "payload_sha256": digest,
            "reference_only": True,
            "original": False,
        }
        source_resolution = {
            "display": {
                "selected": "screenshot-crop",
                "status": "partial-reference" if occluded else "reference-only",
                "payload_sha256": digest,
                "reference_only": True,
                "generated": False,
                "original": False,
            },
            "identity": {
                "selected": "unavailable-from-flat-image",
                "original": False,
            },
            "generatedApproximation": dict(generated),
        }
        asset.update(
            {
                "name": name,
                "kind": kind,
                "bbox": requested,
                "visibleCrop": visible_crop,
                "generatedApproximation": generated,
                "assetIdentity": asset_identity,
                "sourceResolution": source_resolution,
            }
        )
        assets.append(asset)

        classification = classify_full_screenshot_underlay(
            {**asset, "bbox": visible_box},
            recovered,
            width=width,
            height=height,
        )
        if classification["is_underlay"]:
            evidence = {
                "name": name,
                "kind": kind,
                "bbox": requested,
                "visibleCrop": visible_crop,
                "classification": classification,
            }
            underlays.append(evidence)
            asset["referenceUnderlay"] = evidence
            continue

        existing_index = _existing_image_index(recovered, name)
        element = {
            "id": (
                recovered["elements"][existing_index].get("id")
                if existing_index is not None
                else next_id
            ),
            "bbox": visible_box,
            "type": "image",
            "text": "",
            "role": "",
            "source": "image-enrichment:visible-asset",
            "container": None,
            "assetName": name,
            "assetKind": kind,
            "confidence": float(asset.get("confidence") or 0.0),
            "visibleCrop": visible_crop,
            "sourceCrop": visible_crop,
            "generatedApproximation": generated,
            "assetIdentity": asset_identity,
            "sourceResolution": source_resolution,
        }
        if existing_index is None:
            recovered.setdefault("elements", []).append(element)
            next_id += 1
        else:
            recovered["elements"][existing_index] = element

    enrichment["assets"] = assets
    enrichment["referenceUnderlays"] = underlays
    report = {
        "schema_version": "image-enrichment-assets/1.0",
        "status": "applied" if assets else "no-assets",
        "asset_count": len(assets),
        "visible_crop_count": len(assets),
        "underlay_count": len(underlays),
        "underlays": underlays,
        "deduplicated_count": len(deduplicated),
        "deduplicated": deduplicated,
        "source_sha256": screenshot_sha,
        "image_size": [width, height],
        "limitations": [
            "Screenshot crops preserve visible pixels and do not recover original asset bytes.",
            "Transparent object boundaries cannot be inferred from one flat screenshot.",
            "Occluded regions remain candidate-missing until generated and reviewed.",
        ],
    }
    return recovered, report
