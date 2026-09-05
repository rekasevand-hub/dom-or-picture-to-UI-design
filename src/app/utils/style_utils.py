# -*- coding: utf-8 -*-
"""computed style → DesignSpec 样式字段的解析/归一（dom 与 a11y 共享）。"""
from __future__ import annotations

import re


def css_color_to_hex(value) -> str | None:
    """把 computed style 的 rgb()/rgba() 转成 #RRGGBB；透明/无法解析返回 None。"""
    text = (value or "").strip().lower()
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)", text)
    if not m:
        return None
    r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
    alpha = float(m.group(4)) if m.group(4) is not None else 1.0
    if alpha < 0.99:
        return None
    return "#%02x%02x%02x" % (r, g, b)


def css_px(value) -> int | None:
    """解析 computed style 的 px 数值，如 '14px' -> 14；非数值返回 None。"""
    text = (value or "").strip().lower()
    m = re.match(r"^([\d.]+)px$", text)
    if not m:
        return None
    return int(float(m.group(1)))


def css_font_weight(value) -> str | None:
    """把 computed fontWeight 归一到 normal/bold。"""
    text = (value or "").strip().lower()
    if text in ("bold", "bolder"):
        return "bold"
    if text in ("normal", "lighter"):
        return "normal"
    try:
        return "bold" if int(float(text)) >= 600 else "normal"
    except (TypeError, ValueError):
        return None


def build_style(bg=None, page_bg=None, color=None, fontSize=None,
                fontWeight=None, borderRadius=None,
                borderColor=None, borderWidth=None) -> dict:
    """把原始 CSS 值归一成 DesignSpec style 字段（透明/缺失不写）。

    borderColor/borderWidth 必须成对有效才写：computed borderColor 在无边框时
    也会是 rgb(0,0,0) 之类的默认色，单独判断 color 会误加黑边。
    """
    style: dict = {}
    bg_hex = css_color_to_hex(bg)
    page_hex = css_color_to_hex(page_bg)
    if bg_hex and bg_hex != page_hex:
        style["fillColor"] = bg_hex
    color_hex = css_color_to_hex(color)
    if color_hex:
        style["textColor"] = color_hex
    fs = css_px(fontSize)
    if fs:
        style["fontSize"] = fs
    fw = css_font_weight(fontWeight)
    if fw:
        style["fontWeight"] = fw
    radius = css_px(borderRadius)
    if radius:
        style["borderRadius"] = radius
    border_hex = css_color_to_hex(borderColor)
    bw = css_px(borderWidth)
    if border_hex and bw:
        style["borderColor"] = border_hex
        style["borderWidth"] = bw
    return style
