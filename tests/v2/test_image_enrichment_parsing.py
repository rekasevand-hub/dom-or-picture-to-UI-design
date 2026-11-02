from __future__ import annotations

import json

import pytest

from src.app.services.structure.image_enrichment.parsing import (
    parse_enrichment_response,
)
from src.app.services.structure.image_enrichment.prompts import (
    build_background_mask_prompt,
    build_grounding_tile_prompt,
)


def test_parser_keeps_assets_and_clips_background_overlays():
    raw = (
        '{"assets":[{"name":"hero","kind":"illustration","bbox":'
        '{"x":-5,"y":4,"width":40,"height":30}}],"backgrounds":'
        '[{"id":"bg","bbox":{"x":0,"y":0,"width":320,"height":240},'
        '"overlays":[{"id":"nav","name":"Nav","kind":"code-overlay",'
        '"bbox":{"x":-10,"y":2,"width":50,"height":20}}]}]}'
    )

    parsed = parse_enrichment_response(raw, 100, 80)

    assert parsed["assets"][0]["bbox"] == [0, 4, 35, 30]
    assert parsed["backgrounds"][0]["overlays"][0]["bbox"] == [0, 2, 40, 20]


def test_parser_keeps_only_approved_asset_kinds_and_excludes_ui_text():
    allowed = [
        "icon",
        "avatar",
        "illustration",
        "photo",
        "product-image",
        "complex-decoration",
        "complex-chart",
        "logo",
    ]
    raw = json.dumps(
        {
            "assets": [
                {
                    "kind": kind,
                    "bbox": {"x": index * 10, "y": 0, "width": 8, "height": 8},
                }
                for index, kind in enumerate(allowed)
            ]
            + [
                {
                    "kind": "text",
                    "bbox": {"x": 0, "y": 20, "width": 40, "height": 12},
                },
                {
                    "kind": "button",
                    "bbox": {"x": 0, "y": 40, "width": 40, "height": 20},
                },
            ]
        }
    )

    parsed = parse_enrichment_response(raw, 320, 240)

    assert [asset["kind"] for asset in parsed["assets"]] == allowed
    assert parsed["assets"][0]["name"] == "slice_01"
    assert {
        item["code"] for item in parsed["diagnostics"]
        if item["code"] == "unsupported_asset_kind"
    } == {"unsupported_asset_kind"}


def test_parser_normalizes_asset_names_and_clamps_confidence():
    raw = json.dumps(
        {
            "assets": [
                {
                    "name": " Hero Image.PNG ",
                    "kind": "illustration",
                    "bbox": {"x": 0, "y": 0, "width": 40, "height": 30},
                    "confidence": 2,
                },
                {
                    "name": "Hero Image.PNG",
                    "kind": "photo",
                    "bbox": {"x": 40, "y": 0, "width": 40, "height": 30},
                    "confidence": -1,
                },
            ]
        }
    )

    parsed = parse_enrichment_response(raw, 100, 80)

    assert [asset["name"] for asset in parsed["assets"]] == [
        "hero_image",
        "hero_image_2",
    ]
    assert [asset["confidence"] for asset in parsed["assets"]] == [1.0, 0.0]


def test_parser_reports_invalid_bbox_forms_and_tiny_assets():
    raw = json.dumps(
        {
            "assets": [
                {
                    "name": "list_bbox",
                    "kind": "illustration",
                    "bbox": [0, 0, 20, 20],
                },
                {
                    "name": "tiny",
                    "kind": "icon",
                    "bbox": {"x": 1, "y": 1, "width": 3, "height": 3},
                },
                {
                    "name": "non_finite",
                    "kind": "logo",
                    "bbox": {"x": 0, "y": 0, "width": "20", "height": 20},
                },
            ]
        }
    )

    parsed = parse_enrichment_response(raw, 100, 80)

    assert parsed["assets"] == []
    assert [item["code"] for item in parsed["diagnostics"]] == [
        "invalid_asset_bbox",
        "asset_too_small",
        "invalid_asset_bbox",
    ]


