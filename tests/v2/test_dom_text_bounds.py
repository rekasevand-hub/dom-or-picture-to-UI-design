from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright
from PIL import Image

from src.app.services.rendering.text_wrap import ellipsize, wrap_for_spec
from src.app.services.structure.capture import DOM_JS
from src.app.services.som.direct_design import build_direct_design


class DomTextBoundsTests(unittest.TestCase):
    def test_ellipsis_reserves_two_character_widths(self) -> None:
        result = ellipsize("超" * 20, width=100, font_size=10)

        self.assertLessEqual(len(result), 8)
        self.assertTrue(result.endswith("…"))

    def test_nowrap_overflow_records_self_clip_and_scroll_width(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "bounded-title.html"
            fixture.write_text(
                """
                <!doctype html>
                <div
                  id="title"
                  style="width:260px;overflow:hidden;text-overflow:ellipsis;
                         white-space:nowrap;font:16px sans-serif"
                >This title is deliberately much longer than the box.</div>
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

        title = next(node for node in nodes if node.get("textOverflow") == "ellipsis")
        self.assertEqual(title["overflowX"], "hidden")
        self.assertEqual(title["textOverflow"], "ellipsis")
        self.assertTrue(title["clipToBounds"])
        self.assertEqual(title["clientWidth"], 260)
        self.assertGreater(title["scrollWidth"], title["clientWidth"])
        self.assertTrue(title["text"].endswith("…"))
        self.assertIn("deliberately much longer", title["fullText"])

    def test_dom_ancestor_overflow_clips_descendants_outside_scroll_box(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            Image.new("RGB", (200, 200), "white").save(image_path)
            som = {
                "image": str(image_path),
                "size": [200, 200],
                "containers": [],
                "elements": [
                    {
                        "id": "inside",
                        "bbox": [10, 20, 80, 20],
                        "type": "button",
                        "text": "inside",
                        "style": {"textColor": "#000000", "fontSize": 14},
                        "domIndex": 1,
                    },
                    {
                        "id": "outside",
                        "bbox": [10, 130, 80, 20],
                        "type": "text",
                        "text": "outside",
                        "style": {"textColor": "#000000", "fontSize": 14},
                        "domIndex": 2,
                    },
                ],
                "provenance": {"route": "dom", "capture": {}},
            }
            dom_nodes = [
                {
                    "tag": "div",
                    "x": 0,
                    "y": 0,
                    "w": 100,
                    "h": 100,
                    "pIdx": None,
                    "clipToBounds": True,
                },
                {
                    "tag": "div",
                    "x": 10,
                    "y": 20,
                    "w": 80,
                    "h": 20,
                    "pIdx": 0,
                },
                {
                    "tag": "div",
                    "x": 10,
                    "y": 130,
                    "w": 80,
                    "h": 20,
                    "pIdx": 0,
                },
            ]

            design = build_direct_design(som, dom_nodes=dom_nodes)

        texts = [item["text"] for item in design["elements"] if item.get("text")]
        self.assertEqual(texts, ["inside"])

    def test_clipped_text_uses_visible_lines_and_ellipsis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            Image.new("RGB", (220, 220), "white").save(image_path)
            text = "这是一段明显超过父容器可见高度并且需要省略的长文本。" * 8
            som = {
                "image": str(image_path),
                "size": [220, 220],
                "containers": [],
                "elements": [
                    {
                        "id": "clipped-copy",
                        "bbox": [10, 10, 200, 200],
                        "type": "text",
                        "text": text,
                        "clip": [10, 10, 200, 60],
                        "style": {
                            "textColor": "#000000",
                            "fontSize": 14,
                            "lineHeight": 20,
                        },
                        "domIndex": 1,
                    }
                ],
                "provenance": {"route": "dom", "capture": {}},
            }
            dom_nodes = [
                {
                    "tag": "div",
                    "x": 10,
                    "y": 10,
                    "w": 200,
                    "h": 60,
                    "pIdx": None,
                    "clipToBounds": True,
                },
                {
                    "tag": "p",
                    "x": 10,
                    "y": 10,
                    "w": 200,
                    "h": 200,
                    "pIdx": 0,
                },
            ]

            design = build_direct_design(som, dom_nodes=dom_nodes)

        element = next(item for item in design["elements"] if item["id"] == "clipped-copy")
        self.assertEqual(element["style"]["maxLines"], 3)
        lines = wrap_for_spec({**element, **element["style"]})
        self.assertIsNotNone(lines)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[-1].endswith("…"))

    def test_ancestor_row_ellipsis_caps_child_text_to_one_visible_line(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            Image.new("RGB", (240, 120), "white").save(image_path)
            som = {
                "image": str(image_path),
                "size": [240, 120],
                "containers": [],
                "elements": [
                    {
                        "id": "headline",
                        "bbox": [20, 24, 200, 51],
                        "type": "text",
                        "text": "这是一条明显超过单行容器高度的新闻标题，必须在末尾显示省略号",
                        "domIndex": 1,
                        "style": {
                            "textColor": "#222222",
                            "fontSize": 16,
                            "fontWeight": "bold",
                            "lineHeight": 20,
                        },
                    }
                ],
                "provenance": {"route": "dom", "capture": {}},
            }
            dom_nodes = [
                {
                    "tag": "li",
                    "x": 20,
                    "y": 20,
                    "w": 200,
                    "h": 20,
                    "pIdx": None,
                    "clipToBounds": True,
                    "overflowX": "hidden",
                    "overflowY": "hidden",
                    "textOverflow": "ellipsis",
                },
                {
                    "tag": "a",
                    "x": 20,
                    "y": 24,
                    "w": 200,
                    "h": 51,
                    "pIdx": 0,
                    "text": "这是一条明显超过单行容器高度的新闻标题，必须在末尾显示省略号",
                    "textLines": [
                        {
                            "text": "这是一条明显超过单行容器高度的新闻",
                            "box": [20, 24, 200, 20],
                        },
                        {
                            "text": "标题，必须在末尾显示省略号",
                            "box": [20, 44, 200, 20],
                        },
                    ],
                    "textEmLines": 2,
                },
            ]

            design = build_direct_design(som, dom_nodes=dom_nodes)

        headline = next(
            item for item in design["elements"] if item["id"] == "headline"
        )
        self.assertEqual(headline["clip"], [20, 20, 200, 20])
        self.assertEqual(headline["textOverflow"], "ellipsis")
        self.assertEqual(headline["style"]["maxLines"], 1)
        lines = wrap_for_spec({**headline, **headline["style"]})
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith("…"))

    def test_explicit_row_ellipsis_cleans_rich_text_newlines(self) -> None:
        lines = wrap_for_spec(
            {
                "text": "财经\n    |\n    茉莉奶白联名水杯爆裂致用户住院 公司紧急召回",
                "lines": [
                    "财经\n    |\n    茉莉奶白联名水杯爆裂致用户住院 公司紧急召回"
                ],
                "width": 160,
                "height": 30,
                "lineHeight": 30,
                "fontSize": 16,
                "fontWeight": "bold",
                "maxLines": 1,
                "textOverflow": "ellipsis",
            }
        )

        self.assertEqual(len(lines), 1)
        self.assertNotIn("\n", lines[0])
        self.assertTrue(lines[0].startswith("财经 | 茉莉奶白"))
        self.assertTrue(lines[0].endswith("…"))

    def test_paintless_inline_text_uses_visible_range_after_icons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            Image.new("RGB", (220, 80), "white").save(image_path)
            som = {
                "image": str(image_path),
                "size": [220, 80],
                "containers": [],
                "elements": [
                    {
                        "id": "label",
                        "bbox": [10, 10, 170, 37],
                        "type": "text",
                        "text": "#全新TRAE 实战体验#",
                        "textEmBox": [50, 10, 118, 18],
                        "textEmLines": 2,
                        "style": {"textColor": "#000000", "fontSize": 12},
                        "domIndex": 1,
                    }
                ],
                "provenance": {"route": "dom", "capture": {}},
            }
            dom_nodes = [
                {"tag": "p", "x": 10, "y": 10, "w": 170, "h": 19, "pIdx": None},
                {
                    "tag": "span",
                    "x": 10,
                    "y": 10,
                    "w": 170,
                    "h": 37,
                    "pIdx": 0,
                    "display": "inline",
                },
            ]

            design = build_direct_design(som, dom_nodes=dom_nodes)

        label = next(item for item in design["elements"] if item["id"] == "label")
        self.assertEqual(
            (label["x"], label["y"], label["width"], label["height"]),
            (50, 10, 118, 18),
        )

    def test_measured_lines_obey_explicit_max_lines(self) -> None:
        lines = wrap_for_spec(
            {
                "text": "长文本" * 20,
                "lines": ["第一行" * 6, "第二行" * 6, "第三行" * 6],
                "width": 100,
                "height": 40,
                "lineHeight": 20,
                "maxLines": 2,
                "fontSize": 14,
            }
        )

        self.assertIsNotNone(lines)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("…"))

    def test_multiline_aggregate_box_wraps_to_its_own_bounded_height(self) -> None:
        lines = wrap_for_spec(
            {
                "text": "Where teams and agents together.",
                "width": 869,
                "height": 216,
                "lineHeight": 100,
                "fontSize": 96,
                "textEmLines": 2,
                "textLineBox": True,
            }
        )

        self.assertIsNotNone(lines)
        self.assertGreaterEqual(len(lines), 2)
        self.assertLessEqual(len(lines), 2)

    def test_empty_fixed_overlay_is_not_rasterized_over_page_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            Image.new("RGB", (200, 100), "white").save(image_path)
            som = {
                "image": str(image_path),
                "size": [200, 100],
                "containers": [
                    {
                        "id": "empty-toast-layer",
                        "bbox": [0, 0, 200, 32],
                        "style": {"fillColor": "transparent"},
                        "overlay": True,
                        "zIndex": 50,
                        "domIndex": 0,
                    }
                ],
                "elements": [],
                "provenance": {"route": "dom", "capture": {}},
            }
            dom_nodes = [
                {
                    "tag": "ol",
                    "x": 0,
                    "y": 0,
                    "w": 200,
                    "h": 32,
                    "pIdx": None,
                    "position": "fixed",
                    "zIndex": 50,
                }
            ]

            design = build_direct_design(som, dom_nodes=dom_nodes)

        self.assertFalse(
            any(item.get("cropBackdrop") for item in design["elements"])
        )
        self.assertFalse(
            any(
                item.get("id") == "empty-toast-layer"
                and item.get("imageBase64")
                for item in design["elements"]
            )
        )

    def test_multi_run_text_keeps_full_element_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            Image.new("RGB", (1440, 100), "white").save(image_path)
            som = {
                "image": str(image_path),
                "size": [1440, 100],
                "containers": [],
                "elements": [
                    {
                        "id": "plus",
                        "bbox": [1361, 15, 56, 19],
                        "type": "text",
                        "text": "Plus 会员",
                        "textEmBox": [1385, 15, 32, 19],
                        "textEmLines": 1,
                        "richRuns": [
                            {
                                "start": 0,
                                "end": 4,
                                "text": "Plus",
                                "style": {"fontSize": "14px"},
                            },
                            {
                                "start": 4,
                                "end": 7,
                                "text": " 会员",
                                "style": {"fontSize": "14px"},
                            },
                        ],
                        "style": {"fontSize": 14, "textColor": "#ffa116"},
                        "domIndex": 1,
                    }
                ],
                "provenance": {"route": "dom", "capture": {}},
            }
            dom_nodes = [
                {"tag": "html", "x": 0, "y": 0, "w": 1440, "h": 100, "pIdx": None},
                {"tag": "span", "x": 1361, "y": 15, "w": 56, "h": 19, "pIdx": 0},
            ]

            design = build_direct_design(som, dom_nodes=dom_nodes)

        element = next(item for item in design["elements"] if item["id"] == "plus")
        self.assertEqual(
            (element["x"], element["y"], element["width"], element["height"]),
            (1361, 15, 56, 19),
        )

    def test_measured_single_line_collapses_source_indentation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "page.png"
            Image.new("RGB", (240, 80), "white").save(image_path)
            som = {
                "image": str(image_path),
                "size": [240, 80],
                "containers": [],
                "elements": [
                    {
                        "id": "count",
                        "bbox": [10, 10, 67, 15],
                        "type": "text",
                        "text": "11赞 ·\n            1评论",
                        "textEmBox": [10, 10, 67, 15],
                        "textEmLines": 1,
                        "style": {"fontSize": 12, "textColor": "#666666"},
                        "domIndex": 1,
                    }
                ],
                "provenance": {"route": "dom", "capture": {}},
            }
            dom_nodes = [
                {"tag": "html", "x": 0, "y": 0, "w": 240, "h": 80, "pIdx": None},
                {"tag": "p", "x": 10, "y": 10, "w": 67, "h": 15, "pIdx": 0},
            ]

            design = build_direct_design(som, dom_nodes=dom_nodes)

        element = next(item for item in design["elements"] if item["id"] == "count")
        self.assertEqual(element["text"], "11赞 · 1评论")


if __name__ == "__main__":
    unittest.main()
