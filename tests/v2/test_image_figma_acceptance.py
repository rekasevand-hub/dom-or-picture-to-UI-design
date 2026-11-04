from __future__ import annotations

import base64
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from src.app.services.evidence.image_figma_acceptance import (
    build_image_acceptance_report,
    evaluate_image_mvp,
    run_image_figma_evidence,
    visual_similarity_metrics,
)


def _png(path: Path, *, include_second_text: bool = True) -> None:
    image = Image.new("RGB", (320, 180), "#f2f5f8")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 319, 39), fill="#26364f")
    draw.rectangle((20, 60, 300, 150), fill="#ffffff")
    draw.text((20, 12), "Image MVP", fill="#ffffff")
    draw.text((40, 80), "Critical total 128.50", fill="#172033")
    if include_second_text:
        draw.text((40, 110), "Reference-only image", fill="#526071")
    image.save(path)


def _base64_crop() -> str:
    output = io.BytesIO()
    Image.new("RGB", (20, 20), "#e85d75").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _bundle() -> dict:
    payload = _base64_crop()
    design = {
        "canvas": {"width": 320, "height": 180, "background": "#f2f5f8"},
        "elements": [
            {
                "id": "title",
                "type": "text",
                "x": 20,
                "y": 12,
                "width": 130,
                "height": 20,
                "text": "Image MVP",
                "style": {"textColor": "#ffffff", "fontSize": 16},
            },
            {
                "id": "total",
                "type": "text",
                "x": 40,
                "y": 80,
                "width": 210,
                "height": 22,
                "text": "Critical total 128.50",
                "style": {"textColor": "#172033", "fontSize": 16},
            },
            {
                "id": "photo",
                "type": "image",
                "x": 240,
                "y": 70,
                "width": 20,
                "height": 20,
                "imageBase64": payload,
                "sourceResolution": {
                    "identity": {
                        "original": False,
                        "selected": "unavailable",
                    },
                    "display": {
                        "selected": "screenshot-crop",
                        "original": False,
                        "reference_only": True,
                        "generated": False,
                    },
                },
            },
        ],
        "_meta": {
            "imageMVP": {
                "flow": {"value": "fixed-coordinate", "status": "candidate"},
                "input": {"original_asset_claim": False},
            }
        },
    }
    readback = {
        "id": "76:9000",
        "type": "FRAME",
        "x": 0,
        "y": 0,
        "width": 320,
        "height": 180,
        "children": [
            {
                "id": "1:1",
                "type": "TEXT",
                "x": 20,
                "y": 12,
                "width": 130,
                "height": 20,
                "characters": "Image MVP",
            },
            {
                "id": "1:2",
                "type": "TEXT",
                "x": 40,
                "y": 80,
                "width": 210,
                "height": 22,
                "characters": "Critical total 128.50",
            },
            {
                "id": "1:3",
                "type": "RECTANGLE",
                "x": 240,
                "y": 70,
                "width": 20,
                "height": 20,
                "fills": [{"type": "IMAGE", "imageHash": "fill-hash"}],
            },
        ],
    }
    return {
        "design": design,
        "readback_tree": readback,
        "truth": {
            "critical_texts": ["Image MVP", "Critical total 128.50"],
            "asset_claim": "display-replacement-only",
        },
        "text_probe": {"status": "pass"},
        "asset_probe": {"status": "pass"},
        "image_ir": {
            "assets": [
                {
                    "node_id": "photo",
                    "original": False,
                    "reference_only": True,
                    "generated": False,
                }
            ],
            "limitations": [
                "Original asset identity is unavailable from a flat screenshot."
            ],
        },
    }


