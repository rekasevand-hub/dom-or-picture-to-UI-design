"""Axure RP 8 的常量：PName、颜色、内置样式 id、默认样式属性表。

依据：`归档文档 axure_rp8_format.md` §5.4。表里的值全部来自实测
（`output/_axure_samples/rect_a.rp` 的 `Axure:Page.StyleCache` 与
`DesignDocument.StyleSheet`）。
"""
from __future__ import annotations

import uuid

# `DOAName` 是 **有符号** int32：0xC0000000 >> 31 后是负数。
DOA_BASE = -1073741824          # 0xC0000000


def doa(pname: int) -> int:
    """PName -> 记录里的 DOAName。"""
    return DOA_BASE | pname


# --- Axure.Constants.PName（Core.dll，实测取值）---------------------------
P_BASE_STYLE = 0
P_FONT_NAME = 1
P_FONT_SIZE = 2
P_BOLD = 3
P_ITALIC = 4
P_UNDERLINE = 5
P_FORE_GROUND_FILL = 6
P_FILL = 7
P_BORDER_FILL = 8
P_PADDING_LEFT = 11
P_PADDING_TOP = 12
P_PADDING_RIGHT = 13
P_PADDING_BOTTOM = 14
P_BORDER_WIDTH = 15
# 9 / 10 是**实测推断**的文本对齐（原生样式表里 `Default` 是 P9=1/P10=1 且 CSS
# `text-align:center`；`Label`/`Shape`/`Heading 1` 都是 0 且 CSS `left`）。字号/行距
# 在文件里是 **pt**，发布成 CSS 时 ×4/3（10.5 -> 14px，30.0 -> 40px）。
P_ALIGN_H = 9
P_ALIGN_V = 10
P_LINE_SPACING = 20
P_LINE_PATTERN = 16
P_IX_STYLES = 21
P_IMAGE = 27
P_IMAGE_REPEAT = 30
P_COLOR_STYLE = 31
P_SKETCH_FACTOR = 32
P_FAVICON = 33
P_ROTATION = 50
P_OPACITY = 70
P_CORNER_RADIUS = 71
P_OUTER_SHADOW = 72
P_LOCATION = 101
P_SIZE = 105
P_VISIBLE = 110
P_PLACED = 111
P_TYPEFACE = 1000
P_FONT_WEIGHT = 1001
P_FONT_STYLE = 1002
P_WRAP = 1200
P_ITEM_BACK_COLOR = 1204
P_ITEMS_PER_PAGE = 1208
P_START_PAGE = 1209

PNAME_NAMES = {
    P_BASE_STYLE: "BASE_STYLE", P_FONT_NAME: "FONT_NAME", P_FONT_SIZE: "FONT_SIZE",
    P_BOLD: "BOLD", P_ITALIC: "ITALIC", P_UNDERLINE: "UNDERLINE",
    P_FORE_GROUND_FILL: "FORE_GROUND_FILL", P_FILL: "FILL", P_BORDER_FILL: "BORDER_FILL",
    P_PADDING_LEFT: "PADDING_LEFT", P_PADDING_TOP: "PADDING_TOP",
    P_PADDING_RIGHT: "PADDING_RIGHT", P_PADDING_BOTTOM: "PADDING_BOTTOM",
    P_BORDER_WIDTH: "BORDER_WIDTH", P_LINE_PATTERN: "LINE_PATTERN",
    P_ALIGN_H: "P9_ALIGN_H", P_ALIGN_V: "P10_ALIGN_V",
    P_LINE_SPACING: "P20_LINE_SPACING",
    P_IX_STYLES: "IX_STYLES", P_IMAGE: "IMAGE", P_IMAGE_REPEAT: "IMAGE_REPEAT",
    P_COLOR_STYLE: "COLOR_STYLE", P_SKETCH_FACTOR: "SKETCH_FACTOR", P_FAVICON: "FAVICON",
    P_ROTATION: "ROTATION", P_OPACITY: "OPACITY", P_CORNER_RADIUS: "CORNER_RADIUS",
    P_OUTER_SHADOW: "OUTER_SHADOW", P_LOCATION: "LOCATION", P_SIZE: "SIZE",
    P_VISIBLE: "VISIBLE", P_PLACED: "PLACED", P_TYPEFACE: "TYPEFACE",
    P_FONT_WEIGHT: "FONT_WEIGHT", P_FONT_STYLE: "FONT_STYLE", P_WRAP: "WRAP",
    P_ITEM_BACK_COLOR: "ITEM_BACK_COLOR", P_ITEMS_PER_PAGE: "ITEMS_PER_PAGE",
    P_START_PAGE: "START_PAGE",
}


