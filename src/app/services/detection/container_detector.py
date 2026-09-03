"""大容器/卡片/面板背景检测。"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from src.app.models.component import Component
from src.app.utils.color_utils import bgr_to_hex
from src.app.utils.image_utils import resize_frame

logger = logging.getLogger(__name__)


def detect_containers(
    frame: np.ndarray,
    resize_long_edge: int = 640,
    k: int = 8,
    min_area: int = 5000,
    max_area_ratio: float = 0.98,
) -> list[Component]:
    """
    基于颜色分割识别大容器/卡片/面板。

    思路：
    1. 缩小图片降低计算量
    2. K-Means 颜色量化，把相近颜色聚成 k 类
    3. 对每一类主色生成 mask
    4. 形态学闭运算连接断裂区域、填充文字洞
    5. findContours 找大块连通区域作为容器候选
    6. 映射回原图坐标返回
    """
    original_h, original_w = frame.shape[:2]
    analysis = resize_frame(frame, resize_long_edge)
    scale_x = original_w / analysis.shape[1]
    scale_y = original_h / analysis.shape[0]

    data = analysis.reshape((-1, 3)).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers = cv2.kmeans(data, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    quantized = centers[labels.flatten()].reshape(analysis.shape).astype(np.uint8)

    total_area = analysis.shape[0] * analysis.shape[1]
    candidates: list[Component] = []
    next_id = 10000

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    unique_colors = np.unique(quantized.reshape(-1, 3), axis=0)

    for color in unique_colors:
        color_u8 = color.astype(np.uint8)
        mask = cv2.inRange(quantized, color_u8, color_u8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area / total_area > max_area_ratio:
                continue

            x, y, w, h = cv2.boundingRect(cnt)
            if w < 20 or h < 20:
                continue

            x0 = int(x * scale_x)
            y0 = int(y * scale_y)
            w0 = int(w * scale_x)
            h0 = int(h * scale_y)

            roi = frame[y0 : y0 + h0, x0 : x0 + w0]
            if roi.size == 0:
                continue

            color_bgr = tuple(int(v) for v in color)
            comp = Component(
                id=next_id,
                bbox=(x0, y0, w0, h0),
                area=int(area * scale_x * scale_y),
                shape="rectangle",
                color=color_bgr,
                color_hex=bgr_to_hex(color_bgr),
                comp_type="container",
                confidence=0.7,
                meta={"source_bbox": [x0, y0, w0, h0]},
            )
            candidates.append(comp)
            next_id += 1

    logger.info(f"颜色分割检测到 {len(candidates)} 个容器候选")
    return candidates
