# -*- coding: utf-8 -*-
"""渲染 / 采集的**经验阈值**单一定义点（全局级，env 可覆盖）。

这些数字原来散落在各模块里当魔法数，它们的共同点是：**不是等价规则，是"猜"出来的**
（近白判定、深色判定、文本基线公式、投影保留层数、采集等待……）。改错了不会报错，
只会让像素悄悄变差——所以要有一个能一眼看全、能手改、能测的地方。

为什么不放进 `site_profiles`（站点级那份）：这些是**输出端 / 工具链口径**，不是某个
站点的特化——它们跨路线共用（SVG / Figma / 视觉路线都走），按站点调会把"一个站点的
偏好"变成"所有站点的默认"。要按站点覆盖，得先把调用链上的 profile 打通（见
`site_profiles.DEFAULTS` 与 `HANDOFF` 第 19 节）。

覆盖方式：环境变量 `TUNING_<名字>`，例如 `TUNING_BASELINE_CENTER_EM=0.4`。
类型按默认值推断，转不过去就记一条 warning 用回默认值——手滑不该让整页结果静静变样。

**默认值与当初写死时逐位一致**（`tests/test_tuning.py` 钉住这一点）。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_PREFIX = "TUNING_"
_overridden: dict[str, object] = {}


def _env(name: str, default):
    """读 TUNING_<name>；没设或转不过去就用默认值（后者记 warning）。"""
    raw = os.getenv(_PREFIX + name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = type(default)(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("%s%s = %r 不是 %s，改用默认值 %r",
                       _PREFIX, name, raw, type(default).__name__, default)
        return default
    _overridden[name] = value
    return value


def active_overrides() -> dict[str, object]:
    """当前被 env 覆盖过的项（调试/日志用；没被覆盖就是空 dict）。"""
    return dict(_overridden)


# --- 文本基线（输出端把"元素上沿"换算成"基线"） ------------------------------
# 行框里基线落在"行框中心 + 0.375em"附近（这批系统 UI 字体 cap-height/descender
# 中点距基线的经验值）。实测同页文字笔画 meanDiff 20.8 → 9.9 /255。
BASELINE_CENTER_EM = _env("BASELINE_CENTER_EM", 0.375)

# --- 颜色判定（输出端决定"这层要不要画"） --------------------------------------
# 近白填充：`min(rgb) >= 242 且 max-min <= 10`。低于此 alpha 的颜色按"没画"处理。
COLOR_MIN_ALPHA = _env("COLOR_MIN_ALPHA", 0.05)
WHITE_BG_MIN_RGB = _env("WHITE_BG_MIN_RGB", 242)
WHITE_BG_MAX_SPREAD = _env("WHITE_BG_MAX_SPREAD", 10)
# "彩色/深色衬底"：luma < 0.40 或 饱和度 > 0.25。
DARK_LUMA = _env("DARK_LUMA", 0.40)
CHROME_SAT = _env("CHROME_SAT", 0.25)
# 黑白二选一的分界（衬底上的文字色）。
BW_LUMA = _env("BW_LUMA", 0.5)

# --- 样式解析（computed style → DesignSpec 字段） ------------------------------
# computed 颜色里低于该 alpha 的填色视为"没画"（透明底/极淡装饰层）。
MIN_PAINT_ALPHA = _env("MIN_PAINT_ALPHA", 0.02)
# 单节点最多保留几层投影：多出来的是装饰性堆叠，收益递减。
MAX_SHADOWS = _env("MAX_SHADOWS", 4)

# --- 文本基线像素微调（只走 ±1px） ---------------------------------------------
TEXT_ALIGN_MARGIN = _env("TEXT_ALIGN_MARGIN", 1)          # 元素框外扩，避免越界窗口
TEXT_ALIGN_MIN_BOX = _env("TEXT_ALIGN_MIN_BOX", 8)        # 小于此尺寸的文本不试位移
TEXT_ALIGN_MIN_GAIN = _env("TEXT_ALIGN_MIN_GAIN", 0.2)    # 至少比现状好这么多才接受
TEXT_ALIGN_MIN_RATIO = _env("TEXT_ALIGN_MIN_RATIO", 0.5)  # 且要优于现状的这个倍数
TEXT_ALIGN_BLANK_MEAN = _env("TEXT_ALIGN_BLANK_MEAN", 250.0)  # 截图这块更白 = 没墨迹

# --- 退化尺寸（宽/高小于它就没有可画的东西） ------------------------------------
MIN_BOX_SIZE = _env("MIN_BOX_SIZE", 2)

# --- SoM 标注图（只影响 10_som.png 这种诊断图，不进产物） ----------------------
SOM_ANNOTATE_SCALE = _env("SOM_ANNOTATE_SCALE", 0.5)
SOM_ANNOTATE_THICK = _env("SOM_ANNOTATE_THICK", 1)

# --- 网页采集时序 --------------------------------------------------------------
NAV_IDLE_CAP_MS = _env("NAV_IDLE_CAP_MS", 15000)      # networkidle 最多等这么久
SETTLE_POLL_MS = _env("SETTLE_POLL_MS", 500)          # DOM 增长轮询间隔
SETTLE_STABLE_MS = _env("SETTLE_STABLE_MS", 1500)     # 连续这么久不增长即视为铺完
SETTLE_CAP_MS = _env("SETTLE_CAP_MS", 25000)          # 单次加载最多等这么久
CAPTURE_ATTEMPTS = _env("CAPTURE_ATTEMPTS", 3)        # 哈希深链最多重抓几遍
SETTLE_MIN_MS = _env("SETTLE_MIN_MS", 3000)            # 等 DOM 稳定的预算下限
RESTYLE_SETTLE_MS = _env("RESTYLE_SETTLE_MS", 400)     # 禁动画/过渡后等重排落定
CAPTURE_STATE_POLL_MS = _env("CAPTURE_STATE_POLL_MS", 100)
CAPTURE_STATE_STABLE_MS = _env("CAPTURE_STATE_STABLE_MS", 600)
CAPTURE_STATE_CAP_MS = _env("CAPTURE_STATE_CAP_MS", 5000)
CAPTURE_FONT_POLL_MS = _env("CAPTURE_FONT_POLL_MS", 100)
CAPTURE_FONT_WAIT_MS = _env("CAPTURE_FONT_WAIT_MS", 3000)
LOGIN_SHELL_MS = _env("LOGIN_SHELL_MS", 1000)          # 登录窗口：给 SPA 首屏一点时间
LOGIN_PROMPT_MS = _env("LOGIN_PROMPT_MS", 500)         # 登录窗口：回车后再等一下
