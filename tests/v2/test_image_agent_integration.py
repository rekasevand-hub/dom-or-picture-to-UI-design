from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from src.app.agents.precise_agent import PreciseAgent
from src.config.settings import Config


class _ImageProvider:
    def run(self, ctx):
        return {
            "image": ctx.image_path,
            "image_w": ctx.image_w,
            "image_h": ctx.image_h,
            "route": "grounding",
            "containers": [
                {
                    "id": "C1",
                    "bbox": [0, 0, 240, 40],
                    "role": "banner",
                    "source": "grounding",
                    "parent": None,
                    "depth": 0,
                }
            ],
            "elements": [
                {
                    "id": 1,
                    "bbox": [16, 10, 150, 22],
                    "type": "text",
                    "text": "Image Integration",
                    "role": "",
                    "source": "grounding",
                    "container": "C1",
                }
            ],
            "provenance": {"route": "grounding", "fallbacks": [], "warnings": []},
        }


class _RejectingProvider:
    def run(self, ctx):
        raise ValueError("Grounding returned invalid JSON")


class _CVProvider:
    def run(self, ctx):
        return {
            "image": ctx.image_path,
            "image_w": ctx.image_w,
            "image_h": ctx.image_h,
            "route": "cv",
            "containers": [],
            "elements": [
                {
                    "id": 1,
                    "bbox": [16, 10, 150, 22],
                    "type": "text",
                    "text": "Image Integration",
                    "role": "",
                    "source": "cv:ocr",
                    "container": None,
                }
            ],
            "provenance": {"route": "cv", "fallbacks": [], "warnings": []},
        }


def _recover_text(graph, image_path):
    merged = json.loads(json.dumps(graph))
    merged["elements"].append(
        {
            "id": 2,
            "bbox": [24, 44, 90, 20],
            "type": "text",
            "text": "Recovered CTA",
            "role": "",
            "source": "ocr-supplement:easyocr",
            "imageMVPTextStatus": "ocr-candidate",
            "authority": "ocr-candidate",
            "verified": False,
            "container": None,
        }
    )
    return merged, {
        "schema_version": "image-ocr-supplement/1.0",
        "status": "applied",
        "source": "ocr-supplement:easyocr",
        "added_count": 1,
        "added": [merged["elements"][-1]],
        "observation_count": 1,
    }


def _recover_region(graph, image_path):
    merged = json.loads(json.dumps(graph))
    merged["elements"].append(
        {
            "id": 3,
            "bbox": [24, 60, 80, 60],
            "type": "image",
            "text": "",
            "role": "",
            "source": "image-region-recovery:saturation-component",
            "container": None,
        }
    )
    return merged, {
        "schema_version": "image-region-recovery/1.0",
        "status": "applied",
        "source": "image-region-recovery:saturation-component",
        "added_count": 1,
        "added": [merged["elements"][-1]],
    }


