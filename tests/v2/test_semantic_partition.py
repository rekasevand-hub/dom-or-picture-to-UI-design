"""语义分区 → 合成容器：集合合法性、行级过滤、命名确定性。

三条硬约束钉在这里：
1. **一组一个父级**、成员必须有 id 与矩形（集合合法性，不是几何合法性）；
2. **只发射行级**——宽高比不达标的组不建容器，记 `aspect-too-low`；
3. **名字由几何派生**——同一份分区重跑，`行 NN` 与 `partition:NN` 必须逐位相同，
   否则下游按名找帧会在两次运行之间漂移。

2026-11-13 的负结论也钉在这里：补底板（`close_backing`）净收益为零，面积比上限
不设时还会把整张表当底板，让 light-form 从 6 个建成掉到 0。
"""

from __future__ import annotations

from src.app.services.rendering.adapter_base import paint_order, resolve_frames
from src.app.services.structure.fidelity.semantic_partition import (
    CONTAINER_ID_PREFIX,
    build_partition_containers,
    design_fingerprint,
    strip_partition_containers,
    validate_partition,
)


def _element(
    index: int,
    x: int,
    y: int,
    w: int,
    h: int,
    kind: str = "rectangle",
    text: str = "",
) -> dict:
    return {
        "id": f"e{index}",
        "type": kind,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "text": text,
    }


def _row() -> list[dict]:
    """一条 170x20 的行（宽高比 8.5），用来测发射。"""
    return [
        _element(0, 0, 0, 200, 100, "container"),
        _element(1, 10, 10, 80, 20, "text", "a"),
        _element(2, 100, 10, 80, 20, "text", "b"),
    ]


def test_validate_rejects_out_of_range_and_duplicates() -> None:
    groups, rejects = validate_partition(
        {
            "groups": [
                {"label": "ok", "members": [0, 1]},
                {"label": "range", "members": [0, 99]},
                {"label": "dup", "members": [1, 2]},
                {"label": "small", "members": [3]},
            ]
        },
        4,
    )
    assert [group["label"] for group in groups] == ["ok"]
    reasons = {item.label: item.reason for item in rejects}
    assert reasons == {
        "range": "member-out-of-range",
        "dup": "member-claimed-twice",
        "small": "fewer-than-two-members",
    }


def test_validate_rejects_oversized_group() -> None:
    groups, rejects = validate_partition(
        {"groups": [{"label": "huge", "members": list(range(40))}]}, 40
    )
    assert groups == []
    assert rejects[0].reason == "group-too-large"


def test_container_is_inserted_before_its_earliest_member() -> None:
    merged, stats = build_partition_containers(
        _row(), [{"label": "row", "members": [1, 2]}]
    )
    assert stats.containers_created == 1
    assert merged[0]["id"] == "e0"
    assert merged[1]["id"] == f"{CONTAINER_ID_PREFIX}01"
    assert merged[2]["id"] == "e1"


def test_container_is_transparent_and_declares_children() -> None:
    merged, _ = build_partition_containers(
        _row(), [{"label": "row", "members": [1, 2]}]
    )
    container = merged[1]
    assert container["transparent"] is True
    assert container["layout"] == {"mode": "NONE"}
    assert container["layoutChildren"] == [{"id": "e1"}, {"id": "e2"}]
    assert (
        container["x"],
        container["y"],
        container["width"],
        container["height"],
    ) == (
        10,
        10,
        170,
        20,
    )


def test_name_is_chinese_prefix_and_model_label_stays_out() -> None:
    merged, _ = build_partition_containers(
        _row(), [{"label": "列表项·第 7 行数据", "members": [1, 2]}]
    )
    container = merged[1]
    assert container["name"] == "行 01"
    assert "行数据" not in container["name"]
    assert container["imageMVP"]["vlmLabel"] == "列表项·第 7 行数据"


