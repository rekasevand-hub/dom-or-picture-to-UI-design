import json
from src.app.services.structure.backends.grounding_vlm import parse_vlm_json

def _raw(containers, elements):
    return json.dumps({"containers": containers, "elements": elements})

def test_parse_vlm_normalized_scales_to_pixels():
    raw = _raw(
        [{"bbox": [0.0, 0.0, 0.5, 0.25], "role": "banner"}],
        [{"bbox": [0.1, 0.2, 0.3, 0.4], "type": "button", "text": "保存"}])
    out = parse_vlm_json(raw, 1000, 800)
    assert out["containers"] == [{"bbox": [0, 0, 500, 200], "role": "banner"}]
    assert out["elements"] == [{"bbox": [100, 160, 200, 160], "type": "button", "text": "保存"}]

def test_parse_vlm_normalized_clamps_and_rejects_degenerate():
    raw = _raw([{"bbox": [0.9, 0.9, 1.2, 1.0], "role": "panel"}],
               [{"bbox": [0.0, 0.0, 0.0, 0.5], "type": "text", "text": "x"}])
    out = parse_vlm_json(raw, 100, 100)
    assert out["containers"] == [{"bbox": [90, 90, 10, 10], "role": "panel"}]
    assert out["elements"] == []  # 宽 <2 丢弃
