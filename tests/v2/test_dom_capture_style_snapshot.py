from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.app.services.structure.capture import DOM_JS


class DomCaptureStyleSnapshotTests(unittest.TestCase):
    def test_style_snapshot_captures_layout_transform_variables_and_pseudos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "style-snapshot.html"
            fixture.write_text(
                """
                <!doctype html>
                <style>
                  body { margin: 0; font: 16px/20px sans-serif; }
                  #flex {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    gap: 12px;
                    width: 600px;
                    height: 60px;
                  }
                  #grid {
                    display: grid;
                    grid-template-columns: 120px 1fr;
                    grid-template-rows: 40px;
                    width: 600px;
                    height: 40px;
                  }
                  #moved {
                    width: 80px;
                    height: 20px;
                    transform: translateX(10px);
                    transform-origin: left top;
                  }
                  #custom {
                    --brand: #112233;
                    color: var(--brand);
                    width: 80px;
                    height: 20px;
                  }
                  #pseudo {
                    position: relative;
                    width: 120px;
                    height: 30px;
                  }
                  #pseudo::before {
                    content: "•";
                    display: block;
                    position: absolute;
                    color: rgb(17, 34, 51);
                    font: 700 16px/20px sans-serif;
                    transform: translateX(2px);
                    z-index: 3;
                  }
                  #pseudo::after {
                    content: "after";
                    position: relative;
                  }
                </style>
                <div id="flex"><span>Left</span><span>Right</span></div>
                <div id="grid"><span>Cell</span><span>Cell</span></div>
                <div id="moved">Moved</div>
                <div id="custom">Brand</div>
                <div id="pseudo">Pseudo</div>
                """,
                encoding="utf-8",
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": 900, "height": 600})
                    page.goto(fixture.resolve().as_uri(), wait_until="domcontentloaded")
                    nodes = page.evaluate(DOM_JS)
                finally:
                    browser.close()

        by_id = {node.get("id"): node for node in nodes if node.get("id")}
        flex = by_id["flex"]
        grid = by_id["grid"]
        moved = by_id["moved"]
        custom = by_id["custom"]
        pseudo = by_id["pseudo"]

        self.assertEqual(flex["styleSnapshot"]["display"], "flex")
        self.assertEqual(
            flex["styleSnapshot"]["justifyContent"], "space-between"
        )
        self.assertTrue(grid["styleSnapshot"]["gridTemplateColumns"])
        self.assertNotEqual(moved["styleSnapshot"]["transform"], "none")
        self.assertEqual(
            custom["styleSnapshot"]["customProperties"]["--brand"], "#112233"
        )
        self.assertEqual(pseudo["pseudoBefore"]["content"], '"•"')
        self.assertEqual(pseudo["pseudoBefore"]["position"], "absolute")
        self.assertNotIn("bbox", pseudo["pseudoBefore"])
        self.assertEqual(pseudo["pseudoAfter"]["content"], '"after"')


if __name__ == "__main__":
    unittest.main()
