from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.app.services.som.direct_design import build_direct_design
from src.app.services.structure.capture import DOM_JS
from src.app.services.structure.text_model import build_text_model


def _style(**overrides) -> dict:
    value = {
        "fontSize": "16px",
        "fontWeight": "400",
        "fontStyle": "normal",
        "fontFamily": "sans-serif",
    }
    value.update(overrides)
    return value


def _node(index: int, **values) -> dict:
    node = {
        "tag": "div",
        "x": 0,
        "y": index * 30,
        "w": 600,
        "h": 30,
        "interactive": False,
    }
    node.update(values)
    return node


def test_build_text_model_normalizes_runs_roles_lines_and_inline_images() -> None:
    nodes = [
        _node(0, tag="body", w=800, h=600),
        _node(
            1,
            id="0",
            tag="p",
            pIdx=0,
            text="Before bold italic code link",
            richRuns=[
                {"kind": "text", "text": "Before ", "style": _style()},
                {
                    "kind": "text",
                    "text": "bold",
                    "style": _style(fontWeight="700"),
                },
                {"kind": "text", "text": " ", "style": _style()},
                {
                    "kind": "text",
                    "text": "italic",
                    "style": _style(fontStyle="italic"),
                },
                {"kind": "text", "text": " ", "style": _style()},
                {
                    "kind": "text",
                    "text": "code",
                    "style": _style(fontFamily="monospace"),
                },
                {
                    "kind": "text",
                    "text": " link",
                    "style": _style(textColor="#0055aa"),
                },
            ],
            textLines=[
                {"text": "Before bold italic", "box": [0, 0, 210, 24]},
                {"text": "code link", "box": [0, 24, 90, 24]},
            ],
            textBaseline={
                "y": 18,
                "ascent": 14,
                "descent": 4,
                "method": "canvas",
                "lineCount": 2,
            },
        ),
        _node(2, id="1", tag="strong", pIdx=1, text="bold", fontWeight="700"),
        _node(3, id="2", tag="em", pIdx=1, text="italic", fontStyle="italic"),
        _node(4, id="3", tag="code", pIdx=1, text="code", fontFamily="monospace"),
        _node(5, id="4", tag="span", pIdx=1, text="link", display="inline"),
        _node(
            6,
            id="button",
            tag="button",
            pIdx=0,
            text="Search",
            textRoleHint="button-label",
            interactive=True,
        ),
        _node(
            7,
            id="cjk",
            tag="p",
            pIdx=0,
            text="中文句子在第一行换行，第二行继续。",
            textEmLines=2,
            textEmBox=[0, 60, 280, 26],
            textBaseline={
                "y": 75,
                "ascent": 16,
                "descent": 5,
                "method": "canvas",
                "lineCount": 2,
            },
        ),
        _node(
            8,
            id="image-copy",
            tag="p",
            pIdx=0,
            text="Intro After",
            richRuns=[
                {"kind": "text", "text": "Intro ", "style": _style()},
                {
                    "kind": "inline-image",
                    "text": "",
                    "assetSrc": "https://example.test/hero.png",
                    "style": _style(),
                },
                {"kind": "text", "text": " After", "style": _style()},
            ],
        ),
    ]

    model = build_text_model(nodes)

    paragraph = model["blocks"]["text-0"]
    assert [run["text"] for run in paragraph["runs"]] == [
        "Before ",
        "bold",
        " ",
        "italic",
        " ",
        "code",
        " link",
    ]
    assert paragraph["runs"][1]["style"]["fontWeight"] == "700"
    assert model["inlineConsumed"] == ["1", "2", "3", "4"]
    assert model["blocks"]["text-1"]["role"] == "button-label"
    assert model["blocks"]["text-2"]["measuredLineCount"] >= 2
    assert model["blocks"]["text-3"]["runs"][1]["kind"] == "inline-image"
    assert paragraph["sourceIndex"] == 1
    assert paragraph["runs"][0]["sourceIndex"] == 1
    assert paragraph["measuredLines"][0]["text"] == "Before bold italic"


class DomTextCaptureHintTests(unittest.TestCase):
    def test_capture_emits_semantic_hints_and_inline_image_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "text-hints.html"
            fixture.write_text(
                """
                <!doctype html>
                <h2 id="heading">Canonical heading</h2>
                <button id="button"><span id="button-label">Search</span></button>
                <ul>
                  <li id="item">First item</li>
                </ul>
                <p id="image-copy">Before <img alt="dot" width="12" height="12"
                  src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==">
                  after</p>
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

        by_id = {node.get("id"): node for node in nodes if node.get("id")}
        self.assertEqual(by_id["heading"]["textRoleHint"], "heading")
        self.assertEqual(by_id["button-label"]["textRoleHint"], "button-label")
        self.assertEqual(by_id["item"]["listMarker"], {"type": "unordered", "level": 1})
        self.assertTrue(by_id["image-copy"]["richRuns"][1]["kind"] == "inline-image")
        image = next(node for node in nodes if node.get("tag") == "img")
        self.assertTrue(image["inlineImageBoundary"])


def _text_design_fixture() -> tuple[dict, list[dict]]:
    dom_nodes = [
        _node(0, tag="body", w=320, h=180),
        _node(
            1,
            id="paragraph",
            tag="p",
            pIdx=0,
            text="Before bold italic",
            richRuns=[
                {"kind": "text", "text": "Before ", "style": _style()},
                {
                    "kind": "text",
                    "text": "bold",
                    "style": _style(fontWeight="700"),
                },
                {"kind": "text", "text": " italic", "style": _style()},
            ],
            textLines=[
                {"text": "Before bold", "box": [10, 10, 120, 24]},
                {"text": "italic", "box": [10, 34, 60, 24]},
            ],
            textEmLines=2,
            textBaseline={
                "y": 26,
                "ascent": 16,
                "descent": 5,
                "method": "canvas",
                "lineCount": 2,
            },
        ),
    ]
    som = {
        "image": "",
        "size": [320, 180],
        "containers": [],
        "elements": [
            {
                "id": 1,
                "bbox": [10, 10, 200, 48],
                "type": "text",
                "text": "Before bold italic",
                "domIndex": 1,
                "style": {
                    "textColor": "#111111",
                    "fontSize": 16,
                    "fontWeight": "400",
                    "fontFamily": "sans-serif",
                },
            }
        ],
        "provenance": {
            "route": "dom",
            "capture": {
                "viewport": {"width": 320, "height": 180},
                "canvas_size": [320, 180],
                "device_scale_factor": 1,
            },
        },
    }
    return som, dom_nodes


def test_text_model_design_fields_are_feature_flagged(monkeypatch):
    som, dom_nodes = _text_design_fixture()
    monkeypatch.delenv("DOM_TEXT_MODEL_V2", raising=False)
    legacy = build_direct_design(som, dom_nodes=dom_nodes)
    legacy_text = next(item for item in legacy["elements"] if item["type"] == "text")
    assert "textModelId" not in legacy_text

    monkeypatch.setenv("DOM_TEXT_MODEL_V2", "true")
    current = build_direct_design(som, dom_nodes=dom_nodes)
    text_elements = [item for item in current["elements"] if item["type"] == "text"]
    assert len(text_elements) == 1
    item = text_elements[0]
    assert item["textModelId"] == "text-0"
    assert item["paragraphRole"] == "paragraph"
    assert item["textRuns"][1]["text"] == "bold"
    assert item["measuredLines"][0]["text"] == "Before bold"
