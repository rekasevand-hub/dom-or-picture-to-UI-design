# -*- coding: utf-8 -*-
"""让 LLM 给闭环搜索**提候选**（不给定论）。

分工是刻意的：

- LLM 看页面摘要 + 当前像素报告 + **已经试过的逐条结果**，回答两件事——
  **下一轮先动哪个阈值**、**还有哪些档位没覆盖到的值值得试**。
- 到底哪个值更好，**不由 LLM 说**：搜索脚本会把每个候选真的渲染一遍、和截图逐像素
  比，按 `pixel_metrics` 的排序键判定。所以写进 profile 的永远是"跑出来的最优"，
  不是"模型觉得的最优"。

LLM 的输出只当"建议"，要过一道白名单校验：knob 必须在搜索空间里、值必须是数字且在
合理区间、每个 knob 最多留几条。校验不过就丢掉（不报错），退化成"用默认档跑"。

接进闭环之后它是**每轮问一次**的（`search(..., advisor=...)`）：第 0 轮只看得见 base，
  第 1 轮起能看到"上一轮试了什么、分数怎么变、哪些被采纳"，于是能在
  "相邻两档分数几乎一样""某个键的曲线还在往下走"这类信号上补探新值。
  但即便到第 N 轮，它也**只提建议**：要不要采纳永远由像素判定。

没有 `TEXT_API_KEY` / 调用失败 / 解析失败时，返回默认顺序 + 空候选，搜索结果不受影响。
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

MAX_EXTRA_PER_KNOB = 3
# 值的合理区间（挡住模型写出的离谱数：负数、天文数字、把比例写成 80）
BOUNDS = (0.0, 100000.0)
RATIO_KNOBS = {"container_min_span_ratio"}

_SYSTEM = """你是网页复刻管线的调参助手。管线用一套"经验阈值"从 DOM 直出设计稿，
阈值定义在站点 profile 里。阈值现成的候选档已经跑过一遍，你要做的是：

1. 按"这个页面最可能受哪个阈值影响"排序（最可能先试）；
2. 对其中几个阈值，提出 1~3 个**候选档之外**的数值（例如最佳值落在档位边界上，
   就往两侧再探一格）。

只输出 JSON，不要解释文字：
{
  "knob_order": ["overlay_min_area", "container_min_area", ...],
  "candidates": {"overlay_min_area": [600, 1000]},
  "reason": "一句话说明为什么这样排"
}

要求：
- knob_order 只能用给定的键名，不要发明新键；
- candidates 的键必须在 knob_order 里；值必须是数字；每个键最多 3 个值；
  overlay_min_area / container_min_area 是"面积"，量级 0~20000；
  overlay_min_overlap_px 是像素面积，量级 0~50000；
  overlay_min_overlap_w / _h 是像素长度，量级 0~200；
  edge_max_thickness 是像素，量级 1~64；canvas_min_size 是像素，量级 1~16；
  container_min_span_ratio 是 0~1 的比例（不是百分数）；
- 不确定就不给 candidates（给空对象），排序也照常给。

