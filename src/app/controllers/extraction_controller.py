"""特征提取控制器：协调检测与 OCR。"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

    from src.app.models.component import Component
    from src.config import Config

from src.app.services.detection import detect_components, detect_components_with_omniparser
from src.app.services.detection.omniparser_client import OmniParserClient
from src.app.services.ocr import extract_text_with_ocr

logger = logging.getLogger(__name__)


class ExtractionController:
    """负责把输入图片转成 Component 列表。"""

    def __init__(self, config: "Config") -> None:
        self.config = config

    def _build_opencv_kwargs(self) -> dict:
        return {
            "resize_long_edge": self.config.cv_resize_long_edge,
            "min_area": self.config.cv_min_component_area,
            "max_area_ratio": self.config.cv_max_component_area_ratio,
        }

    def _build_red_box_kwargs(self) -> dict:
        return {
            "red_box_enabled": self.config.red_box_enabled,
            "red_box_hue_low1": self.config.red_box_hue_low1,
            "red_box_hue_high1": self.config.red_box_hue_high1,
            "red_box_hue_low2": self.config.red_box_hue_low2,
            "red_box_hue_high2": self.config.red_box_hue_high2,
            "red_box_saturation_min": self.config.red_box_saturation_min,
            "red_box_value_min": self.config.red_box_value_min,
            "red_box_min_area": self.config.red_box_min_area,
            "red_box_max_fill_ratio": self.config.red_box_max_fill_ratio,
            "red_box_shrink": self.config.red_box_shrink,
            "red_box_overlap_threshold": self.config.red_box_overlap_threshold,
        }

    def extract(self, frame: np.ndarray, ocr_engine: str) -> list[Component]:
        """检测组件并执行 OCR。"""
        opencv_kwargs = self._build_opencv_kwargs()
        red_box_kwargs = self._build_red_box_kwargs()

        if self.config.omniparser_enabled:
            client = OmniParserClient.from_config(self.config)
            try:
                components = detect_components_with_omniparser(frame, client, **red_box_kwargs)
            except Exception as exc:
                if self.config.omniparser_fallback:
                    logger.warning("OmniParser 调用失败，回退到 OpenCV 提取: %s", exc)
                    components = detect_components(frame, **opencv_kwargs, **red_box_kwargs)
                else:
                    raise
        else:
            components = detect_components(frame, **opencv_kwargs, **red_box_kwargs)

        extract_text_with_ocr(frame, components, ocr_engine, self.config)
        return components
