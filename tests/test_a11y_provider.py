# -*- coding: utf-8 -*-
"""A11y provider 离线测试：由 AX JSON（CDP getFullAXTree）构建 PageGraph。"""
from __future__ import annotations

import json

from src.app.services.structure.graph import assign_ids, assign_parent_depth
from src.app.services.structure.providers.a11y import A11yProvider
from src.app.services.structure.providers.base import ProviderContext


def _mk_ax(role, name, x, y, w, h):
    return {"ignored": False, "role": {"value": role}, "name": {"value": name},
            "properties": [{"name": "bounds",
                            "value": {"value": {"x": x, "y": y, "width": w, "height": h}}}],
            "childIds": []}


def _sample_ax(tmp_path):
    nodes = [_mk_ax("banner", "顶栏", 0, 0, 100, 20),
             _mk_ax("button", "登录", 70, 5, 20, 10),
             _mk_ax("heading", "标题", 10, 40, 80, 12)]
    p = tmp_path / "ax.json"
    p.write_text(json.dumps(nodes), encoding="utf-8")
    return str(p)


def test_a11y_provider_basic(tmp_path):
    ctx = ProviderContext(image_path="x.png", image_w=100, image_h=100,
                          ax_path=_sample_ax(tmp_path), route="a11y", output_dir=str(tmp_path))
    g = A11yProvider().run(ctx)
    assign_ids(g)
    assign_parent_depth(g)
    assert any(c["role"] == "banner" for c in g["containers"])
    types = {e["type"] for e in g["elements"]}
    assert "button" in types and "text" in types
    assert g["elements"][0]["text"] == "登录"
