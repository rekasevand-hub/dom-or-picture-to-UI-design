# -*- coding: utf-8 -*-
"""结构提供器基类与上下文。"""
from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class ProviderContext:
    image_path: str
    image_w: int
    image_h: int
    route: str = ""
    output_dir: str = ""
    dom_path: str | None = None
    url: str | None = None


class BaseProvider(ABC):
    name: str = ""

    @abstractmethod
    def run(self, ctx: ProviderContext) -> dict: ...
