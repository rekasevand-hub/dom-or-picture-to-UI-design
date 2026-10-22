from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.app.services.structure.capture import DOM_JS
from src.app.services.structure.providers.dom import (
    strip_icon_glyphs,
    _style_from_node,
    _text_geometry_box,
    _text_paint_style,
)
from src.app.services.rendering.text_wrap import wrap_for_spec
from src.app.services.rendering.text_wrap import lines_spec_fields
from src.app.services.som.direct_design import _carry_text_lines


class DomTextGeometryTests(unittest.TestCase):
    def test_style_preserves_font_style(self) -> None:
        style = _style_from_node(
            {
                "fontFamily": "Arial",
                "fontSize": "18px",
                "fontStyle": "italic",
            }
        )

        self.assertEqual(style["fontStyle"], "italic")

    def test_style_preserves_nonstandard_variable_font_weight(self) -> None:
        style = _style_from_node(
            {
                "fontFamily": "Segoe UI Variable",
                "fontSize": "24px",
                "fontWeight": "650",
            }
        )

        self.assertEqual(style["fontWeight"], "bold")
        self.assertEqual(style["fontWeightValue"], 650)

    def test_mixed_text_runs_preserve_boundary_whitespace(self) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "p1"
            / "canonical"
            / "p2"
            / "mixed_font.html"
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 900, "height": 300})
                page.goto(fixture.resolve().as_uri(), wait_until="domcontentloaded")
                nodes = page.evaluate(DOM_JS)
            finally:
                browser.close()

        paragraph = next(
            item for item in nodes if str(item.get("text") or "").startswith("Alpha")
        )
        self.assertEqual(
            [run[0] for run in paragraph["textRuns"]],
            ["Alpha ", " 中文回退保持可编辑"],
        )

    def test_icon_cleanup_can_preserve_text_run_whitespace(self) -> None:
        self.assertEqual(
            strip_icon_glyphs(" 正文 ", preserve_whitespace=True),
            " 正文 ",
        )

    def test_style_preserves_platform_font_provenance(self) -> None:
        node = {
            "fontFamily": "Microsoft YaHei",
            "fontFamilyRequested": "sans-serif",
            "fontFamilyResolution": "browser-platform-font",
            "platformFonts": [
                {
                    "familyName": "Microsoft YaHei",
                    "glyphCount": 24,
                }
            ],
            "fontSize": "16px",
        }

        style = _style_from_node(node)

        self.assertEqual(style["fontFamily"], "Microsoft YaHei")
        self.assertEqual(style["fontFamilyRequested"], "sans-serif")
        self.assertEqual(
            style["fontFamilyResolution"],
            "browser-platform-font",
        )
        self.assertEqual(
            style["platformFonts"][0]["familyName"],
            "Microsoft YaHei",
        )

    def test_text_flow_uses_text_box_even_when_node_paints_its_own_background(
        self,
    ) -> None:
        element_box = [24, 178, 360, 96]
        text_box = [41, 195, 326, 35]

        selected = _text_geometry_box(
            element_box,
            text_box,
            paints_own_box=True,
            text_flow=True,
            element_type="text",
        )

        self.assertEqual(selected, text_box)

    def test_non_flow_background_element_keeps_its_element_box(self) -> None:
        element_box = [24, 178, 360, 96]
        text_box = [41, 195, 326, 35]

        selected = _text_geometry_box(
            element_box,
            text_box,
            paints_own_box=True,
            text_flow=False,
            element_type="text",
        )

        self.assertEqual(selected, element_box)

    def test_flow_text_element_drops_paint_owned_by_container(self) -> None:
        style = {
            "fillColor": "#eef5ff",
            "borderColor": "#2f6fed",
            "borderWidth": "1px",
            "fontSize": "16px",
            "textColor": "#18212f",
        }

        text_style = _text_paint_style(
            style,
            paints_own_box=True,
            text_flow=True,
            element_type="text",
        )

        self.assertNotIn("fillColor", text_style)
        self.assertNotIn("borderColor", text_style)
        self.assertNotIn("borderWidth", text_style)
        self.assertEqual(text_style["fontSize"], "16px")
        self.assertEqual(style["fillColor"], "#eef5ff")

    def test_non_flow_text_style_keeps_paint_fields(self) -> None:
        style = {
            "fillColor": "#eef5ff",
            "borderColor": "#2f6fed",
            "fontSize": "16px",
        }

        text_style = _text_paint_style(
            style,
            paints_own_box=True,
            text_flow=False,
            element_type="text",
        )

        self.assertEqual(text_style, style)

    def test_dom_probe_records_browser_visible_text_lines(self) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "p1"
            / "canonical"
            / "text_flow.html"
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 900, "height": 700})
                page.goto(fixture.resolve().as_uri(), wait_until="domcontentloaded")
                nodes = page.evaluate(DOM_JS)
            finally:
                browser.close()

        paragraph = next(
            item
            for item in nodes
            if str(item.get("text") or "").startswith("第一行 Chinese")
        )
        lines = paragraph["textLines"]
        self.assertGreaterEqual(len(lines), 3)
        self.assertIn("This longer", lines[0]["text"])
        self.assertEqual(
            " ".join(" ".join(item["text"] for item in lines).split()),
            " ".join(str(paragraph["text"]).split()),
        )

    def test_browser_measured_lines_take_priority_over_font_estimation(self) -> None:
        spec = {
            "text": "one two three four",
            "width": 120,
            "fontSize": 18,
            "lineHeight": 24,
            "lines": ["one two", "three four"],
        }

        self.assertEqual(
            wrap_for_spec(spec),
            ["one two", "three four"],
        )

    def test_single_measured_line_prevents_rewrap(self) -> None:
        text = (
            "This long browser-measured sentence fits on one line in the "
            "canonical reference and must not be estimated again."
        )
        spec = {
            "text": text,
            "width": 120,
            "fontSize": 18,
            "lineHeight": 24,
            "lines": [text],
        }

        self.assertEqual(wrap_for_spec(spec), [text])

    def test_single_measured_line_uses_measured_line_box_height(self) -> None:
        spec = {
            "text": "one measured line",
            "fontSize": 16,
            "y": 53,
            "textEmBox": [8, 53, 200, 17],
        }

        fields = lines_spec_fields(spec, ["one measured line"])

        self.assertEqual(fields["lineHeight"], 17)

    def test_direct_design_carries_browser_measured_lines(self) -> None:
        element = {}
        item = {
            "textLines": [
                {"text": "first browser line", "box": [10, 20, 160, 24]},
                {"text": "second browser line", "box": [10, 44, 180, 24]},
            ]
        }

        _carry_text_lines(element, item)

        self.assertEqual(
            element["lines"],
            ["first browser line", "second browser line"],
        )

    def test_direct_design_carries_a_single_measured_line(self) -> None:
        element = {}
        item = {
            "textLines": [
                {"text": "one measured line", "box": [10, 20, 160, 17]},
            ]
        }

        _carry_text_lines(element, item)

        self.assertEqual(element["lines"], ["one measured line"])

    def test_dom_probe_records_a_long_single_line_as_measured_layout(self) -> None:
        text = "Browser measured single line should remain one line."
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "single-line.html"
            fixture.write_text(
                "<!doctype html><body style='margin:0'>"
                f"<p style='width:880px;font:18px/28px Arial'>{text}</p>"
                "</body>",
                encoding="utf-8",
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": 900, "height": 200})
                    page.goto(
                        fixture.resolve().as_uri(),
                        wait_until="domcontentloaded",
                    )
                    nodes = page.evaluate(DOM_JS)
                finally:
                    browser.close()

        paragraph = next(
            item
            for item in nodes
            if str(item.get("text") or "").startswith("Browser measured single")
        )
        self.assertEqual(
            paragraph["textLines"],
            [
                {
                    "text": text,
                    "box": paragraph["textLines"][0]["box"],
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
