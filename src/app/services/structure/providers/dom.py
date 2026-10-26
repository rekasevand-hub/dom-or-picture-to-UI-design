# -*- coding: utf-8 -*-
"""DOM 路线：由 Playwright 收集的 DOM JSON 构建 PageGraph（容器=语义/背景/大区块，元素=交互/文本/图）。"""

from __future__ import annotations

import json
import re
from typing import Any

from src.app.services.structure.graph import new_graph, add_container, add_element
from src.app.services.structure.asset_metadata import (
    build_asset_record,
    object_fit_source_rect,
    parse_data_uri_asset,
)
from src.app.services.structure.providers.base import BaseProvider, ProviderContext
from src.app.services.structure.site_profiles import load_profile, rule as _rule
from src.app.utils.style_utils import build_style, css_color_to_hex, paints_color

CONTAINER_ROLES = {
    "header",
    "nav",
    "main",
    "aside",
    "footer",
    "section",
    "form",
    "article",
}
INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea"}
# 图标字体常用码位（私有区 PUA + 补充私有区）；这些字形只在屏幕上可见，
# 作为文本落到 DesignSpec 会渲染成乱码/豆腐块，进入 PageGraph 前要剥离。
_ICON_CP_RANGES = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))
# 图标/图片的 DOM 标识：图标字体与组件库会在元素上直接标注（anticon/el-icon/
# iconfont/FontAwesome 这类类名，或 type="icon"、role="img"）。有标识就不必靠像素猜，
# DOM 路线直接把这类叶子判成图标，按 bbox 裁原图像素回填（不需要用户框选）。
_ICON_MARKER_RE = re.compile(
    r"(^|[\s_-])(icon|anticon|iconfont|glyphicon|fa-|el-icon|material-icons)"
)


def _rule_default(section: str, key: str):
    """没有 profile 时的默认值；唯一定义点在 site_profiles.DEFAULTS。"""
    return _rule(None, section, key)


def _looks_like_icon(node: dict) -> bool:
    """节点是否自带图标/图片的 DOM 标识（class 带 icon、type=icon、role=img）。

    只判标识，不判尺寸与文本：调用点已限定"叶子 + 无可见文本 + 非交互控件"。
    """
    cls = (node.get("cls") or "").lower()
    if cls and _ICON_MARKER_RE.search(cls):
        return True
    if (node.get("elType") or "").strip().lower() == "icon":
        return True
    return (node.get("role") or "").strip().lower() == "img"


def _normalize_role(node: dict) -> str:
    return (node.get("role") or "").lower().strip()


# Figma 图层面板的可读名：`tag.cls "标签"`。图层面板里一堆
# Rectangle/Text 时，靠这个才能找到要改的那一层。信息全部来自采集端
# 已有的字段（tag/cls/aria 类），不需要新采。
# 这几项是**经验阈值**（不是等价规则），所以做成 site_profiles 里可覆盖的数据；
# 这里的常量只是"没有 profile 时的默认值"的别名，唯一定义点在 site_profiles.DEFAULTS。
_LABEL_MAX = _rule_default("dom", "label_max_len")
_LABEL_KEYS = ("ariaLabel", "title", "placeholder", "alt")


def _pick_class(raw: str) -> str:
    """从 class 列表里挑一个“最能认出来”的类名。

    实测这批 DOM 的 class 常带重复的命名空间前缀（`fa fa-envelope-o`、
    `glyphicon glyphicon-home`，`fa  fa fa-search` 还带双空格），取第一个
    只会得到 `fa`/`glyphicon` 这种没信息量的。先去重，再丢掉“是别的类名
    前缀”的那些，最后取最长的。
    """
    toks = list(dict.fromkeys(raw.split()))
    keep = [t for t in toks if not any(u != t and u.startswith(t) for u in toks)]
    return max(keep, key=len) if keep else ""


def _layer_name(
    node: dict, text: str = "", fallback_tag: str = "", label_max: int = _LABEL_MAX
) -> str:
    tag = str(node.get("tag") or fallback_tag or "").strip()
    # clsAll 是“所有节点都有”的 class（新采集才有），cls 只有图标节点有
    cls = _pick_class(str(node.get("clsAll") or node.get("cls") or ""))
    head = f"{tag}.{cls}" if tag and cls else (tag or cls)
    label = ""
    for key in _LABEL_KEYS:
        label = " ".join(str(node.get(key) or "").split())
        if label:
            break
    label = label or " ".join(str(text or "").split())
    if len(label) > label_max:
        label = label[: label_max - 1] + "…"
    if label:
        return f'{head} "{label}"' if head else f'"{label}"'
    # 没可读标签的（容器 / 表格单元格居多）律带尺寸兜底：同一个 class
    # 会重复出现好几十次（`td.ant-table-cell`），不带尺寸就分不出谁是谁。
    size = (
        f"{int(node['w'])}×{int(node['h'])}" if node.get("w") and node.get("h") else ""
    )
    return " ".join(p for p in (head, size) if p)


def _distinct_bg(node: dict) -> bool:
    bg = (node.get("bg") or "").strip().lower()
    page_bg = (node.get("pageBg") or "").strip().lower()
    if not bg or bg in ("rgba(0, 0, 0, 0)", "transparent"):
        return False
    return bg != page_bg


def _border_px(node: dict) -> float:
    """computed `border-width` 简写的数值（px）。四边不一致时浏览器给空串，按 0 算。"""
    raw = str(node.get("borderWidth") or "").strip().lower()
    if not raw:
        return 0.0
    try:
        return float(raw.replace("px", "").split()[0])
    except (TypeError, ValueError):
        return 0.0


