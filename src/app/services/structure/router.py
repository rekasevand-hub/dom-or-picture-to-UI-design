# -*- coding: utf-8 -*-
"""路由决策：输入形态 × 用户选择 → 候选路线（显式=单候选+校验，auto=回退链）。"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.config import Config

def route_order(input_kind: str, requested: str | None, cfg: "Config", have_dom: bool) -> list[str]:
    valid = {"dom", "grounding", "cv"}
    if requested and requested not in valid:
        raise ValueError(f"未知路线: {requested}")
    dom_ok = (input_kind == "url") and have_dom
    if requested:
        if requested in ("dom",) and not dom_ok:
            raise ValueError(f"路线 {requested} 需要网页 DOM 数据；当前输入为 {input_kind}，请改用 --url 或选 grounding/cv")
        return [requested]
    if input_kind == "url" and have_dom:
        chain = ["dom", "grounding", "cv"]
    else:
        chain = []
        if cfg.vision_api_key:
            chain.append("grounding")
        chain.append("cv")
    return chain
