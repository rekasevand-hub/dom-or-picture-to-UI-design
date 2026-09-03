# -*- coding: utf-8 -*-
"""capture 模块离线测试（integration 需要网络/Chromium，默认跳过）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.app.services.structure.capture import DOM_JS, _ax_bounds


def test_dom_js_present():
    assert "getBoundingClientRect" in DOM_JS


def test_ax_bounds_present():
    props = [{"name": "internal::role", "value": {"value": "button"}},
             {"name": "bounds", "value": {"value": {"x": 1.0, "y": 2.0, "width": 30.0, "height": 20.0}}}]
    assert _ax_bounds(props) == [1, 2, 30, 20]


def test_ax_bounds_missing():
    assert _ax_bounds([{"name": "internal::role", "value": {"value": "button"}}]) is None


@pytest.mark.integration
def test_capture_live(tmp_path):
    from src.config import load_config
    from src.app.services.structure.capture import capture_page
    r = capture_page("https://example.com", load_config(), str(tmp_path))
    assert r["image"] and r["dom"]
    nodes = json.loads(Path(r["ax"]).read_text(encoding="utf-8"))
    assert any(any(p.get("name") == "bounds" for p in node.get("properties", []))
               for node in nodes)
