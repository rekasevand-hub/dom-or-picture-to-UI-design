"""Axure RP 8 对象图构造器：`StreamBuilder` + 页面/控件发射配方。

**为什么发射顺序重要**：名字池与 GUID 池都是「首次用到就分配」，所以池的顺序
== 发射顺序。按本模块的顺序发射，可以逐字节复刻 Axure 自己写出来的页面流
（见 `tests/test_axure_rp8_gen.py::test_reproduce_sample_page`）。

描述符（descriptor）是一门很小的**惰性**值语言：`build()` 在构造条目的同时
按「先 key 后 value」的顺序登记池，因此嵌套描述符也能复刻 Axure 的池顺序。

    ("str", "Arial")            -> tag 8
    ("int", 5) ("f64", 1.0) ("f32", 2.0) ("bool", True) ("i64", -1)
    ("guid", uuid|bytes)        -> tag 17
    ("ref", uuid|bytes)         -> tag 3
    ("fx", "Axure:Page", guid)  -> tag 19
    ("ah", None, guid)          -> tag 16
    ("blob", b"...")            -> tag 4
    ("list", [desc, ...])       -> tag 2
    ("dd", [(key, desc), ...])  -> tag 1
    ("obj", "Axure:Page", guid, body_desc)
"""
from __future__ import annotations

import base64
import hashlib
import uuid
from dataclasses import dataclass, field

from . import c1
from .constants import (
    AXURE_DEFAULT_STYLE_ID,
    BOX_STYLE_ID,
    BOX_STYLE_NAME,
    BUTTON_STYLE_ID,
    BUTTON_STYLE_NAME,
    BUTTON_STYLE_PROPS,
    DEFAULT_LIBRARY_ID,
    DEFAULT_LIBRARY_NAME,
    DEFAULT_STYLE_NAME,
    DEFAULT_STYLE_PROPS,
    ELLIPSE_HANDLE_OFFSET,
    ELLIPSE_STYLE_ID,
    ELLIPSE_STYLE_NAME,
    IMAGE_BOX_CAPABILITIES,
    IMAGE_BOX_STYLE_ID,
    IMAGE_BOX_STYLE_NAME,
    PAGE_STYLE_CAPABILITIES,
    P_BASE_STYLE,
    P_FILL,
    P_IMAGE,
    P_LOCATION,
    P_SIZE,
    STYLE_CAPABILITIES,
    TEXT_FIELD_CAPABILITIES,
    TEXT_FIELD_STYLE_ID,
    TEXT_FIELD_STYLE_NAME,
    TEXT_FIELD_STYLE_PROPS,
    as_int32,
    doa,
)

# Axure 把「无把手」写成 f64 的**负** NaN（0xfff8000000000000），不是 Python 默认的正 NaN。
NAN = -float("nan")

PAGE_KIND = "Axure:Page"
DIAGRAM_KIND = "Axure:Diagram"
SHAPE_KIND = "Axure:DiagramObject:VectorShape"
RICH_TEXT_PANEL_KIND = "Axure:DiagramObject:RichTextPanel"
IMAGE_BOX_KIND = "Axure:DiagramObject:ImageBox"
TEXT_BOX_KIND = "Axure:DiagramObject:TextBox"
RICH_TEXT_BLOCK_TYPE = "rich-text-block"
RICH_TEXT_OBJECT_TYPE = "rich-text-object"
AXRUN_TYPE = "Axure:AttributedString:AxRun"
STYLE_KIND = "Axure:Style"
PAGE_STYLE_KIND = "Axure:PageStyle"
ANNOTATION_KIND = "Axure:Annotation"
TREE_MAP_KIND = "Axure:InteractionTreeMap"
TREE_KIND = "Axure:Tree"
NODE_KIND = "Axure:Node"
EVENT_KIND = "Axure:InteractionEvent"
RULER_KIND = "Axure:RulerGuideSet"


def guid_bytes(value) -> bytes:
    """`uuid.UUID` / `bytes` / 字符串 -> 16 字节 little-endian（.NET Guid 序）。"""
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if len(raw) != 16:
            raise ValueError("guid must be 16 bytes, got %d" % len(raw))
        return raw
    if isinstance(value, uuid.UUID):
        return value.bytes_le
    return uuid.UUID(str(value)).bytes_le


# ---------------------------------------------------------------- GUID 发生器
#
# 默认是**确定性**的：GUID 由 (seed, 计数器) 的 sha256 派生，形状与 v4 相同
# （版本 4 + RFC 4122 variant），所以同一份 `DesignSpec` 连生两次的 `.rp`
# 逐字节相同（P5，见 `归档文档 axure_rp8_plan.md` §9.14）。计数器由 `reset_guids()`
# 归零，而 `doc.build()` 每份文档开头都会调一次。
GUID_SEED = "axure-rp8"

_guid_counter = 0
_guid_seed = GUID_SEED
_guid_random = False


def reset_guids(seed=None, random: bool = False) -> None:
    """重置 GUID 发生器（每生成一份文档前调用；`doc.build()` 已经代劳）。

    默认回到确定性模式：同一 `seed` + 同样的生成调用序列 -> 同样的 GUID 序列。不传 `seed`
    就是默认流 `GUID_SEED` —— **`seed` 只作用于这一次生成**，不留在模块状态里影响后面的调用
    （否则同一份 IR 在「先跑过别的 seed」的进程里产出的字节就不一样：曾实测 923989 -> 924005 B）。
    `random=True` 时退回真正的 `uuid.uuid4()`（要每次都不一样才显式打开）。
    """
    global _guid_counter, _guid_seed, _guid_random
    _guid_counter = 0
    _guid_random = bool(random)
    _guid_seed = GUID_SEED if seed is None else str(seed)


