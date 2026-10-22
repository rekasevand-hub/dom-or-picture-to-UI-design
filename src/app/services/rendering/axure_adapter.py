# -*- coding: utf-8 -*-
"""Axure RP 8 适配器（v2）：`DesignSpec` -> 从零生成的 `.rp`。

**与 v1 的差别**：v1 是「骨架 + 按值改写几何」——模板用完就丢元素，文字 / 图片 /
圆角根本写不进去（见 `归档文档 axure_adapter.md`）。v2 直接走 `axure/` 写入层**从零生成**：
一个元素一个控件，想发多少发多少。方案见 `归档文档 axure_rp8_plan.md`，格式权威
`归档文档 axure_rp8_format.md`（§11 全是真机实测）。

| `DesignSpec` | 落成的控件 | 备注 |
|---|---|---|
| `create_frame` | `doc.Frame`（= 一个 Axure 页面） | 页名 / 画板尺寸原样下发 |
| `rectangle` / `container` / `divider` | `doc.Rect` | 底色 / 描边 / 圆角 |
| `button` | `doc.Button`（库样式 `Button` + 子面板标题） | 底色 / 描边 / 圆角 / 字体；标题写进按钮的子 `RichTextPanel`，位置优先按 `textBox` 落（§11.8 / §11.15） |
| `input` | `doc.TextField`（`Axure:DiagramObject:TextBox`） | 底色 / 字体 / 颜色；发布成 `<input>`（§11.8） |
| `text` | `doc.Text`（宿主形状 + 子 `RichTextPanel`） | 字体 / 字号 / 字重 / 颜色 / 对齐 / 底色 / 行高，配方见 format §11.5 |
| `image` / `avatar` | `doc.Image`（`ImageBox`） | 图片字节**原样**进 `IMAGE(27)` 槽，配方见 format §11.6 |
| `circle` | `doc.Ellipse`（`VectorShape` + `Shape=15`） | 4 点圆路径，配方见 format §11.7 |

两条口径都是真机实测反推的，不是猜的：

* 颜色缺失一律发**透明**（`0x00FFFFFF`）+ 描边宽度 0。Axure 内置的 `Box 1` 库样式默认是
  「白底 + 1px 灰边」，不发就会给每个元素描一圈灰边（发布出来
  `border-color:rgba(121,121,121,1)`）。
* 字体名只取 CSS 字体栈的**第一个**族名（Axure 的 `FONT_NAME` 是单个字体名）。
* 按钮 / 输入框的**文字内嵌在控件自己身上**（按钮的子面板 / 输入框的 `TextBlock`），
  基类紧接着发的那次 `create_text` 会被吃掉 —— 否则同一个标题会画两遍、
  而且按钮在 Axure 里是"没有标题的按钮 + 一个盖在上面的文本框"两个控件。

与 Figma / SVG 链路完全独立：元素只由基类 `render_design` 按绘制序喂进来，本类不碰顺序。
"""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any

from src.app.services.rendering import text_wrap
from src.app.services.rendering.adapter_base import PrototypeAdapter
from src.app.services.rendering.axure import doc, thumbnail, writer

logger = logging.getLogger(__name__)

# 颜色的编码是 **0xAARRGGBB**（真机核对：0xFF00FF00 -> `rgba(0,255,0,1)`）；
# `0x00FFFFFF` 是 Axure 自己写的「透明」（alpha=0 时 RGB 无所谓，照抄它）。
TRANSPARENT = 0x00FFFFFF
_HEX = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_ALIGN = {"left": 0, "start": 0, "center": 1, "centre": 1,
          "right": 2, "end": 2, "justify": 0}


