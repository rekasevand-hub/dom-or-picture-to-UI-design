"""OmniParser HTTP 服务客户端及组件映射。"""
from __future__ import annotations

import base64
import logging
from typing import Any

import cv2
import numpy as np
import requests

from src.app.models.component import Component
from src.app.services.detection.red_box_detector import (
    detect_red_boxes,
    red_box_to_component,
)
from src.app.utils.color_utils import bgr_to_hex, dominant_color, shrink_roi
from src.app.utils.geometry_utils import box_overlap_ratio, snap_to_grid
from src.config import Config

logger = logging.getLogger(__name__)


class OmniParserError(Exception):
    """调用 OmniParser 服务时发生的错误。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OmniParserClient:
    """调用本地 OmniParser HTTP 服务。"""

    def __init__(
        self,
        base_url: str,
        timeout: int = 120,
        box_threshold: float = 0.05,
        iou_threshold: float = 0.7,
        use_paddleocr: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.box_threshold = box_threshold
        self.iou_threshold = iou_threshold
        self.use_paddleocr = use_paddleocr

    @classmethod
    def from_config(cls, config: Config) -> "OmniParserClient":
        return cls(
            base_url=config.omniparser_url,
            timeout=config.omniparser_timeout,
            box_threshold=config.omniparser_box_threshold,
            iou_threshold=config.omniparser_iou_threshold,
            use_paddleocr=config.omniparser_use_paddleocr,
        )

    @staticmethod
    def encode_frame(frame: np.ndarray) -> str:
        """把 OpenCV BGR ndarray 编码为 PNG base64。"""
        success, encoded = cv2.imencode(".png", frame)
        if not success:
            raise OmniParserError("无法将图片编码为 PNG")
        return base64.b64encode(encoded.tobytes()).decode("utf-8")

    def health(self) -> dict[str, Any]:
        """健康检查。"""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=5,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise OmniParserError(f"健康检查失败: {exc}") from exc

    def parse(self, frame: np.ndarray) -> list[dict]:
        """发送图片到 OmniParser 服务，返回原始 parsed_content_list。"""
        image_b64 = self.encode_frame(frame)
        payload = {
            "base64_image": image_b64,
            "box_threshold": self.box_threshold,
            "iou_threshold": self.iou_threshold,
            "use_paddleocr": self.use_paddleocr,
        }

        try:
            response = requests.post(
                f"{self.base_url}/parse",
                json=payload,
                timeout=self.timeout,
            )
        except requests.ConnectionError as exc:
            raise OmniParserError(
                f"无法连接到 OmniParser 服务 ({self.base_url})，请确认服务已启动"
            ) from exc
        except requests.Timeout as exc:
            raise OmniParserError(f"OmniParser 服务调用超时（>{self.timeout}s）") from exc
        except requests.RequestException as exc:
            raise OmniParserError(f"OmniParser 请求失败: {exc}") from exc

        if response.status_code != 200:
            raise OmniParserError(
                f"OmniParser 服务返回错误: HTTP {response.status_code}, {response.text}",
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise OmniParserError("OmniParser 返回非 JSON 响应") from exc

        parsed_content_list = data.get("parsed_content_list")
        if parsed_content_list is None:
            raise OmniParserError("OmniParser 响应缺少 parsed_content_list 字段")

        logger.info(
            "OmniParser 返回 %d 个元素，耗时 %.3fs",
            len(parsed_content_list),
            data.get("latency", 0),
        )
        return parsed_content_list


def detect_components_with_omniparser(
    frame: np.ndarray,
    client: OmniParserClient,
    min_size: int = 4,
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
    调用 OmniParser 本地服务解析截图，返回项目统一的 Component 列表。

    若开启红框检测，用户用红色矩形框选的区域会先被识别为 image 组件，
    并在送给 OmniParser 前被填充为白色背景，避免 OmniParser 把红框内部
    的细碎内容拆成多个元素。
    """
    img_h, img_w = frame.shape[:2]

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
        logger.info(f"OmniParser 模式检测到 {len(red_boxes)} 个红框标注区域")

    frame_for_omni = frame.copy()
    for x, y, w, h in red_boxes:
        x = max(0, x)
        y = max(0, y)
        w = min(w, img_w - x)
        h = min(h, img_h - y)
        if w > 0 and h > 0:
            frame_for_omni[y : y + h, x : x + w] = (255, 255, 255)

    parsed_list = client.parse(frame_for_omni)
    if not parsed_list:
        logger.warning("OmniParser 未返回任何元素")
        return red_components

    components: list[Component] = []

    for idx, item in enumerate(parsed_list):
        bbox_norm = item.get("bbox")
        if not bbox_norm or len(bbox_norm) != 4:
            logger.warning("OmniParser 元素缺少合法 bbox: %s", item)
            continue

        x1 = int(bbox_norm[0] * img_w)
        y1 = int(bbox_norm[1] * img_h)
        x2 = int(bbox_norm[2] * img_w)
        y2 = int(bbox_norm[3] * img_h)

        x = min(x1, x2)
        y = min(y1, y2)
        w = abs(x2 - x1)
        h = abs(y2 - y1)

        if w < min_size or h < min_size:
            continue

        x = snap_to_grid(x)
        y = snap_to_grid(y)
        w = max(snap_to_grid(w), min_size)
        h = max(snap_to_grid(h), min_size)

        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)

        roi = frame[y : y + h, x : x + w]
        color = dominant_color(shrink_roi(roi), k=3) if roi.size > 0 else (0, 0, 0)

        item_type = item.get("type", "")
        content = str(item.get("content", "")).strip()

        if item_type == "text":
            comp_type = "text"
        elif item_type == "icon":
            ar = w / max(h, 1)
            if max(w, h) < 80 and 0.75 < ar < 1.33:
                comp_type = "avatar"
            elif ar > 4 or ar < 0.25:
                comp_type = "input"
            else:
                comp_type = "button"
        else:
            comp_type = "unknown"

        comp = Component(
            id=idx,
            bbox=(x, y, w, h),
            area=w * h,
            shape="rectangle",
            color=color,
            color_hex=bgr_to_hex(color),
            text=content if comp_type == "text" else "",
            comp_type=comp_type,
            confidence=float(item.get("interactivity", False)),
            meta={
                "source": "omniparser",
                "omniparser_type": item_type,
                "omniparser_content": content,
                "interactivity": item.get("interactivity"),
                "source_id": item.get("source"),
                "source_bbox": [x, y, w, h],
            },
        )
        components.append(comp)

    if red_boxes:
        filtered_components = [
            c
            for c in components
            if box_overlap_ratio(c.bbox, red_boxes) < red_box_overlap_threshold
        ]
        if len(filtered_components) < len(components):
            logger.info(
                f"因与红框区域重叠，过滤掉 {len(components) - len(filtered_components)} 个 OmniParser 组件"
            )
        components = filtered_components

    components.extend(red_components)

    logger.info(f"OmniParser 解析出 {len(components)} 个有效组件")
    return components
