"""The three P0/P1 fixes, pinned by the shapes that used to break them.

Each test is the failing case from the audit, reduced: a right-aligned column
whose left edges are 40px apart, a table with one stray label, a container tree
that used to point at itself.  They are written to fail loudly if the fix is
ever reverted by accident.
"""

from __future__ import annotations

import pytest

from src.app.services.structure import line_rulers as lr
from src.app.services.structure.physical_perception import (
    _classify,
    _link_container_tree,
    _split_side_icons,
    column_clusters,
    infer_text_table,
)


def node(name: str, box: list[int]) -> dict:
    return {"id": name, "bbox": list(box), "parent_id": None, "children": []}


# --------------------------------------------------------------- right align


def test_a_right_aligned_column_survives_a_40px_left_edge_gap() -> None:
    # 金额列：右缘都是 500，宽度 40/80/100 → 左缘 460/420/400，相邻差 20 和 40。
    # 任何按左缘的单链聚类都会把它们拆成三个孤点。
    boxes = [[460, 100, 40, 20], [420, 150, 80, 20], [400, 200, 100, 20]]
    assert lr.right_aligned_boxes(boxes) == {0, 1, 2}


def test_column_clusters_finds_the_same_column_across_widths() -> None:
    bands = [
        {"bbox": [380, 90 + index * 50, 200, 44], "role": "row", "group": (380, 580)}
        for index in range(3)
    ]
    texts = [[460, 100, 40, 20], [420, 150, 80, 20], [400, 200, 100, 20]]
    clusters = column_clusters(texts, bands)
    assert clusters and clusters[0]["align"] == "right"


def test_three_fragments_on_one_row_are_not_a_column() -> None:
    # 同一行并排三段字：右缘可能在同一条竖线上，但它们只有一行。
    boxes = [[100, 100, 40, 20], [160, 100, 80, 20], [260, 100, 100, 20]]
    assert lr.right_aligned_boxes(boxes) == set()


def test_a_left_aligned_column_is_still_called_left() -> None:
    boxes = [[100, 100, 40, 20], [100, 150, 80, 20], [100, 200, 100, 20]]
    assert lr.right_aligned_boxes(boxes) == set()


# ------------------------------------------------------------------- columns


def test_a_stray_label_does_not_become_a_table_column() -> None:
    # 5 行 × 3 列，某一行多了一个远处的短标签。没有支持度门槛时它会单独立一列。
    rows = []
    for index in range(5):
        y = 100 + index * 40
        rows.append([0, y, 60, 20])
        rows.append([120, y, 60, 20])
        rows.append([240, y, 60, 20])
    rows.append([900, 260, 40, 20])  # 只出现一次
    table = infer_text_table(rows)
    assert table is not None
    assert len(table["x_boundaries"]) - 1 == 3


def test_a_real_column_survives_the_support_filter() -> None:
    rows = []
    for index in range(6):
        y = 100 + index * 40
        for x in (0, 120, 240, 360):
            rows.append([x, y, 60, 20])
    table = infer_text_table(rows)
    assert table is not None
    assert len(table["x_boundaries"]) - 1 == 4


# ---------------------------------------------------------------------- tree


def test_a_container_tree_never_points_at_itself() -> None:
    outer = node("outer", [0, 0, 500, 400])
    mid = node("mid", [20, 20, 300, 200])
    inner = node("inner", [40, 40, 100, 60])
    _link_container_tree([inner, mid, outer], [])
    assert outer["parent_id"] is None
    assert mid["parent_id"] == "outer"
    # break 生效：inner 认最小的父，不会被 outer 覆写。
    assert inner["parent_id"] == "mid"


def test_a_container_tree_records_child_containers_not_only_leaves() -> None:
    outer = node("outer", [0, 0, 500, 400])
    inner = node("inner", [40, 40, 100, 60])
    leaf = {"id": "t1", "bbox": [50, 50, 20, 20], "parent_id": "inner", "children": []}
    _link_container_tree([inner, outer], [leaf])
    assert "inner" in outer["children"]
    assert "t1" in inner["children"]


def test_coincident_containers_do_not_parent_each_other() -> None:
    a = node("a", [0, 0, 100, 100])
    b = node("b", [0, 0, 100, 101])  # 差 1px，互相包含
    _link_container_tree([a, b], [])
    # 只允许"小的认大的"：严格面积比较挡住了反向认父，因此不会成环。
    assert a["parent_id"] == "b"
    assert b["parent_id"] is None


# ------------------------------------------------------------------- roles


def test_a_page_sized_region_is_a_panel_not_a_card() -> None:
    assert _classify([0, 0, 1000, 800], 1000, 800) == "panel"
    assert _classify([320, 0, 400, 300], 1000, 800) == "card"


@pytest.mark.parametrize("tag", [("header"), ("sidebar")])
def test_header_and_sidebar_are_still_recognised(tag: str) -> None:
    if tag == "header":
        assert _classify([0, 0, 1000, 80], 1000, 800) == "header"
    else:
        assert _classify([0, 0, 200, 600], 1000, 800) == "sidebar"


def test_side_icon_split_returns_an_empty_list_not_none() -> None:
    import numpy as np

    image = np.zeros((40, 40, 3), dtype=np.uint8)
    # 框里没有文字：这个分支过去返回 None，调用处的 for 会直接 TypeError。
    assert _split_side_icons(image, [0, 0, 40, 40], []) == []
