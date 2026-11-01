# -*- coding: utf-8 -*-
"""CSS 布局 → Figma Auto Layout 的推断（移植自 web-to-figma 的 `infer.ts`）。

## 为什么要有这个模块

扁平绝对定位的产物「像但不好改」：dushu 首页 335 个节点里 120 个 button、40 个
container 全是拍平的。要变成「能改的稿」就得把 flex/block 容器还原成 Figma 的
Auto Layout（`layoutMode` + `itemSpacing` + `padding` + 主轴/交叉轴对齐 + 子项
`sizing`）。参考实现见
`D:\\LLM-Data\\oss_refs\\web-to-figma\\packages\\dom-to-figma\\src\\converter\\layout\\infer.ts`。

## 铁律：几何必须能被精确重放

`infer.ts` 的设计核心不是「怎么推断」，而是「**什么时候拒绝推断**」：
每个候选都按推断出的 stack 属性重算一遍各子元素的预期位置，与采集到的实测 rect
逐项比对，任何一项超过 `GEOMETRY_TOLERANCE`(0.6px) 就**整块放弃**，调用方退回
绝对定位——原话是 "applying these to a frame never moves pixels"。

所以本模块的返回值里 `layout is None` 是**正常结果**而不是异常：它表示「这个容器
用绝对定位更安全」。`bail` 字段给出原因，用来统计升级面（见 `scripts/layout_probe.py`）。

## 输入契约（全部来自采集端的只读事实）

容器节点：
- `x` / `y` / `w` / `h`（DesignSpec 元素用 `width`/`height`；两种都认）——**相对页面**
- `display`（缺省 = `block`，见 `capture.DOM_JS` 的约定）
- `flexDirection` / `flexWrap` / `justifyContent` / `alignItems` / `gap` / `padding`
- `borderWidth`（四边同宽时的简写）或 `edges` = `[[side, width, color], ...]`
- `contentSize`：`"w"` / `"h"` / `"wh"`，表示该轴 CSS 声明为内容驱动
  （`auto`/`min-content`/…，由 Typed OM 采到）

子节点额外：`position`、`flexGrow`、`alignSelf`、`order`、`cssFloat`、`contentSize`。

## 两条路径：CSS 语义优先，几何兜底

参考实现只走第一条：**CSS 说这是什么布局**（flex/block/grid）→ 建 spec → 几何验证。
它把「inline 子元素 / float 子元素 / table-cell 容器 / grid」全部 bail —— 但这些 bail
不是因为这些情形**不安全**，而是因为它没实现。

本模块在 CSS 路径拿不出 spec 时再走第二条：**直接看几何**——子元素是否落在同一行
（交叉轴起点对齐）或同一列。是就按「MIN 对齐 + 量出来的 padding/间距」建 spec，
再过**同一把尺子**（`verify_geometry`，0.6px）。多出来的只是覆盖面（容器级：dushu
CSS 15 → 53，antd 106 → 142）。

间距**均匀**时两条路都被同一把尺子把守，「不移动像素」这条铁律不变；间距**不匀**时
（浏览器里来自逐个 margin，而 Figma 的 `itemSpacing` 是单值）几何兜底不 bail：写
`itemSpacing = 0`、跳过重放复核，改用结构判据（同一行/列、主轴单调且不重叠、落在框内）。
那时「不移动像素」靠的是输出端把成员一律 `ABSOLUTE` + 快照复位，而不是重放 —— 见
`归档文档 figma_layout_upgrade_audit.md` §11、§12、§14。

代价要说清：几何路径还原的是**当前这一帧**的静态结果，不携带 CSS 语义 —— 在 Figma 里
改宽度/换内容时，float 行不会像比浏览器那样重排。图的是「能改」，不是「改完还像」。

## 与参考实现的差异（有意为之）

- **加了几何兜底路径**（见上），并且**在那条路上允许间距不匀**：参考实现在
  `uniformGap` 上直接 bail，我们写 `itemSpacing = 0` 并跳过重放（理由见上）。
  CSS 路径（flex / block / inline）仍按参考实现要求间距均匀。
- **wrap / grid / reverse / order 一律 bail**：参考实现用「装箱模拟」支持 wrap/grid，
  代价是 300+ 行；第一刀先把「单行/单列」打通，多行留第二刀。`order != 0` 会让
  视觉序 ≠ DOM 序（输出端按 DOM 序发子元素），也留到后面。
- **采集端丢了 <2px 的子元素、display:none 的子元素**：这些会让 gap 不齐 →
  自动 bail（保守失败，即「宁可退回绝对定位」）。
- 采集端只记「某轴声明的关键字」，父级上下文（flex 主轴/交叉轴、是否 stretch）
  的判断放在这里做（`is_content_driven_size`），与 `infer.ts` 的 `isContentDrivenSize` 同构。
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "GEOMETRY_TOLERANCE",
    "infer_container",
    "uniform_gap",
    "gap_span",
    "is_content_driven_size",
]

# 重放出的子元素位置与实测位置之间允许的最大偏差（px）。参考实现同值。
GEOMETRY_TOLERANCE = 0.6

JUSTIFY_MAP = {
    "normal": "MIN",
    "flex-start": "MIN",
    "start": "MIN",
    "left": "MIN",
    "center": "CENTER",
    "flex-end": "MAX",
    "end": "MAX",
    "right": "MAX",
    "space-between": "SPACE_BETWEEN",
    # Figma 引擎把 SPACE_EVENLY 渲染成 space-between（参考实现 oracle batch-01 实测）。
    # 配合「spacing 从实测 rect 量」就能精确复现 space-evenly（前导 gap = g）与
    # space-around（前导 gap = g/2），由 verify_geometry 兜底。
    "space-evenly": "CENTER",
    "space-around": "CENTER",
}

ALIGN_MAP = {
    # baseline 要做字体度量，先不支持 → 查表失败即 bail。
    "normal": "MIN",
    "stretch": "MIN",
    "flex-start": "MIN",
    "start": "MIN",
    "center": "CENTER",
    "flex-end": "MAX",
    "end": "MAX",
}

# 能参与纵向 block 流的块级 display；缺省（无 display 字段）= block。
# 表格内部盒（table-cell / table-row / ...）出现在**非表格**父级里时，浏览器会替它
# 合成匿名 table 包装，这一层本身是块级的（dushu 的 `<li>` 就是 table-cell 封面 +
# 两个 div 的纵向排列，不认它整块推不出来）。
BLOCK_LEVEL_DISPLAYS = frozenset(
    ["block", "flex", "grid", "flow-root", "table", "list-item",
     "table-cell", "table-caption", "table-row", "table-row-group",
     "table-header-group", "table-footer-group"]
)

# 行内级 display：它们共处**一行**（inline formatting context）。
INLINE_LEVEL_DISPLAYS = frozenset(
    ["inline", "inline-block", "inline-flex", "inline-grid", "inline-table", "ruby"]
)

_CONTENT_SIZED = frozenset(["auto", "min-content", "max-content", "fit-content"])


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace("px", "").strip())
    except (TypeError, ValueError):
        return default


def _rect(node: dict) -> tuple[float, float, float, float]:
    """节点矩形 (x, y, w, h)；兼容采集端 `w/h` 与 IR 的 `width/height`。"""
    width = node.get("width", node.get("w"))
    height = node.get("height", node.get("h"))
    return (_num(node.get("x")), _num(node.get("y")), _num(width), _num(height))


def display_of(node: dict) -> str:
    """缺省 `display` 字段等价于 block（`capture.DOM_JS` 的写入约定）。"""
    return str(node.get("display") or "block")


def _borders(node: dict) -> dict[str, float]:
    """四边描边宽度：同宽走 `borderWidth` 简写，否则从 `edges` 还原。"""
    out = {"t": 0.0, "r": 0.0, "b": 0.0, "l": 0.0}
    edges = node.get("edges")
    if isinstance(edges, (list, tuple)) and edges:
        for item in edges:
            if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] in out:
                out[str(item[0])] = _num(item[1])
        return out
    uniform = _num(node.get("borderWidth"))
    return {k: uniform for k in out}


def _paddings(node: dict) -> list[float]:
    """`padding`=[top,right,bottom,left]，缺省全 0。"""
    pad = node.get("padding")
    if isinstance(pad, (list, tuple)) and len(pad) == 4:
        return [_num(v) for v in pad]
    return [0.0, 0.0, 0.0, 0.0]


def _pad_plus_border(node: dict) -> list[float]:
    """Figma 从 frame 边缘开始排，CSS 从 border+padding 之后排 → 相加（参考实现同）。"""
    borders = _borders(node)
    pad = _paddings(node)
    return [pad[0] + borders["t"], pad[1] + borders["r"],
            pad[2] + borders["b"], pad[3] + borders["l"]]


def _content_axes(node: dict) -> str:
    return str(node.get("contentSize") or "")


def _has_content_keyword(node: dict, axis: str) -> bool:
    """该轴 CSS 是否**声明**了内容驱动关键字（不带父级上下文）。

    子项的 STRETCH 判据用这个（`infer.ts:inferChildOverrides` 用的是
    `hasContentSizedKeyword`），而不是上下文相关的 `is_content_driven_size` ——
    后者对 flex 交叉轴的 `auto` 会返回 False（因为 auto 在交叉轴表示 stretch），
    正是我们要认的情形。
    """
    return axis in _content_axes(node)


def gap_span(rects: list[tuple[float, float, float, float]],
             is_row: bool) -> list[float]:
    """逐对主轴间距（按给定顺序）；负值合法，表示两个子项在主轴上重叠。"""
    return [nxt[0] - (prev[0] + prev[2]) if is_row
            else nxt[1] - (prev[1] + prev[3])
            for prev, nxt in zip(rects, rects[1:])]


def uniform_gap(rects: list[tuple[float, float, float, float]], is_row: bool) -> float | None:
    """子元素之间的等间距（沿主轴），不均匀返回 None。

    间距是**从实测 rect 量出来的**，所以 CSS 的 gap 与 margin（含塌陷）都被覆盖；
    负值合法（Figma 支持负 itemSpacing）。
    """
    if len(rects) < 2:
        return 0.0
    gaps = gap_span(rects, is_row)
    first = gaps[0]
    if any(abs(g - first) > GEOMETRY_TOLERANCE for g in gaps):
        return None
    return round(first * 100) / 100


def verify_geometry(spec: dict, parent: tuple[float, float],
                    rects: list[tuple[float, float, float, float]],
                    tol: float = GEOMETRY_TOLERANCE) -> bool:
    """按 spec 重放各子元素位置，与实测 rect 比对；超容差即 False（整块放弃）。

    位置相对父容器**边框盒**左上角（与参考实现、与输出端的子元素坐标口径一致）。
    `tol` 默认 0.6px —— 那是**推断阶段**的口径（「像不像同一个东西」）。
    **输出端不再拿它复核**：成员一律钉死（`ABSOLUTE` + 打开布局前的快照复位），
    落点与重放无关（真机验收见 归档文档 figma_layout_upgrade_audit.md §10、§11、§12）。
    """
    is_row = spec["mode"] == "HORIZONTAL"
    pad_lead = spec["paddingLeft"] if is_row else spec["paddingTop"]
    pad_trail = spec["paddingRight"] if is_row else spec["paddingBottom"]
    pad_cross = spec["paddingTop"] if is_row else spec["paddingLeft"]
    pad_cross_trail = spec["paddingBottom"] if is_row else spec["paddingRight"]

    primary = (lambda r: r[2]) if is_row else (lambda r: r[3])
    cross = (lambda r: r[3]) if is_row else (lambda r: r[2])

    inner = (parent[0] if is_row else parent[1]) - pad_lead - pad_trail
    inner_cross = (parent[1] if is_row else parent[0]) - pad_cross - pad_cross_trail
    total = sum(primary(r) for r in rects)
    count = len(rects)

    spacing = spec["itemSpacing"]
    cursor = pad_lead
    align = spec["primaryAlign"]
    if align == "CENTER":
        cursor += (inner - total - spacing * (count - 1)) / 2
    elif align == "MAX":
        cursor += inner - total - spacing * (count - 1)
    elif align == "SPACE_BETWEEN":
        spacing = (inner - total) / (count - 1) if count > 1 else 0

    for rect in rects:
        expected_primary = cursor
        expected_cross = pad_cross
        if spec["counterAlign"] == "CENTER":
            expected_cross += (inner_cross - cross(rect)) / 2
        elif spec["counterAlign"] == "MAX":
            expected_cross += inner_cross - cross(rect)
        actual_primary = rect[0] if is_row else rect[1]
        actual_cross = rect[1] if is_row else rect[0]
        if (abs(actual_primary - expected_primary) > tol
                or abs(actual_cross - expected_cross) > tol):
            return False
        cursor += primary(rect) + spacing
    return True


def is_content_driven_size(node: dict, parent: dict | None, axis: str) -> bool:
    """该轴 CSS 是否「由内容决定尺寸」（`auto`/`min-content`/…）。

    照搬 `infer.ts:isContentDrivenSize`：
    - 父是 flex：主轴 → 是；交叉轴 → `auto` 表示 stretch，除非 align-self 主动退出；
    - 否则：`height` 在常规流里都是内容驱动；`width` 只有 shrink-wrap 上下文
      （`inline-flex` / 绝对定位 / 浮动）才是。
    """
    if axis not in _content_axes(node):
        return False
    parent_display = display_of(parent) if parent is not None else "block"
    parent_is_flex = "flex" in parent_display
    if parent_is_flex and parent is not None:
        parent_is_row = str(parent.get("flexDirection") or "row").startswith("row")
        is_main = (axis == "w") == parent_is_row
        if is_main:
            return True
        align_self = str(node.get("alignSelf") or "auto")
        resolved = align_self if align_self not in ("auto", "normal") \
            else str(parent.get("alignItems") or "normal")
        return resolved not in ("stretch", "normal")
    if axis == "h":
        return True
    return (display_of(node) == "inline-flex"
            or str(node.get("position") or "static") in ("absolute", "fixed")
            or str(node.get("cssFloat") or "none") != "none")


def _apply_sizing_modes(node: dict, parent_node: dict | None,
                        parent_size: tuple[float, float], spec: dict,
                        children: list[dict],
                        rects: list[tuple[float, float, float, float]],
                        is_row: bool) -> None:
    """只在「可证 no-op」时才把 FIXED 升级成 hug（RESIZE_TO_FIT）。

    参考实现的真机教训（`infer.ts:15-19`）：贴一个不带 sizing 的 stack，Figma 会在
    主轴上 hug-to-content 把画布缩小 —— 所以 sizing 必须显式写，且默认 FIXED。
    """
    spacing = spec["itemSpacing"]
    count = len(rects)
    primary_sizes = [(r[2] if is_row else r[3]) for r in rects]
    primary_content = sum(primary_sizes) + spacing * (count - 1) + (
        spec["paddingLeft"] + spec["paddingRight"] if is_row
        else spec["paddingTop"] + spec["paddingBottom"])
    cross_content = max(
        (r[3] if is_row else r[2]) for r in rects) + (
        spec["paddingTop"] + spec["paddingBottom"] if is_row
        else spec["paddingLeft"] + spec["paddingRight"])

    primary_driven = is_content_driven_size(node, parent_node,
                                           "w" if is_row else "h")
    cross_driven = is_content_driven_size(node, parent_node,
                                         "h" if is_row else "w")
    primary_size = parent_size[0] if is_row else parent_size[1]
    cross_size = parent_size[1] if is_row else parent_size[0]

    has_grower = any(_num(c.get("flexGrow")) > 0 for c in children)
    distributes = spec["primaryAlign"] == "SPACE_BETWEEN" or has_grower

    if (primary_driven and not distributes
            and abs(primary_size - primary_content) <= GEOMETRY_TOLERANCE):
        spec["primarySizing"] = "RESIZE_TO_FIT"
    if cross_driven and abs(cross_size - cross_content) <= GEOMETRY_TOLERANCE:
        spec["counterSizing"] = "RESIZE_TO_FIT"


def _child_overrides(children: list[dict],
                     rects: list[tuple[float, float, float, float]],
                     spec: dict, parent_size: tuple[float, float],
                     parent_node: dict, is_row: bool) -> list[dict]:
    """子项的 fill / stretch 覆盖项 —— 同样只在实测尺寸与 Figma 模型吻合时才发。

    - `flex-grow` → `layoutGrow=1`：Figma 的 fill 子项是**等分剩余空间**（没有
      flex-basis 概念），只有实测尺寸等于等分份额时才等价；否则保持 fixed
      （几何一样，只是不能跟着拉伸）。
    - `align-self: stretch` → `layoutAlign=STRETCH`：只在实测交叉轴尺寸等于容器
      内宽/内高时才发。
    """
    out: list[dict] = []
    inner = (parent_size[0] if is_row else parent_size[1]) - (
        spec["paddingLeft"] + spec["paddingRight"] if is_row
        else spec["paddingTop"] + spec["paddingBottom"])
    inner_cross = (parent_size[1] if is_row else parent_size[0]) - (
        spec["paddingTop"] + spec["paddingBottom"] if is_row
        else spec["paddingLeft"] + spec["paddingRight"])
    primary = (lambda r: r[2]) if is_row else (lambda r: r[3])
    cross = (lambda r: r[3]) if is_row else (lambda r: r[2])

    growers = [i for i, c in enumerate(children) if _num(c.get("flexGrow")) > 0]
    if growers:
        fixed_total = sum(primary(rects[i]) for i in range(len(children))
                          if i not in growers)
        share = (inner - fixed_total - spec["itemSpacing"] * (len(children) - 1)
                 ) / len(growers)
        if all(abs(primary(rects[i]) - share) <= GEOMETRY_TOLERANCE for i in growers):
            for i in growers:
                out.append({"index": i, "grow": 1})

    for i, child in enumerate(children):
        align_self = str(child.get("alignSelf") or "auto")
        resolved = align_self if align_self not in ("auto", "normal") \
            else str(parent_node.get("alignItems") or "normal")
        if resolved not in ("stretch", "normal"):
            continue
        cross_prop = "h" if is_row else "w"
        if not _has_content_keyword(child, cross_prop):
            continue
        if abs(cross(rects[i]) - inner_cross) <= GEOMETRY_TOLERANCE:
            out.append({"index": i, "alignSelf": "STRETCH"})
    return out


def _flow_and_absolute(children: list[dict]) -> tuple[list[int], list[int], str | None]:
    """拆出布局参与者与绝对定位子项；`order` 非 0 直接 bail（视觉序 ≠ DOM 序）。"""
    flow: list[int] = []
    absolute: list[int] = []
    for i, child in enumerate(children):
        position = str(child.get("position") or "static")
        if position in ("absolute", "fixed"):
            absolute.append(i)
            continue
        if _num(child.get("order")) != 0:
            return [], [], "order-not-zero"
        flow.append(i)
    return flow, absolute, None


def _flex_stack(node: dict, parent: dict | None, parent_size: tuple[float, float],
                children: list[dict], rects: list[tuple[float, float, float, float]],
                flow: list[int]) -> tuple[dict | None, str | None]:
    direction = str(node.get("flexDirection") or "row")
    if direction.endswith("-reverse"):
        return None, "reverse-unsupported"
    is_row = direction.startswith("row")

    justify = JUSTIFY_MAP.get(str(node.get("justifyContent") or "normal"))
    align = ALIGN_MAP.get(str(node.get("alignItems") or "normal"))
    if justify is None or align is None:
        return None, "justify-or-align-unsupported"

    flow_rects = [rects[i] for i in flow]
    spacing = uniform_gap(flow_rects, is_row)
    if spacing is None:
        return None, "non-uniform-gap"

    pad = _pad_plus_border(node)
    spec = {
        "mode": "HORIZONTAL" if is_row else "VERTICAL",
        "itemSpacing": spacing,
        "primaryAlign": justify,
        "counterAlign": align,
        "primarySizing": "FIXED",
        "counterSizing": "FIXED",
        "paddingTop": round(pad[0] * 100) / 100,
        "paddingRight": round(pad[1] * 100) / 100,
        "paddingBottom": round(pad[2] * 100) / 100,
        "paddingLeft": round(pad[3] * 100) / 100,
    }
    if not verify_geometry(spec, parent_size, flow_rects):
        return None, "geometry-mismatch"
    flow_children = [children[i] for i in flow]
    _apply_sizing_modes(node, parent, parent_size, spec, flow_children,
                        flow_rects, is_row)
    spec["_overrides"] = _child_overrides(flow_children, flow_rects, spec,
                                         parent_size, node, is_row)
    spec["_override_index"] = flow
    return spec, None


def _block_stack(node: dict, parent: dict | None, parent_size: tuple[float, float],
                 children: list[dict], rects: list[tuple[float, float, float, float]],
                 flow: list[int]) -> tuple[dict | None, str | None]:
    for i in flow:
        if display_of(children[i]) not in BLOCK_LEVEL_DISPLAYS:
            return None, "inline-flow-child"
        if str(children[i].get("cssFloat") or "none") != "none":
            return None, "float-child"

    flow_rects = [rects[i] for i in flow]
    spacing = uniform_gap(flow_rects, False)
    if spacing is None:
        return None, "non-uniform-gap"

    first, last = flow_rects[0], flow_rects[-1]
    pad_top = first[1]
    pad_bottom = parent_size[1] - (last[1] + last[3])
    if pad_top < -GEOMETRY_TOLERANCE or pad_bottom < -GEOMETRY_TOLERANCE:
        return None, "content-overflows-frame"   # 内容溢出：做成 stack 会被裁/移位

    pad = _pad_plus_border(node)
    for align in ("MIN", "CENTER", "MAX"):
        spec = {
            "mode": "VERTICAL",
            "itemSpacing": spacing,
            "primaryAlign": "MIN",
            "counterAlign": align,
            "primarySizing": "FIXED",
            "counterSizing": "FIXED",
            "paddingTop": round(max(pad_top, 0) * 100) / 100,
            "paddingRight": round(pad[1] * 100) / 100,
            "paddingBottom": round(max(pad_bottom, 0) * 100) / 100,
            "paddingLeft": round(pad[3] * 100) / 100,
        }
        if not verify_geometry(spec, parent_size, flow_rects):
            continue
        flow_children = [children[i] for i in flow]
        _apply_sizing_modes(node, parent, parent_size, spec, flow_children,
                            flow_rects, False)
        # block 子项 `width:auto` 会撑满内容盒 —— 正是 Figma 纵向 stack 的 STRETCH
        inner_width = parent_size[0] - pad[1] - pad[3]
        overrides = []
        for local, i in enumerate(flow):        # index 用 flow 内下标（与 flex 路径同口径）
            if (_has_content_keyword(children[i], "w")
                    and abs(rects[i][2] - inner_width) <= GEOMETRY_TOLERANCE):
                overrides.append({"index": local, "alignSelf": "STRETCH"})
        spec["_overrides"] = overrides
        spec["_override_index"] = flow
        return spec, None

    return None, "geometry-mismatch"


def _inline_row(node: dict, parent_size: tuple[float, float],
                children: list[dict],
                rects: list[tuple[float, float, float, float]],
                flow: list[int]) -> tuple[dict | None, str | None]:
    """行内格式化上下文：**一行**行内级子项（`<span>` / `<a>` / inline-block 图标 + 文本）。

    与 `_geometry_stack` 的差别只在交叉轴判据：行内项按**基线**对齐，高度不同的项
    top 并不相等（6px 状态点 vs 19px 文字行框），所以这里认「同一条带」（纵向区间
    相交），不认「top 相等」。

    主轴仍然**量**出来：x 单调、区间不重叠、间距均匀。「不重叠」是关键 —— 两个区间
    在 x 上叠在一起说明它们是层叠（如 `<svg>` 里套一个内圈），不是一行，这种照样退回
    扁平。落点仍然钉死在原 x/y 上（§12），所以基线的错位不影响像素，这里只是
    「这一串真的排在一行里」的证据检查。

    有意不做的事与 `_geometry_stack` 一致：只发 MIN 对齐（不猜 text-align 的居中/
    右对齐）、不发 grow/stretch。
    """
    for i in flow:
        if display_of(children[i]) not in INLINE_LEVEL_DISPLAYS:
            return None, "inline-mixed-child"
    flow_rects = [rects[i] for i in flow]
    if len(flow_rects) < 2:
        return None, "inline-run-too-short"

    # 单行判据：全体子项共有一段纵向条带（换行后两排的条带交集为空）。
    band_top = max(r[1] for r in flow_rects)
    band_bottom = min(r[1] + r[3] for r in flow_rects)
    if band_top > band_bottom - GEOMETRY_TOLERANCE:
        return None, "inline-wrapped"

    top = min(r[1] for r in flow_rects)
    bottom = max(r[1] + r[3] for r in flow_rects)
    left = min(r[0] for r in flow_rects)
    right = max(r[0] + r[2] for r in flow_rects)
    for prev, nxt in zip(sorted(flow_rects), sorted(flow_rects)[1:]):
        if nxt[0] < prev[0] + prev[2] - GEOMETRY_TOLERANCE:
            return None, "inline-overlap"

    spacing = uniform_gap(flow_rects, True)
    if spacing is None:
        return None, "non-uniform-gap"

    parent_w, parent_h = parent_size
    if left < -GEOMETRY_TOLERANCE or top < -GEOMETRY_TOLERANCE:
        return None, "content-overflows-frame"     # 内容溢出：做成 stack 会被裁/移位
    if parent_w - right < -GEOMETRY_TOLERANCE or parent_h - bottom < -GEOMETRY_TOLERANCE:
        return None, "content-overflows-frame"

    def _round(v: float) -> float:
        return round(max(v, 0.0) * 100) / 100

    spec = {
        "mode": "HORIZONTAL", "itemSpacing": spacing,
        "primaryAlign": "MIN", "counterAlign": "MIN",
        "primarySizing": "FIXED", "counterSizing": "FIXED",
        "paddingTop": _round(top), "paddingRight": _round(parent_w - right),
        "paddingBottom": _round(parent_h - bottom), "paddingLeft": _round(left),
    }
    spec["source"] = "css"
    return spec, None


def _geometry_stack(node: dict, children: list[dict],
                     rects: list[tuple[float, float, float, float]],
                     flow: list[int]) -> dict | None:
    """几何兜底：子元素落在同一行 / 同一列 → 就是一个 stack（MIN 对齐）。

    不看 CSS 的布局意图（float / inline / table-cell 都行），只看量出来的几何：
    主轴单调且不重叠、交叉轴起点必须一致；padding 由「子元素集合到容器边框盒的
    余量」直接量出来。

    间距**均匀**时照常写进 `itemSpacing`，并用 `verify_geometry` 重放一遍（构造即
    成立，等于「用 Figma 的排版规则重放还落在原像素上」）。间距**不匀**也不 bail：
    Figma 的 `itemSpacing` 是单值，表达不了逐对不同的 margin（dushu 的书格 `li` 就
    是 [10, 6]），这时写 `itemSpacing = 0` 并**跳过重放复核** —— 成员在输出端一律
    `ABSOLUTE` + 快照复位，间距不参与落点（真机验收见
    `归档文档 figma_layout_upgrade_audit.md` §11、§12、§14）。这是与参考实现的**有意
    分歧**：`infer.ts` 在 `uniformGap` 上直接 bail；我们多一条几何兜底路，在这里放宽
    最小也最自洽。

    有意不做的事：不发 hug（不猜 CSS 的尺寸意图）、不发 grow/stretch（没有 CSS
    语义就不猜可拉伸性）、不做 CENTER/MAX 交叉轴对齐（只认起点一致，最保守）。
    """
    flow_rects = [rects[i] for i in flow]
    tops, lefts = [r[1] for r in flow_rects], [r[0] for r in flow_rects]
    x_non_overlapping = all(
        nxt[0] >= prev[0] + prev[2] - GEOMETRY_TOLERANCE
        for prev, nxt in zip(flow_rects, flow_rects[1:])
    )
    shared_band = min(r[1] + r[3] for r in flow_rects) - max(tops)
    if max(tops) - min(tops) <= GEOMETRY_TOLERANCE or (
        shared_band > GEOMETRY_TOLERANCE and x_non_overlapping
    ):
        is_row = True
    elif max(lefts) - min(lefts) <= GEOMETRY_TOLERANCE:
        is_row = False
    else:
        return None

    spacing = uniform_gap(flow_rects, is_row)
    uniform = spacing is not None
    if not uniform:
        # 不匀（浏览器里多半来自逐个 margin）：主轴还得单调、不重叠，否则根本不是一条
        # 一维流（逆序 / 层叠），那种情况照旧 bail。
        if any(g < -GEOMETRY_TOLERANCE for g in gap_span(flow_rects, is_row)):
            return None
        spacing = 0.0

    pad = _pad_plus_border(node)
    parent_w, parent_h = _rect(node)[2], _rect(node)[3]
    if is_row:
        lead = min(r[0] for r in flow_rects)
        trail = parent_w - max(r[0] + r[2] for r in flow_rects)
        cross_lead = min(r[1] for r in flow_rects)
        cross_trail = parent_h - max(r[1] + r[3] for r in flow_rects)
    else:
        lead = min(r[1] for r in flow_rects)
        trail = parent_h - max(r[1] + r[3] for r in flow_rects)
        cross_lead = min(r[0] for r in flow_rects)
        cross_trail = parent_w - max(r[0] + r[2] for r in flow_rects)
    if lead < -GEOMETRY_TOLERANCE or cross_lead < -GEOMETRY_TOLERANCE:
        return None          # 内容溢出容器：做成 stack 会被裁/移位

    def _round(v: float) -> float:
        return round(max(v, 0.0) * 100) / 100

    if is_row:
        spec = {
            "mode": "HORIZONTAL", "itemSpacing": spacing,
            "primaryAlign": "MIN", "counterAlign": "MIN",
            "primarySizing": "FIXED", "counterSizing": "FIXED",
            "paddingTop": _round(cross_lead), "paddingRight": _round(trail),
            "paddingBottom": _round(cross_trail), "paddingLeft": _round(lead),
        }
    else:
        spec = {
            "mode": "VERTICAL", "itemSpacing": spacing,
            "primaryAlign": "MIN", "counterAlign": "MIN",
            "primarySizing": "FIXED", "counterSizing": "FIXED",
            "paddingTop": _round(lead), "paddingRight": _round(cross_trail),
            "paddingBottom": _round(trail), "paddingLeft": _round(cross_lead),
        }
    # 均匀时留一道保险：重放一遍该落在哪（规格变了也不会误发）。不匀时 `itemSpacing`
    # 写的是 0，重放必然对不上；上面那几条结构判据（同一行/列、单调不重叠、落在框内）
    # 就是这类 spec 的保险。
    if uniform and not verify_geometry(spec, (parent_w, parent_h), flow_rects):
        return None
    spec["source"] = "geometry"
    spec["cssPadding"] = pad
    return spec


def infer_container(node: dict, children: list[dict],
                    parent: dict | None = None) -> dict:
    """推断一个容器的 Auto Layout；不成立时 `layout` 为 None 并给出 `bail` 原因。

    `node` 是容器（父级上下文 `parent` 供 sizing 判断用），`children` 是**按
    采集顺序**的直接子节点（绝对定位的子项也在里面）。返回 `layout` 里的字段名
    直接对应 Figma Plugin API（见 `figma_bridge/code.js`）。
    """
    display = display_of(node)
    if not children:
        return {"layout": None, "bail": "no-children", "children": [],
                "mode": None, "css_bail": None, "detail": "no-children"}

    flow, absolute, bail = _flow_and_absolute(children)
    if bail:
        return {"layout": None, "bail": bail, "children": [], "mode": None,
                "css_bail": bail, "detail": bail}
    if not flow:
        return {"layout": None, "bail": "only-absolute-children",
                "children": [], "mode": None, "css_bail": None,
                "detail": "only-absolute-children"}

    rects = [(_rect(c)[0] - _rect(node)[0], _rect(c)[1] - _rect(node)[1],
              _rect(c)[2], _rect(c)[3]) for c in children]
    parent_size = (_rect(node)[2], _rect(node)[3])

    css_bail: str | None = None
    spec: dict | None = None
    if display in ("flex", "inline-flex"):
        if str(node.get("flexWrap") or "nowrap") != "nowrap":
            css_bail = "wrap-unsupported"
        else:
            spec, css_bail = _flex_stack(node, parent, parent_size, children,
                                         rects, flow)
    elif display in ("block", "flow-root", "inline", "inline-block", "list-item"):
        spec, css_bail = _block_stack(node, parent, parent_size, children,
                                      rects, flow)
        if spec is None and css_bail == "inline-flow-child":
            # 块级容器里混着行内级子项（<span>/<a>/inline-block）时，再按「一行行内项」
            # 试一次（`_block_stack` 只认全块级）；不成则保留原来那句更准的原因。
            inline_spec, _inline_bail = _inline_row(node, parent_size, children,
                                                    rects, flow)
            if inline_spec is not None:
                spec, css_bail = inline_spec, None
    elif display in ("grid", "inline-grid"):
        css_bail = "grid-unsupported"
    else:
        css_bail = "display-not-layout-container:%s" % display

    # Grid/wrap/reverse retain two-dimensional or ordering semantics that a
    # one-dimensional geometry fallback cannot represent safely. Keep the
    # subtree at fixed coordinates instead of guessing a linear stack.
    if spec is None and css_bail in {
        "grid-unsupported",
        "wrap-unsupported",
        "reverse-unsupported",
    }:
        return {
            "layout": None,
            "bail": f"{css_bail};fixed-fallback-required",
            "children": [],
            "mode": None,
            "css_bail": css_bail,
            "detail": f"{css_bail};fixed-fallback-required",
        }
    if spec is None:
        spec = _geometry_stack(node, children, rects, flow)
    if spec is None:
        return {"layout": None, "bail": "geometry-not-a-line",
                "children": [], "mode": None, "css_bail": css_bail,
                "detail": "%s;geometry-not-a-line" % css_bail if css_bail
                else "geometry-not-a-line"}

    overrides: list[dict] = []
    for item in spec.pop("_overrides", []):
        local = item["index"]
        if not 0 <= local < len(flow):          # 防御：下标越界宁可丢弃覆盖项
            continue
        overrides.append({"child": flow[local], **{
            k: v for k, v in item.items() if k != "index"}})
    for i in absolute:
        overrides.append({"child": i, "positioning": "ABSOLUTE"})
    spec.pop("_override_index", None)
    spec.setdefault("source", "css")
    spec.pop("cssPadding", None)
    return {"layout": spec, "bail": None, "children": overrides,
            "mode": spec["mode"], "css_bail": css_bail,
            "detail": None if spec["source"] == "css"
            else "geometry-fallback"}
