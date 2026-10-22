from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.p1_navigation_timeline_probe import (
    recover_partial_attempts,
    summarize_navigation_attempts,
)


def _engine(
    navigation_status: str,
    *,
    events: list[dict] | None = None,
    stable: bool = True,
) -> dict:
    return {
        "status": "ok",
        "navigation": {"status": navigation_status},
        "page_state": {
            "capture_stability": {"stable": stable},
            "navigation_timeline": {
                "events": events or [],
                "frames": {
                    "root": {
                        "document_generation": 0,
                        "commit_count": 1,
                    }
                },
                "truncated": False,
            },
        },
        "frame_summary": {},
    }


class NavigationTimelineProbeTests(unittest.TestCase):
    def test_navigation_failure_is_not_reported_as_stable_dom_difference(self) -> None:
        attempts = [{
            "attempt": 1,
            "state_gate": {"comparable": False, "reasons": ["state-unstable"]},
            "engines": {
                "chromium": _engine("ok"),
                "webkit": _engine(
                    "browser-navigation-failed",
                    events=[{
                        "kind": "document-request-failed",
                        "url": "https://example.com/",
                        "failure": "net::ERR_TIMED_OUT",
                    }],
                ),
            },
        }]

        summary = summarize_navigation_attempts(attempts, selected_attempt=1)

        self.assertEqual(summary["classification"], "navigation-failure")
        self.assertEqual(
            summary["selected_attempt_reason"],
            "navigation-failed-before-comparable-dom",
        )
        self.assertEqual(summary["request_failed_count"], 1)
        self.assertFalse(summary["stable_dom_difference_claimed"])

    def test_committed_navigation_with_text_delta_is_stable_dom_difference(self) -> None:
        attempts = [{
            "attempt": 1,
            "state_gate": {
                "comparable": False,
                "reasons": ["text-mismatch"],
            },
            "engines": {
                "chromium": _engine(
                    "ok",
                    events=[{
                        "kind": "document-response",
                        "status": 200,
                        "url": "https://example.com/",
                    }],
                ),
                "webkit": _engine(
                    "redirected",
                    events=[
                        {
                            "kind": "document-response",
                            "status": 302,
                            "url": "https://example.com/start",
                        },
                        {
                            "kind": "document-commit",
                            "frame_path": "root",
                            "document_generation": 0,
                        },
                    ],
                ),
            },
        }]

        summary = summarize_navigation_attempts(attempts, selected_attempt=1)

        self.assertEqual(summary["classification"], "stable-dom-difference")
        self.assertEqual(
            summary["selected_attempt_reason"],
            "navigation-committed-stable-dom-difference",
        )
        self.assertTrue(summary["stable_dom_difference_claimed"])
        self.assertEqual(summary["response_statuses"], [200, 302])

    def test_first_ready_attempt_is_the_only_primary_classification(self) -> None:
        attempts = [
            {
                "attempt": 1,
                "state_gate": {"comparable": False, "reasons": ["state-unstable"]},
                "engines": {
                    "chromium": _engine("ok"),
                    "webkit": _engine("browser-navigation-failed"),
                },
            },
            {
                "attempt": 2,
                "state_gate": {"comparable": False, "reasons": ["text-mismatch"]},
                "engines": {
                    "chromium": _engine("ok"),
                    "webkit": _engine("ok"),
                },
            },
        ]

        summary = summarize_navigation_attempts(attempts, selected_attempt=2)

        self.assertEqual(summary["classification"], "stable-dom-difference")
        self.assertEqual(summary["primary_attempt"], 2)
        self.assertEqual(len(summary["attempts"]), 2)

    def test_partial_sidecars_are_recovered_when_pair_summary_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sidecars" / "timeline-S06-round1"
            for engine, navigation_status in (
                ("chromium", "ok"),
                ("webkit", "browser-navigation-failed"),
            ):
                engine_root = root / "_attempt_01" / engine
                engine_root.mkdir(parents=True)
                (engine_root / "00_dom.json").write_text("[]", encoding="utf-8")
                (engine_root / "00_page_state.json").write_text(
                    json.dumps({
                        "final_url": "https://example.com/",
                        "capture_stability": {"stable": True},
                        "navigation": {"status": navigation_status},
                        "frame_inventory": [],
                        "frame_summary": {},
                        "navigation_timeline": {
                            "events": [{
                                "kind": "document-request-failed",
                                "url": "https://example.com/",
                            }],
                            "frames": {"root": {"document_generation": 0}},
                        },
                    }),
                    encoding="utf-8",
                )

            attempts = recover_partial_attempts(root)

        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["attempt"], 1)
        self.assertEqual(
            attempts[0]["engines"]["webkit"]["navigation"]["status"],
            "browser-navigation-failed",
        )

    def test_recovery_reads_capture_artifacts_when_sidecars_are_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sidecar_root = root / "sidecars" / "timeline-S06-round1"
            capture_root = root / "captures" / "timeline-S06-round1"
            sidecar_root.mkdir(parents=True)
            for engine, navigation_status in (
                ("chromium", "ok"),
                ("webkit", "browser-navigation-failed"),
            ):
                engine_root = capture_root / "_attempt_01" / engine
                engine_root.mkdir(parents=True)
                (engine_root / "00_dom.json").write_text("[]", encoding="utf-8")
                (engine_root / "00_page_state.json").write_text(
                    json.dumps({
                        "final_url": "https://example.com/",
                        "capture_stability": {"stable": True},
                        "navigation": {"status": navigation_status},
                        "frame_inventory": [],
                        "frame_summary": {},
                        "navigation_timeline": {
                            "events": [],
                            "frames": {"root": {"document_generation": 0}},
                        },
                    }),
                    encoding="utf-8",
                )

            attempts = recover_partial_attempts(
                sidecar_root,
                capture_run_root=capture_root,
            )

        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["engines"]["chromium"]["status"], "ok")
        self.assertEqual(
            attempts[0]["engines"]["webkit"]["navigation"]["status"],
            "browser-navigation-failed",
        )


if __name__ == "__main__":
    unittest.main()
