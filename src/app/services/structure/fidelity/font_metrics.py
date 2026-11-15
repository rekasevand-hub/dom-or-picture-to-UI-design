"""真实字宽：把 `1.0 / 0.55` 的经验系数换成目标字体的 advance width。

画布上每一段字都会有"渲染出来多宽"的问题：去重时要判断两段字会不会互相压到，
缩字时要判断这一行会不会串到邻列。原来的估法是"CJK 算 1 em、其他算 0.55 em"，
对中文标题勉强够，对拉丁文与数字偏差能到 30%——Gmail 的日期列与 Worklog 的窄列
就是这么偏出去的。

这里直接问字体：`PIL.ImageFont.getlength` 给出这段字在目标字号下的真实宽度，
按字符缓存（一页上的不同字符通常只有几百个）。字体取渲染端真正会用的那一个
（Noto Sans SC，缺字时退到 Arial / DejaVu）；一个都找不到时退回内置系数表，
保证离线也能跑。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

#: 实测用的字号。取得够大，四舍五入误差摊到每个字符上就看不见了。
PROBE_SIZE = 200

#: 没有字体文件时的兜底系数（em）。按 Noto Sans SC 与 Arial 的中位数取整。
FALLBACK_RATIOS = {
    "cjk": 1.0,
    "upper": 0.70,
    "lower": 0.56,
    "digit": 0.56,
    "space": 0.28,
    "punct": 0.34,
}

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/NotoSansSC-VF.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _font_path() -> str:
    override = os.environ.get("TEXT_METRIC_FONT", "")
    if override and Path(override).is_file():
        return override
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return ""


@lru_cache(maxsize=1)
def _font():
    path = _font_path()
    if not path:
        return None
    try:
        from PIL import ImageFont

        return ImageFont.truetype(path, PROBE_SIZE)
    except Exception:  # pragma: no cover - broken font file
        return None


def _fallback_ratio(char: str) -> float:
    if ord(char) > 0x2E80:
        return FALLBACK_RATIOS["cjk"]
    if char.isspace():
        return FALLBACK_RATIOS["space"]
    if char.isdigit():
        return FALLBACK_RATIOS["digit"]
    if char.isupper():
        return FALLBACK_RATIOS["upper"]
    if char.islower():
        return FALLBACK_RATIOS["lower"]
    return FALLBACK_RATIOS["punct"]


@lru_cache(maxsize=8192)
def char_ratio(char: str) -> float:
    """Advance width of one character, in ems, from the real font."""
    font = _font()
    if font is None:
        return _fallback_ratio(char)
    try:
        return float(font.getlength(char)) / PROBE_SIZE
    except Exception:  # pragma: no cover - glyph the font cannot measure
        return _fallback_ratio(char)


def text_width(text: str, font_size: float) -> float:
    """Width the renderer will paint for this string at this size, in pixels."""
    if not text or font_size <= 0:
        return 0.0
    return float(font_size) * sum(char_ratio(char) for char in text)


def em_width(text: str) -> float:
    """The same measurement in ems: handy when comparing against a box."""
    return sum(char_ratio(char) for char in text)


def probe_table(sample: str = "广东特拓MOM 2026-11-08 ¥1,280.00") -> dict[str, float]:
    """Per-character advances for the classes the estimator cares about."""
    rows = {}
    for char in sample:
        if char in rows:
            continue
        rows[char] = round(char_ratio(char), 3)
    return rows
