"""EasyOCR 引擎实现。"""
from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from src.app.services.ocr.base import OcrEngine

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# 缓存 EasyOCR Reader，避免重复初始化
_EASYOCR_READER = None


def _is_long_meaningless(text: str, width: int, height: int) -> bool:
    """判断一段识别结果是否需要字符级拆分重试。"""
    if not text or height <= 0:
        return False
    if width / height < 3:
        return False
    if len(text) < 16:
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return False
    separators = sum(1 for c in text if c.isspace() or c in ".,-_/|\\:;")
    return separators / len(text) < 0.1


def _split_recognize(reader, roi: np.ndarray, width: int, height: int) -> str:
    """把长条形 ROI 按估算字符宽度切分后分别识别，再合并结果。"""
    if height <= 0 or width <= 0:
        return ""
    char_w = max(int(height * 0.7), 4)
    pieces: list[str] = []
    step = max(char_w - 1, 1)
    for start in range(0, width, step):
        end = min(start + char_w, width)
        if end - start < 4:
            continue
        piece_roi = roi[:, start:end]
        result = reader.readtext(piece_roi, detail=0)
        pieces.extend(result)
    return "".join(pieces).strip()


class EasyOcrEngine(OcrEngine):
    """EasyOCR 多语言 OCR 引擎。"""

    def __init__(self, languages: list[str] | None = None, gpu: bool = False) -> None:
        self.languages = languages or ["ch_sim", "en"]
        self.gpu = gpu
        self._reader = None

    def _get_reader(self):
        global _EASYOCR_READER
        if _EASYOCR_READER is None:
            easyocr = importlib.import_module("easyocr")
            _EASYOCR_READER = easyocr.Reader(self.languages, gpu=self.gpu)
        return _EASYOCR_READER

    def recognize(self, roi: np.ndarray) -> str:
        reader = self._get_reader()
        result = reader.readtext(roi, detail=0)
        text = " ".join(result).strip()

        h, w = roi.shape[:2]
        if text and _is_long_meaningless(text, w, h):
            split_text = _split_recognize(reader, roi, w, h)
            if split_text:
                return split_text
        return text