def pname_name(pname: int) -> str:
    return PNAME_NAMES.get(pname, "P%d" % pname)


# --- 颜色 ---------------------------------------------------------------
# `PropList` 里的颜色是 **0xAARRGGBB**；"无填充/无描边" = 0x00FFFFFF。
NO_COLOR = 0x00FFFFFF
BLACK = 0xFF000000
WHITE = 0xFFFFFFFF


def as_int32(value: int) -> int:
    """0xAARRGGBB 这类无符号 32 位值 -> 记录里的**有符号** int32。

    样本里白色是 `-1`（= 0xFFFFFFFF）、深灰是 `-13421773`（= 0xFF333333），
    所以写颜色前必须过这一道，否则 `struct.pack("<i")` 会溢出。
    """
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def argb(red: int, green: int, blue: int, alpha: int = 255) -> int:
    return ((alpha & 0xFF) << 24) | ((red & 0xFF) << 16) | ((green & 0xFF) << 8) | (blue & 0xFF)


def to_argb(text: str, default: int | None = None) -> int | None:
    """`#rgb` / `#rrggbb` / `#aarrggbb` / `rgba(...)` 风格 -> 0xAARRGGBB（含 `#` 可选）。"""
    if text is None:
        return default
    value = text.strip()
    if not value or value.lower() in ("none", "transparent"):
        return NO_COLOR if value.lower() != "transparent" else 0x00000000
    if value.startswith("#"):
        value = value[1:]
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) == 6:
        return 0xFF000000 | int(value, 16)
    if len(value) == 8:
        return int(value, 16)
    raise ValueError("unsupported color: %r" % text)


# --- 内置样式 id（跨样本实测一致）---------------------------------------
DEFAULT_LIBRARY_ID = uuid.UUID("53f4a189-168b-4748-93d4-09a1b736ad03")
BOX_STYLE_ID = uuid.UUID("4b7bfc59-6114-4279-89e1-0bb0b557d0ce")      # 名为 "Box 1"
AXURE_DEFAULT_STYLE_ID = uuid.UUID("627587b6-038d-43cc-a051-c114ac41ad32")
# 图片控件（`Axure:DiagramObject:ImageBox`）命中的内置库样式「图片」。
# 实测 `首页原型.rp` 的 3 个 ImageBox 全部指向它（`MatchInfo.Id` 与 `BASE_STYLE` 值相同）。
# **发布出来的 CSS 类名取自 `MatchInfo.Name`**（"图片" -> `_图片`，与 GUID 无关），
# 所以这个 Name 就是「图片控件长什么样」的那一环。
IMAGE_BOX_STYLE_ID = uuid.UUID("e539a14d-816b-49f2-9281-6d44254d5f72")
IMAGE_BOX_STYLE_NAME = "图片"

DEFAULT_LIBRARY_NAME = "Default"
BOX_STYLE_NAME = "Box 1"
DEFAULT_STYLE_NAME = "Default"

# `Axure:InteractionEvent.event-type`：Axure 给 VectorShape 登记的事件类型
# （顺序取 `rect_a.rp` 的实测序列）。
VECTOR_SHAPE_EVENTS = (288, 321, 322, 325, 324, 16, 17, 323, 19, 32, 33, 338)

# 每页固定登记的交互事件（**与控件数量无关**：rect_a 1 个矩形、rect_b 2 个矩形，
# 都是这 12 条）。页面 `InteractionTreeMap` 的节点数就等于它的条数。
PAGE_EVENTS = VECTOR_SHAPE_EVENTS

# `Style.Capabilities` 是**按控件类型**给的位掩码（同类型的所有实例一致，实测）：
#   Box / Label / Shape / Heading / Paragraph   558483178520511
#   ImageBox                                    382630030212799
#   Ellipse                                     417745690165183
#   Line                                        134071690723263
#   Icon / Marker                               134071690198975
STYLE_CAPABILITIES = 558483178520511      # 形状控件（Box / Label / …）
IMAGE_BOX_CAPABILITIES = 382630030212799  # 图片控件
PAGE_STYLE_CAPABILITIES = -1048577        # 页面 PageStyle.Capabilities（实测）

