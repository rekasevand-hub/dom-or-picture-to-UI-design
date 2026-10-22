from __future__ import annotations

import unittest

from src.app.services.evidence import (
    calibrate_glyph_boxes,
    compare_glyph_boxes,
    compare_glyph_boxes_trusted,
    compare_glyph_text,
    compare_ocr_text,
    parse_tesseract_boxes,
    summarize_ocr_observations,
)


class OcrComparisonTests(unittest.TestCase):
    def test_phrase_matching_normalizes_case_whitespace_and_punctuation(self) -> None:
        result = compare_ocr_text(
            ["Invoice total: 128.50", "This sentence exists only as painted pixels."],
            "INVOICE TOTAL 128.50\nThis sentence exists only as painted pixels",
        )
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["matched_count"], 2)

    def test_missing_phrase_is_reported_without_inventing_text(self) -> None:
        result = compare_ocr_text(
            ["Invoice total: 128.50"],
            "Invoice total: 12.50",
        )
        self.assertEqual(result["status"], "no-match")
        self.assertEqual(result["matched_count"], 0)
        self.assertFalse(result["phrases"][0]["matched"])

    def test_observation_summary_reports_lines_and_confidence(self) -> None:
        summary = summarize_ocr_observations(
            [
                {
                    "text": "Invoice total: 128.50",
                    "confidence": 0.9,
                    "bbox": [[0, 0], [100, 0], [100, 20], [0, 20]],
                },
                {
                    "text": "Only pixels",
                    "confidence": 0.5,
                    "bbox": [[0, 24], [100, 24], [100, 40], [0, 40]],
                },
            ]
        )
        self.assertEqual(summary["line_count"], 2)
        self.assertAlmostEqual(summary["mean_confidence"], 0.7)
        self.assertAlmostEqual(summary["min_confidence"], 0.5)

    def test_tesseract_boxes_are_converted_to_top_left_coordinates(self) -> None:
        glyphs = parse_tesseract_boxes("H 2 0 12 10 0\n", image_height=20)
        self.assertEqual(len(glyphs), 1)
        self.assertEqual(glyphs[0]["text"], "H")
        self.assertEqual(glyphs[0]["bbox"], [2, 10, 10, 10])

    def test_glyph_text_comparison_ignores_spacing_and_punctuation(self) -> None:
        result = compare_glyph_text("Hello, World!", "HelloWorld_")
        self.assertTrue(result["matched"])
        self.assertEqual(result["expected_count"], 10)

    def test_glyph_boxes_report_sequence_and_position_error(self) -> None:
        truth = [
            {"text": "A", "bbox": [0, 0, 10, 12]},
            {"text": "B", "bbox": [12, 0, 10, 12]},
        ]
        observed = [
            {"text": "A", "bbox": [1, 0, 10, 12]},
            {"text": "B", "bbox": [12, 1, 10, 12]},
        ]
        result = compare_glyph_boxes(truth, observed)
        self.assertTrue(result["sequence_match"])
        self.assertEqual(result["compared_count"], 2)
        self.assertEqual(result["max_delta"], 1.0)
        self.assertEqual(result["within_2px_count"], 2)

    def test_glyph_boxes_remove_global_axis_bias(self) -> None:
        truth = [
            {"text": "A", "bbox": [0, 0, 10, 12]},
            {"text": "B", "bbox": [12, 0, 10, 12]},
        ]
        observed = [
            {"text": "A", "bbox": [3, 4, 10, 12]},
            {"text": "B", "bbox": [15, 4, 10, 12]},
        ]
        result = calibrate_glyph_boxes(truth, observed)
        self.assertEqual(result["offsets"], [3.0, 4.0, 0.0, 0.0])
        self.assertTrue(result["calibrated"]["sequence_match"])
        self.assertEqual(result["calibrated"]["max_delta"], 0.0)

    def test_merged_glyph_box_is_excluded_from_trusted_stats(self) -> None:
        truth = [
            {"text": "A", "bbox": [0, 0, 10, 12]},
            {"text": "i", "bbox": [12, 0, 4, 12]},
        ]
        observed = [
            {"text": "A", "bbox": [0, 0, 10, 12]},
            {"text": "i", "bbox": [12, 0, 20, 12]},
        ]
        result = compare_glyph_boxes_trusted(truth, observed)
        self.assertEqual(result["suspect_count"], 1)
        self.assertEqual(result["trusted"]["compared_count"], 1)
        self.assertEqual(result["trusted"]["max_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
