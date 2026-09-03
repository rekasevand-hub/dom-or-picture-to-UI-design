"""基于几何与颜色特征对组件做粗分类。"""
from __future__ import annotations

from typing import Optional

from src.app.models.component import Component


def classify_component(comp: Component, parent: Optional[Component]) -> str:
    """基于几何与颜色做粗分类，LLM 会在此基础上二次校正。"""
    ar = comp.width / max(comp.height, 1)
    area = comp.area

    if comp.text.strip():
        if comp.width < 300 and comp.height < 80:
            return "text"

    if comp.shape in ("circle", "ellipse"):
        return "avatar" if max(comp.width, comp.height) < 80 else "image"

    if ar > 6 and comp.height < 10:
        return "divider"

    if parent is not None and area > 0.7 * parent.area:
        return "container"

    b, g, r = comp.color
    saturation = max(r, g, b) - min(r, g, b)
    if comp.shape in ("rectangle", "square") and 1.5 < ar < 6 and saturation > 40:
        return "button"

    if comp.shape == "rectangle" and ar > 3:
        return "input"

    return "unknown"