# --- 形状枚举与「圆」-----------------------------------------------------
# 圆**不是**单独的类，也不是 8 段路径：`VectorShape.Shape` 只是按控件类型给的
# 枚举，圆 = `Shape = 15` + **4 点贝塞尔**（4 个 Path 落在包围盒 4 条边的中点，
# 把手是**真值** `0.5 ± 0.28`，不是矩形那种 NaN 把手）。原生实测两处独立命中、
# 逐值相同：`首页原型.rp`（8.0.0.3400，`Ellipse` 样式）与 v1 骨架
# `skeleton.rp（v1 资产，已删；发布副本在 output/_axure_oracle/skelref/）`。`Line = 29`、`Placeholder = 10`、图标/自定义路径 = 300。
SHAPE_ELLIPSE = 15
ELLIPSE_HANDLE_OFFSET = 0.28
# 「椭圆」命中的内置库样式（`Default` 库的 `Ellipse`）；发布出的 CSS 类名取自 `Name`。
ELLIPSE_STYLE_ID = uuid.UUID("4041ce63-2342-4373-bade-c8bcf3dd21cb")
ELLIPSE_STYLE_NAME = "Ellipse"
ELLIPSE_CAPABILITIES = 417745690165183

# --- 按钮 / 输入框（真机实测，见 `归档文档 axure_rp8_format.md` §11.8）-------------
# 两者都**不是**独立的对象类：按钮仍是 `VectorShape`（`Shape = 0` + 8 段圆角路径），
# 输入框是 `Axure:DiagramObject:TextBox`。「是按钮 / 是输入框」由命中的内置库样式
# 决定 —— 发布出的 CSS 类名取自 `MatchInfo.Name`（`Button` -> `button`、
# `Text Field` -> `text_field`），**但这个名字必须同时出现在项目样式表里**
# （`CustomStyles`，见下面那组常量）。实测来源：`skeleton.rp（v1 资产，已删；发布副本在 output/_axure_oracle/skelref/）`（Axure
# 自己造的一份控件样例）。
# 注意落盘是 .NET 的小端字节序（`uuid.bytes_le`）。
BUTTON_STYLE_ID = uuid.UUID("1357f3c9-cfa1-914e-a0f2-dbac65e6fb5c")
BUTTON_STYLE_NAME = "Button"
TEXT_FIELD_STYLE_ID = uuid.UUID("08781544-93f2-0041-b68f-2394a66b2bba")
TEXT_FIELD_STYLE_NAME = "Text Field"
# 输入框有自己的 Capabilities（按钮的与普通形状相同，见 STYLE_CAPABILITIES）。
TEXT_FIELD_CAPABILITIES = 13194141765535
# 按钮标题子面板的 `ContainedLocation`：Axure 用 `-100000` 表示「由控件自己排版」，
# 发布成 `#uN_text{left:2px;top:14px;width:<控件宽 - 4>px}`（= 控件内边距 2px）。
CAPTION_SENTINEL = -100000.0

