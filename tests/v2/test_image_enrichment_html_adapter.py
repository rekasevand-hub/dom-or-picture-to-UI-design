from __future__ import annotations

import base64
import io
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pytest
from PIL import Image

from src.app.services.rendering.adapter_factory import build_adapter
from src.app.services.rendering.html_adapter import HTMLAdapter


def _png() -> str:
    output = io.BytesIO()
    Image.new("RGB", (20, 12), "#2f6fed").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _design() -> dict:
    return {
        "name": "Enriched page",
        "canvas": {
            "width": 400,
            "height": 300,
            "background": "#f7f8fa",
        },
        "elements": [
            {
                "id": "panel",
                "type": "rectangle",
                "x": 0,
                "y": 0,
                "width": 400,
                "height": 70,
                "style": {"fillColor": "#24324a"},
                "zIndex": 0,
            },
            {
                "id": "title",
                "type": "text",
                "text": "Title & <More>",
                "x": 20,
                "y": 20,
                "width": 180,
                "height": 30,
                "style": {
                    "fontFamily": "Arial",
                    "fontSize": 20,
                    "fontWeight": "bold",
                    "textColor": "#ffffff",
                },
                "zIndex": 2,
                "clipToBounds": True,
            },
            {
                "id": "generated-image",
                "type": "image",
                "x": 220,
                "y": 100,
                "width": 120,
                "height": 80,
                "imageBase64": _png(),
                "imageMVP": {
                    "generated": True,
                    "reference_only": False,
                },
                "zIndex": 1,
            },
            {
                "id": "save",
                "type": "button",
                "text": "Save",
                "x": 20,
                "y": 120,
                "width": 100,
                "height": 36,
                "style": {
                    "fillColor": "#2f6fed",
                    "textColor": "#ffffff",
                    "fontSize": 14,
                },
                "zIndex": 3,
            },
        ],
        "_meta": {"imageMVP": {"referenceUnderlays": []}},
    }


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        if data.strip():
            self.text.append(data)


def test_html_adapter_renders_native_text_local_images_and_paint_order():
    with tempfile.TemporaryDirectory() as raw_dir:
        output = Path(raw_dir)
        adapter = HTMLAdapter(output)
        adapter.render_design(_design())
        html = (output / "prototype.html").read_text("utf-8")
        css = (output / "styles.css").read_text("utf-8")
        parser = _Collector()
        parser.feed(html)
        asset_files = {path.name for path in (output / "assets").iterdir()}
        elements = [
            attrs
            for tag, attrs in parser.tags
            if attrs.get("data-element-id")
        ]
        images = [
            attrs
            for tag, attrs in parser.tags
            if tag == "img" and attrs.get("data-element-id")
        ]

    assert "Title &amp; &lt;More&gt;" in html
    assert "Title & <More>" in parser.text
    assert "Save" in parser.text
    assert {item["data-element-id"] for item in elements} == {
        "panel",
        "title",
        "generated-image",
        "save",
    }
    assert len(images) == 1
    assert images[0]["src"].startswith("assets/")
    assert images[0]["data-generated"] == "true"
    assert images[0]["src"].endswith(".png")
    assert Path(images[0]["src"]).name in asset_files
    assert "width:400px" in css
    assert "height:300px" in css
    assert "position:absolute" in css
    assert "z-index:2" in css
    assert "overflow:hidden" in css
    paint_orders = [int(item["data-paint-order"]) for item in elements]
    assert paint_orders == sorted(paint_orders)
    assert [item["data-element-id"] for item in elements] == [
        "panel",
        "generated-image",
        "title",
        "save",
    ]


def test_adapter_factory_builds_html_adapter():
    with tempfile.TemporaryDirectory() as raw_dir:
        config = type(
            "Config",
            (),
            {"output_dir": Path(raw_dir)},
        )()
        adapter = build_adapter("html", config)

    assert isinstance(adapter, HTMLAdapter)
    assert adapter.output_dir == Path(raw_dir)


def test_html_adapter_rejects_visible_full_screenshot_underlay():
    design = _design()
    design["elements"].append(
        {
            "id": "full-underlay",
            "type": "image",
            "x": 0,
            "y": 0,
            "width": 400,
            "height": 300,
            "imageBase64": _png(),
        }
    )
    with tempfile.TemporaryDirectory() as raw_dir:
        with pytest.raises(ValueError, match="underlay"):
            HTMLAdapter(raw_dir).render_design(design)
