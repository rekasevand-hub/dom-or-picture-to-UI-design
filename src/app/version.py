# -*- coding: utf-8 -*-
"""项目版本号：单一定义在仓库根的 `VERSION`。

产物目录的 `manifest.json` 会带上它，回头可以直接确认某个产物是哪一版跑出来的。
1.1.0 冻结发版的交付范围、验收结果与已知限制见 `HANDOFF_2026-10-17_release.md`。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

# src/app/version.py -> 仓库根
_ROOT = Path(__file__).resolve().parents[2]
_FALLBACK = "0.0.0"


@lru_cache(maxsize=1)
def app_version() -> str:
    """读仓库根的 `VERSION`；缺失/读坏时回退 `0.0.0`（版本号读不到不能拖垮主链路）。"""
    try:
        text = (_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return _FALLBACK
    return text or _FALLBACK
