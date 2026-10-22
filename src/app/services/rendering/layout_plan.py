# -*- coding: utf-8 -*-
"""Auto Layout 施工图（IR 侧）：把扁平的 DesignSpec 折回「哪些容器能整体当 Frame」。

这一层只看**结构**，不看像素 —— 它的输入是采集到的 DOM 树（`pIdx` 父指针 + 布局字段）
与已经拼好的 DesignSpec。

## 规则（竖切第一刀：单行 / 单列）

按 DOM 树自底向上走一遍，每个节点都先问一句「我自己能不能当一个 Frame」：

- **一个 Frame 的成员 = 各子节点「拍平后」的图元**：子节点子树里恰好只剩一个图元时，
  直接把那个图元当成员（中间那些不出像素的包装层透明穿透）；还剩两个以上时，子节点
  必须自己先成龙（递归），否则整块放弃。
- **但成员的「布局盒子」取那个直接子节点的盒子**（包装层层层往上取最顶那层）：拍平只
  该丢包装层，不该把它量出来的盒子也丢掉 —— dushu 的书名是 inline `<a>`，文字盒比所在
  行盒窄 8px，用文字盒当列位置整列就散了（audit §14.1）。包装层子树拍出 ≥2 个图元时
  （它自己没当成 Frame）退回用图元自己的盒子；包装层盒子宽高非正时同样退回。
- **成员 ≥ 2**：只有一个成员的 stack 没有意义（审计 §8 ①：约 3/4 的候选是这种）。
- **成员可以各自落多个节点**（控件 = 底框 + 文本）：输出端会把 Frame 里的子节点全部
  快照复位，落点与扁平渲染相同。只有**容器自己**必须落单节点 —— 带文字的容器当 Frame
  时文字不落盘，这类容器不建 Frame（见 `adapter_base.resolve_frames` 规则 3）。
- **容器自己没有图元也能成龙**：Figma 里就是一个不画底的透明 Frame，把子图元装进去。
  DOM 里大量容器只有 style 没有 fill/border（`direct_design` 不画），这条是 dushu 能
  落地的前提；合成出来的 Frame 不画任何像素，逐像素与不开 Auto Layout 时相同。
- 推断交给 `layout_infer.infer_container`（CSS 路径 → 几何兜底），它跑不通就没有施工图。

输出不是返回值，而是写回元素本身：容器元素上挂 `layout`（Figma 字段名）与
`layoutChildren`（成员 id + 绝对定位/STRETCH/grow 覆盖项）；需要透明 Frame 时新合成一个
容器元素并**插入**到它的第一个成员前面。输出端还要按绘制序与实测几何复核一遍
（见 `adapter_base.resolve_frames`），两层都过才真建 Frame。
"""
from __future__ import annotations

from src.app.services.rendering import layout_infer as li

__all__ = ["build_layout_plan", "LAYOUT_KEYS"]

# 只把这些字段写给输出端；`source` 留着当溯源标签（css / geometry）。
LAYOUT_KEYS = ("mode", "itemSpacing", "primaryAlign", "counterAlign",
               "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
               "source")


def _is_container(el: dict) -> bool:
    """够格当 Frame 的元素类型（矩形/按钮不能装子元素）。"""
    return el.get("type") == "container"


def _children_table(dom_nodes: list[dict]) -> list[list[int]]:
    """按 `pIdx`（最近的已采集祖先下标）建 children 表。"""
    n = len(dom_nodes)
    kids: list[list[int]] = [[] for _ in range(n)]
    for i, node in enumerate(dom_nodes):
        parent = node.get("pIdx")
        if isinstance(parent, int) and 0 <= parent < n and parent != i:
            kids[parent].append(i)
    return kids


def _box_ok(node: dict) -> bool:
    """这个节点的盒子能不能当几何用（宽高都为正）。"""
    try:
        return float(node.get("w") or 0) > 0 and float(node.get("h") or 0) > 0
    except (TypeError, ValueError):
        return False


