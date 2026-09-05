from src.config import load_config, Config


_DEFAULT_TEST_KEYS = (
    "VISION_MODEL", "TEXT_MODEL", "VISION_BASE_URL", "VISION_MAX_TOKENS",
    "VISION_TIMEOUT", "TEXT_MAX_TOKENS", "TEXT_TIMEOUT", "ROUTE",
    "PLAYWRIGHT_VIEWPORT_WIDTH", "DEVICE_SCALE_FACTOR", "PLAYWRIGHT_STORAGE_STATE",
    "ENRICH_VISUAL", "SOM_BATCH_ENABLED", "SOM_BATCH_SIZE", "SOM_BATCH_MAX_ROUNDS",
    "SOM_BATCH_MIN_COVERAGE", "SOM_COLOR_BACKFILL", "DOM_DIRECT_DESIGN",
)


def _clean_defaults_config():
    """构造 Config() 前先隔离 .env 污染的环境变量，保证断言的是代码内置默认值。"""
    import os
    saved = {k: os.environ[k] for k in _DEFAULT_TEST_KEYS if k in os.environ}
    for k in saved:
        del os.environ[k]
    try:
        return Config()
    finally:
        os.environ.update(saved)


def test_config_new_fields_defaults():
    c: Config = _clean_defaults_config()
    assert c.vision_model == "qwen3-vl-plus"
    assert c.text_model == "deepseek-v4-flash"
    assert c.vision_base_url == "https://www.acctoken.com/v1"
    assert c.vision_max_tokens == 16000
    assert c.vision_timeout == 120
    assert c.text_max_tokens == 16000
    assert c.text_timeout == 120
    assert c.route_default == "auto"
    assert c.playwright_viewport_width == 1440
    assert c.device_scale_factor == 1
    assert c.playwright_storage_state is None
    assert c.enrich_visual is False
    assert c.som_batch_enabled is True
    assert c.som_batch_size == 80
    assert c.som_batch_max_rounds == 3
    assert c.som_batch_min_coverage == 0.9
    assert c.som_color_backfill is False
    assert c.dom_direct_design is True

def test_config_new_fields_env():
    import os
    os.environ["VISION_MODEL"] = "x"
    try:
        c = Config()
        assert c.vision_model == "x"
    finally:
        os.environ.pop("VISION_MODEL", None)


def test_config_playwright_storage_state_env():
    import os
    os.environ["PLAYWRIGHT_STORAGE_STATE"] = "some/state.json"
    try:
        assert Config().playwright_storage_state == "some/state.json"
    finally:
        os.environ.pop("PLAYWRIGHT_STORAGE_STATE", None)


def test_config_vision_text_tokens_env():
    import os
    os.environ["VISION_MAX_TOKENS"] = "8000"
    os.environ["VISION_TIMEOUT"] = "60"
    os.environ["TEXT_MAX_TOKENS"] = "4096"
    os.environ["TEXT_TIMEOUT"] = "30"
    try:
        c = Config()
        assert c.vision_max_tokens == 8000
        assert c.vision_timeout == 60
        assert c.text_max_tokens == 4096
        assert c.text_timeout == 30
    finally:
        for k in ("VISION_MAX_TOKENS", "VISION_TIMEOUT", "TEXT_MAX_TOKENS", "TEXT_TIMEOUT"):
            os.environ.pop(k, None)


def test_config_som_batch_env():
    import os
    os.environ["SOM_BATCH_ENABLED"] = "false"
    os.environ["SOM_BATCH_SIZE"] = "120"
    os.environ["SOM_BATCH_MAX_ROUNDS"] = "5"
    os.environ["SOM_BATCH_MIN_COVERAGE"] = "0.95"
    os.environ["SOM_COLOR_BACKFILL"] = "true"
    try:
        c = Config()
        assert c.som_batch_enabled is False
        assert c.som_batch_size == 120
        assert c.som_batch_max_rounds == 5
        assert c.som_batch_min_coverage == 0.95
        assert c.som_color_backfill is True
    finally:
        for k in ("SOM_BATCH_ENABLED", "SOM_BATCH_SIZE", "SOM_BATCH_MAX_ROUNDS",
                  "SOM_BATCH_MIN_COVERAGE", "SOM_COLOR_BACKFILL"):
            os.environ.pop(k, None)


def test_config_dom_direct_design_env():
    import os
    os.environ["DOM_DIRECT_DESIGN"] = "false"
    try:
        assert Config().dom_direct_design is False
    finally:
        os.environ.pop("DOM_DIRECT_DESIGN", None)
