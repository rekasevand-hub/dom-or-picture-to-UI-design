from __future__ import annotations

import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from src.app.services.rendering.axure.evidence import (
    compare_rp_to_design,
    inspect_rp,
)
from src.app.services.rendering.axure_adapter import AxureRPAdapter


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _design() -> dict:
    image = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
    return {
        "pages": [
            {
                "name": "One",
                "canvas": {"width": 640, "height": 480, "background": "#ffffff"},
                "elements": [
                    {
                        "id": "bg-card",
                        "name": "Card",
                        "type": "rectangle",
                        "x": 20,
                        "y": 20,
                        "width": 300,
                        "height": 120,
                        "style": {"fillColor": "#f6f8fb"},
                    },
                    {
                        "id": "title",
                        "name": "Title",
                        "type": "text",
                        "x": 40,
                        "y": 40,
                        "width": 180,
                        "height": 30,
                        "text": "Shared title",
                        "style": {
                            "fontFamily": "Arial",
                            "fontSize": 18,
                            "textColor": "#202124",
                        },
                    },
                    {
                        "id": "cta",
                        "name": "CTA",
                        "type": "button",
                        "x": 40,
                        "y": 84,
                        "width": 120,
                        "height": 36,
                        "text": "Continue",
                        "style": {
                            "fillColor": "#2457d6",
                            "textColor": "#ffffff",
                            "fontSize": 14,
                        },
                    },
                    {
                        "id": "field",
                        "name": "Search",
                        "type": "input",
                        "x": 340,
                        "y": 40,
                        "width": 220,
                        "height": 40,
                        "text": "Book",
                        "style": {
                            "fillColor": "#ffffff",
                            "borderColor": "#d0d5dd",
                            "borderWidth": 1,
                        },
                    },
                    {
                        "id": "cover",
                        "name": "Cover",
                        "type": "image",
                        "x": 340,
                        "y": 100,
                        "width": 96,
                        "height": 64,
                        "imageBase64": image,
                    },
                ],
            },
            {
                "name": "Two",
                "canvas": {"width": 320, "height": 240, "background": "#fafafa"},
                "elements": [
                    {
                        "id": "second-title",
                        "name": "Second title",
                        "type": "text",
                        "x": 16,
                        "y": 16,
                        "width": 220,
                        "height": 32,
                        "text": "Second page",
                        "style": {"fontSize": 20, "textColor": "#202124"},
                    }
                ],
            },
        ]
    }


def _render(path: Path, design: dict | None = None) -> None:
    adapter = AxureRPAdapter(path)
    adapter.connect()
    adapter.render_design(design or _design())
    adapter.disconnect()


