"""原型工具适配器工厂。"""
from __future__ import annotations

from pathlib import Path

from src.app.services.rendering.axure_adapter import AxureRPAdapter
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter
from src.app.services.rendering.html_adapter import HTMLAdapter
from src.app.services.rendering.js_design_adapter import JSDesignAdapter
from src.app.services.rendering.mocking_bot_adapter import MockingBotAdapter
from src.app.services.rendering.svg_adapter import SVGMockAdapter
from src.config import Config


def build_adapter(tool: str, config: Config) -> "PrototypeAdapter":
    """根据配置创建对应的原型工具适配器。"""
    if tool == "figma":
        return FigmaBridgeAdapter(config.figma_bridge_url)
    if tool == "jsdesign":
        return JSDesignAdapter(config.jsdesign_api_base, config.jsdesign_token)
    if tool == "mockingbot":
        return MockingBotAdapter(config.mockingbot_api_base, config.mockingbot_token)
    if tool == "svg":
        output = config.output_dir / "prototype.svg"
        return SVGMockAdapter(output, font_stack=config.svg_font_stack)
    if tool == "axure":
        # v2：从零生成 `.rp`（不再需要骨架 / 清单；文档级模板由写入层自带）。
        return AxureRPAdapter(config.output_dir / "prototype.rp")
    if tool == "html":
        return HTMLAdapter(config.output_dir)
    raise ValueError(f"未知的原型工具: {tool}")
