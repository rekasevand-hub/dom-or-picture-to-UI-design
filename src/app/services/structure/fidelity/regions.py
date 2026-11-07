"""Reconcile region containers with visible control evidence."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from src.app.services.structure.fidelity.contracts import normalize_bbox

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


def _union(boxes: list[list[int]]) -> list[int] | None:
    if not boxes:
        return None
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return [left, top, right - left, bottom - top]


def reconcile_region_containers(
    graph: Mapping[str, Any],
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Use controls in the toolbar band to repair table region evidence."""
    reconciled = copy.deepcopy(dict(graph))
    tables = reconciled.get("tables")
    if not isinstance(tables, list) or not tables:
        return reconciled
    table = tables[0]
    if not isinstance(table, Mapping):
        return reconciled
    table_bbox = normalize_bbox(table.get("bbox"), width, height)
    if table_bbox is None:
        return reconciled

    table_x, table_y, table_width, _table_height = table_bbox
    section_y = table_y
    for container in reconciled.get("containers") or []:
        if not isinstance(container, Mapping):
            continue
        if str(container.get("role") or "") != "table-section":
            continue
        section_bbox = normalize_bbox(container.get("bbox"), width, height)
        if section_bbox is not None:
            section_y = min(section_y, section_bbox[1])
            break
    band_top = max(0, section_y - 100)
    table_right = table_x + table_width
    split_x = table_x + table_width * 0.65
    left_controls: list[list[int]] = []
    right_controls: list[list[int]] = []
    for element in reconciled.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        control_type = str(
            element.get("controlType") or element.get("type") or ""
        ).lower()
        if control_type not in _CONTROL_TYPES:
            continue
        bbox = normalize_bbox(element.get("bbox"), width, height)
        if bbox is None:
            continue
        left, top, box_width, box_height = bbox
        right = left + box_width
        bottom = top + box_height
        if top < band_top or bottom > table_y:
            continue
        if left < table_x - 8 or right > table_right + 8:
            continue
        (left_controls if left + box_width / 2 < split_x else right_controls).append(
            bbox
        )

    regions = {
        "table-header-controls": _union(left_controls),
        "table-search": _union(right_controls),
    }
    containers = reconciled.get("containers")
    if not isinstance(containers, list):
        return reconciled
    aliases = {
        "table-header-controls": ("table-header-controls", "toolbar"),
        "table-search": ("table-search", "table-header"),
    }
    for target_role, candidates in aliases.items():
        bbox = regions[target_role]
        if bbox is None:
            continue
        container = next(
            (
                item
                for role in candidates
                for item in containers
                if isinstance(item, dict) and str(item.get("role") or "") == role
            ),
            None,
        )
        if container is None:
            continue
        container["role"] = target_role
        container["bbox"] = bbox
        container["geometryAuthority"] = "visible-control-union"
    return reconciled
