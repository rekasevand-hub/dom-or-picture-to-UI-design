"""语义分区 → 合成容器：集合合法性与发射契约。

这些用例只钉两件事：
1. **分区本身**怎么被判合法/非法（下标、重复、成员数）；
2. **合成容器**能不能被 `resolve_frames` 接受——那是发射端的真判据，不是另写一套。

2026-11-13 的负结论也钉在这里：补底板（`close_backing`）净收益为零，面积比上限
不设时还会把整张表当底板，让 light-form 从 6 个建成掉到 0。
"""

from __future__ import annotations

from src.app.services.rendering.adapter_base import paint_order, resolve_frames
from src.app.services.structure.fidelity.semantic_partition import (
    CONTAINER_ID_PREFIX,
    build_partition_containers,
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
    elements = [
        _element(0, 0, 0, 100, 100),
        _element(1, 10, 10, 40, 20),
        _element(2, 60, 60, 10, 10),
    ]
    merged, stats = build_partition_containers(
        elements, [{"label": "row", "members": [1, 2]}]
    )
    assert stats.containers_created == 1
    assert merged[0]["id"] == "e0"
    assert merged[1]["id"] == f"{CONTAINER_ID_PREFIX}0"
    assert merged[2]["id"] == "e1"


def test_container_is_transparent_and_declares_children() -> None:
    elements = [
        _element(0, 0, 0, 100, 100),
        _element(1, 10, 10, 40, 20),
        _element(2, 60, 60, 10, 10),
    ]
    merged, _ = build_partition_containers(
        elements, [{"label": "row", "members": [1, 2]}]
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
        60,
        60,
    )


def test_resolve_frames_accepts_a_clean_row() -> None:
    elements = [
        _element(0, 0, 0, 200, 100, "container"),
        _element(1, 10, 10, 80, 20, "text", "a"),
        _element(2, 100, 10, 80, 20, "text", "b"),
    ]
    merged, _ = build_partition_containers(
        elements, [{"label": "row", "members": [1, 2]}]
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
    elements = [
        _element(0, 0, 0, 200, 100, "container"),
        _element(1, 10, 10, 80, 20, "text", "a"),
        _element(2, 100, 10, 80, 20, "text", "b"),
    ]
    merged, _ = build_partition_containers(
        elements, [{"label": "row", "members": [1, 2]}]
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
    elements = [
        _element(0, 0, 0, 100, 100),
        _element(1, 10, 10, 40, 20),
        _element(2, 60, 60, 10, 10),
    ]
    merged, _ = build_partition_containers(
        elements, [{"label": "row", "members": [1, 2]}]
    )
    flat = strip_partition_containers(merged)
    assert [item["id"] for item in flat] == ["e0", "e1", "e2"]
