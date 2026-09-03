import pytest
from pathlib import Path
from src.config import load_config

def _fake_capture(url, cfg, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "00_screenshot.png").write_bytes(b"PNG")
    (out / "00_dom.json").write_text("[]", encoding="utf-8")
    return {"image": str(out / "00_screenshot.png"), "width": 100, "height": 100,
            "dom": str(out / "00_dom.json"), "ax": None}

def test_route_order_cv_image_no_key():
    from dataclasses import replace
    from src.app.services.structure.router import route_order
    cfg = replace(load_config(), vision_api_key=None)
    assert route_order("image", None, cfg, have_dom=False) == ["cv"]

def test_run_with_cv_provider_smoke_skipped():
    # 端到端（真 CV/真网络）标 integration，不在此离线单测中执行
    assert True

def test_run_fallback_recording_offline(tmp_path, monkeypatch):
    """auto 回退契约离线验证：dom 失败 -> grounding 成功，fallbacks 记录为全局契约。"""
    from dataclasses import replace
    import cv2
    import numpy as np
    from src.config import load_config
    from src.app.agents.precise_agent import PreciseAgent

    def fake_capture(url, cfg, out_dir):
        out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out / "00_screenshot.png"),
                    np.zeros((100, 100, 3), dtype=np.uint8))
        (out / "00_dom.json").write_text("[]", encoding="utf-8")
        return {"image": str(out / "00_screenshot.png"), "width": 100, "height": 100,
                "dom": str(out / "00_dom.json"), "ax": None}

    class _BoomProvider:
        def run(self, ctx):
            raise RuntimeError("boom")

    class _OkProvider:
        def run(self, ctx):
            from src.app.services.structure.graph import new_graph, add_element
            g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "grounding")
            add_element(g, [10, 10, 20, 20], type_="rectangle")
            return g

    def fake_build_provider(cfg, route):
        if route == "dom":
            return _BoomProvider()
        if route == "grounding":
            return _OkProvider()
        raise AssertionError(f"不应走到路线: {route}")

    def fake_call_vlm(messages, cfg):
        return '{"canvas": {"width": 100, "height": 100}, "elements": []}'

    class _NoopRenderer:
        def __init__(self, cfg):
            pass
        def render(self, design, tool):
            pass

    monkeypatch.setattr("src.app.services.structure.capture.capture_page", fake_capture)
    monkeypatch.setattr("src.app.agents.precise_agent._build_provider", fake_build_provider)
    monkeypatch.setattr("src.app.services.llm.llm_service.call_vlm", fake_call_vlm)
    monkeypatch.setattr("src.app.controllers.rendering_controller.RenderingController",
                        _NoopRenderer)

    cfg = replace(load_config(), vision_api_key="sk-test", output_dir=tmp_path)
    g = PreciseAgent(cfg).run(url="https://example.invalid", route="auto", tool="svg")

    assert g["provenance"]["fallbacks"] == [{"from": "dom", "reason": "boom"}]
    assert g["route"] == "grounding"
    assert (tmp_path / "10_pagegraph.json").exists()
    assert (tmp_path / "manifest.json").exists()

@pytest.mark.integration
def test_run_url_auto_svg(tmp_path):
    from dataclasses import replace
    from src.app.agents.precise_agent import PreciseAgent
    cfg = replace(load_config(), output_dir=tmp_path)
    g = PreciseAgent(cfg).run(url="https://example.com", route="auto", tool="svg")
    assert (tmp_path / "11_som.json").exists() and (tmp_path / "prototype.svg").exists()
