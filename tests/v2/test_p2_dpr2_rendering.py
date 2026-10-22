from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from src.app.services.som.design_crops import backfill_design_image_crops
from src.app.services.som.direct_design import build_direct_design
from src.app.services.rendering.figma_acceptance import (
    _evaluate_visual,
    _text_comparison_box,
    _text_vertical_tolerance,
)
from src.app.services.rendering.svg_adapter import SVGMockAdapter
from src.app.services.rendering.text_align import align_text_baselines
from src.app.utils.svg_raster import rasterize_svg
from scripts.p1_canonical_output_fidelity import apply_visual_policy


class Dpr2RenderingTests(unittest.TestCase):
    def test_svg_adapter_renders_non_white_canvas_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "mobile.svg"
            adapter = SVGMockAdapter(output_path)
            adapter.connect()
            adapter.create_frame(
                {
                    "width": 390,
                    "height": 844,
                    "backgroundColor": "#f7f8fa",
                }
            )
            adapter.flush()
            svg = output_path.read_text(encoding="utf-8")

        self.assertIn('fill="#f7f8fa"', svg)

    def test_svg_adapter_preserves_text_run_boundary_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "mixed.svg"
            adapter = SVGMockAdapter(output_path)
            adapter.connect()
            adapter.create_frame({"width": 200, "height": 80})
            adapter.create_text(
                {
                    "x": 20,
                    "y": 20,
                    "height": 30,
                    "text": " 中文回退",
                    "fontSize": 18,
                }
            )
            adapter.flush()
            svg = output_path.read_text(encoding="utf-8")

        self.assertIn('xml:space="preserve"', svg)

    def test_svg_adapter_renders_italic_font_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "italic.svg"
            adapter = SVGMockAdapter(output_path)
            adapter.connect()
            adapter.create_frame({"width": 200, "height": 80})
            adapter.create_text(
                {
                    "x": 20,
                    "y": 20,
                    "height": 30,
                    "text": "Italic run",
                    "fontSize": 18,
                    "fontStyle": "italic",
                }
            )
            adapter.flush()
            svg = output_path.read_text(encoding="utf-8")

        self.assertIn('font-style="italic"', svg)

    def test_svg_adapter_renders_numeric_variable_weight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "variable.svg"
            adapter = SVGMockAdapter(output_path)
            adapter.connect()
            adapter.create_frame({"width": 200, "height": 80})
            adapter.create_text(
                {
                    "x": 20,
                    "y": 20,
                    "height": 30,
                    "text": "Variable run",
                    "fontSize": 18,
                    "fontWeight": "bold",
                    "fontWeightValue": 650,
                }
            )
            adapter.flush()
            svg = output_path.read_text(encoding="utf-8")

        self.assertIn('font-weight="650"', svg)

    def test_visual_bad_pixel_limit_scales_with_reference_area(self) -> None:
        policy = {
            "max_mean": 1.0,
            "max_ink_mean": 10.0,
            "max_over30_pct": 0.8,
            "max_bad_pixel_count": 3000,
            "bad_pixel_count_reference_area": 900 * 700,
            "require_size_match": True,
        }
        base_metrics = {
            "mean": 0.5,
            "ink_mean": 6.8,
            "over30_pct": 0.28,
            "bad_pixel_count": 7089,
            "size_match": True,
        }

        dpr1 = apply_visual_policy(
            {
                **base_metrics,
                "reference_shape": [700, 900, 3],
            },
            policy,
        )
        dpr2 = apply_visual_policy(
            {
                **base_metrics,
                "reference_shape": [1400, 1800, 3],
            },
            policy,
        )

        self.assertEqual(dpr1["status"], "fail")
        self.assertEqual(dpr1["effective_max_bad_pixel_count"], 3000)
        self.assertEqual(dpr2["status"], "pass")
        self.assertEqual(dpr2["effective_max_bad_pixel_count"], 12000)

    def test_visual_count_can_be_observed_without_cross_viewport_gate(self) -> None:
        policy = {
            "max_mean": 1.0,
            "max_ink_mean": 10.0,
            "max_over30_pct": 0.8,
            "max_bad_pixel_count": 3000,
            "gate_bad_pixel_count": False,
            "require_size_match": True,
        }

        result = apply_visual_policy(
            {
                "mean": 0.7,
                "ink_mean": 7.3,
                "over30_pct": 0.62,
                "bad_pixel_count": 2048,
                "size_match": True,
                "reference_shape": [844, 390, 3],
            },
            policy,
        )

        self.assertEqual(result["status"], "pass")
        self.assertNotIn("bad_pixel_count", result["checks"])
        self.assertFalse(result["gate_bad_pixel_count"])

    def test_figma_visual_count_can_be_observed_without_gate(self) -> None:
        policy = {
            "policy_id": "p2-figma-dpr-aware",
            "max_mean": 1.0,
            "max_ink_mean": 10.0,
            "max_over30_pct": 0.8,
            "max_bad_pixel_count": 3000,
            "gate_bad_pixel_count": False,
            "require_size_match": True,
        }

        result = _evaluate_visual(
            {
                "mean": 0.7,
                "ink_mean": 7.3,
                "over30_pct": 0.62,
                "bad_pixel_count": 7089,
                "size_match": True,
            },
            policy,
        )

        self.assertEqual(result["status"], "pass")
        self.assertNotIn("bad_pixel_count", result["checks"])
        self.assertEqual(result["metrics"]["bad_pixel_count"], 7089)

    def test_measured_text_run_allows_figma_line_box_height(self) -> None:
        element = {
            "type": "text",
            "textLineBox": True,
            "style": {"lineHeight": 40},
        }

        box = _text_comparison_box(
            element,
            {"x": 30.0, "y": 105.0, "width": 68.0, "height": 27.0},
        )

        self.assertEqual(box["height"], 40.0)
        self.assertEqual(box["width"], 68.0)

    def test_measured_multiline_text_uses_total_line_box_height(self) -> None:
        element = {
            "type": "text",
            "textEmBox": [58, 160, 47, 16],
            "textEmLines": 2,
            "style": {"lineHeight": 20},
        }

        box = _text_comparison_box(
            element,
            {"x": 58.0, "y": 160.0, "width": 84.0, "height": 36.0},
        )

        self.assertEqual(box["height"], 40.0)

    def test_taller_text_box_allows_inner_vertical_centering(self) -> None:
        tolerance = _text_vertical_tolerance(
            {"type": "text"},
            {"x": 16.0, "y": 63.0, "width": 398.0, "height": 66.0},
            {"x": 16.0, "y": 74.0, "width": 398.0, "height": 44.0},
            base_tolerance=1.0,
        )

        self.assertEqual(tolerance, 12.0)

    def test_design_canvas_uses_logical_viewport_not_physical_screenshot(self) -> None:
        som = {
            "size": [1800, 1400],
            "containers": [],
            "elements": [],
            "provenance": {
                "route": "dom",
                "capture": {
                    "device_scale_factor": 2,
                    "viewport": {"width": 900, "height": 700},
                },
            },
        }

        design = build_direct_design(som)

        self.assertEqual(design["canvas"]["width"], 900)
        self.assertEqual(design["canvas"]["height"], 700)
        self.assertEqual(design["_meta"]["pixelRatio"], 2)

    def test_image_crop_scales_logical_box_to_physical_screenshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "page.png"
            image = np.full((20, 40, 3), 255, dtype=np.uint8)
            image[4:14, 4:24] = (0, 0, 255)
            cv2.imwrite(str(image_path), image)
            design = {
                "canvas": {"width": 20, "height": 10},
                "elements": [
                    {
                        "type": "image",
                        "x": 2,
                        "y": 2,
                        "width": 10,
                        "height": 5,
                    }
                ],
                "_meta": {"pixelRatio": 2},
            }

            stats = backfill_design_image_crops(design, str(image_path))

        self.assertEqual(stats["backfilled"], 1)
        encoded = design["elements"][0]["imageBase64"]
        crop = cv2.imdecode(
            np.frombuffer(base64.b64decode(encoded), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(crop)
        assert crop is not None
        self.assertEqual(crop.shape[:2], (10, 20))

    def test_svg_rasterization_uses_device_scale_factor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            svg_path = root / "sample.svg"
            png_path = root / "sample.png"
            svg_path.write_text(
                (
                    '<svg xmlns="http://www.w3.org/2000/svg" '
                    'width="20" height="10" viewBox="0 0 20 10">'
                    '<rect width="20" height="10" fill="white"/>'
                    '<rect x="2" y="2" width="8" height="4" fill="black"/>'
                    "</svg>"
                ),
                encoding="utf-8",
            )

            rasterize_svg(
                svg_path,
                png_path,
                width=20,
                height=10,
                device_scale_factor=2,
            )
            image = cv2.imread(str(png_path))

        self.assertIsNotNone(image)
        assert image is not None
        self.assertEqual(image.shape[:2], (20, 40))

    def test_text_alignment_scales_design_box_and_offsets_by_dpr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference_path = root / "reference.png"
            render_path = root / "render.png"
            reference = np.full((20, 40, 3), 255, dtype=np.uint8)
            render = reference.copy()
            reference[8:14, 4:24] = 0
            render[4:10, 4:24] = 0
            cv2.imwrite(str(reference_path), reference)
            cv2.imwrite(str(render_path), render)
            design = {
                "elements": [
                    {
                        "type": "text",
                        "text": "DPR2",
                        "x": 2,
                        "y": 2,
                        "width": 10,
                        "height": 6,
                    }
                ]
            }

            result = align_text_baselines(
                design,
                reference_path,
                render_path,
                device_scale_factor=2,
                min_gain=0.1,
                min_ratio=0.9,
            )

        self.assertEqual(result["changed"], 1)
        self.assertEqual(design["elements"][0]["y"], 3)


if __name__ == "__main__":
    unittest.main()
