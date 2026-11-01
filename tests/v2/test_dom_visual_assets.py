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
    assert assets["byDom"][4]["displayMode"] == "image-fill"


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


def test_text_over_unverified_background_does_not_become_source_crop(
    tmp_path,
    monkeypatch,
) -> None:
    screenshot = tmp_path / "page.png"
    Image.new("RGB", (240, 120), "white").save(screenshot)
    dom_nodes = [
        {
            "tag": "section",
            "x": 0,
            "y": 0,
            "w": 240,
            "h": 120,
            "interactive": False,
            "text": "Editable headline",
            "backgroundLayers": [
                {
                    "kind": "image",
                    "source": "https://example.test/missing-background.png",
                }
            ],
        }
    ]
    som = {
        "image": str(screenshot),
        "size": [240, 120],
        "containers": [],
        "elements": [
            {
                "id": 1,
                "bbox": [0, 40, 240, 30],
                "type": "text",
                "text": "Editable headline",
                "domIndex": 0,
                "style": {
                    "textColor": "#111111",
                    "fontSize": 20,
                    "fontFamily": "Arial",
                },
            }
        ],
        "provenance": {
            "route": "dom",
            "capture": {
                "viewport": {"width": 240, "height": 120},
                "canvas_size": [240, 120],
                "device_scale_factor": 1,
            },
        },
    }
    monkeypatch.setenv("DOM_VISUAL_ASSETS_V2", "true")

    design = build_direct_design(som, dom_nodes=dom_nodes)

    generated_background = [
        item
        for item in design["elements"]
        if item.get("source") == "dom:background"
    ]
    assert len(generated_background) == 1
    assert generated_background[0]["type"] == "image"
    assert generated_background[0]["generatedImageRequired"] is True
    assert "imageBase64" not in generated_background[0]
    assert "generationReferenceImageBase64" not in generated_background[0]
    assert any(
        item.get("type") == "text"
        and item.get("text") == "Editable headline"
        for item in design["elements"]
    )


def test_code_block_is_one_image_but_inline_code_stays_text(
    tmp_path,
    monkeypatch,
) -> None:
    screenshot = tmp_path / "page.png"
    image = Image.new("RGB", (320, 180), "white")
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 300, 120), fill="black")
    draw.text((36, 48), "const answer = 42;", fill="white")
    image.save(screenshot)
    dom_nodes = [
        {"tag": "body", "x": 0, "y": 0, "w": 320, "h": 180},
        {
            "tag": "pre",
            "x": 20,
            "y": 20,
            "w": 280,
            "h": 100,
            "pIdx": 0,
            "text": "const answer = 42;",
        },
        {
            "tag": "code",
            "x": 36,
            "y": 48,
            "w": 160,
            "h": 20,
            "pIdx": 1,
            "text": "const answer = 42;",
        },
        {
            "tag": "code",
            "x": 20,
            "y": 140,
            "w": 90,
            "h": 20,
            "pIdx": 0,
            "display": "inline",
            "text": "inlineCode",
        },
    ]
    som = {
        "image": str(screenshot),
        "size": [320, 180],
        "containers": [],
        "elements": [
            {
                "id": 1,
                "bbox": [36, 48, 160, 20],
                "type": "text",
                "text": "const answer = 42;",
                "domIndex": 2,
                "style": {"textColor": "#ffffff", "fontSize": 14},
            },
            {
                "id": 2,
                "bbox": [20, 140, 90, 20],
                "type": "text",
                "text": "inlineCode",
                "domIndex": 3,
                "style": {"textColor": "#111111", "fontSize": 14},
            },
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
    monkeypatch.setenv("DOM_VISUAL_ASSETS_V2", "true")

    design = build_direct_design(som, dom_nodes=dom_nodes)
    code_images = [
        item for item in design["elements"] if item.get("codeBlockImage")
    ]

    assert len(code_images) == 1
    assert code_images[0]["x"] == 20
    assert code_images[0]["width"] == 280
    assert not any(
        item.get("domIndex") in {1, 2}
        and item.get("type") == "text"
        for item in design["elements"]
    )
    assert any(
        item.get("domIndex") == 3 and item.get("text") == "inlineCode"
        for item in design["elements"]
    )


def test_screenshot_crop_containing_native_text_is_regenerated_without_text(
    tmp_path,
) -> None:
    screenshot = tmp_path / "page.png"
    Image.new("RGB", (400, 500), "white").save(screenshot)
    display_payload = {
        "status": "available",
        "kind": "screenshot-crop",
        "display_box": [0, 0, 400, 500],
        "original": False,
        "reference_only": True,
    }
    som = {
        "image": str(screenshot),
        "size": [400, 500],
        "containers": [],
        "elements": [
            {
                "id": "portrait",
                "bbox": [0, 0, 400, 500],
                "type": "image",
                "name": 'img.portrait "Portrait"',
                "domIndex": 1,
                "imageBase64": "AAAA",
                "displaySourceCrop": True,
                "displayPayload": display_payload,
                "sourceResolution": {
                    "display": {
                        "selected": "screenshot-crop",
                        "original": False,
                    }
                },
                "style": {},
            },
            {
                "id": "quote",
                "bbox": [20, 360, 330, 90],
                "type": "text",
                "text": "Editable testimonial text",
                "domIndex": 2,
                "style": {
                    "textColor": "#ffffff",
                    "fontSize": 18,
                    "lineHeight": 28,
                },
            },
        ],
        "provenance": {
            "route": "dom",
            "capture": {
                "viewport": {"width": 400, "height": 500},
                "canvas_size": [400, 500],
                "device_scale_factor": 1,
            },
        },
    }

    design = build_direct_design(som)
    portrait = next(item for item in design["elements"] if item["id"] == "portrait")
    quote = next(item for item in design["elements"] if item["id"] == "quote")

    assert portrait["generatedImageRequired"] is True
    assert portrait["sourceCropContamination"] == ["quote"]
    assert "generationReferenceImageBase64" not in portrait
    assert portrait["imagePrompt"] == 'img.portrait "Portrait"'
    assert "imageBase64" not in portrait
    assert "displaySourceCrop" not in portrait
    assert quote["type"] == "text"
    assert quote["text"] == "Editable testimonial text"
