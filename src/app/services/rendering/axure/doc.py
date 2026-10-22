"""`DesignSpec -> PageSpec`：角色映射（方案 §3）与控件三元组（§6.1）。

一次性把「用户态的元素列表」翻译成 `model.PageSpec`（= 一个 Axure 页面包）。
M2 走「矩形」这条最窄路径；M4 接入文字（`Text` -> `VectorShape` + 子
`RichTextPanel`，配方见 `归档文档 axure_rp8_format.md` §11.5）与图片（`Image` ->
`ImageBox`，图存进 `Axure:Style.PropList` 的 `IMAGE(27)` 槽，配方见 §11.6）；
圆走 `Ellipse` -> `Shape=15` + 4 点圆路径（§11.7）；`Button` -> 库样式 `Button`
的形状 + 子面板标题、`TextField` -> `Axure:DiagramObject:TextBox`（§11.8）。

**与 v1 的结构差异**：角色只决定「发哪个类」，不再决定「用哪条母本模板」。
"""
from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field

from . import constants, model


@dataclass
class Rect:
    """一个矩形控件（Axure `VectorShape` + 它的 `Axure:Style`）。"""

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    label: str = ""
    fill: int | None = None          # 0xAARRGGBB；None = 沿用默认样式（白底灰框）
    border: int | None = None
    border_width: float | None = None
    corner_radius: float = 0.0
    guid: uuid.UUID | None = None
    style_guid: uuid.UUID | None = None
    style_id: uuid.UUID | None = None


@dataclass
class Ellipse:
    """一个圆 / 椭圆（Axure `VectorShape` + `Shape=15` + 4 点圆路径）。

    配方（原生 `首页原型.rp` 与 v1 骨架 `skeleton.rp（v1 资产，已删；发布副本在 output/_axure_oracle/skelref/）` 两处逐值实测）：
    `Shape = 15`、轮廓是**4 点贝塞尔**（不是 8 段弧）、样式命中内置库的 `Ellipse`
    （`Capabilities = 417745690165183`，与矩形那条不同）。`fill` / `border` /
    `border_width` 与 `Rect` 同口径：缺色必须显式发透明 + 0 描边，否则会落回
    `Box 1` 的白底灰边（§2.3 的老坑）。
    """

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    label: str = ""
    fill: int | None = None          # 0xAARRGGBB；None = 沿用默认样式（白底灰框）
    border: int | None = None
    border_width: float | None = None
    guid: uuid.UUID | None = None
    style_guid: uuid.UUID | None = None
    style_id: uuid.UUID | None = None


@dataclass
class Text:
    """一个文字块：`VectorShape`（宿主形状）+ 子 `RichTextPanel`（文字本体）。

    实测 Axure 自己从不把 `RichTextPanel` 放在页面顶层：每个文本控件都是「一个形状
    带着一个文字面板」。所以这里也照这个形状发射，宿主形状默认**无填充无描边**
    （样式只发 SIZE + BASE_STYLE + LOCATION，沿用 `Box 1`，真机实测是空白盒子）。

    `text` 里的 `\n` 按段切开（一个段落 = 一个 `Paragraph` + 一个 `AxRun`）；
    需要一段多格式时用 `runs` 直接给 `list[list[model.TextRun]]`。
    """

    text: str = ""
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    family: str = "Arial"
    size: float = 12.0
    weight: int = 400
    color: int = 0xFF333333
    italic: bool = False
    underline: bool = False
    align: int = 0                     # 水平对齐 -> `P9`（0=左 1=中 2=右，**实测**）
    v_align: int = 1                   # 垂直对齐 -> `P10`（0=上 1=中 2=下，实测中）
    line_spacing: float | None = None  # 行高 px -> `P20`（落盘 pt = px*0.75）；None=不写
    autofit_width: bool = False
    shape_autofit: bool = False        # 宿主形状自己的 `AutoFitWidth`（真机 A/B 见 plan §9.11）
    runs: list | None = None           # 覆盖 text，直接给 list[list[TextRun]]
    pad: float | None = None           # 四边内边距 px；None=0（文字框默认不留白）
    fill: int | None = None            # None=透明（0x00FFFFFF），与 Axure `Label` 同名样式一致
    border: int | None = None          # None=无描边
    border_width: float | None = None  # None=0（发布成 `border:none`）
    corner_radius: float = 0.0
    label: str = ""
    guid: uuid.UUID | None = None
    style_guid: uuid.UUID | None = None
    style_id: uuid.UUID | None = None
    panel_guid: uuid.UUID | None = None


