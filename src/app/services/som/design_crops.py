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

from src.app import tuning

logger = logging.getLogger(__name__)


def crop_image_b64(
    image_path: str,
    x: int,
    y: int,
    w: int,
    h: int,
    canvas_w: int,
    canvas_h: int,
    pixel_ratio: int = 1,
) -> str | None:
    """按 bbox 从整页截图裁出真实像素并编码 PNG base64（越界自动 clamp）。

    截图与 bbox 同为整文档像素坐标，可 1:1 裁剪；缺图/越界/解码失败返回 None。
    """
    from PIL import Image

    try:
        scale = max(1, int(pixel_ratio))
        x0, y0 = max(0, int(x) * scale), max(0, int(y) * scale)
        x1 = min(int(canvas_w) * scale, (int(x) + int(w)) * scale)
        y1 = min(int(canvas_h) * scale, (int(y) + int(h)) * scale)
        if x1 <= x0 or y1 <= y0:
            return None
        with Image.open(image_path) as im:
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            x1, y1 = min(x1, im.width), min(y1, im.height)
            region = im.crop((x0, y0, x1, y1))
        buf = io.BytesIO()
        region.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:  # noqa: BLE001 - 单元素回填失败不应中断整次渲染
        logger.warning(
            "图片元素回填失败 %s @ (%d,%d,%d,%d): %s", image_path, x, y, w, h, exc
        )
        return None


def covers(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int], eps: int = 1
) -> bool:
    """a 是否完全覆盖 b（允许 eps px 容差）；与渲染端 adapter_base._covers 同口径。"""
    return (
        a[0] <= b[0] + eps
        and a[1] <= b[1] + eps
        and b[0] + b[2] <= a[0] + a[2] + eps
        and b[1] + b[3] <= a[1] + a[3] + eps
    )


def rect_of(el: dict) -> tuple[int, int, int, int] | None:
    """取直出元素的轴对齐矩形；缺字段/非数字返回 None。"""
    try:
        return (int(el["x"]), int(el["y"]), int(el["width"]), int(el["height"]))
    except (KeyError, TypeError, ValueError):
        return None


def shadowed_by_pixel_backdrop(el: dict, backdrops: list[dict]) -> bool:
    """元素是否被某块“权威像素区”完全盖住（= 画了也看不见的冗余图层）。

    几何覆盖只是必要条件，还要“像素底确实画在它之后”：渲染端绘制序是
    普通内容 → overlay（zIndex 升序）→ 同 z 的像素底最后落笔
    （adapter_base.render_design 的 cropBackdrop 规则）。两处必须同口径，
    否则会出现“像素底被白底盖住、白底又把底图上的文字擦掉”这类问题。
    """
    if el.get("cropBackdrop"):
        return False  # 像素底之间互为最终像素，不做互相过滤
    r = rect_of(el)
    if r is None:
        return False
    for b in backdrops:
        br = rect_of(b)
        if br is None or not covers(br, r):
            continue
        if not el.get("overlay"):
            return True  # overlay 整体后画，普通图元必被盖住
        if int(b.get("zIndex") or 0) >= int(el.get("zIndex") or 0):
            return True  # 同 z 或更高的像素底在其后落笔
    return False


def apply_crops_to_design(design: dict, image_path: str | None, crops) -> int:
    """把“权威像素区”贴到 DesignSpec 上（任何路线通用），返回贴上的块数。

    两条链路的知识面不同，兜底方式也不同：
    - dom 直出知道每个节点是什么（img/svg、图标字体的 ::before 字形、PUA 码位），
      图标/图片靠 provider 自动判出来；
    - grounding/cv 只有像素，判断不了“这是图标还是文字”，只能由用户框选。
    贴法一致：按原图像素 1:1 裁图 → cropBackdrop（渲染端在同 z 时最后落笔）→
    被它完全盖住的图元丢弃（见 shadowed_by_pixel_backdrop）。
    """
    elements = design.get("elements") or []
    canvas = design.get("canvas") or {}
    canvas_w, canvas_h = canvas.get("width"), canvas.get("height")
    if not elements or not image_path or not canvas_w or not canvas_h:
        return 0
    backdrops: list[dict] = []
    for k, rect in enumerate(crops or []):
        try:
            x, y, w, h = (int(round(float(v))) for v in rect)
        except (TypeError, ValueError):
            continue
        if w < tuning.MIN_BOX_SIZE or h < tuning.MIN_BOX_SIZE:
            continue
        b64 = crop_image_b64(image_path, x, y, w, h, canvas_w, canvas_h)
        if not b64:
            continue
        backdrops.append(
            {
                "id": f"manual-{k + 1}",
                "type": "container",
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "text": "",
                "overlay": True,
                "zIndex": 0,
                "imageBase64": b64,
                "cropBackdrop": True,
                "style": {},
            }
        )
    if not backdrops:
        return 0
    kept = [el for el in elements if not shadowed_by_pixel_backdrop(el, backdrops)]
    design["elements"] = kept + backdrops
    meta = design.setdefault("_meta", {})
    meta["manual_crops"] = len(backdrops)
    meta["skipped_under_manual_crop"] = len(elements) - len(kept)
    return len(backdrops)


def backfill_design_image_crops(design: dict, image_path: str) -> dict:
    """把 design 中所有缺失 imageBase64 的 image/avatar 元素按 bbox 回填。

    design 原地修改；返回 {"image_elements": n, "backfilled": k, "failed": m}。
    已带 base64 或裁剪失败的元素保持不变（失败保留占位，由上层自行决定）。
    """
    elements = design.get("elements") or []
    canvas = design.get("canvas") or {}
    canvas_w = canvas.get("width")
    canvas_h = canvas.get("height")
    pixel_ratio = int((design.get("_meta") or {}).get("pixelRatio") or 1)
    stats = {"image_elements": 0, "backfilled": 0, "failed": 0}
    if not elements or not image_path or not canvas_w or not canvas_h:
        return stats
    for el in elements:
        if el.get("type") not in ("image", "avatar"):
            continue
        stats["image_elements"] += 1
        if el.get("imageBase64"):
            continue
        b64 = crop_image_b64(
            image_path,
            el.get("x", 0),
            el.get("y", 0),
            el.get("width", 0),
            el.get("height", 0),
            canvas_w,
            canvas_h,
            pixel_ratio=pixel_ratio,
        )
        if b64:
            el["imageBase64"] = b64
            stats["backfilled"] += 1
        else:
            stats["failed"] += 1
    if stats["image_elements"]:
        logger.info("image backfill: %s", stats)
    return stats