def axure_color(value: Any) -> int | None:
    """DesignSpec 的颜色 -> `0xAARRGGBB`；空 / `transparent` / `none` / 不认得 -> None。

    `#RGB` / `#RRGGBB` 补成不透明，`#RRGGBBAA` 与 `rgba()` 的 alpha 照抄进 AA。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("transparent", "none"):
        return None
    if text.lower().startswith("rgb"):
        match = re.search(r"rgba?\(([^)]+)\)", text)
        if not match:
            return None
        parts = [p.strip() for p in match.group(1).split(",")]
        try:
            r, g, b = (max(0, min(255, int(float(p)))) for p in parts[:3])
            alpha = 1.0 if len(parts) < 4 else max(0.0, min(1.0, float(parts[3])))
        except (TypeError, ValueError):
            return None
        return (round(alpha * 255) << 24) | (r << 16) | (g << 8) | b
    if not _HEX.match(text):
        return None
    digits = text.lstrip("#")
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits) + "FF"
    elif len(digits) == 6:
        digits += "FF"
    return int(digits[6:8] + digits[0:6], 16)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _opt_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# CSS 的 `font-weight` 是关键字或数字，Axure 的 `FONT_WEIGHT` 只认数字：
# 直接 `float()` 会抛错并静默退回 400 —— `style_utils.css_font_weight` 把字重
# 归一成 `normal` / `bold` 关键字，于是**粗体整批丢失**（真机：38 个 bold 元素的
# 墨量只有参考图的 0.69，而同页 116 个 normal 元素是 1.00，见 plan §9.18）。
_WEIGHT_KEYWORDS = {"normal": 400, "bold": 700, "bolder": 700, "lighter": 300}


def _weight(value: Any, default: int = 400) -> int:
    """CSS `font-weight`（关键字或数字）-> Axure 的整数权重。"""
    if value is None or value == "":
        return default
    key = str(value).strip().lower()
    if key in _WEIGHT_KEYWORDS:
        return _WEIGHT_KEYWORDS[key]
    try:
        return int(float(key))
    except (TypeError, ValueError):
        return default


def _align(value: Any) -> int:
    """CSS `text-align` -> 形状 `P9`（0 左 / 1 中 / 2 右，真机实测）。"""
    return _ALIGN.get(str(value or "").strip().lower(), 0)


def _first_family(value: Any) -> str:
    """CSS 字体栈 -> 第一个族名（去引号）；空栈给 `Arial`。"""
    if not value:
        return "Arial"
    return str(value).split(",")[0].strip().strip("'\"") or "Arial"


def _label(spec: dict[str, Any]) -> str:
    """控件名 -> Axure 对象名（发布成 `<!-- 名字 (Rectangle) -->` + `data-label`）。"""
    return " ".join(str(spec.get("name") or spec.get("label") or "").split())


def _nowrap(spec: dict[str, Any]) -> bool:
    """IR 的 `white-space:nowrap` -> Axure 的「不折行」。

    真实页面上这类元素**永远不折行**（宽度不够就溢出）；Axure 的文字面板默认按面板宽
    折行（发布成 `word-wrap:break-word`），盒子零余量时就会早折一个字符（真宽 172.16px
    落在 172px 的盒子里，dushu 的书名就是这么折的）。控件自己的 `AutoFitWidth=True`
    让发布端把面板发成 `white-space:nowrap`（真机 A/B 见 `归档文档 axure_rp8_plan.md` §9.11）。
    """
    return str(spec.get("whiteSpace") or "").strip().lower() == "nowrap"


def _no_reflow(spec: dict[str, Any]) -> bool:
    """这段文字**不许发布端再折一遍**：IR 说了 nowrap，或盒子就是这一行撑出来的。

    折行决策在 IR 侧（`text_wrap` 按估算字宽算断点），发布端只管落地。但 Axure 的
    文字面板默认按**面板宽**折行（`word-wrap:break-word`），而 IR 的盒宽是四舍五入
    后的整数：行内元素 / 自动宽控件的盒宽本来就等于行宽，**零余量**，发布端字体度量
    宽一丁点就早折一个字符（`<i>01</i>` 的 20px 盒子里放 20.016px 的字，真机 A/B
    见 `归档文档 axure_rp8_plan.md` §9.11 与本轮）。两个来源用的是同一个开关：控件自己
    的 `AutoFitWidth` 让发布端把面板发成 `white-space:nowrap`，面板宽仍是盒宽。

    零余量那条由 `text_wrap.box_is_own_line` 判：有余量的盒子发布端本来也折不错，
    那条路径逐字节不变。
    """
    return _nowrap(spec) or text_wrap.box_is_own_line(spec)


def _pin_breaks(spec: dict[str, Any], text: str) -> str:
    """带**字距**的折行元素：把 IR 算好的断点钉成硬换行。

    Axure RP 8 的文档模型里没有字距这个槽：`Platform.dll` 里那串 `PropList` 枚举名
    （`PaddingAll` / `LineSpacing` / `MouseOver` …）查不到 `LetterSpacing`，整个安装
    目录也搜不到 `letter-spacing`（唯一那处命中的是 `Platform.dll` 的 SVG **导入**
    属性表，不落盘）。发布端于是按自己的字宽模型折行，而 CSS 的 `letter-spacing` 是
    每个字符都多占 1px：dushu 的电子书简介 fs=12 / 字距 1px，一行的 16 个字差 16px，
    发布出来**多塞两个字**，第二行起全错（真机见 `归档文档 axure_rp8_plan.md` §9.19）。
    IR 侧的断点已经算进这份余量（`text_wrap`），这里只剩"照抄"。

    只有带字距的元素会被钉（dushu 首页 4 个）：没有字距时发布端本来就折得对，钉死
    反而会把 `text_wrap` 估算里那点误差变成硬伤。
    """
    lines = spec.get("lines")
    if not lines or text_wrap.letter_spacing_of(spec) == 0.0:
        return text
    return "\n".join(str(line) for line in lines)


def _text_width(text: str, size: float) -> float:
    """一行文字的宽度粗估（px）：CJK 按 1em、其余按 0.55em，再留 5% 余量。

    只在基类没给宽度时用（控件内的文字）—— 目的是**别折行**，不是排版精确。
    """
    units = sum(1.0 if ord(ch) > 0x2E7F else 0.55 for ch in text) or 1.0
    return round(max(size, units * size) * 1.05 + 2.0, 3)


def _round_to_even(value: float) -> float:
    """发布端 `_roundToEven`（`resources/scripts/prototypePost.js`）的等价实现。

    Axure 的发布脚本在 `_setTextAlignment` 里用它算文字面板的 `top`，而它是**字符串
    实现**：整数原样返回；小数部分恰好是单个 `5` 时按 half-even（整部首为偶就取它、
    为奇就 +1，**负数也 +1**）；其余走 `Math.round`。我们只喂 `(高 - 行盒高) / 2`，
    值域就是整数或半数，两条分支覆盖全部情形：

    | `(H - lh)/2` | JS 结果 | 备注 |
    |---|---|---|
    | `5` | `5` | 整数 |
    | `-5.5` | `-4` | `parts[0] = "-5"`（截断到零）-> 奇 -> +1 |
    | `-13.5` | `-12` | 同上；实测 `u236` 发布出来就是 `-12px` |
    | `0.5` | `0` | 偶 -> 取它；实测 `u52` 是 `0px` |
    | `-0.5` | `0` | `-0 % 2 == 0` -> 取它（`(-0) + 'px'` 发布成 `0px`） |
    """
    if value == int(value):
        return float(int(value))
    if abs(abs(value) % 1.0 - 0.5) < 1e-9:
        whole = math.trunc(value)
        return float(whole) if whole % 2 == 0 else float(whole + 1)
    return float(math.floor(value + 0.5))


def _panel_text_top(height: float, line_height: float) -> float:
    """发布端给 `#uN_text` 算的 `top`（`_setTextAlignment` 的 `middle` 分支）。

    控件发的是 `P10 = 1`（垂直居中），面板的上下内边距都是 0，于是
    `top = _roundToEven((控件高 - 行盒高) / 2)`；单行时行盒高就是行高。
    """
    return _round_to_even((height - line_height) / 2.0)


def _aligned_panel_height(spec: dict[str, Any], top: float, height: float) -> float:
    """按采集到的「第一行行框」把控件高改成**落字位置对齐**的高度。

    浏览器把行盒排在自己的位置上；Axure 发布端却把面板在控件里垂直居中，落点于是
    变成 `控件顶 + 控件高/2`。控件高 = IR 的元素盒高，而真实行盒（行高 43 的 `i` 只有
    16px 高）几乎都不是盒高，整批文字因此差 1px（真机：27 个元素，见
    `归档文档 axure_rp8_plan.md` §9.21）。

    解出「要让面板 top 等于目标落点」所需的控件高即可 —— `top` 关于控件高单调：

        target = floor(行盒中心 - 控件顶 - 行高/2 + 0.5)   # .5 一律进位
        H'     = 行高 + 2 * target                        # 于是 top' == target

    只在**单行**（`textEmLines == 1`）上做：多行的行盒是各行并集，「第一行的中心」
    与 `H/2` 不是同一个量。缺 `textEmBox`（老产物 / 别的采集）、行高不是整数 px
    （pt<->px 往返会掉零头）、或者落点本来就对时**原样返回** —— 不改的产物逐字节不变。

    只动**发给 Axure 的控件高**：IR 的 `height` 一个字都不能改，同一份 IR 还喂着
    SVG / Figma 两条出口（它们的落字基准是 `adapter_base.text_baseline_y`）。
    """
    box = spec.get("textEmBox")
    if not box or _number(spec.get("textEmLines"), 0) != 1:
        return height
    line_height = _opt_number(spec.get("lineHeight"))
    if line_height is None or line_height <= 0:
        return height
    if abs(line_height - round(line_height)) > 1e-6:
        return height
    try:
        _x, em_top, _w, em_h = (float(v) for v in box)
    except (TypeError, ValueError):
        return height
    target = math.floor(em_top + em_h / 2.0 - top - line_height / 2.0 + 0.5)
    if _panel_text_top(height, line_height) == target:
        return height
    new_height = line_height + 2.0 * target
    return new_height if new_height >= 1.0 else height


def _caption_inset(spec: dict[str, Any], x: float, width: float,
                   ) -> tuple[float, bool] | None:
    """按钮标题相对控件左缘的偏移与「是否需要 nowrap」；不能接管时给 None。

    `Button` 的标题是控件的子 `RichTextPanel`。**面板几何不是杠杆**：发布端
    `_setTextAlignment` 会用控件的 `paddingLeft/Right` 重算
    `#uN_text{left,width}`，把 `ContainedLocation` 覆盖掉（真机 A/B 见 plan §9.23）。
    所以这里回 `dx = textBox.x - 控件.x`，由调用方写成 `P_PADDING_LEFT`，再把
    标题设为左对齐。

    `textBox` 是 DOM 里文字自己的行框（`Range.getClientRects`），已经含了图标、
    间距、内边距造成的位移：dushu 的 `a.more "查看更多"` 是 54px，导航
    `a "我的账户"` 是 30px。只在**单行**（`textEmLines == 1`）上做；多行的
    `textBox` 是各行并集，左对齐会把短行全部推到并集左缘。行框落在控件外
    （负 `text-indent` / 溢出）或本来没偏（`dx <= 0.5`）时返回 None，产物逐字节不变。

    第二个返回值 `tight`：内边距会把面板宽同时缩成 `控件宽 - dx`，如果
    `控件宽 - dx < max(行宽, 估宽) + 1`，发布端字体度量差一点就会早折一个字
    （plan §9.11）。这种紧盒不能放弃（否则图标继续压字），也不能发 `AutoFitWidth`
    （真机实测会把控件宽撑成 `dx + 文字宽`）。调用方改为 `PADDING_RIGHT = -dx`：
    发布端算出的面板宽仍是 `控件宽 - dx - (-dx) = 控件宽`，落点左移但可用宽度不缩。
    """
    box = spec.get("textBox")
    if not box or _number(spec.get("textEmLines"), 0) != 1:
        return None
    try:
        text_x, _text_y, text_w, _text_h = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    dx = text_x - x
    if text_w <= 0 or dx <= 0.5:
        return None
    if text_x < x - 1.0 or text_x + text_w > x + width + 1.0:
        return None
    text = str(spec.get("text") or "")
    size = _number(spec.get("fontSize"), 12.0) or 12.0
    needed = max(text_w, _text_width(text, size)) + 1.0
    return dx, width - dx < needed


class AxureRPAdapter(PrototypeAdapter):
    """把 `DesignSpec` 写成一个可编辑的 Axure RP 8 `.rp`（从零生成）。"""

    # Axure 的裁剪要真容器（动态面板），本版不做；扁平处理与 SVG 一致。
    supports_clip_frames = False
    # 多页：`design["pages"]` 的第 i 页 -> `.rp` 的第 i 个页面（站点树顺序 = 数组顺序）。
    supports_pages = True
    # 本版真正下发的 DesignSpec 字段；其余（opacity / shadow …）忽略。`letterSpacing`
    # 也不下发（RP8 没有这个槽，见 `_pin_breaks`）—— 它只用来决定折行断点。
    SUPPORTED_FIELDS = ("x", "y", "width", "height", "fillColor", "borderColor",
                        "borderWidth", "borderRadius", "text", "textColor",
                        "fontSize", "fontWeight", "fontFamily", "lineHeight",
                        "textAlign", "whiteSpace", "imageBase64")

    def __init__(self, output_path: str | Path,
                 template_path: str | Path | None = None):
        self.output_path = Path(output_path)
        # 模板缺省 = 仓库默认（`assets/axure/rp8/base_native.rp`，从原生 Axure 抽出）。
        self.template_path = Path(template_path) if template_path else None
        self.canvas_width = 800.0
        self.canvas_height = 600.0
        self._template: writer.Template | None = None
        self._frames: list[doc.Frame] = []
        self._imageless = 0
        # 按钮 / 输入框的文字已经内嵌进控件；基类紧接着会为**同一个 spec** 再发一次
        # `create_text`，那次要被吃掉（配对规则见 `create_text`）。
        self._pending_text: object | None = None

    # --- 生命周期 ---

    def connect(self) -> None:
        if self._template is None:
            self._template = (writer.Template.load(self.template_path)
                              if self.template_path else writer.default_template())

    def disconnect(self) -> None:
        pass

    # --- 画板 / 元素 ---

    def create_frame(self, spec: dict[str, Any]) -> str | None:
        """建一个画板（= 一个 Axure 页面）；页名 / 尺寸原样下发。"""
        self._pending_text = None
        self.canvas_width = _number(spec.get("width"), self.canvas_width) or 800.0
        self.canvas_height = _number(spec.get("height"), self.canvas_height) or 600.0
        frame = doc.Frame(name=str(spec.get("name") or "Home"),
                          width=self.canvas_width,
                          height=self.canvas_height)
        # 页面背景控件：Axure 的页面本身没有可编辑的底色对象（Figma 的画板有），
        # 而页宽/页高在 `.rp` 里也靠内容包围盒撑出来（format §11.9）。发一个铺满
        # 画板的矩形当最底层，既补上「背景控件」，也把画板尺寸钉死。
        background = axure_color(spec.get("backgroundColor")) or 0xFFFFFFFF
        frame.widgets.append(doc.Rect(
            x=0.0, y=0.0, width=self.canvas_width, height=self.canvas_height,
            label="Background", fill=background, border=None, border_width=0.0))
        self._frames.append(frame)
        return None

    def create_rectangle(self, spec: dict[str, Any],
                         parent_id: str | None = None) -> str | None:
        # 基类把 rectangle / container / divider / button / input 都送到这里，靠
        # `spec["type"]` 分派：`button` -> 内置库 Button（顶部标题内嵌），
        # `input` -> `TextBox`（输入框），其余（含 `divider`）还是普通形状。
        role = str(spec.get("type") or "").strip().lower()
        if role == "input":
            widget = self._input(spec)
        elif role == "button":
            widget = self._button(spec)
        else:
            widget = self._rect(spec)
        self._add(widget)
        # 有文字就等于已经内嵌进控件了：下一次 `create_text` 是同一个 spec 的重复下发。
        self._pending_text = (widget if isinstance(widget, (doc.Button, doc.TextField))
                              and str(spec.get("text") or "") else None)
        return None

    def create_ellipse(self, spec: dict[str, Any],
                       parent_id: str | None = None) -> str | None:
        """圆 / 椭圆：`Shape=15` + 4 点圆路径（配方见 format §11.7），不是矩形换色。"""
        self._pending_text = None
        x, y, width, height = self._box(spec)
        fill, border, border_width = self._paint(spec)
        self._add(doc.Ellipse(x=x, y=y, width=width, height=height, label=_label(spec),
                              fill=fill, border=border, border_width=border_width))
        return None

    def create_text(self, spec: dict[str, Any],
                    parent_id: str | None = None) -> str | None:
        # 按钮 / 输入框的文字已经随控件发过了：基类为同一个元素再发的这次文字丢掉。
        # （基类里 `create_rectangle` 与这次 `create_text` 是**紧挨着**的两次调用，
        # 所以这个一次性配对是可靠的；任何别的控件调用都会把哨兵清掉。）
        pending, self._pending_text = self._pending_text, None
        if pending is not None:
            return None
        self._add(self._text(spec))
        return None

    def create_image(self, spec: dict[str, Any],
                     parent_id: str | None = None) -> str | None:
        self._pending_text = None
        data = spec.get("imageBase64")
        if not isinstance(data, (bytes, bytearray, str)):
            data = None
        blob = doc.image_bytes(data)
        if not blob:
            # 没有字节的 ImageBox 发布出来是个坏 `<img>`：宁可退成透明矩形并出声。
            self._imageless += 1
            self._add(self._rect(spec))
            return None
        x, y, width, height = self._box(spec)
        self._add(doc.Image(x=x, y=y, width=width, height=height,
                            data=blob, label=_label(spec)))
        return None

    # --- 落盘 ---

    def flush(self) -> None:
        self.connect()
        self._pending_text = None
        pages = doc.build(doc.DesignSpec(frames=list(self._frames)))
        assert self._template is not None
        # 页包缩略图按页自绘（P4）：`doc.build` 保持帧序，逐页一一对应。
        thumbs = {page.package_guid: thumbnail.render(frame)
                  for page, frame in zip(pages, self._frames)}
        members = writer.generate(self._template, pages, thumbnails=thumbs)
        report = writer.self_check(members)
        if not report["ok"]:
            raise ValueError(
                "Axure .rp 离线自检未通过：c1 %d/%d，存储 %d/%d"
                % (report["c1_ok"], report["c1"], report["stores_ok"], report["stores"]))
        writer.write_rp(members, self.output_path)
        widgets = sum(len(page.widgets) for page in pages)
        logger.info("Axure .rp 已生成：%s（%d 页 / %d 控件）",
                    self.output_path, len(pages), widgets)
        if self._imageless:
            logger.warning("有 %d 个图片元素没有 `imageBase64`，已按透明矩形下发",
                           self._imageless)

    # --- 内部 ---

    def _current(self) -> doc.Frame:
        """当前页面；还没建画板时兜一个默认画板（基类保证会先调 `create_frame`）。"""
        if not self._frames:
            self._frames.append(doc.Frame(width=self.canvas_width,
                                          height=self.canvas_height))
        return self._frames[-1]

    def _add(self, widget) -> None:
        self._current().widgets.append(widget)

    @staticmethod
    def _box(spec: dict[str, Any]) -> tuple[float, float, float, float]:
        return (_number(spec.get("x")), _number(spec.get("y")),
                max(0.0, _number(spec.get("width"))),
                max(0.0, _number(spec.get("height"))))

    @staticmethod
    def _paint(spec: dict[str, Any]) -> tuple[int, int | None, float]:
        """底色 / 描边 / 线宽（矩形与圆共用）。

        缺底色一律发**透明**、没描边也显式发 0 宽：不发就落回 `Box 1` 的
        「白底 + 1px 灰边」（真机踩过）。
        """
        fill = axure_color(spec.get("fillColor"))
        border = axure_color(spec.get("borderColor"))
        stroke = _opt_number(spec.get("borderWidth"))
        return (TRANSPARENT if fill is None else fill, border,
                0.0 if border is None else (stroke if stroke is not None else 1.0))

    def _rect(self, spec: dict[str, Any]) -> doc.Rect:
        x, y, width, height = self._box(spec)
        fill, border, border_width = self._paint(spec)
        return doc.Rect(
            x=x, y=y, width=width, height=height, label=_label(spec),
            fill=fill, border=border, border_width=border_width,
            corner_radius=_number(spec.get("borderRadius"), 0.0))

    @staticmethod
    def _font_args(spec: dict[str, Any], anchor: str = "") -> dict[str, Any]:
        """字体 / 字号 / 字重 / 颜色 / 对齐 / 行高 —— 文字、按钮标题共用一份口径。"""
        return {
            "family": _first_family(spec.get("fontFamily")),
            "size": _number(spec.get("fontSize"), 12.0) or 12.0,
            "weight": _weight(spec.get("fontWeight")),
            "color": axure_color(spec.get("textColor")) or 0xFF333333,
            "align": (_align(spec.get("textAlign")) if spec.get("textAlign")
                      else (1 if anchor == "middle" else 0)),
            "line_spacing": _opt_number(spec.get("lineHeight")),
        }

    def _text(self, spec: dict[str, Any]) -> doc.Text:
        x, y, width, height = self._box(spec)
        border = axure_color(spec.get("borderColor"))
        stroke = _opt_number(spec.get("borderWidth"))
        text = _pin_breaks(spec, str(spec.get("text") or ""))
        anchor = str(spec.get("textAnchor") or "").strip().lower()
        fonts = self._font_args(spec, anchor)
        if width <= 0:
            # 控件（按钮 / 输入框）里的文字：基类只给「盒子中心 x + text-anchor=middle」，
            # 没有宽度。Axure 的文字框按宽度折行，宽度 0 会被钳成 1px -> 一个字一行
            # （真机实测过），所以这里估一行宽度，居中时再把盒子挪回中心。
            width = _text_width(text, fonts["size"])
            if anchor == "middle":
                x -= width / 2.0
        border_width = (0.0 if border is None
                        else (stroke if stroke is not None else 1.0))
        fill = axure_color(spec.get("fillColor"))
        if border_width:
            # 文字盒带边框（CSS `box-sizing:border-box`，内容盒在边框以内）：**边框单独
            # 发一个矩形**，文字控件只管文字。真机 dushu 分类格的 28 个 12px 标签带
            # `border:1px`（盒 96x38 / `lineHeight:38px`）：原截图墨迹 267-277，我们
            # 266-276 —— **整排高 1px**。两个落点的差在这一处：
            #   * 浏览器：行盒**顶在内容盒上沿**（253），字心 = 253 + 38/2 = 272；
            #   * Axure ：把行盒**在控件里垂直居中**（发布成 `#uN_text{top:(控件高-行高)/2}`），
            #     字心 = 控件顶 + 控件高/2。
            # 所以竖直方向**只挪控件、不缩高度**：控件顶 = 内容盒顶 253、高仍是 38 ->
            # 字心 272，与浏览器逐行相同。**把高度也缩掉 2px 是错的**（字心 271，等于没修，
            # 截图与改前逐字节相同 —— 本轮第一版就踩了这个）。高度对**折行**没影响
            # （Axure 按面板宽折行），只影响这个垂直落点。
            # 水平方向按内容盒缩到 94（控件 935）：居中文字看不出，左/右对齐看得出。
            # 面板的 `top` **不是杠杆**（手改发布产物里的 `top` 画面不动），`pad` 也只换来
            # `left:1px`，两者都撤掉了。基类只为「带非中性底色的文字」发过底框
            # （adapter_base `_render_page`：整盒 + 同色 + 同边框）；底色透明 / 纯白时边框
            # 本来就画在文字控件上，那份也一并挪到这个矩形里。
            if not (fill is not None
                    and not self._is_neutral_background(spec.get("fillColor"))):
                self._add(doc.Rect(
                    x=x, y=y, width=width, height=height, label=_label(spec),
                    fill=(TRANSPARENT if fill is None else fill),
                    border=border, border_width=border_width,
                    corner_radius=_number(spec.get("borderRadius"), 0.0)))
            inset = border_width
            x, y = x + inset, y + inset
            width = max(1.0, width - 2 * inset)
            # 控件不再与盒重合，底色交给上面那个矩形（或基类的底框）铺满整盒。
            fill = TRANSPARENT
            border, border_width = None, 0.0
        # 落字位置对齐（见 `_aligned_panel_height`）：只调发给 Axure 的控件高，
        # 上面那个边框矩形仍按原盒画（盒子几何不变，只有文字的落点变）。
        height = _aligned_panel_height(spec, y, height)
        return doc.Text(
            text=text,
            x=x, y=y, width=width, height=height, label=_label(spec),
            # 基类给「带底色的文字」另发过一个底框，这里再给文字形状一份同样的底色
            # 是幂等的（同色同几何）；缺了它「白底文字」就会漏底（基类把白当透明）。
            # 带边框那条分支里底色已由边框矩形铺满整盒，`fill` 在那里被换成透明。
            fill=fill,
            border=border,
            border_width=border_width,
            # 内容盒由控件自身的 x/y/w/h 表达（见上），这里不再要内边距。
            corner_radius=_number(spec.get("borderRadius"), 0.0),
            # 不许发布端再折一遍的元素（见 `_no_reflow`）：控件自己的 `AutoFitWidth`
            # 一发，发布端就写 `white-space:nowrap`，面板宽度仍是盒宽 -> 位置不变。
            shape_autofit=_no_reflow(spec),
            **fonts)

    def _button(self, spec: dict[str, Any]) -> doc.Button:
        """按钮：内置库 `Button` 样式 + **内嵌**标题（配方见 format §11.8）。

        标题不在这里发 —— 它是按钮的子 `RichTextPanel`，`doc.button_spec` 从
        `text` / 字体字段里造；基类随后为同一个 spec 再发的那次 `create_text`
        由 `create_text` 吃掉。

        标题的**水平偏移**优先按采集到的文字行框（`textBox`）：按钮盒常常是整行
        容器，文字只是其中一个 inline 片段（前面还有图标 / 间距）。发布端会用控件
        的 `P_PADDING_LEFT` 重算 `#uN_text{left}`，所以这里把 `textBox.x - 控件.x`
        发成 `pad_left`，并把标题改成左对齐（真机见 plan §9.23）。
        """
        x, y, width, height = self._box(spec)
        fill, border, border_width = self._paint(spec)
        no_reflow = _no_reflow(spec)
        # 按钮的标题内嵌在控件里、落点同样是「控件内居中」——与 `_text` 同一口径
        # 按采集到的第一行行框改控件高（见 `_aligned_panel_height`）。
        height = _aligned_panel_height(spec, y, height)
        fonts = self._font_args(spec, "middle")
        caption = _caption_inset(spec, x, width)
        inset = None
        pad_right = None
        if caption is not None:
            inset, tight = caption
            # 紧盒：左内边距吃掉宽度后放不下这一行。不能退回 Axure 排版（图标会继续
            # 压字），也不能发 `AutoFitWidth`（真机会把控件宽撑成 `dx + 文字宽`）。
            # 用等量的负右内边距把面板宽补回控件宽，落点左移但可用宽度不缩。
            if tight:
                pad_right = -inset
        panel_box = None
        if no_reflow:
            # 不折行（见 `_no_reflow`）：标题面板这时必须给**真实盒子**——哨兵 + `AutoFitWidth`
            # 会让发布端把控件自己算成 1px 宽（真机实测 `#u14{left:126px;width:1px}`）；
            # 给了真实盒子它照旧按垂直居中自己排版。
            panel_box = (0.0, 0.0, width, height)
        if inset is not None:
            # 图标在文字左侧：把标题的**左内边距**发成行框偏移，发布端据此重算
            # `#uN_text{left:dx;width:控件宽-dx}`。面板内再按 textAlign 排一次会把
            # 偏移加回去，所以同时改成左对齐。
            fonts["align"] = 0
        return doc.Button(
            x=x, y=y, width=width, height=height, label=_label(spec),
            text=str(spec.get("text") or ""),
            fill=fill, border=border, border_width=border_width,
            corner_radius=_number(spec.get("borderRadius"), 0.0),
            shape_autofit=no_reflow,
            panel_box=panel_box,
            pad_left=inset,
            pad_right=pad_right,
            **fonts)

    def _input(self, spec: dict[str, Any]) -> doc.TextField:
        """输入框：`Axure:DiagramObject:TextBox`（`Text Field` 库样式，§11.8）。

        `ShowBorder` 跟 DOM 走：DOM 没描边就发 `ShowBorder=False`（否则浏览器会给
        `<input>` 补一圈默认边框，页面上就凭空多一道线）。
        """
        x, y, width, height = self._box(spec)
        fill, border, border_width = self._paint(spec)
        fonts = self._font_args(spec)
        # 行距（P20）没在 TextBox 上实测过，宁可不发，别发明没验过的槽位。
        fonts.pop("line_spacing", None)
        return doc.TextField(
            x=x, y=y, width=width, height=height, label=_label(spec),
            text=str(spec.get("text") or ""),
            fill=fill, border=border, border_width=border_width,
            show_border=(border is not None),
            **fonts)
