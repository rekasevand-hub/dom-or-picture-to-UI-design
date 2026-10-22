from __future__ import annotations

import unittest

from src.app.services.structure.capture import _wait_capture_state, _wait_document_fonts
from src.app.services.structure.capture_state import (
    capture_state_signature,
    evaluate_state_gate,
    state_window_is_stable,
)
from scripts.p1_dual_browser_capture import (
    _content_comparable,
    _select_accepted_attempt,
)


def _dom(*nodes: dict) -> list[dict]:
    return list(nodes)


def _page(url: str = "https://example.com/page") -> dict:
    return {
        "final_url": url,
        "capture_stability": {"stable": True},
    }


class CaptureStateSignatureTests(unittest.TestCase):
    def test_structure_signature_uses_asset_source_not_only_node_count(self) -> None:
        left = _dom(
            {"tag": "div", "text": "", "x": 0, "y": 0, "w": 10, "h": 10},
            {
                "tag": "img",
                "text": "",
                "x": 0,
                "y": 0,
                "w": 10,
                "h": 10,
                "assetSrc": "https://example.com/a.png",
            },
        )
        right = _dom(
            {"tag": "div", "text": "", "x": 0, "y": 0, "w": 10, "h": 10},
            {
                "tag": "img",
                "text": "",
                "x": 0,
                "y": 0,
                "w": 10,
                "h": 10,
                "assetSrc": "https://example.com/b.png",
            },
        )

        gate = evaluate_state_gate(left, _page(), right, _page())

        self.assertFalse(gate["comparable"])
        self.assertEqual(gate["reasons"], ["structure-mismatch"])
        self.assertNotEqual(
            capture_state_signature(left, _page())["structure_sha256"],
            capture_state_signature(right, _page())["structure_sha256"],
        )

    def test_strict_gate_requires_stable_capture_when_requested(self) -> None:
        dom = _dom({"tag": "p", "text": "same", "x": 0, "y": 0, "w": 10, "h": 10})
        unstable = _page()
        unstable["capture_stability"] = {"stable": False}

        gate = evaluate_state_gate(
            dom,
            unstable,
            dom,
            _page(),
            require_stability=True,
        )

        self.assertFalse(gate["comparable"])
        self.assertEqual(gate["reasons"], ["state-unstable"])

    def test_strict_gate_rejects_unsynchronized_frame_barrier(self) -> None:
        dom = _dom({"tag": "p", "text": "same"})
        left = _page()
        left["capture_stability"] = {
            "stable": True,
            "frame_barrier": {
                "synchronized": False,
                "frame_tree_match": False,
            },
        }

        gate = evaluate_state_gate(
            dom,
            left,
            dom,
            _page(),
            require_stability=True,
        )

        self.assertFalse(gate["comparable"])
        self.assertIn("frame-barrier-mismatch", gate["reasons"])

    def test_synchronized_frame_tree_difference_is_observed_not_state_unstable(self) -> None:
        dom = _dom({"tag": "p", "text": "same"})
        barrier = {
            "synchronized": True,
            "frame_tree_match": False,
        }
        left = _page()
        right = _page()
        left["capture_stability"] = {"stable": True, "frame_barrier": barrier}
        right["capture_stability"] = {"stable": True, "frame_barrier": barrier}

        gate = evaluate_state_gate(
            dom,
            left,
            dom,
            right,
            require_stability=True,
        )

        self.assertFalse(gate["comparable"])
        self.assertEqual(gate["reasons"], ["frame-barrier-divergence"])
        self.assertNotIn("state-unstable", gate["reasons"])