def _outlined_box(node: dict) -> bool:
    """“空盒子”只靠 CSS 描边可见时的判据（无可见文本、非交互、非图片）。

    antd 的复选框 `.ant-checkbox-inner` 是 16×16 白底 + 1px `#d9d9d9` 描边 + 2px
    圆角，盒子里没有文本也没有子元素，真正的 `<input>` 本体 opacity:0 采集不到：
    它既进不了容器候选（白底 == 页面白被 _distinct_bg 判成冗余，面积 256 又够不上
    大区块），也过不了元素候选的筛子（非交互 / 无文本 / 非图片，直接 skip），于是
    整列复选框在直出稿里从来就没出现过。

    描边本身就是这个盒子在画布上的全部可见像素，所以判据放宽成“有可见的均匀
    描边”。只对**非交互**节点开口子：控件（按钮/输入框）的底色与描边由元素候选
    那条路负责，这里再放行会画出两层形状；描边色等于页面白的（无描边简写被浏览器
    补成 0px 之外的情况）不算，避免凭空造框。
    """
    if node.get("interactive"):
        return False
    if _border_px(node) < 1:
        return False
    edge = css_color_to_hex(node.get("borderColor"))
    return bool(edge and edge != css_color_to_hex(node.get("pageBg")))


def strip_icon_glyphs(
    text: str,
    *,
    preserve_whitespace: bool = False,
) -> str:
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
    cleaned = "".join(kept)
    return cleaned if preserve_whitespace else cleaned.strip()


def _style_from_node(
    node: dict, keep_page_color: bool = False, bg_under: str | None = None
) -> dict:
    """从 DOM 节点抽取可直出 DesignSpec 的 computed style（缺失/透明不写）。

    keep_page_color=True 时，被非页面背景的祖先覆盖的白底节点也保留
    fillColor（白卡叠在灰底上时，白底不是冗余而是关键图层）。
    bg_under 是本节点背后的实心底色，用于把半透明文字色/底色合成成实心 hex。
    """
    style = build_style(
        bg=node.get("bg"),
        page_bg=node.get("pageBg"),
        color=node.get("color"),
        fontSize=node.get("fontSize"),
        fontWeight=node.get("fontWeight"),
        fontFamily=node.get("fontFamily"),
        lineHeight=node.get("lineHeight"),
        textAlign=node.get("textAlign"),
        whiteSpace=node.get("whiteSpace"),
        lineClamp=node.get("lineClamp"),
        letterSpacing=node.get("letterSpacing"),
        opacity=node.get("opacity"),
        borderRadius=node.get("borderRadius"),
        borderColor=node.get("borderColor"),
        borderWidth=node.get("borderWidth"),
        borderStyle=node.get("borderStyle"),
        boxShadow=node.get("boxShadow"),
        keep_page_color=keep_page_color,
        bg_under=bg_under,
    )
    font_style = str(node.get("fontStyle") or "").strip().lower()
    if font_style and font_style != "normal":
        style["fontStyle"] = font_style
    if node.get("fontFamilyRequested"):
        style["fontFamilyRequested"] = node["fontFamilyRequested"]
    if node.get("fontFamilyResolution"):
        style["fontFamilyResolution"] = node["fontFamilyResolution"]
    if node.get("platformFonts"):
        style["platformFonts"] = [
            dict(item) for item in node["platformFonts"] if isinstance(item, dict)
        ]
    return style


def _canvas_bbox(
    node: dict, canvas_w: int, canvas_h: int, min_size: int = 2
) -> list[int] | None:
    """把节点 bbox 裁剪到截图画布内；完全在画布外（如横向溢出隐藏列）返回 None。

    DOM 里横向滚动容器的隐藏内容 rect 会超出截图宽度（诊断曾出现 x+w>1452 的
    219 个节点），这些像素截图里根本不存在，不能进入 PageGraph/SoM。
    只保留与画布相交的可视部分：跨界节点就地 clamp 到画布边界。
    min_size 是"最小可画尺寸"：普通节点 2px（更小的多是残渣），1px 分隔线单独放行。
    """
    x0, y0 = max(0, int(node["x"])), max(0, int(node["y"]))
    x1 = min(canvas_w, int(node["x"]) + int(node["w"]))
    y1 = min(canvas_h, int(node["y"]) + int(node["h"]))
    if x1 - x0 < min_size or y1 - y0 < min_size:
        return None
    return [x0, y0, x1 - x0, y1 - y0]


def _clip_rect(node: dict) -> list[int] | None:
    """DOM_JS 采到的“祖先裁剪矩形” [x, y, w, h]（overflow ≠ visible 的祖先交集）。

    getBoundingClientRect 不知道浏览器会把滚动容器的溢出内容裁掉，于是滚出可视区
    的列（真实页“工艺/线别”，表格横向内容宽到 3329px）在 DOM 里仍是正常盒子；
    采集端把裁剪矩形一并带出来，这里负责据此裁边。
    """
    raw = node.get("clip")
    if not raw:
        return None
    try:
        x, y, w, h = (int(round(float(v))) for v in raw)
    except (TypeError, ValueError):
        return None
    if w < 1 or h < 1:
        return None
    return [x, y, w, h]


def _node_clip(node: dict, canvas_w: int, canvas_h: int) -> list[int] | None:
    """该节点真正生效的裁剪矩形（夹到画布内）；不需要裁时返回 None。

    只在裁剪矩形确实会切到这个节点的盒子时才返回：完全落在裁剪内的节点、没有裁剪
    祖先的节点（含所有旧抓取数据）都不带这个信息，DOM/SoM 形状保持不变。几何与文本
    基线仍按**原始盒子**算——裁边交给输出端的 clipPath，提前把盒子裁小会连 y/h 一起
    改掉，文本基线跟着漂（0.375em 那条公式吃 height）。
    """
    clip = _clip_rect(node)
    if clip is None:
        return None
    x0, y0 = max(0, clip[0]), max(0, clip[1])
    x1 = min(canvas_w, clip[0] + clip[2])
    y1 = min(canvas_h, clip[1] + clip[3])
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    nx0, ny0 = int(node["x"]), int(node["y"])
    nx1, ny1 = nx0 + int(node["w"]), ny0 + int(node["h"])
    if nx0 >= x0 - 1 and ny0 >= y0 - 1 and nx1 <= x1 + 1 and ny1 <= y1 + 1:
        return None
    return [x0, y0, x1 - x0, y1 - y0]


