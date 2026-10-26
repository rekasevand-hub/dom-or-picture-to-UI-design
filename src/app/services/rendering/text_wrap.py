# -*- coding: utf-8 -*-
"""把一行文本按盒子宽度折成多行：SVG 与 Figma 两个输出端共用同一份折行结果。

直出稿只存"一串文字 + 盒子"，两个输出端都把整串当单行画：`figma_bridge/code.js`
新建的文本默认 auto-size，IR 的 width 被整个忽略；SVG 也只有一个 <text> 元素。
宽 128px 的盒子里放 16px 粗体「数学文化览胜集：教育篇」（约 176px）就会溢出、
压到右边的书名上——真实页在这里是两行（盒子高 43px = 2 x 行高 22px）。

折行只能靠**估算字宽**：浏览器用真实字体度量，而 IR 里没有字形宽度。CJK 在
Microsoft YaHei 这类字体里是全角（advance = font-size），拉丁字母/数字取 0.55em，
整体偏保守——宁可早断，也不能让 Figma 按真实字宽再折一次（二次折行会让行数对不上，
多出一行把盒子撑破）。估算偏保守只影响断点位置，不会让文字溢出盒子。

字距（computed `letter-spacing`）也算进去：CSS 在每个字符后面都补一份，浏览器把这份
余量算进行内盒的 advance；估算漏掉它就会**多塞字**——dushu 的电子书简介 fs=12 /
字距 1px，一行的 16 个字差 16px，正好差两个字（`归档文档 axure_rp8_plan.md` §9.19）。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# 全角（Wide/Fullwidth）字符按 1em 计；其余按 0.55em（Arial 数字 0.556em、
# 小写字母 0.5em 上下），留一点余量。
_LATIN_EM = 0.55
# ASCII 标点单独一档：它们比字母窄得多，按 0.55em 估会**多占**半个字。真机实测
# dushu 电子书简介（fs=12、微软雅黑）里半角逗号的 advance = 3px、圆括号 3~4px；
# Arial 的逗号/句号/分号 0.278em、冒号/括号/感叹号 0.333em。取 0.33em（比实测略宽，
# 宁早断不溢出——§9.19 那条断点就差这 3.6px）。
_PUNCT_EM = 0.33
_PUNCT_CHARS = ",.;:!?()[]{}<>'\"-+*/\\|_"

# 盒子高度能放下多少行：上限只用来挡住"元素盒子高得离谱"的病态输入。
_MAX_LINES_CAP = 20
# 估算宽度超过盒子这么多才算真的放不下（估算有误差，3% 以内当噪声）。
_OVERFLOW_RATIO = 1.03
# 「盒子就是这一行文字自己撑出来的」判定窗：估算宽度落在 [下限, _OVERFLOW_RATIO]
# 里就认为盒宽 = 一行文字的宽（行内元素 / 自动宽控件），即**零余量**。上限跟折行
# 那条同一个口径——超过它 `wrap_for_spec` 自己就折了，轮不到这里。
_OWN_BOX_RATIO_LO = 0.95

# 行首禁则：这些字符不能出现在行首（断在它们前面既难看、也与浏览器不一致）。
# 末尾那个半角逗号与全角「，」同类：它自己**能**收尾（见 `_can_end_line`），但断在
# 它前面就成了「…江琬」/「,字苕文」——真机 dushu 的电子书简介不是这么断的（§9.19）。
_NO_BREAK_BEFORE = "\uff09\u3011\u300b\u3009\u300d\u300f\u201d\u2019\u3001\u3002\uff0c\uff1b\uff1a\uff1f\uff01\u2026\u00b7\uff05\uff0c)]},"
# 行尾禁则：这些字符不能出现在行尾
_NO_BREAK_AFTER = "\uff08\u3010\u300a\u3008\u300c\u300e\u201c\u2018([{\uffe5$"

_TEXT_COMPONENT_STATUSES = {
    "pass",
    "partial",
    "fail",
    "unknown",
    "not-evaluated",
    "not-required",
}


@dataclass(frozen=True, slots=True)
class TextAcceptance:
    content: str
    linebreak: str
    box: str
    baseline: str
    glyph: str

    def __post_init__(self) -> None:
        for name in ("content", "linebreak", "box", "baseline", "glyph"):
            value = getattr(self, name)
            if value not in _TEXT_COMPONENT_STATUSES:
                raise ValueError(f"unknown text component status: {name}={value!r}")

    @property
    def overall(self) -> str:
        statuses = (
            self.content,
            self.linebreak,
            self.box,
            self.baseline,
            self.glyph,
        )
        if "fail" in statuses:
            return "blocked-fail"
        if all(status in {"pass", "not-required"} for status in statuses):
            return "pass"
        if "partial" in statuses:
            return "blocked-partial"
        return "blocked-unknown"

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "linebreak": self.linebreak,
            "box": self.box,
            "baseline": self.baseline,
            "glyph": self.glyph,
            "overall": self.overall,
        }


def char_width(ch: str, font_size: float) -> float:
    """单字估算宽度（px）。"""
    if ch == "\t":
        return 2.0 * font_size
    if unicodedata.combining(ch):
        return 0.0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return font_size
    if ch in _PUNCT_CHARS:
        return font_size * _PUNCT_EM
    return font_size * _LATIN_EM


def estimate_width(text: str, font_size: float, letter_spacing: float = 0.0) -> float:
    """整串文本的估算宽度（px）。

    `letter_spacing` 是 CSS 的 computed `letter-spacing`（px，可负）：CSS 在**每个
    字符后面**都补一份，行内盒的 advance 也把它算进去，所以这里按 `len(text)` 份加。
    """
    return sum(char_width(ch, font_size) for ch in text) + letter_spacing * len(text)


def letter_spacing_of(spec: dict) -> float:
    """IR 的 `letterSpacing`（px，可负）；缺失 / 退化值一律 0（老产物逐字节不变）。"""
    try:
        ls = float(spec.get("letterSpacing"))
    except (TypeError, ValueError):
        return 0.0
    return ls if abs(ls) >= 0.01 else 0.0


def _can_end_line(ch: str) -> bool:
    """ch 能不能当行尾（简体中文的简易禁则 + 拉丁词内不断）。

    CJK 任意字、空格、连字符都能收尾；收尾标点（。，）等）不能——它们必须跟着
    前一个字，所以断点只能落在它们之后（"数学文化览胜集：" 整段收尾，与浏览器一致）。

    半角逗号也能收尾：全角「，」在 `\uff08W\uff09` 那一支里已经能收，半角 `,` 是
    `Na`，漏了它整串就**一个断点都没有**，只能在别的字上硬断。真机 dushu 的电子书
    简介第一行正是断在「…江琬,字苕文,」的逗号之后（§9.19）。其余半角标点（`;` `:`
    与数字里常见的 `.`）没有样本，不动。
    """
    if ch in _NO_BREAK_AFTER:
        return False
    if ch.isspace() or ch in "-\u2013\u2014/,":
        return True
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _pick_cut(current: list, breaks: list, nxt: str) -> int:
    """在 current 里选一个断点；没有合法断点就整行硬断。

    行首禁则（UAX#14 的 LB13）：断点后面的第一个字符不能是收尾标点（。，）等）。
    断点正好落在行尾时，那个"下一个字符"就是还没拼进来的 nxt——所以要带一位
    前瞻：宽 128 的盒子里"一二三四五六七八）"，浏览器宁可把"八"一起挪到下一行，
    也不会让"）"顶在行首。
    """
    if not breaks:
        return len(current)

    def bad_start(index):
        return (current[index] if index < len(current) else nxt) in _NO_BREAK_BEFORE

    cut = breaks[-1]
    while len(breaks) > 1 and bad_start(cut):
        breaks.pop()
        cut = breaks[-1]
    if bad_start(cut):
        return len(current)  # 连一个合法断点都没有：整行硬断（浏览器也是溢出）
    return cut


def ellipsize(
    line: str,
    width: float,
    font_size: float,
    mark: str = "\u2026",
    letter_spacing: float = 0.0,
) -> str:
    """截到连 mark 一起放得下为止（从行尾逐个去掉字符）。"""
    line = line.rstrip()
    while line and estimate_width(line + mark, font_size, letter_spacing) > width:
        line = line[:-1].rstrip()
    return (line + mark) if line else mark


def wrap_lines(
    text: str,
    width: float,
    font_size: float,
    max_lines: int | None = None,
    letter_spacing: float = 0.0,
) -> list[str] | None:
    """把 text 折成每行不超过 width 的行；不需要折行时返回 None。

    max_lines 给定时，超出的行整行丢弃、末行补省略号（对应 CSS 的
    -webkit-line-clamp：真实页就是"只显示 N 行 + 省略号"）。
    """
    if not text or width <= 0 or font_size <= 0:
        return None
    lines: list[str] = []
    current: list[str] = []
    current_w = 0.0
    breaks: list[int] = []  # 在 breaks[-1] 处收行（current[:cut]）是合法的
    for ch in text:
        cw = char_width(ch, font_size) + letter_spacing
        if current and current_w + cw > width:
            cut = _pick_cut(current, breaks, ch)
            head = "".join(current[:cut]).rstrip()
            if head:
                lines.append(head)
            current = current[cut:]
            current_w = estimate_width("".join(current), font_size, letter_spacing)
            breaks = [b - cut for b in breaks if b > cut]
        current.append(ch)
        current_w += cw
        if _can_end_line(ch):
            breaks.append(len(current))
    tail = "".join(current).strip()
    if tail:
        lines.append(tail)
    if len(lines) < 2:
        return None
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = ellipsize(
            lines[-1], width, font_size, letter_spacing=letter_spacing
        )
    return lines


def font_size_of(spec: dict) -> float:
    try:
        size = float(spec.get("fontSize") or 16)
    except (TypeError, ValueError):
        size = 16.0
    return size if size > 0 else 16.0


def line_height_of(spec: dict, font_size: float) -> int:
    """行高：优先用 computed line-height，缺省按 1.4em 估（这批系统 UI 字体的常见值）。"""
    try:
        lh = int(round(float(spec.get("lineHeight"))))
    except (TypeError, ValueError):
        lh = 0
    return lh if lh > 0 else int(round(font_size * 1.4))


def max_lines_of(spec: dict, line_height: int) -> int:
    """这个盒子能画几行：优先 CSS 的 -webkit-line-clamp，否则按高度除以行高。

    按高度推断是这次能修好 dushu 那排书名关键：IR 里没有 clamp 字段，但真实页
    的"两行标题"盒子就是 2 x 行高（h=43 / lh=22）——浏览器既然在这个盒子里排了
    两行，我们照同样行数排就不会错。
    """
    try:
        clamp = int(spec.get("maxLines"))
    except (TypeError, ValueError):
        clamp = 0
    if clamp >= 2:
        return min(clamp, _MAX_LINES_CAP)
    try:
        height = float(spec.get("height") or 0)
    except (TypeError, ValueError):
        height = 0.0
    if height <= 0 or line_height <= 0:
        return 1
    return max(1, min(int(round(height / line_height)), _MAX_LINES_CAP))


def wrap_for_spec(spec: dict) -> list[str] | None:
    """需要折行时返回每行文本；否则 None（调用端据此保持老路径逐字节不变）。"""
    measured = [
        str(line).strip() for line in (spec.get("lines") or []) if str(line).strip()
    ]
    if measured:
        return measured
    text = str(spec.get("text") or "")
    if len(text) < 2 or spec.get("textLineBox"):
        return None
    if str(spec.get("whiteSpace") or "").strip().lower() == "nowrap":
        return None
    try:
        width = float(spec.get("width") or 0)
    except (TypeError, ValueError):
        return None
    font_size = font_size_of(spec)
    letter_spacing = letter_spacing_of(spec)
    body = text.strip()
    if (
        width <= 0
        or estimate_width(body, font_size, letter_spacing) <= width * _OVERFLOW_RATIO
    ):
        return None
    line_height = line_height_of(spec, font_size)
    max_lines = max_lines_of(spec, line_height)
    if max_lines < 2:
        return None
    return wrap_lines(body, width, font_size, max_lines, letter_spacing)


def box_is_own_line(spec: dict) -> bool:
    """盒子是不是「这一行文字自己撑出来的」（盒宽 = 行宽，零余量）。

    行内元素（`<a>` / `<i>` / `<button>`）与自动宽控件的盒宽，就是它那行文字的
    量测宽度，IR 里存的是**四舍五入后的整数**——比真实文字窄零点几像素。发布端拿
    自己的字体度量重排（Axure 把面板发成 `word-wrap:break-word`），差这一丁点就
    **早折一个字符**：真机 dushu 页脚 `<i>01</i>` 盒宽 20px，Arial 18px 的 `01`
    实际 20.016px，折成两行。折行族见 `归档文档 axure_rp8_plan.md` §9.11。

    零余量就是判据本身：盒子有余量（估算宽度不到盒宽的 95%）时发布端折不错，这里
    返回 False，那条路径**逐字节不动**。反过来它也只能认出「盒子就是这一行」——认
    不出「盒子是作者钉死的、而文字恰好占满」，那种元素真实页面上确实两行，这里会
    给它也钉成一行（溢出几个像素）。要分清得让采集端标出「盒宽由内容撑出」。
    """
    if spec.get("lines"):
        return False  # IR 自己折过：这是多行块
    if str(spec.get("whiteSpace") or "").strip().lower() == "nowrap":
        return False  # 页面作者写了 nowrap：走 `_nowrap` 那条路
    text = str(spec.get("text") or "").strip()
    if len(text) < 2:
        return False
    try:
        width = float(spec.get("width") or 0)
    except (TypeError, ValueError):
        return False
    if width <= 0:
        return False
    ratio = estimate_width(text, font_size_of(spec), letter_spacing_of(spec)) / width
    return _OWN_BOX_RATIO_LO <= ratio <= _OVERFLOW_RATIO


def lines_spec_fields(spec: dict, lines: list[str]) -> dict:
    """折行元素下发给输出端的排版字段（行首 x 由调用端按盒子算）。"""
    font_size = font_size_of(spec)
    line_height = line_height_of(spec, font_size)
    if len(lines) == 1 and not spec.get("lineHeight"):
        box = spec.get("textEmBox")
        if isinstance(box, (list, tuple)) and len(box) == 4:
            try:
                measured = int(round(float(box[3])))
            except (TypeError, ValueError):
                measured = 0
            if measured > 0:
                line_height = measured
    align = str(spec.get("textAlign") or "").strip().lower()
    if align in ("center",):
        align = "center"
    elif align in ("end", "right"):
        align = "end"
    else:
        align = "start"
    return {"lines": list(lines), "lineHeight": line_height, "textAlign": align}
