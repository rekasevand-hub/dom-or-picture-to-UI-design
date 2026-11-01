from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.app.services.structure.capture import DOM_JS


class DomRichTextRunTests(unittest.TestCase):
    def test_mixed_inline_text_is_captured_as_one_ordered_run_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "mixed-inline.html"
            fixture.write_text(
                """
                <!doctype html>
                <div id="root" style="width:600px;font:16px sans-serif">
                  在 LeetCode 上，<strong style="font-weight:700">“两数之和”（Two Sum）</strong>
                  是最经典的入门算法题之一。
                </div>
                """,
                encoding="utf-8",
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": 800, "height": 400})
                    page.goto(fixture.resolve().as_uri(), wait_until="domcontentloaded")
                    nodes = page.evaluate(DOM_JS)
                finally:
                    browser.close()

        root = next(node for node in nodes if "LeetCode" in str(node.get("text") or ""))
        self.assertEqual(
            "".join(run["text"] for run in root["richRuns"]),
            root["text"],
        )
        bold = next(run for run in root["richRuns"] if "两数之和" in run["text"])
        self.assertEqual(bold["style"]["fontWeight"], "700")
        self.assertTrue(root["richRuns"][0]["style"]["fontWeight"] in {"400", "normal"})
        self.assertFalse(any(node.get("tag") == "strong" for node in nodes))

    def test_inline_code_is_flattened_into_parent_paragraph_text_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "inline-code.html"
            fixture.write_text(
                """
                <!doctype html>
                <p id="root" style="width:600px;font:16px sans-serif">
                  给定一个整数数组 <code style="font:12px monospace;background:#eee">nums</code>
                  和一个整数目标值 <strong>target</strong>，请找出两个整数，
                  返回 <em><code style="font:12px monospace;background:#eee">target</code></em>。
                </p>
                """,
                encoding="utf-8",
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": 800, "height": 400})
                    page.goto(fixture.resolve().as_uri(), wait_until="domcontentloaded")
                    nodes = page.evaluate(DOM_JS)
                finally:
                    browser.close()

        root = next(node for node in nodes if node.get("tag") == "p")
        code_run = next(run for run in root["richRuns"] if "nums" in run["text"])
        target_run = next(run for run in root["richRuns"] if "target" in run["text"])

        self.assertEqual("".join(run["text"] for run in root["richRuns"]), root["text"])
        self.assertIn("nums", root["text"])
        self.assertEqual(code_run["style"]["fontSize"], "16px")
        self.assertEqual(code_run["style"]["fontWeight"], "400")
        self.assertEqual(target_run["style"]["fontWeight"], "700")
        self.assertFalse(any(node.get("tag") == "code" for node in nodes))
        self.assertFalse(any(node.get("tag") == "em" for node in nodes))


if __name__ == "__main__":
    unittest.main()
