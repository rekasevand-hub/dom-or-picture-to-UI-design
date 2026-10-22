from __future__ import annotations

import unittest

from src.app.services.structure.capture_outcome import classify_capture_outcome


def _engine(
    *,
    navigation_status: str = "ok",
    stable: bool = True,
    opaque_frames: int = 0,
) -> dict:
    return {
        "status": "ok",
        "navigation": {"status": navigation_status},
        "page_state": {"capture_stability": {"stable": stable}},
        "frame_summary": {"opaque_frame_count": opaque_frames},
    }


class CaptureOutcomeTests(unittest.TestCase):
    def test_stable_difference_is_different_not_inconclusive(self) -> None:
        gate = {
            "comparable": False,
            "reasons": ["text-mismatch", "node-count-mismatch"],
        }

        outcome = classify_capture_outcome(
            gate,
            {"chromium": _engine(), "webkit": _engine()},
            {"classification": "text-difference"},
            content_comparable=False,
        )

        self.assertEqual(outcome["execution_status"], "ready")
        self.assertEqual(outcome["comparison_result"], "different")
        self.assertEqual(
            outcome["comparison_reasons"],
            ["observed-content-divergence", "observed-structure-divergence"],
        )

    def test_navigation_failure_is_inconclusive(self) -> None:
        gate = {"comparable": False, "reasons": ["url-mismatch"]}

        outcome = classify_capture_outcome(
            gate,
            {
                "chromium": _engine(),
                "webkit": _engine(navigation_status="browser-navigation-failed"),
            },
            None,
            content_comparable=False,
        )

        self.assertEqual(outcome["execution_status"], "navigation-failed")
        self.assertEqual(outcome["comparison_result"], "inconclusive")
        self.assertEqual(outcome["execution_reasons"], ["navigation-failed"])
        self.assertEqual(outcome["comparison_reasons"], ["navigation-failed"])

    def test_state_unstable_is_inconclusive(self) -> None:
        gate = {"comparable": False, "reasons": ["state-unstable"]}

        outcome = classify_capture_outcome(
            gate,
            {
                "chromium": _engine(),
                "webkit": _engine(stable=False),
            },
            None,
            content_comparable=False,
        )

        self.assertEqual(outcome["execution_status"], "state-unstable")
        self.assertEqual(outcome["comparison_result"], "inconclusive")
        self.assertEqual(outcome["comparison_reasons"], ["state-unmatched"])

    def test_capture_error_is_capture_failed(self) -> None:
        engine = _engine()
        engine["status"] = "error"

        outcome = classify_capture_outcome(
            {"comparable": False, "reasons": ["capture-artifacts-missing"]},
            {"chromium": engine, "webkit": _engine()},
            None,
            content_comparable=False,
        )

        self.assertEqual(outcome["execution_status"], "capture-failed")
        self.assertEqual(outcome["comparison_result"], "inconclusive")

    def test_opaque_frames_are_a_limitation_not_an_equality_claim(self) -> None:
        outcome = classify_capture_outcome(
            {"comparable": True, "reasons": []},
            {
                "chromium": _engine(opaque_frames=1),
                "webkit": _engine(opaque_frames=1),
            },
            None,
            content_comparable=True,
        )

        self.assertEqual(outcome["comparison_result"], "equivalent")
        self.assertIn("observation-opaque", outcome["limitations"])
        self.assertNotIn("opaque-frame-contents", outcome["claims"])

    def test_synchronized_frame_tree_divergence_is_different(self) -> None:
        barrier = {
            "synchronized": True,
            "frame_tree_match": False,
        }
        left = _engine()
        right = _engine()
        left["page_state"] = {
            "capture_stability": {"stable": True, "frame_barrier": barrier}
        }
        right["page_state"] = {
            "capture_stability": {"stable": True, "frame_barrier": barrier}
        }

        outcome = classify_capture_outcome(
            {
                "comparable": False,
                "reasons": ["frame-barrier-divergence"],
            },
            {"chromium": left, "webkit": right},
            None,
            content_comparable=False,
        )

        self.assertEqual(outcome["execution_status"], "ready")
        self.assertEqual(outcome["comparison_result"], "different")
        self.assertEqual(
            outcome["comparison_reasons"],
            ["observed-structure-divergence"],
        )

    def test_explicit_profile_is_reported_without_renaming_old_scope(self) -> None:
        outcome = classify_capture_outcome(
            {"comparable": True, "reasons": []},
            {"chromium": _engine(), "webkit": _engine()},
            None,
            content_comparable=True,
            profile_id="first-party-frame-strict/1.0",
        )

        self.assertEqual(outcome["scope"], "first-party-frame-strict/1.0")
        self.assertNotEqual(outcome["scope"], "rendered-frame-state-strict/1.0")

    def test_boundary_equivalent_claim_is_scope_limited(self) -> None:
        outcome = classify_capture_outcome(
            {"comparable": True, "reasons": []},
            {"chromium": _engine(), "webkit": _engine(opaque_frames=1)},
            None,
            content_comparable=False,
            profile_id="rendered-frame-boundary-strict/1.0",
        )

        self.assertEqual(outcome["comparison_result"], "equivalent")
        self.assertEqual(
            outcome["claims"],
            ["rendered-frame-boundary-equivalent"],
        )
        self.assertIn("observation-opaque", outcome["limitations"])

    def test_boundary_observation_differences_are_structured_reasons(self) -> None:
        outcome = classify_capture_outcome(
            {
                "comparable": False,
                "reasons": [
                    "frame-host-geometry-difference",
                    "frame-url-observation-difference",
                ],
            },
            {"chromium": _engine(), "webkit": _engine()},
            None,
            content_comparable=False,
            profile_id="rendered-frame-boundary-strict/1.0",
        )

        self.assertEqual(outcome["comparison_result"], "different")
        self.assertEqual(
            outcome["comparison_reasons"],
            [
                "observed-navigation-divergence",
                "observed-structure-divergence",
            ],
        )

    def test_incomplete_boundary_observation_is_not_ready_for_difference(self) -> None:
        outcome = classify_capture_outcome(
            {
                "comparable": False,
                "reasons": ["frame-document-generation-unobservable"],
                "boundary_observation_complete": False,
            },
            {"chromium": _engine(), "webkit": _engine()},
            None,
            content_comparable=False,
            profile_id="rendered-frame-boundary-strict/1.0",
        )

        self.assertEqual(outcome["execution_status"], "state-unstable")
        self.assertEqual(outcome["comparison_result"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
