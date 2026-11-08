from __future__ import annotations

import functools
import http.server
import json
import threading
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.app import tuning
from src.app.services.structure.capture import (
    DOM_JS,
    DEFAULT_BROWSER_ENGINE,
    PAGE_STATE_CONTENT,
    PAGE_STATE_SOFT_BLOCK,
    _load_url,
    _promote_attempt,
    capture_page,
    classify_page_state,
    normalize_browser_engine,
)
from src.config.settings import Config


class BrowserEngineTests(unittest.TestCase):
    def test_default_engine_remains_chromium(self) -> None:
        self.assertEqual(DEFAULT_BROWSER_ENGINE, "chromium")
        self.assertEqual(Config().playwright_browser, "chromium")

    def test_webkit_and_firefox_are_explicitly_supported(self) -> None:
        self.assertEqual(normalize_browser_engine("WebKit"), "webkit")
        self.assertEqual(normalize_browser_engine("firefox"), "firefox")

    def test_unknown_engine_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            normalize_browser_engine("blink")

    def test_promote_attempt_copies_optional_m0_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "attempt.png"
            dom = root / "attempt_dom.json"
            m0_image = root / "attempt_m0.png"
            m0_dom = root / "attempt_m0_dom.json"
            image.write_bytes(b"png")
            dom.write_text("[]", encoding="utf-8")
            m0_image.write_bytes(b"m0-png")
            m0_dom.write_text("[]", encoding="utf-8")
            out = root / "out"
            _promote_attempt(
                {
                    "image": str(image),
                    "dom": str(dom),
                    "m0_image": str(m0_image),
                    "m0_dom": str(m0_dom),
                },
                out,
            )
            self.assertTrue((out / "00_screenshot_m0.png").is_file())
            self.assertTrue((out / "00_dom_m0.json").is_file())

    def test_meaningful_content_with_screenshot_error_stays_content(self) -> None:
        probe = {
            "finalUrl": "https://example.com/",
            "title": "Example",
            "passwordInputs": 0,
            "hasForm": False,
            "elementCount": 100,
            "bodyTextLen": 500,
            "imageCount": 1,
            "bodyTextSample": "A meaningful page body.",
            "hasCaptchaElement": False,
        }
        state = classify_page_state(
            probe,
            "https://example.com/",
            status=200,
            error="TimeoutError: Page.screenshot: Timeout 30000ms exceeded.",
        )
        self.assertEqual(state["kind"], PAGE_STATE_CONTENT)
        self.assertTrue(state["signals"]["screenshot_error"])

    def test_non_rendered_svg_clip_geometry_is_not_captured(self) -> None:
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "clip-path.html"
            fixture.write_text(
                """
                <!doctype html>
                <html><body style="margin:0">
                  <svg width="120" height="80" viewBox="0 0 120 80">
                    <defs>
                      <clipPath id="clip">
                        <rect width="40" height="40"></rect>
                      </clipPath>
                    </defs>
                    <rect
                      id="visible-rect"
                      x="10"
                      y="10"
                      width="40"
                      height="40"
                      fill="red"
                      clip-path="url(#clip)"
                    ></rect>
                  </svg>
                </body></html>
                """,
                encoding="utf-8",
            )
            url = fixture.resolve().as_uri()

            observed: dict[str, list[str]] = {}
            with sync_playwright() as playwright:
                for engine in ("chromium", "webkit"):
                    browser = getattr(playwright, engine).launch(headless=True)
                    try:
                        page = browser.new_page()
                        page.goto(url, wait_until="domcontentloaded")
                        nodes = page.evaluate(DOM_JS)
                    finally:
                        browser.close()
                    observed[engine] = [
                        str(item.get("tag") or "")
                        for item in nodes
                        if str(item.get("tag") or "") == "rect"
                    ]

        self.assertEqual(observed["chromium"], ["rect"])
        self.assertEqual(observed["webkit"], ["rect"])

    def test_navigation_sync_runs_before_page_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "page.html"
            fixture.write_text(
                "<!doctype html><title>sync</title><p>ready</p>",
                encoding="utf-8",
            )
            observed_urls: list[str] = []

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
                        device_scale_factor=2,
                        playwright_viewport_width=900,
                        playwright_viewport_height=700,
                        wait_networkidle_timeout=1000,
                    ),
                    str(root / "capture"),
                    capture_attempts=1,
                    navigation_sync=lambda page: observed_urls.append(page.url),
                )

        self.assertEqual(observed_urls, ["about:blank"])
        self.assertEqual(result["device_scale_factor"], 2)
        self.assertEqual(result["viewport"], {"width": 900, "height": 700})
        self.assertEqual(
            result["page_state"]["attempts"][0]["device_scale_factor"],
            2,
        )

    def test_capture_page_recurses_same_origin_iframe_and_records_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "frame-page.html"
            fixture.write_text(
                """
                <!doctype html>
                <style>iframe { width: 240px; height: 100px; border: 0; }</style>
                <p>parent content</p>
                <iframe
                  id="child"
                  srcdoc="<p>child document content</p>"
                ></iframe>
                """,
                encoding="utf-8",
            )
            output = root / "capture"

            with patch.multiple(
                tuning,
                SETTLE_MIN_MS=10,
                SETTLE_STABLE_MS=20,
                SETTLE_POLL_MS=10,
                SETTLE_CAP_MS=100,
                RESTYLE_SETTLE_MS=0,
                CAPTURE_STATE_POLL_MS=10,
                CAPTURE_STATE_STABLE_MS=20,
                CAPTURE_STATE_CAP_MS=200,
                CAPTURE_FONT_POLL_MS=10,
                CAPTURE_FONT_WAIT_MS=100,
            ):
                capture_page(
                    fixture.resolve().as_uri(),
                    Config(
                        playwright_browser="chromium",
                        playwright_headless=True,
                        wait_networkidle_timeout=1000,
                    ),
                    str(output),
                    capture_attempts=1,
                    snapshot_sync=lambda _page: {
                        "synchronized": True,
                        "frame_tree_match": True,
                        "reasons": [],
                    },
                )

            dom = json.loads((output / "00_dom.json").read_text(encoding="utf-8"))
            page_state = json.loads(
                (output / "00_page_state.json").read_text(encoding="utf-8")
            )

        texts = [item.get("text") for item in dom]
        self.assertIn("parent content", texts)
        self.assertIn("child document content", texts)
        self.assertEqual(len(page_state["frame_inventory"]), 1)
        self.assertTrue(page_state["frame_inventory"][0]["accessible"])
        self.assertFalse(page_state["frame_inventory"][0]["opaque_frame"])
        self.assertEqual(page_state["frame_summary"]["frame_count"], 1)
        self.assertTrue(
            page_state["capture_stability"]["frame_barrier"]["synchronized"]
        )

    def test_about_blank_classifies_as_browser_navigation_failure(self) -> None:
        probe = {
            "finalUrl": "about:blank",
            "title": "Loading https://github.com/login",
            "passwordInputs": 0,
            "hasForm": False,
            "elementCount": 4,
            "bodyTextLen": 0,
            "imageCount": 0,
            "bodyTextSample": "",
            "hasCaptchaElement": False,
        }

        state = classify_page_state(
            probe,
            "https://github.com/login",
            navigation_budget_exhausted=True,
        )

        self.assertEqual(state["kind"], PAGE_STATE_SOFT_BLOCK)
        self.assertEqual(
            state["signals"]["navigation_status"],
            "browser-navigation-failed",
        )

    def test_about_blank_without_navigation_context_is_not_failure(self) -> None:
        probe = {
            "finalUrl": "about:blank",
            "title": "",
            "passwordInputs": 0,
            "hasForm": False,
            "elementCount": 4,
            "bodyTextLen": 0,
            "imageCount": 0,
            "bodyTextSample": "",
            "hasCaptchaElement": False,
        }

        state = classify_page_state(probe, "https://github.com/login")

        self.assertEqual(state["kind"], PAGE_STATE_SOFT_BLOCK)
        self.assertEqual(state["signals"]["navigation_status"], "blank-document")

    def test_load_url_retries_blank_document_once_with_domcontentloaded(self) -> None:
        class FakeTimeout(Exception):
            pass

        class FakeNavigationPage:
            def __init__(self) -> None:
                self.url = "about:blank"
                self.calls: list[tuple[str, str]] = []

            def goto(self, url: str, *, wait_until: str, timeout: int):
                del timeout
                self.calls.append((url, wait_until))
                if wait_until == "networkidle":
                    raise FakeTimeout("networkidle timeout")
                self.url = url
                return {"status": 200, "url": url}

            def wait_for_load_state(self, state: str, *, timeout: int) -> None:
                del state, timeout
                raise FakeTimeout("load state timeout")

        page = FakeNavigationPage()
        with (
            patch("playwright.sync_api.TimeoutError", FakeTimeout),
            self.assertLogs("src.app.services.structure.capture", level="INFO"),
        ):
            response = _load_url(
                page,
                "https://example.com/page",
                Config(wait_networkidle_timeout=1000),
            )

        self.assertEqual(response, {"status": 200, "url": "https://example.com/page"})
        self.assertEqual(
            page.calls,
            [
                ("https://example.com/page", "networkidle"),
                ("https://example.com/page", "domcontentloaded"),
            ],
        )

    def test_capture_can_block_cross_origin_frame_documents_explicitly(self) -> None:
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "same.html").write_text(
                "<!doctype html><p>same origin frame content</p>",
                encoding="utf-8",
            )
            (root / "cross.html").write_text(
                "<!doctype html><p>cross origin frame content</p>",
                encoding="utf-8",
            )
            (root / "index.html").write_text(
                """
                <!doctype html>
                <p>parent content</p>
                <iframe src="same.html" style="width:240px;height:100px"></iframe>
                <iframe
                  id="cross"
                  src="http://localhost:__PORT__/cross.html"
                  style="width:240px;height:100px"
                ></iframe>
                """,
                encoding="utf-8",
            )
            handler = functools.partial(QuietHandler, directory=str(root))
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                (root / "index.html").write_text(
                    (root / "index.html").read_text(encoding="utf-8").replace(
                        "__PORT__",
                        str(server.server_port),
                    ),
                    encoding="utf-8",
                )
                output = root / "capture"
                with patch.multiple(
                    tuning,
                    SETTLE_MIN_MS=10,
                    SETTLE_STABLE_MS=20,
                    SETTLE_POLL_MS=10,
                    SETTLE_CAP_MS=100,
                    RESTYLE_SETTLE_MS=0,
                    CAPTURE_STATE_POLL_MS=10,
                    CAPTURE_STATE_STABLE_MS=20,
                    CAPTURE_STATE_CAP_MS=200,
                    CAPTURE_FONT_POLL_MS=10,
                    CAPTURE_FONT_WAIT_MS=100,
                ):
                    capture_page(
                        f"http://127.0.0.1:{server.server_port}/index.html",
                        Config(
                            playwright_browser="chromium",
                            playwright_headless=True,
                            wait_networkidle_timeout=1000,
                        ),
                        str(output),
                        capture_attempts=1,
                        block_cross_origin_frame_documents=True,
                    )
            finally:
                server.shutdown()
                server.server_close()

            dom = json.loads((output / "00_dom.json").read_text(encoding="utf-8"))
            page_state = json.loads(
                (output / "00_page_state.json").read_text(encoding="utf-8")
            )

        texts = [item.get("text") for item in dom]
        self.assertIn("same origin frame content", texts)
        self.assertNotIn("cross origin frame content", texts)
        self.assertEqual(
            page_state["frame_request_policy"]["blocked_document_count"],
            1,
        )
        self.assertEqual(
            page_state["capture_profile"],
            "first-party-frame-strict/1.0",
        )


if __name__ == "__main__":
    unittest.main()
