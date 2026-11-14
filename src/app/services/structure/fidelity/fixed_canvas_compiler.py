"""Compile one fixed-canvas ScenePlan into a DesignSpec."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
from collections.abc import Mapping
from typing import Any

from src.app.services.som.design_crops import crop_image_b64
from src.app.services.structure.asset_fusion import fuse_asset_record
from src.app.services.structure.asset_metadata import (
    attach_display_payload,
    build_asset_record,
)
from src.app.services.structure.fidelity.container_manifest import (
    build_container_manifest,
)
from src.app.services.structure.fidelity.contracts import normalize_bbox
from src.app.services.structure.fidelity.style_resolver import resolve_text_style


def _node_bbox(node: Mapping[str, Any], width: int, height: int) -> list[int]:
    bbox = normalize_bbox(node.get("bbox"), width, height)
    if bbox is None:
        raise ValueError(f"scene node {node.get('id')} bbox is invalid")
    return bbox


def _parent_bbox(
    node: Mapping[str, Any],
    node_by_id: Mapping[str, Mapping[str, Any]],
    width: int,
    height: int,
) -> list[int] | None:
    parent = node_by_id.get(str(node.get("parent_id") or ""))
    return (
        normalize_bbox(parent.get("bbox"), width, height)
        if isinstance(parent, Mapping)
        else None
    )


def _text_role(node: Mapping[str, Any]) -> str:
    content_ref = str(node.get("content_ref") or "")
    if content_ref.startswith("table-header:"):
        return "table-header"
    return str(node.get("role") or "")


def _control_text_bbox(bbox: list[int]) -> list[int]:
    x, y, box_width, box_height = bbox
    inset_x = min(12, max(1, box_width // 4))
    line_height = min(20, max(12, box_height - 4))
    return [
        x + inset_x,
        y + max(0, (box_height - line_height) // 2),
        max(1, box_width - inset_x * 2),
        line_height,
    ]


def _refine_textarea_text_bbox(
    image_path: str,
    control_bbox: list[int],
    text: str,
) -> list[int] | None:
    """Recover textarea ink when a provider text box misses the visible glyphs."""
    if not text:
        return None
    import numpy as np
    from PIL import Image

    x, y, box_width, box_height = control_bbox
    pad_x = max(4, min(12, box_width // 20))
    pad_y = max(3, min(8, box_height // 10))
    left = x + pad_x
    top = y + pad_y
    right = min(
        x + box_width - pad_x,
        left + max(80, len(text) * 32 + 32),
    )
    bottom = min(
        y + box_height - pad_y,
        top + max(24, min(48, box_height - pad_y * 2)),
    )
    if right <= left or bottom <= top:
        return None
    with Image.open(image_path) as source:
        image = np.asarray(source.convert("RGB"), dtype=np.int16)
    crop = image[top:bottom, left:right]
    if crop.size == 0:
        return None
    background = np.median(crop.reshape(-1, 3), axis=0)
    mask = np.max(np.abs(crop - background.reshape(1, 1, 3)), axis=2) > 24
    # Borders and textarea resize rails are long, near-solid rows/columns.
    mask[mask.sum(axis=1) >= max(4, int(round(mask.shape[1] * 0.75))), :] = False
    mask[:, mask.sum(axis=0) >= max(4, int(round(mask.shape[0] * 0.75)))] = False
    if int(mask.sum()) < 2:
        return None
    ys, xs = np.where(mask)
    return [
        left + int(xs.min()),
        top + int(ys.min()),
        int(xs.max() - xs.min() + 1),
        int(ys.max() - ys.min() + 1),
    ]


def _text_element(
    node: Mapping[str, Any],
    *,
    image_path: str,
    width: int,
    height: int,
    node_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    bbox = _node_bbox(node, width, height)
    x, y, box_width, box_height = bbox
    text = str(node.get("text") or "")
    role = _text_role(node)
    is_table_text = role in {"table-cell", "table-header"}
    text_bbox = normalize_bbox(node.get("text_bbox"), width, height)
    style_bbox = text_bbox or bbox
    style = resolve_text_style(
        image_path,
        text,
        style_bbox,
        parent_bbox=(
            bbox if is_table_text else _parent_bbox(node, node_by_id, width, height)
        ),
        role=role,
    )
    render_x = x
    render_y = y
    render_width = box_width
    render_height = box_height
    if role == "table-header":
        style["textAlign"] = "center"
    elif not is_table_text:
        style["textAlign"] = "left"
    if is_table_text:
        if text_bbox is not None:
            text_x, text_y, text_width, text_height = text_bbox
            render_y = text_y
            render_height = max(18, text_height)
            if role == "table-header":
                render_width = box_width
            else:
                style["textAlign"] = "left"
                render_x = text_x
                render_width = max(1, text_width)
        else:
            ink_bbox = style["evidence"].get("ink_bbox")
            normalized_ink = normalize_bbox(ink_bbox, width, height)
            if normalized_ink is not None:
                ink_x, ink_y, ink_width, ink_height = normalized_ink
                render_y = ink_y
                render_height = max(18, ink_height + 4)
                if style["textAlign"] in {"center", "right"}:
                    render_width = box_width
                else:
                    render_x = ink_x
                    render_width = max(1, x + box_width - ink_x)
    if role == "control-label" and box_width <= 32:
        render_x = x + box_width + 4
        render_width = min(
            max(0, width - render_x),
            max(120, len(text) * 16),
        )
        render_y = y + max(0, (box_height - 20) // 2)
        render_height = max(18, min(24, box_height))
    style_payload = {
        "textColor": style["textColor"],
        "fontSize": style["fontSize"],
        "fontWeight": style["fontWeight"],
        "fontFamily": style["fontFamily"],
        "textAlign": style["textAlign"],
    }
    # Only multi-line owners carry a measured line height; single-line text
    # keeps the renderer's default rhythm (the adapter strips it anyway).
    if style.get("lineHeight"):
        style_payload["lineHeight"] = style["lineHeight"]
    return {
        "id": str(node.get("id") or ""),
        "type": "text",
        "x": render_x,
        "y": render_y,
        "width": render_width,
        "height": render_height,
        "text": text,
        "style": style_payload,
        "styleEvidence": style,
        "contentRef": str(node.get("content_ref") or ""),
        "sceneOwnerId": str(node.get("id") or ""),
        "imageMVP": {
            "source": "scene-plan",
            "role": role,
            "candidate_type": "text",
            "grouping_status": "planned",
            "reference_only": False,
            "generated": False,
            "textStatus": "scene-plan-owner",
        },
    }


def _control_element(
    node: Mapping[str, Any],
    *,
    image_path: str,
    width: int,
    height: int,
    node_by_id: Mapping[str, Mapping[str, Any]],
    index: int,
    group_fill: str | None = None,
) -> dict[str, Any]:
    from src.app.services.structure.image_contract import (
        _dominant_color,
        _sample_border_color,
    )

    bbox = _node_bbox(node, width, height)
    x, y, box_width, box_height = bbox
    control_type = str(node.get("control_type") or "button").lower()
    text_bbox = normalize_bbox(node.get("text_bbox"), width, height)
    text = "" if node.get("text_owner_ref") else str(node.get("text") or "")
    if control_type == "textarea":
        refined_text_bbox = _refine_textarea_text_bbox(
            image_path,
            bbox,
            text,
        )
        if refined_text_bbox is not None:
            text_bbox = refined_text_bbox
    style_bbox = text_bbox or (
        _control_text_bbox(bbox) if text and box_width > 24 else bbox
    )
    element_type = (
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
        or (box_width >= 180 and 28 <= box_height <= 60)
        else "button"
    )
    if element_type == "input" and control_type in {"button", "icon-button"}:
        control_type = "input"
    style = resolve_text_style(
        image_path,
        text,
        style_bbox,
        parent_bbox=bbox,
        role="control",
    )
    fill = _dominant_color(image_path, bbox, inset=2)
    if group_fill is not None:
        fill = group_fill
    style_spec = {
        "fillColor": fill,
        "borderColor": (
            _sample_border_color(image_path, bbox, fill) if group_fill is None else fill
        ),
        "borderWidth": 0 if group_fill is not None else 1,
        "textColor": style["textColor"],
        "fontSize": style["fontSize"],
        "fontWeight": "normal",
        "fontFamily": style["fontFamily"],
        "textAlign": "left",
        "borderRadius": (
            0
            if group_fill is not None
            else 6
            if box_width >= 24 and box_height >= 20
            else 0
        ),
    }
    element = {
        "id": str(node.get("id") or f"control-{index}"),
        "type": element_type,
        "x": x,
        "y": y,
        "width": box_width,
        "height": box_height,
        "text": text,
        "style": style_spec,
        "styleEvidence": style,
        "controlType": control_type,
        "controlValue": text,
        "controlState": str(node.get("state") or "enabled"),
        "contentRef": str(node.get("content_ref") or ""),
        "sceneOwnerId": str(node.get("id") or ""),
        "imageMVP": {
            "source": "scene-plan",
            "role": str(node.get("role") or "control"),
            "candidate_type": control_type,
            "grouping_status": (
                "grouped-control" if group_fill is not None else "planned"
            ),
            "reference_only": False,
            "generated": False,
            "textStatus": "scene-plan-owner",
        },
    }
    if element_type == "input" and text:
        element["textBox"] = (
            list(text_bbox) if text_bbox is not None else list(style_bbox)
        )
    return element


def _image_element(
    node: Mapping[str, Any],
    *,
    image_path: str,
    width: int,
    height: int,
    sample_id: str,
    reference: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    bbox = _node_bbox(node, width, height)
    x, y, box_width, box_height = bbox
    payload = crop_image_b64(
        image_path,
        x,
        y,
        box_width,
        box_height,
        width,
        height,
    )
    digest = hashlib.sha256(base64.b64decode(payload)).hexdigest() if payload else None
    screenshot_sha = str(reference["input"]["sha256"])
    record = build_asset_record(
        sample_id=f"{sample_id}-scene",
        node_index=index,
        source_kind="screenshot-crop",
        source=None,
        natural_size=(box_width, box_height),
        display_box=(x, y, box_width, box_height),
        display_payload_sha256=digest,
        screenshot_sha256=screenshot_sha,
        source_rect=(x, y, box_width, box_height),
    )
    if payload:
        record = attach_display_payload(
            record,
            payload_sha256=digest,
            screenshot_sha256=screenshot_sha,
            display_box=(x, y, box_width, box_height),
        )
    return {
        "id": str(node.get("id") or f"image-{index}"),
        "type": "image",
        "x": x,
        "y": y,
        "width": box_width,
        "height": box_height,
        "text": "",
        "style": {},
        "imageBase64": payload,
        "assetIdentity": {"asset_record": record},
        "displayPayload": copy.deepcopy(record["display_payload"]),
        "replacement": copy.deepcopy(record["replacement"]),
        "sourceResolution": fuse_asset_record(record),
        "assetName": str(node.get("role") or node.get("id") or "image"),
        "assetKind": str(node.get("role") or "image"),
        "contentRef": str(node.get("content_ref") or ""),
        "sceneOwnerId": str(node.get("id") or ""),
        "imageMVP": {
            "source": "source-pixels",
            "role": str(node.get("role") or "image"),
            "grouping_status": "planned",
            "reference_only": True,
            "originalAssetClaimed": False,
            "generated": False,
        },
    }


def _source_chrome_right_rail(
    image_path: str,
    nodes: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> dict[str, Any] | None:
    import numpy as np
    from PIL import Image

    with Image.open(image_path) as source:
        image = np.asarray(source.convert("RGB"), dtype=np.int16)
    if image.shape[:2] != (height, width):
        return None
    for start in range(max(0, width - 32), max(0, width - 7)):
        fractions = [
            float((np.max(image[:, start + index], axis=1) < 250).mean())
            for index in range(min(4, width - start))
        ]
        if not fractions or min(fractions) < 0.75:
            continue
        left_start = max(0, start - 4)
        left_fraction = float((np.max(image[:, left_start:start], axis=2) < 250).mean())
        edge_delta = float(
            np.abs(
                image[:, start].mean(axis=1)
                - image[:, left_start:start].mean(axis=2).mean(axis=1)
            ).mean()
        )
        if left_fraction >= 0.5 or edge_delta < 12:
            continue
        if any(
            str(node.get("type") or "") == "text"
            and isinstance(node.get("bbox"), list)
            and len(node["bbox"]) == 4
            and int(node["bbox"][0]) + int(node["bbox"][2]) > start
            for node in nodes
        ):
            continue
        rail_width = width - start
        image_base64 = crop_image_b64(
            image_path,
            start,
            0,
            rail_width,
            height,
            width,
            height,
        )
        if not image_base64:
            return None
        return {
            "id": "source-chrome-right-rail",
            "type": "image",
            "role": "source-chrome",
            "name": "source-chrome-right-rail",
            "x": start,
            "y": 0,
            "width": rail_width,
            "height": height,
            "text": "",
            "controlValue": "",
            "contentRef": None,
            "imageBase64": image_base64,
            "paintDepth": 10000,
            "maskEvidence": {
                "schema_version": "source-chrome-text-mask/1.0",
                "maskSource": "not-applicable",
                "haloPx": 0,
                "excludedContentRefs": [],
                "excludedRectangles": [],
                "maskedRectangleCount": 0,
                "residualTextProbe": {
                    "status": "not-applicable-no-text-owner-overlap",
                    "maskedRectanglesChecked": 0,
                },
            },
            "imageMVP": {
                "source": "source-pixels",
                "role": "source-chrome",
                "reference_only": True,
                "original": False,
                "generated": False,
            },
        }
    return None


def _source_form_background(
    image_path: str,
    elements: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> dict[str, Any] | None:
    from PIL import Image, ImageDraw

    form = next(
        (
            element
            for element in elements
            if str(element.get("role") or "") == "form-section"
        ),
        None,
    )
    if form is None:
        return None
    table = next(
        (
            element
            for element in elements
            if str(element.get("role") or "") == "table-section"
        ),
        None,
    )
    if table is None:
        return None
    x = int(float(form.get("x") or 0))
    y = int(float(form.get("y") or 0))
    box_width = int(float(form.get("width") or 0))
    bottom = min(height, int(float(table.get("y") or height)))
    box_height = bottom - y
    if box_width <= 0 or box_height <= 0:
        return None
    toolbar_top = next(
        (
            int(float(element.get("y") or bottom))
            for element in elements
            if str(element.get("role") or "") == "table-header-controls"
        ),
        bottom,
    )
    with Image.open(image_path) as source:
        source_image = source.convert("RGB")
    image = source_image.copy()
    draw = ImageDraw.Draw(image)
    halo_px = 2
    excluded_rectangles: list[list[int]] = []
    excluded_refs: list[str] = []
    for element in elements:
        evidence = element.get("styleEvidence")
        values = evidence.get("evidence") if isinstance(evidence, Mapping) else None
        ink = values.get("ink_bbox") if isinstance(values, Mapping) else None
        if not isinstance(ink, list) or len(ink) != 4:
            continue
        ink_x, ink_y, ink_width, ink_height = (int(value) for value in ink)
        if not (y <= ink_y < bottom and x <= ink_x < x + box_width):
            continue
        fallback_background = str(values.get("background") or "#ffffff")
        if not fallback_background.startswith("#"):
            fallback_background = "#ffffff"
        background = _local_text_background(
            source_image,
            [ink_x, ink_y, ink_width, ink_height],
            fallback_background,
        )
        mask_left = max(0, ink_x - halo_px)
        mask_top = max(0, ink_y - halo_px)
        mask_right = min(width - 1, ink_x + ink_width + halo_px - 1)
        mask_bottom = min(height - 1, ink_y + ink_height + halo_px - 1)
        draw.rectangle(
            (
                mask_left,
                mask_top,
                mask_right,
                mask_bottom,
            ),
            fill=background,
        )
        excluded_rectangles.append(
            [
                mask_left,
                mask_top,
                mask_right - mask_left + 1,
                mask_bottom - mask_top + 1,
            ]
        )
        if element.get("contentRef"):
            excluded_refs.append(str(element["contentRef"]))
    for element in elements:
        if str(element.get("type") or "") not in {"button", "input"}:
            continue
        center_x = float(element.get("x") or 0) + float(element.get("width") or 0) / 2
        center_y = float(element.get("y") or 0) + float(element.get("height") or 0) / 2
        if x <= center_x <= x + box_width and y <= center_y < toolbar_top:
            element["sourceChromeCovered"] = True
    crop = image.crop((x, y, x + box_width, y + box_height))
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {
        "id": "source-chrome-form-background",
        "type": "image",
        "role": "source-chrome",
        "name": "source-chrome-form-background",
        "x": x,
        "y": y,
        "width": box_width,
        "height": box_height,
        "text": "",
        "controlValue": "",
        "contentRef": None,
        "imageBase64": payload,
        "paintDepth": 1,
        "maskEvidence": {
            "schema_version": "source-chrome-text-mask/1.0",
            "maskSource": "reference-styleEvidence.ink_bbox",
            "haloPx": halo_px,
            "excludedContentRefs": sorted(set(excluded_refs)),
            "excludedRectangles": excluded_rectangles,
            "maskedRectangleCount": len(excluded_rectangles),
            "residualTextProbe": {
                "status": "masked-uniform-fill",
                "maskedRectanglesChecked": len(excluded_rectangles),
            },
        },
        "imageMVP": {
            "source": "source-pixels",
            "role": "source-chrome",
            "reference_only": True,
            "original": False,
            "generated": False,
        },
    }


def _local_text_background(
    image: Any,
    ink_bbox: list[int],
    fallback: str,
) -> str:
    """Sample the immediate glyph surround instead of trusting a tight bbox edge."""
    import numpy as np

    x, y, box_width, box_height = ink_bbox
    ring = 3
    left = max(0, x - ring)
    top = max(0, y - ring)
    right = min(image.width, x + box_width + ring)
    bottom = min(image.height, y + box_height + ring)
    if right <= left or bottom <= top:
        return fallback
    pixels = np.asarray(image.crop((left, top, right, bottom)), dtype=np.int16)
    inner_left = max(0, x - left)
    inner_top = max(0, y - top)
    inner_right = min(pixels.shape[1], inner_left + box_width)
    inner_bottom = min(pixels.shape[0], inner_top + box_height)
    mask = np.ones(pixels.shape[:2], dtype=bool)
    mask[inner_top:inner_bottom, inner_left:inner_right] = False
    ring_pixels = pixels[mask]
    if ring_pixels.size == 0:
        return fallback
    red, green, blue = np.median(ring_pixels, axis=0)
    return f"#{int(round(red)):02x}{int(round(green)):02x}{int(round(blue)):02x}"


def _icon_control_element(
    node: Mapping[str, Any],
    *,
    image_path: str,
    width: int,
    height: int,
    sample_id: str,
    reference: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    element = _image_element(
        node,
        image_path=image_path,
        width=width,
        height=height,
        sample_id=sample_id,
        reference=reference,
        index=index,
    )
    control_type = str(node.get("control_type") or "icon-button").lower()
    element.update(
        {
            "text": "",
            "controlType": control_type,
            "controlValue": str(node.get("text") or ""),
            "controlState": str(node.get("state") or "enabled"),
        }
    )
    element["imageMVP"].update(
        {
            "candidate_type": control_type,
            "role": control_type,
            "textStatus": "reference-only-control",
        }
    )
    return element


def _container_render_box(
    image_path: str,
    bbox: list[int],
    role: str,
) -> list[int]:
    if role != "header":
        return bbox

    import numpy as np
    from PIL import Image

    x, y, box_width, box_height = bbox
    with Image.open(image_path) as source:
        image = np.asarray(source.convert("RGB"), dtype=np.int16)
    if y + box_height > image.shape[0] or x + box_width > image.shape[1]:
        return bbox
    trim = 0
    for row in range(y + box_height - 1, y, -1):
        pixels = image[row, x : x + box_width]
        if float(pixels.mean()) < 220 or float(pixels.std()) > 20:
            break
        trim += 1
        if trim >= 8:
            break
    if trim < 2 or trim >= box_height:
        return bbox
    return [x, y, box_width, box_height - trim]


def _is_source_pixel_control(node: Mapping[str, Any]) -> bool:
    control_type = str(node.get("control_type") or "").lower()
    bbox = node.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False
    try:
        box_width, box_height = (int(value) for value in bbox[2:4])
    except (TypeError, ValueError):
        return False
    small_control = (
        control_type == "icon-button"
        and box_width <= 64
        and box_height <= 64
        and len(str(node.get("text") or "").strip()) <= 2
    )
    checked_control = control_type in {"checkbox", "radio"} and str(
        node.get("state") or ""
    ).lower() in {"checked", "mixed"}
    return small_control or checked_control


def _hex_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    if len(text) != 6:
        return (0, 0, 0)
    try:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


def _same_fill(left: str, right: str, tolerance: int = 20) -> bool:
    left_rgb = _hex_rgb(left)
    right_rgb = _hex_rgb(right)
    return (
        max(abs(left_rgb[index] - right_rgb[index]) for index in range(3)) <= tolerance
    )


def _button_groups(
    nodes: list[dict[str, Any]],
    *,
    image_path: str,
    width: int,
    height: int,
) -> tuple[
    dict[str, str],
    dict[str, str],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    from src.app.services.structure.image_contract import (
        _dominant_color,
        _sample_border_color,
    )

    candidates: list[tuple[dict[str, Any], list[int], str]] = []
    for node in nodes:
        if node.get("type") != "control":
            continue
        if str(node.get("control_type") or "").lower() != "button":
            continue
        if _is_source_pixel_control(node):
            continue
        try:
            bbox = _node_bbox(node, width, height)
        except ValueError:
            continue
        candidates.append(
            (
                node,
                bbox,
                _dominant_color(image_path, bbox, inset=2),
            )
        )
    candidates.sort(key=lambda item: (item[1][1], item[1][0]))
    rows: list[list[tuple[dict[str, Any], list[int], str]]] = []
    for candidate in candidates:
        row = next(
            (
                existing
                for existing in rows
                if abs(existing[0][1][1] - candidate[1][1]) <= 2
            ),
            None,
        )
        if row is None:
            rows.append([candidate])
        else:
            row.append(candidate)
    ordered_candidates = [
        candidate
        for row in sorted(rows, key=lambda items: min(item[1][1] for item in items))
        for candidate in sorted(row, key=lambda item: item[1][0])
    ]

    runs: list[list[tuple[dict[str, Any], list[int], str]]] = []
    for candidate in ordered_candidates:
        if not runs:
            runs.append([candidate])
            continue
        previous = runs[-1][-1]
        previous_bbox = previous[1]
        bbox = candidate[1]
        previous_right = previous_bbox[0] + previous_bbox[2]
        gap = bbox[0] - previous_right
        same_row = (
            abs(previous_bbox[1] - bbox[1]) <= 2
            and abs(previous_bbox[3] - bbox[3]) <= 2
        )
        if same_row and -2 <= gap <= 2 and _same_fill(previous[2], candidate[2]):
            runs[-1].append(candidate)
        else:
            runs.append([candidate])

    grouped: dict[str, str] = {}
    grouped_fill: dict[str, str] = {}
    group_elements: list[dict[str, Any]] = []
    group_decorations: list[dict[str, Any]] = []
    for run in runs:
        if len(run) < 2:
            continue
        boxes = [item[1] for item in run]
        left = min(box[0] for box in boxes)
        top = min(box[1] for box in boxes)
        right = max(box[0] + box[2] for box in boxes)
        bottom = max(box[1] + box[3] for box in boxes)
        group_id = f"control-group:{run[0][0].get('id')}"
        fill = run[0][2]
        border = _sample_border_color(
            image_path,
            [left, top, right - left, bottom - top],
            fill,
        )
        for node, _bbox, _fill in run:
            node_id = str(node.get("id") or "")
            grouped[node_id] = group_id
            grouped_fill[node_id] = fill
        group_elements.append(
            {
                "id": group_id,
                "type": "container",
                "x": left,
                "y": top,
                "width": right - left,
                "height": bottom - top,
                "text": "",
                "style": {
                    "fillColor": fill,
                    "borderColor": border,
                    "borderWidth": 0,
                    "borderRadius": 6,
                },
                "role": "control-group",
                "name": "control-group",
                "contentRef": None,
                "sceneOwnerId": group_id,
                "imageMVP": {
                    "source": "scene-plan",
                    "role": "control-group",
                    "grouping_status": "shared-border",
                },
            }
        )
        group_decorations.append(
            {
                "id": f"control-group-outline:{run[0][0].get('id')}",
                "type": "rectangle",
                "x": left,
                "y": top,
                "width": right - left,
                "height": bottom - top,
                "text": "",
                "style": {
                    "fillColor": "transparent",
                    "borderColor": border,
                    "borderWidth": 1,
                    "borderRadius": 6,
                },
                "role": "control-group-outline",
                "name": "control-group-outline",
                "contentRef": None,
                "sceneOwnerId": group_id,
            }
        )
        for index in range(1, len(run)):
            group_decorations.append(
                {
                    "id": f"control-group-separator:{run[0][0].get('id')}:{index}",
                    "type": "rectangle",
                    "x": max(left, run[index][1][0] - 1),
                    "y": top + 1,
                    "width": 1,
                    "height": max(1, bottom - top - 2),
                    "text": "",
                    "style": {"fillColor": border},
                    "role": "control-group-separator",
                    "name": "control-group-separator",
                    "contentRef": None,
                    "sceneOwnerId": group_id,
                }
            )
    return grouped, grouped_fill, group_elements, group_decorations


def _apply_group_decoration_depths(
    elements: list[dict[str, Any]],
    groups: list[dict[str, Any]],
) -> None:
    rects: list[tuple[int, int, int, int] | None] = []
    for element in elements:
        try:
            x = int(element.get("x", 0))
            y = int(element.get("y", 0))
            width = int(element.get("width", 0))
            height = int(element.get("height", 0))
        except (TypeError, ValueError):
            rects.append(None)
            continue
        rects.append((x, y, width, height) if width > 0 and height > 0 else None)

    unique: list[tuple[int, int, int, int]] = []
    for rect in rects:
        if rect is not None and rect not in unique:
            unique.append(rect)

    def covers(
        outer: tuple[int, int, int, int],
        inner: tuple[int, int, int, int],
        eps: int = 1,
    ) -> bool:
        return (
            outer[0] <= inner[0] + eps
            and outer[1] <= inner[1] + eps
            and inner[0] + inner[2] <= outer[0] + outer[2] + eps
            and inner[1] + inner[3] <= outer[1] + outer[3] + eps
        )

    group_depths: dict[str, int] = {}
    for group in groups:
        try:
            group_rect = (
                int(group.get("x", 0)),
                int(group.get("y", 0)),
                int(group.get("width", 0)),
                int(group.get("height", 0)),
            )
        except (TypeError, ValueError):
            continue
        members = [
            rect for rect in unique if rect != group_rect and covers(group_rect, rect)
        ]
        if not members:
            continue
        member_depths = [
            sum(1 for other in unique if other != member and covers(other, member))
            for member in members
        ]
        group_depths[str(group.get("id") or "")] = max(member_depths) + 1
    for element in elements:
        if str(element.get("role") or "") not in {
            "control-group-outline",
            "control-group-separator",
        }:
            continue
        depth = group_depths.get(str(element.get("sceneOwnerId") or ""))
        if depth is None:
            continue
        element["paintDepth"] = depth + (
            1 if str(element.get("role") or "") == "control-group-separator" else 0
        )


def _container_element(
    node: Mapping[str, Any],
    *,
    image_path: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    from src.app.services.structure.image_contract import _dominant_color
    from src.app.services.structure.fidelity.pixel_probe import (
        sample_container_decoration,
    )

    bbox = _node_bbox(node, width, height)
    role = str(node.get("role") or "")
    render_bbox = _container_render_box(image_path, bbox, role)
    x, y, box_width, box_height = render_bbox
    style: dict[str, Any] = {
        "fillColor": _dominant_color(image_path, render_bbox, inset=2)
    }
    # Border and corner radius live in the pixels, not in the plan: the
    # renderer accepts both, but nothing was feeding them, so every card came
    # out as a flat rectangle with no edge and square corners.
    style.update(
        sample_container_decoration(image_path, render_bbox, style["fillColor"])
    )
    return {
        "id": str(node.get("id") or ""),
        "type": "container",
        "x": x,
        "y": y,
        "width": box_width,
        "height": box_height,
        "text": "",
        "style": style,
        "role": role,
        "name": str(role or node.get("id") or "Container"),
        "contentRef": node.get("content_ref"),
        "sceneOwnerId": str(node.get("id") or ""),
        "imageMVP": {
            "source": "scene-plan",
            "role": str(node.get("role") or ""),
            "grouping_status": "planned",
        },
    }


def _table_decorations(
    graph: Mapping[str, Any],
    table_node: Mapping[str, Any],
    *,
    width: int,
    height: int,
    table_ordinal: int,
) -> list[dict[str, Any]]:
    table_bbox = _node_bbox(table_node, width, height)
    tables = graph.get("tables") or []
    table = (
        tables[table_ordinal]
        if table_ordinal < len(tables) and isinstance(tables[table_ordinal], Mapping)
        else {}
    )
    rows = table.get("rows") or []
    row_count = len(rows) + (1 if table.get("header_texts") else 0)
    columns = len(table.get("header_texts") or [])
    if not columns and rows and isinstance(rows[0], list):
        columns = len(rows[0])
    x, y, box_width, box_height = table_bbox
    grid = table_node.get("grid")
    x_boundaries: list[int] = []
    y_boundaries: list[int] = []
    if isinstance(grid, Mapping):
        raw_x = grid.get("x_boundaries")
        raw_y = grid.get("y_boundaries")
        if isinstance(raw_x, list) and len(raw_x) >= 2:
            x_boundaries = [int(value) for value in raw_x]
        if isinstance(raw_y, list) and len(raw_y) >= 2:
            y_boundaries = [int(value) for value in raw_y]
    if x_boundaries:
        columns = len(x_boundaries) - 1
    else:
        x_boundaries = [
            x + round(column_index * box_width / max(1, columns))
            for column_index in range(columns + 1)
        ]
    if y_boundaries:
        row_count = len(y_boundaries) - 1
    else:
        y_boundaries = [
            y + round(row_index * box_height / max(1, row_count))
            for row_index in range(row_count + 1)
        ]
    header_height = (
        y_boundaries[1] - y_boundaries[0] if len(y_boundaries) >= 2 else box_height
    )
    decorations = [
        {
            "id": f"table-grid-header-{table_ordinal}",
            "type": "container",
            "x": x,
            "y": y,
            "width": box_width,
            "height": header_height,
            "text": "",
            "style": {"fillColor": "#fbfcfd"},
            "role": "table-header",
            "contentRef": None,
        }
    ]
    for column_index, line_x in enumerate(x_boundaries):
        decorations.append(
            {
                "id": f"table-grid-vertical-{table_ordinal}-{column_index}",
                "type": "divider",
                "x": line_x,
                "y": y,
                "width": 1,
                "height": box_height,
                "text": "",
                "style": {"fillColor": "#e7ecf1"},
                "role": "table-grid",
                "contentRef": None,
            }
        )
    for row_index, line_y in enumerate(y_boundaries):
        decorations.append(
            {
                "id": f"table-grid-horizontal-{table_ordinal}-{row_index}",
                "type": "divider",
                "x": x,
                "y": line_y,
                "width": box_width,
                "height": 1,
                "text": "",
                "style": {"fillColor": "#e7ecf1"},
                "role": "table-grid",
                "contentRef": None,
            }
        )
    return decorations


OVERLAY_TIER = 1000

_LAYOUT_MEMBER_TYPES = {
    "text",
    "image",
    "button",
    "input",
    "circle",
    "rectangle",
    "container",
}



def _layout_rect(element: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
    try:
        return (
            int(round(float(element.get("x") or 0))),
            int(round(float(element.get("y") or 0))),
            int(round(float(element.get("width") or 0))),
            int(round(float(element.get("height") or 0))),
        )
    except (TypeError, ValueError):
        return None


def _rect_contains(
    outer: tuple[int, int, int, int],
    inner: tuple[int, int, int, int],
    tolerance: int = 1,
) -> bool:
    return (
        outer[0] - tolerance <= inner[0]
        and outer[1] - tolerance <= inner[1]
        and inner[0] + inner[2] <= outer[0] + outer[2] + tolerance
        and inner[1] + inner[3] <= outer[1] + outer[3] + tolerance
    )


def _owner_index(
    rects: list[tuple[int, int, int, int] | None],
    index: int,
    *,
    parent_candidates: set[int] | None = None,
) -> int | None:
    """Smallest container that fully contains ``index``.

    ``parent_candidates`` restricts which elements may act as a parent.  Only
    containers qualify: without it a large image behind the copy swallowed the
    text nodes, so they never became members of the card frame that contained
    them and the frame was rejected for covering a stranger.
    """
    inner = rects[index]
    if inner is None:
        return None
    inner_area = inner[2] * inner[3]
    best: int | None = None
    best_area: int | None = None
    for other, outer in enumerate(rects):
        if other == index or outer is None:
            continue
        if parent_candidates is not None and other not in parent_candidates:
            continue
        if outer[2] * outer[3] <= inner_area:
            continue
        if not _rect_contains(outer, inner):
            continue
        area = outer[2] * outer[3]
        if best_area is None or area < best_area:
            best, best_area = other, area
    return best


def _rows(
    boxes: list[tuple[int, int, int, int]],
) -> list[list[int]]:
    """Group boxes that share a horizontal band into rows.

    A card heading and its star button sit on the same line, so treating the
    card as a flat list of children always produces a negative gap.  Grouping
    first turns ``heading + star, body, tags`` into three rows.
    """
    order = sorted(range(len(boxes)), key=lambda index: (boxes[index][1], boxes[index][0]))
    rows: list[list[int]] = []
    bottoms: list[int] = []
    for index in order:
        box = boxes[index]
        for position, bottom in enumerate(bottoms):
            if box[1] < bottom - 4:
                rows[position].append(index)
                bottoms[position] = max(bottom, box[1] + box[3])
                break
        else:
            rows.append([index])
            bottoms.append(box[1] + box[3])
    return rows


def _row_box(
    boxes: list[tuple[int, int, int, int]],
    members: list[int],
) -> tuple[int, int, int, int]:
    left = min(boxes[index][0] for index in members)
    top = min(boxes[index][1] for index in members)
    right = max(boxes[index][0] + boxes[index][2] for index in members)
    bottom = max(boxes[index][1] + boxes[index][3] for index in members)
    return (left, top, right - left, bottom - top)


def _vertical_spec(
    parent: tuple[int, int, int, int],
    rows: list[tuple[int, int, int, int]],
) -> dict[str, Any] | None:
    """Vertical stack spec over row boxes (not raw children)."""
    if len(rows) < 2:
        return None
    ordered = sorted(rows, key=lambda box: (box[1], box[0]))
    gaps = [
        ordered[index + 1][1] - (ordered[index][1] + ordered[index][3])
        for index in range(len(ordered) - 1)
    ]
    if any(gap < -4 for gap in gaps):
        return None
    # Spacing variance is not disqualifying: a real sidebar mixes section
    # headers and menu items, and a card mixes a heading with a footer far
    # below it.  Overlap on the stacking axis is the only structural signal,
    # and it is what separates one column from a grid.
    spacing = int(round(sum(gaps) / len(gaps))) if gaps else 0
    left = min(box[0] for box in ordered) - parent[0]
    right = (parent[0] + parent[2]) - max(box[0] + box[2] for box in ordered)
    top = min(box[1] for box in ordered) - parent[1]
    bottom = (parent[1] + parent[3]) - max(box[1] + box[3] for box in ordered)
    padding = {
        "paddingTop": top,
        "paddingBottom": bottom,
        "paddingLeft": left,
        "paddingRight": right,
    }
    if any(value < 0 for value in padding.values()):
        return None
    return {
        "mode": "VERTICAL",
        "itemSpacing": max(0, spacing),
        "primaryAlign": "MIN",
        "counterAlign": "MIN",
        **padding,
        "source": "geometry",
    }


def _horizontal_spec(
    parent: tuple[int, int, int, int],
    boxes: list[tuple[int, int, int, int]],
) -> dict[str, Any] | None:
    """Horizontal spec for children that all share one band."""
    if len(boxes) < 2:
        return None
    ordered = sorted(boxes, key=lambda box: (box[0], box[1]))
    tops = [box[1] for box in ordered]
    band = max(tops) - min(tops)
    if band > max(8, int(max(box[3] for box in ordered) * 0.8)):
        return None
    gaps = [
        ordered[index + 1][0] - (ordered[index][0] + ordered[index][2])
        for index in range(len(ordered) - 1)
    ]
    if any(gap < -4 for gap in gaps):
        return None
    left = min(box[0] for box in ordered) - parent[0]
    right = (parent[0] + parent[2]) - max(box[0] + box[2] for box in ordered)
    top = min(box[1] for box in ordered) - parent[1]
    bottom = (parent[1] + parent[3]) - max(box[1] + box[3] for box in ordered)
    padding = {
        "paddingTop": top,
        "paddingBottom": bottom,
        "paddingLeft": left,
        "paddingRight": right,
    }
    if any(value < 0 for value in padding.values()):
        return None
    spacing = int(round(sum(gaps) / len(gaps))) if gaps else 0
    return {
        "mode": "HORIZONTAL",
        "itemSpacing": max(0, spacing),
        "primaryAlign": "MIN",
        "counterAlign": "MIN",
        **padding,
        "source": "geometry",
    }


def _stack_layout(
    parent: tuple[int, int, int, int],
    children: list[tuple[int, int, int, int]],
) -> dict[str, Any] | None:
    """Best-effort spec for a container, trying one row then stacked rows."""
    if len(children) < 2:
        return None
    horizontal = _horizontal_spec(parent, children)
    if horizontal is not None:
        return horizontal
    rows = _rows(children)
    if len(rows) < 2:
        return None
    return _vertical_spec(parent, [_row_box(children, row) for row in rows])


def _has_nested_container(
    children: list[int],
    elements: list[dict[str, Any]],
) -> bool:
    """Whether a member container is still waiting to become a frame.

    ``collect()`` builds a frame's member closure from its members plus the
    members of member *frames*.  A child container without ``layoutChildren``
    leaves its own children outside that closure, and the renderer rejects the
    parent for covering them.  Processing innermost-first and holding a parent
    back until its child containers are framed yields a real frame tree instead
    of a flat pile.
    """
    return any(
        str(elements[index].get("type")) == "container"
        and not elements[index].get("layoutChildren")
        for index in children
    )


def _overlap_over_smaller(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> float:
    """Intersection over the smaller area.

    Note this returns 1.0 for any box fully inside the other, which makes it
    useless for "is this a duplicate of the frame" — use ``_iou`` for that.
    """
    overlap_w = min(left[0] + left[2], right[0] + right[2]) - max(left[0], right[0])
    overlap_h = min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1])
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0
    intersection = overlap_w * overlap_h
    return intersection / max(1, min(left[2] * left[3], right[2] * right[3]))


def _iou(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> float:
    """Intersection over union.

    ``_overlap_over_smaller`` reports 1.0 when a small icon sits inside a large
    frame, which rejected every container: a grid is never "mostly covered" by
    one of its own children.  Only a box of comparable size can be a duplicate.
    """
    overlap_w = min(left[0] + left[2], right[0] + right[2]) - max(left[0], right[0])
    overlap_h = min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1])
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0
    intersection = overlap_w * overlap_h
    union = left[2] * left[3] + right[2] * right[3] - intersection
    return intersection / union if union > 0 else 0.0


def _has_straddling_block(
    owner: int,
    rects: list[tuple[int, int, int, int] | None],
    members: set[int],
) -> bool:
    """Whether a non-member covers most of this frame.

    A floating panel often comes back alongside a button that fills it to
    within two pixels.  The button belongs to whichever container happened to
    contain it first, so the panel can never own it — and a frame that covers
    a stranger is rejected.  Such a container is an ambiguous duplicate of its
    own child, not a layout box.
    """
    frame = rects[owner]
    if frame is None:
        return False
    frame_area = frame[2] * frame[3]
    for index, other in enumerate(rects):
        if index == owner or other is None or index in members:
            continue
        # Ancestors and siblings cover the frame by definition; only a smaller
        # neighbour can be the ambiguous duplicate we are looking for.
        if other[2] * other[3] >= frame_area:
            continue
        if _iou(frame, other) > 0.8:
            return True
    return False


def _rects_overlap(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> bool:
    return (
        min(left[0] + left[2], right[0] + right[2]) - max(left[0], right[0]) > 0
        and min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1]) > 0
    )


def _avoid_coloured_neighbours(
    containers: list[dict[str, Any]],
    background: str,
) -> int:
    """Push a neutral container off a coloured one it overlaps.

    ``main-content`` starts at x=180 while the sidebar ends at x=346, so its
    white fill painted over 166px of the sidebar's ``#f9f9fb``.  Dropping the
    fill is the wrong fix — that white is also hiding the layer underneath.
    Moving the left edge to the sidebar's right edge keeps both: the sidebar
    stays grey and the content area still has its backing.

    Only the left edge moves, and only when the trim is a small fraction of the
    width, so a container that merely touches a coloured block is left alone.
    """
    page = str(background or "").strip().lower()
    coloured: list[dict[str, Any]] = []
    for container in containers:
        fill = str((container.get("style") or {}).get("fillColor") or "").strip().lower()
        rect = _layout_rect(container)
        if fill and fill != page and rect is not None:
            coloured.append(container)
    if not coloured:
        return 0
    moved = 0
    for container in containers:
        rect = _layout_rect(container)
        if rect is None:
            continue
        fill = str((container.get("style") or {}).get("fillColor") or "").strip().lower()
        if container in coloured:
            continue
        for blocker in coloured:
            other = _layout_rect(blocker)
            if other is None or not _rects_overlap(rect, other):
                continue
            # A coloured block *inside* this container is a child, not an
            # intruder: the cards live inside main-content.  Only a block that
            # starts to the left of us can push our edge.
            if _rect_contains(rect, other, tolerance=2) or other[0] >= rect[0]:
                continue
            # A full-width band pinned to the top is the header strip; it is
            # meant to cross the page and hide what is behind it.  Trimming it
            # exposes that layer as a grey band across the canvas.
            if rect[1] <= 2 and rect[3] < 120:
                continue
            trim = (other[0] + other[2]) - rect[0]
            if trim <= 2 or trim >= rect[2] * 0.5:
                continue
            container["x"] = rect[0] + trim
            container["width"] = rect[2] - trim
            rect = _layout_rect(container) or rect
            moved += 1
    return moved


def _frame_closure(
    root: int,
    elements: list[dict[str, Any]],
) -> set[int]:
    """Every element painted as part of ``root``'s frame, children included."""
    by_id = {str(element.get("id")): index for index, element in enumerate(elements)}
    seen: set[int] = set()

    def walk(index: int) -> None:
        if index in seen:
            return
        seen.add(index)
        for child in elements[index].get("layoutChildren") or []:
            nested = by_id.get(str(child.get("id")))
            if nested is not None and nested not in seen:
                walk(nested)

    walk(root)
    return seen


