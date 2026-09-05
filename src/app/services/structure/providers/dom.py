# -*- coding: utf-8 -*-
"""DOM 路线：由 Playwright 收集的 DOM JSON 构建 PageGraph（容器=语义/背景/大区块，元素=交互/文本/图）。"""
from __future__ import annotations

import json

from src.app.services.structure.graph import new_graph, add_container, add_element
from src.app.services.structure.providers.base import BaseProvider, ProviderContext
from src.app.utils.style_utils import build_style

CONTAINER_ROLES = {"header", "nav", "main", "aside", "footer", "section", "form", "article"}
INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea"}
# 图标字体常用码位（私有区 PUA + 补充私有区）；这些字形只在屏幕上可见，
# 作为文本落到 DesignSpec 会渲染成乱码/豆腐块，进入 PageGraph 前要剥离。
_ICON_CP_RANGES = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))


def _normalize_role(node: dict) -> str:
    return (node.get("role") or "").lower().strip()


def _distinct_bg(node: dict) -> bool:
    bg = (node.get("bg") or "").strip().lower()
    page_bg = (node.get("pageBg") or "").strip().lower()
    if not bg or bg in ("rgba(0, 0, 0, 0)", "transparent"):
        return False
    return bg != page_bg


def strip_icon_glyphs(text: str) -> str:
    """去掉图标字体私有区字形，保留可读正文；整段纯图标的叶子返回空串。

    如 el-icon/iconfont/FontAwesome 把字形映射到 \\uE000-\\uF8FF 等私有区码位，
    截图里能显示成小图标，但拿去做文字还原只会得到乱码或缺字方块。
    """
    if not text:
        return ""
    kept = []
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _ICON_CP_RANGES):
            continue
        kept.append(ch)
    return "".join(kept).strip()


def _style_from_node(node: dict) -> dict:
    """从 DOM 节点抽取可直出 DesignSpec 的 computed style（缺失/透明不写）。"""
    return build_style(bg=node.get("bg"), page_bg=node.get("pageBg"),
                       color=node.get("color"), fontSize=node.get("fontSize"),
                       fontWeight=node.get("fontWeight"),
                       borderRadius=node.get("borderRadius"),
                       borderColor=node.get("borderColor"),
                       borderWidth=node.get("borderWidth"))


def _canvas_bbox(node: dict, canvas_w: int, canvas_h: int) -> list[int] | None:
    """把节点 bbox 裁剪到截图画布内；完全在画布外（如横向溢出隐藏列）返回 None。

    DOM 里横向滚动容器的隐藏内容 rect 会超出截图宽度（诊断曾出现 x+w>1452 的
    219 个节点），这些像素截图里根本不存在，不能进入 PageGraph/SoM。
    只保留与画布相交的可视部分：跨界节点就地 clamp 到画布边界。
    """
    x0, y0 = max(0, int(node["x"])), max(0, int(node["y"]))
    x1 = min(canvas_w, int(node["x"]) + int(node["w"]))
    y1 = min(canvas_h, int(node["y"]) + int(node["h"]))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return [x0, y0, x1 - x0, y1 - y0]


# 浮层判定（定位 + 几何）：
# - 候选只取 fixed/sticky 与 absolute（z≥0；负 z 是画在内容之下的装饰层），
#   避免把普通流式布局/表格本身误判——antd 固定列正是 absolute z=1 的整列容器
#   （老版）或单元格级 sticky（v5）；
# - 文档序在后的候选与“前面的兄弟内容”发生实质重叠才算盖在上面，且前面的
#   节点 z 更高（吸顶/弹层先入 DOM）时不算；重叠要求像素量级（≥1500px² 且
#   宽≥30/高≥15），避免 1px 边框/徽标贴边误判；
# - 子节点经文档序祖先继承 overlay，保证固定列的按钮/图标整体随列浮动（含 zIndex）。
_OVERLAY_MIN_AREA = 800            # 太小的是图标/角标装饰，不进浮层判定
_OVERLAY_MIN_OVERLAP_PX = 1500     # 与前面兄弟内容的最小重叠像素面积
_OVERLAY_MIN_OVERLAP_W = 30        # 重叠最小宽（px）
_OVERLAY_MIN_OVERLAP_H = 15        # 重叠最小高（px）


