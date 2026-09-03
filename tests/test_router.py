from dataclasses import replace
import pytest
from src.app.services.structure.router import route_order
from src.config import load_config

@pytest.fixture
def cfg():
    return load_config()

def test_explicit_dom_on_image_raises(cfg):
    with pytest.raises(ValueError, match="dom"):
        route_order("image", "dom", cfg, have_dom=False)

def test_auto_url_prefers_dom(cfg):
    assert route_order("url", None, cfg, have_dom=True)[0] == "dom"

def test_auto_image_no_vision_key(cfg):
    c = replace(cfg, vision_api_key=None)
    assert route_order("image", None, c, have_dom=False) == ["cv"]

def test_auto_image_with_vision_key(cfg):
    c = replace(cfg, vision_api_key="sk-test")
    assert route_order("image", None, c, have_dom=False) == ["grounding", "cv"]

def test_explicit_grounding_on_image_ok(cfg):
    assert "grounding" in route_order("image", "grounding", cfg, have_dom=False)
