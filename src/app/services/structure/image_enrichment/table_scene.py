"""Reconstruct table text from visible grid cells instead of VLM row guesses."""

from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2
import numpy as np

TABLE_GRID_COLOR = "#e7ecf1"
TABLE_HEADER_FILL = "#fbfcfd"


def _group(values: list[int], tolerance: int = 4) -> list[int]:
    groups: list[list[int]] = []
    for value in sorted(values):
        if not groups or value - groups[-1][-1] > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [int(round(sum(group) / len(group))) for group in groups]


def _text(value: Any) -> str:
    return re.sub(
        r"\s+",
        "",
        unicodedata.normalize("NFKC", str(value or "")).casefold(),
    )


def _bbox(value: Any) -> list[int] | None:
    try:
        x, y, width, height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    return [x, y, width, height] if width > 0 and height > 0 else None


def _element_box(element: Mapping[str, Any]) -> list[int] | None:
    return _bbox(
        [
            element.get("x"),
            element.get("y"),
            element.get("width"),
            element.get("height"),
        ]
    )


def _cell_ink_box(
    grayscale: np.ndarray,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> list[int] | None:
    inset = 3
    x0 = max(0, left + inset)
    y0 = max(0, top + inset)
    x1 = min(grayscale.shape[1], right - inset)
    y1 = min(grayscale.shape[0], bottom - inset)
    if x1 <= x0 or y1 <= y0:
        return None
    mask = grayscale[y0:y1, x0:x1] < 180
    mask[:, mask.sum(axis=0) >= max(4, (y1 - y0) * 0.80)] = False
    mask[mask.sum(axis=1) >= max(4, (x1 - x0) * 0.80), :] = False
    ys, xs = np.where(mask)
    if len(xs) < 2:
        return None
    return [
        x0 + int(xs.min()),
        y0 + int(ys.min()),
        int(xs.max()) - int(xs.min()) + 1,
        int(ys.max()) - int(ys.min()) + 1,
    ]


def detect_table_grid(
    image_path: str | Path,
    table_bbox: list[int],
) -> dict[str, list[int]] | None:
    source = cv2.imread(str(image_path))
    if source is None:
        return None
    image_height, image_width = source.shape[:2]
    x, y, width, height = table_bbox
    left = max(0, x)
    top = max(0, y)
    right = min(image_width, x + width)
    bottom = min(image_height, y + height)
    if right - left < 40 or bottom - top < 40:
        return None
    crop = source[top:bottom, left:right]
    edges = cv2.Canny(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), 30, 100)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=40,
        minLineLength=30,
        maxLineGap=5,
    )
    if lines is None:
        return None
    crop_width = right - left
    crop_height = bottom - top
    vertical: list[int] = []
    horizontal: list[int] = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        if abs(int(x2) - int(x1)) <= 2 and abs(int(y2) - int(y1)) >= 30:
            vertical.append(round((int(x1) + int(x2)) / 2))
        if abs(int(y2) - int(y1)) <= 2 and abs(int(x2) - int(x1)) >= crop_width * 0.45:
            horizontal.append(round((int(y1) + int(y2)) / 2))
    x_lines = _group(vertical, tolerance=20)
    y_lines = _group(horizontal)
    if len(x_lines) < 3 or len(y_lines) < 3:
        return None
    x_boundaries = [0]
    x_boundaries.extend(line for line in x_lines if 12 < line < crop_width - 20)
    right_edge = next(
        (line for line in reversed(x_lines) if line <= crop_width - 8),
        crop_width,
    )
    x_boundaries.append(right_edge)
    x_boundaries = sorted(set(x_boundaries))
    y_boundaries = [line for line in y_lines if 0 <= line < crop_height]
    if not y_boundaries:
        return None
    if y_boundaries[0] > 24:
        y_boundaries.insert(0, 0)
    if y_boundaries[-1] < crop_height - 24:
        y_boundaries.append(crop_height)
    y_boundaries = sorted(set(y_boundaries))
    return {
        "source_bbox": [left, top, right - left, bottom - top],
        "x_boundaries": x_boundaries,
        "y_boundaries": y_boundaries,
    }


def _table_bbox(graph: Mapping[str, Any]) -> list[int] | None:
    candidates = []
    for container in graph.get("containers") or []:
        if not isinstance(container, Mapping):
            continue
        role = str(container.get("role") or "").lower()
        if "table" not in role:
            continue
        box = _bbox(container.get("bbox"))
        if box is not None:
            candidates.append(box)
    return max(candidates, key=lambda box: box[2] * box[3]) if candidates else None


