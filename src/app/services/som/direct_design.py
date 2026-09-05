# -*- coding: utf-8 -*-
"""结构路线（dom）样式直出 DesignSpec：用 computed style 确定性拼装，跳过 VLM。

前提：SoM JSON 的 containers/elements 带 style 字段——dom 由 DOM_JS 采集，
由 capture 阶段直接落盘，样式齐备后走同一条直出规则。
image/avatar 元素会按 SoM bbox 从整页截图裁真实像素回填（imageBase64），
避免直出稿里所有图片都变成占位灰块。
"""
from __future__ import annotations

import base64
import io
import logging

logger = logging.getLogger(__name__)

_DIRECT_ROUTES = ("dom",)


def _snap4(value: int) -> int:
    """数值就近取整到 4px 网格。"""
    return int(round(float(value) / 4.0) * 4)


def _geometry(item: dict) -> tuple[int, int, int, int]:
    x, y, w, h = item["bbox"]
    return (max(0, _snap4(x)), max(0, _snap4(y)),
            max(1, _snap4(w)), max(1, _snap4(h)))


def _border_fields(style: dict) -> dict:
    """从 style 取边框字段；borderColor/borderWidth 成对存在才返回。"""
    if style.get("borderColor") and style.get("borderWidth"):
        return {"borderColor": str(style["borderColor"]),
                "borderWidth": int(style["borderWidth"])}
    return {}


def _crop_image_b64(image_path: str, x: int, y: int, w: int, h: int,
                    canvas_w: int, canvas_h: int) -> str | None:
    """按 bbox 从整页截图裁出图片真实像素并编码 PNG base64（越界自动 clamp）。

    截图与 SoM bbox 同为整文档像素坐标，可 1:1 裁剪；缺图/越界/解码失败返回
    None，由上层决定是否保留占位。
    """
    from PIL import Image
    try:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(canvas_w, x + w), min(canvas_h, y + h)
        if x1 <= x0 or y1 <= y0:
            return None
        with Image.open(image_path) as im:
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            region = im.crop((x0, y0, x1, y1))
        buf = io.BytesIO()
        region.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        logger.warning("图片元素回填失败 %s @ (%d,%d,%d,%d): %s",
                       image_path, x, y, w, h, exc)
        return None


