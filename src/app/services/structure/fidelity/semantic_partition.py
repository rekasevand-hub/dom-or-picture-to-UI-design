"""语义分区 → 合成嵌套容器（纯函数，不做任何测量）。

VLM 只回答一件事：哪些元素属于同一块。本模块把这个答案变成
``layout: {"mode": "NONE"}`` 的合成容器，交给 ``resolve_frames`` 逐组验收。

三条设计约束，任何一条都不许在本模块里绕过：

1. **一组一个父级。** 一个元素只能进一个组；跨组重复直接判该组无效。
2. **容器不画东西。** ``transparent=True`` 让插件清空 fills（见 ``code.js`` 的
   ``createFrame``），否则 Figma 的 Frame 默认白底会盖住下面的内容。
3. **容器只落一个节点。** 合成容器不带 ``text``，满足 ``_single_node``；带文字的控件
   当 Frame 时它的文字节点不会落盘，所以那种元素只能当成员，不能当容器。

验收不在本模块：``resolve_frames`` 的四条守门（成员在后、成员闭包、单节点、裁剪
一致）才是判据。被拒的组退回扁平绝对定位，逐像素与不开分区时相同。
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

PARTITION_SCHEMA_VERSION = "semantic-partition/1.0"
CONTAINER_ID_PREFIX = "partition:"

# 单组元素个数的上限。超过这个数基本等于「把半个页面圈成一块」——那种组在
# `resolve_frames` 里必然被 `covers-other-element` 拒掉，先在这里挡掉省一次测量。
MAX_GROUP_MEMBERS = 24

# 本期只发射行级结构。3.0 的来历见 `build_partition_containers` 的 docstring。
DEFAULT_MIN_ASPECT_RATIO = 3.0
DEFAULT_ROW_PREFIX = "行"


@dataclass
class GroupReport:
    """一组分区的处理结果；`reason` 为空表示已生成容器。"""

    index: int
    label: str
    members: list[int]
    reason: str | None = None
    bbox: tuple[int, int, int, int] | None = None


@dataclass
class PartitionStats:
    groups_in: int = 0
    containers_created: int = 0
    groups_rejected: list[GroupReport] = field(default_factory=list)
    groups_accepted_by_schema: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "groups_in": self.groups_in,
            "containers_created": self.containers_created,
            "groups_accepted_by_schema": self.groups_accepted_by_schema,
            "groups_rejected": [
                {
                    "index": item.index,
                    "label": item.label,
                    "members": item.members,
                    "reason": item.reason,
                }
                for item in self.groups_rejected
            ],
        }


def design_fingerprint(elements: Sequence[Mapping[str, Any]]) -> str:
    """这份元素列表的指纹：id + 类型 + 几何，按列表顺序。

    分区用的下标只在**同一份列表**里有意义。2026-11-13 的单页验证就是这样翻车的：
    探针拿校准后的终版算了分区，mvp 却把它套在校准前的设计上——151 个元素顺序一致，
    但 **89 个坐标不同**，组的 bbox 和成员闭包条件全变了，`resolve_frames` 在错的几何
    上放行了 10 个组，`within30` 从 95.60 掉到 59.37。

    指纹进 `partitions.json`，mvp 应用前比对；不一致就拒跑，而不是静默错位。
    """
    rows = [
        [
            str(element.get("id") or ""),
            str(element.get("type") or ""),
            round(float(element.get("x") or 0), 1),
            round(float(element.get("y") or 0), 1),
            round(float(element.get("width") or 0), 1),
            round(float(element.get("height") or 0), 1),
        ]
        for element in elements
    ]
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _element_rect(element: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
    try:
        x = int(round(float(element.get("x"))))
        y = int(round(float(element.get("y"))))
        w = int(round(float(element.get("width"))))
        h = int(round(float(element.get("height"))))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def _union(rects: Sequence[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    left = min(rect[0] for rect in rects)
    top = min(rect[1] for rect in rects)
    right = max(rect[0] + rect[2] for rect in rects)
    bottom = max(rect[1] + rect[3] for rect in rects)
    return (left, top, right - left, bottom - top)


def validate_partition(
    partition: Mapping[str, Any],
    element_count: int,
) -> tuple[list[dict[str, Any]], list[GroupReport]]:
    """把模型输出收敛成合法组；不合法的组带上原因返回，不抛异常。

    只做**集合层面**的合法性（下标范围、重复、成员数）。几何合法性由
    `resolve_frames` 负责——在这里预判几何等于把两套判据写两遍，迟早不一致。
    """
    groups: list[dict[str, Any]] = []
    rejects: list[GroupReport] = []
    raw_groups = partition.get("groups")
    if not isinstance(raw_groups, list):
        return groups, rejects

    claimed: dict[int, int] = {}
    for position, raw in enumerate(raw_groups):
        if not isinstance(raw, Mapping):
            continue
        label = str(raw.get("label") or f"group-{position}")
        raw_members = raw.get("members")
        if not isinstance(raw_members, list):
            rejects.append(GroupReport(position, label, [], "members-not-a-list"))
            continue
        members: list[int] = []
        bad: str | None = None
        for value in raw_members:
            if isinstance(value, bool) or not isinstance(value, int):
                bad = "member-not-an-index"
                break
            if value < 0 or value >= element_count:
                bad = "member-out-of-range"
                break
            members.append(value)
        if bad is not None:
            rejects.append(GroupReport(position, label, members, bad))
            continue
        deduped = list(dict.fromkeys(members))
        if len(deduped) < 2:
            rejects.append(
                GroupReport(position, label, deduped, "fewer-than-two-members")
            )
            continue
        if len(deduped) > MAX_GROUP_MEMBERS:
            rejects.append(GroupReport(position, label, deduped, "group-too-large"))
            continue
        overlap = [index for index in deduped if index in claimed]
        if overlap:
            rejects.append(
                GroupReport(position, label, deduped, "member-claimed-twice")
            )
            continue
        for index in deduped:
            claimed[index] = position
        groups.append({"label": label, "members": deduped})
    return groups, rejects


def _contains(
    outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]
) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[0] + outer[2] >= inner[0] + inner[2]
        and outer[1] + outer[3] >= inner[1] + inner[3]
    )


def _backing_members(
    members: Sequence[int],
    by_index: Mapping[int, Mapping[str, Any]],
    rects: Mapping[int, tuple[int, int, int, int]],
    canvas_area: float,
    max_backing: int = 3,
    max_area_ratio: float = 4.0,
) -> list[int]:
    """把「组的底板」补进成员：包住整组、不是文字、也不铺满整页的那些元素。

    为什么必须补：`resolve_frames` 的成员闭包要求「夹在成员中间、与 Frame 相交的
    图元都必须是成员」。卡片的底板通常被模型漏掉（它只圈文字与图标），于是底板成了
    那个「外人」，整组被判 `covers-other-element`——2026-11-13 实测 14 次拒绝里
    绝大多数是这一条。补底板是几何闭合，不是语义猜测。

    两条排除：
    - 铺满页面的背景：那是画布底，不属于任何一张卡。
    - **面积超过整组 4 倍的底板**：2026-11-13 实测，不设这条时「一行表格」会把整张
      表当底板，Frame 一撑到全表就撞 `covers-other-element`，light-form 从 6 个建成
      掉到 0。`max_area_ratio` 是那条实测的产物，不是先验。
    """
    if not members:
        return []
    group_rect = _union([rects[index] for index in members if index in rects])
    if group_rect[2] <= 0 or group_rect[3] <= 0:
        return []
    group_area = float(group_rect[2]) * float(group_rect[3])
    candidates: list[tuple[int, int]] = []
    for index, element in by_index.items():
        if index in members:
            continue
        rect = rects.get(index)
        if rect is None:
            continue
        if str(element.get("type") or "") == "text":
            continue
        area = float(rect[2]) * float(rect[3])
        if area > canvas_area * 0.4:
            continue
        if group_area and area > group_area * max_area_ratio:
            continue
        if not _contains(rect, group_rect):
            continue
        candidates.append((int(area), index))
    candidates.sort()
    return [index for _area, index in candidates[:max_backing]]


def build_partition_containers(
    elements: Sequence[Mapping[str, Any]],
    groups: Sequence[Mapping[str, Any]],
    *,
    canvas: Mapping[str, Any] | None = None,
    close_backing: bool = False,
    min_aspect_ratio: float = DEFAULT_MIN_ASPECT_RATIO,
    row_prefix: str = DEFAULT_ROW_PREFIX,
) -> tuple[list[dict[str, Any]], PartitionStats]:
    """把合法组变成合成容器，插在各自最早成员之前。

    返回**新列表**（深拷贝），调用方的元素列表不受影响。容器与成员的相对次序按
    「容器先、成员后」排，真正的绘制序仍由 `paint_order` 决定——这里只保证下标
    单调，让 `pos_of` 的比较有确定的起点。

    本期只发射**行级**结构：宽高比低于 `min_aspect_ratio` 的组不建容器，记
    `aspect-too-low`。名字与 id 由组框的 (y, x) 排序派生，与模型给的顺序无关——
    同一份分区重跑必须得到同一批名字。

    ``min_aspect_ratio`` 的 3.0 不是拍的：2026-11-13 五族实测里，18 个能通过
    `resolve_frames` 的组宽高比最小 4.88、最大 79.0，3.0 留了 1.6 倍余量。

    ``close_backing`` 打开后，每组先补上包住它的底板（见 `_backing_members`），
    容器的插入点也跟着前移到最早的那个成员——底板通常画在文字之前，容器必须排在
    它前面才能让 `pos_of[member] > pos_of[frame]` 成立。
    """
    stats = PartitionStats(groups_in=len(groups))
    out: list[dict[str, Any]] = [copy.deepcopy(dict(element)) for element in elements]
    by_index = {index: element for index, element in enumerate(out)}
    rects = {
        index: rect
        for index, element in by_index.items()
        if (rect := _element_rect(element)) is not None
    }
    canvas_size = canvas or {}
    try:
        canvas_area = float(canvas_size.get("width") or 0) * float(
            canvas_size.get("height") or 0
        )
    except (TypeError, ValueError):
        canvas_area = 0.0

    first_member: dict[int, int] = {}
    containers: dict[int, dict[str, Any]] = {}
    for gi, group in enumerate(groups):
        members = [int(value) for value in group.get("members") or []]
        label = str(group.get("label") or f"group-{gi}")
        if not members:
            stats.groups_rejected.append(GroupReport(gi, label, [], "no-members"))
            continue
        missing = [
            index
            for index in members
            if index not in by_index or not by_index[index].get("id")
        ]
        if missing:
            stats.groups_rejected.append(
                GroupReport(gi, label, members, "member-without-id")
            )
            continue
        member_rects = [_element_rect(by_index[index]) for index in members]
        if any(rect is None for rect in member_rects):
            stats.groups_rejected.append(
                GroupReport(gi, label, members, "member-without-rect")
            )
            continue
        if close_backing:
            backing = _backing_members(members, by_index, rects, canvas_area)
            members = sorted(set(members) | set(backing))
        rect = _union([rects[index] for index in members if index in rects])
        if rect[3] <= 0 or rect[2] / rect[3] < min_aspect_ratio:
            # 本期只发射行级结构：宽高比不达标的组直接不建，交给 `resolve_frames`
            # 去拒是浪费一次测量，而且会把「不发射」和「发射不合格」混成一条。
            stats.groups_rejected.append(
                GroupReport(gi, label, members, "aspect-too-low")
            )
            continue
        containers[gi] = {
            "id": f"{CONTAINER_ID_PREFIX}{gi}",
            "type": "container",
            "role": "group",
            "name": label[:60],
            "x": rect[0],
            "y": rect[1],
            "width": rect[2],
            "height": rect[3],
            "text": "",
            "transparent": True,
            # 必须同时把 fill 设成 transparent：`resolve_frames` 拒掉这个组时，
            # 容器会退回普通矩形绘制，而矩形没有 fill 时插件会填 Figma 默认灰
            # `#d9d9d9`——每一行多一条灰底，2026-11-13 一页就掉了 26 个点。
            "style": {"fillColor": "transparent", "borderColor": "transparent"},
            "layout": {"mode": "NONE"},
            "layoutChildren": [{"id": by_index[index]["id"]} for index in members],
            "imageMVP": {
                "source": "vlm-partition",
                "grouping_status": "semantic",
                "memberCount": len(members),
                "vlmLabel": label[:60],
            },
        }
        first_member[gi] = min(members)
        stats.groups_accepted_by_schema += 1

    # 名字与 id 都由**几何**派生，不由组的下标或模型给的顺序派生：同一份分区
    # 重跑必须得到同一批名字，否则下游按名找帧会在两次运行之间漂移。
    # 排序键用 (y, x)，读图层的人看到的是从上到下、从左到右，不是绘制序。
    ordered = sorted(
        containers.items(),
        key=lambda pair: (pair[1]["y"], pair[1]["x"]),
    )
    renamed: dict[int, dict[str, Any]] = {}
    for rank, (gi, container) in enumerate(ordered, start=1):
        container = dict(container)
        container["id"] = f"{CONTAINER_ID_PREFIX}{rank:02d}"
        container["name"] = f"{row_prefix} {rank:02d}"
        renamed[gi] = container
    containers = renamed

    start_at: dict[int, int] = {}
    for gi, index in first_member.items():
        start_at.setdefault(index, gi)

    merged: list[dict[str, Any]] = []
    for index, element in enumerate(out):
        gi = start_at.get(index)
        if gi is not None:
            merged.append(containers[gi])
            stats.containers_created += 1
        merged.append(element)
    return merged, stats


def strip_partition_containers(
    elements: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """移除分区容器，回到扁平列表（用于对比 A/B 两侧）。"""
    return [
        copy.deepcopy(dict(element))
        for element in elements
        if not str(element.get("id") or "").startswith(CONTAINER_ID_PREFIX)
    ]
