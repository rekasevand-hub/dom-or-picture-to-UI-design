from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from src.app.services.evidence.image_strategy_benchmark import (
    build_strategy_row,
    build_strategy_comparison,
    describe_cv_execution,
    describe_grounding_execution,
    evaluate_hybrid_decision,
    plan_strategy_attempts,
    validate_benchmark_manifest,
)


def _row(strategy: str, **overrides):
    row = {
        "strategy": strategy,
        "figma_runtime": "observed",
        "critical_text": {
            "matched": 14,
            "required": 14,
            "status": "pass",
        },
        "native_text": {
            "node_count": 16,
            "edit_restore": "pass",
        },
        "asset": {
            "image_node_count": 1,
            "reference_only_count": 1,
            "replace_restore": "pass",
            "original_claim": False,
        },
        "structure": {
            "node_count": 21,
            "text_candidates": 16,
            "image_candidates": 1,
            "ambiguity_count": 0,
        },
        "visual": {
            "size_match": True,
            "within30_pct": 96.5,
            "mean_channel_delta": 4.2,
            "ink_mean_delta": 9.9,
            "over30_pct": 3.5,
        },
        "runtime": {
            "wall_time_seconds": 40.0,
            "grounding_vlm_calls": 1,
            "cv_executions": 0,
            "cost_telemetry_status": "bounded-by-request-count",
        },
        "provenance": {
            "requested_route": "auto",
            "ordered_attempts": True,
            "selected_strategy": True,
            "all_candidate_sources": True,
            "ambiguity_retained": True,
            "hidden_route_switch": False,
        },
        "non_claims": {
            "original_asset": False,
            "adaptive_flow": False,
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(row.get(key), dict):
            row[key] = {**row[key], **value}
        else:
            row[key] = value
    return row


def _policy():
    return {
        "visual_within30_min_pct": 90.0,
        "hybrid_wall_time_max_seconds": 180.0,
        "hybrid_max_grounding_ratio": 2.0,
        "hybrid_grounding_calls_max": 1,
    }


def _rows():
    grounding = _row("grounding-only")
    cv = _row(
        "cv-fallback",
        structure={
            "node_count": 19,
            "text_candidates": 14,
            "image_candidates": 1,
            "ambiguity_count": 2,
        },
        runtime={
            "wall_time_seconds": 52.0,
            "grounding_vlm_calls": 0,
            "cv_executions": 1,
            "cost_telemetry_status": "bounded-by-request-count",
        },
    )
    hybrid = _row(
        "grounding-cv-hybrid",
        structure={
            "node_count": 22,
            "text_candidates": 17,
            "image_candidates": 1,
            "ambiguity_count": 1,
        },
        runtime={
            "wall_time_seconds": 67.0,
            "grounding_vlm_calls": 1,
            "cv_executions": 1,
            "cost_telemetry_status": "bounded-by-request-count",
        },
    )
    return [grounding, cv, hybrid]


class ImageStrategyBenchmarkTests(unittest.TestCase):
    def test_adopts_only_when_every_independent_gate_passes(self) -> None:
        decision = evaluate_hybrid_decision(_rows(), _policy())

        self.assertEqual(decision["decision"], "adopt-hybrid")
        self.assertEqual(decision["reasons"], [])
        self.assertTrue(all(gate["pass"] for gate in decision["gates"].values()))
        self.assertTrue(decision["no_composite_score"])

    def test_critical_text_regression_rejects_hybrid(self) -> None:
        rows = _rows()
        rows[-1]["critical_text"]["matched"] = 13
        rows[-1]["critical_text"]["status"] = "fail"

        decision = evaluate_hybrid_decision(rows, _policy())

        self.assertEqual(decision["decision"], "reject-hybrid")
        self.assertIn("critical-text", decision["reasons"])
        self.assertFalse(decision["gates"]["critical-text"]["pass"])

    def test_visual_regression_rejects_hybrid(self) -> None:
        rows = _rows()
        rows[-1]["visual"]["within30_pct"] = 96.0

        decision = evaluate_hybrid_decision(rows, _policy())

        self.assertEqual(decision["decision"], "reject-hybrid")
        self.assertIn("visual-quality", decision["reasons"])

    def test_missing_provenance_or_hidden_route_switch_rejects_hybrid(self) -> None:
        rows = _rows()
        rows[-1]["provenance"]["all_candidate_sources"] = False
        rows[-1]["provenance"]["hidden_route_switch"] = True

        decision = evaluate_hybrid_decision(rows, _policy())

        self.assertEqual(decision["decision"], "reject-hybrid")
        self.assertIn("provenance", decision["reasons"])
        self.assertIn("routing-safety", decision["reasons"])

    def test_unbounded_runtime_rejects_hybrid(self) -> None:
        rows = _rows()
        rows[-1]["runtime"]["wall_time_seconds"] = 190.0

        decision = evaluate_hybrid_decision(rows, _policy())

        self.assertEqual(decision["decision"], "reject-hybrid")
        self.assertIn("latency-bound", decision["reasons"])

    def test_absence_of_independent_improvement_rejects_hybrid(self) -> None:
        rows = _rows()
        rows[-1]["structure"] = copy.deepcopy(rows[0]["structure"])

        decision = evaluate_hybrid_decision(rows, _policy())

        self.assertEqual(decision["decision"], "reject-hybrid")
        self.assertIn("independent-improvement", decision["reasons"])

    def test_strategy_comparison_has_no_composite_score(self) -> None:
        report = build_strategy_comparison(
            _rows(),
            _policy(),
            corpus_id="IMAGE-STRATEGY-CORPUS-TEST",
        )

        self.assertEqual(report["schema_version"], "image-strategy-comparison/1.0")
        self.assertFalse(report["composite_score_used"])
        self.assertNotIn("composite_score", report)
        self.assertEqual(len(report["strategies"]), 3)
        self.assertEqual(report["decision"]["decision"], "adopt-hybrid")

    def test_manifest_validation_checks_frozen_hashes_and_strategies(self) -> None:
        manifest_path = Path("tests/fixtures/image_strategy_benchmark/manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        validated = validate_benchmark_manifest(manifest, root=Path.cwd())

        self.assertEqual(
            validated["corpus_id"],
            "IMAGE-STRATEGY-CORPUS-2026-10-26-R1",
        )
        self.assertEqual(validated["strategies"], list(_rows_strategy_names()))

    def test_strategy_row_keeps_acceptance_dimensions_independent(self) -> None:
        acceptance = {
            "figma_runtime": "observed",
            "critical_text": {
                "matched_count": 14,
                "required_count": 14,
                "status": "pass",
            },
            "dimensions": {
                "structure": {"status": "pass"},
                "edit": {"status": "pass"},
                "asset": {"status": "pass"},
                "visual": {"status": "pass", "within30_pct": 96.5},
            },
            "visual": {
                "size_match": True,
                "within30_pct": 96.5,
                "mean": 4.2,
                "ink_mean": 9.9,
                "over30_pct": 3.5,
            },
            "asset_claims": {
                "original_asset": False,
                "reference_only_display": True,
            },
            "limitations": [],
            "non_claims": [],
        }
        readback = {
            "children": [
                {"type": "TEXT", "characters": "Workspace"},
                {"type": "RECTANGLE", "fills": [{"type": "IMAGE"}]},
            ]
        }
        pipeline = {
            "route": "hybrid",
            "design": {"elements": [{"type": "text"}, {"type": "image"}]},
            "image_ir": {
                "counts": {"nodes": 2, "text_candidates": 1, "image_candidates": 1},
                "assets": [{"reference_only": True}],
            },
            "provenance": {
                "requested_route": "auto",
                "attempts": [
                    {"strategy": "grounding", "status": "selected"},
                    {"strategy": "cv", "status": "supplemented"},
                ],
                "hidden_route_switch": False,
                "ambiguity_count": 0,
                "duplicate_suppressed_count": 33,
                "all_candidate_sources": True,
            },
        }

        row = build_strategy_row(
            strategy="grounding-cv-hybrid",
            acceptance=acceptance,
            readback_tree=readback,
            pipeline=pipeline,
            runtime={
                "wall_time_seconds": 67.0,
                "grounding_vlm_calls": 1,
                "cv_executions": 1,
                "cost_telemetry_status": "bounded-by-request-count",
            },
        )

        self.assertEqual(row["strategy"], "grounding-cv-hybrid")
        self.assertEqual(row["critical_text"]["matched"], 14)
        self.assertEqual(row["native_text"]["node_count"], 1)
        self.assertEqual(row["asset"]["image_node_count"], 1)
        self.assertEqual(row["visual"]["within30_pct"], 96.5)
        self.assertEqual(row["structure"]["ambiguity_count"], 0)
        self.assertEqual(row["structure"]["duplicate_suppressed_count"], 33)
        self.assertNotIn("composite_score", row)

    def test_cv_fallback_plan_is_explicit_and_has_no_hidden_switch(self) -> None:
        plan = plan_strategy_attempts(
            "cv-fallback",
            grounding_available=False,
        )

        self.assertEqual(plan["selected"], "cv")
        self.assertEqual(
            plan["attempts"],
            [
                {
                    "strategy": "grounding",
                    "status": "unavailable",
                    "reason": "grounding-config-missing",
                },
                {"strategy": "cv", "status": "selected"},
            ],
        )
        self.assertTrue(plan["fallback_used"])
        self.assertFalse(plan["hidden_route_switch"])

    def test_shared_grounding_replay_is_explicit_in_runtime_contract(self) -> None:
        benchmark = describe_grounding_execution(
            "grounding-cv-hybrid",
            shared_graph_available=True,
        )
        fallback = describe_grounding_execution(
            "cv-fallback",
            shared_graph_available=False,
        )

        self.assertEqual(benchmark["logical_grounding_calls"], 1)
        self.assertEqual(benchmark["provider_grounding_calls"], 0)
        self.assertTrue(benchmark["grounding_replay"])
        self.assertEqual(fallback["logical_grounding_calls"], 0)
        self.assertEqual(fallback["provider_grounding_calls"], 0)
        self.assertFalse(fallback["grounding_replay"])

    def test_shared_cv_replay_is_explicit_in_runtime_contract(self) -> None:
        fallback = describe_cv_execution(
            "cv-fallback",
            shared_graph_available=True,
        )
        hybrid = describe_cv_execution(
            "grounding-cv-hybrid",
            shared_graph_available=True,
        )
        grounding = describe_cv_execution(
            "grounding-only",
            shared_graph_available=False,
        )

        self.assertEqual(fallback["logical_cv_executions"], 1)
        self.assertEqual(fallback["provider_cv_executions"], 0)
        self.assertTrue(fallback["cv_replay"])
        self.assertEqual(hybrid["logical_cv_executions"], 1)
        self.assertEqual(grounding["logical_cv_executions"], 0)


def _rows_strategy_names():
    return (
        "grounding-only",
        "cv-fallback",
        "grounding-cv-hybrid",
    )


if __name__ == "__main__":
    unittest.main()