@dataclass
class Image:
    """一个图片控件（Axure `ImageBox`）。

    图**不是**独立文件：原始字节以 blob 形式存在 `Axure:Style.PropList` 的
    `IMAGE(27)` 槽里，`Hash = base64(md5(字节))`。真机实测（`首页原型.rp` -> 发布）
    发布出来的 `images/<page>/uN.png` 与槽里的字节**逐字节相同**（Axure 不重编码、
    不改分辨率），所以这里给什么图，页面上就是什么图。

    `data` 收字节或 base64 字符串（允许带 `data:image/png;base64,` 前缀）；
    `extension` 缺省按 magic 判（原生样本里出现过空串，也是合法的）。
    """

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    data: bytes | str | None = None
    extension: str | None = None
    fit_to_image: bool = False
    label: str = ""
    guid: uuid.UUID | None = None
    style_guid: uuid.UUID | None = None
    style_id: uuid.UUID | None = None


@dataclass
class Button:
    """一个按钮（Axure 内置库的「Button」控件）。

    真机配方（`skeleton.rp（v1 资产，已删；发布副本在 output/_axure_oracle/skelref/）` 里 Axure 自己造的 Button 样例，发布产物见
    `归档文档 axure_rp8_format.md` §11.8）：**不是**独立对象类 —— 仍是
    `Axure:DiagramObject:VectorShape`（`Shape = 0`），"是按钮"由命中的库样式
    `Default/Button`（`MatchInfo.Id = 1357f3c9-…`）决定，发布成
    `class="ax_default button"`。标题**不是**独立控件，而是挂在
    `diagram-objects` 的子 `RichTextPanel` 上、位置留 `CAPTION_SENTINEL` 让 Axure
    自己排版。发布端 `_setTextAlignment` 用控件的 `P_PADDING_LEFT/RIGHT` 重算
    `#uN_text{left,width}`，所以标题水平偏移发 `pad_left`（见 `Button.pad_left`），
    面板几何不参与定位。

    字段口径与 `Text` 一致（字体 / 颜色 / 对齐 / 行高）+ 与 `Rect` 一致的
    底色 / 描边；`_text_props` 直接吃这个对象（鸭子类型），只有 `BASE_STYLE` 与
    几何路径在 `button_spec` 里换掉。
    """

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    text: str = ""
    label: str = ""
    family: str = "Arial"
    size: float = 12.0
    weight: int = 400
    color: int = 0xFF333333
    italic: bool = False
    underline: bool = False
    align: int = 1                     # 按钮标题默认居中（与 Axure 一致）
    v_align: int = 1
    line_spacing: float | None = None
    # 四边内边距（落成 `PropList` 的 `P_PADDING_*`）。原生 `Button` 库样式是 2px
    # （`skeleton.rp` 样式表条目实测），Axure 随之把标题面板排成
    # `#uN_text{left:2px;width:控件宽-4}`。但我们的按钮全都由 DOM 盒子派生
    # （`<a>` / `<button>` / `<select>`），行内控件的盒子常常**紧贴文字**，任一侧
    # 吃 2px 可用宽度就少 4px，标题随即折行——真机 `dushuax1` 实测 120 个按钮里
    # 53 个中招（见 `归档文档 axure_rp8_plan.md` §9.4 P1）。所以默认 0：标题面板占满
    # 控件宽，与 DOM 的可用宽度一致，而控件盒子的几何仍是逐值命中。
    pad: float = 0.0
    # 标题面板的**左内边距**单独覆盖（None = 用 `pad`）。发布端
    # `_setTextAlignment` 会用 `paddingLeft` 重算 `#uN_text{left,width}`，并**忽略**
    # `RichTextPanel` 的 `ContainedLocation`（真机 A/B 见 plan §9.23）；按钮前面有
    # 图标时，用这个字段把标题推到 `textBox` 的左缘。
    pad_left: float | None = None
    # 右内边距单独覆盖（None = 用 `pad`）。紧盒会用 `pad_right = -pad_left`
    # 把发布端缩掉的面板宽补回来：`width - dx - (-dx) = width`，控件几何不变。
    pad_right: float | None = None
    # 文字「不折行」的语义开关（`white-space:nowrap`）：True 时把面板的
    # `AutoFitWidth` 发成真，Axure 发布成 `white-space:nowrap`（面板不折行、
    # 文字按自然宽溢出），False 才是默认的「按面板宽折行」。
    # 实测见 `归档文档 axure_rp8_plan.md` §9.11（折行族）。
    autofit_width: bool = False
    shape_autofit: bool = False        # 宿主形状自己的 `AutoFitWidth`（真机 A/B 见 plan §9.11）
    panel_box: tuple | None = None     # (x, y, w, h)：直接给标题面板几何；None = 用 Axure 自己排版的哨兵
    fill: int | None = None
    border: int | None = None
    border_width: float | None = None
    corner_radius: float = 0.0
    guid: uuid.UUID | None = None
    style_guid: uuid.UUID | None = None
    style_id: uuid.UUID | None = None
    panel_guid: uuid.UUID | None = None


