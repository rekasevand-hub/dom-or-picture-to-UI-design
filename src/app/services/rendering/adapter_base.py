"""原型工具适配器抽象基类与通用渲染逻辑。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PrototypeAdapter(ABC):
    """原型工具适配器抽象基类。"""

    @abstractmethod
    def connect(self) -> None:
        """建立连接或初始化资源。"""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接或释放资源。"""
        ...

    @abstractmethod
    def create_frame(self, spec: dict[str, Any]) -> str | None:
        """创建画板/容器，返回节点 id。"""
        ...

    @abstractmethod
    def create_rectangle(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        """创建矩形/按钮/输入框等元素。"""
        ...

    @abstractmethod
    def create_ellipse(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        """创建椭圆/圆形元素。"""
        ...

    @abstractmethod
    def create_text(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        """创建文本元素。"""
        ...

    @abstractmethod
    def create_image(self, spec: dict[str, Any], parent_id: str | None = None) -> str | None:
        """创建图片元素（用真实图像填充）。"""
        ...

    @abstractmethod
    def flush(self) -> None:
        """提交/保存最终输出。"""
        ...

    def render_design(self, design: dict[str, Any]) -> None:
        """渲染完整的 DesignSpec。元素之间保持独立，不建立组合关系。"""
        canvas = design.get("canvas", {})
        frame_id = self.create_frame({
            "name": "Screen",
            "x": 0,
            "y": 0,
            "width": canvas.get("width", 800),
            "height": canvas.get("height", 600),
        })

        for el in design.get("elements", []):
            el_type = el.get("type", "rectangle")
            style = el.get("style", {})
            spec = {**el, **style}

            if el_type in ("button", "input", "rectangle", "container"):
                self.create_rectangle(spec, parent_id=frame_id)
            elif el_type in ("image", "avatar"):
                self.create_image(spec, parent_id=frame_id)
            elif el_type == "circle":
                self.create_ellipse(spec, parent_id=frame_id)
            elif el_type == "text":
                fill_color = spec.get("fillColor")
                if fill_color and not self._is_neutral_background(fill_color):
                    bg_spec = {
                        "x": spec.get("x", 0),
                        "y": spec.get("y", 0),
                        "width": spec.get("width", 100),
                        "height": spec.get("height", 40),
                        "fillColor": fill_color,
                        "borderColor": spec.get("borderColor"),
                        "borderWidth": spec.get("borderWidth", 0),
                        "borderRadius": spec.get("borderRadius", 0),
                    }
                    self.create_rectangle(bg_spec, parent_id=frame_id)
                self.create_text(spec, parent_id=frame_id)
            elif el_type == "divider":
                self.create_rectangle(spec, parent_id=frame_id)
            else:
                self.create_rectangle(spec, parent_id=frame_id)

            if el_type != "text" and spec.get("text"):
                text_spec = {
                    "x": spec.get("x", 0) + 12,
                    "y": spec.get("y", 0) + (spec.get("height", 40) // 2) - (spec.get("fontSize", 16) // 2),
                    "text": spec.get("text"),
                    "textColor": spec.get("textColor", "#000000"),
                    "fontSize": spec.get("fontSize", 16),
                }
                self.create_text(text_spec, parent_id=frame_id)

        self.flush()

    @staticmethod
    def _is_neutral_background(color: str) -> bool:
        """判断颜色是否接近纯白或透明，不需要额外绘制背景矩形。"""
        if not color or color.lower() in ("transparent", "none"):
            return True
        hex_color = color.lstrip("#").upper()
        if len(hex_color) == 3:
            hex_color = "".join(c * 2 for c in hex_color)
        return hex_color in ("FFFFFF", "FFFFFE", "FFFEFE", "FEFEFE", "FFFFFF")
