from __future__ import annotations

import copy
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

COMPONENT_PATTERNS_SCHEMA_VERSION = "dom-component-patterns/1.0"

_VISUAL_TAGS = {"img", "svg", "video", "canvas", "picture", "object"}
_INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea"}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _bbox(node: Mapping[str, Any]) -> list[int]:
    return [
        max(0, _int(node.get("x"))),
        max(0, _int(node.get("y"))),
        max(0, _int(node.get("w"))),
        max(0, _int(node.get("h"))),
    ]


def _tag(node: Mapping[str, Any]) -> str:
    return str(node.get("tag") or "").strip().lower()


def _role(node: Mapping[str, Any]) -> str:
    return str(node.get("role") or "").strip().lower()


def _class_tokens(node: Mapping[str, Any]) -> str:
    values = sorted(
        {
            token
            for token in re.split(r"\s+", str(node.get("clsAll") or "").strip())
            if token
        }
    )
    return ".".join(values)


def _source_indices(component: Mapping[str, Any]) -> list[int]:
    values = component.get("sourceDomIndices")
    if not isinstance(values, list):
        return []
    return [
        value
        for value in values
        if isinstance(value, int) and not isinstance(value, bool)
    ]


def _parents(nodes: Sequence[Mapping[str, Any]]) -> list[int | None]:
    result: list[int | None] = [None] * len(nodes)
    for index, node in enumerate(nodes):
        parent = node.get("pIdx")
        if (
            isinstance(parent, int)
            and not isinstance(parent, bool)
            and 0 <= parent < len(nodes)
            and parent != index
        ):
            result[index] = parent
    return result


def _children(parents: Sequence[int | None]) -> list[list[int]]:
    result: list[list[int]] = [[] for _ in parents]
    for index, parent in enumerate(parents):
        if parent is not None:
            result[parent].append(index)
    return result


def _ancestors(index: int, parents: Sequence[int | None]) -> list[int]:
    result: list[int] = []
    seen = {index}
    current = parents[index]
    while current is not None and current not in seen:
        result.append(current)
        seen.add(current)
        current = parents[current]
    return result


def _descendants(index: int, children: Sequence[Sequence[int]]) -> list[int]:
    result: list[int] = []
    stack = list(reversed(children[index]))
    seen = {index}
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        result.append(current)
        stack.extend(reversed(children[current]))
    return result


def _bucket(value: int) -> int:
    return min(max(0, int(value)), 3)


def _position_mode(node: Mapping[str, Any]) -> str:
    position = str(node.get("position") or "static").strip().lower()
    return "out-of-flow" if position in {"absolute", "fixed"} else "flow"


def _is_visual(node: Mapping[str, Any]) -> bool:
    if _tag(node) in _VISUAL_TAGS or bool(node.get("assetSrc")):
        return True
    layers = node.get("backgroundLayers")
    return isinstance(layers, list) and any(
        isinstance(layer, Mapping) and layer.get("kind") in {"image", "gradient"}
        for layer in layers
    )


def _is_interactive(node: Mapping[str, Any]) -> bool:
    return (
        bool(node.get("interactive"))
        or _tag(node) in _INTERACTIVE_TAGS
        or _role(node) in {"button", "link", "textbox", "combobox"}
    )


def _structure_counts(
    index: int,
    nodes: Sequence[Mapping[str, Any]],
    parents: Sequence[int | None],
    children: Sequence[Sequence[int]],
) -> dict[str, int]:
    descendants = _descendants(index, children)
    interactive = {
        current
        for current in descendants
        if _is_interactive(nodes[current])
    }
    visual_count = sum(_is_visual(nodes[current]) for current in descendants)
    interactive_count = len(interactive)
    text_count = 0
    for current in descendants:
        if not str(nodes[current].get("text") or "").strip():
            continue
        if current in interactive or any(
            ancestor in interactive for ancestor in _ancestors(current, parents)
        ):
            continue
        text_count += 1
    return {
        "visual": _bucket(visual_count),
        "text": _bucket(text_count),
        "interactive": _bucket(interactive_count),
    }


def _structural_signature(counts: Mapping[str, int]) -> str:
    return (
        f"visual:{int(counts.get('visual', 0))}"
        f"|text:{int(counts.get('text', 0))}"
        f"|interactive:{int(counts.get('interactive', 0))}"
    )


def _repeat_signature(
    role: str,
    node: Mapping[str, Any],
    counts: Mapping[str, int],
) -> str:
    return "|".join(
        [
            f"tag:{_tag(node) or 'unknown'}",
            f"role:{role}",
            f"class:{_class_tokens(node) or '-'}",
            _structural_signature(counts),
            f"position:{_position_mode(node)}",
        ]
    )