def new_guid() -> uuid.UUID:
    """新 GUID：确定性模式下取 (seed, 计数器) 的 sha256 前 16 字节。"""
    global _guid_counter
    if _guid_random:
        return uuid.uuid4()
    _guid_counter += 1
    raw = bytearray(hashlib.sha256(
        ("%s:%d" % (_guid_seed, _guid_counter)).encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40          # 版本 4
    raw[8] = (raw[8] & 0x3F) | 0x80          # RFC 4122 variant
    return uuid.UUID(bytes=bytes(raw))


class StreamBuilder:
    """c1 流构造器：负责名字池 / GUID 池与条目发射。"""

    def __init__(self, version=c1.OBJ_VERSION):
        self.version = version
        self._names = [None]
        self._name_index = {}
        self._guids = [None]
        self._guid_index = {}
        self.items = []

    @classmethod
    def seeded(cls, version, names, guids, items=None):
        """用一条已存在流的池初始化构造器。

        池只会在**尾部**增长，所以原有条目的下标仍然有效；`items` 若给出则作为
        起始条目列表原样保留（用于在已有对象图里增删对象，如改写注册表）。
        """
        b = cls(version)
        b._names = list(names)
        b._name_index = {}
        for i, n in enumerate(b._names):
            if i > 0 and n not in b._name_index:
                b._name_index[n] = i
        b._guids = list(guids)
        b._guid_index = {}
        for i, g in enumerate(b._guids):
            if i > 0 and g not in b._guid_index:
                b._guid_index[g] = i
        b.items = list(items) if items else []
        return b

    @property
    def names(self):
        return self._names

    @property
    def guids(self):
        return self._guids

    # --- 池（首次使用即分配）----------------------------------------
    def name_id(self, text: str) -> int:
        idx = self._name_index.get(text)
        if idx is None:
            self._names.append(text)
            idx = len(self._names) - 1
            self._name_index[text] = idx
        return idx

    def guid_id(self, value) -> int:
        key = guid_bytes(value)
        idx = self._guid_index.get(key)
        if idx is None:
            self._guids.append(key)
            idx = len(self._guids) - 1
            self._guid_index[key] = idx
        return idx

    # --- 叶子条目 ---------------------------------------------------
    def str_(self, text):
        return [c1.T_STR, self.name_id(text), c1.T_STR]

    def int_(self, value):
        return [c1.T_INT, int(value), c1.T_INT]

    def f64_(self, value):
        return [c1.T_F64, float(value), c1.T_F64]

    def f32_(self, value):
        return [c1.T_F32, float(value), c1.T_F32]

    def bool_(self, value):
        return [c1.T_BOOL, 1 if value else 0, c1.T_BOOL]

    def i64_(self, value):
        return [c1.T_I64, int(value), c1.T_I64]

    def blob_(self, data):
        return [c1.T_BLOB, bytes(data), c1.T_BLOB]

    def guid_(self, value):
        return [c1.T_GUID, self.guid_id(value), c1.T_GUID]

    def ref_(self, value):
        return [c1.T_REF, self.guid_id(value), c1.T_REF]

    def fx_(self, type_name, value):
        return [c1.T_FX, self.name_id(type_name), self.guid_id(value), c1.T_FX]

    def ah_(self, name, value):
        return [c1.T_AH, 0 if name is None else self.name_id(name),
                self.guid_id(value), c1.T_AH]

    def dd_(self, pairs):
        return [c1.T_DD, list(pairs), c1.T_DD]

    def list_(self, items):
        return [c1.T_LIST, list(items), c1.T_LIST]

    def obj_(self, type_name, guid, body_desc):
        # 池顺序：先登记对象 GUID 与类型名，再构造 body —— 与 Axure 一致。
        gid = self.guid_id(guid)
        nid = self.name_id(type_name)
        return [c1.T_OBJ, gid, nid, self.build(body_desc), c1.T_OBJ]

    def pkgctx_(self, root_guid, package_guid):
        return [c1.T_PKGCTX, 15, self.guid_id(root_guid),
                18, self.guid_id(package_guid), c1.T_PKGCTX]

    def end_(self):
        return [c1.T_END, c1.T_END]

    def add(self, item):
        self.items.append(item)
        return item

    def add_end(self):
        """追加流结尾（tag 28）。"""
        return self.add(self.end_())

    # --- 描述符 -----------------------------------------------------
    def build(self, desc):
        kind = desc[0]
        if kind == "str":
            return self.str_(desc[1])
        if kind == "int":
            return self.int_(desc[1])
        if kind == "f64":
            return self.f64_(desc[1])
        if kind == "f32":
            return self.f32_(desc[1])
        if kind == "bool":
            return self.bool_(desc[1])
        if kind == "i64":
            return self.i64_(desc[1])
        if kind == "guid":
            return self.guid_(desc[1])
        if kind == "ref":
            return self.ref_(desc[1])
        if kind == "fx":
            return self.fx_(desc[1], desc[2])
        if kind == "ah":
            return self.ah_(desc[1], desc[2])
        if kind == "blob":
            return self.blob_(desc[1])
        if kind == "list":
            return self.list_([self.build(x) for x in desc[1]])
        if kind == "dd":
            # key 可以是字符串（自动成为 str 条目）或描述符；池顺序统一为「先 key 后 value」。
            pairs = []
            for key, value in desc[1]:
                key_item = self.str_(key) if isinstance(key, str) else self.build(key)
                pairs.append((key_item, self.build(value)))
            return self.dd_(pairs)
        if kind == "obj":
            return self.obj_(desc[1], desc[2], desc[3])
        raise ValueError("unknown descriptor %r" % (kind,))

    def to_bytes(self):
        return c1.serialize(self.version, self._names, self._guids, self.items)


# --------------------------------------------------------------------------- 规格

@dataclass(frozen=True)
class StyleMatch:
    """命中的文档级样式（`DesignDocument.StyleSheet` 里的具名样式）。"""

    library_id: uuid.UUID = DEFAULT_LIBRARY_ID
    library_name: str = DEFAULT_LIBRARY_NAME
    style_id: uuid.UUID = BOX_STYLE_ID
    name: str = BOX_STYLE_NAME


BOX_STYLE = StyleMatch()
LOCAL_STYLE = StyleMatch(library_id=uuid.UUID(int=0), library_name="",
                         style_id=AXURE_DEFAULT_STYLE_ID, name=DEFAULT_STYLE_NAME)
# 图片控件命中的内置库样式（`Default` 库里的「图片」）。
IMAGE_BOX_STYLE = StyleMatch(style_id=IMAGE_BOX_STYLE_ID, name=IMAGE_BOX_STYLE_NAME)
# 圆控件命中的内置库样式（`Default` 库里的 `Ellipse`）。
ELLIPSE_STYLE = StyleMatch(style_id=ELLIPSE_STYLE_ID, name=ELLIPSE_STYLE_NAME)
# 按钮 / 输入框命中的内置库样式（`Default` 库的 `Button` / `Text Field`）。
# 按钮仍是 `VectorShape`（`Shape = 0`），输入框是 `TextBox`；发布出的 CSS 类名
# 直接取自这里的 `Name`（`Button` -> `button`、`Text Field` -> `text_field`）。
BUTTON_STYLE = StyleMatch(style_id=BUTTON_STYLE_ID, name=BUTTON_STYLE_NAME)
TEXT_FIELD_STYLE = StyleMatch(style_id=TEXT_FIELD_STYLE_ID, name=TEXT_FIELD_STYLE_NAME)

# 项目样式表（`DesignDocument.StyleSheet.CustomStyles`）里必须存在的两条。Axure 按
# **样式名**给发布出的元素加 CSS 类（`.button` / `.text_field`），模板 `base_native.rp`
# 里没有这两条，所以 `writer` 改 `DesignDocument` 时补进去（已存在则跳过）。
STYLE_SHEET_EXTRAS = (
    (BUTTON_STYLE_NAME, BUTTON_STYLE_ID, BUTTON_STYLE_PROPS),
    (TEXT_FIELD_STYLE_NAME, TEXT_FIELD_STYLE_ID, TEXT_FIELD_STYLE_PROPS),
)


# `IMAGE(27)` 槽里的 `Hash` = `base64(md5(原始字节))`（原生 3/3 命中，逐字节相同）。
def image_hash(blob: bytes) -> str:
    return base64.b64encode(hashlib.md5(blob).digest()).decode("ascii")


@dataclass
class TextRun:
    """`Axure:AttributedString:AxRun`：一段同格式的文字。

    **样式全在这里**（`Family` / `Size` / `Weight` / `Style` / `Stretch` /
    `Underline` / `Color`），不在 `Axure:Style` 的 `PropList` 里 —— 实测
    `RichTextPanel` 连 `MyStyle` 都没有。
    """

    text: str = ""
    family: str = "Arial"
    size: float = 10.5
    weight: int = 400          # 400 = regular, 700 = bold
    style: int = 0             # 0 = upright（斜体映射未实测）
    stretch: int = 5           # 实测常量
    underline: bool = False
    color: int = 0xFF333333    # 有符号 int32 落盘，见 constants.as_int32


@dataclass
class RichTextPanelSpec:
    """`Axure:DiagramObject:RichTextPanel`：**形状的子对象**，承载文字。

    实测（`首页原型.rp`，8.0.0.3400）：126 个面板**全部**挂在某个
    `VectorShape` / `Layer` 的 `diagram-objects` 下，没有顶层面板；dd 只有 9 个键
    （`name-block` / `tooltip` / `IsContained` / `IsLocked` / `SelectedStyleGroup` /
    `ContainedLocation` / `ContainedSize` / `rtf-block` / `AutoFitWidth`），
    既没有 `ControlPoints` 也没有 `MyStyle` / `Annotation`。
    """

    guid: uuid.UUID = field(default_factory=new_guid)
    x: float = 0.0                       # ContainedLocation.X（父形状内相对坐标）
    y: float = 0.0                       # ContainedLocation.Y
    width: float = 0.0                   # ContainedSize.Width
    height: float = 0.0                  # ContainedSize.Height
    paragraphs: list = field(default_factory=list)   # list[list[TextRun]]
    label: str = ""                      # name-block.text（**对象名**，不是内容）
    align: int = 0                       # Paragraph.HorizontalAlignment
    line_spacing: float = 0.0            # Paragraph.LineSpacing
    autofit_width: bool = False
    sub_objects: list = field(default_factory=list)


@dataclass
class VectorShapeSpec:
    """一个形状控件（`Axure:DiagramObject:VectorShape`）+ 它的 `Axure:Style`。"""

    guid: uuid.UUID = field(default_factory=new_guid)
    style_guid: uuid.UUID = field(default_factory=new_guid)
    style_id: uuid.UUID = field(default_factory=new_guid)
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    label: str = ""
    style_match: StyleMatch = BOX_STYLE
    kind: str = SHAPE_KIND
    shape: int = 0
    props: list | None = None
    sub_objects: list = field(default_factory=list)   # M4：文字面板等
    corners: tuple = (0.0, 0.0, 0.0, 0.0)             # (TL,TR,BR,BL) 归一化半径
    ellipse: bool = False                             # 圆：ControlPoints 走 4 点圆路径
    capabilities: int = STYLE_CAPABILITIES            # 按控件类型给（见 constants）
    autofit_width: bool = False                       # 控件自己的 `AutoFitWidth`（原生 Label 是 1）

    def prop_list(self):
        """[(PName, desc)]；默认 = SIZE + BASE_STYLE + LOCATION（与样本一致）。"""
        if self.props is not None:
            return self.props
        return [
            (P_SIZE, ("dd", [("Width", ("f64", self.width)),
                             ("Height", ("f64", self.height))])),
            (P_BASE_STYLE, ("guid", self.style_match.style_id)),
            (P_LOCATION, ("dd", [("X", ("f64", self.x)), ("Y", ("f64", self.y))])),
        ]


@dataclass
class ImageBoxSpec:
    """一个图片控件（`Axure:DiagramObject:ImageBox`）+ 它的 `Axure:Style`。

    实测（`首页原型.rp`，8.0.0.3400，3 个样本）：

    * 对象 dd 有 **17 个键**，与 `VectorShape` 的差别是：**没有** `ControlPoints` /
      `Shape` / `reference-page-package-id`，多了 `PreserveCornersRectangle` 与
      `fit-to-image`（键序见 `image_box_descriptor`）。
    * 图在 `Axure:Style.PropList` 的 `IMAGE(27)` 槽：`{Stream: blob, Extension: str,
      Hash: str}`；`Hash = base64(md5(blob))`（3/3 逐字节命中）。
    * `Extension` 可以是空串（原生第 1 个样本就是空串，字节仍是 PNG）——发布不看它，
      所以这里按 magic 判，判不出来才留空。
    * 发布出来的 HTML 是 `<div class="ax_default _图片"><img src="images/<page>/uN.png"/></div>`，
      **没有** `uN_div` 子元素；落盘的 PNG 与 `Stream` 逐字节相同（Axure 不重编码）。
    """

    guid: uuid.UUID = field(default_factory=new_guid)
    style_guid: uuid.UUID = field(default_factory=new_guid)
    style_id: uuid.UUID = field(default_factory=new_guid)
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    label: str = ""
    stream: bytes = b""                                 # 原始图片字节
    extension: str = ""                                 # '.png' / '.jpg' / ''（空也合法）
    fit_to_image: bool = False                          # `fit-to-image`
    style_match: StyleMatch = IMAGE_BOX_STYLE
    kind: str = IMAGE_BOX_KIND
    capabilities: int = IMAGE_BOX_CAPABILITIES
    sub_objects: list = field(default_factory=list)

    def prop_list(self):
        """[(PName, desc)]：原生 `ImageBox` 的槽序是 BASE_STYLE -> SIZE -> LOCATION -> IMAGE。"""
        return [
            (P_BASE_STYLE, ("guid", self.style_match.style_id)),
            (P_SIZE, ("dd", [("Width", ("f64", self.width)),
                             ("Height", ("f64", self.height))])),
            (P_LOCATION, ("dd", [("X", ("f64", self.x)), ("Y", ("f64", self.y))])),
            (P_IMAGE, ("dd", [("Stream", ("blob", self.stream)),
                              ("Extension", ("str", self.extension)),
                              ("Hash", ("str", image_hash(self.stream)))])),
        ]


@dataclass
class TextBoxSpec:
    """一个输入框控件（`Axure:DiagramObject:TextBox`）+ 它的 `Axure:Style`。

    真机配方（`skeleton.rp（v1 资产，已删；发布副本在 output/_axure_oracle/skelref/）`，Axure 自己造的 `Text Field` 样例）：

    * `TextBox` **没有** `ControlPoints` / `Shape` / `reference-page-package-id`，
      比形状多 7 个键（键序见 `text_box_descriptor`）：`TextBlock` / `WordWrap` /
      `ShowBorder` / `ReadOnly` / `PlaceholderText` / `HideHintOnFocus` / `Type` /
      `MaxLength`。
    * `TextBlock` = `{*type: 'text-block', text: <输入框里的文字>,
      property-dictionary: {type: 'plain-text-object', diagram-object-label: '',
      text-object-id: <自身 guid>, parent-diagram-id: <页面 diagram guid>}}`；
      原生样例里 `txt` 是空串。
    * `PropList` = SIZE / BASE_STYLE / LOCATION / FILL（原生还多一条 `IX_STYLES(21)`
      指向 Hint 样式；我们没有 Hint，不发）。
    * `Capabilities` 与所有形状都不同（`constants.TEXT_FIELD_CAPABILITIES`）。
    * 发布形态：`<div class="ax_default text_field"><input id="uN_input" type="text"
      value=""/></div>` —— 视觉全在 `#uN_input` 上，**没有** `uN_div` 子元素。
    """

    guid: uuid.UUID = field(default_factory=new_guid)
    style_guid: uuid.UUID = field(default_factory=new_guid)
    style_id: uuid.UUID = field(default_factory=new_guid)
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    label: str = ""
    text: str = ""                      # TextBlock.text（输入框当前值）
    wrap: bool = False                  # WordWrap
    show_border: bool = True            # ShowBorder
    read_only: bool = False             # ReadOnly
    placeholder: str = ""               # PlaceholderText
    hide_hint_on_focus: bool = False    # HideHintOnFocus
    field_type: int = 0                 # Type（0 = 单行文本）
    max_length: int = 2147483647        # MaxLength（原生默认值）
    style_match: StyleMatch = TEXT_FIELD_STYLE
    kind: str = TEXT_BOX_KIND
    capabilities: int = TEXT_FIELD_CAPABILITIES
    props: list | None = None           # [(PName, desc)]；None = 默认槽序
    sub_objects: list = field(default_factory=list)

    def prop_list(self):
        """[(PName, desc)]：原生槽序 = SIZE -> BASE_STYLE -> LOCATION -> FILL。"""
        if self.props is not None:
            return self.props
        return [
            (P_SIZE, ("dd", [("Width", ("f64", self.width)),
                             ("Height", ("f64", self.height))])),
            (P_BASE_STYLE, ("guid", self.style_match.style_id)),
            (P_LOCATION, ("dd", [("X", ("f64", self.x)), ("Y", ("f64", self.y))])),
            (P_FILL, ("dd", [("fill-type", ("str", "solid")),
                             ("fill-color", ("int", as_int32(0xFFFFFFFF)))])),
        ]


@dataclass
class PageSpec:
    """一个 Axure 页面包（= 一个 frame/画板）。"""

    package_guid: uuid.UUID = field(default_factory=new_guid)
    page_object_guid: uuid.UUID = field(default_factory=new_guid)
    diagram_guid: uuid.UUID = field(default_factory=new_guid)
    page_style_guid: uuid.UUID = field(default_factory=new_guid)
    page_style_id: uuid.UUID = field(default_factory=new_guid)
    annotation_guid: uuid.UUID = field(default_factory=new_guid)
    interaction_guid: uuid.UUID = field(default_factory=new_guid)
    tree_guid: uuid.UUID = field(default_factory=new_guid)
    ruler_guid: uuid.UUID = field(default_factory=new_guid)
    name: str = "Home"
    width: float = 800.0
    height: float = 600.0
    widgets: list = field(default_factory=list)
    style_cache: bool = True
    # `interactionmap` 里为控件登记的事件类型。留空 = 空树（M2 最小形态）。
    interaction_events: list = field(default_factory=list)
    node_guids: list = field(default_factory=list)
    event_guids: list = field(default_factory=list)


def _point(x, y):
    handle = lambda: ("dd", [("X", ("f64", NAN)), ("Y", ("f64", NAN))])
    return ("dd", [
        ("Path", ("dd", [("X", ("f64", x)), ("Y", ("f64", y))])),
        ("LowerHandle", handle()),
        ("HigherHandle", handle()),
        ("HigherSegmentExists", ("bool", True)),
    ])


def control_points(corners=(0.0, 0.0, 0.0, 0.0)):
    """形状轮廓：直角矩形 = 4 点；有圆角 = 8 点（每条边 + 每个角各一点）。"""
    if not any(corners):
        pts = [_point(0.0, 0.0), _point(1.0, 0.0), _point(1.0, 1.0), _point(0.0, 1.0)]
    else:
        tl, tr, br, bl = corners
        pts = [_point(tl, 0.0), _point(1.0 - tr, 0.0), _point(1.0, tr),
               _point(1.0, 1.0 - br), _point(1.0 - br, 1.0), _point(bl, 1.0),
               _point(0.0, 1.0 - bl), _point(0.0, tl)]
    return ("list", [("list", pts)])


def _handle_point(x, y, lower, higher):
    """一个 Path 点 + 它的两个**真**把手（`_point` 那种 NaN 把手是「无把手」）。"""
    def handle(px, py):
        return ("dd", [("X", ("f64", px)), ("Y", ("f64", py))])
    return ("dd", [
        ("Path", handle(x, y)),
        ("LowerHandle", handle(lower[0], lower[1])),
        ("HigherHandle", handle(higher[0], higher[1])),
        ("HigherSegmentExists", ("bool", True)),
    ])


def ellipse_control_points():
    """圆的轮廓 = **4 点贝塞尔**（原生 `Ellipse` 逐值实测，见 constants）。

    `Shape = 15` 由 `shape_descriptor` 单独发；这里只给轮廓。把手沿切线方向
    偏 `ELLIPSE_HANDLE_OFFSET`（`Lower` 在后、`Higher` 在前，按 (0.5,0) ->
    (1,0.5) -> (0.5,1) -> (0,0.5) 的顺时针序），**不是** NaN。
    """
    o = ELLIPSE_HANDLE_OFFSET
    points = [
        _handle_point(0.5, 0.0, (0.5 - o, 0.0), (0.5 + o, 0.0)),
        _handle_point(1.0, 0.5, (1.0, 0.5 - o), (1.0, 0.5 + o)),
        _handle_point(0.5, 1.0, (0.5 + o, 1.0), (0.5 - o, 1.0)),
        _handle_point(0.0, 0.5, (0.0, 0.5 + o), (0.0, 0.5 - o)),
    ]
    return ("list", [("list", points)])


def attributed_string_descriptor(spec: RichTextPanelSpec):
    """`attributed-string`：Version + Paragraphs（每段一把 AxRun）。"""
    major, minor, build, revision = c1.OBJ_VERSION[:4]
    paragraphs = []
    for runs in spec.paragraphs:
        inlines = [("dd", [
            ("Type", ("str", AXRUN_TYPE)),
            ("Text", ("str", run.text)),
            ("Family", ("str", run.family)),
            ("Size", ("f64", run.size)),
            ("Weight", ("int", run.weight)),
            ("Style", ("int", run.style)),
            ("Stretch", ("int", run.stretch)),
            ("Underline", ("bool", run.underline)),
            ("Color", ("int", as_int32(run.color))),
        ]) for run in runs]
        paragraphs.append(("dd", [
            ("HorizontalAlignment", ("int", spec.align)),
            ("LineSpacing", ("f64", spec.line_spacing)),
            ("Inlines", ("list", inlines)),
        ]))
    return ("dd", [
        ("Version", ("dd", [("Major", ("int", major)), ("Minor", ("int", minor)),
                            ("Build", ("int", build)), ("Revision", ("int", revision))])),
        ("Paragraphs", ("list", paragraphs)),
    ])


def rich_text_panel_descriptor(spec: RichTextPanelSpec, diagram_guid):
    """`Axure:DiagramObject:RichTextPanel` 的 dd 描述符（键序 = 实测键序）。"""
    return ("dd", [
        ("name-block", ("dd", [
            ("*type", ("str", "text-block")),
            ("text", ("str", spec.label)),
            ("property-dictionary", ("dd", [
                ("type", ("str", "label")),
                ("diagram-object-id", ("guid", spec.guid)),
                ("parent-diagram-id", ("guid", diagram_guid)),
            ])),
        ])),
        ("tooltip", ("str", "")),
        ("IsContained", ("bool", True)),
        ("IsLocked", ("bool", False)),
        ("SelectedStyleGroup", ("str", "")),
        ("ContainedLocation", ("dd", [("X", ("f64", spec.x)), ("Y", ("f64", spec.y))])),
        ("ContainedSize", ("dd", [("Width", ("f64", spec.width)),
                                  ("Height", ("f64", spec.height))])),
        ("rtf-block", ("dd", [
            ("*type", ("str", RICH_TEXT_BLOCK_TYPE)),
            ("attributed-string", attributed_string_descriptor(spec)),
            ("property-dictionary", ("dd", [
                ("type", ("str", RICH_TEXT_OBJECT_TYPE)),
                ("diagram-object-label", ("str", "")),
                ("text-object-id", ("guid", spec.guid)),
                ("parent-diagram-id", ("guid", diagram_guid)),
            ])),
        ])),
        ("AutoFitWidth", ("bool", spec.autofit_width)),
    ])


def shape_descriptor(spec: VectorShapeSpec, diagram_guid):
    """`Axure:DiagramObject:<Class>` 的 dd 描述符。"""
    return ("dd", [
        ("ControlPoints", ellipse_control_points() if spec.ellipse
                          else control_points(spec.corners)),
        ("Shape", ("int", spec.shape)),
        ("reference-page-package-id", ("fx", PAGE_KIND, c1.NULL_GUID)),
        ("AutoFitHeight", ("bool", False)),
        ("AutoFitWidth", ("bool", spec.autofit_width)),
        ("name-block", ("dd", [
            ("*type", ("str", "text-block")),
            ("text", ("str", spec.label)),
            ("property-dictionary", ("dd", [
                ("type", ("str", "label")),
                ("diagram-object-id", ("guid", spec.guid)),
                ("parent-diagram-id", ("guid", diagram_guid)),
            ])),
        ])),
        ("tooltip", ("str", "")),
        ("IsContained", ("bool", False)),
        ("IsLocked", ("bool", False)),
        ("SelectedStyleGroup", ("str", "")),
        ("Annotation", ("ref", c1.NULL_GUID)),
        ("MyStyle", ("ref", spec.style_guid)),
        ("AdaptiveStyles", ("list", [])),
        ("SubmitButton", ("ref", c1.NULL_GUID)),
        ("Disabled", ("bool", False)),
        ("Selected", ("bool", False)),
        ("VisibleFromSettings", ("bool", True)),
        ("diagram-objects", ("list", [("ref", child.guid)
                                        for child in spec.sub_objects])),
    ])


def style_descriptor(spec: VectorShapeSpec):
    """`Axure:Style` 的 dd 描述符（几何/颜色/字体都在这条的 `PropList`）。"""
    match = spec.style_match
    prop_items = [("dd", [("DOAName", ("int", doa(pname))), ("Value", desc)])
                  for pname, desc in spec.prop_list()]
    return ("dd", [
        ("LibraryId", ("guid", match.library_id)),
        ("LibraryName", ("str", match.library_name)),
        ("MatchInfo", ("dd", [
            ("LibraryId", ("guid", match.library_id)),
            ("LibraryName", ("str", match.library_name)),
            ("Id", ("guid", match.style_id)),
            ("Name", ("str", match.name)),
        ])),
        ("LegacyName", ("str", "")),
        ("style-name", ("str", "MyStyle-" + spec.kind)),
        ("Id", ("guid", spec.style_id)),
        ("PropList", ("list", prop_items)),
        ("Capabilities", ("i64", spec.capabilities)),
        ("All", ("bool", False)),
    ])


def style_cache_descriptor():
    """`StyleCache.Styles`：[命中的库样式, 生效的 Default 样式]（复刻样本形状）。"""
    first = ("dd", [
        ("Info", ("dd", [
            ("LibraryId", ("guid", BOX_STYLE.library_id)),
            ("LibraryName", ("str", BOX_STYLE.library_name)),
            ("Id", ("guid", BOX_STYLE.style_id)),
            ("Name", ("str", BOX_STYLE.name)),
        ])),
        ("Props", ("list", [])),
    ])
    props = [("dd", [("DOAName", ("int", doa(pname))), ("Value", desc)])
             for pname, desc in DEFAULT_STYLE_PROPS]
    second = ("dd", [
        ("Info", ("dd", [
            ("LibraryId", ("guid", LOCAL_STYLE.library_id)),
            ("LibraryName", ("str", LOCAL_STYLE.library_name)),
            ("Id", ("guid", LOCAL_STYLE.style_id)),
            ("Name", ("str", LOCAL_STYLE.name)),
        ])),
        ("Props", ("list", props)),
    ])
    return [first, second]


def style_sheet_entry_descriptor(name, style_id, props):
    """`DesignDocument.StyleSheet.CustomStyles` 里的一个具名样式（原生键序）。

    **为什么要在意**：Axure 发布时按控件命中的**样式名**给元素加 CSS 类
    （`Button` -> `class="ax_default button"`）；样式名得能从项目样式表里查到，
    查不到就只发 `class="ax_default"`（真机 m8ctl 实测，见
    `归档文档 axure_rp8_format.md` §11.8）。模板 `base_native.rp` 里没有
    `Button` / `Text Field`，所以由 `writer` 在改写 `DesignDocument` 时补上。

    与页面级 `Axure:Style` 的两处差别（原生样式表条目实测）：没有 `MatchInfo`；
    `Capabilities = -1`。`PropList` 的 `DOAName` 是**原始 int32**（大多只带
    `0x80000000` 位），所以 `props` 直接给 `(DOAName, 值描述符)`，不过 `doa()`。
    """
    rows = [("dd", [("DOAName", ("int", pname)), ("Value", desc)])
            for pname, desc in props]
    return ("dd", [
        ("LibraryId", ("guid", DEFAULT_LIBRARY_ID)),
        ("LibraryName", ("str", DEFAULT_LIBRARY_NAME)),
        ("LegacyName", ("str", "")),
        ("style-name", ("str", name)),
        ("Id", ("guid", style_id)),
        ("PropList", ("list", rows)),
        ("Capabilities", ("i64", -1)),
        ("All", ("bool", True)),
    ])

def image_box_descriptor(spec: ImageBoxSpec, diagram_guid):
    """`Axure:DiagramObject:ImageBox` 的 dd 描述符（17 键，键序 = 实测键序）。"""
    return ("dd", [
        ("AutoFitHeight", ("bool", False)),
        ("AutoFitWidth", ("bool", False)),
        ("name-block", ("dd", [
            ("*type", ("str", "text-block")),
            ("text", ("str", spec.label)),
            ("property-dictionary", ("dd", [
                ("type", ("str", "label")),
                ("diagram-object-id", ("guid", spec.guid)),
                ("parent-diagram-id", ("guid", diagram_guid)),
            ])),
        ])),
        ("tooltip", ("str", "")),
        ("IsContained", ("bool", False)),
        ("IsLocked", ("bool", False)),
        ("SelectedStyleGroup", ("str", "")),
        ("Annotation", ("ref", c1.NULL_GUID)),
        ("MyStyle", ("ref", spec.style_guid)),
        ("AdaptiveStyles", ("list", [])),
        ("SubmitButton", ("ref", c1.NULL_GUID)),
        ("Disabled", ("bool", False)),
        ("Selected", ("bool", False)),
        ("VisibleFromSettings", ("bool", True)),
        ("diagram-objects", ("list", [("ref", child.guid)
                                      for child in spec.sub_objects])),
        ("PreserveCornersRectangle", ("dd", [("X", ("f64", 0.0)), ("Y", ("f64", 0.0)),
                                             ("Width", ("f64", 0.0)),
                                             ("Height", ("f64", 0.0))])),
        ("fit-to-image", ("bool", spec.fit_to_image)),
    ])


def text_box_descriptor(spec: TextBoxSpec, diagram_guid):
    """`Axure:DiagramObject:TextBox` 的 dd 描述符（21 键，键序 = 实测键序）。"""
    def text_block():
        return ("dd", [
            ("*type", ("str", "text-block")),
            ("text", ("str", spec.text)),
            ("property-dictionary", ("dd", [
                ("type", ("str", "plain-text-object")),
                ("diagram-object-label", ("str", "")),
                ("text-object-id", ("guid", spec.guid)),
                ("parent-diagram-id", ("guid", diagram_guid)),
            ])),
        ])
    return ("dd", [
        ("name-block", ("dd", [
            ("*type", ("str", "text-block")),
            ("text", ("str", spec.label)),
            ("property-dictionary", ("dd", [
                ("type", ("str", "label")),
                ("diagram-object-id", ("guid", spec.guid)),
                ("parent-diagram-id", ("guid", diagram_guid)),
            ])),
        ])),
        ("tooltip", ("str", "")),
        ("IsContained", ("bool", False)),
        ("IsLocked", ("bool", False)),
        ("SelectedStyleGroup", ("str", "")),
        ("Annotation", ("ref", c1.NULL_GUID)),
        ("MyStyle", ("ref", spec.style_guid)),
        ("AdaptiveStyles", ("list", [])),
        ("SubmitButton", ("ref", c1.NULL_GUID)),
        ("Disabled", ("bool", False)),
        ("Selected", ("bool", False)),
        ("VisibleFromSettings", ("bool", True)),
        ("diagram-objects", ("list", [("ref", child.guid)
                                      for child in spec.sub_objects])),
        ("TextBlock", text_block()),
        ("WordWrap", ("bool", spec.wrap)),
        ("ShowBorder", ("bool", spec.show_border)),
        ("ReadOnly", ("bool", spec.read_only)),
        ("PlaceholderText", ("str", spec.placeholder)),
        ("HideHintOnFocus", ("bool", spec.hide_hint_on_focus)),
        ("Type", ("int", spec.field_type)),
        ("MaxLength", ("int", spec.max_length)),
    ])


def _emit_node(b, node, diagram_guid):
    """按 Axure 的发射顺序登记一个控件：形状（+ 它的 `Axure:Style`）-> 子对象。

    实测 `首页原型.rp`：父 `VectorShape`、它的 `Axure:Style`、再紧跟子
    `RichTextPanel`（子对象自己**没有** `Axure:Style`）。
    """
    if isinstance(node, RichTextPanelSpec):
        b.add(b.build(("obj", RICH_TEXT_PANEL_KIND, node.guid,
                       rich_text_panel_descriptor(node, diagram_guid))))
    else:
        if isinstance(node, ImageBoxSpec):
            body = image_box_descriptor(node, diagram_guid)
        elif isinstance(node, TextBoxSpec):
            body = text_box_descriptor(node, diagram_guid)
        else:
            body = shape_descriptor(node, diagram_guid)
        b.add(b.build(("obj", node.kind, node.guid, body)))
        b.add(b.build(("obj", STYLE_KIND, node.style_guid, style_descriptor(node))))
    for child in node.sub_objects:
        _emit_node(b, child, diagram_guid)


def build_stream(spec: PageSpec, builder=None) -> StreamBuilder:
    """按 Axure 的发射顺序构造整页对象图（发射顺序 == 池分配顺序）。"""
    b = builder if builder is not None else StreamBuilder()
    b.add(b.pkgctx_(spec.page_object_guid, spec.package_guid))

    b.add(b.build(("obj", PAGE_KIND, spec.page_object_guid, ("dd", [
        ("diagram", ("ref", spec.diagram_guid)),
        ("page-style", ("ref", spec.page_style_guid)),
        ("AdaptiveStyles", ("list", [])),
        ("AdaptiveViewMatchInfos", ("list", [])),
        ("annotation", ("ref", spec.annotation_guid)),
        ("interactionmap", ("ref", spec.interaction_guid)),
        ("StyleCache", ("dd", [
            ("Styles", ("list", style_cache_descriptor() if spec.style_cache else [])),
            ("TypefaceToFullName", ("list", [])),
            ("TypefaceToCssName", ("list", [])),
        ])),
        ("IsAdaptiveEnabled", ("bool", False)),
        ("HackLegacyContainedObjects2", ("bool", True)),
    ]))))

    b.add(b.build(("obj", DIAGRAM_KIND, spec.diagram_guid, ("dd", [
        ("diagram-objects", ("list", [("ref", w.guid) for w in spec.widgets])),
        ("ann-link-list", ("list", [])),
        ("ruler-guide-set", ("ref", spec.ruler_guid)),
        ("GroupsClean3", ("bool", True)),
    ]))))

    for widget in spec.widgets:
        _emit_node(b, widget, spec.diagram_guid)

    b.add(b.build(("obj", RULER_KIND, spec.ruler_guid,
                   ("dd", [("ruler-guides", ("list", []))]))))

    b.add(b.build(("obj", PAGE_STYLE_KIND, spec.page_style_guid, ("dd", [
        ("BaseStyle.Name", ("str", "")),
        ("style-name", ("str", "MyPageStyle")),
        ("Id", ("guid", spec.page_style_id)),
        ("PropList", ("list", [])),
        ("Capabilities", ("i64", PAGE_STYLE_CAPABILITIES)),
        ("All", ("bool", False)),
    ]))))

    b.add(b.build(("obj", ANNOTATION_KIND, spec.annotation_guid, ("dd", [
        ("property-name-id-to-value", ("dd", [])),
        ("property-name-id-to-name-text", ("dd", [])),
        ("annotation-field-set-type", ("str", "PageFragment")),
    ]))))

    events = list(spec.interaction_events)
    node_guids = list(spec.node_guids) or [new_guid() for _ in events]
    event_guids = list(spec.event_guids) or [new_guid() for _ in events]
    if len(node_guids) != len(events) or len(event_guids) != len(events):
        raise ValueError("node/event guid count must match interaction_events")
    # 池顺序：node-table 交替登记 (node, event)，最后才是 tree —— 与 Axure 一致。
    node_table = [(("ref", node), ("ref", event))
                  for node, event in zip(node_guids, event_guids)]
    b.add(b.build(("obj", TREE_MAP_KIND, spec.interaction_guid, ("dd", [
        ("node-table", ("dd", node_table)),
        ("tree", ("ref", spec.tree_guid)),
        ("PackageMode", ("bool", False)),
    ]))))

    if node_guids:
        first = ("obj", NODE_KIND, node_guids[0], ("dd", [
            ("children", ("list", [])),
            ("parent-node", ("ref", spec.tree_guid)),
            ("tree", ("ref", spec.tree_guid)),
        ]))
        b.add(b.build(first))
    b.add(b.build(("obj", TREE_KIND, spec.tree_guid, ("dd", [
        ("children", ("list", [("ref", node) for node in node_guids])),
        ("tree", ("ref", spec.tree_guid)),
    ]))))
    for node in node_guids[1:]:
        b.add(b.build(("obj", NODE_KIND, node, ("dd", [
            ("children", ("list", [])),
            ("parent-node", ("ref", spec.tree_guid)),
            ("tree", ("ref", spec.tree_guid)),
        ]))))
    for event, event_type in zip(event_guids, events):
        b.add(b.build(("obj", EVENT_KIND, event, ("dd", [
            ("event-type", ("int", event_type)),
            ("master-containing-raised-event", ("ah", None, c1.NULL_GUID)),
            ("raised-event-id", ("guid", c1.NULL_GUID)),
        ]))))

    b.add(b.end_())
    return b


def build_page_stream(spec: PageSpec) -> bytes:
    """一个页面 = 一条 c1 包流（放进 Page 包 L2 的 `package` part）。"""
    return build_stream(spec).to_bytes()
