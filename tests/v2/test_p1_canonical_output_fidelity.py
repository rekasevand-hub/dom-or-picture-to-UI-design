from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import cv2
import numpy as np

from scripts.p1_canonical_output_fidelity import (
    apply_visual_policy,
    evaluate_design_against_truth,
    evaluate_visual_fidelity,
    verify_remote_asset_evidence,
)


class CanonicalOutputFidelityTests(unittest.TestCase):
    def test_visual_policy_requires_every_metric_without_composite_score(self) -> None:
        policy = {
            "max_mean": 1.0,
            "max_ink_mean": 20.0,
            "max_over30_pct": 1.5,
            "max_bad_pixel_count": 6000,
            "require_size_match": True,
        }

        passed = apply_visual_policy({
            "mean": 0.8,
            "ink_mean": 18.0,
            "over30_pct": 1.0,
            "bad_pixel_count": 5000,
            "size_match": True,
        }, policy)
        failed = apply_visual_policy({
            "mean": 0.8,
            "ink_mean": 25.0,
            "over30_pct": 1.0,
            "bad_pixel_count": 5000,
            "size_match": True,
        }, policy)

        self.assertEqual(passed["status"], "pass")
        self.assertEqual(failed["status"], "fail")
        self.assertEqual(failed["failed_metrics"], ["ink_mean"])
        self.assertFalse(failed["composite_score_used"])

    def test_remote_asset_evidence_requires_mime_and_content_hash(self) -> None:
        rows = [{
            "asset_id": "remote-svg",
            "status": "downloaded",
            "final_url": "http://127.0.0.1:1234/remote.svg",
            "mime": "image/svg+xml",
            "sha256": "expected-sha",
            "size_bytes": 120,
        }]
        expected = [{
            "asset_id": "remote-svg",
            "url_suffix": "/remote.svg",
            "mime": "image/svg+xml",
            "sha256": "expected-sha",
        }]

        passed = verify_remote_asset_evidence(rows, expected)
        rows[0]["sha256"] = "wrong-sha"
        failed = verify_remote_asset_evidence(rows, expected)

        self.assertEqual(passed["status"], "pass")
        self.assertEqual(failed["status"], "fail")
        self.assertFalse(failed["rows"][0]["sha256_passed"])

    def test_opaque_region_can_be_excluded_from_visual_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = np.full((20, 20, 3), 255, dtype=np.uint8)
            render = reference.copy()
            render[5:15, 5:15] = 0
            reference_path = root / "reference.png"
            render_path = root / "render.png"
            cv2.imwrite(str(reference_path), reference)
            cv2.imwrite(str(render_path), render)

            result = evaluate_visual_fidelity(
                reference_path,
                render_path,
                exclusion_regions=[{
                    "name": "opaque-frame-interior",
                    "x": 5,
                    "y": 5,
                    "width": 10,
                    "height": 10,
                    "reason": "opaque-frame-content",
                }],
            )

        self.assertEqual(result["mean"], 0.0)
        self.assertEqual(result["bad_pixel_count"], 0)
        self.assertEqual(result["excluded_region_pixel_count"], 100)

    def test_dimensions_are_reported_independently_without_composite_score(self) -> None:
        design = {
            "canvas": {"width": 800, "height": 600},
            "elements": [
                {
                    "id": "title",
                    "type": "text",
                    "text": "中文 / English",
                    "x": 20,
                    "y": 30,
                    "width": 300,
                    "height": 40,
                },
                {
                    "id": "body",
                    "type": "text",
                    "text": "第二行 multiline text",
                    "x": 20,
                    "y": 80,
                    "width": 420,
                    "height": 60,
                },
                {
                    "id": "photo",
                    "type": "image",
                    "x": 20,
                    "y": 160,
                    "width": 120,
                    "height": 80,
                    "imageBase64": "abc",
                },
            ],
        }
        truth = {
            "expected_texts": ["中文 / English", "第二行 multiline text"],
            "critical_boxes": [
                {
                    "text": "中文 / English",
                    "x": 20,
                    "y": 30,
                    "width": 300,
                    "height": 40,
                    "tolerance_px": 1,
                }
            ],
            "expected_asset_count": 1,
            "native_text_required": True,
        }

        result = evaluate_design_against_truth(design, truth)

        self.assertNotIn("score", result)
        self.assertEqual(result["content"]["status"], "pass")
        self.assertEqual(result["geometry"]["status"], "pass")
        self.assertEqual(result["assets"]["status"], "pass")
        self.assertEqual(result["editability"]["status"], "pass")
        self.assertEqual(result["editability"]["native_text_count"], 2)
        self.assertFalse(result["composite_score_used"])

    def test_missing_content_is_not_hidden_by_other_passing_dimensions(self) -> None:
        design = {
            "canvas": {"width": 800, "height": 600},
            "elements": [
                {
                    "type": "text",
                    "text": "present",
                    "x": 0,
                    "y": 0,
                    "width": 100,
                    "height": 20,
                },
                {
                    "type": "image",
                    "x": 0,
                    "y": 40,
                    "width": 100,
                    "height": 100,
                    "imageBase64": "abc",
                },
            ],
        }
        truth = {
            "expected_texts": ["present", "missing required"],
            "expected_asset_count": 1,
            "native_text_required": True,
        }

        result = evaluate_design_against_truth(design, truth)

        self.assertEqual(result["content"]["status"], "fail")
        self.assertEqual(result["content"]["text_coverage"], 0.5)
        self.assertEqual(result["content"]["missing_texts"], ["missing required"])
        self.assertEqual(result["assets"]["status"], "pass")
        self.assertEqual(result["editability"]["status"], "pass")

    def test_declared_missing_asset_is_partial_not_pass(self) -> None:
        design = {
            "canvas": {"width": 800, "height": 600},
            "elements": [
                {
                    "type": "text",
                    "text": "asset failure remains explainable",
                    "x": 0,
                    "y": 0,
                    "width": 300,
                    "height": 24,
                },
                {
                    "type": "image",
                    "x": 0,
                    "y": 40,
                    "width": 100,
                    "height": 100,
                    "imageBase64": "valid-asset",
                },
            ],
        }
        truth = {
            "expected_texts": ["asset failure remains explainable"],
            "expected_asset_count": 2,
            "minimum_asset_count": 1,
            "expected_output_status": "partial",
            "expected_limitations": ["missing-asset-bytes"],
            "native_text_required": True,
        }

        result = evaluate_design_against_truth(design, truth)

        self.assertEqual(result["assets"]["status"], "partial")
        self.assertEqual(result["assets"]["missing_asset_count"], 1)
        self.assertEqual(result["expected_output_status"], "partial")
        self.assertEqual(
            result["expected_limitations"],
            ["missing-asset-bytes"],
        )
        self.assertFalse(result["composite_score_used"])

    def test_font_fallback_marker_is_reported_as_declared_family_only(self) -> None:
        design = {
            "canvas": {"width": 800, "height": 600},
            "elements": [{
                "type": "text",
                "text": "font fallback text",
                "x": 0,
                "y": 0,
                "width": 300,
                "height": 24,
                "style": {
                    "fontFamily": '"Missing Font", Arial, sans-serif',
                },
            }],
        }
        truth = {
            "expected_texts": ["font fallback text"],
            "expected_font_markers": [{
                "text": "font fallback text",
                "family_contains": "Arial",
            }],
            "native_text_required": True,
        }

        result = evaluate_design_against_truth(design, truth)

        self.assertEqual(result["font"]["status"], "pass")
        self.assertEqual(
            result["font"]["scope"],
            "declared-font-family-not-final-glyph-identity",
        )

    def test_asset_regions_verify_display_box_and_local_bytes(self) -> None:
        design = {
            "canvas": {"width": 800, "height": 600},
            "elements": [
                {
                    "type": "image",
                    "x": 40,
                    "y": 40,
                    "width": 100,
                    "height": 100,
                    "imageBase64": "local-crop-bytes",
                },
                {
                    "type": "image",
                    "x": 180,
                    "y": 40,
                    "width": 80,
                    "height": 80,
                },
            ],
        }
        truth = {
            "expected_asset_count": 2,
            "expected_asset_regions": [
                {
                    "name": "cropped-image",
                    "x": 40,
                    "y": 40,
                    "width": 100,
                    "height": 100,
                    "tolerance_px": 1,
                    "require_local_bytes": True,
                },
                {
                    "name": "missing-local-bytes",
                    "x": 180,
                    "y": 40,
                    "width": 80,
                    "height": 80,
                    "tolerance_px": 1,
                    "require_local_bytes": True,
                },
            ],
        }

        result = evaluate_design_against_truth(design, truth)

        rows = result["assets"]["region_rows"]
        self.assertTrue(rows[0]["passed"])
        self.assertFalse(rows[1]["passed"])
        self.assertEqual(result["assets"]["status"], "fail")
        self.assertEqual(
            result["assets"]["scope"],
            "displayed-box-and-local-bytes-not-source-crop-identity",
        )

    def test_asset_region_can_verify_source_identity_and_crop_rect(self) -> None:
        design = {
            "canvas": {"width": 800, "height": 600},
            "elements": [{
                "type": "image",
                "x": 40,
                "y": 40,
                "width": 100,
                "height": 100,
                "imageBase64": "display-crop",
                "assetIdentity": {
                    "content_sha256": "source-sha",
                    "natural_size": [200.0, 100.0],
                },
                "sourceCrop": {
                    "source_rect": [100.0, 0.0, 100.0, 100.0],
                    "object_fit": "cover",
                },
            }],
        }
        truth = {
            "expected_asset_count": 1,
            "expected_asset_regions": [{
                "name": "right-half-crop",
                "x": 40,
                "y": 40,
                "width": 100,
                "height": 100,
                "tolerance_px": 1,
                "require_local_bytes": True,
                "expected_content_sha256": "source-sha",
                "expected_natural_size": [200.0, 100.0],
                "expected_source_rect": [100.0, 0.0, 100.0, 100.0],
                "expected_object_fit": "cover",
            }],
        }

        result = evaluate_design_against_truth(design, truth)

        row = result["assets"]["region_rows"][0]
        self.assertTrue(row["identity_passed"])
        self.assertTrue(row["crop_passed"])
        self.assertTrue(row["passed"])
        self.assertEqual(result["assets"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
