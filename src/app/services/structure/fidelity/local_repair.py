"""Crop-scoped Grounding repair adapter with page-coordinate translation."""

from __future__ import annotations

import copy
import hashlib
import io
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from src.app.services.structure.fidelity.contracts import (
    canonical_json,
    stable_id,
)


class GroundingCropBackend(Protocol):
    def ground(
        self,
        image_path: str | Path,
        image_w: int,
        image_h: int,
    ) -> dict[str, Any]: ...


def _request_bbox(
    value: Any,
    width: int,
    height: int,
    *,
    padding: int,
) -> list[int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("repair bbox must contain x, y, width, and height")
    if any(isinstance(item, bool) for item in value):
        raise ValueError("repair bbox must contain numeric values")
    try:
        x, y, box_width, box_height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("repair bbox must contain numeric values") from None
    if box_width <= 0 or box_height <= 0:
        raise ValueError("repair bbox must be positive")
    left = max(0, x - max(0, padding))
    top = max(0, y - max(0, padding))
    right = min(width, x + box_width + max(0, padding))
    bottom = min(height, y + box_height + max(0, padding))
    if right <= left or bottom <= top:
        raise ValueError("repair bbox is outside the image canvas")
    return [left, top, right - left, bottom - top]


def _translate_bbox(value: Any, offset_x: int, offset_y: int) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(isinstance(item, bool) for item in value):
        return None
    try:
        x, y, width, height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError, OverflowError):
        return None
    if width <= 0 or height <= 0:
        return None
    return [x + offset_x, y + offset_y, width, height]


def _translate_operation(
    operation: Mapping[str, Any],
    offset_x: int,
    offset_y: int,
) -> dict[str, Any]:
    translated = copy.deepcopy(dict(operation))
    if "bbox" in translated:
        bbox = _translate_bbox(translated["bbox"], offset_x, offset_y)
        if bbox is not None:
            translated["bbox"] = bbox
    node = translated.get("node")
    if isinstance(node, Mapping):
        node_value = copy.deepcopy(dict(node))
        bbox = _translate_bbox(node_value.get("bbox"), offset_x, offset_y)
        if bbox is not None:
            node_value["bbox"] = bbox
        translated["node"] = node_value
    nodes = translated.get("nodes")
    if isinstance(nodes, list):
        translated_nodes: list[Any] = []
        for value in nodes:
            if not isinstance(value, Mapping):
                continue
            node_value = copy.deepcopy(dict(value))
            bbox = _translate_bbox(node_value.get("bbox"), offset_x, offset_y)
            if bbox is not None:
                node_value["bbox"] = bbox
            translated_nodes.append(node_value)
        translated["nodes"] = translated_nodes
    return translated


