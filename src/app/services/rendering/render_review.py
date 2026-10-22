# -*- coding: utf-8 -*-
"""渲染图视觉复核：把成品图按条带切块丢给多模态模型，列出它"看见"的排版毛病。

为什么要它：像素差分（`pixel_metrics`）只回答"差多少"，不回答"错在哪"。文字因宽度
重叠、被盒子截断、图片缺失这类**语义**缺陷，差分数值只能给一个偏高却说不出原因的数。
用户的原话就是"文字因宽度而重叠只有看到了才知道改"。

为什么必须切条带，不能整页丢：整页 1440x2544 交给 VLM 会被服务端缩放（长边一般压到
1~1.5k），16px 的字缩完只剩几个像素，"挤在一起"根本看不出来。所以按原分辨率切条带，
让每条带上的正文高度都还在模型看得清的范围内。

条带边界会挪到"墨迹最少的那一行"：直接按固定高度切，正好切在某行文字中间时，模型会
把两个半行当成"文字被截断"报上来（实测过，噪声很大）。

**必须拿采集截图当锚**：只给渲染图问"有什么毛病"，模型会把原页面本来就这样画的东西
也报上来（"暂无图片"占位图、被页面裁掉的"→更多"箭头……实测 dushu 首页 16 条里大半是
这类误报）。所以默认同时给"同一条带的原页截图"，只让它报"渲染有、原页没有"的那些。
"""
from __future__ import annotations

import base64
import json
import logging

logger = logging.getLogger(__name__)

# 一条带多高：700px 大约 3~4 行 16px 正文加若干卡片，缩放后仍看得清字。
BAND_HEIGHT = 700
# 一次复核最多问几条带：防止有人拿一张超长整页图把 VLM 打爆。
MAX_BANDS = 16
# 找"墨迹最少的一行"时允许上下挪动的范围（px）。
SNAP = 40
# 低于这个灰度算"有墨"（文字/线条/深色块）。
_INK_GRAY = 200

_SYSTEM = (
    "你是 UI 还原质检员。用户给你同一条带的两张图：图1 = 原网页截图（正确基准），"
    "图2 = 我们的原型渲染。\n"
    "只报告**图2 有、图1 没有**的渲染缺陷——也就是我们画错的地方。\n"
    "如果图1 里也是这个样子的（例如本来就是“暂无图片”占位图、本来就被页面边缘裁掉的"
    "文字），那不是缺陷，不要报。\n"
    "重点看：文字互相重叠、文字被截断/糊成一团、文字冲出盒子压到邻居、"
    "该有的图片/色块没画出来、颜色明显不对。\n"
    "只输出 JSON，不要解释、不要 markdown 代码块。\n"
    'Schema: {"defects": [{"type": "text_overlap|text_clipped|text_overflow|'
    'missing_image|color_mismatch|other", "detail": "用中文说清是哪段文字/哪个元素、'
    '错在哪", "where": "大致位置，例如 左侧书名列表第 2 项"}]}\n'
    "没有缺陷就输出 {\"defects\": []}。不要报告主观审美问题，也不要猜测画面外的东西。"
)


def band_bounds(height: int, ink_rows, band_height: int = BAND_HEIGHT,
                snap: int = SNAP) -> list[tuple[int, int]]:
    """把 [0, height) 切成若干条带；边界尽量落在"没有墨"的行上。

    ink_rows 是每行的深色像素数（长度 = height）。返回 [(y0, y1), ...]，首尾相接。
    """
    if height <= 0:
        return []
    if height <= band_height:
        return [(0, height)]
    bounds: list[tuple[int, int]] = []
    y0 = 0
    while y0 < height:
        y1 = min(y0 + band_height, height)
        if y1 < height:
            lo = max(y0 + 1, y1 - snap)
            hi = min(height - 1, y1 + snap)
            if hi >= lo:
                y1 = int(lo) + int(ink_rows[lo:hi + 1].argmin())
                y1 = max(y1, y0 + 1)
        bounds.append((y0, y1))
        y0 = y1
    return bounds


def _parse_defects(raw: str) -> list[dict]:
    """从模型回复里取缺陷列表；解析不了就原样记一条，别把整次复核带崩。"""
    from src.app.services.llm.llm_service import _extract_json_block
    try:
        data = json.loads(_extract_json_block(raw or ""))
    except Exception:
        return [{"type": "unparsed", "detail": (raw or "")[:300]}]
    items = data.get("defects") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return [{"type": "unparsed", "detail": (raw or "")[:300]}]
    out = []
    for item in items:
        if isinstance(item, dict):
            out.append({"type": str(item.get("type") or "other"),
                        "detail": str(item.get("detail") or ""),
                        "where": str(item.get("where") or "")})
    return out


def _band_messages(render_b64: str, y0: int, y1: int, width: int,
                   ref_b64: str | None = None) -> list[dict]:
    content: list[dict] = [
        {"type": "text",
         "text": ("这是 %d px 宽、y=%d~%d 那一条带（原分辨率，未缩放）。" % (width, y0, y1)
                  + ("图1 是原网页截图，图2 是我们的渲染。只报“图2 有、图1 没有”的缺陷。"
                     if ref_b64 else "请报告这条带里的渲染缺陷。"))},
    ]
    if ref_b64:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + ref_b64}})
    content.append({"type": "image_url",
                    "image_url": {"url": "data:image/png;base64," + render_b64}})
    return [{"role": "system", "content": _SYSTEM},
            {"role": "user", "content": content}]


def _encode(img) -> str:
    import cv2
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("条带 PNG 编码失败")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def review_render(png_path, cfg, *, ref_png=None,
                  band_height: int = BAND_HEIGHT,
                  max_bands: int = MAX_BANDS, snap: int = SNAP) -> dict:
    """把 png_path 切条带逐条问 VLM，返回 {size, bands, defects, ...}。

    ref_png 是同尺寸的采集截图：给了就按"图2 有、图1 没有"问，误报会少一个量级
    （原页本来就有的占位图/裁切不再被当成我们的错）。条带按**渲染图**的墨迹切，
    参考图照同一 y 区间裁。
    """
    import cv2

    from src.app.services.llm.llm_service import call_vlm

    img = cv2.imread(str(png_path))
    if img is None:
        raise FileNotFoundError("读不到渲染图：%s" % png_path)
    height, width = img.shape[:2]
    ref = cv2.imread(str(ref_png)) if ref_png else None
    if ref is not None and ref.shape[:2] != (height, width):
        ref = cv2.resize(ref, (width, height))

    ink_rows = (img.mean(axis=2) < _INK_GRAY).sum(axis=1)
    bounds = band_bounds(height, ink_rows, band_height, snap)[:max_bands]

    defects: list[dict] = []
    for index, (y0, y1) in enumerate(bounds):
        ref_b64 = _encode(ref[y0:y1]) if ref is not None else None
        raw = call_vlm(_band_messages(_encode(img[y0:y1]), y0, y1, width, ref_b64), cfg)
        for item in _parse_defects(raw):
            item["band"] = index
            item["y0"] = y0
            defects.append(item)

    logger.info("视觉复核：%d 条带，%d 条缺陷（参考图=%s）",
                len(bounds), len(defects), bool(ref is not None))
    return {"png": str(png_path), "ref": str(ref_png) if ref_png else None,
            "size": [width, height], "bands": len(bounds), "defects": defects}