def _lift_frame_overlays(
    elements: list[dict[str, Any]],
    frames: list[int],
) -> int:
    """Pull overlays out of a frame's paint interval and put them on top.

    ``paint_order`` sorts the flat element list by geometry, so a card's
    background, the floating panel's background and the card's own text end up
    interleaved: background → overlay → text.  ``resolve_frames`` then sees an
    outsider inside the frame's interval and rejects the frame.

    A frame's members are already a contiguous unit when it is painted as one
    node, so anything that lands inside the interval without belonging to the
    frame is an overlay sitting on top of it.  Moving that whole overlay (its
    own children too) past the frame with ``zIndex`` restores both facts: the
    frame paints as one block, and the overlay still covers it.
    """
    if not frames:
        return 0
    from src.app.services.rendering.adapter_base import paint_order

    # Overlays go to a tier nothing else reaches.  A "max + 1" value is shared
    # by every frame in this pass, so an overlay lifted for one frame could end
    # up level with another frame's members and stay inside its interval.
    overlay_z = OVERLAY_TIER
    lifted: set[int] = set()
    lifted_count = 0
    closures = {frame: _frame_closure(frame, elements) for frame in frames}
    # Largest frame first.  The big grid pushes its overlay out of the way
    # before the small panel is examined; walking the other way round let the
    # panel push the grid's own text up in return.
    for frame in sorted(
        frames,
        key=lambda index: (
            -(_layout_rect(elements[index]) or (0, 0, 0, 0))[2]
            * (_layout_rect(elements[index]) or (0, 0, 0, 0))[3]
        ),
    ):
        # Refresh after every frame: pushing one overlay changes the order the
        # next frame sees, and stale indices are how the two frames kept
        # handing members back and forth.
        order = [index for index, _item in paint_order(elements)]
        position = {index: spot for spot, index in enumerate(order)}
        closure = closures[frame]
        spots = [position[member] for member in closure if member in position]
        if not spots:
            continue
        last = max(spots)
        start = position.get(frame, last)
        frame_box = _layout_rect(elements[frame])
        if frame_box is None:
            continue
        frame_area = frame_box[2] * frame_box[3]
        # Members of *other* frames must not be dragged along: an overlay's
        # icon can be geometrically inside a card, so it also belongs to the
        # grid's closure.  Lifting it stretched the grid's interval past the
        # overlay and re-blocked the frame.
        foreign: set[int] = set()
        for other_frame, other_closure in closures.items():
            if other_frame in (frame, None):
                continue
            foreign |= other_closure
        foreign -= closure
        for index in order[start + 1 : last + 1]:
            if index in closure or index in lifted:
                continue
            box = _layout_rect(elements[index])
            if box is None:
                continue
            # Only something that actually covers the frame is an overlay.
            if not _rects_overlap(frame_box, box):
                continue
            # A box inside the frame is its own decoration (a group outline, a
            # separator) or a straggler member; lifting it would put that
            # chrome above the very buttons it frames.
            if _rect_contains(frame_box, box, tolerance=4):
                continue
            # An ancestor or any larger container is the layer *underneath*,
            # never an overlay on top: pushing it would invert the stack.
            if _rect_contains(box, frame_box, tolerance=4):
                continue
            if box[2] * box[3] >= frame_area:
                continue
            elements[index]["zIndex"] = overlay_z
            # Its children ride one tier higher, so they stay above their own
            # background and above the frame they cover.
            for other, element in enumerate(elements):
                if other == index or other in foreign:
                    continue
                child = _layout_rect(element)
                if child is not None and _rect_contains(box, child, tolerance=4):
                    element["zIndex"] = overlay_z + 1
                    lifted.add(other)
            lifted.add(index)
            lifted_count += 1
    return lifted_count


