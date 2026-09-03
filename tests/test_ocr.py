"""纯函数单元测试：OCR 辅助函数。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app.services.ocr.easyocr_engine import _is_long_meaningless


def test_is_long_meaningless_true() -> None:
    text = "skabcdefghijklmnopqrstuvwxyz1234"
    assert _is_long_meaningless(text, width=320, height=24) is True


def test_is_long_meaningless_chinese_false() -> None:
    text = "这是一段很长很长的中文字符串没有任何空格"
    assert _is_long_meaningless(text, width=320, height=24) is False


def test_is_long_meaningless_short_false() -> None:
    text = "shorttext"
    assert _is_long_meaningless(text, width=320, height=24) is False


def test_is_long_meaningless_not_thin_false() -> None:
    text = "abcdefghijklmnopqrstuvwxyz"
    assert _is_long_meaningless(text, width=50, height=24) is False


if __name__ == "__main__":
    test_is_long_meaningless_true()
    test_is_long_meaningless_chinese_false()
    test_is_long_meaningless_short_false()
    test_is_long_meaningless_not_thin_false()
    print("all ocr helper tests passed")