def _parent_for_request(
    request: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> str | None:
    nodes = {
        str(node.get("id")): node
        for node in plan.get("nodes") or []
        if isinstance(node, Mapping)
    }
    targets = [str(value) for value in request.get("target_ids") or [] if str(value)]
    for target in targets:
        node = nodes.get(target)
        if node is None:
            continue
        if node.get("type") in {"table", "container"}:
            return str(node["id"])
        parent_id = str(node.get("parent_id") or "")
        if parent_id:
            return parent_id
    for node in nodes.values():
        if node.get("type") == "table":
            return str(node["id"])
    for node in nodes.values():
        if node.get("type") == "container" and node.get("role") in {
            "main",
            "form",
            "page",
        }:
            return str(node["id"])
    return targets[0] if targets else None


def _node_type(value: Any) -> str:
    candidate = str(value or "text").lower()
    if candidate in {"image", "avatar"}:
        return "image"
    if candidate in {
        "button",
        "checkbox",
        "icon-button",
        "input",
        "navigation",
        "pagination",
        "radio",
        "select",
        "textarea",
        "toggle",
    }:
        return "control"
    if candidate == "table":
        return "table"
    if candidate == "container":
        return "container"
    return "text"


def _element_operations(
    raw: Mapping[str, Any],
    request: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    offset_x: int,
    offset_y: int,
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    parent_id = _parent_for_request(request, plan)
    for index, item in enumerate(raw.get("elements") or []):
        if not isinstance(item, Mapping):
            continue
        bbox = _translate_bbox(item.get("bbox"), offset_x, offset_y)
        if bbox is None:
            continue
        node_type = _node_type(item.get("controlType") or item.get("type"))
        text = str(item.get("text") or item.get("value") or "")
        content_ref = str(item.get("content_ref") or "")
        if not content_ref:
            content_ref = stable_id(
                "repair-content",
                node_type,
                text,
                bbox,
                request.get("id"),
                index,
            )
        node_id = stable_id(
            "repair-node",
            content_ref,
            bbox,
            request.get("id"),
        )
        node = {
            "id": node_id,
            "parent_id": parent_id,
            "type": node_type,
            "role": str(
                item.get("role") or item.get("controlType") or item.get("type") or ""
            ),
            "bbox": bbox,
            "content_ref": content_ref,
            "geometry_ref": "",
            "children": [],
            "text": text,
            "authority": "grounding-local-repair",
        }
        if node_type == "control":
            node["control_type"] = str(
                item.get("controlType") or item.get("type") or ""
            )
            node["state"] = str(item.get("controlState") or item.get("state") or "")
            node["text_owner_ref"] = None
        if node_type == "image":
            node["reference_only"] = True
            node["original"] = False
        operations.append({"op": "add_node", "node": node})
    return operations


class GroundingLocalRepairer:
    """Read one expanded page region and return a ScenePlan patch."""

    def __init__(
        self,
        backend: GroundingCropBackend,
        *,
        crop_padding: int = 0,
        max_cache_entries: int = 64,
    ) -> None:
        if crop_padding < 0:
            raise ValueError("crop_padding must be non-negative")
        if max_cache_entries <= 0:
            raise ValueError("max_cache_entries must be positive")
        self.backend = backend
        self.crop_padding = int(crop_padding)
        self.max_cache_entries = int(max_cache_entries)
        self._cache: dict[str, dict[str, Any] | None] = {}
        self.backend_calls = 0
        self.cache_hits = 0

    def _cache_key(
        self,
        crop_digest: str,
        request: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> str:
        target_ids = [str(value) for value in request.get("target_ids") or []]
        target_nodes = [
            node
            for node in plan.get("nodes") or []
            if isinstance(node, Mapping) and str(node.get("id")) in target_ids
        ]
        return hashlib.sha256(
            canonical_json(
                {
                    "crop_sha256": crop_digest,
                    "request": request,
                    "target_nodes": target_nodes,
                }
            ).encode("utf-8")
        ).hexdigest()

    def repair(
        self,
        request: Mapping[str, Any],
        image_path: str | Path,
        plan: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if not isinstance(request, Mapping):
            raise ValueError("request must be an object")
        if not isinstance(plan, Mapping):
            raise ValueError("plan must be an object")
        source = Path(image_path)
        if not source.is_file():
            raise FileNotFoundError(source)
        with Image.open(source) as opened:
            image = opened.convert("RGB")
            page_width, page_height = image.size
            plan_size = plan.get("image_size")
            if plan_size is not None and list(plan_size) != [
                page_width,
                page_height,
            ]:
                raise ValueError("plan and source image sizes must match")
            crop_bbox = _request_bbox(
                request.get("bbox"),
                page_width,
                page_height,
                padding=self.crop_padding,
            )
            x, y, width, height = crop_bbox
            crop = image.crop((x, y, x + width, y + height))
            buffer = io.BytesIO()
            crop.save(buffer, format="PNG")
            crop_bytes = buffer.getvalue()
            crop_digest = hashlib.sha256(crop_bytes).hexdigest()
            cache_key = self._cache_key(crop_digest, request, plan)
            if cache_key in self._cache:
                self.cache_hits += 1
                return copy.deepcopy(self._cache[cache_key])
            with tempfile.TemporaryDirectory(prefix="grounding-repair-") as temp:
                crop_path = Path(temp) / "region.png"
                crop_path.write_bytes(crop_bytes)
                self.backend_calls += 1
                raw = self.backend.ground(crop_path, width, height)

        operations: list[dict[str, Any]] = []
        if isinstance(raw, Mapping) and isinstance(raw.get("operations"), list):
            operations = [
                _translate_operation(operation, x, y)
                for operation in raw["operations"]
                if isinstance(operation, Mapping)
            ]
        elif isinstance(raw, Mapping):
            operations = _element_operations(
                raw,
                request,
                plan,
                offset_x=x,
                offset_y=y,
            )
        if not operations:
            if len(self._cache) >= self.max_cache_entries:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = None
            return None
        patch = {
            "region_id": str(request.get("region_id") or request.get("kind") or ""),
            "target_ids": [str(value) for value in request.get("target_ids") or []],
            "reason": str(request.get("reason") or "local repair"),
            "operations": operations,
            "crop": {
                "bbox": crop_bbox,
                "size": [width, height],
                "sha256": crop_digest,
            },
            "source": "grounding-crop-repair",
        }
        if len(self._cache) >= self.max_cache_entries:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = copy.deepcopy(patch)
        return patch