@dataclass
class TextField:
    """一个输入框（Axure `Axure:DiagramObject:TextBox`）。

    真机配方（同一个骨架里的 `Text Field` 样例）：`TextBox` **没有**
    `ControlPoints` / `Shape`，比形状多 7 个键（`TextBlock` / `WordWrap` /
    `ShowBorder` / `ReadOnly` / `PlaceholderText` / `HideHintOnFocus` / `Type` /
    `MaxLength`），`PropList` 只发 SIZE + BASE_STYLE + LOCATION + FILL（+ 有字体
    信息时补那几条）；`Capabilities` 是输入框专属的位掩码。发布成
    `<div class="ax_default text_field"><input id="uN_input" type="text"/></div>`。
    """

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    label: str = ""
    text: str = ""                     # 输入框里的值（`TextBlock.text`）
    family: str = "Arial"
    size: float = 12.0
    weight: int = 400
    color: int = 0x333333
    align: int = 0
    wrap: bool = False
    show_border: bool = True
    read_only: bool = False
    placeholder: str = ""
    hide_hint_on_focus: bool = False
    field_type: int = 0
    max_length: int = 2147483647
    fill: int | None = None
    border: int | None = None
    border_width: float | None = None
    guid: uuid.UUID | None = None
    style_guid: uuid.UUID | None = None
    style_id: uuid.UUID | None = None


@dataclass
class Frame:
    """一个画板（= 一个 Axure 页面）。"""

    name: str = "Home"
    width: float = 800.0
    height: float = 600.0
    widgets: list = field(default_factory=list)
    package_guid: uuid.UUID | None = None


@dataclass
class DesignSpec:
    """一次生成任务的输入（= 若干画板）。"""

    frames: list = field(default_factory=list)


