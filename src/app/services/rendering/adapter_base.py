"""原型工具适配器抽象基类与通用渲染逻辑。"""

from __future__ import annotations

import itertools
import math

from abc import ABC, abstractmethod
from typing import Any

from src.app import tuning
from src.app.services.rendering.text_layout import layout_text
from src.app.services.rendering.text_wrap import (
    fit_measured_lines,
    lines_spec_fields,
    wrap_for_spec,
)


# 文本基线：computed style/DesignSpec 里的 y 是元素（行框）上沿，而按基线绘制的
# 输出端（SVG）要的是基线位置。行框里基线落在“行框中心 + 0.375em”附近
# （0.375em 是这批系统 UI 字体 cap-height/descender 中点距基线的经验值）。
# 实测：同一份 1331 节点页面，基线从 y+fontSize 换成该公式后文字笔画
# meanDiff 从 20.8 降到 9.9 /255（脚本 output/_p2_final.py）。
# 数值本身在 `src/app/tuning.py`（"猜出来的数"的唯一定义点，env 可覆盖）；调用时读，
# 不缓存成模块常量——就地改 tuning 对已导入的模块同样生效。
def text_baseline_y(y: Any, height: Any, font_size: Any, inset_top: Any = 0.0) -> int:
    """把元素上沿 y 换算成文本基线（供按基线绘制的输出端使用）。

    `inset_top` 是**内容盒相对边框盒的上偏移**（= `border-top` + `padding-top`，px）。
    采集下来的 `y`/`height` 是 `getBoundingClientRect` 的**边框盒**，而浏览器把行框
    排在**内容盒**里；带边框的文字盒两者差 `border-top`（真机 dushu 分类格：
    `box-sizing:border-box; border:1px`，内容盒上沿 = 252+1，28 个格子整排文字高 1px）。
    Chromium 探针对齐过：`top=252 + border-box + border:1px` 的墨迹行 = 原截图行。

    **取整用“四舍五入（.5 进位）”，不用 `round()`**：`0.375em` 是个偏低的经验值
    （12px 时真值 ≈0.4167em，差 0.5px），`h` 又是整数，所以 `y + h/2 + 0.375em`
    的尾数常常正好是 `.5`；`round()` 的 half-even 会把**相邻两个 y 舍到同一个基线**
    （`round(275.5)==round(276.5)==276`），于是 ±1px 的位移写进 IR 也**纹丝不动**
    （`text_align` 的 ±1 微调在这里空转），而 `.5 进位` 让 y → 基线的映射恢复成
    严格 +1 单调。真机 A/B（dushu 首页，同一份 IR 只换取整）：整图 mean
    1.060 → 0.910 /255；再叠加内容盒偏移 0.910 → 0.647（分类格墨迹行与原截图
    逐行相同）。
    """
    try:
        return math.floor(
            float(y)
            + float(inset_top or 0.0)
            + 0.5 * float(height)
            + tuning.BASELINE_CENTER_EM * float(font_size)
            + 0.5
        )
    except (TypeError, ValueError):
        return int(float(y or 0)) + int(float(font_size or 0))


def _offset_box(box: Any, origin: tuple[int, int]) -> list[int] | None:
    """把页面绝对坐标的文本行框 [x, y, w, h] 换成相对裁剪容器原点的坐标。"""
    if not box:
        return None
    try:
        x, y, w, h = (int(v) for v in box)
    except (TypeError, ValueError):
        return None
    return [x - origin[0], y - origin[1], w, h]


def _measured_control_text_box(
    spec: dict[str, Any],
) -> tuple[int, int, int] | None:
    """Measured first-line origin for a single-line or nowrap control."""
    try:
        measured_lines = int(spec.get("textEmLines") or 0)
    except (TypeError, ValueError):
        measured_lines = 0
    nowrap = str(spec.get("whiteSpace") or "").strip().lower() == "nowrap"
    if measured_lines != 1 and not nowrap:
        return None
    box = spec.get("textEmBox")
    if not box:
        return None
    try:
        x, y, _w, h = (int(v) for v in box)
    except (TypeError, ValueError):
        return None
    return x, y, h


def _control_text_anchor(
    *,
    has_text_box: bool,
    has_run_box: bool,
    has_measured_box: bool,
) -> str:
    return (
        "start"
        if has_text_box or has_run_box or has_measured_box
        else "middle"
    )


def _single_line_text(spec: dict[str, Any]) -> bool:
    """Whether Figma should keep this text on one auto-width line."""
    if spec.get("singleLine"):
        return True
    try:
        measured_lines = int(spec.get("textEmLines") or 0)
        explicit_max_lines = int(spec.get("maxLines") or 0)
    except (TypeError, ValueError):
        return False
    lines = spec.get("lines")
    if isinstance(lines, list) and len(lines) > 1:
        return False
    return (
        measured_lines == 1
        and explicit_max_lines < 1
        and not spec.get("clip")
        and not spec.get("clipToBounds")
    )


def _semantic_plugin_data(spec: Mapping[str, Any]) -> dict[str, str]:
    values = {
        "figma_auto_agent.semantic_role": spec.get("semanticRole"),
        "figma_auto_agent.semantic_group_id": spec.get("semanticGroupId"),
        "figma_auto_agent.semantic_confidence": spec.get("semanticConfidence"),
    }
    return {
        key: str(value)
        for key, value in values.items()
        if value is not None and str(value).strip()
    }


