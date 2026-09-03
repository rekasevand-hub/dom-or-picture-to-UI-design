# -*- coding: utf-8 -*-
"""DOM provider 离线测试：由样例 DOM JSON 构建 PageGraph。"""
from __future__ import annotations

import json

from src.app.services.structure.graph import assign_ids, assign_parent_depth
from src.app.services.structure.providers.dom import DomProvider
from src.app.services.structure.providers.base import ProviderContext


def _sample_dom(tmp_path):
    nodes = [
        {"tag": "body", "role": "", "text": "", "x": 0, "y": 0, "w": 100, "h": 100,
         "bg": "rgb(255,255,255)", "interactive": False},
        {"tag": "header", "role": "", "text": "", "x": 0, "y": 0, "w": 100, "h": 20,
         "bg": "rgb(240,240,240)", "interactive": False},
        {"tag": "button", "role": "", "text": "登录", "x": 70, "y": 5, "w": 20, "h": 10,
         "bg": "rgb(0,120,255)", "interactive": True},
        {"tag": "div", "role": "", "text": "正文标题", "x": 10, "y": 40, "w": 80, "h": 12,
         "bg": "rgb(255,255,255)", "interactive": False},
    ]
    p = tmp_path / "dom.json"
    p.write_text(json.dumps(nodes), encoding="utf-8")
    return str(p)


def test_dom_provider_basic(tmp_path):
    ctx = ProviderContext(image_path="x.png", image_w=100, image_h=100,
                          dom_path=_sample_dom(tmp_path), route="dom", output_dir=str(tmp_path))
    g = DomProvider().run(ctx)
    assign_ids(g)
    assign_parent_depth(g)
    roles = {c["role"] for c in g["containers"]}
    assert "header" in roles                      # 语义容器
    types = {e["type"] for e in g["elements"]}
    assert "button" in types and "text" in types
    assert len(g["containers"]) >= 1 and len(g["elements"]) >= 2
