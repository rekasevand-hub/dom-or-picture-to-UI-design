from __future__ import annotations

import unittest

from scripts.p1_rendered_frame_boundary_experiment import (
    _boundary_result,
    summarize_boundary_experiment,
)


class RenderedFrameBoundaryExperimentTests(unittest.TestCase):
    def test_old_strict_first_party_and_boundary_are_reported_separately(self) -> None:
        runs = [
            {
                "sample_id": "S03",
                "condition": "full-visible",
                "execution_status": "ready",
                "comparison_result": "different",
                "capture_profile": "rendered-frame-state-strict/1.0",
            },
            {
                "sample_id": "S03",
                "condition": "first-party-frame",
                "execution_status": "ready",
                "comparison_result": "different",
                "capture_profile": "first-party-frame-strict/1.0",
                "blocked_document_count": 4,
            },
            {
                "sample_id": "S03",
                "condition": "rendered-frame-boundary",
                "execution_status": "ready",
                "comparison_result": "equivalent",
                "capture_profile": "rendered-frame-state-strict/1.0",
                "comparison_profile": "rendered-frame-boundary-strict/1.0",
                "rendered_frame_boundary": {
                    "comparable": True,
                    "claims": ["rendered-frame-boundary-equivalent"],
                    "opaque_contents_observable": False,
                },
            },
        ]

        summary = summarize_boundary_experiment(runs)
        sample = summary["samples"]["S03"]

        self.assertEqual(
            sample["legacy_full_visible"]["comparison_result"],
            "different",
        )
        self.assertEqual(
            sample["first_party_scope"]["comparison_result"],
            "different",
        )
        self.assertEqual(
            sample["rendered_boundary_scope"]["comparison_result"],
            "equivalent",
        )
        self.assertFalse(summary["page_equivalence_claimed"])
        self.assertFalse(summary["false_equivalence_detected"])

    def test_boundary_result_with_wrong_profile_is_false_equivalence(self) -> None:
        summary = summarize_boundary_experiment([{
            "sample_id": "S05",
            "condition": "rendered-frame-boundary",
            "execution_status": "ready",
            "comparison_result": "equivalent",
            "capture_profile": "rendered-frame-state-strict/1.0",
            "comparison_profile": "rendered-frame-state-strict/1.0",
            "rendered_frame_boundary": {
                "comparable": True,
                "claims": ["rendered-frame-state-equivalent"],
            },
        }])

        self.assertTrue(summary["false_equivalence_detected"])
        self.assertEqual(summary["profile_mismatches"][0]["sample_id"], "S05")

    def test_nested_boundary_gate_uses_inner_result_for_claims_and_metrics(self) -> None:
        gate = {
            "comparable": True,
            "boundary": {
                "comparable": True,
                "claims": ["rendered-frame-boundary-equivalent"],
                "opaque_contents_observable": False,
                "unobservable": [{"scope": "root/v0"}],
                "excluded": {"left": [], "right": [{"path": "root/0"}]},
            },
        }

        boundary = _boundary_result(gate)

        self.assertEqual(
            boundary["claims"],
            ["rendered-frame-boundary-equivalent"],
        )
        self.assertEqual(len(boundary["unobservable"]), 1)


if __name__ == "__main__":
    unittest.main()
