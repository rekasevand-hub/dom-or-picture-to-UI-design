from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

LAYER_TREE_SCHEMA_VERSION = "dom-layer-tree/1.0"


def build_layer_tree(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    node_ids = [f"n{index}" for index in range(len(nodes))]
    tree_nodes: dict[str, dict[str, Any]] = {}
    roots: list[str] = []

    for index, source in enumerate(nodes):
        node_id = node_ids[index]
        parent_index = source.get("pIdx")
        parent_id = None
        if (
            isinstance(parent_index, int)
            and not isinstance(parent_index, bool)
            and 0 <= parent_index < len(nodes)
            and parent_index != index
        ):
            parent_id = node_ids[parent_index]
        if parent_id is None:
            roots.append(node_id)
        tree_nodes[node_id] = {
            "sourceIndex": index,
            "parentId": parent_id,
            "children": [],
            "tag": str(source.get("tag") or ""),
            "bbox": [
                source.get("x", 0),
                source.get("y", 0),
                source.get("w", 0),
                source.get("h", 0),
            ],
        }

    for node_id in node_ids:
        node = tree_nodes[node_id]
        parent_id = node["parentId"]
        if parent_id is not None:
            tree_nodes[parent_id]["children"].append(node_id)

    return {
        "schema_version": LAYER_TREE_SCHEMA_VERSION,
        "roots": roots,
        "nodes": tree_nodes,
    }