def _trim_under_top_band(
    containers: list[dict[str, Any]],
    width: int,
) -> int:
    """Give the top band its strip back.

    The header spans the page and is painted last, so it covers the sidebar's
    first 72px.  That overlap is meaningless — it is a measuring artefact, not
    a design — and it makes ``resolve_frames`` treat the header as a later
    outsider inside the sidebar's rectangle, which blocks the sidebar frame.
    Trimming the sidebar's top edge to the band's bottom removes the overlap
    without moving anything visible: the header already hides that strip.
    """
    trunks: list[tuple[int, int, int, int]] = []
    for container in containers:
        rect = _layout_rect(container)
        if rect is None:
            continue
        if rect[1] <= 2 and rect[3] < 120 and rect[2] >= width * 0.8:
            trunks.append(rect)
    if not trunks:
        return 0
    trimmed = 0
    for container in containers:
        rect = _layout_rect(container)
        if rect is None or rect[1] > 2:
            continue
        for trunk in trunks:
            if rect == trunk:
                continue
            overlap_w = min(rect[0] + rect[2], trunk[0] + trunk[2]) - max(rect[0], trunk[0])
            if overlap_w <= 2:
                continue
            if _rect_contains(rect, trunk, tolerance=2) or _rect_contains(
                trunk, rect, tolerance=2
            ):
                continue
            band_bottom = trunk[1] + trunk[3]
            if band_bottom >= rect[1] + rect[3] - 4:
                continue
            container["y"] = band_bottom
            container["height"] = rect[3] - (band_bottom - rect[1])
            trimmed += 1
            break
    return trimmed


