from __future__ import annotations

import unittest

from scripts.p1_s01_generation_drift_audit import summarize_s01_attempts


def _frame(generation: int | None) -> dict:
    return {
        "path": "root/0",
        "scope_path": "root/v0",
        "depth": 1,
        "visible_index": 0,
        "url": "https://example.com/frame",
        "src": "frame",
        "sandbox": "",
        "sandbox_present": False,
        "sandbox_tokens": [],
        "same_origin": True,
        "accessible": True,
        "opaque_frame": False,
        "opaque_reason": None,
        "navigation_state": "loaded",
        "x": 10,
        "y": 20,
        "width": 300,
        "height": 200,
        "rendered": True,
        "display": "block",
        "visibility": "visible",
        "opacity": 1.0,
        "document_generation": generation,
        "navigation_phase": "committed",
        "state": {},
    }


def _engine(
    *,
    stable: bool = True,
    generation: int | None = 0,
    navigation: str = "ok",
) -> dict:
    return {
        "status": "ok",
        "navigation": {"status": navigation},
        "page_state": {
            "capture_stability": {
                "stable": stable,
                "samples": 10 if stable else 51,
                "waited_ms": 600 if stable else 5000,
                "probe_errors": 0,
            },
            "frame_inventory": [_frame(generation)],
            "navigation_timeline": {
                "events": [],
                "frames": {
                    "root/0": {
                        "document_generation": generation,
                        "commit_count": 1 if generation is not None else 0,
                    }
                },
                "truncated": False,
            },
        },
        "frame_summary": {},
    }


class S01GenerationDriftAuditTests(unittest.TestCase):
    def test_primary_attempt_is_not_replaced_by_later_generation_drift(self) -> None:
        attempts = [
            {
                "attempt": 1,
                "engines": {
                    "chromium": _engine(stable=False),
                    "webkit": _engine(stable=True),
                },
                "state_gate": {
                    "comparable": False,
                    "reasons": ["state-unstable"],
                },
            },
            {
                "attempt": 2,
                "engines": {
                    "chromium": _engine(generation=0),
                    "webkit": _engine(generation=1),
                },
                "state_gate": {
                    "comparable": False,
                    "reasons": ["frame-document-generation-difference"],
                },
            },
        ]

        result = summarize_s01_attempts(attempts, selected_attempt=1)

        self.assertEqual(result["primary_attempt"], 1)
        self.assertEqual(
            result["primary_classification"],
            "execution-instability",
        )
        self.assertEqual(
            result["classification_counts"]["frame-generation-drift"],
            1,
        )
        self.assertEqual(
            result["attempts"][1]["generation_drift_paths"],
            ["root/v0"],
        )

    def test_navigation_failure_precedes_generation_observation(self) -> None:
        attempts = [{
            "attempt": 1,
            "engines": {
                "chromium": _engine(generation=0),
                "webkit": _engine(
                    generation=1,
                    navigation="browser-navigation-failed",
                ),
            },
            "state_gate": {
                "comparable": False,
                "reasons": ["frame-document-generation-difference"],
            },
        }]

        result = summarize_s01_attempts(attempts, selected_attempt=1)

        self.assertEqual(
            result["primary_classification"],
            "navigation-failure",
        )

    def test_missing_page_state_is_capture_failure(self) -> None:
        attempts = [{
            "attempt": 1,
            "engines": {
                "chromium": _engine(),
                "webkit": {
                    "status": "error",
                    "navigation": {"status": "capture-failed"},
                    "page_state": {},
                    "frame_summary": {},
                },
            },
            "state_gate": {
                "comparable": False,
                "reasons": ["capture-artifacts-missing"],
            },
        }]

        result = summarize_s01_attempts(attempts, selected_attempt=1)

        self.assertEqual(
            result["primary_classification"],
            "capture-failure",
        )


if __name__ == "__main__":
    unittest.main()
