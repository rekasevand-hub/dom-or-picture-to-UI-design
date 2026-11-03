"""Deterministic image-to-Figma MVP contracts and presentation helpers."""

from __future__ import annotations

import base64
import copy
import difflib
import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image

from src.app.services.som.design_crops import crop_image_b64
from src.app.services.structure.asset_fusion import fuse_asset_record
from src.app.services.structure.asset_metadata import (
    attach_display_payload,
    build_asset_record,
)
from src.app.services.structure.image_enrichment.assets import (
    classify_full_screenshot_underlay,
)

SCHEMA_VERSION = "image-figma-mvp/1.0"
REFERENCE_SCHEMA_VERSION = "image-reference/1.0"
IR_SCHEMA_VERSION = "image-ir/1.0"

_MIME_BY_FORMAT = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
    "GIF": "image/gif",
}


def inspect_image_reference(
    image_path: str | Path,
    *,
    reference_id: str | None = None,
) -> dict[str, Any]:
    """Describe the screenshot as one faithful, immutable pixel reference."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"image does not exist: {path}")
    with Image.open(path) as image:
        width, height = image.size
        mime = _MIME_BY_FORMAT.get(str(image.format or "").upper())
    digest = _file_sha256(path)
    return {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "reference_id": reference_id or f"image-sha256:{digest}",
        "input": {
            "path": str(path.resolve()),
            "sha256": digest,
            "size": [int(width), int(height)],
            "mime": mime,
            "single_frame": True,
        },
        "state": {
            "mode": "faithful",
            "pixels": "observed",
            "coordinate_basis": "source-pixel-top-left",
            "dpr": "unknown",
            "viewport": "unknown",
            "font_identity": "unknown",
            "hidden_regions": "unknown",
            "motion": "single-frame",
        },
        "claims": [
            "source-pixel-payload",
            "source-pixel-geometry",
            "single-visible-state",
        ],
        "cannot_claim": [
            "original-asset",
            "original-dpr",
            "original-viewport",
            "original-font",
            "hidden-regions",
            "adaptive-flow",
        ],
    }


def select_ocr_languages(graph: Mapping[str, Any]) -> list[str]:
    """Use the bilingual model only when the candidate structure contains CJK."""
    texts = [
        str(item.get("text") or "")
        for item in graph.get("elements") or []
        if isinstance(item, Mapping)
    ]
    if any(any("\u4e00" <= char <= "\u9fff" for char in text) for text in texts):
        return ["ch_sim", "en"]
    return ["en"]


def extract_easyocr_observations(
    image_path: str | Path,
    *,
    languages: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Read text candidates from the full screenshot without changing route."""
    import cv2
    import easyocr
    import numpy as np

    try:
        import torch

        use_gpu = bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001 - CPU OCR remains usable
        use_gpu = False
    image = cv2.cvtColor(cv2.imread(str(image_path)), cv2.COLOR_BGR2RGB)
    reader = easyocr.Reader(languages or ["en"], gpu=use_gpu)
    observations = []
    for polygon, text, confidence in reader.readtext(
        image,
        text_threshold=0.4,
    ):
        points = np.asarray(polygon, dtype=float)
        x0 = int(max(0, np.floor(points[:, 0].min())))
        y0 = int(max(0, np.floor(points[:, 1].min())))
        x1 = int(min(image.shape[1], np.ceil(points[:, 0].max())))
        y1 = int(min(image.shape[0], np.ceil(points[:, 1].max())))
        normalized = str(text or "").strip()
        if not normalized or x1 - x0 < 2 or y1 - y0 < 2:
            continue
        observations.append(
            {
                "text": normalized,
                "bbox": [x0, y0, x1 - x0, y1 - y0],
                "confidence": float(confidence),
                "engine": "easyocr",
            }
        )
    return observations