class AxureEvidenceTests(unittest.TestCase):
    def test_inspector_reads_real_page_widget_geometry_and_asset_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.rp"
            _render(path)

            report = inspect_rp(path)

        self.assertTrue(report["integrity"]["ok"])
        self.assertTrue(report["self_check"]["ok"])
        self.assertEqual(report["page_count"], 2)
        self.assertEqual([page["name"] for page in report["pages"]], ["One", "Two"])
        one = report["pages"][0]
        kinds = [widget["kind"] for widget in one["widgets"]]
        self.assertEqual(kinds.count("Text"), 1)
        self.assertEqual(kinds.count("Button"), 1)
        self.assertEqual(kinds.count("TextField"), 1)
        self.assertEqual(kinds.count("Image"), 1)
        title = next(widget for widget in one["widgets"] if widget["label"] == "Title")
        self.assertEqual(title["text"], "Shared title")
        self.assertEqual(title["geometry"]["width"], 180.0)
        cover = next(widget for widget in one["widgets"] if widget["label"] == "Cover")
        self.assertEqual(
            cover["image_sha256"],
            hashlib.sha256(PNG_BYTES).hexdigest(),
        )
        self.assertEqual(len(one["widgets"]), 6)

    def test_comparator_validates_pages_widgets_content_and_exact_image_bytes(
        self,
    ) -> None:
        design = _design()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compare.rp"
            _render(path, design)
            report = inspect_rp(path)

        comparison = compare_rp_to_design(report, design)

        self.assertTrue(comparison["ok"])
        self.assertEqual(comparison["page_count"], 2)
        self.assertEqual(comparison["widget_count"], 8)
        self.assertEqual(comparison["asset_count"], 1)
        self.assertEqual(comparison["mismatches"], [])

    def test_comparator_fails_when_expected_image_bytes_change(self) -> None:
        design = _design()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset-mismatch.rp"
            _render(path, design)
            report = inspect_rp(path)

        changed = _design()
        changed["pages"][0]["elements"][4]["imageBase64"] = "data:image/png;base64," + (
            base64.b64encode(b"different image bytes").decode("ascii")
        )
        comparison = compare_rp_to_design(report, changed)

        self.assertFalse(comparison["ok"])
        self.assertTrue(
            any(row["kind"] == "asset-bytes" for row in comparison["mismatches"])
        )

    def test_comparator_accepts_primary_widgets_and_axure_text_fallbacks(self) -> None:
        design = _design()
        design["pages"][0]["elements"].append(
            {
                "id": "spaced-note",
                "name": "Spaced note",
                "type": "text",
                "x": 40,
                "y": 180,
                "width": 220,
                "height": 36,
                "text": "First line Second line",
                "lines": ["First line", "Second line"],
                "textEmLines": 1,
                "textEmBox": [40.0, 183.0, 220.0, 14.0],
                "style": {
                    "fontSize": 12,
                    "lineHeight": 18,
                    "letterSpacing": 1,
                    "borderColor": "#d0d5dd",
                    "borderWidth": 1,
                    "textColor": "#202124",
                },
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fallback.rp"
            _render(path, design)
            report = inspect_rp(path)

        comparison = compare_rp_to_design(report, design)

        self.assertTrue(comparison["ok"])
        self.assertGreater(comparison["auxiliary_widget_count"], 0)
        self.assertEqual(comparison["content_mismatches"], 0)

    def test_image_candidate_single_line_text_avoids_axure_reflow(self) -> None:
        design = _design()
        design["pages"][0]["elements"].extend(
            [
                {
                    "id": "image-heading",
                    "name": "Image heading",
                    "type": "text",
                    "x": 40,
                    "y": 280,
                    "width": 348,
                    "height": 40,
                    "text": "Image import workspace",
                    "style": {"fontSize": 32, "fontWeight": "bold"},
                    "imageMVP": {"candidate_type": "text"},
                },
                {
                    "id": "image-description",
                    "name": "Image description",
                    "type": "text",
                    "x": 40,
                    "y": 330,
                    "width": 400,
                    "height": 60,
                    "text": "Editable text, sampled surfaces and reference-only image crops stay visible.",
                    "style": {"fontSize": 17},
                    "imageMVP": {"candidate_type": "text"},
                },
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image-text.rp"
            _render(path, design)
            report = inspect_rp(path)

        widgets = {widget["label"]: widget for widget in report["pages"][0]["widgets"]}
        self.assertTrue(widgets["Image heading"]["autofit_width"])
        self.assertFalse(widgets["Image description"]["autofit_width"])

    def test_comparator_maps_payload_only_container_to_image_box(self) -> None:
        design = _design()
        design["pages"][0]["elements"].append(
            {
                "id": "payload-container",
                "name": "Payload container",
                "type": "container",
                "x": 40,
                "y": 280,
                "width": 120,
                "height": 50,
                "imageBase64": "data:image/png;base64,"
                + base64.b64encode(PNG_BYTES).decode("ascii"),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payload-container.rp"
            _render(path, design)
            report = inspect_rp(path)

        comparison = compare_rp_to_design(report, design)

        self.assertTrue(comparison["ok"])
        self.assertEqual(comparison["asset_count"], 2)

    def test_measured_single_line_dom_text_avoids_axure_reflow(self) -> None:
        design = _design()
        design["pages"][0]["elements"].append(
            {
                "id": "measured-heading",
                "name": "Measured heading",
                "type": "text",
                "x": 40,
                "y": 280,
                "width": 150,
                "height": 40,
                "text": "Browser Support",
                "textEmLines": 1,
                "style": {"fontSize": 30, "lineHeight": 54},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "measured-single-line.rp"
            _render(path, design)
            report = inspect_rp(path)

        widget = next(
            item
            for item in report["pages"][0]["widgets"]
            if item["label"] == "Measured heading"
        )
        self.assertTrue(widget["autofit_width"])

    def test_styled_text_background_rect_is_an_auxiliary_widget(self) -> None:
        design = _design()
        design["pages"][0]["elements"].append(
            {
                "id": "styled-text",
                "name": "Styled text",
                "type": "text",
                "x": 40,
                "y": 280,
                "width": 360,
                "height": 96,
                "text": "Flow block keeps native text and a fixed-height contract.",
                "textEmLines": 2,
                "style": {
                    "fillColor": "#eef5ff",
                    "borderColor": "#2f6fed",
                    "borderWidth": 1,
                    "fontSize": 16,
                },
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "styled-text.rp"
            _render(path, design)
            report = inspect_rp(path)

        comparison = compare_rp_to_design(report, design)

        self.assertTrue(comparison["ok"])
        self.assertEqual(comparison["auxiliary_widget_count"], 1)
        self.assertEqual(
            comparison["auxiliary_widgets"],
            [
                {
                    "page": "One",
                    "source_label": "Styled text",
                    "kind": "Rect",
                    "geometry": {
                        "x": 40.0,
                        "y": 280.0,
                        "width": 360.0,
                        "height": 96.0,
                    },
                }
            ],
        )

    def test_unlabeled_rect_does_not_explain_neutral_text_background(self) -> None:
        design = _design()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "neutral-text-extra-rect.rp"
            _render(path, design)
            report = inspect_rp(path)

        report["pages"][0]["widgets"].append(
            {
                "label": "",
                "kind": "Rect",
                "geometry": {
                    "x": 40.0,
                    "y": 40.0,
                    "width": 180.0,
                    "height": 30.0,
                },
                "text": "",
            }
        )

        comparison = compare_rp_to_design(report, design)

        self.assertFalse(comparison["ok"])
        self.assertEqual(comparison["auxiliary_widget_count"], 0)
        self.assertTrue(
            any(row["kind"] == "widget-extra" for row in comparison["mismatches"])
        )

    def test_wide_captioned_button_does_not_expand_for_single_line_text(self) -> None:
        design = _design()
        design["pages"][0]["elements"].append(
            {
                "id": "wide-caption",
                "name": "Wide caption",
                "type": "button",
                "x": 40,
                "y": 280,
                "width": 858,
                "height": 40,
                "text": "Source",
                "textBox": [440.0, 292.0, 42.0, 15.0],
                "textEmBox": [440.0, 292.0, 42.0, 15.0],
                "textEmLines": 1,
                "style": {"fontSize": 11, "lineHeight": 20, "textAlign": "center"},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wide-caption.rp"
            _render(path, design)
            report = inspect_rp(path)

        widget = next(
            item
            for item in report["pages"][0]["widgets"]
            if item["label"] == "Wide caption"
        )
        self.assertFalse(widget["autofit_width"])
        self.assertEqual(widget["geometry"]["width"], 858.0)


if __name__ == "__main__":
    unittest.main()
