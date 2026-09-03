"""基于 OpenCV 的 UI 组件检测。"""
from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

from src.app.models.component import Component
from src.app.services.detection.component_classifier import classify_component
from src.app.services.detection.container_detector import detect_containers
from src.app.services.detection.red_box_detector import detect_red_boxes, red_box_to_component
from src.app.utils.color_utils import bgr_to_hex, dominant_color, shrink_roi
from src.app.utils.geometry_utils import box_overlap_ratio, snap_to_grid
from src.app.utils.image_utils import resize_frame

logger = logging.getLogger(__name__)


def _auto_canny(gray: np.ndarray) -> np.ndarray:
    """基于中位数的自适应 Canny 阈值。"""
    median = float(np.median(gray))
    lower = int(max(0, 0.66 * median))
    upper = int(min(255, 1.33 * median))
    return cv2.Canny(gray, lower, upper)


def _approx_shape(contour: np.ndarray, area: int, w: int, h: int) -> str:
    """粗略判断轮廓形状。"""
    peri = cv2.arcLength(contour, True)
    if peri < 1e-3:
        return "unknown"

    approx = cv2.approxPolyDP(contour, 0.04 * peri, True)
    vertices = len(approx)
    ar = w / max(h, 1)

    if vertices == 3:
        return "triangle"

    if vertices >= 8:
        (_, radius) = cv2.minEnclosingCircle(approx)
        circle_area = np.pi * (radius ** 2)
        if circle_area > 0 and area / circle_area > 0.75:
            return "circle"
        return "ellipse"

    if vertices == 4:
        if 0.85 < ar < 1.15:
            return "square"
        return "rectangle"

    return "polygon"