def _position_mode_for_members(
    members: Sequence[int],
    nodes: Sequence[Mapping[str, Any]],
) -> str | None:
    modes = {_position_mode(nodes[index]) for index in members}
    return next(iter(modes)) if len(modes) == 1 else None


def _axis_and_gap(
    members: Sequence[int],
    nodes: Sequence[Mapping[str, Any]],
) -> tuple[str, float] | None:
    if len(members) < 2:
        return None
    boxes = [_bbox(nodes[index]) for index in members]
    if any(box[2] <= 0 or box[3] <= 0 for box in boxes):
        return None

    by_x = sorted(zip(members, boxes), key=lambda item: (item[1][0], item[0]))
    x_boxes = [item[1] for item in by_x]
    row_overlap = all(
        max(0, min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1]))
        / max(1, min(left[3], right[3]))
        >= 0.60
        for left, right in zip(x_boxes, x_boxes[1:])
    )
    if row_overlap:
        gaps = [
            right[0] - (left[0] + left[2])
            for left, right in zip(x_boxes, x_boxes[1:])
        ]
        if gaps and max(gaps) - min(gaps) <= 2:
            return "x", round(sum(gaps) / len(gaps), 2)

    by_y = sorted(zip(members, boxes), key=lambda item: (item[1][1], item[0]))
    y_boxes = [item[1] for item in by_y]
    column_overlap = all(
        max(0, min(left[0] + left[2], right[0] + right[2]) - max(left[0], right[0]))
        / max(1, min(left[2], right[2]))
        >= 0.60
        for left, right in zip(y_boxes, y_boxes[1:])
    )
    if column_overlap:
        gaps = [
            lower[1] - (upper[1] + upper[3])
            for upper, lower in zip(y_boxes, y_boxes[1:])
        ]
        if gaps and max(gaps) - min(gaps) <= 2:
            return "y", round(sum(gaps) / len(gaps), 2)
    return None


def _nearest_ancestor(
    index: int,
    candidates: set[int],
    parents: Sequence[int | None],
) -> int | None:
    for ancestor in _ancestors(index, parents):
        if ancestor in candidates:
            return ancestor
    return None


