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

def _run_provider(tmp_path, nodes, w=800, h=600):
    p = tmp_path / "dom.json"
    p.write_text(json.dumps(nodes), encoding="utf-8")
    ctx = ProviderContext(image_path="x.png", image_w=w, image_h=h,
                          dom_path=str(p), route="dom", output_dir=str(tmp_path))
    return DomProvider().run(ctx)


def _a_button(x, y, w, h, aria=""):
    return {"tag": "a", "role": "", "ariaLabel": aria, "text": "", "x": x, "y": y,
            "w": w, "h": h, "bg": "rgba(0, 0, 0, 0)",
            "pageBg": "rgb(255, 255, 255)", "interactive": True}


def test_dom_provider_does_not_backfill_visible_caption(tmp_path):
    """按钮真实标题来自子 span（如表头排序触发器）时，不拿图标 aria 覆盖；
    标题作为独立 text 元素保留，按钮保持空（现状不回填）。"""
    nodes = [
        _a_button(200, 100, 80, 24),
        {"tag": "span", "role": "", "ariaLabel": "", "text": "生产单号",
         "x": 200, "y": 103, "w": 60, "h": 16, "bg": "rgba(0, 0, 0, 0)",
         "pageBg": "rgb(255, 255, 255)", "interactive": False},
        {"tag": "i", "role": "", "ariaLabel": "图标: caret-up", "text": "",
         "x": 262, "y": 103, "w": 14, "h": 14, "bg": "rgba(0, 0, 0, 0)",
         "pageBg": "rgb(255, 255, 255)", "interactive": False},
    ]
    g = _run_provider(tmp_path, nodes)
    btns = [e for e in g["elements"] if e["type"] == "button"]
    assert len(btns) == 1 and not btns[0]["text"]       # 标题由下方 text 元素承担
    assert any(e["type"] == "text" and e["text"] == "生产单号" for e in g["elements"])


def test_dom_provider_uses_own_non_icon_aria(tmp_path):
    """按钮自身带真实可读 aria（无“图标:”前缀）时原样作为 ariaLabel 候选。"""
    nodes = [_a_button(50, 50, 30, 24, aria="关闭")]
    g = _run_provider(tmp_path, nodes)
    btn = next(e for e in g["elements"] if e["type"] == "button")
    assert btn["text"] == "" and btn["ariaLabel"] == "关闭"


def test_dom_provider_passes_aria_and_title_through(tmp_path):
    nodes = [{"tag": "a", "role": "", "ariaLabel": "图标: form", "text": "",
              "title": "编辑表单", "x": 100, "y": 200, "w": 57, "h": 19,
              "bg": "rgba(0, 0, 0, 0)", "pageBg": "rgb(255,255,255)",
              "interactive": True}]
    g = _run_provider(tmp_path, nodes)
    btn = next(e for e in g["elements"] if e["type"] == "button")
    assert btn["text"] == ""                 # 核心不做语义回填
    assert btn["ariaLabel"] == "图标: form"  # 候选原样透传
    assert btn["title"] == "编辑表单"


def test_dom_provider_text_never_inferred_from_aria(tmp_path):
    nodes = [
        _a_button(100, 200, 57, 19),
        {"tag": "i", "role": "", "ariaLabel": "图标: form", "text": "",
         "x": 100, "y": 203, "w": 14, "h": 14, "bg": "rgba(0, 0, 0, 0)",
         "pageBg": "rgb(255, 255, 255)", "interactive": False},
    ]
    g = _run_provider(tmp_path, nodes)
    btn = next(e for e in g["elements"] if e["type"] == "button")
    assert btn["text"] == "" and btn["ariaLabel"] == "图标: form"
