from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.app.services.evidence.dom_text_quality import (
    canonical_text,
    evaluate_text_nodes,
)
from scripts.dom_text_quality import _build_parser, build_report


THRESHOLDS = {
    "text": {
        "linebreak_match_rate": 0.98,
        "box_tolerance_px": 2.0,
        "baseline_tolerance_px": 1.0,
        "glyph_identity_status": "explicit-not-evaluated",
    }
}


def _node() -> dict:
    return {
        "tag": "div",
        "text": "Hello world",
        "x": 10,
        "y": 20,
        "w": 120,
        "h": 44,
        "textEmBox": [10, 20, 120, 42],
        "textEmLines": 2,
        "textLines": [
            {"text": "Hello", "box": [10, 20, 48, 20]},
            {"text": "world", "box": [10, 42, 44, 20]},
        ],
        "textBaseline": {
            "y": 35.0,
            "ascent": 14.0,
            "descent": 3.0,
            "method": "canvas-font-metrics",
            "lineCount": 2,
        },
        "platformFonts": [
            {
                "familyName": "Arial",
                "postScriptName": "ArialMT",
                "glyphCount": 10,
            }
        ],
    }


class DomTextQualityTests(unittest.TestCase):
    def test_canonical_text_removes_layout_whitespace_only(self) -> None:
        self.assertEqual(canonical_text("  Hello\n world\t"), "Helloworld")
        self.assertNotEqual(canonical_text("Hello world"), canonical_text("Hello word"))

    def test_report_keeps_five_dimensions_independent(self) -> None:
        report = evaluate_text_nodes([_node()], THRESHOLDS)
        self.assertEqual(
            set(report["dimensions"]),
            {"content", "linebreak", "box", "baseline", "glyph"},
        )
        self.assertFalse(report["composite_score_used"])
        self.assertEqual(report["dimensions"]["content"]["status"], "pass")
        self.assertEqual(report["dimensions"]["linebreak"]["status"], "pass")
        self.assertEqual(report["dimensions"]["box"]["status"], "pass")
        self.assertEqual(report["dimensions"]["baseline"]["status"], "derived")
        self.assertEqual(report["dimensions"]["glyph"]["status"], "partial")
        self.assertEqual(
            report["dimensions"]["glyph"]["final_identity"],
            "not-evaluated",
        )
        self.assertEqual(report["nodes"][0]["glyph"]["face_status"], "face-observed")

    def test_changed_content_fails_without_affecting_box_check(self) -> None:
        node = _node()
        node["textLines"][1]["text"] = "word"
        report = evaluate_text_nodes([node], THRESHOLDS)
        self.assertEqual(report["dimensions"]["content"]["status"], "fail")
        self.assertEqual(report["dimensions"]["box"]["status"], "pass")

    def test_line_count_mismatch_fails_linebreak(self) -> None:
        node = _node()
        node["textEmLines"] = 3
        report = evaluate_text_nodes([node], THRESHOLDS)
        self.assertEqual(report["dimensions"]["linebreak"]["status"], "fail")

    def test_measured_single_line_counts_as_linebreak_evidence(self) -> None:
        node = _node()
        node.pop("textLines")
        node["textEmLines"] = 1
        report = evaluate_text_nodes([node], THRESHOLDS)
        linebreak = report["nodes"][0]["linebreak"]
        self.assertEqual(linebreak["status"], "pass")
        self.assertEqual(linebreak["method"], "measured-single-line")

    def test_multiline_without_line_text_remains_not_evaluated(self) -> None:
        node = _node()
        node.pop("textLines")
        node["textEmLines"] = 3
        report = evaluate_text_nodes([node], THRESHOLDS)
        self.assertEqual(
            report["nodes"][0]["linebreak"]["status"],
            "not-evaluated",
        )
        self.assertEqual(
            report["dimensions"]["linebreak"]["status"],
            "not-evaluated",
        )

    def test_text_box_outside_tolerance_fails_box_only(self) -> None:
        node = _node()
        node["textEmBox"] = [13, 20, 120, 42]
        report = evaluate_text_nodes([node], THRESHOLDS)
        self.assertEqual(report["dimensions"]["box"]["status"], "fail")
        self.assertEqual(report["dimensions"]["content"]["status"], "pass")

    def test_vertical_font_paint_overflow_is_not_horizontal_box_misplacement(
        self,
    ) -> None:
        node = _node()
        node["textEmBox"] = [10, 17, 120, 42]
        report = evaluate_text_nodes([node], THRESHOLDS)
        box = report["nodes"][0]["box"]
        self.assertEqual(box["status"], "pass")
        self.assertEqual(box["vertical_paint_overflow_top"], 3.0)
        self.assertEqual(box["vertical_paint_overflow_bottom"], 0.0)

    def test_baseline_estimate_without_browser_method_is_not_evaluated(self) -> None:
        node = _node()
        node["textBaseline"] = {
            "y": 35.0,
            "ascent": 14.0,
            "descent": 3.0,
            "method": "center-plus-em",
            "lineCount": 2,
        }
        report = evaluate_text_nodes([node], THRESHOLDS)
        self.assertEqual(report["dimensions"]["baseline"]["status"], "not-evaluated")

    def test_mixed_and_missing_font_evidence_remain_explicit(self) -> None:
        mixed = _node()
        mixed["platformFonts"] = [
            {"familyName": "Arial", "glyphCount": 5},
            {"familyName": "Noto Sans SC", "glyphCount": 3},
        ]
        missing = copy.deepcopy(_node())
        missing["fontSize"] = "18px"
        missing.pop("platformFonts")
        report = evaluate_text_nodes([mixed, missing], THRESHOLDS)
        glyph = report["dimensions"]["glyph"]
        self.assertEqual(glyph["status"], "partial")
        self.assertEqual(glyph["ambiguous_count"], 1)
        self.assertEqual(glyph["missing_evidence_count"], 1)
        self.assertEqual(glyph["final_identity"], "not-evaluated")

    def test_same_font_style_inherits_representative_face_evidence(self) -> None:
        representative = _node()
        representative.update(
            {
                "fontFamilyRequested": "Arial",
                "fontFamily": "Arial",
                "fontWeight": "400",
                "fontSize": "16px",
                "fontStyle": "normal",
            }
        )
        sibling = copy.deepcopy(representative)
        sibling["text"] = "A second text node"
        sibling["textLines"] = [
            {"text": "A second text node", "box": [10, 20, 120, 20]}
        ]
        sibling["textEmLines"] = 1
        sibling.pop("platformFonts")
        report = evaluate_text_nodes([representative, sibling], THRESHOLDS)
        self.assertEqual(
            report["nodes"][1]["glyph"]["face_status"],
            "representative-face-observed",
        )
        self.assertEqual(
            report["dimensions"]["glyph"]["representative_face_count"],
            1,
        )


