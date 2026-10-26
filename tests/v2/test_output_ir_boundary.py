from __future__ import annotations

import copy
import unittest

from src.app.services.contracts import (
    OUTPUT_IR_SCHEMA_VERSION,
    build_output_ir,
    output_capabilities,
    project_for_output,
    validate_output_ir,
)
from src.app.services.rendering.axure_adapter import AxureRPAdapter
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter


def _reference() -> dict:
    return {
        "reference_id": "image-sha256:" + "a" * 64,
        "input": {"sha256": "a" * 64, "size": [320, 180]},
        "state": {"mode": "faithful"},
    }


def _design() -> dict:
    return {
        "name": "Shared IR sample",
        "canvas": {
            "width": 320,
            "height": 180,
            "background": "#f2f5f8",
        },
        "elements": [
            {
                "id": "title",
                "type": "text",
                "x": 20,
                "y": 12,
                "width": 140,
                "height": 24,
                "text": "Shared IR",
                "source": "grounding",
                "style": {
                    "textColor": "#172033",
                    "fontSize": 16,
                    "letterSpacing": 1,
                },
                "clip": [10, 0, 300, 100],
            },
            {
                "id": "photo",
                "type": "image",
                "x": 200,
                "y": 40,
                "width": 80,
                "height": 60,
                "imageBase64": "aW1hZ2U=",
                "sourceResolution": {
                    "asset_id": "asset:unverified:example",
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
                    },
                },
                "displayPayload": {
                    "kind": "screenshot-crop",
                    "payload_sha256": "b" * 64,
                },
            },
        ],
        "_meta": {
            "imageMVP": {
                "flow": {
                    "value": "fixed-coordinate",
                    "status": "candidate",
                }
            }
        },
    }


