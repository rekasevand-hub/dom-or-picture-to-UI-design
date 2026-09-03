"""Tesseract OCR 引擎实现。"""
from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from src.app.services.ocr.base import OcrEngine

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)


class TesseractEngine(OcrEngine):
    """Tesseract-OCR 引擎封装。"""

    def __init__(self, lang: str = "chi_sim+eng", tesseract_cmd: str | None = None) -> None:
        self.lang = lang
        self.tesseract_cmd = tesseract_cmd
        self._pytesseract = None

    def _get_engine(self):
        if self._pytesseract is None:
            self._pytesseract = importlib.import_module("pytesseract")
            if self.tesseract_cmd:
                self._pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
        return self._pytesseract

    def recognize(self, roi: np.ndarray) -> str:
        pytesseract = self._get_engine()
        return pytesseract.image_to_string(roi, lang=self.lang)
