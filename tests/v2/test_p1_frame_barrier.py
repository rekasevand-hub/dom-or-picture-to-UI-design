from __future__ import annotations

import time
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.app.services.structure.frame_barrier import (
    FrameBarrierGate,
    compare_frame_trees,
    frame_tree_key,
)
from scripts.p1_frame_barrier_experiment import _derive_pair_outcome, summarize_ab


def _frame(
    path: str,
    *,
    url: str = "https://example.com/frame",
    x: int = 10,
    width: int = 300,
) -> dict:
    return {
        "path": path,
        "scope_path": path.replace("root/", "root/v"),
        "depth": 1,
        "url": url,
        "navigation_state": "loaded",
        "rendered": True,
        "accessible": True,
        "opaque_frame": False,
        "opaque_reason": None,
        "x": x,
        "y": 20,
        "width": width,
        "height": 100,
    }


class FrameTreeComparisonTests(unittest.TestCase):
    def test_same_tree_matches(self) -> None:
        left = [_frame("root/0")]
        right = [_frame("root/0")]

        result = compare_frame_trees(left, right)

        self.assertTrue(result["match"])
        self.assertEqual(result["reasons"], [])
        self.assertEqual(frame_tree_key(left), frame_tree_key(right))

    def test_count_url_and_geometry_differences_are_reported(self) -> None:
        left = [_frame("root/0"), _frame("root/1")]
        right = [_frame("root/0", url="https://other.example/frame", x=30)]

        result = compare_frame_trees(left, right)

        self.assertFalse(result["match"])
        self.assertIn("frame-count-mismatch", result["reasons"])
        self.assertIn("frame-url-mismatch", result["reasons"])
        self.assertIn("frame-geometry-mismatch", result["reasons"])

    def test_unrendered_frames_are_excluded(self) -> None:
        hidden = _frame("root/0")
        hidden["rendered"] = False

        self.assertEqual(frame_tree_key([hidden]), [])


class FrameBarrierGateTests(unittest.TestCase):
    def test_matching_peers_synchronize(self) -> None:
        gate = FrameBarrierGate(timeout_s=1)
        frame = _frame("root/0")

        with ThreadPoolExecutor(max_workers=2) as pool:
            chromium = pool.submit(gate.sync, "chromium", [frame])
            webkit = pool.submit(gate.sync, "webkit", [frame])
            left = chromium.result(timeout=2)
            right = webkit.result(timeout=2)

        self.assertTrue(left["synchronized"])
        self.assertTrue(left["frame_tree_match"])
        self.assertTrue(right["synchronized"])
        self.assertTrue(right["frame_tree_match"])

    def test_different_peers_still_synchronize_but_report_mismatch(self) -> None:
        gate = FrameBarrierGate(timeout_s=1)

        with ThreadPoolExecutor(max_workers=2) as pool:
            chromium = pool.submit(
                gate.sync,
                "chromium",
                [_frame("root/0", x=10)],
            )
            webkit = pool.submit(
                gate.sync,
                "webkit",
                [_frame("root/0", x=40)],
            )
            results = [chromium.result(timeout=2), webkit.result(timeout=2)]

        self.assertTrue(all(item["synchronized"] for item in results))
        self.assertTrue(all(not item["frame_tree_match"] for item in results))
        self.assertTrue(all(
            "frame-geometry-mismatch" in item["reasons"] for item in results
        ))

    def test_timeout_is_recorded_without_waiting_for_missing_peer(self) -> None:
        gate = FrameBarrierGate(timeout_s=0.05)
        started = time.monotonic()

        result = gate.sync("chromium", [_frame("root/0")])

        self.assertLess(time.monotonic() - started, 1)
        self.assertFalse(result["synchronized"])
        self.assertIn("peer-timeout", result["reasons"])


