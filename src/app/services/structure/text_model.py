from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

TEXT_MODEL_SCHEMA_VERSION = "dom-text-model/1.0"

_TEXT_ROLES = {
    "paragraph",
    "heading",
    "button-label",
    "input-value",
    "list-marker",
    "caption",
}
_INLINE_TAGS = {
    "a",
    "abbr",
    "b",
    "cite",
    "code",
    "em",
    "i",
    "kbd",
    "label",
    "mark",
    "s",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "u",
    "var",
}
_STYLE_KEYS = (
    "fontSize",
    "fontWeight",
    "fontStyle",
    "fontFamily",
    "lineHeight",
    "letterSpacing",
    "textDecorationLine",
    "textColor",
    "color",
)


def _source_id(index: int, node: Mapping[str, Any]) -> str:
    for key in ("id", "domId", "sourceId"):
        value = node.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return str(index)


def _source_index(node: Mapping[str, Any], fallback: int) -> int:
    value = node.get("domIndex")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return fallback


def _parent_index(node: Mapping[str, Any]) -> int | None:
    value = node.get("pIdx")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _normalized_style(node: Mapping[str, Any]) -> dict[str, Any]:
    source = node.get("style")
    style: dict[str, Any] = {}
    if isinstance(source, Mapping):
        style.update(source)
    for key in _STYLE_KEYS:
        value = node.get(key)
        if value not in (None, ""):
            target = "textColor" if key == "color" else key
            style[target] = value
    return style


def _normalize_run(
    run: Mapping[str, Any],
    *,
    block_index: int,
    fallback_style: Mapping[str, Any],
) -> dict[str, Any]:
    kind = str(run.get("kind") or "text")
    if kind not in {"text", "inline-image"}:
        kind = "text"
    style = dict(fallback_style)
    if isinstance(run.get("style"), Mapping):
        style.update({str(k): v for k, v in run["style"].items() if v not in (None, "")})
    text = str(run.get("text") or "")
    normalized: dict[str, Any] = {
        "kind": kind,
        "text": text,
        "style": style,
        "sourceIndex": block_index,
    }
    if kind == "inline-image":
        for key in ("assetSrc", "tag", "naturalWidth", "naturalHeight", "alt"):
            if run.get(key) not in (None, ""):
                normalized[key] = run[key]
    return normalized


def _role_for(index: int, nodes: Sequence[Mapping[str, Any]]) -> str:
    node = nodes[index]
    hint = str(node.get("textRoleHint") or "").strip()
    if hint in _TEXT_ROLES:
        return hint
    tag = str(node.get("tag") or "").lower()
    role = str(node.get("role") or "").lower()
    if tag in {"button"} or role == "button":
        return "button-label"
    if tag in {"input", "textarea"} or role in {"textbox", "searchbox"}:
        return "input-value"
    if tag in {"figcaption", "caption"}:
        return "caption"
    if tag == "li" and isinstance(node.get("listMarker"), Mapping):
        return "list-marker"

    current = _parent_index(node)
    seen: set[int] = set()
    while current is not None and 0 <= current < len(nodes) and current not in seen:
        seen.add(current)
        ancestor = nodes[current]
        ancestor_tag = str(ancestor.get("tag") or "").lower()
        ancestor_role = str(ancestor.get("role") or "").lower()
        if ancestor_tag in {"h1", "h2", "h3", "h4", "h5", "h6"} or (
            ancestor_role == "heading"
        ):
            return "heading"
        if ancestor_tag == "button" or ancestor_role == "button":
            return "button-label"
        current = _parent_index(ancestor)
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} or role == "heading":
        return "heading"
    return "paragraph"


def _is_inline_node(node: Mapping[str, Any]) -> bool:
    display = str(node.get("display") or "").lower()
    tag = str(node.get("tag") or "").lower()
    return display in {"inline", "inline-block", "inline-flex"} or tag in _INLINE_TAGS


def _is_inline_descendant(
    index: int,
    ancestor_index: int,
    nodes: Sequence[Mapping[str, Any]],
) -> bool:
    current = _parent_index(nodes[index])
    seen: set[int] = set()
    while (
        current is not None
        and current != ancestor_index
        and 0 <= current < len(nodes)
        and current not in seen
    ):
        seen.add(current)
        if not _is_inline_node(nodes[current]):
            return False
        current = _parent_index(nodes[current])
    return current == ancestor_index


def _has_inline_image(run: Mapping[str, Any], index: int) -> bool:
    tag = str(run.get("tag") or "").lower()
    return (
        str(run.get("kind") or "") == "inline-image"
        or bool(run.get("inlineImageBoundary"))
        or bool(run.get("assetSrc")) and tag in {"img", "svg"} and index >= 0
    )


def _text_bearing(node: Mapping[str, Any]) -> bool:
    if str(node.get("text") or ""):
        return True
    runs = node.get("richRuns")
    return isinstance(runs, list) and any(
        isinstance(run, Mapping)
        and (
            str(run.get("text") or "")
            or _has_inline_image(run, 0)
        )
        for run in runs
    )


