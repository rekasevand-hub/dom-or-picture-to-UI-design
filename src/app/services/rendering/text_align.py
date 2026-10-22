# -*- coding: utf-8 -*-
"""文本基线的像素级微调：把直出稿的文本行对齐到原截图的墨迹（只走 ±1px）。

`adapter_base.text_baseline_y` 用 `y + h/2 + 0.375em` 估浏览器基线。在 1331 节点的
真实页上，89 个可比文本元素里 79 个正好落在浏览器用的那一行；剩下的因为所在行高盒
不同 / 采集端整数化，会整体差 1px——文本是高频细笔画，差 1px 整行字的抗锯齿就全变
（这些元素区域 meanDiff 30~47 /255，拨正后 1~3）。

全局改公式救不了它们：三份采集一致显示，把基线整体 ±1px 会让 73/89 个元素从“正好”
变成“差 1px”，整图 1.375 → 3.404 /255（脚本 output/_p6_ab.py）。所以只能逐个元素判断，
判据就是**这次复刻的目标像素**（原截图）：

1. 调用方先按当前 DesignSpec 渲染一遍并栅格化（见 PreciseAgent._refine_text_baselines）；
2. 每个文本元素在自己框内试 -1 / 0 / +1 三种窗口偏移，取与截图最接近的那个；
3. 只有同时满足“比现状至少好 `min_gain`”且“优于现状 `min_ratio` 倍”才接受——不做
   更大的平移，也不动其它几何；截图里是空白的框直接跳过。

与 P4 像素底 / 人工框选同一条思路（这次复刻的目标像素就是截图），区别是只做 ±1px 的
整数对齐、不替换任何像素。位移写回 DesignSpec 的 `y`，SVG / Figma 等输出端都受益。
"""

from __future__ import annotations

import logging

from src.app import tuning

logger = logging.getLogger(__name__)


def _text_elements(design: dict) -> list[dict]:
    return [
        e
        for e in (design.get("elements") or [])
        if e.get("type") == "text" and (e.get("text") or "").strip()
    ]


def align_text_baselines(
    design: dict,
    reference_png,
    render_png,
    *,
    min_gain: float | None = None,
    min_ratio: float | None = None,
    blank_mean: float | None = None,
    device_scale_factor: int = 1,
) -> dict:
    """把文本元素整体平移 ±1px 对齐到 reference_png；就地改 design，返回统计。

    三个判据的默认值在 `src/app/tuning.py`（env 可覆盖）；显式传参优先。
    """
    if min_gain is None:
        min_gain = tuning.TEXT_ALIGN_MIN_GAIN
    if min_ratio is None:
        min_ratio = tuning.TEXT_ALIGN_MIN_RATIO
    if blank_mean is None:
        blank_mean = tuning.TEXT_ALIGN_BLANK_MEAN
    import cv2
    import numpy as np

    ref = cv2.imread(str(reference_png))
    cur = cv2.imread(str(render_png))
    if ref is None:
        raise FileNotFoundError(f"读不到参考截图：{reference_png}")
    if cur is None:
        raise FileNotFoundError(f"读不到渲染稿：{render_png}")
    if ref.shape != cur.shape:
        raise ValueError(f"参考截图与渲染稿尺寸不一致：{ref.shape} vs {cur.shape}")
    h, w = ref.shape[:2]
    scale = max(1, int(device_scale_factor))
    ref_f, cur_f = ref.astype(np.float32), cur.astype(np.float32)
    candidates = changed = 0
    gain_px = 0.0
    for el in _text_elements(design):
        try:
            x, y = int(el["x"]), int(el["y"])
            ew, eh = int(el["width"]), int(el["height"])
        except (KeyError, TypeError, ValueError):
            continue
        # 元素框外扩 margin 才允许试位移，避免碰到画布外的越界窗口
        sx, sy = x * scale, y * scale
        sw, sh = ew * scale, eh * scale
        margin = tuning.TEXT_ALIGN_MARGIN * scale
        if (
            sw < tuning.TEXT_ALIGN_MIN_BOX
            or sh < tuning.TEXT_ALIGN_MIN_BOX
            or sx < margin
            or sy < margin
        ):
            continue
        if sx + sw + margin > w or sy + sh + margin > h:
            continue
        box = ref_f[sy : sy + sh, sx : sx + sw]
        if box.mean() > blank_mean:  # 截图里这块空白，没有可对齐的墨迹
            continue
        scores = [
            (
                float(np.abs(box - cur_f[sy + dy : sy + dy + sh, sx : sx + sw]).mean()),
                dy,
            )
            for dy in (-scale, 0, scale)
        ]
        best, dy = min(scores)
        now = [s for s in scores if s[1] == 0][0][0]
        candidates += 1
        if dy and best < now - min_gain and best < now * min_ratio:
            # dy 是“窗口在渲染稿里的偏移”：渲染稿偏高 1px 时 dy=-1，元素要下移 1px
            el["y"] = y - dy // scale
            changed += 1
            gain_px += (now - best) * sw * sh
    stats = {
        "candidates": candidates,
        "changed": changed,
        "gain_px": round(gain_px, 1),
        "device_scale_factor": scale,
    }
    logger.info(
        "文本基线微调：%d/%d 个文本元素平移 1px（预计消 %d 像素·灰度差）",
        changed,
        candidates,
        int(gain_px),
    )
    return stats