def _image(path: Path) -> None:
    image = Image.new("RGB", (240, 140), "#eef2f7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 239, 39), fill="#24324a")
    draw.text((16, 10), "Image Integration", fill="#ffffff")
    image.save(path)


class ImageAgentIntegrationTests(unittest.TestCase):
    def test_image_input_writes_reference_ir_and_deterministic_design(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            path = root / "upload.png"
            output = root / "out"
            _image(path)
            cfg = Config(
                output_dir=output,
                vision_api_key="configured",
                text_align=False,
            )
            with (
                patch(
                    "src.app.agents.precise_agent._build_provider",
                    return_value=_ImageProvider(),
                ),
                patch(
                    "src.app.controllers.rendering_controller."
                    "RenderingController.render",
                    return_value=None,
                ),
                patch(
                    "src.app.agents.precise_agent.recover_image_text_candidates",
                    side_effect=_recover_text,
                ),
                patch(
                    "src.app.agents.precise_agent.recover_image_region_candidates",
                    side_effect=_recover_region,
                ),
            ):
                PreciseAgent(cfg).run(
                    image=str(path),
                    route="auto",
                    tool="svg",
                )

            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            design = json.loads((output / "12_design.json").read_text(encoding="utf-8"))
            image_ir = json.loads(
                (output / "image_ir.json").read_text(encoding="utf-8")
            )
            ocr_supplement = json.loads(
                (output / "ocr_supplement.json").read_text(encoding="utf-8")
            )
            region_recovery = json.loads(
                (output / "image_region_recovery.json").read_text(encoding="utf-8")
            )

        self.assertEqual(manifest["input_kind"], "image")
        self.assertEqual(manifest["route"], "grounding")
        self.assertEqual(
            manifest["imageMVP"]["presentation"],
            "grounding-pixel-sampled-fixed-coordinate",
        )
        self.assertEqual(
            design["_meta"]["imagePresentation"],
            "grounding-pixel-sampled-fixed-coordinate",
        )
        self.assertEqual(image_ir["input"]["state"]["mode"], "faithful")
        self.assertEqual(image_ir["strategy"]["selected"], "grounding")
        self.assertEqual(image_ir["counts"]["text_candidates"], 2)
        self.assertTrue(
            any(
                (node.get("fields", {}).get("text") or {}).get("authority")
                == "ocr-candidate"
                for node in image_ir["nodes"]
            )
        )
        self.assertEqual(ocr_supplement["added_count"], 1)
        self.assertEqual(manifest["ocr_supplement"]["added_count"], 1)
        self.assertEqual(region_recovery["added_count"], 1)
        self.assertEqual(manifest["image_region_recovery"]["added_count"], 1)
        self.assertEqual(image_ir["counts"]["image_candidates"], 1)

    def test_auto_image_route_does_not_fallback_on_parse_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            path = root / "upload.png"
            _image(path)
            cfg = Config(
                output_dir=root / "out",
                vision_api_key="configured",
                text_align=False,
            )
            with patch(
                "src.app.agents.precise_agent._build_provider",
                side_effect=[_RejectingProvider(), _ImageProvider()],
            ) as build_provider:
                with self.assertRaises(ValueError):
                    PreciseAgent(cfg).run(image=str(path), route="auto", tool="svg")

        self.assertEqual(build_provider.call_count, 1)

    def test_image_auto_missing_vlm_config_records_grounding_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            path = root / "upload.png"
            output = root / "out"
            _image(path)
            cfg = Config(
                output_dir=output,
                vision_api_key="",
                text_align=False,
            )
            with (
                patch(
                    "src.app.agents.precise_agent._build_provider",
                    return_value=_CVProvider(),
                ),
                patch(
                    "src.app.controllers.rendering_controller."
                    "RenderingController.render",
                    return_value=None,
                ),
                patch(
                    "src.app.agents.precise_agent.recover_image_text_candidates",
                    side_effect=_recover_text,
                ),
                patch(
                    "src.app.agents.precise_agent.recover_image_region_candidates",
                    side_effect=_recover_region,
                ),
            ):
                PreciseAgent(cfg).run(
                    image=str(path),
                    route="auto",
                    tool="svg",
                )

            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )

        strategy = manifest["imageMVP"]["strategy"]
        self.assertEqual(strategy["selected"], "cv")
        self.assertEqual(
            manifest["imageMVP"]["presentation"],
            "cv-pixel-sampled-fixed-coordinate",
        )
        self.assertEqual(
            strategy["attempts"],
            [
                {
                    "strategy": "grounding",
                    "status": "unavailable",
                    "reason": "grounding-config-missing",
                },
                {"strategy": "cv", "status": "selected"},
            ],
        )
        self.assertTrue(strategy["fallback_used"])
        self.assertEqual(manifest["fallbacks"][0]["reason"], "grounding-config-missing")


if __name__ == "__main__":
    unittest.main()