# 空交互按钮的语义回填：antd 系常把操作列做成 <a><i aria-label="图标: form"></i></a>，
# <a> 没有任何可读正文（<i> 又是不产出文本的纯图标叶子），导致还原成空按钮。
# aria 图标名 -> 常用按钮文案；箭头/翻页/排序类（caret-*、left/right/down…）不属于
# 操作语义，保持空更安全（真实标题由列头/页码文本承担）。
_ICON_ARIA_PREFIXES = ("图标:", "图标：", "icon:", "icon：")
_ICON_ARIA_LABELS = {
    "form": "编辑", "edit": "编辑", "delete": "删除", "search": "搜索",
    "plus": "新增", "download": "下载", "upload": "上传",
    "setting": "设置", "settings": "设置", "close": "关闭",
    "eye": "查看", "eye-invisible": "隐藏",
    "reload": "刷新", "refresh": "刷新", "redo": "重做",
}


def _icon_aria_text(aria: str) -> str:
    """图标型 aria-label 转可读文案；无前缀（真实可读名）原样返回；不认识/结构图标返回空。"""
    if not aria:
        return ""
    s = aria.strip()
    for prefix in _ICON_ARIA_PREFIXES:
        if s.startswith(prefix):
            return _ICON_ARIA_LABELS.get(s[len(prefix):].strip().lower(), "")
    return s


def _empty_button_fallback_text(nodes, rects, i, bbox, text_leaves, aria_idxs):
    """交互按钮无可读文字时，用自身/最内层子孙的图标 aria 语义回填按钮文案。

    仅当该按钮整棵子树都不含可读正文叶子时回填（如 <a><i aria-label="图标: form"/>），
    避免覆盖真实标题来自子 span 的排序/导航触发器——它们的文字已作为独立 text 元素
    输出，按钮本身留空即可。
    """
    own = (nodes[i].get("ariaLabel") or "").strip()
    if own:
        txt = _icon_aria_text(own)
        if txt:
            return txt
    bx0, by0, bw, bh = bbox
    box_area = bw * bh
    for j in text_leaves:
        rj = rects[j]
        if rj[2] * rj[3] >= box_area:
            continue
        if _box_covers(bbox, rj):
            return ""   # 子树已有正文叶子：标题交给独立文字元素，不回填
    best, best_area = "", None
    for j in aria_idxs:
        if j == i:
            continue
        rj = rects[j]
        if rj[2] * rj[3] >= box_area:
            continue
        if not _box_covers(bbox, rj):
            continue
        txt = _icon_aria_text(nodes[j].get("ariaLabel", ""))
        if not txt:
            continue
        area = rj[2] * rj[3]
        if best_area is None or area < best_area:
            best, best_area = txt, area
    return best


def _node_z_index(node: dict) -> int:
    try:
        return int(node.get("zIndex") or 0)
    except (TypeError, ValueError):
        return 0


def _node_box(node: dict, canvas_w: int, canvas_h: int) -> list[int]:
    b = _canvas_bbox(node, canvas_w, canvas_h)
    return b if b is not None else [int(node["x"]), int(node["y"]),
                                    int(node["w"]), int(node["h"])]


def _is_overlay_positioned(node: dict) -> bool:
    pos = (node.get("position") or "").strip().lower()
    if pos in ("fixed", "sticky"):
        return True
    return pos == "absolute" and _node_z_index(node) >= 0


def _box_covers(a: list[int], b: list[int]) -> bool:
    return (a[0] <= b[0] and a[1] <= b[1]
            and a[0] + a[2] >= b[0] + b[2] and a[1] + a[3] >= b[1] + b[3])


def _box_intersection_area(a: list[int], b: list[int]) -> int:
    iw = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    ih = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return iw * ih


def _overlay_flags(nodes: list[dict], rects: list[list[int]]) -> list[bool]:
    flags = [False] * len(nodes)
    for i, node in enumerate(nodes):
        if not _is_overlay_positioned(node):
            continue
        a = rects[i]
        area = (a[2] * a[3]) if a else 0
        if area < _OVERLAY_MIN_AREA:
            continue
        for j in range(i):   # 只与文档序在前的内容比“后画者压住先画者”
            b = rects[j]
            if not b:
                continue
            if _box_covers(a, b) or _box_covers(b, a):
                continue  # 祖先/后代（含等大包夹）不算兄弟重叠
            ow = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
            oh = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
            if ow < _OVERLAY_MIN_OVERLAP_W or oh < _OVERLAY_MIN_OVERLAP_H:
                continue
            inter = ow * oh
            if inter >= _OVERLAY_MIN_OVERLAP_PX and _node_z_index(nodes[j]) <= _node_z_index(node):
                flags[i] = True
                break
    return flags


