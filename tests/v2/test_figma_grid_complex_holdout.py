from __future__ import annotations

import unittest

from scripts.figma_grid_complex_holdout_probe import (
    build_grid_holdout_checks,
    diff_grid_snapshots,
    project_grid_tree,
)


def _tree() -> dict:
    return {
        "id": "10:1",
        "name": "Complex Grid",
        "type": "FRAME",
        "x": 10,
        "y": 20,
        "width": 640,
        "height": 420,
        "absolute": {"x": 100, "y": 200, "width": 640, "height": 420},
        "layoutMode": "GRID",
        "gridRowCount": 2,
        "gridColumnCount": 3,
        "gridRowGap": 10,
        "gridColumnGap": 12,
        "gridItemsPositioning": "MANUAL",
        "gridAutoTracks": "NONE",
        "gridRowSizes": [
            {"type": "FIXED", "value": 120},
            {"type": "FLEX", "value": 1},
        ],
        "gridColumnSizes": [
            {"type": "FIXED", "value": 180},
            {"type": "FLEX", "value": 1},
            {"type": "HUG"},
        ],
        "children": [
            {
                "id": "10:2",
                "name": "Nested Grid",
                "type": "FRAME",
                "x": 12,
                "y": 12,
                "width": 300,
                "height": 180,
                "layoutMode": "GRID",
                "gridRowCount": 2,
                "gridColumnCount": 2,
                "gridRowAnchorIndex": 0,
                "gridColumnAnchorIndex": 0,
                "gridColumnSpan": 2,
                "children": [
                    {
                        "id": "10:3",
                        "name": "Long text",
                        "type": "TEXT",
                        "characters": "A long line\nwraps across the track.",
                        "x": 6,
                        "y": 6,
                        "width": 220,
                        "height": 64,
                        "gridColumnSpan": 2,
                    },
                    {
                        "id": "10:4",
                        "name": "Image",
                        "type": "RECTANGLE",
                        "x": 6,
                        "y": 80,
                        "width": 80,
                        "height": 60,
                        "fills": [
                            {
                                "type": "IMAGE",
                                "imageHash": "image-hash",
                                "scaleMode": "FILL",
                            }
                        ],
                    },
                ],
            }
        ],
    }


class GridComplexHoldoutTests(unittest.TestCase):
    def test_projection_keeps_persistent_grid_semantics(self) -> None:
        projected = project_grid_tree(_tree())

        self.assertNotIn("absolute", projected)
        self.assertEqual(projected["gridColumnSizes"][2], {"type": "HUG"})
        self.assertEqual(projected["children"][0]["layoutMode"], "GRID")
        self.assertEqual(
            projected["children"][0]["children"][1]["fills"][0]["imageHash"],
            "image-hash",
        )

    def test_snapshot_diff_tolerates_subpixel_geometry_but_reports_drift(self) -> None:
        expected = project_grid_tree(_tree())
        within_tolerance = project_grid_tree(_tree())
        within_tolerance["children"][0]["width"] += 0.4
        self.assertEqual(diff_grid_snapshots(expected, within_tolerance), [])

        outside_tolerance = project_grid_tree(_tree())
        outside_tolerance["children"][0]["width"] += 0.6
        differences = diff_grid_snapshots(expected, outside_tolerance)
        self.assertEqual(len(differences), 1)
        self.assertEqual(differences[0]["path"], "$.children[0].width")

    def test_snapshot_diff_reports_child_order_changes(self) -> None:
        expected = project_grid_tree(_tree())
        actual = project_grid_tree(_tree())
        actual["children"][0]["children"].reverse()

        differences = diff_grid_snapshots(expected, actual)

        self.assertTrue(
            any("children[0].children[0].name" in item["path"] for item in differences)
        )

    def test_holdout_checks_require_mixed_tracks_nested_grid_text_and_image(
        self,
    ) -> None:
        checks = build_grid_holdout_checks(_tree())

        self.assertTrue(checks["outer_manual_grid"])
        self.assertTrue(checks["mixed_track_types"])
        self.assertTrue(checks["nested_grid"])
        self.assertTrue(checks["long_text"])
        self.assertTrue(checks["image_fill"])
        self.assertEqual(
            [name for name, passed in checks.items() if not passed],
            [],
        )


if __name__ == "__main__":
    unittest.main()
