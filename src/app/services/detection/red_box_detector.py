"""红框标注区域检测：用户用红色矩形框选的图片区域。"""
from __future__ import annotations

import logging
from typing import Tuple

import cv2
import numpy as np

from src.app.models.component import Component
from src.app.utils.color_utils import bgr_to_hex, dominant_color, shrink_roi

logger = logging.getLogger(__name__)


def detect_red_boxes(
    frame: np.ndarray,
    hue_low1: int = 0,
    hue_high1: int = 10,
    hue_low2: int = 170,
    hue_high2: int = 180,
    saturation_min: int = 100,
    value_min: int = 80,
    min_box_area: int = 500,
    max_fill_ratio: float = 0.5,
    shrink: int = 3,
) -> list[tuple[int, int, int, int]]:
    """
    检测用户用红色矩形框选的区域。

    红色在 HSV 色相环上跨 0°/180° 边界，因此需要合并两段色相区间。
    返回 [(x, y, w, h), ...]，坐标为原图像素坐标。
    """
    if frame.size == 0:
        return []

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    img_h, img_w = frame.shape[:2]

    lower1 = np.array([hue_low1, saturation_min, value_min], dtype=np.uint8)
    upper1 = np.array([hue_high1, 255, 255], dtype=np.uint8)
    mask1 = cv2.inRange(hsv, lower1, upper1)

    lower2 = np.array([hue_low2, saturation_min, value_min], dtype=np.uint8)
    upper2 = np.array([hue_high2, 255, 255], dtype=np.uint8)
    mask2 = cv2.inRange(hsv, lower2, upper2)

    red_mask = cv2.bitwise_or(mask1, mask2)

    # 轻度闭运算：只连接真正断裂的红框线条
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes: list[tuple[int, int, int, int]] = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_box_area:
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < 20 or bh < 20:
            continue
        if bw > 0.95 * img_w and bh > 0.95 * img_h:
            continue

        peri = cv2.arcLength(cnt, True)
        if peri < 1e-3:
            continue
        approx = cv2.approxPolyDP(cnt, 0.05 * peri, True)
        if not (4 <= len(approx) <= 8):
            logger.debug("跳过非矩形红色区域 (vertices=%d, bbox=%dx%d)", len(approx), bw, bh)
            continue

        red_pixels = cv2.countNonZero(red_mask[y : y + bh, x : x + bw])
        bbox_area = bw * bh
        fill_ratio = red_pixels / bbox_area if bbox_area > 0 else 1.0
        if fill_ratio > max_fill_ratio:
            logger.debug("跳过实心红色区域 (fill_ratio=%.2f, bbox=%dx%d)", fill_ratio, bw, bh)
            continue

        x_in = min(x + shrink, x + bw // 2)
        y_in = min(y + shrink, y + bh // 2)
        w_in = max(bw - 2 * shrink, 4)
        h_in = max(bh - 2 * shrink, 4)

        x_in = max(0, min(x_in, img_w - 1))
        y_in = max(0, min(y_in, img_h - 1))
        w_in = min(w_in, img_w - x_in)
        h_in = min(h_in, img_h - y_in)

        boxes.append((x_in, y_in, w_in, h_in))

    logger.info(f"检测到 {len(boxes)} 个红框标注区域")
    return boxes


def red_box_to_component(
    idx: int,
    bbox: tuple[int, int, int, int],
    frame: np.ndarray,
) -> Component:
    """把一个红框区域转为 image 类型 Component。"""
    x, y, w, h = bbox
    roi = frame[y : y + h, x : x + w]
    color = dominant_color(shrink_roi(roi), k=3) if roi.size > 0 else (0, 0, 0)
    return Component(
        id=idx,
        bbox=bbox,
        area=w * h,
        shape="rectangle",
        color=color,
        color_hex=bgr_to_hex(color),
        comp_type="image",
        confidence=1.0,
        meta={"source": "red_box_annotation", "source_bbox": list(bbox)},
    )
