from __future__ import annotations

import base64
import hashlib
import unittest

from src.app.services.rendering.figma_acceptance import (
    FourDimensionDecision,
    _asset_acceptance,
    _evaluate_content,
    _evaluate_geometry,
    _evaluate_native_text,
    accept_output,
    evaluate_figma_acceptance,
)
from src.app.services.rendering.text_wrap import TextAcceptance
from src.app.services.structure.asset_fusion import fuse_asset_record


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

    def test_scoped_glyph_identity_is_nonblocking(self) -> None:
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
                    linebreak="pass",
                    box="pass",
                    baseline="pass",
                    glyph="not-required",
                ),
            },
            "fixed-authored-figma-readback/1.0",
        )

        self.assertEqual(decision.text["glyph"], "not-required")
        self.assertEqual(decision.text["overall"], "pass")
        self.assertEqual(decision.status, "pass")

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

    def test_explicit_asset_record_separates_crop_and_replaceability(self) -> None:
        display_b64 = base64.b64encode(b"screenshot-crop").decode("ascii")
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
                    "imageBase64": display_b64,
                    "assetIdentity": {
                        "asset_record": {
                            "source_identity": {
                                "status": "verified-original",
                                "payload_sha256": "a" * 64,
                                "natural_size": [100.0, 60.0],
                                "bytes_present": True,
                                "mime": "image/png",
                            },
                            "display_payload": {
                                "status": "available",
                                "kind": "screenshot-crop",
                                "payload_sha256": "b" * 64,
                                "original": False,
                                "reference_only": True,
                            },
                            "replacement": {
                                "allowed": True,
                                "mode": "source-bytes",
                                "figma_runtime": "not-evaluated",
                            },
                            "missing": {
                                "is_missing": False,
                                "outcome": "pass",
                            },
                        }
                    },
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
                            "imageHash": "image-1",
                            "scaleMode": "FILL",
                            "visible": True,
                        }
                    ],
                }
            ],
        }
        metrics, policy = _visual_pass()

        result = accept_output(
            {
                "design": design,
                "truth": {
                    "expected_texts": [],
                    "expected_asset_count": 1,
                    "native_text_required": False,
                },
                "readback_tree": readback,
                "visual_metrics": metrics,
                "visual_policy": policy,
                "image_report": {
                    "fills": [
                        {
                            "nodeId": "2:2",
                            "fillIndex": 0,
                            "imageHash": "image-1",
                            "byteBase64": display_b64,
                        }
                    ]
                },
                "asset_probe": {
                    "status": "pass",
                    "node_type_preserved": True,
                    "image_hash_changed": True,
                    "scale_mode_preserved": True,
                    "restored": True,
                },
            },
            "fixed-authored-figma-readback/1.0",
        )

        asset = result.dimensions["asset"]
        self.assertEqual(asset["status"], "pass")
        identity = result.assets["identities"][0]
        self.assertEqual(identity["source_status"], "verified-original")
        self.assertEqual(identity["display_payload_kind"], "screenshot-crop")
        self.assertFalse(identity["display_payload_original"])
        self.assertTrue(identity["replacement_allowed"])

    def test_generated_display_cannot_mask_asset_partial_status(self) -> None:
        display_b64 = base64.b64encode(b"generated-bytes").decode("ascii")
        record = {
            "asset_id": "asset:sha256:" + "a" * 64,
            "source_identity": {
                "status": "verified-original",
                "source_kind": "data-uri",
                "payload_sha256": "a" * 64,
                "mime": "image/png",
                "natural_size": [100.0, 60.0],
                "bytes_present": True,
                "provenance": "data-uri",
            },
            "display_payload": {
                "status": "missing",
                "kind": "none",
                "payload_sha256": None,
                "original": False,
                "reference_only": False,
            },
            "replacement": {
                "allowed": True,
                "mode": "source-bytes",
                "figma_runtime": "not-evaluated",
            },
            "missing": {"is_missing": True, "outcome": "partial-not-pass"},
            "use": {"use_id": "DQ-T:1:img"},
        }
        resolution = fuse_asset_record(
            record,
            generated_candidates=[
                {
                    "payload_sha256": hashlib.sha256(
                        base64.b64decode(display_b64)
                    ).hexdigest(),
                    "bytes_present": True,
                    "generator": "fixture-generator",
                    "model": "fixture-model",
                    "input_reference": "DQ-T:1:img",
                    "prompt": "reconstruct",
                    "prompt_version": "1",
                    "review_status": "unreviewed",
                }
            ],
        )
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
                    "imageBase64": display_b64,
                    "assetIdentity": {"asset_record": record},
                    "displayPayload": resolution["display"]["provenance"],
                    "replacement": record["replacement"],
                    "sourceResolution": resolution,
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
                            "imageHash": "generated",
                            "scaleMode": "FILL",
                        }
                    ],
                }
            ],
        }
        metrics, policy = _visual_pass()
        result = accept_output(
            {
                "design": design,
                "truth": {
                    "expected_texts": [],
                    "expected_asset_count": 1,
                    "native_text_required": False,
                },
                "readback_tree": readback,
                "visual_metrics": metrics,
                "visual_policy": policy,
                "image_report": {
                    "fills": [
                        {
                            "nodeId": "2:2",
                            "fillIndex": 0,
                            "imageHash": "generated",
                            "byteBase64": display_b64,
                        }
                    ]
                },
                "asset_probe": {
                    "status": "pass",
                    "node_type_preserved": True,
                    "image_hash_changed": True,
                    "scale_mode_preserved": True,
                    "restored": True,
                },
            },
            "fixed-authored-figma-readback/1.0",
        )

        self.assertEqual(result.dimensions["asset"]["status"], "partial")
        identity = result.assets["identities"][0]
        self.assertEqual(identity["fusion_status"], "partial-generated-display")
        self.assertEqual(identity["display_selected"], "generated-approximation")
        self.assertTrue(identity["display_generated"])

    def test_generated_icon_crop_is_scoped_out_of_original_image_denominator(
        self,
    ) -> None:
        display_b64 = base64.b64encode(b"generated-icon").decode("ascii")
        record = {
            "asset_id": "asset:unverified:icon",
            "source_identity": {
                "status": "unavailable",
                "source_kind": "none",
                "payload_sha256": None,
                "bytes_present": False,
            },
            "display_payload": {
                "status": "available",
                "kind": "screenshot-crop",
                "payload_sha256": "c" * 64,
                "original": False,
                "reference_only": True,
            },
            "replacement": {"allowed": False, "mode": "none"},
            "missing": {"is_missing": False, "outcome": "pass"},
            "use": {
                "use_id": "DQ-T:1:icon-crop",
                "source_kind": "icon-crop",
            },
        }
        resolution = fuse_asset_record(
            record,
            generated_candidates=[
                {
                    "payload_sha256": hashlib.sha256(
                        base64.b64decode(display_b64)
                    ).hexdigest(),
                    "bytes_present": True,
                    "generator": "fixture-generator",
                    "model": "fixture-model",
                    "input_reference": "DQ-T:1:icon-crop",
                    "prompt": "similar search icon",
                    "prompt_version": "1",
                    "review_status": "accepted-product-policy",
                    "use_class": "icon-crop",
                }
            ],
            prefer_generated_for_icon_crop=True,
        )
        design = {
            "canvas": {"width": 100, "height": 100, "background": "#ffffff"},
            "elements": [
                {
                    "id": "icon",
                    "type": "image",
                    "x": 10,
                    "y": 10,
                    "width": 24,
                    "height": 24,
                    "imageBase64": display_b64,
                    "assetIdentity": {"asset_record": record},
                    "sourceResolution": resolution,
                }
            ],
        }
        readback = {
            "id": "5:1",
            "type": "FRAME",
            "x": 0,
            "y": 0,
            "width": 100,
            "height": 100,
            "absolute": {"x": 0, "y": 0, "width": 100, "height": 100},
            "children": [
                {
                    "id": "5:2",
                    "type": "RECTANGLE",
                    "x": 10,
                    "y": 10,
                    "width": 24,
                    "height": 24,
                    "absolute": {
                        "x": 10,
                        "y": 10,
                        "width": 24,
                        "height": 24,
                    },
                    "fills": [
                        {
                            "type": "IMAGE",
                            "imageHash": "generated-icon",
                            "scaleMode": "FILL",
                        }
                    ],
                }
            ],
        }
        metrics, policy = _visual_pass()
        result = accept_output(
            {
                "design": design,
                "truth": {
                    "expected_texts": [],
                    "expected_asset_count": 1,
                    "native_text_required": False,
                },
                "readback_tree": readback,
                "visual_metrics": metrics,
                "visual_policy": policy,
                "image_report": {
                    "fills": [
                        {
                            "nodeId": "5:2",
                            "fillIndex": 0,
                            "imageHash": "generated-icon",
                            "byteBase64": display_b64,
                        }
                    ]
                },
                "asset_probe": {
                    "status": "pass",
                    "node_type_preserved": True,
                    "image_hash_changed": True,
                    "scale_mode_preserved": True,
                    "restored": True,
                },
            },
            "fixed-authored-figma-readback/1.0",
        )

        self.assertEqual(result.dimensions["asset"]["status"], "pass")
        identity = result.assets["identities"][0]
        self.assertEqual(identity["status"], "not-required")
        self.assertFalse(identity["requires_original"])
        self.assertTrue(identity["display_generated"])
        self.assertFalse(identity["display_original"])
        self.assertFalse(identity["replacement_allowed"])

    def test_missing_display_fusion_fails_asset_dimension(self) -> None:
        display_b64 = base64.b64encode(b"placeholder").decode("ascii")
        resolution = fuse_asset_record(
            {
                "asset_id": "asset:ref:" + "b" * 64,
                "source_identity": {
                    "status": "reference-only",
                    "source_kind": "remote-url",
                    "bytes_present": False,
                },
                "display_payload": {"status": "missing", "kind": "none"},
                "replacement": {"allowed": False, "mode": "none"},
                "missing": {"is_missing": True, "outcome": "partial-not-pass"},
                "use": {"use_id": "DQ-T:2:img"},
            }
        )
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
                    "imageBase64": display_b64,
                    "sourceResolution": resolution,
                }
            ],
        }
        readback = {
            "id": "2:1",
            "type": "FRAME",
            "x": 0,
            "y": 0,
            "width": 200,
            "height": 120,
            "absolute": {"x": 0, "y": 0, "width": 200, "height": 120},
            "children": [
                {
                    "id": "2:2",
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
                            "imageHash": "placeholder",
                            "scaleMode": "FILL",
                        }
                    ],
                }
            ],
        }
        metrics, policy = _visual_pass()
        result = accept_output(
            {
                "design": design,
                "truth": {
                    "expected_texts": [],
                    "expected_asset_count": 1,
                    "native_text_required": False,
                },
                "readback_tree": readback,
                "visual_metrics": metrics,
                "visual_policy": policy,
                "image_report": {
                    "fills": [
                        {
                            "nodeId": "2:2",
                            "fillIndex": 0,
                            "imageHash": "placeholder",
                            "byteBase64": display_b64,
                        }
                    ]
                },
                "asset_probe": {
                    "status": "pass",
                    "node_type_preserved": True,
                    "image_hash_changed": True,
                    "scale_mode_preserved": True,
                    "restored": True,
                },
            },
            "fixed-authored-figma-readback/1.0",
        )

        self.assertEqual(result.dimensions["asset"]["status"], "fail")
        identity = result.assets["identities"][0]
        self.assertEqual(identity["fusion_status"], "partial-missing-display")
        self.assertEqual(identity["display_selected"], "missing")

    def test_unknown_fusion_status_fails_closed(self) -> None:
        result = _asset_acceptance(
            {
                "elements": [
                    {
                        "id": "image",
                        "type": "image",
                        "sourceResolution": {
                            "status": "unexpected-future-state",
                            "identity": {
                                "selected": "verified-source",
                                "original": True,
                                "replaceable": True,
                            },
                            "display": {
                                "selected": "screenshot-crop",
                                "status": "available",
                                "original": False,
                                "reference_only": True,
                            },
                        },
                    }
                ]
            },
            {"dimensions": {}},
        )

        self.assertEqual(result["overall_status"], "fail")

    def test_reference_identity_with_capture_remains_partial(self) -> None:
        result = _asset_acceptance(
            {
                "elements": [
                    {
                        "id": "image",
                        "type": "image",
                        "sourceResolution": {
                            "status": "partial-unresolved-identity",
                            "identity": {
                                "selected": "reference-only",
                                "original": False,
                                "replaceable": False,
                            },
                            "display": {
                                "selected": "screenshot-crop",
                                "status": "available",
                                "original": False,
                                "reference_only": True,
                            },
                        },
                    }
                ]
            },
            {"dimensions": {}},
        )

        self.assertEqual(result["overall_status"], "partial")

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

    def test_content_includes_text_owned_by_non_text_elements(self) -> None:
        design = {
            "elements": [
                {
                    "id": "button",
                    "type": "button",
                    "text": "Action",
                    "x": 10,
                    "y": 10,
                    "width": 80,
                    "height": 32,
                }
            ]
        }
        readback = [
            {"id": "root", "type": "FRAME", "children": []},
            {
                "id": "text",
                "type": "TEXT",
                "characters": "Action",
                "x": 20,
                "y": 10,
                "width": 40,
                "height": 32,
            },
        ]

        result = _evaluate_content(design, {"expected_texts": []}, readback)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["expected_text_count"], 1)
        self.assertEqual(result["unexpected_texts"], [])

    def test_content_ignores_layout_whitespace_inside_cjk_text(self) -> None:
        design = {
            "elements": [
                {
                    "id": "text",
                    "type": "text",
                    "text": "读书好，好读书，读好书！",
                    "x": 0,
                    "y": 0,
                    "width": 160,
                    "height": 24,
                }
            ]
        }
        readback = [
            {"id": "root", "type": "FRAME", "children": []},
            {
                "id": "text-node",
                "type": "TEXT",
                "characters": "读书好，好读书，\n读好书！",
                "x": 0,
                "y": 0,
                "width": 160,
                "height": 24,
            },
        ]

        result = _evaluate_content(design, {"expected_texts": []}, readback)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["missing_texts"], [])
        self.assertEqual(result["unexpected_texts"], [])

    def test_centered_text_geometry_compares_center_not_left_edge(self) -> None:
        design = _design_with_text()
        design["elements"][0]["style"]["textAlign"] = "center"
        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            _readback_with_text(x=49),
            edit_probe=_passing_edit_probe(),
        )

        self.assertEqual(result["checks"]["geometry"]["status"], "pass")
        row = next(
            item
            for item in result["checks"]["geometry"]["rows"]
            if item.get("kind") == "text"
        )
        self.assertEqual(row["horizontal_alignment"], "center")
        self.assertTrue(row["passed"])

    def test_geometry_matches_text_across_layout_linebreak(self) -> None:
        design = _design_with_text()
        design["elements"][0]["text"] = "中文文本"
        readback = _readback_with_text(text="中文\n文本")

        result = _evaluate_geometry(
            design,
            [
                readback,
                *readback["children"],
            ],
            root_origin=(0, 0),
            policy={
                "position_tolerance_px": 2.0,
                "size_tolerance_px": 2.0,
            },
        )

        self.assertEqual(result["status"], "pass")

    def test_geometry_matches_missing_image_placeholder_rectangle(self) -> None:
        design = {
            "canvas": {"x": 0, "y": 0, "width": 200, "height": 120},
            "elements": [
                {
                    "id": "missing-image",
                    "type": "image",
                    "x": 10,
                    "y": 20,
                    "width": 40,
                    "height": 30,
                    "sourceResolution": {
                        "status": "partial-missing-display",
                        "display": {"selected": "missing"},
                    },
                }
            ],
        }
        root = {
            "id": "root",
            "type": "FRAME",
            "x": 0,
            "y": 0,
            "width": 200,
            "height": 120,
            "absolute": {"x": 0, "y": 0, "width": 200, "height": 120},
            "children": [
                {
                    "id": "placeholder",
                    "type": "RECTANGLE",
                    "x": 10,
                    "y": 20,
                    "width": 40,
                    "height": 30,
                    "absolute": {
                        "x": 10,
                        "y": 20,
                        "width": 40,
                        "height": 30,
                    },
                    "fills": [],
                }
            ],
        }

        result = _evaluate_geometry(
            design,
            [root, *root["children"]],
            root_origin=(0, 0),
            policy={
                "position_tolerance_px": 2.0,
                "size_tolerance_px": 2.0,
            },
        )

        self.assertEqual(result["status"], "pass")

    def test_geometry_order_uses_renderer_paint_order(self) -> None:
        design = {
            "canvas": {"x": 0, "y": 0, "width": 300, "height": 200},
            "elements": [
                {
                    "id": "inner",
                    "type": "rectangle",
                    "x": 10,
                    "y": 10,
                    "width": 50,
                    "height": 50,
                },
                {
                    "id": "background",
                    "type": "container",
                    "x": 0,
                    "y": 0,
                    "width": 100,
                    "height": 100,
                },
            ],
        }
        root = {
            "id": "root",
            "type": "FRAME",
            "x": 0,
            "y": 0,
            "width": 300,
            "height": 200,
            "absolute": {"x": 0, "y": 0, "width": 300, "height": 200},
            "children": [
                {
                    "id": "background-node",
                    "type": "FRAME",
                    "x": 0,
                    "y": 0,
                    "width": 100,
                    "height": 100,
                },
                {
                    "id": "inner-node",
                    "type": "RECTANGLE",
                    "x": 10,
                    "y": 10,
                    "width": 50,
                    "height": 50,
                },
            ],
        }

        result = _evaluate_geometry(
            design,
            [root, *root["children"]],
            root_origin=(0, 0),
            policy={
                "position_tolerance_px": 2.0,
                "size_tolerance_px": 2.0,
            },
        )

        self.assertEqual(result["order"]["status"], "pass")
        self.assertEqual(result["status"], "pass")

    def test_geometry_order_does_not_compare_across_parent_frames(self) -> None:
        design = {
            "canvas": {"x": 0, "y": 0, "width": 200, "height": 100},
            "elements": [
                {
                    "id": "nested-text",
                    "type": "text",
                    "text": "Nested",
                    "x": 10,
                    "y": 10,
                    "width": 80,
                    "height": 20,
                    "zIndex": 1,
                },
                {
                    "id": "logo",
                    "type": "rectangle",
                    "x": 10,
                    "y": 10,
                    "width": 80,
                    "height": 40,
                    "zIndex": 0,
                },
            ],
        }
        root = {
            "id": "root",
            "type": "FRAME",
            "x": 0,
            "y": 0,
            "width": 200,
            "height": 100,
            "children": [
                {
                    "id": "parent",
                    "type": "FRAME",
                    "x": 0,
                    "y": 0,
                    "width": 100,
                    "height": 60,
                    "children": [
                        {
                            "id": "text-node",
                            "type": "TEXT",
                            "characters": "Nested",
                            "x": 10,
                            "y": 10,
                            "width": 80,
                            "height": 20,
                        }
                    ],
                },
                {
                    "id": "logo-node",
                    "type": "RECTANGLE",
                    "x": 10,
                    "y": 10,
                    "width": 80,
                    "height": 40,
                },
            ],
        }

        result = _evaluate_geometry(
            design,
            [
                root,
                root["children"][0],
                *root["children"][0]["children"],
                root["children"][1],
            ],
            root_origin=(0, 0),
            policy={
                "position_tolerance_px": 2.0,
                "size_tolerance_px": 2.0,
            },
        )

        self.assertEqual(result["order"]["status"], "pass")
        self.assertEqual(result["status"], "pass")

    def test_font_matching_ignores_layout_linebreak(self) -> None:
        design = _design_with_text()
        design["elements"][0]["text"] = "中文文本"
        readback = _readback_with_text(text="中文\n文本")

        result = evaluate_figma_acceptance(
            design,
            {
                "expected_texts": ["中文文本"],
                "expected_asset_count": 0,
                "native_text_required": True,
            },
            readback,
            font_report={
                "usedFonts": {"Arial / Bold": 1},
                "stackProbe": [["Arial", 1]],
            },
            edit_probe=_passing_edit_probe(),
        )

        self.assertEqual(result["checks"]["font"]["status"], "pass")

    def test_native_text_count_includes_non_text_elements(self) -> None:
        design = {
            "elements": [
                {
                    "id": "button",
                    "type": "button",
                    "text": "Action",
                    "x": 10,
                    "y": 10,
                    "width": 80,
                    "height": 32,
                }
            ]
        }
        nodes = [
            {"id": "root", "type": "FRAME", "children": []},
            {
                "id": "text",
                "type": "TEXT",
                "characters": "Action",
                "x": 20,
                "y": 10,
                "width": 40,
                "height": 32,
            },
        ]

        result = _evaluate_native_text(
            design,
            {"native_text_required": True},
            nodes,
            _passing_edit_probe(),
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["expected_native_text_count"], 1)

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