class FrameBarrierExperimentTests(unittest.TestCase):
    def test_pair_outcome_recomputes_gate_from_attempt_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            attempts = []
            for attempt, barrier in (
                (1, {"synchronized": False, "frame_tree_match": False}),
                (2, {"synchronized": True, "frame_tree_match": False}),
            ):
                engines = {}
                for engine in ("chromium", "webkit"):
                    capture_dir = root / f"attempt-{attempt}" / engine
                    capture_dir.mkdir(parents=True)
                    dom = [{"tag": "p", "text": "same"}]
                    page_state = {
                        "final_url": "https://example.com/",
                        "frame_inventory": [],
                        "capture_stability": {
                            "stable": True,
                            "frame_barrier": barrier,
                        },
                    }
                    (capture_dir / "00_dom.json").write_text(
                        json.dumps(dom),
                        encoding="utf-8",
                    )
                    (capture_dir / "00_page_state.json").write_text(
                        json.dumps(page_state),
                        encoding="utf-8",
                    )
                    engines[engine] = {
                        "status": "ok",
                        "capture_dir": str(capture_dir),
                        "navigation": {"status": "ok"},
                        "page_state": page_state,
                        "frame_summary": {"opaque_frame_count": 0},
                    }
                attempts.append({
                    "attempt": attempt,
                    "content_comparable": False,
                    "text_delta": {"classification": "none"},
                    "state_gate": {
                        "comparable": False,
                        "reasons": ["state-unstable"],
                    },
                    "engines": engines,
                })

            selected, _ = _derive_pair_outcome({
                "state_attempts": attempts,
            })

        self.assertEqual(selected["attempt"], 2)
        self.assertEqual(selected["execution_status"], "ready")
        self.assertEqual(selected["comparison_result"], "different")
        self.assertIn(
            "frame-barrier-divergence",
            selected["state_gate"]["reasons"],
        )

    def test_pair_outcome_reselects_first_ready_under_current_barrier_rule(self) -> None:
        def engine(barrier: dict) -> dict:
            return {
                "status": "ok",
                "navigation": {"status": "ok"},
                "page_state": {
                    "capture_stability": {
                        "stable": True,
                        "frame_barrier": barrier,
                    }
                },
                "frame_summary": {"opaque_frame_count": 0},
            }

        summary = {
            "state_attempts": [
                {
                    "attempt": 1,
                    "content_comparable": False,
                    "text_delta": {"classification": "none"},
                    "state_gate": {
                        "comparable": False,
                        "reasons": ["frame-barrier-mismatch"],
                    },
                    "engines": {
                        "chromium": engine({
                            "synchronized": False,
                            "frame_tree_match": False,
                        }),
                        "webkit": engine({
                            "synchronized": False,
                            "frame_tree_match": False,
                        }),
                    },
                },
                {
                    "attempt": 2,
                    "content_comparable": False,
                    "text_delta": {"classification": "none"},
                    "state_gate": {
                        "comparable": False,
                        "reasons": ["frame-barrier-divergence"],
                    },
                    "engines": {
                        "chromium": engine({
                            "synchronized": True,
                            "frame_tree_match": False,
                        }),
                        "webkit": engine({
                            "synchronized": True,
                            "frame_tree_match": False,
                        }),
                    },
                },
            ]
        }

        selected, attempts = _derive_pair_outcome(summary)

        self.assertEqual(selected["attempt"], 2)
        self.assertEqual(selected["execution_status"], "ready")
        self.assertEqual(selected["comparison_result"], "different")
        self.assertEqual(len(attempts), 2)

    def test_summary_reports_inconclusive_to_different_change(self) -> None:
        result = summarize_ab([
            {
                "sample_id": "S01",
                "condition": "without-frame-barrier",
                "execution_status": "state-unstable",
                "comparison_result": "inconclusive",
                "selected_attempt": 1,
                "attempt_count": 3,
                "elapsed_s": 10,
                "state_gate": {
                    "chromium": {"text_count": 20},
                    "webkit": {"text_count": 24},
                },
                "text_alignment": {"coverage": 0.8},
            },
            {
                "sample_id": "S01",
                "condition": "with-frame-barrier",
                "execution_status": "ready",
                "comparison_result": "different",
                "selected_attempt": 2,
                "attempt_count": 2,
                "elapsed_s": 12,
                "state_gate": {
                    "chromium": {"text_count": 20},
                    "webkit": {"text_count": 20},
                },
                "text_alignment": {"coverage": 1.0},
                "barrier": {
                    "synchronized": True,
                    "frame_tree_match": False,
                },
            },
        ])

        change = result["samples"]["S01"]["change"]
        self.assertEqual(change["from"], "inconclusive")
        self.assertEqual(change["to"], "different")
        self.assertTrue(change["became_ready"])
        drift = result["samples"]["S01"]["drift"]
        self.assertTrue(drift["text_drift_reduced"])
        self.assertTrue(drift["coverage_increased"])
        self.assertEqual(drift["text_count_delta_after"], 0)

    def test_summary_never_calls_barrier_mismatch_equivalent(self) -> None:
        result = summarize_ab([
            {
                "sample_id": "S03",
                "condition": "with-frame-barrier",
                "execution_status": "state-unstable",
                "comparison_result": "inconclusive",
                "barrier": {
                    "synchronized": True,
                    "frame_tree_match": False,
                },
            },
        ])

        sample = result["samples"]["S03"]
        self.assertEqual(sample["comparison_result"], "inconclusive")
        self.assertFalse(result["false_equivalence_detected"])


if __name__ == "__main__":
    unittest.main()
