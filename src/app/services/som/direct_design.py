# -*- coding: utf-8 -*-
"""结构路线（dom）样式直出 DesignSpec：用 computed style 确定性拼装，跳过 VLM。

PreciseAgent 中 route 实际解析为 dom 时恒定走本规则（不回落 VLM）。
前提：SoM JSON 的 containers/elements 带 style 字段——dom 由 DOM_JS 采集，
由 capture 阶段直接落盘，样式齐备后走同一条直出规则。
image/avatar 元素会按 SoM bbox 从整页截图裁真实像素回填（imageBase64），
避免直出稿里所有图片都变成占位灰块。
透明无边框的 overlay 容器（fixed wrapper）同样按 bbox 裁真实像素作“像素底”
（imageBase64 + cropBackdrop），它是该浮层区域的**最终像素**：渲染端在同 z 时
最后画它；被它完全盖住的图元（同框白底、表头条、列内按钮/图标/文本）画出来也
看不见，属冗余图层，这里直接丢弃（见 _shadowed_by_backdrop，计数 _meta.skipped_under_backdrop）。

但浮层**自己内部**就有一块不透明底板时（antd 固定列里的 table.ant-table-fixed 白板），
位图底是纯冗余：列内每个真实图层都能画，位图只会让整列不可编辑。此时跳过位图
（见 _covered_by_own_plate）。同理，`clip` 只对文字必需——形状夹进裁剪矩形即可，
夹完不再输出 clipPath（Figma 端也就不必再套不好改的 Clip 框）。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
from pathlib import Path

from src.app.services.som.design_crops import (
    covers as _covers,
    crop_image_b64 as _crop_image_b64,
    rect_of as _rect_of,
    shadowed_by_pixel_backdrop as _shadowed_by_backdrop,
)
from src.app.services.rendering.layout_plan import build_layout_plan
from src.app.services.structure.site_profiles import load_profile, rule as _rule
from src.app.services.structure.asset_metadata import (
    attach_display_payload,
    build_asset_record,
)
from src.app.services.structure.asset_fusion import fuse_asset_record
from src.app.services.structure.text_model import build_text_model
from src.app.services.structure.visual_assets import build_visual_assets
from src.app.services.structure.svg_materialization import materialize_svg_assets
from src.app.utils.style_utils import css_color_to_hex
from src.config.settings import Config

logger = logging.getLogger(__name__)

_DIRECT_ROUTES = ("dom",)


def _geometry(item: dict) -> tuple[int, int, int, int]:
    """几何一律按原图像素取整——不做 4px 网格吸附。

    DOM 的 getBoundingClientRect 本来就是真值（采集端已 Math.round），再吸到 4px
    网格只会引入误差。历史上“容器/色块吸网格求边沿整齐”的做法在三份真实页采集上
    都是净亏（脚本 output/_ab_snap2.py）：关掉吸附后整图 meanDiff 一致下降
    （1.609→1.375 / 1.972→1.779 / 1.824→1.623），文字笔画 3.747→3.543。
    最刺眼的是大色块整边平移：x=255 的白卡片被吸到 256，597px 长的竖边整条错 1px，
    它的投影也跟着偏（该区域 2.44→0.20）。矢量几何不需要吸附。
    """
    x, y, w, h = item["bbox"]
    return (
        max(0, int(round(float(x)))),
        max(0, int(round(float(y)))),
        max(1, int(round(float(w)))),
        max(1, int(round(float(h)))),
    )


def _visual_asset_manifest(som_json: dict) -> dict:
    rows = []
    for item in som_json.get("elements") or []:
        if not isinstance(item, dict):
            continue
        record = (item.get("assetIdentity") or {}).get("asset_record") or {}
        source = record.get("source_identity") or {}
        if not isinstance(source, dict):
            continue
        url = str(source.get("source_url") or "").strip()
        if not url:
            continue
        rows.append(
            {
                "source_url": url,
                "status": source.get("status"),
                "sha256": source.get("sha256"),
                "locator": source.get("locator"),
                "mime": source.get("mime"),
            }
        )
    return {"assets": rows}


def _pseudo_visual_style(asset: dict) -> dict:
    source = asset.get("style") or {}
    style: dict = {}
    text_color = css_color_to_hex(source.get("color"))
    if text_color:
        style["textColor"] = text_color
    matcher = re.search(r"(\d+(?:\.\d+)?)px", str(source.get("font") or ""))
    style["fontSize"] = int(round(float(matcher.group(1)))) if matcher else 16
    style["fontWeight"] = "700" if re.search(r"\b(?:700|bold)\b", str(source.get("font") or ""), re.I) else "400"
    return style


def _carry_clip(out: dict, item: dict) -> None:
    """把 SoM 上的“祖先裁剪矩形”带到 DesignSpec（输出端据此套 clipPath）。

    几何与文本基线仍按原始盒子算：滚出容器的列只能靠裁边处理，提前把盒子裁小
    会把文本的 y/h 一起改掉（基线 = y + h/2 + 0.375em）。没有这个字段的元素
    （含 grounding/cv 与旧抓取产物）输出与以前逐字节一致。
    """
    clip = item.get("clip")
    if not clip:
        return
    try:
        out["clip"] = [int(round(float(v))) for v in clip]
    except (TypeError, ValueError):
        pass


def _apply_clipped_text_lines(
    style: dict,
    *,
    element_type: str,
    x: int,
    y: int,
    width: int,
    height: int,
    clip: list[int] | None,
) -> None:
    """Limit overflowing text to the part that survives an ancestor clip.

    The text's own DOM box may be much taller than the visible scroll/clip box. Keeping
    all measured lines would make SVG/Figma paint the overflow into neighbouring cards.
    We only derive a line cap here; both renderers still use the shared text_wrap path.
    """
    if element_type != "text" or not clip or len(clip) != 4:
        return
    try:
        clip_x, clip_y, clip_w, clip_h = (int(value) for value in clip)
        line_height = float(style.get("lineHeight") or 0)
        if line_height <= 0:
            line_height = max(1.0, float(style.get("fontSize") or 16) * 1.4)
        visible_top = max(y, clip_y)
        visible_bottom = min(y + height, clip_y + clip_h)
        visible_height = visible_bottom - visible_top
        if visible_height <= 0 or visible_height >= height - 1:
            return
        if x + width <= clip_x or x >= clip_x + clip_w:
            return
        max_lines = max(1, int((visible_height + 0.5) // line_height))
        existing = int(style.get("maxLines") or 0)
        if existing > 0:
            max_lines = min(max_lines, existing)
        style["maxLines"] = max_lines
    except (TypeError, ValueError):
        return


def _apply_measured_text_geometry(
    item: dict,
    x: int,
    y: int,
    width: int,
    height: int,
    style: dict,
) -> tuple[int, int, int, int]:
    """Use the browser text range for paintless mixed-inline text layers."""
    if item.get("type") != "text":
        return x, y, width, height
    rich_runs = item.get("richRuns")
    if isinstance(rich_runs, list) and len(rich_runs) > 1:
        return x, y, width, height
    if style.get("fillColor") or style.get("borderColor"):
        return x, y, width, height
    box = item.get("textEmBox")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return x, y, width, height
    try:
        bx, by, bw, bh = (int(round(float(value))) for value in box)
        measured_lines = int(item.get("textEmLines") or 0)
    except (TypeError, ValueError):
        return x, y, width, height
    if bw <= 0 or bh <= 0 or measured_lines > 2:
        return x, y, width, height
    # A wrapper can cover the whole row while its actual text starts after inline
    # icons. Only adopt the range when that visible offset exists.
    if bx <= x + 1 and by <= y + 1:
        return x, y, width, height
    return bx, by, bw, bh


def _normalize_single_line_text(item: dict) -> str:
    """Collapse source indentation when the browser measured one visual line."""
    text = str(item.get("text") or "")
    if not text or item.get("richRuns"):
        return text
    try:
        measured_lines = int(item.get("textEmLines") or 0)
    except (TypeError, ValueError):
        measured_lines = 0
    white_space = str(item.get("whiteSpace") or "").strip().lower()
    if measured_lines != 1 or white_space in {
        "pre",
        "pre-wrap",
        "pre-line",
        "break-spaces",
    }:
        return text
    return re.sub(r"[ \t\r\n\f\v]+", " ", text).strip()


def _carry_flag(out: dict, item: dict, key: str) -> None:
    """把 SoM 上的布尔标记带到 DesignSpec（没有就不写，老产物逐字节不变）。"""
    if item.get(key):
        out[key] = True


def _carry_box(out: dict, item: dict, key: str) -> None:
    """把 SoM 上的“文本行框”（[x, y, w, h]）带到 DesignSpec（没有就不写）。"""
    box = item.get(key)
    if not box:
        return
    try:
        out[key] = [int(round(float(v))) for v in box]
    except (TypeError, ValueError):
        pass


def _carry_int(out: dict, item: dict, key: str) -> None:
    """把 SoM 上的整数标量带到 DesignSpec（没有 / 不是整数就不写）。"""
    value = item.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        out[key] = int(value)


def _carry_text_lines(out: dict, item: dict) -> None:
    """Carry browser-measured line breaks into the output contract."""
    lines = [
        str(line.get("text") or "").strip()
        for line in (item.get("textLines") or [])
        if isinstance(line, dict) and str(line.get("text") or "").strip()
    ]
    if lines:
        out["lines"] = lines


def _carry_asset_metadata(out: dict, item: dict) -> None:
    if isinstance(item.get("assetIdentity"), dict):
        out["assetIdentity"] = dict(item["assetIdentity"])
    if isinstance(item.get("sourceCrop"), dict):
        out["sourceCrop"] = dict(item["sourceCrop"])
    if isinstance(item.get("displayPayload"), dict):
        out["displayPayload"] = dict(item["displayPayload"])
    if isinstance(item.get("replacement"), dict):
        out["replacement"] = dict(item["replacement"])


def _carry_name(out: dict, item: dict) -> None:
    """把 SoM 上的图层可读名带到 DesignSpec（没有就不写，老产物逐字节不变）。"""
    if item.get("name"):
        out["name"] = item["name"]


def _carry_dom_index(out: dict, item: dict) -> None:
    """把「这段来自采集数组里的第几个节点」带到 DesignSpec。

    只在有这个字段时写（grounding/cv 与老产物逐字节不变）。Auto Layout 施工图
    靠它把元素归回 DOM 父子关系（见 rendering/layout_plan）；没有它这条链路整体
    不动，输出与以前完全一致。
    """
    if isinstance(item.get("domIndex"), int):
        out["domIndex"] = int(item["domIndex"])


def _carry_shape_extras(style: dict, out_style: dict) -> None:
    """可选渲染字段（圆角四角 / 字距 / 透明度）的透传。

    都是"有才写"的可选字段：没有这些字段的老产物输出逐字节不变。
    borderRadius 始终是标量（保持给旧消费端/LLM schema 的形状），非均匀时才多加
    borderRadiusCorners=[tl,tr,br,bl]，由 Figma/SVG 两端优先采用。
    """
    if style.get("borderRadius"):
        out_style["borderRadius"] = int(style["borderRadius"])
    corners = style.get("borderRadiusCorners")
    if isinstance(corners, (list, tuple)) and len(corners) == 4:
        out_style["borderRadiusCorners"] = [int(c) for c in corners]
    if style.get("letterSpacing"):
        out_style["letterSpacing"] = float(style["letterSpacing"])
    if style.get("opacity"):
        out_style["opacity"] = float(style["opacity"])


def _border_fields(style: dict) -> dict:
    """从 style 取边框字段；borderColor/borderWidth 成对存在才返回。"""
    if style.get("borderColor") and style.get("borderWidth"):
        fields = {
            "borderColor": str(style["borderColor"]),
            "borderWidth": int(style["borderWidth"]),
        }
        if style.get("borderStyle"):
            fields["borderStyle"] = str(style["borderStyle"])
        return fields
    return {}


def _rect_area(el: dict) -> int:
    r = _rect_of(el)
    return (r[2] * r[3]) if r else 0


def _merge_backdrop_clones(backdrops: list[dict]) -> list[dict]:
    """合并同框克隆像素底：被别的像素底完全盖住的那块不再出图。

    浮层固定列常有 2–4 层 wrapper 带同一个（或差 1px 的）盒子，各裁一遍就会在
    SVG 里把同一块区域画好几遍。按面积从大到小保留：大盒子的裁图天然包含小盒子
    的像素，盖住即等价（两个盒子都是同一张截图的像素）。
    """
    kept: list[dict] = []
    for b in sorted(backdrops, key=lambda el: -_rect_area(el)):
        br = _rect_of(b)
        if br is None or any(_covers(_rect_of(k), br) for k in kept):
            continue
        kept.append(b)
    return kept


def _bbox_rect(item: dict) -> tuple[int, int, int, int] | None:
    """SoM 条目的轴对齐矩形（采集端已是整像素，与 _geometry 同口径）。"""
    try:
        b = item["bbox"]
        return (
            max(0, int(round(float(b[0])))),
            max(0, int(round(float(b[1])))),
            max(1, int(round(float(b[2])))),
            max(1, int(round(float(b[3])))),
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _intersect_rect(a, b) -> tuple[int, int, int, int] | None:
    """两矩形交集；不相交或退化成零面积返回 None。"""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def _opaque_plates(som_json: dict) -> list[tuple[int, int, int, int]]:
    """所有“不透明底板”矩形：有实心 fill 的容器（浮层自己的白板等）。"""
    plates = []
    for c in som_json.get("containers") or []:
        fill = (c.get("style") or {}).get("fillColor")
        if not fill or str(fill).strip().lower() in ("transparent", "none"):
            continue
        r = _bbox_rect(c)
        if r:
            plates.append(r)
    return plates


def _clamp_clip(el: dict) -> tuple[bool, bool]:
    """把形状类元素夹进 clip 矩形并去掉 clip 字段，返回 (是否保留, 是否夹过)。

    夹完什么都不剩（完全在裁剪区外）返回 (False, False)。

    形状（容器/分隔线/图片）少画一段 = 被裁掉，像素完全等价，夹完就不需要
    clipPath（Figma 端也就不必再套 Clip 框）。文字不能这么办：字形长度 ≠ 盒子，
    把盒子裁小也挡不住溢出的字，仍要保留 clipPath（见元素循环）。
    """
    clip = el.get("clip")
    if not clip:
        return True, False
    r = _rect_of(el)
    vis = _intersect_rect(r, tuple(clip)) if r is not None else None
    el.pop("clip", None)
    if vis is None:
        return False, False
    el.update(x=vis[0], y=vis[1], width=vis[2], height=vis[3])
    return True, True


def _dom_ancestor_clip(
    element: dict, dom_nodes
) -> tuple[list[int] | None, bool]:
    """Resolve overflow clipping from DOM ancestry when capture metadata is missing."""
    if not isinstance(dom_nodes, list):
        return None, False
    dom_index = element.get("domIndex")
    if not isinstance(dom_index, int) or not 0 <= dom_index < len(dom_nodes):
        return None, False
    clip = element.get("clip")
    current = (
        tuple(int(value) for value in clip)
        if isinstance(clip, (list, tuple)) and len(clip) == 4
        else None
    )
    parent = dom_nodes[dom_index].get("pIdx")
    seen: set[int] = set()
    while isinstance(parent, int) and 0 <= parent < len(dom_nodes):
        if parent in seen:
            break
        seen.add(parent)
        ancestor = dom_nodes[parent]
        if ancestor.get("clipToBounds"):
            try:
                box = (
                    int(ancestor.get("x") or 0),
                    int(ancestor.get("y") or 0),
                    int(ancestor.get("w") or 0),
                    int(ancestor.get("h") or 0),
                )
            except (TypeError, ValueError):
                box = (0, 0, 0, 0)
            if box[2] > 0 and box[3] > 0:
                current = (
                    _intersect_rect(current, box) if current is not None else box
                )
                if current is None:
                    return None, True
        parent = ancestor.get("pIdx")
    return (list(current) if current is not None else None), False


def _dom_subtree_has_visible_content(root_index, dom_nodes) -> bool:
    """Whether a captured DOM subtree contains anything visible to recreate.

    Empty fixed-position portal layers (toast/message roots) can span the viewport
    while painting nothing. Rasterizing their box would copy unrelated page pixels
    and cover the real editable layers underneath.
    """
    if not isinstance(dom_nodes, list):
        return True
    if not isinstance(root_index, int) or not 0 <= root_index < len(dom_nodes):
        return True
    children: dict[int, list[int]] = {}
    for index, node in enumerate(dom_nodes):
        parent = node.get("pIdx") if isinstance(node, dict) else None
        if isinstance(parent, int) and 0 <= parent < len(dom_nodes):
            children.setdefault(parent, []).append(index)
    stack = [root_index]
    while stack:
        index = stack.pop()
        node = dom_nodes[index]
        if not isinstance(node, dict):
            continue
        tag = str(node.get("tag") or "").lower()
        if (
            str(node.get("text") or "").strip()
            or node.get("iconBox")
            or node.get("bgImage")
            or node.get("boxShadow")
            or node.get("edges")
            or tag in {"img", "svg", "video", "canvas"}
        ):
            return True
        background = css_color_to_hex(node.get("bg"))
        if background and background.upper() not in {"#FFFFFF", "#FFFFFE"}:
            return True
        try:
            if float(str(node.get("borderWidth") or "0px").replace("px", "")) > 0:
                return True
        except (TypeError, ValueError):
            pass
        stack.extend(children.get(index, []))
    return False


def _covered_by_own_plate(rect, plates) -> bool:
    """rect 是否被某块“同框底板”整块盖住（互相覆盖 = 同一块区域）。

    单方向覆盖不够：整张白卡片也会“盖住”它内部的浮层，但那是背景不是浮层自己的
    底板——把浮层的位图底去掉就会露出底下的内容。
    """
    return any(_covers(p, rect) and _covers(rect, p) for p in plates)


def _covered_by_plate(el: dict, rect, plates: list[tuple]) -> bool:
    """rect 是否被某块浮层底板盖住且底板画在它之后（与像素底同口径）。"""
    for pr, pz in plates:
        if not _covers(pr, rect):
            continue
        if not el.get("overlay"):
            return True  # 普通图元先画，浮层必在其后落笔
        if pz >= int(el.get("zIndex") or 0):
            return True
    return False


def _merge_collinear_dividers(elements: list[dict]) -> tuple[list[dict], int]:
    """把同一层、同色、共线的 1px 分隔线并成一整条，返回 (新列表, 并掉的段数)。

    采集端是**逐节点**采的：antd 表格一行线的真实来源是每个 `td` 的
    `border-bottom: 1px solid #e8e8e8`，所以"一行"在 DOM 里就是 8~10 段各自独立的边框，
    SoM 也照实收 8~10 个 `divider`。采集端的去重（`seen_edges`）只丢**完全同框同色**的，
    首尾相接的相邻段全部留下——真实页一行线被画成 10 条短线，Figma 图层面板里一行就是
    10 个矩形，改一根要改十次（竖分隔线同理，一列 11 段）。

    这些段都落在整数坐标上、1px 粗、颜色不透明，取并集是**逐像素等价**的
    （同一不透明色叠两遍还是那个颜色），所以只做并集，不做任何平滑或吸附。

    难点在**落笔顺序**：`adapter_base.render_design` 对非浮层内容按"被包含深度"排
    （深度 = 有多少个别的图元完整覆盖我，深度大的先画），而深度只由几何算出。一整条
    合并线的覆盖集合和它每个分段都不一样：真实页表头那 60px 截线落在固定列白板
    `table.ant-table-fixed`（61×496）和表头格 `th` 里，深度 5、排在表头灰底之后；并成
    整行宽之后没人再完整覆盖它，深度掉到 3、排到表头灰底之前，整截线被灰底擦掉
    （实测 59 个像素从 232 变 250）。所以合并这一趟把各分段的真实深度取最大值写成
    `paintDepth`，渲染端优先用它——整条线的落笔位置 = 它最深那一段原来的位置。

    跨 `overlay` / `zIndex` 一律不合并（会让某一截的落笔顺序提到别的层里，那就不再是
    像素等价）；带 `clip` 的段不参与（形状还没夹进裁剪矩形）。
    """
    geoms: list[tuple] = []
    seen_geom: set[tuple] = set()
    for el in elements:
        r = _rect_of(el)
        if r is not None and r not in seen_geom:
            seen_geom.add(r)
            geoms.append(r)

    def _paint_depth(rect: tuple) -> int:
        """该矩形在渲染端会拿到的几何深度（与 adapter 的 `_depth` 同口径）。"""
        return sum(1 for g in geoms if g != rect and _covers(g, rect))

    rows: list[tuple] = []  # (下标, 轴, 分组键, 起点, 终点, 深度)
    for i, el in enumerate(elements):
        if el.get("type") != "divider" or el.get("clip"):
            continue
        color = (el.get("style") or {}).get("fillColor")
        if not color:
            continue
        w, h = int(el["width"]), int(el["height"])
        layer = (bool(el.get("overlay")), int(el.get("zIndex") or 0), str(color))
        if h == 1 and w > 1:
            rect = (int(el["x"]), int(el["y"]), w, h)
            rows.append(
                (
                    i,
                    "h",
                    layer + (int(el["y"]),),
                    int(el["x"]),
                    int(el["x"]) + w,
                    _paint_depth(rect),
                )
            )
        elif w == 1 and h > 1:
            rect = (int(el["x"]), int(el["y"]), w, h)
            rows.append(
                (
                    i,
                    "v",
                    layer + (int(el["x"]),),
                    int(el["y"]),
                    int(el["y"]) + h,
                    _paint_depth(rect),
                )
            )
    if not rows:
        return elements, 0

    groups: dict[tuple, list[tuple[int, int, int, int]]] = {}
    for i, axis, key, start, end, depth in rows:
        groups.setdefault((axis, key), []).append((start, end, i, depth))

    replacement: dict[int, dict] = {}
    drop: set[int] = set()
    merged = 0
    for (axis, _key), segs in groups.items():
        segs.sort()
        # 每个 run = [起点, 终点, [段下标...], [各段深度...]]
        runs: list[list] = [[segs[0][0], segs[0][1], [segs[0][2]], [segs[0][3]]]]
        for start, end, i, depth in segs[1:]:
            if start <= runs[-1][1]:  # 首尾相接或重叠都算同一段
                runs[-1][1] = max(runs[-1][1], end)
                runs[-1][2].append(i)
                runs[-1][3].append(depth)
            else:
                runs.append([start, end, [i], [depth]])
        for start, end, idxs, depths in runs:
            if len(idxs) < 2:
                continue
            out = dict(elements[idxs[0]])
            out["paintDepth"] = max(depths)  # 并集后几何推不出原深度，显式带上
            if axis == "h":
                out["x"], out["width"] = start, end - start
            else:
                out["y"], out["height"] = start, end - start
            replacement[idxs[0]] = out
            drop.update(idxs[1:])
            merged += len(idxs) - 1
    if not drop:
        return elements, 0
    got = [replacement.get(i, el) for i, el in enumerate(elements) if i not in drop]
    return got, merged


def _page_background(dom_nodes) -> str:
    """页底色：body 的实心底色 -> html 的实心底色 -> 白。

    采集端把 `document.body` 的 computed 底色同时写成每个节点的 `pageBg`；
    `bg` 是该节点自己的底色。body 透明时按 html 的底色合成，仍拿不到就白。
    这个值只作为画板元数据带给出口（Axure 用它铺背景控件），不进元素列表。
    """
    nodes = dom_nodes or []
    html_hex = "#ffffff"
    for node in nodes:
        if str(node.get("tag") or "").lower() == "html":
            html_hex = css_color_to_hex(node.get("bg")) or html_hex
            break
    for node in nodes:
        if str(node.get("tag") or "").lower() == "body":
            body_hex = css_color_to_hex(node.get("bg"), bg=html_hex)
            if body_hex:
                return body_hex
            break
    return html_hex


def _capture_pixel_ratio(
    size: list[int],
    viewport: dict,
    dom_nodes,
    declared_ratio,
) -> int:
    """Resolve screenshot DPR, including artifacts captured without capture metadata."""
    try:
        ratio = max(1, int(declared_ratio or 1))
    except (TypeError, ValueError):
        ratio = 1
    if ratio > 1:
        return ratio

    try:
        screenshot_width = int(size[0])
    except (IndexError, TypeError, ValueError):
        return ratio
    if screenshot_width <= 0:
        return ratio

    logical_widths: list[int] = []
    if isinstance(dom_nodes, list):
        for node in dom_nodes:
            if (
                not isinstance(node, dict)
                or str(node.get("tag") or "").lower() != "html"
            ):
                continue
            try:
                logical_widths.append(int(float(node.get("w") or 0)))
            except (TypeError, ValueError):
                pass
            break
    try:
        logical_widths.append(int(viewport.get("width") or 0))
    except (AttributeError, TypeError, ValueError):
        pass

    for logical_width in logical_widths:
        if logical_width <= 1 or logical_width >= screenshot_width:
            continue
        candidate = round(screenshot_width / logical_width)
        if candidate > 1 and abs(screenshot_width - logical_width * candidate) <= 1:
            return candidate
    return ratio


def build_direct_design(som_json: dict, profile=None, dom_nodes=None) -> dict:
    """按 SoM（含 style 字段）确定性生成 DesignSpec。

    容器只要“有非透明背景色”或“带真实边框（color+width 成对）”就画出；
    透明且无边框才跳过，避免凭空造框（计数写入 _meta.skipped_transparent_containers）。
    元素按 DOM type/text/computed style 拼装；image/avatar 回填原图裁剪。
    颜色/字号以浏览器计算结果为准，比让 VLM 看图猜测更准、更快。
    几何一律按 SoM bbox 取原图像素（不做 4px 网格吸附，见 _geometry）。
    dom_nodes 是同一页的采集结果（`00_dom.json`）：给了才做 Auto Layout 施工图
    （元素上多出 `layout` / `layoutChildren`）；不给（grounding/cv、老产物、单测）
    输出与以前逐字节相同。
    带可见文本的节点还会
    带上页面 computed 字体栈（fontFamily），输出端按它渲染文本。
    """
    provenance = som_json.get("provenance") or {}
    text_model = None
    text_blocks_by_source: dict[int, dict] = {}
    inline_consumed_indices: set[int] = set()
    if isinstance(dom_nodes, list) and Config().dom_text_model_v2:
        text_model = build_text_model(dom_nodes)
        text_blocks_by_source = {
            int(block["sourceIndex"]): block
            for block in text_model.get("blocks", {}).values()
            if isinstance(block, dict) and isinstance(block.get("sourceIndex"), int)
        }
        inline_consumed_indices = {
            int(index)
            for index in text_model.get("inlineConsumedIndices", [])
            if isinstance(index, int)
        }
    if profile is None:
        # 与采集端取同一个 profile：url 由 precise_agent 注入 provenance（见该文件）。
        profile = load_profile(provenance.get("url"))
    route = provenance.get("route") or "dom"
    size = som_json.get("size") or [0, 0]
    capture = provenance.get("capture") or {}
    viewport = capture.get("viewport") or {}
    pixel_ratio = _capture_pixel_ratio(
        size,
        viewport,
        dom_nodes,
        capture.get("device_scale_factor"),
    )
    canvas_size = capture.get("canvas_size")
    if isinstance(canvas_size, (list, tuple)) and len(canvas_size) >= 2:
        logical_width = max(1, int(canvas_size[0]) // pixel_ratio)
        logical_height = max(1, int(canvas_size[1]) // pixel_ratio)
    else:
        screenshot_width = int(size[0]) // pixel_ratio
        screenshot_height = int(size[1]) // pixel_ratio
        logical_width = screenshot_width or int(viewport.get("width") or 1)
        logical_height = screenshot_height or int(viewport.get("height") or 1)
    canvas = {
        "width": logical_width,
        "height": logical_height,
        "background": _page_background(dom_nodes),
    }
    image_path = som_json.get("image")
    screenshot_sha256 = None
    if image_path:
        try:
            digest = hashlib.sha256()
            with open(image_path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            screenshot_sha256 = digest.hexdigest()
        except OSError:
            screenshot_sha256 = None
    elements: list[dict] = []
    backdrops: list[dict] = []  # 浮层像素底，渲染端在同 z 时最后画（见文末）
    visual_assets = None
    if (
        isinstance(dom_nodes, list)
        and os.getenv("DOM_VISUAL_ASSETS_V2", "false").strip().lower()
        in {"1", "true", "yes"}
    ):
        visual_assets = build_visual_assets(
            dom_nodes,
            _visual_asset_manifest(som_json),
        )
    svg_assets_by_dom: dict[int, dict] = {}
    if (
        isinstance(dom_nodes, list)
        and image_path
        and os.getenv("DOM_SVG_MATERIALIZATION_V2", "false").strip().lower()
        in {"1", "true", "yes"}
    ):
        svg_manifest = materialize_svg_assets(
            dom_nodes,
            Path(image_path).parent / "svg_materialization",
            page_url=str(provenance.get("url") or ""),
        )
        svg_assets_by_dom = {
            int(row["domIndex"]): row
            for row in svg_manifest.get("assets", [])
            if isinstance(row, dict) and isinstance(row.get("domIndex"), int)
        }
    skipped_containers = 0  # 透明且无边框（凭空造不出框）的容器
    drawn_containers = 0  # 真有 fill/border 的容器（像素底另外计）

    plates = _opaque_plates(som_json)
    emitted_plates: list[tuple] = []  # 已下发的“浮层实心底板”(rect, zIndex)
    skipped_occluded = 0  # 被底板完全盖住、画了也看不见的图元
    clamped_clip = 0  # 夹进裁剪矩形后不再需要 clipPath 的图元
    for c in som_json.get("containers", []):
        style = c.get("style") or {}
        fill = style.get("fillColor")
        border = _border_fields(style)
        is_overlay = bool(c.get("overlay", False))
        if not fill and not border:
            if (
                is_overlay
                and image_path
                and _dom_subtree_has_visible_content(c.get("domIndex"), dom_nodes)
                and not _covered_by_own_plate(_geometry(c), plates)
            ):
                # 透明浮层容器（antd fixed wrapper 等）没有自身底色，裁原截图对应
                # 区域真实像素作底，浮层排在普通内容之上时能把底下内容正确盖住。
                # 这块“像素底”是该区域的最终像素：渲染端在同 z 时最后画它
                # （见 adapter_base.render_design），被它盖住的列内图层都是冗余
                # （见文末过滤）。几何按原图像素取整（见 _geometry）。
                bx, by, bw, bh = _geometry(c)
                b64 = _crop_image_b64(
                    image_path,
                    bx,
                    by,
                    bw,
                    bh,
                    canvas["width"],
                    canvas["height"],
                    pixel_ratio=pixel_ratio,
                )
                if b64:
                    # cropBackdrop 标记“这块是该区域的最终像素”，渲染端据此把
                    # 它排在同 z 的其它 overlay 之后落笔；文末过滤据此丢冗余图层。
                    backdrop_el = {
                        "id": c["id"],
                        "type": "container",
                        "x": bx,
                        "y": by,
                        "width": bw,
                        "height": bh,
                        "text": "",
                        "overlay": True,
                        "zIndex": int(c.get("zIndex") or 0),
                        "imageBase64": b64,
                        "cropBackdrop": True,
                        **({"name": c["name"]} if c.get("name") else {}),
                        "style": (
                            {"shadows": style["shadows"]}
                            if style.get("shadows")
                            else {}
                        ),
                    }

                    _carry_dom_index(backdrop_el, c)
                    backdrops.append(backdrop_el)
                    continue
            if style.get("shadows"):
                # 透明无边框但有投影的容器（antd 固定列滚动阴影层等）：投影本身就是
                # 要画的东西，不能因为“没有底色”整块丢掉。
                cx, cy, cw, ch = _geometry(c)
                shadow_el = {
                    "id": c["id"],
                    "type": "container",
                    "x": cx,
                    "y": cy,
                    "width": cw,
                    "height": ch,
                    "text": "",
                    "overlay": is_overlay,
                    "zIndex": int(c.get("zIndex") or 0),
                    **({"name": c["name"]} if c.get("name") else {}),
                    "style": {"fillColor": "transparent", "shadows": style["shadows"]},
                }
                _carry_dom_index(shadow_el, c)
                elements.append(shadow_el)
                drawn_containers += 1
                continue
            skipped_containers += 1
            continue
        x, y, w, h = _geometry(c)
        out_style: dict = {}
        if fill:
            out_style["fillColor"] = fill
        else:
            # 透明底 + 真实边框（白卡片/描边输入组等）：SVG 默认灰底会盖住整块，
            # 显式 transparent 保留原透明背景、只画描边。
            out_style["fillColor"] = "transparent"
        out_style.update(border)
        _carry_shape_extras(style, out_style)
        if style.get("shadows"):
            out_style["shadows"] = style["shadows"]
        drawn_containers += 1
        container_el = {
            "id": c["id"],
            "type": "container",
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "text": "",
            "overlay": is_overlay,
            "zIndex": int(c.get("zIndex") or 0),
            "style": out_style,
        }
        _carry_clip(container_el, c)
        for key in (
            "clipToBounds",
            "overflowX",
            "overflowY",
            "clientWidth",
            "clientHeight",
            "scrollWidth",
            "scrollHeight",
        ):
            if c.get(key) not in (None, "", 0, False):
                container_el[key] = c[key]
        _carry_name(container_el, c)
        _carry_dom_index(container_el, c)
        kept_el, was_clamped = _clamp_clip(container_el)
        if not kept_el:
            drawn_containers -= 1
            skipped_occluded += 1
            continue
        clamped_clip += 1 if was_clamped else 0
        elements.append(container_el)
        if is_overlay and out_style.get("fillColor") not in (None, "", "transparent"):
            emitted_plates.append((_rect_of(container_el), int(c.get("zIndex") or 0)))

    image_backfilled = 0
    for e in som_json.get("elements", []):
        style = e.get("style") or {}
        etype = e.get("type") or "rectangle"
        dom_index = e.get("domIndex")
        if (
            text_model is not None
            and etype == "text"
            and isinstance(dom_index, int)
            and dom_index in inline_consumed_indices
        ):
            continue
        text_block = (
            text_blocks_by_source.get(dom_index)
            if text_model is not None and etype == "text" and isinstance(dom_index, int)
            else None
        )
        if text_block is not None:
            e = dict(e)
            e["text"] = str(text_block.get("text") or e.get("text") or "")
            measured_lines = text_block.get("measuredLines")
            if isinstance(measured_lines, list) and measured_lines:
                e["textLines"] = measured_lines
        x, y, w, h = _geometry(e)
        out_style: dict = {}
        fill = style.get("fillColor")
        border = _border_fields(style)
        if fill:
            out_style["fillColor"] = fill
        elif etype in ("button", "input"):
            # 控件自己**没有** computed 底色就是"透明"，不能补白：像素就是它背后
            # 那一层。补白会在深色顶栏/彩色块上凭空多出一块白盒子（antd 顶栏图标
            # 按钮、python.org 头栏链接），渲染端还得再写规则把它抠掉——那条规则
            # 又会连带吃掉真正的白（见 rendering/adapter_base._white_leaf_backing）。
            # 显式写 transparent 是必须的：SVG 出口对缺失的 fill 会退回灰 #cccccc。
            out_style["fillColor"] = "transparent"
        out_style.update(border)
        if style.get("textColor"):
            out_style["textColor"] = style["textColor"]
        elif etype == "text":
            out_style["textColor"] = "#000000"
        if style.get("fontSize"):
            out_style["fontSize"] = int(style["fontSize"])
        if style.get("fontWeight"):
            out_style["fontWeight"] = style["fontWeight"]
        if style.get("fontFamily"):
            out_style["fontFamily"] = style["fontFamily"]
        for key in (
            "lineHeight",
            "textAlign",
            "whiteSpace",
            "maxLines",
            "fontStyle",
            "fontWeightValue",
            "fontFamilyRequested",
            "fontFamilyResolution",
        ):
            if style.get(key):
                out_style[key] = style[key]
        if style.get("platformFonts"):
            out_style["platformFonts"] = [
                dict(item) for item in style["platformFonts"] if isinstance(item, dict)
            ]
        _carry_shape_extras(style, out_style)
        if style.get("shadows"):
            out_style["shadows"] = style["shadows"]
        x, y, w, h = _apply_measured_text_geometry(
            {**e, "type": etype}, x, y, w, h, out_style
        )
        is_overlay = bool(e.get("overlay", False))
        element = {
            "id": str(e["id"]),
            "type": etype,
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "text": _normalize_single_line_text(e),
            "overlay": is_overlay,
            "zIndex": int(e.get("zIndex") or 0),
            "style": out_style,
        }
        _carry_clip(element, e)
        _apply_clipped_text_lines(
            out_style,
            element_type=etype,
            x=x,
            y=y,
            width=w,
            height=h,
            clip=element.get("clip"),
        )
        _carry_name(element, e)
        _carry_dom_index(element, e)
        _carry_flag(element, e, "textLineBox")
        _carry_box(element, e, "textBox")
        # Axure 出口的落字对齐输入（见 rendering/axure_adapter）：第一行行框 + 行数
        _carry_box(element, e, "textEmBox")
        _carry_int(element, e, "textEmLines")
        baseline = e.get("textBaseline")
        dom_index = e.get("domIndex")
        if (
            not isinstance(baseline, dict)
            and isinstance(dom_nodes, list)
            and isinstance(dom_index, int)
            and 0 <= dom_index < len(dom_nodes)
            and isinstance(dom_nodes[dom_index], dict)
        ):
            baseline = dom_nodes[dom_index].get("textBaseline")
        if isinstance(baseline, dict):
            element["textBaseline"] = dict(baseline)
        _carry_text_lines(element, e)
        rich_runs = e.get("richRuns")
        if isinstance(rich_runs, list) and rich_runs:
            element["richRuns"] = [
                {
                    "start": int(run.get("start") or 0),
                    "end": int(run.get("end") or 0),
                    "text": str(run.get("text") or ""),
                    "style": dict(run.get("style") or {}),
                }
                for run in rich_runs
                if isinstance(run, dict)
            ]
        if text_block is not None:
            element["text"] = str(text_block.get("text") or element["text"])
            element["textModelId"] = str(text_block["id"])
            element["paragraphRole"] = str(text_block.get("role") or "paragraph")
            element["textRuns"] = [
                dict(run)
                for run in text_block.get("runs", [])
                if isinstance(run, dict)
            ]
            element["measuredLines"] = [
                dict(line)
                for line in text_block.get("measuredLines", [])
                if isinstance(line, dict)
            ]
        for key in (
            "clipToBounds",
            "overflowX",
            "overflowY",
            "textOverflow",
            "clientWidth",
            "clientHeight",
            "scrollWidth",
            "scrollHeight",
        ):
            if e.get(key) not in (None, "", 0, False):
                element[key] = e[key]
        _carry_asset_metadata(element, e)
        # 裁剪：文字必须靠 clipPath（字形长度 ≠ 盒子），先看裁剪后的可见部分是不是
        # 整块被后画的浮层底板盖住——盖住就整个丢掉；形状则直接把盒子夹进裁剪矩形，
        # 像素等价，夹完不再输出 clipPath（Figma 端也就不必再套 Clip 框）。
        clip = element.get("clip")
        if clip:
            if etype == "text":
                vis = _intersect_rect((x, y, w, h), tuple(clip))
                if vis and _covered_by_plate(element, vis, emitted_plates):
                    skipped_occluded += 1
                    continue
            else:
                kept_el, was_clamped = _clamp_clip(element)
                if not kept_el:
                    skipped_occluded += 1
                    continue
                x, y, w, h = (
                    element["x"],
                    element["y"],
                    element["width"],
                    element["height"],
                )
                clamped_clip += 1 if was_clamped else 0
        # 图标字形叶子（iconCrop）与 image/avatar 同一条回填链：DOM 只有盒子和字形码位，
        # 真实像素只能从原截图裁（antd 图标字体在顶层栏/侧栏/分页上大量使用）。
        if etype in ("image", "avatar") or e.get("iconCrop"):
            b64 = None
            svg_asset = svg_assets_by_dom.get(
                int(e["domIndex"]) if isinstance(e.get("domIndex"), int) else -1
            )
            if svg_asset and svg_asset.get("displayPayloadPath"):
                payload_path = (
                    Path(image_path).parent
                    / "svg_materialization"
                    / str(svg_asset["displayPayloadPath"])
                )
                if payload_path.is_file():
                    b64 = base64.b64encode(payload_path.read_bytes()).decode("ascii")
            if b64 is None and image_path:
                b64 = _crop_image_b64(
                    image_path,
                    x,
                    y,
                    w,
                    h,
                    canvas["width"],
                    canvas["height"],
                    pixel_ratio=pixel_ratio,
                )
                if b64:
                    element["imageBase64"] = b64
                    asset_identity = element.get("assetIdentity") or {}
                    record = asset_identity.get("asset_record")
                    if isinstance(record, dict):
                        try:
                            payload_sha256 = hashlib.sha256(
                                base64.b64decode(b64)
                            ).hexdigest()
                        except (ValueError, TypeError):
                            payload_sha256 = None
                        enriched = attach_display_payload(
                            record,
                            payload_sha256=payload_sha256,
                            screenshot_sha256=screenshot_sha256,
                            display_box=(x, y, w, h),
                        )
                        asset_identity["asset_record"] = enriched
                        element["assetIdentity"] = asset_identity
                        element["displayPayload"] = dict(enriched["display_payload"])
                        element["replacement"] = dict(enriched["replacement"])
                    image_backfilled += 1
            if svg_asset:
                for key in (
                    "mode",
                    "originalVectorPath",
                    "sanitizedVectorPath",
                    "displayPayloadPath",
                    "displayMode",
                    "visualFallbackReason",
                ):
                    if svg_asset.get(key):
                        element[key] = svg_asset[key]
            asset_identity = element.get("assetIdentity") or {}
            record = asset_identity.get("asset_record")
            if not isinstance(record, dict):
                record = build_asset_record(
                    sample_id="dom",
                    node_index=int(e.get("domIndex") or len(elements)),
                    source_kind=("icon-crop" if e.get("iconCrop") else "image"),
                    source=None,
                    natural_size=(w, h),
                    display_box=(x, y, w, h),
                )
                if b64:
                    try:
                        payload_sha256 = hashlib.sha256(
                            base64.b64decode(b64)
                        ).hexdigest()
                    except (ValueError, TypeError):
                        payload_sha256 = None
                    record = attach_display_payload(
                        record,
                        payload_sha256=payload_sha256,
                        screenshot_sha256=screenshot_sha256,
                        display_box=(x, y, w, h),
                    )
                asset_identity["asset_record"] = record
                element["assetIdentity"] = asset_identity
                element["displayPayload"] = dict(record["display_payload"])
                element["replacement"] = dict(record["replacement"])
            if isinstance(record, dict):
                generated_candidates = e.get("generatedAssetCandidates")
                if not isinstance(generated_candidates, list):
                    generated_candidates = []
                element["sourceResolution"] = fuse_asset_record(
                    record,
                    generated_candidates=generated_candidates,
                )
        elements.append(element)

    if visual_assets is not None:
        for asset_index, asset in enumerate(visual_assets.get("assets") or []):
            dom_index = asset.get("domIndex")
            if not isinstance(dom_index, int) or not 0 <= dom_index < len(dom_nodes):
                continue
            source_node = dom_nodes[dom_index]
            if (
                asset.get("kind") == "background-image"
                and not str(source_node.get("text") or "")
                and not source_node.get("richRuns")
                and source_node.get("bgImage")
            ):
                # The existing DOM image path already materialized this leaf.
                continue
            bbox = asset.get("bbox") or []
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            x, y, w, h = _geometry({"bbox": list(bbox)})
            common = {
                "id": str(asset.get("visualAssetId") or f"visual-{asset_index}"),
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "overlay": str((asset.get("style") or {}).get("position") or "") == "absolute",
                "zIndex": int(source_node.get("zIndex") or 0),
                "source": asset.get("sourceKind") or "dom:visual",
                "visualAssetId": str(asset.get("visualAssetId") or ""),
                "domIndex": dom_index,
            }
            if asset.get("visualFallbackReason"):
                common["visualFallbackReason"] = asset["visualFallbackReason"]
            if asset.get("kind") == "text":
                element = {
                    **common,
                    "type": "text",
                    "text": str(asset.get("text") or ""),
                    "style": _pseudo_visual_style(asset),
                    **(
                        {"pseudoElement": asset["pseudo"]}
                        if asset.get("pseudo")
                        else {}
                    ),
                    **(
                        {"geometrySource": asset["geometrySource"]}
                        if asset.get("geometrySource")
                        else {}
                    ),
                }
                elements.append(element)
                continue
            if asset.get("kind") == "gradient":
                gradient = asset.get("gradient") or {}
                stops = gradient.get("stops") or []
                element = {
                    **common,
                    "type": "container",
                    "text": "",
                    "style": {"fillColor": stops[0] if stops else "transparent"},
                    "gradient": dict(gradient),
                }
                elements.append(element)
                continue
            b64 = None
            if image_path:
                b64 = _crop_image_b64(
                    image_path,
                    x,
                    y,
                    w,
                    h,
                    canvas["width"],
                    canvas["height"],
                    pixel_ratio=pixel_ratio,
                )
            element = {
                **common,
                "type": "image" if b64 else "rectangle",
                "text": "",
                "style": {"fillColor": "transparent"},
            }
            if b64:
                element["imageBase64"] = b64
                element["displaySourceCrop"] = True
            elements.append(element)

    if dom_nodes:
        kept_by_dom_clip: list[dict] = []
        for element in elements:
            clip, fully_clipped = _dom_ancestor_clip(element, dom_nodes)
            if fully_clipped:
                continue
            if clip is not None:
                rect = _rect_of(element)
                visible = _intersect_rect(rect, tuple(clip)) if rect else None
                if visible is None:
                    continue
            kept_by_dom_clip.append(element)
        elements = kept_by_dom_clip

    # 冗余图层过滤：被浮层像素底完全盖住的图元（同框白底容器、表头条、列内
    # 按钮/图标/文本）画出来也看不见，留着只会让“改绘制序”重新踩坑——历史上
    # 像素底被同框白底盖住，白底又把底图上的“编辑/删除”文字擦掉。统一丢弃，
    # 像素底最后追加进 elements（既是可读性，也让同 key 时它排在最后）。
    cloned_backdrops = len(backdrops)
    backdrops = _merge_backdrop_clones(backdrops)
    merged_clones = cloned_backdrops - len(backdrops)
    kept: list[dict] = []
    skipped_under_backdrop = 0
    for el in elements:
        if _shadowed_by_backdrop(el, backdrops):
            skipped_under_backdrop += 1
            continue
        kept.append(el)
    elements = kept + backdrops
    if _rule(profile, "direct_design", "merge_dividers"):
        elements, merged_dividers = _merge_collinear_dividers(elements)
    else:
        merged_dividers = 0

    # Auto Layout 施工图：有 DOM 树时按父子关系挑出「可以整体当 Frame」的
    # 容器，写回元素上的 `layout` / `layoutChildren`；输出端还要按绘制序与
    # 实测几何复核一遍才真建 Frame（见 adapter_base.resolve_frames）。
    autolayout_frames = build_layout_plan(elements, dom_nodes) if dom_nodes else 0
    overlay_count = sum(1 for el in elements if el.get("overlay"))
    drawn_containers += len(backdrops)

    containers = som_json.get("containers") or []
    som_elements = som_json.get("elements") or []
    expected = len(containers) + len(som_elements)
    meta = {
        "mode": f"{route}-direct",
        "source": f"{route} computed style, no VLM",
        "calls": 0,
        "rounds": 0,
        "expected": expected,
        "returned": len(elements),
        "coverage": 1.0,
        "containers": drawn_containers,
        "pixelRatio": pixel_ratio,
        "elements": len(elements) - drawn_containers,
        "overlays": overlay_count,
        "backdrops": len(backdrops),
        "image_backfilled": image_backfilled,
        "skipped_transparent_containers": skipped_containers,
        "merged_backdrop_clones": merged_clones,
        "skipped_under_backdrop": skipped_under_backdrop,
        "clamped_to_clip": clamped_clip,
        "skipped_occluded": skipped_occluded,
        "merged_dividers": merged_dividers,
        "autolayout_frames": autolayout_frames,
    }
    return {"canvas": canvas, "elements": elements, "_meta": meta}


def try_build_direct_design(
    som_json: dict, profile=None, dom_nodes=None
) -> dict | None:
    """dom 路线且有足够 computed style 时直出 DesignSpec，否则返回 None。

    返回 None 的两个场景由上层区别处理：非 dom 路线交给 VLM 语义生成；
    dom 路线则直接调用 build_direct_design 兜底直出（不回落 VLM）。
    是否直出只看「路线 + 样式覆盖」，不受配置开关控制（旧 --fast / DOM_DIRECT_DESIGN
    两轮之后已无实际作用，P5 一并移除）。
    """
    provenance = som_json.get("provenance") or {}
    if provenance.get("route") not in _DIRECT_ROUTES:
        return None
    items = list(som_json.get("containers") or []) + list(
        som_json.get("elements") or []
    )
    styled = [it for it in items if it.get("style")]
    if profile is None:
        profile = load_profile(provenance.get("url"))
    if not items or len(styled) < len(items) * _rule(
        profile, "direct_design", "min_style_coverage"
    ):
        return None
    return build_direct_design(som_json, profile, dom_nodes)
