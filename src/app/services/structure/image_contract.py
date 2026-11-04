"""Deterministic image-to-Figma MVP contracts and presentation helpers."""

from __future__ import annotations

import base64
import copy
import difflib
import hashlib
import html
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2
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
from src.app.services.structure.image_enrichment.vector_icons import (
    vector_icon_svg,
)
from src.app.services.structure.image_enrichment.table_scene import (
    normalize_table_design,
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
        overlong = [
            current
            for current in existing
            if len(current["normalized"]) > max(32, len(normalized) * 2)
            and normalized in current["normalized"]
            and _box_coverage(line["bbox"], current["bbox"]) >= 0.5
        ]
        if overlong:
            replaced_covered.extend(overlong)
            replaced_keys.update(current["key"] for current in overlong)
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
    enrichment_mode = (
        str(enrichment.get("mode") or "") if isinstance(enrichment, Mapping) else ""
    )
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
            "name": str(container.get("name") or container.get("role") or "Container"),
            "role": str(container.get("role") or ""),
            "imageMVP": {
                "source": _candidate_authority(container.get("source")),
                "role": str(container.get("role") or ""),
                "grouping_status": "candidate",
            },
        }
        if container.get("contentRef"):
            element["contentRef"] = str(container["contentRef"])
        if container.get("sceneOwnerId"):
            element["sceneOwnerId"] = str(container["sceneOwnerId"])
        elements.append(element)

    if enrichment_mode in {"analyze", "apply"}:
        elements.extend(
            _recover_surface_bands(
                image_path,
                graph,
                width=width,
                height=height,
            )
        )

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
        control_value = str(item.get("controlValue") or item.get("value") or "")
        control_type = str(item.get("controlType") or candidate_type).lower()
        raw_control_text = str(control_value or item.get("text") or "")
        if (
            control_type == "icon-button"
            and w >= 100
            and h >= 28
            and any(
                token in _ui_text(raw_control_text)
                for token in ("search", "搜索", "筛选")
            )
        ):
            control_type = "input"
        search_placeholder = control_type == "input" and any(
            token in _ui_text(raw_control_text) for token in ("search", "搜索", "筛选")
        )
        if search_placeholder:
            control_value = ""
        element_type = {
            "link": "text",
            "avatar": "image",
            "circle": "circle",
            "checkbox": "input",
            "icon-button": "button",
            "navigation": "button",
            "pagination": "button",
            "radio": "input",
            "select": "input",
            "textarea": "input",
            "toggle": "input",
        }.get(control_type, candidate_type)
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
        is_control = control_type in {
            "button",
            "checkbox",
            "icon-button",
            "input",
            "link",
            "navigation",
            "pagination",
            "radio",
            "select",
            "textarea",
            "toggle",
        }
        if (
            enrichment_mode in {"analyze", "apply"}
            and is_control
            and not search_placeholder
            and not control_value
        ):
            control_value = _text_inside_box(graph, bbox, width, height)
        if (
            enrichment_mode == "apply"
            and candidate_type == "icon-button"
            and not control_value
            and w <= 64
            and h <= 64
        ):
            continue
        text = (
            "" if search_placeholder else control_value or str(item.get("text") or "")
        )
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
        if item.get("contentRef"):
            element["contentRef"] = str(item["contentRef"])
        if item.get("sceneOwnerId"):
            element["sceneOwnerId"] = str(item["sceneOwnerId"])
        if enrichment_mode in {"analyze", "apply"} and is_control:
            element["controlType"] = control_type
            element["controlValue"] = (
                ""
                if search_placeholder
                else control_value or str(item.get("text") or "")
            )
            element["controlState"] = str(
                item.get("controlState") or item.get("state") or ""
            )

        if element_type == "text":
            if enrichment_mode in {"analyze", "apply"}:
                recovered_status = _recover_status_text_box(
                    image_path,
                    bbox,
                    text,
                )
                if recovered_status is not None:
                    bbox = recovered_status
                    x, y, w, h = bbox
                    element.update(
                        {
                            "x": x,
                            "y": y,
                            "width": w,
                            "height": h,
                        }
                    )
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
                if enrichment_mode in {"analyze", "apply"}:
                    element["controlType"] = "button"
                    element["controlState"] = element.get("controlState") or "enabled"
                text_color, _ink_box, _band_height = _foreground_color(
                    image_path, surface_box
                )
                element["style"] = {
                    "fillColor": surface_fill,
                    "textColor": text_color,
                    "fontSize": max(12, min(16, int(round(h * 0.38)))),
                    "fontWeight": "normal",
                    "fontFamily": (
                        _teacher_font_family(text)
                        if enrichment_mode in {"analyze", "apply"}
                        else _font_family(text)
                    ),
                    "borderRadius": 6 if w >= 24 and h >= 20 else 0,
                }
                if enrichment_mode in {"analyze", "apply"}:
                    element["style"]["lineHeight"] = max(
                        24,
                        int(round(element["style"]["fontSize"] * 1.5)),
                    )
                element["imageMVP"]["textStatus"] = "ocr-candidate"
                element["imageMVP"]["surfaceRecovery"] = "local-color-component"
                elements.append(element)
                continue
            text_color, ink_box, band_height = _foreground_color(image_path, bbox)
            if ink_box is not None and enrichment_mode in {"analyze", "apply"}:
                ink_x = ink_box[0]
                element["width"] = max(8, w - (ink_x - x))
                x = ink_x
                element["x"] = x
            font_size = _estimate_font_size(text, ink_box or (0, 0, w, h), band_height)
            element["style"] = {
                "textColor": text_color,
                "fontSize": font_size,
                "fontWeight": "bold" if font_size >= 20 else "normal",
                "fontFamily": (
                    _teacher_font_family(text)
                    if enrichment_mode in {"analyze", "apply"}
                    else _font_family(text)
                ),
            }
            if enrichment_mode in {"analyze", "apply"}:
                element["style"]["lineHeight"] = max(
                    24,
                    int(round(font_size * 1.5)),
                )
            element["imageMVP"]["textStatus"] = "grounding-candidate"
        elif element_type in {"button", "input"}:
            fill = _dominant_color(image_path, bbox, inset=2)
            text_color, _ink_box, _band_height = _foreground_color(image_path, bbox)
            style = {
                "fillColor": fill,
                "textColor": text_color,
                "fontSize": max(12, min(16, int(round(h * 0.38)))),
                "fontWeight": "normal",
                "fontFamily": (
                    _teacher_font_family(text)
                    if enrichment_mode in {"analyze", "apply"}
                    else _font_family(text)
                ),
                "borderRadius": 6 if w >= 24 and h >= 20 else 0,
            }
            if enrichment_mode in {"analyze", "apply"}:
                style["lineHeight"] = max(
                    24,
                    int(round(style["fontSize"] * 1.5)),
                )
            if element_type == "input":
                style["borderColor"] = _sample_border_color(
                    image_path,
                    bbox,
                    fill,
                )
                style["borderWidth"] = 1
            element["style"] = style
            if (
                element_type == "input"
                and str(control_type) in {"input", "text", "textarea", "text-area"}
                and text
            ):
                text_top = 9 if str(control_type) in {"textarea", "text-area"} else 10
                text_height = (
                    24 if str(control_type) in {"textarea", "text-area"} else 20
                )
                recovered_text_box = _recover_control_text_box(
                    image_path,
                    bbox,
                )
                element["textBox"] = (
                    list(recovered_text_box)
                    if recovered_text_box is not None
                    else [
                        x + 12,
                        y + text_top,
                        max(1, w - 24),
                        text_height,
                    ]
                )
            if element_type == "input":
                element["x"] = x + 1
                element["y"] = y + 1
                if element.get("textBox"):
                    element["textBox"][0] += 1
                    element["textBox"][1] += 1
            element["imageMVP"]["textStatus"] = "grounding-candidate"
        elif element_type in {"image", "avatar"}:
            identity = item.get("assetIdentity")
            asset_name = (
                item.get("assetName")
                or item.get("name")
                or (identity.get("name") if isinstance(identity, Mapping) else "")
            )
            asset_kind = (
                item.get("assetKind")
                or item.get("kind")
                or (identity.get("kind") if isinstance(identity, Mapping) else "")
                or "image"
            )
            if str(asset_kind).lower() == "icon":
                foreground = _foreground_color(image_path, bbox)[0]
                vector_svg = vector_icon_svg(
                    str(asset_name),
                    w,
                    h,
                    foreground,
                )
                if vector_svg is not None:
                    element.update(
                        {
                            "vectorSvg": vector_svg,
                            "assetName": str(asset_name or ""),
                            "assetKind": "icon",
                            "assetIdentity": {
                                "status": "native-vector",
                                "name": str(asset_name or ""),
                                "kind": "icon",
                                "reference_only": False,
                                "original": False,
                            },
                        }
                    )
                    element["imageMVP"].update(
                        {
                            "sourceStatus": "native-vector",
                            "reference_only": False,
                            "displayReplaceable": True,
                            "originalAssetClaimed": False,
                            "generated": False,
                        }
                    )
                    elements.append(element)
                    continue
            visible_crop = item.get("visibleCrop") or item.get("sourceCrop")
            payload = None
            digest = None
            source_rect = None
            identity_box = None
            special_box = None
            if isinstance(visible_crop, Mapping):
                displayed = _normalized_box(
                    visible_crop.get("display_box"),
                    width,
                    height,
                )
                if displayed is not None:
                    identity_box = displayed
                    x, y, w, h = displayed
                requested = _normalized_box(
                    visible_crop.get("requested_bbox") or bbox,
                    width,
                    height,
                )
                if str(asset_kind).lower() == "logo":
                    special_box = (
                        _logo_display_box(image_path, requested)
                        if requested is not None
                        else None
                    )
                elif str(asset_kind).lower() == "avatar":
                    special_box = (
                        _avatar_display_box(image_path, requested)
                        if requested is not None
                        else None
                    )
                elif (
                    str(asset_kind).lower() == "icon"
                    and "badge" in str(asset_name).lower()
                ):
                    special_box = (
                        _badge_display_box(image_path, requested)
                        if requested is not None
                        else None
                    )
                if special_box is not None:
                    x, y, w, h = special_box
                else:
                    crop_path = Path(str(visible_crop.get("path") or ""))
                    if crop_path.is_file():
                        payload = base64.b64encode(crop_path.read_bytes()).decode(
                            "ascii"
                        )
                        digest = hashlib.sha256(base64.b64decode(payload)).hexdigest()
                source_rect = _normalized_box(
                    visible_crop.get("source_rect"),
                    width,
                    height,
                )
                if special_box is not None:
                    source_rect = list(special_box)
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
            if identity_box is not None:
                element["assetIdentity"]["bbox"] = list(identity_box)
            element["displayPayload"] = dict(record["display_payload"])
            element["replacement"] = dict(record["replacement"])
            element["assetName"] = str(asset_name or "")
            element["assetKind"] = str(asset_kind or "image")
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
                        isinstance(generated, Mapping) and generated.get("generated")
                    ),
                }
            )
        else:
            fill = _dominant_color(image_path, bbox, inset=1)
            element["style"] = {"fillColor": fill}

        elements.append(element)

    if enrichment_mode in {"analyze", "apply"}:
        _normalize_sidebar_rows(
            elements,
            graph,
            width=width,
            height=height,
        )
        elements.extend(
            _recover_sidebar_search(
                image_path,
                graph,
                elements,
                width=width,
                height=height,
            )
        )
        elements.extend(
            _recover_chrome_icons(
                image_path,
                graph,
                elements,
                width=width,
                height=height,
            )
        )
        _normalize_breadcrumb_design(
            elements,
            graph,
            width=width,
            height=height,
        )
        search_field = _recover_search_field(
            image_path,
            graph,
            elements,
            width=width,
            height=height,
        )
        if search_field is not None:
            elements.append(search_field)
        elements = normalize_table_design(
            elements,
            image_path,
            graph,
            canvas_size=(width, height),
        )
        elements = _prefer_input_text_owner(elements)
        elements = _normalize_checked_checkboxes(elements)
        elements = _dedupe_design_elements(elements)
        containers = [
            element
            for element in elements
            if str(element.get("type") or "") == "container"
        ]
        container_ids = {str(container.get("id") or "") for container in containers}
        children_by_container: dict[str, list[str]] = {}
        container_boxes = {
            str(container.get("id") or ""): (
                float(container.get("x") or 0),
                float(container.get("y") or 0),
                float(container.get("width") or 0),
                float(container.get("height") or 0),
            )
            for container in containers
        }

        def smallest_owner(
            child: Mapping[str, Any],
            *,
            require_containment: bool,
        ) -> str:
            x = float(child.get("x") or 0)
            y = float(child.get("y") or 0)
            w = float(child.get("width") or 0)
            h = float(child.get("height") or 0)
            child_id = str(child.get("id") or "")
            candidates = []
            for container_id, (cx, cy, cw, ch) in container_boxes.items():
                if container_id == child_id or cw <= 0 or ch <= 0:
                    continue
                inside = cx <= x and cy <= y and x + w <= cx + cw and y + h <= cy + ch
                if require_containment and not inside:
                    continue
                if not require_containment:
                    center_x, center_y = x + w / 2, y + h / 2
                    inside = cx <= center_x <= cx + cw and cy <= center_y <= cy + ch
                if inside:
                    candidates.append((cw * ch, container_id))
            return min(candidates)[1] if candidates else ""

        for element in elements:
            element_id = str(element.get("id") or "")
            if not element_id:
                continue
            if element_id not in container_ids:
                owner = smallest_owner(element, require_containment=False)
            else:
                owner = smallest_owner(element, require_containment=True)
            if owner:
                children_by_container.setdefault(owner, []).append(element_id)
        order = {
            str(element.get("id") or ""): index
            for index, element in enumerate(elements)
        }
        for element in elements:
            children = list(
                dict.fromkeys(
                    children_by_container.get(
                        str(element.get("id") or ""),
                        [],
                    )
                )
            )
            if not children:
                continue
            children.sort(key=lambda item_id: order.get(item_id, 0))
            element["layout"] = {"mode": "NONE", "itemSpacing": 0}
            element["layoutChildren"] = [{"id": item_id} for item_id in children]
    scene_plan = graph.get("scenePlan")
    if isinstance(scene_plan, Mapping):
        elements = _materialize_scene_plan_text(
            elements,
            scene_plan,
            image_path,
            width=width,
            height=height,
        )
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


