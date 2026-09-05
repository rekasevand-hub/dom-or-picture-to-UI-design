# -*- coding: utf-8 -*-
"""路由器回归：a11y 已删除，route_order 合法集为 dom/grounding/cv。"""
from dataclasses import replace
from src.config import load_config
from src.app.services.structure.router import route_order


def test_route_set_has_no_a11y():
    cfg = replace(load_config(), vision_api_key=None)
    # route_order 的 requested 参数：auto 由调用侧转成 None（见 precise_agent）
    for chain in (route_order("url", None, cfg, have_dom=True),
                  route_order("url", None, cfg, have_dom=False)):
        assert "a11y" not in chain


def test_dom_route_requires_url_dom():
    cfg = replace(load_config(), vision_api_key=None)
    try:
        route_order("image", "dom", cfg, have_dom=False)
    except ValueError:
        return
    raise AssertionError("dom 在纯图片输入下应报错")
