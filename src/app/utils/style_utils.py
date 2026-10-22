# -*- coding: utf-8 -*-
"""computed style → DesignSpec 样式字段的解析/归一。"""

from __future__ import annotations

import re

from src.app import tuning

# 注意：本模块的"经验阈值"（透明度下限、投影层数上限）在 `src/app/tuning.py`
# 单一定义（env 可覆盖），调用时读；这里只留真正的结构常量。

# computed 字体栈长度上限：超长的（多为站点自定义堆叠）不值得写进 DesignSpec
_MAX_FONT_FAMILY_LEN = 300

_RGB_RE = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)"
)


def parse_css_rgb(value) -> tuple[int, int, int, float] | None:
    """解析 computed style 的 rgb()/rgba()，返回 (r, g, b, alpha)；无法解析返回 None。"""
    m = _RGB_RE.match((value or "").strip().lower())
    if not m:
        return None
    return (
        int(m.group(1)),
        int(m.group(2)),
        int(m.group(3)),
        float(m.group(4)) if m.group(4) is not None else 1.0,
    )


def paints_color(value) -> bool:
    """该 computed 颜色是否真的会画出来（透明/无法解析/极淡都不算）。"""
    rgba = parse_css_rgb(value)
    return bool(rgba and rgba[3] > tuning.MIN_PAINT_ALPHA)


def _hex_to_rgb(hex_color) -> tuple[int, int, int] | None:
    text = (hex_color or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return None


def css_color_to_hex(value, bg: str | None = None) -> str | None:
    """把 computed style 的 rgb()/rgba() 转成 #RRGGBB；透明/无法解析返回 None。

    alpha<1 且给了 bg（实心底色 #RRGGBB，一般取节点背后的实心背景）时按 alpha
    合成成实心 hex：浏览器是把半透明文字/底色画在背后图层上的，而直出稿只有实心
    hex，不合成就会把 rgba(0,0,0,.65) 这类正文判成透明、回退成纯黑（比原 UI 更黑）。
    未给 bg 时保留旧行为：alpha<1 一律返回 None。
    """
    rgba = parse_css_rgb(value)
    if rgba is None:
        return None
    r, g, b, alpha = rgba
    if alpha < 0.99:
        base = _hex_to_rgb(bg)
        if base is None:
            return None
        r = int(alpha * r + (1 - alpha) * base[0] + 0.5)
        g = int(alpha * g + (1 - alpha) * base[1] + 0.5)
        b = int(alpha * b + (1 - alpha) * base[2] + 0.5)
    return "#%02x%02x%02x" % (r, g, b)


def css_px(value) -> int | None:
    """解析 computed style 的 px 数值，如 '14px' -> 14；非数值返回 None。"""
    text = (value or "").strip().lower()
    m = re.match(r"^([\d.]+)px$", text)
    if not m:
        return None
    return int(float(m.group(1)))


def css_px_float(value) -> float | None:
    """解析可为小数/负数的 px（letter-spacing 允许 -0.2px、0.5px）；非 px 返回 None。"""
    text = (value or "").strip().lower()
    m = re.match(r"^(-?[\d.]+)px$", text)
    if not m:
        return None
    return float(m.group(1))


def parse_border_radius(value) -> tuple[int, list[int] | None] | None:
    """computed `border-radius` → (标量半径, 四角 [tl,tr,br,bl] 或 None)。

    CSS 简写最多四值，顺序 tl/tr/br/bl（"4px 4px 0 0" = 上圆下直角）。旧实现用
    `css_px` 只认单值，遇到四值简写整条返回 None —— 页面上"顶部圆角卡片/标签页"
    的圆角因此被整块丢掉（Figma 与 SVG 两端都画成直角）。这里把四角解出来：均匀时
    仍回标量（老产物逐字节不变），只有真的非均匀才回四角列表。斜杠语法（椭圆角）
    与百分比不表达，返回 None（两端都不支持）。
    """
    text = (value or "").strip().lower()
    if not text or "/" in text:
        return None
    parts = [p for p in re.split(r"\s+", text) if p]
    if not 1 <= len(parts) <= 4:
        return None
    nums: list[int] = []
    for part in parts:
        # computed 值都是 px（"14px" / "14px 14px 0px 0px"）；裸 0 是 CSS 简写的
        # 合法写法（手写 IR 会遇到），只放行这一种无单位形式。
        m = re.match(r"^([\d.]+)(px)?$", part)
        if not m or (m.group(2) is None and float(m.group(1)) != 0):
            return None
        nums.append(int(round(float(m.group(1)))))
    if len(nums) == 1:
        corners = nums * 4
    elif len(nums) == 2:
        corners = [nums[0], nums[1], nums[0], nums[1]]
    elif len(nums) == 3:
        corners = [nums[0], nums[1], nums[2], nums[1]]
    else:
        corners = list(nums)
    corners = [max(0, c) for c in corners]
    uniform = max(corners)
    if uniform <= 0:
        return None
    if len(set(corners)) == 1:
        return uniform, None
    return uniform, corners


def parse_opacity(value) -> float | None:
    """computed opacity → 0..1 的浮点；缺省 1 / 非法值返回 None（不写字段）。"""
    try:
        op = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if 0.0 < op < 1.0:
        return round(op, 3)
    return None


def css_font_weight(value) -> str | None:
    """把 computed fontWeight 归一到 normal/bold。"""
    text = (value or "").strip().lower()
    if text in ("bold", "bolder"):
        return "bold"
    if text in ("normal", "lighter"):
        return "normal"
    try:
        return "bold" if int(float(text)) >= 600 else "normal"
    except (TypeError, ValueError):
        return None


def css_font_weight_value(value) -> int | None:
    text = (value or "").strip().lower()
    if text in {"normal", "regular"}:
        return 400
    if text in {"bold", "bolder"}:
        return 700
    try:
        weight = int(round(float(text)))
    except (TypeError, ValueError):
        return None
    return weight if 1 <= weight <= 1000 else None


def css_font_family(value) -> str | None:
    """归一 computed fontFamily：压空白、去掉 XML 不安全的字符；无效返回 None。

    SVG/Figma 输出把字体栈原样写进属性，所以这里必须挡掉 < > & 这类会破坏
    标记的字符，并限制长度（computed 字体栈通常 <200 字符）。
    """
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text or len(text) > _MAX_FONT_FAMILY_LEN:
        return None
    if any(ch in text for ch in "<>&"):
        return None
    return text


# computed box-shadow 里的长度值（px，可为负）与颜色
_SHADOW_LEN_RE = re.compile(r"(-?[\d.]+)px")
_SHADOW_FUNC_RE = re.compile(r"rgba?\([^)]*\)")
_SHADOW_HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})")


