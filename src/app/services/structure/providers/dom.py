# -*- coding: utf-8 -*-
"""DOM 路线：由 Playwright 收集的 DOM JSON 构建 PageGraph（容器=语义/背景/大区块，元素=交互/文本/图）。"""
from __future__ import annotations

import json

from src.app.services.structure.graph import new_graph, add_container, add_element
from src.app.services.structure.providers.base import BaseProvider, ProviderContext

CONTAINER_ROLES = {"header", "nav", "main", "aside", "footer", "section", "form", "article"}
INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea"}


def _normalize_role(node: dict) -> str:
    return (node.get("role") or "").lower().strip()


def _distinct_bg(node: dict) -> bool:
    bg = (node.get("bg") or "").strip().lower()
    page_bg = (node.get("pageBg") or "").strip().lower()
    if not bg or bg in ("rgba(0, 0, 0, 0)", "transparent"):
        return False
    return bg != page_bg


class DomProvider(BaseProvider):
    name = "dom"

    def run(self, ctx: ProviderContext) -> dict:
        with open(ctx.dom_path, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "dom")
        # 容器候选：语义角色 / 明显背景块 / 大区块(>25% 高或宽 且面积>2000)
        for n in nodes:
            if _normalize_role(n) in CONTAINER_ROLES or _distinct_bg(n) or (
                n["w"] * n["h"] > 2000 and (n["w"] >= ctx.image_w * 0.5 or n["h"] >= ctx.image_h * 0.5)):
                add_container(g, [n["x"], n["y"], n["w"], n["h"]],
                              role=_normalize_role(n) or n["tag"],
                              source=f"dom:{n['tag']}")
        # 元素候选：交互 / 叶子文本 / 图片
        for n in nodes:
            if n["interactive"] or n["tag"] in ("img", "svg") or n.get("text"):
                etype = "button" if n["tag"] in ("button", "a", "select") else (
                    "input" if n["tag"] in ("input", "textarea") else (
                    "image" if n["tag"] in ("img", "svg") else "text"))
                add_element(g, [n["x"], n["y"], n["w"], n["h"]], type_=etype,
                            text=n.get("text", ""), role=_normalize_role(n),
                            source=f"dom:{n['tag']}")
        return g
