from __future__ import annotations

import base64
import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path

from src.app.services.evidence.axure_acceptance import evaluate_published_axure
from src.app.services.rendering.axure_adapter import AxureRPAdapter
from src.app.services.rendering.axure.evidence import inspect_rp


PNG_A = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PNG_B = b"\x89PNG\r\n\x1a\nsecond-axure-published-image"


def _image(payload: bytes, use_id: str, *, generated: bool = False) -> dict:
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "imageBase64": "data:image/png;base64,"
        + base64.b64encode(payload).decode("ascii"),
        "sourceResolution": {
            "use_id": use_id,
            "identity": {
                "selected": "unavailable",
                "original": False,
                "replaceable": False,
            },
            "display": {
                "selected": "generated-approximation"
                if generated
                else "screenshot-crop",
                "original": False,
                "reference_only": not generated,
                "generated": generated,
                "provenance": {"payload_sha256": digest},
            },
        },
        "displayPayload": {
            "kind": "generated-approximation" if generated else "screenshot-crop",
            "original": False,
            "reference_only": not generated,
            "generated": generated,
            "payload_sha256": digest,
        },
    }


def _design() -> dict:
    return {
        "pages": [
            {
                "name": "Home",
                "canvas": {"width": 640, "height": 480},
                "elements": [
                    {
                        "id": "title",
                        "name": "Headline",
                        "type": "text",
                        "x": 24,
                        "y": 20,
                        "width": 240,
                        "height": 32,
                        "text": "Axure DOM",
                    },
                    {
                        "id": "crop",
                        "name": "Crop",
                        "type": "image",
                        "x": 24,
                        "y": 72,
                        "width": 160,
                        "height": 100,
                        **_image(PNG_A, "image:1:crop"),
                    },
                    {
                        "id": "quoted",
                        "name": 'span "Quoted"',
                        "type": "text",
                        "x": 24,
                        "y": 190,
                        "width": 180,
                        "height": 24,
                        "text": "Quoted label",
                    },
                ],
            },
            {
                "name": "Details",
                "canvas": {"width": 400, "height": 320},
                "elements": [
                    {
                        "id": "detail",
                        "name": "Detail",
                        "type": "text",
                        "x": 20,
                        "y": 20,
                        "width": 200,
                        "height": 30,
                        "text": "Detail page",
                    },
                    {
                        "id": "icon",
                        "name": "Icon",
                        "type": "image",
                        "x": 20,
                        "y": 72,
                        "width": 24,
                        "height": 24,
                        **_image(PNG_B, "image:2:icon", generated=True),
                    },
                ],
            },
        ]
    }


def _write_fixture(root: Path) -> None:
    (root / "data").mkdir(parents=True)
    (root / "files" / "home").mkdir(parents=True)
    (root / "files" / "details").mkdir(parents=True)
    (root / "images" / "home").mkdir(parents=True)
    (root / "images" / "details").mkdir(parents=True)
    (root / "data" / "document.js").write_text(
        'var t="rootNodes",u="pageName",v="Home",y="url",z="home.html",'
        'A="Details",B="details.html",C="globalVariables";',
        encoding="utf-8",
    )
    (root / "home.html").write_text(
        '<div data-label="Background"></div>'
        '<div data-label="Headline"><span>Axure DOM</span></div>'
        '<div data-label="Crop"></div>'
        '<div data-label="span &quot;Quoted&quot;"><span>Quoted label</span></div>',
        encoding="utf-8",
    )
    (root / "details.html").write_text(
        '<div data-label="Background"></div>'
        '<div data-label="Detail"><span>Detail page</span></div>'
        '<div data-label="Icon"></div>',
        encoding="utf-8",
    )
    (root / "files" / "home" / "data.js").write_text(
        'var q="name",a="Home",r="packageId",b="11111111111111111111111111111111",'
        's="width",c=640,t="height",d=480;',
        encoding="utf-8",
    )
    (root / "files" / "details" / "data.js").write_text(
        'var q="name",a="Details",r="packageId",b="22222222222222222222222222222222",'
        's="width",c=400,t="height",d=320;',
        encoding="utf-8",
    )
    (root / "files" / "home" / "styles.css").write_text(
        "body { width:640px; } #u0_div { width:640px; height:480px; }",
        encoding="utf-8",
    )
    (root / "files" / "details" / "styles.css").write_text(
        "body { width:400px; } #u0_div { width:400px; height:320px; }",
        encoding="utf-8",
    )
    (root / "images" / "home" / "crop.png").write_bytes(PNG_A)
    (root / "images" / "details" / "icon.png").write_bytes(PNG_B)


