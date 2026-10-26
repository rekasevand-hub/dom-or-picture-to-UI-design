from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.image_axure_mvp import main
from src.app.services.contracts import build_output_ir


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _design() -> dict:
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    reference_id = "image-sha256:" + digest
    return {
        "name": "Image Axure fixture",
        "canvas": {"width": 320, "height": 180, "background": "#eef2f7"},
        "elements": [
            {
                "id": "title",
                "type": "text",
                "x": 20,
                "y": 16,
                "width": 180,
                "height": 24,
                "text": "Image Axure",
                "style": {"fontSize": 16, "textColor": "#202124"},
            },
            {
                "id": "crop",
                "type": "image",
                "x": 20,
                "y": 56,
                "width": 96,
                "height": 64,
                "imageBase64": "data:image/png;base64,"
                + base64.b64encode(PNG_BYTES).decode("ascii"),
                "imageMVP": {
                    "displayReplaceable": True,
                    "reference_only": True,
                    "originalAssetClaimed": False,
                },
                "sourceResolution": {
                    "use_id": reference_id + ":1:screenshot-crop",
                    "asset_id": "asset:unverified:image-fixture",
                    "identity": {
                        "selected": "unavailable",
                        "original": False,
                        "replaceable": False,
                    },
                    "display": {
                        "selected": "screenshot-crop",
                        "original": False,
                        "reference_only": True,
                        "generated": False,
                        "provenance": {"payload_sha256": digest},
                    },
                },
                "displayPayload": {
                    "kind": "screenshot-crop",
                    "original": False,
                    "reference_only": True,
                    "generated": False,
                    "payload_sha256": digest,
                },
            },
        ],
        "_meta": {
            "imageMVP": {
                "reference_id": reference_id,
                "state": {
                    "mode": "faithful",
                    "viewport": "unknown",
                    "dpr": "unknown",
                },
                "flow": {
                    "value": "fixed-coordinate",
                    "status": "candidate",
                    "adaptive": False,
                },
            }
        },
    }


class ImageAxureOutputTests(unittest.TestCase):
    def test_wrapper_runs_image_route_and_writes_deterministic_artifact(self) -> None:
        design = _design()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "image_design.json"
            ir_path = root / "image.ir.json"
            out = root / "evidence"
            design_path.write_text(json.dumps(design), encoding="utf-8")
            ir_path.write_text(
                json.dumps(build_output_ir(design, source_kind="image")),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "--design",
                    str(design_path),
                    "--ir",
                    str(ir_path),
                    "--out",
                    str(out),
                    "--page-name",
                    "A003 Image Axure",
                    "--generate-twice",
                ]
            )

            self.assertEqual(exit_code, 0)
            route = json.loads((out / "route.json").read_text(encoding="utf-8"))
            report = json.loads(
                (out / "artifact_report.json").read_text(encoding="utf-8")
            )

        self.assertEqual(route["source_kind"], "image")
        self.assertEqual(
            route["source_reference"]["reference_id"],
            design["_meta"]["imageMVP"]["reference_id"],
        )
        self.assertEqual(
            route["source_reference"]["state"]["mode"],
            "faithful",
        )
        self.assertIn(
            "runtime-image-replace->creation-only-image-box",
            route["projection"]["degraded"],
        )
        self.assertFalse(
            route["projection"]["acceptance"]["figma_evidence_transferable"]
        )
        self.assertTrue(report["determinism"]["identical"])
        self.assertEqual(report["inspection"]["page_count"], 1)
        self.assertEqual(report["inspection"]["asset_count"], 1)
        self.assertEqual(
            report["inspection"]["pages"][0]["name"],
            "A003 Image Axure",
        )


if __name__ == "__main__":
    unittest.main()
