from __future__ import annotations

from playwright.sync_api import sync_playwright
from PIL import Image

from src.app.services.som.direct_design import build_direct_design
from src.app.services.structure.capture import DOM_JS
from src.app.services.structure.visual_assets import build_visual_assets


def test_visual_assets_materialize_background_gradients_and_pseudos():
    nodes = [
        {
            "tag": "div",
            "x": 0,
            "y": 0,
            "w": 200,
            "h": 100,
            "backgroundLayers": [
                {
                    "kind": "image",
                    "source": "https://example.test/hero.png",
                    "size": "cover",
                    "position": "50% 50%",
                    "repeat": "no-repeat",
                }
            ],
        },
        {
            "tag": "div",
            "x": 0,
            "y": 100,
            "w": 200,
            "h": 100,
            "backgroundLayers": [
                {
                    "kind": "gradient",
                    "css": "linear-gradient(90deg, #ffffff 0%, #112233 100%)",
                }
            ],
        },
        {
            "tag": "span",
            "x": 10,
            "y": 220,
            "w": 20,
            "h": 20,
            "pseudoBefore": {
                "content": '"•"',
                "display": "block",
                "position": "absolute",
            },
        },
        {
            "tag": "span",
            "x": 40,
            "y": 220,
            "w": 16,
            "h": 16,
            "pseudoAfter": {
                "content": 'url("https://example.test/search.svg")',
                "display": "inline-block",
                "position": "static",
            },
        },
        {
            "tag": "div",
            "x": 0,
            "y": 260,
            "w": 240,
            "h": 80,
            "text": "Caption over image",
            "backgroundLayers": [
                {
                    "kind": "image",
                    "source": "https://example.test/hero.png",
                    "size": "cover",
                    "position": "center",
                    "repeat": "no-repeat",
                }
            ],
        },
    ]
    manifest = {
        "assets": [
            {
                "source_url": "https://example.test/hero.png",
                "status": "verified-original",
                "locator": "assets/hero.png",
                "sha256": "a" * 64,
            }
        ]
    }

    assets = build_visual_assets(nodes, manifest)

    assert assets["byDom"][0]["kind"] == "background-image"
    assert assets["byDom"][0]["displayMode"] == "image-fill"
    assert assets["byDom"][1]["gradient"]["stops"] == ["#ffffff", "#112233"]
    assert assets["byDom"][2]["pseudo"] == "before"
    assert assets["byDom"][2]["kind"] == "text"
    assert assets["byDom"][3]["kind"] == "mask"
    assert assets["byDom"][4]["displayMode"] == "source-crop"
    assert assets["byDom"][4]["visualFallbackReason"]


def test_direct_design_materializes_pseudo_only_when_flagged(tmp_path, monkeypatch):
    screenshot = tmp_path / "page.png"
    Image.new("RGB", (240, 160), "white").save(screenshot)
    dom_nodes = [
        {
            "tag": "span",
            "x": 20,
            "y": 30,
            "w": 16,
            "h": 16,
            "interactive": False,
            "pseudoBefore": {
                "content": '"•"',
                "display": "block",
                "position": "absolute",
                "color": "rgb(17, 34, 51)",
            },
        }
    ]
    som = {
        "image": str(screenshot),
        "size": [240, 160],
        "containers": [],
        "elements": [],
        "provenance": {
            "route": "dom",
            "capture": {
                "viewport": {"width": 240, "height": 160},
                "canvas_size": [240, 160],
                "device_scale_factor": 1,
            },
        },
    }

    monkeypatch.setenv("DOM_VISUAL_ASSETS_V2", "false")
    legacy = build_direct_design(som, dom_nodes=dom_nodes)
    assert not [item for item in legacy["elements"] if item.get("source") == "dom:pseudo"]

    monkeypatch.setenv("DOM_VISUAL_ASSETS_V2", "true")
    current = build_direct_design(som, dom_nodes=dom_nodes)
    pseudo = next(item for item in current["elements"] if item.get("source") == "dom:pseudo")
    assert pseudo["text"] == "•"
    assert pseudo["visualAssetId"].startswith("visual-0-")


def test_visual_assets_are_enabled_by_default(tmp_path, monkeypatch):
    screenshot = tmp_path / "page.png"
    Image.new("RGB", (240, 160), "white").save(screenshot)
    dom_nodes = [
        {
            "tag": "span",
            "x": 20,
            "y": 30,
            "w": 16,
            "h": 16,
            "interactive": False,
            "pseudoBefore": {
                "content": '"•"',
                "display": "block",
                "position": "absolute",
                "color": "rgb(17, 34, 51)",
            },
        }
    ]
    som = {
        "image": str(screenshot),
        "size": [240, 160],
        "containers": [],
        "elements": [],
        "provenance": {
            "route": "dom",
            "capture": {
                "viewport": {"width": 240, "height": 160},
                "canvas_size": [240, 160],
                "device_scale_factor": 1,
            },
        },
    }
    monkeypatch.delenv("DOM_VISUAL_ASSETS_V2", raising=False)

    design = build_direct_design(som, dom_nodes=dom_nodes)

    assert any(item.get("source") == "dom:pseudo" for item in design["elements"])


def test_browser_capture_emits_structured_background_layers(tmp_path):
    fixture = tmp_path / "background.html"
    fixture.write_text(
        """
        <!doctype html>
        <div id="hero" style="width:200px;height:100px;
          background-image:linear-gradient(90deg,#fff,#112233),
          url('data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==');
          background-size:100% 100%,cover;
          background-position:center,50% 50%;
          background-repeat:no-repeat,no-repeat"></div>
        """,
        encoding="utf-8",
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 400, "height": 200})
            page.goto(fixture.resolve().as_uri(), wait_until="domcontentloaded")
            nodes = page.evaluate(DOM_JS)
        finally:
            browser.close()

    hero = next(node for node in nodes if node.get("id") == "hero")
    layers = hero["backgroundLayers"]
    assert layers[0]["kind"] == "gradient"
    assert layers[1]["kind"] == "image"
    assert layers[1]["size"] == "cover"
    assert layers[1]["position"] == "50% 50%"


def test_visual_source_crop_is_clamped_to_screenshot_canvas(tmp_path, monkeypatch):
    screenshot = tmp_path / "page.png"
    Image.new("RGB", (160, 100), "white").save(screenshot)
    dom_nodes = [
        {
            "tag": "section",
            "x": 0,
            "y": 0,
            "w": 160,
            "h": 200,
            "interactive": False,
            "backgroundLayers": [
                {
                    "kind": "image",
                    "source": "https://example.test/page-bg.png",
                }
            ],
        }
    ]
    som = {
        "image": str(screenshot),
        "size": [160, 100],
        "containers": [],
        "elements": [],
        "provenance": {
            "route": "dom",
            "capture": {
                "viewport": {"width": 160, "height": 100},
                "canvas_size": [160, 100],
                "device_scale_factor": 1,
            },
        },
    }

    monkeypatch.setenv("DOM_VISUAL_ASSETS_V2", "true")
    design = build_direct_design(som, dom_nodes=dom_nodes)

    visual = next(
        item for item in design["elements"] if item.get("visualAssetId") == "visual-0-0"
    )
    assert visual["y"] == 0
    assert visual["height"] == 100