def preprocess_for_contours(frame: np.ndarray) -> np.ndarray:
    """
    预处理：缩放、灰度、双边滤波、阈值/边缘，得到用于 findContours 的二值图。
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.bilateralFilter(gray, 9, 75, 75)

    binary = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 5
    )

    edges = _auto_canny(blurred)
    combined = cv2.bitwise_or(binary, edges)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=1)

    return combined


def detect_components(
    frame: np.ndarray,
    resize_long_edge: int = 1280,
    min_area: int = 80,
    max_area_ratio: float = 0.95,
    red_box_enabled: bool = True,
    red_box_hue_low1: int = 0,
    red_box_hue_high1: int = 10,
    red_box_hue_low2: int = 170,
    red_box_hue_high2: int = 180,
    red_box_saturation_min: int = 100,
    red_box_value_min: int = 80,
    red_box_min_area: int = 500,
    red_box_max_fill_ratio: float = 0.5,
    red_box_shrink: int = 3,
    red_box_overlap_threshold: float = 0.5,
) -> list[Component]:
    """
    主入口：从 BGR 图片中提取候选组件（红框标注 + 轮廓检测 + 颜色分割容器）。
    """
    original_h, original_w = frame.shape[:2]

    red_boxes: list[tuple[int, int, int, int]] = []
    red_components: list[Component] = []
    if red_box_enabled:
        red_boxes = detect_red_boxes(
            frame,
            hue_low1=red_box_hue_low1,
            hue_high1=red_box_hue_high1,
            hue_low2=red_box_hue_low2,
            hue_high2=red_box_hue_high2,
            saturation_min=red_box_saturation_min,
            value_min=red_box_value_min,
            min_box_area=red_box_min_area,
            max_fill_ratio=red_box_max_fill_ratio,
            shrink=red_box_shrink,
        )
        red_id_start = 200000
        for i, bbox in enumerate(red_boxes):
            red_components.append(red_box_to_component(red_id_start + i, bbox, frame))

    analysis = resize_frame(frame, resize_long_edge)
    scale_x = original_w / analysis.shape[1]
    scale_y = original_h / analysis.shape[0]

    combined = preprocess_for_contours(analysis)
    contours, hierarchy = cv2.findContours(combined, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    if hierarchy is None:
        return []

    hierarchy = hierarchy[0]
    total_area = analysis.shape[0] * analysis.shape[1]
    candidates: list[Component] = []

    for idx, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if area < min_area or area / total_area > max_area_ratio:
            continue

        x, y, w, h = cv2.boundingRect(cnt)
        if w < 4 or h < 4:
            continue

        x0 = int(x * scale_x)
        y0 = int(y * scale_y)
        w0 = int(w * scale_x)
        h0 = int(h * scale_y)

        roi = frame[y0 : y0 + h0, x0 : x0 + w0]
        if roi.size == 0:
            continue

        color = dominant_color(shrink_roi(roi), k=3)
        comp = Component(
            id=idx,
            bbox=(x0, y0, w0, h0),
            area=int(area * scale_x * scale_y),
            shape=_approx_shape(cnt, area, w, h),
            color=color,
            color_hex=bgr_to_hex(color),
            confidence=0.6,
            meta={"source_bbox": [x0, y0, w0, h0]},
        )
        candidates.append(comp)

    containers = detect_containers(frame, resize_long_edge=resize_long_edge)

    all_components = candidates[:]
    for container in containers:
        overlap = False
        cx, cy, cw, ch = container.bbox
        for existing in candidates:
            ex, ey, ew, eh = existing.bbox
            inter_x = max(0, min(cx + cw, ex + ew) - max(cx, ex))
            inter_y = max(0, min(cy + ch, ey + eh) - max(cy, ey))
            inter_area = inter_x * inter_y
            container_area = cw * ch
            if container_area > 0 and inter_area / container_area > 0.85:
                overlap = True
                break
        if not overlap:
            all_components.append(container)

    if red_boxes:
        filtered_components = [
            c for c in all_components
            if box_overlap_ratio(c.bbox, red_boxes) < red_box_overlap_threshold
        ]
        if len(filtered_components) < len(all_components):
            logger.info(
                f"因与红框区域重叠，过滤掉 {len(all_components) - len(filtered_components)} 个组件"
            )
        all_components = filtered_components

    all_components.extend(red_components)

    all_components.sort(key=lambda c: c.area, reverse=True)
    id_map = {c.id: c for c in all_components}

    for comp in all_components:
        parent = None
        for other in all_components:
            if other.id == comp.id:
                continue
            ox, oy, ow, oh = other.bbox
            if ox <= comp.x and oy <= comp.y and ox + ow >= comp.x + comp.width and oy + oh >= comp.y + comp.height:
                if parent is None or parent.area > other.area:
                    parent = other
        if parent is not None:
            comp.parent_id = parent.id
            comp.level = parent.level + 1
            parent.children.append(comp.id)

    for comp in all_components:
        if comp.meta.get("source") == "red_box_annotation":
            comp.comp_type = "image"
            continue
        parent = id_map.get(comp.parent_id) if comp.parent_id is not None else None
        comp.comp_type = classify_component(comp, parent)

    for comp in all_components:
        x, y, w, h = comp.bbox
        comp.bbox = (
            snap_to_grid(x),
            snap_to_grid(y),
            max(snap_to_grid(w), 4),
            max(snap_to_grid(h), 4),
        )

    logger.info(f"检测到 {len(all_components)} 个候选组件")
    return all_components


def layout_rows(components: list[Component], y_tolerance: float = 0.25) -> list[list[int]]:
    """基于垂直中心点把组件划分成若干行（仅作为 LLM 参考，不用于成组）。"""
    if not components:
        return []

    rows: list[list[Component]] = []
    sorted_comps = sorted(components, key=lambda c: c.y)
    for comp in sorted_comps:
        cy = comp.y + comp.height / 2
        placed = False
        for row in rows:
            ref_cy = sum(c.y + c.height / 2 for c in row) / len(row)
            if abs(cy - ref_cy) / max(comp.height, 1) <= y_tolerance:
                row.append(comp)
                placed = True
                break
        if not placed:
            rows.append([comp])

    for row in rows:
        row.sort(key=lambda c: c.x)
    return [[c.id for c in row] for row in rows]