def build_direct_design(som_json: dict) -> dict:
    """按 SoM（含 style 字段）确定性生成 DesignSpec。

    容器只要“有非透明背景色”或“带真实边框（color+width 成对）”就画出；
    透明且无边框才跳过，避免凭空造框（计数写入 _meta.skipped_transparent_containers）。
    元素按 DOM type/text/computed style 拼装；image/avatar 回填原图裁剪。
    颜色/字号以浏览器计算结果为准，比让 VLM 看图猜测更准、更快。
    几何一律按 SoM bbox 4px 网格取整。
    """
    route = (som_json.get("provenance") or {}).get("route") or "dom"
    size = som_json.get("size") or [0, 0]
    canvas = {"width": int(size[0]), "height": int(size[1])}
    image_path = som_json.get("image")
    elements: list[dict] = []
    skipped_containers = 0
    overlay_count = 0
    seen_band_crops: set[tuple[int, int, int, int]] = set()

    for c in som_json.get("containers", []):
        style = c.get("style") or {}
        fill = style.get("fillColor")
        border = _border_fields(style)
        x, y, w, h = _geometry(c)
        is_overlay = bool(c.get("overlay", False))
        if not fill and not border:
            if is_overlay and image_path:
                # 透明浮层容器（antd fixed wrapper 等）没有自身底色，裁原截图对应
                # 区域真实像素作底，浮层排在普通内容之上时能把底下内容正确盖住。
                b64 = _crop_image_b64(image_path, x, y, w, h,
                                      canvas["width"], canvas["height"])
                if b64:
                    band_key = (x, y, w, h)
                    if band_key in seen_band_crops:
                        skipped_containers += 1   # 同框克隆容器不重复出底
                        continue
                    seen_band_crops.add(band_key)
                    elements.append({"id": c["id"], "type": "container",
                                     "x": x, "y": y, "width": w, "height": h,
                                     "text": "", "overlay": True,
                                     "zIndex": int(c.get("zIndex") or 0),
                                     "imageBase64": b64, "style": {}})
                    overlay_count += 1
                    continue
            skipped_containers += 1
            continue
        out_style: dict = {}
        if fill:
            out_style["fillColor"] = fill
        else:
            # 透明底 + 真实边框（白卡片/描边输入组等）：SVG 默认灰底会盖住整块，
            # 显式 transparent 保留原透明背景、只画描边。
            out_style["fillColor"] = "transparent"
        out_style.update(border)
        if style.get("borderRadius"):
            out_style["borderRadius"] = int(style["borderRadius"])
        if is_overlay:
            overlay_count += 1
        elements.append({"id": c["id"], "type": "container", "x": x, "y": y,
                         "width": w, "height": h, "text": "",
                         "overlay": is_overlay,
                         "zIndex": int(c.get("zIndex") or 0),
                         "style": out_style})

    image_backfilled = 0
    for e in som_json.get("elements", []):
        style = e.get("style") or {}
        etype = e.get("type") or "rectangle"
        x, y, w, h = _geometry(e)
        out_style: dict = {}
        fill = style.get("fillColor")
        border = _border_fields(style)
        if fill:
            out_style["fillColor"] = fill
        elif etype in ("button", "input"):
            # 无自身背景且无真实边框的控件常见白底，给保守默认；
            # 有边框则保留透明背景 + 描边（例如工具栏里的描边按钮）。
            out_style["fillColor"] = "#FFFFFF" if not border else "transparent"
        out_style.update(border)
        if style.get("textColor"):
            out_style["textColor"] = style["textColor"]
        elif etype == "text":
            out_style["textColor"] = "#000000"
        if style.get("fontSize"):
            out_style["fontSize"] = int(style["fontSize"])
        if style.get("fontWeight"):
            out_style["fontWeight"] = style["fontWeight"]
        if style.get("borderRadius"):
            out_style["borderRadius"] = int(style["borderRadius"])
        is_overlay = bool(e.get("overlay", False))
        if is_overlay:
            overlay_count += 1
        element = {"id": str(e["id"]), "type": etype, "x": x, "y": y,
                   "width": w, "height": h, "text": e.get("text") or "",
                   "overlay": is_overlay,
                   "zIndex": int(e.get("zIndex") or 0),
                   "style": out_style}
        if etype in ("image", "avatar") and image_path:
            b64 = _crop_image_b64(image_path, x, y, w, h,
                                  canvas["width"], canvas["height"])
            if b64:
                element["imageBase64"] = b64
                image_backfilled += 1
        elements.append(element)

    containers = som_json.get("containers") or []
    som_elements = som_json.get("elements") or []
    drawn_containers = len(containers) - skipped_containers
    expected = len(containers) + len(som_elements)
    meta = {"mode": f"{route}-direct", "source": f"{route} computed style, no VLM",
            "calls": 0, "rounds": 0, "expected": expected,
            "returned": drawn_containers + len(som_elements),
            "coverage": 1.0, "containers": drawn_containers,
            "elements": len(som_elements),
            "overlays": overlay_count,
            "image_backfilled": image_backfilled,
            "skipped_transparent_containers": skipped_containers}
    return {"canvas": canvas, "elements": elements, "_meta": meta}


def try_build_direct_design(som_json: dict, cfg) -> dict | None:
    """dom 路线且有足够 computed style 时直出 DesignSpec，否则返回 None 让上层走 VLM。"""
    provenance = som_json.get("provenance") or {}
    if provenance.get("route") not in _DIRECT_ROUTES:
        return None
    if not getattr(cfg, "dom_direct_design", False):
        return None
    items = list(som_json.get("containers") or []) + list(som_json.get("elements") or [])
    styled = [it for it in items if it.get("style")]
    if not items or len(styled) < len(items) * 0.5:
        return None
    return build_direct_design(som_json)