# --- 项目样式表条目（`DesignDocument.StyleSheet.CustomStyles`）----------------
# **为什么必须有**：Axure 发布时按控件命中的**样式名**给元素加 CSS 类
# （`Button` -> `class="ax_default button"`、`Text Field` -> `text_field`），而
# 样式名得能从项目样式表里查到。模板 `base_native.rp`（来自 `首页原型.rp`）里没有
# 这两条，所以按钮 / 输入框只会发成 `class="ax_default"`（真机 m8ctl 实测：
# `button=False text_field=False`，补上这两条后变成 `RESULT=OK`）。
#
# 下面两组行是原生 `skeleton.rp（v1 资产，已删；发布副本在 output/_axure_oracle/skelref/）` 样式表里同名条目的**逐值照抄**
# （行序 / DOAName / 值标签都一致，`#` 后面只是 PName 对照）。注意这里的
# DOAName 大多只带 `0x80000000` 位、个别行带 `0xC0000000`（pname 71、Text Field
# 的 6/9/10），与页面级 `Axure:Style` 的 `doa()` 不是一套编码，所以这里直接写
# 原始 int32。
BUTTON_STYLE_PROPS = [
    (-2147483647, ("str", 'Arial')),  # pname 1 P_FONT_NAME
    (-2147482647, ("int", 400)),  # pname 1001 P_FONT_WEIGHT
    (-2147482646, ("int", 0)),  # pname 1002 P_FONT_STYLE
    (-2147482645, ("int", 5)),  # pname 1003
    (-2147483646, ("f64", 9.75)),  # pname 2 P_FONT_SIZE
    (-2147483645, ("int", 1)),  # pname 3 P_BOLD
    (-2147483644, ("int", 1)),  # pname 4 P_ITALIC
    (-2147483643, ("bool", 1)),  # pname 5 P_UNDERLINE
    (-2147483642, ("dd", [('fill-type', ("str", 'solid')), ('fill-color', ("int", -13421773))])),  # pname 6 P_FORE_GROUND_FILL
    (-2147483640, ("dd", [('fill-type', ("str", 'solid')), ('fill-color', ("int", -8816263))])),  # pname 8 P_BORDER_FILL
    (-2147483633, ("f64", 1.0)),  # pname 15 P_BORDER_WIDTH
    (-2147483632, ("int", 1)),  # pname 16 P_LINE_PATTERN
    (-2147483568, ("int", 15)),  # pname 80
    (-1073741753, ("f64", 5.0)),  # pname 71 P_CORNER_RADIUS
    (-2147483567, ("int", 15)),  # pname 81
    (-2147483641, ("dd", [('fill-type', ("str", 'solid')), ('fill-color', ("int", -1))])),  # pname 7 P_FILL
    (-2147483578, ("f64", 1.0)),  # pname 70 P_OPACITY
    (-2147483576, ("dd", [('On', ("bool", 1)), ('OffsetX', ("f64", 5.0)), ('OffsetY', ("f64", 5.0)), ('BlurRadius', ("f64", 5.0)), ('Color', ("int", 1493172224)), ('Spread', ("f64", 0.0))])),  # pname 72 P_OUTER_SHADOW
    (-2147483575, ("dd", [('On', ("bool", 1)), ('OffsetX', ("f64", 0.0)), ('OffsetY', ("f64", 5.0)), ('BlurRadius', ("f64", 5.0)), ('Color', ("int", 1493172224)), ('Spread', ("f64", 0.0))])),  # pname 73
    (-2147483574, ("dd", [('On', ("bool", 1)), ('OffsetX', ("f64", 1.0)), ('OffsetY', ("f64", 1.0)), ('BlurRadius', ("f64", 5.0)), ('Color', ("int", -1526726656)), ('Spread', ("f64", 0.0))])),  # pname 74
    (-2147483639, ("int", 1)),  # pname 9 P_ALIGN_H
    (-2147483638, ("int", 1)),  # pname 10 P_ALIGN_V
    (-2147483637, ("f64", 2.0)),  # pname 11 P_PADDING_LEFT
    (-2147483636, ("f64", 2.0)),  # pname 12 P_PADDING_TOP
    (-2147483635, ("f64", 2.0)),  # pname 13 P_PADDING_RIGHT
    (-2147483634, ("f64", 2.0)),  # pname 14 P_PADDING_BOTTOM
    (-2147483628, ("f64", 0.0)),  # pname 20 P_LINE_SPACING
]

TEXT_FIELD_STYLE_PROPS = [
    (-2147483647, ("str", 'Arial')),  # pname 1 P_FONT_NAME
    (-2147482647, ("int", 400)),  # pname 1001 P_FONT_WEIGHT
    (-2147482646, ("int", 0)),  # pname 1002 P_FONT_STYLE
    (-2147482645, ("int", 5)),  # pname 1003
    (-2147483646, ("f64", 9.75)),  # pname 2 P_FONT_SIZE
    (-2147483645, ("int", 1)),  # pname 3 P_BOLD
    (-2147483644, ("int", 1)),  # pname 4 P_ITALIC
    (-2147483643, ("bool", 1)),  # pname 5 P_UNDERLINE
    (-1073741818, ("dd", [('fill-type', ("str", 'solid')), ('fill-color', ("int", -16777216))])),  # pname 6 P_FORE_GROUND_FILL
    (-2147483640, ("dd", [('fill-type', ("str", 'solid')), ('fill-color', ("int", -8816263))])),  # pname 8 P_BORDER_FILL
    (-2147483633, ("f64", 1.0)),  # pname 15 P_BORDER_WIDTH
    (-2147483632, ("int", 1)),  # pname 16 P_LINE_PATTERN
    (-2147483568, ("int", 15)),  # pname 80
    (-2147483577, ("f64", 0.0)),  # pname 71 P_CORNER_RADIUS
    (-2147483567, ("int", 15)),  # pname 81
    (-2147483641, ("dd", [('fill-type', ("str", 'solid')), ('fill-color', ("int", -1))])),  # pname 7 P_FILL
    (-2147483578, ("f64", 1.0)),  # pname 70 P_OPACITY
    (-2147483576, ("dd", [('On', ("bool", 1)), ('OffsetX', ("f64", 5.0)), ('OffsetY', ("f64", 5.0)), ('BlurRadius', ("f64", 5.0)), ('Color', ("int", 1493172224)), ('Spread', ("f64", 0.0))])),  # pname 72 P_OUTER_SHADOW
    (-2147483575, ("dd", [('On', ("bool", 1)), ('OffsetX', ("f64", 0.0)), ('OffsetY', ("f64", 5.0)), ('BlurRadius', ("f64", 5.0)), ('Color', ("int", 1493172224)), ('Spread', ("f64", 0.0))])),  # pname 73
    (-2147483574, ("dd", [('On', ("bool", 1)), ('OffsetX', ("f64", 1.0)), ('OffsetY', ("f64", 1.0)), ('BlurRadius', ("f64", 5.0)), ('Color', ("int", -1526726656)), ('Spread', ("f64", 0.0))])),  # pname 74
    (-1073741815, ("int", 0)),  # pname 9 P_ALIGN_H
    (-1073741814, ("int", 1)),  # pname 10 P_ALIGN_V
    (-2147483637, ("f64", 2.0)),  # pname 11 P_PADDING_LEFT
    (-2147483636, ("f64", 2.0)),  # pname 12 P_PADDING_TOP
    (-2147483635, ("f64", 2.0)),  # pname 13 P_PADDING_RIGHT
    (-2147483634, ("f64", 2.0)),  # pname 14 P_PADDING_BOTTOM
    (-2147483628, ("f64", 0.0)),  # pname 20 P_LINE_SPACING
]