def test_naming_is_deterministic_even_if_group_order_changes() -> None:
    """同一批组换个顺序传进来，名字与 id 必须不变（按 (y, x) 排，不按模型顺序）。"""
    elements = [
        _element(0, 0, 0, 400, 300, "container"),
        _element(1, 10, 200, 80, 20, "text", "lower"),
        _element(2, 100, 200, 80, 20, "text", "lower-b"),
        _element(3, 10, 20, 80, 20, "text", "upper"),
        _element(4, 100, 20, 80, 20, "text", "upper-b"),
    ]
    lower = {"label": "下", "members": [1, 2]}
    upper = {"label": "上", "members": [3, 4]}
    first, _ = build_partition_containers(elements, [lower, upper])
    second, _ = build_partition_containers(elements, [upper, lower])

    def names(merged: list[dict]) -> list[tuple[str, str]]:
        return [
            (item["id"], item["name"])
            for item in merged
            if str(item.get("id") or "").startswith(CONTAINER_ID_PREFIX)
        ]

    assert names(first) == names(second)
    # 出现顺序跟着元素下标走，编号跟着 (y, x) 走——两者不是同一个序，所以比较排序后的集合。
    assert sorted(name for _id, name in names(first)) == ["行 01", "行 02"]
    by_name = {
        item["name"]: item
        for item in first
        if str(item.get("id") or "").startswith(CONTAINER_ID_PREFIX)
    }
    assert by_name["行 01"]["imageMVP"]["vlmLabel"] == "上"
    assert by_name["行 02"]["imageMVP"]["vlmLabel"] == "下"


def test_non_row_group_is_not_emitted() -> None:
    """宽高比 1.0 的方块不建容器——本期只收行级。"""
    elements = [
        _element(0, 0, 0, 200, 200, "container"),
        _element(1, 10, 10, 60, 60, "text", "a"),
        _element(2, 80, 10, 60, 60, "text", "b"),
    ]
    merged, stats = build_partition_containers(
        elements, [{"label": "card", "members": [1, 2]}]
    )
    assert stats.containers_created == 0
    assert [item.reason for item in stats.groups_rejected] == ["aspect-too-low"]
    assert [item["id"] for item in merged] == ["e0", "e1", "e2"]


def test_aspect_threshold_is_configurable() -> None:
    elements = [
        _element(0, 0, 0, 200, 200, "container"),
        _element(1, 10, 10, 60, 60, "text", "a"),
        _element(2, 80, 10, 60, 60, "text", "b"),
    ]
    merged, stats = build_partition_containers(
        elements, [{"label": "card", "members": [1, 2]}], min_aspect_ratio=1.0
    )
    assert stats.containers_created == 1
    assert merged[1]["name"] == "行 01"


def test_resolve_frames_accepts_a_clean_row() -> None:
    merged, _ = build_partition_containers(
        _row(), [{"label": "row", "members": [1, 2]}]
    )
    frames = resolve_frames(merged, paint_order(merged), {})
    assert len(frames) == 1


def test_resolve_frames_rejects_when_a_stranger_sits_inside() -> None:
    """成员之间夹着一个相交的外人 → 建 Frame 会改笔序，必须拒。

    外人放在两个成员之间的空档（95..105），既不与成员相交，又落在 Frame 矩形内：
    这正是 2026-11-13 五族里 `covers-other-element` 的形状。
    """
    elements = [
        _element(0, 0, 0, 200, 100, "container"),
        _element(1, 10, 10, 80, 20, "text", "a"),
        _element(2, 95, 12, 10, 16, "rectangle"),
        _element(3, 100, 10, 80, 20, "text", "b"),
    ]
    merged, _ = build_partition_containers(
        elements, [{"label": "row", "members": [1, 3]}]
    )
    reasons: dict[int, str] = {}
    frames = resolve_frames(merged, paint_order(merged), reasons)
    assert frames == {}
    assert "covers-other-element" in reasons.values()


def test_close_backing_stays_off_by_default() -> None:
    merged, _ = build_partition_containers(
        _row(), [{"label": "row", "members": [1, 2]}]
    )
    assert merged[1]["layoutChildren"] == [{"id": "e1"}, {"id": "e2"}]


def test_close_backing_excludes_a_much_larger_backing() -> None:
    """细行不能把整张表当底板——面积比上限就是这条实测的产物。"""
    elements = [
        _element(0, 0, 0, 400, 400, "container"),
        _element(1, 10, 10, 300, 20, "text", "a"),
        _element(2, 200, 10, 80, 20, "text", "b"),
    ]
    merged, _ = build_partition_containers(
        elements,
        [{"label": "row", "members": [1, 2]}],
        canvas={"width": 400, "height": 400},
        close_backing=True,
    )
    container = merged[1]
    assert [child["id"] for child in container["layoutChildren"]] == ["e1", "e2"]


