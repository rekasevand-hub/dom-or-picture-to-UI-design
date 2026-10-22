from __future__ import annotations

import unittest

from scripts.figma_asset_probe import (
    build_asset_probe_report,
    replace_with_restore,
)
from scripts.figma_edit_probe import (
    build_edit_probe_report,
    edit_with_restore,
)


def _text_tree(text: str, width: float) -> dict:
    return {
        "id": "1:1",
        "type": "FRAME",
        "children": [
            {
                "id": "1:2",
                "type": "TEXT",
                "characters": text,
                "x": 10,
                "y": 20,
                "width": width,
                "height": 20,
                "fontName": {"family": "Arial", "style": "Regular"},
                "fontSize": 16,
            }
        ],
    }


def _image_tree(image_hash: str, scale_mode: str = "FILL") -> dict:
    return {
        "id": "2:1",
        "type": "FRAME",
        "children": [
            {
                "id": "2:2",
                "type": "RECTANGLE",
                "fills": [
                    {
                        "type": "IMAGE",
                        "imageHash": image_hash,
                        "scaleMode": scale_mode,
                        "visible": True,
                    }
                ],
            }
        ],
    }


class FigmaProbeReportTests(unittest.TestCase):
    def test_edit_restore_runs_when_intermediate_readback_fails(self) -> None:
        class FailingReadbackAdapter:
            def __init__(self) -> None:
                self.text_calls = []
                self.read_count = 0

            def set_text(self, node_id, text):
                self.text_calls.append((node_id, text))
                return {"nodeId": node_id}

            def _send(self, action, params):
                self.read_count += 1
                if self.read_count == 1:
                    raise RuntimeError("readback failed")
                return _text_tree("Original", 60)

        adapter = FailingReadbackAdapter()
        with self.assertRaises(RuntimeError):
            edit_with_restore(
                adapter,
                root_id="1:1",
                node_id="1:2",
                original_text="Original",
                probe_text="Native edit probe",
            )

        self.assertEqual(
            adapter.text_calls,
            [
                ("1:2", "Native edit probe"),
                ("1:2", "Original"),
            ],
        )

    def test_native_edit_probe_requires_restored_geometry_and_font(self) -> None:
        report = build_edit_probe_report(
            _text_tree("Original", 60),
            _text_tree("Native edit probe", 140),
            _text_tree("Original", 60),
            node_id="1:2",
            probe_text="Native edit probe",
        )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["characters_updated"])
        self.assertTrue(report["font_preserved"])
        self.assertTrue(report["geometry_updated"])
        self.assertIs(report["restored"], True)
        self.assertIn("restored_state", report)

    def test_native_edit_probe_reports_missing_geometry_propagation(self) -> None:
        report = build_edit_probe_report(
            _text_tree("Original", 60),
            _text_tree("Native edit probe", 60),
            _text_tree("Original", 60),
            node_id="1:2",
            probe_text="Native edit probe",
        )

        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["geometry_updated"])

    def test_asset_probe_requires_hash_change_and_restore(self) -> None:
        report = build_asset_probe_report(
            _image_tree("source-hash"),
            _image_tree("replacement-hash"),
            _image_tree("source-hash"),
            node_id="2:2",
        )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["image_hash_changed"])
        self.assertTrue(report["scale_mode_preserved"])
        self.assertIs(report["restored"], True)
        self.assertIn("restored_state", report)

    def test_asset_restore_runs_when_intermediate_readback_fails(self) -> None:
        class FailingReadbackAdapter:
            def __init__(self) -> None:
                self.replace_calls = []
                self.read_count = 0

            def replace_image_fill(self, node_id, image_base64):
                self.replace_calls.append((node_id, image_base64))
                return {"nodeId": node_id}

            def _send(self, action, params):
                self.read_count += 1
                if self.read_count == 1:
                    raise RuntimeError("readback failed")
                return _image_tree("source-hash")

        adapter = FailingReadbackAdapter()
        with self.assertRaises(RuntimeError):
            replace_with_restore(
                adapter,
                root_id="2:1",
                node_id="2:2",
                source_base64="source-bytes",
                replacement_base64="replacement-bytes",
            )

        self.assertEqual(
            adapter.replace_calls,
            [
                ("2:2", "replacement-bytes"),
                ("2:2", "source-bytes"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