def _keep_renderable_frames(
    elements: list[dict[str, Any]],
    written: int,
) -> int:
    """Drop frames the renderer would reject, so the count means what it says.

    ``resolve_frames`` is the only authority on whether a frame survives — it
    checks paint order, member order and the closure over members — so ask it
    directly instead of duplicating those rules here.  A container whose
    rectangle a later-painted sibling covers can never be a frame: the
    floating panel and the AtomCode button are painted over the card grid, and
    the header is painted over the sidebar.  Those two stay flat, which is
    correct: wrapping them would let the frame swallow the overlay.
    """
    if not written:
        return 0
    from src.app.services.rendering.adapter_base import paint_order, resolve_frames

    reasons: dict[int, str] = {}
    accepted = set(resolve_frames(elements, paint_order(elements), reasons))
    kept = 0
    for index, element in enumerate(elements):
        if not element.get("layoutChildren"):
            continue
        if index in accepted:
            kept += 1
            continue
        element.pop("layoutChildren", None)
        element.pop("layout", None)
    return kept


def attach_layout_frames(elements: list[dict[str, Any]]) -> int:
    """Group elements into Auto Layout frames along the strict containment tree.

    The renderer already builds real Figma frames when an element carries
    ``layout`` + ``layoutChildren``; nothing was producing them for image
    input, so every element landed flat on the canvas at depth 1.  This pass
    writes the two fields and leaves the renderer's own safety gates to reject
    anything ambiguous — a rejected frame renders exactly like the flat file.
    """
    rects = [
        _layout_rect(element) if str(element.get("type")) in _LAYOUT_MEMBER_TYPES else None
        for element in elements
    ]
    containers = {
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "container"
    }
    owners = [
        _owner_index(rects, index, parent_candidates=containers)
        if rects[index]
        else None
        for index in range(len(elements))
    ]

    members: dict[int, list[int]] = {}
    for index, owner in enumerate(owners):
        if owner is None:
            continue
        members.setdefault(owner, []).append(index)

    built = 0
    # Innermost first: a parent may only become a frame once every container
    # among its members is already a frame.
    order = sorted(
        members,
        key=lambda index: (rects[index][2] * rects[index][3]) if rects[index] else 0,
    )
    for owner in order:
        children = members[owner]
        container = elements[owner]
        if str(container.get("type")) != "container":
            continue
        if container.get("imageBase64") or container.get("text"):
            continue
        boxes = [rects[child] for child in children if rects[child]]
        parent_box = rects[owner]
        if not boxes or parent_box is None:
            continue
        spec = _stack_layout(parent_box, boxes)  # type: ignore[arg-type]
        if spec is None:
            continue
        if _has_nested_container(children, elements):
            continue
        # No straddling veto here.  An overlay that covers this container is
        # lifted during the paint-order pass that follows, and only then does
        # the renderer have the final say.  Vetoing earlier deadlocked the two:
        # the overlay blocked the frame, and without the frame the overlay was
        # never lifted.
        container["layout"] = spec
        container["layoutChildren"] = [
            {"id": str(elements[child].get("id") or "")} for child in children
        ]
        built += 1
    return built


