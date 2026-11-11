"""SVG 兜底适配器：把 DesignSpec 渲染成 .svg 文件，用于快速验证。"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from src.app.services.rendering.adapter_base import PrototypeAdapter, text_baseline_y

logger = logging.getLogger(__name__)

# 输出端兜底字体栈：computed 字体栈缺失时（VLM 路线、旧抓取数据）用它，
# 让 CJK 落到系统字体、拉丁字母落到 Segoe UI，而不是浏览器默认的 sans-serif
# （默认 sans-serif 在本机解析成 Microsoft YaHei，拉丁字形与原页面不一致）。
# 站点/框架特定的字体栈由 DesignSpec 的 fontFamily（DOM computed 值）逐条覆盖。
DEFAULT_FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", '
    '"Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Helvetica, '
    "Arial, sans-serif"
)


def _font_weight(spec: dict[str, Any]) -> str | None:
    """CSS ``font-weight`` for a text spec, or ``None`` to leave it unset.

    ``style.fontWeight`` upstream is numeric (``_normalize_font_weight`` returns
    400/500/700), but this adapter used to read only ``fontWeightValue`` or the
    literal string ``"bold"``.  A numeric weight therefore fell through to the
    default, and the mock drew Regular where Figma draws Bold -- 10 text owners
    on dark-card-grid.  It is latent rather than active: ``ink-convergence``
    measures the Figma export, not this render, so fixing it changes no pixel
    (verified: 0 px between the two runs).  It stays fixed because a preview
    that disagrees with the deliverable is a trap for the next reader.
    """
    value = spec.get("fontWeightValue")
    if value is None:
        value = spec.get("fontWeight")
    if isinstance(value, (int, float)):
        return str(int(value))
    text = str(value or "").strip().lower()
    if text in {"bold", "bolder", "normal", "lighter"}:
        return text
    return None


class SVGMockAdapter(PrototypeAdapter):
    """SVG 兜底适配器。"""

    supports_vectors = True

    def __init__(self, output_path: str | Path, font_stack: str | None = None):
        self.output_path = Path(output_path)
        self.font_stack = font_stack or DEFAULT_FONT_STACK
        self.elements: list[ET.Element] = []
        self.defs: list[ET.Element] = []
        self._blur_filters: dict[float, str] = {}
        self._clip_paths: dict[tuple[int, int, int, int], str] = {}
        self.canvas_width = 800
        self.canvas_height = 600
        self.canvas_background: str | None = None

    def connect(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def disconnect(self) -> None:
        pass

    def create_frame(self, spec: dict[str, Any]) -> str | None:
        self.canvas_width = int(spec.get("width", 800))
        self.canvas_height = int(spec.get("height", 600))
        background = str(spec.get("backgroundColor") or "").strip()
        self.canvas_background = (
            background
            if background.lower() not in {"", "#fff", "#ffffff", "transparent"}
            else None
        )
        return None

    def _get_color(
        self, spec: dict[str, Any], key: str, default: str = "#000000"
    ) -> str:
        return spec.get(key, default)

    @staticmethod
    def _mix_hex(color: str, white_weight: float) -> str:
        """Mix a hex color toward white for CSS bevel border edges."""
        raw = str(color or "#000000").strip().lstrip("#")
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        if len(raw) != 6:
            raw = "000000"
        try:
            channels = [int(raw[i : i + 2], 16) for i in (0, 2, 4)]
        except ValueError:
            channels = [0, 0, 0]
        value = max(0.0, min(1.0, float(white_weight)))
        mixed = [round(ch * (1.0 - value) + 255 * value) for ch in channels]
        return "#" + "".join(f"{ch:02x}" for ch in mixed)

    @staticmethod
    def _bevel_colors(color: str, style: str) -> tuple[str, str]:
        """Return (top-left, bottom-right) colors for a 2D CSS bevel."""
        # Chromium's black 2px inset bevel rasterizes to #9a9a9a / #eeeeee
        # over white.  These weights keep the same 3D border ramp for other
        # border colors while matching those canonical edge samples.
        dark = SVGMockAdapter._mix_hex(color, 154 / 255)
        light = SVGMockAdapter._mix_hex(color, 238 / 255)
        if style in {"outset", "ridge"}:
            return light, dark
        return dark, light

    def _append_bevel_border(
        self,
        spec: dict[str, Any],
        x: int,
        y: int,
        width: int,
        height: int,
        stroke_width: int,
        stroke: str,
        style: str,
    ) -> None:
        """Draw a CSS inset/outset border as four inner edge rectangles."""
        tl, br = self._bevel_colors(stroke, style)
        edge = max(1, min(stroke_width, min(width, height) // 2))
        # CSS borders are painted inside the border box.  The two axes share
        # corners; the later bottom/right pass intentionally wins there.
        edges = [
            (x, y, width, edge, tl),
            (x, y, edge, height, tl),
            (x, y + height - edge, width, edge, br),
            (x + width - edge, y, edge, height, br),
        ]
        for ex, ey, ew, eh, color in edges:
            band = ET.Element("rect")
            band.set("x", str(ex))
            band.set("y", str(ey))
            band.set("width", str(max(1, ew)))
            band.set("height", str(max(1, eh)))
            band.set("fill", color)
            self._apply_opacity(band, spec)
            self._append(band, spec)

    @staticmethod
    def _apply_opacity(el: ET.Element, spec: dict[str, Any]) -> None:
        """computed `opacity` → SVG `opacity`（缺失 / 1 不写，老产物逐字节不变）。"""
        try:
            op = float(spec.get("opacity"))
        except (TypeError, ValueError):
            return
        if 0.0 < op < 1.0:
            el.set("opacity", "%.3f" % op)

    @staticmethod
    def _apply_letter_spacing(el: ET.Element, spec: dict[str, Any]) -> None:
        """computed `letter-spacing` → SVG `letter-spacing`（px = 用户单位，可负）。"""
        try:
            ls = float(spec.get("letterSpacing"))
        except (TypeError, ValueError):
            return
        if abs(ls) >= 0.01:
            el.set("letter-spacing", ("%.2f" % ls).rstrip("0").rstrip("."))

    @staticmethod
    def _rect_corners(spec: dict[str, Any]) -> list[int] | None:
        """非均匀四角半径 [tl,tr,br,bl]；均匀 / 缺失返回 None（走 <rect rx/ry>）。"""
        corners = spec.get("borderRadiusCorners")
        if not isinstance(corners, (list, tuple)) or len(corners) != 4:
            return None
        try:
            vals = [max(0, int(round(float(c)))) for c in corners]
        except (TypeError, ValueError):
            return None
        return vals if len(set(vals)) > 1 else None

    @staticmethod
    def _rounded_rect_path(x: int, y: int, w: int, h: int, corners: list[int]) -> str:
        """四角半径不同的圆角矩形：<rect> 只能给统一的 rx/ry，改画 path。

        corners 是 CSS 顺序 [tl,tr,br,bl]；半径按 min(w,h)/2 夹一遍（与浏览器
        的溢出缩放同向的保守近似）。
        """
        limit = max(0, min(w, h) // 2)
        tl, tr, br, bl = (min(c, limit) for c in corners)
        return (
            "M %d %d H %d A %d %d 0 0 1 %d %d V %d A %d %d 0 0 1 %d %d "
            "H %d A %d %d 0 0 1 %d %d V %d A %d %d 0 0 1 %d %d Z"
        ) % (
            x + tl,
            y,
            x + w - tr,
            tr,
            tr,
            x + w,
            y + tr,
            y + h - br,
            br,
            br,
            x + w - br,
            y + h,
            x + bl,
            bl,
            bl,
            x,
            y + h - bl,
            y + tl,
            tl,
            tl,
            x + tl,
            y,
        )

    def _clip_id(self, spec: dict[str, Any]) -> str | None:
        """把 DesignSpec 上的祖先裁剪矩形换成 clipPath id（同矩形复用同一个）。

        真实页的表格是横向滚动容器：单元格的 getBoundingClientRect 仍是布局矩形
        （表格横向内容宽到 3329px），滚出可视区的列在几何上完全正常，直出端只能
        靠这个 id 把内容裁到祖先容器边界内。没有 clip 字段的 spec（含旧产物、
        grounding/cv 路线）返回 None，输出与以前逐字节一致。
        """
        clip = (spec or {}).get("clip")
        if not clip:
            return None
        try:
            x, y, w, h = (int(round(float(v))) for v in clip)
        except (TypeError, ValueError):
            return None
        if w < 1 or h < 1:
            return None
        key = (x, y, w, h)
        cid = self._clip_paths.get(key)
        if cid is not None:
            return cid
        cid = "clip-%d" % len(self._clip_paths)
        self._clip_paths[key] = cid
        clip_path = ET.Element("clipPath")
        clip_path.set("id", cid)
        rect = ET.SubElement(clip_path, "rect")
        rect.set("x", str(x))
        rect.set("y", str(y))
        rect.set("width", str(w))
        rect.set("height", str(h))
        self.defs.append(clip_path)
        return cid

    def _append(self, el: ET.Element, spec: dict[str, Any]) -> None:
        """挂一个图元：需要裁边时套一层 <g clip-path>，几何本身一律不动。

        不用"把盒子裁小"的做法：文本基线吃 height（y + h/2 + 0.375em），改盒子会
        让基线跟着漂。裁边只该发生在绘制阶段。

        倾斜同理只发生在绘制阶段：`rotation`（度，逆时针正，与 Figma 同向）
        绕**元素盒子中心**旋转。中心与 Figma 侧 `node.rotation` 的旋转中心一致，
        两边落笔才对得上。裁边要包在旋转外层——clip 是页面坐标，转过的形状
        再裁就会错。
        """
        node = el
        degrees = spec.get("rotation")
        if isinstance(degrees, (int, float)) and abs(float(degrees)) >= 0.01:
            x = float(spec.get("x", 0))
            y = float(spec.get("y", 0))
            width = float(spec.get("width", 0))
            height = float(spec.get("height", 0))
            group = ET.Element("g")
            group.set(
                "transform",
                "rotate(%g %g %g)" % (float(degrees), x + width / 2, y + height / 2),
            )
            group.append(el)
            node = group
        cid = self._clip_id(spec)
        if not cid:
            self.elements.append(node)
            return
        clip_group = ET.Element("g")
        clip_group.set("clip-path", "url(#%s)" % cid)
        clip_group.append(node)
        self.elements.append(clip_group)

    def create_rectangle(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        x = int(spec.get("x", 0))
        y = int(spec.get("y", 0))
        width = int(spec.get("width", 100))
        height = int(spec.get("height", 40))
        fill = self._get_color(spec, "fillColor", "#cccccc")
        stroke = self._get_color(spec, "borderColor", "none")
        stroke_width = int(spec.get("borderWidth", 0))
        radius = int(spec.get("borderRadius", 0))
        border_style = str(spec.get("borderStyle") or "").strip().lower()

        # 盒子投影先落笔（画在本元素之下、先前内容之上），与 CSS 的绘制序一致
        for shadow in spec.get("shadows") or []:
            self._append_shadow(spec, shadow, radius)

        corners = self._rect_corners(spec)
        if corners:
            shape = ET.Element("path")
            shape.set("d", self._rounded_rect_path(x, y, width, height, corners))
            shape.set("fill", fill)
        else:
            shape = ET.Element("rect")
            shape.set("x", str(x))
            shape.set("y", str(y))
            shape.set("width", str(width))
            shape.set("height", str(height))
            # 属性写入顺序与旧实现保持一致（ElementTree 按插入序序列化，
            # fill 必须在 rx/ry 之前），否则老产物的 SVG 字节会变。
            shape.set("fill", fill)
            shape.set("rx", str(radius))
            shape.set("ry", str(radius))
        bevel = (
            stroke_width > 0
            and stroke != "none"
            and border_style in {"inset", "outset", "groove", "ridge"}
        )
        if stroke_width > 0 and stroke != "none" and not bevel:
            shape.set("stroke", stroke)
            shape.set("stroke-width", str(stroke_width))
        self._apply_opacity(shape, spec)
        self._append(shape, spec)
        if bevel:
            self._append_bevel_border(
                spec, x, y, width, height, stroke_width, stroke, border_style
            )
        return None

    def _shadow_filter(self, blur: float) -> str | None:
        """按模糊半径取（或新建）一个高斯模糊滤镜 id；blur<=0 不需要滤镜。"""
        if blur <= 0:
            return None
        key = round(float(blur), 2)
        fid = self._blur_filters.get(key)
        if fid is not None:
            return fid
        fid = "shadow-blur-%d" % len(self._blur_filters)
        self._blur_filters[key] = fid
        filt = ET.Element("filter")
        filt.set("id", fid)
        # 过滤区域要留够扩散空间，否则模糊边缘会被自身 bbox 裁掉
        filt.set("x", "-60%")
        filt.set("y", "-60%")
        filt.set("width", "220%")
        filt.set("height", "220%")
        # CSS 的 blur 半径 ≈ 2×高斯 stdDeviation（Chrome 的实现口径）
        ET.SubElement(filt, "feGaussianBlur").set(
            "stdDeviation", "%.3f" % (float(blur) / 2.0)
        )
        self.defs.append(filt)
        return fid

    def _append_shadow(self, spec: dict[str, Any], shadow: dict, radius: int) -> None:
        """把一层 CSS 盒子投影画成一个矩形色块（+ 可选模糊）。

        几何按 CSS 规则：整个盒子先按 spread 外扩，再平移 (dx, dy)；圆角同步外扩。
        画在本元素之前 → 落在元素下方、先前内容上方（与浏览器绘制序一致）。
        """
        try:
            w = float(spec.get("width", 0))
            h = float(spec.get("height", 0))
        except (TypeError, ValueError):
            return
        if w <= 0 or h <= 0:
            return
        spread = float(shadow.get("spread", 0) or 0)
        sx = float(spec.get("x", 0)) + float(shadow.get("dx", 0) or 0) - spread
        sy = float(spec.get("y", 0)) + float(shadow.get("dy", 0) or 0) - spread
        sw, sh = w + 2 * spread, h + 2 * spread
        if sw <= 0 or sh <= 0:
            return
        rect = ET.Element("rect")
        rect.set("x", str(int(round(sx))))
        rect.set("y", str(int(round(sy))))
        rect.set("width", str(max(1, int(round(sw)))))
        rect.set("height", str(max(1, int(round(sh)))))
        rx = max(0, int(round(radius + spread)))
        if rx:
            rect.set("rx", str(rx))
            rect.set("ry", str(rx))
        rect.set("fill", str(shadow.get("color") or "#000000"))
        alpha = float(shadow.get("alpha", 1.0) or 1.0)
        if alpha < 1.0:
            rect.set("fill-opacity", "%.3f" % alpha)
        fid = self._shadow_filter(float(shadow.get("blur", 0) or 0))
        if fid:
            rect.set("filter", "url(#%s)" % fid)
        self._append(rect, spec)

    def create_ellipse(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        x = int(spec.get("x", 0))
        y = int(spec.get("y", 0))
        width = int(spec.get("width", 100))
        height = int(spec.get("height", 100))
        fill = self._get_color(spec, "fillColor", "#cccccc")

        ellipse = ET.Element("ellipse")
        ellipse.set("cx", str(x + width // 2))
        ellipse.set("cy", str(y + height // 2))
        ellipse.set("rx", str(width // 2))
        ellipse.set("ry", str(height // 2))
        ellipse.set("fill", fill)
        self._apply_opacity(ellipse, spec)
        self._append(ellipse, spec)
        return None

    def create_image(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        x = int(spec.get("x", 0))
        y = int(spec.get("y", 0))
        width = int(spec.get("width", 100))
        height = int(spec.get("height", 100))
        image_b64 = str(spec.get("imageBase64", ""))
        is_avatar = bool(spec.get("isAvatar", False))

        if not image_b64:
            return self.create_rectangle(spec, parent_id=parent_id)

        # 像素底/图片同样可能带投影（透明浮层容器的滚动阴影）——阴影画在图片之前
        for shadow in spec.get("shadows") or []:
            self._append_shadow(spec, shadow, int(spec.get("borderRadius", 0) or 0))

        image_el = ET.Element("image")
        image_el.set("x", str(x))
        image_el.set("y", str(y))
        image_el.set("width", str(width))
        image_el.set("height", str(height))
        image_el.set("href", f"data:image/png;base64,{image_b64}")
        if is_avatar:
            clip_id = f"avatar-clip-{x}-{y}"
            defs = ET.Element("defs")
            clip_path = ET.SubElement(defs, "clipPath")
            clip_path.set("id", clip_id)
            circle = ET.SubElement(clip_path, "circle")
            circle.set("cx", str(x + width // 2))
            circle.set("cy", str(y + height // 2))
            circle.set("r", str(min(width, height) // 2))
            self.elements.append(defs)
            image_el.set("clip-path", f"url(#{clip_id})")
        self._apply_opacity(image_el, spec)
        self._append(image_el, spec)
        return None

    def create_vector(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        raw = str(spec.get("vectorSvg") or "").strip()
        if not raw:
            return None
        try:
            node = ET.fromstring(raw)
        except ET.ParseError:
            return self.create_image(spec, parent_id=parent_id)
        node.set("x", str(int(spec.get("x", 0))))
        node.set("y", str(int(spec.get("y", 0))))
        node.set("width", str(int(spec.get("width", 100))))
        node.set("height", str(int(spec.get("height", 100))))
        self._append(node, spec)
        return None

    @staticmethod
    def _baseline_inset(spec: dict[str, Any]) -> float:
        """内容盒相对边框盒的上偏移 = `border-top`（IR 只采到 border，没采 padding）。"""
        try:
            return max(0.0, float(spec.get("borderWidth") or 0.0))
        except (TypeError, ValueError):
            return 0.0

    def create_text(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        text = str(spec.get("text", ""))

        if not text:
            return None

        lines = spec.get("lines")
        if lines:
            # 折行文本：一行一个 <tspan>（断点由 IR 的 text_wrap 算好），每行的
            # 基线按行高逐行下移，与浏览器里那些行框一一对应。
            self._append(self._lines_text_element(spec, lines), spec)
            return None

        x = int(spec.get("x", 0))
        # y 是元素上沿（DesignSpec 约定），SVG 要的是基线
        baseline_height = spec.get("height", 0)
        measured_line = False
        em_box = spec.get("textEmBox")
        if (
            not spec.get("lineHeight")
            and isinstance(em_box, (list, tuple))
            and len(em_box) == 4
            and int(spec.get("textEmLines") or 0) == 1
        ):
            try:
                baseline_height = float(em_box[3])
                measured_line = True
            except (TypeError, ValueError):
                baseline_height = spec.get("height", 0)
        y = text_baseline_y(
            spec.get("y", 0),
            baseline_height,
            spec.get("fontSize", 16),
            self._baseline_inset(spec),
        )
        if measured_line:
            # The Range line box starts one pixel below the CSS line-box
            # baseline anchor used by the element-height fallback.
            y -= 1
        fill = self._get_color(spec, "textColor", "#000000")
        font_size = int(spec.get("fontSize", 16))
        # 元素框里的水平对齐，与 `_lines_text_element` 同一口径（x 挪到锚点 + 写锚点）。
        # 单行文本元素原先只看 `textAnchor`——那是**控件**路径的字段（x 已按盒子中心
        # 算好），于是带 `text-align:center` 的文本元素全被左对齐：真机 dushu 首页
        # 30 个居中元素（28 个分类格 + 页脚版权）整体左偏，版权那行盒宽 1170px 直接
        # 偏了半个页面（整图 mean 1.229 → 1.050）。控件路径（anchor=middle）与
        # 左对齐（start/缺省）保持逐字节不变。
        align = ""
        anchor = str(spec.get("textAnchor") or "").strip().lower()
        box_width = int(spec.get("width") or 0)
        if anchor != "middle" and box_width > 0:
            align = str(spec.get("textAlign") or "").strip().lower()
            if align == "center":
                x += box_width // 2
            elif align in ("end", "right"):
                align = "end"
                x += box_width
            else:
                align = ""

        text_el = ET.Element("text")
        text_el.set("x", str(x))
        text_el.set("y", str(y))
        text_el.set("fill", fill)
        text_el.set("font-size", str(font_size))
        # 优先用节点 computed 字体栈（dom 直出），否则用输出端默认栈
        text_el.set("font-family", spec.get("fontFamily") or self.font_stack)
        weight = _font_weight(spec)
        if weight is not None:
            text_el.set("font-weight", weight)
        if str(spec.get("fontStyle") or "").lower() in {"italic", "oblique"}:
            text_el.set("font-style", "italic")
        if (
            str(spec.get("textAnchor") or "").strip().lower() == "middle"
            or align == "center"
        ):
            text_el.set("text-anchor", "middle")
        elif align == "end":
            text_el.set("text-anchor", "end")
        self._apply_letter_spacing(text_el, spec)
        self._apply_opacity(text_el, spec)
        text_el.text = text
        self._apply_text_whitespace(text_el, text)
        self._append(text_el, spec)
        return None

    def _lines_text_element(self, spec: dict[str, Any], lines: list) -> ET.Element:
        """把多行文本拼成一个 <text> + 每行一个 <tspan>。"""
        font_size = int(spec.get("fontSize", 16))
        line_height = int(spec.get("lineHeight") or round(font_size * 1.4))
        if len(lines) == 1 and not spec.get("lineHeight"):
            # Range.getClientRects() 对 single-line block records the real line
            # box height.  Use it when computed line-height is "normal": the
            # generic 1.4em fallback is too tall for Times New Roman paragraphs
            # and shifts their glyphs down by several pixels.
            box = spec.get("textEmBox")
            if isinstance(box, (list, tuple)) and len(box) == 4:
                try:
                    measured = int(round(float(box[3])))
                except (TypeError, ValueError):
                    measured = 0
                if measured > 0:
                    line_height = measured
        width = int(spec.get("width") or 0)
        align = str(spec.get("textAlign") or "start")
        x = int(spec.get("x", 0))
        if width > 0 and align == "center":
            x += width // 2
        elif width > 0 and align == "end":
            x += width
        text_el = ET.Element("text")
        text_el.set("x", str(x))
        text_el.set("fill", self._get_color(spec, "textColor", "#000000"))
        text_el.set("font-size", str(font_size))
        text_el.set("font-family", spec.get("fontFamily") or self.font_stack)
        weight = _font_weight(spec)
        if weight is not None:
            text_el.set("font-weight", weight)
        if str(spec.get("fontStyle") or "").lower() in {"italic", "oblique"}:
            text_el.set("font-style", "italic")
        if width > 0 and align == "center":
            text_el.set("text-anchor", "middle")
        elif width > 0 and align == "end":
            text_el.set("text-anchor", "end")
        self._apply_letter_spacing(text_el, spec)
        self._apply_opacity(text_el, spec)
        top = spec.get("y", 0) + self._baseline_inset(spec)
        line_sizes = spec.get("lineSizes")
        mixed = (
            isinstance(line_sizes, list)
            and len(line_sizes) == len(lines)
            and any(
                isinstance(value, (int, float)) and value > 0 and int(value) != font_size
                for value in line_sizes
            )
        )
        if not mixed:
            for i, line in enumerate(lines):
                tspan = ET.SubElement(text_el, "tspan")
                tspan.set("x", str(x))
                tspan.set(
                    "y",
                    str(text_baseline_y(top + i * line_height, line_height, font_size)),
                )
                tspan.text = line
        else:
            # 一个块里的行可以有不同字号（价格 + 单位：`5.8` 62pt、`折` 30pt）。
            # 各行按**自己**的字号算行框与基线——不同字号的 em 基线不在同一条
            # 线上，共用一个 line_height 会让大行压住小行。行框比例沿用上面算出的
            # `line_height / font_size`，这样显式 lineHeight 仍然生效。
            ratio = (line_height / font_size) if font_size else 1.4
            cursor = top
            for i, line in enumerate(lines):
                size = line_sizes[i]
                size = int(size) if isinstance(size, (int, float)) and size > 0 else font_size
                box_height = max(1, int(round(size * ratio)))
                tspan = ET.SubElement(text_el, "tspan")
                tspan.set("x", str(x))
                tspan.set("font-size", str(size))
                tspan.set(
                    "y", str(text_baseline_y(cursor, box_height, size))
                )
                tspan.text = line
                cursor += box_height
        self._apply_text_whitespace(
            text_el,
            "\n".join(str(line) for line in lines),
        )
        return text_el

    @staticmethod
    def _apply_text_whitespace(text_el: ET.Element, text: str) -> None:
        if text[:1].isspace() or text[-1:].isspace():
            text_el.set(
                "{http://www.w3.org/XML/1998/namespace}space",
                "preserve",
            )

    def flush(self) -> None:
        svg = ET.Element("svg")
        svg.set("xmlns", "http://www.w3.org/2000/svg")
        svg.set("width", str(self.canvas_width))
        svg.set("height", str(self.canvas_height))
        svg.set("viewBox", f"0 0 {self.canvas_width} {self.canvas_height}")

        if self.canvas_background:
            ET.SubElement(
                svg,
                "rect",
                x="0",
                y="0",
                width=str(self.canvas_width),
                height=str(self.canvas_height),
                fill=self.canvas_background,
            )
        if self.defs:
            defs = ET.Element("defs")
            for d in self.defs:
                defs.append(d)
            svg.append(defs)
        for el in self.elements:
            svg.append(el)

        tree = ET.ElementTree(svg)
        tree.write(self.output_path, encoding="utf-8", xml_declaration=True)
        logger.info(f"SVG 已保存: {self.output_path}")
