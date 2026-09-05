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
        """渲染完整的 DesignSpec。元素之间保持独立，不建立组合关系。

        绘制序规则（所有输出端共用，解决扁平顺序后画盖先画的问题）：
        1) overlay 浮层整体最后画，同层内 zIndex 升序；
        2) 非浮层内容按“被包含深度”先铺大背景/卡片，再画侧栏与正文，避免重复的
           全宽背景在文档序里排到侧栏后面把侧栏盖白；
        3) 白色叶子若与先前彩色衬底完全重合，或整体落在深色容器衬底上，视为重复
           chrome/幽灵按钮，跳过白底保留衬底色。
        """
        canvas = design.get("canvas", {})
        frame_id = self.create_frame({
            "name": "Screen",
            "x": 0,
            "y": 0,
            "width": canvas.get("width", 800),
            "height": canvas.get("height", 600),
        })

        elements = design.get("elements", [])
        rects = [self._element_rect(e) for e in elements]

        # 重复矩形（同节点被多次采集成容器）会互相抬高深度，导致本应铺底的白底
        # 工具栏排到彩色按钮之后。按唯一几何矩形统计“被谁覆盖”，消除该膨胀。
        seen_geom: set[tuple[int, int, int, int]] = set()
        unique_geoms = []
        for r in rects:
            if r is not None and r not in seen_geom:
                seen_geom.add(r)
                unique_geoms.append(r)

        def _depth(idx: int) -> int:
            r = rects[idx]
            if r is None:
                return 0
            return sum(1 for o in unique_geoms
                       if o != r and self._covers(o, r))

        ordered = sorted(
            enumerate(elements),
            key=lambda pair: (1 if pair[1].get("overlay") else 0,
                              int(pair[1].get("zIndex") or 0),
                              _depth(pair[0]), pair[0]))

        chrome: list[tuple[int, int, int, int, tuple[int, int, int]]] = []
        skipped_text_color: dict[int, str] = {}

        for _, el in ordered:
            el_type = el.get("type", "rectangle")
            style = el.get("style", {})
            spec = {**el, **style}
            idx = elements.index(el)

            if spec.get("imageBase64"):
                # 透明浮层容器按原截图像素回填（如 fixed wrapper 的整列底），
                # 以图片形式画，保证它盖在底下内容之上时观感与截图一致。
                self.create_image(spec, parent_id=frame_id)
            elif el_type in ("button", "input", "rectangle", "container"):
                r = self._element_rect(spec)
                backing = self._white_leaf_backing(r, spec, chrome)
                if backing is not None:
                    skipped_text_color[idx] = self._contrast_text_color(backing[4])
                else:
                    if r is not None and self._is_chrome_color(spec.get("fillColor")):
                        parsed = self._parse_hex_color(spec.get("fillColor"))
                        if parsed is not None:
                            chrome.append((*r, parsed))
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
                r = self._element_rect(spec)
                if r is not None and self._is_chrome_color(spec.get("fillColor")):
                    parsed = self._parse_hex_color(spec.get("fillColor"))
                    if parsed is not None:
                        chrome.append((*r, parsed))
                self.create_rectangle(spec, parent_id=frame_id)
            else:
                r = self._element_rect(spec)
                backing = self._white_leaf_backing(r, spec, chrome)
                if backing is not None:
                    skipped_text_color[idx] = self._contrast_text_color(backing[4])
                else:
                    if r is not None and self._is_chrome_color(spec.get("fillColor")):
                        parsed = self._parse_hex_color(spec.get("fillColor"))
                        if parsed is not None:
                            chrome.append((*r, parsed))
                    self.create_rectangle(spec, parent_id=frame_id)

            text_color = spec.get("textColor", "#000000")
            if idx in skipped_text_color:
                text_color = skipped_text_color[idx]
            if el_type != "text" and spec.get("text"):
                text_spec = {
                    "x": spec.get("x", 0) + 12,
                    "y": spec.get("y", 0) + (spec.get("height", 40) // 2) - (spec.get("fontSize", 16) // 2),
                    "text": spec.get("text"),
                    "textColor": text_color,
                    "fontSize": spec.get("fontSize", 16),
                }
                self.create_text(text_spec, parent_id=frame_id)

        self.flush()

    @staticmethod
    def _element_rect(spec: dict[str, Any]) -> tuple[int, int, int, int] | None:
        """取元素轴对齐矩形；宽高非正视为无效，返回 None。"""
        try:
            x, y = int(spec.get("x", 0)), int(spec.get("y", 0))
            w, h = int(spec.get("width", 0)), int(spec.get("height", 0))
        except (TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        return (x, y, w, h)

    @staticmethod
    def _covers(a: tuple[int, int, int, int], b: tuple[int, int, int, int],
                eps: int = 1) -> bool:
        """a 是否完全覆盖 b（含同边界，允许 1px 容差）。"""
        return (a[0] <= b[0] + eps and a[1] <= b[1] + eps
                and b[0] + b[2] <= a[0] + a[2] + eps
                and b[1] + b[3] <= a[1] + a[3] + eps)

    @staticmethod
    def _parse_hex_color(color: Any) -> tuple[int, int, int] | None:
        """解析 #RRGGBB / #RGB / rgb() / rgba()；失败返回 None。"""
        if not color:
            return None
        text = str(color).strip()
        if text.lower().startswith("rgb"):
            import re
            match = re.search(r"rgba?\(([^)]+)\)", text)
            if not match:
                return None
            parts = [p.strip() for p in match.group(1).split(",")]
            try:
                if len(parts) > 3 and float(parts[3]) < 0.05:
                    return None
                return (int(parts[0]), int(parts[1]), int(parts[2]))
            except (ValueError, IndexError):
                return None
        hex_color = text.lstrip("#")
        if len(hex_color) == 3:
            hex_color = "".join(ch * 2 for ch in hex_color)
        if len(hex_color) != 6:
            return None
        try:
            return (int(hex_color[0:2], 16), int(hex_color[2:4], 16),
                    int(hex_color[4:6], 16))
        except ValueError:
            return None

    @classmethod
    def _is_white_fill(cls, color: Any) -> bool:
        """近似纯白填充。"""
        rgb = cls._parse_hex_color(color)
        if rgb is None:
            return False
        return min(rgb) >= 242 and max(rgb) - min(rgb) <= 10

    @classmethod
    def _is_chrome_color(cls, color: Any) -> bool:
        """彩色/深色衬底色（非近白、非中性浅灰）。"""
        rgb = cls._parse_hex_color(color)
        if rgb is None:
            return False
        mx, mn = max(rgb), min(rgb)
        luma = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255.0
        sat = (mx - mn) / 255.0
        return luma < 0.40 or sat > 0.25

    @classmethod
    def _contrast_text_color(cls, rgb: tuple[int, int, int]) -> str:
        luma = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255.0
        return "#FFFFFF" if luma < 0.5 else "#000000"

    @classmethod
    def _white_leaf_backing(
        cls,
        rect: tuple[int, int, int, int] | None,
        spec: dict[str, Any],
        chrome: list[tuple[int, int, int, int, tuple[int, int, int]]],
    ) -> tuple[int, int, int, int, tuple[int, int, int]] | None:
        """白色叶子是否应透明化，返回其彩色衬底；无则返回 None。

        A) 与先前彩色衬底完全重合 → 同节点重复进料（容器+叶子），去白色重复层；
        B) 白色叶子整体落在深色容器衬底（luma<0.40，深色顶栏/侧栏）上 →
           透明图标按钮的白底幻影，去白底让衬底透出。
        """
        if rect is None or not cls._is_white_fill(spec.get("fillColor")):
            return None
        for x, y, w, h, rgb in chrome:
            if rgb is None:
                continue
            luma = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255.0
            same_area = (x, y, w, h) == rect
            inside_dark = luma < 0.40 and cls._covers((x, y, w, h), rect)
            if same_area or inside_dark:
                return (x, y, w, h, rgb)
        return None

    @staticmethod
    def _is_neutral_background(color: str) -> bool:
        """判断颜色是否接近纯白或透明，不需要额外绘制背景矩形。"""
        if not color or color.lower() in ("transparent", "none"):
            return True
        hex_color = color.lstrip("#").upper()
        if len(hex_color) == 3:
            hex_color = "".join(c * 2 for c in hex_color)
        return hex_color in ("FFFFFF", "FFFFFE", "FFFEFE", "FEFEFE", "FFFFFF")