如果用户消息里带了"已经试过的结果"，那是你上一轮建议的真实打分：**已经试过的
阈值=取值不要重复给**，请据此判断"哪个键还没挖透"再补新值。
"""


def _digest(profile, report: dict, elements: int) -> str:
    """给模型看的页面摘要（都是数值，不带截图，省 token 且可复现）。"""
    lines = [
        "当前像素报告（越小越好）：整图 %.3f/255，笔画 %.3f，>30 占比 %.2f%%，元素 %d 个"
        % (report.get("mean", 0), report.get("ink_mean", 0),
           report.get("over30_pct", 0), elements),
        "分区（max 通道差均值）：" + "、".join(
            "%s %.3f" % (k, v) for k, v in (report.get("regions") or {}).items()),
        "当前站点覆盖：" + (json.dumps(report.get("overrides") or {}, ensure_ascii=False)
                       if report.get("overrides") else "无（全用默认值）"),
    ]
    return "\n".join(lines)


def _history_digest(history: list, tried: dict, knobs: list[str]) -> str:
    """给模型看"上一轮试了什么、结果如何"——多轮优化靠的就是这段。"""
    from src.app.services.structure.profile_search import SEARCHABLE

    items = history or []
    lines = []
    if items:
        lines.append("已经试过的（阈值=取值 -> 整图/笔画，越小越好）：")
        for h in items[-40:]:
            tail = ""
            if h.get("blocked"):
                tail = "（被否决：会把可编辑图层换成位图底）"
            elif h.get("accepted"):
                tail = "（采纳，成为当前最优）"
            lines.append("  第%s轮 %s=%s -> %.3f / %.3f%s"
                         % (h.get("round"), h.get("knob"), h.get("value"),
                            float(h.get("mean") or 0), float(h.get("ink_mean") or 0), tail))
    left = {}
    for k in knobs:
        done = set(tried.get(k) or [])
        rest = [v for v in SEARCHABLE.get(k, []) if v not in done]
        if rest:
            left[k] = rest
    if left:
        lines.append("还没试过的现成档位：" + json.dumps(left, ensure_ascii=False))
    return "\n".join(lines)


def _drop_tried(cands: dict, tried: dict) -> dict:
    """把已经评过的取值剔掉，别浪费模型那几条名额。"""
    out = {}
    for knob, values in (cands or {}).items():
        done = set((tried or {}).get(knob) or [])
        keep = [v for v in values if v not in done]
        if keep:
            out[knob] = keep
    return out


def _knob_catalog(knobs, profile) -> str:
    """列出生效值 + 现成候选档，让模型知道"哪些试过了"。"""
    from src.app.services.structure.profile_search import SEARCHABLE
    from src.app.services.structure.site_profiles import rule as _rule
    out = []
    for k in knobs:
        cur = _rule(profile, "dom", k)
        out.append("  %s：当前 %s，现成候选档 %s" % (k, cur, SEARCHABLE.get(k, [])))
    return "\n".join(out)


def sanitize(raw: dict, knobs: list[str]) -> dict:
    """白名单校验：只留认识的键、合理区间内的数字，去重并限量。"""
    order = [k for k in (raw.get("knob_order") or []) if k in knobs]
    order += [k for k in knobs if k not in order]        # 漏掉的按默认序补在后面
    cands: dict[str, list] = {}
    for knob, values in (raw.get("candidates") or {}).items():
        if knob not in knobs or not isinstance(values, (list, tuple)):
            continue
        keep = []
        for v in values:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            v = float(v) if knob in RATIO_KNOBS else int(round(v))
            if not (BOUNDS[0] <= v <= (1.0 if knob in RATIO_KNOBS else BOUNDS[1])):
                continue
            if v not in keep:
                keep.append(v)
        if keep:
            cands[knob] = keep[:MAX_EXTRA_PER_KNOB]
    return {"knob_order": order, "candidates": cands,
            "reason": str(raw.get("reason") or "")[:400]}


def propose(knobs: list[str], profile, report: dict, *, elements: int = 0,
            cfg=None, caller=None, history: list | None = None,
            tried: dict | None = None) -> dict:
    """向 LLM 要候选；任何一步出问题都降级成"默认顺序 + 空候选"。

    `history` / `tried` 是闭环里已经跑过的结果（见 `search` 的 advisor 参数），
    第 2 轮起带着它们问，模型才是"看着效果调"而不是开局盲猜。
    """
    fallback = {"knob_order": list(knobs), "candidates": {}, "reason": ""}
    try:
        if cfg is None:
            from src.config import load_config
            cfg = load_config()
        if caller is None:
            from src.app.services.llm.llm_service import call_text_llm as caller
        hist = _history_digest(history or [], tried or {}, knobs)
        user = ("页面摘要：\n" + _digest(profile, report, elements)
                + ("\n\n" + hist if hist else "")
                + "\n\n可调阈值（按你的判断排序）：\n" + _knob_catalog(knobs, profile))
        text = caller([{"role": "system", "content": _SYSTEM},
                       {"role": "user", "content": user}], cfg)
        from src.app.services.llm.llm_service import _extract_json_block
        raw = json.loads(_extract_json_block(text))
        if not isinstance(raw, dict):
            raise ValueError("模型返回的不是 JSON 对象")
        out = sanitize(raw, knobs)
        out["candidates"] = _drop_tried(out["candidates"], tried or {})
        logger.info("profile 搜索建议：顺序=%s 额外候选=%s（%s）",
                    out["knob_order"], out["candidates"], out["reason"])
        return out
    except Exception as exc:      # noqa: BLE001 - 建议环节失败不该拖垮搜索
        logger.warning("LLM 建议不可用（%s: %s），改用默认顺序与候选档",
                       type(exc).__name__, exc)
        return fallback
