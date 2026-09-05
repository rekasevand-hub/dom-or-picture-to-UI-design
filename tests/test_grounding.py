# -*- coding: utf-8 -*-
"""Grounding 提供器离线测试：VLM JSON 解析/裁剪/白名单 + Provider 构建 PageGraph（fake 后端）。"""
from __future__ import annotations

from src.app.services.structure.backends.grounding_vlm import parse_vlm_json


def test_parse_vlm_json_clamps():
    # bbox 语义为 0~1 归一化角坐标 [x,y,x2,y2]（与 PROMPT/parse 实现一致）：画布 100x80，
    # 容器归一化坐标出界(<0 或 >1) -> clamp 回 [0,1] 后还原整图 [0,0,100,80]；
    # 元素完全在画布内 -> 转 (x,y,w,h) 后原样 [10,10,50,20]。
    raw = ('{"containers": [{"bbox": [-0.05, -0.1, 2.0, 1.0]}], '
           '"elements": [{"bbox": [0.1, 0.125, 0.6, 0.375], "type": "button", "text": "hi"}]}')
    out = parse_vlm_json(raw, 100, 80)
    assert out["containers"][0]["bbox"] == [0, 0, 100, 80]
    assert out["elements"][0]["bbox"] == [10, 10, 50, 20]


def test_parse_vlm_json_rejects_bad_type():
    raw = '{"elements": [{"bbox": [1, 2, 3, 4], "type": "spaceship"}]}'
    out = parse_vlm_json(raw, 100, 100)
    assert out["elements"] == []


def test_grounding_provider_builds_graph(tmp_path, monkeypatch):
    from src.app.services.structure.providers.grounding import GroundingProvider
    from src.app.services.structure.providers.base import ProviderContext
    from src.app.services.structure.graph import assign_ids
    from src.app.services.structure.backends.grounding_base import GroundingBackend

    class Fake(GroundingBackend):
        def ground(self, image_path, image_w, image_h):
            return {"containers": [{"bbox": [0, 0, 100, 50], "role": "banner"}],
                    "elements": [{"bbox": [10, 10, 20, 20], "type": "button", "text": "确定"}]}

    monkeypatch.setattr("src.app.services.structure.providers.grounding._default_backend",
                        lambda cfg: Fake())
    ctx = ProviderContext(image_path="x.png", image_w=100, image_h=100,
                          route="grounding", output_dir=str(tmp_path))
    g = GroundingProvider(None).run(ctx)
    assign_ids(g)
    assert len(g["containers"]) == 1 and g["elements"][0]["text"] == "确定"