def _shape_props(shape, base_style_id, corner_radius):
    """形状 `PropList`（`Rect` 与 `Ellipse` 共用）。

    默认只发 SIZE + BASE_STYLE + LOCATION（与样本 `rect_a` 逐字节一致，颜色走
    `BASE_STYLE` 命中的库样式）；只有显式给了颜色/边框才追加那几条。`base_style_id`
    换成内置库的 `Ellipse` 就是圆的 `PropList`（圆发的槽位与矩形同序）。
    """
    props = [
        (constants.P_SIZE, ("dd", [("Width", ("f64", shape.width)),
                                   ("Height", ("f64", shape.height))])),
        (constants.P_BASE_STYLE, ("guid", base_style_id)),
    ]
    if shape.fill is not None:
        props.append((constants.P_FILL, ("dd", [("fill-type", ("str", "solid")),
                                                ("fill-color", ("int", constants.as_int32(shape.fill)))])))
    if shape.border is not None:
        props.append((constants.P_BORDER_FILL,
                      ("dd", [("fill-type", ("str", "solid")),
                              ("fill-color", ("int", constants.as_int32(shape.border)))])))
    if shape.border_width is not None:
        props.append((constants.P_BORDER_WIDTH, ("f64", shape.border_width)))
    if corner_radius:
        props.append((constants.P_CORNER_RADIUS, ("f64", corner_radius)))
    props.append((constants.P_LOCATION, ("dd", [("X", ("f64", shape.x)),
                                                ("Y", ("f64", shape.y))])))
    return props


def _corners(rect: Rect) -> tuple:
    """把 `corner_radius`(px) 归一化成 `model.control_points` 要的 (TL,TR,BR,BL)。"""
    if not rect.corner_radius:
        return (0.0, 0.0, 0.0, 0.0)
    x = rect.corner_radius / rect.width if rect.width else 0.0
    y = rect.corner_radius / rect.height if rect.height else 0.0
    value = max(x, y) if x != y else x
    return (value, value, value, value)


def rect_spec(rect: Rect) -> model.VectorShapeSpec:
    """`Rect` -> `VectorShapeSpec`。"""
    kwargs = {}
    if rect.guid is not None:
        kwargs["guid"] = rect.guid
    if rect.style_guid is not None:
        kwargs["style_guid"] = rect.style_guid
    if rect.style_id is not None:
        kwargs["style_id"] = rect.style_id
    return model.VectorShapeSpec(
        x=rect.x, y=rect.y, width=rect.width, height=rect.height,
        label=rect.label,
        props=_shape_props(rect, model.BOX_STYLE.style_id, rect.corner_radius),
        corners=_corners(rect), **kwargs)


def ellipse_spec(item: Ellipse) -> model.VectorShapeSpec:
    """`Ellipse` -> `VectorShapeSpec`：`Shape=15` + 4 点圆路径 + 内置 `Ellipse` 样式。"""
    kwargs = {}
    if item.guid is not None:
        kwargs["guid"] = item.guid
    if item.style_guid is not None:
        kwargs["style_guid"] = item.style_guid
    if item.style_id is not None:
        kwargs["style_id"] = item.style_id
    return model.VectorShapeSpec(
        x=item.x, y=item.y, width=item.width, height=item.height,
        label=item.label,
        props=_shape_props(item, model.ELLIPSE_STYLE.style_id, 0.0),
        ellipse=True, shape=constants.SHAPE_ELLIPSE,
        style_match=model.ELLIPSE_STYLE,
        capabilities=constants.ELLIPSE_CAPABILITIES, **kwargs)


def _pt(size_px: float) -> float:
    """px -> pt（Axure 文件里字号/行距是 pt，发布 HTML 时 x4/3 变回 px）。"""
    return round(size_px * 0.75, 4)


# `IMAGE(27)` 槽的 `Extension`：Axure 自己也不总是填（原生 3 个样本里 1 个是空串），
# 所以按 magic 判一次，判不出来就留空 —— 发布时不影响。
IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)


def image_extension(data: bytes) -> str:
    """按文件头判扩展名；认不出来返回空串（原生允许空串）。"""
    for magic, ext in IMAGE_MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ""