def _search_table_grid(
    image_path: str | Path,
    table_bbox: list[int],
    *,
    canvas_size: tuple[int, int],
    column_count: int,
    row_count: int,
) -> dict[str, list[int]] | None:
    left, top, width, height = table_bbox
    bottom = top + height
    if bottom >= canvas_size[1] - 40:
        bottom = canvas_size[1]
    max_delta = 140
    deltas = [0]
    for distance in range(24, max_delta + 1, 24):
        deltas.extend((distance, -distance))
    best: tuple[tuple[int, int, int], dict[str, list[int]]] | None = None
    for delta in deltas:
        candidate_top = max(0, top + delta)
        if bottom - candidate_top < 40:
            continue
        grid = detect_table_grid(
            image_path,
            [left, candidate_top, width, bottom - candidate_top],
        )
        if grid is None:
            continue
        if len(grid["x_boundaries"]) != column_count + 1:
            continue
        if len(grid["y_boundaries"]) < row_count + 1:
            continue
        score = (
            abs(delta),
            len(grid["y_boundaries"]) - (row_count + 1),
            0 if delta >= 0 else 1,
        )
        if best is None or score < best[0]:
            best = (score, grid)
    return best[1] if best is not None else None


def normalize_table_design(
    elements: list[dict[str, Any]],
    image_path: str | Path,
    graph: Mapping[str, Any],
    *,
    canvas_size: tuple[int, int],
) -> list[dict[str, Any]]:
    table_bbox = _table_bbox(graph)
    if table_bbox is None:
        return elements
    model_table = None
    model_table_value: Mapping[str, Any] = {}
    for table in graph.get("tables") or []:
        if not isinstance(table, Mapping):
            continue
        candidate = _bbox(table.get("bbox"))
        if candidate is None:
            continue
        if model_table is None or candidate[2] * candidate[3] > (
            model_table[2] * model_table[3]
        ):
            model_table = candidate
            model_table_value = table
    if model_table is not None:
        model_bbox = list(model_table)
        if model_bbox[1] + model_bbox[3] >= canvas_size[1] - 40:
            model_bbox[3] = canvas_size[1] - model_bbox[1]
        headers = [
            str(value).strip()
            for value in model_table_value.get("header_texts") or []
            if str(value).strip()
        ]
        rows = [
            [str(cell).strip() for cell in row]
            for row in model_table_value.get("rows") or []
            if isinstance(row, (list, tuple))
        ]
        column_count = max(
            len(headers),
            max((len(row) for row in rows), default=0),
        )
        row_values = ([headers] if headers else []) + rows
        table_left, table_top, table_width, table_height = table_bbox
        model_grid = _search_table_grid(
            image_path,
            table_bbox,
            canvas_size=canvas_size,
            column_count=column_count,
            row_count=len(row_values),
        )
        if column_count > 0 and row_values:
            row_boundaries: list[int] = []
            if model_grid and len(model_grid["x_boundaries"]) == column_count + 1:
                tx, ty, _tw, _th = model_grid["source_bbox"]
                x_boundaries = [tx + value for value in model_grid["x_boundaries"]]
                grid_y = [ty + value for value in model_grid["y_boundaries"]]
                needed_boundaries = len(row_values) + 1
                if len(grid_y) >= needed_boundaries:
                    starts_at_grid_top = model_bbox[1] <= grid_y[0] + 24
                    row_boundaries = (
                        grid_y[:needed_boundaries]
                        if starts_at_grid_top
                        else grid_y[-needed_boundaries:]
                    )
            else:
                x_boundaries = [
                    table_left + round(index * table_width / column_count)
                    for index in range(column_count + 1)
                ]
                grid_y = []
            header_top = (
                row_boundaries[0]
                if row_boundaries
                else (
                    max(line for line in grid_y if line <= model_bbox[1] - 8)
                    if any(line <= model_bbox[1] - 8 for line in grid_y)
                    else model_bbox[1]
                )
            )
            header_height = 44
            body_row_height = 36
            table_bottom = table_top + table_height
            removal_bottom = (
                canvas_size[1]
                if table_bottom >= canvas_size[1] - 40
                else table_bottom + 8
            )
            removed = {
                str(element.get("id") or "")
                for element in elements
                if isinstance(element, dict)
                and _element_box(element) is not None
                and table_left
                <= _element_box(element)[0] + _element_box(element)[2] / 2
                <= table_left + table_width
                and header_top - 8
                <= _element_box(element)[1] + _element_box(element)[3] / 2
                <= removal_bottom
                and (
                    element.get("text")
                    or element.get("controlValue")
                    or str(element.get("type") or "") in {"button", "input", "text"}
                )
            }
            grid_elements: list[dict[str, Any]] = []
            if row_boundaries and len(x_boundaries) >= 2:
                grid_left = x_boundaries[0]
                grid_right = x_boundaries[-1]
                grid_top = row_boundaries[0]
                grid_bottom = row_boundaries[-1]
                if headers:
                    grid_elements.append(
                        {
                            "id": "table-grid-header",
                            "type": "container",
                            "x": grid_left,
                            "y": grid_top,
                            "width": max(1, grid_right - grid_left),
                            "height": max(1, row_boundaries[1] - grid_top),
                            "text": "",
                            "role": "table-header",
                            "source": "grounding-table-grid",
                            "style": {"fillColor": TABLE_HEADER_FILL},
                        }
                    )
                for index, boundary in enumerate(row_boundaries):
                    grid_elements.append(
                        {
                            "id": f"table-grid-horizontal-{index}",
                            "type": "container",
                            "x": grid_left,
                            "y": boundary,
                            "width": max(1, grid_right - grid_left),
                            "height": 1,
                            "text": "",
                            "role": "table-grid-horizontal",
                            "source": "grounding-table-grid",
                            "style": {"fillColor": TABLE_GRID_COLOR},
                        }
                    )
                for index, boundary in enumerate(x_boundaries):
                    grid_elements.append(
                        {
                            "id": f"table-grid-vertical-{index}",
                            "type": "container",
                            "x": boundary,
                            "y": grid_top,
                            "width": 1,
                            "height": max(1, grid_bottom - grid_top),
                            "text": "",
                            "role": "table-grid-vertical",
                            "source": "grounding-table-grid",
                            "style": {"fillColor": TABLE_GRID_COLOR},
                        }
                    )
            generated = []
            source = cv2.imread(str(image_path))
            grayscale = (
                cv2.cvtColor(source, cv2.COLOR_BGR2GRAY) if source is not None else None
            )
            previous_bottom = header_top
            for row_index, values in enumerate(row_values):
                if row_boundaries:
                    row_top = row_boundaries[row_index]
                    row_bottom = row_boundaries[row_index + 1]
                else:
                    row_top = (
                        header_top
                        if row_index == 0
                        else header_top
                        + header_height
                        + (row_index - 1) * body_row_height
                    )
                    row_bottom = row_top + (
                        header_height if row_index == 0 else body_row_height
                    )
                    row_top = max(row_top, previous_bottom)
                    row_bottom = row_top + (
                        header_height if row_index == 0 else body_row_height
                    )
                previous_bottom = row_bottom
                current_row_height = row_bottom - row_top
                for column_index in range(column_count):
                    text = (
                        values[column_index].strip()
                        if column_index < len(values)
                        else ""
                    )
                    if not text:
                        continue
                    cell_left = x_boundaries[column_index]
                    cell_right = x_boundaries[column_index + 1]
                    cell_height = max(20, min(24, current_row_height))
                    is_header = row_index == 0 and bool(headers)
                    if is_header:
                        text_x = cell_left
                        text_width = max(8, cell_right - cell_left)
                        vertical_adjust = 0
                    else:
                        is_date = bool(re.match(r"^\d{4}-\d{2}-\d{2}", text))
                        left_pad = 24 if is_date else 12
                        right_pad = 4 if is_date else 8
                        text_x = cell_left + left_pad
                        text_width = max(8, cell_right - text_x - right_pad)
                        vertical_adjust = 0
                    ink_box = (
                        _cell_ink_box(
                            grayscale,
                            cell_left,
                            row_top,
                            cell_right,
                            row_bottom,
                        )
                        if grayscale is not None
                        else None
                    )
                    if ink_box is not None:
                        text_x = ink_box[0] - 1
                        text_width = ink_box[2] + 2
                        if not is_header:
                            text_width = max(
                                text_width,
                                cell_right - text_x - 4,
                            )
                    generated.append(
                        {
                            "id": f"table-model-{row_index}-{column_index}",
                            "type": "text",
                            "x": text_x,
                            "y": row_top
                            + max(0, (current_row_height - cell_height) / 2)
                            + vertical_adjust,
                            "width": text_width,
                            "height": cell_height,
                            "text": text,
                            "controlType": "text",
                            "controlValue": "",
                            "clipToBounds": True,
                            "source": "grounding-table-model",
                            "style": {
                                "fontSize": 17,
                                "lineHeight": 24,
                                "fontWeight": "bold" if is_header else "normal",
                                "textColor": ("#555555" if is_header else "#666666"),
                                "textAlign": (
                                    "start"
                                    if ink_box is not None
                                    else ("center" if is_header else "start")
                                ),
                                "fontFamily": (
                                    "Microsoft YaHei, Noto Sans SC, sans-serif"
                                    if any(
                                        "\u4e00" <= char <= "\u9fff" for char in text
                                    )
                                    else "Segoe UI, Arimo, Arial, sans-serif"
                                ),
                            },
                        }
                    )
            kept = [
                element
                for element in elements
                if str(element.get("id") or "") not in removed
            ]
            return [*kept, *grid_elements, *generated]
    image_height = canvas_size[1]
    expanded = list(table_bbox)
    if expanded[1] + expanded[3] >= image_height - 40:
        expanded[3] = image_height - expanded[1]
    grid = detect_table_grid(image_path, expanded)
    if grid is None:
        return elements
    tx, ty, _tw, _th = grid["source_bbox"]
    x_boundaries = [tx + value for value in grid["x_boundaries"]]
    y_boundaries = [ty + value for value in grid["y_boundaries"]]
    if len(x_boundaries) < 3 or len(y_boundaries) < 3:
        return elements
    candidates = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        text = str(element.get("controlValue") or element.get("text") or "").strip()
        box = _element_box(element)
        if not text or box is None or "icon" in _text(text):
            continue
        center_x = box[0] + box[2] / 2
        center_y = box[1] + box[3] / 2
        if not (
            x_boundaries[0] <= center_x <= x_boundaries[-1]
            and y_boundaries[0] <= center_y <= y_boundaries[-1]
        ):
            continue
        candidates.append((element, box))

    header_index = 0
    for index in range(max(0, len(y_boundaries) - 1)):
        top, bottom = y_boundaries[index], y_boundaries[index + 1]
        if any(
            _text(element.get("controlValue") or element.get("text")) == "#"
            and top <= box[1] + box[3] / 2 <= bottom
            for element, box in candidates
        ):
            header_index = index
            break
    if header_index + 2 >= len(y_boundaries):
        header_index = max(0, len(y_boundaries) - 6)
    y_boundaries = y_boundaries[header_index:]

    owned: dict[tuple[int, int], dict[str, Any]] = {}
    remove_ids: set[str] = set()
    for row in range(len(y_boundaries) - 1):
        top, bottom = y_boundaries[row], y_boundaries[row + 1]
        if bottom - top < 4:
            continue
        for column in range(len(x_boundaries) - 1):
            left, right = x_boundaries[column], x_boundaries[column + 1]
            if right - left < 8:
                continue
            in_cell = [
                (element, box)
                for element, box in candidates
                if left <= box[0] + box[2] / 2 <= right
                and top <= box[1] + box[3] / 2 <= bottom
            ]
            if not in_cell:
                continue
            center_x = (left + right) / 2
            center_y = (top + bottom) / 2
            in_cell.sort(
                key=lambda item: (
                    0 if str(item[0].get("type")) == "text" else 1,
                    abs(item[1][0] + item[1][2] / 2 - center_x)
                    + abs(item[1][1] + item[1][3] / 2 - center_y),
                    -len(_text(item[0].get("controlValue") or item[0].get("text"))),
                )
            )
            kept = in_cell[0][0]
            for removed, _box in in_cell[1:]:
                remove_ids.add(str(removed.get("id") or ""))
            row_height = bottom - top
            cell_height = max(20, min(24, row_height))
            owned[(row, column)] = {
                **copy.deepcopy(kept),
                "id": str(kept.get("id") or f"table-{row}-{column}"),
                "type": "text",
                "text": str(kept.get("controlValue") or kept.get("text") or ""),
                "x": left + 12,
                "y": top + max(0, (row_height - cell_height) / 2),
                "width": max(8, right - left - 24),
                "height": cell_height,
                "controlType": "text",
                "controlValue": "",
                "clipToBounds": True,
                "style": {
                    **(kept.get("style") or {}),
                    "fontSize": 16,
                    "lineHeight": 24,
                    "fontFamily": "Segoe UI, Arimo, Arial, sans-serif",
                },
            }
    if not owned:
        return elements
    output = []
    owned_by_id = {str(element["id"]): element for element in owned.values()}
    for element in elements:
        element_id = str(element.get("id") or "")
        if element_id in owned_by_id:
            output.append(owned_by_id[element_id])
        elif element_id not in remove_ids:
            output.append(element)
    seen = {
        str(element.get("id") or "")
        for element in output
        if str(element.get("type") or "") == "text"
    }
    for element in owned.values():
        if str(element["id"]) not in seen:
            output.append(element)
    return output