def test_strip_removes_only_partition_containers() -> None:
    merged, _ = build_partition_containers(
        _row(), [{"label": "row", "members": [1, 2]}]
    )
    flat = strip_partition_containers(merged)
    assert [item["id"] for item in flat] == ["e0", "e1", "e2"]


def test_design_fingerprint_is_stable_and_geometry_sensitive() -> None:
    """分区只对同一份元素列表成立：坐标挪 1px 或换个顺序，指纹就必须变。"""
    base = _row()
    assert design_fingerprint(base) == design_fingerprint([dict(item) for item in base])

    moved = [dict(item) for item in base]
    moved[1]["x"] = moved[1]["x"] + 1
    assert design_fingerprint(moved) != design_fingerprint(base)

    reordered = [base[1], base[0], base[2]]
    assert design_fingerprint(reordered) != design_fingerprint(base)


def test_paint_order_is_unchanged_by_transparent_containers() -> None:
    """透明容器不参与覆盖计数：成员与其它元素的相对笔序必须原样不变。

    2026-11-13：不修这条时，light-table 建 10 个行容器后 109/152 个元素名次变化、
    最多挪 97 位；修好后共同元素的绘制序与基线逐位一致。
    """
    from src.app.services.rendering.adapter_base import paint_order

    elements = [
        _element(0, 0, 0, 300, 200, "container"),
        _element(1, 10, 10, 120, 20, "text", "a"),
        _element(2, 140, 10, 120, 20, "text", "b"),
        _element(3, 10, 60, 250, 20, "text", "c"),
        _element(4, 10, 100, 250, 20, "text", "d"),
    ]
    merged, _ = build_partition_containers(
        elements, [{"label": "row", "members": [1, 2]}]
    )
    base = [item.get("id") for _i, item in paint_order(elements)]
    after = [
        item.get("id")
        for _i, item in paint_order(merged)
        if not str(item.get("id") or "").startswith(CONTAINER_ID_PREFIX)
    ]
    assert base == after


def test_container_has_no_fill_so_a_rejected_group_is_invisible() -> None:
    """帧被拒时容器退回普通矩形绘制；没有 fill 时插件会填默认灰 `#d9d9d9`。"""
    merged, _ = build_partition_containers(
        _row(), [{"label": "row", "members": [1, 2]}]
    )
    style = merged[1]["style"]
    assert style["fillColor"] == "transparent"
    assert style["borderColor"] == "transparent"


def test_frame_sits_between_its_ancestor_and_its_members() -> None:
    """行 Frame 的深度必须等于成员那一层——不能固定成 0。

    2026-11-13：透明容器曾被固定成深度 0，于是 Frame 排到自己的祖先之前，
    祖先落入 `resolve_frames` 的「Frame 之后」窗口，被判 `covers-other-element`；
    light-form 12 个行组因此全灭、light-table 只建成 1/10。
    """
    elements = [
        _element(0, 0, 0, 400, 300, "container"),  # 页面
        _element(1, 20, 20, 360, 200, "container"),  # 区块（行的祖先）
        _element(2, 30, 40, 100, 20, "text", "a"),
        _element(3, 160, 40, 100, 20, "text", "b"),
        _element(4, 30, 140, 100, 20, "text", "c"),  # 行外的兄弟，不该进来
    ]
    merged, _ = build_partition_containers(
        elements, [{"label": "row", "members": [2, 3]}]
    )
    frame = next(
        item
        for item in merged
        if str(item.get("id") or "").startswith(CONTAINER_ID_PREFIX)
    )
    order = [item.get("id") for _i, item in paint_order(merged)]
    assert order.index("e1") < order.index(frame["id"]) < order.index("e2")
    assert order.index(frame["id"]) < order.index("e3")

    reasons: dict[int, str] = {}
    frames = resolve_frames(merged, paint_order(merged), reasons)
    assert reasons == {}
    assert len(frames) == 1
    built_index = next(iter(frames))
    assert merged[built_index]["id"] == frame["id"]
