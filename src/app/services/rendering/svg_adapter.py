"""SVG 兜底适配器：把 DesignSpec 渲染成 .svg 文件，用于快速验证。"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from src.app.services.rendering.adapter_base import PrototypeAdapter

logger = logging.getLogger(__name__)


class SVGMockAdapter(PrototypeAdapter):
    """SVG 兜底适配器。"""

    def __init__(self, output_path: str | Path):
        self.output_path = Path(output_path)
        self.elements: list[ET.Element] = []
        self.canvas_width = 800
        self.canvas_height = 600

    def connect(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def disconnect(self) -> None:
        pass

    def create_frame(self, spec: dict[str, Any]) -> str | None:
        self.canvas_width = int(spec.get("width", 800))
        self.canvas_height = int(spec.get("height", 600))
        return None

    def _get_color(self, spec: dict[str, Any], key: str, default: str = "#000000") -> str:
        return spec.get(key, default)

    def create_rectangle(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        x = int(spec.get("x", 0))
        y = int(spec.get("y", 0))
        width = int(spec.get("width", 100))
        height = int(spec.get("height", 40))
        fill = self._get_color(spec, "fillColor", "#cccccc")
        stroke = self._get_color(spec, "borderColor", "none")
        stroke_width = int(spec.get("borderWidth", 0))
        radius = int(spec.get("borderRadius", 0))

        rect = ET.Element("rect")
        rect.set("x", str(x))
        rect.set("y", str(y))
        rect.set("width", str(width))
        rect.set("height", str(height))
        rect.set("fill", fill)
        rect.set("rx", str(radius))
        rect.set("ry", str(radius))
        if stroke_width > 0 and stroke != "none":
            rect.set("stroke", stroke)
            rect.set("stroke-width", str(stroke_width))
        self.elements.append(rect)
        return None

    def create_ellipse(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        x = int(spec.get("x", 0))
        y = int(spec.get("y", 0))
        width = int(spec.get("width", 100))
        height = int(spec.get("height", 100))
        fill = self._get_color(spec, "fillColor", "#cccccc")

        ellipse = ET.Element("ellipse")
        ellipse.set("cx", str(x + width // 2))
        ellipse.set("cy", str(y + height // 2))
        ellipse.set("rx", str(width // 2))
        ellipse.set("ry", str(height // 2))
        ellipse.set("fill", fill)
        self.elements.append(ellipse)
        return None

    def create_image(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        x = int(spec.get("x", 0))
        y = int(spec.get("y", 0))
        width = int(spec.get("width", 100))
        height = int(spec.get("height", 100))
        image_b64 = str(spec.get("imageBase64", ""))
        is_avatar = bool(spec.get("isAvatar", False))

        if not image_b64:
            return self.create_rectangle(spec, parent_id=parent_id)

        image_el = ET.Element("image")
        image_el.set("x", str(x))
        image_el.set("y", str(y))
        image_el.set("width", str(width))
        image_el.set("height", str(height))
        image_el.set("href", f"data:image/png;base64,{image_b64}")
        if is_avatar:
            clip_id = f"avatar-clip-{x}-{y}"
            defs = ET.Element("defs")
            clip_path = ET.SubElement(defs, "clipPath")
            clip_path.set("id", clip_id)
            circle = ET.SubElement(clip_path, "circle")
            circle.set("cx", str(x + width // 2))
            circle.set("cy", str(y + height // 2))
            circle.set("r", str(min(width, height) // 2))
            self.elements.append(defs)
            image_el.set("clip-path", f"url(#{clip_id})")
        self.elements.append(image_el)
        return None

    def create_text(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        x = int(spec.get("x", 0))
        y = int(spec.get("y", 0))
        text = str(spec.get("text", ""))
        fill = self._get_color(spec, "textColor", "#000000")
        font_size = int(spec.get("fontSize", 16))

        if not text:
            return None

        text_el = ET.Element("text")
        text_el.set("x", str(x))
        text_el.set("y", str(y + font_size))
        text_el.set("fill", fill)
        text_el.set("font-size", str(font_size))
        text_el.set("font-family", "sans-serif")
        text_el.text = text
        self.elements.append(text_el)
        return None

    def flush(self) -> None:
        svg = ET.Element("svg")
        svg.set("xmlns", "http://www.w3.org/2000/svg")
        svg.set("width", str(self.canvas_width))
        svg.set("height", str(self.canvas_height))
        svg.set("viewBox", f"0 0 {self.canvas_width} {self.canvas_height}")

        for el in self.elements:
            svg.append(el)

        tree = ET.ElementTree(svg)
        tree.write(self.output_path, encoding="utf-8", xml_declaration=True)
        logger.info(f"SVG 已保存: {self.output_path}")
