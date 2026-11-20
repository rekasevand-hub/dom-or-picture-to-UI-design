"""Row bands that are a table, and the one size its body is set in.

Two rules are locked here: a stack of row bands only becomes a table when its
columns hold up (otherwise a list would be cut into one), and a table body has
one font size even when the per-cell ink measurement disagrees.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.structure.physical_perception import (  # noqa: E402
    TABLE_MIN_COLUMNS,
    _table_from_bands,
)
from src.app.services.structure.fidelity import text_calibration  # noqa: E402


def _page(width: int = 400, height: int = 300) -> np.ndarray:
    page = np.full((height, width, 3), 255, dtype=np.int16)
    page[:, :] = (250, 250, 250)
    return page


def _bands(rows: int, *, top: int = 40, height: int = 40, left: int = 20, right: int = 380):
    return [
        {
            "bbox": [left, top + index * height + 1, right - left, height - 1],
            "role": "row",
            "group": (left, right),
        }
        for index in range(rows)
    ]


def _clusters(count: int, rows: int) -> list[dict]:
    return [
        {
            "left": 30 + index * 80,
            "right": 30 + index * 80 + 60,
            "rows": rows,
            "leftStd": 0.0,
            "rightStd": 0.0,
            "boxes": [],
            "align": "left",
        }
        for index in range(count)
    ]


def test_a_stack_of_rows_with_stable_columns_becomes_one_table() -> None:
    bands = _bands(4)
    table = _table_from_bands(bands, _clusters(4, 4), _page())

    assert table is not None
    # 四条行带合成一张表：上边界就是第一条行带的上沿，下边界是最后一条的下沿。
    assert table["bbox"] == [20, 40, 360, 4 * 40]
    assert len(table["y_boundaries"]) == 5
    assert len(table["x_boundaries"]) >= TABLE_MIN_COLUMNS + 1
    assert table["grid_flags"]["verticals"] is False


def test_a_list_whose_rows_share_no_column_stays_rows() -> None:
    """Two stable columns is a list: the avatar column is a picture, not a cell."""
    assert _table_from_bands(_bands(4), _clusters(2, 4), _page()) is None


def test_two_rows_are_never_a_table() -> None:
    assert _table_from_bands(_bands(2), _clusters(4, 2), _page()) is None


def test_a_column_that_appears_once_is_not_a_column() -> None:
    """Support has to hold: a cluster in one row out of four cannot divide a table."""
    clusters = _clusters(4, 4)
    clusters[3]["rows"] = 1
    table = _table_from_bands(_bands(4), clusters, _page())
    assert table is not None
    # 四条列线里第一条离表格左缘只有 10px（小于列间距下限），所以被并进左缘：
    # 剩下左缘 + 两条列线 + 右缘。
    assert len(table["x_boundaries"]) == 4


def _table_design() -> dict:
    """A 3-column table, 3 body rows, with its header band a separate element.

    That split is how the physical plan writes it: the header band is a
    ``table-header`` element painted over the table, so the table's own children
    are body cells only.
    """
    elements: list[dict] = []
    header_cells = []
    for column in range(3):
        cell = {
            "id": f"h{column}",
            "type": "text",
            "role": "",
            "text": f"H{column}",
            "x": 20 + column * 100,
            "y": 40,
            "width": 80,
            "height": 20,
            "style": {"fontSize": 15.25},
        }
        elements.append(cell)
        header_cells.append({"id": cell["id"]})
    elements.append(
        {
            "id": "table-grid-header-0",
            "type": "rectangle",
            "role": "table-header",
            "x": 10,
            "y": 38,
            "width": 320,
            "height": 24,
            "layoutChildren": header_cells,
        }
    )
    body_ids = []
    for row in range(3):
        for column in range(3):
            cell = {
                "id": f"c{row}{column}",
                "type": "text",
                "role": "",
                "text": f"R{row}C{column}",
                "x": 20 + column * 100,
                "y": 70 + row * 30,
                "width": 80,
                "height": 20,
                "style": {"fontSize": 11.5},
            }
            elements.append(cell)
            body_ids.append({"id": cell["id"]})
    elements.append(
        {
            "id": "table:1",
            "type": "container",
            "role": "table",
            "x": 10,
            "y": 66,
            "width": 320,
            "height": 94,
            "layoutChildren": body_ids,
        }
    )
    return {"elements": elements}


def test_table_body_takes_one_size_and_the_header_keeps_its_own() -> None:
    design = _table_design()
    by_id = {element["id"]: element for element in design["elements"]}
    groups = text_calibration._table_groups(design)
    assert groups, "the table must be recognised"
    body = [cells for owner, cells in groups if owner.get("role") == "table"]
    heads = [cells for owner, cells in groups if owner.get("role") == "table-header"]
    assert len(body) == 1 and len(body[0]) == 9
    assert len(heads) == 1 and len(heads[0]) == 3

    # 正文每格的墨迹在原图里宽 60、渲染里只有 40：整表一个比值（1.5），
    # 于是每一格都该被拉到 11.5 x 1.5。
    reference = np.full((300, 400), 255, dtype=np.int16)
    rendered = np.full((300, 400), 255, dtype=np.int16)
    for row in range(3):
        for column in range(3):
            box = by_id[f"c{row}{column}"]
            top = box["y"] + 4
            left = box["x"]
            reference[top : top + 12, left : left + 60] = 40
            rendered[top : top + 12, left : left + 40] = 40
    measured = {
        id(by_id[f"c{row}{column}"]): (11.5, 12.0, 8.0)
        for row in range(3)
        for column in range(3)
    }
    changes = text_calibration._align_table_body_fonts(groups, measured, reference, rendered)

    body = {by_id[f"c{row}{column}"]["style"]["fontSize"] for row in range(3) for column in range(3)}
    assert len(body) == 1, body
    assert body == {17.25}
    # 表头行不动：它本来就该比正文大，不是"同列离群"。
    assert {by_id[f"h{column}"]["style"]["fontSize"] for column in range(3)} == {15.25}
    assert len(changes) == 9
