# -*- coding: utf-8 -*-
"""页包里的 `thumbnail`：按页面内容自己画一张预览（P4）。

页成员 `Page/<guid>.rppkg` 的 L2 里有三块 —— `thumbnail`（Axure **Pages 面板**里的预览图）、
`widgetinfo`、`package`（页面本身）。`thumbnail` 之前一直是**借**原生常量
（`assets/axure/rp8/thumbnail_native.bin`，256x190 JPEG），于是面板里每一页长得都一样。

这里按 `doc.Frame` 自己画：底色 + 每个控件一块颜色 + 图片贴缩略图。**不画字形**（要字体、
还会引入跨版本差异），文字用「文字色向白里兑 60%」的色块表示位置；圆角 / 阴影 / 渐变忽略。

**确定性**：输出只取决于（页面内容, Pillow 版本）—— 没有时间戳、EXIF、随机数，也没有字体，
所以同一份 IR 连生两次的 `.rp` 仍逐字节相同（§9.14；跨 Pillow 版本不比字节这一点与 §9.14 的
「跨 Python / zlib 版本不比字节」同性质）。画不出来（没装 Pillow / 坏图）时返回 `b""`，
调用方退回模板常量图 —— 缩略图不该让整份产物生成失败。
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

# 原生缩略图的形状：Axure Pages 面板按这个比例显示，照抄它最稳。
THUMB_SIZE = (256, 190)
_BG = (255, 255, 255)
_SHAPE_EDGE = (200, 200, 200)      # 形状没给填充色时的描边
_IMAGE_FALLBACK = (180, 180, 180)  # 图片解不开时的兜底色
_JPEG_QUALITY = 80


def render(frame, size=THUMB_SIZE) -> bytes:
    """`doc.Frame` -> `thumbnail` 的 JPEG 字节；画不出来返回 `b""`（调用方退回常量）。"""
    try:
        from PIL import Image, ImageDraw, ImageOps
    except Exception as exc:                       # pragma: no cover - 只在本机缺 Pillow 时走
        logger.warning("没有可用的 Pillow（%s），页包缩略图退回模板常量", exc)
        return b""

    width, height = int(size[0]), int(size[1])
    page_w = float(frame.width) or 1.0
    page_h = float(frame.height) or 1.0
    zoom = min(width / page_w, height / page_h)
    pad_x = (width - page_w * zoom) / 2.0
    pad_y = (height - page_h * zoom) / 2.0

    canvas = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(canvas)
    resample = getattr(Image, "Resampling", Image).LANCZOS

    def box(x, y, w, h):
        """页面坐标 -> 缩略图整数盒 `(left, top, right, bottom)`（至少 1px，顺序已排好）。"""
        left = int(round(pad_x + float(x) * zoom))
        top = int(round(pad_y + float(y) * zoom))
        right = int(round(pad_x + (float(x) + float(w)) * zoom))
        bottom = int(round(pad_y + (float(y) + float(h)) * zoom))
        right = max(right, left + 1)
        bottom = max(bottom, top + 1)
        return left, top, right, bottom

    for widget in getattr(frame, "widgets", []):
        rect = box(widget.x, widget.y, widget.width, widget.height)
        kind = type(widget).__name__
        blob = getattr(widget, "data", None)
        if kind == "Image" and isinstance(blob, (bytes, bytearray)):
            thumb = _image_thumb(Image, ImageOps, bytes(blob), rect, resample)
            canvas.paste(thumb, rect[:2])
            continue
        paint = _paint_color(widget, kind)
        if paint is None:
            draw.rectangle(rect, outline=_SHAPE_EDGE)
        elif kind == "Ellipse":
            draw.ellipse(rect, fill=paint)
        else:
            draw.rectangle(rect, fill=paint)

    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=_JPEG_QUALITY, optimize=True, progressive=False)
    return out.getvalue()


def _paint_color(widget, kind):
    """这块控件该涂什么色；`None` = 没填充色（形状只描边）。"""
    fill = _opaque_rgb(getattr(widget, "fill", None))
    if fill is not None:
        return fill
    if kind in ("Text", "Button", "TextField"):
        # 文字类：用文字色向白里兑 60%，落在缩略图上就是一条淡灰「字块」而不是一团黑。
        raw = getattr(widget, "color", None)
        color = _rgb(0xFF333333 if raw is None else raw)
        return tuple(int(round(255 * 0.6 + channel * 0.4)) for channel in color)
    return None


def _image_thumb(Image, ImageOps, blob, rect, resample):
    """图片 -> 目标盒的 RGB（cover 裁切）；坏字节退回纯色块。"""
    left, top, right, bottom = rect
    try:
        with Image.open(io.BytesIO(blob)) as src:
            return ImageOps.fit(src.convert("RGB"), (right - left, bottom - top),
                                method=resample)
    except Exception as exc:
        logger.debug("缩略图里跳过一个解不开的图片：%s", exc)
        return Image.new("RGB", (right - left, bottom - top), _IMAGE_FALLBACK)


def _rgb(value):
    """`0xAARRGGBB` -> `(r, g, b)`（alpha 忽略）。"""
    value = int(value)
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def _opaque_rgb(value):
    """`0xAARRGGBB` -> `(r, g, b)`；`None` / 全透明 -> `None`（不画填充）。"""
    if value is None:
        return None
    value = int(value)
    if (value >> 24) & 0xFF == 0:
        return None
    return _rgb(value)