def _clipped_out(box: list[int], clip: list[int] | None) -> bool:
    """盒子在裁剪矩形里完全没有可见面积（整块被滚出/隐藏）→ 不进 PageGraph。"""
    if clip is None:
        return False
    x, y, w, h = box
    return (
        x + w <= clip[0]
        or y + h <= clip[1]
        or x >= clip[0] + clip[2]
        or y >= clip[1] + clip[3]
    )


# 浮层判定（定位 + 几何）：
# - 候选只取 fixed/sticky 与 absolute（z≥0；负 z 是画在内容之下的装饰层），
#   避免把普通流式布局/表格本身误判——absolute/sticky 浮层列、吸顶块是常见
#   形态，因此按定位+重叠判定；
# - 文档序在后的候选与“前面的兄弟内容”发生实质重叠才算盖在上面，且前面的
#   节点 z 更高（吸顶/弹层先入 DOM）时不算；重叠要求像素量级（≥1500px² 且
#   宽≥30/高≥15），避免 1px 边框/徽标贴边误判；
# - 子节点经文档序祖先继承 overlay，保证固定列的按钮/图标整体随列浮动（含 zIndex）。
_OVERLAY_MIN_AREA = _rule_default("dom", "overlay_min_area")
_OVERLAY_MIN_OVERLAP_PX = _rule_default("dom", "overlay_min_overlap_px")
_OVERLAY_MIN_OVERLAP_W = _rule_default("dom", "overlay_min_overlap_w")
_OVERLAY_MIN_OVERLAP_H = _rule_default("dom", "overlay_min_overlap_h")
_EDGE_MAX_THICKNESS = _rule_default("dom", "edge_max_thickness")
_CANVAS_MIN_SIZE = _rule_default("dom", "canvas_min_size")


def _node_z_index(node: dict) -> int:
    try:
        return int(node.get("zIndex") or 0)
    except (TypeError, ValueError):
        return 0


def _node_box(node: dict, canvas_w: int, canvas_h: int) -> list[int]:
    b = _canvas_bbox(node, canvas_w, canvas_h)
    return (
        b
        if b is not None
        else [int(node["x"]), int(node["y"]), int(node["w"]), int(node["h"])]
    )


def _is_overlay_positioned(node: dict) -> bool:
    pos = (node.get("position") or "").strip().lower()
    if pos in ("fixed", "sticky"):
        return True
    return pos == "absolute" and _node_z_index(node) >= 0


def _box_covers(a: list[int], b: list[int]) -> bool:
    return (
        a[0] <= b[0]
        and a[1] <= b[1]
        and a[0] + a[2] >= b[0] + b[2]
        and a[1] + a[3] >= b[1] + b[3]
    )


def _rect_covers_eps(a: list[int], b: list[int], eps: int = 1) -> bool:
    """a 是否完全覆盖 b（允许 eps px 容差）；用于判断白底是否叠在非页面背景祖先上。"""
    return (
        a[0] <= b[0] + eps
        and a[1] <= b[1] + eps
        and a[0] + a[2] >= b[0] + b[2] - eps
        and a[1] + a[3] >= b[1] + b[3] - eps
    )


def _effective_under(
    nodes: list[dict], rects: list[list[int]], paints: list[bool]
) -> list[str]:
    """逐节点求“背后的实心底色”：页面底色 + 覆盖它的前置图层由外到内 alpha 合成。

    直出稿只有实心 hex，而 DOM 里正文/表头大量用 rgba(0,0,0,.65) 这类半透明文字色：
    不合成就会被判成透明、回退纯黑（整页文字比原图更黑）。图层用“几何完全覆盖 +
    文档序在前”近似（与白底保留判定同源），面积由大到小即由外到内。
    """
    under: list[str] = []
    painted: list[int] = []
    for i, node in enumerate(nodes):
        acc = css_color_to_hex(node.get("pageBg")) or "#ffffff"
        rect = rects[i]
        if rect is not None and painted:
            covers = [
                j
                for j in painted
                if rects[j] is not None and _rect_covers_eps(rects[j], rect)
            ]
            covers.sort(key=lambda j: -(rects[j][2] * rects[j][3]))
            for j in covers:
                acc = css_color_to_hex(nodes[j].get("bg"), bg=acc) or acc
        under.append(acc)
        if paints[i]:
            painted.append(i)
    return under


def _box_intersection_area(a: list[int], b: list[int]) -> int:
    iw = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    ih = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return iw * ih


