"""UI 自动还原 Agent：串联图像加载、特征提取、LLM/直接渲染、原型输出。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from src.app.controllers.extraction_controller import ExtractionController
from src.app.controllers.rendering_controller import RenderingController
from src.app.services.llm import build_prompt, call_vision_llm, parse_design_json
from src.app.utils.image_utils import draw_debug_overlay, encode_image_base64, load_image, save_image
from src.config import Config

logger = logging.getLogger(__name__)


def _save_json(data: dict | list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _hex_to_brightness(hex_color: str) -> float:
    """计算 #RRGGBB 的亮度（0-255）。"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    if len(hex_color) != 6:
        return 255.0
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _components_to_design(components: list, frame: np.ndarray, img_w: int, img_h: int) -> dict[str, Any]:
    """直接把检测到的 Component 列表转成 DesignSpec，跳过 LLM。"""
    elements: list[dict[str, Any]] = []
    for comp in components:
        x, y, w, h = comp.bbox
        comp_type = comp.comp_type
        fill_color = comp.color_hex or "#CCCCCC"
        text_color = "#FFFFFF" if _hex_to_brightness(fill_color) < 128 else "#000000"
        font_size = max(10, min(int(h * 0.45), 32))
        border_radius = 4 if comp_type in ("button", "input") else 0

        element: dict[str, Any] = {
            "id": str(comp.id),
            "type": comp_type if comp_type in ("text", "button", "input", "image", "avatar", "divider", "container") else "rectangle",
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "text": comp.text or "",
            "style": {
                "fillColor": fill_color,
                "textColor": text_color,
                "fontSize": font_size,
                "fontWeight": "normal",
                "borderRadius": border_radius,
                "borderWidth": 0,
                "borderColor": "#000000",
            },
        }

        if comp_type in ("image", "avatar") or comp.meta.get("source") == "red_box_annotation":
            roi = frame[y : y + h, x : x + w]
            if roi.size > 0:
                element["imageBase64"] = encode_image_base64(roi)
                element["isAvatar"] = comp_type == "avatar"

        elements.append(element)

    return {"canvas": {"width": img_w, "height": img_h}, "elements": elements}


class ReconstructAgent:
    """UI 自动还原工作流编排器。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.extraction_controller = ExtractionController(config)
        self.rendering_controller = RenderingController(config)

    def run(self, image_path: str, tool: str, ocr_engine: str, direct_render: bool) -> None:
        logger.info(f"加载图片: {image_path}")
        frame = load_image(image_path)
        img_h, img_w = frame.shape[:2]
        self.config.ensure_dirs()
        save_image(frame, self.config.output_dir / "01_original.png")

        logger.info("提取视觉特征...")
        components = self.extraction_controller.extract(frame, ocr_engine)

        overlay = draw_debug_overlay(frame, components)
        save_image(overlay, self.config.output_dir / "02_overlay.png")

        from src.app.services.detection.component_detector import layout_rows
        features = {
            "image_width": img_w,
            "image_height": img_h,
            "component_count": len(components),
            "components": [c.to_dict() for c in components],
            "rows": layout_rows(components),
        }
        _save_json(features, self.config.output_dir / "03_features.json")

        if direct_render:
            logger.info("直接渲染模式：跳过 LLM...")
            design = _components_to_design(components, frame, img_w, img_h)
            _save_json({"raw": "direct-render"}, self.config.output_dir / "04_llm_raw.json")
        else:
            logger.info("调用 LLM...")
            image_b64 = encode_image_base64(frame)
            messages = build_prompt(image_b64, features, img_w, img_h)
            raw_output = call_vision_llm(messages, self.config)
            _save_json({"raw": raw_output}, self.config.output_dir / "04_llm_raw.json")
            design = parse_design_json(raw_output)

        _save_json(design, self.config.output_dir / "05_design.json")

        logger.info(f"渲染到原型工具: {tool}")
        self.rendering_controller.render(design, tool)
        logger.info("完成")