class PrototypeAdapter(ABC):
    """原型工具适配器抽象基类。"""

    # 输出端是否用"嵌套裁剪容器"表达 DesignSpec 的 clip。SVG 用
    # <g clip-path> 自己处理、保持扁平（False）；Figma 只有 frame 能裁子元素，
    # 必须真嵌套（True）。False 时 clip 被忽略，产物与老版本逐字节一致。
    supports_clip_frames = False
    # 是否吃 `design["pages"]`（多页；Axure = 多页面，Figma / SVG 各自实现）。
    supports_pages = False

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
    def create_rectangle(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        """创建矩形/按钮/输入框等元素。"""
        ...

    @abstractmethod
    def create_ellipse(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        """创建椭圆/圆形元素。"""
        ...

    @abstractmethod
    def create_text(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        """创建文本元素。"""
        ...

    @abstractmethod
    def create_image(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        """创建图片元素（用真实图像填充）。"""
        ...

    @abstractmethod
    def flush(self) -> None:
        """提交/保存最终输出。"""
        ...

    def render_design(self, design: dict[str, Any]) -> None:
        """渲染完整的 DesignSpec。元素之间保持独立，不建立组合关系。

        多页：`design["pages"] = [{name, canvas, elements}, …]` 时**逐页**渲染，
        **第 i 页 = 第 i 个画板**（数组顺序即页面顺序）；没给 `pages` 就按老的
        单页形状 `{"canvas": …, "elements": …}` 走，旧产物的字节行为不变。
        不支持多页的输出端（`supports_pages = False`）遇到 `pages` 直接抛错，
        不静默把几页叠成一页。
        """
        pages = design.get("pages") or []
        if pages:
            if not self.supports_pages:
                raise ValueError(
                    "该输出端不支持多页 DesignSpec（pages）：%s" % type(self).__name__
                )
            for index, page in enumerate(pages):
                self._render_page(page, index)
        else:
            self._render_page(design, None)
        self.flush()

    def _render_page(self, page: dict[str, Any], index: int | None) -> None:
        """渲染一页（= 一个画板 / frame）；`index` 只在多页时给（用于兜页名）。

        绘制序规则（所有输出端共用，解决扁平顺序后画盖先画的问题）：
        1) overlay 浮层整体最后画，同层内 zIndex 升序，其中 cropBackdrop
           （浮层像素底，来自原截图裁剪）再排在同 z 的其它元素之后——它是该区域
           的最终像素，必须最后落笔（直出侧会丢弃被它盖住的冗余图层，
           见 direct_design._shadowed_by_backdrop，两处口径必须一致）；
        2) 非浮层内容按“被包含深度”先铺大背景/卡片，再画侧栏与正文，避免重复的
           全宽背景在文档序里排到侧栏后面把侧栏盖白；
        3) 白色叶子若整体落在先前画过的深色**局部**衬底（顶栏/侧栏/面板）上，视为
           "透明控件补出来的白底幻影"，跳过白底保留衬底色。**页面背景层不算衬底**
           ——它铺满画布，任何白色内容都落在它上面，当衬底会把整页白卡片全吞掉
           （python.org 真机：蓝 `html` 与白 `body` 同矩形、却是两个节点，见
           `_is_page_backing`）。
        """
        canvas = page.get("canvas", {})
        name = page.get("name") or self._frame_name(page)
        if index is not None and index > 0 and not page.get("name"):
            name = "%s %d" % (name, index + 1)
        frame_id = self.create_frame(
            {
                "name": name,
                "x": canvas.get("x", 0),
                "y": canvas.get("y", 0),
                "width": canvas.get("width", 800),
                "height": canvas.get("height", 600),
                "backgroundColor": canvas.get("background") or "#ffffff",
            }
        )

        elements = page.get("elements", [])
        ordered = paint_order(elements)

        # Auto Layout：IR（`layout_plan.build_layout_plan`）已经按 DOM 父子关系挑出
        # 够格的容器，这里再按绘制序与实测几何复核一遍。只有支持真嵌套容器的输出端
        # （Figma）才建 Frame；复核不过就整块退回扁平绝对定位，逐像素与不开 Auto
        # Layout 时相同（见 归档文档 figma_layout_upgrade_audit.md §4.4）。
        frames = resolve_frames(elements, ordered) if self.supports_clip_frames else {}
        frame_nodes: dict[int, tuple[str, tuple[int, int]]] = {}
        child_owner: dict[int, int] = {}
        closing: dict[int, list[int]] = {}
        for plan_idx, plan in frames.items():
            closing.setdefault(plan["end"], []).append(plan_idx)

        chrome: list[tuple[int, int, int, int, tuple[int, int, int]]] = []
        skipped_text_color: dict[int, str] = {}
        # 页面背景层（铺满画布的那一层）不算"衬底块"，见 _is_page_backing。
        page_rect = (
            0,
            0,
            int(canvas.get("width", 800)),
            int(canvas.get("height", 600)),
        )

        # 裁剪容器：clip 是"该元素被祖先滚动容器切掉的矩形"（页面绝对坐标）。
        # 支持嵌套裁剪的输出端（Figma）要建真容器把子元素放进去；SVG 用
        # <g clip-path> 自己处理、保持扁平。只在绘制序里连续的一段共用一个容器
        # ——frame 自带层叠上下文，把被别的元素隔开的带 clip 元素硬塞进同一个
        # 容器会改掉全局笔序。
        clip_frame_id: str | None = None
        clip_key: tuple[int, int, int, int] | None = None

        for pos, (idx, el) in enumerate(ordered):
            el_type = el.get("type", "rectangle")
            style = el.get("style", {})
            spec = {**el, **style}

            host = child_owner.get(idx)
            if host is not None:
                # 已经挂进 Auto Layout 父 Frame：坐标换成相对那个 Frame 的原点
                parent_id, origin = frame_nodes[host]
            else:
                el_clip = (
                    self._clip_rect_of(spec) if self.supports_clip_frames else None
                )
                if el_clip is not None and el_clip != clip_key:
                    # 必须挂到 Screen 画板下：挂 currentPage 会变成同级，
                    # 那整段裁剪内容就会画在全部内容之上。
                    clip_frame_id, clip_key = (
                        self.create_clip_frame(el_clip, frame_id),
                        el_clip,
                    )
                elif el_clip is None:
                    clip_frame_id, clip_key = None, None
                if el_clip is None or clip_frame_id is None:
                    # 无 clip，或输出端没建出容器：退回扁平直画（不裁）
                    parent_id: str | None = frame_id
                    origin = (0, 0)
                else:
                    parent_id, origin = clip_frame_id, (el_clip[0], el_clip[1])
            # 判定（chrome 覆盖、白叶衬底）继续用页面绝对坐标，下发才换成父级相对
            spec_out = self._offset_spec(spec, origin)
            plugin_data = _semantic_plugin_data(spec)
            if plugin_data:
                spec_out["pluginData"] = plugin_data

            # 这个容器整体变成一个 Auto Layout Frame：底/描边/圆角画在 Frame 自身上，
            # 子项照旧按它们原本的绝对坐标挂进去，等这一组挂完再打开 layoutMode
            # （顺序约束见 set_autolayout）。
            frame_plan = frames.get(idx)
            if frame_plan is not None:
                fill = self._note_chrome(
                    spec, chrome, skipped_text_color, idx, page_rect
                )
                frame_params = {
                    **spec_out,
                    "parentId": parent_id,
                    "applyStyle": True,
                    "clipsContent": bool(spec.get("clipToBounds")),
                    "name": spec.get("name") or "Container",
                }
                if fill:
                    frame_params["fillColor"] = fill
                else:
                    frame_params["transparent"] = True
                new_frame_id = self.create_frame(frame_params)
                if new_frame_id:
                    frame_nodes[idx] = (
                        new_frame_id,
                        (int(spec.get("x", 0)), int(spec.get("y", 0))),
                    )
                    for member, _item in frame_plan["members"]:
                        child_owner[member] = idx
                    continue

            if spec.get("imageBase64"):
                # 透明浮层容器按原截图像素回填（如 fixed wrapper 的整列底），
                # 以图片形式画，保证它盖在底下内容之上时观感与截图一致。
                self.create_image(spec_out, parent_id=parent_id)
            elif el_type in ("button", "input", "rectangle", "container"):
                r = self._element_rect(spec)
                backing = self._white_leaf_backing(r, spec, chrome)
                if backing is not None:
                    skipped_text_color[idx] = self._contrast_text_color(backing[4])
                else:
                    self._note_backing(r, spec.get("fillColor"), chrome, page_rect)
                    self.create_rectangle(spec_out, parent_id=parent_id)
            elif el_type in ("image", "avatar"):
                if spec.get("imageBase64"):
                    self.create_image(spec_out, parent_id=parent_id)
                else:
                    # Missing display payloads stay editable/honest placeholders;
                    # the asset record keeps their original status separate.
                    placeholder = {
                        **spec_out,
                        "name": spec.get("name") or spec.get("id") or "Image",
                        "fillColor": "transparent",
                    }
                    self.create_rectangle(placeholder, parent_id=parent_id)
            elif el_type == "circle":
                self.create_ellipse(spec_out, parent_id=parent_id)
            elif el_type == "text":
                fill_color = spec.get("fillColor")
                if fill_color and not self._is_neutral_background(fill_color):
                    bg_spec = {
                        "x": spec_out.get("x", 0),
                        "y": spec_out.get("y", 0),
                        "width": spec.get("width", 100),
                        "height": spec.get("height", 40),
                        "fillColor": fill_color,
                        "borderColor": spec.get("borderColor"),
                        "borderWidth": spec.get("borderWidth", 0),
                        "borderRadius": spec.get("borderRadius", 0),
                        "borderRadiusCorners": spec.get("borderRadiusCorners"),
                        # 文本元素自带底色时，底色与文字共享同一份透明度/字距
                        "opacity": spec.get("opacity"),
                        "letterSpacing": spec.get("letterSpacing"),
                    }
                    self.create_rectangle(bg_spec, parent_id=parent_id)
                text_spec = self._text_render_spec(spec, spec_out, origin)
                single_line = _single_line_text({**spec, **style})
                if single_line:
                    text_spec["singleLine"] = True
                    text_spec.pop("lines", None)
                    text_spec.pop("boundedText", None)
                elif (
                    text_spec.get("richRuns")
                    or str(spec.get("whiteSpace") or "").strip().lower() == "nowrap"
                    or spec.get("clipToBounds")
                ):
                    text_spec["boundedText"] = True
                self.create_text(
                    self._wrap_text_spec(text_spec),
                    parent_id=parent_id,
                )
            elif el_type == "divider":
                r = self._element_rect(spec)
                self._note_backing(r, spec.get("fillColor"), chrome, page_rect)
                self.create_rectangle(spec_out, parent_id=parent_id)
            else:
                r = self._element_rect(spec)
                backing = self._white_leaf_backing(r, spec, chrome)
                if backing is not None:
                    skipped_text_color[idx] = self._contrast_text_color(backing[4])
                else:
                    self._note_backing(r, spec.get("fillColor"), chrome, page_rect)
                    self.create_rectangle(spec_out, parent_id=parent_id)

            text_color = spec.get("textColor", "#000000")
            if idx in skipped_text_color:
                text_color = skipped_text_color[idx]
            if el_type != "text" and spec.get("text"):
                # 控件（按钮/输入框）里的文字是"控件内居中"的，与文本元素不同：
                # 这里按控件盒子中心 x + text-anchor=middle 放置，垂直交给统一的
                # text_baseline_y（盒子中心 + 0.375em）。
                # 例外：bbox 本身就是这行文本的 Range 行框时（混合内容控件，如
                # <a><i class="anticon"/>编辑</a> 的 bbox 是"编辑"两字的行框），
                # 真实页面里文字是从行框左缘起排的，再按盒子居中会整体右偏
                # （实测 antd 操作列的"编辑"偏 6px、"删除"偏 3px）——改左对齐。
                width = spec.get("width", 100)
                run_box = bool(spec.get("textLineBox"))
                # 控件自带底色/描边时，几何盒要留着画框，但落字按 IR 带来的真实行框
                # （spec["textBox"]，见 providers/dom）：按盒子居中会把文字推到同级
                # 图标上（dushu 导航按钮图标压首字、「查看更多」左偏 107px）。行框是
                # 单行这一点在 IR 侧已经判过。
                tbox = None if run_box else _offset_box(spec.get("textBox"), origin)
                measured_box = None
                if tbox is not None:
                    text_x, text_y, text_h = tbox[0], tbox[1], tbox[3]
                elif (
                    measured_box := _measured_control_text_box(spec)
                ) is not None:
                    text_x = (
                        spec_out.get("x", 0)
                        + measured_box[0]
                        - int(spec.get("x", 0))
                    )
                    text_y = (
                        spec_out.get("y", 0)
                        + measured_box[1]
                        - int(spec.get("y", 0))
                    )
                    text_h = measured_box[2]
                elif run_box:
                    text_x, text_y, text_h = (
                        spec_out.get("x", 0),
                        spec_out.get("y", 0),
                        spec.get("height", 40),
                    )
                else:
                    text_x, text_y, text_h = (
                        spec_out.get("x", 0) + int(width) // 2,
                        spec_out.get("y", 0),
                        spec.get("height", 40),
                    )
                text_spec = {
                    "x": text_x,
                    "y": text_y,
                    "height": text_h,
                    "text": spec.get("text"),
                    "textColor": text_color,
                    "fontSize": spec.get("fontSize", 16),
                    "fontWeight": spec.get("fontWeight"),
                    "fontWeightValue": spec.get("fontWeightValue"),
                    "fontFamily": spec.get("fontFamily"),
                    "fontStyle": spec.get("fontStyle"),
                    "letterSpacing": spec.get("letterSpacing"),
                    "opacity": spec.get("opacity"),
                    "richRuns": spec.get("richRuns"),
                    "whiteSpace": spec.get("whiteSpace"),
                    "textAnchor": _control_text_anchor(
                        has_text_box=tbox is not None,
                        has_run_box=run_box,
                        has_measured_box=measured_box is not None,
                    ),
                }
                if str(spec.get("whiteSpace") or "").strip().lower() == "nowrap":
                    # 元素自己的 `white-space:nowrap` 必须跟着标题走：控件的底框被
                    # "白叶衬底"规则吞掉时，标题是**独立文字**下发的（`_text()` 按估宽
                    # 居中，见上），丢了它窄盒里的标题就会早折一个字符——与
                    # `_button()` 内嵌标题的口径必须一致（真机 A/B 见 plan §9.11）。
                    text_spec["whiteSpace"] = "nowrap"
                single_line = _single_line_text({**spec, **style})
                if single_line:
                    text_spec["singleLine"] = True
                elif text_spec.get("richRuns") or text_spec.get("whiteSpace") == "nowrap":
                    text_spec["boundedText"] = True
                lines = None if (tbox is not None or run_box) else wrap_for_spec(spec)
                if single_line:
                    lines = None
                if lines:
                    # 折行后"控件内居中"这条经验规则不再成立（多行块的排版该跟
                    # 真实页面走）：行首落到盒子左缘，水平对齐改用 DOM 的
                    # textAlign，垂直由每行自己的行框基线决定。
                    text_spec.update(lines_spec_fields(spec, lines))
                    text_spec["x"] = spec_out.get("x", 0)
                    # width 必须一并带走：折行块的契约是「x=行首、width=盒子宽、
                    # 对齐看 textAlign」（SVG / Figma 靠它算居中/右对齐）。Axure 出口
                    # 缺 width 时会退化成"估一行宽、再回移半个行宽"，把元素发到画布外
                    # （真机 python.org 首页 left:-846px，见 归档文档 axure_rp8_plan.md §9.7）。
                    text_spec["width"] = spec_out.get("width", width)
                    # 锚点也不能留在 middle：它只对上面那条"盒子中心 + 估宽"的
                    # 单行路径成立，这里 x 已经是行首了。
                    text_spec["textAnchor"] = "start"
                self.create_text(text_spec, parent_id=parent_id)

            # 这一组挂完了：最后一步才把容器改成 Auto Layout
            for done in closing.get(pos, []):
                node = frame_nodes.get(done)
                if node is None:
                    continue
                done_plan = frames[done]
                done_rect = self._element_rect(elements[done]) or (0, 0, 0, 0)
                if done_plan.get("layout") is None:
                    continue
                # 子项坐标不再下发：插件在打开 layoutMode 前先快照**每个**子节点当前的
                # x/y，打开后原样写回（全量复位）。快照永远等于扁平渲染时的落点 ——
                # 交给 Figma 的 Auto Layout 流式摆放会叠加成员自己的 x/y，整组漂一个
                # itemSpacing（真机实测整图均差 2.176 → 4.615，见
                # 归档文档 figma_layout_upgrade_audit.md §10）。这样「一个成员落多个节点」
                # （控件 = 底框 + 文本）也不会错位（§12）。
                self.set_autolayout(
                    node[0],
                    {
                        "layout": done_plan["layout"],
                        "width": done_rect[2],
                        "height": done_rect[3],
                        "expectChildren": len(done_plan["members"]),
                    },
                )

    def _wrap_text_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        """文本元素按盒子宽度折行；不需要折行时原样返回（产物逐字节不变）。

        折行结果在 IR 侧就算好（text_wrap），SVG 与 Figma 只是照着画同一份断点，
        免得两边字体度量不同、折出来的行数对不上。
        """
        measured_lines = spec.get("measuredLines")
        if (
            spec.get("richRuns")
            and _single_line_text(spec)
            and not measured_lines
        ):
            return spec
        if isinstance(measured_lines, (list, tuple)) and measured_lines:
            layout = layout_text(spec, measured_lines=measured_lines)
            fitted_lines = fit_measured_lines(
                spec,
                list(layout["lines"]),
            )
            return {
                **spec,
                "lines": fitted_lines,
                "lineBoxes": [
                    list(box)
                    for box in layout.get("lineBoxes", [])[:len(fitted_lines)]
                ],
                "lineHeight": int(layout["lineHeight"]),
                "textAlign": str(layout["textAlign"]),
                "source": str(layout["source"]),
                "baselineSource": str(layout["baselineSource"]),
                "layoutConfidence": float(layout["confidence"]),
            }
        lines = wrap_for_spec(spec)
        if not lines:
            return spec
        return {
            **spec,
            **lines_spec_fields(spec, lines),
            # Wrapping or truncation changes character positions. Keeping the old
            # rich-run offsets would format the wrong glyphs and can reintroduce
            # overflow in Figma. Prefer readable, bounded plain text in this case.
            "richRuns": [],
        }

    def _text_render_spec(
        self,
        spec: dict[str, Any],
        local_spec: dict[str, Any],
        origin: tuple[int, int],
    ) -> dict[str, Any]:
        """给输出端一次机会，按本端文本排版语义修正已局部化的元素。"""
        del spec, origin
        return local_spec

    @staticmethod
    def _frame_name(design: dict[str, Any]) -> str:
        """画板名带上覆盖率：一眼能看出这一版是不是抓全了。

        例：`Screen 1452×933 · 337/536 (100%)`。_meta 缺失时只留尺寸，
        老产物（无 _meta）仍然只叫 Screen。
        """
        canvas = design.get("canvas") or {}
        meta = design.get("_meta") or {}
        name = "Screen"
        if canvas.get("width") and canvas.get("height"):
            name += f" {int(canvas['width'])}×{int(canvas['height'])}"
        expected, returned = meta.get("expected"), meta.get("returned")
        if expected is not None and returned is not None:
            name += f" · {int(returned)}/{int(expected)}"
            coverage = meta.get("coverage")
            if coverage is not None:
                name += f" ({float(coverage):.0%})"
        return name

    @staticmethod
    def _clip_rect_of(spec: dict[str, Any]) -> tuple[int, int, int, int] | None:
        """取元素携带的裁剪矩形（页面绝对坐标）；无 / 无效返回 None。"""
        clip = spec.get("clip")
        try:
            if isinstance(clip, (list, tuple)) and len(clip) == 4:
                x, y, w, h = (int(v) for v in clip)
            elif spec.get("clipToBounds"):
                x, y, w, h = (
                    int(spec.get("x", 0)),
                    int(spec.get("y", 0)),
                    int(spec.get("width", 0)),
                    int(spec.get("height", 0)),
                )
            else:
                return None
        except (TypeError, ValueError):
            return None
        if w <= 0 or h <= 0:
            return None
        return (x, y, w, h)

    @staticmethod
    def _offset_spec(spec: dict[str, Any], origin: tuple[int, int]) -> dict[str, Any]:
        """把页面绝对坐标换成相对裁剪容器原点的坐标（Figma 的 x/y 相对父级）。"""
        ox, oy = origin
        if not ox and not oy:
            return spec
        out = dict(spec)
        out["x"] = int(spec.get("x", 0)) - ox
        out["y"] = int(spec.get("y", 0)) - oy
        return out

    def create_clip_frame(
        self, rect: tuple[int, int, int, int], parent_id: str | None = None
    ) -> str | None:
        """建一个裁剪容器（矩形裁剪 + 切子元素），返回节点 id。

        仅当 supports_clip_frames 为 True 时被调用。clip 的语义只是 overflow 的
        矩形裁剪，圆角 / `mask` 不在其内（capture 侧就只取 overflow 矩形）。
        """
        raise NotImplementedError(f"{type(self).__name__} 不支持裁剪容器")

    def _note_chrome(
        self,
        spec: dict[str, Any],
        chrome: list[tuple[int, int, int, int, tuple[int, int, int]]],
        skipped_text_color: dict[int, str],
        idx: int,
        page_rect: tuple[int, int, int, int],
    ) -> str | None:
        """画底色前的记账（规则见 render_design 文档串第 3 条），返回该用的底色。

        返回 None = 这块白底是幽灵按钮的白底幻影，别画（只留衬底色）。
        """
        rect = self._element_rect(spec)
        backing = self._white_leaf_backing(rect, spec, chrome)
        if backing is not None:
            skipped_text_color[idx] = self._contrast_text_color(backing[4])
            return None
        fill = spec.get("fillColor")
        self._note_backing(rect, fill, chrome, page_rect)
        return fill

    def _note_backing(
        self,
        rect: tuple[int, int, int, int] | None,
        fill: Any,
        chrome: list[tuple[int, int, int, int, tuple[int, int, int]]],
        page_rect: tuple[int, int, int, int],
    ) -> None:
        """把刚画过的「彩色/深色衬底」记进 chrome；页面背景层不算衬底。"""
        if self._is_page_backing(rect, page_rect):
            return
        if rect is not None and self._is_chrome_color(fill):
            parsed = self._parse_hex_color(fill)
            if parsed is not None:
                chrome.append((*rect, parsed))

    def set_autolayout(self, node_id: str, payload: dict[str, Any]) -> Any:
        """把已经挂完子元素的容器改成 Auto Layout，返回输出端的原始结果。

        **顺序是硬约束**：Figma 一旦 `layoutMode != NONE` 就立刻重排子元素，所以必须
        「先按绝对坐标把子元素全部挂完 → 最后再打开 layoutMode 并把 sizing 写死」。
        `payload`：`layout`（字段名即 Figma Plugin API）、`width`/`height`（容器自己的
        尺寸，打开布局后再 resize 一次钉住）、`expectChildren`（成员数；**下界**，
        实际子节点数少于它说明有成员没画出来，整个不动、退回扁平绝对定位）。子项坐标
        不下发：输出端自己快照再复位（「一个成员落多个节点」也不会错位）。
        """
        raise NotImplementedError(f"{type(self).__name__} 不支持 Auto Layout")

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
    def _covers(
        a: tuple[int, int, int, int], b: tuple[int, int, int, int], eps: int = 1
    ) -> bool:
        """a 是否完全覆盖 b（含同边界，允许 1px 容差）。"""
        return (
            a[0] <= b[0] + eps
            and a[1] <= b[1] + eps
            and b[0] + b[2] <= a[0] + a[2] + eps
            and b[1] + b[3] <= a[1] + a[3] + eps
        )

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
                if len(parts) > 3 and float(parts[3]) < tuning.COLOR_MIN_ALPHA:
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
            return (
                int(hex_color[0:2], 16),
                int(hex_color[2:4], 16),
                int(hex_color[4:6], 16),
            )
        except ValueError:
            return None

    @classmethod
    def _is_white_fill(cls, color: Any) -> bool:
        """近似纯白填充。"""
        rgb = cls._parse_hex_color(color)
        if rgb is None:
            return False
        return (
            min(rgb) >= tuning.WHITE_BG_MIN_RGB
            and max(rgb) - min(rgb) <= tuning.WHITE_BG_MAX_SPREAD
        )

    @classmethod
    def _is_chrome_color(cls, color: Any) -> bool:
        """彩色/深色衬底色（非近白、非中性浅灰）。"""
        rgb = cls._parse_hex_color(color)
        if rgb is None:
            return False
        mx, mn = max(rgb), min(rgb)
        luma = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255.0
        sat = (mx - mn) / 255.0
        return luma < tuning.DARK_LUMA or sat > tuning.CHROME_SAT

    @classmethod
    def _contrast_text_color(cls, rgb: tuple[int, int, int]) -> str:
        luma = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255.0
        return "#FFFFFF" if luma < tuning.BW_LUMA else "#000000"

    @classmethod
    def _is_page_backing(
        cls,
        rect: tuple[int, int, int, int] | None,
        page_rect: tuple[int, int, int, int],
    ) -> bool:
        """这块衬底是**页面背景层**（铺满整个画布）吗？

        页面背景不是"衬底块"：它整页都在，任何白色内容都落在它上面。把它当深色衬底
        会让 `_white_leaf_backing` 把整页的白卡片全吞掉——python.org 真机：蓝 `html`
        与白 `body` 是同一个矩形、却是**两个**节点，三页共 423 块白被吞（发布产物成
        整页蓝底）。顶栏/侧栏/面板这类真衬底块永远不会铺满整页。
        """
        return rect is not None and cls._covers(rect, page_rect)

    @classmethod
    def _white_leaf_backing(
        cls,
        rect: tuple[int, int, int, int] | None,
        spec: dict[str, Any],
        chrome: list[tuple[int, int, int, int, tuple[int, int, int]]],
    ) -> tuple[int, int, int, int, tuple[int, int, int]] | None:
        """白色叶子是否该透明化（去掉白底幻影），返回它落的深色衬底；无则返回 None。

        白色叶子整体落在先前画过的**深色局部衬底**（luma < DARK_LUMA 的顶栏/侧栏/
        面板）上 → 那是"透明控件补出来的白底幻影"，去白底让衬底透出。

        判据只有几何覆盖：**同矩形不等于同一节点**（python.org 的蓝 `html` 与白
        `body` 同矩形、却是两个节点），所以原先"完全重合即去白"那条已经不成立；
        页面背景层在记账时就被排除（见 `_is_page_backing`）。
        """
        if rect is None or not cls._is_white_fill(spec.get("fillColor")):
            return None
        for x, y, w, h, rgb in chrome:
            if rgb is None:
                continue
            luma = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255.0
            if luma < tuning.DARK_LUMA and cls._covers((x, y, w, h), rect):
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


# ── 绘制序 / Auto Layout 施工图的复核（输出端共用，纯函数） ──────────────────


def paint_order(elements: list[dict]) -> list[tuple[int, dict]]:
    """全局绘制序：返回 [(原下标, 元素)]；所有输出端共用（规则见 render_design）。

    显式落笔深度优先（共线分隔线合并后几何推不出原深度，见 direct_design）：`_depth`
    只由几何决定，合并成一整条后「被谁完整覆盖」变少、深度就变小、落笔提前，会被本该
    在它下面的底色擦掉；合并那一趟知道每个分段的真实深度，取最大值写进 `paintDepth`。
    """
    rects = [PrototypeAdapter._element_rect(e) for e in elements]
    # 重复矩形（同节点被多次采集成容器）会互相抬高深度，导致本应铺底的白底工具栏排到
    # 彩色按钮之后。按唯一几何矩形统计「被谁覆盖」，消除该膨胀。
    seen: set[tuple[int, int, int, int]] = set()
    unique_geoms = []
    for rect in rects:
        if rect is not None and rect not in seen:
            seen.add(rect)
            unique_geoms.append(rect)

    def _depth(idx: int) -> int:
        rect = rects[idx]
        if rect is None:
            return 0
        return sum(
            1
            for other in unique_geoms
            if other != rect and PrototypeAdapter._covers(other, rect)
        )

    def _paint_depth(idx: int, el: dict) -> int:
        if "paintDepth" in el:
            return int(el["paintDepth"])
        return _depth(idx)

    return sorted(
        enumerate(elements),
        key=lambda pair: (
            1 if pair[1].get("overlay") else 0,
            int(pair[1].get("zIndex") or 0),
            1 if pair[1].get("cropBackdrop") else 0,
            _paint_depth(pair[0], pair[1]),
            pair[0],
        ),
    )


def _single_node(spec: dict) -> bool:
    """这个元素**自己当 Frame**时只会落一个节点吗？

    只有容器本身受这条限制：带文字的容器（按钮/输入框）当 Frame 时它的文字节点不会
    被画出来（`render_design` 走 Frame 分支就 `continue` 了），所以不给它建 Frame。
    **成员不受此限** —— 成员多落的节点由插件全量快照复位，落点仍与扁平渲染相同
    （见 `resolve_frames` 规则 3）。
    """
    if spec.get("type", "rectangle") == "text":
        return PrototypeAdapter._is_neutral_background(spec.get("fillColor"))
    return not spec.get("text")


def _clip_key(spec: dict) -> tuple[int, int, int, int] | None:
    """元素携带的裁剪矩形（作为「是不是同一套裁剪」的比较键）。"""
    clip = spec.get("clip")
    if not isinstance(clip, (list, tuple)) or len(clip) != 4:
        return None
    try:
        return tuple(int(v) for v in clip)
    except (TypeError, ValueError):
        return None


def _pin_reason(
    elements: list[dict], idx: int, members: list[tuple[int, dict]]
) -> str | None:
    """钉死时代的准入检查：只剩「成员与 Frame 同一套裁剪」。

    这里原本按 Figma 的排版规则重放子项位置、与实测 rect 逐项比对，对不上就报
    `geometry-mismatch` / `text-member` / `flow-too-few` 退回扁平。2026-10-12 真机验收
    （`归档文档 figma_layout_upgrade_audit.md` §10、§11）把这个模型废掉了：成员现在是
    `ABSOLUTE` + 写回原 x/y，**不吃**排版引擎的流式摆放 —— 于是「按 spacing 重放能不能
    对上」「文本盒的尺寸是引擎按字体度量算的」都不再影响落点，只有裁剪还会挪像素：
    成员带着和 Frame 不一样的 clip 时，输出端会在 Frame 中间再插一层裁剪容器，笔序变了。
    """
    base_clip = _clip_key(elements[idx])
    for member, _item in members:
        if _clip_key(elements[member]) != base_clip:
            return "clip-mismatch"
    return None


def _intersects(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """两个矩形有没有正面积交集（只是贴边不算）。"""
    return not (
        a[0] + a[2] <= b[0]
        or b[0] + b[2] <= a[0]
        or a[1] + a[3] <= b[1]
        or b[1] + b[3] <= a[1]
    )


def resolve_frames(
    elements: list[dict],
    ordered: list[tuple[int, dict]],
    reasons: dict[int, str] | None = None,
) -> dict[int, dict]:
    """复核 IR 写的 Auto Layout 施工图，返回 {元素下标: {layout, members, end}}。

    四条守门，任一不满足就放弃这个 Frame（放弃是安全的：退回扁平绝对定位，输出与不开
    Auto Layout 时逐像素相同）：

    1. **成员都排在 Frame 之后，且矩形落在 Frame 里**。成员是挂在 Frame 下的子节点，
       Figma 只会把它们放在 Frame 内部；矩形不相交就说明成员会被排到别处去。
    2. **画在最后一个成员之前、与 Frame 矩形相交的图元必须都是成员**（成员闭包：成员
       本身，以及成员里的子 Frame 的成员）。Frame 自带层叠上下文，整组会一起落在原来
       容器元素那一笔上：与它相交却不属于它、又**夹在成员中间**的外人，层序会从「夹在
       中间」变成「整组之后」—— 那是真的要拒。画在**整组之后**的外人不受影响：它在扁平
       图里本来就是排在 Frame 之后的一笔（`render_design` 也是把 Frame 与它依次 append
       给同一个父级），层序不变（§15）。
    3. **容器自己只落一个节点**（见 `_single_node`）：带文字的控件当 Frame 时它的文字
       节点不落盘，所以这类容器不建 Frame。成员**不再**受此限：一个成员落多个节点
       （控件 = 底框 + 文本）时，插件会把 Frame 里**全部**子节点钉死（`ABSOLUTE` + 打开
       布局前的快照 x/y），落点与扁平渲染逐像素相同（§12）。
    4. **成员与 Frame 同一套裁剪**（见 `_pin_reason`）。**几何不再复核**：成员一律钉死
       （`ABSOLUTE` + 快照复位），不吃排版引擎的流式摆放，所以"按 spacing 重放能不能
       对上""文本盒尺寸是引擎算的"都不再影响落点（真机验收见 §10、§11）。

    成员顺序在这里统一成**绘制序**（`render_design` 就是按绘制序把子节点 append 进
    Frame 的，覆盖项的序号也按这个来）。子 Frame 掉了，父 Frame 必然也掉（见
    `children_ok`）：子 Frame 没建出来时它的成员退回扁平绝对定位，而它们落在父 Frame
    的区间里 —— 父 Frame 一建，这些图元就会被排在父 Frame 之后，笔序照样变。反过来父
    Frame 掉了不影响子 Frame。

    `reasons` 给统计用：会把没建成的候选与原因写进去（`scripts/layout_frames_probe.py`）。
    """
    pos_of = {idx: rank for rank, (idx, _el) in enumerate(ordered)}
    seq = [idx for idx, _el in ordered]
    rect_of = [PrototypeAdapter._element_rect(el) for el in elements]
    by_id: dict[Any, int] = {}
    for i, el in enumerate(elements):
        by_id.setdefault(el.get("id"), i)

    def note(i: int, why: str) -> None:
        if reasons is not None:
            reasons[i] = why

    plans: dict[int, tuple[dict | None, list[tuple[int, dict]]]] = {}
    for i, el in enumerate(elements):
        layout = el.get("layout")
        children = el.get("layoutChildren")
        if (
            (layout is not None and not isinstance(layout, dict))
            or not isinstance(children, list)
            or len(children) < 2
        ):
            continue
        if not _single_node(el):
            note(i, "container-multi-node")
            continue
        if i not in pos_of:
            note(i, "container-not-painted")
            continue
        if rect_of[i] is None:
            note(i, "container-bad-rect")
            continue
        members: list[tuple[int, dict]] = []
        why = None
        for item in children:
            member = by_id.get(item.get("id")) if isinstance(item, dict) else None
            if member is None or member == i:
                why = "member-missing"
            elif member not in pos_of:
                why = "member-not-painted"
            elif rect_of[member] is None:
                why = "member-bad-rect"
            else:
                members.append((member, item))
                continue
            break
        if why is not None:
            note(i, why)
            continue
        plans[i] = (layout, members)

    built: dict[int, bool] = {}
    last: dict[int, int] = {}

    def by_paint(members: list[tuple[int, dict]]) -> list[tuple[int, dict]]:
        return sorted(members, key=lambda pair: pos_of[pair[0]])

    def expand(i: int, acc: list[int]) -> None:
        """Frame 的**展开绘制序**：成员按绘制序排，成员里的子 Frame 就地递归展开。

        这就是输出端真正会画出来的顺序（`render_design` 把成员按绘制序 append 进
        Frame，子 Frame 的成员又在它自己那一笔上展开）。
        """
        for member, _item in by_paint(plans[i][1]):
            acc.append(member)
            if member in plans:
                expand(member, acc)

    def collect(i: int, members: list[tuple[int, dict]], acc: set[int]) -> None:
        """把成员闭包收进 `acc`：成员自己 + 成员里的子 Frame 的成员（递归）。"""
        for member, _item in members:
            if member in acc:
                continue
            acc.add(member)
            plan = plans.get(member)
            if plan is not None:
                collect(member, by_paint(plan[1]), acc)

    def solve(i: int) -> None:
        if i in last:
            return
        layout, members = plans[i]
        paint_members = by_paint(members)
        closure: set[int] = set()
        collect(i, paint_members, closure)
        children_ok = True
        end = pos_of[i]
        for member, _item in paint_members:
            if member in plans:
                solve(member)
                children_ok = children_ok and built[member]
            end = max(end, last.get(member, pos_of[member]))
        last[i] = end
        expanded: list[int] = []
        expand(i, expanded)
        exp_rank = {idx: rank for rank, idx in enumerate(expanded)}

        def order_flips() -> bool:
            """展开序里**相交**的两个图元先后被翻转过吗？

            展开序 = 输出端真正 append 进 Frame 的子节点顺序；真实扁平序 = `paint_order`。
            两者对不相交的图元谁先谁后都无所谓（钉死后位置不变、互不遮挡），只有当两个
            图元**矩形相交**、先后又反了，层序才会真的变 —— 那才建不得。
            """
            for u, v in itertools.combinations(closure, 2):
                if (exp_rank[u] - exp_rank[v]) * (pos_of[u] - pos_of[v]) < 0:
                    if _intersects(rect_of[u], rect_of[v]):
                        return True
            return False

        if not children_ok:
            why = "child-frame-dropped"
        elif order_flips():
            why = "member-order"
        elif any(pos_of[member] < pos_of[i] for member, _item in paint_members):
            why = "member-before-frame"
        elif any(
            not _intersects(rect_of[member], rect_of[i])
            for member, _item in paint_members
        ):
            why = "member-outside-frame"
        else:
            why = None
            for k in seq[pos_of[i] + 1 : end + 1]:
                rect = rect_of[k]
                if (
                    rect is not None
                    and k not in closure
                    and _intersects(rect, rect_of[i])
                ):
                    why = "covers-other-element"
                    break
            if why is None:
                why = _pin_reason(elements, i, paint_members)
        built[i] = why is None
        if why is not None:
            note(i, why)

    for i in plans:
        solve(i)

    out: dict[int, dict] = {}
    for i, (layout, members) in plans.items():
        if not built[i]:
            continue
        paint_members = by_paint(members)
        out[i] = {"layout": layout, "members": paint_members, "end": last[i]}
    return out