def _measured_lines(node: Mapping[str, Any]) -> list[dict[str, Any]]:
    lines = node.get("textLines")
    if isinstance(lines, list):
        result = []
        for line in lines:
            if not isinstance(line, Mapping):
                continue
            text = str(line.get("text") or "")
            box = line.get("box")
            if not text:
                continue
            item: dict[str, Any] = {"text": text}
            if isinstance(box, (list, tuple)) and len(box) == 4:
                item["box"] = [int(value) for value in box]
            if isinstance(line.get("baseline"), Mapping):
                item["baseline"] = dict(line["baseline"])
            result.append(item)
        if result:
            return result
    box = node.get("textEmBox")
    text = str(node.get("text") or "")
    if isinstance(box, (list, tuple)) and len(box) == 4 and text:
        line: dict[str, Any] = {
            "text": text,
            "box": [int(value) for value in box],
        }
        if isinstance(node.get("textBaseline"), Mapping):
            line["baseline"] = dict(node["textBaseline"])
        return [line]
    return []


def build_text_model(dom_nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    nodes = list(dom_nodes)
    text_indices = {index for index, node in enumerate(nodes) if _text_bearing(node)}
    consumed_indices: set[int] = set()
    block_indices: list[int] = []

    for index in sorted(text_indices):
        node = nodes[index]
        parent = _parent_index(node)
        consumed_by_parent = False
        if parent is not None and parent in text_indices:
            parent_node = nodes[parent]
            if isinstance(parent_node.get("richRuns"), list) or _is_inline_node(node):
                consumed_by_parent = _is_inline_descendant(index, parent, nodes)
            if consumed_by_parent:
                consumed_indices.add(index)
        if not consumed_by_parent:
            block_indices.append(index)

    blocks: dict[str, dict[str, Any]] = {}
    for block_position, source_index in enumerate(block_indices):
        node = nodes[source_index]
        fallback_style = _normalized_style(node)
        runs: list[dict[str, Any]] = []
        raw_runs = node.get("richRuns")
        if isinstance(raw_runs, list) and raw_runs:
            for run in raw_runs:
                if isinstance(run, Mapping):
                    runs.append(
                        _normalize_run(
                            run,
                            block_index=source_index,
                            fallback_style=fallback_style,
                        )
                    )
        elif str(node.get("text") or ""):
            runs.append(
                {
                    "kind": "text",
                    "text": str(node["text"]),
                    "style": fallback_style,
                    "sourceIndex": source_index,
                }
            )

        for child_index in sorted(text_indices):
            child = nodes[child_index]
            if child_index == source_index:
                continue
            if _parent_index(child) != source_index:
                continue
            if _has_inline_image(child, child_index):
                runs.append(
                    {
                        "kind": "inline-image",
                        "text": "",
                        "style": _normalized_style(child),
                        "sourceIndex": child_index,
                        "assetSrc": child.get("assetSrc"),
                        "tag": child.get("tag"),
                    }
                )
            elif isinstance(node.get("richRuns"), list) and _is_inline_node(child):
                consumed_indices.add(child_index)

        for child_index in sorted(consumed_indices):
            if child_index in text_indices and _is_inline_descendant(
                child_index, source_index, nodes
            ):
                consumed_indices.add(child_index)

        block_id = f"text-{block_position}"
        measured_lines = _measured_lines(node)
        measured_line_count = int(node.get("textEmLines") or 0)
        if measured_lines:
            measured_line_count = max(measured_line_count, len(measured_lines))
        if node.get("textBaseline") is not None and measured_line_count == 0:
            measured_line_count = 1
        source_fields = [
            key
            for key in (
                "tag",
                "role",
                "textRoleHint",
                "listMarker",
                "text",
                "richRuns",
                "textLines",
                "textBox",
                "textEmBox",
                "textBaseline",
                "pIdx",
            )
            if key in node
        ]
        block: dict[str, Any] = {
            "id": block_id,
            "sourceIndex": source_index,
            "sourceId": _source_id(source_index, node),
            "role": _role_for(source_index, nodes),
            "text": "".join(str(run.get("text") or "") for run in runs),
            "runs": runs,
            "measuredLines": measured_lines,
            "measuredLineCount": measured_line_count,
            "style": fallback_style,
            "sourceFields": source_fields,
        }
        for key in ("textBox", "textEmBox", "textBaseline", "listMarker"):
            value = node.get(key)
            if isinstance(value, Mapping):
                block[key] = dict(value)
            elif isinstance(value, (list, tuple)):
                block[key] = list(value)
            elif value is not None:
                block[key] = value
        blocks[block_id] = block

    inline_consumed_indices = sorted(consumed_indices)
    ordered_consumed = [
        _source_id(index, nodes[index])
        for index in inline_consumed_indices
    ]
    return {
        "schema_version": TEXT_MODEL_SCHEMA_VERSION,
        "blocks": blocks,
        "inlineConsumed": ordered_consumed,
        "inlineConsumedIndices": inline_consumed_indices,
    }
