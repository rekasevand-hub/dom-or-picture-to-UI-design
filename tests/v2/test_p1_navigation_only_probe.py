from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from scripts.p1_navigation_only_probe import (
    load_observation_file,
    summarize_navigation_only,
)


def _observation(
    engine: str,
    status: str,
    *,
    attempt: int = 1,
    valid: bool = True,
    failed_events: int = 0,
    responses: int = 0,
    commits: int = 0,
) -> dict:
    events = []
    events.extend(
        {"kind": "document-request-failed", "url": "https://example.com/"}
        for _ in range(failed_events)
    )
    events.extend(
        {"kind": "document-response", "status": 200}
        for _ in range(responses)
    )
    events.extend(
        {"kind": "document-commit", "frame_path": "root"}
        for _ in range(commits)
    )
    return {
        "engine": engine,
        "attempt": attempt,
        "valid": valid,
        "navigation": {"status": status},
        "final_url": (
            "https://example.com/"
            if status in {"ok", "redirected"}
            else "about:blank"
        ),
        "timeline": {"events": events, "frames": {}},
    }


class NavigationOnlyProbeTests(unittest.TestCase):
    def test_first_attempt_navigation_failure_remains_primary(self) -> None:
        summary = summarize_navigation_only([
            _observation("chromium", "ok", failed_events=0, responses=1, commits=1),
            _observation(
                "webkit",
                "browser-navigation-failed",
                failed_events=1,
            ),
            _observation("chromium", "ok", attempt=2, responses=1, commits=1),
            _observation("webkit", "ok", attempt=2, responses=1, commits=1),
        ])

        self.assertEqual(summary["classification"], "navigation-failure")
        self.assertEqual(summary["primary_attempt"], 1)
        self.assertTrue(summary["later_navigation_recovered"])
        self.assertFalse(summary["stable_dom_difference_claimed"])
        self.assertFalse(summary["dom_difference_evaluated"])
        self.assertEqual(summary["request_failed_count"], 1)

    def test_two_committed_documents_are_only_navigation_comparable(self) -> None:
        summary = summarize_navigation_only([
            _observation("chromium", "ok", responses=1, commits=1),
            _observation("webkit", "redirected", responses=2, commits=1),
        ])

        self.assertEqual(summary["classification"], "navigation-comparable")
        self.assertFalse(summary["stable_dom_difference_claimed"])
        self.assertFalse(summary["dom_difference_evaluated"])
        self.assertEqual(summary["response_count"], 3)
        self.assertEqual(summary["commit_count"], 2)

    def test_invalid_worker_is_capture_failure_not_navigation_absence(self) -> None:
        failed = _observation(
            "webkit",
            "capture-failed",
            valid=False,
        )
        failed["error"] = "worker-timeout"
        summary = summarize_navigation_only([
            _observation("chromium", "ok", responses=1, commits=1),
            failed,
        ])

        self.assertEqual(summary["classification"], "capture-failure")
        self.assertFalse(summary["stable_dom_difference_claimed"])

    def test_committed_navigation_with_document_failure_keeps_warning(self) -> None:
        summary = summarize_navigation_only([
            _observation(
                "chromium",
                "ok",
                failed_events=1,
                responses=1,
                commits=1,
            ),
            _observation(
                "webkit",
                "ok",
                failed_events=1,
                responses=1,
                commits=1,
            ),
        ])

        self.assertEqual(
            summary["classification"],
            "navigation-comparable-with-document-failures",
        )
        self.assertFalse(summary["stable_dom_difference_claimed"])

    def test_existing_observations_can_be_resummarized_without_new_network_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "probe.json"
            observations = [
                _observation("chromium", "ok", responses=1, commits=1),
                _observation("webkit", "ok", responses=1, commits=1),
            ]
            path.write_text(
                json.dumps({"observations": observations}),
                encoding="utf-8",
            )

            loaded = load_observation_file(path)

        self.assertEqual(loaded, observations)

    def test_later_navigation_failure_is_reported_without_replacing_primary(self) -> None:
        summary = summarize_navigation_only([
            _observation("chromium", "ok", responses=1, commits=1),
            _observation("webkit", "ok", responses=1, commits=1),
            _observation("chromium", "ok", attempt=2, responses=1, commits=1),
            _observation(
                "webkit",
                "browser-navigation-failed",
                attempt=2,
                failed_events=1,
            ),
        ])

        self.assertEqual(summary["classification"], "navigation-comparable")
        self.assertTrue(summary["later_navigation_failed"])
        self.assertFalse(summary["stable_dom_difference_claimed"])


if __name__ == "__main__":
    unittest.main()
