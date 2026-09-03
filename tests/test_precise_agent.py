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

@pytest.mark.integration
def test_run_url_auto_svg(tmp_path):
    from dataclasses import replace
    from src.app.agents.precise_agent import PreciseAgent
    cfg = replace(load_config(), output_dir=tmp_path)
    g = PreciseAgent(cfg).run(url="https://example.com", route="auto", tool="svg")
    assert (tmp_path / "11_som.json").exists() and (tmp_path / "prototype.svg").exists()