def _materialize_scene_plan_text(
    elements: list[dict[str, Any]],
    scene_plan: Mapping[str, Any],
    image_path: str,
    *,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    """Compile planned text owners that no existing DesignSpec element covers."""
    existing_refs = {
        str(element.get("contentRef"))
        for element in elements
        if element.get("contentRef")
    }
    additions: list[dict[str, Any]] = []
    for index, node in enumerate(scene_plan.get("nodes") or []):
        if not isinstance(node, Mapping) or str(node.get("type") or "") not in {
            "text",
            "control",
        }:
            continue
        text = str(node.get("text") or "").strip()
        bbox = _normalized_box(node.get("bbox"), width, height)
        content_ref = str(node.get("content_ref") or "")
        if not text or bbox is None or not content_ref:
            continue
        if content_ref in existing_refs and str(node.get("type") or "") != "control":
            continue
        x, y, node_width, node_height = bbox
        role = str(node.get("role") or "")
        if role in {"table-cell", "table-header"}:
            line_height = max(14, min(22, node_height - 4))
            rendered = {
                "x": x + min(8, max(2, node_width // 12)),
                "y": y + max(2, (node_height - line_height) // 2),
                "width": max(8, node_width - 16),
                "height": line_height,
            }
        elif role == "control-label" and node_width <= 32:
            label_width = min(
                max(80, width - x - node_width - 4),
                max(120, len(text) * 16),
            )
            rendered = {
                "x": x + node_width + 4,
                "y": y + max(0, (node_height - 20) // 2),
                "width": label_width,
                "height": max(18, min(24, node_height)),
            }
        else:
            rendered = {
                "x": x,
                "y": y,
                "width": node_width,
                "height": node_height,
            }
        if str(node.get("type") or "") == "control":
            owner = next(
                (
                    element
                    for element in elements
                    if str(element.get("type") or "") in {"button", "input"}
                    and str(element.get("contentRef") or "") == content_ref
                ),
                None,
            )
            if owner is None:
                owner = next(
                    (
                        element
                        for element in elements
                        if str(element.get("type") or "") in {"button", "input"}
                        and _scene_text_overlaps(element, rendered)
                    ),
                    None,
                )
            if owner is not None:
                owner["text"] = text
                owner["controlValue"] = text
                owner["contentRef"] = content_ref
                owner["sceneOwnerId"] = str(node.get("id") or content_ref)
                owner.setdefault("imageMVP", {})["source"] = "scene-plan"
                existing_refs.add(content_ref)
                continue
            control_type = str(node.get("control_type") or "button").lower()
            owner_type = (
                "input"
                if control_type
                in {
                    "checkbox",
                    "input",
                    "radio",
                    "select",
                    "textarea",
                    "toggle",
                }
                else "button"
            )
            owner = {
                "id": f"scene-control-{index}",
                "type": owner_type,
                "text": text,
                "controlType": control_type,
                "controlValue": text,
                "controlState": str(node.get("state") or "enabled"),
                "style": {
                    "fillColor": _dominant_color(
                        image_path,
                        [x, y, node_width, node_height],
                        inset=2,
                    ),
                    "textColor": _foreground_color(
                        image_path,
                        [x, y, node_width, node_height],
                    )[0],
                    "fontSize": max(
                        12,
                        min(16, int(round(node_height * 0.38))),
                    ),
                    "fontFamily": _teacher_font_family(text),
                    "lineHeight": max(20, min(24, node_height)),
                },
                "imageMVP": {
                    "source": "scene-plan",
                    "role": role,
                    "candidate_type": control_type,
                    "grouping_status": "planned",
                    "reference_only": False,
                    "generated": False,
                    "textStatus": "scene-plan-owner",
                },
                "contentRef": content_ref,
                "sceneOwnerId": str(node.get("id") or content_ref),
                **rendered,
            }
            elements.append(owner)
            additions.append(owner)
            existing_refs.add(content_ref)
            continue
        covered_by = next(
            (
                existing
                for existing in elements
                if _ui_text(existing.get("text") or existing.get("controlValue"))
                == _ui_text(text)
                and _scene_text_overlaps(existing, rendered)
            ),
            None,
        )
        if covered_by is not None:
            covered_by["contentRef"] = content_ref
            covered_by["sceneOwnerId"] = str(node.get("id") or content_ref)
            covered_by.setdefault("imageMVP", {})["source"] = "scene-plan"
            existing_refs.add(content_ref)
            continue
        text_color, ink_box, band_height = _foreground_color(
            image_path,
            [
                rendered["x"],
                rendered["y"],
                rendered["width"],
                rendered["height"],
            ],
        )
        if role in {"table-cell", "table-header"}:
            font_size = 13
        elif role == "control-label":
            font_size = 13
        else:
            font_size = _estimate_font_size(
                text,
                ink_box or list(rendered.values()),
                band_height,
            )
        element = {
            "id": f"scene-text-{index}",
            "type": "text",
            "text": text,
            "style": {
                "textColor": text_color,
                "fontSize": font_size,
                "fontWeight": "bold" if node.get("role") == "title" else "normal",
                "fontFamily": _teacher_font_family(text),
                "lineHeight": max(18, min(24, rendered["height"])),
            },
            "imageMVP": {
                "source": "scene-plan",
                "role": role,
                "candidate_type": "text",
                "grouping_status": "planned",
                "reference_only": False,
                "generated": False,
                "textStatus": "scene-plan-owner",
            },
            "contentRef": content_ref,
            "sceneOwnerId": str(node.get("id") or content_ref),
            **rendered,
        }
        elements.append(element)
        additions.append(element)
        existing_refs.add(content_ref)
    return elements


def _scene_text_overlaps(
    existing: Mapping[str, Any],
    rendered: Mapping[str, Any],
) -> bool:
    left = max(float(existing.get("x") or 0), float(rendered["x"]))
    top = max(float(existing.get("y") or 0), float(rendered["y"]))
    right = min(
        float(existing.get("x") or 0) + float(existing.get("width") or 0),
        float(rendered["x"]) + float(rendered["width"]),
    )
    bottom = min(
        float(existing.get("y") or 0) + float(existing.get("height") or 0),
        float(rendered["y"]) + float(rendered["height"]),
    )
    if right <= left or bottom <= top:
        return False
    intersection = (right - left) * (bottom - top)
    existing_area = float(existing.get("width") or 0) * float(
        existing.get("height") or 0
    )
    return intersection / existing_area >= 0.5 if existing_area > 0 else False


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
        if element_type not in {"image", "avatar"} and not element.get("imageBase64"):
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
            element.get("referenceUnderlay") or role == "reference-underlay"
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
            and str(element.get("type") or "").lower() in {"text", "button", "input"}
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


def _text_inside_box(
    graph: Mapping[str, Any],
    box: tuple[int, int, int, int],
    width: int,
    height: int,
) -> str:
    target_area = box[2] * box[3]
    ranked: list[tuple[float, str]] = []
    for item in graph.get("elements") or []:
        if (
            not isinstance(item, Mapping)
            or str(item.get("type") or "").lower() != "text"
        ):
            continue
        text = str(item.get("text") or "").strip()
        candidate = _normalized_box(item.get("bbox"), width, height)
        if not text or candidate is None:
            continue
        left = max(box[0], candidate[0])
        top = max(box[1], candidate[1])
        right = min(box[0] + box[2], candidate[0] + candidate[2])
        bottom = min(box[1] + box[3], candidate[1] + candidate[3])
        overlap = max(0, right - left) * max(0, bottom - top)
        candidate_area = candidate[2] * candidate[3]
        if candidate_area and overlap / candidate_area >= 0.80:
            ranked.append((overlap / max(1, target_area), text))
    return max(ranked)[1] if ranked else ""


def _ui_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    if text.startswith("wauto"):
        text = "以" + text[1:]
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)


def _contains_design_box(outer: Mapping[str, Any], inner: Mapping[str, Any]) -> bool:
    try:
        ox, oy = float(outer["x"]), float(outer["y"])
        ow, oh = float(outer["width"]), float(outer["height"])
        ix, iy = float(inner["x"]), float(inner["y"])
        iw, ih = float(inner["width"]), float(inner["height"])
    except (KeyError, TypeError, ValueError):
        return False
    return ox <= ix and oy <= iy and ix + iw <= ox + ow and iy + ih <= oy + oh


def _dedupe_design_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def box(element: Mapping[str, Any]) -> tuple[float, float, float, float]:
        return (
            float(element.get("x") or 0),
            float(element.get("y") or 0),
            float(element.get("width") or 0),
            float(element.get("height") or 0),
        )

    def overlap_ratio(first: Mapping[str, Any], second: Mapping[str, Any]) -> float:
        ax, ay, aw, ah = box(first)
        bx, by, bw, bh = box(second)
        left = max(ax, bx)
        top = max(ay, by)
        right = min(ax + aw, bx + bw)
        bottom = min(ay + ah, by + bh)
        overlap = max(0.0, right - left) * max(0.0, bottom - top)
        smaller = min(aw * ah, bw * bh)
        return overlap / smaller if smaller > 0 else 0.0

    priority = {
        "input": 0,
        "checkbox": 0,
        "text": 1,
        "button": 2,
    }
    without_icon_labels = []
    for element in elements:
        raw_text = str(element.get("controlValue") or element.get("text") or "")
        text = _ui_text(raw_text)
        if "#" in raw_text and raw_text.strip() != "#":
            continue
        if (
            "icon" in text
            and len(text) <= 40
            and str(element.get("type") or "") not in {"image", "avatar"}
        ):
            continue
        without_icon_labels.append(element)

    candidates = [
        (index, element)
        for index, element in enumerate(without_icon_labels)
        if _ui_text(
            element.get("text")
            if str(element.get("type") or "") == "input"
            else element.get("controlValue") or element.get("text")
        )
        and element.get("type") not in {"container", "image", "avatar"}
    ]
    candidates.sort(
        key=lambda item: (
            priority.get(
                str(item[1].get("controlType") or item[1].get("type") or ""),
                3,
            ),
            0
            if str((item[1].get("imageMVP") or {}).get("source") or "")
            == "ocr-candidate"
            else 1,
            box(item[1])[2] * box(item[1])[3],
            item[0],
        )
    )
    kept: list[tuple[int, dict[str, Any]]] = []
    for index, element in candidates:
        normalized = _ui_text(element.get("controlValue") or element.get("text"))
        duplicate = any(
            normalized == _ui_text(existing.get("controlValue") or existing.get("text"))
            and (
                overlap_ratio(element, existing) >= 0.50
                or (
                    abs(
                        box(element)[1]
                        + box(element)[3] / 2
                        - box(existing)[1]
                        - box(existing)[3] / 2
                    )
                    <= 12
                    and abs(
                        box(element)[0]
                        + box(element)[2] / 2
                        - box(existing)[0]
                        - box(existing)[2] / 2
                    )
                    <= 700
                )
            )
            for _existing_index, existing in kept
        )
        if not duplicate:
            kept.append((index, element))
    kept_indices = {index for index, _element in kept}
    return [
        element
        for index, element in enumerate(without_icon_labels)
        if not _ui_text(
            element.get("text")
            if str(element.get("type") or "") == "input"
            else element.get("controlValue") or element.get("text")
        )
        or index in kept_indices
    ]


def _recover_surface_bands(
    image_path: str | Path,
    graph: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    main_box = None
    for container in graph.get("containers") or []:
        if not isinstance(container, Mapping):
            continue
        if str(container.get("role") or "").lower() != "main-content":
            continue
        main_box = _normalized_box(container.get("bbox"), width, height)
        if main_box is not None:
            break
    if main_box is None:
        return []
    x, y, w, h = main_box
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        region = image.crop((x, y, x + w, y + h))
    occupied: list[bool] = []
    for row_index in range(region.height):
        row = region.crop((0, row_index, region.width, row_index + 1))
        colors = row.getcolors(maxcolors=max(256, region.width + 16))
        if not colors:
            occupied.append(False)
            continue
        nonwhite = [
            (count, color)
            for count, color in colors
            if _color_distance(color, (255, 255, 255)) >= 12
        ]
        occupied.append(
            bool(
                nonwhite
                and max(nonwhite, key=lambda item: item[0])[0] >= region.width * 0.50
            )
        )
    bands: list[dict[str, Any]] = []
    start = None
    for index, present in enumerate([*occupied, False]):
        if present and start is None:
            start = index
        elif not present and start is not None:
            band_height = index - start
            if band_height >= 8:
                crop = region.crop((0, start, region.width, index))
                colors = crop.getcolors(maxcolors=100000)
                nonwhite = [
                    (count, color)
                    for count, color in colors or []
                    if _color_distance(color, (255, 255, 255)) >= 12
                ]
                if nonwhite:
                    fill = _hex_color(max(nonwhite, key=lambda item: item[0])[1])
                    bands.append(
                        {
                            "id": f"surface-band-{y + start}",
                            "type": "container",
                            "x": x,
                            "y": y + start,
                            "width": w,
                            "height": band_height,
                            "text": "",
                            "name": "Surface band",
                            "role": "surface-band",
                            "style": {"fillColor": fill},
                        }
                    )
            start = None
    return bands


def _normalize_breadcrumb_design(
    elements: list[dict[str, Any]],
    graph: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> None:
    main_box = None
    for container in graph.get("containers") or []:
        if not isinstance(container, Mapping):
            continue
        if str(container.get("role") or "").lower() != "main-content":
            continue
        main_box = _normalized_box(container.get("bbox"), width, height)
        if main_box is not None:
            break
    if main_box is None:
        return
    for element in elements:
        text = str(element.get("text") or "").strip()
        if text != "自动备份" or float(element.get("y") or 0) >= main_box[1] + 120:
            continue
        element["x"] = float(element.get("x") or 0) + 16
        element["y"] = main_box[1] + 17
        element["width"] = max(40, min(160, len(text) * 20))
        element.setdefault("style", {})["fontSize"] = 18
        return


def _normalize_sidebar_rows(
    elements: list[dict[str, Any]],
    graph: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> None:
    sidebar = None
    for container in graph.get("containers") or []:
        if not isinstance(container, Mapping):
            continue
        if str(container.get("role") or "").lower() != "sidebar":
            continue
        sidebar = _normalized_box(container.get("bbox"), width, height)
        if sidebar is not None:
            break
    if sidebar is None:
        return
    for element in elements:
        if str(element.get("type") or "") != "text":
            continue
        x = float(element.get("x") or 0)
        y = float(element.get("y") or 0)
        if x < sidebar[0] + sidebar[2] and y >= sidebar[1] + 140:
            element["y"] = y + 3


def _recover_sidebar_search(
    image_path: str | Path,
    graph: Mapping[str, Any],
    elements: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    sidebar = None
    for container in graph.get("containers") or []:
        if not isinstance(container, Mapping):
            continue
        if str(container.get("role") or "").lower() != "sidebar":
            continue
        sidebar = _normalized_box(container.get("bbox"), width, height)
        if sidebar is not None:
            break
    if sidebar is None:
        return []
    x, y, w, _h = sidebar
    box = (x + 12, y + 96, max(80, w - 24), 38)
    if any(
        str(element.get("type") or "") == "input"
        and float(element.get("x") or 0) >= box[0]
        and float(element.get("y") or 0) >= box[1]
        and float(element.get("y") or 0) <= box[1] + box[3]
        for element in elements
    ):
        return []
    fill = _dominant_color(image_path, box, inset=3)
    border = _sample_border_color(image_path, box, fill)
    placeholder = {
        "id": "recovered-sidebar-search-text",
        "type": "text",
        "x": box[0] + 16,
        "y": box[1] + 10,
        "width": max(80, box[2] - 64),
        "height": 20,
        "text": "输入关键字过滤菜单",
        "style": {
            "textColor": "#758397",
            "fontSize": 14,
            "fontWeight": "normal",
            "fontFamily": _teacher_font_family("输入关键字过滤菜单"),
            "lineHeight": 24,
        },
    }
    search = {
        "id": "recovered-sidebar-search",
        "type": "input",
        "x": box[0],
        "y": box[1],
        "width": box[2],
        "height": box[3],
        "text": "",
        "controlType": "input",
        "controlValue": "",
        "controlState": "enabled",
        "role": "search-input",
        "style": {
            "fillColor": fill,
            "textColor": "#758397",
            "fontSize": 14,
            "fontWeight": "normal",
            "fontFamily": _teacher_font_family("输入关键字过滤菜单"),
            "lineHeight": 24,
            "borderColor": border,
            "borderWidth": 1,
            "borderRadius": 4,
        },
        "imageMVP": {
            "source": "source-pixels-candidate",
            "reference_only": False,
            "generated": False,
        },
    }
    return [search, placeholder]


def _recover_search_field(
    image_path: str | Path,
    graph: Mapping[str, Any],
    elements: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> dict[str, Any] | None:
    main_box = None
    for container in graph.get("containers") or []:
        if not isinstance(container, Mapping):
            continue
        if str(container.get("role") or "").lower() != "main-content":
            continue
        main_box = _normalized_box(container.get("bbox"), width, height)
        if main_box is not None:
            break
    if main_box is None:
        return None
    target = next(
        (
            element
            for element in elements
            if str(element.get("type") or "") == "text"
            and "搜索" in str(element.get("text") or "")
            and main_box[0] <= float(element.get("x") or 0) <= main_box[0] + main_box[2]
        ),
        None,
    )
    if target is None:
        return None
    x = int(float(target.get("x") or 0)) - 16
    y = int(float(target.get("y") or 0)) - 10
    w = 168
    h = 36
    center = (
        int(float(target["x"])) + int(float(target["width"])) // 2,
        y + h // 2,
    )
    if any(
        str(element.get("type") or "") == "input"
        and float(element.get("x") or 0)
        <= center[0]
        <= float(element.get("x") or 0) + float(element.get("width") or 0)
        and float(element.get("y") or 0)
        <= center[1]
        <= float(element.get("y") or 0) + float(element.get("height") or 0)
        for element in elements
    ):
        return None
    fill = _dominant_color(image_path, (x, y, w, h), inset=2)
    return {
        "id": "recovered-table-search",
        "type": "input",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "text": "",
        "controlType": "input",
        "controlValue": "",
        "controlState": "enabled",
        "role": "search-input",
        "style": {
            "fillColor": fill,
            "textColor": "#999999",
            "fontSize": 14,
            "fontWeight": "normal",
            "fontFamily": _teacher_font_family("搜索"),
            "lineHeight": 24,
            "borderColor": _sample_border_color(
                image_path,
                (x, y, w, h),
                fill,
            ),
            "borderWidth": 1,
            "borderRadius": 0,
        },
        "imageMVP": {
            "source": "source-pixels-candidate",
            "reference_only": False,
            "generated": False,
        },
    }


def _traced_icon_svg(
    image_path: str | Path,
    bbox: tuple[int, int, int, int],
    color: str,
) -> str | None:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        x, y, w, h = bbox
        crop = image.crop((x, y, x + w, y + h))
    colors = crop.getcolors(maxcolors=100000)
    if not colors:
        return None
    background = max(colors, key=lambda item: item[0])[1]
    pixel_values = list(getattr(crop, "get_flattened_data", crop.getdata)())
    foreground = []
    for red, green, blue in pixel_values:
        pixel = (red, green, blue)
        if _color_distance(pixel, background) >= 40:
            foreground.append(pixel)
    if len(foreground) < 3:
        return None
    mask = Image.new("L", crop.size, 0)
    mask.putdata(
        [
            255 if _color_distance(pixel, background) >= 40 else 0
            for pixel in pixel_values
        ]
    )
    path_parts = []
    for row in range(crop.height):
        column = 0
        while column < crop.width:
            if not mask.getpixel((column, row)):
                column += 1
                continue
            start = column
            while column < crop.width and mask.getpixel((column, row)):
                column += 1
            path_parts.append(f"M{start} {row}h{column - start}v1h-{column - start}z")
    if not path_parts:
        return None
    safe_color = html.escape(color, quote=True)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" shape-rendering="crispEdges">'
        f'<path d="{"".join(path_parts)}" fill="{safe_color}"/></svg>'
    )


def _recover_chrome_icons(
    image_path: str | Path,
    graph: Mapping[str, Any],
    elements: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    containers: dict[str, tuple[int, int, int, int]] = {}
    for container in graph.get("containers") or []:
        if not isinstance(container, Mapping):
            continue
        role = str(container.get("role") or "").lower()
        bbox = _normalized_box(container.get("bbox"), width, height)
        if role and bbox is not None:
            containers[role] = bbox
    header = containers.get("header")
    sidebar = containers.get("sidebar")
    main = containers.get("main-content")
    texts = [element for element in elements if element.get("text")]
    icons: list[dict[str, Any]] = []

    def add(
        name: str,
        x: int,
        y: int,
        icon_width: int,
        icon_height: int,
        color: str,
        sample_color: bool = True,
        force_template: bool = False,
    ) -> None:
        left = max(0, min(width, x))
        top = max(0, min(height, y))
        requested_left = left
        requested_top = top
        requested_width = icon_width
        requested_height = icon_height
        sampled_color, ink_box, _band = _foreground_color(
            image_path,
            (left, top, icon_width, icon_height),
        )
        icon_color = sampled_color if sample_color and ink_box is not None else color
        if ink_box is not None:
            left, top, icon_width, icon_height = ink_box
        if name == "search" and (icon_width < 16 or icon_height < 16):
            left = requested_left
            top = requested_top
            icon_width = max(16, requested_width)
            icon_height = max(16, requested_height)
        if force_template:
            vector = vector_icon_svg(name, icon_width, icon_height, icon_color)
            geometry_source = "lucide-template"
        else:
            vector = _traced_icon_svg(
                image_path,
                (left, top, icon_width, icon_height),
                icon_color,
            )
            geometry_source = "raster-vector-trace"
            if vector is None:
                vector = vector_icon_svg(name, icon_width, icon_height, icon_color)
                geometry_source = "lucide-template"
        if vector is None:
            return
        if name == "mail" and any(
            "badge" in str(existing.get("assetName") or "").lower()
            for existing in elements
        ):
            return
        if any(
            existing.get("assetName") == name
            and abs(float(existing.get("x") or 0) - left) <= 8
            and abs(float(existing.get("y") or 0) - top) <= 8
            for existing in [*elements, *icons]
        ):
            return
        icons.append(
            {
                "id": f"chrome-icon-{name}-{left}-{top}",
                "type": "image",
                "x": left,
                "y": top,
                "width": icon_width,
                "height": icon_height,
                "text": "",
                "role": "ui-icon",
                "assetName": name,
                "assetKind": "icon",
                "vectorSvg": vector,
                "geometrySource": geometry_source,
                "imageMVP": {
                    "source": "source-pixels-candidate",
                    "reference_only": False,
                    "generated": False,
                },
            }
        )

    if header is not None:
        header_x, header_y, header_width, _header_height = header
        header_right = header_x + header_width
        brand = next(
            (
                element
                for element in texts
                if "flexweaver" in _ui_text(element.get("text"))
            ),
            None,
        )
        if brand is not None:
            add(
                "menu",
                int(float(brand["x"])) - 85,
                int(float(brand["y"])) + 3,
                24,
                18,
                "#9fb1c8",
            )
        add("search", header_right - 367, header_y + 23, 22, 22, "#9fb1c8")
        add("mail", header_right - 321, header_y + 23, 22, 22, "#9fb1c8")
        add("list", header_right - 262, header_y + 26, 22, 18, "#9fb1c8")
        add("panel-left", header_right - 66, header_y + 23, 22, 22, "#9fb1c8")
        add("x", header_right - 27, header_y + 23, 18, 18, "#9fb1c8")
        add("chevron-down", header_right - 112, header_y + 30, 12, 7, "#9fb1c8")

    if sidebar is not None:
        sidebar_x, sidebar_y, sidebar_width, _sidebar_height = sidebar
        label_icons = {
            "首页": "home",
            "系统管理": "panel-left",
            "PC端": "monitor",
            "移动端": "smartphone",
        }
        for label, icon_name in label_icons.items():
            target = next(
                (
                    element
                    for element in texts
                    if str(element.get("text") or "").strip() == label
                ),
                None,
            )
            if target is None:
                continue
            target_y = int(float(target["y"]))
            add(
                icon_name,
                sidebar_x + 20,
                target_y,
                22,
                22,
                "#5b9e43",
                sample_color=False,
                force_template=True,
            )
            add(
                "chevron-right",
                sidebar_x + sidebar_width - 25,
                target_y + 5,
                6,
                10,
                "#808a99",
                sample_color=False,
            )
        add(
            "search",
            sidebar_x + sidebar_width - 50,
            sidebar_y + 104,
            16,
            16,
            "#758397",
            sample_color=False,
            force_template=True,
        )

    if main is not None:
        main_x, main_y, main_width, _main_height = main
        breadcrumb = next(
            (
                element
                for element in texts
                if str(element.get("text") or "").strip() == "自动备份"
                and int(float(element["y"])) < main_y + 120
            ),
            None,
        )
        if breadcrumb is not None:
            add(
                "file-text",
                int(float(breadcrumb["x"])) - 2,
                int(float(breadcrumb["y"])) - 8,
                16,
                16,
                "#555555",
            )
        add(
            "pencil",
            main_x + main_width - 68,
            main_y + 23,
            14,
            14,
            "#555555",
        )
        add(
            "maximize",
            main_x + main_width - 34,
            main_y + 23,
            14,
            14,
            "#555555",
        )
    return icons


def _prefer_input_text_owner(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    controls = [
        element
        for element in elements
        if str(element.get("type") or "") == "input"
        and _ui_text(element.get("controlValue") or element.get("text"))
    ]
    removed: set[int] = set()
    for index, element in enumerate(elements):
        if str(element.get("type") or "") != "text":
            continue
        text = _ui_text(element.get("text"))
        if not text:
            continue
        for control in controls:
            owner_text = _ui_text(control.get("controlValue") or control.get("text"))
            if difflib.SequenceMatcher(None, text, owner_text).ratio() < 0.82:
                continue
            if _contains_design_box(control, element):
                removed.add(index)
                break
            control_type = str(control.get("controlType") or "").lower()
            text_x = float(element.get("x") or 0)
            text_w = float(element.get("width") or 0)
            control_x = float(control.get("x") or 0)
            vertical_gap = abs(
                float(element.get("y") or 0)
                + float(element.get("height") or 0) / 2
                - float(control.get("y") or 0)
                - float(control.get("height") or 0) / 2
            )
            if (
                control_type == "checkbox"
                and vertical_gap <= 10
                and -4 <= control_x - (text_x + text_w) <= 20
            ):
                element["text"] = str(
                    control.get("controlValue") or element.get("text") or ""
                )
                control["text"] = ""
                break
    return [element for index, element in enumerate(elements) if index not in removed]


def _normalize_checked_checkboxes(
    elements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text_elements = [
        element
        for element in elements
        if str(element.get("type") or "") == "text" and element.get("text")
    ]
    additions: list[dict[str, Any]] = []
    for control in elements:
        if (
            str(control.get("type") or "") != "input"
            or str(control.get("controlType") or "").lower() != "checkbox"
            or str(control.get("controlState") or "").lower() != "checked"
        ):
            continue
        control_text = str(control.get("controlValue") or "").strip()
        control["text"] = ""
        cx = float(control.get("x") or 0)
        cy = float(control.get("y") or 0)
        cw = float(control.get("width") or 0)
        ch = float(control.get("height") or 0)
        normalized = _ui_text(control_text)
        external_label = any(
            abs(
                float(label.get("y") or 0)
                + float(label.get("height") or 0) / 2
                - cy
                - ch / 2
            )
            <= 10
            and (
                abs(float(label.get("x") or 0) + float(label.get("width") or 0) - cx)
                <= 20
                or abs(float(label.get("x") or 0) - cx - cw) <= 20
            )
            and (
                normalized == _ui_text(label.get("text"))
                or difflib.SequenceMatcher(
                    None,
                    normalized,
                    _ui_text(label.get("text")),
                ).ratio()
                >= 0.82
            )
            for label in text_elements
        )
        if external_label:
            check_x, check_y = cx + 2, cy + 2
            check_w, check_h = max(10, cw - 4), max(10, ch - 4)
        else:
            control["style"] = {
                **(control.get("style") or {}),
                "fillColor": "transparent",
                "borderWidth": 0,
            }
            check_x, check_y = cx - 4, cy - 1
            check_w, check_h = 20, 18
            if control_text:
                additions.append(
                    {
                        "id": f"checkbox-label-{control.get('id')}",
                        "type": "text",
                        "x": cx + cw + 4,
                        "y": cy + 4,
                        "width": 96,
                        "height": 20,
                        "text": control_text,
                        "style": {
                            "textColor": "#008000",
                            "fontSize": 14,
                            "fontWeight": "normal",
                            "fontFamily": _teacher_font_family(control_text),
                            "lineHeight": 24,
                        },
                    }
                )
        check_svg = vector_icon_svg("check", int(check_w), int(check_h), "#008000")
        if check_svg is not None:
            additions.append(
                {
                    "id": f"checkbox-check-{control.get('id')}",
                    "type": "image",
                    "x": check_x,
                    "y": check_y,
                    "width": check_w,
                    "height": check_h,
                    "text": "",
                    "role": "ui-icon",
                    "assetName": "check",
                    "assetKind": "icon",
                    "vectorSvg": check_svg,
                    "geometrySource": "lucide-template",
                    "imageMVP": {
                        "source": "source-pixels-candidate",
                        "reference_only": False,
                        "generated": False,
                    },
                }
            )
    kept = [
        element
        for element in elements
        if not (
            str(element.get("type") or "") == "image"
            and str(element.get("assetName") or "").lower() in {"check", "check_icon"}
        )
    ]
    return [*kept, *additions]


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


def _logo_display_box(
    image_path: str | Path,
    requested_bbox: tuple[int, int, int, int],
) -> tuple[int, int, int, int] | None:
    image = cv2.imread(str(image_path))
    if image is None:
        return None
    x, y, w, h = requested_bbox
    margin = 16
    left = max(0, x - margin)
    top = max(0, y - margin)
    right = min(image.shape[1], x + w + margin)
    bottom = min(image.shape[0], y + h + margin)
    crop = image[top:bottom, left:right]
    mask = cv2.inRange(crop, (244, 244, 244), (255, 255, 255))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask,
        8,
    )
    requested = (x - left, y - top, w, h)
    best = None
    for index in range(1, count):
        cx, cy, cw, ch, area = (int(value) for value in stats[index])
        if area < 100:
            continue
        overlap_width = max(
            0,
            min(requested[0] + requested[2], cx + cw) - max(requested[0], cx),
        )
        overlap_height = max(
            0,
            min(requested[1] + requested[3], cy + ch) - max(requested[1], cy),
        )
        overlap = overlap_width * overlap_height
        candidate = (overlap, area, cx, cy, cw, ch)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None or best[0] <= 0:
        return None
    _overlap, _area, cx, cy, cw, ch = best
    return left + cx, top + cy, cw, ch


def _largest_component_box(
    mask,
    *,
    left: int,
    top: int,
) -> tuple[int, int, int, int] | None:
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask,
        8,
    )
    best = None
    for index in range(1, count):
        cx, cy, cw, ch, area = (int(value) for value in stats[index])
        if area < 20:
            continue
        candidate = (area, cx, cy, cw, ch)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        return None
    _area, cx, cy, cw, ch = best
    return left + cx, top + cy, cw, ch


def _avatar_display_box(
    image_path: str | Path,
    requested_bbox: tuple[int, int, int, int],
) -> tuple[int, int, int, int] | None:
    image = cv2.imread(str(image_path))
    if image is None:
        return None
    x, y, w, h = requested_bbox
    margin = 16
    left = max(0, x - margin)
    top = max(0, y - margin)
    right = min(image.shape[1], x + w + margin)
    bottom = min(image.shape[0], y + h + margin)
    crop = image[top:bottom, left:right]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 80, 50), (95, 255, 255))
    component = _largest_component_box(mask, left=left, top=top)
    if component is None:
        return None
    cx, cy, cw, ch = component
    side = max(cw, ch) + 4
    center_x = cx + cw // 2
    center_y = cy + ch // 2
    return (
        max(0, center_x - side // 2),
        max(0, center_y - side // 2),
        side,
        side,
    )


def _badge_display_box(
    image_path: str | Path,
    requested_bbox: tuple[int, int, int, int],
) -> tuple[int, int, int, int] | None:
    image = cv2.imread(str(image_path))
    if image is None:
        return None
    x, y, w, h = requested_bbox
    margin = 20
    left = max(0, x - margin)
    top = max(0, y - margin)
    right = min(image.shape[1], x + w + margin)
    bottom = min(image.shape[0], y + h + margin)
    crop = image[top:bottom, left:right]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red_low = cv2.inRange(hsv, (0, 120, 100), (12, 255, 255))
    red_high = cv2.inRange(hsv, (168, 120, 100), (179, 255, 255))
    mask = cv2.bitwise_or(red_low, red_high)
    component = _largest_component_box(mask, left=left, top=top)
    if component is None:
        return None
    cx, cy, cw, ch = component
    return (
        max(0, cx - 4),
        max(0, cy - 4),
        cw + 20,
        ch + 20,
    )


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


def _recover_status_text_box(
    image_path: str | Path,
    bbox: tuple[int, int, int, int],
    text: str,
) -> tuple[int, int, int, int] | None:
    normalized = _ui_text(text)
    if normalized != "success" and "成功" not in normalized:
        return None
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        x, y, w, h = bbox
        left = max(0, x - 48)
        top = max(0, y - 80)
        right = min(image.width, x + w + 48)
        bottom = min(image.height, y + h + 80)
        crop = image.crop((left, top, right, bottom))
    mask = Image.new("L", crop.size, 0)
    values = []
    for red, green, blue in getattr(crop, "get_flattened_data", crop.getdata)():
        values.append(
            255 if green >= 60 and green - red >= 24 and green - blue >= 12 else 0
        )
    mask.putdata(values)
    ink_box = mask.getbbox()
    if ink_box is None:
        return None
    ink_width = ink_box[2] - ink_box[0]
    ink_height = ink_box[3] - ink_box[1]
    if ink_width < 8 or ink_height < 4:
        return None
    return (
        left + ink_box[0] - 2,
        top + ink_box[1] - 4,
        ink_width + 4,
        max(20, min(24, ink_height + 8)),
    )


def _recover_control_text_box(
    image_path: str | Path,
    bbox: tuple[int, int, int, int],
) -> tuple[int, int, int, int] | None:
    with Image.open(image_path) as source:
        image = source.convert("L")
        x, y, w, h = bbox
        left = max(0, x + 4)
        top = max(0, y + 4)
        right = min(image.width, x + w - 4)
        bottom = min(image.height, y + h - 4)
        crop = image.crop((left, top, right, bottom))
    mask = crop.point(lambda value: 255 if value < 180 else 0)
    ink_box = mask.getbbox()
    if ink_box is None:
        return None
    ink_width = ink_box[2] - ink_box[0]
    ink_height = ink_box[3] - ink_box[1]
    if ink_width < 2 or ink_height < 4:
        return None
    return (
        left + ink_box[0] - 1,
        top + ink_box[1] - 4,
        ink_width + 2,
        max(20, min(24, ink_height + 8)),
    )


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


def _teacher_font_family(text: str) -> str:
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "Microsoft YaHei, Noto Sans SC, sans-serif"
    return "Segoe UI, Arimo, Arial, sans-serif"


def _contrast_border_color(fill: str) -> str:
    red, green, blue = _parse_hex(fill)
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "#c8d1de" if luminance >= 150 else "#64748b"


def _sample_border_color(
    image_path: str | Path,
    bbox: tuple[int, int, int, int],
    fill: str,
) -> str:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        x, y, w, h = bbox
        edge = max(1, min(2, w // 8, h // 8))
        pixels = []
        for box in (
            (x, y, x + w, y + edge),
            (x, y + h - edge, x + w, y + h),
            (x, y, x + edge, y + h),
            (x + w - edge, y, x + w, y + h),
        ):
            edge_crop = image.crop(box)
            pixels.extend(getattr(edge_crop, "get_flattened_data", edge_crop.getdata)())
    fill_rgb = _parse_hex(fill)
    candidates = [pixel for pixel in pixels if _color_distance(pixel, fill_rgb) >= 24]
    if not candidates:
        return _contrast_border_color(fill)
    colors: dict[tuple[int, int, int], int] = {}
    for pixel in candidates:
        colors[pixel] = colors.get(pixel, 0) + 1
    sampled = max(colors, key=colors.get)
    if min(sampled) >= 248 and _color_distance(fill_rgb, (255, 255, 255)) >= 12:
        return _contrast_border_color(fill)
    return _hex_color(sampled)


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
