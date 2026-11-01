from __future__ import annotations

import base64
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.structure.asset_metadata import build_asset_record
from src.app.services.structure.generated_icon_recovery import (
    generate_icon_approximations,
)


def _crop(color: tuple[int, int, int] = (80, 80, 80)) -> str:
    image = Image.new("RGB", (24, 24), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((5, 5, 17, 17), outline=color, width=2)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _icon_element(element_id: str, name: str) -> dict:
    crop = _crop()
    record = build_asset_record(
        sample_id="dom",
        node_index=int(element_id),
        source_kind="icon-crop",
        source=None,
        natural_size=(24, 24),
        display_box=(0, 0, 24, 24),
        display_payload_sha256=hashlib.sha256(base64.b64decode(crop)).hexdigest(),
        screenshot_sha256="f" * 64,
    )
    return {
        "id": element_id,
        "type": "image",
        "name": name,
        "x": 0,
        "y": 0,
        "width": 24,
        "height": 24,
        "imageBase64": crop,
        "assetIdentity": {"asset_record": record},
        "displayPayload": record["display_payload"],
        "replacement": record["replacement"],
    }


class GeneratedIconRecoveryTests(unittest.TestCase):
    def test_generates_distinct_provenanced_icon_candidates(self) -> None:
        design = {
            "canvas": {"width": 100, "height": 100},
            "elements": [
                _icon_element("1", "span.icon-search"),
                _icon_element("2", "span.icon-arrow-right"),
            ],
        }
        original = design["elements"][0]["imageBase64"]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = generate_icon_approximations(design, output_dir=root)
            files = sorted((root / "icons").iterdir())
            file_payloads = [path.read_bytes() for path in files]

        self.assertEqual(result["generated_count"], 2)
        self.assertEqual(len(files), 2)
        self.assertNotEqual(file_payloads[0], file_payloads[1])
        first = result["design"]["elements"][0]
        self.assertNotEqual(first["imageBase64"], original)
        candidate = first["generatedAssetCandidates"][0]
        self.assertEqual(
            first["sourceResolution"]["display"]["selected"],
            "generated-approximation",
        )
        self.assertEqual(
            first["sourceResolution"]["status"],
            "generated-icon-display",
        )
        self.assertTrue(candidate["bytes_present"])
        self.assertEqual(
            candidate["payload_sha256"],
            hashlib.sha256(base64.b64decode(first["imageBase64"])).hexdigest(),
        )
        for key in (
            "generator",
            "model",
            "input_reference",
            "prompt",
            "prompt_version",
            "review_status",
        ):
            self.assertTrue(candidate[key])
        generated = Image.open(
            io.BytesIO(base64.b64decode(first["imageBase64"]))
        ).convert("RGBA")
        self.assertEqual(generated.size, (24, 24))
        self.assertLess(min(generated.getchannel("A").get_flattened_data()), 255)

    def test_non_icon_elements_are_untouched(self) -> None:
        design = {
            "canvas": {"width": 100, "height": 100},
            "elements": [
                {
                    "id": "photo",
                    "type": "image",
                    "name": "img.photo",
                    "imageBase64": _crop(),
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            result = generate_icon_approximations(design, output_dir=tmp)

        self.assertEqual(result["generated_count"], 0)
        self.assertEqual(
            result["design"]["elements"][0]["imageBase64"],
            design["elements"][0]["imageBase64"],
        )

    def test_missing_regular_image_can_use_explicit_approximation_policy(
        self,
    ) -> None:
        record = build_asset_record(
            sample_id="dom",
            node_index=172,
            source_kind="image",
            source=None,
            natural_size=(18, 18),
            display_box=(118, 2764, 18, 18),
            display_payload_sha256=None,
            screenshot_sha256=None,
        )
        design = {
            "canvas": {"width": 100, "height": 3000},
            "elements": [
                {
                    "id": "172",
                    "type": "image",
                    "name": "svg 18x18",
                    "x": 118,
                    "y": 2764,
                    "width": 18,
                    "height": 18,
                    "imageBase64": "",
                    "assetIdentity": {"asset_record": record},
                    "displayPayload": record["display_payload"],
                    "replacement": record["replacement"],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            result = generate_icon_approximations(
                design,
                output_dir=tmp,
                include_missing_images=True,
            )

        element = result["design"]["elements"][0]
        candidate = element["generatedAssetCandidates"][0]
        self.assertEqual(result["generated_count"], 1)
        self.assertTrue(element["imageBase64"])
        self.assertEqual(candidate["use_class"], "image-placeholder")
        self.assertEqual(
            element["sourceResolution"]["display"]["selected"],
            "generated-approximation",
        )
        self.assertEqual(
            element["sourceResolution"]["status"],
            "partial-generated-display",
        )
        self.assertFalse(element["sourceResolution"]["identity"]["original"])

    def test_missing_img_tag_uses_generated_similar_image_even_with_screenshot_crop(
        self,
    ) -> None:
        screenshot_crop = _crop()
        source = {
            "source_url": "https://example.test/hero.jpg",
            "status": "missing",
            "sha256": None,
            "mime": None,
            "natural_size": None,
            "locator": None,
            "size_bytes": None,
        }
        record = build_asset_record(
            sample_id="dom",
            node_index=7,
            source_kind="image",
            source=source,
            natural_size=(320, 180),
            display_box=(10, 10, 320, 180),
            display_payload_sha256=hashlib.sha256(
                base64.b64decode(screenshot_crop)
            ).hexdigest(),
            screenshot_sha256="f" * 64,
        )
        design = {
            "canvas": {"width": 360, "height": 220},
            "elements": [
                {
                    "id": "hero",
                    "type": "image",
                    "name": 'img.hero "A mountain lake at sunrise"',
                    "alt": "A mountain lake at sunrise",
                    "x": 10,
                    "y": 10,
                    "width": 320,
                    "height": 180,
                    "imageBase64": screenshot_crop,
                    "assetIdentity": {"asset_record": record},
                    "displayPayload": record["display_payload"],
                    "replacement": record["replacement"],
                }
            ],
        }
        calls = []

        def image_generator(request):
            calls.append(request)
            image = Image.new("RGB", (64, 36), (20, 80, 140))
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        with tempfile.TemporaryDirectory() as tmp:
            result = generate_icon_approximations(
                design,
                output_dir=tmp,
                include_missing_images=True,
                image_generator=image_generator,
            )

        element = result["design"]["elements"][0]
        candidate = element["generatedAssetCandidates"][0]
        self.assertEqual(len(calls), 1)
        self.assertIn("mountain lake", calls[0]["prompt"])
        self.assertNotEqual(element["imageBase64"], screenshot_crop)
        self.assertEqual(candidate["use_class"], "image-generated")
        self.assertEqual(candidate["generation_mode"], "provider-generated")

    def test_missing_img_tag_can_use_vlm_authored_svg_fallback(self) -> None:
        source = {
            "source_url": "https://example.test/product.jpg",
            "status": "missing",
            "sha256": None,
            "mime": None,
            "natural_size": None,
            "locator": None,
            "size_bytes": None,
        }
        record = build_asset_record(
            sample_id="dom",
            node_index=9,
            source_kind="image",
            source=source,
            natural_size=(120, 80),
            display_box=(10, 10, 120, 80),
            display_payload_sha256=None,
            screenshot_sha256=None,
        )
        design = {
            "canvas": {"width": 160, "height": 120},
            "elements": [
                {
                    "id": "product",
                    "type": "image",
                    "name": 'img.product "A blue ceramic coffee mug"',
                    "alt": "A blue ceramic coffee mug",
                    "x": 10,
                    "y": 10,
                    "width": 120,
                    "height": 80,
                    "assetIdentity": {"asset_record": record},
                    "displayPayload": record["display_payload"],
                    "replacement": record["replacement"],
                }
            ],
        }

        def svg_generator(request):
            self.assertIn("coffee mug", request["prompt"])
            return (
                '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
                '<rect width="120" height="80" fill="#dceeff"/>'
                '<ellipse cx="60" cy="42" rx="28" ry="22" fill="#2563eb"/>'
                '</svg>'
            )

        with tempfile.TemporaryDirectory() as tmp:
            result = generate_icon_approximations(
                design,
                output_dir=tmp,
                include_missing_images=True,
                svg_generator=svg_generator,
            )

        element = result["design"]["elements"][0]
        candidate = element["generatedAssetCandidates"][0]
        self.assertEqual(candidate["generation_mode"], "vlm-svg")
        self.assertEqual(candidate["use_class"], "image-generated")
        self.assertTrue(element["imageBase64"])

    def test_text_over_missing_background_uses_reference_for_generation(
        self,
    ) -> None:
        reference = _crop()
        design = {
            "canvas": {"width": 320, "height": 180},
            "elements": [
                {
                    "id": "hero-background",
                    "type": "image",
                    "name": "img.background 320×180",
                    "imagePrompt": "abstract mountain landscape",
                    "x": 0,
                    "y": 0,
                    "width": 320,
                    "height": 180,
                    "generatedImageRequired": True,
                    "generationReferenceImageBase64": reference,
                },
                {
                    "id": "hero-title",
                    "type": "text",
                    "text": "Editable headline",
                    "x": 40,
                    "y": 70,
                    "width": 240,
                    "height": 40,
                },
            ],
        }
        calls = []

        def image_generator(request):
            calls.append(request)
            image = Image.new("RGB", (64, 36), (30, 90, 130))
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

        with tempfile.TemporaryDirectory() as tmp:
            result = generate_icon_approximations(
                design,
                output_dir=tmp,
                include_missing_images=True,
                image_generator=image_generator,
            )

        elements = result["design"]["elements"]
        background = elements[0]
        title = elements[1]
        self.assertEqual(len(calls), 1)
        self.assertIn("mountain landscape", calls[0]["prompt"])
        self.assertEqual(calls[0]["reference_image_base64"], reference)
        self.assertTrue(background["imageBase64"])
        self.assertNotIn("generatedImageRequired", background)
        self.assertEqual(title["text"], "Editable headline")
        self.assertNotIn("imageBase64", title)


if __name__ == "__main__":
    unittest.main()
