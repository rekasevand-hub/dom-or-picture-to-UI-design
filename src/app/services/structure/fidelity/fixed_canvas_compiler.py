"""Compile one fixed-canvas ScenePlan into a DesignSpec."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import re
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
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


def _stamp_rotation(element: dict[str, Any], node: Mapping[str, Any]) -> None:
    """Carry a plan's angle onto the element, folded and rounded.

    Only present when the plan actually named one: an axis-aligned page keeps a
    byte-identical design, which is what the frozen samples are checked against.
    """
    from src.app.services.structure.fidelity.rotation import normalise_angle

    angle = normalise_angle(node.get("rotation"))
    if angle:
        element["rotation"] = angle


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
    # The numeric weight is what the renderer actually applies; the keyword is
    # kept for the output ends that only understand "bold".
    if style.get("fontWeightValue") is not None:
        style_payload["fontWeightValue"] = style["fontWeightValue"]
    # Only multi-line owners carry a measured line height; single-line text
    # keeps the renderer's default rhythm (the adapter strips it anyway).
    if style.get("lineHeight"):
        style_payload["lineHeight"] = style["lineHeight"]
    element_payload = {
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
    _stamp_rotation(element_payload, node)
    return element_payload


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
        "fontWeight": style.get("fontWeight") or "normal",
        "fontWeightValue": style.get("fontWeightValue"),
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
        # 图层的显示名：OmniParser 的语义描述（hamburger / star）只落在这一层，
        # 它是元数据，不是画布上的字。
        "name": str(node.get("name") or node.get("caption") or ""),
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
    element = {
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
    _stamp_rotation(element, node)
    return element


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


_LAYOUT_MEMBER_TYPES = {
    "text",
    "image",
    "button",
    "input",
    "circle",
    "rectangle",
    "divider",
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

    Strict containment is tried before the one-pixel tolerance.  A grid line
    drawn on a panel's bottom edge touches that panel but does not lie inside
    it; claiming it makes the line a member, and the next row's cells — which
    start exactly where the line ends — then overlap a member and the frame is
    rejected.  Falling back to the parent panel puts the line where it belongs.
    """
    inner = rects[index]
    if inner is None:
        return None
    inner_area = inner[2] * inner[3]
    for tolerance in (0, 1):
        best: int | None = None
        best_area: int | None = None
        for other, outer in enumerate(rects):
            if other == index or outer is None:
                continue
            if parent_candidates is not None and other not in parent_candidates:
                continue
            if outer[2] * outer[3] <= inner_area:
                continue
            if not _rect_contains(outer, inner, tolerance=tolerance):
                continue
            area = outer[2] * outer[3]
            if best_area is None or area < best_area:
                best, best_area = other, area
        if best is not None:
            return best
    return None


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
    members: dict[int, list[int]] | None = None,
) -> bool:
    """Whether a member container is still waiting to become a frame.

    ``collect()`` builds a frame's member closure from its members plus the
    members of member *frames*.  A child container without ``layoutChildren``
    leaves its own children outside that closure, and the renderer rejects the
    parent for covering them.  Processing innermost-first and holding a parent
    back until its child containers are framed yields a real frame tree instead
    of a flat pile.

    A container that owns nothing is exempt.  Two containers can measure out
    nearly identically (one is a duplicate rectangle); the poorer one keeps
    zero members and is dropped as a frame candidate, and counting it here
    would block its parent forever with no orphan to protect.
    """
    for index in children:
        if str(elements[index].get("type")) != "container":
            continue
        if elements[index].get("layoutChildren"):
            continue
        if members is not None and not members.get(index):
            continue
        return True
    return False


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
            if elements[index].get("planeDetached"):
                # It stands on the page behind the dialog.  Lifting it would put
                # the page's own content on top of the glass.
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
            # A box that nearly coincides with the frame is its own outline or
            # separator — chrome drawn for the frame, not an overlay on it.
            if _iou(frame_box, box) > 0.9:
                continue
            # Relative tier, not a constant: an overlay is one level above the
            # frame it covers.  Walking largest-first chains the levels, so a
            # dropdown over a modal over a page lands at depth 3 on its own,
            # without any per-role constant.
            frame_z = int(elements[frame].get("zIndex") or 0)
            target_z = frame_z + 1
            elements[index]["zIndex"] = max(
                int(elements[index].get("zIndex") or 0), target_z
            )
            # Its children ride one tier higher, so they stay above their own
            # background and above the frame they cover.
            riders = [
                other
                for other, element in enumerate(elements)
                if other != index
                and other not in foreign
                and (
                    child := _layout_rect(element)
                )
                is not None
                and _rect_contains(box, child, tolerance=4)
            ]
            # A lifted element that is itself a frame must take its members
            # with it.  Geometry is not enough to find them: the members that
            # overhang the frame's own rectangle are exactly the ones the
            # containment test misses, and they stay below it — the renderer
            # then rejects the frame for having a member painted before it.
            if elements[index].get("layoutChildren"):
                riders.extend(_frame_closure(index, elements))
            for other in riders:
                if other == index:
                    continue
                elements[other]["zIndex"] = max(
                    int(elements[other].get("zIndex") or 0), target_z + 1
                )
                lifted.add(other)
            lifted.add(index)
            lifted_count += 1
    return lifted_count


def _trim_under_top_band(
    containers: list[dict[str, Any]],
    elements: list[dict[str, Any]],
    width: int,
) -> int:
    """Resolve a corner overlap between a horizontal band and a vertical rail.

    Two containers with no containment relation may still clip at a corner —
    a full-width header and a full-height sidebar meeting at the top-left.  It
    is a measuring artefact, not a design, and it makes the later-painted band
    an outsider inside the rail's rectangle, which blocks the rail's frame.

    Which side gives way is decided by geometry, not by role:

    * If leaves inside the intersection belong to one side, that side owns the
      corner and the other retreats.
    * Otherwise the container spanning the main axis keeps its strip and the
      crossing one is trimmed, which is what a header-over-sidebar layout
      means.

    Only corner-sized overlaps qualify (0 < IoU < 0.25); anything larger is a
    real nesting problem, not a measurement slip.
    """
    del width
    rectangles: list[tuple[int, dict[str, Any], tuple[int, int, int, int]]] = []
    for container in containers:
        rect = _layout_rect(container)
        if rect is not None:
            rectangles.append((containers.index(container), container, rect))
    trimmed = 0
    for position, (index_a, first, rect_a) in enumerate(rectangles):
        for index_b, second, rect_b in rectangles[position + 1 :]:
            if _rect_contains(rect_a, rect_b, tolerance=2) or _rect_contains(
                rect_b, rect_a, tolerance=2
            ):
                continue
            overlap = _iou(rect_a, rect_b)
            if not 0 < overlap < 0.25:
                continue
            first_wide = rect_a[2] >= rect_a[3]
            second_wide = rect_b[2] >= rect_b[3]
            if first_wide == second_wide:
                continue  # parallel strips, not a crossing
            inter_left = max(rect_a[0], rect_b[0])
            inter_top = max(rect_a[1], rect_b[1])
            inter_right = min(rect_a[0] + rect_a[2], rect_b[0] + rect_b[2])
            inter_bottom = min(rect_a[1] + rect_a[3], rect_b[1] + rect_b[3])
            if inter_right <= inter_left or inter_bottom <= inter_top:
                continue
            inside_a = inside_b = 0
            for element in elements:
                if str(element.get("type")) not in _LAYOUT_MEMBER_TYPES:
                    continue
                rect = _layout_rect(element)
                if rect is None:
                    continue
                centre_x = rect[0] + rect[2] / 2
                centre_y = rect[1] + rect[3] / 2
                if not (
                    inter_left <= centre_x <= inter_right
                    and inter_top <= centre_y <= inter_bottom
                ):
                    continue
                if _rect_contains(rect_a, rect, tolerance=2):
                    inside_a += 1
                # Independent, not elif: a leaf inside the intersection can be
                # contained by both rectangles, and counting it for one side
                # only made the corner look owned when it was actually shared.
                if _rect_contains(rect_b, rect, tolerance=2):
                    inside_b += 1
            if inside_a and not inside_b:
                victim, keeper = second, first
                victim_rect, keeper_rect = rect_b, rect_a
            elif inside_b and not inside_a:
                victim, keeper = first, second
                victim_rect, keeper_rect = rect_a, rect_b
            else:
                # Empty or contested corner: the band that spans the page keeps
                # its strip, the crossing rail is trimmed away from it.
                victim, keeper = (second, first) if first_wide else (first, second)
                victim_rect, keeper_rect = (
                    (rect_b, rect_a) if first_wide else (rect_a, rect_b)
                )
            if keeper_rect[1] <= 2 and victim_rect[1] <= 2:
                band_bottom = keeper_rect[1] + keeper_rect[3]
                if band_bottom < victim_rect[1] + victim_rect[3] - 4:
                    victim["y"] = band_bottom
                    victim["height"] = victim_rect[3] - (band_bottom - victim_rect[1])
                    trimmed += 1
            elif keeper_rect[0] <= 2 and victim_rect[0] <= 2:
                band_right = keeper_rect[0] + keeper_rect[2]
                if band_right < victim_rect[0] + victim_rect[2] - 4:
                    victim["x"] = band_right
                    victim["width"] = victim_rect[2] - (band_right - victim_rect[0])
                    trimmed += 1
    return trimmed


def _duplicate_containers(
    containers: list[int],
    rects: list[tuple[int, int, int, int] | None],
    members: dict[int, list[int]],
) -> set[int]:
    """Containers measuring the same region twice; keep the richer one.

    A dark sidebar can come back as both ``sidebar`` (0,0,276,682) and
    ``card`` (0,61,283,765).  They overlap almost completely, the later one
    paints over the other, and the frame gets rejected for covering a
    stranger.  Only one of them can own the region, so the one that actually
    gathered members wins and the other stays flat.
    """
    doomed: set[int] = set()
    for position, first in enumerate(containers):
        for second in containers[position + 1 :]:
            first_rect = rects[first]
            second_rect = rects[second]
            if first_rect is None or second_rect is None:
                continue
            # A container nested inside another overlaps it almost fully by
            # definition: the card grid fills its main content area.  That is
            # nesting, not a double measurement.
            if _rect_contains(first_rect, second_rect, tolerance=2) or _rect_contains(
                second_rect, first_rect, tolerance=2
            ):
                continue
            if _overlap_over_smaller(first_rect, second_rect) <= 0.85:
                continue
            loser = (
                first
                if len(members.get(first, ())) < len(members.get(second, ()))
                else second
            )
            doomed.add(loser)
    return doomed


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


def _merge_slots(
    boxes: list[tuple[int, int, int, int]],
    axis: str,
    threshold: float = 0.6,
) -> list[tuple[int, int]]:
    """Collapse boxes stacked at one position into single slots.

    A toolbar can carry three overlapping icon cuts at the same x — a glyph, a
    badge and its background.  Measuring gaps between them yields negative
    values and the row is rejected, although visually it is one slot.  Boxes
    overlapping more than 60% of the smaller one become one slot.

    This only shapes the gap measurement.  Every original box still belongs to
    the frame; dropping the overlapping cuts would leave them inside the frame
    rectangle as non-members.
    """
    if axis == "x":
        ordered = sorted(boxes, key=lambda box: (box[0], box[1]))
        offset, span = 0, 2
    else:
        ordered = sorted(boxes, key=lambda box: (box[1], box[0]))
        offset, span = 1, 3
    slots: list[tuple[int, int]] = []
    for box in ordered:
        start = box[offset]
        end = start + box[span]
        if slots:
            previous_start, previous_end = slots[-1]
            overlap = min(previous_end, end) - max(previous_start, start)
            smaller = min(previous_end - previous_start, end - start)
            if overlap > 0 and overlap / max(1, smaller) > threshold:
                slots[-1] = (min(previous_start, start), max(previous_end, end))
                continue
        slots.append((start, end))
    return slots


def _pixel_edges(
    image_path: str,
    width: int,
    height: int,
):
    """Load the screenshot as an array, or None when it cannot be read.

    Boundaries are searched per container rather than over the whole image: a
    rule under one panel spans a few hundred pixels, and averaging it into a
    2560px-wide profile buries the step in the sidebar's own colours.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return None
    try:
        image = Image.open(image_path).convert("RGB")
        if image.size != (width, height):
            image = image.resize((width, height))
        return np.asarray(image, dtype=np.int16)
    except Exception:  # pragma: no cover - unreadable file
        return None


PIXEL_EDGE_MIN_STEP = 10.0


def _pixel_limit(
    edge: str,
    span: tuple[int, int],
    cross: tuple[int, int],
    pixels,
) -> int | None:
    """Strongest colour boundary inside one padding band, if there is one.

    ``span`` is the band along the edge's axis, ``cross`` the container's extent
    on the other axis.  Returns the coordinate to snap to, or None when the band
    is flat — which is exactly what a genuine padding margin looks like.
    """
    try:
        import numpy as np
    except Exception:  # pragma: no cover
        return None
    low, high = span
    if high - low < 4 or pixels is None:
        return None
    top, bottom = max(0, cross[0]), max(0, cross[1])
    if bottom - top < 2:
        return None
    if edge in ("top", "bottom"):
        band = pixels[low:high, top:bottom]
        if band.shape[0] < 2:
            return None
        steps = np.abs(np.diff(band, axis=0)).mean(axis=(1, 2))
        if steps.size == 0:
            return None
        position = int(np.argmax(steps))
        if float(steps[position]) < PIXEL_EDGE_MIN_STEP:
            return None
        return low + position + 1
    band = pixels[top:bottom, max(0, low) : max(0, high)]
    if band.ndim != 3 or band.shape[1] < 2:
        return None
    steps = np.abs(np.diff(band, axis=1)).mean(axis=(0, 2))
    position = int(np.argmax(steps))
    if float(steps[position]) < PIXEL_EDGE_MIN_STEP:
        return None
    return max(0, low) + position + 1


def _paints_page(element: Mapping[str, Any], background: str | None) -> bool:
    """Whether resizing this container leaves the picture unchanged."""
    style = element.get("style") or {}
    fill = str(style.get("fillColor") or "").strip().lower()
    if not fill or fill in {"transparent", "none"}:
        return True
    return bool(background) and fill == str(background).strip().lower()


#: A container's declared fill may be a few channels off what the box actually
#: shows: the sample landed on a border, a shadow, or the page behind an
#: over-measured edge.  Beyond this it is the wrong colour, not a rounding.
FILL_CALIBRATION_DELTA = 6
#: The interior has to be one colour before it may overrule the declaration.
FILL_CALIBRATION_SHARE = 0.6


def _calibrate_container_fills(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    background: str = "",
) -> int:
    """Repaint a container in the colour its own interior actually is.

    ``card:container-9`` came back #d9d9d9 for a band that is white in the
    screenshot — the sample landed on the band's top shadow — and AtomGit's
    pink cards were declared #fef4f2 against a truth of #fee7e0.  One wrong
    fill paints a whole card wrong, so it is worth one pass over the picture.

    Only a uniform interior may overrule the declaration: a box that reaches
    past its own card samples two colours, and there is nothing better to say
    about it than what the model already said.
    """
    if not image_path:
        return 0
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    if image.ndim != 3:
        return 0
    pictures = [
        box
        for box in (
            _layout_rect(element)
            for element in elements
            if element.get("imageBase64")
        )
        if box is not None
    ]
    changed = 0
    for element in elements:
        if str(element.get("type")) != "container":
            continue
        fill = _solid_fill(element)
        if not fill:
            continue
        # A box that paints the page is a shell, not a panel: its interior is
        # whatever happens to be in front of it, and repainting it white is how
        # a dialog ends up with three white sections across its dark backdrop.
        if background and _same_fill(fill, background, FILL_CALIBRATION_DELTA):
            continue
        box = _layout_rect(element)
        if box is None or box[2] * box[3] < 400:
            continue
        inset = 3 if min(box[2], box[3]) > 8 else 0
        x = max(0, box[0] + inset)
        y = max(0, box[1] + inset)
        right = min(image.shape[1], box[0] + box[2] - inset)
        bottom = min(image.shape[0], box[1] + box[3] - inset)
        if right - x < 4 or bottom - y < 4:
            continue
        if any(_overlap_share(box, picture) >= 0.5 for picture in pictures):
            # The box is a picture frame; its average is not a fill.
            continue
        # The container's own surface is the ring just inside its edge.  Its
        # interior may be full of cards, and a page whose middle is two cards
        # would otherwise be repainted in the cards' colour.
        ring = 4 if min(right - x, bottom - y) > 12 else 0
        patch = np.concatenate(
            [
                image[y : y + ring, x:right].reshape(-1, 3),
                image[bottom - ring : bottom, x:right].reshape(-1, 3),
                image[y:bottom, x : x + ring].reshape(-1, 3),
                image[y:bottom, right - ring : right].reshape(-1, 3),
            ]
        ) if ring else image[y:bottom, x:right].reshape(-1, 3)
        if patch.size == 0:
            continue
        colour = _dominant_colour(patch)
        if colour is None:
            continue
        quantised = (patch.reshape(-1, 3) // 16).astype(np.int32)
        keys = quantised[:, 0] * 4096 + quantised[:, 1] * 64 + quantised[:, 2]
        chosen = (np.asarray(colour, dtype=np.int32) // 16)
        key = int(chosen[0] * 4096 + chosen[1] * 64 + chosen[2])
        share = float((keys == key).mean())
        if share < FILL_CALIBRATION_SHARE:
            continue
        hexed = "#{:02x}{:02x}{:02x}".format(*colour)
        if _same_fill(hexed, fill, FILL_CALIBRATION_DELTA):
            continue
        element.setdefault("style", {})["fillColor"] = hexed
        changed += 1
    return changed


def _trim_overshoot_into_conflicts(
    elements: list[dict[str, Any]],
    image_path: str | None = None,
    canvas: tuple[int, int] | None = None,
    background: str | None = None,
) -> int:
    """Shrink a container edge only where its padding actually collides.

    A container's measured box can be a little larger than its own content —
    that is padding, and it is often exactly right: a card's inner margin, a
    sidebar's blank strip at the bottom.  Trimming every container to its
    members would erase that.

    The problem only appears when the padding band overlaps something that is
    not part of the container: ``form-section`` measures down to y=608 while
    its last field ends at 544, and the 64px band runs into the table header at
    y=549.  That stranger is painted inside the frame rectangle but can never be
    its member, so the frame is rejected.

    Hence: walk each of the four bands, and pull that edge in only if a foreign
    element sits in it.  No collision, no change.
    """
    rects = [_layout_rect(element) for element in elements]
    containers = [
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "container" and rects[index] is not None
    ]
    if not containers:
        return 0
    owners = [
        _owner_index(rects, index, parent_candidates=set(containers))
        if rects[index] is not None and index not in containers
        else None
        for index in range(len(elements))
    ]

    def belongs_to(index: int, container: int) -> bool:
        """Whether ``index`` is inside ``container``'s own tree."""
        seen: set[int] = set()
        current = owners[index]
        while current is not None and current not in seen:
            if current == container:
                return True
            seen.add(current)
            current = owners[current] if current < len(owners) else None
        return False

    pixels = (
        _pixel_edges(image_path, canvas[0], canvas[1])
        if image_path and canvas
        else None
    )
    trimmed = 0
    for container in containers:
        own = rects[container]
        members = [
            index
            for index in range(len(elements))
            if index != container
            and rects[index] is not None
            and belongs_to(index, container)
        ]
        # Two-member containers are badges, chips and floating panels.  Their
        # padding is the whole point and tightening it only shifts how they
        # stack against neighbours.
        if len(members) < 3:
            continue
        left = min(rects[index][0] for index in members)
        top = min(rects[index][1] for index in members)
        right = max(rects[index][0] + rects[index][2] for index in members)
        bottom = max(rects[index][1] + rects[index][3] for index in members)

        outsiders: list[int] = []
        for index in range(len(elements)):
            if index == container or rects[index] is None:
                continue
            if belongs_to(index, container):
                continue
            # An ancestor is the layer underneath, not an intruder.
            if _rect_contains(rects[index], own, tolerance=2):
                continue
            outsiders.append(index)
        if not outsiders:
            continue

        bands = {
            "bottom": (own[1] + own[3] - bottom, bottom, own[1] + own[3]),
            "top": (top - own[1], own[1], top),
            "left": (left - own[0], own[0], left),
            "right": (own[0] + own[2] - right, right, own[0] + own[2]),
        }
        for edge, (slack, start, end) in bands.items():
            if slack <= 2:
                continue
            limit: int | None = None
            for index in outsiders:
                other = rects[index]
                if edge in ("top", "bottom"):
                    centre = other[1] + other[3] / 2
                    if not start <= centre <= end:
                        continue
                    if min(own[0] + own[2], other[0] + other[2]) - max(
                        own[0], other[0]
                    ) <= 0:
                        continue
                    candidate = other[1] if edge == "bottom" else other[1] + other[3]
                else:
                    centre = other[0] + other[2] / 2
                    if not start <= centre <= end:
                        continue
                    if min(own[1] + own[3], other[1] + other[3]) - max(
                        own[1], other[1]
                    ) <= 0:
                        continue
                    candidate = other[0] if edge == "right" else other[0] + other[2]
                limit = candidate if limit is None else (
                    min(limit, candidate) if edge in ("bottom", "right") else max(limit, candidate)
                )
            if limit is None and pixels is not None:
                spans = {
                    "bottom": ((bottom, own[1] + own[3]), (own[0], own[0] + own[2])),
                    "top": ((own[1], top), (own[0], own[0] + own[2])),
                    "right": ((right, own[0] + own[2]), (own[1], own[1] + own[3])),
                    "left": ((own[0], left), (own[1], own[1] + own[3])),
                }
                band, cross = spans[edge]
                candidate = _pixel_limit(edge, band, cross, pixels)
                # Only a container that paints the page colour (or nothing) may
                # be resized on pixel evidence alone: for anything else the box
                # is also a visible rectangle, and moving it changes the picture.
                # The move is capped to a small correction, because a large one
                # is a mis-detected content edge, not slack.
                if candidate is not None and _paints_page(
                    elements[container], background
                ):
                    distance = abs(candidate - (own[1] if edge in ("top", "bottom") else own[0]))
                    if distance <= 24:
                        limit = candidate
            if limit is None:
                continue
            if edge == "bottom":
                new_end = min(own[1] + own[3], max(bottom, limit))
                if new_end < own[1] + own[3]:
                    elements[container]["height"] = new_end - own[1]
                    trimmed += 1
            elif edge == "top":
                new_start = max(own[1], min(top, limit))
                if new_start > own[1]:
                    elements[container]["y"] = new_start
                    elements[container]["height"] = own[1] + own[3] - new_start
                    trimmed += 1
            elif edge == "right":
                new_end = min(own[0] + own[2], max(right, limit))
                if new_end < own[0] + own[2]:
                    elements[container]["width"] = new_end - own[0]
                    trimmed += 1
            else:
                new_start = max(own[0], min(left, limit))
                if new_start > own[0]:
                    elements[container]["x"] = new_start
                    elements[container]["width"] = own[0] + own[2] - new_start
                    trimmed += 1
    return trimmed


_XY_TOLERANCE = 2


def _union_rect(
    indexes: list[int],
    rects: list[tuple[int, int, int, int] | None],
) -> tuple[int, int, int, int] | None:
    """Bounding box of a set of members."""
    boxes = [rects[index] for index in indexes if rects[index] is not None]
    if not boxes:
        return None
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return (left, top, right - left, bottom - top)


def _axis_bands(
    items: list[int],
    rects: list[tuple[int, int, int, int] | None],
    axis: str,
) -> list[list[int]]:
    """Split items into bands wherever a gutter separates them on ``axis``.

    A gutter is any positive distance between one box's end and the next
    box's start; two pixels of overlap still count as touching, because a
    measured border or a shared cell edge routinely overshoots by that much.
    """
    start_i, size_i = (0, 2) if axis == "x" else (1, 3)
    cross_i = 1 if axis == "x" else 0
    ordered = sorted(
        items, key=lambda index: (rects[index][start_i], rects[index][cross_i])
    )
    bands: list[list[int]] = []
    edge: int | None = None
    for index in ordered:
        rect = rects[index]
        start = rect[start_i]
        stop = start + rect[size_i]
        if edge is None or start >= edge - _XY_TOLERANCE:
            bands.append([index])
            edge = stop
        else:
            bands[-1].append(index)
            edge = max(edge, stop)
    return bands


def _cut_axis(
    items: list[int],
    rects: list[tuple[int, int, int, int] | None],
    axis: str,
) -> tuple[list[list[int]], list[int]] | None:
    """Try to cut along one axis.

    Returns the bands plus the elements skipped because they span the whole
    extent — a section background or a rule running edge to edge belongs to no
    single band, and leaving it in the projection makes every band overlap so
    the axis looks uncuttable.
    """
    union = _union_rect(items, rects)
    if union is None:
        return None
    span = union[2] if axis == "x" else union[3]
    size_i = 2 if axis == "x" else 3
    spanning = [index for index in items if rects[index][size_i] >= span * 0.92]
    skipped = set(spanning)
    body = [index for index in items if index not in skipped]
    if len(body) < 2:
        return None
    bands = _axis_bands(body, rects, axis)
    if len(bands) < 2:
        return None
    return bands, spanning


def _xy_cut(
    items: list[int],
    rects: list[tuple[int, int, int, int] | None],
    prefer: str = "y",
) -> tuple[list[int], str] | None:
    """Recursive XY-cut: reading order plus the axis of the first cut.

    Rows first, then columns, then recurse into every band on the other axis.
    A band that will not cut either way is a free collage and keeps its
    reading order — it still belongs to the frame, it just has no Auto Layout
    story to tell.
    """
    if len(items) <= 1:
        return (list(items), "") if items else None
    axes = ("y", "x") if prefer == "y" else ("x", "y")
    for axis in axes:
        cut = _cut_axis(items, rects, axis)
        if cut is None:
            continue
        bands, spanning = cut
        other = "x" if axis == "y" else "y"
        ordered: list[int] = sorted(
            spanning, key=lambda index: (rects[index][1], rects[index][0])
        )
        for band in bands:
            deeper = _xy_cut(band, rects, other)
            if deeper is None:
                ordered.extend(
                    sorted(band, key=lambda index: (rects[index][1], rects[index][0]))
                )
            else:
                ordered.extend(deeper[0])
        return ordered, axis
    return None


def _xy_cut_layout(
    parent: tuple[int, int, int, int],
    children: list[int],
    rects: list[tuple[int, int, int, int] | None],
) -> tuple[dict[str, Any], list[int]] | None:
    """General layout candidate: recursive orthogonal splitting.

    Replaces the row-band recogniser, which needed every row to be a clean
    grid of non-crossing cells — a table with a merged header or a banner with
    a badge would fail it.  XY-cut only asks for a gutter somewhere, so those
    fall out of the same recursion with no special case.
    """
    usable = [index for index in children if rects[index] is not None]
    if len(usable) < 2:
        return None
    parent_area = max(1, parent[2] * parent[3])
    body = [
        index
        for index in usable
        if rects[index][2] * rects[index][3] < parent_area * 0.5
    ]
    if len(body) < 2:
        return None
    cut = _xy_cut(body, rects)
    if cut is None:
        return None
    ordered, axis = cut
    if not axis:
        return None
    bands = _cut_axis(body, rects, axis)
    if bands is None:
        return None
    union = _union_rect(body, rects) or parent
    gaps: list[int] = []
    previous_end: int | None = None
    for band in bands[0]:
        band_union = _union_rect(band, rects)
        if band_union is None:
            continue
        start = band_union[0] if axis == "x" else band_union[1]
        size = band_union[2] if axis == "x" else band_union[3]
        if previous_end is not None:
            gaps.append(max(0, start - previous_end))
        previous_end = start + size
    spacing = int(round(sorted(gaps)[len(gaps) // 2])) if gaps else 0
    spec: dict[str, Any] = {
        "mode": "VERTICAL" if axis == "y" else "HORIZONTAL",
        "itemSpacing": spacing,
        "primaryAlign": "MIN",
        "counterAlign": "MIN",
        "paddingTop": max(0, union[1] - parent[1]),
        "paddingBottom": max(0, (parent[1] + parent[3]) - (union[1] + union[3])),
        "paddingLeft": max(0, union[0] - parent[0]),
        "paddingRight": max(0, (parent[0] + parent[2]) - (union[0] + union[2])),
        "source": "geometry-xy-cut",
        "bandCount": len(bands[0]),
    }
    ordered_all = list(ordered)
    seen = set(ordered_all)
    for index in children:
        if index not in seen:
            ordered_all.append(index)
    return spec, ordered_all


def _widen_to_members(
    owner: int,
    children: list[int],
    elements: list[dict[str, Any]],
    rects: list[tuple[int, int, int, int] | None],
) -> tuple[int, int, int, int] | None:
    """Make a frame's rectangle cover what it owns.

    Ownership is decided with a one-pixel tolerance, so a grid line can belong
    to a container it only touches.  One pixel of that is absorbed by the
    renderer's own edge slack; anything more means the frame is measurably
    smaller than its contents, and a child outside its frame gets clipped away.
    Growing the frame is the least invasive repair, and nothing moves.

    Beyond a few pixels this is not slack but a real mismatch, and is left to
    the renderer's gates.
    """
    base = rects[owner]
    union = _union_rect([owner, *children], rects)
    if base is None or union is None:
        return base
    if _rect_contains(base, union, tolerance=0):
        return base
    growth = max(
        base[0] - union[0],
        base[1] - union[1],
        (union[0] + union[2]) - (base[0] + base[2]),
        (union[1] + union[3]) - (base[1] + base[3]),
    )
    if growth <= 1 or growth > 8:
        return base
    element = elements[owner]
    element["x"], element["y"] = union[0], union[1]
    element["width"], element["height"] = union[2], union[3]
    rects[owner] = union
    return union


TABLE_TEXT_PREFIXES = ("table-header:", "table-cell:")
#: A table cell never carries a display-size font.  Below the floor a glyph is
#: unreadable; above the ceiling the "size" came from a box, not from ink.
TABLE_FONT_MIN = 9.0
TABLE_FONT_MAX = 34.0
#: Ink height to font size.  CJK ink fills roughly the em box, so the measured
#: stroke height is a good estimate of the type size, as ``perception_contract``
#: already assumes when it takes over from a measured ink box.
INK_TO_FONT = 0.95


def _measure_ink(
    pixels,
    box: tuple[int, int, int, int],
):
    """Bounding box of the ink inside ``box``, in absolute pixels.

    The local background is taken per cell, so a header on a tinted row and a
    value on white both work.  Anything below a few pixels of coverage is noise
    and reported as missing rather than as a two-pixel "line".
    """
    if pixels is None:
        return None
    try:
        import numpy as np
    except Exception:  # pragma: no cover
        return None
    x, y, width, height = box
    left, top = max(0, x), max(0, y)
    right = min(int(pixels.shape[1]), x + width)
    bottom = min(int(pixels.shape[0]), y + height)
    if right - left < 4 or bottom - top < 4:
        return None
    crop = pixels[top:bottom, left:right]
    background = np.median(crop.reshape(-1, 3), axis=0)
    mask = np.max(np.abs(crop - background), axis=2) > 36
    if int(mask.sum()) < 8:
        return None
    rows = np.where(mask.any(axis=1))[0]
    columns = np.where(mask.any(axis=0))[0]
    return (
        left + int(columns.min()),
        top + int(rows.min()),
        int(columns.max() - columns.min() + 1),
        int(rows.max() - rows.min() + 1),
    )


#: A row needs at least this many cells agreeing with OCR before its columns
#: are rebuilt, and at least one of them this far out of place.
ROW_REPARTITION_MIN_MATCHES = 2
ROW_REPARTITION_MIN_SHIFT = 40
#: Cells within this many pixels of each other vertically are one row.
ROW_BAND = 14
#: A row's cells must also start at the same height.  A data band whose cells
#: are scattered over 60px is a partially detected row, and re-slicing it would
#: invent columns between cells that belong to different lines.
ROW_SPREAD_MAX = 24
#: Narrowest column a rebuilt row may produce.  Below this a CJK glyph no longer
#: fits and the cell wraps into a vertical strip.
ROW_REPARTITION_MIN_WIDTH = 40
#: How far a text may drift from the line OCR read for it before the drift is
#: the defect rather than the OCR.
TEXT_SNAP_MIN_SHIFT = 40
#: Similarity at which two readings are the same sentence.  Long lines read by
#: OCR lose their punctuation and gain stray characters, so this cannot be an
#: equality test.
TEXT_SNAP_SIMILARITY = 0.85


def _snap_text_to_ocr(
    elements: list[dict[str, Any]],
    observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Put a drifted sentence back on the line it was read from.

    A text box is sometimes measured from the wrong origin — the wecom-modal
    paragraph came back 800px to the right in a 55px box, so it printed straight
    through the dialog's border.  OCR read the same words at their true place on
    the same line; when the wording agrees and the line agrees, the horizontal
    coordinate is simply wrong.

    Only x moves.  Y was already right (the line matched), and a cell's columns
    are the table pass's business, not this one's.
    """
    if not observations:
        return 0
    from src.app.services.structure.fidelity.contracts import owner_text_similarity

    lines = _ocr_lines(observations)
    if not lines:
        return 0
    snapped = 0
    for element in elements:
        # A label is a label whether the plan called it text or wrapped it in a
        # control: the wecom sentence that ran through the dialog's border came
        # back as a one-line "input".
        if str(element.get("type")) not in {"text", "button", "input"}:
            continue
        if not element.get("text"):
            continue
        if str(element.get("contentRef") or element.get("id") or "").startswith(
            TABLE_TEXT_PREFIXES
        ):
            continue
        box = _layout_rect(element)
        if box is None:
            continue
        # Only a box too narrow for its own words is evidence of a bad origin.
        # A label that already fits its box was measured fine, and the line OCR
        # read around it may simply be a longer one.
        left, right = _rendered_span(element)
        if right - left <= max(box[2] * 1.3, box[2] + 8):
            continue
        text = str(element.get("text") or "").strip()
        centre_y = box[1] + box[3] / 2
        best: tuple[float, tuple[int, int, int, int]] | None = None
        for line_text, line_box in lines:
            if abs((line_box[1] + line_box[3] / 2) - centre_y) > max(
                box[3] * 0.6, ROW_SPREAD_MAX
            ):
                continue
            if owner_text_similarity(line_text, text) < TEXT_SNAP_SIMILARITY:
                continue
            distance = abs(line_box[0] - box[0])
            if best is None or distance < best[0]:
                best = (distance, line_box)
        if best is None or best[0] <= TEXT_SNAP_MIN_SHIFT:
            continue
        element["x"] = best[1][0]
        element["width"] = max(1, best[1][2])
        # The box no longer decides where the line starts: OCR does.  A right
        # or centre alignment would keep the words pinned to the wrong edge of
        # the corrected box.
        style = element.get("style")
        if isinstance(style, dict):
            style["textAlign"] = "left"
        # A control carries the line box it was measured with, and the renderer
        # lays the label out from *that*, not from x.  Leaving it behind pinned
        # the corrected sentence back to the old origin.
        for key in ("textBox", "textEmBox"):
            box_value = element.get(key)
            if isinstance(box_value, (list, tuple)) and len(box_value) == 4:
                element[key] = [
                    best[1][0],
                    best[1][1],
                    best[1][2],
                    best[1][3],
                ]
        snapped += 1
    return snapped


#: A solid coloured bar: thin, wide, saturated, and filled edge to edge.  A
#: rule is unsaturated, a border is thinner, a highlighted row is taller.
BAR_MIN_HEIGHT = 6
BAR_MAX_HEIGHT = 22
BAR_MIN_WIDTH = 100
BAR_MIN_ASPECT = 6.0
#: Saturation on the 0-255 scale.  A dark slate panel measures 83, a blue bar
#: around 200 — the floor has to sit between the two or every sidebar edge
#: becomes a "bar".
BAR_MIN_SATURATION = 110
BAR_MIN_VALUE = 40
BAR_FILL_RATIO = 0.7
#: Overlap with an element the plan already carries, above which the bar is
#: that element rather than a missing one.
BAR_EXISTING_IOU = 0.35
BAR_MAX_REGIONS = 8
#: A control has to be at least this far from its own words before the box is
#: treated as the error rather than a repeat of a label that is simply nearby.
CONTROL_REANCHOR_MIN_SHIFT = 80
#: How far a cell may sit from the OCR line it is matched to.  Its own words
#: are read within a couple of row heights; a line several rows away is a
#: different row's label that happens to read the same.
ROW_ATTACH_MAX = 160


def _table_roots(
    elements: list[dict[str, Any]],
) -> tuple[list[int | None], list[tuple[int, int, int, int] | None]]:
    """Owner chain plus, for each element, the table that contains it."""
    rects = [
        _layout_rect(element) if str(element.get("type")) in _LAYOUT_MEMBER_TYPES else None
        for element in elements
    ]
    containers = {
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) in ("container", "table")
    }
    owners = [
        _owner_index(rects, index, parent_candidates=containers) if rects[index] else None
        for index in range(len(elements))
    ]
    roots: list[int | None] = []
    for index in range(len(elements)):
        current = owners[index]
        seen: set[int] = set()
        found = None
        while current is not None and current not in seen:
            element = elements[current]
            if str(element.get("type")) == "table" or str(element.get("id") or "").startswith(
                "table-node:"
            ):
                found = current
                break
            seen.add(current)
            current = owners[current] if current < len(owners) else None
        roots.append(found)
    return roots, rects


def _repartition_table_rows(
    elements: list[dict[str, Any]],
    observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Rebuild one table row's columns from where its words actually are.

    A detected grid can put a row's columns at the extremes — the inventory
    header came back as 383 / 408 / 435 / 2492 / 2519 while the words are at
    626 / 844 / 1064 / 1274 / 1548 — leaving five labels in 25px columns and a
    pair swapped end for end.  Per-cell nudging cannot fix that: widening one
    cell pushes it into its neighbour and the renderer refuses the whole table
    (measured: inventory2 lost two frames).

    So the row is rebuilt as a whole.  Each cell takes its column from the
    midpoint between its own words and the next cell's words, the first column
    starts at the row's left edge and the last ends at its right edge.  The
    result is contiguous by construction, so no cell can overlap another.

    Only OCR whose centre lies inside the table is considered.  Without that
    filter a sidebar label that happens to share a word with a cell would drag
    a column out of the table entirely.
    """
    if not observations:
        return 0
    from src.app.services.structure.fidelity.contracts import (
        normalize_match_text,
        owner_text_similarity,
    )

    # Headers only.  A data row's columns must agree with the header's, and
    # re-slicing one independently produced columns that no longer lined up
    # with anything — on inventory2 it cost two frames.  The header is the row
    # that gets to define them.
    cells = [
        index
        for index, element in enumerate(elements)
        if str(element.get("contentRef") or element.get("id") or "").startswith(
            "table-header:"
        )
        and element.get("text")
    ]
    if len(cells) < ROW_REPARTITION_MIN_MATCHES:
        return 0
    roots, rects = _table_roots(elements)

    lines: list[tuple[str, tuple[int, int, int, int]]] = []
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        text = normalize_match_text(observation.get("text"))
        box = observation.get("bbox")
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            values = tuple(int(round(float(value))) for value in box)
        except (TypeError, ValueError):
            continue
        if values[2] <= 0 or values[3] <= 0:
            continue
        lines.append((text, values))  # type: ignore[arg-type]

    # Group by where the words are, not by where the cells currently sit.  A
    # half-corrected row has some cells on the real baseline and others still
    # on the grid's, and grouping by the cell would split one row in two.
    #
    # The table is taken from the *words*, not from the cell: a cell measured
    # below the table's own rectangle has no table in its owner chain at all,
    # and that is exactly the label that stays adrift (inventory2's "失效日期",
    # 112px under its row).  Its OCR line is inside the table, so the line knows
    # where the cell belongs even though the cell does not.
    tables = [
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "table"
        or str(element.get("id") or "").startswith("table-node:")
    ]

    def table_at(line_box: tuple[int, int, int, int]) -> int | None:
        centre_x = line_box[0] + line_box[2] / 2
        centre_y = line_box[1] + line_box[3] / 2
        best: tuple[int, int] | None = None
        for table in tables:
            box = rects[table]
            if box is None:
                continue
            if not (
                box[0] <= centre_x <= box[0] + box[2]
                and box[1] <= centre_y <= box[1] + box[3]
            ):
                continue
            area = box[2] * box[3]
            if best is None or area < best[0]:
                best = (area, table)
        return best[1] if best else None

    bands: dict[tuple[int, int], list[tuple[int, tuple[int, int, int, int]]]] = {}
    for index in cells:
        box = rects[index]
        if box is None:
            continue
        text = normalize_match_text(elements[index].get("text"))
        if not text:
            continue
        best = None
        for line_text, line_box in lines:
            if line_text != text and owner_text_similarity(line_text, text) < 0.85:
                continue
            if abs((line_box[1] + line_box[3] / 2) - (box[1] + box[3] / 2)) > ROW_ATTACH_MAX:
                continue
            owner = table_at(line_box)
            if owner is None:
                # Nothing in the picture claims these words: fall back to the
                # cell's own table, and only if it really contains them.
                owner = roots[index]
                table_box = rects[owner] if owner is not None else None
                centre_x = line_box[0] + line_box[2] / 2
                centre_y = line_box[1] + line_box[3] / 2
                if table_box is None or not (
                    table_box[0] <= centre_x <= table_box[0] + table_box[2]
                    and table_box[1] <= centre_y <= table_box[1] + table_box[3]
                ):
                    continue
            # Nearest line on both axes, weighted towards y: two tables can
            # carry the same header words at the same x, and only the row they
            # sit on tells them apart.
            score = abs(
                (line_box[1] + line_box[3] / 2) - (box[1] + box[3] / 2)
            ) + 0.25 * abs((line_box[0] + line_box[2] / 2) - (box[0] + box[2] / 2))
            if best is None or score < best[0]:
                best = (score, line_box, owner)
        if best is None:
            continue
        bands.setdefault((best[2], int(round(best[1][1] / ROW_BAND))), []).append(
            (index, best[1])
        )

    rebuilt = 0
    column_plans: dict[int, list[int]] = {}
    for (root, _band), group in bands.items():
        if len(group) < ROW_REPARTITION_MIN_MATCHES:
            continue
        table_box = rects[root]
        if table_box is None:
            continue
        members = [index for index, _line in group]
        # The words decide whether these cells are one row.  Where the *cells*
        # were measured is the thing being repaired, so a cell sitting a
        # hundred pixels below its own words is an outlier to pull back, not a
        # reason to leave the whole row mis-columned — that is how the
        # inventory2 header kept five squeezed columns and one label adrift.
        line_tops = [line[1] for _index, line in group]
        if max(line_tops) - min(line_tops) > ROW_SPREAD_MAX:
            continue
        matches = group
        shift = max(
            abs((rects[index][0] + rects[index][2] / 2) - (line[0] + line[2] / 2))
            for index, line in matches
        )
        vertical = max(abs(rects[index][1] - line[1]) for index, line in matches)
        if shift <= ROW_REPARTITION_MIN_SHIFT and vertical <= ROW_REPARTITION_MIN_SHIFT:
            continue

        matches.sort(key=lambda pair: pair[1][0])
        cell_tops = sorted(rects[index][1] for index in members)
        top = cell_tops[len(cell_tops) // 2]
        inliers = [
            index for index in members if abs(rects[index][1] - top) <= ROW_SPREAD_MAX
        ]
        if not inliers:
            continue
        bottom = max(rects[index][1] + rects[index][3] for index in inliers)

        left = min(rects[index][0] for index in members)
        right = max(rects[index][0] + rects[index][2] for index in members)
        left = max(left, table_box[0])
        right = min(right, table_box[0] + table_box[2])
        if right - left < ROW_REPARTITION_MIN_WIDTH * len(matches):
            continue
        # Midpoints between neighbouring words, walked left to right and forced
        # to stay at least one readable column apart.  The row is then a
        # partition by construction: `cell[i].right == cell[i+1].left`, nothing
        # overlaps, and nothing leaves the table.
        boundaries = [left]
        for position in range(len(matches) - 1):
            first = matches[position][1]
            second = matches[position + 1][1]
            boundary = (first[0] + first[2] + second[0]) // 2
            boundaries.append(max(boundary, boundaries[-1] + ROW_REPARTITION_MIN_WIDTH))
        boundaries.append(right)
        if boundaries[-1] < boundaries[-2] + ROW_REPARTITION_MIN_WIDTH:
            continue

        for position, (index, _line) in enumerate(matches):
            element = elements[index]
            element["x"] = boundaries[position]
            element["width"] = max(1, boundaries[position + 1] - boundaries[position])
            element["y"] = top
            element["height"] = max(18, bottom - top)
            style = element.get("style")
            if isinstance(style, dict):
                style["textAlign"] = "center"
            rebuilt += 1
        column_plans[root] = boundaries

    rebuilt += _apply_column_plans(elements, rects, roots, lines, column_plans)
    return rebuilt


def _apply_column_plans(
    elements: list[dict[str, Any]],
    rects: Sequence[tuple[int, int, int, int] | None],
    roots: Sequence[int | None],
    lines: Sequence[tuple[str, tuple[int, int, int, int]]],
    column_plans: Mapping[int, list[int]],
) -> int:
    """Lay a table's data rows out on the columns its header just defined.

    Repairing the header alone leaves the body where the grid put it: in the
    inventory2 first table the five values stayed in 20px boxes hard against
    the table's edges and painted as a smudge under 生产日期/失效日期.  The
    header is the row that knows the columns; the body only has to keep its own
    left-to-right order.

    Order is all a body row can be trusted for.  OCR says where the sequence
    *starts* — the cells it reads land on known columns — and the offset those
    agree on carries the rest, including values no OCR line ever saw.
    """
    if not column_plans:
        return 0
    from src.app.services.structure.fidelity.contracts import (
        normalize_match_text,
        owner_text_similarity,
    )

    grouped: dict[int, list[int]] = {}
    for index, element in enumerate(elements):
        if not str(element.get("contentRef") or "").startswith("table-cell:"):
            continue
        if not str(element.get("text") or "").strip():
            continue
        root = roots[index] if index < len(roots) else None
        box = rects[index]
        if root is None or root not in column_plans or box is None:
            continue
        grouped.setdefault(root, []).append(index)

    laid_out = 0
    for root, members in grouped.items():
        boundaries = column_plans[root]
        columns = len(boundaries) - 1
        if columns < 2:
            continue
        members.sort(key=lambda index: rects[index][1])  # type: ignore[index]
        rows: list[list[int]] = []
        for index in members:
            top = rects[index][1]  # type: ignore[index]
            if rows and abs(top - rects[rows[-1][0]][1]) <= ROW_SPREAD_MAX:  # type: ignore[index]
                rows[-1].append(index)
            else:
                rows.append([index])
        for row in rows:
            if len(row) < 2:
                continue
            ordered = sorted(row, key=lambda index: rects[index][0])  # type: ignore[index]
            anchors: list[int] = []
            for rank, index in enumerate(ordered):
                text = normalize_match_text(elements[index].get("text"))
                box = rects[index]
                if not text or box is None:
                    continue
                centre = box[0] + box[2] / 2
                row_centre = box[1] + box[3] / 2
                best: tuple[float, int] | None = None
                for line_text, line_box in lines:
                    if line_text != text and owner_text_similarity(line_text, text) < 0.85:
                        continue
                    if abs((line_box[1] + line_box[3] / 2) - row_centre) > ROW_ATTACH_MAX:
                        continue
                    column = _column_of(line_box[0] + line_box[2] / 2, boundaries)
                    if column is None:
                        continue
                    distance = abs((line_box[0] + line_box[2] / 2) - centre)
                    if best is None or distance < best[0]:
                        best = (distance, column)
                if best is not None:
                    anchors.append(best[1] - rank)
            if len(anchors) < 2:
                continue
            anchors.sort()
            offset = anchors[len(anchors) // 2]
            # The sequence has to agree with the words, or the row is not a
            # row — a merged cell or a second line would land on nonsense.
            if sum(1 for value in anchors if abs(value - offset) <= 1) < len(anchors) - 1:
                continue
            top = min(rects[index][1] for index in row)  # type: ignore[index]
            bottom = max(rects[index][1] + rects[index][3] for index in row)  # type: ignore[index]
            width_rows: list[tuple[int, int, int, int]] = []
            for rank, index in enumerate(ordered):
                column = rank + offset
                if not 0 <= column < columns:
                    continue
                width_rows.append(
                    (
                        index,
                        boundaries[column],
                        max(1, boundaries[column + 1] - boundaries[column]),
                        column,
                    )
                )
            # Overlapping assignments mean the offset is wrong for this row.
            seen: set[int] = set()
            if any(column in seen or seen.add(column) for _i, _x, _w, column in width_rows):
                continue
            for index, x, width, _column in width_rows:
                element = elements[index]
                element["x"] = x
                element["width"] = width
                element["y"] = top
                element["height"] = max(18, bottom - top)
                style = element.get("style")
                if isinstance(style, dict):
                    style["textAlign"] = "center"
                laid_out += 1
    return laid_out


def _column_of(centre: float, boundaries: Sequence[int]) -> int | None:
    for column in range(len(boundaries) - 1):
        if boundaries[column] <= centre <= boundaries[column + 1]:
            return column
    return None


def _fit_table_text(
    elements: list[dict[str, Any]],
    observations: Sequence[Mapping[str, Any]] | None,
    pixels,
) -> int:
    """Size table text by its ink, not by the cell it sits in.

    A cell box is a grid interval.  When the grid is coarse — a narrow column
    that spans two rows, a header band measured 73px tall — deriving the font
    from the box height produces 40-55px type in a 20px column, which then
    wraps one glyph per line.  Ink is the only honest measure: the OCR line
    when the same words were read, otherwise the foreground mask inside the
    cell itself.

    Geometry is left alone on purpose: widening a cell to its ink pushes it
    over a neighbour, and the renderer then refuses the whole table for
    covering a stranger — measured on inventory2, two frames went that way.
    A column narrower than its own text is a grid problem, and shrinking the
    type is the part that can be fixed without moving anything.
    """
    cells = [
        element
        for element in elements
        if str(element.get("contentRef") or element.get("id") or "").startswith(
            TABLE_TEXT_PREFIXES
        )
        and element.get("text")
    ]
    if not cells:
        return 0
    from src.app.services.structure.fidelity.contracts import normalize_match_text

    lines: list[tuple[str, tuple[int, int, int, int]]] = []
    for observation in observations or []:
        if not isinstance(observation, Mapping):
            continue
        text = normalize_match_text(observation.get("text"))
        box = observation.get("bbox")
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            values = tuple(int(round(float(value))) for value in box)
        except (TypeError, ValueError):
            continue
        if values[2] <= 0 or values[3] <= 0:
            continue
        lines.append((text, values))  # type: ignore[arg-type]

    resized = 0
    for element in cells:
        box = _layout_rect(element)
        if box is None:
            continue
        text = normalize_match_text(element.get("text"))
        ink = None
        for line_text, line_box in lines:
            if line_text == text:
                ink = line_box
                break
        if ink is None:
            ink = _measure_ink(pixels, box)
        if ink is None:
            continue
        font = max(TABLE_FONT_MIN, min(TABLE_FONT_MAX, round(ink[3] * INK_TO_FONT * 4) / 4))
        style = element.get("style")
        if not isinstance(style, dict):
            continue
        style["fontSize"] = font
        style["lineHeight"] = max(
            int(round(font * 1.35)), int(style.get("lineHeight") or 0)
        )
        resized += 1

    # A row of cells shares one type size.  Anything far from the row median is
    # still a bad box measurement, and clamping to the median is what keeps a
    # single narrow cell from shouting.
    rows: dict[int, list[dict[str, Any]]] = {}
    for element in cells:
        style = element.get("style")
        if not isinstance(style, dict) or not style.get("fontSize"):
            continue
        rows.setdefault(int(round(element["y"] / 10.0)), []).append(element)
    for row in rows.values():
        if len(row) < 2:
            continue
        sizes = sorted(float(element["style"]["fontSize"]) for element in row)
        median = sizes[len(sizes) // 2]
        for element in row:
            size = float(element["style"]["fontSize"])
            if size > median * 1.35 or size < median * 0.7:
                element["style"]["fontSize"] = median
    return resized


TABLE_TEXT_PREFIXES = ("table-header:", "table-cell:")
#: Below this the grid is roughly right and moving cells only risks tearing a
#: table that already frames; above it the grid origin is plainly wrong.  The
#: inventory block is out by 272px, the tables that already work by 20-90px.
TABLE_ANCHOR_MIN_SHIFT = 100
TABLE_ANCHOR_MAX_SHIFT = 300
TABLE_ANCHOR_MIN_X_OVERLAP = 0.3


def _anchor_table_text(
    elements: list[dict[str, Any]],
    observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Move synthesized table text onto the OCR line that reads the same words.

    Table cells come out of a detected grid, so their box is the cell rather
    than the ink.  When the grid's origin is wrong, the words print one or two
    hundred pixels away from where the picture has them — in the inventory
    screenshot straight over the card rows above.  OCR already read those words
    at their real position and the grid has no authority over it.

    Only a displacement several cells agree on counts.  One cell that matches
    far away is usually the same label in another table, and following it tears
    a correct table apart; a shared offset is the signature of a bad grid
    origin, which is what this repairs.
    """
    if not observations:
        return 0
    from src.app.services.structure.fidelity.contracts import (
        normalize_match_text,
        owner_text_similarity,
    )

    lines: list[tuple[str, tuple[int, int, int, int]]] = []
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        text = str(observation.get("text") or "").strip()
        box = observation.get("bbox")
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            left, top, width, height = (int(round(float(value))) for value in box)
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        lines.append((normalize_match_text(text), (left, top, width, height)))
    if not lines:
        return 0

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
        _owner_index(rects, index, parent_candidates=containers) if rects[index] else None
        for index in range(len(elements))
    ]
    roots, table_rects = _table_roots(elements)

    matches: list[tuple[dict[str, Any], tuple[int, int, int, int], int]] = []
    for position, element in enumerate(elements):
        reference = str(element.get("contentRef") or element.get("id") or "")
        if not reference.startswith(TABLE_TEXT_PREFIXES):
            continue
        text = normalize_match_text(element.get("text"))
        box = _layout_rect(element)
        if not text or box is None:
            continue
        # A cell may only follow words read inside its own table.  A sidebar
        # label two panels away can share a cell's wording ("盘点单"), and
        # following it drags the cell — and with it the column — out of the
        # table.
        root = roots[position] if position < len(roots) else None
        table_box = table_rects[root] if root is not None else None
        if table_box is None:
            # Not under a declared table node: its owning container is the
            # table as far as this pass is concerned.
            owner = owners[position]
            table_box = rects[owner] if owner is not None else None
        if table_box is None:
            continue
        best: tuple[float, tuple[int, int, int, int]] | None = None
        for line_text, line_box in lines:
            centre_x = line_box[0] + line_box[2] / 2
            centre_y = line_box[1] + line_box[3] / 2
            if not (
                table_box[0] <= centre_x <= table_box[0] + table_box[2]
                and table_box[1] <= centre_y <= table_box[1] + table_box[3]
            ):
                continue
            if line_text != text and owner_text_similarity(line_text, text) < 0.9:
                continue
            # Both axes, weighted towards y: a wrong grid origin shifts a whole
            # block at once, so requiring x overlap would hide the very cells
            # that need moving.
            distance = abs(
                (box[1] + box[3] / 2) - (line_box[1] + line_box[3] / 2)
            ) + 0.25 * abs((box[0] + box[2] / 2) - (line_box[0] + line_box[2] / 2))
            if best is None or distance < best[0]:
                best = (distance, line_box)
        if best is None:
            continue
        line_box = best[1]
        vertical = line_box[1] - box[1]
        horizontal = abs((box[0] + box[2] / 2) - (line_box[0] + line_box[2] / 2))
        if max(abs(vertical), horizontal) > TABLE_ANCHOR_MAX_SHIFT:
            continue
        if abs(vertical) <= TABLE_ANCHOR_MIN_SHIFT and horizontal <= TABLE_ANCHOR_MIN_SHIFT:
            continue
        owner = owners[position]
        if owner is None or rects[owner] is None:
            continue
        # The cell may only move inside the box that owns it.  A target outside
        # means the container is wrong as well, and moving the text alone would
        # leave a member outside its frame — the renderer rejects the whole
        # frame for that.
        if not _rect_contains(rects[owner], line_box, tolerance=8):
            continue
        matches.append((element, line_box, vertical))

    if not matches:
        return 0
    buckets: dict[int, list[tuple[dict[str, Any], tuple[int, int, int, int]]]] = {}
    for element, line_box, vertical in matches:
        buckets.setdefault(int(round(vertical / 6.0)), []).append((element, line_box))
    dominant = max(buckets.values(), key=len)
    if len(dominant) < 2:
        return 0

    moved = 0
    for element, (left, top, width, height) in dominant:
        element["x"] = left
        element["y"] = top
        element["width"] = max(1, width)
        element["height"] = max(18, height)
        style = element.get("style")
        if isinstance(style, dict):
            style["textAlign"] = "start"
        moved += 1
    return moved

def _drop_page_coloured_shells(
    elements: list[dict[str, Any]],
    background: str,
) -> int:
    """Remove containers that paint the page colour and own nothing.

    A dialog screenshot is dimmed end to end, so the page background itself is
    the scrim colour and several boxes measure out as the same flat grey.  One
    of them lands on top of a real card and blocks its frame, yet it adds not a
    single pixel: it paints exactly what is already there.

    Only shell containers are removed — ones with no members of their own and
    no picture or text.  Anything that owns content still has a job.
    """
    target = str(background or "").strip().lower()
    if not target.startswith("#"):
        return 0
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
        _owner_index(rects, index, parent_candidates=containers) if rects[index] else None
        for index in range(len(elements))
    ]
    owning = {owner for owner in owners if owner is not None}
    doomed = [
        index
        for index in containers
        if index not in owning
        and str(elements[index].get("role") or "") != "text-backdrop"
        and not elements[index].get("imageBase64")
        and not elements[index].get("text")
        and str((elements[index].get("style") or {}).get("fillColor") or "")
        .strip()
        .lower()
        == target
    ]
    if not doomed:
        return 0
    drop = set(doomed)
    elements[:] = [
        element for index, element in enumerate(elements) if index not in drop
    ]
    return len(doomed)


COINCIDENT_TEXT_COVERAGE = 0.65
COINCIDENT_TEXT_SIMILARITY = 0.55
#: Two labels on one line whose boxes overlap less than this vertically are
#: stacked, not duplicated.
DUPLICATE_LINE_Y_OVERLAP = 0.6
#: A shared prefix/suffix this long (after stripping spaces and punctuation) is
#: one label read twice, even when the middle was cut differently.
DUPLICATE_LINE_AFFIX = 6
#: OCR confuses O/0 and l/1, so a pair that differs only in those glyphs is
#: still the same label.  Measured as a whole-string ratio.
DUPLICATE_LINE_SIMILARITY = 0.85
#: Share of the shorter label one unbroken run of the longer has to cover
#: before the two count as one label read twice.
DUPLICATE_LINE_COVERAGE = 0.72
#: Two prints of one label that miss each other by a few pixels: row overlap
#: and wording are enough, and the gap between them is what separates a ghost
#: from two real labels that happen to read the same (a Star button per card).
DUPLICATE_GHOST_Y_OVERLAP = 0.5
DUPLICATE_GHOST_SIMILARITY = 0.80
DUPLICATE_GHOST_REACH = 24
#: ... and their widths have to agree.  Two labels 20px apart with one three
#: times the width of the other are a title and its subtitle, not a ghost.
DUPLICATE_GHOST_WIDTH_RATIO = 0.4
#: A paragraph's wrapped remainder, modelled a second time: a suffix of at least
#: this many characters, starting a line below its host, inside the same span.
PARAGRAPH_TAIL_MIN_CHARS = 6
PARAGRAPH_TAIL_LENGTH_MARGIN = 8
PARAGRAPH_TAIL_MIN_DROP = 4
PARAGRAPH_TAIL_REACH = 12
PARAGRAPH_TAIL_HORIZONTAL_SHARE = 0.5
#: 文本落在补丁里的面积超过这个比例，它就是在给同一句话做第二次印刷。
PATCH_TEXT_COVER = 0.55
#: 小框被大框包含到这个比例，且用词对得上，就判为重影。
CONTAINED_TEXT_IOA = 0.55
CONTAINED_TEXT_SIMILARITY = 0.45
#: 小框被更大的文本框盖住这么多、且处在同一条基线带里，只可能是第二遍印刷。
NESTED_TEXT_SHARE = 0.6
NESTED_TEXT_LINE_TOLERANCE = 0.5
NESTED_TEXT_HEIGHT_RATIO = 2.5
#: OCR 观测与盒子的重叠达到这个比例，才算"这条线在说这个盒子"。
OCR_SUPPORT_OVERLAP = 0.3
#: 且这条线要复现节点自身这么多字符，才算它真的在说这句话。
OCR_SUPPORT_CHARS = 0.7
#: 文字压在与自己面积相当（不超过这个倍数）的图片上：那是芯片/图标，不是照片。
NESTED_IMAGE_AREA_RATIO = 3.0
#: 大号展示标题：字号下限，以及判定为展示字重所需的最小笔宽比。
DISPLAY_MIN_SIZE = 40.0
DISPLAY_STROKE_MIN = 0.075
#: Rebuilding a paragraph from its OCR lines: the seed has to sit on the node's
#: own first line, the chain grows downwards in the same column, and the joined
#: text has to agree with the model's wording this well before anything moves.
PARAGRAPH_REFLOW_MIN_CHARS = 20
PARAGRAPH_REFLOW_MAX_LINES = 6
PARAGRAPH_REFLOW_MIN_SIMILARITY = 0.85
PARAGRAPH_REFLOW_BAND_SHARE = 0.5
PARAGRAPH_REFLOW_MAX_GAP = 1.8
#: Channel distance under which text colour and surface are the same colour.
INK_MIN_CONTRAST = 30


def _text_cleanliness(element: Mapping[str, Any]) -> tuple[int, int]:
    """Prefer model wording over a raw OCR line, then the longer string."""
    return (
        0 if str(element.get("textBoxAuthority") or "") == "ocr-line" else 1,
        len(str(element.get("text") or "")),
    )


def _rendered_span(element: Mapping[str, Any]) -> tuple[int, int]:
    """Left edge and right edge a text will actually paint to.

    A synthesized cell can carry a 48px box for a forty-character line: the
    box is the measurement, the string is what lands on the canvas, and the
    renderer draws the whole line.  Comparing boxes alone therefore misses the
    double-printed rows, because the two boxes sit side by side while the two
    strings overlap by hundreds of pixels.
    """
    rect = _layout_rect(element)
    if rect is None:
        return (0, 0)
    left, _top, box_width, _box_height = rect
    text = str(element.get("text") or "")
    style = element.get("style") or {}
    try:
        font = float(style.get("fontSize") or 0.0)
    except (TypeError, ValueError):
        font = 0.0
    estimated = 0.0
    for char in text:
        estimated += font * (1.0 if ord(char) > 0x2E80 else 0.55)
    return (left, left + max(box_width, int(round(estimated))))


#: Glyphs OCR swaps for one another inside an identifier.  "WO5OS-OO5" and
#: "W0505-005" are the same rack, read twice by two engines; without folding,
#: one substituted letter looks like a different label and both get printed.
OCR_HOMOGLYPHS = str.maketrans(
    {
        "o": "0",
        "s": "5",
        "i": "1",
        "l": "1",
        "b": "8",
        "z": "2",
        "g": "6",
    }
)


def _fold_homoglyphs(text: str) -> str:
    """Collapse letter/digit pairs OCR cannot tell apart, for matching only."""
    return text.translate(OCR_HOMOGLYPHS)


def _ghost_gap(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> int:
    """Horizontal distance between two boxes, zero when they overlap."""
    return max(0, max(left[0], right[0]) - min(left[0] + left[2], right[0] + right[2]))


def _shared_affix(left: str, right: str) -> int:
    heads = 0
    for first, second in zip(left, right):
        if first != second:
            break
        heads += 1
    tails = 0
    for first, second in zip(reversed(left), reversed(right)):
        if first != second:
            break
        tails += 1
    return max(heads, tails)


def _label_match_ratio(left: str, right: str) -> float:
    """Share of the shorter string covered by one unbroken run of the longer.

    A prefix test is too brittle for OCR: "W0505" and "WO505" break it on the
    fourth character, and the rest of a twenty-character label matches exactly.
    The longest common run tolerates that single substituted glyph.
    """
    if not left or not right:
        return 0.0
    block = SequenceMatcher(
        None, left, right, autojunk=False
    ).find_longest_match(0, len(left), 0, len(right))
    return block.size / min(len(left), len(right))


def _ink_contrast(
    element: Mapping[str, Any],
    elements: Sequence[dict[str, Any]],
    background: str,
) -> int:
    """How far the text colour sits from the surface it is printed on.

    Two readings of one label can differ only in the colour each sampled, and
    one of them sampled the card instead of the ink: #fefffe words on a white
    row are there, and cannot be read.  The surface is the smallest container
    that holds the text; the page is the fallback.
    """
    style = element.get("style")
    if not isinstance(style, dict):
        return 0
    ink = _hex_rgb(str(style.get("textColor") or background))
    box = _layout_rect(element)
    if box is None:
        return 0
    surface = str(background or "")
    smallest = None
    for candidate in elements:
        if str(candidate.get("type")) != "container":
            continue
        if str(candidate.get("role") or "") == "text-backdrop":
            # A surface inferred from the pixels around a text cannot also
            # vouch for that text's colour — the two would agree by
            # construction, and a white reading on its own white row would
            # look readable because a nearby badge was sampled under it.
            continue
        fill = _opaque_fill(candidate)
        if not fill:
            continue
        other = _layout_rect(candidate)
        if other is None:
            continue
        # The whole text has to sit on the surface.  Testing the centre alone
        # let a badge under the middle of a long row label count as that
        # label's background, which made a near-white reading look readable.
        if not _rect_contains(other, box, tolerance=2):
            continue
        area = other[2] * other[3]
        if smallest is None or area < smallest[0]:
            smallest = (area, fill)
    if smallest is not None:
        surface = smallest[1]
    base = _hex_rgb(surface or background)
    return max(abs(one - two) for one, two in zip(ink, base))


def _preferred_copy(
    first: int,
    second: int,
    elements: Sequence[dict[str, Any]],
    background: str = "",
) -> int:
    """Which of two readings of one label survives.

    A readable reading beats an unreadable one: one of the pair may carry the
    colour of the surface it was measured against, which prints invisible.
    Otherwise the fuller string wins — a reading that swallowed the rest of the
    row still prints the words the shorter one has, while the shorter one drops
    them.  On equal wording the box that fits its own text better wins, because
    a 48px box around a 400px line is a measurement error and its x is not
    trustworthy.
    """
    one = str(elements[first].get("text") or "")
    two = str(elements[second].get("text") or "")
    first_contrast = _ink_contrast(elements[first], elements, background)
    second_contrast = _ink_contrast(elements[second], elements, background)
    if (first_contrast >= INK_MIN_CONTRAST) != (second_contrast >= INK_MIN_CONTRAST):
        return first if first_contrast >= INK_MIN_CONTRAST else second
    if len(one) != len(two):
        return first if len(one) > len(two) else second

    def fit(index: int, text: str) -> float:
        rect = _layout_rect(elements[index])
        if rect is None or not text:
            return 0.0
        left, right = _rendered_span(elements[index])
        span = max(1, right - left)
        return min(rect[2], span) / span

    return first if fit(first, one) >= fit(second, two) else second


def _drop_coincident_texts(
    elements: list[dict[str, Any]],
    background: str = "",
) -> int:
    """Remove a label that a later stage measured again over the same words.

    Table synthesis writes header cells straight from the detected grid, while
    OCR reads the same words as a short line.  They are produced by different
    stages, so the stage that merges text never sees the pair; the export then
    prints one string on top of the other.  Two text boxes covering the same
    area and agreeing on the wording are one label — the poorer copy goes.

    Coverage, not IoU: one box is usually a full-width cell and the other the
    ink-tight line inside it, which keeps IoU low while the smaller box is
    almost entirely covered.

    Two readings of one row can also land *side by side*: the label box was
    measured narrow, the renderer prints the whole line from it, and the line
    runs straight over its own twin.  Coverage never fires there — the boxes do
    not overlap.  So a pair on the same line whose normalised strings share a
    prefix, a suffix, or one contains the other, is compared on what it will
    paint rather than on what it was measured as.
    """
    from src.app.services.structure.fidelity.contracts import (
        normalize_owner_text,
        owner_text_similarity,
    )

    texts = [
        index
        for index, element in enumerate(elements)
        if element.get("type") == "text" and element.get("text")
    ]
    doomed: set[int] = set()
    for position, first in enumerate(texts):
        if first in doomed:
            continue
        first_badge = bool(elements[first].get("badgeLabel"))
        first_rect = _layout_rect(elements[first])
        if first_rect is None:
            continue
        for second in texts[position + 1 :]:
            if second in doomed:
                continue
            # A chip's own word and the row's reading of the same line are two
            # different objects and can live beside each other.  Two chip words
            # are not: one of them is a second print of the same label.
            if first_badge != bool(elements[second].get("badgeLabel")):
                continue
            second_rect = _layout_rect(elements[second])
            if second_rect is None:
                continue
            overlap_h = min(first_rect[1] + first_rect[3], second_rect[1] + second_rect[3]) - max(
                first_rect[1], second_rect[1]
            )
            if overlap_h <= 0:
                continue
            box_overlap_w = min(
                first_rect[0] + first_rect[2], second_rect[0] + second_rect[2]
            ) - max(first_rect[0], second_rect[0])
            first_left, first_right = _rendered_span(elements[first])
            second_left, second_right = _rendered_span(elements[second])
            overlap_w = min(first_right, second_right) - max(first_left, second_left)
            same_line = overlap_h / max(1, min(first_rect[3], second_rect[3]))
            if overlap_w <= 0:
                # Two prints of one label can miss each other by a few pixels:
                # the box was measured a little to the left and the copy a
                # little to the right, so nothing overlaps even though both
                # paint the same sentence.  Same row, same words, within
                # reading distance — one of them is a ghost.
                one_ghost = str(elements[first].get("text") or "")
                two_ghost = str(elements[second].get("text") or "")
                widths_agree = abs(first_rect[2] - second_rect[2]) <= max(
                    first_rect[2], second_rect[2]
                ) * DUPLICATE_GHOST_WIDTH_RATIO
                if (
                    same_line >= DUPLICATE_GHOST_Y_OVERLAP
                    and widths_agree
                    and owner_text_similarity(one_ghost, two_ghost)
                    >= DUPLICATE_GHOST_SIMILARITY
                    and _ghost_gap(first_rect, second_rect) <= DUPLICATE_GHOST_REACH
                ):
                    keep = _preferred_copy(first, second, elements, background)
                    if keep == first:
                        doomed.add(second)
                        continue
                    doomed.add(first)
                    break
                continue
            coverage = (box_overlap_w * overlap_h) / max(
                1, min(first_rect[2] * first_rect[3], second_rect[2] * second_rect[3])
            ) if box_overlap_w > 0 else 0.0
            # Same line, one string inside the other: one reading merged the
            # whole row while another reported a single field of it.  The long
            # one already prints every word, so the short copy is redundant —
            # no need for the coverage threshold, the y agreement carries it.
            if same_line >= DUPLICATE_LINE_Y_OVERLAP:
                one = str(elements[first].get("text") or "").strip()
                two = str(elements[second].get("text") or "").strip()
                key_one = _fold_homoglyphs(normalize_owner_text(one))
                key_two = _fold_homoglyphs(normalize_owner_text(two))
                if one and two and (
                    one in two or two in one or key_one in key_two or key_two in key_one
                ):
                    shorter = one if len(one) <= len(two) else two
                    # A number on its own is a value, not a shortened label:
                    # the "100" cell in a quantity column is inside the row's
                    # prose and still needs to print.  The same number twice on
                    # the same spot is a double print, and that is not a value.
                    if one == two or (len(shorter) >= 4 and not shorter.isdigit()):
                        keep = _preferred_copy(first, second, elements, background)
                        if keep == first:
                            doomed.add(second)
                            continue
                        doomed.add(first)
                        break
                if key_one and key_two and not (
                    key_one in key_two or key_two in key_one
                ):
                    shared = _shared_affix(key_one, key_two)
                    alike = owner_text_similarity(key_one, key_two)
                    covered = _label_match_ratio(key_one, key_two)
                    if (
                        shared >= DUPLICATE_LINE_AFFIX
                        or alike >= DUPLICATE_LINE_SIMILARITY
                        or covered >= DUPLICATE_LINE_COVERAGE
                    ) and min(len(key_one), len(key_two)) >= DUPLICATE_LINE_AFFIX:
                        keep = _preferred_copy(first, second, elements, background)
                        other = second if keep == first else first
                        doomed.add(other)
                        if keep == first:
                            continue
                        break
            if coverage < COINCIDENT_TEXT_COVERAGE:
                continue
            if (
                owner_text_similarity(
                    elements[first].get("text"), elements[second].get("text")
                )
                < COINCIDENT_TEXT_SIMILARITY
            ):
                continue
            if _text_cleanliness(elements[first]) >= _text_cleanliness(elements[second]):
                doomed.add(second)
            else:
                doomed.add(first)
                break
    if not doomed:
        return 0
    elements[:] = [
        element for index, element in enumerate(elements) if index not in doomed
    ]
    return len(doomed)


#: Names a vision model gives an icon, never words the page prints.  ``search``
#: and ``mail`` in a toolbar are the magnifier and the envelope; the screenshot
#: shows two glyphs, and a TEXT node made from the caption prints "search"
#: across the icon.  Support from OCR is what separates the two: if the words
#: are really on the page, some line reads them at that very spot.
ICON_DESCRIPTOR_WORDS = frozenset(
    {
        "search",
        "find",
        "mail",
        "envelope",
        "inbox",
        "menu",
        "hamburger",
        "kebab",
        "ellipsis",
        "close",
        "dismiss",
        "dropdown",
        "caret",
        "chevron",
        "arrow",
        "settings",
        "setting",
        "gear",
        "user",
        "avatar",
        "profile",
        "account",
        "filter",
        "funnel",
        "bell",
        "notification",
        "more",
        "plus",
        "minus",
        "add",
        "remove",
        "edit",
        "pencil",
        "delete",
        "trash",
        "refresh",
        "reload",
        "share",
        "download",
        "upload",
        "link",
        "home",
        "back",
        "forward",
        "expand",
        "collapse",
        "grid",
        "list",
        "calendar",
        "clock",
        "star",
        "heart",
        "bookmark",
        "cart",
        "help",
        "question",
        "spinner",
        "loading",
        "logo",
        "icon",
        "badge",
    }
)
#: An icon label is a caption on a glyph, so it lives in a glyph-sized box.
ICON_DESCRIPTOR_MAX_SIDE = 96
#: How far from the box OCR may read the same words and still count as proof
#: that they are printed on the page.
ICON_DESCRIPTOR_OCR_SLACK = 8
#: A gap this small is inside the glyph; the words start where the icon ends.
BADGE_ICON_GAP = 4
#: A badge is a chip: wide enough for a few words, never taller than a line.
BADGE_MAX_WIDTH = 260
BADGE_MAX_HEIGHT = 64
#: Share of a text or icon that a later-painted fill has to bury to count.
FILL_OCCLUSION_COVERAGE = 0.5
#: Colour distance under which a fill is "the page colour again".
PAGE_FILL_TOLERANCE = 10
#: A backdrop fragment is a panel-sized patch, not a stray chip.
PAGE_FRAGMENT_MIN_AREA = 40000


def _ocr_lines(
    observations: Sequence[Mapping[str, Any]] | None,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Normalised OCR text with its box, ready for matching."""
    from src.app.services.structure.fidelity.contracts import normalize_match_text

    lines: list[tuple[str, tuple[int, int, int, int]]] = []
    for observation in observations or ():
        if not isinstance(observation, Mapping):
            continue
        text = normalize_match_text(observation.get("text"))
        box = observation.get("bbox")
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            values = tuple(int(round(float(value))) for value in box)
        except (TypeError, ValueError):
            continue
        if values[2] <= 0 or values[3] <= 0:
            continue
        lines.append((text, values))  # type: ignore[arg-type]
    return lines


def _icon_descriptor(text: str) -> bool:
    """True when the whole string is a control/icon name, not prose."""
    words = [word for word in re.split(r"[^a-z]+", str(text or "").strip().lower()) if word]
    if not words or len(words) > 3:
        return False
    return all(word in ICON_DESCRIPTOR_WORDS for word in words)


def _has_ocr_support(
    text: str,
    box: tuple[int, int, int, int],
    lines: Sequence[tuple[str, tuple[int, int, int, int]]],
    *,
    slack: int = ICON_DESCRIPTOR_OCR_SLACK,
    threshold: float = 0.75,
) -> bool:
    from src.app.services.structure.fidelity.contracts import (
        normalize_match_text,
        owner_text_similarity,
    )

    key = normalize_match_text(text)
    if not key:
        return False
    for line_text, line_box in lines:
        if line_text != key and owner_text_similarity(line_text, key) < threshold:
            continue
        left = box[0] - slack
        top = box[1] - slack
        right = box[0] + box[2] + slack
        bottom = box[1] + box[3] + slack
        centre_x = line_box[0] + line_box[2] / 2
        centre_y = line_box[1] + line_box[3] / 2
        if left <= centre_x <= right and top <= centre_y <= bottom:
            return True
    return False


def _drop_icon_descriptor_labels(
    elements: list[dict[str, Any]],
    observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Strip captions the model invented for icons.

    A toolbar comes back as ``search``, ``mail``, ``menu``, ``dropdown``,
    ``close`` — five words that name five glyphs and appear nowhere in the
    screenshot.  Written as text they print on top of the glyphs and read as
    page content, which is worse than the icon alone.

    OCR decides.  When a line really reads those words at that spot (a "Star"
    button, an English "Search" label) the text stays; without that support the
    string is a semantic annotation and only the shape is kept.
    """
    if not elements:
        return 0
    lines = _ocr_lines(observations)
    doomed: set[int] = set()
    cleared = 0
    for index, element in enumerate(elements):
        kind = str(element.get("type") or "")
        if kind not in {"text", "button", "input"}:
            continue
        text = str(element.get("text") or "").strip()
        if not text or not text.isascii() or not _icon_descriptor(text):
            continue
        if str(element.get("contentRef") or element.get("id") or "").startswith(
            TABLE_TEXT_PREFIXES
        ):
            continue
        rect = _layout_rect(element)
        if rect is None or max(rect[2], rect[3]) > ICON_DESCRIPTOR_MAX_SIDE:
            continue
        if _has_ocr_support(text, rect, lines):
            continue
        if kind == "text":
            doomed.add(index)
        else:
            element["text"] = ""
            element.pop("controlValue", None)
        cleared += 1
    if doomed:
        elements[:] = [
            element for index, element in enumerate(elements) if index not in doomed
        ]
    return cleared


def _chip_ink(
    pixels,
    box: tuple[int, int, int, int],
    fill: str,
) -> tuple[str, float] | None:
    """Colour and height of the glyphs printed on a chip.

    The chip's fill is known, so the ink is whatever stands far from it.  The
    median of those pixels is the type colour, and their vertical extent gives
    the size the way the table pass measures it.
    """
    try:
        import numpy as np
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return None
    if pixels is None:
        return None
    frame_height, frame_width = pixels.shape[:2]
    x, y, width, height = box
    left, top = max(0, x), max(0, y)
    right = min(frame_width, x + width)
    bottom = min(frame_height, y + height)
    if right - left < 4 or bottom - top < 4:
        return None
    patch = pixels[top:bottom, left:right]
    target = np.asarray(_hex_rgb(fill), dtype=np.int16)
    distance = np.abs(patch - target).max(axis=2)
    strong = distance >= 60
    if int(strong.sum()) < 4:
        return None
    # The glyph's core, not its antialiased rim: the rim blends into the chip
    # and turns a white label pale green.
    core = distance >= max(60.0, float(distance.max()) * 0.8)
    ink = patch[core] if int(core.sum()) >= 4 else patch[strong]
    colour = "#%02x%02x%02x" % tuple(
        int(value) for value in np.median(ink.reshape(-1, 3), axis=0)
    )
    rows = np.where(strong.sum(axis=1) >= max(2, (right - left) // 20))[0]
    if rows.size == 0:
        return None
    return colour, float(rows.max() - rows.min() + 1)


#: A line OCR read this confidently is a line that is on the page.
OCR_PROMOTE_CONFIDENCE = 0.6
#: ... unless a node already paints that box: anything above this share of the
#: OCR line covered by an existing text node is "already there".
OCR_PROMOTE_MAX_IOA = 0.3
#: Two readings on one line whose strings agree this well are the same words.
OCR_PROMOTE_SIMILARITY = 0.6
#: ... and at this agreement the node is simply misplaced: the words are the
#: same, so OCR's box is where they belong and the node is moved, not copied.
OCR_PROMOTE_MOVE_SIMILARITY = 0.9


def _rows_share(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
    share: float = 0.5,
    reach: int = 160,
) -> bool:
    """Whether two boxes sit on one visual row, within reading distance."""
    rows = min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1])
    if rows < min(left[3], right[3]) * share:
        return False
    gap = max(left[0], right[0]) - min(left[0] + left[2], right[0] + right[2])
    return gap <= reach


def _promote_ocr_text(
    elements: list[dict[str, Any]],
    image_path: str,
    canvas: tuple[int, int] | None,
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Turn words OCR read into text nodes the plan never carried.

    The scene plan is a model's summary of a screenshot, and it skips whole nav
    bars, button labels and status lines: marketplace's 首页/模型广场/控制台,
    AtomGit's AtomCode/探索更多, review's 系统运行正常.  OCR read every one of
    them at its true coordinates, but until now those readings were only used to
    *correct* nodes that already existed — a missed line stayed missing.

    A confident line that no node covers is promoted as an ordinary text node.
    From there it follows the same path as any other: chip sampling paints the
    red/blue/black pill behind it, duplicate removal still applies, and the
    frame pass decides whether it belongs to a container.  Exact wording is
    skipped rather than merged — a line that overlaps a node, or repeats one on
    the same row, was already printed.
    """
    if not ocr_observations or not canvas:
        return 0
    from src.app.services.structure.fidelity.contracts import (
        normalize_match_text,
        owner_text_similarity,
    )

    width, height = canvas
    existing: list[tuple[tuple[int, int, int, int], str]] = []
    for element in elements:
        if str(element.get("type")) != "text" or not element.get("text"):
            continue
        rect = _layout_rect(element)
        if rect is None:
            continue
        existing.append((rect, normalize_match_text(element.get("text"))))

    added = 0
    for observation in ocr_observations:
        if not isinstance(observation, Mapping):
            continue
        try:
            confidence = float(observation.get("confidence") or 0)
        except (TypeError, ValueError):
            continue
        if confidence < OCR_PROMOTE_CONFIDENCE:
            continue
        text = str(observation.get("text") or "").strip()
        if not text or text.isdigit():
            continue
        if not any(character.isalnum() for character in text):
            continue
        box = observation.get("bbox")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            left, top, box_width, box_height = (int(value) for value in box)
        except (TypeError, ValueError):
            continue
        if box_width < 6 or box_height < 8:
            continue
        left = max(0, left)
        top = max(0, top)
        box_width = min(box_width, width - left)
        box_height = min(box_height, height - top)
        if box_width < 6 or box_height < 8:
            continue
        rect = (left, top, box_width, box_height)
        # A single glyph is only worth a node when it sits on a row that other
        # words already describe: the 起 beside a price, the 折 inside a badge.
        # A stray mark on its own is not a label.
        if len(text) < 2 and not any(
            _rows_share(rect, other_rect)
            for other_rect, _key in existing
        ):
            continue
        key = normalize_match_text(text)
        moved = False
        blocked = False
        for element in elements:
            if str(element.get("type")) != "text" or not element.get("text"):
                continue
            if str(element.get("imageMVP", {}).get("source")) == "ocr-promotion":
                continue
            other_rect = _layout_rect(element)
            if other_rect is None:
                continue
            rows = min(rect[1] + rect[3], other_rect[1] + other_rect[3]) - max(
                rect[1], other_rect[1]
            )
            if rows < min(rect[3], other_rect[3]) * 0.6:
                continue
            if (
                owner_text_similarity(element.get("text"), text)
                < OCR_PROMOTE_MOVE_SIMILARITY
            ):
                continue
            # Same words on the same row: this is the node that was measured in
            # the wrong place, and OCR is where it actually is.  Moving it is
            # the repair; adding a second copy prints the row twice.
            if abs(other_rect[0] - left) > 6 or abs(other_rect[2] - box_width) > 8:
                element["x"] = left
                element["y"] = top
                element["width"] = box_width
                element["height"] = box_height
                style = element.get("style")
                if isinstance(style, dict):
                    style["textAlign"] = "left"
                for name in ("textBox", "textEmBox"):
                    value = element.get(name)
                    if isinstance(value, (list, tuple)) and len(value) == 4:
                        element[name] = [left, top, box_width, box_height]
                moved = True
            else:
                blocked = True
            break
        if moved:
            continue
        if blocked:
            continue
        for other_rect, other_key in existing:
            if _overlap_share(rect, other_rect) >= OCR_PROMOTE_MAX_IOA:
                blocked = True
                break
            rows = min(rect[1] + rect[3], other_rect[1] + other_rect[3]) - max(
                rect[1], other_rect[1]
            )
            same_row = rows >= min(rect[3], other_rect[3]) * 0.6
            if not other_key or not key:
                continue
            # OCR reads a paragraph line by line while the plan writes it as one
            # box with different wrapping, so the same words can sit ten pixels
            # apart and still be one sentence.  Within a few line heights, one
            # string containing the other is a repeat, not a new label.
            near = abs(
                (rect[1] + rect[3] / 2) - (other_rect[1] + other_rect[3] / 2)
            ) <= max(rect[3], other_rect[3]) * 2.5
            if (same_row or near) and (key in other_key or other_key in key):
                blocked = True
                break
            if same_row and owner_text_similarity(other_key, key) >= OCR_PROMOTE_SIMILARITY:
                blocked = True
                break
        if blocked:
            continue
        digest = hashlib.sha1(
            f"{left}:{top}:{box_width}:{box_height}:{text}".encode("utf-8")
        ).hexdigest()[:16]
        node = {
            "id": f"text:ocr-{digest}",
            "type": "text",
            "role": "text",
            "bbox": [left, top, box_width, box_height],
            "text": text,
            "content_ref": f"text:ocr-{digest}",
        }
        element = _text_element(
            node,
            image_path=image_path,
            width=width,
            height=height,
            node_by_id={},
        )
        # The line was read, not described: it keeps OCR's own box.
        element["x"] = left
        element["y"] = top
        element["width"] = box_width
        element["height"] = box_height
        element.setdefault("imageMVP", {})["source"] = "ocr-promotion"
        elements.append(element)
        existing.append((rect, key))
        added += 1

    return added


def _restore_chip_labels(
    elements: list[dict[str, Any]],
    image_path: str,
    canvas: tuple[int, int] | None,
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Put the word back inside a badge whose label was absorbed by its row.

    A row reads two ways: "库位" on the green chip, and the whole line as one
    string.  The line wins the duplicate pass — it carries every word — and the
    chip is left empty: the badge is real, its word is missing.  OCR still has
    the chip's own reading at the chip's own coordinates, so the label is rebuilt
    from there, centred in the chip and inked in the chip's own type colour.
    """
    if not ocr_observations or not canvas:
        return 0
    pixels = _pixel_edges(image_path, canvas[0], canvas[1])
    lines: list[tuple[str, tuple[int, int, int, int]]] = []
    for observation in ocr_observations:
        if not isinstance(observation, Mapping):
            continue
        text = str(observation.get("text") or "").strip()
        box = observation.get("bbox")
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            lines.append((text, tuple(int(value) for value in box)))
        except (TypeError, ValueError):
            continue
    if not lines:
        return 0
    existing = [
        rect
        for rect in (
            _layout_rect(element)
            for element in elements
            if str(element.get("type")) == "text" and element.get("text")
        )
        if rect is not None
    ]
    restored = 0
    for element in list(elements):
        if str(element.get("role") or "") != "text-backdrop":
            continue
        chip = _layout_rect(element)
        if chip is None:
            continue
        if not (
            CHIP_MIN_WIDTH <= chip[2] <= CHIP_MAX_WIDTH and chip[3] <= CHIP_MAX_HEIGHT
        ):
            continue
        if any(_rect_contains(chip, other, tolerance=2) for other in existing):
            continue
        fill = _solid_fill(element)
        if not fill:
            continue
        best: tuple[float, str, tuple[int, int, int, int]] | None = None
        for text, line in lines:
            if not _rect_contains(chip, line, tolerance=3):
                continue
            share = _overlap_share(line, chip)
            if best is None or share > best[0]:
                best = (share, text, line)
        if best is None or best[0] < 0.5:
            continue
        ink = _chip_ink(pixels, best[2], fill)
        colour = ink[0] if ink else "#ffffff"
        height = ink[1] if ink else best[2][3] * 0.8
        size = min(max(height * INK_TO_FONT, TABLE_FONT_MIN), TABLE_FONT_MAX)
        width = best[2][2]
        digest = hashlib.sha1(
            f"{chip[0]}:{chip[1]}:{best[1]}".encode("utf-8")
        ).hexdigest()[:16]
        # A badge centres its word; the OCR box is the ink's own extent, so its
        # size is kept and only its origin is moved to the middle.
        box_x = chip[0] + (chip[2] - width) / 2
        box_y = chip[1] + (chip[3] - best[2][3]) / 2
        label = {
            "id": f"text:chip-{digest}",
            "type": "text",
            "x": int(round(box_x)),
            "y": int(round(box_y)),
            "width": width,
            "height": best[2][3],
            "text": best[1],
            "style": {
                "textColor": colour,
                "fontSize": round(size, 2),
                "fontWeight": "normal",
                "fontFamily": "Noto Sans SC",
                "textAlign": "center",
            },
            "contentRef": f"text:chip-{digest}",
            "sceneOwnerId": f"text:chip-{digest}",
            "imageMVP": {
                "source": "pixel-recovery",
                "role": "text",
                "candidate_type": "text",
                "grouping_status": "recovered",
                "reference_only": False,
                "generated": False,
                "textStatus": "ocr-chip-label",
            },
            "badgeLabel": True,
        }
        elements.append(label)
        existing.append((label["x"], label["y"], label["width"], label["height"]))
        restored += 1
    return restored


def _tail_key(element: Mapping[str, Any]) -> str:
    """A text node's words, comparable across two models of the same sentence.

    ``OCR_HOMOGLYPHS`` folds the lower-case confusions; a capital ``I`` read as a
    lower-case ``l`` ("AI" vs "Al") is the one this pass actually met, so the
    vertical strokes are folded here as well.  Comparison only — the text keeps
    whatever the model wrote.
    """
    folded = "".join(_fold_homoglyphs(str(element.get("text") or "")).split())
    return (
        folded.replace("I", "1").replace("i", "1").replace("l", "1").replace("|", "1")
    )


def _drop_paragraph_tails(elements: list[dict[str, Any]]) -> int:
    """Remove a fragment that is only the tail of a paragraph printed above it.

    When a paragraph is modelled once as a whole string and once as its wrapped
    remainder, the two boxes do not overlap — the fragment starts on the line
    below — so the coincidence test leaves both.  In the SVG the paragraph then
    runs past the card edge and the fragment repeats its last words; in Figma,
    where the paragraph wraps inside its box, the two occupy the same lines and
    print on top of each other.

    The signature is specific enough to act on: the short string is a *suffix*
    of the long one, it starts on a later line, and it sits inside the same
    horizontal span.  A standalone label that happens to repeat the end of a
    nearby paragraph is the risk, so the fragment has to be a real piece of
    prose (six characters), the paragraph has to be most of a sentence longer,
    and the fragment has to begin below the paragraph's first line.
    """
    tails = 0
    texts = [
        (index, element)
        for index, element in enumerate(elements)
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    doomed: set[int] = set()
    for fragment_index, fragment in texts:
        if fragment_index in doomed:
            continue
        # OCR reads the same word differently in the two models ("AI" vs "Al"),
        # so the comparison folds homoglyphs and drops the spaces that a line
        # break introduced.  Matching only; the text itself is untouched.
        fragment_text = _tail_key(fragment)
        if len(fragment_text) < PARAGRAPH_TAIL_MIN_CHARS:
            continue
        for host_index, host in texts:
            if host_index == fragment_index or host_index in doomed:
                continue
            host_text = _tail_key(host)
            if len(host_text) < len(fragment_text) + PARAGRAPH_TAIL_LENGTH_MARGIN:
                continue
            if not host_text.endswith(fragment_text):
                continue
            fragment_box = _layout_rect(fragment)
            host_box = _layout_rect(host)
            if fragment_box is None or host_box is None:
                continue
            fx, fy, fw, fh = fragment_box
            hx, hy, hw, hh = host_box
            if fy < hy + PARAGRAPH_TAIL_MIN_DROP:
                continue
            if fy > hy + hh + PARAGRAPH_TAIL_REACH:
                continue
            overlap = min(fx + fw, hx + hw) - max(fx, hx)
            if overlap < fw * PARAGRAPH_TAIL_HORIZONTAL_SHARE:
                continue
            doomed.add(fragment_index)
            tails += 1
            break
    if not doomed:
        return 0
    elements[:] = [
        element for index, element in enumerate(elements) if index not in doomed
    ]
    return tails


def _drop_text_under_patches(elements: list[dict[str, Any]]) -> int:
    """Delete vector text that a picture patch already prints.

    A patch is cut from the screenshot, so any vector node inside it is a second
    print of the same words — the discount stamps were exactly that: a bitmap of
    "5.8 折" with a text node on top of it.  The patch wins because it carries the
    真实像素; the node only adds a ghost.

    `mark` crops are deliberately *not* included: a mark is often a bitmap of a
    label that is also modelled as text (AtomGit's 智能体开发), and there the text
    is the better asset — it stays editable.  Words with no OCR support sitting on
    a chip-sized mark are handled by `_drop_nested_texts`, which asks the picture
    first.

    Frame members are referenced by id, so removing an element is safe once the
    id is also removed from any frame that lists it.
    """
    patches = [
        _layout_rect(element)
        for element in elements
        if str(element.get("role") or "") == "patch"
    ]
    patches = [box for box in patches if box]
    if not patches:
        return 0
    doomed: set[str] = set()
    for element in elements:
        if element.get("type") != "text" or not str(element.get("text") or "").strip():
            continue
        box = _layout_rect(element)
        if box is None:
            continue
        area = max(1, box[2] * box[3])
        for patch in patches:
            overlap_w = min(box[0] + box[2], patch[0] + patch[2]) - max(box[0], patch[0])
            overlap_h = min(box[1] + box[3], patch[1] + patch[3]) - max(box[1], patch[1])
            if overlap_w <= 0 or overlap_h <= 0:
                continue
            if (overlap_w * overlap_h) / area >= PATCH_TEXT_COVER:
                doomed.add(str(element.get("id") or element.get("contentRef") or ""))
                break
    if not doomed:
        return 0
    elements[:] = [
        element
        for element in elements
        if str(element.get("id") or element.get("contentRef") or "") not in doomed
    ]
    for element in elements:
        members = element.get("layoutChildren")
        if isinstance(members, list):
            element["layoutChildren"] = [
                member
                for member in members
                if str(member.get("id") or "") not in doomed
            ]
    return len(doomed)


def _drop_contained_texts(elements: list[dict[str, Any]]) -> int:
    """Delete a text node that is the ghost of a bigger one in the same place.

    "11月 &日更新" sat inside "价目牌 · 82 个模型 · 11 月 8 日更新" and printed on
    top of it; "Kimi" sat inside "Kimi K3"; "¥8.00" inside "¥4.64 ¥8.00".  The
    overlap test upstream compares coverage and wording and lets these through
    because the words differ.  Containment is the signal: when the smaller box
    lives inside the larger one and the two share the words they do have, the
    smaller is a second model of the same line.
    """
    from difflib import SequenceMatcher

    texts = [
        element
        for element in elements
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    doomed: set[str] = set()
    for small in texts:
        small_key = str(small.get("id") or "")
        if not small_key or small_key in doomed:
            continue
        small_box = _layout_rect(small)
        if small_box is None:
            continue
        small_area = max(1, small_box[2] * small_box[3])
        for big in texts:
            if big is small:
                continue
            big_box = _layout_rect(big)
            if big_box is None:
                continue
            if big_box[2] * big_box[3] <= small_area:
                continue
            overlap_w = min(small_box[0] + small_box[2], big_box[0] + big_box[2]) - max(
                small_box[0], big_box[0]
            )
            overlap_h = min(small_box[1] + small_box[3], big_box[1] + big_box[3]) - max(
                small_box[1], big_box[1]
            )
            if overlap_w <= 0 or overlap_h <= 0:
                continue
            if (overlap_w * overlap_h) / small_area < CONTAINED_TEXT_IOA:
                continue
            one = _tail_key(small)
            two = _tail_key(big)
            if not one or not two:
                continue
            # 用词对得上：相似度够、或互相包含、或短的那句的字符几乎都在长句里
            # （OCR 把 "8" 读成 "&" 时，"11月 &日更新" 与 "…11 月 8 日更新" 的
            # 相似度只有 0.45，但字符覆盖是 0.83）。
            covered = set(one) & set(two)
            char_cover = len(covered) / max(1, len(set(one)))
            if (
                SequenceMatcher(None, one, two).ratio() >= CONTAINED_TEXT_SIMILARITY
                or one in two
                or two in one
                or _shared_affix(one, two) >= 4
                or char_cover >= 0.8
            ):
                doomed.add(small_key)
                break
    if not doomed:
        return 0
    elements[:] = [
        element
        for element in elements
        if str(element.get("id") or element.get("contentRef") or "") not in doomed
    ]
    for element in elements:
        members = element.get("layoutChildren")
        if isinstance(members, list):
            element["layoutChildren"] = [
                member for member in members if str(member.get("id") or "") not in doomed
            ]
    return len(doomed)


def _ocr_carries(
    text: str,
    box: tuple[int, int, int, int],
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> bool:
    """Does an OCR line *at this box* actually spell these words?

    Containment, not character overlap.  "¥4.64" shares two characters with
    "DeepSeek V4.1 Flash", and counting that as support is how a phantom price
    gets to sit on top of a title: every box test passes because the title's box
    covers it.
    """
    key = "".join(_fold_homoglyphs(str(text or "")).split()).lower()
    if not key:
        return False
    wanted = set(key)
    for observation in ocr_observations or []:
        line = "".join(
            _fold_homoglyphs(str(observation.get("text") or "")).split()
        ).lower()
        if not line:
            continue
        raw_box = observation.get("bbox") or []
        if len(raw_box) != 4:
            continue
        other = tuple(int(value) for value in raw_box)
        if (
            _overlap_share(box, other) < OCR_SUPPORT_OVERLAP
            and _overlap_share(other, box) < OCR_SUPPORT_OVERLAP
        ):
            continue
        # Characters, not containment: OCR spells "输入 · 峰时" as "输入 .峰时"
        # and "谷时 ¥0.58" as "谷时半0.58", and a legit line must not be thrown
        # away because the engine guessed one glyph wrong.
        if len(wanted & set(line)) / len(wanted) >= OCR_SUPPORT_CHARS:
            return True
    return False


def _drop_nested_texts(
    elements: list[dict[str, Any]],
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Delete a text node that prints where a bigger text node already prints.

    Two lines of type never share the same pixels; when they appear to, one of
    them is not describing the picture.  marketplace's DeepSeek card had four of
    these — "¥4.64", "¥8.00", "¥2.00" and "起 ¥23.00" all mapped onto the card's
    title band, so the export looked like a title with small type smudged into it.

    Wording cannot decide this: those strings are not variants of the title, they
    are different words in the wrong place.  What decides it is support — the
    picture's own OCR at that box.  A table cell where "冻结库存" sits inside a
    wide value box *is* supported by OCR, and is left alone.
    """
    texts = [
        element
        for element in elements
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    # Pictures about the size of the words they sit under are chips and icons — a
    # crop the compiler already committed to.  A full-bleed photo is not: words
    # over a photo are normal, so only comparable areas count here.
    chips = [
        (_layout_rect(element), int(element.get("width") or 0) * int(element.get("height") or 0))
        for element in elements
        if element.get("imageBase64")
    ]
    chips = [(box, area) for box, area in chips if box]
    doomed: set[str] = set()
    for small in texts:
        small_key = str(small.get("id") or "")
        if not small_key or small_key in doomed:
            continue
        small_box = _layout_rect(small)
        if small_box is None:
            continue
        if _ocr_carries(str(small.get("text") or ""), small_box, ocr_observations):
            continue
        small_area = small_box[2] * small_box[3]
        small_centre = small_box[1] + small_box[3] / 2.0
        for big in texts:
            if big is small or str(big.get("id") or "") in doomed:
                continue
            big_box = _layout_rect(big)
            if big_box is None:
                continue
            if big_box[2] * big_box[3] <= small_area:
                continue
            if _overlap_share(small_box, big_box) < NESTED_TEXT_SHARE:
                continue
            # Same line: a value printed under a heading lives one line lower and
            # keeps its own vertical band.  These occupy the same band.
            if abs(small_centre - (big_box[1] + big_box[3] / 2.0)) > max(
                3.0, small_box[3] * NESTED_TEXT_LINE_TOLERANCE
            ):
                continue
            if big_box[3] > small_box[3] * NESTED_TEXT_HEIGHT_RATIO:
                continue
            doomed.add(small_key)
            break
        if small_key in doomed:
            continue
        for picture_box, picture_area in chips:
            if picture_area > small_area * NESTED_IMAGE_AREA_RATIO:
                continue
            if _overlap_share(small_box, picture_box) >= PATCH_TEXT_COVER:
                doomed.add(small_key)
                break
    if not doomed:
        return 0
    elements[:] = [
        element
        for element in elements
        if str(element.get("id") or element.get("contentRef") or "") not in doomed
    ]
    for element in elements:
        members = element.get("layoutChildren")
        if isinstance(members, list):
            element["layoutChildren"] = [
                member for member in members if str(member.get("id") or "") not in doomed
            ]
    return len(doomed)


def _restore_display_weight(
    elements: list[dict[str, Any]],
    image_path: str | Path,
    width: int,
    height: int,
) -> int:
    """Give the page's biggest line the weight a display title is set in.

    The stroke test in `style_resolver` measures `2*area/perimeter`, which is the
    right number for text at reading sizes and the wrong one for a 99px hero: a
    Song face has 12px verticals and 2px horizontals, so the average lands at
    0.086em — under the bold threshold — and the title comes out Regular, which
    is the one thing a page cannot afford.

    So the biggest line is judged by role, not by average: if it measures at
    least `DISPLAY_STROKE_MIN` of its own em, it is display type and gets 800.
    """
    import numpy as np
    from PIL import Image

    from src.app.services.structure.fidelity.style_resolver import _stroke_thickness

    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, FileNotFoundError):
        return 0
    sized = [
        element
        for element in elements
        if element.get("type") == "text"
        and str(element.get("text") or "").strip()
        and float((element.get("style") or {}).get("fontSize") or 0) >= DISPLAY_MIN_SIZE
    ]
    if not sized:
        return 0
    biggest = max(float((element.get("style") or {}).get("fontSize") or 0) for element in sized)
    changed = 0
    for element in sized:
        style = element.setdefault("style", {})
        size = float(style.get("fontSize") or 0)
        if abs(size - biggest) > 1.0:
            continue
        if int(style.get("fontWeightValue") or 400) >= 800:
            continue
        box = _layout_rect(element)
        if box is None:
            continue
        x, y, w, h = box
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        crop = image[y0:y1, x0:x1]
        luminance = crop.mean(axis=2)
        if float(luminance.max() - luminance.min()) < 40:
            continue
        mask = luminance >= (float(np.percentile(luminance, 5)) + float(luminance.max())) / 2.0
        if mask.sum() < 60:
            continue
        thickness = _stroke_thickness(mask.astype(np.uint8))
        if thickness / max(1.0, size) < DISPLAY_STROKE_MIN:
            continue
        style["fontWeightValue"] = 800
        style["fontWeight"] = "bold"
        element["weightEvidence"] = {
            "method": "display-role",
            "stroke": round(float(thickness), 2),
            "size": round(size, 1),
        }
        changed += 1
    return changed


def _separate_badge_icon_text(elements: list[dict[str, Any]]) -> int:
    """Start a badge's words after the glyph instead of inside it.

    A pill that reads "● 大厂直供" arrives as a box over the pill, an icon cut
    over the dot and a text box that begins on top of the dot.  The three are
    measured independently, so nothing notices that the first word is printed
    through the icon.  Moving the words to the icon's right edge is the whole
    repair; the pill keeps its size, so no frame changes.

    Only inside a badge: a pill or a button is a few hundred pixels wide and at
    most a line tall.  A sidebar row is wider than that, and its icon cut
    already carries the first millimetres of the label as pixels — nudging the
    text there would print the leading glyph twice.
    """
    if not elements:
        return 0
    rects = [_layout_rect(element) for element in elements]
    icons = [
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "image"
        and rects[index] is not None
        and rects[index][2] <= 48
        and rects[index][3] <= 48
    ]
    if not icons:
        return 0
    chips = [
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "container"
        and rects[index] is not None
        and rects[index][2] <= BADGE_MAX_WIDTH
        and rects[index][3] <= BADGE_MAX_HEIGHT
    ]
    moved = 0
    for index, element in enumerate(elements):
        if str(element.get("type")) != "text" or not element.get("text"):
            continue
        box = rects[index]
        if box is None:
            continue
        chip = None
        for candidate in chips:
            chip_box = rects[candidate]
            if chip_box is None or not _rect_contains(chip_box, box, tolerance=2):
                continue
            if chip is None or chip_box[2] * chip_box[3] < rects[chip][2] * rects[chip][3]:
                chip = candidate
        if chip is None:
            continue
        chip_box = rects[chip]
        for icon in icons:
            icon_box = rects[icon]
            if icon_box is None or chip_box is None:
                continue
            if not _rect_contains(chip_box, icon_box, tolerance=2):
                continue
            overlap_h = min(box[1] + box[3], icon_box[1] + icon_box[3]) - max(
                box[1], icon_box[1]
            )
            if overlap_h < min(box[3], icon_box[3]) * 0.5:
                continue
            # The words' leading edge has to be *inside* the glyph and they have
            # to run past it: that is the printed-through-the-icon shape.  A
            # label that starts left of the icon is a different defect.
            if not (icon_box[0] + 1 < box[0] < icon_box[0] + icon_box[2] - 1):
                continue
            if box[0] + box[2] <= icon_box[0] + icon_box[2]:
                continue
            target = icon_box[0] + icon_box[2] + BADGE_ICON_GAP
            if target <= box[0]:
                continue
            # Clearing the glyph must leave the words somewhere to go.  A
            # two-pixel remainder means the "icon" was measured over the label
            # as well, so the shift would trade one bad box for another.
            remaining = box[0] + box[2] - target
            if remaining < max(12, box[2] * 0.5):
                continue
            element["x"] = target
            element["width"] = max(1, remaining)
            rects[index] = (target, box[1], element["width"], box[3])
            moved += 1
            break
    return moved


def _table_containing(
    box: tuple[int, int, int, int],
    tables: Sequence[int],
    rects: Sequence[tuple[int, int, int, int] | None],
) -> int | None:
    """The smallest table whose rectangle holds this box's centre."""
    centre_x = box[0] + box[2] / 2
    centre_y = box[1] + box[3] / 2
    best: tuple[int, int] | None = None
    for table in tables:
        other = rects[table]
        if other is None:
            continue
        if not (
            other[0] <= centre_x <= other[0] + other[2]
            and other[1] <= centre_y <= other[1] + other[3]
        ):
            continue
        area = other[2] * other[3]
        if best is None or area < best[0]:
            best = (area, table)
    return best[1] if best else None


def _recover_saturated_bars(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
) -> int:
    """Add the solid coloured bars nothing else in the plan accounts for.

    A progress bar is the one element every perception stage drops: too thin to
    be a container, no words on it, not a glyph.  The review screen came back
    with "处理进度 90%" and nothing under it.  Pixels know: a run six to
    twenty-two pixels tall, at least a hundred wide, saturated, and almost
    completely filled is a painted bar, not a line, not a border, not text.
    """
    import numpy as np
    from PIL import Image

    try:
        import cv2
    except Exception:  # pragma: no cover - opencv is a pipeline dependency
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    if image.ndim != 3 or image.shape[0] < 8 or image.shape[1] < 8:
        return 0
    image = image[:height, :width].astype(np.int32)
    pool = image.reshape(-1, 3)
    # HSV saturation, computed the cheap way: (max - min) / max.  int32 is not
    # optional: on int16 the 255x multiply overflows and a blue bar reads as
    # unsaturated noise.
    high = pool.max(axis=1)
    low = pool.min(axis=1)
    saturation = np.where(high > 0, (high - low) * 255 // np.maximum(high, 1), 0)
    mask = (
        (saturation.reshape(image.shape[:2]) >= BAR_MIN_SATURATION)
        & (high.reshape(image.shape[:2]) >= BAR_MIN_VALUE)
    ).astype(np.uint8)
    if not mask.any():
        return 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)

    rects = [_layout_rect(element) for element in elements]
    texts = [
        rects[index]
        for index, element in enumerate(elements)
        if str(element.get("type")) == "text" and element.get("text") and rects[index]
    ]

    candidates: list[tuple[int, list[int]]] = []
    for index in range(1, count):
        x, y, box_width, box_height, area = (int(value) for value in stats[index, :5])
        if box_height < BAR_MIN_HEIGHT or box_height > BAR_MAX_HEIGHT:
            continue
        if box_width < BAR_MIN_WIDTH:
            continue
        if box_width / max(1, box_height) < BAR_MIN_ASPECT:
            continue
        if area / max(1, box_width * box_height) < BAR_FILL_RATIO:
            continue
        box = (x, y, box_width, box_height)
        # Words printed on it means it is a highlight behind a label, not a bar.
        if any(_iou(box, text) >= 0.25 for text in texts):
            continue
        # Already in the design: a rule, a chip, a divider that came with a fill.
        if any(
            rect is not None
            and _iou(box, rect) >= BAR_EXISTING_IOU
            for rect in rects
        ):
            continue
        candidates.append((area, [x, y, box_width, box_height]))

    if not candidates:
        return 0
    candidates.sort(key=lambda item: item[0], reverse=True)
    added = 0
    from src.app.services.structure.image_contract import _dominant_color
    from src.app.services.structure.fidelity.pixel_probe import (
        sample_container_decoration,
    )

    for _area, box in candidates[:BAR_MAX_REGIONS]:
        digest = hashlib.sha1(
            f"{box[0]}:{box[1]}:{box[2]}:{box[3]}:{image_path}".encode("utf-8")
        ).hexdigest()[:16]
        style: dict[str, Any] = {"fillColor": _dominant_color(image_path, box, inset=1)}
        style.update(sample_container_decoration(image_path, box, style["fillColor"]))
        style.setdefault("borderRadius", max(2, min(box[3] // 2, 8)))
        elements.append(
            {
                "id": f"bar:{digest}",
                "type": "container",
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "text": "",
                "style": style,
                "role": "progress",
                "name": "Progress bar",
                "contentRef": f"bar:{digest}",
                "sceneOwnerId": f"bar:{digest}",
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "progress",
                    "grouping_status": "recovered",
                },
            }
        )
        added += 1
    return added


def _resolve_misfiled_controls(
    elements: list[dict[str, Any]],
    observations: Sequence[Mapping[str, Any]] | None,
    image_path: str,
) -> int:
    """Put a control back where its own words were read, or drop the copy.

    A navigation item measured over a table is a double fault: the table now
    has a stranger painted across its first row, and the sidebar row it came
    from is empty.  OCR knows where those words really are.  When nothing on
    the page reads them at the box the control sits in, the box is the error —
    move it onto its line, and sample the fill again, because the colour was
    taken at the wrong place too (a cyan nav pill measured over a white table
    becomes white).

    If another element already prints those words at that line, the control is
    a second copy of it and goes away instead of stacking on it.
    """
    if not elements:
        return 0
    from src.app.services.structure.fidelity.contracts import (
        normalize_owner_text,
        owner_text_similarity,
    )

    lines = _ocr_lines(observations)
    if not lines:
        return 0
    rects = [_layout_rect(element) for element in elements]
    tables = [
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "table"
        or str(element.get("id") or "").startswith("table-node:")
    ]
    if not tables:
        return 0
    doomed: set[int] = set()
    repaired = 0
    for index, element in enumerate(elements):
        if str(element.get("type")) not in {"button", "input"}:
            continue
        if str(element.get("contentRef") or "").startswith(TABLE_TEXT_PREFIXES):
            continue
        text = normalize_owner_text(element.get("text"))
        box = rects[index]
        if not text or box is None:
            continue
        if _table_containing(box, tables, rects) is None:
            continue
        # Words printed here already?  Then the box is right and this is not
        # the defect this pass handles.
        if _has_ocr_support(
            str(element.get("text") or ""), box, lines, slack=4, threshold=0.85
        ):
            continue
        target: tuple[float, tuple[int, int, int, int]] | None = None
        for line_text, line_box in lines:
            if line_text != text and owner_text_similarity(line_text, text) < 0.85:
                continue
            distance = abs(
                (line_box[0] + line_box[2] / 2) - (box[0] + box[2] / 2)
            ) + abs((line_box[1] + line_box[3] / 2) - (box[1] + box[3] / 2))
            if distance < CONTROL_REANCHOR_MIN_SHIFT:
                continue
            if target is None or distance < target[0]:
                target = (distance, line_box)
        if target is None:
            continue
        line_box = target[1]
        twin = any(
            other is not element
            and other_index not in doomed
            and str(other.get("type")) in {"text", "button", "input"}
            and normalize_owner_text(other.get("text"))
            and owner_text_similarity(other.get("text"), element.get("text")) >= 0.85
            and _rect_contains(
                _layout_rect(other) or (0, 0, 0, 0), line_box, tolerance=12
            )
            for other_index, other in enumerate(elements)
        )
        if twin:
            doomed.add(index)
            repaired += 1
            continue
        width, height = box[2], box[3]
        new_x = int(round(line_box[0] + line_box[2] / 2 - width / 2))
        new_y = int(round(line_box[1] + line_box[3] / 2 - height / 2))
        element["x"], element["y"] = new_x, new_y
        moved = (new_x, new_y, width, height)
        rects[index] = moved
        _resample_fill(element, image_path, moved)
        repaired += 1
    if doomed:
        elements[:] = [
            element for index, element in enumerate(elements) if index not in doomed
        ]
    return repaired


def _resample_fill(
    element: dict[str, Any],
    image_path: str,
    box: tuple[int, int, int, int],
) -> None:
    """Take the fill colour from where the element now sits."""
    style = element.get("style")
    if not isinstance(style, dict) or not style.get("fillColor"):
        return
    from src.app.services.structure.image_contract import _dominant_color

    try:
        colour = _dominant_color(image_path, list(box))
    except Exception:  # noqa: BLE001 - a colour hint must never break the build
        return
    if colour:
        style["fillColor"] = colour


#: A patch behind bare text has to differ from the text's own surface by this
#: much before it counts as a badge rather than the card the text sits on.
BACKDROP_FILL_DELTA = 18
#: A hairline is fainter than a fill: an empty search box is white on white
#: with a #e0e0e0 edge, which is a 30-channel step but only one pixel wide.
BACKDROP_EDGE_DELTA = 10
#: How far the sampling walks out from a text box looking for its edge.
BACKDROP_MAX_PAD = 32
#: A chip closes on every side; fewer edges is a neighbour, not a chip.
BACKDROP_MIN_SIDES = 3
#: A chip hugs its words.  A container's border sits further out than this, and
#: a box that reaches it is the card, not a badge.  A button is the widest chip
#: there is: 登录 is two glyphs in a 98px pill, so 23px of padding per side is
#: still a control and not a panel.
BACKDROP_MAX_PAD_PER_SIDE = 32
BACKDROP_MAX_TOTAL_PAD = 96
#: Share of a side's pixels that has to leave the fill before it is an edge.
BACKDROP_EDGE_SHARE = 0.6
#: A patch larger than this share of the canvas is a surface, not a badge.
BACKDROP_MAX_AREA_SHARE = 0.25


def _frame_colour(image, box: tuple[int, int, int, int], inset: int) -> tuple[int, int, int]:
    """Median colour of a 2px frame drawn ``inset`` pixels inside ``box``."""
    import numpy as np

    x, y, width, height = box
    left, top = x + inset, y + inset
    right, bottom = x + width - inset, y + height - inset
    if right - left < 2 or bottom - top < 2:
        left, top, right, bottom = x, y, x + width, y + height
    chunks = [
        image[top : top + 2, left:right],
        image[max(top, bottom - 2) : bottom, left:right],
        image[top:bottom, left : left + 2],
        image[top:bottom, max(left, right - 2) : right],
    ]
    pool = np.concatenate([chunk.reshape(-1, 3) for chunk in chunks if chunk.size])
    median = np.median(pool, axis=0)
    return (int(median[0]), int(median[1]), int(median[2]))


def _walk_to_edge(image, fill, box, side: str, limit: int) -> tuple[int, int] | None:
    """First distance out of ``box`` on ``side`` whose colour leaves ``fill``."""
    import numpy as np

    x, y, width, height = box
    for step in range(1, limit + 1):
        if side == "left":
            band = image[y : y + height, max(0, x - step) : max(0, x - step) + 1]
        elif side == "right":
            band = image[y : y + height, x + width + step - 1 : x + width + step]
        elif side == "top":
            band = image[max(0, y - step) : max(0, y - step) + 1, x : x + width]
        else:
            band = image[y + height + step - 1 : y + height + step, x : x + width]
        if band.size == 0:
            return None
        distance = np.abs(band.reshape(-1, 3) - np.asarray(fill, dtype=np.int16)).max(axis=1)
        if int(distance.max()) >= BACKDROP_EDGE_DELTA:
            column = band.reshape(-1, 3)[int(distance.argmax())]
            return step, 0, 0, 0  # placeholder, colour read by the caller
    return None


def _recover_text_backdrops(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
) -> int:
    """Give bare text the badge, pill or button it is printed on.

    A plan describes words, not the coloured chips behind them: the green 库位
    tag, the red 模型广场 tab, the black 推荐/登录 buttons, the white 看详情
    button all arrive as plain text on whatever surface happens to be there.
    The pixels know the chip — it ends a few pixels from the words, and what is
    outside it is a different colour.

    Walk out from each text box until the colour leaves the text's own surface.
    A step of 18 or more is a fill; a step between 10 and 18 is a hairline, which
    is how an empty input on a white card shows up at all.
    """
    import numpy as np
    from PIL import Image

    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    if image.ndim != 3:
        return 0
    canvas_area = max(1, width * height)

    from src.app.services.structure.fidelity.pixel_probe import estimate_corner_radius

    def hex_of(colour: tuple[int, int, int]) -> str:
        return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, value)) for value in colour])

    # Surfaces already described by a filled element: no chip to add.
    existing: list[tuple[tuple[int, int, int, int], str]] = []
    for element in elements:
        style = element.get("style")
        if not isinstance(style, dict):
            continue
        fill = str(style.get("fillColor") or "")
        box = _layout_rect(element)
        if fill and box is not None:
            existing.append((box, fill.lower()))

    out: list[dict[str, Any]] = []
    added = 0
    for element in elements:
        out.append(element)
        if str(element.get("type")) != "text" or not element.get("text"):
            continue
        box = _layout_rect(element)
        if box is None or box[2] < 2 or box[3] < 2:
            continue
        x, y, box_width, box_height = box
        fill = _frame_colour(image, box, inset=2)
        if fill == (0, 0, 0) and image[y : y + 1, x : x + 1].size == 0:
            continue

        edges: dict[str, int] = {}
        border_samples: list[tuple[int, int, int]] = []
        for side in ("left", "right", "top", "bottom"):
            for step in range(1, BACKDROP_MAX_PAD + 1):
                if side == "left":
                    band = image[y : y + box_height, max(0, x - step) : max(0, x - step) + 1]
                elif side == "right":
                    band = image[y : y + box_height, x + box_width + step - 1 : x + box_width + step]
                elif side == "top":
                    band = image[max(0, y - step) : max(0, y - step) + 1, x : x + box_width]
                else:
                    band = image[y + box_height + step - 1 : y + box_height + step, x : x + box_width]
                if band.size == 0:
                    break
                pixels = band.reshape(-1, 3)
                distance = np.abs(pixels - np.asarray(fill, dtype=np.int16)).max(axis=1)
                strong = np.where(distance >= BACKDROP_EDGE_DELTA)[0]
                # An edge spans the side.  A handful of antialiased pixels at
                # the rim of the fill are not the chip ending — without this the
                # walk stops 1-4px out, on the glyph's own fringe.
                if strong.size < max(2, int(pixels.shape[0] * BACKDROP_EDGE_SHARE)):
                    continue
                edges[side] = step
                border_samples.append(tuple(int(value) for value in pixels[strong[0]]))
                break

        # A chip closes around its words on every side.  Two edges are a text
        # sitting next to a badge or above a rule, and building a box for that
        # paints a strip across the row.
        if len(edges) < BACKDROP_MIN_SIDES:
            continue
        if max(edges.values()) > BACKDROP_MAX_PAD_PER_SIDE:
            continue
        if sum(edges.values()) > BACKDROP_MAX_TOTAL_PAD:
            continue
        left = x - edges.get("left", 0)
        top = y - edges.get("top", 0)
        right = x + box_width + edges.get("right", 0)
        bottom = y + box_height + edges.get("bottom", 0)
        patch = (
            max(0, left),
            max(0, top),
            max(1, min(width, right) - max(0, left)),
            max(1, min(height, bottom) - max(0, top)),
        )
        if patch[2] * patch[3] > canvas_area * BACKDROP_MAX_AREA_SHARE:
            continue
        # What is beyond the edge has to be a different colour, or the "chip"
        # is just the surface the words were already printed on (a dark title
        # on a dark page found its own gradient and made a dark rectangle).
        beyond: list[tuple[int, int, int]] = []
        for side in edges:
            sample = {
                "left": (
                    slice(max(0, patch[1]), patch[1] + patch[3]),
                    slice(max(0, patch[0] - 3), max(0, patch[0])),
                ),
                "right": (
                    slice(patch[1], patch[1] + patch[3]),
                    slice(patch[0] + patch[2], patch[0] + patch[2] + 3),
                ),
                "top": (
                    slice(max(0, patch[1] - 3), max(0, patch[1])),
                    slice(patch[0], patch[0] + patch[2]),
                ),
                "bottom": (
                    slice(patch[1] + patch[3], patch[1] + patch[3] + 3),
                    slice(patch[0], patch[0] + patch[2]),
                ),
            }[side]
            chunk = image[sample]
            if chunk.size:
                beyond.append(tuple(int(value) for value in np.median(chunk.reshape(-1, 3), axis=0)))
        if beyond:
            outside = tuple(
                int(np.median([sample[channel] for sample in beyond]))
                for channel in range(3)
            )
            if max(abs(one - two) for one, two in zip(fill, outside)) < BACKDROP_FILL_DELTA:
                continue
        # Something already paints this surface — a button, a card, a chip that
        # the plan did describe.  Adding a second one would only stack paint.
        if any(
            _rect_contains(box_, patch, tolerance=3)
            and _same_fill(fill_, hex_of(fill), 6)
            for box_, fill_ in existing
        ):
            continue

        border_hex = ""
        if border_samples:
            median = tuple(
                int(np.median([sample[channel] for sample in border_samples]))
                for channel in range(3)
            )
            step = max(
                abs(one - two) for one, two in zip(median, fill)
            )
            if BACKDROP_EDGE_DELTA <= step <= 120:
                border_hex = hex_of(median)
        patch_hex = hex_of(fill)
        if not border_hex and _same_fill(patch_hex, "", 0):
            continue

        digest = hashlib.sha1(
            f"{patch[0]}:{patch[1]}:{patch[2]}:{patch[3]}:{patch_hex}".encode("utf-8")
        ).hexdigest()[:16]
        style: dict[str, Any] = {"fillColor": patch_hex}
        if border_hex:
            style["borderColor"] = border_hex
            style["borderWidth"] = 1
        radius = 0
        try:
            radius = int(estimate_corner_radius(image, patch) or 0)
        except Exception:  # noqa: BLE001 - a radius hint must never break a build
            radius = 0
        if radius:
            style["borderRadius"] = radius
        out.insert(
            len(out) - 1,
            {
                "id": f"backdrop:{digest}",
                "type": "container",
                "x": patch[0],
                "y": patch[1],
                "width": patch[2],
                "height": patch[3],
                "text": "",
                "style": style,
                "role": "text-backdrop",
                "name": "Text backdrop",
                "contentRef": f"backdrop:{digest}",
                "sceneOwnerId": f"backdrop:{digest}",
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "text-backdrop",
                    "grouping_status": "recovered",
                },
            },
        )
        # Only a word that fits inside its chip is that chip's label.  A long
        # row label that merely starts on one keeps its own reading and stays
        # subject to the duplicate pass — otherwise it printed white words
        # across the row.
        span_left, span_right = _rendered_span(element)
        if span_right - span_left <= patch[2] * 1.3:
            element["badgeLabel"] = True
        added += 1
    if added:
        elements[:] = out
    return added


#: Recovered marks: a logo is wider than an icon but still a mark, not a panel,
#: and a stamp around a price is wider still.
VISUAL_MIN_SIDE = 12
VISUAL_MAX_WIDTH = 260
VISUAL_MAX_HEIGHT = 120
#: How far a glyph's antialiased edge may sit from the label's own colour and
#: still be that label's ink.
VISUAL_INK_TOLERANCE = 60
VISUAL_MIN_FILL = 0.25
VISUAL_MAX_FILL = 0.97
VISUAL_MIN_CONTRAST = 24
VISUAL_MAX_REGIONS = 10


def _overlap_share(
    box: tuple[int, int, int, int],
    other: tuple[int, int, int, int],
) -> float:
    """Share of ``box`` covered by ``other``."""
    width = min(box[0] + box[2], other[0] + other[2]) - max(box[0], other[0])
    height = min(box[1] + box[3], other[1] + other[3]) - max(box[1], other[1])
    if width <= 0 or height <= 0:
        return 0.0
    return (width * height) / max(1, box[2] * box[3])


#: A card can be three channels away from the page it sits on: marketplace's
#: #161618 on #0d0d0f, AtomGit's #fdf6f5 on #ffffff.  Six is the floor where a
#: difference is real and no longer compression noise.
SOFT_PANEL_MIN_DELTA = 6
#: A page can be a gradient.  Eight bands follow it closely enough that the
#: step between neighbours is under the eye's threshold.
PAGE_BANDS = 8
#: 四边中位色相差超过这个值，说明它们属于两个不同的面，不能取平均。
PAGE_EDGE_SPLIT = 8
#: 分带底色与声明的页底色差小于这个值时，这条带子什么也没画，只是接缝。
#: 取 6 而不是 10：wecom 的页底声明 #666666、实到 #5d6064，差 9 个通道——
#: 在中灰上这已经看得见，按 10 放过它时 within15 掉了 1.4 个点。
PAGE_BAND_MIN_DELTA = 6
#: A solid container that stops short of its own paint: how far to follow
#: colour continuity, and how much of a row has to agree before it counts.
CONTAINER_GROW_MAX = 32
#: A card's box is routinely a few pixels short of its own paint; the cap is
#: smaller than the page chrome's because a card has neighbours close by.
CONTAINER_GROW_CARD_MAX = 16
#: A card's own rows carry words, so 90% of a row is never the card's colour.
#: Half is enough to tell "still this card" from "the page underneath".
CONTAINER_GROW_CARD_SHARE = 0.5
CONTAINER_GROW_TOLERANCE = 12
CONTAINER_GROW_SHARE = 0.9
#: Consecutive off-colour rows a growth may step over (an antialiased seam).
CONTAINER_GROW_BRIDGE = 2
#: A solid panel fills its own box.  A line of text covers half of it at most,
#: which is what keeps this from recovering every word as a card.
SOFT_PANEL_MIN_FILL = 0.9
#: An outline-only box (an empty input) fills nothing; its *border* closes the
#: box instead, so the share of the bbox perimeter that is drawn is the test.
SOFT_PANEL_MIN_EDGE = 0.8
SOFT_PANEL_MIN_WIDTH = 24
SOFT_PANEL_MIN_HEIGHT = 16
SOFT_PANEL_MIN_AREA = 800
#: Never the page itself: a blob that covers most of the canvas is the ground.
SOFT_PANEL_MAX_SHARE = 0.5
#: Already described by a filled element or a picture: nothing to add.
SOFT_PANEL_EXISTING_IOA = 0.7
SOFT_PANEL_MAX_REGIONS = 24


def _panel_edge_share(mask, box: tuple[int, int, int, int]) -> float:
    """Share of a box's one-pixel perimeter that is painted."""
    import numpy as np

    x, y, width, height = box
    if width < 3 or height < 3:
        return 0.0
    top = mask[y, x : x + width]
    bottom = mask[y + height - 1, x : x + width]
    left = mask[y : y + height, x]
    right = mask[y : y + height, x + width - 1]
    sides = np.concatenate([top, bottom, left, right])
    return float(sides.mean()) if sides.size else 0.0


def _already_painted(
    box: tuple[int, int, int, int],
    fill: str,
    covered: Sequence[tuple[tuple[int, int, int, int], str]],
) -> bool:
    """Whether an existing filled box already paints this patch in this colour.

    Geometry alone is not enough: the sidebar paints #364150 across its whole
    height, and the cyan highlight inside it is a *different* element that the
    plan never had.  Covering is only "already there" when the colour agrees.
    """
    for other, other_fill in covered:
        share = _overlap_share(box, other)
        if share < SOFT_PANEL_EXISTING_IOA:
            continue
        if not other_fill:
            # A picture: its pixels are the answer, not a fill.
            if share >= 0.5:
                return True
            continue
        if not fill or _same_fill(fill, other_fill, SOFT_PANEL_MIN_DELTA):
            return True
    return False


#: A block of one flat colour is a button, a highlight, a chip.  It has to be
#: big enough to be a block and opaque enough to fill its own box; words never
#: do either.
COLOUR_REGION_MIN_PIXELS = 600
COLOUR_REGION_MIN_FILL = 0.9
COLOUR_REGION_MIN_SIDE = 14
COLOUR_REGION_MAX_SHARE = 0.35
COLOUR_REGION_TOLERANCE = 10
COLOUR_REGION_MIN_SAMPLES = 2500
#: Capsules and rounded chips: wide, short, filled except where the corners are
#: rounded away.  The fill band sits strictly below the solid pass's 0.90 so the
#: two recoveries never claim the same region.
PILL_MIN_WIDTH = 24
PILL_MAX_WIDTH = 420
PILL_MIN_HEIGHT = 14
PILL_MAX_HEIGHT = 96
PILL_MIN_FILL = 0.60
PILL_MAX_FILL = 0.94
PILL_CORNER_TOLERANCE = 12
PILL_MIN_CONTRAST = 8
#: 只有一圈细线的芯片：内芯是卡片色，边缘比卡片亮 8 个通道以上。
OUTLINE_CHIP_MIN_DELTA = 8
OUTLINE_CHIP_MAX_DELTA = 90
OUTLINE_CHIP_INNER_FILL = 0.8
OUTLINE_CHIP_MIN_WIDTH = 30
OUTLINE_CHIP_MAX_WIDTH = 260
OUTLINE_CHIP_MIN_HEIGHT = 18
OUTLINE_CHIP_MAX_HEIGHT = 80
OUTLINE_CHIP_SEARCH_PAD = 30
#: 标签外围已有控件时，控件盒最多比文字大这么多才算"这只芯片已经画过了"。
OUTLINE_CHIP_WRAP_PAD = 24
#: 细线最厚算几像素：更厚的连通域是实心块，不是描边。
OUTLINE_CHIP_MAX_THICKNESS = 3
#: 胶囊内边距至少这么大，紧贴字面的那一圈算抗锯齿。
OUTLINE_CHIP_MIN_PAD = 6
#: 胶囊盒最多比标签大这么多；超过就是区块边框，不是芯片。
OUTLINE_CHIP_MAX_PAD = 20
#: 胶囊盒最多比标签大这么多；超过就是区块边框，不是芯片。
OUTLINE_CHIP_MAX_PAD = 20
#: 胶囊内边距至少这么大，紧贴字面的那一圈算抗锯齿。
OUTLINE_CHIP_MIN_PAD = 6
#: 细线芯片恢复：默认开启，但只作为"帧锁定后的视觉装饰层"，不成帧。
_CHIP_OUTLINE_ENABLED = True
#: 图片边缘/冒名控件/印章裁片三条子规则：默认开启，各自有独立前置条件。
_SETTLE_PICTURES_ENABLED = True
#: C 子规则（印章裁片补全）只在"图文双印"区域触发，普通图标一律不动。
_PICTURE_GROW_ENABLED = True
_PICTURE_TRIM_ENABLED = True
#: 卡片与页底色差至少这么大，才用填充色连通域去吸附它的盒。
SNAP_MIN_PAGE_GAP = 8
SNAP_MIN_CHANGE = 12
#: 连通域至少要盖住方案盒这么大比例，才算"这张盒子的底"；被徽章劈开的半张卡不算。
SNAP_MIN_COVER = 0.8
SNAP_MIN_OVERLAP = 30
SNAP_MIN_RIGHT_PULL = 30
#: 卡片吸附同样移到帧锁定之后：只加 paint 层，不改结构。
_SNAP_FILL_ENABLED = True
#: 主卡片级容器的下限：宽度占画布这个比例、且至少包住这么多条文字。
CARD_MIN_WIDTH_SHARE = 0.2
CARD_MIN_TEXT_MEMBERS = 2
CARD_MIN_HEIGHT = 120
#: 填充色吸附默认关闭：见 _settle_pictures_and_controls 上方的实测记录。
#: 图片来源的墨迹阈值：与自身表面差多少算"有内容"。
PICTURE_INK_TOLERANCE = 40
#: 墨迹同时压到上下边框这么多，说明这张裁片是被切断的形状，不是一行字。
PICTURE_CUT_SHARE = 0.3
#: 文字盒至少这么大比例落在裁片里，才算"图文双印"，而不是旁边那行字。
PICTURE_PRINT_SHARE = 0.35
#: 裁片右侧的墨迹距离文字起始多少像素内，才算"裁片画到了字上"。
PICTURE_TRIM_REACH = 4
#: 会被"裁到文字起始处"的裁片上限：大于这个尺寸的是插图，不是一段字形。
PICTURE_TRIM_MAX_WIDTH = 140
PICTURE_TRIM_MAX_HEIGHT = 72
#: 文字压在这张裁片上多大比例，才认为印章是它的宿主。
STAMP_HOST_SHARE = 0.25
#: 冒名小控件的框色与背后底色差这么多，就算"看得见的框"，不能删。
OUTLINE_IMPOSTOR_GAP = 12
#: 旋转后的四角允许超出宿主这么多像素（印章是斜的，盒子是正的）。
STAMP_ROTATION_SLACK = 8
#: 小于这个角度不转：手写印章也不会只歪 3°，而 3° 足以把导航文字转糊。
STAMP_MIN_ANGLE = 5.0
#: 会转的宿主必须小而成块：整屏的插图不是徽章。
STAMP_MAX_AREA_SHARE = 0.03
#: 徽章的长宽比范围，超出就说明它是个条形装饰。
STAMP_MAX_ASPECT = 2.0
PICTURE_GROW_PAD = 96
PICTURE_GROW_TOLERANCE = 48
#: 只有描边、没有独立填充的芯片：内芯是卡片色，边缘一圈比卡片亮 8 个通道以上。
CHIP_OUTLINE_MIN_DELTA = 8
CHIP_OUTLINE_MAX_DELTA = 90
CHIP_INNER_FILL = 0.8
CHIP_MIN_WIDTH = 30
CHIP_MAX_WIDTH = 260
CHIP_MIN_HEIGHT = 18
CHIP_MAX_HEIGHT = 80
CHIP_SEARCH_PAD = 30
PILL_MAX_REGIONS = 20
COLOUR_REGION_MAX = 40


def _recover_colour_regions(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    background: str,
) -> int:
    """Recover flat blocks of one colour that the plan never described.

    Thresholding against the page merges everything into one blob: the sidebar,
    the highlighted menu row inside it and the badge on top of that are one
    component because they all differ from the page.  Segmenting *per colour*
    separates them, and a fill that occupies more than 90% of its own bounding
    box is a block — a button, a highlight bar, a chip — while text covers less
    than half of its box and is dropped without a second thought.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return 0
    try:
        import cv2
    except Exception:  # pragma: no cover - opencv is a pipeline dependency
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    if image.ndim != 3:
        return 0
    image = image[:height, :width]
    page = np.asarray(_hex_rgb(background), dtype=np.int16) if background else None

    quantised = (image // 12).astype(np.int32)
    keys = quantised[:, :, 0] * 4096 + quantised[:, :, 1] * 64 + quantised[:, :, 2]
    values, counts = np.unique(keys.reshape(-1), return_counts=True)
    order = np.argsort(counts)[::-1]
    colours: list[tuple[int, int, int]] = []
    for position in order[:24]:
        if int(counts[position]) < COLOUR_REGION_MIN_SAMPLES:
            break
        key = int(values[position])
        sample = image.reshape(-1, 3)[keys.reshape(-1) == key]
        colour = tuple(int(value) for value in np.median(sample, axis=0))
        if page is not None and max(
            abs(one - two) for one, two in zip(colour, tuple(page))
        ) < SOFT_PANEL_MIN_DELTA:
            continue
        colours.append(colour)

    covered: list[tuple[tuple[int, int, int, int], str]] = []
    for element in elements:
        box = _layout_rect(element)
        if box is None:
            continue
        fill = _solid_fill(element)
        if fill:
            covered.append((box, fill))
        elif element.get("imageBase64"):
            covered.append((box, ""))

    canvas_area = max(1, width * height)
    found: list[tuple[int, tuple[int, int, int, int], str]] = []
    for colour in colours:
        target = np.asarray(colour, dtype=np.int16)
        mask = (
            np.abs(image - target).max(axis=2) <= COLOUR_REGION_TOLERANCE
        ).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            x, y, box_width, box_height, area = (
                int(value) for value in stats[index, :5]
            )
            if area < COLOUR_REGION_MIN_PIXELS:
                continue
            if box_width < COLOUR_REGION_MIN_SIDE or box_height < COLOUR_REGION_MIN_SIDE:
                continue
            if box_width * box_height > canvas_area * COLOUR_REGION_MAX_SHARE:
                continue
            if area / max(1, box_width * box_height) < COLOUR_REGION_MIN_FILL:
                continue
            found.append(
                (
                    area,
                    (x, y, box_width, box_height),
                    "#{:02x}{:02x}{:02x}".format(*colour),
                )
            )
    if not found:
        return 0
    found.sort(key=lambda item: item[0], reverse=True)
    added = 0
    for _area, box, fill in found:
        if added >= COLOUR_REGION_MAX:
            break
        if _already_painted(box, fill, covered):
            continue
        if any(_iou(box, other) >= 0.8 for other, _fill in covered):
            continue
        digest = hashlib.sha1(
            f"{box[0]}:{box[1]}:{box[2]}:{box[3]}:{fill}".encode("utf-8")
        ).hexdigest()[:16]
        elements.append(
            {
                "id": f"block:{digest}",
                "type": "container",
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "text": "",
                "style": {"fillColor": fill},
                "role": "panel",
                "name": "Colour block",
                "contentRef": f"block:{digest}",
                "sceneOwnerId": f"block:{digest}",
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "panel",
                    "grouping_status": "recovered",
                },
            }
        )
        covered.append((box, fill))
        added += 1
    return added


def _recover_pill_shapes(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    background: str,
) -> int:
    """Recover the capsules and rounded chips that carry words.

    The solid-panel pass requires a block to fill 90% of its own box, which is
    exactly what a capsule does not do: its four corners are rounded away, so it
    lands at 0.80-0.90 and is dropped.  That is how a nav item loses its pill and
    ends up as words lying directly on the page.

    The shape is what identifies it, and the shape is measurable:

    * all four corner patches are *not* the colour (roundness), while
    * the left and right mid-edge are the colour (it spans the full width).

    A line of text fails the second test; a square block fails the first.  The
    fill share sits between the solid pass's 0.90 and a bare block, so the two
    passes cannot both claim the same region.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return 0
    try:
        import cv2
    except Exception:  # pragma: no cover - opencv is a pipeline dependency
        return 0
    if not background:
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    if image.ndim != 3:
        return 0
    image = image[:height, :width]
    page = np.asarray(_hex_rgb(background), dtype=np.int16)

    quantised = (image // 12).astype(np.int32)
    keys = quantised[:, :, 0] * 4096 + quantised[:, :, 1] * 64 + quantised[:, :, 2]
    values, counts = np.unique(keys.reshape(-1), return_counts=True)
    order = np.argsort(counts)[::-1]

    covered: list[tuple[tuple[int, int, int, int], str]] = []
    for element in elements:
        box = _layout_rect(element)
        if box is None:
            continue
        fill = _solid_fill(element)
        if fill:
            covered.append((box, fill))
        elif element.get("imageBase64"):
            covered.append((box, ""))

    found: list[tuple[int, tuple[int, int, int, int], str, int]] = []
    for position in order[:24]:
        if int(counts[position]) < COLOUR_REGION_MIN_SAMPLES:
            break
        key = int(values[position])
        sample = image.reshape(-1, 3)[keys.reshape(-1) == key]
        colour = tuple(int(value) for value in np.median(sample, axis=0))
        if max(abs(one - two) for one, two in zip(colour, tuple(page))) < PILL_MIN_CONTRAST:
            continue
        target = np.asarray(colour, dtype=np.int16)
        mask = (np.abs(image - target).max(axis=2) <= COLOUR_REGION_TOLERANCE).astype(
            np.uint8
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            x, y, box_width, box_height, area = (int(value) for value in stats[index, :5])
            if not (PILL_MIN_WIDTH <= box_width <= PILL_MAX_WIDTH):
                continue
            if not (PILL_MIN_HEIGHT <= box_height <= PILL_MAX_HEIGHT):
                continue
            share = area / max(1, box_width * box_height)
            if not (PILL_MIN_FILL <= share <= PILL_MAX_FILL):
                continue
            if not _pill_corners_rounded(image, (x, y, box_width, box_height), target):
                continue
            if not _pill_spans_width(image, (x, y, box_width, box_height), target):
                continue
            radius = _pill_radius(image, (x, y, box_width, box_height), target, box_height)
            found.append(
                (
                    area,
                    (x, y, box_width, box_height),
                    "#{:02x}{:02x}{:02x}".format(*colour),
                    radius,
                )
            )

    if not found:
        return 0
    found.sort(key=lambda item: item[0], reverse=True)
    added = 0
    for _area, box, fill_hex, radius in found[:PILL_MAX_REGIONS]:
        if _already_painted(box, fill_hex, covered):
            continue
        digest = hashlib.sha1(
            f"pill:{box[0]}:{box[1]}:{box[2]}:{box[3]}:{fill_hex}".encode("utf-8")
        ).hexdigest()[:16]
        elements.append(
            {
                "id": f"pill:{digest}",
                "type": "container",
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "text": "",
                "style": {"fillColor": fill_hex, "borderRadius": radius},
                "role": "panel",
                "name": "Pill",
                "contentRef": f"pill:{digest}",
                "sceneOwnerId": f"pill:{digest}",
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "panel",
                    "grouping_status": "recovered",
                },
            }
        )
        covered.append((box, fill_hex))
        added += 1
    return added


def _pill_corners_rounded(image, box, target) -> bool:
    """All four corners are off-colour: the rectangle has been rounded."""
    import numpy as np

    x, y, box_width, box_height = box
    if box_width < 10 or box_height < 8:
        return False
    corners = (
        (x + 1, y + 1),
        (x + box_width - 4, y + 1),
        (x + 1, y + box_height - 4),
        (x + box_width - 4, y + box_height - 4),
    )
    for left, top in corners:
        patch = image[top : top + 3, left : left + 3]
        if patch.size == 0:
            return False
        if np.abs(patch - target).max(axis=2).min() <= PILL_CORNER_TOLERANCE:
            # A corner still holds the fill: a square block, not a capsule.
            return False
    return True


def _pill_spans_width(image, box, target) -> bool:
    """The left and right mid-edge carry the fill: it runs the full width."""
    import numpy as np

    x, y, box_width, box_height = box
    middle = y + box_height // 2
    for column in (x + 1, x + box_width - 2):
        patch = image[middle - 1 : middle + 2, column : column + 1]
        if patch.size == 0:
            return False
        if np.abs(patch - target).max(axis=2).min() > COLOUR_REGION_TOLERANCE:
            return False
    return True


def _pill_radius(image, box, target, box_height: int) -> int:
    """Corner inset measured on the top row: how far in the fill starts."""
    import numpy as np

    x, y, box_width, _box_height = box
    row = image[y + 1, x : x + box_width]
    if row.size == 0:
        return max(2, min(box_height // 2, 8))
    inside = np.abs(row - target).max(axis=1) <= COLOUR_REGION_TOLERANCE
    if not inside.any():
        return max(2, min(box_height // 2, 8))
    inset = int(np.argmax(inside))
    return int(max(2, min(box_height // 2, inset, 24)))


def _reflow_key(text: str) -> str:
    """Words comparable across OCR and the model, punctuation included.

    OCR prints a half-width colon where the model wrote a full-width one, so the
    punctuation is folded as well; everything else is the fold the duplicate
    passes already use.  Whitespace is dropped: a line break is exactly what is
    being reconstructed.
    """
    folded = _tail_key({"text": text})
    return folded.translate(
        str.maketrans({"：": ":", "，": ",", "。": ".", "；": ";", "（": "(", "）": ")", "、": ","})
    )


def _reflow_paragraphs(
    elements: list[dict[str, Any]],
    ocr_observations: Sequence[Mapping[str, Any]] | None,
    image_path: str | Path | None = None,
    background: str | None = None,
) -> int:
    """Give a paragraph back the lines the picture actually has.

    The plan models a card's description as one string in a one-line-tall box.
    The picture wraps that string over two lines, so the browser prints one long
    line, the patch pass fills the second line with a picture of it, and Figma —
    which wraps inside the box — draws two lines on top of each other.  Three
    renderers, three wrong answers, one cause: nobody went back to the OCR lines.

    This pass does, and only when the lines agree with the node's own words: the
    seed line has to overlap the box, the chain has to grow downwards in the same
    horizontal band, and the joined text has to match the node at
    ``PARAGRAPH_REFLOW_MIN_SIMILARITY``.  The node keeps the model's wording —
    the OCR lines only say *where* to break it — because OCR misreads characters
    ("Al" for "AI") and the model does not.
    """
    if not ocr_observations:
        return 0
    # A column of page colour between two blocks is the geometry that says they
    # are not the same paragraph.  Read from the picture, so a three-column table
    # or a single centred card behaves the same way.
    picture = None
    if image_path and background:
        try:
            import numpy as _np
            from PIL import Image as _Image

            picture = _np.asarray(_Image.open(image_path).convert("RGB"), dtype=_np.int16)
        except (OSError, ValueError):
            picture = None

    def _separated(one: Sequence[int], two: Sequence[int]) -> bool:
        if picture is None or not background:
            return False
        from src.app.services.structure.fidelity.pixel_probe import separated_by_page

        return separated_by_page(picture, str(background), one, two)
    import numpy as np

    lines = []
    for observation in ocr_observations:
        box = observation.get("bbox")
        text = str(observation.get("text") or "").strip()
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            x, y, w, h = (float(value) for value in box)
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        lines.append({"text": text, "key": _reflow_key(text), "box": (x, y, w, h)})
    if not lines:
        return 0

    reflowed = 0
    for element in elements:
        if element.get("type") != "text" or not element.get("text"):
            continue
        if element.get("lines"):
            continue
        style = element.get("style") or {}
        size = float(style.get("fontSize") or 0)
        height = float(element.get("height") or 0)
        if size <= 0 or height <= 0 or height > size * 1.7:
            continue
        node_key = _reflow_key(str(element.get("text") or ""))
        if len(node_key) < PARAGRAPH_REFLOW_MIN_CHARS:
            continue
        box = _layout_rect(element)
        if box is None:
            continue
        seed = _reflow_seed(lines, box, node_key)
        if seed is None:
            continue
        chain = _reflow_chain(lines, seed, box, node_key, separated=_separated)
        if len(chain) < 2:
            continue
        joined = "".join(line["key"] for line in chain)
        from difflib import SequenceMatcher

        if SequenceMatcher(None, joined, node_key).ratio() < PARAGRAPH_REFLOW_MIN_SIMILARITY:
            continue
        counts = [len(line["key"]) for line in chain]
        parts = _split_by_lengths(str(element.get("text") or ""), counts)
        if len(parts) < 2 or not all(parts):
            continue
        left = min(line["box"][0] for line in chain)
        top = min(line["box"][1] for line in chain)
        right = max(line["box"][0] + line["box"][2] for line in chain)
        bottom = max(line["box"][1] + line["box"][3] for line in chain)
        pitches = [
            chain[index + 1]["box"][1] - chain[index]["box"][1]
            for index in range(len(chain) - 1)
        ]
        pitch = float(np.median(pitches)) if pitches else float(height)
        element["x"] = round(left, 1)
        element["y"] = round(top, 1)
        element["width"] = round(right - left, 1)
        element["height"] = round(bottom - top, 1)
        element["lines"] = parts
        element["lineHeight"] = round(pitch, 1)
        element["lineHeightPolicy"] = "observed"
        element["textAnchor"] = "start"
        element["reflowEvidence"] = {
            "method": "ocr-lines",
            "lines": len(chain),
            "pitch": round(pitch, 1),
            "similarity": round(
                SequenceMatcher(None, joined, node_key).ratio(), 3
            ),
        }
        reflowed += 1
    return reflowed


def _reflow_seed(
    lines: Sequence[Mapping[str, Any]],
    box: tuple[int, int, int, int],
    node_key: str,
) -> Mapping[str, Any] | None:
    """The OCR line this node starts on: over the box's first line, first words agree."""
    x, y, w, h = box
    best = None
    best_score = 0.0
    for line in lines:
        lx, ly, lw, lh = line["box"]
        if ly > y + h * 0.8:
            continue
        if ly + lh < y + h * 0.2:
            continue
        overlap = min(x + w, lx + lw) - max(x, lx)
        if overlap < min(w, lw) * PARAGRAPH_REFLOW_BAND_SHARE:
            continue
        key = str(line["key"])
        if not key or not node_key.startswith(key[: max(4, len(key) // 2)]):
            continue
        score = len(key) / max(1, len(node_key))
        if score > best_score:
            best = line
            best_score = score
    return best


def _reflow_chain(
    lines: Sequence[Mapping[str, Any]],
    seed: Mapping[str, Any],
    box: tuple[int, int, int, int],
    node_key: str,
    separated: Any = None,
) -> list[Mapping[str, Any]]:
    """Follow the seed downwards while the lines still spell the node's words.

    Geometry alone would happily eat the meta row under the paragraph ("TSX ·
    4 小时前"), so every step also has to be the next piece of the sentence:
    the remaining text must start with the candidate's words.  That is what
    makes the chain stop at the paragraph's last line instead of the card's.
    """
    x, _y, w, _h = box
    chain = [seed]
    cursor = seed
    consumed = len(str(seed["key"]))
    while consumed < len(node_key) and len(chain) < PARAGRAPH_REFLOW_MAX_LINES:
        current_bottom = cursor["box"][1] + cursor["box"][3]
        remaining = node_key[consumed:]
        candidates = []
        for line in lines:
            if line in chain:
                continue
            lx, ly, lw, lh = line["box"]
            gap = ly - current_bottom
            if gap < -cursor["box"][3] * 0.4 or gap > cursor["box"][3] * PARAGRAPH_REFLOW_MAX_GAP:
                continue
            overlap = min(x + w, lx + lw) - max(x, lx)
            if overlap < lw * PARAGRAPH_REFLOW_BAND_SHARE:
                continue
            # Two columns of a layout are not one paragraph, whatever the words
            # say: a strip of page between them is enough to say no.
            if separated is not None and separated(cursor["box"], line["box"]):
                continue
            candidates.append((gap, line))
        if not candidates:
            break
        candidates.sort(key=lambda item: item[0])
        picked = None
        for _gap, line in candidates:
            key = str(line["key"])
            if key and remaining.startswith(key):
                picked = line
                break
        if picked is None:
            # The last line of the picture may hold more than the model wrote;
            # accept it when the remaining words are its prefix.
            for _gap, line in candidates:
                key = str(line["key"])
                if key and len(remaining) >= 4 and key.startswith(remaining[: max(4, len(remaining) - 2)]):
                    picked = line
                    break
        if picked is None:
            break
        chain.append(picked)
        cursor = picked
        consumed += len(str(picked["key"]))
    return chain


def _split_by_lengths(text: str, counts: Sequence[int]) -> list[str]:
    """Cut the model's own words at the character counts the picture used."""
    parts: list[str] = []
    position = 0
    consumed = 0
    start = 0
    for index, limit in enumerate(counts):
        last = index == len(counts) - 1
        target = consumed + limit
        while position < len(text) and (last or consumed < target):
            char = text[position]
            position += 1
            if not char.isspace():
                consumed += 1
        parts.append(text[start:position].strip())
        start = position
    return parts


def _recover_page_fill(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    background: str,
) -> bool:
    """Paint the canvas in the colours the screenshot's own margins are.

    The plan declares a page colour, and a page is not always that colour:
    review's ground is a pale blue gradient declared #fefefe, so every pixel
    outside a card was 34 channels off and no rule downstream could see it —
    the fill was "correct" by declaration.  The margin of the picture is the
    only witness that cannot be wrong.

    One rect would flatten the gradient into a step, so the ground is laid down
    in horizontal bands, each sampling its own margins.  A page that really is
    one colour produces identical bands and costs nothing.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return False
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return False
    if image.ndim != 3:
        return False
    image = image[:height, :width]
    edges = [
        image[0:4].reshape(-1, 3),
        image[max(0, height - 4) : height].reshape(-1, 3),
        image[:, 0:4].reshape(-1, 3),
        image[:, max(0, width - 4) : width].reshape(-1, 3),
    ]
    medians = [np.median(edge, axis=0) for edge in edges if edge.size]
    if not medians:
        return False
    # The page is one colour on all four sides.  A sidebar or a dark header owns
    # one edge, and a page read off that edge paints the whole canvas wrong.
    agreeing = [
        median
        for median in medians
        if sum(
            1
            for other in medians
            if float(np.abs(median - other).max()) <= 24
        )
        >= 3
    ]
    if not agreeing:
        return False
    declared = tuple(int(value) for value in _hex_rgb(background)) if background else None
    spread = max(
        (
            float(np.abs(left - right).max())
            for left in agreeing
            for right in agreeing
        ),
        default=0.0,
    )
    if spread > PAGE_EDGE_SPLIT:
        # The four edges are two different surfaces, not one page: marketplace is
        # #1a1917 at top and bottom and #100f0d down both sides.  Averaging them
        # produced #151412 — a colour that matches the declared background, so the
        # whole calibration bailed out and the page kept its wrong base.  Vote
        # instead, and break a tie towards the side the declaration got wrong.
        votes = [
            (
                sum(
                    1
                    for other in agreeing
                    if float(np.abs(median - other).max()) <= PAGE_EDGE_SPLIT
                ),
                0.0
                if declared is None
                else float(np.abs(median - np.asarray(declared, dtype=np.float64)).max()),
                median,
            )
            for median in agreeing
        ]
        colour = tuple(
            int(value) for value in max(votes, key=lambda vote: (vote[0], vote[1]))[2]
        )
    else:
        colour = tuple(int(value) for value in np.median(agreeing, axis=0))
    hexed = "#{:02x}{:02x}{:02x}".format(*colour)
    if background and _same_fill(hexed, background, SOFT_PANEL_MIN_DELTA):
        return False

    # Bands: each one reads its own left and right margins — the page is what
    # shows at the edges — but only the margin pixels nothing else owns.  review
    # is the reason: its top band has a gradient on the left and a white card
    # touching the right edge, so the median of the two was a colour that exists
    # nowhere (#dee7fb against a truth of #f2f5fb).  Unowned interior pixels are
    # not the page either — on the bottom band they are mostly a card — so the
    # sample stays at the margins and simply excludes what has been painted.
    strip = max(4, min(24, width // 40))
    covered = np.zeros((height, width), dtype=bool)
    for element in elements:
        box = _layout_rect(element)
        if box is None:
            continue
        x, y, w, h = box
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(width, int(x + w)), min(height, int(y + h))
        if x1 <= x0 or y1 <= y0:
            continue
        if _solid_fill(element) or element.get("imageBase64"):
            covered[y0:y1, x0:x1] = True

    bands: list[tuple[int, int, str]] = []
    previous: tuple[int, int, int] | None = None
    for band in range(PAGE_BANDS):
        top = height * band // PAGE_BANDS
        bottom = height * (band + 1) // PAGE_BANDS
        if bottom - top < 2:
            continue
        sides: list[tuple[int, int, int]] = []
        for attempt in range(3):
            width_strip = strip * (2**attempt)
            for left_edge in (True, False):
                if left_edge:
                    crop = image[top:bottom, 0:width_strip]
                    free = covered[top:bottom, 0:width_strip]
                else:
                    crop = image[top:bottom, max(0, width - width_strip) : width]
                    free = covered[top:bottom, max(0, width - width_strip) : width]
                pixels = crop[~free]
                if pixels.size and pixels.reshape(-1, 3).shape[0] >= max(
                    24, (bottom - top) // 4
                ):
                    median = np.median(pixels.reshape(-1, 3), axis=0)
                    sides.append(tuple(int(value) for value in median))
            if sides:
                break
        if not sides:
            continue
        # Two margins that disagree are two different surfaces: one of them is a
        # card that reaches the edge.  Averaging them invents a colour, so the
        # band takes the side that continues the band above it.
        if len(sides) == 1:
            band_colour = sides[0]
        else:
            left_colour, right_colour = sides[0], sides[-1]
            if max(abs(a - b) for a, b in zip(left_colour, right_colour)) <= 8:
                band_colour = left_colour
            elif previous is not None:
                band_colour = min(
                    (left_colour, right_colour),
                    key=lambda colour: max(
                        abs(a - b) for a, b in zip(colour, previous)
                    ),
                )
            else:
                band_colour = left_colour
        previous = band_colour
        if declared is not None and max(
            abs(band_colour[index] - declared[index]) for index in range(3)
        ) < PAGE_BAND_MIN_DELTA:
            continue
        bands.append(
            (top, bottom, "#{:02x}{:02x}{:02x}".format(*band_colour))
        )
    if not bands:
        return False
    if len({colour for _top, _bottom, colour in bands}) == 1:
        bands = [(0, height, bands[0][2])]
    placed = 0
    for top, bottom, band_colour in bands:
        digest = hashlib.sha1(
            f"page:{band_colour}:{top}:{bottom}".encode("utf-8")
        ).hexdigest()[:16]
        elements.insert(
            placed,
            {
                "id": f"page:{digest}",
                "type": "container",
                "x": 0,
                "y": top,
                "width": width,
                "height": bottom - top,
                "text": "",
                "style": {"fillColor": band_colour},
                "role": "page-ground",
                "name": "Page ground",
                "contentRef": f"page:{digest}",
                "sceneOwnerId": f"page:{digest}",
                "zIndex": -2,
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "page-ground",
                    "grouping_status": "recovered",
                },
            },
        )
        placed += 1
    return True


def _recover_chip_outlines(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
) -> int:
    """Give a stroke-only chip the 1px outline it is drawn with.

    A chip whose fill is its card's own colour is invisible to every fill-based
    pass: `_recover_pill_shapes` wants four corners off-colour and two mid-edges
    on-colour, and `_already_painted` calls it "same fill as the card".  What is
    actually there is a hairline ring.

    The search is anchored on the words, not on the page: a whole-card scan
    fragments the ring into the text around it (1556 components, none in range),
    while a 30px window around one label yields exactly one ring.  A label with
    no ring around it produces nothing, which is why the four model chips are
    found and "输入 · 峰时" is not.
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    image = image[:height, :width]
    added = 0
    page_fill = _page_fill(elements, "#000000")
    page_rgb = np.asarray(_hex_rgb(page_fill), dtype=np.int16)
    boxes = [
        (_layout_rect(element), element)
        for element in elements
        if _layout_rect(element) and element.get("type") == "container"
    ]
    # Anything already modelled at this size is not a chip we are missing — the
    # two buttons in the same row have a faint ring too, and a second container
    # over them would double the paint.
    painted = [
        _layout_rect(element)
        for element in elements
        if _layout_rect(element)
        and element.get("type") in ("image", "button", "input", "container")
        and str(element.get("role") or "") not in ("page-ground",)
    ]
    painted = [box for box in painted if box]
    for label in [
        element
        for element in elements
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]:
        text_box = _layout_rect(label)
        if text_box is None or text_box[2] < 20 or text_box[3] < 14:
            continue
        # The innermost container with a *surface* colour, not the page: after
        # the paint pass the card itself is transparent page colour, and reading
        # a chip's ring against the page turns the whole card into "outline".
        owner = None
        for box, element in boxes:
            if not _rect_contains(box, text_box, tolerance=2):
                continue
            candidate_fill = _solid_fill(element)
            if not candidate_fill:
                continue
            if _same_fill(candidate_fill, page_fill, SOFT_PANEL_MIN_DELTA):
                continue
            if owner is None or box[2] * box[3] < owner[0][2] * owner[0][3]:
                owner = (box, element)
        if owner is None:
            continue
        fill = _solid_fill(owner[1])
        if not fill:
            continue
        x, y, w, h = text_box
        pad = OUTLINE_CHIP_SEARCH_PAD
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(width, x + w + pad), min(height, y + h + pad)
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        colour = np.asarray(_hex_rgb(fill), dtype=np.int16)
        delta = np.abs(crop - colour).max(axis=2)
        faint = (
            (delta >= CHIP_OUTLINE_MIN_DELTA) & (delta <= CHIP_OUTLINE_MAX_DELTA)
        ).astype(np.uint8)
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(faint, 8)
        for index in range(1, count):
            bx, by, bw, bh, _area = (int(value) for value in stats[index])
            if not (
                OUTLINE_CHIP_MIN_WIDTH <= bw <= OUTLINE_CHIP_MAX_WIDTH
                and OUTLINE_CHIP_MIN_HEIGHT <= bh <= OUTLINE_CHIP_MAX_HEIGHT
            ):
                continue
            ax, ay = bx + x0, by + y0
            inside = (
                ax - 6 <= x
                and ay - 6 <= y
                and ax + bw + 6 >= x + w
                and ay + bh + 6 >= y + h
            )
            if not inside:
                continue
            # 真正的胶囊在文字四周留着一圈内边距。紧贴字面的那一圈是抗锯齿，
            # 不是描边——白底卡片上尤其明显。
            if (
                x - ax < OUTLINE_CHIP_MIN_PAD
                or y - ay < OUTLINE_CHIP_MIN_PAD // 2
                or (ax + bw) - (x + w) < OUTLINE_CHIP_MIN_PAD
                or (ay + bh) - (y + h) < OUTLINE_CHIP_MIN_PAD // 2
            ):
                continue
            # 一只胶囊只装一行字。套住两行、或左右留白超过一只胶囊的边距，
            # 那圈线是整个区块的边框，不是这一个标签的芯片。
            if (
                bw > w + 2 * OUTLINE_CHIP_MAX_PAD
                or bh > h + 2 * OUTLINE_CHIP_MAX_PAD
            ):
                continue
            area = bw * bh
            # 只认"一圈细线"：连通域的面积得接近周长乘线宽。一块实心色块也满足
            # 尺寸范围，但它不是描边，画上去就是给卡片糊一块底。
            thin = OUTLINE_CHIP_MAX_THICKNESS * 2 * (bw + bh)
            if _area > thin:
                continue
            if any(
                _overlap_share((ax, ay, bw, bh), other) >= 0.7
                for other in painted
                if other[2] * other[3] <= area * 3
            ):
                continue
            ring = np.concatenate(
                [
                    crop[by, bx : bx + bw].reshape(-1, 3),
                    crop[by + bh - 1, bx : bx + bw].reshape(-1, 3),
                ]
            )
            ring_colour = np.median(ring, axis=0)
            if int(np.abs(ring_colour - colour).max()) < CHIP_OUTLINE_MIN_DELTA:
                continue
            # 白底卡片上一圈白线不是描边，是两张近白面之间的缝。线上必须和页面
            # 有色差，否则画出来只是一块同色底板。
            if int(np.abs(ring_colour - page_rgb).max()) < CHIP_OUTLINE_MIN_DELTA:
                continue
            stroke = "#{:02x}{:02x}{:02x}".format(*(int(v) for v in ring_colour))
            # 标签已经被现有控件包着（button / input / panel 的盒把它整个盖住），
            # 再画一圈就是重复套框：AtomGit 的工具栏按钮全属这种情况。
            if _wrapped_by_control(elements, (x, y, w, h), ignore=label):
                continue
            outline = {
                "id": f"chip-outline:{ax}:{ay}",
                "type": "container",
                "role": "panel",
                "x": ax,
                "y": ay,
                "width": bw,
                "height": bh,
                "text": "",
                "style": {
                    "fillColor": fill,
                    "borderColor": stroke,
                    "borderWidth": 1,
                    "borderRadius": min(14, max(8, bh // 3)),
                },
                "name": "Chip outline",
                # 装饰层的笔：画在标签下面，不是任何帧的成员，也不是外人。
                "paintBackdrop": True,
                "contentRef": f"chip-outline:{ax}:{ay}",
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "chip-outline",
                    "grouping_status": "recovered",
                },
            }
            # 插在标签之前：装饰层永远在文字之下，文字永远在它之上。
            elements.insert(elements.index(label), outline)
            added += 1
            break
    return added


def _wrapped_by_control(
    elements: Sequence[Mapping[str, Any]],
    box: tuple[int, int, int, int],
    *,
    ignore: Mapping[str, Any] | None = None,
) -> bool:
    """Whether an existing control already draws a box around these words.

    A label inside a real button already has the button's own border; the ring
    the pixel pass finds around it is that border, not a missing chip.  Only a
    *tight* panel counts — the card the chip sits on contains the words too, and
    treating that as "already wrapped" would drop every chip on the page.
    """
    for element in elements:
        if element is ignore:
            continue
        kind = str(element.get("type") or "")
        role = str(element.get("role") or "")
        other = _layout_rect(element)
        if other is None:
            continue
        if kind in ("button", "input"):
            if _rect_contains(other, box, tolerance=6):
                return True
            continue
        if kind != "container" or role not in ("panel", "chip"):
            continue
        if (
            other[2] <= box[2] + 2 * OUTLINE_CHIP_WRAP_PAD
            and other[3] <= box[3] + 2 * OUTLINE_CHIP_WRAP_PAD
            and _rect_contains(other, box, tolerance=6)
        ):
            return True
    return False


def _picture_stats(
    image,
    width: int,
    height: int,
    box: tuple[int, int, int, int],
) -> dict[str, Any] | None:
    """Ink summary of one crop: how much of each edge it touches, and its colour."""
    import numpy as np

    x, y, w, h = box
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    crop = image[y0:y1, x0:x1]
    surface = np.median(
        np.concatenate([crop[:2].reshape(-1, 3), crop[-2:].reshape(-1, 3)]), axis=0
    )
    ink = np.abs(crop - surface).max(axis=2) > PICTURE_INK_TOLERANCE
    if not ink.any():
        return None
    return {
        "ink": ink,
        "colour": np.median(crop[ink], axis=0),
        "top": float(ink[0].mean()),
        "bottom": float(ink[-1].mean()),
        "left": float(ink[:, 0].mean()),
        "right": float(ink[:, -1].mean()),
        "colours": np.flatnonzero(ink.any(axis=0)),
    }


def _picture_guests(
    elements: Sequence[Mapping[str, Any]],
    picture: Mapping[str, Any],
    box: tuple[int, int, int, int],
    skip: set[str],
) -> list[dict[str, Any]]:
    """Text nodes printed on top of this crop."""
    guests = []
    for text in elements:
        if text is picture or text.get("type") != "text":
            continue
        if not str(text.get("text") or "").strip():
            continue
        if str(text.get("id") or "") in skip:
            continue
        text_box = _layout_rect(text)
        if text_box is None:
            continue
        if _overlap_share(text_box, box) >= 0.25:
            guests.append(text)
    return guests


def _surface_behind(
    elements: Sequence[Mapping[str, Any]],
    box: tuple[int, int, int, int],
) -> str:
    """The colour a control's own fill has to differ from to be a real surface."""
    owner_fill, owner_area = "", 0
    for element in elements:
        if element.get("type") != "container":
            continue
        other = _layout_rect(element)
        if other is None or not _rect_contains(other, box, tolerance=2):
            continue
        fill = _solid_fill(element)
        if not fill:
            continue
        area = other[2] * other[3]
        if not owner_area or area < owner_area:
            owner_fill, owner_area = fill, area
    return owner_fill


def _complete_stamp_crops(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
) -> tuple[int, int]:
    """Sub-rule C: complete a cut stamp, but only where the words are on top.

    A crop that runs off its own top *and* bottom edges is a fragment of a shape
    rather than a whole icon, and that shape is the seal the picture drew.  The
    second condition is what keeps this rule away from ordinary icons: a text
    node has to be printing on the same pixels — the 图文双印 a tilted seal
    produces.  AtomGit's fifty-odd toolbar icons sit fully inside their boxes and
    carry no words, so none of them qualifies.

    Those words are dropped afterwards: the seal already contains them, and a
    horizontal copy on top of tilted pixels is exactly the double print.
    """
    import numpy as np
    from PIL import Image

    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0, 0
    image = image[:height, :width]
    grown = 0
    doomed: set[str] = set()
    for picture in list(elements):
        if not picture.get("imageBase64"):
            continue
        box = _layout_rect(picture)
        if box is None or box[2] < 24 or box[3] < 16:
            continue
        stats = _picture_stats(image, width, height, box)
        if stats is None:
            continue
        if not (
            stats["top"] >= PICTURE_CUT_SHARE and stats["bottom"] >= PICTURE_CUT_SHARE
        ):
            continue
        overprinted = [
            text
            for text in _picture_guests(elements, picture, box, doomed)
            if _overlap_share(_layout_rect(text), box) >= PICTURE_PRINT_SHARE
        ]
        if not overprinted:
            continue
        colour = stats["colour"]
        pad = PICTURE_GROW_PAD
        window = (
            max(0, box[0] - pad),
            max(0, box[1] - pad),
            min(width, box[0] + box[2] + pad),
            min(height, box[1] + box[3] + pad),
        )
        crop = image[window[1] : window[3], window[0] : window[2]]
        mask = (np.abs(crop - colour).max(axis=2) <= PICTURE_GROW_TOLERANCE).astype(
            np.uint8
        )
        try:
            import cv2

            labels_count, _labels, comp_stats, _c = cv2.connectedComponentsWithStats(
                mask, 8
            )
        except Exception:  # pragma: no cover
            labels_count = 0
        if labels_count <= 1:
            continue
        keep = np.zeros(mask.shape, dtype=bool)
        for label in range(1, labels_count):
            bx, by, bw, bh, _area = (int(value) for value in comp_stats[label])
            absolute = (window[0] + bx, window[1] + by, bw, bh)
            if _overlap_share(absolute, box) > 0.0:
                keep[by : by + bh, bx : bx + bw] = True
        rows = np.flatnonzero(keep.any(axis=1))
        cols = np.flatnonzero(keep.any(axis=0))
        if not rows.size or not cols.size:
            continue
        new_box = (
            window[0] + int(cols[0]),
            window[1] + int(rows[0]),
            int(cols[-1] - cols[0] + 1),
            int(rows[-1] - rows[0] + 1),
        )
        if new_box[2] * new_box[3] <= box[2] * box[3]:
            continue
        from src.app.services.structure.image_contract import crop_image_b64

        encoded = crop_image_b64(
            image_path,
            new_box[0],
            new_box[1],
            new_box[2],
            new_box[3],
            width,
            height,
        )
        if not encoded:
            continue
        picture["imageBase64"] = encoded
        picture["x"], picture["y"] = new_box[0], new_box[1]
        picture["width"], picture["height"] = new_box[2], new_box[3]
        grown += 1
        for text in overprinted:
            doomed.add(str(text.get("id") or ""))
    if doomed:
        elements[:] = [
            element
            for element in elements
            if str(element.get("id") or "") not in doomed
        ]
    return grown, len(doomed)


def _ink_reaches(columns, cut: int, reach: int) -> bool:
    """Whether any ink sits within ``reach`` pixels of ``cut`` (a column index)."""
    import numpy as np

    if columns is None or not len(columns):
        return False
    return bool(np.min(np.abs(np.asarray(columns) - int(cut))) <= int(reach))


def _trim_pictures_under_text(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
) -> int:
    """Sub-rule A: a crop that prints into the words beside it ends where they do.

    The crop carries a second copy of the first glyphs of its label — "Kimi" with
    the logo, the model name with its mark — so it is cut at the first column the
    words occupy.  Nothing else about the crop changes.
    """
    import numpy as np
    from PIL import Image

    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    image = image[:height, :width]
    trimmed = 0
    for picture in list(elements):
        if not picture.get("imageBase64"):
            continue
        box = _layout_rect(picture)
        if box is None or box[2] < 24 or box[3] < 16:
            continue
        # 只有"一小段字形"会被裁：照片、插图、整块图标即使旁边有字，也不能切。
        if box[2] > PICTURE_TRIM_MAX_WIDTH or box[3] > PICTURE_TRIM_MAX_HEIGHT:
            continue
        stats = _picture_stats(image, width, height, box)
        if stats is None:
            continue
        if stats["top"] >= PICTURE_CUT_SHARE and stats["bottom"] >= PICTURE_CUT_SHARE:
            # A cut shape belongs to sub-rule C; this one only handles a whole
            # crop whose right edge prints into the label.
            continue
        for text in _picture_guests(elements, picture, box, set()):
            text_box = _layout_rect(text)
            if text_box is None:
                continue
            if not (box[0] + 4 < text_box[0] < box[0] + box[2]):
                continue
            cut = int(text_box[0] - box[0])
            # 只有墨迹真的画到文字起始处，才叫"裁片压到字上"。图标旁边正好是
            # 一行字、而图标自己的墨早在一半就结束时，裁掉的是图标本身。
            if not _ink_reaches(stats["colours"], cut, PICTURE_TRIM_REACH):
                continue
            keep_width = cut - 2
            if keep_width < 12:
                continue
            picture["width"] = keep_width
            trimmed += 1
            break
    return trimmed


def _drop_impostor_controls(
    elements: list[dict[str, Any]],
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Sub-rule B: a borderless mini control printing over real words is a ghost.

    "输入 · 峰时" was covered by a 48x23 button the plan had moved there; its
    rounded border printed straight across the word.  A genuine control has a
    label the picture reads at the control's own box, so the test is OCR support
    at the *text* node's box, not at the control's.
    """
    texts = [
        element
        for element in elements
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    dropped = 0
    for element in list(elements):
        if element.get("type") not in ("button", "input"):
            continue
        label = str(element.get("text") or "").strip()
        if not label:
            continue
        box = _layout_rect(element)
        if box is None:
            continue
        if _ocr_carries(label, box, ocr_observations):
            continue
        style = element.get("style") or {}
        fill = str(style.get("fillColor") or "")
        border_width = int(style.get("borderWidth") or 0)
        behind = _surface_behind(elements, box)
        if border_width > 0:
            border = str(style.get("borderColor") or "")
            if not behind or not _same_fill(border, behind, OUTLINE_IMPOSTOR_GAP):
                # 真有框、且框色和背后的底不一样：这是正经控件。
                continue
        if fill and behind and not _same_fill(fill, behind, 4):
            # 真有自己的一块底：不是"无底色小框"。
            continue
        for text in texts:
            text_box = _layout_rect(text)
            if text_box is None:
                continue
            if _overlap_share(box, text_box) >= 0.6 and not _ocr_carries(
                label, text_box, ocr_observations
            ):
                elements.remove(element)
                dropped += 1
                break
    return dropped


def _rotated_bbox(
    box: tuple[int, int, int, int], angle: float
) -> tuple[float, float, float, float]:
    """Axis-aligned box a rotated rectangle occupies (degrees, anticlockwise)."""
    import math

    x, y, w, h = (float(value) for value in box)
    theta = math.radians(-angle)
    cos, sin = math.cos(theta), math.sin(theta)
    cx, cy = x + w / 2.0, y + h / 2.0
    corners = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        corners.append((cx + dx * cos - dy * sin, cy + dx * sin + dy * cos))
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _in_navigation(
    elements: Sequence[Mapping[str, Any]], box: tuple[int, int, int, int]
) -> bool:
    """Whether this box sits inside a sidebar / menu / nav container."""
    for element in elements:
        if element.get("type") != "container":
            continue
        role = str(element.get("role") or "")
        if role not in ("sidebar", "sidebar-menu", "nav", "menu", "navigation"):
            continue
        outer = _layout_rect(element)
        if outer is not None and _rect_contains(outer, box, tolerance=2):
            return True
    return False

def _measure_stamp_rotations(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
) -> int:
    """Give a tilted seal's words their real angle, and drop the level copies.

    The angle is measured from the *picture* under the words, not from the words
    themselves: a text box is axis-aligned by construction, while the seal's ink
    is a rotated rectangle that `minAreaRect` reads directly.  The picture is
    never rotated — its pixels already carry the tilt, and rotating the crop
    would tilt it twice — so this pass only touches vector nodes standing in for
    the stamp's type.

    A copy of the same words that stays level inside the same seal is the second
    print the eye reads as a shadow, so it goes.
    """
    import numpy as np
    from PIL import Image

    from src.app.services.structure.fidelity.rotation import estimate_rotation

    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    image = image[:height, :width]
    pictures = [
        element
        for element in elements
        if element.get("imageBase64") and _layout_rect(element) is not None
    ]
    if not pictures:
        return 0
    owners = [
        element
        for element in elements
        if element.get("type") == "container" and _layout_rect(element) is not None
    ]
    rotated = 0
    doomed: set[str] = set()
    for element in list(elements):
        if element.get("type") != "text" or not str(element.get("text") or "").strip():
            continue
        if str(element.get("id") or "") in doomed:
            continue
        if element.get("rotation"):
            continue
        box = _layout_rect(element)
        if box is None or box[2] < 12 or box[3] < 10:
            continue
        host, host_share = None, 0.0
        for picture in pictures:
            share = _overlap_share(box, _layout_rect(picture))
            if share > host_share:
                host, host_share = picture, share
        if host is None or host_share < STAMP_HOST_SHARE:
            continue
        host_box = _layout_rect(host)
        # 只有"孤立的倾斜徽章"才转。侧边栏菜单项、普通小图标旁边也可能有
        # 一块深色裁片，一转就把整行导航拧歪（盲测里 worklog 的"个人信息"、
        # gmail 的"推广"标签都是这么被转坏的）。
        if _in_navigation(elements, box):
            continue
        if host_box[2] * host_box[3] > width * height * STAMP_MAX_AREA_SHARE:
            continue
        ratio = host_box[2] / max(1.0, float(host_box[3]))
        if not (1.0 / STAMP_MAX_ASPECT <= ratio <= STAMP_MAX_ASPECT):
            continue
        angle = estimate_rotation(image, host_box)
        if not angle or abs(angle) < STAMP_MIN_ANGLE:
            continue
        turned = _rotated_bbox(box, angle)
        # 文字的中心必须落在这张印章里，否则就是把旁边的字也转了。旋转后 AABB
        # 必然比原盒大（斜着放的盒子就是这么算的），所以判中心不判四角。
        cx = box[0] + box[2] / 2.0
        cy = box[1] + box[3] / 2.0
        if not _rect_contains(
            host_box, (int(cx), int(cy), 1, 1), tolerance=STAMP_ROTATION_SLACK
        ):
            continue
        # 帧成员被钉死在自己的帧里，旋转后超出帧界会被裁掉。
        for owner in owners:
            owner_box = _layout_rect(owner)
            if _rect_contains(owner_box, box, tolerance=2):
                if not _rect_contains(
                    owner_box, turned, tolerance=STAMP_ROTATION_SLACK
                ):
                    host = None
                    break
        if host is None:
            continue
        element["rotation"] = angle
        element.setdefault("rotationEvidence", {})["stamp"] = {
            "angle": angle,
            "host": str(host.get("id") or ""),
        }
        rotated += 1
        label = str(element.get("text") or "").strip()
        for other in elements:
            if other is element or other.get("type") != "text":
                continue
            if other.get("rotation") or str(other.get("id") or "") in doomed:
                continue
            other_box = _layout_rect(other)
            if other_box is None:
                continue
            if _overlap_share(other_box, box) < 0.5:
                continue
            if _label_match_ratio(label, str(other.get("text") or "")) >= 0.8:
                doomed.add(str(other.get("id") or ""))
    if doomed:
        elements[:] = [
            element
            for element in elements
            if str(element.get("id") or "") not in doomed
        ]
    return rotated


def _settle_pictures_and_controls(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> tuple[int, int]:
    """A + B + C, each with its own precondition.

    The three used to share one switch, which is why two of them had to be
    parked behind a flag: "complete any crop that touches its own edges" is true
    of a great many ordinary icons, and AtomGit paid for it.  Split apart, each
    rule only fires where the picture itself proves it should.
    """
    grown = dropped_texts = 0
    if _PICTURE_GROW_ENABLED:
        grown, dropped_texts = _complete_stamp_crops(elements, image_path, width, height)
    trimmed = 0
    if _PICTURE_TRIM_ENABLED:
        trimmed = _trim_pictures_under_text(elements, image_path, width, height)
    dropped_controls = _drop_impostor_controls(elements, ocr_observations)
    return grown + trimmed, dropped_controls + dropped_texts


def _page_fill(elements: Sequence[Mapping[str, Any]], background: str) -> str:
    """The colour the page actually is, which is not always the declared one.

    The plan declares a canvas colour and `_recover_page_fill` may then paint
    bands over it; a pass that compares a card against the *declared* background
    concludes the card is the page and skips it.  marketplace declares #1a1917
    and paints #100f0d, and the model cards are #1a1917 — the declared value
    would have made every card "the page".
    """
    for element in elements:
        if str(element.get("role") or "") == "page-ground":
            fill = _solid_fill(element)
            if fill:
                return fill
    return background


def _decorate_locked_frames(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    background: str,
) -> dict[str, int]:
    """视觉装饰层：帧结构锁定之后才落笔，只画，不成帧。

    两件事都在这里做，因为它们是同一类东西——原图上有、方案里没有的**笔画**：

    * 卡片的底板与 1px 低对比度轮廓（`_snap_containers_to_fill`）；
    * 标签外围那一圈闭合的细线（`_recover_chip_outlines`）。

    之前它们在 `attach_layout_frames` 之前跑，新增的 panel 会被当成容器参与布局
    推断：AtomGit 从 13 帧涨到 17 帧、review 3→2、wecom 6→4。挪到
    `_keep_renderable_frames` 之后，帧的成员名单与数量已经写死，这里加多少笔都
    不会再改一次结构。
    """
    report = {"cardPanels": 0, "chipOutlines": 0}
    if _SNAP_FILL_ENABLED:
        report["cardPanels"] = _snap_containers_to_fill(
            elements, image_path, width, height, background
        )
    if _CHIP_OUTLINE_ENABLED:
        report["chipOutlines"] = _recover_chip_outlines(
            elements, image_path, width, height
        )
    return report


def _is_main_card(
    element: Mapping[str, Any],
    elements: Sequence[Mapping[str, Any]],
    canvas_width: int,
) -> bool:
    """Whether this box is one cell of the page skeleton, not a sub-block.

    macOS-style pages are built from a handful of large surfaces; inside each of
    them live dozens of boxes of the same colour.  Snapping a sub-block produces
    a second paint layer over its own content, which is how AtomGit lost four
    frames when this pass ran before the frame lock.  A cell of the skeleton is
    wide, holds several lines of text, and is not itself the page.
    """
    try:
        x, y = float(element.get("x") or 0), float(element.get("y") or 0)
        w, h = float(element.get("width") or 0), float(element.get("height") or 0)
    except (TypeError, ValueError):
        return False
    if w < max(200.0, canvas_width * CARD_MIN_WIDTH_SHARE) or h < CARD_MIN_HEIGHT:
        return False
    texts = 0
    for other in elements:
        if other is element or other.get("type") != "text":
            continue
        if not str(other.get("text") or "").strip():
            continue
        ox, oy = float(other.get("x") or 0), float(other.get("y") or 0)
        ow, oh = float(other.get("width") or 0), float(other.get("height") or 0)
        if ox >= x - 2 and oy >= y - 2 and ox + ow <= x + w + 2 and oy + oh <= y + h + 2:
            texts += 1
    return texts >= CARD_MIN_TEXT_MEMBERS


def _snap_containers_to_fill(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    background: str,
) -> int:
    """Take a panel's box from the paint it owns, not from the plan's guess.

    marketplace's model cards are measured 1243x534 at (96,588) while the picture
    paints 1150x640 at (96,585): the boxes are a hundred pixels short at the
    bottom and ninety too wide on the right, so the two cards of a column overlap
    by 61px and Figma draws them as one slab with no gap.  Colour continuity
    cannot settle it — both cards are the same #1a1917 — so the box is read from
    the picture as the connected region of the card's own fill.

    Only the page's larger chrome is treated this way.  A chip sitting on a card
    of the same colour would flood-fill the whole card.
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    image = image[:height, :width]
    effective = _page_fill(elements, background)
    page = np.asarray(_hex_rgb(effective), dtype=np.int16) if effective else None

    snapped = 0
    for element in elements:
        if element.get("type") != "container":
            continue
        if str(element.get("role") or "") not in (
            "card",
            "panel",
            "header",
            "sidebar",
            "main-content",
        ):
            continue
        fill = _solid_fill(element)
        if not fill:
            continue
        colour = np.asarray(_hex_rgb(fill), dtype=np.int16)
        if page is not None and int(np.abs(colour - page).max()) < SOFT_PANEL_MIN_DELTA:
            continue
        try:
            x, y, w, h = (int(element[key]) for key in ("x", "y", "width", "height"))
        except (KeyError, TypeError, ValueError):
            continue
        if w < 200 or h < 120:
            continue
        # 只处理主卡片级容器。AtomGit 内部那些 60~200px 的细碎子块一旦被吸附，
        # 就会多出一层 paint 并把内容盖住；判据看的是"这张盒子是不是页面骨架的
        # 一格"，与具体站点无关。
        if not _is_main_card(element, elements, width):
            continue
        # The tolerance has to be a fraction of the gap to the page, or the page
        # joins the mask: marketplace's card is #1a1917 on #100f0d, ten channels
        # apart, and the generic twelve-channel tolerance floods the whole canvas
        # into one component whose bbox is the canvas.
        tolerance = CONTAINER_GROW_TOLERANCE
        if page is not None:
            gap = int(np.abs(colour - page).max())
            if gap < SNAP_MIN_PAGE_GAP:
                # A card two channels off its page cannot be separated from it by
                # colour: AtomGit's white-on-white cards flood the whole canvas.
                continue
            tolerance = max(3, min(CONTAINER_GROW_TOLERANCE, gap // 3))
        mask = (np.abs(image - colour).max(axis=2) <= tolerance).astype(np.uint8)
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        if count <= 1:
            continue
        # Probe the middle of the top edge, not the corner: a rounded corner is
        # page colour, and the first attempt read label 0 there and gave up on
        # every real card.  The candidate also has to be *this* box's paint —
        # two cards side by side share a fill colour, so a probe that lands on
        # the neighbour would snap the wrong way.
        probe = None
        for px, py in (
            (x + w // 2, y + 6),
            (x + w // 2, y + h // 2),
            (x + 6, y + h // 2),
            (x + w - 6, y + h // 2),
        ):
            if not (0 <= px < width and 0 <= py < height):
                continue
            label = int(labels[py, px])
            if label <= 0:
                continue
            bx, by, bw, bh, _area = (int(value) for value in stats[label])
            overlap = _overlap_share((x, y, w, h), (bx, by, bw, bh))
            if overlap >= 0.5:
                probe = label
                break
        if probe is None:
            continue
        bx, by, bw, bh, _area = (int(value) for value in stats[probe])
        # A component that swallows the page is not this card.
        if bw * bh > w * h * 4 or bw < 40 or bh < 30:
            continue
        if (bx, by, bw, bh) == (x, y, w, h):
            continue
        # The component has to be *this box's* paint, not a slice of it: a white
        # card split by a badge yields a same-colour half, and snapping to that
        # half moved AtomGit's card by 260px.  A box measured short still covers
        # its own paint; one measured over a neighbour covers a piece.
        covered = _overlap_share((x, y, w, h), (bx, by, bw, bh))
        if covered < SNAP_MIN_COVER:
            continue
        # A box that is off by a few pixels is a measurement, not a mistake:
        # only a real gap (a card measured into its neighbour) is worth a
        # second paint layer.  AtomGit's sub-cards move by 2-4px and three of
        # them turned into frames when this had no floor.
        shift = max(
            abs(bx - x), abs(by - y),
            abs((bx + bw) - (x + w)), abs((by + bh) - (y + h)),
        )
        from src.app.services.structure.fidelity.pixel_probe import (
            sample_container_decoration,
        )

        if shift < SNAP_MIN_CHANGE:
            # 盒子本身没量错，缺的只是那一圈 1px 轮廓：直接补样式，不再多画一层
            # 同色底板（多一层会把卡片里的内容压住，也会把 a11y 树弄脏）。
            style = element.setdefault("style", {})
            if not int(style.get("borderWidth") or 0):
                decoration = sample_container_decoration(
                    image_path, (x, y, w, h), str(fill)
                )
                if decoration.get("borderColor"):
                    style.update(decoration)
                    snapped += 1
            continue

        decoration = sample_container_decoration(image_path, (bx, by, bw, bh), str(fill))
        # Move the paint, not the structure.  Rewriting the container's box
        # changes which elements it owns, and the frame pass then fails its
        # layout inference on the survivors — both model cards lost their frames
        # that way.  The container keeps its measured box (same members, same
        # layout) and paints nothing; a plain panel paints the box the picture
        # actually has, in front of it in paint order.
        panel: dict[str, Any] = {
            "id": f"paint:{element.get('id') or len(elements)}",
            "type": "container",
            "role": "panel",
            "x": bx,
            "y": by,
            "width": bw,
            "height": bh,
            "text": "",
            "style": {"fillColor": fill, **decoration},
            "name": f"{str(element.get('role') or 'panel')} paint",
            # 这是"补画在帧下面的一层漆"，不是帧的成员，也不是外人。帧准入
            # 检查要放它过去，否则每补一层漆就有一个帧被拒（wecom 6→4）。
            "paintBackdrop": True,
            "contentRef": f"paint:{element.get('id') or len(elements)}",
            "edgeEvidence": {
                "method": "fill-flood",
                "box": [bx, by, bw, bh],
                "was": [x, y, w, h],
            },
        }
        index = elements.index(element)
        elements.insert(index, panel)
        # 容器自己不再画那块错误的底色：真盒已经由 panel 画在它下面，容器再涂
        # 一次就会把 panel 盖掉，并把多出来的 61px 铺到邻卡上（两卡粘成一块）。
        # 置为透明而不是页色：页色会把下面那张 panel 一起糊掉。
        style = element.setdefault("style", {})
        style["fillColor"] = "transparent"
        element["transparent"] = True
        for key in ("borderColor", "borderWidth", "borderRadius"):
            style.pop(key, None)
        snapped += 1
    return snapped


#: A solid coloured bar: thin, wide, saturated, and filled edge to edge.  A
#: rule is unsaturated, a border is thinner, a highlighted row is taller.
BAR_MIN_HEIGHT = 6
BAR_MAX_HEIGHT = 22
BAR_MIN_WIDTH = 100
BAR_MIN_ASPECT = 6.0
#: Saturation on the 0-255 scale.  A dark slate panel measures 83, a blue bar
#: around 200 — the floor has to sit between the two or every sidebar edge
#: becomes a "bar".
BAR_MIN_SATURATION = 110
BAR_MIN_VALUE = 40
BAR_FILL_RATIO = 0.7
#: Overlap with an element the plan already carries, above which the bar is
#: that element rather than a missing one.
BAR_EXISTING_IOU = 0.35
BAR_MAX_REGIONS = 8
#: A control has to be at least this far from its own words before the box is
#: treated as the error rather than a repeat of a label that is simply nearby.
CONTROL_REANCHOR_MIN_SHIFT = 80
#: How far a cell may sit from the OCR line it is matched to.  Its own words
#: are read within a couple of row heights; a line several rows away is a
#: different row's label that happens to read the same.
ROW_ATTACH_MAX = 160


def _table_roots(
    elements: list[dict[str, Any]],
) -> tuple[list[int | None], list[tuple[int, int, int, int] | None]]:
    """Owner chain plus, for each element, the table that contains it."""
    rects = [
        _layout_rect(element) if str(element.get("type")) in _LAYOUT_MEMBER_TYPES else None
        for element in elements
    ]
    containers = {
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) in ("container", "table")
    }
    owners = [
        _owner_index(rects, index, parent_candidates=containers) if rects[index] else None
        for index in range(len(elements))
    ]
    roots: list[int | None] = []
    for index in range(len(elements)):
        current = owners[index]
        seen: set[int] = set()
        found = None
        while current is not None and current not in seen:
            element = elements[current]
            if str(element.get("type")) == "table" or str(element.get("id") or "").startswith(
                "table-node:"
            ):
                found = current
                break
            seen.add(current)
            current = owners[current] if current < len(owners) else None
        roots.append(found)
    return roots, rects


def _repartition_table_rows(
    elements: list[dict[str, Any]],
    observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Rebuild one table row's columns from where its words actually are.

    A detected grid can put a row's columns at the extremes — the inventory
    header came back as 383 / 408 / 435 / 2492 / 2519 while the words are at
    626 / 844 / 1064 / 1274 / 1548 — leaving five labels in 25px columns and a
    pair swapped end for end.  Per-cell nudging cannot fix that: widening one
    cell pushes it into its neighbour and the renderer refuses the whole table
    (measured: inventory2 lost two frames).

    So the row is rebuilt as a whole.  Each cell takes its column from the
    midpoint between its own words and the next cell's words, the first column
    starts at the row's left edge and the last ends at its right edge.  The
    result is contiguous by construction, so no cell can overlap another.

    Only OCR whose centre lies inside the table is considered.  Without that
    filter a sidebar label that happens to share a word with a cell would drag
    a column out of the table entirely.
    """
    if not observations:
        return 0
    from src.app.services.structure.fidelity.contracts import (
        normalize_match_text,
        owner_text_similarity,
    )

    # Headers only.  A data row's columns must agree with the header's, and
    # re-slicing one independently produced columns that no longer lined up
    # with anything — on inventory2 it cost two frames.  The header is the row
    # that gets to define them.
    cells = [
        index
        for index, element in enumerate(elements)
        if str(element.get("contentRef") or element.get("id") or "").startswith(
            "table-header:"
        )
        and element.get("text")
    ]
    if len(cells) < ROW_REPARTITION_MIN_MATCHES:
        return 0
    roots, rects = _table_roots(elements)

    lines: list[tuple[str, tuple[int, int, int, int]]] = []
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        text = normalize_match_text(observation.get("text"))
        box = observation.get("bbox")
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            values = tuple(int(round(float(value))) for value in box)
        except (TypeError, ValueError):
            continue
        if values[2] <= 0 or values[3] <= 0:
            continue
        lines.append((text, values))  # type: ignore[arg-type]

    # Group by where the words are, not by where the cells currently sit.  A
    # half-corrected row has some cells on the real baseline and others still
    # on the grid's, and grouping by the cell would split one row in two.
    #
    # The table is taken from the *words*, not from the cell: a cell measured
    # below the table's own rectangle has no table in its owner chain at all,
    # and that is exactly the label that stays adrift (inventory2's "失效日期",
    # 112px under its row).  Its OCR line is inside the table, so the line knows
    # where the cell belongs even though the cell does not.
    tables = [
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "table"
        or str(element.get("id") or "").startswith("table-node:")
    ]

    def table_at(line_box: tuple[int, int, int, int]) -> int | None:
        centre_x = line_box[0] + line_box[2] / 2
        centre_y = line_box[1] + line_box[3] / 2
        best: tuple[int, int] | None = None
        for table in tables:
            box = rects[table]
            if box is None:
                continue
            if not (
                box[0] <= centre_x <= box[0] + box[2]
                and box[1] <= centre_y <= box[1] + box[3]
            ):
                continue
            area = box[2] * box[3]
            if best is None or area < best[0]:
                best = (area, table)
        return best[1] if best else None

    bands: dict[tuple[int, int], list[tuple[int, tuple[int, int, int, int]]]] = {}
    for index in cells:
        box = rects[index]
        if box is None:
            continue
        text = normalize_match_text(elements[index].get("text"))
        if not text:
            continue
        best = None
        for line_text, line_box in lines:
            if line_text != text and owner_text_similarity(line_text, text) < 0.85:
                continue
            if abs((line_box[1] + line_box[3] / 2) - (box[1] + box[3] / 2)) > ROW_ATTACH_MAX:
                continue
            owner = table_at(line_box)
            if owner is None:
                # Nothing in the picture claims these words: fall back to the
                # cell's own table, and only if it really contains them.
                owner = roots[index]
                table_box = rects[owner] if owner is not None else None
                centre_x = line_box[0] + line_box[2] / 2
                centre_y = line_box[1] + line_box[3] / 2
                if table_box is None or not (
                    table_box[0] <= centre_x <= table_box[0] + table_box[2]
                    and table_box[1] <= centre_y <= table_box[1] + table_box[3]
                ):
                    continue
            # Nearest line on both axes, weighted towards y: two tables can
            # carry the same header words at the same x, and only the row they
            # sit on tells them apart.
            score = abs(
                (line_box[1] + line_box[3] / 2) - (box[1] + box[3] / 2)
            ) + 0.25 * abs((line_box[0] + line_box[2] / 2) - (box[0] + box[2] / 2))
            if best is None or score < best[0]:
                best = (score, line_box, owner)
        if best is None:
            continue
        bands.setdefault((best[2], int(round(best[1][1] / ROW_BAND))), []).append(
            (index, best[1])
        )

    rebuilt = 0
    column_plans: dict[int, list[int]] = {}
    for (root, _band), group in bands.items():
        if len(group) < ROW_REPARTITION_MIN_MATCHES:
            continue
        table_box = rects[root]
        if table_box is None:
            continue
        members = [index for index, _line in group]
        # The words decide whether these cells are one row.  Where the *cells*
        # were measured is the thing being repaired, so a cell sitting a
        # hundred pixels below its own words is an outlier to pull back, not a
        # reason to leave the whole row mis-columned — that is how the
        # inventory2 header kept five squeezed columns and one label adrift.
        line_tops = [line[1] for _index, line in group]
        if max(line_tops) - min(line_tops) > ROW_SPREAD_MAX:
            continue
        matches = group
        shift = max(
            abs((rects[index][0] + rects[index][2] / 2) - (line[0] + line[2] / 2))
            for index, line in matches
        )
        vertical = max(abs(rects[index][1] - line[1]) for index, line in matches)
        if shift <= ROW_REPARTITION_MIN_SHIFT and vertical <= ROW_REPARTITION_MIN_SHIFT:
            continue

        matches.sort(key=lambda pair: pair[1][0])
        cell_tops = sorted(rects[index][1] for index in members)
        top = cell_tops[len(cell_tops) // 2]
        inliers = [
            index for index in members if abs(rects[index][1] - top) <= ROW_SPREAD_MAX
        ]
        if not inliers:
            continue
        bottom = max(rects[index][1] + rects[index][3] for index in inliers)

        left = min(rects[index][0] for index in members)
        right = max(rects[index][0] + rects[index][2] for index in members)
        left = max(left, table_box[0])
        right = min(right, table_box[0] + table_box[2])
        if right - left < ROW_REPARTITION_MIN_WIDTH * len(matches):
            continue
        # Midpoints between neighbouring words, walked left to right and forced
        # to stay at least one readable column apart.  The row is then a
        # partition by construction: `cell[i].right == cell[i+1].left`, nothing
        # overlaps, and nothing leaves the table.
        boundaries = [left]
        for position in range(len(matches) - 1):
            first = matches[position][1]
            second = matches[position + 1][1]
            boundary = (first[0] + first[2] + second[0]) // 2
            boundaries.append(max(boundary, boundaries[-1] + ROW_REPARTITION_MIN_WIDTH))
        boundaries.append(right)
        if boundaries[-1] < boundaries[-2] + ROW_REPARTITION_MIN_WIDTH:
            continue

        for position, (index, _line) in enumerate(matches):
            element = elements[index]
            element["x"] = boundaries[position]
            element["width"] = max(1, boundaries[position + 1] - boundaries[position])
            element["y"] = top
            element["height"] = max(18, bottom - top)
            style = element.get("style")
            if isinstance(style, dict):
                style["textAlign"] = "center"
            rebuilt += 1
        column_plans[root] = boundaries

    rebuilt += _apply_column_plans(elements, rects, roots, lines, column_plans)
    return rebuilt


def _apply_column_plans(
    elements: list[dict[str, Any]],
    rects: Sequence[tuple[int, int, int, int] | None],
    roots: Sequence[int | None],
    lines: Sequence[tuple[str, tuple[int, int, int, int]]],
    column_plans: Mapping[int, list[int]],
) -> int:
    """Lay a table's data rows out on the columns its header just defined.

    Repairing the header alone leaves the body where the grid put it: in the
    inventory2 first table the five values stayed in 20px boxes hard against
    the table's edges and painted as a smudge under 生产日期/失效日期.  The
    header is the row that knows the columns; the body only has to keep its own
    left-to-right order.

    Order is all a body row can be trusted for.  OCR says where the sequence
    *starts* — the cells it reads land on known columns — and the offset those
    agree on carries the rest, including values no OCR line ever saw.
    """
    if not column_plans:
        return 0
    from src.app.services.structure.fidelity.contracts import (
        normalize_match_text,
        owner_text_similarity,
    )

    grouped: dict[int, list[int]] = {}
    for index, element in enumerate(elements):
        if not str(element.get("contentRef") or "").startswith("table-cell:"):
            continue
        if not str(element.get("text") or "").strip():
            continue
        root = roots[index] if index < len(roots) else None
        box = rects[index]
        if root is None or root not in column_plans or box is None:
            continue
        grouped.setdefault(root, []).append(index)

    laid_out = 0
    for root, members in grouped.items():
        boundaries = column_plans[root]
        columns = len(boundaries) - 1
        if columns < 2:
            continue
        members.sort(key=lambda index: rects[index][1])  # type: ignore[index]
        rows: list[list[int]] = []
        for index in members:
            top = rects[index][1]  # type: ignore[index]
            if rows and abs(top - rects[rows[-1][0]][1]) <= ROW_SPREAD_MAX:  # type: ignore[index]
                rows[-1].append(index)
            else:
                rows.append([index])
        for row in rows:
            if len(row) < 2:
                continue
            ordered = sorted(row, key=lambda index: rects[index][0])  # type: ignore[index]
            anchors: list[int] = []
            for rank, index in enumerate(ordered):
                text = normalize_match_text(elements[index].get("text"))
                box = rects[index]
                if not text or box is None:
                    continue
                centre = box[0] + box[2] / 2
                row_centre = box[1] + box[3] / 2
                best: tuple[float, int] | None = None
                for line_text, line_box in lines:
                    if line_text != text and owner_text_similarity(line_text, text) < 0.85:
                        continue
                    if abs((line_box[1] + line_box[3] / 2) - row_centre) > ROW_ATTACH_MAX:
                        continue
                    column = _column_of(line_box[0] + line_box[2] / 2, boundaries)
                    if column is None:
                        continue
                    distance = abs((line_box[0] + line_box[2] / 2) - centre)
                    if best is None or distance < best[0]:
                        best = (distance, column)
                if best is not None:
                    anchors.append(best[1] - rank)
            if len(anchors) < 2:
                continue
            anchors.sort()
            offset = anchors[len(anchors) // 2]
            # The sequence has to agree with the words, or the row is not a
            # row — a merged cell or a second line would land on nonsense.
            if sum(1 for value in anchors if abs(value - offset) <= 1) < len(anchors) - 1:
                continue
            top = min(rects[index][1] for index in row)  # type: ignore[index]
            bottom = max(rects[index][1] + rects[index][3] for index in row)  # type: ignore[index]
            width_rows: list[tuple[int, int, int, int]] = []
            for rank, index in enumerate(ordered):
                column = rank + offset
                if not 0 <= column < columns:
                    continue
                width_rows.append(
                    (
                        index,
                        boundaries[column],
                        max(1, boundaries[column + 1] - boundaries[column]),
                        column,
                    )
                )
            # Overlapping assignments mean the offset is wrong for this row.
            seen: set[int] = set()
            if any(column in seen or seen.add(column) for _i, _x, _w, column in width_rows):
                continue
            for index, x, width, _column in width_rows:
                element = elements[index]
                element["x"] = x
                element["width"] = width
                element["y"] = top
                element["height"] = max(18, bottom - top)
                style = element.get("style")
                if isinstance(style, dict):
                    style["textAlign"] = "center"
                laid_out += 1
    return laid_out


def _column_of(centre: float, boundaries: Sequence[int]) -> int | None:
    for column in range(len(boundaries) - 1):
        if boundaries[column] <= centre <= boundaries[column + 1]:
            return column
    return None


def _fit_table_text(
    elements: list[dict[str, Any]],
    observations: Sequence[Mapping[str, Any]] | None,
    pixels,
) -> int:
    """Size table text by its ink, not by the cell it sits in.

    A cell box is a grid interval.  When the grid is coarse — a narrow column
    that spans two rows, a header band measured 73px tall — deriving the font
    from the box height produces 40-55px type in a 20px column, which then
    wraps one glyph per line.  Ink is the only honest measure: the OCR line
    when the same words were read, otherwise the foreground mask inside the
    cell itself.

    Geometry is left alone on purpose: widening a cell to its ink pushes it
    over a neighbour, and the renderer then refuses the whole table for
    covering a stranger — measured on inventory2, two frames went that way.
    A column narrower than its own text is a grid problem, and shrinking the
    type is the part that can be fixed without moving anything.
    """
    cells = [
        element
        for element in elements
        if str(element.get("contentRef") or element.get("id") or "").startswith(
            TABLE_TEXT_PREFIXES
        )
        and element.get("text")
    ]
    if not cells:
        return 0
    from src.app.services.structure.fidelity.contracts import normalize_match_text

    lines: list[tuple[str, tuple[int, int, int, int]]] = []
    for observation in observations or []:
        if not isinstance(observation, Mapping):
            continue
        text = normalize_match_text(observation.get("text"))
        box = observation.get("bbox")
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            values = tuple(int(round(float(value))) for value in box)
        except (TypeError, ValueError):
            continue
        if values[2] <= 0 or values[3] <= 0:
            continue
        lines.append((text, values))  # type: ignore[arg-type]

    resized = 0
    for element in cells:
        box = _layout_rect(element)
        if box is None:
            continue
        text = normalize_match_text(element.get("text"))
        ink = None
        for line_text, line_box in lines:
            if line_text == text:
                ink = line_box
                break
        if ink is None:
            ink = _measure_ink(pixels, box)
        if ink is None:
            continue
        font = max(TABLE_FONT_MIN, min(TABLE_FONT_MAX, round(ink[3] * INK_TO_FONT * 4) / 4))
        style = element.get("style")
        if not isinstance(style, dict):
            continue
        style["fontSize"] = font
        style["lineHeight"] = max(
            int(round(font * 1.35)), int(style.get("lineHeight") or 0)
        )
        resized += 1

    # A row of cells shares one type size.  Anything far from the row median is
    # still a bad box measurement, and clamping to the median is what keeps a
    # single narrow cell from shouting.
    rows: dict[int, list[dict[str, Any]]] = {}
    for element in cells:
        style = element.get("style")
        if not isinstance(style, dict) or not style.get("fontSize"):
            continue
        rows.setdefault(int(round(element["y"] / 10.0)), []).append(element)
    for row in rows.values():
        if len(row) < 2:
            continue
        sizes = sorted(float(element["style"]["fontSize"]) for element in row)
        median = sizes[len(sizes) // 2]
        for element in row:
            size = float(element["style"]["fontSize"])
            if size > median * 1.35 or size < median * 0.7:
                element["style"]["fontSize"] = median
    return resized


TABLE_TEXT_PREFIXES = ("table-header:", "table-cell:")
#: Below this the grid is roughly right and moving cells only risks tearing a
#: table that already frames; above it the grid origin is plainly wrong.  The
#: inventory block is out by 272px, the tables that already work by 20-90px.
TABLE_ANCHOR_MIN_SHIFT = 100
TABLE_ANCHOR_MAX_SHIFT = 300
TABLE_ANCHOR_MIN_X_OVERLAP = 0.3


def _anchor_table_text(
    elements: list[dict[str, Any]],
    observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Move synthesized table text onto the OCR line that reads the same words.

    Table cells come out of a detected grid, so their box is the cell rather
    than the ink.  When the grid's origin is wrong, the words print one or two
    hundred pixels away from where the picture has them — in the inventory
    screenshot straight over the card rows above.  OCR already read those words
    at their real position and the grid has no authority over it.

    Only a displacement several cells agree on counts.  One cell that matches
    far away is usually the same label in another table, and following it tears
    a correct table apart; a shared offset is the signature of a bad grid
    origin, which is what this repairs.
    """
    if not observations:
        return 0
    from src.app.services.structure.fidelity.contracts import (
        normalize_match_text,
        owner_text_similarity,
    )

    lines: list[tuple[str, tuple[int, int, int, int]]] = []
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        text = str(observation.get("text") or "").strip()
        box = observation.get("bbox")
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            left, top, width, height = (int(round(float(value))) for value in box)
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        lines.append((normalize_match_text(text), (left, top, width, height)))
    if not lines:
        return 0

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
        _owner_index(rects, index, parent_candidates=containers) if rects[index] else None
        for index in range(len(elements))
    ]
    roots, table_rects = _table_roots(elements)

    matches: list[tuple[dict[str, Any], tuple[int, int, int, int], int]] = []
    for position, element in enumerate(elements):
        reference = str(element.get("contentRef") or element.get("id") or "")
        if not reference.startswith(TABLE_TEXT_PREFIXES):
            continue
        text = normalize_match_text(element.get("text"))
        box = _layout_rect(element)
        if not text or box is None:
            continue
        # A cell may only follow words read inside its own table.  A sidebar
        # label two panels away can share a cell's wording ("盘点单"), and
        # following it drags the cell — and with it the column — out of the
        # table.
        root = roots[position] if position < len(roots) else None
        table_box = table_rects[root] if root is not None else None
        if table_box is None:
            # Not under a declared table node: its owning container is the
            # table as far as this pass is concerned.
            owner = owners[position]
            table_box = rects[owner] if owner is not None else None
        if table_box is None:
            continue
        best: tuple[float, tuple[int, int, int, int]] | None = None
        for line_text, line_box in lines:
            centre_x = line_box[0] + line_box[2] / 2
            centre_y = line_box[1] + line_box[3] / 2
            if not (
                table_box[0] <= centre_x <= table_box[0] + table_box[2]
                and table_box[1] <= centre_y <= table_box[1] + table_box[3]
            ):
                continue
            if line_text != text and owner_text_similarity(line_text, text) < 0.9:
                continue
            # Both axes, weighted towards y: a wrong grid origin shifts a whole
            # block at once, so requiring x overlap would hide the very cells
            # that need moving.
            distance = abs(
                (box[1] + box[3] / 2) - (line_box[1] + line_box[3] / 2)
            ) + 0.25 * abs((box[0] + box[2] / 2) - (line_box[0] + line_box[2] / 2))
            if best is None or distance < best[0]:
                best = (distance, line_box)
        if best is None:
            continue
        line_box = best[1]
        vertical = line_box[1] - box[1]
        horizontal = abs((box[0] + box[2] / 2) - (line_box[0] + line_box[2] / 2))
        if max(abs(vertical), horizontal) > TABLE_ANCHOR_MAX_SHIFT:
            continue
        if abs(vertical) <= TABLE_ANCHOR_MIN_SHIFT and horizontal <= TABLE_ANCHOR_MIN_SHIFT:
            continue
        owner = owners[position]
        if owner is None or rects[owner] is None:
            continue
        # The cell may only move inside the box that owns it.  A target outside
        # means the container is wrong as well, and moving the text alone would
        # leave a member outside its frame — the renderer rejects the whole
        # frame for that.
        if not _rect_contains(rects[owner], line_box, tolerance=8):
            continue
        matches.append((element, line_box, vertical))

    if not matches:
        return 0
    buckets: dict[int, list[tuple[dict[str, Any], tuple[int, int, int, int]]]] = {}
    for element, line_box, vertical in matches:
        buckets.setdefault(int(round(vertical / 6.0)), []).append((element, line_box))
    dominant = max(buckets.values(), key=len)
    if len(dominant) < 2:
        return 0

    moved = 0
    for element, (left, top, width, height) in dominant:
        element["x"] = left
        element["y"] = top
        element["width"] = max(1, width)
        element["height"] = max(18, height)
        style = element.get("style")
        if isinstance(style, dict):
            style["textAlign"] = "start"
        moved += 1
    return moved

def _drop_page_coloured_shells(
    elements: list[dict[str, Any]],
    background: str,
) -> int:
    """Remove containers that paint the page colour and own nothing.

    A dialog screenshot is dimmed end to end, so the page background itself is
    the scrim colour and several boxes measure out as the same flat grey.  One
    of them lands on top of a real card and blocks its frame, yet it adds not a
    single pixel: it paints exactly what is already there.

    Only shell containers are removed — ones with no members of their own and
    no picture or text.  Anything that owns content still has a job.
    """
    target = str(background or "").strip().lower()
    if not target.startswith("#"):
        return 0
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
        _owner_index(rects, index, parent_candidates=containers) if rects[index] else None
        for index in range(len(elements))
    ]
    owning = {owner for owner in owners if owner is not None}
    doomed = [
        index
        for index in containers
        if index not in owning
        and str(elements[index].get("role") or "") != "text-backdrop"
        and not elements[index].get("imageBase64")
        and not elements[index].get("text")
        and str((elements[index].get("style") or {}).get("fillColor") or "")
        .strip()
        .lower()
        == target
    ]
    if not doomed:
        return 0
    drop = set(doomed)
    elements[:] = [
        element for index, element in enumerate(elements) if index not in drop
    ]
    return len(doomed)


COINCIDENT_TEXT_COVERAGE = 0.65
COINCIDENT_TEXT_SIMILARITY = 0.55
#: Two labels on one line whose boxes overlap less than this vertically are
#: stacked, not duplicated.
DUPLICATE_LINE_Y_OVERLAP = 0.6
#: A shared prefix/suffix this long (after stripping spaces and punctuation) is
#: one label read twice, even when the middle was cut differently.
DUPLICATE_LINE_AFFIX = 6
#: OCR confuses O/0 and l/1, so a pair that differs only in those glyphs is
#: still the same label.  Measured as a whole-string ratio.
DUPLICATE_LINE_SIMILARITY = 0.85
#: Share of the shorter label one unbroken run of the longer has to cover
#: before the two count as one label read twice.
DUPLICATE_LINE_COVERAGE = 0.72
#: Two prints of one label that miss each other by a few pixels: row overlap
#: and wording are enough, and the gap between them is what separates a ghost
#: from two real labels that happen to read the same (a Star button per card).
DUPLICATE_GHOST_Y_OVERLAP = 0.5
DUPLICATE_GHOST_SIMILARITY = 0.80
DUPLICATE_GHOST_REACH = 24
#: ... and their widths have to agree.  Two labels 20px apart with one three
#: times the width of the other are a title and its subtitle, not a ghost.
DUPLICATE_GHOST_WIDTH_RATIO = 0.4
#: A paragraph's wrapped remainder, modelled a second time: a suffix of at least
#: this many characters, starting a line below its host, inside the same span.
PARAGRAPH_TAIL_MIN_CHARS = 6
PARAGRAPH_TAIL_LENGTH_MARGIN = 8
PARAGRAPH_TAIL_MIN_DROP = 4
PARAGRAPH_TAIL_REACH = 12
PARAGRAPH_TAIL_HORIZONTAL_SHARE = 0.5
#: 文本落在补丁里的面积超过这个比例，它就是在给同一句话做第二次印刷。
PATCH_TEXT_COVER = 0.55
#: 小框被大框包含到这个比例，且用词对得上，就判为重影。
CONTAINED_TEXT_IOA = 0.55
CONTAINED_TEXT_SIMILARITY = 0.45
#: 小框被更大的文本框盖住这么多、且处在同一条基线带里，只可能是第二遍印刷。
NESTED_TEXT_SHARE = 0.6
NESTED_TEXT_LINE_TOLERANCE = 0.5
NESTED_TEXT_HEIGHT_RATIO = 2.5
#: OCR 观测与盒子的重叠达到这个比例，才算"这条线在说这个盒子"。
OCR_SUPPORT_OVERLAP = 0.3
#: 且这条线要复现节点自身这么多字符，才算它真的在说这句话。
OCR_SUPPORT_CHARS = 0.7
#: 文字压在与自己面积相当（不超过这个倍数）的图片上：那是芯片/图标，不是照片。
NESTED_IMAGE_AREA_RATIO = 3.0
#: 大号展示标题：字号下限，以及判定为展示字重所需的最小笔宽比。
DISPLAY_MIN_SIZE = 40.0
DISPLAY_STROKE_MIN = 0.075
#: Rebuilding a paragraph from its OCR lines: the seed has to sit on the node's
#: own first line, the chain grows downwards in the same column, and the joined
#: text has to agree with the model's wording this well before anything moves.
PARAGRAPH_REFLOW_MIN_CHARS = 20
PARAGRAPH_REFLOW_MAX_LINES = 6
PARAGRAPH_REFLOW_MIN_SIMILARITY = 0.85
PARAGRAPH_REFLOW_BAND_SHARE = 0.5
PARAGRAPH_REFLOW_MAX_GAP = 1.8
#: Channel distance under which text colour and surface are the same colour.
INK_MIN_CONTRAST = 30


def _text_cleanliness(element: Mapping[str, Any]) -> tuple[int, int]:
    """Prefer model wording over a raw OCR line, then the longer string."""
    return (
        0 if str(element.get("textBoxAuthority") or "") == "ocr-line" else 1,
        len(str(element.get("text") or "")),
    )


def _rendered_span(element: Mapping[str, Any]) -> tuple[int, int]:
    """Left edge and right edge a text will actually paint to.

    A synthesized cell can carry a 48px box for a forty-character line: the
    box is the measurement, the string is what lands on the canvas, and the
    renderer draws the whole line.  Comparing boxes alone therefore misses the
    double-printed rows, because the two boxes sit side by side while the two
    strings overlap by hundreds of pixels.
    """
    rect = _layout_rect(element)
    if rect is None:
        return (0, 0)
    left, _top, box_width, _box_height = rect
    text = str(element.get("text") or "")
    style = element.get("style") or {}
    try:
        font = float(style.get("fontSize") or 0.0)
    except (TypeError, ValueError):
        font = 0.0
    estimated = 0.0
    for char in text:
        estimated += font * (1.0 if ord(char) > 0x2E80 else 0.55)
    return (left, left + max(box_width, int(round(estimated))))


#: Glyphs OCR swaps for one another inside an identifier.  "WO5OS-OO5" and
#: "W0505-005" are the same rack, read twice by two engines; without folding,
#: one substituted letter looks like a different label and both get printed.
OCR_HOMOGLYPHS = str.maketrans(
    {
        "o": "0",
        "s": "5",
        "i": "1",
        "l": "1",
        "b": "8",
        "z": "2",
        "g": "6",
    }
)


def _fold_homoglyphs(text: str) -> str:
    """Collapse letter/digit pairs OCR cannot tell apart, for matching only."""
    return text.translate(OCR_HOMOGLYPHS)


def _ghost_gap(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> int:
    """Horizontal distance between two boxes, zero when they overlap."""
    return max(0, max(left[0], right[0]) - min(left[0] + left[2], right[0] + right[2]))


def _shared_affix(left: str, right: str) -> int:
    heads = 0
    for first, second in zip(left, right):
        if first != second:
            break
        heads += 1
    tails = 0
    for first, second in zip(reversed(left), reversed(right)):
        if first != second:
            break
        tails += 1
    return max(heads, tails)


def _label_match_ratio(left: str, right: str) -> float:
    """Share of the shorter string covered by one unbroken run of the longer.

    A prefix test is too brittle for OCR: "W0505" and "WO505" break it on the
    fourth character, and the rest of a twenty-character label matches exactly.
    The longest common run tolerates that single substituted glyph.
    """
    if not left or not right:
        return 0.0
    block = SequenceMatcher(
        None, left, right, autojunk=False
    ).find_longest_match(0, len(left), 0, len(right))
    return block.size / min(len(left), len(right))


def _ink_contrast(
    element: Mapping[str, Any],
    elements: Sequence[dict[str, Any]],
    background: str,
) -> int:
    """How far the text colour sits from the surface it is printed on.

    Two readings of one label can differ only in the colour each sampled, and
    one of them sampled the card instead of the ink: #fefffe words on a white
    row are there, and cannot be read.  The surface is the smallest container
    that holds the text; the page is the fallback.
    """
    style = element.get("style")
    if not isinstance(style, dict):
        return 0
    ink = _hex_rgb(str(style.get("textColor") or background))
    box = _layout_rect(element)
    if box is None:
        return 0
    surface = str(background or "")
    smallest = None
    for candidate in elements:
        if str(candidate.get("type")) != "container":
            continue
        if str(candidate.get("role") or "") == "text-backdrop":
            # A surface inferred from the pixels around a text cannot also
            # vouch for that text's colour — the two would agree by
            # construction, and a white reading on its own white row would
            # look readable because a nearby badge was sampled under it.
            continue
        fill = _opaque_fill(candidate)
        if not fill:
            continue
        other = _layout_rect(candidate)
        if other is None:
            continue
        # The whole text has to sit on the surface.  Testing the centre alone
        # let a badge under the middle of a long row label count as that
        # label's background, which made a near-white reading look readable.
        if not _rect_contains(other, box, tolerance=2):
            continue
        area = other[2] * other[3]
        if smallest is None or area < smallest[0]:
            smallest = (area, fill)
    if smallest is not None:
        surface = smallest[1]
    base = _hex_rgb(surface or background)
    return max(abs(one - two) for one, two in zip(ink, base))


def _preferred_copy(
    first: int,
    second: int,
    elements: Sequence[dict[str, Any]],
    background: str = "",
) -> int:
    """Which of two readings of one label survives.

    A readable reading beats an unreadable one: one of the pair may carry the
    colour of the surface it was measured against, which prints invisible.
    Otherwise the fuller string wins — a reading that swallowed the rest of the
    row still prints the words the shorter one has, while the shorter one drops
    them.  On equal wording the box that fits its own text better wins, because
    a 48px box around a 400px line is a measurement error and its x is not
    trustworthy.
    """
    one = str(elements[first].get("text") or "")
    two = str(elements[second].get("text") or "")
    first_contrast = _ink_contrast(elements[first], elements, background)
    second_contrast = _ink_contrast(elements[second], elements, background)
    if (first_contrast >= INK_MIN_CONTRAST) != (second_contrast >= INK_MIN_CONTRAST):
        return first if first_contrast >= INK_MIN_CONTRAST else second
    if len(one) != len(two):
        return first if len(one) > len(two) else second

    def fit(index: int, text: str) -> float:
        rect = _layout_rect(elements[index])
        if rect is None or not text:
            return 0.0
        left, right = _rendered_span(elements[index])
        span = max(1, right - left)
        return min(rect[2], span) / span

    return first if fit(first, one) >= fit(second, two) else second


def _drop_coincident_texts(
    elements: list[dict[str, Any]],
    background: str = "",
) -> int:
    """Remove a label that a later stage measured again over the same words.

    Table synthesis writes header cells straight from the detected grid, while
    OCR reads the same words as a short line.  They are produced by different
    stages, so the stage that merges text never sees the pair; the export then
    prints one string on top of the other.  Two text boxes covering the same
    area and agreeing on the wording are one label — the poorer copy goes.

    Coverage, not IoU: one box is usually a full-width cell and the other the
    ink-tight line inside it, which keeps IoU low while the smaller box is
    almost entirely covered.

    Two readings of one row can also land *side by side*: the label box was
    measured narrow, the renderer prints the whole line from it, and the line
    runs straight over its own twin.  Coverage never fires there — the boxes do
    not overlap.  So a pair on the same line whose normalised strings share a
    prefix, a suffix, or one contains the other, is compared on what it will
    paint rather than on what it was measured as.
    """
    from src.app.services.structure.fidelity.contracts import (
        normalize_owner_text,
        owner_text_similarity,
    )

    texts = [
        index
        for index, element in enumerate(elements)
        if element.get("type") == "text" and element.get("text")
    ]
    doomed: set[int] = set()
    for position, first in enumerate(texts):
        if first in doomed:
            continue
        first_badge = bool(elements[first].get("badgeLabel"))
        first_rect = _layout_rect(elements[first])
        if first_rect is None:
            continue
        for second in texts[position + 1 :]:
            if second in doomed:
                continue
            # A chip's own word and the row's reading of the same line are two
            # different objects and can live beside each other.  Two chip words
            # are not: one of them is a second print of the same label.
            if first_badge != bool(elements[second].get("badgeLabel")):
                continue
            second_rect = _layout_rect(elements[second])
            if second_rect is None:
                continue
            overlap_h = min(first_rect[1] + first_rect[3], second_rect[1] + second_rect[3]) - max(
                first_rect[1], second_rect[1]
            )
            if overlap_h <= 0:
                continue
            box_overlap_w = min(
                first_rect[0] + first_rect[2], second_rect[0] + second_rect[2]
            ) - max(first_rect[0], second_rect[0])
            first_left, first_right = _rendered_span(elements[first])
            second_left, second_right = _rendered_span(elements[second])
            overlap_w = min(first_right, second_right) - max(first_left, second_left)
            same_line = overlap_h / max(1, min(first_rect[3], second_rect[3]))
            if overlap_w <= 0:
                # Two prints of one label can miss each other by a few pixels:
                # the box was measured a little to the left and the copy a
                # little to the right, so nothing overlaps even though both
                # paint the same sentence.  Same row, same words, within
                # reading distance — one of them is a ghost.
                one_ghost = str(elements[first].get("text") or "")
                two_ghost = str(elements[second].get("text") or "")
                widths_agree = abs(first_rect[2] - second_rect[2]) <= max(
                    first_rect[2], second_rect[2]
                ) * DUPLICATE_GHOST_WIDTH_RATIO
                if (
                    same_line >= DUPLICATE_GHOST_Y_OVERLAP
                    and widths_agree
                    and owner_text_similarity(one_ghost, two_ghost)
                    >= DUPLICATE_GHOST_SIMILARITY
                    and _ghost_gap(first_rect, second_rect) <= DUPLICATE_GHOST_REACH
                ):
                    keep = _preferred_copy(first, second, elements, background)
                    if keep == first:
                        doomed.add(second)
                        continue
                    doomed.add(first)
                    break
                continue
            coverage = (box_overlap_w * overlap_h) / max(
                1, min(first_rect[2] * first_rect[3], second_rect[2] * second_rect[3])
            ) if box_overlap_w > 0 else 0.0
            # Same line, one string inside the other: one reading merged the
            # whole row while another reported a single field of it.  The long
            # one already prints every word, so the short copy is redundant —
            # no need for the coverage threshold, the y agreement carries it.
            if same_line >= DUPLICATE_LINE_Y_OVERLAP:
                one = str(elements[first].get("text") or "").strip()
                two = str(elements[second].get("text") or "").strip()
                key_one = _fold_homoglyphs(normalize_owner_text(one))
                key_two = _fold_homoglyphs(normalize_owner_text(two))
                if one and two and (
                    one in two or two in one or key_one in key_two or key_two in key_one
                ):
                    shorter = one if len(one) <= len(two) else two
                    # A number on its own is a value, not a shortened label:
                    # the "100" cell in a quantity column is inside the row's
                    # prose and still needs to print.  The same number twice on
                    # the same spot is a double print, and that is not a value.
                    if one == two or (len(shorter) >= 4 and not shorter.isdigit()):
                        keep = _preferred_copy(first, second, elements, background)
                        if keep == first:
                            doomed.add(second)
                            continue
                        doomed.add(first)
                        break
                if key_one and key_two and not (
                    key_one in key_two or key_two in key_one
                ):
                    shared = _shared_affix(key_one, key_two)
                    alike = owner_text_similarity(key_one, key_two)
                    covered = _label_match_ratio(key_one, key_two)
                    if (
                        shared >= DUPLICATE_LINE_AFFIX
                        or alike >= DUPLICATE_LINE_SIMILARITY
                        or covered >= DUPLICATE_LINE_COVERAGE
                    ) and min(len(key_one), len(key_two)) >= DUPLICATE_LINE_AFFIX:
                        keep = _preferred_copy(first, second, elements, background)
                        other = second if keep == first else first
                        doomed.add(other)
                        if keep == first:
                            continue
                        break
            if coverage < COINCIDENT_TEXT_COVERAGE:
                continue
            if (
                owner_text_similarity(
                    elements[first].get("text"), elements[second].get("text")
                )
                < COINCIDENT_TEXT_SIMILARITY
            ):
                continue
            if _text_cleanliness(elements[first]) >= _text_cleanliness(elements[second]):
                doomed.add(second)
            else:
                doomed.add(first)
                break
    if not doomed:
        return 0
    elements[:] = [
        element for index, element in enumerate(elements) if index not in doomed
    ]
    return len(doomed)


#: Names a vision model gives an icon, never words the page prints.  ``search``
#: and ``mail`` in a toolbar are the magnifier and the envelope; the screenshot
#: shows two glyphs, and a TEXT node made from the caption prints "search"
#: across the icon.  Support from OCR is what separates the two: if the words
#: are really on the page, some line reads them at that very spot.
ICON_DESCRIPTOR_WORDS = frozenset(
    {
        "search",
        "find",
        "mail",
        "envelope",
        "inbox",
        "menu",
        "hamburger",
        "kebab",
        "ellipsis",
        "close",
        "dismiss",
        "dropdown",
        "caret",
        "chevron",
        "arrow",
        "settings",
        "setting",
        "gear",
        "user",
        "avatar",
        "profile",
        "account",
        "filter",
        "funnel",
        "bell",
        "notification",
        "more",
        "plus",
        "minus",
        "add",
        "remove",
        "edit",
        "pencil",
        "delete",
        "trash",
        "refresh",
        "reload",
        "share",
        "download",
        "upload",
        "link",
        "home",
        "back",
        "forward",
        "expand",
        "collapse",
        "grid",
        "list",
        "calendar",
        "clock",
        "star",
        "heart",
        "bookmark",
        "cart",
        "help",
        "question",
        "spinner",
        "loading",
        "logo",
        "icon",
        "badge",
    }
)
#: An icon label is a caption on a glyph, so it lives in a glyph-sized box.
ICON_DESCRIPTOR_MAX_SIDE = 96
#: How far from the box OCR may read the same words and still count as proof
#: that they are printed on the page.
ICON_DESCRIPTOR_OCR_SLACK = 8
#: A gap this small is inside the glyph; the words start where the icon ends.
BADGE_ICON_GAP = 4
#: A badge is a chip: wide enough for a few words, never taller than a line.
BADGE_MAX_WIDTH = 260
BADGE_MAX_HEIGHT = 64
#: Share of a text or icon that a later-painted fill has to bury to count.
FILL_OCCLUSION_COVERAGE = 0.5
#: Colour distance under which a fill is "the page colour again".
PAGE_FILL_TOLERANCE = 10
#: A backdrop fragment is a panel-sized patch, not a stray chip.
PAGE_FRAGMENT_MIN_AREA = 40000


def _ocr_lines(
    observations: Sequence[Mapping[str, Any]] | None,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Normalised OCR text with its box, ready for matching."""
    from src.app.services.structure.fidelity.contracts import normalize_match_text

    lines: list[tuple[str, tuple[int, int, int, int]]] = []
    for observation in observations or ():
        if not isinstance(observation, Mapping):
            continue
        text = normalize_match_text(observation.get("text"))
        box = observation.get("bbox")
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            values = tuple(int(round(float(value))) for value in box)
        except (TypeError, ValueError):
            continue
        if values[2] <= 0 or values[3] <= 0:
            continue
        lines.append((text, values))  # type: ignore[arg-type]
    return lines


def _icon_descriptor(text: str) -> bool:
    """True when the whole string is a control/icon name, not prose."""
    words = [word for word in re.split(r"[^a-z]+", str(text or "").strip().lower()) if word]
    if not words or len(words) > 3:
        return False
    return all(word in ICON_DESCRIPTOR_WORDS for word in words)


def _has_ocr_support(
    text: str,
    box: tuple[int, int, int, int],
    lines: Sequence[tuple[str, tuple[int, int, int, int]]],
    *,
    slack: int = ICON_DESCRIPTOR_OCR_SLACK,
    threshold: float = 0.75,
) -> bool:
    from src.app.services.structure.fidelity.contracts import (
        normalize_match_text,
        owner_text_similarity,
    )

    key = normalize_match_text(text)
    if not key:
        return False
    for line_text, line_box in lines:
        if line_text != key and owner_text_similarity(line_text, key) < threshold:
            continue
        left = box[0] - slack
        top = box[1] - slack
        right = box[0] + box[2] + slack
        bottom = box[1] + box[3] + slack
        centre_x = line_box[0] + line_box[2] / 2
        centre_y = line_box[1] + line_box[3] / 2
        if left <= centre_x <= right and top <= centre_y <= bottom:
            return True
    return False


def _drop_icon_descriptor_labels(
    elements: list[dict[str, Any]],
    observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Strip captions the model invented for icons.

    A toolbar comes back as ``search``, ``mail``, ``menu``, ``dropdown``,
    ``close`` — five words that name five glyphs and appear nowhere in the
    screenshot.  Written as text they print on top of the glyphs and read as
    page content, which is worse than the icon alone.

    OCR decides.  When a line really reads those words at that spot (a "Star"
    button, an English "Search" label) the text stays; without that support the
    string is a semantic annotation and only the shape is kept.
    """
    if not elements:
        return 0
    lines = _ocr_lines(observations)
    doomed: set[int] = set()
    cleared = 0
    for index, element in enumerate(elements):
        kind = str(element.get("type") or "")
        if kind not in {"text", "button", "input"}:
            continue
        text = str(element.get("text") or "").strip()
        if not text or not text.isascii() or not _icon_descriptor(text):
            continue
        if str(element.get("contentRef") or element.get("id") or "").startswith(
            TABLE_TEXT_PREFIXES
        ):
            continue
        rect = _layout_rect(element)
        if rect is None or max(rect[2], rect[3]) > ICON_DESCRIPTOR_MAX_SIDE:
            continue
        if _has_ocr_support(text, rect, lines):
            continue
        if kind == "text":
            doomed.add(index)
        else:
            element["text"] = ""
            element.pop("controlValue", None)
        cleared += 1
    if doomed:
        elements[:] = [
            element for index, element in enumerate(elements) if index not in doomed
        ]
    return cleared


def _chip_ink(
    pixels,
    box: tuple[int, int, int, int],
    fill: str,
) -> tuple[str, float] | None:
    """Colour and height of the glyphs printed on a chip.

    The chip's fill is known, so the ink is whatever stands far from it.  The
    median of those pixels is the type colour, and their vertical extent gives
    the size the way the table pass measures it.
    """
    try:
        import numpy as np
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return None
    if pixels is None:
        return None
    frame_height, frame_width = pixels.shape[:2]
    x, y, width, height = box
    left, top = max(0, x), max(0, y)
    right = min(frame_width, x + width)
    bottom = min(frame_height, y + height)
    if right - left < 4 or bottom - top < 4:
        return None
    patch = pixels[top:bottom, left:right]
    target = np.asarray(_hex_rgb(fill), dtype=np.int16)
    distance = np.abs(patch - target).max(axis=2)
    strong = distance >= 60
    if int(strong.sum()) < 4:
        return None
    # The glyph's core, not its antialiased rim: the rim blends into the chip
    # and turns a white label pale green.
    core = distance >= max(60.0, float(distance.max()) * 0.8)
    ink = patch[core] if int(core.sum()) >= 4 else patch[strong]
    colour = "#%02x%02x%02x" % tuple(
        int(value) for value in np.median(ink.reshape(-1, 3), axis=0)
    )
    rows = np.where(strong.sum(axis=1) >= max(2, (right - left) // 20))[0]
    if rows.size == 0:
        return None
    return colour, float(rows.max() - rows.min() + 1)


#: A line OCR read this confidently is a line that is on the page.
OCR_PROMOTE_CONFIDENCE = 0.6
#: ... unless a node already paints that box: anything above this share of the
#: OCR line covered by an existing text node is "already there".
OCR_PROMOTE_MAX_IOA = 0.3
#: Two readings on one line whose strings agree this well are the same words.
OCR_PROMOTE_SIMILARITY = 0.6
#: ... and at this agreement the node is simply misplaced: the words are the
#: same, so OCR's box is where they belong and the node is moved, not copied.
OCR_PROMOTE_MOVE_SIMILARITY = 0.9


def _rows_share(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
    share: float = 0.5,
    reach: int = 160,
) -> bool:
    """Whether two boxes sit on one visual row, within reading distance."""
    rows = min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1])
    if rows < min(left[3], right[3]) * share:
        return False
    gap = max(left[0], right[0]) - min(left[0] + left[2], right[0] + right[2])
    return gap <= reach


def _promote_ocr_text(
    elements: list[dict[str, Any]],
    image_path: str,
    canvas: tuple[int, int] | None,
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Turn words OCR read into text nodes the plan never carried.

    The scene plan is a model's summary of a screenshot, and it skips whole nav
    bars, button labels and status lines: marketplace's 首页/模型广场/控制台,
    AtomGit's AtomCode/探索更多, review's 系统运行正常.  OCR read every one of
    them at its true coordinates, but until now those readings were only used to
    *correct* nodes that already existed — a missed line stayed missing.

    A confident line that no node covers is promoted as an ordinary text node.
    From there it follows the same path as any other: chip sampling paints the
    red/blue/black pill behind it, duplicate removal still applies, and the
    frame pass decides whether it belongs to a container.  Exact wording is
    skipped rather than merged — a line that overlaps a node, or repeats one on
    the same row, was already printed.
    """
    if not ocr_observations or not canvas:
        return 0
    from src.app.services.structure.fidelity.contracts import (
        normalize_match_text,
        owner_text_similarity,
    )

    width, height = canvas
    existing: list[tuple[tuple[int, int, int, int], str]] = []
    for element in elements:
        if str(element.get("type")) != "text" or not element.get("text"):
            continue
        rect = _layout_rect(element)
        if rect is None:
            continue
        existing.append((rect, normalize_match_text(element.get("text"))))

    added = 0
    for observation in ocr_observations:
        if not isinstance(observation, Mapping):
            continue
        try:
            confidence = float(observation.get("confidence") or 0)
        except (TypeError, ValueError):
            continue
        if confidence < OCR_PROMOTE_CONFIDENCE:
            continue
        text = str(observation.get("text") or "").strip()
        if not text or text.isdigit():
            continue
        if not any(character.isalnum() for character in text):
            continue
        box = observation.get("bbox")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            left, top, box_width, box_height = (int(value) for value in box)
        except (TypeError, ValueError):
            continue
        if box_width < 6 or box_height < 8:
            continue
        left = max(0, left)
        top = max(0, top)
        box_width = min(box_width, width - left)
        box_height = min(box_height, height - top)
        if box_width < 6 or box_height < 8:
            continue
        rect = (left, top, box_width, box_height)
        # A single glyph is only worth a node when it sits on a row that other
        # words already describe: the 起 beside a price, the 折 inside a badge.
        # A stray mark on its own is not a label.
        if len(text) < 2 and not any(
            _rows_share(rect, other_rect)
            for other_rect, _key in existing
        ):
            continue
        key = normalize_match_text(text)
        moved = False
        blocked = False
        for element in elements:
            if str(element.get("type")) != "text" or not element.get("text"):
                continue
            if str(element.get("imageMVP", {}).get("source")) == "ocr-promotion":
                continue
            other_rect = _layout_rect(element)
            if other_rect is None:
                continue
            rows = min(rect[1] + rect[3], other_rect[1] + other_rect[3]) - max(
                rect[1], other_rect[1]
            )
            if rows < min(rect[3], other_rect[3]) * 0.6:
                continue
            if (
                owner_text_similarity(element.get("text"), text)
                < OCR_PROMOTE_MOVE_SIMILARITY
            ):
                continue
            # Same words on the same row: this is the node that was measured in
            # the wrong place, and OCR is where it actually is.  Moving it is
            # the repair; adding a second copy prints the row twice.
            if abs(other_rect[0] - left) > 6 or abs(other_rect[2] - box_width) > 8:
                element["x"] = left
                element["y"] = top
                element["width"] = box_width
                element["height"] = box_height
                style = element.get("style")
                if isinstance(style, dict):
                    style["textAlign"] = "left"
                for name in ("textBox", "textEmBox"):
                    value = element.get(name)
                    if isinstance(value, (list, tuple)) and len(value) == 4:
                        element[name] = [left, top, box_width, box_height]
                moved = True
            else:
                blocked = True
            break
        if moved:
            continue
        if blocked:
            continue
        for other_rect, other_key in existing:
            if _overlap_share(rect, other_rect) >= OCR_PROMOTE_MAX_IOA:
                blocked = True
                break
            rows = min(rect[1] + rect[3], other_rect[1] + other_rect[3]) - max(
                rect[1], other_rect[1]
            )
            same_row = rows >= min(rect[3], other_rect[3]) * 0.6
            if not other_key or not key:
                continue
            # OCR reads a paragraph line by line while the plan writes it as one
            # box with different wrapping, so the same words can sit ten pixels
            # apart and still be one sentence.  Within a few line heights, one
            # string containing the other is a repeat, not a new label.
            near = abs(
                (rect[1] + rect[3] / 2) - (other_rect[1] + other_rect[3] / 2)
            ) <= max(rect[3], other_rect[3]) * 2.5
            if (same_row or near) and (key in other_key or other_key in key):
                blocked = True
                break
            if same_row and owner_text_similarity(other_key, key) >= OCR_PROMOTE_SIMILARITY:
                blocked = True
                break
        if blocked:
            continue
        digest = hashlib.sha1(
            f"{left}:{top}:{box_width}:{box_height}:{text}".encode("utf-8")
        ).hexdigest()[:16]
        node = {
            "id": f"text:ocr-{digest}",
            "type": "text",
            "role": "text",
            "bbox": [left, top, box_width, box_height],
            "text": text,
            "content_ref": f"text:ocr-{digest}",
        }
        element = _text_element(
            node,
            image_path=image_path,
            width=width,
            height=height,
            node_by_id={},
        )
        # The line was read, not described: it keeps OCR's own box.
        element["x"] = left
        element["y"] = top
        element["width"] = box_width
        element["height"] = box_height
        element.setdefault("imageMVP", {})["source"] = "ocr-promotion"
        elements.append(element)
        existing.append((rect, key))
        added += 1

    return added


def _restore_chip_labels(
    elements: list[dict[str, Any]],
    image_path: str,
    canvas: tuple[int, int] | None,
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Put the word back inside a badge whose label was absorbed by its row.

    A row reads two ways: "库位" on the green chip, and the whole line as one
    string.  The line wins the duplicate pass — it carries every word — and the
    chip is left empty: the badge is real, its word is missing.  OCR still has
    the chip's own reading at the chip's own coordinates, so the label is rebuilt
    from there, centred in the chip and inked in the chip's own type colour.
    """
    if not ocr_observations or not canvas:
        return 0
    pixels = _pixel_edges(image_path, canvas[0], canvas[1])
    lines: list[tuple[str, tuple[int, int, int, int]]] = []
    for observation in ocr_observations:
        if not isinstance(observation, Mapping):
            continue
        text = str(observation.get("text") or "").strip()
        box = observation.get("bbox")
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            lines.append((text, tuple(int(value) for value in box)))
        except (TypeError, ValueError):
            continue
    if not lines:
        return 0
    existing = [
        rect
        for rect in (
            _layout_rect(element)
            for element in elements
            if str(element.get("type")) == "text" and element.get("text")
        )
        if rect is not None
    ]
    restored = 0
    for element in list(elements):
        if str(element.get("role") or "") != "text-backdrop":
            continue
        chip = _layout_rect(element)
        if chip is None:
            continue
        if not (
            CHIP_MIN_WIDTH <= chip[2] <= CHIP_MAX_WIDTH and chip[3] <= CHIP_MAX_HEIGHT
        ):
            continue
        if any(_rect_contains(chip, other, tolerance=2) for other in existing):
            continue
        fill = _solid_fill(element)
        if not fill:
            continue
        best: tuple[float, str, tuple[int, int, int, int]] | None = None
        for text, line in lines:
            if not _rect_contains(chip, line, tolerance=3):
                continue
            share = _overlap_share(line, chip)
            if best is None or share > best[0]:
                best = (share, text, line)
        if best is None or best[0] < 0.5:
            continue
        ink = _chip_ink(pixels, best[2], fill)
        colour = ink[0] if ink else "#ffffff"
        height = ink[1] if ink else best[2][3] * 0.8
        size = min(max(height * INK_TO_FONT, TABLE_FONT_MIN), TABLE_FONT_MAX)
        width = best[2][2]
        digest = hashlib.sha1(
            f"{chip[0]}:{chip[1]}:{best[1]}".encode("utf-8")
        ).hexdigest()[:16]
        # A badge centres its word; the OCR box is the ink's own extent, so its
        # size is kept and only its origin is moved to the middle.
        box_x = chip[0] + (chip[2] - width) / 2
        box_y = chip[1] + (chip[3] - best[2][3]) / 2
        label = {
            "id": f"text:chip-{digest}",
            "type": "text",
            "x": int(round(box_x)),
            "y": int(round(box_y)),
            "width": width,
            "height": best[2][3],
            "text": best[1],
            "style": {
                "textColor": colour,
                "fontSize": round(size, 2),
                "fontWeight": "normal",
                "fontFamily": "Noto Sans SC",
                "textAlign": "center",
            },
            "contentRef": f"text:chip-{digest}",
            "sceneOwnerId": f"text:chip-{digest}",
            "imageMVP": {
                "source": "pixel-recovery",
                "role": "text",
                "candidate_type": "text",
                "grouping_status": "recovered",
                "reference_only": False,
                "generated": False,
                "textStatus": "ocr-chip-label",
            },
            "badgeLabel": True,
        }
        elements.append(label)
        existing.append((label["x"], label["y"], label["width"], label["height"]))
        restored += 1
    return restored


def _tail_key(element: Mapping[str, Any]) -> str:
    """A text node's words, comparable across two models of the same sentence.

    ``OCR_HOMOGLYPHS`` folds the lower-case confusions; a capital ``I`` read as a
    lower-case ``l`` ("AI" vs "Al") is the one this pass actually met, so the
    vertical strokes are folded here as well.  Comparison only — the text keeps
    whatever the model wrote.
    """
    folded = "".join(_fold_homoglyphs(str(element.get("text") or "")).split())
    return (
        folded.replace("I", "1").replace("i", "1").replace("l", "1").replace("|", "1")
    )


def _drop_paragraph_tails(elements: list[dict[str, Any]]) -> int:
    """Remove a fragment that is only the tail of a paragraph printed above it.

    When a paragraph is modelled once as a whole string and once as its wrapped
    remainder, the two boxes do not overlap — the fragment starts on the line
    below — so the coincidence test leaves both.  In the SVG the paragraph then
    runs past the card edge and the fragment repeats its last words; in Figma,
    where the paragraph wraps inside its box, the two occupy the same lines and
    print on top of each other.

    The signature is specific enough to act on: the short string is a *suffix*
    of the long one, it starts on a later line, and it sits inside the same
    horizontal span.  A standalone label that happens to repeat the end of a
    nearby paragraph is the risk, so the fragment has to be a real piece of
    prose (six characters), the paragraph has to be most of a sentence longer,
    and the fragment has to begin below the paragraph's first line.
    """
    tails = 0
    texts = [
        (index, element)
        for index, element in enumerate(elements)
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    doomed: set[int] = set()
    for fragment_index, fragment in texts:
        if fragment_index in doomed:
            continue
        # OCR reads the same word differently in the two models ("AI" vs "Al"),
        # so the comparison folds homoglyphs and drops the spaces that a line
        # break introduced.  Matching only; the text itself is untouched.
        fragment_text = _tail_key(fragment)
        if len(fragment_text) < PARAGRAPH_TAIL_MIN_CHARS:
            continue
        for host_index, host in texts:
            if host_index == fragment_index or host_index in doomed:
                continue
            host_text = _tail_key(host)
            if len(host_text) < len(fragment_text) + PARAGRAPH_TAIL_LENGTH_MARGIN:
                continue
            if not host_text.endswith(fragment_text):
                continue
            fragment_box = _layout_rect(fragment)
            host_box = _layout_rect(host)
            if fragment_box is None or host_box is None:
                continue
            fx, fy, fw, fh = fragment_box
            hx, hy, hw, hh = host_box
            if fy < hy + PARAGRAPH_TAIL_MIN_DROP:
                continue
            if fy > hy + hh + PARAGRAPH_TAIL_REACH:
                continue
            overlap = min(fx + fw, hx + hw) - max(fx, hx)
            if overlap < fw * PARAGRAPH_TAIL_HORIZONTAL_SHARE:
                continue
            doomed.add(fragment_index)
            tails += 1
            break
    if not doomed:
        return 0
    elements[:] = [
        element for index, element in enumerate(elements) if index not in doomed
    ]
    return tails


def _drop_text_under_patches(elements: list[dict[str, Any]]) -> int:
    """Delete vector text that a picture patch already prints.

    A patch is cut from the screenshot, so any vector node inside it is a second
    print of the same words — the discount stamps were exactly that: a bitmap of
    "5.8 折" with a text node on top of it.  The patch wins because it carries the
    真实像素; the node only adds a ghost.

    `mark` crops are deliberately *not* included: a mark is often a bitmap of a
    label that is also modelled as text (AtomGit's 智能体开发), and there the text
    is the better asset — it stays editable.  Words with no OCR support sitting on
    a chip-sized mark are handled by `_drop_nested_texts`, which asks the picture
    first.

    Frame members are referenced by id, so removing an element is safe once the
    id is also removed from any frame that lists it.
    """
    patches = [
        _layout_rect(element)
        for element in elements
        if str(element.get("role") or "") == "patch"
    ]
    patches = [box for box in patches if box]
    if not patches:
        return 0
    doomed: set[str] = set()
    for element in elements:
        if element.get("type") != "text" or not str(element.get("text") or "").strip():
            continue
        box = _layout_rect(element)
        if box is None:
            continue
        area = max(1, box[2] * box[3])
        for patch in patches:
            overlap_w = min(box[0] + box[2], patch[0] + patch[2]) - max(box[0], patch[0])
            overlap_h = min(box[1] + box[3], patch[1] + patch[3]) - max(box[1], patch[1])
            if overlap_w <= 0 or overlap_h <= 0:
                continue
            if (overlap_w * overlap_h) / area >= PATCH_TEXT_COVER:
                doomed.add(str(element.get("id") or element.get("contentRef") or ""))
                break
    if not doomed:
        return 0
    elements[:] = [
        element
        for element in elements
        if str(element.get("id") or element.get("contentRef") or "") not in doomed
    ]
    for element in elements:
        members = element.get("layoutChildren")
        if isinstance(members, list):
            element["layoutChildren"] = [
                member
                for member in members
                if str(member.get("id") or "") not in doomed
            ]
    return len(doomed)


def _drop_contained_texts(elements: list[dict[str, Any]]) -> int:
    """Delete a text node that is the ghost of a bigger one in the same place.

    "11月 &日更新" sat inside "价目牌 · 82 个模型 · 11 月 8 日更新" and printed on
    top of it; "Kimi" sat inside "Kimi K3"; "¥8.00" inside "¥4.64 ¥8.00".  The
    overlap test upstream compares coverage and wording and lets these through
    because the words differ.  Containment is the signal: when the smaller box
    lives inside the larger one and the two share the words they do have, the
    smaller is a second model of the same line.
    """
    from difflib import SequenceMatcher

    texts = [
        element
        for element in elements
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    doomed: set[str] = set()
    for small in texts:
        small_key = str(small.get("id") or "")
        if not small_key or small_key in doomed:
            continue
        small_box = _layout_rect(small)
        if small_box is None:
            continue
        small_area = max(1, small_box[2] * small_box[3])
        for big in texts:
            if big is small:
                continue
            big_box = _layout_rect(big)
            if big_box is None:
                continue
            if big_box[2] * big_box[3] <= small_area:
                continue
            overlap_w = min(small_box[0] + small_box[2], big_box[0] + big_box[2]) - max(
                small_box[0], big_box[0]
            )
            overlap_h = min(small_box[1] + small_box[3], big_box[1] + big_box[3]) - max(
                small_box[1], big_box[1]
            )
            if overlap_w <= 0 or overlap_h <= 0:
                continue
            if (overlap_w * overlap_h) / small_area < CONTAINED_TEXT_IOA:
                continue
            one = _tail_key(small)
            two = _tail_key(big)
            if not one or not two:
                continue
            # 用词对得上：相似度够、或互相包含、或短的那句的字符几乎都在长句里
            # （OCR 把 "8" 读成 "&" 时，"11月 &日更新" 与 "…11 月 8 日更新" 的
            # 相似度只有 0.45，但字符覆盖是 0.83）。
            covered = set(one) & set(two)
            char_cover = len(covered) / max(1, len(set(one)))
            if (
                SequenceMatcher(None, one, two).ratio() >= CONTAINED_TEXT_SIMILARITY
                or one in two
                or two in one
                or _shared_affix(one, two) >= 4
                or char_cover >= 0.8
            ):
                doomed.add(small_key)
                break
    if not doomed:
        return 0
    elements[:] = [
        element
        for element in elements
        if str(element.get("id") or element.get("contentRef") or "") not in doomed
    ]
    for element in elements:
        members = element.get("layoutChildren")
        if isinstance(members, list):
            element["layoutChildren"] = [
                member for member in members if str(member.get("id") or "") not in doomed
            ]
    return len(doomed)


def _ocr_carries(
    text: str,
    box: tuple[int, int, int, int],
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> bool:
    """Does an OCR line *at this box* actually spell these words?

    Containment, not character overlap.  "¥4.64" shares two characters with
    "DeepSeek V4.1 Flash", and counting that as support is how a phantom price
    gets to sit on top of a title: every box test passes because the title's box
    covers it.
    """
    key = "".join(_fold_homoglyphs(str(text or "")).split()).lower()
    if not key:
        return False
    wanted = set(key)
    for observation in ocr_observations or []:
        line = "".join(
            _fold_homoglyphs(str(observation.get("text") or "")).split()
        ).lower()
        if not line:
            continue
        raw_box = observation.get("bbox") or []
        if len(raw_box) != 4:
            continue
        other = tuple(int(value) for value in raw_box)
        if (
            _overlap_share(box, other) < OCR_SUPPORT_OVERLAP
            and _overlap_share(other, box) < OCR_SUPPORT_OVERLAP
        ):
            continue
        # Characters, not containment: OCR spells "输入 · 峰时" as "输入 .峰时"
        # and "谷时 ¥0.58" as "谷时半0.58", and a legit line must not be thrown
        # away because the engine guessed one glyph wrong.
        if len(wanted & set(line)) / len(wanted) >= OCR_SUPPORT_CHARS:
            return True
    return False


def _drop_nested_texts(
    elements: list[dict[str, Any]],
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Delete a text node that prints where a bigger text node already prints.

    Two lines of type never share the same pixels; when they appear to, one of
    them is not describing the picture.  marketplace's DeepSeek card had four of
    these — "¥4.64", "¥8.00", "¥2.00" and "起 ¥23.00" all mapped onto the card's
    title band, so the export looked like a title with small type smudged into it.

    Wording cannot decide this: those strings are not variants of the title, they
    are different words in the wrong place.  What decides it is support — the
    picture's own OCR at that box.  A table cell where "冻结库存" sits inside a
    wide value box *is* supported by OCR, and is left alone.
    """
    texts = [
        element
        for element in elements
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    # Pictures about the size of the words they sit under are chips and icons — a
    # crop the compiler already committed to.  A full-bleed photo is not: words
    # over a photo are normal, so only comparable areas count here.
    chips = [
        (_layout_rect(element), int(element.get("width") or 0) * int(element.get("height") or 0))
        for element in elements
        if element.get("imageBase64")
    ]
    chips = [(box, area) for box, area in chips if box]
    doomed: set[str] = set()
    for small in texts:
        small_key = str(small.get("id") or "")
        if not small_key or small_key in doomed:
            continue
        small_box = _layout_rect(small)
        if small_box is None:
            continue
        if _ocr_carries(str(small.get("text") or ""), small_box, ocr_observations):
            continue
        small_area = small_box[2] * small_box[3]
        small_centre = small_box[1] + small_box[3] / 2.0
        for big in texts:
            if big is small or str(big.get("id") or "") in doomed:
                continue
            big_box = _layout_rect(big)
            if big_box is None:
                continue
            if big_box[2] * big_box[3] <= small_area:
                continue
            if _overlap_share(small_box, big_box) < NESTED_TEXT_SHARE:
                continue
            # Same line: a value printed under a heading lives one line lower and
            # keeps its own vertical band.  These occupy the same band.
            if abs(small_centre - (big_box[1] + big_box[3] / 2.0)) > max(
                3.0, small_box[3] * NESTED_TEXT_LINE_TOLERANCE
            ):
                continue
            if big_box[3] > small_box[3] * NESTED_TEXT_HEIGHT_RATIO:
                continue
            doomed.add(small_key)
            break
        if small_key in doomed:
            continue
        for picture_box, picture_area in chips:
            if picture_area > small_area * NESTED_IMAGE_AREA_RATIO:
                continue
            if _overlap_share(small_box, picture_box) >= PATCH_TEXT_COVER:
                doomed.add(small_key)
                break
    if not doomed:
        return 0
    elements[:] = [
        element
        for element in elements
        if str(element.get("id") or element.get("contentRef") or "") not in doomed
    ]
    for element in elements:
        members = element.get("layoutChildren")
        if isinstance(members, list):
            element["layoutChildren"] = [
                member for member in members if str(member.get("id") or "") not in doomed
            ]
    return len(doomed)


# ---------------------------------------------------------------------------
# 文本融合的三道闸：无据标签、同页重复、空间互斥
#
# 盲测（ERP / 日工时 / Gmail）暴露的不是"某条阈值不准"，而是**判据的维度错了**：
# 去重按字符串相似度判断，而同一块内容被 grounding 与 OCR 各描述一次时，两份的
# 字符串本来就不同（"新建" vs "+ 新建"）；冲突按覆盖率判断，而两份往往是一大一小
# 叠在一起。物理界面上两块文本不可能同时占同一片区域，所以这里改成按**位置**判，
# 字符串只用来决定谁留下。
# ---------------------------------------------------------------------------

#: 两个文本框的交并比到这个程度，就是同一块内容的两次建模。
TEXT_NMS_IOU = 0.35
#: 或者：小框被大框吃掉这么多（一整个单元格 vs 里面那行字）。
TEXT_NMS_IOA = 0.55
#: 重复表头里，没被 OCR 支撑的那一份最多比有支撑的那份大这么多倍才允许删。
DUPLICATE_LABEL_MAX_SLACK = 4
#: 表格正文字号上限：同表行字号中位数 + 这么多像素。
TABLE_FONT_SLACK = 2.0
#: 行分带的粒度：单元格高度在 24~40px 之间，取 24 刚好一行一带。
TABLE_ROW_BAND = 24
#: 字号最多占单元格高度的这个比例，再大就溢出到邻行了。
TABLE_FONT_FIT = 0.95


def _rect_overlap(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int]
) -> tuple[float, float]:
    """(IoU, share of the smaller box that is covered)."""
    width = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    height = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0, 0.0
    inter = width * height
    union = a[2] * a[3] + b[2] * b[3] - inter
    smaller = min(a[2] * a[3], b[2] * b[3])
    return inter / max(1, union), inter / max(1, smaller)


def _texts_collide(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int]
) -> bool:
    iou, ioa = _rect_overlap(a, b)
    return iou >= TEXT_NMS_IOU or ioa >= TEXT_NMS_IOA


def _ocr_supported(
    text: str,
    box: tuple[int, int, int, int] | None,
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> bool:
    if box is None:
        return False
    return bool(_ocr_carries(text, box, ocr_observations))


def _spatial_text_nms(
    elements: list[dict[str, Any]],
    ocr_observations: Sequence[Mapping[str, Any]] | None = None,
    background: str = "",
) -> int:
    """Two text boxes cannot occupy one patch of a screen. Keep one, by position.

    The old pass asked "do these two strings look alike"; a label the VLM wrote
    as "新建" and OCR read as "+ 新建" is the same words on the page and scored
    0.5.  The question that actually has a physical answer is "do these two boxes
    cover the same area" — and it does not care what the strings say.

    Who survives: the reading the picture supports (OCR read characters inside
    its own box), then the one that can actually be seen (ink contrast), then
    the one whose box fits its own rendered span.  Losing a member can cost a
    frame, so this runs before the frame pass and `_keep_renderable_frames`
    still has the last word.
    """
    texts = [
        index
        for index, element in enumerate(elements)
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    if len(texts) < 2:
        return 0
    rects = {index: _layout_rect(elements[index]) for index in texts}

    def score(index: int) -> tuple:
        element = elements[index]
        supported = _ocr_supported(
            str(element.get("text") or ""), rects[index], ocr_observations
        )
        contrast = _ink_contrast(element, elements, background)
        rect = rects[index]
        fit = 0.0
        if rect is not None:
            left, right = _rendered_span(element)
            span = max(1, right - left)
            fit = min(rect[2], span) / span
        return (1 if supported else 0, 1 if contrast >= INK_MIN_CONTRAST else 0, contrast, fit)

    doomed: set[int] = set()
    for position, first in enumerate(texts):
        if first in doomed or rects[first] is None:
            continue
        for second in texts[position + 1 :]:
            if second in doomed or rects[second] is None:
                continue
            if not _texts_collide(rects[first], rects[second]):
                continue
            loser = first if score(first) < score(second) else second
            winner = second if loser == first else first
            # 字体差三倍以上、又没有 OCR 支撑的那份，几乎一定是把装饰字当正文。
            doomed.add(loser)
            elements[winner].setdefault("nmsEvidence", {})["absorbed"] = (
                str(elements[loser].get("text") or "")[:20]
            )
            if loser == first:
                break
    if not doomed:
        return 0
    elements[:] = [
        element for index, element in enumerate(elements) if index not in doomed
    ]
    return len(doomed)


def _drop_unsupported_duplicate_labels(
    elements: list[dict[str, Any]],
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """Same words twice on one page: the copy the picture does not read goes.

    ERP's item-table header cells were synthesised a second time inside the form
    area, 350px above the real row.  Both copies are internally consistent, so
    no similarity test can arbitrate — but only one of them sits where the
    picture has those characters, and OCR already knows which.
    """
    if not ocr_observations:
        return 0
    groups: dict[str, list[int]] = {}
    for index, element in enumerate(elements):
        if element.get("type") != "text":
            continue
        text = str(element.get("text") or "").strip()
        if len(text) < 2:
            continue
        # 表格单元格也进组：ERP 那份浮动表头正是 `table-header:` 与普通 `text:`
        # 各一份。同名多行（两行都写"广东特拓MOM"）不会误删——它们每一份都有
        # OCR 支撑，规则要求"有的有支撑、有的没有"才动手。
        groups.setdefault(_fold_homoglyphs(text), []).append(index)
    doomed: set[int] = set()
    for members in groups.values():
        if not 2 <= len(members) <= DUPLICATE_LABEL_MAX_SLACK:
            continue
        supported = [
            index
            for index in members
            if _ocr_supported(
                str(elements[index].get("text") or ""),
                _layout_rect(elements[index]),
                ocr_observations,
            )
        ]
        if not supported or len(supported) == len(members):
            continue
        for index in members:
            if index in supported:
                continue
            box = _layout_rect(elements[index])
            twin = _layout_rect(elements[supported[0]])
            if box is None or twin is None:
                continue
            # 只处理"同一行、位置不同"的副本；叠在一起的那种归空间互斥管。
            if _texts_collide(box, twin):
                continue
            doomed.add(index)
    if not doomed:
        return 0
    elements[:] = [
        element for index, element in enumerate(elements) if index not in doomed
    ]
    return len(doomed)


def _text_like_ink(image, box: tuple[int, int, int, int]) -> bool:
    """Whether the picture at this box looks like words rather than a glyph/icon.

    One connected blob the size of the box is an icon (a star, a chevron, a "?").
    Words are several small components with thin strokes.  The test is only ever
    used to *reject* a label, so an ambiguous crop counts as text and the label
    survives.
    """
    import cv2
    import numpy as np

    x, y, w, h = box
    height, width = image.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 6 or y1 - y0 < 6:
        return True
    crop = np.asarray(image[y0:y1, x0:x1], dtype=np.int16)
    ring = np.concatenate(
        [
            crop[0:1].reshape(-1, 3),
            crop[-1:].reshape(-1, 3),
            crop[:, 0:1].reshape(-1, 3),
            crop[:, -1:].reshape(-1, 3),
        ]
    )
    surface = np.median(ring, axis=0)
    ink = (np.abs(crop - surface).max(axis=2) > 40).astype(np.uint8)
    share = float(ink.mean())
    if share < 0.01 or share > 0.45:
        return False
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(ink, 8)
    area = max(1, (x1 - x0) * (y1 - y0))
    small = 0
    for index in range(1, count):
        component = int(stats[index][4])
        if component < 3:
            continue
        if component <= area * 0.25:
            small += 1
    return small >= 2


def _drop_unbacked_labels(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """A name the VLM gave an icon is not text on the page.

    Gmail came back with nine `星标` buttons down a column of star icons, plus
    "设置 / 帮助 / 上一页 / 下一页" floating over glyphs.  Each is a label the
    model attached to a shape: OCR read nothing at that box and the picture has
    one blob there, not characters.  Three things must all hold before dropping,
    because losing a real label is worse than keeping a hallucinated one: no OCR
    support at its own box, no OCR line overlapping it at all, and no text-like
    ink underneath.
    """
    if not ocr_observations:
        # 没有 OCR 就没有"字符支撑"这回事：这条规则的前提是 OCR 跑过且这一带
        # 一个字都没读到。离线样本没有 OCR 时必须整体跳过，否则会把正常文字删光。
        return 0
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    image = image[:height, :width]
    lines = [
        (str(item.get("text") or ""), tuple(int(v) for v in item.get("bbox") or []))
        for item in ocr_observations or []
        if len(item.get("bbox") or []) == 4
    ]
    doomed: set[int] = set()
    for index, element in enumerate(elements):
        if element.get("type") not in ("text", "button", "input"):
            continue
        label = str(element.get("text") or "").strip()
        if not label:
            continue
        if str(element.get("id") or "").startswith("table-"):
            continue
        box = _layout_rect(element)
        if box is None or box[2] < 6 or box[3] < 6:
            continue
        if _ocr_supported(label, box, ocr_observations):
            continue
        if any(
            _rect_overlap(box, other)[1] >= 0.3 for _text, other in lines if len(other) == 4
        ):
            # 这一带 OCR 读到过字（哪怕读成别的），说明画面里确实有文字。
            continue
        if element.get("type") in ("button", "input"):
            style = element.get("style") or {}
            if int(style.get("borderWidth") or 0) > 0:
                continue
        if _text_like_ink(image, box):
            continue
        doomed.add(index)
    if not doomed:
        return 0
    elements[:] = [
        element for index, element in enumerate(elements) if index not in doomed
    ]
    return len(doomed)


#: 渲染宽度超出盒子这么多才动手：字体度量差 1~2% 是正常抖动。
TEXT_FIT_TOLERANCE = 0.03
#: 缩字下限：小于原字号 85% 就不是同一层级了，宁可收字距。
TEXT_FIT_MIN_SCALE = 0.85
#: 负字距最多收到字号的这个比例。
TEXT_FIT_MAX_TRACKING = -0.04


def _estimated_width(text: str, font: float) -> float:
    """Width the renderer will paint, from the same per-character estimate."""
    width = 0.0
    for char in text:
        width += font * (1.0 if ord(char) > 0x2E80 else 0.55)
    return width


def _fit_text_to_box(elements: list[dict[str, Any]]) -> int:
    """A line that overruns its measured box far enough to touch the next column.

    The screenshot measured the ink; the output font has different metrics, so a
    cell that fits in the picture can overprint its neighbour in Figma.  Only an
    overrun that actually reaches another text node is touched — shrinking every
    wide line would flatten the type hierarchy for nothing.

    Two knobs, in order: type size down to 85% of the measured size, then a small
    negative tracking.  Both are recorded on the element so the change is
    reviewable instead of mysterious.
    """
    texts = [
        index
        for index, element in enumerate(elements)
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    if len(texts) < 2:
        return 0
    rects = {index: _layout_rect(elements[index]) for index in texts}
    fitted = 0
    for index in texts:
        element = elements[index]
        box = rects[index]
        if box is None or box[2] <= 4:
            continue
        style = element.setdefault("style", {})
        try:
            font = float(style.get("fontSize") or 0.0)
        except (TypeError, ValueError):
            font = 0.0
        if font <= 0:
            continue
        text = str(element.get("text") or "")
        estimated = _estimated_width(text, font)
        if estimated <= box[2] * (1.0 + TEXT_FIT_TOLERANCE):
            continue
        # 可用宽度：自己的盒子，以及同一行右边最近那段文字的左缘。表格里"格子"
        # 往往没有容器，能防住串列的就是邻列的位置。
        limit = float(box[2])
        for other in texts:
            if other == index:
                continue
            other_box = rects[other]
            if other_box is None:
                continue
            if other_box[1] >= box[1] + box[3] or other_box[1] + other_box[3] <= box[1]:
                continue
            gap = other_box[0] - box[0]
            if gap > box[2] - 2:
                limit = min(limit, float(gap))
        if estimated <= limit * (1.0 + TEXT_FIT_TOLERANCE):
            continue
        scale = max(TEXT_FIT_MIN_SCALE, min(1.0, limit * 0.99 / estimated))
        new_font = round(font * scale * 2) / 2
        if new_font >= font:
            new_font = max(6.0, round(font * TEXT_FIT_MIN_SCALE * 2) / 2)
        style["fontSize"] = new_font
        remaining = limit - _estimated_width(text, new_font)
        if remaining < 0 and text:
            tracking = max(
                TEXT_FIT_MAX_TRACKING * new_font,
                remaining / max(1, len(text)),
            )
            style["letterSpacing"] = round(tracking, 2)
        element.setdefault("fitEvidence", {})["widthFit"] = {
            "from": round(font, 1),
            "to": round(new_font, 1),
            "box": box[2],
            "estimated": round(estimated, 1),
        }
        fitted += 1
    return fitted


def _clamp_table_fonts(elements: list[dict[str, Any]]) -> int:
    """A table's body copy cannot be twice the size of its own rows.

    The worklog table came back with 34px cells next to 30.5px ones; in a 30px
    row that overflows the cell and prints over its neighbours.  The cap is the
    table's own row median + 2px — a per-page constant would be wrong on a 2x
    screenshot and on a 1x one alike.
    """
    groups: dict[Any, list[int]] = {}
    for index, element in enumerate(elements):
        if element.get("type") != "text":
            continue
        if not str(element.get("text") or "").strip():
            continue
        if not str(element.get("id") or "").startswith(("table-cell:", "table-header:")):
            continue
        box = _layout_rect(element)
        if box is None:
            continue
        # 按**行**分组，不是按整张表：规则说的是"该表行字号中位数"，
        # 一行的单元格字号本来就该一致；按整表取中位数会把标题行的高字号
        # 也算进正文里，34px 的离群永远压不下来。
        band = int(round(float(box[1]) / TABLE_ROW_BAND))
        groups.setdefault(band, []).append(index)
    changed = 0
    for members in groups.values():
        sizes = sorted(
            float((elements[index].get("style") or {}).get("fontSize") or 0)
            for index in members
        )
        sizes = [size for size in sizes if size > 0]
        if len(sizes) < 3:
            continue
        median = sizes[len(sizes) // 2]
        ceiling = median + TABLE_FONT_SLACK
        for index in members:
            style = elements[index].setdefault("style", {})
            size = float(style.get("fontSize") or 0)
            box = _layout_rect(elements[index])
            # 第二个上限来自盒子本身：字号大于单元格高度，字就印到邻行上去了。
            # 行中位数只能防"比同行大"，防不了"比自己的格子还高"。
            limit = ceiling
            if box is not None and box[3] >= 8:
                limit = min(limit, box[3] * TABLE_FONT_FIT)
            if size > limit:
                style["fontSize"] = max(TABLE_FONT_MIN, round(limit * 2) / 2)
                changed += 1
    return changed


def _restore_display_weight(
    elements: list[dict[str, Any]],
    image_path: str | Path,
    width: int,
    height: int,
) -> int:
    """Give the page's biggest line the weight a display title is set in.

    The stroke test in `style_resolver` measures `2*area/perimeter`, which is the
    right number for text at reading sizes and the wrong one for a 99px hero: a
    Song face has 12px verticals and 2px horizontals, so the average lands at
    0.086em — under the bold threshold — and the title comes out Regular, which
    is the one thing a page cannot afford.

    So the biggest line is judged by role, not by average: if it measures at
    least `DISPLAY_STROKE_MIN` of its own em, it is display type and gets 800.
    """
    import numpy as np
    from PIL import Image

    from src.app.services.structure.fidelity.style_resolver import _stroke_thickness

    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, FileNotFoundError):
        return 0
    sized = [
        element
        for element in elements
        if element.get("type") == "text"
        and str(element.get("text") or "").strip()
        and float((element.get("style") or {}).get("fontSize") or 0) >= DISPLAY_MIN_SIZE
    ]
    if not sized:
        return 0
    biggest = max(float((element.get("style") or {}).get("fontSize") or 0) for element in sized)
    changed = 0
    for element in sized:
        style = element.setdefault("style", {})
        size = float(style.get("fontSize") or 0)
        if abs(size - biggest) > 1.0:
            continue
        if int(style.get("fontWeightValue") or 400) >= 800:
            continue
        box = _layout_rect(element)
        if box is None:
            continue
        x, y, w, h = box
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        crop = image[y0:y1, x0:x1]
        luminance = crop.mean(axis=2)
        if float(luminance.max() - luminance.min()) < 40:
            continue
        mask = luminance >= (float(np.percentile(luminance, 5)) + float(luminance.max())) / 2.0
        if mask.sum() < 60:
            continue
        thickness = _stroke_thickness(mask.astype(np.uint8))
        if thickness / max(1.0, size) < DISPLAY_STROKE_MIN:
            continue
        style["fontWeightValue"] = 800
        style["fontWeight"] = "bold"
        element["weightEvidence"] = {
            "method": "display-role",
            "stroke": round(float(thickness), 2),
            "size": round(size, 1),
        }
        changed += 1
    return changed


def _separate_badge_icon_text(elements: list[dict[str, Any]]) -> int:
    """Start a badge's words after the glyph instead of inside it.

    A pill that reads "● 大厂直供" arrives as a box over the pill, an icon cut
    over the dot and a text box that begins on top of the dot.  The three are
    measured independently, so nothing notices that the first word is printed
    through the icon.  Moving the words to the icon's right edge is the whole
    repair; the pill keeps its size, so no frame changes.

    Only inside a badge: a pill or a button is a few hundred pixels wide and at
    most a line tall.  A sidebar row is wider than that, and its icon cut
    already carries the first millimetres of the label as pixels — nudging the
    text there would print the leading glyph twice.
    """
    if not elements:
        return 0
    rects = [_layout_rect(element) for element in elements]
    icons = [
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "image"
        and rects[index] is not None
        and rects[index][2] <= 48
        and rects[index][3] <= 48
    ]
    if not icons:
        return 0
    chips = [
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "container"
        and rects[index] is not None
        and rects[index][2] <= BADGE_MAX_WIDTH
        and rects[index][3] <= BADGE_MAX_HEIGHT
    ]
    moved = 0
    for index, element in enumerate(elements):
        if str(element.get("type")) != "text" or not element.get("text"):
            continue
        box = rects[index]
        if box is None:
            continue
        chip = None
        for candidate in chips:
            chip_box = rects[candidate]
            if chip_box is None or not _rect_contains(chip_box, box, tolerance=2):
                continue
            if chip is None or chip_box[2] * chip_box[3] < rects[chip][2] * rects[chip][3]:
                chip = candidate
        if chip is None:
            continue
        chip_box = rects[chip]
        for icon in icons:
            icon_box = rects[icon]
            if icon_box is None or chip_box is None:
                continue
            if not _rect_contains(chip_box, icon_box, tolerance=2):
                continue
            overlap_h = min(box[1] + box[3], icon_box[1] + icon_box[3]) - max(
                box[1], icon_box[1]
            )
            if overlap_h < min(box[3], icon_box[3]) * 0.5:
                continue
            # The words' leading edge has to be *inside* the glyph and they have
            # to run past it: that is the printed-through-the-icon shape.  A
            # label that starts left of the icon is a different defect.
            if not (icon_box[0] + 1 < box[0] < icon_box[0] + icon_box[2] - 1):
                continue
            if box[0] + box[2] <= icon_box[0] + icon_box[2]:
                continue
            target = icon_box[0] + icon_box[2] + BADGE_ICON_GAP
            if target <= box[0]:
                continue
            # Clearing the glyph must leave the words somewhere to go.  A
            # two-pixel remainder means the "icon" was measured over the label
            # as well, so the shift would trade one bad box for another.
            remaining = box[0] + box[2] - target
            if remaining < max(12, box[2] * 0.5):
                continue
            element["x"] = target
            element["width"] = max(1, remaining)
            rects[index] = (target, box[1], element["width"], box[3])
            moved += 1
            break
    return moved


def _table_containing(
    box: tuple[int, int, int, int],
    tables: Sequence[int],
    rects: Sequence[tuple[int, int, int, int] | None],
) -> int | None:
    """The smallest table whose rectangle holds this box's centre."""
    centre_x = box[0] + box[2] / 2
    centre_y = box[1] + box[3] / 2
    best: tuple[int, int] | None = None
    for table in tables:
        other = rects[table]
        if other is None:
            continue
        if not (
            other[0] <= centre_x <= other[0] + other[2]
            and other[1] <= centre_y <= other[1] + other[3]
        ):
            continue
        area = other[2] * other[3]
        if best is None or area < best[0]:
            best = (area, table)
    return best[1] if best else None


def _recover_saturated_bars(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
) -> int:
    """Add the solid coloured bars nothing else in the plan accounts for.

    A progress bar is the one element every perception stage drops: too thin to
    be a container, no words on it, not a glyph.  The review screen came back
    with "处理进度 90%" and nothing under it.  Pixels know: a run six to
    twenty-two pixels tall, at least a hundred wide, saturated, and almost
    completely filled is a painted bar, not a line, not a border, not text.
    """
    import numpy as np
    from PIL import Image

    try:
        import cv2
    except Exception:  # pragma: no cover - opencv is a pipeline dependency
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    if image.ndim != 3 or image.shape[0] < 8 or image.shape[1] < 8:
        return 0
    image = image[:height, :width].astype(np.int32)
    pool = image.reshape(-1, 3)
    # HSV saturation, computed the cheap way: (max - min) / max.  int32 is not
    # optional: on int16 the 255x multiply overflows and a blue bar reads as
    # unsaturated noise.
    high = pool.max(axis=1)
    low = pool.min(axis=1)
    saturation = np.where(high > 0, (high - low) * 255 // np.maximum(high, 1), 0)
    mask = (
        (saturation.reshape(image.shape[:2]) >= BAR_MIN_SATURATION)
        & (high.reshape(image.shape[:2]) >= BAR_MIN_VALUE)
    ).astype(np.uint8)
    if not mask.any():
        return 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)

    rects = [_layout_rect(element) for element in elements]
    texts = [
        rects[index]
        for index, element in enumerate(elements)
        if str(element.get("type")) == "text" and element.get("text") and rects[index]
    ]

    candidates: list[tuple[int, list[int]]] = []
    for index in range(1, count):
        x, y, box_width, box_height, area = (int(value) for value in stats[index, :5])
        if box_height < BAR_MIN_HEIGHT or box_height > BAR_MAX_HEIGHT:
            continue
        if box_width < BAR_MIN_WIDTH:
            continue
        if box_width / max(1, box_height) < BAR_MIN_ASPECT:
            continue
        if area / max(1, box_width * box_height) < BAR_FILL_RATIO:
            continue
        box = (x, y, box_width, box_height)
        # Words printed on it means it is a highlight behind a label, not a bar.
        if any(_iou(box, text) >= 0.25 for text in texts):
            continue
        # Already in the design: a rule, a chip, a divider that came with a fill.
        if any(
            rect is not None
            and _iou(box, rect) >= BAR_EXISTING_IOU
            for rect in rects
        ):
            continue
        candidates.append((area, [x, y, box_width, box_height]))

    if not candidates:
        return 0
    candidates.sort(key=lambda item: item[0], reverse=True)
    added = 0
    from src.app.services.structure.image_contract import _dominant_color
    from src.app.services.structure.fidelity.pixel_probe import (
        sample_container_decoration,
    )

    for _area, box in candidates[:BAR_MAX_REGIONS]:
        digest = hashlib.sha1(
            f"{box[0]}:{box[1]}:{box[2]}:{box[3]}:{image_path}".encode("utf-8")
        ).hexdigest()[:16]
        style: dict[str, Any] = {"fillColor": _dominant_color(image_path, box, inset=1)}
        style.update(sample_container_decoration(image_path, box, style["fillColor"]))
        style.setdefault("borderRadius", max(2, min(box[3] // 2, 8)))
        elements.append(
            {
                "id": f"bar:{digest}",
                "type": "container",
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "text": "",
                "style": style,
                "role": "progress",
                "name": "Progress bar",
                "contentRef": f"bar:{digest}",
                "sceneOwnerId": f"bar:{digest}",
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "progress",
                    "grouping_status": "recovered",
                },
            }
        )
        added += 1
    return added


def _resolve_misfiled_controls(
    elements: list[dict[str, Any]],
    observations: Sequence[Mapping[str, Any]] | None,
    image_path: str,
) -> int:
    """Put a control back where its own words were read, or drop the copy.

    A navigation item measured over a table is a double fault: the table now
    has a stranger painted across its first row, and the sidebar row it came
    from is empty.  OCR knows where those words really are.  When nothing on
    the page reads them at the box the control sits in, the box is the error —
    move it onto its line, and sample the fill again, because the colour was
    taken at the wrong place too (a cyan nav pill measured over a white table
    becomes white).

    If another element already prints those words at that line, the control is
    a second copy of it and goes away instead of stacking on it.
    """
    if not elements:
        return 0
    from src.app.services.structure.fidelity.contracts import (
        normalize_owner_text,
        owner_text_similarity,
    )

    lines = _ocr_lines(observations)
    if not lines:
        return 0
    rects = [_layout_rect(element) for element in elements]
    tables = [
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "table"
        or str(element.get("id") or "").startswith("table-node:")
    ]
    if not tables:
        return 0
    doomed: set[int] = set()
    repaired = 0
    for index, element in enumerate(elements):
        if str(element.get("type")) not in {"button", "input"}:
            continue
        if str(element.get("contentRef") or "").startswith(TABLE_TEXT_PREFIXES):
            continue
        text = normalize_owner_text(element.get("text"))
        box = rects[index]
        if not text or box is None:
            continue
        if _table_containing(box, tables, rects) is None:
            continue
        # Words printed here already?  Then the box is right and this is not
        # the defect this pass handles.
        if _has_ocr_support(
            str(element.get("text") or ""), box, lines, slack=4, threshold=0.85
        ):
            continue
        target: tuple[float, tuple[int, int, int, int]] | None = None
        for line_text, line_box in lines:
            if line_text != text and owner_text_similarity(line_text, text) < 0.85:
                continue
            distance = abs(
                (line_box[0] + line_box[2] / 2) - (box[0] + box[2] / 2)
            ) + abs((line_box[1] + line_box[3] / 2) - (box[1] + box[3] / 2))
            if distance < CONTROL_REANCHOR_MIN_SHIFT:
                continue
            if target is None or distance < target[0]:
                target = (distance, line_box)
        if target is None:
            continue
        line_box = target[1]
        twin = any(
            other is not element
            and other_index not in doomed
            and str(other.get("type")) in {"text", "button", "input"}
            and normalize_owner_text(other.get("text"))
            and owner_text_similarity(other.get("text"), element.get("text")) >= 0.85
            and _rect_contains(
                _layout_rect(other) or (0, 0, 0, 0), line_box, tolerance=12
            )
            for other_index, other in enumerate(elements)
        )
        if twin:
            doomed.add(index)
            repaired += 1
            continue
        width, height = box[2], box[3]
        new_x = int(round(line_box[0] + line_box[2] / 2 - width / 2))
        new_y = int(round(line_box[1] + line_box[3] / 2 - height / 2))
        element["x"], element["y"] = new_x, new_y
        moved = (new_x, new_y, width, height)
        rects[index] = moved
        _resample_fill(element, image_path, moved)
        repaired += 1
    if doomed:
        elements[:] = [
            element for index, element in enumerate(elements) if index not in doomed
        ]
    return repaired


def _resample_fill(
    element: dict[str, Any],
    image_path: str,
    box: tuple[int, int, int, int],
) -> None:
    """Take the fill colour from where the element now sits."""
    style = element.get("style")
    if not isinstance(style, dict) or not style.get("fillColor"):
        return
    from src.app.services.structure.image_contract import _dominant_color

    try:
        colour = _dominant_color(image_path, list(box))
    except Exception:  # noqa: BLE001 - a colour hint must never break the build
        return
    if colour:
        style["fillColor"] = colour


#: A patch behind bare text has to differ from the text's own surface by this
#: much before it counts as a badge rather than the card the text sits on.
BACKDROP_FILL_DELTA = 18
#: A hairline is fainter than a fill: an empty search box is white on white
#: with a #e0e0e0 edge, which is a 30-channel step but only one pixel wide.
BACKDROP_EDGE_DELTA = 10
#: How far the sampling walks out from a text box looking for its edge.
BACKDROP_MAX_PAD = 32
#: A chip closes on every side; fewer edges is a neighbour, not a chip.
BACKDROP_MIN_SIDES = 3
#: A chip hugs its words.  A container's border sits further out than this, and
#: a box that reaches it is the card, not a badge.  A button is the widest chip
#: there is: 登录 is two glyphs in a 98px pill, so 23px of padding per side is
#: still a control and not a panel.
BACKDROP_MAX_PAD_PER_SIDE = 32
BACKDROP_MAX_TOTAL_PAD = 96
#: Share of a side's pixels that has to leave the fill before it is an edge.
BACKDROP_EDGE_SHARE = 0.6
#: A patch larger than this share of the canvas is a surface, not a badge.
BACKDROP_MAX_AREA_SHARE = 0.25


def _frame_colour(image, box: tuple[int, int, int, int], inset: int) -> tuple[int, int, int]:
    """Median colour of a 2px frame drawn ``inset`` pixels inside ``box``."""
    import numpy as np

    x, y, width, height = box
    left, top = x + inset, y + inset
    right, bottom = x + width - inset, y + height - inset
    if right - left < 2 or bottom - top < 2:
        left, top, right, bottom = x, y, x + width, y + height
    chunks = [
        image[top : top + 2, left:right],
        image[max(top, bottom - 2) : bottom, left:right],
        image[top:bottom, left : left + 2],
        image[top:bottom, max(left, right - 2) : right],
    ]
    pool = np.concatenate([chunk.reshape(-1, 3) for chunk in chunks if chunk.size])
    median = np.median(pool, axis=0)
    return (int(median[0]), int(median[1]), int(median[2]))


def _walk_to_edge(image, fill, box, side: str, limit: int) -> tuple[int, int] | None:
    """First distance out of ``box`` on ``side`` whose colour leaves ``fill``."""
    import numpy as np

    x, y, width, height = box
    for step in range(1, limit + 1):
        if side == "left":
            band = image[y : y + height, max(0, x - step) : max(0, x - step) + 1]
        elif side == "right":
            band = image[y : y + height, x + width + step - 1 : x + width + step]
        elif side == "top":
            band = image[max(0, y - step) : max(0, y - step) + 1, x : x + width]
        else:
            band = image[y + height + step - 1 : y + height + step, x : x + width]
        if band.size == 0:
            return None
        distance = np.abs(band.reshape(-1, 3) - np.asarray(fill, dtype=np.int16)).max(axis=1)
        if int(distance.max()) >= BACKDROP_EDGE_DELTA:
            column = band.reshape(-1, 3)[int(distance.argmax())]
            return step, 0, 0, 0  # placeholder, colour read by the caller
    return None


def _recover_text_backdrops(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
) -> int:
    """Give bare text the badge, pill or button it is printed on.

    A plan describes words, not the coloured chips behind them: the green 库位
    tag, the red 模型广场 tab, the black 推荐/登录 buttons, the white 看详情
    button all arrive as plain text on whatever surface happens to be there.
    The pixels know the chip — it ends a few pixels from the words, and what is
    outside it is a different colour.

    Walk out from each text box until the colour leaves the text's own surface.
    A step of 18 or more is a fill; a step between 10 and 18 is a hairline, which
    is how an empty input on a white card shows up at all.
    """
    import numpy as np
    from PIL import Image

    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    if image.ndim != 3:
        return 0
    canvas_area = max(1, width * height)

    from src.app.services.structure.fidelity.pixel_probe import estimate_corner_radius

    def hex_of(colour: tuple[int, int, int]) -> str:
        return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, value)) for value in colour])

    # Surfaces already described by a filled element: no chip to add.
    existing: list[tuple[tuple[int, int, int, int], str]] = []
    for element in elements:
        style = element.get("style")
        if not isinstance(style, dict):
            continue
        fill = str(style.get("fillColor") or "")
        box = _layout_rect(element)
        if fill and box is not None:
            existing.append((box, fill.lower()))

    out: list[dict[str, Any]] = []
    added = 0
    for element in elements:
        out.append(element)
        if str(element.get("type")) != "text" or not element.get("text"):
            continue
        box = _layout_rect(element)
        if box is None or box[2] < 2 or box[3] < 2:
            continue
        x, y, box_width, box_height = box
        fill = _frame_colour(image, box, inset=2)
        if fill == (0, 0, 0) and image[y : y + 1, x : x + 1].size == 0:
            continue

        edges: dict[str, int] = {}
        border_samples: list[tuple[int, int, int]] = []
        for side in ("left", "right", "top", "bottom"):
            for step in range(1, BACKDROP_MAX_PAD + 1):
                if side == "left":
                    band = image[y : y + box_height, max(0, x - step) : max(0, x - step) + 1]
                elif side == "right":
                    band = image[y : y + box_height, x + box_width + step - 1 : x + box_width + step]
                elif side == "top":
                    band = image[max(0, y - step) : max(0, y - step) + 1, x : x + box_width]
                else:
                    band = image[y + box_height + step - 1 : y + box_height + step, x : x + box_width]
                if band.size == 0:
                    break
                pixels = band.reshape(-1, 3)
                distance = np.abs(pixels - np.asarray(fill, dtype=np.int16)).max(axis=1)
                strong = np.where(distance >= BACKDROP_EDGE_DELTA)[0]
                # An edge spans the side.  A handful of antialiased pixels at
                # the rim of the fill are not the chip ending — without this the
                # walk stops 1-4px out, on the glyph's own fringe.
                if strong.size < max(2, int(pixels.shape[0] * BACKDROP_EDGE_SHARE)):
                    continue
                edges[side] = step
                border_samples.append(tuple(int(value) for value in pixels[strong[0]]))
                break

        # A chip closes around its words on every side.  Two edges are a text
        # sitting next to a badge or above a rule, and building a box for that
        # paints a strip across the row.
        if len(edges) < BACKDROP_MIN_SIDES:
            continue
        if max(edges.values()) > BACKDROP_MAX_PAD_PER_SIDE:
            continue
        if sum(edges.values()) > BACKDROP_MAX_TOTAL_PAD:
            continue
        left = x - edges.get("left", 0)
        top = y - edges.get("top", 0)
        right = x + box_width + edges.get("right", 0)
        bottom = y + box_height + edges.get("bottom", 0)
        patch = (
            max(0, left),
            max(0, top),
            max(1, min(width, right) - max(0, left)),
            max(1, min(height, bottom) - max(0, top)),
        )
        if patch[2] * patch[3] > canvas_area * BACKDROP_MAX_AREA_SHARE:
            continue
        # What is beyond the edge has to be a different colour, or the "chip"
        # is just the surface the words were already printed on (a dark title
        # on a dark page found its own gradient and made a dark rectangle).
        beyond: list[tuple[int, int, int]] = []
        for side in edges:
            sample = {
                "left": (
                    slice(max(0, patch[1]), patch[1] + patch[3]),
                    slice(max(0, patch[0] - 3), max(0, patch[0])),
                ),
                "right": (
                    slice(patch[1], patch[1] + patch[3]),
                    slice(patch[0] + patch[2], patch[0] + patch[2] + 3),
                ),
                "top": (
                    slice(max(0, patch[1] - 3), max(0, patch[1])),
                    slice(patch[0], patch[0] + patch[2]),
                ),
                "bottom": (
                    slice(patch[1] + patch[3], patch[1] + patch[3] + 3),
                    slice(patch[0], patch[0] + patch[2]),
                ),
            }[side]
            chunk = image[sample]
            if chunk.size:
                beyond.append(tuple(int(value) for value in np.median(chunk.reshape(-1, 3), axis=0)))
        if beyond:
            outside = tuple(
                int(np.median([sample[channel] for sample in beyond]))
                for channel in range(3)
            )
            if max(abs(one - two) for one, two in zip(fill, outside)) < BACKDROP_FILL_DELTA:
                continue
        # Something already paints this surface — a button, a card, a chip that
        # the plan did describe.  Adding a second one would only stack paint.
        if any(
            _rect_contains(box_, patch, tolerance=3)
            and _same_fill(fill_, hex_of(fill), 6)
            for box_, fill_ in existing
        ):
            continue

        border_hex = ""
        if border_samples:
            median = tuple(
                int(np.median([sample[channel] for sample in border_samples]))
                for channel in range(3)
            )
            step = max(
                abs(one - two) for one, two in zip(median, fill)
            )
            if BACKDROP_EDGE_DELTA <= step <= 120:
                border_hex = hex_of(median)
        patch_hex = hex_of(fill)
        if not border_hex and _same_fill(patch_hex, "", 0):
            continue

        digest = hashlib.sha1(
            f"{patch[0]}:{patch[1]}:{patch[2]}:{patch[3]}:{patch_hex}".encode("utf-8")
        ).hexdigest()[:16]
        style: dict[str, Any] = {"fillColor": patch_hex}
        if border_hex:
            style["borderColor"] = border_hex
            style["borderWidth"] = 1
        radius = 0
        try:
            radius = int(estimate_corner_radius(image, patch) or 0)
        except Exception:  # noqa: BLE001 - a radius hint must never break a build
            radius = 0
        if radius:
            style["borderRadius"] = radius
        out.insert(
            len(out) - 1,
            {
                "id": f"backdrop:{digest}",
                "type": "container",
                "x": patch[0],
                "y": patch[1],
                "width": patch[2],
                "height": patch[3],
                "text": "",
                "style": style,
                "role": "text-backdrop",
                "name": "Text backdrop",
                "contentRef": f"backdrop:{digest}",
                "sceneOwnerId": f"backdrop:{digest}",
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "text-backdrop",
                    "grouping_status": "recovered",
                },
            },
        )
        # Only a word that fits inside its chip is that chip's label.  A long
        # row label that merely starts on one keeps its own reading and stays
        # subject to the duplicate pass — otherwise it printed white words
        # across the row.
        span_left, span_right = _rendered_span(element)
        if span_right - span_left <= patch[2] * 1.3:
            element["badgeLabel"] = True
        added += 1
    if added:
        elements[:] = out
    return added


#: Recovered marks: a logo is wider than an icon but still a mark, not a panel,
#: and a stamp around a price is wider still.
VISUAL_MIN_SIDE = 12
VISUAL_MAX_WIDTH = 260
VISUAL_MAX_HEIGHT = 120
#: How far a glyph's antialiased edge may sit from the label's own colour and
#: still be that label's ink.
VISUAL_INK_TOLERANCE = 60
VISUAL_MIN_FILL = 0.25
VISUAL_MAX_FILL = 0.97
VISUAL_MIN_CONTRAST = 24
VISUAL_MAX_REGIONS = 10


def _overlap_share(
    box: tuple[int, int, int, int],
    other: tuple[int, int, int, int],
) -> float:
    """Share of ``box`` covered by ``other``."""
    width = min(box[0] + box[2], other[0] + other[2]) - max(box[0], other[0])
    height = min(box[1] + box[3], other[1] + other[3]) - max(box[1], other[1])
    if width <= 0 or height <= 0:
        return 0.0
    return (width * height) / max(1, box[2] * box[3])


#: A card can be three channels away from the page it sits on: marketplace's
#: #161618 on #0d0d0f, AtomGit's #fdf6f5 on #ffffff.  Six is the floor where a
#: difference is real and no longer compression noise.
SOFT_PANEL_MIN_DELTA = 6
#: A page can be a gradient.  Eight bands follow it closely enough that the
#: step between neighbours is under the eye's threshold.
PAGE_BANDS = 8
#: 四边中位色相差超过这个值，说明它们属于两个不同的面，不能取平均。
PAGE_EDGE_SPLIT = 8
#: 分带底色与声明的页底色差小于这个值时，这条带子什么也没画，只是接缝。
#: 取 6 而不是 10：wecom 的页底声明 #666666、实到 #5d6064，差 9 个通道——
#: 在中灰上这已经看得见，按 10 放过它时 within15 掉了 1.4 个点。
PAGE_BAND_MIN_DELTA = 6
#: A solid container that stops short of its own paint: how far to follow
#: colour continuity, and how much of a row has to agree before it counts.
CONTAINER_GROW_MAX = 32
#: A card's box is routinely a few pixels short of its own paint; the cap is
#: smaller than the page chrome's because a card has neighbours close by.
CONTAINER_GROW_CARD_MAX = 16
#: A card's own rows carry words, so 90% of a row is never the card's colour.
#: Half is enough to tell "still this card" from "the page underneath".
CONTAINER_GROW_CARD_SHARE = 0.5
CONTAINER_GROW_TOLERANCE = 12
CONTAINER_GROW_SHARE = 0.9
#: Consecutive off-colour rows a growth may step over (an antialiased seam).
CONTAINER_GROW_BRIDGE = 2
#: A solid panel fills its own box.  A line of text covers half of it at most,
#: which is what keeps this from recovering every word as a card.
SOFT_PANEL_MIN_FILL = 0.9
#: An outline-only box (an empty input) fills nothing; its *border* closes the
#: box instead, so the share of the bbox perimeter that is drawn is the test.
SOFT_PANEL_MIN_EDGE = 0.8
SOFT_PANEL_MIN_WIDTH = 24
SOFT_PANEL_MIN_HEIGHT = 16
SOFT_PANEL_MIN_AREA = 800
#: Never the page itself: a blob that covers most of the canvas is the ground.
SOFT_PANEL_MAX_SHARE = 0.5
#: Already described by a filled element or a picture: nothing to add.
SOFT_PANEL_EXISTING_IOA = 0.7
SOFT_PANEL_MAX_REGIONS = 24


def _panel_edge_share(mask, box: tuple[int, int, int, int]) -> float:
    """Share of a box's one-pixel perimeter that is painted."""
    import numpy as np

    x, y, width, height = box
    if width < 3 or height < 3:
        return 0.0
    top = mask[y, x : x + width]
    bottom = mask[y + height - 1, x : x + width]
    left = mask[y : y + height, x]
    right = mask[y : y + height, x + width - 1]
    sides = np.concatenate([top, bottom, left, right])
    return float(sides.mean()) if sides.size else 0.0


def _already_painted(
    box: tuple[int, int, int, int],
    fill: str,
    covered: Sequence[tuple[tuple[int, int, int, int], str]],
) -> bool:
    """Whether an existing filled box already paints this patch in this colour.

    Geometry alone is not enough: the sidebar paints #364150 across its whole
    height, and the cyan highlight inside it is a *different* element that the
    plan never had.  Covering is only "already there" when the colour agrees.
    """
    for other, other_fill in covered:
        share = _overlap_share(box, other)
        if share < SOFT_PANEL_EXISTING_IOA:
            continue
        if not other_fill:
            # A picture: its pixels are the answer, not a fill.
            if share >= 0.5:
                return True
            continue
        if not fill or _same_fill(fill, other_fill, SOFT_PANEL_MIN_DELTA):
            return True
    return False


#: A block of one flat colour is a button, a highlight, a chip.  It has to be
#: big enough to be a block and opaque enough to fill its own box; words never
#: do either.
COLOUR_REGION_MIN_PIXELS = 600
COLOUR_REGION_MIN_FILL = 0.9
COLOUR_REGION_MIN_SIDE = 14
COLOUR_REGION_MAX_SHARE = 0.35
COLOUR_REGION_TOLERANCE = 10
COLOUR_REGION_MIN_SAMPLES = 2500
#: Capsules and rounded chips: wide, short, filled except where the corners are
#: rounded away.  The fill band sits strictly below the solid pass's 0.90 so the
#: two recoveries never claim the same region.
PILL_MIN_WIDTH = 24
PILL_MAX_WIDTH = 420
PILL_MIN_HEIGHT = 14
PILL_MAX_HEIGHT = 96
PILL_MIN_FILL = 0.60
PILL_MAX_FILL = 0.94
PILL_CORNER_TOLERANCE = 12
PILL_MIN_CONTRAST = 8
PILL_MAX_REGIONS = 20
COLOUR_REGION_MAX = 40


def _recover_colour_regions(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    background: str,
) -> int:
    """Recover flat blocks of one colour that the plan never described.

    Thresholding against the page merges everything into one blob: the sidebar,
    the highlighted menu row inside it and the badge on top of that are one
    component because they all differ from the page.  Segmenting *per colour*
    separates them, and a fill that occupies more than 90% of its own bounding
    box is a block — a button, a highlight bar, a chip — while text covers less
    than half of its box and is dropped without a second thought.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return 0
    try:
        import cv2
    except Exception:  # pragma: no cover - opencv is a pipeline dependency
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    if image.ndim != 3:
        return 0
    image = image[:height, :width]
    page = np.asarray(_hex_rgb(background), dtype=np.int16) if background else None

    quantised = (image // 12).astype(np.int32)
    keys = quantised[:, :, 0] * 4096 + quantised[:, :, 1] * 64 + quantised[:, :, 2]
    values, counts = np.unique(keys.reshape(-1), return_counts=True)
    order = np.argsort(counts)[::-1]
    colours: list[tuple[int, int, int]] = []
    for position in order[:24]:
        if int(counts[position]) < COLOUR_REGION_MIN_SAMPLES:
            break
        key = int(values[position])
        sample = image.reshape(-1, 3)[keys.reshape(-1) == key]
        colour = tuple(int(value) for value in np.median(sample, axis=0))
        if page is not None and max(
            abs(one - two) for one, two in zip(colour, tuple(page))
        ) < SOFT_PANEL_MIN_DELTA:
            continue
        colours.append(colour)

    covered: list[tuple[tuple[int, int, int, int], str]] = []
    for element in elements:
        box = _layout_rect(element)
        if box is None:
            continue
        fill = _solid_fill(element)
        if fill:
            covered.append((box, fill))
        elif element.get("imageBase64"):
            covered.append((box, ""))

    canvas_area = max(1, width * height)
    found: list[tuple[int, tuple[int, int, int, int], str]] = []
    for colour in colours:
        target = np.asarray(colour, dtype=np.int16)
        mask = (
            np.abs(image - target).max(axis=2) <= COLOUR_REGION_TOLERANCE
        ).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            x, y, box_width, box_height, area = (
                int(value) for value in stats[index, :5]
            )
            if area < COLOUR_REGION_MIN_PIXELS:
                continue
            if box_width < COLOUR_REGION_MIN_SIDE or box_height < COLOUR_REGION_MIN_SIDE:
                continue
            if box_width * box_height > canvas_area * COLOUR_REGION_MAX_SHARE:
                continue
            if area / max(1, box_width * box_height) < COLOUR_REGION_MIN_FILL:
                continue
            found.append(
                (
                    area,
                    (x, y, box_width, box_height),
                    "#{:02x}{:02x}{:02x}".format(*colour),
                )
            )
    if not found:
        return 0
    found.sort(key=lambda item: item[0], reverse=True)
    added = 0
    for _area, box, fill in found:
        if added >= COLOUR_REGION_MAX:
            break
        if _already_painted(box, fill, covered):
            continue
        if any(_iou(box, other) >= 0.8 for other, _fill in covered):
            continue
        digest = hashlib.sha1(
            f"{box[0]}:{box[1]}:{box[2]}:{box[3]}:{fill}".encode("utf-8")
        ).hexdigest()[:16]
        elements.append(
            {
                "id": f"block:{digest}",
                "type": "container",
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "text": "",
                "style": {"fillColor": fill},
                "role": "panel",
                "name": "Colour block",
                "contentRef": f"block:{digest}",
                "sceneOwnerId": f"block:{digest}",
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "panel",
                    "grouping_status": "recovered",
                },
            }
        )
        covered.append((box, fill))
        added += 1
    return added


def _recover_pill_shapes(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    background: str,
) -> int:
    """Recover the capsules and rounded chips that carry words.

    The solid-panel pass requires a block to fill 90% of its own box, which is
    exactly what a capsule does not do: its four corners are rounded away, so it
    lands at 0.80-0.90 and is dropped.  That is how a nav item loses its pill and
    ends up as words lying directly on the page.

    The shape is what identifies it, and the shape is measurable:

    * all four corner patches are *not* the colour (roundness), while
    * the left and right mid-edge are the colour (it spans the full width).

    A line of text fails the second test; a square block fails the first.  The
    fill share sits between the solid pass's 0.90 and a bare block, so the two
    passes cannot both claim the same region.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return 0
    try:
        import cv2
    except Exception:  # pragma: no cover - opencv is a pipeline dependency
        return 0
    if not background:
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    if image.ndim != 3:
        return 0
    image = image[:height, :width]
    page = np.asarray(_hex_rgb(background), dtype=np.int16)

    quantised = (image // 12).astype(np.int32)
    keys = quantised[:, :, 0] * 4096 + quantised[:, :, 1] * 64 + quantised[:, :, 2]
    values, counts = np.unique(keys.reshape(-1), return_counts=True)
    order = np.argsort(counts)[::-1]

    covered: list[tuple[tuple[int, int, int, int], str]] = []
    for element in elements:
        box = _layout_rect(element)
        if box is None:
            continue
        fill = _solid_fill(element)
        if fill:
            covered.append((box, fill))
        elif element.get("imageBase64"):
            covered.append((box, ""))

    found: list[tuple[int, tuple[int, int, int, int], str, int]] = []
    for position in order[:24]:
        if int(counts[position]) < COLOUR_REGION_MIN_SAMPLES:
            break
        key = int(values[position])
        sample = image.reshape(-1, 3)[keys.reshape(-1) == key]
        colour = tuple(int(value) for value in np.median(sample, axis=0))
        if max(abs(one - two) for one, two in zip(colour, tuple(page))) < PILL_MIN_CONTRAST:
            continue
        target = np.asarray(colour, dtype=np.int16)
        mask = (np.abs(image - target).max(axis=2) <= COLOUR_REGION_TOLERANCE).astype(
            np.uint8
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            x, y, box_width, box_height, area = (int(value) for value in stats[index, :5])
            if not (PILL_MIN_WIDTH <= box_width <= PILL_MAX_WIDTH):
                continue
            if not (PILL_MIN_HEIGHT <= box_height <= PILL_MAX_HEIGHT):
                continue
            share = area / max(1, box_width * box_height)
            if not (PILL_MIN_FILL <= share <= PILL_MAX_FILL):
                continue
            if not _pill_corners_rounded(image, (x, y, box_width, box_height), target):
                continue
            if not _pill_spans_width(image, (x, y, box_width, box_height), target):
                continue
            radius = _pill_radius(image, (x, y, box_width, box_height), target, box_height)
            found.append(
                (
                    area,
                    (x, y, box_width, box_height),
                    "#{:02x}{:02x}{:02x}".format(*colour),
                    radius,
                )
            )

    if not found:
        return 0
    found.sort(key=lambda item: item[0], reverse=True)
    added = 0
    for _area, box, fill_hex, radius in found[:PILL_MAX_REGIONS]:
        if _already_painted(box, fill_hex, covered):
            continue
        digest = hashlib.sha1(
            f"pill:{box[0]}:{box[1]}:{box[2]}:{box[3]}:{fill_hex}".encode("utf-8")
        ).hexdigest()[:16]
        elements.append(
            {
                "id": f"pill:{digest}",
                "type": "container",
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "text": "",
                "style": {"fillColor": fill_hex, "borderRadius": radius},
                "role": "panel",
                "name": "Pill",
                "contentRef": f"pill:{digest}",
                "sceneOwnerId": f"pill:{digest}",
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "panel",
                    "grouping_status": "recovered",
                },
            }
        )
        covered.append((box, fill_hex))
        added += 1
    return added


def _pill_corners_rounded(image, box, target) -> bool:
    """All four corners are off-colour: the rectangle has been rounded."""
    import numpy as np

    x, y, box_width, box_height = box
    if box_width < 10 or box_height < 8:
        return False
    corners = (
        (x + 1, y + 1),
        (x + box_width - 4, y + 1),
        (x + 1, y + box_height - 4),
        (x + box_width - 4, y + box_height - 4),
    )
    for left, top in corners:
        patch = image[top : top + 3, left : left + 3]
        if patch.size == 0:
            return False
        if np.abs(patch - target).max(axis=2).min() <= PILL_CORNER_TOLERANCE:
            # A corner still holds the fill: a square block, not a capsule.
            return False
    return True


def _pill_spans_width(image, box, target) -> bool:
    """The left and right mid-edge carry the fill: it runs the full width."""
    import numpy as np

    x, y, box_width, box_height = box
    middle = y + box_height // 2
    for column in (x + 1, x + box_width - 2):
        patch = image[middle - 1 : middle + 2, column : column + 1]
        if patch.size == 0:
            return False
        if np.abs(patch - target).max(axis=2).min() > COLOUR_REGION_TOLERANCE:
            return False
    return True


def _pill_radius(image, box, target, box_height: int) -> int:
    """Corner inset measured on the top row: how far in the fill starts."""
    import numpy as np

    x, y, box_width, _box_height = box
    row = image[y + 1, x : x + box_width]
    if row.size == 0:
        return max(2, min(box_height // 2, 8))
    inside = np.abs(row - target).max(axis=1) <= COLOUR_REGION_TOLERANCE
    if not inside.any():
        return max(2, min(box_height // 2, 8))
    inset = int(np.argmax(inside))
    return int(max(2, min(box_height // 2, inset, 24)))


def _reflow_key(text: str) -> str:
    """Words comparable across OCR and the model, punctuation included.

    OCR prints a half-width colon where the model wrote a full-width one, so the
    punctuation is folded as well; everything else is the fold the duplicate
    passes already use.  Whitespace is dropped: a line break is exactly what is
    being reconstructed.
    """
    folded = _tail_key({"text": text})
    return folded.translate(
        str.maketrans({"：": ":", "，": ",", "。": ".", "；": ";", "（": "(", "）": ")", "、": ","})
    )


def _reflow_paragraphs(
    elements: list[dict[str, Any]],
    ocr_observations: Sequence[Mapping[str, Any]] | None,
    image_path: str | Path | None = None,
    background: str | None = None,
) -> int:
    """Give a paragraph back the lines the picture actually has.

    The plan models a card's description as one string in a one-line-tall box.
    The picture wraps that string over two lines, so the browser prints one long
    line, the patch pass fills the second line with a picture of it, and Figma —
    which wraps inside the box — draws two lines on top of each other.  Three
    renderers, three wrong answers, one cause: nobody went back to the OCR lines.

    This pass does, and only when the lines agree with the node's own words: the
    seed line has to overlap the box, the chain has to grow downwards in the same
    horizontal band, and the joined text has to match the node at
    ``PARAGRAPH_REFLOW_MIN_SIMILARITY``.  The node keeps the model's wording —
    the OCR lines only say *where* to break it — because OCR misreads characters
    ("Al" for "AI") and the model does not.
    """
    if not ocr_observations:
        return 0
    # A column of page colour between two blocks is the geometry that says they
    # are not the same paragraph.  Read from the picture, so a three-column table
    # or a single centred card behaves the same way.
    picture = None
    if image_path and background:
        try:
            import numpy as _np
            from PIL import Image as _Image

            picture = _np.asarray(_Image.open(image_path).convert("RGB"), dtype=_np.int16)
        except (OSError, ValueError):
            picture = None

    def _separated(one: Sequence[int], two: Sequence[int]) -> bool:
        if picture is None or not background:
            return False
        from src.app.services.structure.fidelity.pixel_probe import separated_by_page

        return separated_by_page(picture, str(background), one, two)
    import numpy as np

    lines = []
    for observation in ocr_observations:
        box = observation.get("bbox")
        text = str(observation.get("text") or "").strip()
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            x, y, w, h = (float(value) for value in box)
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        lines.append({"text": text, "key": _reflow_key(text), "box": (x, y, w, h)})
    if not lines:
        return 0

    reflowed = 0
    for element in elements:
        if element.get("type") != "text" or not element.get("text"):
            continue
        if element.get("lines"):
            continue
        style = element.get("style") or {}
        size = float(style.get("fontSize") or 0)
        height = float(element.get("height") or 0)
        if size <= 0 or height <= 0 or height > size * 1.7:
            continue
        node_key = _reflow_key(str(element.get("text") or ""))
        if len(node_key) < PARAGRAPH_REFLOW_MIN_CHARS:
            continue
        box = _layout_rect(element)
        if box is None:
            continue
        seed = _reflow_seed(lines, box, node_key)
        if seed is None:
            continue
        chain = _reflow_chain(lines, seed, box, node_key, separated=_separated)
        if len(chain) < 2:
            continue
        joined = "".join(line["key"] for line in chain)
        from difflib import SequenceMatcher

        if SequenceMatcher(None, joined, node_key).ratio() < PARAGRAPH_REFLOW_MIN_SIMILARITY:
            continue
        counts = [len(line["key"]) for line in chain]
        parts = _split_by_lengths(str(element.get("text") or ""), counts)
        if len(parts) < 2 or not all(parts):
            continue
        left = min(line["box"][0] for line in chain)
        top = min(line["box"][1] for line in chain)
        right = max(line["box"][0] + line["box"][2] for line in chain)
        bottom = max(line["box"][1] + line["box"][3] for line in chain)
        pitches = [
            chain[index + 1]["box"][1] - chain[index]["box"][1]
            for index in range(len(chain) - 1)
        ]
        pitch = float(np.median(pitches)) if pitches else float(height)
        element["x"] = round(left, 1)
        element["y"] = round(top, 1)
        element["width"] = round(right - left, 1)
        element["height"] = round(bottom - top, 1)
        element["lines"] = parts
        element["lineHeight"] = round(pitch, 1)
        element["lineHeightPolicy"] = "observed"
        element["textAnchor"] = "start"
        element["reflowEvidence"] = {
            "method": "ocr-lines",
            "lines": len(chain),
            "pitch": round(pitch, 1),
            "similarity": round(
                SequenceMatcher(None, joined, node_key).ratio(), 3
            ),
        }
        reflowed += 1
    return reflowed


def _reflow_seed(
    lines: Sequence[Mapping[str, Any]],
    box: tuple[int, int, int, int],
    node_key: str,
) -> Mapping[str, Any] | None:
    """The OCR line this node starts on: over the box's first line, first words agree."""
    x, y, w, h = box
    best = None
    best_score = 0.0
    for line in lines:
        lx, ly, lw, lh = line["box"]
        if ly > y + h * 0.8:
            continue
        if ly + lh < y + h * 0.2:
            continue
        overlap = min(x + w, lx + lw) - max(x, lx)
        if overlap < min(w, lw) * PARAGRAPH_REFLOW_BAND_SHARE:
            continue
        key = str(line["key"])
        if not key or not node_key.startswith(key[: max(4, len(key) // 2)]):
            continue
        score = len(key) / max(1, len(node_key))
        if score > best_score:
            best = line
            best_score = score
    return best


def _reflow_chain(
    lines: Sequence[Mapping[str, Any]],
    seed: Mapping[str, Any],
    box: tuple[int, int, int, int],
    node_key: str,
    separated: Any = None,
) -> list[Mapping[str, Any]]:
    """Follow the seed downwards while the lines still spell the node's words.

    Geometry alone would happily eat the meta row under the paragraph ("TSX ·
    4 小时前"), so every step also has to be the next piece of the sentence:
    the remaining text must start with the candidate's words.  That is what
    makes the chain stop at the paragraph's last line instead of the card's.
    """
    x, _y, w, _h = box
    chain = [seed]
    cursor = seed
    consumed = len(str(seed["key"]))
    while consumed < len(node_key) and len(chain) < PARAGRAPH_REFLOW_MAX_LINES:
        current_bottom = cursor["box"][1] + cursor["box"][3]
        remaining = node_key[consumed:]
        candidates = []
        for line in lines:
            if line in chain:
                continue
            lx, ly, lw, lh = line["box"]
            gap = ly - current_bottom
            if gap < -cursor["box"][3] * 0.4 or gap > cursor["box"][3] * PARAGRAPH_REFLOW_MAX_GAP:
                continue
            overlap = min(x + w, lx + lw) - max(x, lx)
            if overlap < lw * PARAGRAPH_REFLOW_BAND_SHARE:
                continue
            # Two columns of a layout are not one paragraph, whatever the words
            # say: a strip of page between them is enough to say no.
            if separated is not None and separated(cursor["box"], line["box"]):
                continue
            candidates.append((gap, line))
        if not candidates:
            break
        candidates.sort(key=lambda item: item[0])
        picked = None
        for _gap, line in candidates:
            key = str(line["key"])
            if key and remaining.startswith(key):
                picked = line
                break
        if picked is None:
            # The last line of the picture may hold more than the model wrote;
            # accept it when the remaining words are its prefix.
            for _gap, line in candidates:
                key = str(line["key"])
                if key and len(remaining) >= 4 and key.startswith(remaining[: max(4, len(remaining) - 2)]):
                    picked = line
                    break
        if picked is None:
            break
        chain.append(picked)
        cursor = picked
        consumed += len(str(picked["key"]))
    return chain


def _split_by_lengths(text: str, counts: Sequence[int]) -> list[str]:
    """Cut the model's own words at the character counts the picture used."""
    parts: list[str] = []
    position = 0
    consumed = 0
    start = 0
    for index, limit in enumerate(counts):
        last = index == len(counts) - 1
        target = consumed + limit
        while position < len(text) and (last or consumed < target):
            char = text[position]
            position += 1
            if not char.isspace():
                consumed += 1
        parts.append(text[start:position].strip())
        start = position
    return parts


def _recover_page_fill(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    background: str,
) -> bool:
    """Paint the canvas in the colours the screenshot's own margins are.

    The plan declares a page colour, and a page is not always that colour:
    review's ground is a pale blue gradient declared #fefefe, so every pixel
    outside a card was 34 channels off and no rule downstream could see it —
    the fill was "correct" by declaration.  The margin of the picture is the
    only witness that cannot be wrong.

    One rect would flatten the gradient into a step, so the ground is laid down
    in horizontal bands, each sampling its own margins.  A page that really is
    one colour produces identical bands and costs nothing.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return False
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return False
    if image.ndim != 3:
        return False
    image = image[:height, :width]
    edges = [
        image[0:4].reshape(-1, 3),
        image[max(0, height - 4) : height].reshape(-1, 3),
        image[:, 0:4].reshape(-1, 3),
        image[:, max(0, width - 4) : width].reshape(-1, 3),
    ]
    medians = [np.median(edge, axis=0) for edge in edges if edge.size]
    if not medians:
        return False
    # The page is one colour on all four sides.  A sidebar or a dark header owns
    # one edge, and a page read off that edge paints the whole canvas wrong.
    agreeing = [
        median
        for median in medians
        if sum(
            1
            for other in medians
            if float(np.abs(median - other).max()) <= 24
        )
        >= 3
    ]
    if not agreeing:
        return False
    declared = tuple(int(value) for value in _hex_rgb(background)) if background else None
    spread = max(
        (
            float(np.abs(left - right).max())
            for left in agreeing
            for right in agreeing
        ),
        default=0.0,
    )
    if spread > PAGE_EDGE_SPLIT:
        # The four edges are two different surfaces, not one page: marketplace is
        # #1a1917 at top and bottom and #100f0d down both sides.  Averaging them
        # produced #151412 — a colour that matches the declared background, so the
        # whole calibration bailed out and the page kept its wrong base.  Vote
        # instead, and break a tie towards the side the declaration got wrong.
        votes = [
            (
                sum(
                    1
                    for other in agreeing
                    if float(np.abs(median - other).max()) <= PAGE_EDGE_SPLIT
                ),
                0.0
                if declared is None
                else float(np.abs(median - np.asarray(declared, dtype=np.float64)).max()),
                median,
            )
            for median in agreeing
        ]
        colour = tuple(
            int(value) for value in max(votes, key=lambda vote: (vote[0], vote[1]))[2]
        )
    else:
        colour = tuple(int(value) for value in np.median(agreeing, axis=0))
    hexed = "#{:02x}{:02x}{:02x}".format(*colour)
    if background and _same_fill(hexed, background, SOFT_PANEL_MIN_DELTA):
        return False

    # Bands: each one reads its own left and right margins — the page is what
    # shows at the edges — but only the margin pixels nothing else owns.  review
    # is the reason: its top band has a gradient on the left and a white card
    # touching the right edge, so the median of the two was a colour that exists
    # nowhere (#dee7fb against a truth of #f2f5fb).  Unowned interior pixels are
    # not the page either — on the bottom band they are mostly a card — so the
    # sample stays at the margins and simply excludes what has been painted.
    strip = max(4, min(24, width // 40))
    covered = np.zeros((height, width), dtype=bool)
    for element in elements:
        box = _layout_rect(element)
        if box is None:
            continue
        x, y, w, h = box
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(width, int(x + w)), min(height, int(y + h))
        if x1 <= x0 or y1 <= y0:
            continue
        if _solid_fill(element) or element.get("imageBase64"):
            covered[y0:y1, x0:x1] = True

    bands: list[tuple[int, int, str]] = []
    previous: tuple[int, int, int] | None = None
    for band in range(PAGE_BANDS):
        top = height * band // PAGE_BANDS
        bottom = height * (band + 1) // PAGE_BANDS
        if bottom - top < 2:
            continue
        sides: list[tuple[int, int, int]] = []
        for attempt in range(3):
            width_strip = strip * (2**attempt)
            for left_edge in (True, False):
                if left_edge:
                    crop = image[top:bottom, 0:width_strip]
                    free = covered[top:bottom, 0:width_strip]
                else:
                    crop = image[top:bottom, max(0, width - width_strip) : width]
                    free = covered[top:bottom, max(0, width - width_strip) : width]
                pixels = crop[~free]
                if pixels.size and pixels.reshape(-1, 3).shape[0] >= max(
                    24, (bottom - top) // 4
                ):
                    median = np.median(pixels.reshape(-1, 3), axis=0)
                    sides.append(tuple(int(value) for value in median))
            if sides:
                break
        if not sides:
            continue
        # Two margins that disagree are two different surfaces: one of them is a
        # card that reaches the edge.  Averaging them invents a colour, so the
        # band takes the side that continues the band above it.
        if len(sides) == 1:
            band_colour = sides[0]
        else:
            left_colour, right_colour = sides[0], sides[-1]
            if max(abs(a - b) for a, b in zip(left_colour, right_colour)) <= 8:
                band_colour = left_colour
            elif previous is not None:
                band_colour = min(
                    (left_colour, right_colour),
                    key=lambda colour: max(
                        abs(a - b) for a, b in zip(colour, previous)
                    ),
                )
            else:
                band_colour = left_colour
        previous = band_colour
        if declared is not None and max(
            abs(band_colour[index] - declared[index]) for index in range(3)
        ) < PAGE_BAND_MIN_DELTA:
            continue
        bands.append(
            (top, bottom, "#{:02x}{:02x}{:02x}".format(*band_colour))
        )
    if not bands:
        return False
    if len({colour for _top, _bottom, colour in bands}) == 1:
        bands = [(0, height, bands[0][2])]
    placed = 0
    for top, bottom, band_colour in bands:
        digest = hashlib.sha1(
            f"page:{band_colour}:{top}:{bottom}".encode("utf-8")
        ).hexdigest()[:16]
        elements.insert(
            placed,
            {
                "id": f"page:{digest}",
                "type": "container",
                "x": 0,
                "y": top,
                "width": width,
                "height": bottom - top,
                "text": "",
                "style": {"fillColor": band_colour},
                "role": "page-ground",
                "name": "Page ground",
                "contentRef": f"page:{digest}",
                "sceneOwnerId": f"page:{digest}",
                "zIndex": -2,
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "page-ground",
                    "grouping_status": "recovered",
                },
            },
        )
        placed += 1
    return True


def _extend_solid_edges(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    background: str,
) -> int:
    """Grow a solid container into the rows that are still its own colour.

    inventory's header is measured 64px tall and painted #2b3643, while the
    picture keeps that colour down to y=79: sixteen rows of a 2216-wide band
    rendered as page white, which is 82.8% of that sample's ground failures.  The
    plan measured the element, not the paint.

    Growth is bounded and colour-tested row by row, so it stops at the first row
    that is not the container's own colour.  Containers the same colour as the
    page are skipped: growing those would paint page into page.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    image = image[:height, :width]
    page = np.asarray(_hex_rgb(background), dtype=np.int16) if background else None

    grown = 0
    for element in elements:
        if element.get("type") != "container":
            continue
        # Page chrome only.  Growing a card was tried and reverted: marketplace's
        # two model cards overlap each other by 61px, so the guard refused them
        # and the growth did nothing, while inventory2 lost two frames to the
        # relaxation.  A card whose box is short of its paint needs the box fixed
        # at plan time, not a pass that guesses at its neighbour.
        role = str(element.get("role") or "")
        if role not in ("header", "sidebar", "main-content"):
            continue
        budget_max = CONTAINER_GROW_MAX
        share_min = CONTAINER_GROW_SHARE
        fill = _solid_fill(element)
        if not fill:
            continue
        colour = np.asarray(_hex_rgb(fill), dtype=np.int16)
        if page is not None and int(np.abs(colour - page).max()) < SOFT_PANEL_MIN_DELTA:
            continue
        try:
            x, y, w, h = (int(element[key]) for key in ("x", "y", "width", "height"))
        except (KeyError, TypeError, ValueError):
            continue
        if w < 40 or h < 16:
            continue
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        inner = image[y0 + 2 : max(y0 + 3, y1 - 2), x0 + 2 : max(x0 + 3, x1 - 2)]
        if inner.size == 0:
            continue
        if float((np.abs(inner - colour).max(axis=2) <= CONTAINER_GROW_TOLERANCE).mean()) < 0.6:
            continue

        def contiguity(getter, start: int, limit: int, step: int) -> int:
            """How far the colour continues, bridging a short seam.

            A single antialiased row at y=63 stops a naive walk one row into a
            sixteen-row band; two rows of slack step over the seam and the whole
            band comes back.
            """
            cursor = start
            misses = 0
            furthest = start
            budget = budget_max + CONTAINER_GROW_BRIDGE
            while 0 <= cursor < limit and abs(cursor - start) <= budget:
                line = getter(cursor)
                if line.size and float(
                    (np.abs(line - colour).max(axis=1) <= CONTAINER_GROW_TOLERANCE).mean()
                ) >= CONTAINER_GROW_SHARE:
                    furthest = cursor + step
                    misses = 0
                else:
                    misses += 1
                    if misses > CONTAINER_GROW_BRIDGE:
                        break
                cursor += step
            return furthest

        top = y0
        for _step in range(budget_max):
            if top <= 0:
                break
            row = image[top - 1, x0:x1]
            if float((np.abs(row - colour).max(axis=1) <= CONTAINER_GROW_TOLERANCE).mean()) < share_min:
                break
            top -= 1
        bottom = contiguity(lambda y: image[y, x0:x1], y1, height, 1)
        right = contiguity(lambda x: image[y0:max(y0 + 1, y1), x], x1, width, 1)
        left = x0
        for _step in range(budget_max):
            if left <= 0:
                break
            column = image[top:bottom, left - 1]
            if float((np.abs(column - colour).max(axis=1) <= CONTAINER_GROW_TOLERANCE).mean()) < share_min:
                break
            left -= 1
        if (top, bottom, left, right) == (y0, y1, x0, x1):
            continue
        # A frame owns its members' paint run: growing into one costs the frame.
        # wecom-modal lost two frames that way, so any frame that the new edge
        # would touch makes this container stay where it was measured.
        touches_frame = False
        for other in elements:
            if other is element or not other.get("layoutChildren"):
                continue
            ox, oy = int(other.get("x") or 0), int(other.get("y") or 0)
            ow, oh = int(other.get("width") or 0), int(other.get("height") or 0)
            # A frame that was already inside this container is its own child:
            # the card's inner button row overlaps every inset of the card, and
            # reading that as a collision kept every card at its measured box.
            inside_before = (
                ox >= x0 - 1 and oy >= y0 - 1
                and ox + ow <= x1 + 1 and oy + oh <= y1 + 1
            )
            if inside_before:
                continue
            if min(right, ox + ow) > max(left, ox) and min(bottom, oy + oh) > max(top, oy):
                touches_frame = True
                break
        if touches_frame:
            continue
        element["x"] = left
        element["y"] = top
        element["width"] = right - left
        element["height"] = bottom - top
        element["edgeEvidence"] = {
            "method": "colour-continuation",
            "grew": [top - y0, bottom - y1, left - x0, right - x1],
        }
        # The paint just moved, so its decoration has to be read again: a border
        # probe on the short box finds two sides out of four and gives up, which
        # is why the cards came out with no edge at all.
        from src.app.services.structure.fidelity.pixel_probe import (
            sample_container_decoration,
        )

        decoration = sample_container_decoration(
            image_path,
            (left, top, right - left, bottom - top),
            str(fill),
        )
        if decoration:
            element.setdefault("style", {}).update(decoration)
        grown += 1
    return grown


def _recover_soft_panels(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    background: str,
) -> int:
    """Recover the cards and input boxes that differ from the page only slightly.

    A card three channels away from its page is invisible to a threshold built
    for badges: marketplace's #161618 cards on #0d0d0f, AtomGit's #fdf6f5 cards
    on white, a 1px #ececec outline around an empty field.  Without them the
    render looks flat and scattered — text floating on the page instead of
    sitting in a panel.

    Two shapes qualify, and both are cheap to tell apart from text:

    * a solid panel fills its own box (>=90% of it), while a line of words
      covers half of its box at most;
    * an empty outline fills nothing but draws its whole perimeter, so the
      bbox edge share is what identifies it.
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return 0
    try:
        import cv2
    except Exception:  # pragma: no cover - opencv is a pipeline dependency
        return 0
    if not background:
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    if image.ndim != 3:
        return 0
    image = image[:height, :width]
    page = np.asarray(_hex_rgb(background), dtype=np.int16)
    mask = (np.abs(image - page).max(axis=2) >= SOFT_PANEL_MIN_DELTA).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))

    covered: list[tuple[tuple[int, int, int, int], str]] = []
    for element in elements:
        box = _layout_rect(element)
        if box is None:
            continue
        if str(element.get("type")) == "container" and _solid_fill(element):
            covered.append((box, _solid_fill(element)))
        elif element.get("imageBase64"):
            covered.append((box, ""))

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    canvas_area = max(1, width * height)
    candidates: list[tuple[int, tuple[int, int, int, int], str]] = []
    for index in range(1, count):
        x, y, box_width, box_height, area = (
            int(value) for value in stats[index, :5]
        )
        if box_width < SOFT_PANEL_MIN_WIDTH or box_height < SOFT_PANEL_MIN_HEIGHT:
            continue
        if area < SOFT_PANEL_MIN_AREA:
            continue
        if box_width * box_height > canvas_area * SOFT_PANEL_MAX_SHARE:
            continue
        box = (x, y, box_width, box_height)
        patch = image[y : y + box_height, x : x + box_width]
        share = area / max(1, box_width * box_height)
        if share >= SOFT_PANEL_MIN_FILL:
            # The fill is the colour most of the box actually is.
            fill = _dominant_colour(patch)
            if fill is None:
                continue
            if max(abs(one - two) for one, two in zip(fill, tuple(page))) < SOFT_PANEL_MIN_DELTA:
                continue
            candidates.append(
                (area, box, "#{:02x}{:02x}{:02x}".format(*fill))
            )
            continue
        # Outline-only: only worth it when the ring closes.
        if _panel_edge_share(mask, box) < SOFT_PANEL_MIN_EDGE:
            continue
        inner = patch[2:-2, 2:-2] if box_width > 6 and box_height > 6 else patch
        if inner.size == 0:
            continue
        fill = _dominant_colour(inner)
        ring = _dominant_colour(
            np.concatenate(
                [
                    patch[0:1].reshape(-1, 3),
                    patch[-1:].reshape(-1, 3),
                    patch[:, 0:1].reshape(-1, 3),
                    patch[:, -1:].reshape(-1, 3),
                ]
            )
        )
        if fill is None or ring is None:
            continue
        if max(abs(one - two) for one, two in zip(fill, tuple(page))) >= SOFT_PANEL_MIN_DELTA:
            # The interior is another colour, so this is a filled box with a
            # border, not an empty field; the solid branch above owns it.
            continue
        if max(abs(one - two) for one, two in zip(fill, ring)) < 18:
            continue
        candidates.append(
            (
                area,
                box,
                "#{:02x}{:02x}{:02x}".format(*fill),
                "#{:02x}{:02x}{:02x}".format(*ring),
            )
        )
    if not candidates:
        return 0
    candidates.sort(key=lambda item: item[0], reverse=True)
    added = 0
    for candidate in candidates[:SOFT_PANEL_MAX_REGIONS]:
        if len(candidate) == 3:
            _area, box, fill_hex = candidate
            border_hex = ""
        else:
            _area, box, fill_hex, border_hex = candidate
        if _already_painted(box, fill_hex, covered):
            continue
        digest = hashlib.sha1(
            f"{box[0]}:{box[1]}:{box[2]}:{box[3]}:{fill_hex}".encode("utf-8")
        ).hexdigest()[:16]
        style: dict[str, Any] = {"fillColor": fill_hex}
        if border_hex:
            style["borderColor"] = border_hex
            style["borderWidth"] = 1
        elements.append(
            {
                "id": f"panel:{digest}",
                "type": "container",
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "text": "",
                "style": style,
                "role": "panel",
                "name": "Panel",
                "contentRef": f"panel:{digest}",
                "sceneOwnerId": f"panel:{digest}",
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "panel",
                    "grouping_status": "recovered",
                },
            }
        )
        covered.append((box, fill_hex))
        added += 1
    return added


def _dominant_colour(patch) -> tuple[int, int, int] | None:
    """Median of the most common 16-level colour bin in a patch."""
    import numpy as np

    if patch is None or patch.size == 0:
        return None
    flat = patch.reshape(-1, 3)
    if flat.shape[0] < 4:
        return None
    quantised = (flat // 16).astype(np.int32)
    keys = quantised[:, 0] * 4096 + quantised[:, 1] * 64 + quantised[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    if values.size == 0:
        return None
    chosen = values[int(counts.argmax())]
    sample = flat[keys == chosen]
    return tuple(int(value) for value in np.median(sample, axis=0))


def _recover_visual_regions(
    elements: list[dict[str, Any]],
    image_path: str,
    width: int,
    height: int,
    observations: Sequence[Mapping[str, Any]] | None = None,
    background: str = "",
) -> int:
    """Cut out the marks nothing in the plan explains: icons, logos, stamps.

    Grounding reliably reports photos and avatars and just as reliably drops
    the brand mark in the corner, the 90px check badge and the tilted discount
    stamp around a price — they are neither text nor "image" in its vocabulary.

    The old rule was "never touch a word box", which also threw away every icon
    that stands next to a label: AtomCode's mark, the blue check in review.  The
    rule now is finer: erase the *ink* of known text — the pixels that carry the
    label's own colour, inside its own box — and keep everything else.  A red
    stamp frame around a price is not the price's ink, so the whole stamp
    survives; an icon beside a word is outside the glyphs, so it survives too.
    """
    import numpy as np
    from PIL import Image

    try:
        import cv2
    except Exception:  # pragma: no cover - opencv is a pipeline dependency
        return 0
    try:
        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    except (OSError, ValueError):
        return 0
    if image.ndim != 3:
        return 0
    image = image[:height, :width]
    page = np.asarray(_hex_rgb(background), dtype=np.int16) if background else None

    # Whole boxes that are already drawn as something else: a picture, a
    # control with its own fill, a chip, a recovered panel.
    explained: list[tuple[int, int, int, int]] = []
    for element in elements:
        kind = str(element.get("type") or "")
        role = str(element.get("role") or "")
        box = _layout_rect(element)
        if box is None:
            continue
        if kind in {"image", "button", "input"} or role in {
            "text-backdrop",
            "mark",
            "progress",
            "panel",
            "block",
            "page-ground",
            "patch",
        }:
            explained.append(box)

    # The ink of known text, pixel by pixel: the label's own colour, inside the
    # label's own box, dilated a little for antialiasing.  Everything the words
    # actually paint is erased; the icon standing next to them is not.
    ink = np.zeros(image.shape[:2], dtype=bool)
    for element in elements:
        if str(element.get("type")) != "text" or not element.get("text"):
            continue
        box = _layout_rect(element)
        if box is None:
            continue
        style = element.get("style") if isinstance(element.get("style"), dict) else {}
        colour = str(style.get("textColor") or "")
        left, top = max(0, box[0]), max(0, box[1])
        right = min(width, box[0] + box[2])
        bottom = min(height, box[1] + box[3])
        if right - left < 2 or bottom - top < 2:
            continue
        if _hex_rgb(colour) != (0, 0, 0) or colour.strip("#").lower() == "000000":
            distance = np.abs(
                image[top:bottom, left:right] - np.asarray(_hex_rgb(colour), dtype=np.int16)
            ).max(axis=2)
            ink[top:bottom, left:right] |= distance <= VISUAL_INK_TOLERANCE
        else:
            ink[top:bottom, left:right] = True
    if ink.any():
        ink = cv2.dilate(ink.astype(np.uint8), np.ones((3, 3), dtype=np.uint8)).astype(bool)

    reference = page
    if reference is None:
        border = np.concatenate(
            [
                image[0:2].reshape(-1, 3),
                image[max(0, height - 2) : height].reshape(-1, 3),
                image[:, 0:2].reshape(-1, 3),
                image[:, max(0, width - 2) : width].reshape(-1, 3),
            ]
        )
        reference = np.median(border, axis=0)
    mask = (
        np.abs(image - np.asarray(reference, dtype=np.int16)).max(axis=2)
        >= VISUAL_MIN_CONTRAST
    ).astype(np.uint8)
    for x, y, box_width, box_height in explained:
        mask[
            max(0, y - 1) : min(height, y + box_height + 1),
            max(0, x - 1) : min(width, x + box_width + 1),
        ] = 0
    mask[ink] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)

    candidates: list[tuple[int, list[int]]] = []
    for index in range(1, count):
        x, y, box_width, box_height, area = (int(value) for value in stats[index, :5])
        if box_width < VISUAL_MIN_SIDE or box_height < VISUAL_MIN_SIDE:
            continue
        if box_width > VISUAL_MAX_WIDTH or box_height > VISUAL_MAX_HEIGHT:
            continue
        ratio = box_width / max(1, box_height)
        if ratio < 0.12 or ratio > 10.0:
            continue
        # A short wide sliver with almost no ink in it is a leftover of a text
        # line the plan missed, not a mark.
        if box_height <= 18 and ratio >= 2.2:
            continue
        fill = area / max(1, box_width * box_height)
        if fill < VISUAL_MIN_FILL:
            continue
        box = (x, y, box_width, box_height)
        if any(_iou(box, other) >= 0.3 for other in explained):
            continue
        candidates.append((area, [x, y, box_width, box_height]))

    if not candidates:
        return 0
    candidates.sort(key=lambda item: item[0], reverse=True)
    added = 0
    accepted: list[tuple[int, int, int, int]] = []
    for _area, box in candidates[:VISUAL_MAX_REGIONS]:
        # The same glyph can break into two blobs; the first one wins.
        if any(_overlap_share(box, other) > 0.3 for other in accepted):
            continue
        payload = crop_image_b64(image_path, box[0], box[1], box[2], box[3], width, height)
        if not payload:
            continue
        digest = hashlib.sha1(
            f"{box[0]}:{box[1]}:{box[2]}:{box[3]}:{image_path}".encode("utf-8")
        ).hexdigest()[:16]
        elements.append(
            {
                "id": f"mark:{digest}",
                "type": "image",
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "text": "",
                "imageBase64": payload,
                "role": "mark",
                "name": "Visual mark",
                "contentRef": f"mark:{digest}",
                "sceneOwnerId": f"mark:{digest}",
                "imageMVP": {
                    "source": "pixel-recovery",
                    "role": "mark",
                    "grouping_status": "recovered",
                },
            }
        )
        accepted.append((box[0], box[1], box[2], box[3]))
        added += 1
    return added


def _paint_as_backdrop(
    elements: Sequence[dict[str, Any]],
    rects: Sequence[tuple[int, int, int, int] | None],
    position: Mapping[int, int],
    index: int,
    background: str,
) -> bool:
    """Repaint a box in the colour of whatever is already under it.

    Only for a box that hides nothing but the backdrop itself: a chip on a
    panel, a strip on a card.  When real content sits between the two, hiding
    the fill is the repair and this is not it.
    """
    element = elements[index]
    style = element.get("style")
    if not isinstance(style, dict):
        return False
    box = rects[index]
    if box is None:
        return False
    colour = str(background or "").strip()
    latest = -1
    for other, candidate in enumerate(elements):
        if other == index or position.get(other, -1) >= position.get(index, 0):
            continue
        fill = _opaque_fill(candidate)
        if not fill:
            continue
        other_box = rects[other]
        if other_box is None or not _rect_contains(other_box, box, tolerance=4):
            continue
        if position[other] > latest:
            latest = position[other]
            colour = fill
    if not colour:
        return False
    if _same_fill(str(style.get("fillColor") or ""), colour, 0):
        return False
    style["fillColor"] = colour
    return True


def _make_transparent(element: dict[str, Any]) -> bool:
    """Leave the border, drop the paint.

    ``none`` is what both renderers understand as "do not fill".  Removing the
    key is not the same thing: a renderer handed no fill falls back to its own
    default, and the default rectangle is grey.
    """
    style = element.get("style")
    if not isinstance(style, dict):
        return False
    if str(style.get("fillColor") or "").strip().lower() in {"", "none"}:
        return False
    style["fillColor"] = "none"
    return True


def _opaque_fill(element: Mapping[str, Any]) -> str:
    style = element.get("style")
    if not isinstance(style, dict):
        return ""
    return str(style.get("fillColor") or "").strip()


def _buried_content(
    elements: Sequence[dict[str, Any]],
    rects: Sequence[tuple[int, int, int, int] | None],
    position: Mapping[int, int],
    occluder: int,
    closures: Mapping[int, set[int]],
) -> list[int]:
    """Earlier-painted text or icons that a filled box covers."""
    box = rects[occluder]
    if box is None:
        return []
    own = closures.get(occluder, set())
    occluder_kind = str(elements[occluder].get("type") or "")
    buried: list[int] = []
    for index, element in enumerate(elements):
        if index == occluder or index in own:
            continue
        kind = str(element.get("type") or "")
        if kind == "text":
            if not str(element.get("text") or "").strip():
                continue
        elif kind == "image":
            # A glyph-sized cut that **straddles** the box: the icon is real and
            # half of it is hidden.  One that sits wholly inside is that box's
            # own decoration — often a control the model invented, invisible in
            # the screenshot and correct to leave under its backing.
            rect = rects[index]
            if rect is None or rect[2] > 64 or rect[3] > 64:
                continue
            if _rect_contains(box, rect, tolerance=2):
                continue
            # A control's own face is its glyph; the pair composes into a
            # button, and there is nothing to uncover.
            if occluder_kind in {"button", "input"}:
                continue
        else:
            continue
        rect = rects[index]
        if rect is None or position.get(index, -1) >= position.get(occluder, 0):
            continue
        overlap_w = min(rect[0] + rect[2], box[0] + box[2]) - max(rect[0], box[0])
        overlap_h = min(rect[1] + rect[3], box[1] + box[3]) - max(rect[1], box[1])
        if overlap_w <= 0 or overlap_h <= 0:
            continue
        # Nearly the same rectangle: a control and the glyph cut that is its
        # own face.  Whatever the order, the two compose into one control, so
        # there is nothing hidden to repair.
        union = rect[2] * rect[3] + box[2] * box[3] - overlap_w * overlap_h
        if union > 0 and (overlap_w * overlap_h) / union >= 0.4:
            continue
        if (overlap_w * overlap_h) / max(1, rect[2] * rect[3]) < FILL_OCCLUSION_COVERAGE:
            continue
        buried.append(index)
    return buried


def _is_scrim_fragment(
    elements: Sequence[dict[str, Any]],
    rects: Sequence[tuple[int, int, int, int] | None],
    position: Mapping[int, int],
    fragment: int,
    fill: str,
    background: str,
) -> bool:
    """A page-coloured patch sitting on a solid panel is the backdrop, not a box.

    A dialog screenshot is dimmed end to end, so the page colour is the scrim.
    A region measured over the dimmed area then paints that same grey *inside*
    the white dialog and blocks it.  Repainting the backdrop over a solid panel
    is never what the picture shows, so the fill goes and only the border (if
    any) remains.
    """
    if not _same_fill(fill, background, PAGE_FILL_TOLERANCE):
        return False
    if str(elements[fragment].get("type")) != "container":
        # A button or an input that happens to be white is a control with a
        # fill, not a piece of the backdrop.
        return False
    box = rects[fragment]
    if box is None:
        return False
    if box[2] * box[3] < PAGE_FRAGMENT_MIN_AREA:
        return False
    for index, element in enumerate(elements):
        if index == fragment or position.get(index, len(elements)) >= position.get(
            fragment, 0
        ):
            continue
        other = rects[index]
        if other is None or not _rect_contains(other, box, tolerance=4):
            continue
        other_fill = _opaque_fill(element)
        if not other_fill or _same_fill(other_fill, background, PAGE_FILL_TOLERANCE):
            continue
        return True
    return False


def _audit_filled_occluders(
    elements: list[dict[str, Any]],
    background: str,
) -> int:
    """Stop a solid rectangle from painting over text it does not own.

    Frame batching gathers a frame's closure into one run.  A container that
    merely *overlaps* the frame — a table section measured a little wider than
    the card it sits in — is not a member, so it keeps its own slot and now
    lands after the whole run: the white block covers every row of the table
    it was supposed to sit behind.  The header bar's backdrop does the same to
    the nav labels.

    Repairs, in this order:

    * a member of a frame cannot be re-ordered without breaking the run its
      frame needs — stop painting it instead;
    * a box that hides nothing but the backdrop is repainted in the backdrop's
      colour, which changes no pixel except the ones it was covering;
    * otherwise sink the box below whatever it is hiding by one tier.  If that
      would cost a frame, stop painting it instead.
    """
    if not elements:
        return 0
    from src.app.services.rendering.adapter_base import paint_order, resolve_frames

    rects = [_layout_rect(element) for element in elements]
    closures = {
        index: _frame_closure(index, elements)
        for index, element in enumerate(elements)
        if element.get("layoutChildren")
    }
    before = len(resolve_frames(elements, paint_order(elements))) if closures else 0

    order = [index for index, _element in paint_order(elements)]
    position = {index: spot for spot, index in enumerate(order)}
    demoted: list[int] = []
    filled = 0
    for index, element in enumerate(elements):
        if str(element.get("role") or "") == "text-backdrop":
            # Sampled from the picture to sit *under* its own words; moving or
            # repainting it is the one thing that would break it.
            continue
        fill = _opaque_fill(element)
        if not fill:
            continue
        box = rects[index]
        # Rules, separators and progress bars are strokes, not panels.
        if box is None or min(box[2], box[3]) <= 12:
            continue
        buried = _buried_content(elements, rects, position, index, closures)
        scrim = _is_scrim_fragment(
            elements, rects, position, index, fill, background
        )
        if not buried and not scrim:
            continue
        member_of = next(
            (
                closure
                for key, closure in closures.items()
                if key != index and index in closure
            ),
            None,
        )
        if member_of is not None:
            # A member cannot be re-ordered inside the frame that owns it —
            # that reordering is exactly what the frame gate refuses — so the
            # only repair left is to stop painting.
            if _make_transparent(element):
                filled += 1
            continue
        if not buried:
            # Nothing but the backdrop is under it: repainting it in the
            # backdrop's colour hides it without moving anything.
            if _paint_as_backdrop(elements, rects, position, index, background):
                filled += 1
            continue
        floor = min(int(elements[member].get("zIndex") or 0) for member in buried)
        element["zIndex"] = floor - 1
        demoted.append(index)

    if demoted and closures:
        after = len(resolve_frames(elements, paint_order(elements)))
        if after < before:
            for index in demoted:
                elements[index].pop("zIndex", None)
                if _make_transparent(elements[index]):
                    filled += 1
    return filled + len(demoted)


#: Colour distance at which the surface under a member is a different plane
#: from the box that claims it.
PLANE_SURFACE_DELTA = 40
#: ... and at which that surface is the page itself.
PLANE_PAGE_DELTA = 40
#: Share of the ring around a member that has to be page colour.  A member
#: straddling the plane edge samples both sides, and only an unambiguous
#: majority is worth acting on.
PLANE_PAGE_SHARE = 0.8
#: How far a sampled column may sit from the container's fill and still count
#: as that fill.  Wide enough for a soft shadow, far below any page colour.
PLANE_EDGE_TOLERANCE = 24
#: A cut smaller than this is an antialiased rim, not an over-measured box.
PLANE_TRIM_MIN = 4
#: A chip is a badge for one short word.  The band is what tells a badge from a
#: card: wider is a panel, shorter is a dot.
CHIP_MIN_WIDTH = 36
CHIP_MAX_WIDTH = 72
CHIP_MAX_HEIGHT = 72


def _solid_fill(element: Mapping[str, Any]) -> str:
    """The element's fill when it paints one, else an empty string."""
    fill = _opaque_fill(element).lower()
    if not fill or fill in {"none", "transparent"}:
        return ""
    return fill


def _plane_children(
    elements: Sequence[Mapping[str, Any]],
    rects: Sequence[tuple[int, int, int, int] | None],
) -> dict[int, list[int]]:
    """Geometric containment tree, recovered roles excluded as parents."""
    recovered = {"text-backdrop", "mark", "progress", "page-ground"}
    containers = {
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "container"
        and str(element.get("role") or "") not in recovered
    }
    children: dict[int, list[int]] = {}
    owners: list[int | None] = []
    for index, rect in enumerate(rects):
        if rect is None:
            owners.append(None)
            continue
        owner = _owner_index(rects, index, parent_candidates=containers)
        owners.append(owner)
        if owner is not None:
            children.setdefault(owner, []).append(index)
    return children


def _member_anchor(
    index: int,
    rects: Sequence[tuple[int, int, int, int] | None],
    children: Mapping[int, list[int]],
) -> tuple[int, int, int, int] | None:
    """Where a member actually stands: its own box, narrowed to its content.

    A container's measured box can be far wider than what it holds — the
    background page's form section was measured at the full content width while
    every word it owns sits in the right column.  Its content is what stands on
    a plane, so that is what gets sampled.
    """
    own = rects[index]
    if own is None:
        return None
    nested = children.get(index) or []
    if not nested:
        return own
    union = _union_rect(nested, rects)
    if union is None or not _rect_contains(own, union, tolerance=4):
        return own
    return union


def _page_share(
    pixels,
    box: tuple[int, int, int, int],
    colour: str,
    spread: int = 6,
) -> float:
    """Share of the band just outside ``box`` painted ``colour``."""
    try:
        import numpy as np
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return 0.0
    if pixels is None or not colour:
        return 0.0
    target = np.asarray(_hex_rgb(colour), dtype=np.int16)
    frame_height, frame_width = pixels.shape[:2]
    x, y, box_width, box_height = box
    left = max(0, x - spread)
    right = min(frame_width, x + box_width + spread)
    top = max(0, y - spread)
    bottom = min(frame_height, y + box_height + spread)
    if right - left < 4 or bottom - top < 4:
        return 0.0
    patch = pixels[top:bottom, left:right]
    mask = np.ones(patch.shape[:2], dtype=bool)
    inner_left = max(0, x - left)
    inner_top = max(0, y - top)
    mask[inner_top : inner_top + box_height, inner_left : inner_left + box_width] = False
    sample = patch[mask]
    if sample.size == 0:
        return 0.0
    distance = np.abs(sample - target).max(axis=1)
    return float((distance <= PLANE_PAGE_DELTA).mean())


def _filled_edge(
    pixels,
    box: tuple[int, int, int, int],
    fill: str,
    edge: str,
    floor: int,
) -> int | None:
    """Walk in from ``edge`` and stop on the first line that paints ``fill``.

    The median of a whole column is used, not a single pixel: a copyright line
    sits in the middle of the band being skipped, and one white glyph is not the
    dialog starting again.
    """
    try:
        import numpy as np
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return None
    if pixels is None or not fill:
        return None
    x, y, width, height = box
    target = np.asarray(_hex_rgb(fill), dtype=np.int16)
    inset = 4 if min(width, height) > 16 else 0
    if edge in {"left", "right"}:
        band = pixels[y + inset : y + height - inset, :]
        if band.shape[0] < 2:
            return None
        columns = (
            range(x + width - 1, max(-1, floor - 1), -1)
            if edge == "right"
            else range(x, min(band.shape[1], floor + 1))
        )
        for column in columns:
            if column < 0 or column >= band.shape[1]:
                continue
            median = np.median(band[:, column].reshape(-1, 3), axis=0)
            if float(np.abs(median - target).max()) <= PLANE_EDGE_TOLERANCE:
                return column + 1 if edge == "right" else column
        return None
    band = pixels[:, x + inset : x + width - inset]
    if band.shape[1] < 2:
        return None
    rows = (
        range(y + height - 1, max(-1, floor - 1), -1)
        if edge == "bottom"
        else range(y, min(band.shape[0], floor + 1))
    )
    for row in rows:
        if row < 0 or row >= band.shape[0]:
            continue
        median = np.median(band[row].reshape(-1, 3), axis=0)
        if float(np.abs(median - target).max()) <= PLANE_EDGE_TOLERANCE:
            return row + 1 if edge == "bottom" else row
    return None


#: A child may be clipped by its parent, but not to nothing.
CONTAIN_MIN_SIZE = 8
#: ... and a label may be narrowed by its neighbour, but never below a word.
CONTAIN_MIN_TEXT = 24
#: Keep this far clear of the neighbour a label is running into.
CONTAIN_TEXT_GAP = 4
#: Beyond this the child is right and the parent is wrong.
CONTAIN_MAX_OVERFLOW = 24


def _constrain_children(
    elements: list[dict[str, Any]],
    background: str = "",
) -> int:
    """Keep every child inside its parent, and every label inside its row.

    Two overflows, one cause: a box measured a little wider than the thing it
    describes.  A container whose members reach past it leaves a strip of its
    fill outside the panel — the white patches crossing the inventory sidebar —
    and a label whose text is wider than its box prints over the note beside it,
    because the renderer lays the string out from the box and does not know a
    neighbour is there.

    So: the rectangle is clipped to the parent's rectangle (the parent is the
    authority on where its own world ends), and a label's width is capped at
    whatever is left before the next sibling on its row.
    """
    rects = [_layout_rect(element) for element in elements]
    recovered = {"text-backdrop", "mark", "progress", "page-ground", "block"}
    containers = {
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "container" and rects[index] is not None
        and str(element.get("role") or "") not in recovered
    }
    clipped = 0
    for kid, box in enumerate(rects):
        if box is None:
            continue
        # Labels have their own rule below (a text box that is clipped wraps
        # for no reason), and a planned container is the model's reading of a
        # group — clipping it deletes structure.  What is left is exactly the
        # case that produced the white patches: pixel-recovered blocks and
        # controls, drawn from a threshold and measured a little too wide.
        kind = str(elements[kid].get("type") or "")
        role = str(elements[kid].get("role") or "")
        if kind == "text":
            continue
        if kind == "container" and role not in {"block", "panel"}:
            continue
        # The parent is the smallest container that *mostly* holds this box.
        # Strict containment cannot find it: the whole point is that the child
        # sticks out, so it is never fully inside anything.
        centre_x = box[0] + box[2] / 2
        centre_y = box[1] + box[3] / 2
        parent: int | None = None
        best_area: int | None = None
        for candidate in containers:
            outer = rects[candidate]
            if outer is None or outer[2] * outer[3] <= box[2] * box[3]:
                continue
            if not (
                outer[0] <= centre_x <= outer[0] + outer[2]
                and outer[1] <= centre_y <= outer[1] + outer[3]
            ):
                continue
            if _overlap_share(box, outer) < 0.6:
                continue
            area = outer[2] * outer[3]
            if best_area is None or area < best_area:
                parent, best_area = candidate, area
        if parent is None:
            continue
        parent_box = rects[parent]
        # Only a panel with its own paint is an authority on where its world
        # ends.  A page-coloured wrapper measures the same as the page, and
        # clipping to it just shortens cards that were right.
        panel_fill = _solid_fill(elements[parent])
        if not panel_fill or (background and _same_fill(panel_fill, background, SOFT_PANEL_MIN_DELTA)):
            continue
        if True:
            right = min(box[0] + box[2], parent_box[0] + parent_box[2])
            bottom = min(box[1] + box[3], parent_box[1] + parent_box[3])
            width = right - box[0]
            height = bottom - box[1]
            if width < CONTAIN_MIN_SIZE or height < CONTAIN_MIN_SIZE:
                continue
            if width == box[2] and height == box[3]:
                continue
            # A small overshoot is a measurement slip and is clipped.  A large
            # one is the parent that is wrong — a highlight bar that runs the
            # full width of a sidebar is not the thing to cut.
            if max(box[2] - width, box[3] - height) > CONTAIN_MAX_OVERFLOW:
                continue
            element = elements[kid]
            element["width"] = width
            element["height"] = height
            rects[kid] = (box[0], box[1], width, height)
            clipped += 1

    # A label that would print past the next thing on its row is capped at the
    # room that is actually there.
    for index, element in enumerate(elements):
        if str(element.get("type")) != "text" or not element.get("text"):
            continue
        box = rects[index]
        if box is None:
            continue
        span_left, span_right = _rendered_span(element)
        if span_right - span_left <= box[2] + 2:
            continue
        limit: int | None = None
        for other, other_box in enumerate(rects):
            if other == index or other_box is None:
                continue
            if other_box[0] < box[0] + box[2] - 2:
                continue
            rows = min(box[1] + box[3], other_box[1] + other_box[3]) - max(
                box[1], other_box[1]
            )
            if rows < min(box[3], other_box[3]) * 0.5:
                continue
            candidate = other_box[0] - CONTAIN_TEXT_GAP - box[0]
            if candidate < CONTAIN_MIN_TEXT:
                continue
            limit = candidate if limit is None else min(limit, candidate)
        if limit is None or limit >= box[2]:
            continue
        element["width"] = limit
        rects[index] = (box[0], box[1], limit, box[3])
        clipped += 1
    return clipped


def _evict_cross_plane_members(
    elements: list[dict[str, Any]],
    image_path: str,
    canvas: tuple[int, int] | None,
    background: str | None,
    ocr_observations: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[int, int]:
    """Give back the members that never lived inside their container.

    A dialog is measured once, and a wide measurement swallows everything to
    its right: the page's own column, a copyright line two hundred pixels below
    the dialog's last row.  They become members, so the union of members reaches
    the page edge, and every downstream "is this box too big?" test answers no.

    The screenshot knows which plane each element is on.  Sampling the band
    around a member: a member of the white dialog stands on white, a member of
    the dimmed page behind it stands on the page colour.  When that band is the
    page colour while the container paints something else entirely, the member
    is on the other side of the glass — it is detached, painted underneath, and
    stops voting on the container's extent.

    A control detached this way whose label nothing on the page reads, and whose
    declared fill is not what its box actually shows, is an invented control on
    the background plane: it is removed rather than left as a black pill on a
    grey page.
    """
    if not background or not canvas:
        return 0, 0
    pixels = _pixel_edges(image_path, canvas[0], canvas[1])
    if pixels is None:
        return 0, 0
    rects = [_layout_rect(element) for element in elements]
    children = _plane_children(elements, rects)
    lines = _ocr_lines(ocr_observations)
    page = str(background)
    doomed: set[int] = set()
    evicted = 0
    for container, members in children.items():
        if str(elements[container].get("type")) != "container":
            continue
        fill = _solid_fill(elements[container])
        if not fill or _same_fill(fill, page, PLANE_SURFACE_DELTA):
            continue
        for member in members:
            anchor = _member_anchor(member, rects, children)
            if anchor is None:
                continue
            if _page_share(pixels, anchor, page) < PLANE_PAGE_SHARE:
                continue
            element = elements[member]
            element["planeDetached"] = True
            # The layer underneath, by construction: it must never be lifted
            # over the box that was merely mis-measured.
            element["zIndex"] = -1
            evicted += 1
            if str(element.get("type")) not in {"button", "input"}:
                continue
            text = str(element.get("text") or "").strip()
            if not text or _has_ocr_support(text, anchor, lines, slack=8, threshold=0.8):
                continue
            shown = _page_share(pixels, anchor, fill)
            if shown > 0.2:
                continue
            doomed.add(member)
    if doomed:
        elements[:] = [
            element for index, element in enumerate(elements) if index not in doomed
        ]
    return evicted, len(doomed)


def _beyond_is_page(
    pixels,
    box: tuple[int, int, int, int],
    edge: str,
    coordinate: int,
    background: str,
    spread: int = 6,
) -> bool:
    """Whether the band just outside ``coordinate`` is the page colour.

    The trim repairs a box that walks over the page.  If the paint on the other
    side is *not* the page — a sidebar's own highlight band, another panel — the
    edge is where the design puts it and cutting it would expose the canvas.
    """
    try:
        import numpy as np
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return False
    if pixels is None or not background:
        return False
    frame_height, frame_width = pixels.shape[:2]
    x, y, width, height = box
    if edge == "left":
        band = (slice(y, y + height), slice(max(0, coordinate - spread), coordinate))
    elif edge == "right":
        band = (
            slice(y, y + height),
            slice(coordinate, min(frame_width, coordinate + spread)),
        )
    elif edge == "top":
        band = (slice(max(0, coordinate - spread), coordinate), slice(x, x + width))
    else:
        band = (
            slice(coordinate, min(frame_height, coordinate + spread)),
            slice(x, x + width),
        )
    patch = pixels[band]
    if patch.size == 0:
        return False
    median = np.median(patch.reshape(-1, 3), axis=0)
    target = np.asarray(_hex_rgb(background), dtype=np.int16)
    return float(np.abs(median - target).max()) <= PLANE_PAGE_DELTA


def _trim_to_fill_boundary(
    elements: list[dict[str, Any]],
    image_path: str,
    canvas: tuple[int, int] | None,
    background: str | None,
) -> int:
    """Cut a container back to the edge its own paint actually reaches.

    Once the members that stood on the page have been given back, the union of
    what is left is where the container's content really ends.  Any face of the
    box beyond that is examined against the picture: if the pixels just inside
    the declared edge are not the container's own fill, the edge is walking over
    the page and is pulled in to the colour step.  Padding that *is* fill is
    left alone — the dialog's inner margin is part of the dialog.
    """
    if not background or not canvas:
        return 0
    pixels = _pixel_edges(image_path, canvas[0], canvas[1])
    if pixels is None:
        return 0
    rects = [_layout_rect(element) for element in elements]
    children = _plane_children(elements, rects)
    containers = {
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "container" and rects[index] is not None
    }
    trimmed = 0
    for container in containers:
        own = rects[container]
        fill = _solid_fill(elements[container])
        if own is None or not fill or _same_fill(fill, background, PLANE_SURFACE_DELTA):
            continue
        members = [
            index
            for index in children.get(container, [])
            if not elements[index].get("planeDetached")
        ]
        # A single member is a card around one label; its padding is design.
        if len(members) < 2:
            continue
        union = _union_rect(members, rects)
        if union is None:
            continue
        left, top = own[0], own[1]
        right, bottom = own[0] + own[2], own[1] + own[3]
        found_left = (
            _filled_edge(pixels, own, fill, "left", union[0])
            if union[0] - left >= PLANE_TRIM_MIN
            else None
        )
        found_top = (
            _filled_edge(pixels, own, fill, "top", union[1])
            if union[1] - top >= PLANE_TRIM_MIN
            else None
        )
        found_right = (
            _filled_edge(pixels, own, fill, "right", union[0] + union[2])
            if right - (union[0] + union[2]) >= PLANE_TRIM_MIN
            else None
        )
        found_bottom = (
            _filled_edge(pixels, own, fill, "bottom", union[1] + union[3])
            if bottom - (union[1] + union[3]) >= PLANE_TRIM_MIN
            else None
        )
        if found_left is not None and not _beyond_is_page(
            pixels, own, "left", found_left, background
        ):
            found_left = None
        if found_top is not None and not _beyond_is_page(
            pixels, own, "top", found_top, background
        ):
            found_top = None
        if found_right is not None and not _beyond_is_page(
            pixels, own, "right", found_right, background
        ):
            found_right = None
        if found_bottom is not None and not _beyond_is_page(
            pixels, own, "bottom", found_bottom, background
        ):
            found_bottom = None
        # A step of one or two pixels is the container's own antialiased rim.
        if found_left is not None and found_left - left < PLANE_TRIM_MIN:
            found_left = None
        if found_top is not None and found_top - top < PLANE_TRIM_MIN:
            found_top = None
        if found_right is not None and right - found_right < PLANE_TRIM_MIN:
            found_right = None
        if found_bottom is not None and bottom - found_bottom < PLANE_TRIM_MIN:
            found_bottom = None
        new_left = left if found_left is None else found_left
        new_top = top if found_top is None else found_top
        new_right = right if found_right is None else found_right
        new_bottom = bottom if found_bottom is None else found_bottom
        if (new_left, new_top, new_right, new_bottom) == (left, top, right, bottom):
            continue
        if new_right - new_left < 8 or new_bottom - new_top < 8:
            continue
        element = elements[container]
        element["x"] = new_left
        element["y"] = new_top
        element["width"] = new_right - new_left
        element["height"] = new_bottom - new_top
        rects[container] = (new_left, new_top, new_right - new_left, new_bottom - new_top)
        trimmed += 1
    return trimmed


#: A patch is the last resort: the region's own pixels, cut out of the picture,
#: when nothing else can draw it.  Above everything, because it replaces the
#: drawing that is wrong.
PATCH_Z_INDEX = 5


# ── 背景层合并 / 分层 / 遮挡守卫 ────────────────────────────────────────────
#
# 盲测暴露的第三类问题不是"少画了什么"，而是"画了两遍、后画的那遍把前一遍盖住
# 了"。两个来源：同一块面板被两套感知各建了一个容器；残差补丁压在矢量字上。
# VLM 仲裁看不见它——设计树里节点明明在，只是被埋了。
#
# 三条规则按"结构 → 层序 → 守卫"的顺序落地：合并改结构（必须在成帧前），分层
# 写 paintDepth（纯排序），守卫只降层或裁补丁（不改帧）。

#: 两个背景块重合到这个 IoU，就是同一块区域量了两遍。
CONTAINER_MERGE_IOU = 0.70
#: 小盒 85% 落在大盒里也算——但必须面积相近：卡片落在面板里同样是 100% 包含，
#: 那是层级不是重复。面积比把两者分开（见 `_merge_duplicate_containers`）。
CONTAINER_MERGE_CONTAIN = 0.85
CONTAINER_MERGE_AREA_RATIO = 0.70
#: 四条边都差在这个像素内，才是"同一块量了两遍"。差得更多的是两层结构——
#: 列表区嵌在页面卡里、表格节点嵌在区块里——合掉任何一层都会少一个帧。
CONTAINER_MERGE_EDGE = 12
#: 小于画布这个比例的盒子不参与：小徽章互相压着是设计，不是双测。
CONTAINER_MERGE_MIN_SHARE = 0.02
#: 两次测量必须是同一种漆。色差更大说明是两层不同材质（玻璃压卡片）。
CONTAINER_MERGE_FILL_DELTA = 6

#: 层序分层：每层留这么多个槽位，同层内按面积降序。
LAYER_STRIDE = 1000
#: 不透明的东西盖住文本框这么多，就算"吞字"。
OCCLUSION_TEXT_COVER = 0.5
#: 文本框里墨迹占到这个比例，说明原图这个位置确实有字。
TEXT_VISIBLE_INK = 0.008
#: 补丁被裁到只剩这么点，就不值得留了——整块删掉比留个碎片更干净。
PATCH_KEEP_SHARE = 0.3


def _background_fill(element: Mapping[str, Any]) -> str:
    style = element.get("style") or {}
    fill = str(style.get("fillColor") or "")
    if element.get("transparent") or fill.lower() in ("", "transparent", "none"):
        return ""
    return fill


def _owned_between(
    elements: Sequence[Mapping[str, Any]],
    first: int,
    second: int,
    first_box: tuple[int, int, int, int],
    second_box: tuple[int, int, int, int],
) -> tuple[int, int]:
    """How many elements each of the two boxes would own, smallest box wins.

    The frame pass gives a member to the smallest container that holds it, with
    the earlier index breaking ties — the same rule here, so "owns members"
    means exactly what it will mean when frames are built.
    """
    first_area = first_box[2] * first_box[3]
    second_area = second_box[2] * second_box[3]
    owned_first = owned_second = 0
    for index, element in enumerate(elements):
        if index in (first, second):
            continue
        box = _layout_rect(element)
        if box is None:
            continue
        in_first = _rect_contains(first_box, box, tolerance=2)
        in_second = _rect_contains(second_box, box, tolerance=2)
        if in_first and in_second:
            if first_area <= second_area:
                owned_first += 1
            else:
                owned_second += 1
        elif in_first:
            owned_first += 1
        elif in_second:
            owned_second += 1
    return owned_first, owned_second


def _merge_duplicate_containers(
    elements: list[dict[str, Any]],
    ocr_observations: Sequence[Mapping[str, Any]] | None,
    canvas: tuple[int, int],
) -> int:
    """One panel measured twice: merge the boxes instead of painting twice.

    Two perception paths describe the same card — one as a ``card``, one as a
    ``panel`` — and both reach the list.  The later one paints over the first,
    which is how a card ends up a flat block with its own words buried under it.
    The VLM cannot repair that: the tree already has a node at that coordinate.

    Merging is not "delete the poorer one".  Its children would go with it, and
    ownership is derived from geometry.  The survivor takes the **union** box,
    so nothing that lived inside the loser falls outside the winner; the text
    passes that follow dedupe the words.  A patch that duplicates a container is
    the one case that is deleted outright: pixels of the very panel that is
    already drawn, sitting on top of its editable content.
    """
    width, height = canvas
    floor = max(1, width * height) * CONTAINER_MERGE_MIN_SHARE

    def mergeable(element: Mapping[str, Any]) -> bool:
        role = str(element.get("role") or "")
        if role == "patch":
            return True
        if str(element.get("type") or "") != "container":
            return False
        if element.get("imageBase64"):
            return False
        if str(element.get("text") or "").strip():
            return False
        return role not in ("page", "page-ground", "page-background", "mark")

    pool = [
        (index, _layout_rect(element))
        for index, element in enumerate(elements)
        if mergeable(element)
    ]
    pool = [
        (index, box)
        for index, box in pool
        if box and box[2] * box[3] >= floor
    ]
    if len(pool) < 2:
        return 0

    def carried(box: tuple[int, int, int, int]) -> tuple[int, int]:
        supported = total = 0
        for element in elements:
            if element.get("type") != "text":
                continue
            text = str(element.get("text") or "").strip()
            inner = _layout_rect(element) if text else None
            if inner is None:
                continue
            cx = inner[0] + inner[2] / 2.0
            cy = inner[1] + inner[3] / 2.0
            if not (
                box[0] <= cx <= box[0] + box[2] and box[1] <= cy <= box[1] + box[3]
            ):
                continue
            total += 1
            if _ocr_supported(text, inner, ocr_observations):
                supported += 1
        return supported, total

    doomed: set[int] = set()
    merged = 0
    for position, (first, first_box) in enumerate(pool):
        if first in doomed:
            continue
        for second, second_box in pool[position + 1 :]:
            if second in doomed:
                continue
            first_area = first_box[2] * first_box[3]
            second_area = second_box[2] * second_box[3]
            ratio = min(first_area, second_area) / max(1, max(first_area, second_area))
            edges = max(
                abs(first_box[0] - second_box[0]),
                abs(first_box[1] - second_box[1]),
                abs((first_box[0] + first_box[2]) - (second_box[0] + second_box[2])),
                abs((first_box[1] + first_box[3]) - (second_box[1] + second_box[3])),
            )
            same = (
                _iou(first_box, second_box) >= CONTAINER_MERGE_IOU
                or (
                    _overlap_over_smaller(first_box, second_box)
                    >= CONTAINER_MERGE_CONTAIN
                    and ratio >= CONTAINER_MERGE_AREA_RATIO
                )
            ) and edges <= CONTAINER_MERGE_EDGE
            if not same:
                continue
            first_element, second_element = elements[first], elements[second]
            first_patch = str(first_element.get("role") or "") == "patch"
            second_patch = str(second_element.get("role") or "") == "patch"
            # 两边都自带成员时不合并：那不是"同一块量了两遍"，是两层结构
            # （列表区嵌在页面卡里、表格节点嵌在区块里）。删掉任何一层都会
            # 少一个帧，而帧数是硬约束。谁"自带"成员按最小包含盒算，与成帧
            # 时的归属规则一致：完全重合的两个盒子，成员只会归其中一个。
            if not first_patch and not second_patch:
                owned_first, owned_second = _owned_between(
                    elements, first, second, first_box, second_box
                )
                if owned_first >= 2 and owned_second >= 2:
                    continue
            if not first_patch and not second_patch:
                first_fill = _background_fill(first_element)
                second_fill = _background_fill(second_element)
                if first_fill and second_fill and not _same_fill(
                    first_fill, second_fill, CONTAINER_MERGE_FILL_DELTA
                ):
                    # 两层不同的漆：这是玻璃压在卡片上，不是同一块量了两遍。
                    continue
            # 谁当主体：装得下更多 OCR 确认文字的那一版；打平则选可编辑的容器，
            # 再打平选面积大的。补丁永远输给容器——它是像素，不是结构。
            first_score = (carried(first_box), 0 if first_patch else 1, first_area)
            second_score = (carried(second_box), 0 if second_patch else 1, second_area)
            loser = first if first_score < second_score else second
            winner = second if loser == first else first
            loser_box = first_box if loser == first else second_box
            winner_box = second_box if loser == first else first_box
            winner_element = elements[winner]
            if str(winner_element.get("role") or "") != "patch":
                union = (
                    min(winner_box[0], loser_box[0]),
                    min(winner_box[1], loser_box[1]),
                    max(winner_box[0] + winner_box[2], loser_box[0] + loser_box[2])
                    - min(winner_box[0], loser_box[0]),
                    max(winner_box[1] + winner_box[3], loser_box[1] + loser_box[3])
                    - min(winner_box[1], loser_box[1]),
                )
                winner_element["x"], winner_element["y"] = union[0], union[1]
                winner_element["width"], winner_element["height"] = union[2], union[3]
            winner_element.setdefault("mergeEvidence", {}).setdefault(
                "absorbed", []
            ).append(
                {
                    "id": str(elements[loser].get("id") or ""),
                    "iou": round(_iou(first_box, second_box), 3),
                    "box": list(loser_box),
                }
            )
            doomed.add(loser)
            merged += 1
            if loser == first:
                break
    if not doomed:
        return 0
    elements[:] = [
        element for index, element in enumerate(elements) if index not in doomed
    ]
    return merged


def _layer_category(element: Mapping[str, Any], canvas_area: float) -> int:
    """Which band of the stack this element belongs to.

    0 page surface · 1 panels and cards · 2 pictures · 3 controls · 4 words and
    icons · 5 bitmap patches.  Panels sort by area inside their band, so a big
    frame is always under the small cards it contains.
    """
    role = str(element.get("role") or "")
    kind = str(element.get("type") or "")
    if role in ("page", "page-ground", "page-background"):
        return 0
    if role == "patch":
        return 5
    if kind == "text" or role in ("mark", "icon"):
        return 4
    if kind in ("button", "input", "control", "switch", "checkbox", "tab"):
        return 3
    if str(element.get("text") or "").strip():
        return 3
    area = float(element.get("width") or 0) * float(element.get("height") or 0)
    if kind in ("image", "picture", "video"):
        return 0 if area >= canvas_area * 0.5 else 2
    if kind == "container":
        return 1
    return 3


def _merge_control_labels(
    elements: list[dict[str, Any]],
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> int:
    """A control and a text node printing in the same box.

    An input carries its own label, and the OCR pass carries a text node for the
    characters it read.  Both print.  ERP's "在制" dropdown came out twice — a
    20px regular in the control, a 22px bold on top — and a phantom input whose
    label read "10" drew its border around the words "产品版本".

    Two outcomes, both decided by what the picture reads:

    * same words — the control keeps its box, the label goes to whoever OCR
      supports (the text node wins a tie: it has the measured type);
    * different words, only the text node is supported — the control is a
      mis-typed duplicate of that label, so it goes.
    """
    if not ocr_observations:
        return 0
    controls = [
        element
        for element in elements
        if str(element.get("type") or "") in ("button", "input")
        and str(element.get("text") or "").strip()
    ]
    if not controls:
        return 0
    texts = [
        element
        for element in elements
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    doomed: set[str] = set()
    changed = 0
    for control in controls:
        control_box = _layout_rect(control)
        if control_box is None:
            continue
        control_text = _fold_homoglyphs(str(control.get("text") or "").strip())
        if not control_text:
            continue
        supported_control = _ocr_supported(
            str(control.get("text") or ""), control_box, ocr_observations
        )
        for text in texts:
            if str(text.get("id") or "") in doomed:
                continue
            box = _layout_rect(text)
            if box is None or not _texts_collide(control_box, box):
                continue
            words = _fold_homoglyphs(str(text.get("text") or "").strip())
            if not words:
                continue
            supported_text = _ocr_supported(
                str(text.get("text") or ""), box, ocr_observations
            )
            same = words == control_text or words in control_text or control_text in words
            if same and (supported_text or not supported_control):
                control["text"] = ""
                control.setdefault("style", {}).pop("textColor", None)
                control.setdefault("mergeEvidence", {})["labelGivenTo"] = str(
                    text.get("id") or ""
                )
                changed += 1
                break
            if not same and supported_text and not supported_control:
                doomed.add(str(control.get("id") or ""))
                text.setdefault("mergeEvidence", {})["absorbed"] = str(
                    control.get("id") or ""
                )
                changed += 1
                break
    if doomed:
        elements[:] = [
            element
            for element in elements
            if str(element.get("id") or "") not in doomed
        ]
    return changed


def _order_layers(elements: list[dict[str, Any]]) -> int:
    """Emit the tree in paint order: page → panels → pictures → controls → words.

    The renderer derives that order from geometry already — a big panel is
    covered by more boxes than the small card on top of it, so it sorts first.
    What was missing is that the **design tree** was emitted in measurement
    order, so opening the file showed a text node before the card it belongs to.
    Sorting the list by the renderer's own key materialises the rule without
    inventing a second ordering that the frame pass would then have to fight:
    the sorted result paints exactly the same pixels, because a stable sort by
    the key the renderer already uses is that order.
    """
    from src.app.services.rendering.adapter_base import paint_order

    ordered = [element for _index, element in paint_order(elements)]
    if len(ordered) != len(elements):
        return 0
    moved = sum(1 for before, after in zip(elements, ordered) if before is not after)
    elements[:] = ordered
    return moved


def _paint_ranks(elements: list[dict[str, Any]]) -> dict[int, int]:
    """Flat paint rank per element, computed by the renderer's own rule."""
    from src.app.services.rendering.adapter_base import paint_order

    return {index: rank for rank, (index, _item) in enumerate(paint_order(elements))}


def _opaque(element: Mapping[str, Any]) -> bool:
    if element.get("imageBase64"):
        return True
    return bool(_background_fill(element))


def _cover_share(
    outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]
) -> float:
    width = min(outer[0] + outer[2], inner[0] + inner[2]) - max(outer[0], inner[0])
    height = min(outer[1] + outer[3], inner[1] + inner[3]) - max(outer[1], inner[1])
    if width <= 0 or height <= 0:
        return 0.0
    return (width * height) / max(1, inner[2] * inner[3])


def _text_visible(image, box: tuple[int, int, int, int]) -> bool:
    """Whether the picture itself has strokes inside this box.

    The surface is read from a ring *outside* the box: a text box measured tight
    around a dark word has no background of its own, and taking the median of
    its interior would call the word the background.
    """
    import numpy as np

    x, y, width, height = box
    rows, columns = image.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(columns, x + width), min(rows, y + height)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return False
    crop = image[y0:y1, x0:x1]
    ring = []
    for top, bottom in ((y0 - 3, y0), (y1, min(rows, y1 + 3))):
        if bottom > top:
            ring.append(image[top:bottom, x0:x1].reshape(-1, crop.shape[2]))
    for left, right in ((x0 - 3, x0), (x1, min(columns, x1 + 3))):
        if right > left:
            ring.append(image[y0:y1, left:right].reshape(-1, crop.shape[2]))
    background = (
        np.median(np.concatenate(ring), axis=0)
        if ring
        else np.median(crop.reshape(-1, crop.shape[2]), axis=0)
    )
    ink = np.abs(crop - background).max(axis=2) >= 40
    return float(ink.mean()) >= TEXT_VISIBLE_INK


def _largest_free_rect(
    box: tuple[int, int, int, int],
    blockers: Sequence[tuple[int, int, int, int]],
) -> tuple[int, int, int, int] | None:
    """The biggest part of ``box`` that touches none of ``blockers``."""
    x, y, width, height = box
    options = [(x, y, width, height)]
    for bx, by, bw, bh in blockers:
        options.append((x, y, width, max(0, by - y)))
        options.append((x, by + bh, width, max(0, y + height - (by + bh))))
        options.append((x, y, max(0, bx - x), height))
        options.append((bx + bw, y, max(0, x + width - (bx + bw)), height))
    best: tuple[int, int, int, int] | None = None
    for candidate in options:
        if candidate[2] < 4 or candidate[3] < 4:
            continue
        if any(_rects_overlap(candidate, blocker) for blocker in blockers):
            continue
        if best is None or candidate[2] * candidate[3] > best[2] * best[3]:
            best = candidate
    return best


def _accepted_frames(elements: list[dict[str, Any]]) -> int:
    """How many frames the renderer would accept right now."""
    from src.app.services.rendering.adapter_base import paint_order, resolve_frames

    return len(resolve_frames(elements, paint_order(elements), {}))


def _guard_text_occlusion(
    elements: list[dict[str, Any]],
    image_path: str,
    canvas: tuple[int, int],
    ocr_observations: Sequence[Mapping[str, Any]] | None,
) -> dict[str, int]:
    """Nothing opaque may paint over a word the picture actually has.

    A patch is cut from the screenshot and wins every tie by construction; a
    duplicated background panel paints after the text it was measured around.
    Both read as "the words are missing" to a reviewer while the tree insists
    they are there.

    Who counts as protected: OCR read characters in that box, or the picture
    itself has ink there.  A protected word wins — the patch is cut back to the
    largest part that misses it (deleted if that is a fragment), and a container
    is demoted one tier below the lowest word it buries.  Elements whose box has
    no ink and no OCR are left alone: those are the invented labels, and
    `_drop_unbacked_labels` already owns them.
    """
    report = {"clipped": 0, "demoted": 0, "lifted": 0, "deleted": 0, "unresolved": 0}
    texts = [
        index
        for index, element in enumerate(elements)
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    if not texts:
        return report
    image = None
    try:
        import numpy as np
        from PIL import Image

        image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
        if image.shape[1] != canvas[0] or image.shape[0] != canvas[1]:
            image = None
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        image = None

    protected: dict[int, str] = {}
    for index in texts:
        box = _layout_rect(elements[index])
        if box is None:
            continue
        text = str(elements[index].get("text") or "")
        if _ocr_supported(text, box, ocr_observations):
            protected[index] = "ocr"
        elif image is not None and _text_visible(image, box):
            protected[index] = "ink"
    if not protected:
        return report

    # 帧内元素不能往下压：成员必须排在帧之后，压到帧下面会让整个帧被拒。
    # 这些位置改成"把字抬上来"——同帧内两个成员的先后是自由的。
    framed: set[str] = set()
    for element in elements:
        for child in element.get("layoutChildren") or []:
            if isinstance(child, dict):
                framed.add(str(child.get("id") or ""))
        if element.get("layoutChildren"):
            framed.add(str(element.get("id") or ""))

    from src.app.services.rendering.adapter_base import _frame_batches

    # 成员 -> 所在帧根。字的位置由帧的批次决定，所以要拿帧根的 z 当底线。
    frame_owner = dict(_frame_batches(elements))

    doomed: set[int] = set()
    for _round in range(3):
        ranks = _paint_ranks(elements)
        changed = False
        for text_index, _why in protected.items():
            if text_index in doomed or text_index not in ranks:
                continue
            text_box = _layout_rect(elements[text_index])
            if text_box is None:
                continue
            for other, element in enumerate(elements):
                if other == text_index or other in doomed:
                    continue
                if element.get("type") == "text" or not _opaque(element):
                    continue
                if ranks.get(other, -1) <= ranks[text_index]:
                    continue
                box = _layout_rect(element)
                if box is None or _cover_share(box, text_box) < OCCLUSION_TEXT_COVER:
                    continue
                role = str(element.get("role") or "")
                if element.get("imageBase64") and role in ("patch", "mark"):
                    blockers = [
                        candidate
                        for candidate in (
                            _layout_rect(elements[index]) for index in protected
                        )
                        if candidate and _rects_overlap(candidate, box)
                    ]
                    keep = _largest_free_rect(box, blockers)
                    original = max(1, box[2] * box[3])
                    if keep is not None and keep[2] * keep[3] >= original * PATCH_KEEP_SHARE:
                        element["x"], element["y"] = keep[0], keep[1]
                        element["width"], element["height"] = keep[2], keep[3]
                        element.setdefault("occlusionEvidence", {})["clippedOff"] = str(
                            elements[text_index].get("id") or ""
                        )
                        report["clipped"] += 1
                    else:
                        doomed.add(other)
                        report["deleted"] += 1
                    changed = True
                    continue
                # 容器/背景：降到它埋住的那颗字下面。帧内的字只抬自己没用——
                # 它的位置由所在帧的批次决定，所以要用"帧根 z - 1"当底线。
                # 改完复核帧数，掉帧就回退：帧数是硬约束，遮挡是软的。
                word_z = int(elements[text_index].get("zIndex") or 0)
                floor_z = word_z
                owner = frame_owner.get(text_index)
                if owner is not None:
                    floor_z = min(floor_z, int(elements[owner].get("zIndex") or 0))
                own_z = int(element.get("zIndex") or 0)
                if own_z < floor_z:
                    report["unresolved"] += 1
                    continue
                before = _accepted_frames(elements) if framed else 0
                element["zIndex"] = floor_z - 1
                if framed and _accepted_frames(elements) < before:
                    element["zIndex"] = own_z
                    report["unresolved"] += 1
                    continue
                element.setdefault("occlusionEvidence", {})[
                    "demotedBelow"
                ] = str(elements[text_index].get("id") or "")
                report["demoted"] += 1
                changed = True
                changed = True
        if not changed:
            break
    if doomed:
        elements[:] = [
            element for index, element in enumerate(elements) if index not in doomed
        ]
    return report


def _apply_residual_patches(
    elements: list[dict[str, Any]],
    image_path: str,
    canvas: tuple[int, int] | None,
    regions: Sequence[Sequence[int]] | None,
) -> int:
    """Paint the last few percent with the picture itself.

    Logos, tilted discount badges, product thumbnails, the stray glyph nobody
    modelled: a region that is still badly wrong after every rule has run, is
    small (a badge, not a panel) and is not mostly a line of text, is cut out of
    the screenshot and placed on top.  It is the honest option — the alternative
    is leaving a hole — and it is bounded so it can never become "return the
    screenshot".
    """
    if not regions or not canvas:
        return 0
    width, height = canvas
    added = 0
    for region in regions:
        if len(region) not in (4, 5):
            continue
        try:
            x, y, box_width, box_height = (int(value) for value in region[:4])
            layer = int(region[4]) if len(region) == 5 else PATCH_Z_INDEX
        except (TypeError, ValueError):
            continue
        x = max(0, x)
        y = max(0, y)
        box_width = min(box_width, width - x)
        box_height = min(box_height, height - y)
        if box_width < 2 or box_height < 2:
            continue
        payload = crop_image_b64(image_path, x, y, box_width, box_height, width, height)
        if not payload:
            continue
        digest = hashlib.sha1(
            f"patch:{x}:{y}:{box_width}:{box_height}".encode("utf-8")
        ).hexdigest()[:16]
        elements.append(
            {
                "id": f"patch:{digest}",
                "type": "image",
                "x": x,
                "y": y,
                "width": box_width,
                "height": box_height,
                "text": "",
                "imageBase64": payload,
                "role": "patch",
                "name": "Residual patch",
                "contentRef": f"patch:{digest}",
                "sceneOwnerId": f"patch:{digest}",
                "zIndex": layer,
                "imageMVP": {
                    "source": "residual-patch",
                    "role": "patch",
                    "grouping_status": "recovered",
                },
            }
        )
        added += 1
    return added


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
    # Recovered pixels are paint, never structure: a crop that happened to fall
    # inside a card must not turn into a layer group or change its layout.
    # Recovered colour blocks are paint: a flat rectangle found by thresholding
    # is a background, not a group, and making it a frame parent only holds its
    # container back.
    recovered_roles = {
        "text-backdrop",
        "mark",
        "progress",
        "page-ground",
        "block",
    }
    containers = {
        index
        for index, element in enumerate(elements)
        if str(element.get("type")) == "container"
        and str(element.get("role") or "") not in recovered_roles
    }
    owners = [
        # An element the plane pass gave back to the page is nobody's child:
        # the dialog it was measured inside was simply too wide.
        None
        if elements[index].get("planeDetached")
        else _owner_index(rects, index, parent_candidates=containers)
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
    duplicates = _duplicate_containers(
        [index for index in order if str(elements[index].get("type")) == "container"],
        rects,
        members,
    )
    # Recovered pixels are paint: a container holding nothing but a mark or a
    # chip does not need a frame of its own, and counting it as "still waiting"
    # held its parent back for nothing.
    paint_only = {"mark", "patch", "text-backdrop", "progress"}
    structural = {
        owner: [
            child
            for child in kids
            if str(elements[child].get("role") or "") not in paint_only
        ]
        for owner, kids in members.items()
    }
    for owner in order:
        if owner in duplicates:
            continue
        children = members[owner]
        container = elements[owner]
        if str(container.get("type")) != "container":
            continue
        if container.get("imageBase64") or container.get("text"):
            continue
        parent_box = _widen_to_members(owner, children, elements, rects)
        boxes = [rects[child] for child in children if rects[child]]
        if not boxes or parent_box is None:
            continue
        spec: dict[str, Any] | None = _stack_layout(parent_box, boxes)  # type: ignore[arg-type]
        ordered_children = list(children)
        if spec is None:
            # General candidate.  Pass 1 stays first because it is stricter
            # and cheaper, but nothing depends on it any more: XY-cut covers
            # every layout that has a gutter on some axis.
            fallback = _xy_cut_layout(parent_box, children, rects)
            if fallback is not None:
                spec, ordered_children = fallback
        if _has_nested_container(children, elements, structural):
            continue
        if spec is None and len(children) < 2:
            # A plain frame still needs two members for the renderer to treat
            # it as a grouping boundary rather than a stray duplicate.
            continue
        # No straddling veto here.  An overlay that covers this container is
        # lifted during the paint-order pass that follows, and only then does
        # the renderer have the final say.  Vetoing earlier deadlocked the two:
        # the overlay blocked the frame, and without the frame the overlay was
        # never lifted.
        # Auto Layout is progressive enhancement, not the price of admission.
        # A container that no formula can describe — a merged-cell table, a
        # banner with a badge, a free collage — still becomes a frame, just
        # one whose children keep their absolute coordinates.  Wrapping it
        # costs nothing: the renderer pins every child to its measured
        # position, so the export is pixel-identical, and the layer tree keeps
        # the grouping a designer expects.  Only the renderer's Z-order gates
        # can reject it, and it does so safely.
        if spec is not None:
            container["layout"] = spec
        else:
            container.pop("layout", None)
        container["layoutChildren"] = [
            {"id": str(elements[child].get("id") or "")} for child in ordered_children
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
    ocr_observations: Sequence[Mapping[str, Any]] | None = None,
    residual_regions: Sequence[Sequence[int]] | None = None,
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
    _trim_under_top_band(containers, leaves, width)
    elements = [*containers, *decorations, *leaves]
    # A box measured a few pixels wide samples the shadow, the border or the
    # page, and paints its own colour wrong.  The interior knows better.
    _calibrate_container_fills(elements, image_path, width, height, background)
    _trim_overshoot_into_conflicts(
        elements, image_path, (width, height), background
    )
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
    # 结构阶段最后一件事：同一块面板被两套感知各建一次、补丁复制了整张卡，
    # 都在这里并成一个。必须在成帧之前——合并要改盒与成员归属。
    merged_backgrounds = _merge_duplicate_containers(
        elements, ocr_observations, (width, height)
    )
    _anchor_table_text(elements, ocr_observations)
    _repartition_table_rows(elements, ocr_observations)
    _fit_table_text(
        elements,
        ocr_observations,
        _pixel_edges(image_path, width, height),
    )
    # A description the plan flattened into one line is a paragraph in the
    # picture; OCR still knows where its lines break.  Rebuild it before the
    # snap, which would otherwise pin the node back onto its first line.
    _reflow_paragraphs(elements, ocr_observations, image_path, background)
    # A sentence measured from the wrong origin prints through its own border.
    _snap_text_to_ocr(elements, ocr_observations)
    # Words the plan never carried: OCR read them, so they are on the page.
    _promote_ocr_text(elements, image_path, (width, height), ocr_observations)
    # Pixel recovery needs the words.  Without OCR lines there is no way to
    # tell an unmodelled line of text from a logo, and guessing adds a crop of
    # words that are already on the canvas as vectors.
    if ocr_observations:
        # Bars are the one element every perception stage drops: too thin for a
        # container, no words, not a glyph.
        _recover_saturated_bars(elements, image_path, width, height)
        # Words arrive without the chip behind them; the pixels still have it.
        _recover_text_backdrops(elements, image_path, width, height)
        # Cards and empty fields three channels off the page: invisible to the
        # badge threshold, and the difference between a layout and a pile.
        _recover_page_fill(elements, image_path, width, height, background)
        _recover_soft_panels(elements, image_path, width, height, background)
        _recover_colour_regions(elements, image_path, width, height, background)
        # Capsules whose corners are rounded away fall under the solid pass's
        # fill share and are not a panel either; they are what a nav item sits in.
        _recover_pill_shapes(elements, image_path, width, height, background)
        # Logos and oversized glyphs are the marks no stage reports.
        _recover_visual_regions(
            elements, image_path, width, height, ocr_observations, background
        )
    # 页面最大的那行是展示标题：它按角色定字重，不按平均笔宽。
    _restore_display_weight(elements, image_path, width, height)
    _drop_page_coloured_shells(elements, background)
    # Icon captions the model invented have to go before the duplicate pass:
    # "search" over a magnifier looks like a label that a real one duplicates.
    _drop_icon_descriptor_labels(elements, ocr_observations)
    _drop_coincident_texts(elements, background)
    # A paragraph and the tail of it, modelled twice.  The overlap test above
    # only sees boxes that cover each other; a wrapped remainder sits *below*
    # the paragraph, so it survives and both get printed — in the browser as an
    # overflowing line, in Figma as two lines on top of each other.
    _drop_paragraph_tails(elements)
    # 一个框被另一个更大的框包住、用词还对得上：同一行的第二次建模。
    _drop_contained_texts(elements)
    # 同一带里被更大文本框整个盖住、而原图在它自己的位置没有任何 OCR 支撑的，
    # 是方案把一句话放错了地方（marketplace 那四个价格就是）。
    _drop_nested_texts(elements, ocr_observations)
    # 三张盲测图暴露的共同根因：同一块内容被 grounding 与 OCR 各描述了一次。
    # 这三道闸都按**位置与画面证据**判，不按字符串像不像：
    #   1 画面里那块地方本来就没有字（图标被起了个名字）→ 删掉那个名字；
    #   2 同一页同一句出现两次、只有一处有 OCR 支撑 → 删没有支撑的那份；
    #   3 两块文本框压在同一片区域 → 只留一份（空间互斥，与字符串无关）。
    _drop_unbacked_labels(elements, image_path, width, height, ocr_observations)
    _drop_unsupported_duplicate_labels(elements, ocr_observations)
    _spatial_text_nms(elements, ocr_observations, background)
    # 表格正文字号不许超过同表行中位数 + 2px：盲测里日工时的 34px 单元格
    # 在 30px 行高里直接印到了邻行上。
    _fit_text_to_box(elements)
    _clamp_table_fonts(elements)
    # 图片裁片与它旁边的文字：补全被切断的形状 / 把裁片裁到文字开始处，
    # 并清掉落在文字上的冒名控件。
    if _SETTLE_PICTURES_ENABLED:
        _settle_pictures_and_controls(
            elements, image_path, width, height, ocr_observations
        )
    # 倾斜的印章：角度从裁片上量，写到矢量字上，水平重复的那一份删掉。
    _measure_stamp_rotations(elements, image_path, width, height)
    _separate_badge_icon_text(elements)
    # A chip whose word was absorbed by the row's own line prints empty; OCR
    # read that chip's word at the chip's coordinates.
    _restore_chip_labels(elements, image_path, (width, height), ocr_observations)
    # A control measured over a table belongs to the words OCR read for it,
    # which are somewhere else entirely.
    _resolve_misfiled_controls(elements, ocr_observations, image_path)
    # 晚段再互斥一次：芯片标签（`text:chip-*`）与 OCR 提升是**在第一次 NMS 之后**
    # 才进列表的，Gmail 的"50"就是这么压在主题行首字上的。规则是幂等的，跑两次
    # 只是把后进的这批也纳进来。
    _spatial_text_nms(elements, ocr_observations, background)
    # 控件自带标签，OCR 也带一份：同一个盒子里两遍印刷，这里只留一遍。
    _merge_control_labels(elements, ocr_observations)
    # Nothing may stick out of the box that owns it.
    _constrain_children(elements, background)
    # A member standing on the page's own surface was never inside the dialog
    # that claims it: give it back, then cut the dialog down to its own paint.
    _evict_cross_plane_members(
        elements, image_path, (width, height), background, ocr_observations
    )
    _trim_to_fill_boundary(elements, image_path, (width, height), background)
    # After the trimmers, before the frames: a container measured short of its
    # own paint leaves a band of page where the picture has colour — inventory's
    # header, sixteen rows of it.  Run any earlier and the trim passes take the
    # grown edge straight back.  (_extend_solid_edges owns that job now; the
    # card snap moved behind the frame lock and only paints.)
    _extend_solid_edges(elements, image_path, width, height, background)
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
    # Batching moves a non-member that overlapped a frame's run to *after* the
    # run, which is how a white block ends up on top of the table it belongs
    # under.  Check the final order, not the one the boxes were authored in.
    _audit_filled_occluders(elements, background)
    layout_frames = _keep_renderable_frames(elements, written_frames)
    # 帧结构已经锁定（谁是谁的成员、谁在第几帧，都不会再变）。装饰层从这里开始
    # 只画不改结构：卡片的 1px 轮廓、被切开的两张卡之间的底板、芯片外那一圈细线。
    # 放在锁之后，加多少笔都不会掉帧或增帧——这是之前 13→17 帧的真因。
    decoration = _decorate_locked_frames(
        elements, image_path, width, height, background
    )
    # Last, and outside every frame: a patch is an overlay on the drawing, not a
    # member of it.  Joining a frame would change that frame's member list and,
    # with it, the paint order of everything the frame contains.
    _apply_residual_patches(elements, image_path, (width, height), residual_regions)
    # 补丁是从原图裁的像素，它盖住的矢量文字就是第二遍印刷。
    _drop_text_under_patches(elements)
    # 然后把"仍然压在字上的不透明块"清掉：补丁裁开、容器降层。VLM 仲裁看不见
    # 这一类缺陷——树里节点在，只是被埋了。
    occlusion = _guard_text_occlusion(
        elements, image_path, (width, height), ocr_observations
    )
    # 降层可能让某个帧不再是"成员都排在它之后"，复核一次，别让计数说谎。
    layout_frames = _keep_renderable_frames(elements, layout_frames)
    # 设计树按绘制序输出：打开文件看到的第一层就是页面底色，最后一层是文字
    # 与补丁。纯排序，不改任何几何或 zIndex。
    layers_written = _order_layers(elements)
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
                    "containers": sum(
                        1 for element in elements if element.get("type") == "container"
                    ),
                    "layoutFrames": layout_frames,
                },
                "layers": {
                    "backgroundsMerged": merged_backgrounds,
                    "depthsWritten": layers_written,
                    "occlusion": dict(occlusion),
                },
                "assetClaim": "display-replacement-only",
                "originalAssetClaimed": False,
            },
        },
    }