class StateWindowTests(unittest.TestCase):
    def test_stable_window_requires_continuously_equal_samples(self) -> None:
        self.assertTrue(
            state_window_is_stable(["a", "a", "a", "a"], poll_ms=100, stable_ms=300)
        )
        self.assertFalse(
            state_window_is_stable(["a", "a", "b", "b", "b"], poll_ms=100, stable_ms=300)
        )

    def test_attempt_selection_uses_first_ready_capture(self) -> None:
        history = [
            {"attempt": 1, "execution_status": "navigation-failed"},
            {"attempt": 2, "execution_status": "ready", "comparison_result": "different"},
            {"attempt": 3, "execution_status": "ready", "comparison_result": "equivalent"},
        ]

        selected = _select_accepted_attempt(history)

        self.assertEqual(selected["attempt"], 2)

    def test_attempt_selection_does_not_pick_later_strict_over_first_ready(self) -> None:
        history = [
            {"attempt": 1, "execution_status": "ready", "comparison_result": "different"},
            {"attempt": 2, "execution_status": "ready", "comparison_result": "equivalent"},
        ]

        self.assertEqual(_select_accepted_attempt(history)["attempt"], 1)

    def test_all_inconclusive_attempts_keep_first_for_audit_without_ranking(self) -> None:
        history = [
            {"attempt": 1, "execution_status": "navigation-failed"},
            {"attempt": 2, "execution_status": "state-unstable"},
        ]

        self.assertEqual(_select_accepted_attempt(history)["attempt"], 1)

    def test_dual_content_scope_requires_text_hash_and_coverage(self) -> None:
        gate = {
            "comparable": False,
            "chromium": {
                "url": "https://example.com/",
                "text_sha256": "same",
            },
            "webkit": {
                "url": "https://example.com/",
                "text_sha256": "same",
            },
        }

        self.assertTrue(_content_comparable(gate, {"coverage": 0.95}))
        self.assertFalse(_content_comparable(gate, {"coverage": 0.949}))
        gate["webkit"]["text_sha256"] = "different"
        self.assertFalse(_content_comparable(gate, {"coverage": 1.0}))


class _FakePage:
    def __init__(self, signatures: list[object]) -> None:
        self._signatures = iter(signatures)
        self._last = signatures[-1]

    def evaluate(self, _script: str) -> dict:
        value = next(self._signatures, self._last)
        if isinstance(value, Exception):
            raise value
        return value

    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


class CaptureStabilityProbeTests(unittest.TestCase):
    def test_wait_capture_state_returns_stable_signature(self) -> None:
        signature = {"visible_nodes": 4, "total_nodes": 6, "hash": "stable"}
        result = _wait_capture_state(
            _FakePage([signature, signature, signature, signature]),
            poll_ms=100,
            stable_ms=300,
            cap_ms=1000,
        )

        self.assertTrue(result["stable"])
        self.assertEqual(result["signature"], signature)
        self.assertGreaterEqual(result["stable_ms"], 300)

    def test_wait_capture_state_fails_closed_for_alternating_state(self) -> None:
        left = {"visible_nodes": 4, "total_nodes": 6, "hash": "left"}
        right = {"visible_nodes": 5, "total_nodes": 6, "hash": "right"}
        result = _wait_capture_state(
            _FakePage([left, right, left, right, left, right]),
            poll_ms=100,
            stable_ms=300,
            cap_ms=500,
        )

        self.assertFalse(result["stable"])

    def test_wait_capture_state_retries_transient_probe_error(self) -> None:
        signature = {"visible_nodes": 4, "total_nodes": 6, "hash": "stable"}
        result = _wait_capture_state(
            _FakePage([RuntimeError("document replaced"), *([signature] * 4)]),
            poll_ms=100,
            stable_ms=300,
            cap_ms=1000,
        )

        self.assertTrue(result["stable"])
        self.assertEqual(result["probe_errors"], 1)

    def test_probe_error_resets_partial_stable_window(self) -> None:
        signature = {"visible_nodes": 4, "total_nodes": 6, "hash": "stable"}
        result = _wait_capture_state(
            _FakePage([
                signature,
                signature,
                RuntimeError("document replaced"),
                *([signature] * 4),
            ]),
            poll_ms=100,
            stable_ms=300,
            cap_ms=200,
        )

        self.assertFalse(result["stable"])
        self.assertEqual(result["samples"], 1)
        self.assertEqual(result["probe_errors"], 1)

    def test_wait_document_fonts_reports_loaded_and_timeout(self) -> None:
        loaded = _wait_document_fonts(
            _FakePage(["loading", "loaded"]),
            poll_ms=100,
            timeout_ms=300,
        )
        timed_out = _wait_document_fonts(
            _FakePage(["loading"]),
            poll_ms=100,
            timeout_ms=100,
        )

        self.assertTrue(loaded["ready"])
        self.assertEqual(loaded["status"], "loaded")
        self.assertFalse(timed_out["ready"])
        self.assertEqual(timed_out["status"], "loading")


if __name__ == "__main__":
    unittest.main()