def compile_scene_plan_to_design(
    graph: Mapping[str, Any],
    reference: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    image_path: str,
    width: int,
    height: int,
    background: str,
    sample_id: str,
) -> dict[str, Any]:
    """Compile one fixed-canvas plan without post-hoc owner appenders."""
    if not isinstance(plan, Mapping):
        raise ValueError("scene plan must be an object")
    if list(plan.get("image_size") or []) != [width, height]:
        raise ValueError("scene plan and target canvas sizes must match")
    nodes = [
        copy.deepcopy(dict(node))
        for node in plan.get("nodes") or []
        if isinstance(node, Mapping)
    ]
    node_by_id = {str(node.get("id") or ""): node for node in nodes}
    build_container_manifest(plan)
    containers: list[dict[str, Any]] = []
    decorations: list[dict[str, Any]] = []
    leaves: list[dict[str, Any]] = []
    (
        grouped_controls,
        grouped_fill,
        control_groups,
        control_group_decorations,
    ) = _button_groups(
        nodes,
        image_path=image_path,
        width=width,
        height=height,
    )
    table_ordinal = 0
    for index, node in enumerate(nodes):
        node_type = str(node.get("type") or "")
        if node_type in {"container", "table"}:
            containers.append(
                _container_element(
                    node,
                    image_path=image_path,
                    width=width,
                    height=height,
                )
            )
            if node_type == "table":
                decorations.extend(
                    _table_decorations(
                        graph,
                        node,
                        width=width,
                        height=height,
                        table_ordinal=table_ordinal,
                    )
                )
                table_ordinal += 1
        elif node_type == "text":
            leaves.append(
                _text_element(
                    node,
                    image_path=image_path,
                    width=width,
                    height=height,
                    node_by_id=node_by_id,
                )
            )
        elif node_type == "control":
            if _is_source_pixel_control(node):
                leaves.append(
                    _icon_control_element(
                        node,
                        image_path=image_path,
                        width=width,
                        height=height,
                        sample_id=sample_id,
                        reference=reference,
                        index=index,
                    )
                )
            else:
                leaves.append(
                    _control_element(
                        node,
                        image_path=image_path,
                        width=width,
                        height=height,
                        node_by_id=node_by_id,
                        index=index,
                        group_fill=grouped_fill.get(str(node.get("id") or "")),
                    )
                )
        elif node_type == "image":
            leaves.append(
                _image_element(
                    node,
                    image_path=image_path,
                    width=width,
                    height=height,
                    sample_id=sample_id,
                    reference=reference,
                    index=index,
                )
            )
    containers.extend(control_groups)
    decorations.extend(control_group_decorations)
    _avoid_coloured_neighbours(containers, background)
    _trim_under_top_band(containers, width)
    elements = [*containers, *decorations, *leaves]
    _apply_group_decoration_depths(elements, control_groups)
    form_background = _source_form_background(
        image_path,
        elements,
        width=width,
        height=height,
    )
    if form_background is not None:
        elements.append(form_background)
    right_rail = _source_chrome_right_rail(
        image_path,
        nodes,
        width=width,
        height=height,
    )
    if right_rail is not None:
        elements.append(right_rail)
    written_frames = attach_layout_frames(elements)
    # A frame's members must paint as one contiguous unit; an overlay that
    # lands inside that interval belongs on top of it, not in the middle.
    _lift_frame_overlays(
        elements,
        [
            index
            for index, element in enumerate(elements)
            if element.get("layoutChildren")
        ],
    )
    layout_frames = _keep_renderable_frames(elements, written_frames)
    text_count = sum(
        element.get("type") == "text" and bool(element.get("text"))
        for element in elements
    )
    image_count = sum(bool(element.get("imageBase64")) for element in elements)
    return {
        "name": f"Fixed canvas {sample_id}",
        "canvas": {
            "width": width,
            "height": height,
            "background": background,
        },
        "elements": elements,
        "_meta": {
            "mode": "fixed-canvas-owner-compiler",
            "source": "scene-plan-owner-manifest",
            "expected": len(nodes),
            "returned": len(elements),
            "coverage": 1.0,
            "calls": 1,
            "rounds": 1,
            "ownerCount": sum(bool(node.get("content_ref")) for node in nodes),
            "imageMVP": {
                "reference_id": reference["reference_id"],
                "state": dict(reference["state"]),
                "flow": {
                    "value": "fixed-canvas-absolute",
                    "status": "planned",
                    "adaptive": False,
                },
                "counts": {
                    "text": text_count,
                    "images": image_count,
                    "containers": len(containers),
                    "layoutFrames": layout_frames,
                },
                "assetClaim": "display-replacement-only",
                "originalAssetClaimed": False,
            },
        },
    }
