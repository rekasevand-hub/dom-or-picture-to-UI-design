from __future__ import annotations

import pytest
from PIL import Image

from src.app.services.structure.image_enrichment.tiling import (
    crop_image_tile,
    plan_image_tiles,
    translate_bbox_to_page,
)
from src.config.settings import Config


def test_long_image_is_fully_covered_without_changing_resolution():
    tiles = plan_image_tiles(1200, 9000, max_tile_height=4096, overlap=128)

    assert [tile["source_rect"] for tile in tiles] == [
        [0, 0, 1200, 4096],
        [0, 3968, 1200, 4096],
        [0, 7936, 1200, 1064],
    ]
    assert [tile["overlap_with_previous"] for tile in tiles] == [0, 128, 128]
    assert [tile["reason"] for tile in tiles] == [
        "page-start",
        "configured-height",
        "page-end",
    ]
    assert [tile["id"] for tile in tiles] == [
        "tile-0000",
        "tile-0001",
        "tile-0002",
    ]
    assert tiles[-1]["source_rect"][1] + tiles[-1]["source_rect"][3] == 9000
    assert all(
        current["source_rect"][1]
        <= previous["source_rect"][1] + previous["source_rect"][3]
        for previous, current in zip(tiles, tiles[1:])
    )
    assert translate_bbox_to_page([0.25, 0.5, 0.5, 1.0], tiles[1]) == [
        300,
        6016,
        600,
        4096,
    ]


def test_ordinary_image_uses_one_unscaled_tile():
    tiles = plan_image_tiles(1200, 826, max_tile_height=4096, overlap=256)

    assert len(tiles) == 1
    assert tiles[0]["source_rect"] == [0, 0, 1200, 826]
    assert tiles[0]["page_origin"] == [0, 0]
    assert tiles[0]["overlap_with_previous"] == 0
    assert tiles[0]["reason"] == "single-tile"


def test_tile_crop_preserves_source_pixels():
    image = Image.new("RGB", (8, 12), "white")
    for y in range(12):
        for x in range(8):
            image.putpixel((x, y), (x, y, (x + y) % 256))

    tiles = plan_image_tiles(8, 12, max_tile_height=8, overlap=2)
    assert crop_image_tile(image, tiles[0]).size == (8, 8)

    second = crop_image_tile(image, tiles[1])
    assert second.size == (8, 6)
    assert second.getpixel((3, 0)) == image.getpixel((3, 6))
    assert second.getpixel((7, 5)) == image.getpixel((7, 11))


def test_break_y_aligns_tiles_inside_the_overlap_window():
    tiles = plan_image_tiles(
        200,
        9000,
        max_tile_height=4096,
        overlap=128,
        break_y=[100, 4000, 8000, 9000],
    )

    assert [tile["source_rect"][1] for tile in tiles] == [0, 4000, 8000]
    assert [tile["source_rect"][3] for tile in tiles] == [4096, 4096, 1000]
    assert [tile["overlap_with_previous"] for tile in tiles] == [0, 96, 96]
    assert [tile["reason"] for tile in tiles] == [
        "page-start",
        "section-boundary",
        "section-boundary",
    ]
    assert tiles[-1]["source_rect"][1] + tiles[-1]["source_rect"][3] == 9000


def test_overlap_is_clamped_below_tile_height_to_guarantee_progress():
    tiles = plan_image_tiles(10, 10, max_tile_height=4, overlap=99)

    assert [tile["source_rect"][1] for tile in tiles] == list(range(7))
    assert [tile["overlap_with_previous"] for tile in tiles[1:]] == [3] * 6
    assert tiles[-1]["source_rect"][1] + tiles[-1]["source_rect"][3] == 10


@pytest.mark.parametrize(
    "kwargs",
    [
        {"width": 0, "height": 10},
        {"width": 10, "height": 0},
        {"width": 10, "height": 10, "max_tile_height": 0},
        {"width": 10, "height": 10, "overlap": -1},
    ],
)
def test_tile_planner_rejects_invalid_geometry(kwargs):
    with pytest.raises(ValueError):
        plan_image_tiles(**kwargs)


def test_translation_rejects_pixels_and_out_of_range_boxes():
    tile = plan_image_tiles(100, 100, max_tile_height=100, overlap=0)[0]

    with pytest.raises(ValueError, match="normalized"):
        translate_bbox_to_page([25, 20, 10, 10], tile)
    with pytest.raises(ValueError, match="normalized"):
        translate_bbox_to_page([0.9, 0.1, 1.2, 0.1], tile)


def test_crop_rejects_tile_rect_outside_image():
    image = Image.new("RGB", (8, 12), "white")
    tile = {
        "source_rect": [0, 8, 8, 8],
    }

    with pytest.raises(ValueError, match="outside"):
        crop_image_tile(image, tile)


def test_vision_tile_config_defaults_and_environment(monkeypatch):
    monkeypatch.delenv("VISION_TILE_MAX_HEIGHT", raising=False)
    monkeypatch.delenv("VISION_TILE_OVERLAP", raising=False)
    defaults = Config()
    assert defaults.vision_tile_max_height == 4096
    assert defaults.vision_tile_overlap == 256

    monkeypatch.setenv("VISION_TILE_MAX_HEIGHT", "2048")
    monkeypatch.setenv("VISION_TILE_OVERLAP", "64")
    configured = Config()
    assert configured.vision_tile_max_height == 2048
    assert configured.vision_tile_overlap == 64
