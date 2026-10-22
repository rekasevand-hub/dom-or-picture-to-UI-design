# -*- coding: utf-8 -*-
"""结构提供器基类与上下文。"""
from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Any


@dataclass
class ProviderContext:
    image_path: str
    image_w: int
    image_h: int
    route: str = ""
    output_dir: str = ""
    dom_path: str | None = None
    url: str | None = None
    # 站点 profile 覆盖（有就用它，不按 url 去查）。给"离线闭环搜索"用：
    # 同一个页面要连续试多组阈值，不能每次都去改磁盘上的 profile 文件。
    profile: Any = None


class BaseProvider(ABC):
    name: str = ""

    @abstractmethod
    def run(self, ctx: ProviderContext) -> dict: ...
