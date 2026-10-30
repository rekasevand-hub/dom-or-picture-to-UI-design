from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "dom_visual_ab.py"
    spec = importlib.util.spec_from_file_location("dom_visual_ab", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ab_report_reports_per_metric_regressions_without_composite_score():
    module = _load_script()
    cases = [
        {
            "name": "stats",
            "baseline": {
                "status": "pass",
                "metrics": {
                    "bad_pixel_ratio": 0.05,
                    "image_fill_rate": 1.0,
                    "text_node_count": 20,
                    "blank_area_ratio": 0.4,
                },
                "regions": {"header": 1.0, "body": 2.0},
            },
            "treatment": {
                "status": "fail",
                "metrics": {
                    "bad_pixel_ratio": 0.28,
                    "image_fill_rate": 1.0,
                    "text_node_count": 14,
                    "blank_area_ratio": 0.4,
                },
                "regions": {"header": 40.0, "body": 2.5},
            },
        }
    ]

    report = module.build_visual_ab_report(cases)

    assert report["schema_version"] == "dom-visual-ab/1.0"
    case = report["cases"][0]
    assert case["deltas"]["bad_pixel_ratio"] == 0.23
    assert case["deltas"]["text_node_count"] == -6
    assert "bad_pixel_ratio" in case["regressions"]
    assert report["aggregate"]["regression_counts"]["bad_pixel_ratio"] == 1
    assert "score" not in report["aggregate"]
