# -*- coding: utf-8 -*-
"""DesignSpec 图片裁剪回填工具（所有路线共用）。

结构/语义路线生成的 DesignSpec 里，type=image/avatar 的元素（logo、图标、
头像、正文插图）默认只有 bbox 没有真实像素。渲染前按 bbox 从整页截图裁剪
PNG base64 回填到 imageBase64，SVG/Figma 才能画出非空位图。
"""
from __future__ import annotations

import base64
import io
import logging

logger = logging.getLogger(__name__)


def crop_image_b64(image_path: str, x: int, y: int, w: int, h: int,
                   canvas_w: int, canvas_h: int) -> str | None:
    """按 bbox 从整页截图裁出真实像素并编码 PNG base64（越界自动 clamp）。

    截图与 bbox 同为整文档像素坐标，可 1:1 裁剪；缺图/越界/解码失败返回 None。
    """
    from PIL import Image
    try:
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(int(canvas_w), int(x) + int(w)), min(int(canvas_h), int(y) + int(h))
        if x1 <= x0 or y1 <= y0:
            return None
        with Image.open(image_path) as im:
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            region = im.crop((x0, y0, x1, y1))
        buf = io.BytesIO()
        region.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:  # noqa: BLE001 - 单元素回填失败不应中断整次渲染
        logger.warning("图片元素回填失败 %s @ (%d,%d,%d,%d): %s",
                       image_path, x, y, w, h, exc)
        return None


def backfill_design_image_crops(design: dict, image_path: str) -> dict:
    """把 design 中所有缺失 imageBase64 的 image/avatar 元素按 bbox 回填。

    design 原地修改；返回 {"image_elements": n, "backfilled": k, "failed": m}。
    已带 base64 或裁剪失败的元素保持不变（失败保留占位，由上层自行决定）。
    """
    elements = design.get("elements") or []
    canvas = design.get("canvas") or {}
    canvas_w = canvas.get("width")
    canvas_h = canvas.get("height")
    stats = {"image_elements": 0, "backfilled": 0, "failed": 0}
    if not elements or not image_path or not canvas_w or not canvas_h:
        return stats
    for el in elements:
        if el.get("type") not in ("image", "avatar"):
            continue
        stats["image_elements"] += 1
        if el.get("imageBase64"):
            continue
        b64 = crop_image_b64(image_path, el.get("x", 0), el.get("y", 0),
                             el.get("width", 0), el.get("height", 0),
                             canvas_w, canvas_h)
        if b64:
            el["imageBase64"] = b64
            stats["backfilled"] += 1
        else:
            stats["failed"] += 1
    if stats["image_elements"]:
        logger.info("image backfill: %s", stats)
    return stats
