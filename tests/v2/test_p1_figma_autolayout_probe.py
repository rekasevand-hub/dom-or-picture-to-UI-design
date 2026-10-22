from __future__ import annotations

import unittest

from scripts.figma_autolayout_edit_probe import (
    build_autolayout_probe_report,
)


def _tree(
    *,
    frame_height: float,
    text_height: float,
    sibling_y: float,
) -> dict:
    return {
        "id": "7:1",
        "type": "FRAME",
        "width": 320,
        "height": frame_height,
        "layoutMode": "VERTICAL",
        "children": [
            {
                "id": "7:2",
                "type": "TEXT",
                "height": text_height,
                "y": 16,
            },
            {
                "id": "7:3",
                "type": "RECTANGLE",
                "height": 40,
                "y": sibling_y,
            },
        ],
    }


class FigmaAutoLayoutEditProbeTests(unittest.TestCase):
    def test_text_growth_propagates_to_sibling_and_parent(self) -> None:
        report = build_autolayout_probe_report(
            _tree(frame_height=106, text_height=38, sibling_y=66),
            _tree(frame_height=146, text_height=78, sibling_y=106),
            _tree(frame_height=106, text_height=38, sibling_y=66),
            frame_id="7:1",
            text_id="7:2",
            sibling_id="7:3",
        )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["text_height_changed"])
        self.assertTrue(report["sibling_y_changed"])
        self.assertTrue(report["parent_height_changed"])
        self.assertTrue(report["restored"])

    def test_unchanged_sibling_layout_fails_propagation(self) -> None:
        report = build_autolayout_probe_report(
            _tree(frame_height=106, text_height=38, sibling_y=66),
            _tree(frame_height=146, text_height=78, sibling_y=66),
            _tree(frame_height=106, text_height=38, sibling_y=66),
            frame_id="7:1",
            text_id="7:2",
            sibling_id="7:3",
        )

        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["sibling_y_changed"])
        self.assertIn("sibling_y_changed", report["failed_checks"])


if __name__ == "__main__":
    unittest.main()