def _overlay_flags(
    nodes: list[dict], rects: list[list[int]], profile=None
) -> list[bool]:
    """判定浮层候选；profile 为站点 profile，可覆盖四个重叠阈值。

    覆盖键见 site_profiles.DEFAULTS["dom"] 的 overlay_*；缺失/不合法就沿用默认，
    无 profile 时行为与当初写死时逐位一致。
    """
    min_area = _rule(profile, "dom", "overlay_min_area")
    min_overlap_px = _rule(profile, "dom", "overlay_min_overlap_px")
    min_overlap_w = _rule(profile, "dom", "overlay_min_overlap_w")
    min_overlap_h = _rule(profile, "dom", "overlay_min_overlap_h")
    flags = [False] * len(nodes)
    for i, node in enumerate(nodes):
        if not _is_overlay_positioned(node):
            continue
        a = rects[i]
        area = (a[2] * a[3]) if a else 0
        if area < min_area:
            continue
        for j in range(i):  # 只与文档序在前的内容比“后画者压住先画者”
            b = rects[j]
            if not b:
                continue
            if _box_covers(a, b) or _box_covers(b, a):
                continue  # 祖先/后代（含等大包夹）不算兄弟重叠
            ow = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
            oh = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
            if ow < min_overlap_w or oh < min_overlap_h:
                continue
            inter = ow * oh
            if inter >= min_overlap_px and _node_z_index(nodes[j]) <= _node_z_index(
                node
            ):
                flags[i] = True
                break
    return flags


def _inside_floating(nodes: list[dict], rects: list[list[int]]) -> list[bool]:
    """节点是否落在某个“绝对/固定定位容器”的盒子里（= 浮层子树）。

    栈式传播（_overlay_context）在这里会漏：antd 左固定列的 wrapper
    `div.ant-table-fixed-left`（61×496）里有个更宽的子层
    `div.ant-table-body-inner`（81×496），文档序走到它时会把 wrapper 弹栈，
    后面的 `table.ant-table-fixed`（61×496）就丢了浮层标记——同一份页面右侧
    固定列（wrapper 内没有更宽子层）却能正确继承。浮层子树的判定直接影响
    “白底算不算冗余”（见 run 里的 keep_white），所以这里按几何直接判，不赌栈。
    """
    out = [False] * len(nodes)
    positioned = [
        j for j, n in enumerate(nodes) if rects[j] and _is_overlay_positioned(n)
    ]
    for i, r in enumerate(rects):
        if not r:
            continue
        out[i] = any(j < i and _box_covers(rects[j], r) for j in positioned)
    return out


def _overlay_context(
    nodes: list[dict], rects: list[list[int]], flags: list[bool]
) -> list[tuple[bool, int]]:
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


def _contained_icon_aria(
    nodes: list[dict], rects: list[list[int]], i: int, bbox: list[int]
) -> str:
    """取按钮子树中最小图标节点的 aria-label 原样返回作语义候选。

    图标按钮常是 <a><i aria-label="..."/></a>：aria 挂在不可交互的图标节点上，
    这里只把它带出为候选字段，不映射成文案（text 仍只含 DOM 可见文本）。
    """
    bw, bh = bbox[2], bbox[3]
    box_area = bw * bh
    best, best_area = "", None
    for j, node in enumerate(nodes):
        if j == i:
            continue
        aria = (node.get("ariaLabel") or "").strip()
        rj = rects[j]
        if not aria or not rj:
            continue
        if rj[2] * rj[3] >= box_area or not _box_covers(bbox, rj):
            continue
        area = rj[2] * rj[3]
        if best_area is None or area < best_area:
            best, best_area = aria, area
    return best


def _covered_by_image(
    nodes: list[dict], rects: list[list[int]], i: int, bbox: list[int]
) -> bool:
    """元素盒是否基本被某个图片节点盖住（图片链接外壳）。

    页脚的 `<a><img 举报徽标></a>` 自身无文字、无背景，直出端却按“控件默认白底”
    补了一块白矩形；它的绘制顺序排在子图片之后，白块直接盖住徽标（实测只上下两条
    蓝边残留）。这类外壳不该再有自身底色。

    只判“白底会盖住图片”的情形：直出稿按阅读顺序（bbox 的 y 再 x，见 graph.
    _reading_key）落笔，图片排在前面才会被白块压住；图片排在后面时白块本就垫在
    图片下（如顶部 logo 链接），去掉它只是白白改产物。
    """
    area = bbox[2] * bbox[3]
    if area <= 0:
        return False
    for j, node in enumerate(nodes):
        if j == i or node.get("tag") not in ("img", "svg"):
            continue
        rj = rects[j]
        if not rj or (rj[1], rj[0]) >= (bbox[1], bbox[0]):
            continue
        ow = min(bbox[0] + bbox[2], rj[0] + rj[2]) - max(bbox[0], rj[0])
        oh = min(bbox[1] + bbox[3], rj[1] + rj[3]) - max(bbox[1], rj[1])
        if ow > 0 and oh > 0 and ow * oh >= area * 0.6:
            return True
    return False


def _text_run_box(node: dict, canvas_w: int, canvas_h: int) -> list[int] | None:
    """混合内容节点的“文本行框”（DOM_JS 用 Range 采到的 textBox），没有则 None。

    元素盒可能比一行高很多——大容器里一段游离的直接文本（如面板标题 + 下方大块
    内容）按元素盒中心估基线会飘到容器中部；行框中心才与输出端的基线公式对得上。
    输入类节点的 textBox 是“内容盒里放一行行框”，走 _placeholder_text，不在这里。
    """
    box = node.get("textBox")
    if not box:
        return None
    try:
        x, y, w, h = (int(round(float(v))) for v in box)
    except (TypeError, ValueError):
        return None
    return _canvas_bbox({"x": x, "y": y, "w": w, "h": h}, canvas_w, canvas_h)