def _deduplicate_components(components: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    best_by_bbox: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    for component in components:
        if not isinstance(component, Mapping):
            continue
        box = component.get("bbox")
        if not isinstance(box, list) or len(box) < 4:
            continue
        key = tuple(_int(value) for value in box[:4])
        explicit_weight = sum(
            float(item.get("weight") or 0)
            for item in component.get("evidence") or []
            if isinstance(item, Mapping)
            and str(item.get("kind") or "")
            in {"tag", "aria-role", "list-type", "list-child"}
        )
        source = _source_indices(component)
        rank = (
            explicit_weight,
            float(component.get("confidence") or 0),
            -min(source) if source else -10**9,
        )
        current = best_by_bbox.get(key)
        if current is None:
            best_by_bbox[key] = copy.deepcopy(dict(component))
            continue
        current_source = _source_indices(current)
        current_rank = (
            sum(
                float(item.get("weight") or 0)
                for item in current.get("evidence") or []
                if isinstance(item, Mapping)
                and str(item.get("kind") or "")
                in {"tag", "aria-role", "list-type", "list-child"}
            ),
            float(current.get("confidence") or 0),
            -min(current_source) if current_source else -10**9,
        )
        if rank > current_rank:
            best_by_bbox[key] = copy.deepcopy(dict(component))
    return list(best_by_bbox.values())


def infer_component_patterns(
    dom_nodes: Sequence[Mapping[str, Any]],
    semantic: Mapping[str, Any],
) -> dict[str, Any]:
    nodes = [node if isinstance(node, Mapping) else {} for node in dom_nodes]
    parents = _parents(nodes)
    children = _children(parents)
    components = _deduplicate_components(
        [
            item
            for item in semantic.get("components") or []
            if isinstance(item, Mapping)
        ]
    )
    component_by_source: dict[int, int] = {}
    for index, component in enumerate(components):
        for source in _source_indices(component):
            component_by_source[source] = index

    groups: dict[str, dict[str, Any]] = {}
    component_signatures: dict[str, str] = {}
    list_counter = 0
    card_counter = 0
    button_counter = 0

    list_indices = {
        source
        for component in components
        if component.get("role") == "list"
        for source in _source_indices(component)
    }
    cards_by_list: dict[int, list[int]] = defaultdict(list)
    for component in components:
        if component.get("role") != "card":
            continue
        for source in _source_indices(component):
            list_source = _nearest_ancestor(source, list_indices, parents)
            if list_source is not None:
                cards_by_list[list_source].append(source)

    for list_source in sorted(cards_by_list):
        members = sorted(set(cards_by_list[list_source]))
        if len(members) < 3:
            continue
        if _position_mode_for_members(members, nodes) is None:
            continue
        geometry = _axis_and_gap(members, nodes)
        if geometry is None:
            continue
        axis, gap = geometry
        list_group_id = f"list-{list_counter}"
        list_counter += 1
        groups[list_group_id] = {
            "id": list_group_id,
            "role": "list",
            "sourceDomIndex": list_source,
            "members": members,
            "axis": axis,
            "gap": gap,
        }

        signatures = []
        member_counts = []
        for source in members:
            counts = _structure_counts(source, nodes, parents, children)
            member_counts.append(counts)
            signatures.append(
                _repeat_signature(
                    "card",
                    nodes[source],
                    counts,
                )
            )
        if len(set(signatures)) != 1:
            continue
        card_group_id = f"card-set-{card_counter}"
        card_counter += 1
        structural = _structural_signature(member_counts[0])
        groups[card_group_id] = {
            "id": card_group_id,
            "role": "card",
            "listGroupId": list_group_id,
            "members": members,
            "axis": axis,
            "gap": gap,
            "structuralSignature": structural,
        }
        component_signatures[card_group_id] = signatures[0]

    button_buckets: dict[tuple[int | None, str], list[int]] = defaultdict(list)
    for component in components:
        if component.get("role") != "button":
            continue
        for source in _source_indices(component):
            counts = _structure_counts(source, nodes, parents, children)
            signature = _repeat_signature(
                "button",
                nodes[source],
                counts,
            )
            button_buckets[(parents[source], signature)].append(source)

    for (_parent, signature), members in sorted(
        button_buckets.items(),
        key=lambda item: (min(item[1]), item[1]),
    ):
        members = sorted(set(members))
        if len(members) < 2:
            continue
        if _position_mode_for_members(members, nodes) is None:
            continue
        geometry = _axis_and_gap(members, nodes)
        if geometry is None:
            continue
        group_id = f"button-set-{button_counter}"
        button_counter += 1
        axis, gap = geometry
        structural = _structural_signature(
            _structure_counts(members[0], nodes, parents, children)
        )
        groups[group_id] = {
            "id": group_id,
            "role": "button",
            "members": members,
            "axis": axis,
            "gap": gap,
            "structuralSignature": structural,
        }
        component_signatures[group_id] = signature

    group_by_source: dict[int, str] = {}
    for group_id, group in groups.items():
        for source in group["members"]:
            group_by_source[source] = group_id

    for component in components:
        sources = _source_indices(component)
        if component.get("role") == "list":
            for source in sources:
                list_group = next(
                    (
                        group_id
                        for group_id, group in groups.items()
                        if group.get("role") == "list"
                        and group.get("sourceDomIndex") == source
                    ),
                    None,
                )
                if list_group is not None:
                    component["groupId"] = list_group
                    component["groupRole"] = "list"
                    break
            if component.get("groupId"):
                continue
        assigned = next(
            (
                (source, group_by_source[source])
                for source in sources
                if source in group_by_source
            ),
            None,
        )
        if assigned is None:
            for source in sources:
                list_source = _nearest_ancestor(source, list_indices, parents)
                if list_source is not None:
                    list_group = next(
                        (
                            group_id
                            for group_id, group in groups.items()
                            if group.get("sourceDomIndex") == list_source
                        ),
                        None,
                    )
                    if list_group is not None:
                        component["groupId"] = list_group
                        component["groupRole"] = "list"
                        break
            continue
        source, group_id = assigned
        group = groups[group_id]
        member_index = group["members"].index(source)
        component["groupId"] = group_id
        component["groupRole"] = group["role"]
        component["memberIndex"] = member_index
        component["memberCount"] = len(group["members"])
        if group.get("structuralSignature"):
            component["structuralSignature"] = group["structuralSignature"]
        list_group_id = group.get("listGroupId")
        if list_group_id:
            component["listGroupId"] = list_group_id

    role_counts = Counter(str(item.get("role") or "unknown") for item in components)
    return {
        "schema_version": COMPONENT_PATTERNS_SCHEMA_VERSION,
        "components": components,
        "groups": groups,
        "componentSignatures": component_signatures,
        "roleCounts": dict(sorted(role_counts.items())),
    }
