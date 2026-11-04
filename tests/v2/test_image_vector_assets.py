from __future__ import annotations

from PIL import Image, ImageDraw

from src.app.services.structure.image_contract import (
    build_image_design,
    inspect_image_reference,
)
from src.app.services.structure.image_enrichment.assets import (
    recover_visible_assets,
)
from src.app.services.structure.image_enrichment.vector_icons import (
    vector_icon_svg,
)


def test_known_icon_asset_uses_svg_vector_instead_of_image_fill(tmp_path):
    image_path = tmp_path / "icons.png"
    image = Image.new("RGB", (240, 120), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.ellipse((28, 18, 52, 42), outline="#5d6570", width=2)
    draw.line((48, 38, 58, 48), fill="#5d6570", width=2)
    draw.rectangle((160, 20, 199, 49), fill="#2f6fed")
    image.save(image_path)
    graph = {
        "image": str(image_path),
        "image_w": 240,
        "image_h": 120,
        "route": "grounding",
        "containers": [],
        "elements": [],
        "imageEnrichment": {
            "mode": "apply",
            "assets": [
                {
                    "name": "search_icon",
                    "kind": "icon",
                    "bbox": [20, 10, 48, 48],
                },
                {
                    "name": "brand_logo",
                    "kind": "logo",
                    "bbox": [150, 12, 60, 48],
                },
            ],
        },
        "provenance": {"route": "grounding"},
    }

    recovered, _report = recover_visible_assets(
        graph,
        image_path,
        work_dir=tmp_path / "work",
    )
    design = build_image_design(recovered, inspect_image_reference(image_path))

    by_name = {
        element["assetName"]: element
        for element in design["elements"]
        if element.get("assetName")
    }
    assert by_name["search_icon"]["vectorSvg"].startswith("<svg")
    assert "imageBase64" not in by_name["search_icon"]
    assert by_name["brand_logo"]["imageBase64"]
    assert "vectorSvg" not in by_name["brand_logo"]


def test_vector_icon_helpers_match_common_ui_icons():
    search = vector_icon_svg("search", 24, 24, "#555555")
    mail = vector_icon_svg("toolbar_mail_icon", 22, 22, "#555555")
    home = vector_icon_svg("home", 22, 22, "#5b9e43")
    panel = vector_icon_svg("panel_left", 22, 22, "#9fb1c8")

    assert search and "<circle" in search
    assert mail and "<rect" in mail
    assert home and "<path" in home
    assert panel and "<rect" in panel
    assert vector_icon_svg("brand_logo", 24, 24, "#555555") is None


def test_structural_chrome_recovers_native_navigation_icons(tmp_path):
    image_path = tmp_path / "chrome.png"
    image = Image.new("RGB", (1200, 600), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 179, 599), fill="#364150")
    draw.rectangle((180, 0, 1199, 59), fill="#394353")
    draw.ellipse((836, 26, 852, 42), outline="#9fb1c8", width=2)
    draw.rectangle((21, 100, 42, 121), outline="#5b9e43", width=2)
    image.save(image_path)
    graph = {
        "image": str(image_path),
        "image_w": 1200,
        "image_h": 600,
        "route": "grounding",
        "containers": [
            {"id": "C1", "bbox": [0, 0, 180, 600], "role": "sidebar"},
            {"id": "C2", "bbox": [180, 0, 1020, 60], "role": "header"},
            {"id": "C3", "bbox": [180, 60, 1020, 540], "role": "main-content"},
        ],
        "elements": [
            {
                "id": 1,
                "bbox": [50, 100, 60, 20],
                "type": "text",
                "text": "首页",
            },
            {
                "id": 2,
                "bbox": [220, 20, 100, 20],
                "type": "text",
                "text": "FlexWeaver",
            },
            {
                "id": 3,
                "bbox": [220, 80, 100, 20],
                "type": "text",
                "text": "自动备份",
            },
        ],
        "imageEnrichment": {"mode": "apply"},
        "provenance": {"route": "grounding"},
    }

    design = build_image_design(graph, inspect_image_reference(image_path))

    icon_elements = [
        element for element in design["elements"] if element.get("role") == "ui-icon"
    ]
    icons = {element["assetName"]: element for element in icon_elements}
    assert {"menu", "search", "mail", "home", "file-text"} <= set(icons)
    assert all(icon.get("vectorSvg", "").startswith("<svg") for icon in icons.values())
    assert all(icon["width"] <= 32 and icon["height"] <= 32 for icon in icons.values())
    assert "#5b9e43" in icons["home"]["vectorSvg"]
    assert any(
        icon.get("geometrySource") == "raster-vector-trace" for icon in icon_elements
    )
