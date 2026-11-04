"""Merge page-coordinate graphs produced from overlapping image tiles."""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from src.app.services.structure.graph import (
    assign_ids,
    assign_parent_depth,
    iou,
    new_graph,
)

TEXT_DUPLICATE_IOU = 0.85
TEXT_DUPLICATE_CONTAINMENT = 0.90
TEXT_AMBIGUOUS_OVERLAP = 0.35
VISUAL_DUPLICATE_IOU = 0.75
VISUAL_HASH_DUPLICATE_IOU = 0.45
CONTAINER_DUPLICATE_IOU = 0.85
CONTAINER_DUPLICATE_CONTAINMENT = 0.90


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _bbox(value: Any, width: int, height: int) -> list[int] | None:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        return None
    x, y, box_width, box_height = (int(item) for item in value)
    left = max(0, x)
    top = max(0, y)
    right = min(width, x + box_width)
    bottom = min(height, y + box_height)
    if right - left < 2 or bottom - top < 2:
        return None
    return [left, top, right - left, bottom - top]


def _union_bbox(first: list[int], second: list[int]) -> list[int]:
    left = min(first[0], second[0])
    top = min(first[1], second[1])
    right = max(first[0] + first[2], second[0] + second[2])
    bottom = max(first[1] + first[3], second[1] + second[3])
    return [left, top, right - left, bottom - top]


def _intersection_area(first: list[int], second: list[int]) -> int:
    width = max(
        0,
        min(first[0] + first[2], second[0] + second[2])
        - max(first[0], second[0]),
    )
    height = max(
        0,
        min(first[1] + first[3], second[1] + second[3])
        - max(first[1], second[1]),
    )
    return width * height


def _containment(first: list[int], second: list[int]) -> float:
    first_area = first[2] * first[3]
    second_area = second[2] * second[3]
    smaller = min(first_area, second_area)
    return _intersection_area(first, second) / smaller if smaller > 0 else 0.0


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _tile_info(graph: Mapping[str, Any]) -> dict[str, Any]:
    provenance = graph.get("provenance")
    if not isinstance(provenance, Mapping):
        return {}
    tiling = provenance.get("tiling")
    if not isinstance(tiling, Mapping):
        return {}
    tile = tiling.get("tile")
    return dict(tile) if isinstance(tile, Mapping) else {}


def _tile_id(graph: Mapping[str, Any]) -> str:
    return str(_tile_info(graph).get("id") or "")


def _source_hash(candidate: Mapping[str, Any]) -> str:
    for field in ("sourceCrop", "assetIdentity"):
        value = candidate.get(field)
        if isinstance(value, Mapping):
            for key in ("payloadSha256", "payload_sha256", "sha256"):
                digest = str(value.get(key) or "")
                if digest:
                    return digest
    for key in ("payloadSha256", "payload_sha256"):
        digest = str(candidate.get(key) or "")
        if digest:
            return digest
    return ""


