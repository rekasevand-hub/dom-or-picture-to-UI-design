from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "dom_semantic_benchmark.py"
    spec = importlib.util.spec_from_file_location("dom_semantic_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_semantic_benchmark_preserves_per_page_evidence_without_composite_score():
    module = _load_script()
    cases = [
        {
            "name": "IT之家",
            "kind": "regression",
            "status": "pass",
            "visual": {"status": "pass", "metrics": {"badPixelRatio": 0.037}},
            "semantics": {
                "roleCounts": {"navigation": 8, "list": 5, "button": 7},
                "unknownCount": 0,
            },
            "falsePositiveCandidates": [
                {"kind": "duplicate-bounds", "sourceDomIndex": 10}
            ],
            "groupsNotComponentized": [
                {"groupId": "list-0", "memberCount": 3, "reason": "feature-disabled"}
            ],
            "geometryInvariant": True,
            "featureFlags": {
                "domSemanticComponents": False,
                "domSemanticComponentInstances": False,
            },
        },
        {
            "name": "国家数据",
            "kind": "regression",
            "status": "warn",
            "visual": {"status": "pass", "metrics": {"badPixelRatio": 0.051}},
            "semantics": {
                "roleCounts": {"navigation": 2, "table": 0},
                "unknownCount": 1,
            },
            "falsePositiveCandidates": [
                {"kind": "table-card", "sourceDomIndex": 44}
            ],
            "groupsNotComponentized": [],
            "geometryInvariant": True,
            "featureFlags": {
                "domSemanticComponents": False,
                "domSemanticComponentInstances": False,
            },
        },
        {
            "name": "Rust",
            "kind": "holdout",
            "status": "pass",
            "visual": {"status": "pass", "metrics": {"badPixelRatio": 0.059}},
            "semantics": {
                "roleCounts": {"navigation": 2, "card": 3},
                "unknownCount": 0,
            },
            "falsePositiveCandidates": [],
            "groupsNotComponentized": [],
            "geometryInvariant": True,
            "featureFlags": {
                "domSemanticComponents": False,
                "domSemanticComponentInstances": False,
            },
        },
    ]

    report = module.build_semantic_benchmark_report(cases)

    assert report["schema_version"] == "dom-semantic-benchmark/1.0"
    assert [case["name"] for case in report["cases"]] == ["IT之家", "Rust", "国家数据"]
    assert report["cases"][0]["falsePositiveCandidates"][0]["kind"] == "duplicate-bounds"
    assert report["cases"][2]["semantics"]["unknownCount"] == 1
    assert report["aggregate"]["regressionCaseCount"] == 2
    assert report["aggregate"]["holdoutCaseCount"] == 1
    assert report["aggregate"]["roleTotals"]["navigation"] == 12
    assert report["aggregate"]["falsePositiveCandidateCount"] == 2
    assert report["aggregate"]["groupsNotComponentizedCount"] == 1
    assert report["aggregate"]["geometryInvariantCaseCount"] == 3
    assert report["aggregate"]["statusCounts"] == {"pass": 2, "warn": 1}
    assert "score" not in report["aggregate"]
