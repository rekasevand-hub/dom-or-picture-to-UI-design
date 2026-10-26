from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.axure_dom_output import main


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
SECOND_BYTES = b"\x89PNG\r\n\x1a\nsecond-axure-image"


def _image(payload: bytes, use_id: str, generated: bool = False) -> dict:
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "imageBase64": "data:image/png;base64,"
        + base64.b64encode(payload).decode("ascii"),
        "sourceResolution": {
            "use_id": use_id,
            "asset_id": f"asset:test:{use_id}",
            "identity": {
                "selected": "unavailable" if generated else "verified-source",
                "original": not generated,
                "replaceable": not generated,
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
            "payload_sha256": digest,
            "original": False,
            "reference_only": not generated,
            "generated": generated,
        },
    }


def _design() -> dict:
    first = _image(PNG_BYTES, "dom:1:img")
    second = _image(SECOND_BYTES, "dom:2:icon", generated=True)
    return {
        "pages": [
            {
                "name": "Home",
                "canvas": {"width": 640, "height": 480, "background": "#ffffff"},
                "elements": [
                    {
                        "id": "headline",
                        "name": "Headline",
                        "type": "text",
                        "x": 24,
                        "y": 20,
                        "width": 280,
                        "height": 32,
                        "text": "Axure DOM",
                        "style": {"fontSize": 20, "textColor": "#202124"},
                    },
                    {
                        "id": "crop",
                        "name": "Crop",
                        "type": "image",
                        "x": 24,
                        "y": 72,
                        "width": 160,
                        "height": 100,
                        **first,
                    },
                ],
            },
            {
                "name": "Details",
                "canvas": {"width": 400, "height": 320, "background": "#fafafa"},
                "elements": [
                    {
                        "id": "detail",
                        "name": "Detail",
                        "type": "text",
                        "x": 20,
                        "y": 20,
                        "width": 240,
                        "height": 30,
                        "text": "Detail page",
                        "style": {"fontSize": 18, "textColor": "#202124"},
                    },
                    {
                        "id": "icon",
                        "name": "Generated icon",
                        "type": "image",
                        "x": 20,
                        "y": 72,
                        "width": 24,
                        "height": 24,
                        **second,
                    },
                ],
            },
        ]
    }


class AxureDomOutputProbeTests(unittest.TestCase):
    def test_probe_writes_deterministic_artifacts_and_separate_acceptance_scope(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "design.json"
            design_path.write_text(
                json.dumps(_design(), ensure_ascii=False),
                encoding="utf-8",
            )
            out = root / "evidence"

            exit_code = main(
                [
                    "--design",
                    str(design_path),
                    "--out",
                    str(out),
                    "--source-kind",
                    "dom",
                    "--generate-twice",
                ]
            )

            self.assertEqual(exit_code, 0)
            for name in (
                "prototype.rp",
                "design.ir.json",
                "route.json",
                "artifact_report.json",
            ):
                self.assertTrue((out / name).is_file(), name)
            route = json.loads((out / "route.json").read_text(encoding="utf-8"))
            report = json.loads(
                (out / "artifact_report.json").read_text(encoding="utf-8")
            )

        self.assertEqual(route["document_id"], report["document_id"])
        self.assertEqual(report["inspection"]["page_count"], 2)
        self.assertEqual(report["inspection"]["asset_count"], 2)
        self.assertTrue(report["self_check"]["ok"])
        self.assertTrue(report["integrity"]["ok"])
        self.assertTrue(report["determinism"]["identical"])
        self.assertFalse(
            route["projection"]["acceptance"]["figma_evidence_transferable"]
        )
        self.assertEqual(
            report["acceptance_scope"],
            "axure-specific-required",
        )

    def test_probe_requires_an_image_payload_for_each_ir_asset(self) -> None:
        design = _design()
        design["pages"][0]["elements"][1]["imageBase64"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "broken.json"
            design_path.write_text(json.dumps(design), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "image payload is missing"):
                main(
                    [
                        "--design",
                        str(design_path),
                        "--out",
                        str(root / "out"),
                        "--source-kind",
                        "dom",
                    ]
                )

    def test_probe_can_set_a_target_specific_page_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "design.json"
            design_path.write_text(json.dumps(_design()), encoding="utf-8")
            out = root / "evidence"

            exit_code = main(
                [
                    "--design",
                    str(design_path),
                    "--out",
                    str(out),
                    "--source-kind",
                    "dom",
                    "--page-name",
                    "Axure Home",
                    "--page-name",
                    "Axure Details",
                ]
            )

            self.assertEqual(exit_code, 0)
            target_design = json.loads(
                (out / "axure_design.json").read_text(encoding="utf-8")
            )
            report = json.loads(
                (out / "artifact_report.json").read_text(encoding="utf-8")
            )
        self.assertEqual(
            [page["name"] for page in target_design["pages"]],
            ["Axure Home", "Axure Details"],
        )
        self.assertEqual(
            [page["name"] for page in report["inspection"]["pages"]],
            ["Axure Home", "Axure Details"],
        )


if __name__ == "__main__":
    unittest.main()
