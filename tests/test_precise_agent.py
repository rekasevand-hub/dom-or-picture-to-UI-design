import pytest
from pathlib import Path
from src.config import load_config

def _fake_capture(url, cfg, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "00_screenshot.png").write_bytes(b"PNG")
    (out / "00_dom.json").write_text("[]", encoding="utf-8")
    return {"image": str(out / "00_screenshot.png"), "width": 100, "height": 100,
            "dom": str(out / "00_dom.json")}

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
                "dom": str(out / "00_dom.json")}

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

    def fake_generate(som_json, image_b64, cfg, output_dir=None, **kwargs):
        return {"canvas": {"width": som_json["size"][0], "height": som_json["size"][1]},
                "elements": []}

    class _NoopRenderer:
        def __init__(self, cfg):
            pass
        def render(self, design, tool):
            pass

    monkeypatch.setattr("src.app.services.structure.capture.capture_page", fake_capture)
    monkeypatch.setattr("src.app.agents.precise_agent._build_provider", fake_build_provider)
    monkeypatch.setattr("src.app.services.llm.llm_service.generate_som_design", fake_generate)
    monkeypatch.setattr("src.app.controllers.rendering_controller.RenderingController",
                        _NoopRenderer)

    cfg = replace(load_config(), vision_api_key="sk-test", output_dir=tmp_path)
    g = PreciseAgent(cfg).run(url="https://example.invalid", route="auto", tool="svg")

    assert g["provenance"]["fallbacks"] == [{"from": "dom", "reason": "boom"}]
    assert g["route"] == "grounding"
    assert (tmp_path / "10_pagegraph.json").exists()
    assert (tmp_path / "manifest.json").exists()


def test_capture_receives_storage_state_from_config(tmp_path, monkeypatch):
    """Config.playwright_storage_state 必须传到 capture_page（登录态复用契约）。"""
    import numpy as np
    from dataclasses import replace
    from src.config import load_config
    from src.app.agents.precise_agent import PreciseAgent

    seen = {}

    def fake_capture(url, cfg, out_dir, **kwargs):
        seen["cfg"] = cfg
        seen["kwargs"] = kwargs
        out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
        import cv2
        cv2.imwrite(str(out / "00_screenshot.png"),
                    np.zeros((100, 100, 3), dtype=np.uint8))
        (out / "00_dom.json").write_text("[]", encoding="utf-8")
        return {"image": str(out / "00_screenshot.png"), "width": 100, "height": 100,
                "dom": str(out / "00_dom.json")}

    class _OkProvider:
        def run(self, ctx):
            from src.app.services.structure.graph import new_graph, add_element
            g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "grounding")
            add_element(g, [10, 10, 20, 20], type_="rectangle")
            return g

    def fake_build_provider(cfg, route):
        if route == "grounding":
            return _OkProvider()
        raise AssertionError(f"不应走到路线: {route}")

    def fake_generate(som_json, image_b64, cfg, output_dir=None, **kwargs):
        return {"canvas": {"width": som_json["size"][0], "height": som_json["size"][1]},
                "elements": []}

    class _NoopRenderer:
        def __init__(self, cfg):
            pass

        def render(self, design, tool):
            pass

    monkeypatch.setattr("src.app.services.structure.capture.capture_page", fake_capture)
    monkeypatch.setattr("src.app.agents.precise_agent._build_provider", fake_build_provider)
    monkeypatch.setattr("src.app.services.llm.llm_service.generate_som_design", fake_generate)
    monkeypatch.setattr("src.app.controllers.rendering_controller.RenderingController",
                        _NoopRenderer)

    cfg = replace(load_config(), vision_api_key="sk-test",
                  playwright_storage_state="state.json", output_dir=tmp_path)
    PreciseAgent(cfg).run(url="https://example.invalid", route="grounding", tool="svg")
    assert seen["cfg"] is cfg
    assert seen["cfg"].playwright_storage_state == "state.json"
    assert seen["kwargs"] == {}  # capture_page 不再接收额外关键字参数

@pytest.mark.integration
def test_run_url_auto_svg(tmp_path):
    from dataclasses import replace
    from src.app.agents.precise_agent import PreciseAgent
    cfg = replace(load_config(), output_dir=tmp_path)
    g = PreciseAgent(cfg).run(url="https://example.com", route="auto", tool="svg")
    assert (tmp_path / "11_som.json").exists() and (tmp_path / "prototype.svg").exists()


def test_run_fast_flips_dom_direct_design(tmp_path, monkeypatch):
    """--fast 语义：run 内 replace 出 dom_direct_design=True 的 cfg 并贯穿 try_build_direct_design。"""
    from dataclasses import replace
    import cv2, numpy as np
    from pathlib import Path
    from src.config import load_config
    from src.app.agents.precise_agent import PreciseAgent

    seen = {}
    def fake_capture(url, cfg, out_dir):
        out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out / "00_screenshot.png"), np.zeros((100, 100, 3), dtype=np.uint8))
        (out / "00_dom.json").write_text("[]", encoding="utf-8")
        return {"image": str(out / "00_screenshot.png"), "width": 100,
                "height": 100, "dom": str(out / "00_dom.json")}
    class _OkProvider:
        def run(self, ctx):
            from src.app.services.structure.graph import new_graph
            return new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "dom")
    def fake_build(cfg, route):
        assert route == "dom"
        return _OkProvider()
    def fake_try(som_json, cfg):
        seen["direct_cfg"] = cfg
        return {"canvas": {}, "elements": []}
    class _NoopRenderer:
        def __init__(self, cfg): pass
        def render(self, design, tool): pass
    monkeypatch.setattr("src.app.services.structure.capture.capture_page", fake_capture)
    monkeypatch.setattr("src.app.agents.precise_agent._build_provider", fake_build)
    monkeypatch.setattr("src.app.services.som.direct_design.try_build_direct_design", fake_try)
    monkeypatch.setattr("src.app.controllers.rendering_controller.RenderingController", _NoopRenderer)
    cfg = replace(load_config(), vision_api_key="sk-test", output_dir=tmp_path)
    PreciseAgent(cfg).run(url="https://example.invalid", route="dom", tool="svg", fast=True)
    assert seen["direct_cfg"].dom_direct_design is True
