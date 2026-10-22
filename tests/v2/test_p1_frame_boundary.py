from __future__ import annotations

import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from src.app import tuning
from src.app.services.structure.capture import capture_page
from src.app.services.structure.frame_boundary import (
    build_frame_boundary_snapshot,
    compare_rendered_frame_boundaries,
)
from src.app.services.structure.navigation_timeline import NavigationTimeline
from src.config.settings import Config
from scripts.p1_dual_browser_capture import _boundary_gate


def _frame(
    scope_path: str,
    *,
    url: str = "https://example.com/frame",
    x: int = 10,
    y: int = 20,
    width: int = 300,
    height: int = 200,
    sandbox: str = "",
    opaque_reason: str | None = None,
    generation: int | None = 0,
    navigation_phase: str = "committed",
    state: dict | None = None,
) -> dict:
    return {
        "path": scope_path.replace("/v", "/"),
        "scope_path": scope_path,
        "depth": max(1, scope_path.count("/")),
        "url": url,
        "src": url,
        "sandbox": sandbox,
        "sandbox_present": bool(sandbox),
        "sandbox_tokens": sandbox.split(),
        "same_origin": opaque_reason != "cross-origin",
        "accessible": opaque_reason is None,
        "opaque_frame": opaque_reason is not None,
        "opaque_reason": opaque_reason,
        "navigation_state": "loaded",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "rendered": True,
        "display": "inline",
        "visibility": "visible",
        "opacity": 1.0,
        "document_generation": generation,
        "navigation_phase": navigation_phase,
        "state": state or {},
    }


def _page(*frames: dict) -> dict:
    return {
        "final_url": "https://example.com/",
        "capture_stability": {"stable": True},
        "frame_inventory": list(frames),
    }


class RenderedFrameBoundaryTests(unittest.TestCase):
    def test_frame_identity_is_topology_first_and_url_is_an_observation(self) -> None:
        left = _page(_frame("root/v0", url="https://a.example/frame"))
        right = _page(_frame("root/v0", url="https://b.example/frame"))

        result = compare_rendered_frame_boundaries(left, right)

        self.assertFalse(result["comparable"])
        self.assertEqual(result["identity_match_count"], 1)
        self.assertIn("frame-url-observation-difference", result["reasons"])
        self.assertNotIn("frame-topology-difference", result["reasons"])
        self.assertNotIn("url", result["identity_fields"])

    def test_same_url_at_different_visible_positions_is_not_the_same_boundary(self) -> None:
        left = _page(
            _frame("root/v0", width=320),
            _frame("root/v1", width=970),
        )
        right = _page(
            _frame("root/v1", width=320),
            _frame("root/v0", width=970),
        )

        result = compare_rendered_frame_boundaries(left, right)

        self.assertFalse(result["comparable"])
        self.assertEqual(result["identity_match_count"], 2)
        self.assertNotIn("frame-topology-difference", result["reasons"])
        self.assertIn("frame-host-geometry-difference", result["reasons"])

    def test_host_geometry_and_navigation_phase_are_compared_for_matched_identity(self) -> None:
        left = _page(
            _frame("root/v0"),
            _frame("root/v0/v0", x=12, width=180, navigation_phase="committed"),
        )
        right = _page(
            _frame("root/v0"),
            _frame("root/v0/v0", x=14, width=190, navigation_phase="navigating"),
        )

        result = compare_rendered_frame_boundaries(left, right)

        self.assertFalse(result["comparable"])
        self.assertIn("frame-host-geometry-difference", result["reasons"])
        self.assertIn("frame-navigation-phase-difference", result["reasons"])

    def test_frame_count_difference_is_reported_as_topology_difference(self) -> None:
        left = _page(_frame("root/v0"))
        right = _page(_frame("root/v0"), _frame("root/v1"))

        result = compare_rendered_frame_boundaries(left, right)

        self.assertFalse(result["comparable"])
        self.assertIn("frame-topology-difference", result["reasons"])

    def test_parent_chain_lists_ancestors_without_the_frame_itself(self) -> None:
        snapshot = build_frame_boundary_snapshot(_page(
            _frame("root/v0"),
            _frame("root/v0/v0"),
        ))
        records = snapshot["by_identity"]

        self.assertEqual(records["root/v0"]["parent_chain"], ["root"])
        self.assertEqual(
            records["root/v0/v0"]["parent_chain"],
            ["root", "root/v0"],
        )

    def test_boundary_gate_carries_scope_observability_into_outcome(self) -> None:
        gate = _boundary_gate(
            _page(_frame("root/v0", opaque_reason="cross-origin")),
            _page(_frame("root/v0", opaque_reason="cross-origin")),
        )

        self.assertTrue(gate["comparable"])
        self.assertEqual(
            gate["comparison_profile"],
            "rendered-frame-boundary-strict/1.0",
        )
        self.assertTrue(gate["boundary_observation_complete"])
        self.assertFalse(gate["boundary"]["opaque_contents_observable"])

    def test_document_generation_difference_marks_navigation_divergence(self) -> None:
        left = _page(_frame("root/v0", generation=1))
        right = _page(_frame("root/v0", generation=3))

        result = compare_rendered_frame_boundaries(left, right)

        self.assertFalse(result["comparable"])
        self.assertIn("frame-document-generation-difference", result["reasons"])

    def test_opaque_internal_state_is_never_used_as_boundary_equality(self) -> None:
        left = _page(
            _frame(
                "root/v0",
                opaque_reason="cross-origin",
                state={"placeholder": "left", "internal_hash": "a"},
            )
        )
        right = _page(
            _frame(
                "root/v0",
                opaque_reason="cross-origin",
                state={"placeholder": "right", "internal_hash": "b"},
            )
        )

        result = compare_rendered_frame_boundaries(left, right)

        self.assertTrue(result["comparable"])
        self.assertEqual(result["claims"], ["rendered-frame-boundary-equivalent"])
        self.assertFalse(result["opaque_contents_observable"])
        self.assertEqual(result["unobservable"][0]["scope"], "root/v0")
        self.assertNotIn("opaque-frame-content-equivalent", result["claims"])

    def test_missing_document_generation_fails_closed_as_incomplete_observation(self) -> None:
        left = _page(_frame("root/v0", generation=None))
        right = _page(_frame("root/v0", generation=0))

        result = compare_rendered_frame_boundaries(left, right)

        self.assertFalse(result["comparable"])
        self.assertFalse(result["boundary_observation_complete"])
        self.assertIn("frame-document-generation-unobservable", result["reasons"])


