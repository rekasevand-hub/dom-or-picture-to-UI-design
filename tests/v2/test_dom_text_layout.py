from __future__ import annotations

from src.app.services.rendering.adapter_base import PrototypeAdapter
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter
from src.app.services.rendering.text_layout import layout_text


def test_browser_lines_win_over_estimated_wrap():
    result = layout_text(
        {
            "text": "中文，句子。以及EnglishMixedText",
            "width": 180,
            "fontSize": 18,
        },
        measured_lines=[
            {"text": "中文，句子。", "box": [0, 0, 120, 26]},
        ],
    )
    assert result["source"] == "browser-range"
    assert result["lines"] == ["中文，句子。"]
    assert result["lineBoxes"] == [[0, 0, 120, 26]]
    assert result["baselineSource"] == "browser-measured"


def test_cjk_and_ascii_share_original_line_break():
    result = layout_text(
        {
            "text": "小米 HyperOS 4",
            "width": 130,
            "fontSize": 20,
        },
        measured_lines=[
            {"text": "小米", "box": [0, 0, 40, 28]},
            {"text": "HyperOS 4", "box": [0, 28, 110, 28]},
        ],
    )
    assert result["lines"] == ["小米", "HyperOS 4"]
    assert result["baselineSource"] == "browser-measured"


def test_estimate_fallback_is_explicit_and_less_confident():
    estimated = layout_text(
        {
            "text": "one two three four five",
            "width": 72,
            "fontSize": 16,
            "lineHeight": 22,
        }
    )
    assert estimated["source"] == "estimated"
    assert estimated["baselineSource"] == "estimated"
    assert 0 < estimated["confidence"] < 1
    assert len(estimated["lines"]) > 1


def test_adapter_keeps_one_rich_text_spec_with_browser_line_boxes():
    spec = {
        "text": "Before bold 中文",
        "width": 180,
        "height": 52,
        "fontSize": 18,
        "lineHeight": 26,
        "measuredLines": [
            {"text": "Before bold", "box": [10, 20, 110, 26]},
            {"text": "中文", "box": [10, 46, 36, 26]},
        ],
        "textBaseline": {
            "y": 35,
            "ascent": 14,
            "descent": 5,
            "method": "canvas-font-metrics",
            "lineCount": 2,
        },
        "richRuns": [
            {"start": 0, "end": 7, "text": "Before ", "style": {}},
            {
                "start": 7,
                "end": 11,
                "text": "bold",
                "style": {"fontWeight": "700"},
            },
            {"start": 11, "end": 14, "text": " 中文", "style": {}},
        ],
    }

    rendered = PrototypeAdapter._wrap_text_spec(object(), spec)

    assert rendered["text"] == spec["text"]
    assert rendered["richRuns"] == spec["richRuns"]
    assert rendered["lines"] == ["Before bold", "中文"]
    assert rendered["lineBoxes"] == [[10, 20, 110, 26], [10, 46, 36, 26]]
    assert rendered["source"] == "browser-range"
    assert rendered["baselineSource"] == "browser-measured"


def test_figma_browser_baseline_is_not_shifted_twice():
    adapter = object.__new__(FigmaBridgeAdapter)
    spec = {
        "text": "Measured line",
        "textEmBox": [20, 40, 120, 18],
        "textEmLines": 1,
        "height": 30,
        "fontSize": 16,
        "lineHeight": 24,
        "baselineSource": "browser-measured",
    }
    rendered = adapter._text_render_spec(
        spec,
        {
            "x": 20,
            "y": 40,
            "height": 30,
            "lineHeight": 24,
            "text": "Measured line",
        },
        (0, 0),
    )

    assert rendered["y"] == 40
    assert "lineHeight" not in rendered
    assert rendered["baselineSource"] == "browser-measured"
