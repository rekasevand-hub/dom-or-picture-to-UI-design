from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

SEMANTIC_COMPONENTS_SCHEMA_VERSION = "dom-semantic-components/1.0"

_LANDMARK_ROLES = {
    "nav": "navigation",
    "main": "main",
    "aside": "complementary",
    "footer": "contentinfo",
    "header": "banner",
}
_KNOWN_ROLES = {"navigation", "list", "article", "button", "link"}
_TABLE_TAGS = {"table", "thead", "tbody", "tfoot", "tr", "td", "th"}
_VISUAL_TAGS = {"img", "svg", "video", "canvas", "picture", "object"}
_TRANSPARENT_COLORS = {"", "transparent", "none", "rgba(0,0,0,0)", "rgb(0,0,0,0)"}


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


def _hints(node: Mapping[str, Any]) -> Mapping[str, Any]:
    value = node.get("semanticHints")
    return value if isinstance(value, Mapping) else {}


def _text(index: int, nodes: Sequence[Mapping[str, Any]]) -> str:
    return str(nodes[index].get("text") or "").strip()


def _parents(
    nodes: Sequence[Mapping[str, Any]],
    layer_tree: Mapping[str, Any] | None,
) -> list[int | None]:
    parents: list[int | None] = [None] * len(nodes)
    for index, node in enumerate(nodes):
        parent = node.get("pIdx")
        if (
            isinstance(parent, int)
            and not isinstance(parent, bool)
            and 0 <= parent < len(nodes)
            and parent != index
        ):
            parents[index] = parent

    if not isinstance(layer_tree, Mapping):
        return parents
    raw_nodes = layer_tree.get("nodes")
    if not isinstance(raw_nodes, Mapping):
        return parents
    source_by_id: dict[str, int] = {}
    for node_id, value in raw_nodes.items():
        if not isinstance(value, Mapping):
            continue
        source = value.get("sourceIndex")
        if isinstance(source, int) and not isinstance(source, bool):
            source_by_id[str(node_id)] = source
    for value in raw_nodes.values():
        if not isinstance(value, Mapping):
            continue
        source = value.get("sourceIndex")
        parent_id = value.get("parentId")
        parent = source_by_id.get(str(parent_id)) if parent_id is not None else None
        if (
            isinstance(source, int)
            and not isinstance(source, bool)
            and 0 <= source < len(nodes)
            and parent is not None
            and parent != source
            and parents[source] is None
        ):
            parents[source] = parent
    return parents


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


def _is_link(index: int, nodes: Sequence[Mapping[str, Any]]) -> bool:
    node = nodes[index]
    return _tag(node) == "a" or _role(node) == "link"


def _is_table_context(
    index: int,
    nodes: Sequence[Mapping[str, Any]],
    parents: Sequence[int | None],
) -> bool:
    for current in [index, *_ancestors(index, parents)]:
        node = nodes[current]
        if _tag(node) in _TABLE_TAGS or _role(node) in {
            "table",
            "row",
            "cell",
            "columnheader",
            "rowheader",
        }:
            return True
    return False


def _has_visual_asset(
    index: int,
    nodes: Sequence[Mapping[str, Any]],
    children: Sequence[Sequence[int]],
) -> bool:
    for current in [index, *_descendants(index, children)]:
        node = nodes[current]
        if _tag(node) in _VISUAL_TAGS:
            return True
        if bool(node.get("bgImage")) or bool(node.get("assetSrc")):
            return True
        layers = node.get("backgroundLayers")
        if isinstance(layers, list) and any(
            isinstance(layer, Mapping) and layer.get("kind") in {"image", "gradient"}
            for layer in layers
        ):
            return True
    return False


def _has_text_block(
    index: int,
    nodes: Sequence[Mapping[str, Any]],
    children: Sequence[Sequence[int]],
) -> bool:
    return any(_text(current, nodes) for current in [index, *_descendants(index, children)])


def _visible_length(value: str) -> float:
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return abs(float(match.group(0))) if match else 0.0