def _split_shadow_layers(text: str) -> list[str]:
    """按顶层逗号切分多层投影——逗号也会出现在 rgba(...) 里，要跳过括号内部。"""
    layers, depth, buf = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            layers.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    layers.append("".join(buf))
    return [s.strip() for s in layers if s.strip()]


def _parse_shadow_color(token: str) -> tuple[str, float] | None:
    """投影颜色 → (#rrggbb, alpha)；解析不了返回 None。"""
    rgba = parse_css_rgb(token)
    if rgba is not None:
        return "#%02x%02x%02x" % rgba[:3], rgba[3]
    m = _SHADOW_HEX_RE.match((token or "").strip())
    if not m:
        return None
    digits = m.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    if len(digits) == 8:  # #RRGGBBAA
        return ("#" + digits[:6].lower(), int(digits[6:8], 16) / 255.0)
    if len(digits) == 6:
        return "#" + digits.lower(), 1.0
    return None


def parse_box_shadow(value) -> list[dict]:
    """computed `box-shadow` → 结构化投影列表（DesignSpec `style.shadows`）。

    直出端原先完全不采投影，antd 固定列的“滚动阴影”（`rgba(0,0,0,.15) -6px 0 6px -4px`）
    与表格卡片的 `rgb(234,234,234) 1px 1px 2px 2px` 因此一直缺失——截图里表格左右缘
    那几条 2~4px 渐变竖线在直出稿里没有。输出端据此绘制：SVG 用 rect + feGaussianBlur，
    Figma 用 DROP_SHADOW 效果。

    内阴影（inset）需要反向裁剪，输出端不表达，直接跳过；模糊与扩散都为 0 且没有偏移
    的层完全被自身盖住，也跳过。返回 [{"dx","dy","blur","spread","color","alpha"}...]。
    """
    if not value:
        return []
    shadows: list[dict] = []
    for layer in _split_shadow_layers(str(value)):
        if "inset" in layer.lower():
            continue
        color, rest = None, layer
        m = _SHADOW_FUNC_RE.search(layer) or _SHADOW_HEX_RE.search(layer)
        if m:
            color = _parse_shadow_color(m.group(0))
            rest = layer[: m.start()] + " " + layer[m.end() :]
        lengths = [float(v) for v in _SHADOW_LEN_RE.findall(rest)]
        dx = lengths[0] if len(lengths) > 0 else 0.0
        dy = lengths[1] if len(lengths) > 1 else 0.0
        blur = lengths[2] if len(lengths) > 2 else 0.0
        spread = lengths[3] if len(lengths) > 3 else 0.0
        hex_color, alpha = color or ("#000000", 1.0)
        if alpha < tuning.MIN_PAINT_ALPHA:
            continue
        if blur <= 0 and spread <= 0 and dx == 0 and dy == 0:
            continue
        shadows.append(
            {
                "dx": round(dx, 2),
                "dy": round(dy, 2),
                "blur": round(blur, 2),
                "spread": round(spread, 2),
                "color": hex_color,
                "alpha": round(alpha, 3),
            }
        )
        if len(shadows) >= tuning.MAX_SHADOWS:
            break
    return shadows


