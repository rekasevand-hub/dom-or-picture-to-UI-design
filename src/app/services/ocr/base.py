"""OCR 引擎抽象接口。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

    from src.app.models.component import Component


class OcrEngine(ABC):
    """OCR 引擎抽象基类。"""

    @abstractmethod
    def recognize(self, roi: np.ndarray) -> str:
        """对 ROI 图像执行 OCR，返回识别到的文本。"""
        ...

    def run(self, frame: np.ndarray, components: list[Component]) -> None:
        """对候选组件批量执行 OCR，结果直接写回 comp.text。"""
        for comp in components:
            if comp.comp_type not in ("text", "button", "input", "unknown"):
                continue
            x, y, w, h = comp.bbox
            roi = frame[y : y + h, x : x + w]
            if roi.size == 0:
                continue
            original_text = comp.text
            text = self.recognize(roi).strip()
            if not text and original_text:
                text = original_text
            comp.text = text
