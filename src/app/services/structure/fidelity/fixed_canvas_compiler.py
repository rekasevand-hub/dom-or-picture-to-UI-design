"""Compile one fixed-canvas ScenePlan into a DesignSpec."""

from __future__ import annotations

import base64
import copy
import hashlib
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
    return {
        "id": str(node.get("id") or ""),
        "type": "text",
        "x": render_x,
        "y": render_y,
        "width": render_width,
        "height": render_height,
        "text": text,
        "style": {
            "textColor": style["textColor"],
            "fontSize": style["fontSize"],
            "fontWeight": style["fontWeight"],
            "fontFamily": style["fontFamily"],
            "textAlign": style["textAlign"],
        },
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
    style_spec = {
        "fillColor": fill,
        "borderColor": _sample_border_color(image_path, bbox, fill),
        "borderWidth": 1,
        "textColor": style["textColor"],
        "fontSize": style["fontSize"],
        "fontWeight": "normal",
        "fontFamily": style["fontFamily"],
        "textAlign": "left",
        "borderRadius": 6 if box_width >= 24 and box_height >= 20 else 0,
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
            "grouping_status": "planned",
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


def _container_element(
    node: Mapping[str, Any],
    *,
    image_path: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    from src.app.services.structure.image_contract import _dominant_color

    bbox = _node_bbox(node, width, height)
    role = str(node.get("role") or "")
    render_bbox = _container_render_box(image_path, bbox, role)
    x, y, box_width, box_height = render_bbox
    return {
        "id": str(node.get("id") or ""),
        "type": "container",
        "x": x,
        "y": y,
        "width": box_width,
        "height": box_height,
        "text": "",
        "style": {"fillColor": _dominant_color(image_path, render_bbox, inset=2)},
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
    elements = [*containers, *decorations, *leaves]
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
                },
                "assetClaim": "display-replacement-only",
                "originalAssetClaimed": False,
            },
        },
    }
