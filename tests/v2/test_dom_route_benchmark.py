from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_dom_route.py"
    spec = importlib.util.spec_from_file_location("benchmark_dom_route", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_route_benchmark_preserves_failures_and_determinism():
    module = _load_script()
    rows = [
        {
            "name": "xiaomi",
            "bundle": "/captures/xiaomi",
            "bundle_sha256": "a" * 64,
            "pagegraph_sha256": "b" * 64,
            "design_sha256": "c" * 64,
            "deterministic": True,
            "quality": {
                "status": "fail",
                "checks": {
                    "redirect": {"status": "fail"},
                    "image_coverage": {"status": "pass"},
                },
            },
            "image_counts": {
                "references": 12,
                "design_images": 9,
                "figma_fills": 0,
            },
            "text_node_count": 42,
            "browser_used": False,
            "network_used": False,
        },
        {
            "name": "stats",
            "bundle": "/captures/stats",
            "bundle_sha256": "d" * 64,
            "pagegraph_sha256": "e" * 64,
            "design_sha256": "f" * 64,
            "deterministic": True,
            "quality": {
                "status": "pass",
                "checks": {
                    "redirect": {"status": "pass"},
                    "image_coverage": {"status": "pass"},
                },
            },
            "image_counts": {
                "references": 3,
                "design_images": 3,
                "figma_fills": 3,
            },
            "text_node_count": 18,
            "browser_used": False,
            "network_used": False,
        },
    ]

    report = module.build_route_benchmark_report(rows)

    assert report["schema_version"] == "dom-route-benchmark/1.0"
    assert [case["name"] for case in report["cases"]] == ["stats", "xiaomi"]
    assert report["aggregate"]["failure_counts"]["redirect"] == 1
    assert report["aggregate"]["deterministic_case_count"] == 2
    assert report["aggregate"]["figma_fill_count"] == 3
    assert report["browser_used"] is False
    assert report["network_used"] is False
