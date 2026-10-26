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


if __name__ == "__main__":
    unittest.main()