class DomTextQualityCliTests(unittest.TestCase):
    def test_cli_accepts_manifest_capture_root_and_output(self) -> None:
        args = _build_parser().parse_args(
            [
                "--manifest",
                "tests/fixtures/dom_quality/real_site_corpus_v1.json",
                "--capture-root",
                "output/captures",
                "--out",
                "output/report",
            ]
        )
        self.assertEqual(args.capture_root, Path("output/captures"))

    def test_report_keeps_three_samples_and_fails_on_content_loss(self) -> None:
        root = Path(__file__).resolve().parents[2]
        corpus = json.loads(
            (root / "tests/fixtures/dom_quality/real_site_corpus_v1.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            capture_root = Path(tmp)
            for sample in corpus["samples"]:
                capture_dir = capture_root / sample["sample_id"]
                capture_dir.mkdir()
                dom = []
                for text in sample["required_text"]:
                    dom.append(
                        {
                            "tag": "p",
                            "text": text,
                            "x": 0,
                            "y": 40 * len(dom),
                            "w": 200,
                            "h": 30,
                            "textEmBox": [0, 40 * len(dom), 200, 24],
                            "textEmLines": 1,
                            "textLines": [
                                {
                                    "text": text,
                                    "box": [0, 40 * len(dom), 200, 24],
                                    "baseline": {
                                        "y": 40 * len(dom) + 18,
                                        "ascent": 18,
                                        "descent": 4,
                                        "method": "canvas-font-metrics",
                                    },
                                }
                            ],
                            "textBaseline": {
                                "y": 40 * len(dom) + 18,
                                "ascent": 18,
                                "descent": 4,
                                "method": "canvas-font-metrics",
                                "lineCount": 1,
                            },
                        }
                    )
                (capture_dir / "00_dom.json").write_text(
                    json.dumps(dom),
                    encoding="utf-8",
                )
            report = build_report(corpus, capture_root)
            self.assertFalse(report["hard_gate_failed"])
            self.assertEqual(len(report["samples"]), 3)

            broken_path = capture_root / "DQ-R01" / "00_dom.json"
            broken = json.loads(broken_path.read_text(encoding="utf-8"))
            for item in broken:
                item["text"] = "changed"
                item["textLines"][0]["text"] = "changed"
            broken_path.write_text(json.dumps(broken), encoding="utf-8")
            broken_report = build_report(corpus, capture_root)
            self.assertTrue(broken_report["hard_gate_failed"])
            self.assertEqual(
                broken_report["samples"][0]["critical_text"]["status"], "fail"
            )


if __name__ == "__main__":
    unittest.main()
