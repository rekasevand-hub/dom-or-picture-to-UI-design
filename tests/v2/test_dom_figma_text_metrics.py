from __future__ import annotations

import unittest

from src.app.services.evidence.dom_figma_text_metrics import (
    build_figma_text_metrics,
)


def _readback(
    text: str,
    *,
    x: float = 10,
    y: float = 20,
    width: float = 100,
    height: float = 24,
) -> dict:
    return {
        "id": "root",
        "type": "FRAME",
        "x": 0,
        "y": 0,
        "width": 200,
        "height": 100,
        "absolute": {"x": 0, "y": 0, "width": 200, "height": 100},
        "children": [
            {
                "id": "text-1",
                "type": "TEXT",
                "characters": text,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "absolute": {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                },
                "fontName": {"family": "Arial", "style": "Regular"},
                "fontSize": 14,
            }
        ],
    }


def _design(
    text: str,
    *,
    lines: list[str] | None = None,
    text_em_lines: int | None = None,
    baseline: dict | None = None,
) -> dict:
    element = {
        "id": "text-1",
        "type": "text",
        "text": text,
        "x": 10,
        "y": 20,
        "width": 100,
        "height": 24,
        "textEmBox": [10, 20, 100, 24],
        "style": {
            "fontFamily": "Arial",
            "fontSize": 14,
            "fontWeight": "normal",
        },
    }
    if lines is not None:
        element["lines"] = lines
    if text_em_lines is not None:
        element["textEmLines"] = text_em_lines
    if baseline is not None:
        element["textBaseline"] = baseline
    return {
        "canvas": {"width": 200, "height": 100},
        "elements": [element],
    }


class DomFigmaTextMetricsTests(unittest.TestCase):
    def test_explicit_multiline_and_projected_baseline_pass(self) -> None:
        design = _design(
            "first\nsecond",
            lines=["first", "second"],
            text_em_lines=2,
            baseline={
                "y": 34,
                "ascent": 14,
                "descent": 4,
                "method": "canvas-font-metrics",
                "lineCount": 2,
            },
        )

        metrics = build_figma_text_metrics(
            design,
            _readback("first\nsecond", height=38),
        )

        self.assertEqual(metrics["dimensions"]["linebreak"]["status"], "pass")
        self.assertEqual(metrics["dimensions"]["baseline"]["status"], "pass")
        self.assertEqual(metrics["dimensions"]["glyph"]["status"], "not-evaluated")
        self.assertEqual(metrics["matches"][0]["baseline"]["delta_px"], 0)

    def test_linebreak_mismatch_fails(self) -> None:
        design = _design(
            "first second",
            lines=["first", "second"],
            text_em_lines=2,
        )

        metrics = build_figma_text_metrics(
            design,
            _readback("first second"),
        )

        self.assertEqual(metrics["dimensions"]["linebreak"]["status"], "fail")
        self.assertEqual(metrics["dimensions"]["linebreak"]["fail_count"], 1)

    def test_baseline_outside_tolerance_fails(self) -> None:
        design = _design(
            "line",
            text_em_lines=1,
            baseline={
                "y": 34,
                "ascent": 14,
                "descent": 4,
                "method": "canvas-font-metrics",
                "lineCount": 1,
            },
        )

        metrics = build_figma_text_metrics(
            design,
            _readback("line", y=18),
        )

        self.assertEqual(metrics["dimensions"]["baseline"]["status"], "fail")
        self.assertEqual(metrics["matches"][0]["baseline"]["delta_px"], -2)

    def test_missing_line_and_baseline_evidence_stays_not_evaluated(self) -> None:
        design = _design("single")

        metrics = build_figma_text_metrics(
            design,
            _readback("single"),
        )

        self.assertEqual(
            metrics["dimensions"]["linebreak"]["status"],
            "not-evaluated",
        )
        self.assertEqual(
            metrics["dimensions"]["baseline"]["status"],
            "not-evaluated",
        )
        self.assertEqual(
            metrics["matches"][0]["linebreak"]["reason"],
            "line-count-evidence-missing",
        )
        self.assertEqual(
            metrics["matches"][0]["baseline"]["reason"],
            "textBaseline-missing",
        )

    def test_missing_match_remains_in_denominator(self) -> None:
        design = _design("source", text_em_lines=1)

        metrics = build_figma_text_metrics(
            design,
            _readback("different"),
        )

        self.assertEqual(metrics["expected_text_count"], 1)
        self.assertEqual(metrics["matched_count"], 0)
        self.assertEqual(metrics["dimensions"]["linebreak"]["coverage"], 0)


if __name__ == "__main__":
    unittest.main()
