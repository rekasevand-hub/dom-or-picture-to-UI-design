from __future__ import annotations

import base64
import unittest

from src.app.services.rendering.figma_acceptance import (
    FourDimensionDecision,
    accept_output,
    evaluate_figma_acceptance,
)
from src.app.services.rendering.text_wrap import TextAcceptance


def _design_with_text() -> dict:
    return {
        "canvas": {
            "width": 300,
            "height": 200,
            "background": "#ffffff",
        },
        "elements": [
            {
                "id": "title",
                "type": "text",
                "text": "Title",
                "x": 10,
                "y": 20,
                "width": 120,
                "height": 30,
                "style": {
                    "fontFamily": "Arial",
                    "fontWeight": "bold",
                    "fontSize": 20,
                },
            },
            {
                "id": "card",
                "type": "container",
                "x": 10,
                "y": 60,
                "width": 100,
                "height": 50,
                "style": {"fillColor": "#eeeeee"},
            },
        ],
    }


def _readback_with_text(
    *,
    text: str = "Title",
    family: str = "Arial",
    x: float = 10,
) -> dict:
    return {
        "id": "1:1",
        "name": "Screen",
        "type": "FRAME",
        "x": 0,
        "y": 0,
        "width": 300,
        "height": 200,
        "absolute": {"x": 0, "y": 0, "width": 300, "height": 200},
        "children": [
            {
                "id": "1:2",
                "name": "Title",
                "type": "TEXT",
                "x": x,
                "y": 20,
                "width": 42,
                "height": 24,
                "absolute": {
                    "x": x,
                    "y": 20,
                    "width": 42,
                    "height": 24,
                },
                "characters": text,
                "fontName": {"family": family, "style": "Bold"},
                "fontSize": 20,
            },
            {
                "id": "1:3",
                "name": "Card",
                "type": "FRAME",
                "x": 10,
                "y": 60,
                "width": 100,
                "height": 50,
                "absolute": {
                    "x": 10,
                    "y": 60,
                    "width": 100,
                    "height": 50,
                },
            },
        ],
    }


def _passing_edit_probe() -> dict:
    return {
        "status": "pass",
        "node_type_preserved": True,
        "characters_updated": True,
        "font_preserved": True,
        "geometry_updated": True,
        "restored": True,
    }


def _visual_pass() -> tuple[dict, dict]:
    metrics = {
        "mean": 0.1,
        "ink_mean": 1.0,
        "over30_pct": 0.0,
        "bad_pixel_count": 0,
        "size_match": True,
    }
    policy = {
        "policy_id": "figma-test-visual/1.0",
        "max_mean": 1.0,
        "max_ink_mean": 10.0,
        "max_over30_pct": 1.0,
        "max_bad_pixel_count": 100,
        "require_size_match": True,
    }
    return metrics, policy


