from src.config import load_config, Config

def test_config_new_fields_defaults():
    c: Config = load_config()
    assert c.vision_model == "qwen3-vl-plus"
    assert c.text_model == "deepseek-v4-flash"
    assert c.vision_base_url == "https://www.acctoken.com/v1"
    assert c.route_default == "auto"
    assert c.playwright_viewport_width == 1440
    assert c.device_scale_factor == 1
    assert c.enrich_visual is False

def test_config_new_fields_env():
    import os
    os.environ["VISION_MODEL"] = "x"
    try:
        c = Config()
        assert c.vision_model == "x"
    finally:
        os.environ.pop("VISION_MODEL", None)