def image_bytes(data) -> bytes:
    """`bytes` / base64 字符串（可带 data URL 前缀）-> 原始字节。"""
    if data is None:
        return b""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    text = data.strip()
    if text.startswith("data:"):
        text = text.split(",", 1)[1] if "," in text else ""
    return base64.b64decode(text) if text else b""


def image_spec(item: Image) -> model.ImageBoxSpec:
    """`Image` -> `ImageBoxSpec`（样式走内置「图片」库样式）。"""
    kwargs = {}
    if item.guid is not None:
        kwargs["guid"] = item.guid
    if item.style_guid is not None:
        kwargs["style_guid"] = item.style_guid
    if item.style_id is not None:
        kwargs["style_id"] = item.style_id
    data = image_bytes(item.data)
    extension = image_extension(data) if item.extension is None else item.extension
    return model.ImageBoxSpec(
        x=item.x, y=item.y, width=item.width, height=item.height,
        label=item.label, stream=data, extension=extension,
        fit_to_image=item.fit_to_image, **kwargs)


def rich_text_panel_spec(item) -> model.RichTextPanelSpec:
    """`Text` / `Button` -> 子 `RichTextPanelSpec`（字段按名字取，两者共用）。

    `ContainedLocation` 取 (0,0)、尺寸取控件尺寸 —— 调用方（`button_spec`）会把
    按钮标题那三个值换成 Axure 的「自己排版」哨兵。
    """
    kwargs = {}
    if item.panel_guid is not None:
        kwargs["guid"] = item.panel_guid
    runs = getattr(item, "runs", None)
    if runs is not None:
        paragraphs = [list(paragraph) for paragraph in runs]
    else:
        style = (1 if item.italic else 0, item.underline)
        paragraphs = [[model.TextRun(text=line, family=item.family,
                                     size=_pt(item.size),
                                     weight=item.weight, style=style[0],
                                     underline=style[1], color=item.color)]
                      for line in (item.text.split("\n") if item.text else [""])]
    line_spacing = 0.0 if item.line_spacing is None else _pt(item.line_spacing)
    return model.RichTextPanelSpec(
        x=0.0, y=0.0, width=item.width, height=item.height,
        paragraphs=paragraphs, align=item.align, line_spacing=line_spacing,
        autofit_width=getattr(item, "autofit_width", False), **kwargs)


def _text_props(item, base_style_id=None):
    """带文字的宿主形状 `PropList`：几何 + 字体 + 对齐 + 填充/描边。

    `Text` 与 `Button` 共用（两者字段名一致）：`base_style_id` 缺省是 `Box 1`，
    按钮传内置库的 `Button`。

    **为什么字体要写在形状的 `Axure:Style` 里**：真机实测（`首页原型.rp`）——
    Axure 把 `FORE_GROUND_FILL` 发成 `#uN_div{color:...}`、`P20` 发成
    `line-height`，而 `Font/Size/Weight` 决定字号字体；`RichTextPanel` 的 `AxRun`
    只在**与形状样式不一致**时才补 inline `<span style>`。字号在文件里是 pt。
    """
    pad = 0.0 if item.pad is None else item.pad
    pad_left = getattr(item, "pad_left", None)
    if pad_left is None:
        pad_left = pad
    pad_right = getattr(item, "pad_right", None)
    if pad_right is None:
        pad_right = pad
    props = [
        (constants.P_SIZE, ("dd", [("Width", ("f64", item.width)),
                                   ("Height", ("f64", item.height))])),
        (constants.P_BASE_STYLE, ("guid", model.BOX_STYLE.style_id
                                  if base_style_id is None else base_style_id)),
        (constants.P_LOCATION, ("dd", [("X", ("f64", item.x)), ("Y", ("f64", item.y))])),
        (constants.P_ALIGN_V, ("int", item.v_align)),
        (constants.P_FONT_NAME, ("str", item.family)),
        (constants.P_FONT_SIZE, ("f64", _pt(item.size))),
        (constants.P_FONT_WEIGHT, ("int", item.weight)),
        (constants.P_FORE_GROUND_FILL,
         ("dd", [("fill-type", ("str", "solid")),
                 ("fill-color", ("int", constants.as_int32(item.color)))])),
        (constants.P_ALIGN_H, ("int", item.align)),
        (constants.P_PADDING_LEFT, ("f64", pad_left)),
        (constants.P_PADDING_TOP, ("f64", pad)),
        (constants.P_PADDING_RIGHT, ("f64", pad_right)),
        (constants.P_PADDING_BOTTOM, ("f64", pad)),
        (constants.P_BORDER_WIDTH, ("f64", 0.0 if item.border_width is None
                                    else item.border_width)),
        (constants.P_FILL,
         ("dd", [("fill-type", ("str", "solid")),
                 ("fill-color", ("int", constants.as_int32(
                     0x00FFFFFF if item.fill is None else item.fill)))])),
    ]
    if item.line_spacing is not None:
        props.append((constants.P_LINE_SPACING, ("f64", _pt(item.line_spacing))))
    if item.border is not None:
        props.append((constants.P_BORDER_FILL,
                      ("dd", [("fill-type", ("str", "solid")),
                              ("fill-color", ("int", constants.as_int32(item.border)))])))
    if item.corner_radius:
        props.append((constants.P_CORNER_RADIUS, ("f64", item.corner_radius)))
    return props