class OutputIRProjectionTests(unittest.TestCase):
    def test_single_page_design_projects_neutral_nodes_and_assets(self) -> None:
        ir = build_output_ir(
            _design(),
            source_kind="image",
            reference=_reference(),
        )

        self.assertEqual(ir["schema_version"], OUTPUT_IR_SCHEMA_VERSION)
        self.assertTrue(ir["output_neutral"])
        self.assertEqual(ir["source"]["input_kind"], "image")
        self.assertEqual(ir["source"]["reference_id"], _reference()["reference_id"])
        self.assertEqual(len(ir["frames"]), 1)
        self.assertEqual(ir["frames"][0]["canvas"]["width"], 320)
        self.assertEqual(len(ir["frames"][0]["nodes"]), 2)
        title = next(
            node
            for node in ir["frames"][0]["nodes"]
            if node["source_node_id"] == "title"
        )
        self.assertEqual(title["kind"], "text")
        self.assertEqual(
            title["geometry"], {"x": 20.0, "y": 12.0, "width": 140.0, "height": 24.0}
        )
        self.assertEqual(title["content"]["text"], "Shared IR")
        self.assertEqual(title["layout"]["mode"], "fixed-coordinate")
        self.assertEqual(title["layout"]["status"], "candidate")
        self.assertEqual(title["provenance"]["source"], "grounding")
        self.assertEqual(len(ir["assets"]), 1)
        self.assertFalse(ir["assets"][0]["original"])
        self.assertFalse(ir["assets"][0]["display_original"])
        self.assertTrue(ir["assets"][0]["reference_only"])
        self.assertIn("native-text", ir["required_features"])
        self.assertIn("image-fill", ir["required_features"])
        self.assertIn("clip", ir["required_features"])
        self.assertIn("letter-spacing", ir["required_features"])

    def test_document_identity_is_deterministic_for_same_design(self) -> None:
        first = build_output_ir(
            _design(),
            source_kind="image",
            reference=_reference(),
        )
        second = build_output_ir(
            _design(),
            source_kind="image",
            reference=_reference(),
        )

        self.assertEqual(first, second)
        self.assertEqual(first["document_id"], second["document_id"])
        ids = [node["node_id"] for node in first["frames"][0]["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_multi_page_design_keeps_frame_order_and_shared_assets(self) -> None:
        design = {
            "pages": [
                {
                    "name": "One",
                    "canvas": {"width": 320, "height": 180},
                    "elements": _design()["elements"],
                },
                {
                    "name": "Two",
                    "canvas": {"width": 320, "height": 180},
                    "elements": [_design()["elements"][0]],
                },
            ]
        }

        ir = build_output_ir(design, source_kind="dom")

        self.assertEqual([frame["name"] for frame in ir["frames"]], ["One", "Two"])
        self.assertIn("multi-page", ir["required_features"])
        self.assertEqual(len(ir["assets"]), 1)
        self.assertEqual(
            len({node["node_id"] for frame in ir["frames"] for node in frame["nodes"]}),
            3,
        )

    def test_payload_only_image_fill_keeps_unverified_provenance(self) -> None:
        design = _design()
        design["elements"].append(
            {
                "id": "background-payload",
                "type": "container",
                "x": 10,
                "y": 110,
                "width": 120,
                "height": 50,
                "imageBase64": "iVBORw0KGgo=",
            }
        )

        ir = build_output_ir(design, source_kind="dom")

        node = next(
            node
            for node in ir["frames"][0]["nodes"]
            if node["source_node_id"] == "background-payload"
        )
        self.assertIn("image-fill", node["required_features"])
        payload_asset = next(
            asset for asset in ir["assets"] if asset["display"] == "unverified-payload"
        )
        self.assertEqual(payload_asset["source_status"], "unavailable")
        self.assertFalse(payload_asset["original"])
        self.assertFalse(payload_asset["display_original"])
        self.assertTrue(payload_asset["reference_only"])
        self.assertFalse(payload_asset["replaceable"])


class OutputIRValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ir = build_output_ir(
            _design(),
            source_kind="image",
            reference=_reference(),
        )

    def test_duplicate_node_ids_fail_closed(self) -> None:
        broken = copy.deepcopy(self.ir)
        broken["frames"][0]["nodes"][1]["node_id"] = broken["frames"][0]["nodes"][0][
            "node_id"
        ]

        codes = {issue["code"] for issue in validate_output_ir(broken)}

        self.assertIn("duplicate-node-id", codes)

    def test_reference_only_asset_cannot_be_marked_original(self) -> None:
        broken = copy.deepcopy(self.ir)
        broken["assets"][0]["display_original"] = True

        codes = {issue["code"] for issue in validate_output_ir(broken)}

        self.assertIn("reference-only-cannot-be-original", codes)

    def test_verified_identity_can_coexist_with_reference_only_display(self) -> None:
        design = _design()
        design["elements"][1]["sourceResolution"]["identity"] = {
            "selected": "verified-source",
            "original": True,
            "replaceable": True,
        }
        ir = build_output_ir(design, source_kind="dom")

        codes = {issue["code"] for issue in validate_output_ir(ir)}

        self.assertTrue(ir["assets"][0]["original"])
        self.assertTrue(ir["assets"][0]["reference_only"])
        self.assertFalse(ir["assets"][0]["display_original"])
        self.assertNotIn("reference-only-cannot-be-original", codes)

    def test_verified_flow_requires_explicit_evidence(self) -> None:
        broken = copy.deepcopy(self.ir)
        broken["frames"][0]["nodes"][0]["layout"]["status"] = "verified"

        codes = {issue["code"] for issue in validate_output_ir(broken)}

        self.assertIn("verified-flow-without-evidence", codes)

    def test_invalid_geometry_is_rejected(self) -> None:
        broken = copy.deepcopy(self.ir)
        broken["frames"][0]["nodes"][0]["geometry"]["width"] = -1

        codes = {issue["code"] for issue in validate_output_ir(broken)}

        self.assertIn("invalid-geometry", codes)


class OutputCapabilityTests(unittest.TestCase):
    def test_capability_matrix_is_target_specific(self) -> None:
        figma = output_capabilities("figma")
        axure = output_capabilities("axure")

        self.assertTrue(figma["features"]["clip"])
        self.assertFalse(figma["features"]["multi-page"])
        self.assertTrue(figma["features"]["auto-layout"])
        self.assertTrue(figma["features"]["runtime-image-replace"])
        self.assertTrue(axure["features"]["multi-page"])
        self.assertFalse(axure["features"]["clip"])
        self.assertFalse(axure["features"]["auto-layout"])
        self.assertFalse(axure["features"]["runtime-image-replace"])
        self.assertFalse(axure["acceptance"]["figma_evidence_transferable"])
        self.assertFalse(axure["acceptance"]["image_figma_evidence_transferable"])

    def test_capability_matrix_matches_adapter_class_boundaries(self) -> None:
        figma = output_capabilities("figma")["features"]
        axure = output_capabilities("axure")["features"]

        self.assertEqual(figma["clip"], FigmaBridgeAdapter.supports_clip_frames)
        self.assertEqual(figma["multi-page"], FigmaBridgeAdapter.supports_pages)
        self.assertIn("set_autolayout", FigmaBridgeAdapter.__dict__)
        self.assertTrue(hasattr(FigmaBridgeAdapter, "replace_image_fill"))
        self.assertEqual(axure["clip"], AxureRPAdapter.supports_clip_frames)
        self.assertEqual(axure["multi-page"], AxureRPAdapter.supports_pages)
        self.assertNotIn("set_autolayout", AxureRPAdapter.__dict__)
        self.assertFalse(hasattr(AxureRPAdapter, "replace_image_fill"))
        self.assertNotIn("letterSpacing", AxureRPAdapter.SUPPORTED_FIELDS)

    def test_projection_preserves_supported_and_reports_degraded_features(self) -> None:
        design = {
            "pages": [
                _design(),
                {
                    "name": "Second",
                    "canvas": {"width": 320, "height": 180},
                    "elements": [_design()["elements"][0]],
                },
            ]
        }
        ir = build_output_ir(design, source_kind="image", reference=_reference())

        axure = project_for_output(ir, "axure")

        self.assertEqual(axure["target"], "axure")
        self.assertIn("multi-page", axure["supported_features"])
        self.assertIn("native-text", axure["supported_features"])
        self.assertIn("image-fill", axure["supported_features"])
        self.assertIn("clip", axure["unsupported_features"])
        self.assertIn("letter-spacing", axure["unsupported_features"])
        self.assertIn("clip->flatten-or-reference-crop", axure["degraded"])
        self.assertIn("letter-spacing->linebreak-workaround", axure["degraded"])
        self.assertFalse(axure["can_claim_complete"])
        self.assertEqual(
            axure["acceptance_scope"],
            "axure-specific-required",
        )

    def test_projection_rejects_unknown_target(self) -> None:
        ir = build_output_ir(_design(), source_kind="image")

        with self.assertRaises(ValueError):
            project_for_output(ir, "unknown")


if __name__ == "__main__":
    unittest.main()
