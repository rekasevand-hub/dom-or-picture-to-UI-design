from __future__ import annotations

import base64
import copy
import hashlib
import unittest

from src.app.services.contracts import build_output_ir
from src.app.services.rendering.axure_route import plan_axure_route


IMAGE_A = b"\x89PNG\r\n\x1a\naxure-route-a"
IMAGE_B = b"\x89PNG\r\n\x1a\naxure-route-b"


def _data_url(payload: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")


def _design() -> dict:
    return {
        "name": "Axure route sample",
        "canvas": {
            "width": 640,
            "height": 480,
            "background": "#ffffff",
        },
        "elements": [
            {
                "id": "title",
                "type": "text",
                "x": 24,
                "y": 20,
                "width": 320,
                "height": 32,
                "text": "Axure route",
                "name": "Title",
                "source": "dom",
                "style": {
                    "fontFamily": "Microsoft YaHei",
                    "fontSize": 20,
                    "fontWeight": 700,
                    "textColor": "#202124",
                    "letterSpacing": 1,
                },
                "clip": [0, 0, 640, 480],
            },
            {
                "id": "crop-image",
                "type": "image",
                "x": 24,
                "y": 80,
                "width": 160,
                "height": 100,
                "name": "Reference crop",
                "imageBase64": _data_url(IMAGE_A),
                "sourceResolution": {
                    "use_id": "dom:1:img",
                    "asset_id": "asset:sha256:source-a",
                    "identity": {
                        "selected": "verified-source",
                        "original": True,
                        "replaceable": True,
                    },
                    "display": {
                        "selected": "screenshot-crop",
                        "original": False,
                        "reference_only": True,
                        "generated": False,
                        "provenance": {
                            "payload_sha256": hashlib.sha256(IMAGE_A).hexdigest()
                        },
                    },
                },
                "displayPayload": {
                    "kind": "screenshot-crop",
                    "payload_sha256": hashlib.sha256(IMAGE_A).hexdigest(),
                    "original": False,
                    "reference_only": True,
                    "generated": False,
                },
            },
            {
                "id": "generated-icon",
                "type": "image",
                "x": 220,
                "y": 80,
                "width": 24,
                "height": 24,
                "name": "Generated icon",
                "imageBase64": _data_url(IMAGE_B),
                "sourceResolution": {
                    "use_id": "dom:2:icon",
                    "asset_id": "asset:unverified:generated-b",
                    "identity": {
                        "selected": "unavailable",
                        "original": False,
                        "replaceable": False,
                    },
                    "display": {
                        "selected": "generated-approximation",
                        "original": False,
                        "reference_only": False,
                        "generated": True,
                        "provenance": {
                            "payload_sha256": hashlib.sha256(IMAGE_B).hexdigest()
                        },
                    },
                },
                "displayPayload": {
                    "kind": "generated-approximation",
                    "payload_sha256": hashlib.sha256(IMAGE_B).hexdigest(),
                    "original": False,
                    "reference_only": False,
                    "generated": True,
                },
            },
        ],
    }


class AxureRoutePlannerTests(unittest.TestCase):
    def test_route_binds_every_ir_node_to_its_source_node(self) -> None:
        design = _design()
        ir = build_output_ir(design, source_kind="dom")
        original = copy.deepcopy(design)

        route = plan_axure_route(design, source_kind="dom", ir=ir)

        self.assertEqual(design, original)
        self.assertEqual(len(route["node_bindings"]), len(ir["frames"][0]["nodes"]))
        self.assertEqual(
            [row["source_node_id"] for row in route["node_bindings"]],
            ["title", "crop-image", "generated-icon"],
        )
        self.assertEqual(
            [row["source_index"] for row in route["node_bindings"]],
            [0, 1, 2],
        )
        self.assertEqual(route["document_id"], ir["document_id"])

    def test_route_fails_when_an_ir_source_node_is_missing(self) -> None:
        design = _design()
        ir = build_output_ir(design, source_kind="dom")
        ir["frames"][0]["nodes"][1]["source_node_id"] = "missing-image"

        with self.assertRaisesRegex(ValueError, "missing-image"):
            plan_axure_route(design, source_kind="dom", ir=ir)

    def test_route_preserves_generated_and_reference_only_asset_status(self) -> None:
        design = _design()
        ir = build_output_ir(design, source_kind="dom")

        route = plan_axure_route(design, source_kind="dom", ir=ir)

        bindings = {row["source_node_id"]: row for row in route["asset_bindings"]}
        self.assertEqual(len(bindings), 2)
        self.assertEqual(
            bindings["crop-image"]["actual_payload_sha256"],
            hashlib.sha256(IMAGE_A).hexdigest(),
        )
        self.assertEqual(
            bindings["generated-icon"]["actual_payload_sha256"],
            hashlib.sha256(IMAGE_B).hexdigest(),
        )
        self.assertTrue(bindings["crop-image"]["reference_only"])
        self.assertTrue(bindings["crop-image"]["original"])
        self.assertFalse(bindings["crop-image"]["display_original"])
        self.assertTrue(bindings["generated-icon"]["generated"])
        self.assertFalse(bindings["generated-icon"]["display_original"])

    def test_route_reports_axure_degradations_without_transferring_figma_claims(
        self,
    ) -> None:
        route = plan_axure_route(_design(), source_kind="dom")

        projection = route["projection"]
        degraded = {row["feature"]: row for row in route["degradations"]}
        self.assertFalse(projection["acceptance"]["figma_evidence_transferable"])
        self.assertFalse(projection["can_claim_complete"])
        self.assertIn("clip", degraded)
        self.assertIn("letter-spacing", degraded)
        self.assertEqual(
            degraded["letter-spacing"]["fallback"],
            "linebreak-workaround",
        )
        self.assertEqual(
            degraded["letter-spacing"]["source_node_ids"],
            ["title"],
        )

    def test_image_route_preserves_reference_and_creation_only_image_semantics(
        self,
    ) -> None:
        design = _design()
        reference_id = "image-sha256:" + hashlib.sha256(IMAGE_A).hexdigest()
        design["_meta"] = {
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
        }
        design["elements"][1]["imageMVP"] = {
            "displayReplaceable": True,
            "reference_only": True,
            "originalAssetClaimed": False,
        }
        reference = {
            "reference_id": reference_id,
            "input": {
                "sha256": hashlib.sha256(IMAGE_A).hexdigest(),
                "size": [640, 480],
            },
            "state": design["_meta"]["imageMVP"]["state"],
        }
        ir = build_output_ir(design, source_kind="image", reference=reference)

        route = plan_axure_route(
            design,
            source_kind="image",
            reference=reference,
            ir=ir,
        )

        self.assertEqual(route["source_reference"]["reference_id"], reference_id)
        self.assertEqual(
            route["source_reference"]["sha256"], reference["input"]["sha256"]
        )
        self.assertEqual(route["source_reference"]["state"]["mode"], "faithful")
        self.assertEqual(len(route["node_bindings"]), 3)
        self.assertEqual(len(route["asset_bindings"]), 2)
        crop = next(
            row
            for row in route["asset_bindings"]
            if row["source_node_id"] == "crop-image"
        )
        self.assertTrue(crop["reference_only"])
        self.assertFalse(crop["display_original"])
        replacement = next(
            row
            for row in route["degradations"]
            if row["feature"] == "runtime-image-replace"
        )
        self.assertEqual(replacement["fallback"], "creation-only-image-box")
        self.assertEqual(replacement["source_node_ids"], ["crop-image"])

    def test_non_image_asset_uses_remain_provenance_without_rendering(self) -> None:
        design = _design()
        design["elements"].append(
            {
                "id": "css-background",
                "type": "button",
                "x": 300,
                "y": 120,
                "width": 144,
                "height": 81,
                "text": "",
                "assetIdentity": {
                    "asset_record": {
                        "asset_id": "asset:ref:css-background",
                        "source_identity": {
                            "status": "reference-only",
                            "source_kind": "remote-url",
                            "payload_sha256": None,
                        },
                        "display_payload": {
                            "kind": "none",
                            "status": "missing",
                            "original": False,
                            "reference_only": True,
                            "payload_sha256": None,
                        },
                        "replacement": {"allowed": False},
                        "use": {"use_id": "dom:9:bg-0"},
                    }
                },
            }
        )
        ir = build_output_ir(design, source_kind="dom")

        route = plan_axure_route(design, source_kind="dom", ir=ir)

        rows = {row["source_node_id"]: row for row in route["asset_bindings"]}
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows["css-background"]["render_status"], "not-rendered")
        self.assertEqual(
            rows["css-background"]["reason"],
            "non-image-node-without-display-payload",
        )
        self.assertTrue(rows["css-background"]["reference_only"])
        self.assertFalse(rows["css-background"]["display_original"])
        self.assertEqual(route["asset_render_summary"]["rendered"], 2)
        self.assertEqual(route["asset_render_summary"]["not_rendered"], 1)

    def test_non_image_node_with_image_payload_binds_as_rendered(self) -> None:
        design = _design()
        design["elements"].append(
            {
                "id": "background-payload",
                "type": "container",
                "x": 300,
                "y": 120,
                "width": 120,
                "height": 50,
                "text": "",
                "imageBase64": "data:image/png;base64,"
                + base64.b64encode(IMAGE_B).decode("ascii"),
            }
        )
        ir = build_output_ir(design, source_kind="dom")

        route = plan_axure_route(design, source_kind="dom", ir=ir)

        row = next(
            row
            for row in route["asset_bindings"]
            if row["source_node_id"] == "background-payload"
        )
        self.assertEqual(row["render_status"], "rendered")
        self.assertEqual(
            row["actual_payload_sha256"],
            hashlib.sha256(IMAGE_B).hexdigest(),
        )
        self.assertEqual(route["asset_render_summary"]["not_rendered"], 0)


if __name__ == "__main__":
    unittest.main()
