from __future__ import annotations

import functools
import http.server
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from scripts.p1_dual_browser_capture import (
    _capture_profile_id,
    _classify_failure,
    _retry_delay_ms,
)
from src.app.services.structure.capture import DOM_JS
from src.app.services.structure.capture_state import (
    classify_capture_navigation,
    evaluate_state_gate,
    text_delta,
)
from src.app.services.structure.frames import (
    capture_frame_state,
    collect_frame_dom,
    summarize_frame_inventory,
)
from src.app.services.structure.font_provenance import PlatformFontProbe


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return None


def _serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


class FrameCaptureIntegrationTests(unittest.TestCase):
    def test_platform_font_probe_resolves_main_and_child_generic_text(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                probe = PlatformFontProbe(page)
                page.set_content(
                    """
                    <!doctype html>
                    <p id="main-font" style="font-family:sans-serif">main generic</p>
                    <iframe
                      id="child"
                      style="width:240px;height:80px"
                      srcdoc="
                        <p id='child-font' style='font-family:sans-serif'>
                          child generic
                        </p>
                      "
                    ></iframe>
                    """
                )
                page.wait_for_timeout(100)
                snapshot = collect_frame_dom(
                    page,
                    DOM_JS,
                    font_probe=probe,
                )
                main_marker = page.get_attribute(
                    "#main-font",
                    "data-p1-font-probe-id",
                )
                child_marker = page.frame_locator("#child").locator(
                    "#child-font"
                ).get_attribute("data-p1-font-probe-id")
            finally:
                browser.close()

        main = next(
            item for item in snapshot.nodes if item.get("text") == "main generic"
        )
        child = next(
            item for item in snapshot.nodes if item.get("text") == "child generic"
        )
        for item in (main, child):
            self.assertNotEqual(item["fontFamily"], "sans-serif")
            self.assertTrue(item["platformFonts"])
            self.assertNotIn("fontProbeId", item)
        self.assertIsNone(main_marker)
        self.assertIsNone(child_marker)

    def test_generic_text_is_marked_for_platform_font_probe(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content(
                    """
                    <!doctype html>
                    <p id="generic" style="font-family:sans-serif">generic text</p>
                    <p id="explicit" style="font-family:Arial">explicit text</p>
                    """
                )
                nodes = page.evaluate(DOM_JS, "root")
                generic = next(
                    item for item in nodes if item.get("text") == "generic text"
                )
                explicit = next(
                    item for item in nodes if item.get("text") == "explicit text"
                )
                marker = page.get_attribute("#generic", "data-p1-font-probe-id")
            finally:
                browser.close()

        self.assertTrue(generic.get("fontProbeId", "").startswith("root-"))
        self.assertEqual(
            marker,
            generic["fontProbeId"],
        )
        self.assertNotIn("fontProbeId", explicit)

    def test_same_origin_frames_are_recursive_and_opaque_frames_are_inventoried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            other = root / "other"
            other.mkdir()
            (root / "grandchild.html").write_text(
                "<!doctype html><p>grandchild content</p>",
                encoding="utf-8",
            )
            (root / "child.html").write_text(
                """
                <!doctype html>
                <p>child content</p>
                <iframe src="grandchild.html" style="width:220px;height:80px"></iframe>
                """,
                encoding="utf-8",
            )
            (root / "lazy.html").write_text(
                "<!doctype html><p>lazy content</p>",
                encoding="utf-8",
            )
            (root / "tracker.html").write_text(
                "<!doctype html><p>tracker only content</p>",
                encoding="utf-8",
            )
            (other / "cross.html").write_text(
                "<!doctype html><p>cross content</p>",
                encoding="utf-8",
            )
            (root / "index.html").write_text(
                """
                <!doctype html>
                <style>iframe { width: 240px; height: 100px; border: 0; }</style>
                <main><p>main content</p></main>
                <iframe id="child" src="child.html"></iframe>
                <iframe
                  id="sandboxed"
                  sandbox
                  srcdoc="<p>sandbox content</p>"
                ></iframe>
                <iframe
                  id="sandboxed-accessible"
                  sandbox="allow-same-origin"
                  srcdoc="<p>sandbox accessible content</p>"
                ></iframe>
                <iframe id="cross" src="__CROSS_URL__/cross.html"></iframe>
                <iframe
                  id="tracking"
                  src="tracker.html"
                  style="width:240px;height:100px;border:0;opacity:0"
                ></iframe>
                <script>
                  setTimeout(() => {
                    const frame = document.createElement('iframe');
                    frame.id = 'lazy';
                    frame.src = 'lazy.html';
                    document.body.appendChild(frame);
                  }, 400);
                </script>
                """.replace("__CROSS_URL__", f"http://127.0.0.1:{0}"),
                encoding="utf-8",
            )
            main_server, main_url = _serve(root)
            cross_server, cross_url = _serve(other)
            try:
                page_file = root / "index.html"
                page_file.write_text(
                    page_file.read_text(encoding="utf-8").replace(
                        "http://127.0.0.1:0",
                        cross_url,
                    ),
                    encoding="utf-8",
                )
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(viewport={"width": 1000, "height": 800})
                        page.goto(f"{main_url}/index.html", wait_until="domcontentloaded")
                        page.wait_for_timeout(900)
                        snapshot = collect_frame_dom(page, DOM_JS)
                    finally:
                        browser.close()
            finally:
                main_server.shutdown()
                cross_server.shutdown()
                main_server.server_close()
                cross_server.server_close()

        texts = [str(node.get("text") or "") for node in snapshot.nodes]
        self.assertIn("main content", texts)
        self.assertIn("child content", texts)
        self.assertIn("grandchild content", texts)
        self.assertIn("lazy content", texts)
        self.assertIn("sandbox accessible content", texts)
        self.assertNotIn("sandbox content", texts)
        self.assertNotIn("cross content", texts)
        self.assertNotIn("tracker only content", texts)

        records = {item["path"]: item for item in snapshot.inventory}
        root_children = [item for item in snapshot.inventory if item["depth"] == 1]
        self.assertEqual(len(root_children), 6)
        self.assertEqual(
            sum(not item["rendered"] for item in root_children),
            1,
        )
        sandboxed = next(
            item
            for item in root_children
            if item["opaque_reason"] == "sandboxed-opaque-origin"
        )
        self.assertFalse(sandboxed["accessible"])
        self.assertEqual(sandboxed["opaque_reason"], "sandboxed-opaque-origin")
        cross = next(item for item in root_children if item["opaque_reason"] == "cross-origin")
        self.assertTrue(cross["opaque_frame"])
        self.assertGreater(cross["width"], 0)
        self.assertGreater(cross["height"], 0)
        self.assertTrue(any(item["depth"] == 2 for item in records.values()))

        summary = summarize_frame_inventory(snapshot.inventory)
        self.assertGreaterEqual(summary["frame_count"], 5)
        self.assertEqual(summary["unrendered_frame_count"], 1)
        self.assertGreaterEqual(summary["opaque_frame_count"], 2)
        self.assertGreaterEqual(summary["accessible_frame_count"], 3)

    def test_frame_navigation_changes_capture_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.html").write_text("<!doctype html><p>frame A</p>", encoding="utf-8")
            (root / "b.html").write_text("<!doctype html><p>frame B</p>", encoding="utf-8")
            (root / "index.html").write_text(
                """
                <!doctype html>
                <iframe id="target" src="a.html" style="width:240px;height:100px"></iframe>
                <script>
                  setTimeout(() => document.querySelector('#target').src = 'b.html', 500);
                </script>
                """,
                encoding="utf-8",
            )
            server, base_url = _serve(root)
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page()
                        page.goto(f"{base_url}/index.html", wait_until="domcontentloaded")
                        before = capture_frame_state(
                            page,
                            "() => ({ token: 'a' })",
                            include_unrendered=False,
                        )
                        page.wait_for_timeout(800)
                        after = capture_frame_state(
                            page,
                            "() => ({ token: 'b' })",
                            include_unrendered=False,
                        )
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()

        self.assertIn("/a.html", before[0]["url"])
        self.assertIn("/b.html", after[0]["url"])
        self.assertNotEqual(before, after)

    def test_accessible_child_text_uses_the_iframe_host_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(
                """
                <!doctype html>
                <body style="margin:0">
                  <iframe style="display:none" src="about:blank"></iframe>
                  <h1 style="margin:8px">Before frame</h1>
                  <p style="margin:8px">Parent paragraph before the iframe.</p>
                  <iframe
                    style="position:absolute;left:100px;top:120px;width:300px;height:120px;border:0"
                    srcdoc="<body style='margin:0'><p style='margin:8px'>Offset child</p></body>"
                  ></iframe>
                </body>
                """,
                encoding="utf-8",
            )
            server, base_url = _serve(root)
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page()
                        page.goto(
                            f"{base_url}/index.html",
                            wait_until="domcontentloaded",
                        )
                        page.wait_for_timeout(300)
                        snapshot = collect_frame_dom(page, DOM_JS)
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()

        child = next(
            item for item in snapshot.nodes
            if item.get("text") == "Offset child"
        )
        self.assertAlmostEqual(float(child["x"]), 108.0, delta=1.0)
        self.assertAlmostEqual(float(child["y"]), 128.0, delta=1.0)

    def test_child_text_offset_includes_the_iframe_border(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(
                """
                <!doctype html>
                <body style="margin:0">
                  <iframe
                    style="position:absolute;left:100px;top:120px;width:300px;height:120px"
                    srcdoc="<body style='margin:0'><p style='margin:8px'>Border child</p></body>"
                  ></iframe>
                </body>
                """,
                encoding="utf-8",
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto((root / "index.html").resolve().as_uri(),
                              wait_until="domcontentloaded")
                    page.wait_for_timeout(300)
                    snapshot = collect_frame_dom(page, DOM_JS)
                finally:
                    browser.close()

        child = next(
            item for item in snapshot.nodes
            if item.get("text") == "Border child"
        )
        self.assertAlmostEqual(float(child["x"]), 110.0, delta=1.0)
        self.assertAlmostEqual(float(child["y"]), 130.0, delta=1.0)

    def test_accessible_child_text_after_main_content_uses_the_real_host(self) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "p1"
            / "iframe.html"
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(fixture.resolve().as_uri(), wait_until="domcontentloaded")
                page.wait_for_timeout(300)
                snapshot = collect_frame_dom(page, DOM_JS)
            finally:
                browser.close()

        child = next(
            item for item in snapshot.nodes
            if item.get("text") == "Accessible iframe content"
        )
        self.assertAlmostEqual(float(child["x"]), 18.0, delta=1.0)
        self.assertAlmostEqual(float(child["y"]), 132.0, delta=1.0)
        self.assertEqual(child["fontFamily"], "sans-serif")


class StateDriftClassificationTests(unittest.TestCase):
    def test_explicit_first_party_profile_is_not_renamed_as_full_visible(self) -> None:
        profile = _capture_profile_id({
            "chromium": {"capture_profile": "first-party-frame-strict/1.0"},
            "webkit": {"capture_profile": "first-party-frame-strict/1.0"},
        })

        self.assertEqual(profile, "first-party-frame-strict/1.0")

    def test_default_profile_remains_rendered_frame_strict(self) -> None:
        self.assertEqual(
            _capture_profile_id({"chromium": {}, "webkit": {}}),
            "rendered-frame-state-strict/1.0",
        )

    def test_dynamic_glyph_delta_is_reported_without_relaxing_strict_gate(self) -> None:
        left = [{"tag": "p", "text": "same content"}]
        right = [{"tag": "p", "text": "same content"}, {"tag": "span", "text": "❯"}]
        page = {"final_url": "https://example.com/"}

        delta = text_delta(left, right)
        gate = evaluate_state_gate(left, page, right, page)

        self.assertEqual(delta["classification"], "dynamic-glyph")
        self.assertEqual(delta["added"], [{"text": "❯", "count": 1}])
        self.assertFalse(gate["comparable"])
        self.assertIn("text-mismatch", gate["reasons"])

    def test_glyph_disappearance_is_classified_in_both_directions(self) -> None:
        with_glyph = [{"tag": "p", "text": "same"}, {"tag": "span", "text": "›"}]
        without_glyph = [{"tag": "p", "text": "same"}]

        self.assertEqual(text_delta(with_glyph, without_glyph)["classification"], "dynamic-glyph")
        self.assertEqual(text_delta(without_glyph, with_glyph)["classification"], "dynamic-glyph")

    def test_frame_inventory_mismatch_blocks_strict_equality(self) -> None:
        dom = [{"tag": "p", "text": "same"}]
        left = {
            "final_url": "https://example.com/",
            "frame_inventory": [{"path": "root/0", "url": "https://example.com/a"}],
        }
        right = {
            "final_url": "https://example.com/",
            "frame_inventory": [{"path": "root/0", "url": "https://example.com/b"}],
        }

        gate = evaluate_state_gate(dom, left, dom, right)

        self.assertFalse(gate["comparable"])
        self.assertEqual(gate["reasons"], ["frame-inventory-mismatch"])

    def test_unrendered_tracking_frames_are_evidence_only_for_strict_state(self) -> None:
        dom = [{"tag": "p", "text": "same"}]
        left = {
            "final_url": "https://example.com/",
            "frame_inventory": [
                {
                    "path": "root/0",
                    "scope_path": "root/v0",
                    "url": "https://tracker.example/a",
                    "rendered": False,
                }
            ],
        }
        right = {
            "final_url": "https://example.com/",
            "frame_inventory": [
                {
                    "path": "root/0",
                    "scope_path": "root/v0",
                    "url": "https://tracker.example/b",
                    "rendered": False,
                }
            ],
        }

        self.assertTrue(evaluate_state_gate(dom, left, dom, right)["comparable"])

        left["frame_inventory"][0]["rendered"] = True
        right["frame_inventory"][0]["rendered"] = True
        gate = evaluate_state_gate(dom, left, dom, right)
        self.assertFalse(gate["comparable"])
        self.assertEqual(gate["reasons"], ["frame-inventory-mismatch"])

    def test_about_blank_alone_is_not_browser_navigation_failure(self) -> None:
        result = classify_capture_navigation(
            "https://github.com/login",
            "about:blank",
            error=None,
        )

        self.assertEqual(result["status"], "blank-document")
        self.assertEqual(result["final_url"], "about:blank")

    def test_about_blank_is_failure_after_expected_nonblank_budget_is_exhausted(self) -> None:
        result = classify_capture_navigation(
            "https://github.com/login",
            "about:blank",
            error=None,
            navigation_budget_exhausted=True,
        )

        self.assertEqual(result["status"], "browser-navigation-failed")
        self.assertEqual(result["final_url"], "about:blank")

    def test_failure_classification_prefers_navigation_over_dom_delta(self) -> None:
        gate = {"comparable": False, "reasons": ["url-mismatch", "text-mismatch"]}
        engines = {
            "webkit": {
                "navigation": {
                    "status": "browser-navigation-failed",
                }
            }
        }

        result = _classify_failure(
            gate,
            engines,
            {"classification": "dynamic-glyph"},
        )

        self.assertEqual(result, "browser-navigation-failed")

    def test_failure_classification_surfaces_glyph_delta_before_frame_scope(self) -> None:
        gate = {
            "comparable": False,
            "reasons": ["frame-inventory-mismatch", "text-mismatch"],
        }

        result = _classify_failure(
            gate,
            {},
            {"classification": "dynamic-glyph"},
        )

        self.assertEqual(result, "dynamic-glyph")

    def test_retry_backoff_is_exponential_and_capped(self) -> None:
        self.assertEqual(
            [_retry_delay_ms(index) for index in range(6)],
            [250, 500, 1000, 2000, 2000, 2000],
        )


if __name__ == "__main__":
    unittest.main()
