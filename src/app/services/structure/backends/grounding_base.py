# -*- coding: utf-8 -*-
"""Grounding 后端抽象。"""
from __future__ import annotations

from abc import ABC, abstractmethod


class GroundingBackend(ABC):
    @abstractmethod
    def ground(self, image_path: str, image_w: int, image_h: int) -> dict: ...