class _FakeRequest:
    def __init__(
        self,
        url: str,
        resource_type: str,
        frame: object,
        *,
        redirected_from: "_FakeRequest | None" = None,
    ) -> None:
        self.url = url
        self.resource_type = resource_type
        self.frame = frame
        self.redirected_from = redirected_from


class _FakeResponse:
    def __init__(self, request: _FakeRequest, status: int) -> None:
        self.request = request
        self.status = status
        self.url = request.url


class _FakeFrame:
    def __init__(
        self,
        url: str,
        *,
        parent: "_FakeFrame | None" = None,
    ) -> None:
        self.url = url
        self.parent_frame = parent
        self.child_frames: list[_FakeFrame] = []
        if parent is not None:
            parent.child_frames.append(self)


class _FakePage:
    def __init__(self, main_frame: _FakeFrame) -> None:
        self.main_frame = main_frame
        self.handlers: dict[str, object] = {}

    def on(self, event: str, handler: object) -> None:
        self.handlers[event] = handler


class NavigationTimelineTests(unittest.TestCase):
    def test_document_events_and_frame_generations_are_bounded_evidence(self) -> None:
        root = _FakeFrame("https://example.com/")
        child = _FakeFrame("about:blank", parent=root)
        page = _FakePage(root)
        timeline = NavigationTimeline(page, max_events=16, clock=lambda: 1.0)
        request = _FakeRequest("https://example.com/frame", "document", child)
        first_redirect = _FakeRequest(
            "https://example.com/start",
            "document",
            child,
        )
        response = _FakeResponse(request, 200)
        failed = _FakeRequest("https://example.com/missing", "image", child)

        page.handlers["request"](request)
        page.handlers["response"](response)
        page.handlers["requestfailed"](failed)
        page.handlers["requestfailed"](_FakeRequest(
            "https://example.com/frame-error",
            "document",
            child,
        ))
        page.handlers["framenavigated"](child)
        page.handlers["framenavigated"](child)
        page.handlers["framenavigated"](root)

        snapshot = timeline.snapshot()

        self.assertEqual(snapshot["schema_version"], "p1-navigation-timeline/1.0")
        self.assertEqual(
            [item["kind"] for item in snapshot["events"]],
            [
                "document-request",
                "document-response",
                "document-request-failed",
                "document-commit",
                "document-commit",
                "document-commit",
            ],
        )
        self.assertEqual(
            snapshot["frames"]["root/0"]["document_generation"],
            1,
        )
        self.assertEqual(snapshot["frames"]["root"]["document_generation"], 0)
        self.assertFalse(snapshot["truncated"])

        for index in range(20):
            page.handlers["framenavigated"](child)
        bounded = timeline.snapshot()
        self.assertTrue(bounded["truncated"])
        self.assertLessEqual(len(bounded["events"]), 16)

    def test_capture_can_attach_bounded_navigation_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "page.html"
            fixture.write_text(
                """
                <!doctype html>
                <p>timeline evidence</p>
                <iframe srcdoc="<p>child</p>" style="width:220px;height:80px"></iframe>
                """,
                encoding="utf-8",
            )
            with patch.multiple(
                tuning,
                SETTLE_MIN_MS=10,
                SETTLE_STABLE_MS=20,
                SETTLE_POLL_MS=10,
                SETTLE_CAP_MS=100,
                RESTYLE_SETTLE_MS=0,
                CAPTURE_STATE_POLL_MS=10,
                CAPTURE_STATE_STABLE_MS=20,
                CAPTURE_STATE_CAP_MS=100,
            ):
                result = capture_page(
                    fixture.resolve().as_uri(),
                    Config(
                        playwright_browser="chromium",
                        playwright_headless=True,
                        wait_networkidle_timeout=1000,
                    ),
                    str(root / "capture"),
                    capture_attempts=1,
                    capture_navigation_timeline=True,
                )

        timeline = result["page_state"]["navigation_timeline"]
        self.assertEqual(timeline["schema_version"], "p1-navigation-timeline/1.0")
        self.assertIn("root", timeline["frames"])
        child = next(
            item
            for item in result["page_state"]["frame_inventory"]
            if item.get("rendered") is True
        )
        self.assertIsInstance(child["document_generation"], int)
        self.assertEqual(child["navigation_phase"], "committed")


if __name__ == "__main__":
    unittest.main()