def _asset_metadata_for_node(
    node: dict[str, Any],
    display_box: list[int],
    node_index: int = 0,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    source = str(
        node.get("assetSrc") or next(iter(node.get("bgUrls") or []), "") or ""
    ).strip()
    if not source:
        return None, None
    parsed = parse_data_uri_asset(source)
    natural_size = [
        float(node.get("naturalWidth") or 0),
        float(node.get("naturalHeight") or 0),
    ]
    if (natural_size[0] <= 0 or natural_size[1] <= 0) and parsed.get("natural_size"):
        natural_size = list(parsed["natural_size"])
    is_data_uri = parsed.get("source_kind") == "data-uri"
    complete_data_uri = is_data_uri and len(source) < 20000
    natural_tuple = (
        (natural_size[0], natural_size[1])
        if all(size > 0 for size in natural_size)
        else None
    )
    load_status = (
        "missing" if node.get("tag") == "img" and natural_tuple is None else "loaded"
    )
    asset_record = build_asset_record(
        sample_id="dom",
        node_index=node_index,
        source_kind=("img" if node.get("assetSrc") else "bg-0"),
        source=source,
        natural_size=natural_tuple,
        source_payload_sha256=parsed.get("sha256") if is_data_uri else None,
        mime=parsed.get("mime") if is_data_uri else None,
        source_bytes_present=complete_data_uri,
        source_provenance="data-uri" if is_data_uri else "remote-url",
        display_box=(display_box[0], display_box[1], display_box[2], display_box[3]),
        object_fit=str(node.get("objectFit") or "fill"),
        load_status=load_status,
    )
    identity = {
        "source_kind": parsed.get("source_kind"),
        "source": source[:20000],
        "mime": parsed.get("mime"),
        "byte_length": parsed.get("byte_length"),
        "natural_size": natural_size
        if all(size > 0 for size in natural_size)
        else None,
        "content_sha256": parsed.get("sha256") if complete_data_uri else None,
        "source_ref_sha256": (parsed.get("sha256") if not is_data_uri else None),
        "inline_data_uri": source[:20000] if is_data_uri else None,
        "source_truncated": is_data_uri and not complete_data_uri,
        "asset_record": asset_record,
    }
    crop = None
    if natural_size[0] > 0 and natural_size[1] > 0:
        crop = object_fit_source_rect(
            display_size=display_box[2:4],
            natural_size=natural_size,
            object_fit=str(node.get("objectFit") or "fill"),
            object_position=str(node.get("objectPosition") or "50% 50%"),
        )
        crop["display_box"] = list(display_box)
        crop["natural_size"] = natural_size
    return identity, crop


def _text_geometry_box(
    element_box: list[int],
    text_box: list[int] | None,
    *,
    paints_own_box: bool,
    text_flow: bool,
    element_type: str,
) -> list[int]:
    """Choose the text layout box without shrinking painted element geometry.

    Background and border stay on the element box. A block text node that paints
    its own box still needs the measured text box so padding is not discarded.
    """
    if text_box is None:
        return element_box
    if not paints_own_box:
        return text_box
    if text_flow and element_type == "text":
        return text_box
    return element_box


def _text_paint_style(
    style: dict[str, Any],
    *,
    paints_own_box: bool,
    text_flow: bool,
    element_type: str,
) -> dict[str, Any]:
    """Keep container paint on the container; flow text stays text-only."""
    if not (paints_own_box and text_flow and element_type == "text"):
        return style
    return {
        key: value
        for key, value in style.items()
        if key
        not in {
            "fillColor",
            "borderColor",
            "borderWidth",
            "borderRadius",
            "shadows",
        }
    }


def _run_box_is_single_line(run_box: list[int], style: dict) -> bool:
    """行框是不是“已经排好的一行”（多行的 Range 给的是各行并集，高 ≈ 行数 × 行高）。

    控件文字改用行框落字的前提是单行——单行才没有折行可言。拿不到行高/字号
    （老产物、合成节点）时返回 False，保持“控件内居中”的老行为：宁可不动，也不能
    把多行控件画成一整行。
    """
    try:
        h = float(run_box[3])
    except (TypeError, ValueError, IndexError):
        return False
    lh = 0.0
    try:
        lh = float(style.get("lineHeight"))
    except (TypeError, ValueError):
        lh = 0.0
    if lh <= 0:
        try:
            lh = float(style.get("fontSize")) * 1.2  # 无行高时按默认行高估
        except (TypeError, ValueError):
            return False
    return lh > 0 and h <= lh * 1.5


def _text_runs_box(box: list, canvas_w: int, canvas_h: int) -> list[int] | None:
    """textRuns 里某一段的行框（DOM_JS 已按 Range 量成 [x, y, w, h] 整数）。"""
    try:
        x, y, w, h = (int(round(float(v))) for v in box)
    except (TypeError, ValueError):
        return None
    return _canvas_bbox({"x": x, "y": y, "w": w, "h": h}, canvas_w, canvas_h)


def _text_em_box(node: dict, canvas_w: int, canvas_h: int) -> list[int] | None:
    """节点的「第一行行框」（DOM_JS 用 Range 采到的 textEmBox），没有则 None。

    与 textBox / textRuns 同一口径（整型 + 画布夹取）。它记的是**真实排版出来
    的第一行**落在哪：元素盒可以比行盒高（行高大于盒高的行内元素）也可以矮
    （多行块），行盒中心才是输出端要对的落字基准。
    """
    box = node.get("textEmBox")
    if not box:
        return None
    try:
        x, y, w, h = (int(round(float(v))) for v in box)
    except (TypeError, ValueError):
        return None
    if w < 1 or h < 1:
        return None
    return _canvas_bbox({"x": x, "y": y, "w": w, "h": h}, canvas_w, canvas_h)


def _placeholder_text(
    node: dict, bg_under: str, min_size: int = _CANVAS_MIN_SIZE
) -> dict | None:
    """空输入框的 placeholder：补一个独立文本元素（DOM 里它挂在 <input> 上）。

    placeholder 是输入框内真实渲染的一行灰字，原先直出稿整行缺失。位置取 DOM_JS
    采到的“文本排版盒”（内容盒中的行框），颜色取 ::placeholder 伪元素色——antd 的
    灰字与输入态文字色不同。只在左对齐时输出：居中/右对齐需要给文本输出端传锚点，
    这里不猜位置（宁可留白）。placeholder 本身仍作为输入框的独立语义字段保留。
    """
    ph = (node.get("placeholder") or "").strip()
    box = node.get("textBox")
    align = (node.get("textAlign") or "").strip().lower()
    if not ph or not box or align not in ("start", "left", "justify", ""):
        return None
    try:
        x, y, w, h = (int(round(float(v))) for v in box)
    except (TypeError, ValueError):
        return None
    # 退化文本框（宽/高太小）画不出字：与容器候选同口径，用 profile 的
    # canvas_min_size（默认 2），不再单写一个 2。
    if w < min_size or h < min_size:
        return None
    # 探针节点：抹掉背景/边框（placeholder 元素只画字，不重复画输入框），
    # 文字色换成 placeholder 色
    probe = dict(node)
    probe.update(
        {
            "bg": "",
            "borderColor": "",
            "borderWidth": "",
            "borderRadius": "",
            "color": node.get("placeholderColor") or node.get("color"),
        }
    )
    result = {
        "bbox": [x, y, w, h],
        "style": _style_from_node(probe, bg_under=bg_under),
        "text": ph,
    }
    em_box = node.get("textEmBox")
    if isinstance(em_box, list) and len(em_box) == 4:
        result["textEmBox"] = [int(round(float(value))) for value in em_box]
        result["textEmLines"] = max(1, int(node.get("textEmLines") or 1))
    if isinstance(node.get("textBaseline"), dict):
        result["textBaseline"] = dict(node["textBaseline"])
    return result


def _edge_rect(
    node: dict, side: str, width: int, max_thickness: int = _EDGE_MAX_THICKNESS
) -> list[int] | None:
    """把“单边边框”折成细线矩形（dom 直出不支持单边描边，用 1px 色块替代）。

    表格行的 `border-bottom: 1px solid #e8e8e8` 是这类页面上最常见的分隔线：computed
    borderWidth 简写在四边不一致时为空串，原先整排行线在直出稿里都缺失。
    过粗（超过 edge_max_thickness，默认 8px）的不是分隔线，交给均匀边框路径，
    避免把整块描边画成色块。
    """
    try:
        x, y, w, h = int(node["x"]), int(node["y"]), int(node["w"]), int(node["h"])
    except (KeyError, TypeError, ValueError):
        return None
    t = max(1, int(width))
    if t > max_thickness:
        return None
    if side == "b":
        return [x, y + h - t, w, t]
    if side == "t":
        return [x, y, w, t]
    if side == "l":
        return [x, y, t, h]
    if side == "r":
        return [x + w - t, y, t, h]
    return None


class DomProvider(BaseProvider):
    name = "dom"

    def run(self, ctx: ProviderContext) -> dict:
        with open(ctx.dom_path, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "dom")
        rects = [_node_box(n, ctx.image_w, ctx.image_h) for n in nodes]
        # 站点 profile 可覆盖若干**经验阈值**；无 profile 时用的就是 DEFAULTS。
        # ctx.profile 优先（闭环搜索一次进程里试多组阈值，不走磁盘）。
        prof = ctx.profile if ctx.profile is not None else load_profile(ctx.url)
        cmin = _rule(prof, "dom", "canvas_min_size")
        edge_max = _rule(prof, "dom", "edge_max_thickness")
        label_max = _rule(prof, "dom", "label_max_len")
        c_area = _rule(prof, "dom", "container_min_area")
        c_ratio = _rule(prof, "dom", "container_min_span_ratio")
        # 底色/白底判定：
        # 1) 先求每个节点背后的实心底色（页面底色 + 覆盖它的前置图层合成），
        #    供 build_style 把半透明文字色/底色合成实心 hex——rgba(0,0,0,.65) 的
        #    正文原先被判成透明、直出回退纯黑，整页文字比原图明显更黑；
        # 2) 自身背景等于页面白、但背后另有非页面底色的节点是“叠在灰底/半透明遮罩上
        #    的白卡/白内容区”，keep_page_color=True 保留 fillColor；否则视为画布原生
        #    白底，跳过不写以避免整屏白色矩形堆叠；
        # 3) 例外：**浮层子树里的白底一律保留**。antd 的固定列是
        #    “绝对定位 wrapper（透明，只有滚动阴影）+ 里面一块白板
        #    table.ant-table-fixed”，白板背后按几何算出来也是页面白，但少了它，
        #    被固定列压住的横向滚动列（右缘那截“工艺路线”）就会从透明浮层里透出来。
        #    浮层是“盖在别人上面”的图层，它的底色是不是冗余不能按静态背景判断。
        paints = [paints_color(n.get("bg")) for n in nodes]
        under = _effective_under(nodes, rects, paints)
        overlay_ctx = _overlay_context(nodes, rects, _overlay_flags(nodes, rects, prof))
        floating = _inside_floating(nodes, rects)
        keep_white = []
        text_backing = []  # 本节点自身文字所落的实心底色（自身底色，透明则背后底色）
        for i, n in enumerate(nodes):
            page_hex = css_color_to_hex(n.get("pageBg"))
            solid = css_color_to_hex(n.get("bg"), bg=under[i]) if paints[i] else None
            keep_white.append(
                bool(
                    solid
                    and page_hex
                    and solid == page_hex
                    and (under[i] != page_hex or floating[i])
                )
            )
            text_backing.append(solid or under[i])
        # 容器候选：语义角色 / 明显背景块 / 大区块(面积与占比见 DEFAULTS) /
        # 白底透明但带可见描边的空盒子（复选框、分页选中项、下拉选择框，见 _outlined_box）
        for i, n in enumerate(nodes):
            if (
                _normalize_role(n) in CONTAINER_ROLES
                or _distinct_bg(n)
                or _outlined_box(n)
                or (
                    n["w"] * n["h"] > c_area
                    and (
                        n["w"] >= ctx.image_w * c_ratio
                        or n["h"] >= ctx.image_h * c_ratio
                    )
                )
            ):
                bbox = _canvas_bbox(n, ctx.image_w, ctx.image_h, min_size=cmin)
                if bbox is None:
                    continue
                clip = _node_clip(n, ctx.image_w, ctx.image_h)
                if _clipped_out(bbox, clip):
                    continue
                is_overlay, z_index = overlay_ctx[i]
                add_container(
                    g,
                    bbox,
                    role=_normalize_role(n) or n["tag"],
                    source=f"dom:{n['tag']}",
                    style=_style_from_node(
                        n, keep_page_color=keep_white[i], bg_under=under[i]
                    ),
                    overlay=is_overlay,
                    z_index=z_index,
                    clip=clip,
                    name=_layer_name(n, label_max=label_max),
                    dom_index=i,
                )
        # 非均匀边框（表格行的 1px 分隔线）：逐边补成细线元素。原先只在 borderWidth
        # 简写为空时才补采，而真实页的简写是带 0 的多值（"0px 1px 1px 0px"）→ 整排
        # 行线缺失（真实页 9 条线占整页差异 6.1%）。
        seen_edges: set[tuple] = set()
        for i, n in enumerate(nodes):
            for edge in n.get("edges") or []:
                try:
                    side, width, color = str(edge[0]), float(edge[1]), edge[2]
                except (IndexError, TypeError, ValueError):
                    continue
                if width < 1:
                    continue
                fill = css_color_to_hex(color)
                rect = _edge_rect(n, side, width, max_thickness=edge_max)
                if not fill or rect is None:
                    continue
                bbox = _canvas_bbox(
                    {"x": rect[0], "y": rect[1], "w": rect[2], "h": rect[3]},
                    ctx.image_w,
                    ctx.image_h,
                    min_size=1,
                )
                if bbox is None:
                    continue
                clip = _node_clip(n, ctx.image_w, ctx.image_h)
                if _clipped_out(bbox, clip):
                    continue
                # 相邻单元格的边框会在同一位置重复（td 的右边框 vs 下一列的左边框、
                # 行线 vs 表格外框）：同位置同色只画一条。
                key = (bbox[0], bbox[1], bbox[2], bbox[3], fill)
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                is_overlay, z_index = overlay_ctx[i]
                add_element(
                    g,
                    bbox,
                    type_="divider",
                    source=f"dom:edge-{side}",
                    style={"fillColor": fill},
                    overlay=is_overlay,
                    z_index=z_index,
                    clip=clip,
                    name=f"divider {side}",
                    dom_index=i,
                )
        # 元素候选：交互 / 叶子文本 / 图片 / 图标字形叶子
        for i, n in enumerate(nodes):
            is_image = n["tag"] in ("img", "svg")
            text = strip_icon_glyphs(n.get("text", ""))
            # 图标的两种 DOM 依据：私有区字形叶子（iconBox）或元素自带图标标识
            # （class 带 icon/anticon、type=icon、role=img）。交互控件除外——按钮/链接
            # 要保留控件语义，不能整块换成位图。
            icon_crop = (
                (bool(n.get("iconBox")) or _looks_like_icon(n))
                and not n["interactive"]
                and not text
            )
            # 纯图标的叶子（如 <i class="anticon anticon-search">）不是可读正文：
            # 图标字体把字形映射到私有区码位，作为文本落到直出稿只会是乱码/豆腐块。
            # 改为按 bbox 裁原图像素回填（与 img/svg 同一条链），语义上它本来就是小图。
            if icon_crop:
                is_image = True
            # CSS 背景图（sprite 图标/照片层）：采集端只在“自身无文本、无子元素”时打标，
            # 这里直接当图片按 bbox 裁原图像素（背景渐变色不在其列——那些仍是容器）。
            if n.get("bgImage"):
                is_image = True
            # 纯图标字形的叶子（如 <i class="iconfont">）不是可读正文，直接跳过
            if not n["interactive"] and not is_image and not text:
                continue
            bbox = _canvas_bbox(n, ctx.image_w, ctx.image_h, min_size=cmin)
            if bbox is None:
                continue
            clip = _node_clip(n, ctx.image_w, ctx.image_h)
            if _clipped_out(bbox, clip):
                continue
            is_overlay, z_index = overlay_ctx[i]
            etype = (
                "button"
                if n["tag"] in ("button", "a", "select")
                else (
                    "input"
                    if n["tag"] in ("input", "textarea")
                    else ("image" if is_image else "text")
                )
            )
            style = _style_from_node(
                n, keep_page_color=keep_white[i], bg_under=under[i]
            )
            # 图片链接外壳（如页脚 <a><img 徽标></a>）：无文字、无背景，却被
            # 直出端按“控件默认白底”补一块白矩形，盖住它包着的图片。显式标透明。
            if (
                not text
                and etype == "button"
                and not style.get("fillColor")
                and _covered_by_image(nodes, rects, i, bbox)
            ):
                style["fillColor"] = "transparent"
            # 混合内容节点（既有子元素又有直接文本，如 antd 操作列的
            # <a>编辑<i class="anticon"/></a>）改用“文本行框”当几何：文字按行框排，
            # 而元素盒可能高出一行很多（大容器里一段游离直接文本，基线会飘到中部），
            # 也可能连图标一起框进来（控件内居中会把文字推到图标上，实测偏 12px）。
            # 只换“自身没东西可画”的节点：有底色/描边的盒子是真几何，换掉会把底色块
            # 或描边画小（文本元素的底色块、控件的默认白底与描边都取自这个盒子）。
            run_box = _text_run_box(n, ctx.image_w, ctx.image_h) if text else None
            # 叶子块级文本的“可排盒”（浮动块把行框推到右侧，见 DOM_JS textFlow）：
            # 几何用行框，但它是一整段可折行的文本，不是已经排好的一行——不能挂
            # textLineBox（那会跳过折行，长简介被画成一整行溢出卡片）。
            text_flow = bool(n.get("textFlow"))
            paints_own_box = bool(style.get("fillColor")) or (
                etype != "text" and bool(style.get("borderColor"))
            )
            # 多段直接文本（被子元素隔开的“文本运行”，如 跳至<input/>页）：一段文本只能
            # 画一次，拼成一个字符串画在合并框里第二段的位置必然是错的。主元素画第一
            # 段，其余段按各自行框补成独立 text 元素（与 placeholder 同一条“一个 DOM
            # 节点出多个元素”的路子）。有底色/描边的盒子是真几何，不拆。
            text_runs = n.get("textRuns") or []
            if len(text_runs) > 1 and text and not paints_own_box:
                first = strip_icon_glyphs(
                    str(text_runs[0][0]),
                    preserve_whitespace=True,
                )
                if first:
                    text = first
                    box = _text_runs_box(text_runs[0][1], ctx.image_w, ctx.image_h)
                    if box is not None:
                        run_box = box
            bbox = _text_geometry_box(
                bbox,
                run_box,
                paints_own_box=paints_own_box,
                text_flow=text_flow,
                element_type=etype,
            )
            # 控件自带底色/描边时几何必须留元素盒（底色块/描边都按它画），但**落字**
            # 仍要按真实行框——按盒子居中会把文字推到同级图标上（dushu 导航按钮实测
            # 图标压住首字、「查看更多」左偏 107px）。只认“单行”行框：多行的行框是
            # 各行并集，得走折行那条老路。
            text_box = None
            if (
                run_box is not None
                and paints_own_box
                and etype != "text"
                and _run_box_is_single_line(run_box, style)
            ):
                text_box = run_box
            # 「第一行行框」+ 行数：只有 Axure 出口读它（把控件高对齐到真实落字
            # 位置，见 rendering/axure_adapter）。缺字段不出，其它输出端逐字节不变。
            em_box = _text_em_box(n, ctx.image_w, ctx.image_h) if text else None
            output_style = _text_paint_style(
                style,
                paints_own_box=paints_own_box,
                text_flow=text_flow,
                element_type=etype,
            )
            asset_identity = None
            source_crop = None
            if is_image:
                asset_identity, source_crop = _asset_metadata_for_node(
                    n,
                    bbox,
                    node_index=i,
                )
            aria_label = n.get("ariaLabel", "")
            # 图标按钮自身无 aria 时，把子树图标节点的 aria-label 原样带出为
            # 语义候选（不映射成文案，text 保持 DOM 可见文本）
            if (
                not text
                and etype == "button"
                and not (aria_label or "").strip()
                and n["tag"] in ("a", "button")
            ):
                aria_label = _contained_icon_aria(nodes, rects, i, bbox)
            add_element(
                g,
                bbox,
                type_=etype,
                text=text,
                role=_normalize_role(n),
                source=f"dom:{n['tag']}",
                style=output_style,
                name=_layer_name(n, text=text, fallback_tag=etype, label_max=label_max),
                overlay=is_overlay,
                z_index=z_index,
                aria_label=aria_label,
                title=n.get("title", ""),
                placeholder=n.get("placeholder", ""),
                alt=n.get("alt", ""),
                text_box=text_box,
                text_em_box=em_box,
                text_em_lines=int(n.get("textEmLines") or 0),
                text_lines=n.get("textLines"),
                asset_identity=asset_identity,
                source_crop=source_crop,
                text_line_box=(
                    run_box is not None and not paints_own_box and not text_flow
                ),
                icon_crop=icon_crop,
                clip=clip,
                dom_index=i,
            )
            if len(text_runs) > 1 and not paints_own_box:
                for run in text_runs[1:]:
                    rtext = strip_icon_glyphs(
                        str(run[0]),
                        preserve_whitespace=True,
                    )
                    rbox = _text_runs_box(run[1], ctx.image_w, ctx.image_h)
                    if not rtext or rbox is None:
                        continue
                    if _clipped_out(rbox, clip):
                        continue
                    add_element(
                        g,
                        rbox,
                        type_="text",
                        text=rtext,
                        source="dom:textrun",
                        style=style,
                        overlay=is_overlay,
                        z_index=z_index,
                        text_line_box=True,
                        clip=clip,
                        name=_layer_name(n, text=rtext, label_max=label_max),
                        dom_index=i,
                    )
            if etype == "input" and not text:
                ph = _placeholder_text(n, text_backing[i], min_size=cmin)
                if ph is not None:
                    box = ph["bbox"]
                    pbox = _canvas_bbox(
                        {"x": box[0], "y": box[1], "w": box[2], "h": box[3]},
                        ctx.image_w,
                        ctx.image_h,
                        min_size=cmin,
                    )
                    if pbox is not None and not _clipped_out(pbox, clip):
                        add_element(
                            g,
                            pbox,
                            type_="text",
                            text=ph["text"],
                            source="dom:placeholder",
                            style=ph["style"],
                            overlay=is_overlay,
                            z_index=z_index,
                            clip=clip,
                            name=_layer_name(n, text=ph["text"], label_max=label_max),
                            text_em_box=ph.get("textEmBox"),
                            text_em_lines=int(ph.get("textEmLines") or 0),
                            dom_index=i,
                        )
        return g