def text_spec(item: Text) -> model.VectorShapeSpec:
    """`Text` -> 宿主 `VectorShapeSpec`（文字面板挂在它的 `sub_objects` 上）。"""
    kwargs = {}
    if item.guid is not None:
        kwargs["guid"] = item.guid
    if item.style_guid is not None:
        kwargs["style_guid"] = item.style_guid
    if item.style_id is not None:
        kwargs["style_id"] = item.style_id
    shape = model.VectorShapeSpec(
        x=item.x, y=item.y, width=item.width, height=item.height,
        label=item.label, props=_text_props(item),
        autofit_width=getattr(item, "shape_autofit", False),
        corners=_corners(Rect(corner_radius=item.corner_radius,
                              width=item.width, height=item.height)), **kwargs)
    shape.sub_objects.append(rich_text_panel_spec(item))
    return shape


def button_spec(item: Button) -> model.VectorShapeSpec:
    """`Button` -> `VectorShapeSpec`（库样式 `Button` + 子 `RichTextPanel` 标题）。"""
    kwargs = {}
    if item.guid is not None:
        kwargs["guid"] = item.guid
    if item.style_guid is not None:
        kwargs["style_guid"] = item.style_guid
    if item.style_id is not None:
        kwargs["style_id"] = item.style_id
    shape = model.VectorShapeSpec(
        x=item.x, y=item.y, width=item.width, height=item.height,
        label=item.label,
        props=_text_props(item, model.BUTTON_STYLE.style_id),
        style_match=model.BUTTON_STYLE,
        autofit_width=getattr(item, "shape_autofit", False),
        corners=_corners(Rect(corner_radius=item.corner_radius,
                              width=item.width, height=item.height)), **kwargs)
    panel = rich_text_panel_spec(item)
    if item.panel_box is not None:
        # 直接给标题面板几何（不让 Axure 自己排版）：面板盒是**控件内相对坐标**。
        panel.x, panel.y, panel.width, panel.height = item.panel_box
    else:
        # 标题面板交给 Axure 自己排版（原生 Button 就是这两个哨兵值，见 constants）。
        panel.x = panel.y = constants.CAPTION_SENTINEL
        panel.width = panel.height = 0.0
    shape.sub_objects.append(panel)
    return shape


