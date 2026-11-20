"""The date rule is a calendar check, not a string rewrite.

EasyOCR reads the trailing 日 of a date as 8 often enough that some repair is
needed, but the tempting rule ("ends with 8 means 日") corrupts "10月8" — a real
date.  The only repair allowed is a day number that cannot exist, so these tests
pin both directions: what gets restored and what must be left alone.
"""

from __future__ import annotations

import pytest

from src.app.services.structure.physical_perception import _normalise_ocr_text


@pytest.mark.parametrize(
    ("drawn", "expected"),
    [
        ("11月148", "11月14日"),  # 14 日被读成 148：越界，还原
        ("11月40", "11月4日"),    # 40 号不存在：还原
        ("11月408", "11月40日"),  # 越界即还原，即使 40 号本身也不存在
        ("12月318", "12月31日"),
    ],
)
def test_impossible_day_is_restored(drawn: str, expected: str) -> None:
    assert _normalise_ocr_text(drawn) == expected


@pytest.mark.parametrize(
    "drawn",
    [
        "10月8",     # 合法日期：一个字都不动
        "11月18",    # 合法
        "11月30",    # 合法边界
        "11月31",    # 合法边界
        "11月3",     # 合法
        # 末位是 B 但日号合法：Y=14 不越界，就不许改。宁可漏一个误读，
        # 也不要把 "11月14B" 这种本来就对不了的字改成别的。
        "11月14B",
        "11月4B",
        "2026年11月",  # 没有日
        "价格 8",
    ],
)
def test_legal_values_are_never_touched(drawn: str) -> None:
    assert _normalise_ocr_text(drawn) == drawn
