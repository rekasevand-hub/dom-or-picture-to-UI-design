"""OCR 服务入口：根据配置创建对应引擎并执行识别。"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.app.services.ocr.base import OcrEngine
from src.app.services.ocr.easyocr_engine import EasyOcrEngine
from src.app.services.ocr.tesseract_engine import TesseractEngine
from src.config import Config

if TYPE_CHECKING:
    import numpy as np

    from src.app.models.component import Component

logger = logging.getLogger(__name__)


def create_ocr_engine(engine: str, config: Config) -> OcrEngine | None:
    """根据引擎名称创建 OCR 引擎实例。"""
    if engine == "none":
        return None
    if engine == "easyocr":
        try:
            return EasyOcrEngine()
        except ImportError:
            logger.warning("easyocr 未安装，跳过 OCR")
            return None
    if engine == "tesseract":
        try:
            return TesseractEngine(
                lang=config.ocr_lang or "chi_sim+eng",
                tesseract_cmd=config.tesseract_cmd,
            )
        except ImportError:
            logger.warning("pytesseract 未安装，跳过 OCR")
            return None
    logger.warning(f"未知 OCR 引擎: {engine}")
    return None


def extract_text_with_ocr(
    frame: np.ndarray,
    components: list[Component],
    engine_name: str,
    config: Config,
) -> None:
    """对组件执行 OCR，结果直接写回 comp.text。"""
    engine = create_ocr_engine(engine_name, config)
    if engine is None:
        return
    engine.run(frame, components)