def _rp_report() -> dict:
    return {
        "pages": [
            {"name": "Home", "package_guid": "11111111-1111-1111-1111-111111111111"},
            {"name": "Details", "package_guid": "22222222-2222-2222-2222-222222222222"},
        ]
    }


def _write_ppm(
    path: Path,
    *,
    width: int = 100,
    height: int = 100,
    ink_box: tuple[int, int, int, int] | None = None,
) -> None:
    pixels = bytearray(b"\xff" * (width * height * 3))
    if ink_box is not None:
        x, y, box_width, box_height = ink_box
        for row in range(max(0, y), min(height, y + box_height)):
            for column in range(max(0, x), min(width, x + box_width)):
                offset = (row * width + column) * 3
                pixels[offset : offset + 3] = b"\x00\x00\x00"
    path.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + pixels)


class AxurePublishedAcceptanceTests(unittest.TestCase):
    def test_evaluator_checks_pages_labels_text_canvas_and_unique_image_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)

            result = evaluate_published_axure(
                root,
                design=_design(),
                rp_report=_rp_report(),
                critical_texts=["Axure DOM", "Detail page"],
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(result["label_count"], 7)
        self.assertEqual(result["critical_text"]["passed"], 2)
        self.assertEqual(result["assets"]["matched_unique"], 2)
        self.assertEqual(result["visual"]["status"], "not-evaluated")
        self.assertEqual(result["acceptance_scope"], "axure-specific-required")

    def test_evaluator_fails_closed_when_a_page_or_asset_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            (root / "details.html").unlink()
            (root / "images" / "home" / "crop.png").unlink()

            result = evaluate_published_axure(
                root,
                design=_design(),
                critical_texts=["Axure DOM", "Detail page"],
            )

        self.assertEqual(result["status"], "fail")
        self.assertTrue(
            any(row["kind"] == "page-missing" for row in result["failures"])
        )
        self.assertTrue(
            any(row["kind"] == "asset-missing" for row in result["failures"])
        )

    def test_evaluator_does_not_inherit_figma_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            result = evaluate_published_axure(
                root,
                design=_design(),
                critical_texts=["Axure DOM"],
            )

        self.assertFalse(result["claims"]["figma_evidence_transferable"])
        self.assertFalse(result["claims"]["runtime_image_replacement"])
        self.assertFalse(result["claims"]["auto_layout"])
        self.assertFalse(result["claims"]["native_letter_spacing"])

    def test_evaluator_reports_reference_only_and_generated_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            result = evaluate_published_axure(
                root,
                design=_design(),
                critical_texts=["Axure DOM"],
            )

        self.assertEqual(result["provenance"]["reference_only"], 1)
        self.assertEqual(result["provenance"]["generated"], 1)
        self.assertEqual(result["provenance"]["display_original"], 0)
        self.assertEqual(result["provenance"]["original"], 0)

    def test_evaluator_does_not_require_empty_labels_from_image_candidates(
        self,
    ) -> None:
        design = _design()
        for page in design["pages"]:
            for element in page["elements"]:
                element.pop("name", None)
                element.pop("label", None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            result = evaluate_published_axure(
                root,
                design=design,
                critical_texts=["Axure DOM"],
            )

        self.assertEqual(result["status"], "pass")
        self.assertFalse(
            any(
                row["kind"] == "label-missing" and row["label"] == ""
                for row in result["failures"]
            )
        )
        self.assertNotIn("DQ-R02", " ".join(result["limitations"]))

    def test_critical_text_matches_across_ocr_punctuation_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            (root / "home.html").write_text(
                '<div data-label="Background"></div>'
                "<span>The page contains an image element;</span>"
                "<span>a CSS background image;</span>"
                "<span>and an inline SVG_</span>",
                encoding="utf-8",
            )
            result = evaluate_published_axure(
                root,
                design=_design(),
                critical_texts=[
                    "The page contains an image element, a CSS background image, and an inline SVG."
                ],
            )

        self.assertEqual(result["critical_text"]["passed"], 1)

    def test_expected_asset_count_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            result = evaluate_published_axure(
                root,
                design=_design(),
                critical_texts=["Axure DOM"],
                expected_asset_count=3,
            )

        self.assertEqual(result["status"], "fail")
        self.assertTrue(any(row["kind"] == "asset-count" for row in result["failures"]))

    def test_visual_critical_region_fails_when_render_region_is_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            reference = root / "reference.ppm"
            render = root / "render.ppm"
            _write_ppm(reference, ink_box=(20, 20, 20, 10))
            _write_ppm(render)

            result = evaluate_published_axure(
                root,
                design=_design(),
                critical_texts=["Axure DOM"],
                reference_screenshot=reference,
                render_screenshot=render,
                critical_regions=[
                    {
                        "name": "headline",
                        "x": 20,
                        "y": 20,
                        "width": 20,
                        "height": 10,
                    }
                ],
            )

        self.assertEqual(result["status"], "fail")
        self.assertTrue(
            any(row["kind"] == "critical-region-missing" for row in result["failures"])
        )
        self.assertFalse(result["claims"]["axure_visual_acceptance"])
        self.assertFalse(result["critical_regions"]["rows"][0]["passed"])

    def test_visual_critical_region_passes_when_reference_ink_is_preserved(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            reference = root / "reference.ppm"
            render = root / "render.ppm"
            _write_ppm(reference, ink_box=(20, 20, 60, 20))
            _write_ppm(render, ink_box=(20, 20, 60, 20))

            result = evaluate_published_axure(
                root,
                design=_design(),
                critical_texts=["Axure DOM"],
                reference_screenshot=reference,
                render_screenshot=render,
                critical_regions=[
                    {
                        "name": "headline",
                        "x": 20,
                        "y": 20,
                        "width": 60,
                        "height": 20,
                    }
                ],
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["critical_regions"]["status"], "pass")
        self.assertTrue(result["critical_regions"]["rows"][0]["passed"])

    def test_payload_only_container_is_counted_as_axure_asset(self) -> None:
        payload = b"\x89PNG\r\n\x1a\ncontainer-holdout"
        design = _design()
        design["pages"][0]["elements"].append(
            {
                "id": "payload-container",
                "type": "container",
                "x": 40,
                "y": 280,
                "width": 120,
                "height": 50,
                "imageBase64": "data:image/png;base64,"
                + base64.b64encode(payload).decode("ascii"),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root)
            (root / "images" / "home" / "container.png").write_bytes(payload)
            result = evaluate_published_axure(
                root,
                design=design,
                critical_texts=["Axure DOM"],
                expected_asset_count=3,
            )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["assets"]["matched_unique"], 3)
        self.assertEqual(result["provenance"]["uses"], 3)

    def test_cli_writes_acceptance_json_from_rp_and_publish_dir(self) -> None:
        module = importlib.import_module("scripts.axure_acceptance")
        design = _design()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_fixture(root / "publish")
            rp_path = root / "prototype.rp"
            adapter = AxureRPAdapter(rp_path)
            adapter.connect()
            adapter.render_design(design)
            adapter.disconnect()
            rp_pages = {
                page["name"]: page["package_guid"].replace("-", "")
                for page in inspect_rp(rp_path)["pages"]
            }
            (root / "publish" / "files" / "home" / "data.js").write_text(
                'var q="name",a="Home",r="packageId",b="%s",'
                's="width",c=640,t="height",d=480;' % rp_pages["Home"],
                encoding="utf-8",
            )
            (root / "publish" / "files" / "details" / "data.js").write_text(
                'var q="name",a="Details",r="packageId",b="%s",'
                's="width",c=400,t="height",d=320;' % rp_pages["Details"],
                encoding="utf-8",
            )
            design_path = root / "design.json"
            design_path.write_text(json.dumps(design), encoding="utf-8")
            out = root / "acceptance"
            reference = root / "reference.ppm"
            render = root / "render.ppm"
            _write_ppm(reference, ink_box=(10, 10, 30, 20))
            _write_ppm(render, ink_box=(10, 10, 30, 20))

            exit_code = module.main(
                [
                    "--publish-dir",
                    str(root / "publish"),
                    "--design",
                    str(design_path),
                    "--rp",
                    str(rp_path),
                    "--out",
                    str(out),
                    "--critical-text",
                    "Axure DOM",
                    "--critical-text",
                    "Detail page",
                    "--reference-screenshot",
                    str(reference),
                    "--render-screenshot",
                    str(render),
                    "--critical-region",
                    "headline,10,10,30,20",
                ]
            )

            self.assertEqual(exit_code, 0)
            result = json.loads((out / "acceptance.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["packages"]["matched"], 2)
        self.assertEqual(result["critical_regions"]["rows"][0]["name"], "headline")
        self.assertTrue(result["critical_regions"]["rows"][0]["passed"])


if __name__ == "__main__":
    unittest.main()
