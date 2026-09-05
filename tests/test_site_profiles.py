from dataclasses import replace
from src.config import load_config
from src.app.services.structure.site_profiles import load_profile

def test_mom_profile_loads_by_domain():
    prof = load_profile("http://flexweaver.rtdsoft.com:6016/index#/production/mfg_order_query")
    assert prof is not None
    assert prof.icon_aria_labels["form"] == "编辑"
    assert "form" in prof.hint_text() and "编辑" in prof.hint_text()

def test_profile_only_matches_its_domain():
    prof = load_profile("http://flexweaver.rtdsoft.com:6016/")
    assert prof is not None and int(prof.overlay["min_area"]) == 800
    assert load_profile("https://example.com") is None
