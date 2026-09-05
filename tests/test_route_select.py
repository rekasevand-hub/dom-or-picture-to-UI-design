from dataclasses import replace
from src.config import load_config
from src.app.agents.route_select import route_options, select_interactive

def _no_key_cfg():
    return replace(load_config(), vision_api_key=None)

def test_route_options_url_with_key():
    opts = route_options("url", replace(load_config(), vision_api_key="sk-test"))
    assert opts == ["auto", "dom", "grounding", "cv"]

def test_route_options_url_no_key():
    opts = route_options("url", _no_key_cfg())
    assert opts == ["auto", "dom", "cv"]

def test_route_options_image_no_key():
    opts = route_options("image", _no_key_cfg())
    assert opts == ["auto", "cv"]

def test_route_options_image_with_key():
    opts = route_options("image", replace(load_config(), vision_api_key="sk-test"))
    assert opts == ["auto", "grounding", "cv"]

def _mk_image(tmp_path):
    p = tmp_path / "shot.png"
    p.write_bytes(b"fake")
    return str(p)

def _ask_sequence(answers):
    it = iter(answers)
    def ask(_prompt):
        return next(it)
    return ask

def test_select_url_grounding(tmp_path, monkeypatch):
    cfg = replace(load_config(), vision_api_key="sk-test")
    req = select_interactive(cfg, ask=_ask_sequence(["1", "https://example.com", "3", "1"]))
    assert req["url"] == "https://example.com"
    assert req["route"] == "grounding" and req["tool"] == "svg"

def test_select_image_cv_calls_runner(tmp_path, monkeypatch):
    cfg = _no_key_cfg()
    img = _mk_image(tmp_path)
    calls = []
    def runner(request):
        calls.append(request)
        return 0
    req = select_interactive(cfg, ask=_ask_sequence(["2", img, "2", "1"]), runner=runner)
    assert req["image"] == img and req["url"] is None and req["route"] == "cv"
    assert len(calls) == 1 and calls[0] == req

def test_select_invalid_then_valid_retry(tmp_path):
    cfg = _no_key_cfg()
    req = select_interactive(cfg, ask=_ask_sequence(["9", "1", "https://example.com", "1", "1"]))
    assert req["route"] == "auto"