def _int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _frame_element(dom_index: int, node: dict, items: list[tuple[int, tuple[str, int]]],
                   elements: list[dict], fresh: list[dict]) -> dict:
    """给「没有代表元素」的容器合成一个透明 Frame 元素。

    几何照采集到的 DOM rect（页面绝对坐标）；`zIndex` 取成员里最小的那个（排序上排在
    它们前面），`overlay` 只有成员全是浮层时才是真 —— 与 `paint_order` 的口径对齐。
    """
    handles = [elements[h[1]] if h[0] == "e" else fresh[h[1]] for _d, h in items]
    z_index = min(_int(el.get("zIndex")) for el in handles)
    overlay = all(bool(el.get("overlay")) for el in handles)
    return {
        "id": "autolayout-%d" % dom_index,
        "type": "container",
        "x": _int(node.get("x")), "y": _int(node.get("y")),
        "width": _int(node.get("w")), "height": _int(node.get("h")),
        "text": "",
        "overlay": overlay,
        "zIndex": z_index,
        "name": str(node.get("tag") or "container"),
        "style": {"fillColor": "transparent"},
        "domIndex": dom_index,
    }


def build_layout_plan(elements: list[dict], dom_nodes: list[dict] | None) -> int:
    """给够格的容器元素写上 `layout` / `layoutChildren`；返回写了几个。

    需要透明 Frame 的容器会在 `elements` 里**插入**新合成的容器元素（插在它的第一个
    成员前面，保证 `paint_order` 里紧挨着成员）。`dom_nodes` 缺失（grounding/cv 路线、
    老产物、单测）时什么都不做 —— 既有链路的输出逐字节不变。
    """
    if not elements or not dom_nodes:
        return 0
    n = len(dom_nodes)
    by_dom: dict[int, list[int]] = {}
    for i, el in enumerate(elements):
        dom_index = el.get("domIndex")
        if isinstance(dom_index, int) and 0 <= dom_index < n:
            by_dom.setdefault(dom_index, []).append(i)
    if not by_dom:
        return 0

    kids = _children_table(dom_nodes)
    dom_of_node = {id(node): i for i, node in enumerate(dom_nodes)}

    def parent_of(i: int) -> dict | None:
        p = dom_nodes[i].get("pIdx")
        if isinstance(p, int) and 0 <= p < n and p != i:
            return dom_nodes[p]
        return None

    # items：节点子树「拍平」后剩下的图元，`(dom 下标, 句柄)`；句柄 `("e", 元素下标)`
    # 是已有图元，`("n", 新元素下标)` 是这一次合成出来的透明 Frame。
    #
    # geom：与 items 等长的「几何来源」dom 下标 —— 一个成员在父容器流里的**盒子**是
    # 它所在那个「直接子节点」的盒子。拍平只该丢掉中间那些不出像素的包装层，不该顺手
    # 把包装层的盒子也丢掉：dushu 的书名是个 inline `<a>`，它自己的文字盒 (80x21) 比
    # 所在行盒 (142x22) 窄 8px，用文字盒当列位置，整列就散了。包装层子树拍出 ≥2 个
    # 图元时（它自己没当成 Frame）退回用图元自己的盒子。
    memo: dict[int, list[tuple[tuple[int, tuple[str, int]], int]] | None] = {}
    plans: dict[int, dict] = {}       # dom 下标 -> 施工图
    fresh: list[dict] = []            # 合成出来的 Frame 元素（待插入）

    def prepare(i: int):
        if i in memo:
            return memo[i]
        memo[i] = None                      # 防环（DOM 树无环，这里只是兜底）
        items: list[tuple[int, tuple[str, int]]] = []
        geom: list[int] = []
        for j in kids[i]:
            children = prepare(j)
            if children is None:
                return None             # 子树里已经有做不成的东西，整块放弃
            if len(children) == 1:      # 子树只拍出一个图元：用 j 自己的盒子
                item, _g = children[0]
                items.append(item)
                geom.append(j)
            else:
                for item, g in children:
                    items.append(item)
                    geom.append(g)

        own = by_dom.get(i) or []
        boxes = [e for e in own if _is_container(elements[e])]
        # 同节点既出容器又出别的图元时，容器仍然是那个 Frame；其它图元变成成员。
        box = boxes[0] if len(boxes) == 1 else None
        own_items = [(i, ("e", e)) for e in own if e != box]
        items = own_items + items
        geom = [i] * len(own_items) + geom

        if len(items) >= 2:
            nodes = []
            for (d, _h), g in zip(items, geom):
                source = dom_nodes[g]
                if g == d or not _box_ok(source):
                    nodes.append(dom_nodes[d])
                    continue
                node = dict(source)     # 用包装层的盒子量布局，成员身份仍是那个图元
                dom_of_node[id(node)] = d
                nodes.append(node)
            got = li.infer_container(dom_nodes[i], nodes, parent_of(i))
            spec = got.get("layout")
            if spec:
                if box is None:
                    fresh.append(_frame_element(i, dom_nodes[i], items, elements, fresh))
                    handle: tuple[str, int] = ("n", len(fresh) - 1)
                else:
                    handle = ("e", box)
                plans[i] = {"handle": handle,
                            "layout": {k: spec[k] for k in LAYOUT_KEYS if k in spec},
                            "items": items, "got": got}
                memo[i] = [((i, handle), i)]
                return memo[i]

        memo[i] = list(zip(items, geom))
        return memo[i]

    for i in range(n):
        prepare(i)
    if not plans:
        return 0

    # 每个 Frame 的插入位置 = 它的第一个「叶子成员」在 elements 里的下标（子 Frame 递归取
    # 自己的插入位置）。按位置降序插，先插的下标不会被后来的插入推移；位置相同时子 Frame
    # 先插（它在 `fresh` 里更靠前）、父 Frame 后插落在它前面。
    pos_cache: dict[int, int] = {}

    def insert_pos(dom_index: int) -> int:
        if dom_index in pos_cache:
            return pos_cache[dom_index]
        best: int | None = None
        for _d, handle in plans[dom_index]["items"]:
            if handle[0] == "e":
                value = handle[1]
            else:
                sub_dom = fresh[handle[1]].get("domIndex")
                value = (insert_pos(sub_dom) if sub_dom in plans else handle[1])
            best = value if best is None else min(best, value)
        pos_cache[dom_index] = best if best is not None else 0
        return pos_cache[dom_index]

    for dom_index, plan in plans.items():
        handle = plan["handle"]
        el = elements[handle[1]] if handle[0] == "e" else fresh[handle[1]]
        el["layout"] = dict(plan["layout"])
        members = [elements[h[1]] if h[0] == "e" else fresh[h[1]]
                   for _d, h in plan["items"]]
        children = [{"id": member.get("id")} for member in members]
        # 覆盖项是 `infer_container` 按子节点对象给的（`child` 字段），换回成员下标。
        index_of_dom = {d: k for k, (d, _h) in enumerate(plan["items"])}
        seen: set[int] = set()
        for item in plan["got"].get("children") or []:
            k = index_of_dom.get(dom_of_node.get(id(item.get("child"))))
            if k is None or k in seen:
                continue
            seen.add(k)
            entry = children[k]
            if item.get("positioning") == "ABSOLUTE":
                entry["absolute"] = True
            if item.get("alignSelf") == "STRETCH":
                entry["alignSelf"] = "STRETCH"
            if item.get("grow"):
                entry["grow"] = int(item["grow"])
        el["layoutChildren"] = children

    for pos, _k, element in sorted(
            ((insert_pos(el.get("domIndex")), k, el) for k, el in enumerate(fresh)),
            key=lambda row: (-row[0], row[1])):
        elements.insert(max(0, min(pos, len(elements))), element)
    return len(plans)