class FigmaAcceptanceTests(unittest.TestCase):
    def test_visual_pass_cannot_offset_font_failure(self) -> None:
        metrics, policy = _visual_pass()
        decision = accept_output(
            {
                "design": _design_with_text(),
                "truth": {
                    "expected_texts": ["Title"],
                    "expected_asset_count": 0,
                    "native_text_required": True,
                },
                "readback_tree": _readback_with_text(family="Inter"),
                "visual_metrics": metrics,
                "visual_policy": policy,
                "edit_probe": _passing_edit_probe(),
            },
            "fixed-authored-figma-readback/1.0",
        )

        self.assertIsInstance(decision, FourDimensionDecision)
        self.assertEqual(decision.dimensions["visual"]["status"], "pass")
        self.assertEqual(decision.dimensions["edit"]["status"], "fail")
        self.assertEqual(decision.status, "blocked-fail")
        self.assertFalse(decision.export_allowed)
        self.assertIn("edit", decision.blocking_dimensions)

    def test_text_components_are_reported_independently(self) -> None:
        metrics, policy = _visual_pass()
        decision = accept_output(
            {
                "design": _design_with_text(),
                "truth": {
                    "expected_texts": ["Title"],
                    "expected_asset_count": 0,
                    "native_text_required": True,
                },
                "readback_tree": _readback_with_text(),
                "visual_metrics": metrics,
                "visual_policy": policy,
                "edit_probe": _passing_edit_probe(),
                "text_components": TextAcceptance(
                    content="pass",
                    linebreak="partial",
                    box="pass",
                    baseline="pass",
                    glyph="not-evaluated",
                ),
            },
            "fixed-authored-figma-readback/1.0",
        )

        self.assertEqual(decision.text["content"], "pass")
        self.assertEqual(decision.text["linebreak"], "partial")
        self.assertEqual(decision.text["box"], "pass")
        self.assertEqual(decision.text["baseline"], "pass")
        self.assertEqual(decision.text["glyph"], "not-evaluated")
        self.assertEqual(decision.text["overall"], "blocked-partial")
        self.assertEqual(decision.status, "blocked-partial")

    def test_remote_asset_reference_blocks_complete_output(self) -> None:
        metrics, policy = _visual_pass()
        design = {
            "canvas": {"width": 300, "height": 200, "background": "#ffffff"},
            "elements": [
                {
                    "id": "hero",
                    "type": "image",
                    "x": 10,
                    "y": 10,
                    "width": 120,
                    "height": 80,
                    "assetIdentity": {
                        "source_url": "https://cdn.example/hero.png",
                        "status": "reference-only",
                    },
                }
            ],
        }
        decision = accept_output(
            {
                "design": design,
                "truth": {
                    "expected_texts": [],
                    "expected_asset_count": 1,
                    "native_text_required": False,
                },
                "readback_tree": {
                    "id": "1:1",
                    "type": "FRAME",
                    "x": 0,
                    "y": 0,
                    "width": 300,
                    "height": 200,
                    "absolute": {
                        "x": 0,
                        "y": 0,
                        "width": 300,
                        "height": 200,
                    },
                    "children": [],
                },
                "visual_metrics": metrics,
                "visual_policy": policy,
            },
            "fixed-authored-figma-readback/1.0",
        )

        self.assertEqual(decision.dimensions["visual"]["status"], "pass")
        self.assertEqual(decision.dimensions["asset"]["status"], "fail")
        self.assertEqual(decision.status, "blocked-fail")
        self.assertFalse(decision.export_allowed)
        self.assertEqual(
            decision.assets["identities"][0]["status"],
            "reference-only",
        )

    def test_italic_request_rejects_upright_figma_face(self) -> None:
        design = _design_with_text()
        design["elements"][0]["style"]["fontStyle"] = "italic"
        metrics, policy = _visual_pass()

        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            _readback_with_text(),
            visual_metrics=metrics,
            visual_policy=policy,
            edit_probe=_passing_edit_probe(),
        )

        row = result["checks"]["font"]["rows"][0]
        self.assertEqual(row["requested_font_style"], "italic")
        self.assertFalse(row["style_passed"])
        self.assertEqual(result["dimensions"]["edit"]["status"], "fail")

    def test_structure_uses_real_readback_text_and_geometry(self) -> None:
        result = evaluate_figma_acceptance(
            _design_with_text(),
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            _readback_with_text(),
            edit_probe=_passing_edit_probe(),
        )

        self.assertEqual(result["checks"]["content"]["status"], "pass")
        self.assertEqual(result["checks"]["geometry"]["status"], "pass")
        self.assertEqual(result["dimensions"]["structure"]["status"], "pass")
        self.assertEqual(result["checks"]["font"]["status"], "pass")
        self.assertEqual(result["checks"]["native_text"]["status"], "pass")
        self.assertEqual(result["dimensions"]["edit"]["status"], "pass")
        self.assertEqual(result["checks"]["assets"]["status"], "not-required")
        self.assertEqual(result["dimensions"]["visual"]["status"], "not-evaluated")
        self.assertFalse(result["acceptance_passed"])
        self.assertEqual(result["figma_attempted_count"], 1)
        self.assertEqual(result["figma_evaluated_count"], 0)
        self.assertFalse(result["composite_score_used"])

    def test_solid_container_can_readback_as_rectangle(self) -> None:
        readback = _readback_with_text()
        readback["children"][1]["type"] = "RECTANGLE"
        readback["children"][1]["fills"] = [
            {
                "type": "SOLID",
                "color": "#eeeeee",
                "visible": True,
            }
        ]

        result = evaluate_figma_acceptance(
            _design_with_text(),
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            readback,
            edit_probe=_passing_edit_probe(),
        )

        self.assertEqual(result["checks"]["geometry"]["status"], "pass")
        self.assertEqual(result["dimensions"]["structure"]["status"], "pass")

    def test_missing_text_blocks_structure_independently(self) -> None:
        result = evaluate_figma_acceptance(
            _design_with_text(),
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            _readback_with_text(text="Different"),
        )

        self.assertEqual(result["checks"]["content"]["status"], "fail")
        self.assertEqual(result["checks"]["geometry"]["status"], "fail")
        self.assertEqual(result["dimensions"]["structure"]["status"], "fail")

    def test_reordered_semantic_nodes_block_structure(self) -> None:
        design = _design_with_text()
        design["elements"][1]["y"] = 20
        readback = _readback_with_text()
        readback["children"][1]["y"] = 20
        readback["children"][1]["absolute"]["y"] = 20
        readback["children"] = [
            readback["children"][1],
            readback["children"][0],
        ]

        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            readback,
        )

        self.assertEqual(result["checks"]["geometry"]["status"], "fail")
        self.assertEqual(
            result["checks"]["geometry"]["order"]["status"],
            "fail",
        )
        self.assertEqual(result["dimensions"]["structure"]["status"], "fail")

    def test_hidden_semantic_node_blocks_structure(self) -> None:
        readback = _readback_with_text()
        readback["children"][0]["visible"] = False

        result = evaluate_figma_acceptance(
            _design_with_text(),
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            readback,
        )

        self.assertEqual(result["checks"]["geometry"]["status"], "fail")
        self.assertEqual(
            result["checks"]["geometry"]["visibility"]["status"],
            "fail",
        )

    def test_generic_font_fallback_blocks_edit_dimension(self) -> None:
        design = _design_with_text()
        design["elements"][0]["style"]["fontFamily"] = "sans-serif"
        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            _readback_with_text(family="Inter"),
            edit_probe=_passing_edit_probe(),
        )

        self.assertEqual(result["checks"]["font"]["status"], "fail")
        self.assertEqual(
            result["checks"]["font"]["rows"][0]["reason"],
            "generic-family-resolved-to-concrete-font",
        )
        self.assertEqual(result["dimensions"]["edit"]["status"], "fail")

    def test_font_rows_report_text_bbox_deltas_per_node(self) -> None:
        result = evaluate_figma_acceptance(
            _design_with_text(),
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            _readback_with_text(),
            edit_probe=_passing_edit_probe(),
        )

        row = result["checks"]["font"]["rows"][0]
        self.assertEqual(
            row["bbox_delta_px"],
            {"x": 0.0, "y": 0.0, "width": -78.0, "height": -6.0},
        )
        self.assertEqual(row["bottom_delta_px"], -6.0)
        self.assertEqual(
            row["metric_scope"],
            "readback-bbox-not-font-engine-metrics",
        )

    def test_font_rows_preserve_browser_platform_provenance(self) -> None:
        design = _design_with_text()
        design["elements"][0]["style"].update(
            {
                "fontFamily": "Microsoft YaHei",
                "fontFamilyRequested": "sans-serif",
                "fontFamilyResolution": "browser-platform-font",
                "platformFonts": [
                    {
                        "familyName": "Microsoft YaHei",
                        "glyphCount": 5,
                    }
                ],
            }
        )
        readback = _readback_with_text()
        readback["children"][0]["fontName"]["family"] = "Microsoft YaHei"

        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            readback,
            edit_probe=_passing_edit_probe(),
        )

        row = result["checks"]["font"]["rows"][0]
        self.assertEqual(row["requested_family"], "sans-serif")
        self.assertEqual(row["resolved_family"], "Microsoft YaHei")
        self.assertEqual(
            row["font_resolution"],
            "browser-platform-font",
        )
        self.assertEqual(
            row["platform_fonts"][0]["familyName"],
            "Microsoft YaHei",
        )

    def test_font_weight_mismatch_is_not_hidden_by_regular_style(self) -> None:
        design = _design_with_text()
        design["elements"][0]["style"]["fontWeight"] = 500
        readback = _readback_with_text()
        readback["children"][0]["fontName"]["style"] = "Regular"

        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            readback,
            edit_probe=_passing_edit_probe(),
        )

        row = result["checks"]["font"]["rows"][0]
        self.assertFalse(row["weight_passed"])
        self.assertEqual(result["checks"]["font"]["status"], "fail")

    def test_compact_semibold_style_matches_requested_weight(self) -> None:
        design = _design_with_text()
        design["elements"][0]["style"]["fontWeight"] = 600
        readback = _readback_with_text()
        readback["children"][0]["fontName"]["style"] = "SemiBold"

        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            readback,
            edit_probe=_passing_edit_probe(),
        )

        self.assertTrue(result["checks"]["font"]["rows"][0]["weight_passed"])

    def test_italic_style_infers_upright_weight(self) -> None:
        design = _design_with_text()
        design["elements"][0]["style"]["fontWeight"] = "normal"
        design["elements"][0]["style"]["fontStyle"] = "italic"
        readback = _readback_with_text()
        readback["children"][0]["fontName"]["style"] = "Italic"

        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            readback,
            edit_probe=_passing_edit_probe(),
        )

        row = result["checks"]["font"]["rows"][0]
        self.assertTrue(row["weight_passed"])
        self.assertTrue(row["style_passed"])

    def test_semilight_named_instance_matches_variable_weight(self) -> None:
        design = _design_with_text()
        design["elements"][0]["style"]["fontWeight"] = "normal"
        design["elements"][0]["style"]["fontWeightValue"] = 350
        readback = _readback_with_text()
        readback["children"][0]["fontName"]["style"] = "Semilight Text"

        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            readback,
            edit_probe=_passing_edit_probe(),
        )

        row = result["checks"]["font"]["rows"][0]
        self.assertEqual(row["requested_weight"], "350")
        self.assertTrue(row["weight_passed"])

    def test_missing_expected_font_size_fails_closed(self) -> None:
        design = _design_with_text()
        design["elements"][0]["style"].pop("fontSize")

        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            _readback_with_text(),
            edit_probe=_passing_edit_probe(),
        )

        row = result["checks"]["font"]["rows"][0]
        self.assertFalse(row["size_passed"])
        self.assertEqual(result["checks"]["font"]["status"], "fail")

    def test_native_edit_probe_requires_update_geometry_and_restore(self) -> None:
        design = _design_with_text()
        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            _readback_with_text(),
            edit_probe={
                "status": "pass",
                "node_type_preserved": True,
                "characters_updated": True,
                "font_preserved": True,
                "geometry_updated": False,
                "restored": True,
            },
        )

        self.assertEqual(result["checks"]["native_text"]["status"], "fail")
        self.assertEqual(
            result["checks"]["native_text"]["failed_checks"],
            ["geometry_updated"],
        )

    def test_truthy_probe_objects_do_not_count_as_boolean_evidence(self) -> None:
        probe = _passing_edit_probe()
        probe["restored"] = {"characters": "not a boolean"}
        result = evaluate_figma_acceptance(
            _design_with_text(),
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            _readback_with_text(),
            edit_probe=probe,
        )

        self.assertEqual(result["checks"]["native_text"]["status"], "fail")
        self.assertEqual(
            result["checks"]["native_text"]["failed_checks"],
            ["restored"],
        )

    def test_acceptance_requires_visual_gate_and_all_edit_evidence(self) -> None:
        metrics, policy = _visual_pass()
        result = evaluate_figma_acceptance(
            _design_with_text(),
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            _readback_with_text(),
            visual_metrics=metrics,
            visual_policy=policy,
            edit_probe=_passing_edit_probe(),
        )

        self.assertEqual(result["dimensions"]["visual"]["status"], "pass")
        self.assertEqual(result["acceptance_status"], "pass")
        self.assertTrue(result["acceptance_passed"])
        self.assertEqual(result["figma_evaluated_count"], 1)

    def test_image_replacement_probe_is_independent_asset_evidence(self) -> None:
        source_bytes = b"source-bytes"
        source_b64 = base64.b64encode(source_bytes).decode("ascii")
        design = {
            "canvas": {"width": 200, "height": 120, "background": "#ffffff"},
            "elements": [
                {
                    "id": "image",
                    "type": "image",
                    "x": 10,
                    "y": 20,
                    "width": 100,
                    "height": 60,
                    "imageBase64": source_b64,
                }
            ],
        }
        readback = {
            "id": "2:1",
            "name": "Screen",
            "type": "FRAME",
            "x": 0,
            "y": 0,
            "width": 200,
            "height": 120,
            "absolute": {"x": 0, "y": 0, "width": 200, "height": 120},
            "children": [
                {
                    "id": "2:2",
                    "name": "Image",
                    "type": "RECTANGLE",
                    "x": 10,
                    "y": 20,
                    "width": 100,
                    "height": 60,
                    "absolute": {
                        "x": 10,
                        "y": 20,
                        "width": 100,
                        "height": 60,
                    },
                    "fills": [
                        {
                            "type": "IMAGE",
                            "imageHash": "replacement",
                            "scaleMode": "FILL",
                            "visible": True,
                        }
                    ],
                }
            ],
        }
        metrics, policy = _visual_pass()
        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": [],
                "expected_asset_count": 1,
                "native_text_required": False,
            },
            readback,
            visual_metrics=metrics,
            visual_policy=policy,
            image_report={
                "fills": [
                    {
                        "nodeId": "2:2",
                        "fillIndex": 0,
                        "imageHash": "replacement",
                        "byteBase64": source_b64,
                    }
                ],
            },
            asset_probe={
                "status": "pass",
                "node_type_preserved": True,
                "image_hash_changed": True,
                "scale_mode_preserved": True,
                "restored": True,
            },
        )

        self.assertEqual(result["checks"]["assets"]["status"], "pass")
        self.assertTrue(result["checks"]["assets"]["rows"][0]["payload_sha256_passed"])
        self.assertEqual(result["dimensions"]["asset"]["status"], "pass")
        self.assertEqual(result["acceptance_status"], "pass")

    def test_declared_partial_asset_stays_partial_but_is_evaluated(self) -> None:
        source_b64 = base64.b64encode(b"source-bytes").decode("ascii")
        design = {
            "canvas": {"width": 200, "height": 120, "background": "#ffffff"},
            "elements": [
                {
                    "id": "image",
                    "type": "image",
                    "x": 10,
                    "y": 20,
                    "width": 100,
                    "height": 60,
                    "imageBase64": source_b64,
                }
            ],
        }
        readback = {
            "id": "2:1",
            "name": "Screen",
            "type": "FRAME",
            "x": 0,
            "y": 0,
            "width": 200,
            "height": 120,
            "absolute": {"x": 0, "y": 0, "width": 200, "height": 120},
            "children": [
                {
                    "id": "2:2",
                    "name": "Image",
                    "type": "RECTANGLE",
                    "x": 10,
                    "y": 20,
                    "width": 100,
                    "height": 60,
                    "absolute": {
                        "x": 10,
                        "y": 20,
                        "width": 100,
                        "height": 60,
                    },
                    "fills": [
                        {
                            "type": "IMAGE",
                            "imageHash": "available",
                            "scaleMode": "FILL",
                            "visible": True,
                        }
                    ],
                }
            ],
        }
        metrics, policy = _visual_pass()
        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": [],
                "expected_asset_count": 2,
                "minimum_asset_count": 1,
                "expected_output_status": "partial",
                "expected_limitations": ["missing-asset-bytes"],
                "native_text_required": False,
            },
            readback,
            visual_metrics=metrics,
            visual_policy=policy,
            image_report={
                "fills": [
                    {
                        "nodeId": "2:2",
                        "fillIndex": 0,
                        "imageHash": "available",
                        "byteBase64": source_b64,
                    }
                ],
            },
            asset_probe={
                "status": "pass",
                "node_type_preserved": True,
                "image_hash_changed": True,
                "scale_mode_preserved": True,
                "restored": True,
            },
        )

        self.assertEqual(result["checks"]["assets"]["structure_status"], "partial")
        self.assertEqual(result["dimensions"]["asset"]["status"], "partial")
        self.assertEqual(result["acceptance_status"], "partial")
        self.assertTrue(result["acceptance_passed"])
        self.assertEqual(result["figma_evaluated_count"], 1)

    def test_asset_payload_hash_mismatch_blocks_asset_dimension(self) -> None:
        source_b64 = base64.b64encode(b"source-bytes").decode("ascii")
        wrong_b64 = base64.b64encode(b"wrong-bytes").decode("ascii")
        design = {
            "canvas": {"width": 200, "height": 120, "background": "#ffffff"},
            "elements": [
                {
                    "id": "image",
                    "type": "image",
                    "x": 10,
                    "y": 20,
                    "width": 100,
                    "height": 60,
                    "imageBase64": source_b64,
                }
            ],
        }
        readback = {
            "id": "2:1",
            "name": "Screen",
            "type": "FRAME",
            "x": 0,
            "y": 0,
            "width": 200,
            "height": 120,
            "absolute": {"x": 0, "y": 0, "width": 200, "height": 120},
            "children": [
                {
                    "id": "2:2",
                    "name": "Image",
                    "type": "RECTANGLE",
                    "x": 10,
                    "y": 20,
                    "width": 100,
                    "height": 60,
                    "absolute": {
                        "x": 10,
                        "y": 20,
                        "width": 100,
                        "height": 60,
                    },
                    "fills": [
                        {
                            "type": "IMAGE",
                            "imageHash": "replacement",
                            "scaleMode": "FILL",
                            "visible": True,
                        }
                    ],
                }
            ],
        }
        metrics, policy = _visual_pass()
        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": [],
                "expected_asset_count": 1,
                "native_text_required": False,
            },
            readback,
            visual_metrics=metrics,
            visual_policy=policy,
            image_report={
                "fills": [
                    {
                        "nodeId": "2:2",
                        "fillIndex": 0,
                        "imageHash": "replacement",
                        "byteBase64": wrong_b64,
                    }
                ],
            },
            asset_probe={
                "status": "pass",
                "node_type_preserved": True,
                "image_hash_changed": True,
                "scale_mode_preserved": True,
                "restored": True,
            },
        )

        self.assertFalse(result["checks"]["assets"]["rows"][0]["payload_sha256_passed"])
        self.assertEqual(result["checks"]["assets"]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
