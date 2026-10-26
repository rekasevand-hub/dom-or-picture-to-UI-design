from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.app.services.evidence.dom_layout_quality import (
    classify_fallback_reason,
    evaluate_layout_tree,
    simulate_l3_local_growth,
)
from scripts.dom_layout_quality import _build_parser, build_layout_report


THRESHOLDS = {
    "structure": {
        "geometry_tolerance_px": 2.0,
    }
}


def _parent(**overrides) -> dict:
    node = {
        "tag": "div",
        "x": 0,
        "y": 0,
        "w": 200,
        "h": 240,
        "display": "flex",
        "flexDirection": "column",
        "gap": [10, 0],
        "padding": [0, 0, 0, 0],
    }
    node.update(overrides)
    return node


def _children(parent_index: int = 0) -> list[dict]:
    return [
        {
            "tag": "div",
            "pIdx": parent_index,
            "x": 0,
            "y": y,
            "w": 200,
            "h": 40,
            "position": "static",
        }
        for y in (0, 50, 100)
    ]


class DomLayoutQualityTests(unittest.TestCase):
    def test_vertical_css_flex_earns_l1_and_l2(self) -> None:
        dom = [_parent(), *_children()]
        report = evaluate_layout_tree(dom, THRESHOLDS)
        decision = report["decisions"][0]
        self.assertTrue(decision["l1"]["pass"])
        self.assertEqual(decision["l1"]["mode"], "VERTICAL")
        self.assertEqual(decision["l1"]["source"], "css")
        self.assertTrue(decision["l2"]["pass"])
        self.assertFalse(decision["fixed_fallback"]["required"])

    def test_grid_wrap_and_order_use_explicit_fixed_fallback(self) -> None:
        cases = [
            (_parent(display="grid"), "grid"),
            (_parent(flexWrap="wrap"), "wrap"),
        ]
        order_children = _children()
        order_children[0]["order"] = 1
        cases.append((_parent(), "order"))

        for parent, expected_reason in cases:
            children = order_children if expected_reason == "order" else _children()
            report = evaluate_layout_tree([parent, *children], THRESHOLDS)
            decision = report["decisions"][0]
            self.assertFalse(decision["l1"]["pass"])
            self.assertTrue(decision["fixed_fallback"]["required"])
            self.assertEqual(
                decision["fixed_fallback"]["reason"],
                expected_reason,
            )
            self.assertEqual(
                classify_fallback_reason(decision["l1"]["detail"]),
                expected_reason,
            )

    def test_nonuniform_geometry_source_is_l1_but_not_l2(self) -> None:
        parent = _parent(display="block")
        children = _children()
        children[1]["y"] = 50
        children[2]["y"] = 130
        report = evaluate_layout_tree([parent, *children], THRESHOLDS)
        decision = report["decisions"][0]
        self.assertTrue(decision["l1"]["pass"])
        self.assertEqual(decision["l1"]["source"], "geometry")
        self.assertFalse(decision["l2"]["pass"])
        self.assertEqual(decision["l2"]["reason"], "non-uniform-gap")

    def test_absolute_child_is_excluded_from_flow_members(self) -> None:
        parent = _parent()
        children = _children()
        absolute = copy.deepcopy(children[1])
        absolute["y"] = 75
        absolute["position"] = "absolute"
        children[1] = absolute
        report = evaluate_layout_tree([parent, *children], THRESHOLDS)
        decision = report["decisions"][0]
        self.assertEqual(decision["flow_child_count"], 2)
        self.assertEqual(decision["absolute_child_count"], 1)
        self.assertTrue(decision["l1"]["pass"])

    def test_report_has_no_composite_score(self) -> None:
        report = evaluate_layout_tree([_parent(), *_children()], THRESHOLDS)
        self.assertFalse(report["composite_score_used"])
        self.assertEqual(report["container_count"], 1)

    def test_vertical_local_growth_moves_following_siblings(self) -> None:
        result = simulate_l3_local_growth(
            {"mode": "VERTICAL", "itemSpacing": 10, "source": "css"},
            [(0, 0, 200, 40), (0, 50, 200, 40), (0, 100, 200, 40)],
            growth_px=24,
        )
        self.assertEqual(result["status"], "contract-pass")
        self.assertEqual(result["following_positions"], [74, 124])
        self.assertTrue(result["cross_axis_unchanged"])
        self.assertEqual(result["parent_propagation"], "not-evaluated")

    def test_horizontal_local_growth_moves_following_siblings_on_x(self) -> None:
        result = simulate_l3_local_growth(
            {"mode": "HORIZONTAL", "itemSpacing": 12, "source": "css"},
            [(0, 0, 40, 60), (52, 0, 40, 60), (104, 0, 40, 60)],
            growth_px=24,
        )
        self.assertEqual(result["following_positions"], [76, 128])
        self.assertTrue(result["cross_axis_unchanged"])

    def test_geometry_source_and_missing_l2_are_not_l3_evaluated(self) -> None:
        geometry = simulate_l3_local_growth(
            {"mode": "VERTICAL", "itemSpacing": 10, "source": "geometry"},
            [(0, 0, 200, 40), (0, 50, 200, 40)],
            growth_px=24,
        )
        missing = simulate_l3_local_growth(
            None,
            [(0, 0, 200, 40), (0, 50, 200, 40)],
            growth_px=24,
        )
        self.assertEqual(geometry["status"], "not-evaluated")
        self.assertEqual(missing["status"], "not-evaluated")

    def test_css_report_exposes_l3_contract_without_parent_claim(self) -> None:
        report = evaluate_layout_tree([_parent(), *_children()], THRESHOLDS)
        decision = report["decisions"][0]
        self.assertEqual(decision["l3"]["status"], "contract-pass")
        self.assertEqual(
            decision["l3"]["parent_propagation"],
            "not-evaluated",
        )
        self.assertEqual(report["levels"]["l3"]["pass_count"], 1)


class DomLayoutQualityCliTests(unittest.TestCase):
    def test_cli_requires_manifest_capture_root_and_output(self) -> None:
        args = _build_parser().parse_args(
            [
                "--manifest",
                "tests/fixtures/dom_quality/real_site_corpus_v1.json",
                "--capture-root",
                "output/captures",
                "--out",
                "output/layout",
            ]
        )
        self.assertEqual(args.out, Path("output/layout"))

    def test_report_aggregates_three_samples_without_runtime_claims(self) -> None:
        root = Path(__file__).resolve().parents[2]
        corpus = json.loads(
            (root / "tests/fixtures/dom_quality/real_site_corpus_v1.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            capture_root = Path(tmp)
            for index, sample in enumerate(corpus["samples"]):
                capture_dir = capture_root / sample["sample_id"]
                capture_dir.mkdir()
                parent = _parent(display="grid" if index == 0 else "flex")
                (capture_dir / "00_dom.json").write_text(
                    json.dumps([parent, *_children()]),
                    encoding="utf-8",
                )
            report = build_layout_report(corpus, capture_root)
        self.assertEqual(report["sample_count"], 3)
        self.assertEqual(report["container_count"], 3)
        self.assertEqual(report["levels"]["l1"]["pass_count"], 2)
        self.assertEqual(report["levels"]["l2"]["pass_count"], 2)
        self.assertEqual(report["levels"]["l3"]["pass_count"], 2)
        self.assertEqual(report["fallback_reasons"]["grid"], 1)
        self.assertEqual(report["source_behavior"], "not-evaluated")
        self.assertEqual(report["parent_propagation"], "not-evaluated")
        self.assertEqual(report["figma_runtime"], "not-evaluated")


if __name__ == "__main__":
    unittest.main()
