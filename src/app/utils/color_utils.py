"""颜色相关工具函数。"""
from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np


def bgr_to_hex(bgr: Tuple[int, int, int]) -> str:
    """把 BGR 元组转为 #RRGGBB 字符串。"""
    return "#{:02x}{:02x}{:02x}".format(bgr[2], bgr[1], bgr[0])


def shrink_roi(roi: np.ndarray, margin: int = 2) -> np.ndarray:
    """去掉边缘像素再计算颜色，避免抗锯齿/边框影响。"""
    h, w = roi.shape[:2]
    if h <= 2 * margin or w <= 2 * margin:
        return roi
    return roi[margin : h - margin, margin : w - margin]


def dominant_color(roi: np.ndarray, k: int = 3) -> Tuple[int, int, int]:
    """使用 K-Means 提取 ROI 的主导颜色（BGR）。"""
    if roi.size == 0:
        return (0, 0, 0)

    small = cv2.resize(roi, (64, 64), interpolation=cv2.INTER_AREA)
    data = small.reshape((-1, 3)).astype(np.float32)

    # 样本数不足时直接返回均值
    if len(data) < k:
        mean = np.mean(data, axis=0).astype(np.uint8)
        return tuple(int(v) for v in mean)

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers = cv2.kmeans(data, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten())
    dominant = centers[np.argmax(counts)].astype(np.uint8)
    return tuple(int(v) for v in dominant)