def merge_ocr_candidates(
    graph: Mapping[str, Any],
    observations: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    source: str = "ocr-supplement:easyocr",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge missing OCR text candidates without overriding Grounding text."""
    merged = copy.deepcopy(dict(graph))
    lines = _merge_ocr_line_observations(observations)
    existing = [
        {
            "id": item.get("id"),
            "key": _ocr_candidate_key(item),
            "text": str(item.get("text") or ""),
            "bbox": list(item.get("bbox") or []),
            "normalized": _normalize_candidate_text(item.get("text") or ""),
        }
        for item in merged.get("elements") or []
        if str(item.get("text") or "").strip()
        and str(item.get("type") or "").lower() in {"text", "link", "button", "input"}
    ]
    next_id = (
        max(
            [
                int(item.get("id"))
                for item in merged.get("elements") or []
                if str(item.get("id") or "").isdigit()
            ]
            or [0]
        )
        + 1
    )
    added: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    replaced_covered: list[dict[str, Any]] = []
    replaced_keys: set[tuple[Any, ...]] = set()
    for line in lines:
        text = str(line.get("text") or "").strip()
        normalized = _normalize_candidate_text(text)
        if len(normalized) < 2:
            skipped.append({"text": text, "reason": "text-too-short"})
            continue
        covered = [
            current
            for current in existing
            if current["key"] not in replaced_keys
            and current["normalized"]
            and current["normalized"] in normalized
            and _box_coverage(current["bbox"], line["bbox"]) >= 0.8
        ]
        if covered:
            replaced_covered.extend(covered)
            replaced_keys.update(current["key"] for current in covered)
            merged["elements"] = [
                item
                for item in merged.get("elements") or []
                if _ocr_candidate_key(item) not in replaced_keys
            ]
            existing = [
                current for current in existing if current["key"] not in replaced_keys
            ]
        if any(
            normalized == current["normalized"]
            or (
                normalized in current["normalized"]
                and _box_coverage(line["bbox"], current["bbox"]) >= 0.25
            )
            or (
                _box_coverage(line["bbox"], current["bbox"]) >= 0.5
                and difflib.SequenceMatcher(
                    None,
                    normalized,
                    current["normalized"],
                ).ratio()
                >= 0.9
            )
            for current in existing
        ):
            skipped.append({"text": text, "reason": "already-covered"})
            continue
        element = {
            "id": next_id,
            "bbox": list(line["bbox"]),
            "type": "text",
            "text": text,
            "role": "",
            "source": source,
            "confidence": float(line.get("confidence") or 0.0),
            "imageMVPTextStatus": "ocr-candidate",
            "authority": "ocr-candidate",
            "verified": False,
            "container": None,
        }
        merged.setdefault("elements", []).append(element)
        added.append(element)
        existing.append(
            {
                "id": element["id"],
                "key": _ocr_candidate_key(element),
                "text": text,
                "bbox": list(line["bbox"]),
                "normalized": normalized,
            }
        )
        next_id += 1
    report = {
        "schema_version": "image-ocr-supplement/1.0",
        "status": "applied" if added else "no-change",
        "source": source,
        "observation_count": len(observations),
        "line_count": len(lines),
        "added_count": len(added),
        "skipped_count": len(skipped),
        "replaced_covered_count": len(replaced_covered),
        "added": added,
        "skipped": skipped,
        "replaced_covered": replaced_covered,
        "limitations": [
            "OCR text is a candidate and does not verify original font or hidden content.",
            "Grounding text is retained; OCR only fills missing candidate text.",
        ],
    }
    return merged, report


def recover_image_text_candidates(
    graph: Mapping[str, Any],
    image_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the text supplement step and retain its candidate evidence."""
    try:
        languages = select_ocr_languages(graph)
        observations = extract_easyocr_observations(
            image_path,
            languages=languages,
        )
    except Exception as exc:  # noqa: BLE001 - the acceptance gate remains fail-closed
        fallback = copy.deepcopy(dict(graph))
        return fallback, {
            "schema_version": "image-ocr-supplement/1.0",
            "status": "unavailable",
            "source": "ocr-supplement:easyocr",
            "error": f"{type(exc).__name__}: {exc}",
            "observation_count": 0,
            "added_count": 0,
            "added": [],
            "languages": languages,
        }
    merged, report = merge_ocr_candidates(graph, observations)
    report["observations"] = observations
    report["languages"] = languages
    return merged, report


def recover_image_region_candidates(
    graph: Mapping[str, Any],
    image_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recover one large embedded visual when Grounding omitted image nodes."""
    recovered = copy.deepcopy(dict(graph))
    existing = [
        item
        for item in recovered.get("elements") or []
        if str(item.get("type") or "").lower() in {"image", "avatar"}
    ]
    if existing:
        return recovered, {
            "schema_version": "image-region-recovery/1.0",
            "status": "not-needed",
            "source": "image-region-recovery:saturation-component",
            "added_count": 0,
            "added": [],
        }
    region = _largest_embedded_saturated_region(image_path)
    if region is None:
        return recovered, {
            "schema_version": "image-region-recovery/1.0",
            "status": "not-found",
            "source": "image-region-recovery:saturation-component",
            "added_count": 0,
            "added": [],
            "limitations": [
                "This fallback only finds large saturated rectangular regions."
            ],
        }
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
    element = {
        "id": next_id,
        "bbox": list(region),
        "type": "image",
        "text": "",
        "role": "",
        "source": "image-region-recovery:saturation-component",
        "authority": "source-pixels",
        "verified": False,
        "container": None,
    }
    recovered.setdefault("elements", []).append(element)
    return recovered, {
        "schema_version": "image-region-recovery/1.0",
        "status": "applied",
        "source": "image-region-recovery:saturation-component",
        "added_count": 1,
        "added": [element],
        "limitations": [
            "Recovered display bytes are reference-only screenshot crops, not original assets.",
            "Low-saturation or small images may remain undetected.",
        ],
    }


def build_image_design(
    graph: Mapping[str, Any],
    reference: Mapping[str, Any],
    *,
    sample_id: str = "image-mvp",
) -> dict[str, Any]:
    """Turn candidate geometry into a deterministic fixed-coordinate design."""
    image_path = str(graph.get("image") or reference["input"]["path"])
    width, height = (int(value) for value in reference["input"]["size"])
    screenshot_sha = str(reference["input"]["sha256"])
    background = _dominant_color(image_path, [0, 0, width, height])
    elements: list[dict[str, Any]] = []
    route = str(graph.get("route") or "grounding")
    presentation = f"{route}-pixel-sampled-fixed-coordinate"
    enrichment = graph.get("imageEnrichment")
    reference_underlays = (
        copy.deepcopy(enrichment.get("referenceUnderlays") or [])
        if isinstance(enrichment, Mapping)
        else []
    )

    for container in graph.get("containers") or []:
        if not isinstance(container, Mapping):
            continue
        bbox = _normalized_box(container.get("bbox"), width, height)
        if bbox is None:
            continue
        x, y, w, h = bbox
        fill = _dominant_color(image_path, bbox, inset=2)
        element = {
            "id": str(container.get("id") or ""),
            "type": "container",
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "text": "",
            "style": {"fillColor": fill},
            "imageMVP": {
                "source": _candidate_authority(container.get("source")),
                "role": str(container.get("role") or ""),
                "grouping_status": "candidate",
            },
        }
        elements.append(element)

    for item in graph.get("elements") or []:
        if not isinstance(item, Mapping):
            continue
        bbox = _normalized_box(item.get("bbox"), width, height)
        if bbox is None:
            continue
        x, y, w, h = bbox
        candidate_type = str(item.get("type") or "rectangle").lower()
        if candidate_type in {"image", "avatar"}:
            classification = classify_full_screenshot_underlay(
                {
                    "name": item.get("assetName") or item.get("name"),
                    "kind": item.get("assetKind") or item.get("kind"),
                    "bbox": list(bbox),
                    "role": item.get("role"),
                    "background": item.get("background"),
                },
                graph,
                width=width,
                height=height,
            )
            if classification["is_underlay"]:
                evidence = {
                    "name": str(item.get("assetName") or item.get("name") or ""),
                    "kind": str(item.get("assetKind") or item.get("kind") or ""),
                    "bbox": list(bbox),
                    "classification": classification,
                }
                if not any(
                    existing.get("name") == evidence["name"]
                    and existing.get("bbox") == evidence["bbox"]
                    for existing in reference_underlays
                ):
                    reference_underlays.append(evidence)
                continue
        element_type = {
            "link": "text",
            "avatar": "image",
            "circle": "circle",
        }.get(candidate_type, candidate_type)
        if element_type not in {
            "text",
            "button",
            "input",
            "image",
            "avatar",
            "rectangle",
            "circle",
        }:
            element_type = "rectangle"
        text = str(item.get("text") or "")
        rendered_text = text if element_type in {"text", "button", "input"} else ""
        element: dict[str, Any] = {
            "id": str(item.get("id") or ""),
            "type": element_type,
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "text": rendered_text,
            "style": {},
            "imageMVP": {
                "source": _candidate_authority(item.get("source")),
                "candidate_type": candidate_type,
                "role": str(item.get("role") or ""),
                "grouping_status": "candidate",
                "reference_only": False,
                "generated": False,
            },
        }

        if element_type == "text":
            local_surface = (
                None
                if _text_has_dark_container(item, graph, image_path)
                else _local_text_surface(image_path, bbox)
            )
            if local_surface is not None:
                surface_box, surface_fill = local_surface
                x, y, w, h = surface_box
                element_type = "button"
                element.update(
                    {
                        "type": "button",
                        "x": x,
                        "y": y,
                        "width": w,
                        "height": h,
                    }
                )
                text_color, _ink_box, _band_height = _foreground_color(
                    image_path, surface_box
                )
                element["style"] = {
                    "fillColor": surface_fill,
                    "textColor": text_color,
                    "fontSize": max(12, min(16, int(round(h * 0.38)))),
                    "fontWeight": "normal",
                    "fontFamily": _font_family(text),
                    "borderRadius": 6 if w >= 24 and h >= 20 else 0,
                }
                element["imageMVP"]["textStatus"] = "ocr-candidate"
                element["imageMVP"]["surfaceRecovery"] = "local-color-component"
                elements.append(element)
                continue
            text_color, ink_box, band_height = _foreground_color(image_path, bbox)
            font_size = _estimate_font_size(text, ink_box or (0, 0, w, h), band_height)
            element["style"] = {
                "textColor": text_color,
                "fontSize": font_size,
                "fontWeight": "bold" if font_size >= 20 else "normal",
                "fontFamily": _font_family(text),
            }
            element["imageMVP"]["textStatus"] = "grounding-candidate"
        elif element_type in {"button", "input"}:
            fill = _dominant_color(image_path, bbox, inset=2)
            text_color, _ink_box, _band_height = _foreground_color(image_path, bbox)
            style = {
                "fillColor": fill,
                "textColor": text_color,
                "fontSize": max(12, min(16, int(round(h * 0.38)))),
                "fontWeight": "normal",
                "fontFamily": _font_family(text),
                "borderRadius": 6 if w >= 24 and h >= 20 else 0,
            }
            if element_type == "input":
                style["borderColor"] = _contrast_border_color(fill)
                style["borderWidth"] = 1
            element["style"] = style
            element["imageMVP"]["textStatus"] = "grounding-candidate"
        elif element_type in {"image", "avatar"}:
            visible_crop = item.get("visibleCrop") or item.get("sourceCrop")
            payload = None
            digest = None
            source_rect = None
            if isinstance(visible_crop, Mapping):
                displayed = _normalized_box(
                    visible_crop.get("display_box"),
                    width,
                    height,
                )
                if displayed is not None:
                    x, y, w, h = displayed
                crop_path = Path(str(visible_crop.get("path") or ""))
                if crop_path.is_file():
                    payload = base64.b64encode(crop_path.read_bytes()).decode("ascii")
                    digest = hashlib.sha256(
                        base64.b64decode(payload)
                    ).hexdigest()
                source_rect = _normalized_box(
                    visible_crop.get("source_rect"),
                    width,
                    height,
                )
            else:
                x, y, w, h = _refine_image_box(image_path, bbox)
            element.update({"x": x, "y": y, "width": w, "height": h})
            if payload is None:
                payload = crop_image_b64(image_path, x, y, w, h, width, height)
            if payload:
                element["imageBase64"] = payload
            if digest is None:
                digest = (
                    hashlib.sha256(base64.b64decode(payload)).hexdigest()
                    if payload
                    else None
                )
            record = build_asset_record(
                sample_id=sample_id,
                node_index=_safe_node_index(item.get("id")),
                source_kind="screenshot-crop",
                source=None,
                natural_size=(w, h),
                display_box=(x, y, w, h),
                display_payload_sha256=digest,
                screenshot_sha256=screenshot_sha,
                source_rect=source_rect,
            )
            if payload:
                record = attach_display_payload(
                    record,
                    payload_sha256=digest,
                    screenshot_sha256=screenshot_sha,
                    display_box=(x, y, w, h),
                )
            element["assetIdentity"] = {"asset_record": record}
            element["displayPayload"] = dict(record["display_payload"])
            element["replacement"] = dict(record["replacement"])
            source_resolution = item.get("sourceResolution")
            element["sourceResolution"] = (
                copy.deepcopy(dict(source_resolution))
                if isinstance(source_resolution, Mapping)
                else fuse_asset_record(record)
            )
            if isinstance(visible_crop, Mapping):
                element["visibleCrop"] = copy.deepcopy(dict(visible_crop))
            generated = item.get("generatedApproximation")
            if isinstance(generated, Mapping):
                element["generatedApproximation"] = copy.deepcopy(dict(generated))
            element["imageMVP"].update(
                {
                    "sourceStatus": "unavailable-from-flat-image",
                    "reference_only": True,
                    "displayReplaceable": bool(payload),
                    "originalAssetClaimed": False,
                    "generated": bool(
                        isinstance(generated, Mapping)
                        and generated.get("generated")
                    ),
                }
            )
        else:
            fill = _dominant_color(image_path, bbox, inset=1)
            element["style"] = {"fillColor": fill}

        elements.append(element)

    image_count = sum(element["type"] in {"image", "avatar"} for element in elements)
    text_count = sum(element["type"] == "text" for element in elements)
    design = {
        "name": f"Image MVP {sample_id}",
        "canvas": {
            "width": width,
            "height": height,
            "background": background,
        },
        "elements": elements,
        "_meta": {
            "mode": "image-mvp-direct",
            "source": f"{route} candidate geometry with screenshot-pixel styles",
            "imagePresentation": presentation,
            "expected": len(graph.get("containers") or [])
            + len(graph.get("elements") or []),
            "returned": len(elements),
            "coverage": 1.0,
            "calls": 1,
            "rounds": 1,
            "imageMVP": {
                "reference_id": reference["reference_id"],
                "state": dict(reference["state"]),
                "flow": {
                    "value": "fixed-coordinate",
                    "status": "candidate",
                    "adaptive": False,
                },
                "counts": {
                    "text": text_count,
                    "images": image_count,
                    "containers": len(graph.get("containers") or []),
                },
                "assetClaim": "display-replacement-only",
                "originalAssetClaimed": False,
                "referenceUnderlays": reference_underlays,
            },
        },
    }
    return design


def audit_native_reconstruction(design: Mapping[str, Any]) -> dict[str, Any]:
    """Reject visible source screenshots used as the native frame background."""

    canvas = design.get("canvas") or {}
    try:
        page_width = int(canvas.get("width") or 0)
        page_height = int(canvas.get("height") or 0)
    except (TypeError, ValueError):
        page_width = page_height = 0
    page_area = page_width * page_height
    underlays = []
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        element_type = str(element.get("type") or "").lower()
        if element_type not in {"image", "avatar"} and not element.get(
            "imageBase64"
        ):
            continue
        role = str(element.get("role") or "").lower()
        asset_kind = str(
            element.get("assetKind")
            or (element.get("assetIdentity") or {}).get("kind")
            or ""
        ).lower()
        if (
            role == "background"
            or asset_kind == "background"
            or element.get("background") is True
        ):
            continue
        try:
            box = _normalized_box(element.get("bbox"), page_width, page_height)
        except Exception:
            box = _normalized_box(
                [
                    element.get("x"),
                    element.get("y"),
                    element.get("width"),
                    element.get("height"),
                ],
                page_width,
                page_height,
            )
        if box is None:
            try:
                width = int(element.get("width") or 0)
                height = int(element.get("height") or 0)
            except (TypeError, ValueError):
                width = height = 0
            area_ratio = width * height / page_area if page_area else 0.0
        else:
            area_ratio = box[2] * box[3] / page_area if page_area else 0.0
        explicit_reference = bool(
            element.get("referenceUnderlay")
            or role == "reference-underlay"
        )
        if explicit_reference or area_ratio >= 0.95:
            underlays.append(
                {
                    "id": str(element.get("id") or ""),
                    "name": str(element.get("name") or ""),
                    "reason": (
                        "explicit-reference-underlay"
                        if explicit_reference
                        else "spans-page"
                    ),
                    "area_ratio": round(area_ratio, 6),
                }
            )
    return {
        "status": "blocked" if underlays else "pass",
        "underlays": underlays,
        "native_text_count": sum(
            bool(str(element.get("text") or ""))
            and str(element.get("type") or "").lower()
            in {"text", "button", "input"}
            for element in design.get("elements") or []
            if isinstance(element, Mapping)
        ),
        "image_fill_count": sum(
            bool(element.get("imageBase64"))
            for element in design.get("elements") or []
            if isinstance(element, Mapping)
        ),
    }


def build_image_ir(
    graph: Mapping[str, Any],
    design: Mapping[str, Any],
    reference: Mapping[str, Any],
    strategy: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the field-level, candidate-safe IR retained beside the design."""
    design_by_id = {
        str(element.get("id") or ""): element
        for element in design.get("elements") or []
        if isinstance(element, Mapping)
    }
    nodes: list[dict[str, Any]] = []
    for item in [
        *(graph.get("containers") or []),
        *(graph.get("elements") or []),
    ]:
        if not isinstance(item, Mapping):
            continue
        node_id = str(item.get("id") or "")
        element = design_by_id.get(node_id, {})
        fields = {
            "bbox": {
                "value": list(item.get("bbox") or []),
                "authority": "source-pixels",
                "status": "observed",
            },
            "role": {
                "value": str(item.get("role") or ""),
                "authority": _candidate_authority(item.get("source")),
                "status": "candidate",
            },
            "flow": {
                "value": "fixed-coordinate",
                "authority": "image-mvp-policy",
                "status": "candidate",
            },
        }
        if str(item.get("text") or "").strip():
            source = str(item.get("source") or "")
            fields["text"] = {
                "value": str(item.get("text")),
                "authority": _candidate_authority(source),
                "status": "candidate",
                "verified": False,
            }
        if str(item.get("type") or "").lower() in {
            "text",
            "link",
            "button",
            "input",
        }:
            fields["editability"] = {
                "value": "native-text-candidate",
                "authority": "image-mvp-policy",
                "status": "candidate",
            }
        if str(item.get("type") or "").lower() in {"image", "avatar"}:
            fields["asset_source"] = {
                "value": "screenshot-crop-reference-only",
                "authority": "source-pixels",
                "status": "candidate",
                "original": False,
            }
        nodes.append(
            {
                "node_id": node_id,
                "node_kind": (
                    "container"
                    if item in (graph.get("containers") or [])
                    else "element"
                ),
                "design_element_id": (
                    str(element.get("id")) if isinstance(element, Mapping) else None
                ),
                "parent_id": item.get("parent"),
                "fields": fields,
            }
        )

    assets = []
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        resolution = element.get("sourceResolution") or {}
        if not isinstance(resolution, Mapping) or not resolution:
            continue
        display = resolution.get("display") or {}
        identity = resolution.get("identity") or {}
        assets.append(
            {
                "node_id": str(element.get("id") or ""),
                "identity": str(identity.get("selected") or "unknown"),
                "display": str(display.get("selected") or "missing"),
                "original": bool(identity.get("original")),
                "reference_only": bool(display.get("reference_only")),
                "generated": bool(display.get("generated")),
                "payload_sha256": (
                    (element.get("displayPayload") or {}).get("payload_sha256")
                ),
            }
        )
    return {
        "schema_version": IR_SCHEMA_VERSION,
        "input": dict(reference),
        "strategy": dict(strategy),
        "state": dict(reference["state"]),
        "nodes": nodes,
        "assets": assets,
        "counts": {
            "nodes": len(nodes),
            "text_candidates": sum("text" in node["fields"] for node in nodes),
            "image_candidates": len(assets),
        },
        "limitations": [
            "Original asset identity is unavailable from a flat screenshot.",
            "Original DPR, viewport and font identity are unknown.",
            "Flow is a fixed-coordinate candidate, not verified adaptive layout.",
            "Grounding text remains a candidate until checked against supplied truth.",
            "Hidden regions cannot be recovered from one screenshot.",
        ],
        "non_claims": [
            "original-asset",
            "original-font",
            "original-dpr",
            "original-viewport",
            "adaptive-flow",
            "hidden-region-recovery",
        ],
    }


def _normalized_box(
    value: Any,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    try:
        x, y, w, h = (int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    x0 = max(0, min(width, x))
    y0 = max(0, min(height, y))
    x1 = max(x0, min(width, x + w))
    y1 = max(y0, min(height, y + h))
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    return x0, y0, x1 - x0, y1 - y0


def _candidate_authority(source: Any) -> str:
    value = str(source or "").strip().lower()
    if value.startswith("cv:ocr"):
        return "cv-ocr-candidate"
    if value.startswith("cv:omniparser"):
        return "cv-omniparser-candidate"
    if value.startswith("cv:v2.4"):
        return "cv-container-candidate"
    if value.startswith("cv:"):
        return "cv-visual-candidate"
    if value.startswith("hybrid:"):
        return "hybrid-cv-candidate"
    if value.startswith("ocr-supplement:"):
        return "ocr-candidate"
    if value.startswith("image-region-recovery:"):
        return "source-pixels-candidate"
    return "grounding-vlm-candidate"


def _dominant_color(
    image_path: str | Path,
    bbox: tuple[int, int, int, int] | list[int],
    *,
    inset: int = 0,
) -> str:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        x, y, w, h = bbox
        x0 = min(image.width, x + max(0, inset))
        y0 = min(image.height, y + max(0, inset))
        x1 = min(image.width, x + w - max(0, inset))
        y1 = min(image.height, y + h - max(0, inset))
        if x1 <= x0 or y1 <= y0:
            x0, y0, x1, y1 = x, y, x + w, y + h
        crop = image.crop((x0, y0, x1, y1))
        if crop.width > 40 or crop.height > 40:
            crop.thumbnail((40, 40))
        colors = crop.getcolors(maxcolors=100000)
    if not colors:
        return "#ffffff"
    return _hex_color(max(colors, key=lambda item: item[0])[1])


def _foreground_color(
    image_path: str | Path,
    bbox: tuple[int, int, int, int],
) -> tuple[str, tuple[int, int, int, int] | None, int | None]:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        x, y, w, h = bbox
        crop = image.crop((x, y, x + w, y + h))
    colors = crop.getcolors(maxcolors=100000)
    if not colors:
        return "#172033", None, None
    background = max(colors, key=lambda item: item[0])[1]
    get_pixels = getattr(crop, "get_flattened_data", crop.getdata)
    pixels = list(get_pixels())
    candidate_pixels = [(pixel, _color_distance(pixel, background)) for pixel in pixels]
    candidate_pixels.sort(key=lambda item: item[1], reverse=True)
    far = [pixel for pixel, distance in candidate_pixels if distance >= 60]
    if far:
        ink = far[0]
    else:
        ink = max(pixels, key=lambda pixel: _color_distance(pixel, background))
    mask = Image.new("L", crop.size, 0)
    mask_pixels = [
        255 if _color_distance(pixel, background) >= 45 else 0 for pixel in pixels
    ]
    mask.putdata(mask_pixels)
    ink_box = mask.getbbox()
    page_box = (
        (
            x + ink_box[0],
            y + ink_box[1],
            ink_box[2] - ink_box[0],
            ink_box[3] - ink_box[1],
        )
        if ink_box
        else None
    )
    band_height = None
    if ink_box:
        rows = [
            any(mask.getpixel((column, row)) for column in range(mask.width))
            for row in range(mask.height)
        ]
        bands: list[int] = []
        current = 0
        for occupied in rows:
            if occupied:
                current += 1
            elif current:
                bands.append(current)
                current = 0
        if current:
            bands.append(current)
        if bands:
            band_height = max(bands)
    return _hex_color(ink), page_box, band_height


def _color_distance(
    left: tuple[int, int, int],
    right: tuple[int, int, int],
) -> float:
    return sum((int(a) - int(b)) ** 2 for a, b in zip(left, right, strict=True)) ** 0.5


def _estimate_font_size(
    text: str,
    ink_box: tuple[int, int, int, int],
    band_height: int | None = None,
) -> int:
    del text
    ink_height = max(1, int(band_height or ink_box[3]))
    return max(10, min(36, int(round(ink_height * 1.05))))


def _font_family(text: str) -> str:
    return "Microsoft YaHei" if any(ord(char) > 127 for char in text) else "Arial"


def _contrast_border_color(fill: str) -> str:
    red, green, blue = _parse_hex(fill)
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "#c8d1de" if luminance >= 150 else "#64748b"


def _parse_hex(value: str) -> tuple[int, int, int]:
    text = str(value).lstrip("#")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def _hex_color(value: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(channel))):02x}" for channel in value)


def _safe_node_index(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        digest = hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
        return int(digest[:8], 16)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _merge_ocr_line_observations(
    observations: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> list[dict[str, Any]]:
    rows = []
    for observation in observations:
        try:
            x, y, width, height = (
                int(round(float(value))) for value in observation["bbox"]
            )
            confidence = float(observation.get("confidence") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        text = str(observation.get("text") or "").strip()
        if not text or confidence < 0.4:
            continue
        rows.append(
            {
                "text": text,
                "bbox": [x, y, width, height],
                "confidence": confidence,
            }
        )
    rows.sort(key=lambda row: (row["bbox"][1] + row["bbox"][3] / 2, row["bbox"][0]))
    bands: list[list[dict[str, Any]]] = []
    for row in rows:
        center_y = row["bbox"][1] + row["bbox"][3] / 2
        if not bands:
            bands.append([row])
            continue
        band = bands[-1]
        band_center = sum(item["bbox"][1] + item["bbox"][3] / 2 for item in band) / len(
            band
        )
        tolerance = max(
            8,
            max(item["bbox"][3] for item in band + [row]) * 0.45,
        )
        if abs(center_y - band_center) <= tolerance:
            band.append(row)
        else:
            bands.append([row])

    lines: list[list[dict[str, Any]]] = []
    for band in bands:
        band.sort(key=lambda item: item["bbox"][0])
        current: list[dict[str, Any]] = []
        for row in band:
            if not current:
                current = [row]
                continue
            current_right = max(item["bbox"][0] + item["bbox"][2] for item in current)
            gap = row["bbox"][0] - current_right
            if -8 <= gap <= 12:
                current.append(row)
            else:
                lines.append(current)
                current = [row]
        if current:
            lines.append(current)
    lines.sort(
        key=lambda line: (
            min(item["bbox"][1] for item in line),
            min(item["bbox"][0] for item in line),
        )
    )
    merged = []
    for line in lines:
        left = min(item["bbox"][0] for item in line)
        top = min(item["bbox"][1] for item in line)
        right = max(item["bbox"][0] + item["bbox"][2] for item in line)
        bottom = max(item["bbox"][1] + item["bbox"][3] for item in line)
        merged.append(
            {
                "text": " ".join(item["text"] for item in line),
                "bbox": [left, top, right - left, bottom - top],
                "confidence": min(item["confidence"] for item in line),
            }
        )
    return merged


def _normalize_candidate_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").casefold())


def _ocr_candidate_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(item.get("source") or ""),
        tuple(item.get("bbox") or []),
        str(item.get("text") or ""),
    )


def _box_coverage(
    inner: tuple[int, int, int, int] | list[int],
    outer: tuple[int, int, int, int] | list[int],
) -> float:
    try:
        ix, iy, iw, ih = (float(value) for value in inner)
        ox, oy, ow, oh = (float(value) for value in outer)
    except (TypeError, ValueError):
        return 0.0
    left = max(ix, ox)
    top = max(iy, oy)
    right = min(ix + iw, ox + ow)
    bottom = min(iy + ih, oy + oh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    inner_area = max(1.0, iw * ih)
    return intersection / inner_area


def _refine_image_box(
    image_path: str | Path,
    bbox: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Shrink a broad panel candidate to its largest visible image-like region."""
    import cv2
    import numpy as np

    x, y, w, h = bbox
    with Image.open(image_path) as source:
        image = np.asarray(source.convert("RGB"))
    crop = image[y : y + h, x : x + w]
    if crop.size == 0:
        return bbox
    background = np.array(_parse_hex(_dominant_color(image_path, bbox, inset=2)))
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
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    candidates = []
    for index in range(1, count):
        left, top, width, height, area = (int(value) for value in stats[index, :5])
        if width < 8 or height < 8:
            continue
        candidates.append((area, left, top, width, height))
    if not candidates:
        return bbox
    area, left, top, width, height = max(candidates, key=lambda item: item[0])
    if area < (w * h * 0.02) or (width * height) >= (w * h * 0.9):
        return bbox
    return x + left, y + top, width, height


def _largest_embedded_saturated_region(
    image_path: str | Path,
) -> tuple[int, int, int, int] | None:
    import cv2
    import numpy as np

    image = cv2.imread(str(image_path))
    if image is None:
        return None
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 1] >= 45) & (hsv[..., 2] >= 45)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        np.ones((7, 7), dtype=np.uint8),
    )
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    minimum_area = width * height * 0.01
    candidates = []
    for index in range(1, count):
        x, y, box_width, box_height, area = (int(value) for value in stats[index, :5])
        if x <= 2 or y <= 2:
            continue
        if x + box_width >= width - 2 or y + box_height >= height - 2:
            continue
        if box_width > width * 0.6 or box_height > height * 0.6:
            continue
        if area < minimum_area or box_width < 40 or box_height < 40:
            continue
        candidates.append((area, x, y, box_width, box_height))
    if not candidates:
        return None
    _area, x, y, box_width, box_height = max(candidates, key=lambda item: item[0])
    return x, y, box_width, box_height


def _text_has_dark_container(
    item: Mapping[str, Any],
    graph: Mapping[str, Any],
    image_path: str | Path,
) -> bool:
    container_id = str(item.get("container") or "")
    container = next(
        (
            candidate
            for candidate in graph.get("containers") or []
            if str(candidate.get("id") or "") == container_id
        ),
        None,
    )
    if container is None:
        return False
    fill = _dominant_color(image_path, container["bbox"], inset=2)
    return _luminance(fill) < 170


def _local_text_surface(
    image_path: str | Path,
    bbox: tuple[int, int, int, int],
) -> tuple[tuple[int, int, int, int], str] | None:
    import cv2
    import numpy as np

    image = cv2.imread(str(image_path))
    if image is None:
        return None
    height, width = image.shape[:2]
    x, y, w, h = bbox
    near = (
        max(0, x - 16),
        max(0, y - 10),
        min(width, x + w + 16),
        min(height, y + h + 10),
    )
    near_fill = _dominant_color(
        image_path,
        [near[0], near[1], near[2] - near[0], near[3] - near[1]],
    )
    if _luminance(near_fill) >= 170:
        return None
    search = (
        max(0, x - 100),
        max(0, y - 40),
        min(width, x + w + 100),
        min(height, y + h + 40),
    )
    crop = image[search[1] : search[3], search[0] : search[2]]
    target = np.array(_parse_hex(near_fill)[::-1])
    mask = (np.linalg.norm(crop.astype(np.int16) - target, axis=2) <= 38).astype(
        np.uint8
    ) * 255
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        np.ones((5, 5), dtype=np.uint8),
    )
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    choices = []
    for index in range(1, count):
        left, top, box_width, box_height, area = (
            int(value) for value in stats[index, :5]
        )
        if box_width < max(20, w) or box_height < max(18, h):
            continue
        if box_width > 360 or box_height > 120:
            continue
        choices.append((area, left, top, box_width, box_height))
    if not choices:
        return None
    _area, left, top, box_width, box_height = max(choices, key=lambda item: item[0])
    return (
        (
            search[0] + left,
            search[1] + top,
            box_width,
            box_height,
        ),
        near_fill,
    )


def _luminance(value: str) -> float:
    red, green, blue = _parse_hex(value)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue
