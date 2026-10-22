from __future__ import annotations

import unittest

from scripts.p1_first_party_scope_experiment import summarize_scope_experiment


class FirstPartyScopeExperimentTests(unittest.TestCase):
    def test_profile_result_is_reported_separately_from_full_visible(self) -> None:
        summary = summarize_scope_experiment([
            {
                "sample_id": "S01",
                "condition": "full-visible",
                "execution_status": "state-unstable",
                "comparison_result": "inconclusive",
                "capture_profile": "rendered-frame-state-strict/1.0",
            },
            {
                "sample_id": "S01",
                "condition": "first-party-frame",
                "execution_status": "ready",
                "comparison_result": "equivalent",
                "capture_profile": "first-party-frame-strict/1.0",
                "blocked_document_count": 3,
            },
        ])

        sample = summary["samples"]["S01"]
        self.assertEqual(sample["baseline"]["comparison_result"], "inconclusive")
        self.assertEqual(
            sample["first_party"]["capture_profile"],
            "first-party-frame-strict/1.0",
        )
        self.assertFalse(summary["false_equivalence_detected"])

    def test_scope_result_with_wrong_profile_is_rejected(self) -> None:
        summary = summarize_scope_experiment([
            {
                "sample_id": "S03",
                "condition": "first-party-frame",
                "execution_status": "ready",
                "comparison_result": "equivalent",
                "capture_profile": "rendered-frame-state-strict/1.0",
            },
        ])

        self.assertTrue(summary["false_equivalence_detected"])


if __name__ == "__main__":
    unittest.main()
