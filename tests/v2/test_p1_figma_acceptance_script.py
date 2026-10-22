from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts.p1_figma_acceptance import (
    _attach_parent_layout_probe,
    build_acceptance_artifact,
    main,
)


class FigmaAcceptanceScriptTests(unittest.TestCase):
    def test_parent_layout_probe_is_attached_to_edit_evidence(self) -> None:
        edit_probe = {
            "status": "pass",
            "restored": True,
        }
        parent = {
            "status": "pass",
            "sibling_y_changed": True,
            "parent_height_changed": True,
        }

        merged = _attach_parent_layout_probe(edit_probe, parent)

        self.assertEqual(
            merged["parent_layout_propagation"]["status"],
            "pass",
        )
        self.assertEqual(
            merged["parent_layout_propagation"]["evidence"],
            parent,
        )
        self.assertNotIn("parent_layout_propagation", edit_probe)

    def test_cli_rejects_non_object_input_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "design.json"
            design.write_text("[]", encoding="utf-8")
            code = main(
                [
                    "--design",
                    str(design),
                    "--truth",
                    str(root / "truth.json"),
                    "--readback",
                    str(root / "readback.json"),
                    "--reference",
                    str(root / "reference.png"),
                    "--render",
                    str(root / "render.png"),
                    "--out",
                    str(root / "out"),
                ]
            )

        self.assertEqual(code, 1)

    def test_figma_policies_are_frozen_for_this_scope(self) -> None:
        fixture_root = (
            Path(__file__).resolve().parents[1] / "fixtures" / "p1" / "canonical"
        )
        structure = json.loads(
            (fixture_root / "figma_structure_policy.json").read_text(encoding="utf-8")
        )
        visual = json.loads(
            (fixture_root / "figma_visual_policy.json").read_text(encoding="utf-8")
        )

        self.assertEqual(structure["policy_id"], "p1-figma-structure/1.0")
        self.assertEqual(structure["position_tolerance_px"], 1.0)
        self.assertEqual(structure["size_tolerance_px"], 2.0)
        self.assertEqual(structure["font_size_tolerance_px"], 0.1)
        self.assertEqual(visual["policy_id"], "p1-figma-frame-v1")
        self.assertEqual(visual["max_mean"], 3.0)
        self.assertEqual(visual["max_ink_mean"], 100.0)
        self.assertEqual(visual["max_over30_pct"], 2.5)
        self.assertEqual(visual["max_bad_pixel_count"], 14000)
        self.assertTrue(visual["require_size_match"])

    def test_builds_report_from_real_artifacts_and_records_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "12_design.json"
            truth_path = root / "truth.json"
            readback_path = root / "readback_tree.json"
            reference_path = root / "00_screenshot.png"
            render_path = root / "figma_render.png"
            image_report_path = root / "image_report.json"
            out = root / "acceptance"

            design = {
                "canvas": {"width": 40, "height": 30, "background": "#ffffff"},
                "elements": [
                    {
                        "id": "title",
                        "type": "text",
                        "text": "Title",
                        "x": 2,
                        "y": 3,
                        "width": 30,
                        "height": 12,
                        "style": {
                            "fontFamily": "Arial",
                            "fontWeight": "normal",
                            "fontSize": 10,
                        },
                    }
                ],
            }
            truth = {
                "expected_texts": ["Title"],
                "expected_asset_count": 0,
                "native_text_required": True,
            }
            readback = {
                "id": "3:1",
                "type": "FRAME",
                "name": "Screen",
                "x": 0,
                "y": 0,
                "width": 40,
                "height": 30,
                "absolute": {"x": 0, "y": 0, "width": 40, "height": 30},
                "children": [
                    {
                        "id": "3:2",
                        "type": "TEXT",
                        "name": "Title",
                        "x": 2,
                        "y": 3,
                        "width": 20,
                        "height": 10,
                        "absolute": {
                            "x": 2,
                            "y": 3,
                            "width": 20,
                            "height": 10,
                        },
                        "characters": "Title",
                        "fontName": {"family": "Arial", "style": "Regular"},
                        "fontSize": 10,
                    }
                ],
            }
            design_path.write_text(json.dumps(design), encoding="utf-8")
            truth_path.write_text(json.dumps(truth), encoding="utf-8")
            readback_path.write_text(json.dumps(readback), encoding="utf-8")
            image_report_path.write_text(
                json.dumps({"fills": [], "fillCount": 0}),
                encoding="utf-8",
            )
            image = np.full((30, 40, 3), 255, dtype=np.uint8)
            cv2.imwrite(str(reference_path), image)
            cv2.imwrite(str(render_path), image)

            report = build_acceptance_artifact(
                design_path=design_path,
                truth_path=truth_path,
                readback_path=readback_path,
                reference_path=reference_path,
                render_path=render_path,
                image_report_path=image_report_path,
                out_dir=out,
            )
            stored = json.loads(
                (out / "figma_acceptance.json").read_text(encoding="utf-8")
            )

        self.assertEqual(
            report["checks"]["visual"]["status"],
            "measured-not-gated",
        )
        self.assertFalse(stored["acceptance_passed"])
        self.assertEqual(stored["figma_evaluated_count"], 0)
        self.assertEqual(
            set(stored["inputs"]),
            {
                "design",
                "truth",
                "readback",
                "reference",
                "render",
                "image_report",
            },
        )
        for item in stored["inputs"].values():
            self.assertEqual(len(item["sha256"]), 64)
            self.assertGreater(item["size_bytes"], 0)
        self.assertEqual(len(stored["content_hash"]), 64)


if __name__ == "__main__":
    unittest.main()