def test_parser_caps_overlays_and_reports_truncation():
    overlays = [
        {
            "id": f"overlay_{index:02d}",
            "name": f"overlay_{index:02d}",
            "kind": "code-overlay",
            "bbox": {"x": index, "y": 2, "width": 8, "height": 8},
        }
        for index in range(50)
    ]
    raw = json.dumps(
        {
            "backgrounds": [
                {
                    "id": "bg",
                    "name": "hero_background",
                    "bbox": {"x": 0, "y": 0, "width": 320, "height": 240},
                    "overlays": overlays,
                }
            ]
        }
    )

    parsed = parse_enrichment_response(raw, 320, 240)

    assert len(parsed["backgrounds"][0]["overlays"]) == 48
    assert any(
        item["code"] == "overlay_limit_truncated"
        for item in parsed["diagnostics"]
    )


def test_parser_drops_unsupported_overlay_kinds():
    raw = json.dumps(
        {
            "backgrounds": [
                {
                    "id": "bg",
                    "bbox": {"x": 0, "y": 0, "width": 100, "height": 80},
                    "overlays": [
                        {
                            "id": "button",
                            "name": "Button",
                            "kind": "button-overlay",
                            "bbox": {"x": 2, "y": 2, "width": 20, "height": 12},
                        }
                    ],
                }
            ]
        }
    )

    parsed = parse_enrichment_response(raw, 100, 80)

    assert parsed["backgrounds"][0]["overlays"] == []
    assert any(
        item["code"] == "unsupported_overlay_kind"
        for item in parsed["diagnostics"]
    )


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "```json\n{\"assets\": [}\n```",
    ],
)
def test_parser_rejects_invalid_json_with_readable_error(raw):
    with pytest.raises(ValueError, match="JSON"):
        parse_enrichment_response(raw, 100, 80)


@pytest.mark.parametrize("width,height", [(0, 100), (100, 0), (True, 100)])
def test_parser_rejects_invalid_source_dimensions(width, height):
    with pytest.raises(ValueError, match="image size"):
        parse_enrichment_response("{}", width, height)


def test_grounding_tile_prompt_preserves_page_and_tile_coordinates():
    tile = {
        "id": "tile-0001",
        "source_rect": [0, 3968, 1200, 4096],
        "page_origin": [0, 3968],
    }
    page_context = {
        "image_size": [2544, 6156],
        "section": "hash-table-optimization",
        "overlap_with_previous": 128,
    }

    prompt = build_grounding_tile_prompt(tile, page_context)

    assert "2544x6156" in prompt
    assert "1200x4096" in prompt
    assert "tile-0001" in prompt
    assert "pixel coordinates relative to this tile" in prompt
    assert "Do not return ordinary UI text" in prompt
    assert "snake_case" in prompt
    assert "product-image" in prompt
    assert "code-overlay" in prompt
    assert "raster-overlay" in prompt
    assert "hash-table-optimization" in prompt


def test_background_mask_prompt_preserves_mask_and_baked_content_rules():
    background = {
        "id": "hero_bg",
        "name": "hero_background",
        "bbox": [0, 0, 320, 240],
    }
    overlays = [
        {
            "id": "nav",
            "name": "Navigation",
            "kind": "code-overlay",
            "bbox": [0, 0, 320, 48],
        },
        {
            "id": "art",
            "name": "Artwork",
            "kind": "raster-overlay",
            "bbox": [20, 60, 200, 120],
        },
    ]

    prompt = build_background_mask_prompt(background, overlays)

    assert "hero_bg" in prompt
    assert "hero_background" in prompt
    assert "[0, 0, 320, 240]" in prompt
    assert "nav" in prompt
    assert "art" in prompt
    assert "transparent" in prompt
    assert "opaque" in prompt
    assert "baked visual content" in prompt
    assert "Do not invent" in prompt