def _has_border(node: Mapping[str, Any]) -> bool:
    for key in ("borderTopWidth", "borderLeftWidth", "borderWidth"):
        if _visible_length(str(node.get(key) or "")) > 0:
            return True
    edges = node.get("edges")
    return bool(edges)


def _has_background(node: Mapping[str, Any]) -> bool:
    color = re.sub(r"\s+", "", str(node.get("bg") or "").lower())
    if color not in _TRANSPARENT_COLORS:
        return True
    layers = node.get("backgroundLayers")
    return isinstance(layers, list) and bool(layers)


def _button_evidence(
    index: int,
    nodes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    node = nodes[index]
    tag = _tag(node)
    role = _role(node)
    if tag == "button" or role == "button":
        evidence = [
            {"kind": "tag" if tag == "button" else "aria-role", "value": tag or role, "weight": 1.0}
        ]
        if _text(index, nodes):
            evidence.append({"kind": "visible-text", "value": True, "weight": 0.4})
        return evidence

    interactive = bool(node.get("interactive")) or (
        tag in {"a", "input", "select", "textarea"} or role in {"link", "button"}
    )
    if not interactive or not _text(index, nodes):
        return []
    signals = []
    if _has_border(node):
        signals.append({"kind": "border", "value": True, "weight": 0.35})
    if _has_background(node):
        signals.append({"kind": "background", "value": True, "weight": 0.35})
    if _int(node.get("h")) >= 28:
        signals.append({"kind": "min-height", "value": _int(node.get("h")), "weight": 0.3})
    if len(signals) < 2:
        return []
    return [
        {"kind": "interactive-element", "value": tag or "true", "weight": 0.5},
        {"kind": "visible-text", "value": True, "weight": 0.4},
        *signals,
    ]


def _navigation_evidence(
    index: int,
    nodes: Sequence[Mapping[str, Any]],
    children: Sequence[Sequence[int]],
) -> tuple[list[dict[str, Any]], float] | None:
    node = nodes[index]
    tag = _tag(node)
    role = _role(node)
    landmark = str(_hints(node).get("landmark") or "").lower()
    explicit = (
        tag == "nav"
        or role == "navigation"
        or _LANDMARK_ROLES.get(landmark) == "navigation"
    )
    links = [
        current
        for current in _descendants(index, children)
        if _is_link(current, nodes)
    ]
    if explicit:
        evidence = [
            {
                "kind": "tag" if tag == "nav" else "aria-role",
                "value": tag or role or landmark,
                "weight": 1.0,
            },
            {"kind": "direct-link-count", "value": len(links), "weight": 0.6},
        ]
        if len(links) >= 3:
            evidence.append({"kind": "horizontal-line", "value": True, "weight": 0.5})
        return evidence, 0.98
    if len(links) < 3:
        return None
    boxes = [_bbox(nodes[current]) for current in links]
    centers = [box[1] + box[3] / 2 for box in boxes]
    if max(centers) - min(centers) > 24:
        return None
    ordered = sorted(links, key=lambda current: (_bbox(nodes[current])[0], current))
    if len(set(ordered)) != len(ordered):
        return None
    return (
        [
            {"kind": "direct-link-count", "value": len(links), "weight": 1.0},
            {
                "kind": "horizontal-center-spread",
                "value": round(max(centers) - min(centers), 2),
                "weight": 0.7,
            },
            {"kind": "no-vertical-card-repetition", "value": True, "weight": 0.5},
        ],
        0.88,
    )


def _stable_signature(node: Mapping[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    classes = tuple(
        sorted(
            token
            for token in re.split(r"\s+", str(node.get("clsAll") or "").strip())
            if token
        )
    )
    return _tag(node), _role(node), classes


def _repeated_axis(
    members: Sequence[int],
    nodes: Sequence[Mapping[str, Any]],
) -> tuple[str, float] | None:
    if len(members) < 3:
        return None
    boxes = [_bbox(nodes[index]) for index in members]
    if any(box[2] <= 0 or box[3] <= 0 for box in boxes):
        return None
    by_x = sorted(zip(members, boxes), key=lambda item: (item[1][0], item[0]))
    x_boxes = [item[1] for item in by_x]
    if (
        max(box[1] for box in x_boxes) - min(box[1] for box in x_boxes) <= 2
        and max(box[3] for box in x_boxes) - min(box[3] for box in x_boxes) <= 2
    ):
        gaps = [
            right[0] - (left[0] + left[2])
            for left, right in zip(x_boxes, x_boxes[1:])
        ]
        if gaps and max(gaps) - min(gaps) <= 2:
            return "x", round(sum(gaps) / len(gaps), 2)
    by_y = sorted(zip(members, boxes), key=lambda item: (item[1][1], item[0]))
    y_boxes = [item[1] for item in by_y]
    if (
        max(box[0] for box in y_boxes) - min(box[0] for box in y_boxes) <= 2
        and max(box[2] for box in y_boxes) - min(box[2] for box in y_boxes) <= 2
    ):
        gaps = [
            lower[1] - (upper[1] + upper[3])
            for upper, lower in zip(y_boxes, y_boxes[1:])
        ]
        if gaps and max(gaps) - min(gaps) <= 2:
            return "y", round(sum(gaps) / len(gaps), 2)
    return None


def _repeated_card_children(
    index: int,
    nodes: Sequence[Mapping[str, Any]],
    parents: Sequence[int | None],
    children: Sequence[Sequence[int]],
) -> tuple[list[int], str, float] | None:
    if _is_table_context(index, nodes, parents):
        return None
    candidates = [
        current
        for current in children[index]
        if (
            _tag(nodes[current]) == "article"
            or _role(nodes[current]) == "article"
            or (
                _has_visual_asset(current, nodes, children)
                and _has_text_block(current, nodes, children)
            )
        )
    ]
    if len(candidates) < 3:
        return None
    signatures = {_stable_signature(nodes[current]) for current in candidates}
    if len(signatures) != 1:
        return None
    axis = _repeated_axis(candidates, nodes)
    if axis is None:
        return None
    return candidates, axis[0], axis[1]


def _list_evidence(
    index: int,
    nodes: Sequence[Mapping[str, Any]],
    parents: Sequence[int | None],
    children: Sequence[Sequence[int]],
) -> tuple[list[dict[str, Any]], float] | None:
    node = nodes[index]
    tag = _tag(node)
    role = _role(node)
    hints = _hints(node)
    if tag in {"ul", "ol"} or role == "list" or hints.get("listType"):
        evidence = [
            {
                "kind": "tag" if tag in {"ul", "ol"} else "aria-role",
                "value": tag or role or hints.get("listType"),
                "weight": 1.0,
            }
        ]
        if hints.get("listType"):
            evidence.append({"kind": "list-type", "value": hints["listType"], "weight": 0.6})
        evidence.append({"kind": "direct-child-count", "value": len(children[index]), "weight": 0.4})
        return evidence, 0.98
    repeated = _repeated_card_children(index, nodes, parents, children)
    if repeated is None:
        return None
    members, axis, gap = repeated
    return (
        [
            {"kind": "repeated-child-count", "value": len(members), "weight": 1.0},
            {"kind": "repeated-geometry-axis", "value": axis, "weight": 0.7},
            {"kind": "equal-axis-spacing", "value": gap, "weight": 0.6},
        ],
        0.86,
    )


def _sort_key(index: int, nodes: Sequence[Mapping[str, Any]], role: str) -> tuple[int, int, str, int]:
    box = _bbox(nodes[index])
    return box[1], box[0], role, index


def classify_semantic_components(
    dom_nodes: Sequence[Mapping[str, Any]],
    *,
    layer_tree: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    nodes = [node if isinstance(node, Mapping) else {} for node in dom_nodes]
    parents = _parents(nodes, layer_tree)
    children = _children(parents)
    candidates: dict[int, tuple[int, float, str, list[dict[str, Any]]]] = {}

    def put(
        index: int,
        role: str,
        confidence: float,
        evidence: list[dict[str, Any]],
        priority: int,
    ) -> None:
        current = candidates.get(index)
        if current is None or (priority, confidence) > (current[0], current[1]):
            candidates[index] = (priority, confidence, role, evidence)

    for index, node in enumerate(nodes):
        tag = _tag(node)
        role = _role(node)
        hints = _hints(node)
        if tag in {"nav", "ul", "ol", "article", "button"} or role in {
            "navigation",
            "list",
            "article",
            "button",
        }:
            continue
        explicit_role = str(hints.get("ariaRole") or "").lower()
        if explicit_role and explicit_role not in _KNOWN_ROLES:
            put(
                index,
                "unknown",
                0.35,
                [{"kind": "unsupported-aria-role", "value": explicit_role, "weight": 1.0}],
                1,
            )

    list_indices: set[int] = set()
    for index, node in enumerate(nodes):
        list_evidence = _list_evidence(index, nodes, parents, children)
        if list_evidence is not None:
            evidence, confidence = list_evidence
            put(index, "list", confidence, evidence, 8)
            list_indices.add(index)
            continue
        navigation = _navigation_evidence(index, nodes, children)
        if navigation is not None:
            evidence, confidence = navigation
            put(index, "navigation", confidence, evidence, 8)
    for index, node in enumerate(nodes):
        if _is_table_context(index, nodes, parents):
            continue
        if _tag(node) == "article" or _role(node) == "article":
            put(
                index,
                "card",
                0.96 if _tag(node) == "article" else 0.94,
                [
                    {
                        "kind": "tag" if _tag(node) == "article" else "aria-role",
                        "value": _tag(node) or _role(node),
                        "weight": 1.0,
                    }
                ],
                7,
            )

    for list_index in sorted(list_indices):
        for index in children[list_index]:
            if (
                not _is_table_context(index, nodes, parents)
                and _has_visual_asset(index, nodes, children)
                and _has_text_block(index, nodes, children)
            ):
                put(
                    index,
                    "card",
                    0.84,
                    [
                        {"kind": "list-child", "value": list_index, "weight": 0.8},
                        {"kind": "visual-asset-count", "value": 1, "weight": 0.7},
                        {"kind": "text-block-count", "value": 1, "weight": 0.7},
                    ],
                    6,
                )

    button_indices: set[int] = set()
    for index in range(len(nodes)):
        button_evidence = _button_evidence(index, nodes)
        if button_evidence:
            explicit = _tag(nodes[index]) == "button" or _role(nodes[index]) == "button"
            put(index, "button", 0.98 if explicit else 0.84, button_evidence, 9)
            button_indices.add(index)

    for index in range(len(nodes)):
        if not _is_link(index, nodes) or index in button_indices:
            continue
        if any(
            candidates.get(ancestor, (0, 0.0, "unknown", []))[0] >= 6
            for ancestor in _ancestors(index, parents)
        ):
            continue
        put(
            index,
            "link",
            0.92,
            [
                {"kind": "tag" if _tag(nodes[index]) == "a" else "aria-role", "value": "link", "weight": 1.0},
                {"kind": "button-evidence-count", "value": 0, "weight": 0.6},
            ],
            3,
        )

    return _build_result(nodes, candidates)


def _build_result(
    nodes: Sequence[Mapping[str, Any]],
    candidates: Mapping[int, tuple[int, float, str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    components = []
    for index in sorted(
        candidates,
        key=lambda value: _sort_key(value, nodes, candidates[value][2]),
    ):
        _priority, confidence, role, evidence = candidates[index]
        box = _bbox(nodes[index])
        if box[2] <= 0 or box[3] <= 0:
            continue
        components.append(
            {
                "id": f"semantic-n{index}",
                "role": role,
                "confidence": round(float(confidence), 4),
                "sourceDomIndices": [index],
                "bbox": box,
                "evidence": list(evidence),
            }
        )
    counts = Counter(item["role"] for item in components)
    return {
        "schema_version": SEMANTIC_COMPONENTS_SCHEMA_VERSION,
        "components": components,
        "roleCounts": dict(sorted(counts.items())),
        "unknownCount": counts["unknown"],
    }
