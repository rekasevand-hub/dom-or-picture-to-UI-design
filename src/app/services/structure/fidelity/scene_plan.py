"""Build one canonical owner graph from inventory and source geometry."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from src.app.services.structure.fidelity.contracts import (
    SCENE_PLAN_SCHEMA_VERSION,
    normalize_bbox,
    normalize_match_text,
)

_CONTROL_TYPES = {
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
}
_TABLE_KINDS = {"table-cell", "table-header"}
_REQUIRED_NODE_FIELDS = {
    "id",
    "parent_id",
    "type",
    "role",
    "bbox",
    "content_ref",
    "geometry_ref",
    "children",
}


def _bbox_contains(outer: list[int], inner: list[int]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[0] + outer[2] >= inner[0] + inner[2]
        and outer[1] + outer[3] >= inner[1] + inner[3]
    )


def _intersection_over_union(left: list[int], right: list[int]) -> float:
    left_x, left_y, left_w, left_h = left
    right_x, right_y, right_w, right_h = right
    intersection_width = max(
        0,
        min(left_x + left_w, right_x + right_w) - max(left_x, right_x),
    )
    intersection_height = max(
        0,
        min(left_y + left_h, right_y + right_h) - max(left_y, right_y),
    )
    intersection = intersection_width * intersection_height
    union = left_w * left_h + right_w * right_h - intersection
    return intersection / union if union > 0 else 0.0


def _role_id(role: str, source_id: str) -> str:
    role_slug = re.sub(r"[^a-z0-9_-]+", "-", role.strip().lower()).strip("-")
    return f"{role_slug or 'container'}:{source_id}"


def _source_index(source_ref: Any, collection: str) -> int | None:
    match = re.fullmatch(rf"graph\.{collection}\[(\d+)\](?:\..*)?", str(source_ref))
    return int(match.group(1)) if match else None


def _geometry_ref(
    geometry_by_content: Mapping[str, Mapping[str, Any]],
    content_ref: str,
    *,
    fallback: str = "",
) -> str:
    item = geometry_by_content.get(content_ref)
    return str(item.get("id") if item is not None else fallback)


def _node_type(item: Mapping[str, Any]) -> str:
    kind = str(item.get("kind") or "")
    control_type = str(item.get("control_type") or "").lower()
    if kind == "control" or control_type in _CONTROL_TYPES:
        return "control"
    if kind == "asset":
        return "image"
    return "text"


def _node_from_item(
    item: Mapping[str, Any],
    *,
    width: int,
    height: int,
    geometry_by_content: Mapping[str, Mapping[str, Any]],
    parent_id: str | None,
) -> dict[str, Any] | None:
    content_ref = str(item.get("id") or "")
    bbox = normalize_bbox(item.get("bbox"), width, height)
    if not content_ref or bbox is None:
        return None
    node_type = _node_type(item)
    node = {
        "id": content_ref,
        "parent_id": parent_id,
        "type": node_type,
        "role": str(
            item.get("role")
            or ("table-cell" if item.get("kind") in _TABLE_KINDS else "")
            or item.get("kind")
            or ""
        ),
        "bbox": bbox,
        "content_ref": content_ref,
        "geometry_ref": _geometry_ref(geometry_by_content, content_ref),
        "children": [],
        "text": str(item.get("text") or ""),
        "source_ref": str(item.get("source_ref") or ""),
        "authority": str(item.get("authority") or ""),
        "table_id": str(item.get("table_id") or ""),
        "reference_only": bool(item.get("reference_only")),
        "original": bool(item.get("original")),
    }
    if node_type == "control":
        node["control_type"] = str(item.get("control_type") or "")
        node["state"] = str(item.get("state") or "")
        node["text_owner_ref"] = None
    return node


def _container_parents(
    graph: Mapping[str, Any],
    container_nodes: list[dict[str, Any]],
) -> dict[str, str | None]:
    graph_containers = graph.get("containers")
    if not isinstance(graph_containers, list):
        return {}
    result: dict[str, str | None] = {}
    for index, container in enumerate(graph_containers):
        if not isinstance(container, Mapping):
            continue
        node_id = container_nodes[index]["id"] if index < len(container_nodes) else ""
        parent_source = str(container.get("parent") or "")
        parent_node = next(
            (
                node["id"]
                for item, node in zip(graph_containers, container_nodes)
                if isinstance(item, Mapping)
                and str(item.get("id") or "") == parent_source
            ),
            None,
        )
        result[node_id] = parent_node
    return result


def _element_parent(
    graph: Mapping[str, Any],
    source_ref: str,
    item_bbox: list[int],
    container_nodes: list[dict[str, Any]],
) -> str | None:
    index = _source_index(source_ref, "elements")
    if index is not None:
        elements = graph.get("elements")
        if isinstance(elements, list) and index < len(elements):
            element = elements[index]
            if isinstance(element, Mapping):
                source_id = str(element.get("container") or "")
                for node in container_nodes:
                    if node["id"].endswith(f":{source_id}"):
                        return str(node["id"])
    containing = [
        node for node in container_nodes if _bbox_contains(node["bbox"], item_bbox)
    ]
    if not containing:
        return None
    return str(
        min(containing, key=lambda node: node["bbox"][2] * node["bbox"][3])["id"]
    )


def _tooltip_owner(
    control: dict[str, Any],
    text_nodes: list[dict[str, Any]],
) -> str | None:
    control_source = str(control.get("source_ref") or "")
    label = normalize_match_text(control.get("text") or "")
    if not label:
        label = normalize_match_text(control.get("label") or "")
    candidates = [
        node
        for node in text_nodes
        if node.get("role") == "control-label"
        or normalize_match_text(node.get("text") or "")
    ]
    for node in candidates:
        same_source = (
            control_source
            and str(node.get("source_ref") or "") == control_source
            and node.get("role") == "control-label"
        )
        same_text = label and normalize_match_text(node.get("text") or "") == label
        if same_source or same_text:
            return str(node["id"])
    return None


def build_scene_plan(
    graph: Mapping[str, Any],
    inventory: Mapping[str, Any],
    geometry: Mapping[str, Any],
) -> dict[str, Any]:
    """Assign each visible inventory item to one rendered owner."""
    if not isinstance(graph, Mapping):
        raise ValueError("graph must be an object")
    if not isinstance(inventory, Mapping):
        raise ValueError("inventory must be an object")
    if not isinstance(geometry, Mapping):
        raise ValueError("geometry must be an object")
    raw_size = inventory.get("image_size")
    try:
        width, height = (int(value) for value in raw_size)
    except (TypeError, ValueError):
        raise ValueError("inventory image size must contain width and height") from None
    if width <= 0 or height <= 0:
        raise ValueError("inventory image size must be positive")
    if list(geometry.get("image_size") or []) != [width, height]:
        raise ValueError("inventory and geometry image sizes must match")

    geometry_items = [
        item
        for item in geometry.get("items") or []
        if isinstance(item, Mapping) and item.get("content_ref")
    ]
    geometry_by_content = {str(item["content_ref"]): item for item in geometry_items}
    graph_containers = graph.get("containers")
    if not isinstance(graph_containers, list):
        graph_containers = []

    container_nodes: list[dict[str, Any]] = []
    geometry_containers = [
        item
        for item in geometry.get("items") or []
        if isinstance(item, Mapping) and item.get("kind") == "container"
    ]
    for index, geometry_item in enumerate(geometry_containers):
        source_index = _source_index(
            geometry_item.get("source_ref"),
            "containers",
        )
        source = (
            graph_containers[source_index]
            if source_index is not None and source_index < len(graph_containers)
            else {}
        )
        if not isinstance(source, Mapping):
            source = {}
        bbox = normalize_bbox(
            source.get("bbox") or geometry_item.get("bbox"),
            width,
            height,
        )
        if bbox is None:
            continue
        source_id = str(source.get("id") or f"container-{index}")
        role = str(source.get("role") or geometry_item.get("role") or "container")
        container_nodes.append(
            {
                "id": _role_id(role, source_id),
                "parent_id": None,
                "type": "container",
                "role": role,
                "bbox": bbox,
                "content_ref": None,
                "geometry_ref": str(geometry_item.get("id") or ""),
                "children": [],
                "source_ref": str(geometry_item.get("source_ref") or ""),
            }
        )
    parent_by_node = _container_parents(graph, container_nodes)
    for node in container_nodes:
        node["parent_id"] = parent_by_node.get(str(node["id"]))

    nodes: list[dict[str, Any]] = [*container_nodes]
    table_nodes: list[dict[str, Any]] = []
    for table in inventory.get("tables") or []:
        if not isinstance(table, Mapping):
            continue
        table_id = str(table.get("id") or "")
        bbox = normalize_bbox(table.get("bbox"), width, height)
        if not table_id or bbox is None:
            continue
        parent = _element_parent(
            graph,
            str(table.get("source_ref") or ""),
            bbox,
            container_nodes,
        )
        table_nodes.append(
            {
                "id": f"table-node:{table_id}",
                "parent_id": parent,
                "type": "table",
                "role": "table",
                "bbox": bbox,
                "content_ref": table_id,
                "geometry_ref": _geometry_ref(geometry_by_content, table_id),
                "children": [],
                "source_ref": str(table.get("source_ref") or ""),
            }
        )
    nodes.extend(table_nodes)

    table_by_id = {
        str(table.get("id") or ""): table
        for table in inventory.get("tables") or []
        if isinstance(table, Mapping)
    }
    candidates: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    text_candidates: list[dict[str, Any]] = []
    for item in inventory.get("items") or []:
        if not isinstance(item, Mapping) or item.get("kind") == "unknown":
            continue
        bbox = normalize_bbox(item.get("bbox"), width, height)
        if bbox is None:
            suppressed.append(
                {
                    "content_ref": str(item.get("id") or ""),
                    "source_ref": str(item.get("source_ref") or ""),
                    "reason": "invalid-bbox",
                    "replacement_ref": None,
                }
            )
            continue
        table_id = str(item.get("table_id") or "")
        if table_id:
            parent_id = f"table-node:{table_id}"
        else:
            parent_id = _element_parent(
                graph,
                str(item.get("source_ref") or ""),
                bbox,
                container_nodes,
            )
        node = _node_from_item(
            item,
            width=width,
            height=height,
            geometry_by_content=geometry_by_content,
            parent_id=parent_id,
        )
        if node is None:
            continue
        node["label"] = str(item.get("label") or "")
        if node["type"] == "text":
            text_candidates.append(node)
        candidates.append(node)

    table_owner_by_text: dict[str, dict[str, Any]] = {}
    for node in candidates:
        if node.get("table_id"):
            key = normalize_match_text(node.get("text"))
            if key:
                table_owner_by_text.setdefault(key, node)

    accepted: list[dict[str, Any]] = []
    content_refs: set[str] = set()
    for node in candidates:
        content_ref = str(node["content_ref"])
        if content_ref in content_refs:
            suppressed.append(
                {
                    "content_ref": content_ref,
                    "source_ref": str(node.get("source_ref") or ""),
                    "reason": "duplicate-content-ref",
                    "replacement_ref": None,
                }
            )
            continue
        if node["type"] == "text" and not node.get("table_id"):
            text_key = normalize_match_text(node.get("text"))
            table_owner = table_owner_by_text.get(text_key)
            if table_owner is not None:
                table_id = str(table_owner.get("table_id") or "")
                table_bbox = normalize_bbox(
                    (table_by_id.get(table_id) or {}).get("bbox"),
                    width,
                    height,
                )
                if table_bbox is not None and _bbox_contains(table_bbox, node["bbox"]):
                    suppressed.append(
                        {
                            "content_ref": content_ref,
                            "source_ref": str(node.get("source_ref") or ""),
                            "reason": "table-cell-owner-authoritative",
                            "replacement_ref": table_owner["content_ref"],
                        }
                    )
                    continue
        duplicate = next(
            (
                existing
                for existing in accepted
                if existing["type"] == node["type"] == "text"
                and not existing.get("table_id")
                and not node.get("table_id")
                and normalize_match_text(existing.get("text"))
                == normalize_match_text(node.get("text"))
                and normalize_match_text(existing.get("text"))
                and _intersection_over_union(existing["bbox"], node["bbox"]) >= 0.7
            ),
            None,
        )
        if duplicate is not None:
            suppressed.append(
                {
                    "content_ref": content_ref,
                    "source_ref": str(node.get("source_ref") or ""),
                    "reason": "duplicate-text-owner",
                    "replacement_ref": duplicate["content_ref"],
                }
            )
            continue
        content_refs.add(content_ref)
        accepted.append(node)

    text_nodes = [node for node in accepted if node["type"] == "text"]
    for node in accepted:
        if node["type"] != "control":
            continue
        owner = _tooltip_owner(node, text_nodes)
        node["text_owner_ref"] = owner
    nodes.extend(accepted)

    nodes_by_id = {str(node["id"]): node for node in nodes}
    for node in nodes:
        parent_id = str(node.get("parent_id") or "")
        if parent_id and parent_id in nodes_by_id:
            nodes_by_id[parent_id]["children"].append(node["id"])
        elif parent_id:
            node["parent_id"] = None
    for node in nodes:
        node["children"] = sorted(
            set(node["children"]),
            key=lambda value: next(
                (
                    (
                        int(item["bbox"][1]),
                        int(item["bbox"][0]),
                        str(value),
                    )
                    for item in nodes
                    if item["id"] == value
                ),
                (0, 0, str(value)),
            ),
        )
    nodes.sort(
        key=lambda node: (
            0 if node["type"] in {"container", "table"} else 1,
            int(node["bbox"][1]),
            int(node["bbox"][0]),
            str(node["id"]),
        )
    )
    return {
        "schema_version": SCENE_PLAN_SCHEMA_VERSION,
        "status": "planned",
        "reference_id": str(inventory.get("reference_id") or ""),
        "image_size": [width, height],
        "coordinate_basis": "source-pixel-top-left",
        "nodes": nodes,
        "suppressed": suppressed,
        "ownership": {
            "content_ref": "unique",
            "slice_layout_authority": "forbidden",
            "source": "content_inventory+geometry_manifest",
        },
    }


def _validate_plan(plan: Mapping[str, Any]) -> tuple[int, int]:
    if not isinstance(plan, Mapping):
        raise ValueError("scene plan must be an object")
    if plan.get("schema_version") != SCENE_PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported scene plan schema_version")
    try:
        width, height = (int(value) for value in plan.get("image_size"))
    except (TypeError, ValueError):
        raise ValueError(
            "scene plan image size must contain width and height"
        ) from None
    nodes = plan.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("scene plan nodes must be a list")
    ids: set[str] = set()
    content_refs: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            raise ValueError(f"scene plan nodes[{index}] must be an object")
        missing = _REQUIRED_NODE_FIELDS - set(node)
        if missing:
            raise ValueError(
                f"scene plan nodes[{index}] is missing " + ", ".join(sorted(missing))
            )
        node_id = str(node.get("id") or "")
        if not node_id or node_id in ids:
            raise ValueError(f"duplicate scene node id: {node_id}")
        ids.add(node_id)
        content_ref = str(node.get("content_ref") or "")
        if content_ref:
            if content_ref in content_refs:
                raise ValueError(f"duplicate content owner: {content_ref}")
            content_refs.add(content_ref)
        if normalize_bbox(node.get("bbox"), width, height) is None:
            raise ValueError(f"scene node {node_id} has invalid bbox")
        if not isinstance(node.get("children"), list):
            raise ValueError(f"scene node {node_id} children must be a list")
    for node in nodes:
        parent_id = str(node.get("parent_id") or "")
        if parent_id and parent_id not in ids:
            raise ValueError(f"scene node {node['id']} has unknown parent {parent_id}")
    return width, height


def apply_scene_plan(
    graph: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Annotate and prune the canonical graph without changing coordinates."""
    if not isinstance(graph, Mapping):
        raise ValueError("graph must be an object")
    width, height = _validate_plan(plan)
    applied = copy.deepcopy(dict(graph))
    if (
        int(applied.get("image_w") or width) != width
        or int(applied.get("image_h") or height) != height
    ):
        raise ValueError("scene plan and graph image sizes must match")

    owners_by_source: dict[str, dict[str, Any]] = {}
    for node in plan["nodes"]:
        source_ref = str(node.get("source_ref") or "")
        if source_ref:
            owners_by_source[source_ref] = dict(node)

    for collection in ("containers", "elements", "tables"):
        records = applied.get(collection)
        if not isinstance(records, list):
            continue
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            owner = owners_by_source.get(f"graph.{collection}[{index}]")
            if owner is None:
                continue
            record["sceneOwnerId"] = owner["id"]
            record["contentRef"] = owner.get("content_ref")
            record["geometryRef"] = owner.get("geometry_ref")
            record["sceneParentId"] = owner.get("parent_id")
            if collection == "elements" and owner.get("type") == "control":
                record["textOwnerRef"] = owner.get("text_owner_ref")

    suppressed_source_refs = {
        str(item.get("source_ref") or "")
        for item in plan.get("suppressed") or []
        if isinstance(item, Mapping) and item.get("source_ref")
    }
    elements = applied.get("elements")
    if isinstance(elements, list):
        applied["elements"] = [
            element
            for index, element in enumerate(elements)
            if f"graph.elements[{index}]" not in suppressed_source_refs
        ]
    applied["scenePlan"] = copy.deepcopy(dict(plan))
    applied["sceneOwnership"] = {
        "schema_version": plan["schema_version"],
        "node_count": len(plan["nodes"]),
        "suppressed_count": len(plan.get("suppressed") or []),
    }
    return applied