def text_field_spec(item: TextField) -> model.TextBoxSpec:
    """`TextField` -> `TextBoxSpec`（输入框：`PropList` 比形状少，`Capabilities` 专属）。"""
    kwargs = {}
    if item.guid is not None:
        kwargs["guid"] = item.guid
    if item.style_guid is not None:
        kwargs["style_guid"] = item.style_guid
    if item.style_id is not None:
        kwargs["style_id"] = item.style_id
    props = [
        (constants.P_SIZE, ("dd", [("Width", ("f64", item.width)),
                                   ("Height", ("f64", item.height))])),
        (constants.P_BASE_STYLE, ("guid", model.TEXT_FIELD_STYLE.style_id)),
        (constants.P_LOCATION, ("dd", [("X", ("f64", item.x)), ("Y", ("f64", item.y))])),
        (constants.P_FILL, ("dd", [("fill-type", ("str", "solid")),
                                   ("fill-color", ("int", constants.as_int32(
                                       constants.NO_COLOR if item.fill is None else item.fill)))])),
        (constants.P_FONT_NAME, ("str", item.family)),
        (constants.P_FONT_SIZE, ("f64", _pt(item.size))),
        (constants.P_FONT_WEIGHT, ("int", item.weight)),
        (constants.P_FORE_GROUND_FILL,
         ("dd", [("fill-type", ("str", "solid")),
                 ("fill-color", ("int", constants.as_int32(item.color)))])),
        (constants.P_ALIGN_H, ("int", item.align)),
    ]
    if item.border is not None:
        props.append((constants.P_BORDER_FILL,
                      ("dd", [("fill-type", ("str", "solid")),
                              ("fill-color", ("int", constants.as_int32(item.border)))])))
    if item.border_width is not None:
        props.append((constants.P_BORDER_WIDTH, ("f64", item.border_width)))
    return model.TextBoxSpec(
        x=item.x, y=item.y, width=item.width, height=item.height, label=item.label,
        text=item.text, wrap=item.wrap, show_border=item.show_border,
        read_only=item.read_only, placeholder=item.placeholder,
        hide_hint_on_focus=item.hide_hint_on_focus, field_type=item.field_type,
        max_length=item.max_length, props=props, **kwargs)


def widget_spec(widget):
    """控件 -> `model.*Spec` 分派（`Rect` / `Ellipse` / `Button` / `TextField` / `Text` / `Image`）。"""
    if isinstance(widget, Text):
        return text_spec(widget)
    if isinstance(widget, Image):
        return image_spec(widget)
    if isinstance(widget, Ellipse):
        return ellipse_spec(widget)
    if isinstance(widget, Button):
        return button_spec(widget)
    if isinstance(widget, TextField):
        return text_field_spec(widget)
    if isinstance(widget, Rect):
        return rect_spec(widget)
    raise TypeError("unsupported widget: %r" % (type(widget).__name__,))


def page_spec(frame: Frame) -> model.PageSpec:
    """`Frame` -> `model.PageSpec`（GUID 缺省即新生成）。"""
    kwargs = {}
    if frame.package_guid is not None:
        kwargs["package_guid"] = frame.package_guid
    return model.PageSpec(
        name=frame.name, width=frame.width, height=frame.height,
        widgets=[widget_spec(w) for w in frame.widgets],
        interaction_events=list(constants.PAGE_EVENTS), **kwargs)


def build(spec: DesignSpec, seed=None, random_guids: bool = False) -> list:
    """`DesignSpec` -> 一串 `model.PageSpec`（顺序 = 页面顺序）。

    进来先把 GUID 发生器归零，所以**同一份 spec 连生两次，GUID 序列相同**、`.rp`
    逐字节相同（P5，见 `归档文档 axure_rp8_plan.md` §9.14）。`seed` 换一批 GUID、
    `random_guids=True` 退回真随机（要每次都不一样时才用）。
    """
    model.reset_guids(seed=seed, random=random_guids)
    return [page_spec(frame) for frame in spec.frames]