def build_style(
    bg=None,
    page_bg=None,
    color=None,
    fontSize=None,
    fontWeight=None,
    borderRadius=None,
    borderColor=None,
    borderWidth=None,
    fontFamily=None,
    boxShadow=None,
    letterSpacing=None,
    opacity=None,
    lineHeight=None,
    textAlign=None,
    whiteSpace=None,
    lineClamp=None,
    keep_page_color: bool = False,
    bg_under: str | None = None,
    borderStyle=None,
) -> dict:
    """把原始 CSS 值归一成 DesignSpec style 字段（透明/缺失不写）。

    borderColor/borderWidth 必须成对有效才写：computed borderColor 在无边框时
    也会是 rgb(0,0,0) 之类的默认色，单独判断 color 会误加黑边。
    fontFamily 只由带可见文本的节点传入（输出端只给文本用），压成单行后原样保留，
    供 SVG 文本按页面字体栈渲染——缺省时输出端用通用系统字体栈兜底。
    默认把等于页面背景的填色当“网格原生白底”省掉；
    当该节点被一个非页面背景的祖先覆盖时，白底是“叠在灰底上的白卡”，
    设 keep_page_color=True 以保留 fillColor。
    bg_under 是本节点背后的实心底色（#RRGGBB，由调用方按祖先图层算好）；半透明的
    fillColor/textColor 按它 alpha 合成成实心 hex，缺省时退回页面底色/白。
    """
    style: dict = {}
    page_hex = css_color_to_hex(page_bg)
    under_hex = bg_under or page_hex or "#ffffff"
    bg_hex = css_color_to_hex(bg, bg=under_hex) if paints_color(bg) else None
    if bg_hex and (bg_hex != page_hex or (keep_page_color and page_hex)):
        style["fillColor"] = bg_hex
    if paints_color(color):
        # 文字画在自身底色上（自身透明则落在背后底色上），半透明色按它合成实心
        color_hex = css_color_to_hex(color, bg=bg_hex or under_hex)
        if color_hex:
            style["textColor"] = color_hex
    fs = css_px(fontSize)
    if fs:
        style["fontSize"] = fs
    fw = css_font_weight(fontWeight)
    if fw:
        style["fontWeight"] = fw
    fw_value = css_font_weight_value(fontWeight)
    if fw_value is not None and fw_value not in {400, 700}:
        style["fontWeightValue"] = fw_value
    ff = css_font_family(fontFamily)
    if ff:
        style["fontFamily"] = ff
    shadows = parse_box_shadow(boxShadow)
    if shadows:
        style["shadows"] = shadows
    radius = parse_border_radius(borderRadius)
    if radius:
        style["borderRadius"] = radius[0]
        if radius[1]:
            style["borderRadiusCorners"] = radius[1]
    border_hex = css_color_to_hex(borderColor)
    bw = css_px(borderWidth)
    if border_hex and bw:
        style["borderColor"] = border_hex
        style["borderWidth"] = bw
        border_style = str(borderStyle or "").strip().lower()
        if border_style in {"inset", "outset", "groove", "ridge"}:
            style["borderStyle"] = border_style
    # 排版/换行：lineHeight 是"这个盒子能放几行"的分母，textAlign 决定折行后
    # 各行怎么对齐，whiteSpace=nowrap / -webkit-line-clamp 是浏览器自己给的规则。
    lh = css_px(lineHeight)
    if lh:
        style["lineHeight"] = lh
    align = (textAlign or "").strip().lower()
    if align:
        style["textAlign"] = align
    if (whiteSpace or "").strip().lower() == "nowrap":
        style["whiteSpace"] = "nowrap"
    try:
        clamp = int(float(str(lineClamp).strip()))
    except (TypeError, ValueError):
        clamp = 0
    if clamp > 1:
        style["maxLines"] = clamp
    # 字距：computed 常带 "normal"（不缺省时是 0），只有真的非零才写；px 原样透传
    # （可为负，Figma 用 PIXELS、SVG 用 letter-spacing，两端口径一致）。
    ls = css_px_float(letterSpacing)
    if ls is not None and abs(ls) >= 0.01:
        style["letterSpacing"] = round(ls, 2)
    # 元素透明度：整棵子树的合成系数，两端都下发（Figma node.opacity / SVG opacity）。
    op = parse_opacity(opacity)
    if op is not None:
        style["opacity"] = op
    return style