class ImageFigmaAcceptanceTests(unittest.TestCase):
    def test_reference_only_display_asset_can_pass_without_original_claim(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            reference = root / "reference.png"
            export = root / "export.png"
            _png(reference)
            _png(export)
            metrics = visual_similarity_metrics(reference, export)
            result = evaluate_image_mvp(
                **_bundle(),
                visual_metrics=metrics,
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["dimensions"]["text"]["status"], "pass")
        self.assertEqual(result["dimensions"]["edit"]["status"], "pass")
        self.assertEqual(result["dimensions"]["asset"]["status"], "pass")
        self.assertEqual(result["dimensions"]["visual"]["status"], "pass")
        self.assertEqual(result["visual"]["within30_pct"], 100.0)
        self.assertFalse(result["asset_claims"]["original_asset"])
        self.assertTrue(result["asset_claims"]["reference_only_display"])

    def test_vector_icon_does_not_inflate_reference_asset_claim_count(self) -> None:
        bundle = _bundle()
        bundle["design"]["elements"].append(
            {
                "id": "search-icon",
                "type": "image",
                "x": 280,
                "y": 20,
                "width": 24,
                "height": 24,
                "vectorSvg": "<svg width='24' height='24'/>",
            }
        )
        bundle["readback_tree"]["children"].append(
            {
                "id": "1:4",
                "type": "FRAME",
                "x": 280,
                "y": 20,
                "width": 24,
                "height": 24,
                "children": [{"id": "1:5", "type": "VECTOR"}],
            }
        )
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            reference = root / "reference.png"
            export = root / "export.png"
            _png(reference)
            _png(export)
            result = evaluate_image_mvp(
                **bundle,
                visual_metrics=visual_similarity_metrics(reference, export),
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["dimensions"]["asset"]["status"], "pass")

    def test_wrong_critical_text_blocks_the_product_gate(self) -> None:
        bundle = _bundle()
        bundle["readback_tree"]["children"][0]["characters"] = "ImageMVP"
        bundle["design"]["elements"][0]["text"] = "ImageMVP"
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            reference = root / "reference.png"
            export = root / "export.png"
            _png(reference)
            _png(export)
            result = evaluate_image_mvp(
                **bundle,
                visual_metrics=visual_similarity_metrics(reference, export),
            )

        self.assertEqual(result["status"], "blocked-fail")
        self.assertEqual(result["dimensions"]["text"]["status"], "fail")
        self.assertIn("critical-text", result["blockers"])

    def test_policy_retains_frozen_90_percent_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            reference = Path(raw_dir) / "reference.png"
            export = Path(raw_dir) / "export.png"
            _png(reference)
            _png(export, include_second_text=False)
            result = evaluate_image_mvp(
                **_bundle(),
                visual_metrics=visual_similarity_metrics(reference, export),
            )

        self.assertEqual(
            result["policy"]["visual_within30_min_pct"],
            90.0,
        )
        self.assertEqual(result["policy"]["frozen"], True)

    def test_report_retains_real_figma_and_export_evidence(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            reference = root / "reference.png"
            export = root / "export.png"
            _png(reference)
            _png(export)
            expected_export_sha256 = hashlib.sha256(export.read_bytes()).hexdigest()
            report = build_image_acceptance_report(
                design=bundle["design"],
                truth=bundle["truth"],
                readback_tree=bundle["readback_tree"],
                reference_path=reference,
                export_path=export,
                text_probe=bundle["text_probe"],
                asset_probe=bundle["asset_probe"],
                image_ir=bundle["image_ir"],
                run_summary={
                    "status": "captured-figma-evidence",
                    "frame_id": "76:9000",
                },
            )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["frame_id"], "76:9000")
        self.assertEqual(report["figma_runtime"], "observed")
        self.assertTrue(report["export"]["exists"])
        self.assertEqual(report["visual"]["within30_pct"], 100.0)
        self.assertEqual(
            report["artifact_sha256"]["export.png"],
            expected_export_sha256,
        )

    def test_real_runner_keeps_image_schema_and_export_bytes(self) -> None:
        class FakeAdapter:
            frame_id = None
            calls = []

            def connect(self):
                pass

            def disconnect(self):
                pass

            def render_design(self, design):
                self.frame_id = "76:9100"

            def _send(self, action, params):
                if action == "get_node_tree":
                    return {"id": self.frame_id, "type": "FRAME", "children": []}
                if action == "export_frame":
                    payload = io.BytesIO()
                    Image.new("RGB", (320, 180), "white").save(payload, format="PNG")
                    return {
                        "base64": base64.b64encode(payload.getvalue()).decode("ascii")
                    }
                raise AssertionError(action)

        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            with (
                patch(
                    "src.app.services.evidence.image_figma_acceptance."
                    "run_text_edit_probe",
                    return_value={"status": "pass"},
                ),
                patch(
                    "src.app.services.evidence.image_figma_acceptance."
                    "run_asset_fill_probe",
                    return_value=({"status": "pass"}, {"fills": []}),
                ),
            ):
                result = run_image_figma_evidence(
                    {"canvas": {"width": 320, "height": 180}, "elements": []},
                    output_dir=root,
                    sample_id="IMG-MVP-01",
                    adapter_factory=FakeAdapter,
                )

            self.assertTrue((root / "readback.json").is_file())
            self.assertTrue((root / "export.png").is_file())

        self.assertEqual(result["schema_version"], "image-figma-real-run/1.0")
        self.assertEqual(result["status"], "captured-figma-evidence")
        self.assertEqual(result["frame_id"], "76:9100")


if __name__ == "__main__":
    unittest.main()