def _overlay_context(nodes: list[dict], rects: list[list[int]],
                     flags: list[bool]) -> list[tuple[bool, int]]:
    """文档序栈式传播：子节点继承最近 overlay 祖先的浮层标记与其 zIndex。"""
    stack: list[tuple[int, int, int, int, bool, int]] = []
    ctx: list[tuple[bool, int]] = [(False, 0)] * len(nodes)
    for i, node in enumerate(nodes):
        a = rects[i]
        if not a:
            continue
        # 栈元素统一按 (x, y, w, h) 存，与 _box_covers 的约定一致
        while stack and not _box_covers(list(stack[-1][:4]), a):
            stack.pop()
        overlay, z = False, 0
        for entry in reversed(stack):
            if entry[4]:
                overlay, z = True, entry[5]
                break
        if flags[i]:
            overlay, z = True, _node_z_index(node)
        ctx[i] = (overlay, z)
        stack.append((a[0], a[1], a[2], a[3], bool(flags[i]), z))
    return ctx


class DomProvider(BaseProvider):
    name = "dom"

    def run(self, ctx: ProviderContext) -> dict:
        with open(ctx.dom_path, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "dom")
        rects = [_node_box(n, ctx.image_w, ctx.image_h) for n in nodes]
        overlay_ctx = _overlay_context(nodes, rects,
                                       _overlay_flags(nodes, rects))
        # 容器候选：语义角色 / 明显背景块 / 大区块(>25% 高或宽 且面积>2000)
        for i, n in enumerate(nodes):
            if _normalize_role(n) in CONTAINER_ROLES or _distinct_bg(n) or (
                n["w"] * n["h"] > 2000 and (n["w"] >= ctx.image_w * 0.5 or n["h"] >= ctx.image_h * 0.5)):
                bbox = _canvas_bbox(n, ctx.image_w, ctx.image_h)
                if bbox is None:
                    continue
                is_overlay, z_index = overlay_ctx[i]
                add_container(g, bbox,
                              role=_normalize_role(n) or n["tag"],
                              source=f"dom:{n['tag']}", style=_style_from_node(n),
                              overlay=is_overlay, z_index=z_index)
        # 元素候选：交互 / 叶子文本 / 图片
        # 预索引：可读正文叶子 / 带 aria 的节点，供空按钮语义回填做几何查找
        text_leaves = [i for i, n in enumerate(nodes)
                       if strip_icon_glyphs(n.get("text", "")) and rects[i]]
        aria_idxs = [i for i, n in enumerate(nodes)
                     if (n.get("ariaLabel") or "").strip() and rects[i]]
        for i, n in enumerate(nodes):
            is_image = n["tag"] in ("img", "svg")
            text = strip_icon_glyphs(n.get("text", ""))
            # 纯图标字形的叶子（如 <i class="iconfont">）不是可读正文，直接跳过
            if not n["interactive"] and not is_image and not text:
                continue
            bbox = _canvas_bbox(n, ctx.image_w, ctx.image_h)
            if bbox is None:
                continue
            is_overlay, z_index = overlay_ctx[i]
            etype = "button" if n["tag"] in ("button", "a", "select") else (
                "input" if n["tag"] in ("input", "textarea") else (
                "image" if is_image else "text"))
            # 纯图标操作列按钮（<a><i aria-label="图标: form"/></a>）没有可读文字，
            # 从自身/子孙 aria 图标名回填成“编辑/删除”等操作文案，避免空按钮
            if not text and etype == "button" and n["tag"] in ("a", "button", "select"):
                text = _empty_button_fallback_text(nodes, rects, i, bbox,
                                                   text_leaves, aria_idxs)
            add_element(g, bbox, type_=etype,
                        text=text, role=_normalize_role(n),
                        source=f"dom:{n['tag']}", style=_style_from_node(n),
                        overlay=is_overlay, z_index=z_index)
        return g
