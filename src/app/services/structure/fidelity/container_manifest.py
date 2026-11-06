"""Separate semantic source regions from fixed-canvas Figma authoring frames."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from src.app.services.structure.fidelity.contracts import (
    CONTAINER_MANIFEST_SCHEMA_VERSION,
    normalize_bbox,
)

_FRAME_NODE_TYPES = {"container", "table", "control"}


def _source_bbox(
    value: Any,
    width: int,
    height: int,
    *,
    name: str,
) -> list[int]:
    bbox = normalize_bbox(value, width, height)
    if bbox is None:
        raise ValueError(f"{name} must be a positive source-pixel bbox")
    return bbox


def _local_bbox(value: Any, origin_x: int, origin_y: int) -> list[int]:
    try:
        x, y, width, height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("scene node bbox is invalid") from None
    if width <= 0 or height <= 0:
        raise ValueError("scene node bbox is invalid")
    return [x - origin_x, y - origin_y, width, height]


def build_container_manifest(
    scene_plan: Mapping[str, Any],
    authoring_frames: Mapping[str, Mapping[str, Any] | list[int]] | None = None,
) -> dict[str, Any]:
    """Build fixed-canvas containers while preserving source geometry."""
    if not isinstance(scene_plan, Mapping):
        raise ValueError("scene_plan must be an object")
    try:
        width, height = (int(value) for value in scene_plan.get("image_size"))
    except (TypeError, ValueError):
        raise ValueError(
            "scene_plan image size must contain width and height"
        ) from None
    if width <= 0 or height <= 0:
        raise ValueError("scene_plan image size must be positive")
    nodes = scene_plan.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("scene_plan nodes must be a list")
    node_by_id = {
        str(node.get("id") or ""): node
        for node in nodes
        if isinstance(node, Mapping) and node.get("id")
    }
    overrides = copy.deepcopy(dict(authoring_frames or {}))
    unknown_overrides = set(overrides) - set(node_by_id)
    if unknown_overrides:
        raise ValueError(
            "authoring frame owner is unknown: " + ", ".join(sorted(unknown_overrides))
        )

    containers: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        node_id = str(node.get("id") or "")
        node_type = str(node.get("type") or "")
        children = [str(value) for value in node.get("children") or [] if str(value)]
        if node_type not in _FRAME_NODE_TYPES or not children:
            continue
        override = overrides.get(node_id)
        if isinstance(override, Mapping):
            raw_authoring_bbox = override.get("authoring_bbox")
            layout_mode = str(override.get("layout_mode") or "fixed-canvas-absolute")
        else:
            raw_authoring_bbox = override
            layout_mode = "fixed-canvas-absolute"
        source_bbox = _source_bbox(
            node.get("bbox"),
            width,
            height,
            name=f"{node_id}.source_bbox",
        )
        authoring_bbox = (
            _source_bbox(
                raw_authoring_bbox,
                width,
                height,
                name=f"{node_id}.authoring_bbox",
            )
            if raw_authoring_bbox is not None
            else list(source_bbox)
        )
        record = {
            "owner_id": node_id,
            "parent_id": str(node.get("parent_id") or "") or None,
            "role": str(node.get("role") or ""),
            "source_bbox": source_bbox,
            "authoring_bbox": authoring_bbox,
            "layout_mode": layout_mode,
            "source_to_authoring_offset": [
                source_bbox[0] - authoring_bbox[0],
                source_bbox[1] - authoring_bbox[1],
            ],
            "children": [child_id for child_id in children if child_id in node_by_id],
        }
        containers.append(record)
        by_id[node_id] = record

    child_transforms: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        parent_id = str(node.get("parent_id") or "")
        parent = by_id.get(parent_id)
        if parent is None:
            continue
        node_id = str(node.get("id") or "")
        try:
            node_bbox = _source_bbox(
                node.get("bbox"),
                width,
                height,
                name=f"{node_id}.bbox",
            )
        except ValueError:
            continue
        child_transforms.append(
            {
                "owner_id": node_id,
                "parent_id": parent_id,
                "source_bbox": node_bbox,
                "local_bbox": _local_bbox(
                    node_bbox,
                    int(parent["authoring_bbox"][0]),
                    int(parent["authoring_bbox"][1]),
                ),
            }
        )
    return {
        "schema_version": CONTAINER_MANIFEST_SCHEMA_VERSION,
        "status": "ready",
        "image_size": [width, height],
        "coordinate_basis": "source-pixel-top-left",
        "default_layout_mode": "fixed-canvas-absolute",
        "containers": containers,
        "child_transforms": child_transforms,
    }