def _diagnostic(
    code: str,
    *,
    action: str,
    candidate: Mapping[str, Any],
    surviving: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tile_ids: list[str] = []
    if surviving is not None:
        kept = str(surviving.get("_tile_id") or "")
        if kept:
            tile_ids.append(kept)
    tile_ids.append(str(candidate.get("_tile_id") or ""))
    return {
        "code": code,
        "action": action,
        "bbox": list(candidate.get("bbox") or []),
        "text": str(candidate.get("text") or ""),
        "type": str(candidate.get("type") or ""),
        "tile_ids": [item for item in tile_ids if item],
    }


def _container_duplicate(
    candidate: Mapping[str, Any], existing: Mapping[str, Any]
) -> bool:
    if str(candidate.get("role") or "") != str(existing.get("role") or ""):
        return False
    candidate_bbox = list(candidate.get("bbox") or [])
    existing_bbox = list(existing.get("bbox") or [])
    overlap = iou(candidate_bbox, existing_bbox)
    return (
        candidate_bbox == existing_bbox
        or overlap >= CONTAINER_DUPLICATE_IOU
        or _containment(candidate_bbox, existing_bbox)
        >= CONTAINER_DUPLICATE_CONTAINMENT
    )


def _visual_duplicate(
    candidate: Mapping[str, Any], existing: Mapping[str, Any]
) -> bool:
    if str(candidate.get("type") or "") != str(existing.get("type") or ""):
        return False
    overlap = iou(
        list(candidate.get("bbox") or []),
        list(existing.get("bbox") or []),
    )
    if overlap >= VISUAL_DUPLICATE_IOU:
        return True
    candidate_hash = _source_hash(candidate)
    return bool(
        candidate_hash
        and candidate_hash == _source_hash(existing)
        and overlap >= VISUAL_HASH_DUPLICATE_IOU
    )


def _text_duplicate_action(
    candidate: Mapping[str, Any], existing: Mapping[str, Any]
) -> str | None:
    normalized = _normalize_text(candidate.get("text"))
    if not normalized or normalized != _normalize_text(existing.get("text")):
        return None
    candidate_bbox = list(candidate.get("bbox") or [])
    existing_bbox = list(existing.get("bbox") or [])
    overlap_iou = iou(candidate_bbox, existing_bbox)
    overlap_containment = _containment(candidate_bbox, existing_bbox)
    if (
        overlap_iou >= TEXT_DUPLICATE_IOU
        or overlap_containment >= TEXT_DUPLICATE_CONTAINMENT
    ):
        return "drop"
    if max(overlap_iou, overlap_containment) >= TEXT_AMBIGUOUS_OVERLAP:
        return "ambiguous"
    return None


def _adjacent_text(
    first: Mapping[str, Any], second: Mapping[str, Any]
) -> bool:
    if str(first.get("type") or "") != "text" or str(second.get("type") or "") != "text":
        return False
    first_bbox = list(first.get("bbox") or [])
    second_bbox = list(second.get("bbox") or [])
    first_center = first_bbox[1] + first_bbox[3] / 2
    second_center = second_bbox[1] + second_bbox[3] / 2
    if abs(first_center - second_center) > max(
        4, min(first_bbox[3], second_bbox[3]) * 0.5
    ):
        return False
    vertical_overlap = min(
        first_bbox[1] + first_bbox[3],
        second_bbox[1] + second_bbox[3],
    ) - max(first_bbox[1], second_bbox[1])
    if vertical_overlap < min(first_bbox[3], second_bbox[3]) * 0.5:
        return False
    gap = max(
        first_bbox[0] - (second_bbox[0] + second_bbox[2]),
        second_bbox[0] - (first_bbox[0] + first_bbox[2]),
        0,
    )
    return gap <= max(16, max(first_bbox[3], second_bbox[3]) * 2)


def _join_text(first: str, second: str) -> str:
    left, right = first, second
    if not left:
        return right
    if not right:
        return left
    if left[-1].isascii() and left[-1].isalnum() and right[0].isascii() and right[0].isalnum():
        return f"{left} {right}"
    return f"{left}{right}"


def _merge_adjacent_text(
    candidate: dict[str, Any],
    existing: dict[str, Any],
    diagnostics: list[dict[str, Any]],
) -> None:
    candidate_text = str(candidate.get("text") or "")
    existing_text = str(existing.get("text") or "")
    if candidate["bbox"][0] <= existing["bbox"][0]:
        existing["bbox"] = _union_bbox(existing["bbox"], candidate["bbox"])
        existing["text"] = _join_text(candidate_text, existing_text)
    else:
        existing["bbox"] = _union_bbox(existing["bbox"], candidate["bbox"])
        existing["text"] = _join_text(existing_text, candidate_text)
    diagnostics.append(
        _diagnostic(
            "adjacent_text_merged",
            action="merged",
            candidate=candidate,
            surviving=existing,
        )
    )


def _merge_elements(
    graphs: list[dict[str, Any]],
    width: int,
    height: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for graph in graphs:
        tile_id = _tile_id(graph)
        for raw in graph.get("elements") or []:
            if not isinstance(raw, Mapping):
                continue
            candidate = copy.deepcopy(dict(raw))
            normalized_bbox = _bbox(candidate.get("bbox"), width, height)
            if normalized_bbox is None:
                continue
            candidate["bbox"] = normalized_bbox
            candidate["_tile_id"] = tile_id
            matched = False
            for existing in merged:
                if (
                    str(candidate.get("type") or "") == "text"
                    and str(existing.get("type") or "") == "text"
                ):
                    action = _text_duplicate_action(candidate, existing)
                    if action == "drop":
                        diagnostics.append(
                            _diagnostic(
                                "duplicate_text",
                                action="dropped",
                                candidate=candidate,
                                surviving=existing,
                            )
                        )
                        matched = True
                        break
                    if action == "ambiguous":
                        diagnostics.append(
                            _diagnostic(
                                "ambiguous_text_duplicate",
                                action="kept",
                                candidate=candidate,
                                surviving=existing,
                            )
                        )
                        continue
                    if (
                        candidate.get("_tile_id") != existing.get("_tile_id")
                        and _adjacent_text(existing, candidate)
                    ):
                        _merge_adjacent_text(candidate, existing, diagnostics)
                        matched = True
                        break
                elif _visual_duplicate(candidate, existing):
                    diagnostics.append(
                        _diagnostic(
                            "duplicate_visual",
                            action="dropped",
                            candidate=candidate,
                            surviving=existing,
                        )
                    )
                    matched = True
                    break
            if not matched:
                merged.append(candidate)

    merged.sort(
        key=lambda item: (
            item["bbox"][1],
            item["bbox"][0],
            str(item.get("type") or ""),
            _normalize_text(item.get("text")),
        )
    )
    return merged, diagnostics


def _merge_containers(
    graphs: list[dict[str, Any]],
    width: int,
    height: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for graph in graphs:
        tile_id = _tile_id(graph)
        for raw in graph.get("containers") or []:
            if not isinstance(raw, Mapping):
                continue
            candidate = copy.deepcopy(dict(raw))
            normalized_bbox = _bbox(candidate.get("bbox"), width, height)
            if normalized_bbox is None:
                continue
            candidate["bbox"] = normalized_bbox
            candidate["_tile_id"] = tile_id
            duplicate = next(
                (
                    existing
                    for existing in merged
                    if _container_duplicate(candidate, existing)
                ),
                None,
            )
            if duplicate is not None:
                diagnostics.append(
                    _diagnostic(
                        "duplicate_container",
                        action="dropped",
                        candidate=candidate,
                        surviving=duplicate,
                    )
                )
                continue
            merged.append(candidate)

    merged.sort(
        key=lambda item: (
            item["bbox"][1],
            item["bbox"][0],
            str(item.get("role") or ""),
        )
    )
    return merged, diagnostics


def _repeated_text_fingerprints(
    elements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for element in elements:
        if str(element.get("type") or "") != "text":
            continue
        normalized = _normalize_text(element.get("text"))
        if not normalized:
            continue
        group = groups.setdefault(
            normalized,
            {"text": str(element.get("text") or ""), "tile_ids": []},
        )
        tile_id = str(element.get("_tile_id") or "")
        if tile_id and tile_id not in group["tile_ids"]:
            group["tile_ids"].append(tile_id)
    return [
        {
            "text": group["text"],
            "count": sum(
                1
                for element in elements
                if _normalize_text(element.get("text"))
                == _normalize_text(group["text"])
            ),
            "tile_ids": group["tile_ids"],
        }
        for group in groups.values()
        if sum(
            1
            for element in elements
            if _normalize_text(element.get("text"))
            == _normalize_text(group["text"])
        )
        > 1
    ]


def merge_tiled_graphs(
    graphs: list[dict],
    width: int,
    height: int,
) -> tuple[dict, dict]:
    """Merge overlapping tile graphs in deterministic page reading order."""

    page_width = _positive_int(width, "width")
    page_height = _positive_int(height, "height")
    normalized_graphs = [
        copy.deepcopy(graph)
        for graph in graphs
        if isinstance(graph, Mapping)
    ]
    normalized_graphs.sort(
        key=lambda graph: (
            int(_tile_info(graph).get("source_rect", [0, 0])[1]),
            _tile_id(graph),
        )
    )

    containers, container_diagnostics = _merge_containers(
        normalized_graphs, page_width, page_height
    )
    elements, element_diagnostics = _merge_elements(
        normalized_graphs, page_width, page_height
    )
    fingerprints = _repeated_text_fingerprints(elements)
    diagnostics = container_diagnostics + element_diagnostics

    for item in containers + elements:
        item.pop("_tile_id", None)

    tile_entries = []
    for graph in normalized_graphs:
        tile = _tile_info(graph)
        if not tile:
            continue
        entry = {
            key: copy.deepcopy(tile[key])
            for key in ("id", "source_rect", "page_origin", "reason", "status")
            if key in tile
        }
        tile_entries.append(entry)
    tile_entries.sort(key=lambda item: str(item.get("id") or ""))

    report = {
        "coordinate_space": "page",
        "tiles": tile_entries,
        "duplicate_count": sum(
            1 for item in diagnostics if item["action"] in {"dropped", "merged"}
        ),
        "ambiguous_count": sum(
            1 for item in diagnostics if item["action"] == "kept"
        ),
        "diagnostics": diagnostics,
        "repeated_text_fingerprints": fingerprints,
    }

    fallbacks: list[Any] = []
    warnings: list[Any] = []
    for graph in normalized_graphs:
        provenance = graph.get("provenance")
        if not isinstance(provenance, Mapping):
            continue
        fallbacks.extend(copy.deepcopy(provenance.get("fallbacks") or []))
        warnings.extend(copy.deepcopy(provenance.get("warnings") or []))
    fallbacks = list(dict.fromkeys(str(item) for item in fallbacks))
    warnings = list(dict.fromkeys(str(item) for item in warnings))
    image = str(normalized_graphs[0].get("image") or "") if normalized_graphs else ""
    graph = new_graph(
        image,
        page_width,
        page_height,
        "grounding",
        provenance={
            "route": "grounding",
            "fallbacks": fallbacks,
            "warnings": warnings,
            "tiling": report,
        },
    )
    graph["containers"] = containers
    graph["elements"] = elements
    tables_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for source_graph in normalized_graphs:
        for table in source_graph.get("tables") or []:
            if not isinstance(table, Mapping):
                continue
            key = (
                str(table.get("name") or ""),
                json.dumps(table.get("bbox") or [], sort_keys=True),
            )
            current = tables_by_key.get(key)
            if current is None or len(table.get("rows") or []) > len(
                current.get("rows") or []
            ):
                tables_by_key[key] = copy.deepcopy(dict(table))
    graph["tables"] = list(tables_by_key.values())
    assign_ids(graph)
    assign_parent_depth(graph)
    return graph, report
