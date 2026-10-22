# -*- coding: utf-8 -*-
"""三源路由的“选择交互入口”：引导选 URL/截图 与 dom/grounding/cv 路线，再交给 PreciseAgent。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from src.config import Config

ALL_ROUTES = ("auto", "dom", "grounding", "cv")
TOOLS = ("svg", "figma", "jsdesign", "mockingbot", "axure")

ROUTE_HINTS = {
    "auto":      "自动：URL 可直接访问就走 DOM；无头被反爬拦截时切真实会话自主截图，再失败才报错",
    "dom":       "网页真实 DOM -> computed style 规则直出（几何/样式保真、不调模型）—— 被拦截时直接报错，不静默降级",
    "grounding": "VLM 语义链：多模态模型看图出结构 -> SoM -> VLM 生成 DesignSpec（需 VISION_API_KEY）",
    "cv":        "纯像素 CV 管线（OmniParser）出结构 -> VLM 语义生成 —— 可直接作为主处理方向",
}
TOOL_HINTS = {
    "svg":       "离线验证，输出 prototype.svg（推荐先跑这个）",
    "figma":     "实时写入 Figma（需先起 bridge_server 并运行插件）",
    "jsdesign":  "JSDesign 适配器（桩：尚未实现）",
    "mockingbot": "墨刀适配器（桩：尚未实现）",
    "axure":     "Axure RP 8 直出：从零生成 .rp（几何 / 颜色 / 圆角 / 文字 / 图片）",
}


def route_options(input_kind: str, cfg: "Config") -> list[str]:
    opts = ["auto"]
    if input_kind == "url":
        opts += ["dom"]
        if cfg.vision_api_key:
            opts.append("grounding")
        opts.append("cv")
    else:
        if cfg.vision_api_key:
            opts.append("grounding")
        opts.append("cv")
    return opts


def prompt_choice(prompt: str, options: list[str], default: int,
                  ask: Callable[[str], str]) -> str:
    lines = [prompt]
    for i, opt in enumerate(options, 1):
        mark = " [默认]" if i == default else ""
        lines.append(f"  {i}) {opt}{mark}")
    while True:
        raw = (ask("\n".join(lines) + "\n> ") or "").strip()
        if raw == "":
            return options[default - 1]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]


def select_interactive(cfg: "Config", *, ask: Callable[[str], str] = input,
                       runner=None, prefill: dict | None = None) -> dict:
    prefill = prefill or {}
    if prefill.get("url") or prefill.get("image"):
        input_kind = "url" if prefill.get("url") else "image"
        url, image = prefill.get("url"), prefill.get("image")
    else:
        src = prompt_choice("输入来源？", ["网页 URL（可 dom）", "本地截图（grounding/cv）"],
                            default=1, ask=ask)
        if src == "网页 URL（可 dom）":
            while True:
                url = (ask("网页地址 (https://...)：") or "").strip()
                if url.lower().startswith(("http://", "https://")):
                    break
            image, input_kind = None, "url"
        else:
            while True:
                image = (ask("截图路径：") or "").strip()
                if Path(image).exists():
                    break
            url, input_kind = None, "image"

    opts = route_options(input_kind, cfg)
    route_default = prefill.get("route") or "auto"
    if route_default not in opts:
        route_default = "auto"
    route = prompt_choice("处理路线？", opts, default=max(1, opts.index(route_default) + 1),
                          ask=ask)
    tool_default = prefill.get("tool") or cfg.prototype_tool
    if tool_default not in TOOLS:
        tool_default = "svg"
    tool = prompt_choice("输出工具？", list(TOOLS),
                         default=max(1, list(TOOLS).index(tool_default) + 1),
                         ask=ask)
    req = {"url": url, "image": image, "route": route, "tool": tool}
    if runner is not None:
        req["exit_code"] = runner(req)
    return req
