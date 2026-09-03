"""DesignSpec 相关模型。"""
from __future__ import annotations

from typing import Any


class DesignSpec:
    """原型工具的输入规范。"""

    def __init__(self, canvas: dict[str, int], elements: list[dict[str, Any]]):
        self.canvas = canvas
        self.elements = elements

    def to_dict(self) -> dict[str, Any]:
        return {"canvas": self.canvas, "elements": self.elements}
