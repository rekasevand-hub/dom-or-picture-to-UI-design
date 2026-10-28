from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "dom_visual_benchmark.py"
    spec = importlib.util.spec_from_file_location("dom_visual_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_benchmark_aggregates_failures_without_composite_score():
    module = _load_script()
    rows = [
        {
            "name": "blank-page",
            "bundle": "/fixtures/blank",
            "status": "fail",
            "network_used": False,
            "browser_used": False,
            "visual": {
                "status": "fail",
                "checks": {
                    "blank_area": {"status": "fail"},
                    "image_fill": {"status": "pass"},
                },
                "metrics": {
                    "image_fill_rate": 1.0,
                    "text_node_count": 12,
                    "bad_pixel_ratio": 0.4,
                },
            },
        },
        {
            "name": "healthy-page",
            "bundle": "/fixtures/healthy",
            "status": "pass",
            "network_used": False,
            "browser_used": False,
            "visual": {
                "status": "pass",
                "checks": {
                    "blank_area": {"status": "pass"},
                    "image_fill": {"status": "pass"},
                },
                "metrics": {
                    "image_fill_rate": 1.0,
                    "text_node_count": 20,
                    "bad_pixel_ratio": 0.01,
                },
            },
        },
    ]

    report = module.build_benchmark_report(rows)

    assert report["schema_version"] == "dom-visual-benchmark/1.0"
    assert [item["name"] for item in report["cases"]] == [
        "blank-page",
        "healthy-page",
    ]
    assert report["aggregate"]["failure_counts"]["blank_area"] == 1
    assert report["aggregate"]["fail_case_count"] == 1
    assert report["browser_used"] is False
    assert report["network_used"] is False
    assert "score" not in report["aggregate"]