# --- 内置 "Default" 样式（Axure.Constants.DefaultStyle 的形状，38 条）----
# 描述符语言见 `model.StreamBuilder.build`。
DEFAULT_STYLE_PROPS = [
    (P_FONT_NAME, ("str", "Arial")),
    (P_FONT_SIZE, ("f64", 9.75)),
    (P_FONT_WEIGHT, ("int", 400)),
    (P_FONT_STYLE, ("int", 0)),
    (1003, ("int", 5)),
    (P_UNDERLINE, ("bool", 0)),
    (P_FORE_GROUND_FILL, ("dd", [("fill-type", ("str", "solid")),
                                 ("fill-color", ("int", -13421773))])),
    (9, ("int", 1)),
    (20, ("f64", 0.0)),
    (18, ("bool", 0)),
    (P_LOCATION, ("dd", [("X", ("f64", 0.0)), ("Y", ("f64", 0.0))])),
    (P_SIZE, ("dd", [("Width", ("f64", 0.0)), ("Height", ("f64", 0.0))])),
    (P_VISIBLE, ("bool", 1)),
    (P_PLACED, ("int", 1)),
    (P_BASE_STYLE, ("guid", AXURE_DEFAULT_STYLE_ID)),
    (P_BOLD, ("int", 0)),
    (P_ITALIC, ("int", 0)),
    (P_FILL, ("dd", [("fill-type", ("str", "solid")), ("fill-color", ("int", -1))])),
    (P_BORDER_FILL, ("dd", [("fill-type", ("str", "solid")), ("fill-color", ("int", -8816263))])),
    (P_BORDER_WIDTH, ("f64", 1.0)),
    (P_LINE_PATTERN, ("int", 1)),
    (17, ("dd", [("Start", ("int", 1)), ("End", ("int", 1))])),
    (P_OPACITY, ("f64", 1.0)),
    (P_CORNER_RADIUS, ("f64", 0.0)),
    (80, ("int", 15)),
    (81, ("int", 15)),
    (10, ("int", 1)),
    (P_PADDING_LEFT, ("f64", 2.0)),
    (P_PADDING_TOP, ("f64", 2.0)),
    (P_PADDING_RIGHT, ("f64", 2.0)),
    (P_PADDING_BOTTOM, ("f64", 2.0)),
    (P_IMAGE, ("dd", [("Hash", ("str", ""))])),
    (P_IX_STYLES, ("dd", [])),
    (P_ROTATION, ("f64", 0.0)),
    (51, ("f64", 0.0)),
    (P_OUTER_SHADOW, ("dd", [("On", ("bool", 0)), ("OffsetX", ("f64", 5.0)),
                             ("OffsetY", ("f64", 5.0)), ("BlurRadius", ("f64", 5.0)),
                             ("Color", ("int", 1493172224)), ("Spread", ("f64", 0.0))])),
    (73, ("dd", [("On", ("bool", 0)), ("OffsetX", ("f64", 0.0)), ("OffsetY", ("f64", 5.0)),
                 ("BlurRadius", ("f64", 5.0)), ("Color", ("int", 1493172224)),
                 ("Spread", ("f64", 0.0))])),
    (74, ("dd", [("On", ("bool", 0)), ("OffsetX", ("f64", 1.0)), ("OffsetY", ("f64", 1.0)),
                 ("BlurRadius", ("f64", 5.0)), ("Color", ("int", -1526726656)),
                 ("Spread", ("f64", 0.0))])),
]
