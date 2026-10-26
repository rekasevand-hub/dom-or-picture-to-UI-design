from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from src.app.services.evidence.dom_figma_diff_attribution import (
    build_diff_attribution,
)
from scripts.dom_figma_diff_attribution import _build_parser


def _readback(*children: dict) -> dict:
    return {
        "id": "root",
        "type": "FRAME",
        "x": 0,
        "y": 0,
        "width": 80,
        "height": 40,
        "absolute": {"x": 0, "y": 0, "width": 80, "height": 40},
        "children": list(children),
    }


def _text_node(node_id: str, x: float, y: float, text: str) -> dict:
    return {
        "id": node_id,
        "type": "TEXT",
        "x": x,
        "y": y,
        "width": 30,
        "height": 20,
        "absolute": {"x": x, "y": y, "width": 30, "height": 20},
        "characters": text,
        "fontName": {"family": "Arial", "style": "Regular"},
        "fontSize": 14,
    }


def _design_text(element_id: str, x: float, y: float, text: str, **style) -> dict:
    return {
        "id": element_id,
        "type": "text",
        "text": text,
        "x": x,
        "y": y,
        "width": 30,
        "height": 20,
        "style": {
            "fontFamily": "Arial",
            "fontSize": 14,
            "fontWeight": "400",
            **style,
        },
    }


class DomFigmaDiffAttributionTests(unittest.TestCase):
    def test_positive_shift_describes_render_offset(self) -> None:
        reference = np.full((40, 80, 3), 255, dtype=np.uint8)
        render = reference.copy()
        reference[10:16, 12:22] = 0
        render[10:16, 13:23] = 0
        design = {
            "canvas": {"width": 80, "height": 40},
            "elements": [_design_text("text-1", 8, 8, "Shift")],
        }
        readback = _readback(_text_node("node-1", 8, 8, "Shift"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference_path = root / "reference.png"
            render_path = root / "render.png"
            cv2.imwrite(str(reference_path), reference)
            cv2.imwrite(str(render_path), render)
            report = build_diff_attribution(
                design,
                readback,
                reference_path,
                render_path,
                threshold=30,
                search_radius=2,
            )

        row = report["nodes"][0]
        self.assertEqual(row["best_dx"], 1)
        self.assertEqual(row["best_dy"], 0)
        self.assertGreater(row["over30"], 0)
        self.assertEqual(report["threshold"], 30)
        self.assertFalse(report["composite_score_used"])
        self.assertEqual(
            report["figma_runtime"],
            "observed-existing-frame",
        )

    def test_identical_crop_reports_zero_shift(self) -> None:
        image = np.full((40, 80, 3), 255, dtype=np.uint8)
        image[10:16, 12:22] = 32
        design = {
            "canvas": {"width": 80, "height": 40},
            "elements": [_design_text("text-1", 8, 8, "Same")],
        }
        readback = _readback(_text_node("node-1", 8, 8, "Same"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference_path = root / "reference.png"
            render_path = root / "render.png"
            cv2.imwrite(str(reference_path), image)
            cv2.imwrite(str(render_path), image)
            report = build_diff_attribution(
                design,
                readback,
                reference_path,
                render_path,
            )

        self.assertEqual(report["nodes"][0]["best_dx"], 0)
        self.assertEqual(report["nodes"][0]["best_dy"], 0)
        self.assertEqual(report["nodes"][0]["over30"], 0)

    def test_style_aggregates_and_residual_stay_independent(self) -> None:
        reference = np.full((40, 80, 3), 255, dtype=np.uint8)
        render = reference.copy()
        reference[5:10, 5:15] = 0
        render[5:10, 5:15] = 60
        reference[25:30, 45:55] = 0
        render[25:30, 45:55] = 200
        image = reference.copy()
        design = {
            "canvas": {"width": 80, "height": 40},
            "elements": [
                _design_text("a", 0, 0, "A", fontSize=14),
                _design_text("b", 40, 20, "B", fontSize=16),
            ],
        }
        readback = _readback(
            _text_node("node-a", 0, 0, "A"),
            {
                **_text_node("node-b", 40, 20, "B"),
                "fontSize": 16,
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference_path = root / "reference.png"
            baseline_path = root / "baseline.png"
            render_path = root / "render.png"
            cv2.imwrite(str(reference_path), reference)
            cv2.imwrite(str(baseline_path), image)
            cv2.imwrite(str(render_path), render)
            report = build_diff_attribution(
                design,
                readback,
                reference_path,
                render_path,
            )

        self.assertEqual(len(report["styles"]), 2)
        self.assertEqual(len(report["nodes"]), 2)
        self.assertGreater(report["total_over30"], 0)
        self.assertIn("unmatched_over30", report)
        self.assertGreaterEqual(report["unmatched_over30"], 0)
        self.assertTrue(
            all(row["style_key"] in report["styles"] for row in report["nodes"])
        )

    def test_cli_parser_and_direct_execution(self) -> None:
        args = _build_parser().parse_args(
            [
                "--design",
                "design.json",
                "--readback",
                "readback.json",
                "--reference",
                "reference.png",
                "--render",
                "render.png",
                "--out",
                "attribution",
            ]
        )
        self.assertEqual(args.out, Path("attribution"))
        self.assertEqual(args.threshold, 30)
        self.assertEqual(args.search_radius, 2)

        result = subprocess.run(
            [
                sys.executable,
                str(
                    Path(__file__).resolve().parents[2]
                    / "scripts"
                    / "dom_figma_diff_attribution.py"
                ),
                "--help",
            ],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--search-radius", result.stdout)

    def test_cli_output_is_safe_for_non_utf8_console(self) -> None:
        image = np.full((40, 80, 3), 255, dtype=np.uint8)
        design = {
            "canvas": {"width": 80, "height": 40},
            "elements": [_design_text("text-1", 8, 8, "😀")],
        }
        readback = _readback(_text_node("node-1", 8, 8, "😀"))
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "gbk"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "design.json"
            readback_path = root / "readback.json"
            image_path = root / "image.png"
            output = root / "out"
            design_path.write_text(
                json.dumps(design, ensure_ascii=False),
                encoding="utf-8",
            )
            readback_path.write_text(
                json.dumps(readback, ensure_ascii=False),
                encoding="utf-8",
            )
            cv2.imwrite(str(image_path), image)
            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        Path(__file__).resolve().parents[2]
                        / "scripts"
                        / "dom_figma_diff_attribution.py"
                    ),
                    "--design",
                    str(design_path),
                    "--readback",
                    str(readback_path),
                    "--reference",
                    str(image_path),
                    "--render",
                    str(image_path),
                    "--out",
                    str(output),
                ],
                cwd=Path(__file__).resolve().parents[2],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
