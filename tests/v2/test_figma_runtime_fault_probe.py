from __future__ import annotations

import unittest

from scripts.figma_runtime_fault_probe import build_runtime_fault_checks


def _tree(text: str = "Before fault", row_gap: float = 10) -> dict:
    return {
        "id": "20:1",
        "name": "Runtime Fault Probe",
        "type": "FRAME",
        "x": 0,
        "y": 0,
        "width": 420,
        "height": 260,
        "layoutMode": "GRID",
        "gridRowCount": 2,
        "gridColumnCount": 2,
        "gridRowGap": row_gap,
        "gridColumnGap": 10,
        "gridItemsPositioning": "MANUAL",
        "gridAutoTracks": "NONE",
        "gridRowSizes": [
            {"type": "FIXED", "value": 80},
            {"type": "FIXED", "value": 80},
        ],
        "gridColumnSizes": [
            {"type": "FIXED", "value": 100},
            {"type": "FIXED", "value": 100},
        ],
        "children": [
            {
                "id": "20:2",
                "name": "Text",
                "type": "TEXT",
                "characters": text,
                "x": 10,
                "y": 10,
                "width": 100,
                "height": 40,
                "gridRowAnchorIndex": 0,
                "gridColumnAnchorIndex": 0,
                "gridColumnSpan": 1,
            },
            {
                "id": "20:3",
                "name": "Adjacent",
                "type": "RECTANGLE",
                "x": 120,
                "y": 10,
                "width": 100,
                "height": 80,
                "gridRowAnchorIndex": 0,
                "gridColumnAnchorIndex": 1,
                "gridColumnSpan": 1,
            },
        ],
    }


def _result() -> dict:
    return {
        "status": "rolled-back",
        "transactionId": "runtime-fault-tx",
        "committed": [{"index": 0, "action": "set_text"}],
        "failed": {
            "index": 1,
            "action": "set_layout_flow",
            "error": "Cannot set child to specified column span",
        },
        "rollback": {
            "attempted": 2,
            "restored": 2,
            "failed": [],
        },
    }


class FigmaRuntimeFaultProbeTests(unittest.TestCase):
    def test_runtime_fault_requires_layout_and_text_restore(self) -> None:
        checks = build_runtime_fault_checks(
            _tree(),
            _result(),
            _tree(),
        )

        self.assertTrue(checks["runtime_failure_observed"])
        self.assertTrue(checks["failed_action_rolled_back"])
        self.assertTrue(checks["text_restored"])
        self.assertTrue(checks["layout_snapshot_restored"])
        self.assertEqual(
            [name for name, passed in checks.items() if not passed],
            [],
        )

    def test_runtime_fault_detects_text_that_survives_rollback(self) -> None:
        checks = build_runtime_fault_checks(
            _tree(),
            _result(),
            _tree(text="Temporary runtime edit"),
        )

        self.assertFalse(checks["text_restored"])

    def test_runtime_fault_detects_layout_that_survives_rollback(self) -> None:
        checks = build_runtime_fault_checks(
            _tree(),
            _result(),
            _tree(row_gap=20),
        )

        self.assertFalse(checks["layout_snapshot_restored"])


if __name__ == "__main__":
    unittest.main()
