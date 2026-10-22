# -*- coding: utf-8 -*-
"""像素差分指标：直出稿 vs 采集截图的 **唯一定义点**。

验收脚本（`output/_live_metrics.py` / `output/_samples_now.py` /
`scripts/figma_replay.py`）与在线闭环搜索（`structure/profile_search.py`）用的是同一套
口径——否则"搜索说变好了、验收说没变"这种事迟早发生。

口径（与历来验收一致，不要随手改）：
- **整图**：三通道绝对差的均值 /255。
- **笔画**：截图里 grayscale < 200 的像素（"有墨的地方"）上取 R 通道差的均值——
  文字是高频细笔画，整体均值会被大片同色区域稀释。
- **>30**：`max(通道差) > 30` 的像素占比（肉眼可见的错位/串色）。
- **纪律像素**：墨迹像素总数（分母，用来判断两次比较是否同一口径）。

分区：`default_bands(w, h)` 给的是**这个业务页面**的分带（顶栏/查询区/表格/表格右缘/
分页/其余），沿用历史验收的分法，便于横向对比。
"""
from __future__ import annotations

from typing import Iterable, Sequence

Band = tuple[str, int, int, int, int]
INK_THRESHOLD = 200      # grayscale 低于此值算"有墨"
BAD_DELTA = 30           # 单像素最大通道差超过此值算"看得见的错"


def default_bands(width: int, height: int) -> list[Band]:
    """历史验收用的分带（x1 = 画布右边）。"""
    return [("顶栏", 0, 60, 0, width),
            ("查询区", 60, 190, 0, width),
            ("表格", 190, 690, 0, width),
            ("表格右缘", 190, 690, 1300, width),
            ("分页", 690, 780, 0, width),
            ("其余", 780, height, 0, width)]


def compare_images(ref, render) -> dict:
    """两张 BGR 图（同尺寸）的差分报告。

    **参数顺序有语义**：`ref` 必须是**采集截图** —— 「笔画」（`ink_mean`）的分母（`ink` 掩膜 = 它上面
    grayscale < 200 的像素）取自 `ref`，只有截图才代表"真实的墨迹在哪里"。反着传会得到另一个
    `ink_mean`（2026-10-15 实测同一对图 `14.452` vs `11.221`），而 `mean` / `over30_pct` 不受影响。
    """
    import cv2
    import numpy as np

    diff = np.abs(render.astype(np.int16) - ref.astype(np.int16))
    gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    ink = gray < INK_THRESHOLD
    return {
        "mean": float(diff.mean()),
        "ink_mean": float(diff[..., 0][ink].mean()) if ink.any() else 0.0,
        "over30_pct": float((diff.max(axis=2) > BAD_DELTA).mean() * 100),
        "ink_px": int(ink.sum()),
        "diff": diff,
    }


def region_scores(diff, bands: Iterable[Band], *, clamp: bool = False):
    """逐带取 `max(通道差)` 的均值；返回 [(name, y0, y1, x0, x1, score)]。

    clamp=True 时把 y1 夹到图高（`figma_replay` 的口径），y0 超出则跳过该带。
    """
    h = diff.shape[0]
    out = []
    for name, y0, y1, x0, x1 in bands:
        if clamp:
            if y0 >= h:
                continue
            y1 = min(y1, h)
        out.append((name, y0, y1, x0, x1,
                    float(diff.max(axis=2)[y0:y1, x0:x1].mean())))
    return out


def score_key(report: dict) -> tuple[float, float, float]:
    """排序键：先整图、再笔画、再 >30（越小越好）。"""
    return (report["mean"], report["ink_mean"], report["over30_pct"])
