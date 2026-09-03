"""渲染控制器：把 DesignSpec 输出到目标原型工具。"""
from __future__ import annotations

from typing import Any

from src.app.services.rendering import build_adapter
from src.config import Config


class RenderingController:
    """负责把 DesignSpec 渲染到具体原型工具。"""

    def __init__(self, config: Config) -> None:
        self.config = config

    def render(self, design: dict[str, Any], tool: str) -> None:
        adapter = build_adapter(tool, self.config)
        adapter.connect()
        try:
            adapter.render_design(design)
        finally:
            adapter.disconnect()
