from __future__ import annotations

import unittest
from pathlib import Path

from scripts.p1_frame_boundary_holdout import run_frame_boundary_holdout


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "p1"
    / "frame_boundary_holdout.json"
)


class FrameBoundaryHoldoutTests(unittest.TestCase):
    def test_authored_holdout_covers_scope_traps_without_false_equivalence(self) -> None:
        result = run_frame_boundary_holdout(FIXTURE)

        self.assertEqual(result["summary"]["case_count"], 9)
        self.assertEqual(result["summary"]["passed_count"], 9)
        self.assertEqual(result["summary"]["failed_count"], 0)
        self.assertFalse(result["summary"]["false_equivalence_detected"])
        self.assertFalse(result["summary"]["page_equivalence_claimed"])
        self.assertGreaterEqual(
            result["summary"]["content_changed_boundary_equivalent_count"],
            3,
        )
        self.assertRegex(result["result_sha256"], r"^[0-9a-f]{64}$")

        by_id = {
            item["case_id"]: item
            for item in result["cases"]
        }
        self.assertEqual(
            by_id["same-url-swap"]["actual"]["reasons"],
            [
                "frame-url-observation-difference",
                "frame-src-observation-difference",
            ],
        )
        self.assertEqual(
            by_id["same-boundary-different-content"]["actual"]["claims"],
            ["rendered-frame-boundary-equivalent"],
        )
        self.assertTrue(
            by_id["opaque-placeholder-different"]["actual"][
                "opaque_contents_observable"
            ]
            is False
        )
        self.assertIn(
            "frame-document-generation-difference",
            by_id["document-generation-drift"]["actual"]["reasons"],
        )
        self.assertIn(
            "frame-topology-difference",
            by_id["nested-parent-child-drift"]["actual"]["reasons"],
        )
        self.assertEqual(
            by_id["sandbox-token-order"]["actual"]["claims"],
            ["rendered-frame-boundary-equivalent"],
        )
        self.assertTrue(
            by_id["mixed-accessible-opaque"]["actual"]["comparable"]
        )
        self.assertEqual(
            len(by_id["mixed-accessible-opaque"]["actual"]["unobservable"]),
            1,
        )
        self.assertTrue(
            by_id["sandbox-opaque-same-token"]["actual"]["comparable"]
        )


if __name__ == "__main__":
    unittest.main()
