"""截图中的候选 UI 组件模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class Component:
    """截图中的一个候选 UI 组件。"""

    id: int
    bbox: Tuple[int, int, int, int]  # (x, y, width, height)，原图坐标
    area: int
    level: int = 0
    parent_id: Optional[int] = None
    shape: str = "rectangle"
    color: Tuple[int, int, int] = (0, 0, 0)  # BGR
    color_hex: str = "#000000"
    text: str = ""
    comp_type: str = "unknown"
    confidence: float = 0.0
    children: list[int] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def x(self) -> int:
        return self.bbox[0]

    @property
    def y(self) -> int:
        return self.bbox[1]

    @property
    def width(self) -> int:
        return self.bbox[2]

    @property
    def height(self) -> int:
        return self.bbox[3]

    def to_dict(self) -> dict:
        """转为可序列化的字典，方便传给 LLM。"""
        return {
            "id": self.id,
            "type": self.comp_type,
            "shape": self.shape,
            "bbox": list(self.bbox),
            "area": self.area,
            "level": self.level,
            "parent_id": self.parent_id,
            "color": {"bgr": list(self.color), "hex": self.color_hex},
            "text": self.text,
            "confidence": self.confidence,
            "children": self.children,
            "meta": self.meta,
        }
