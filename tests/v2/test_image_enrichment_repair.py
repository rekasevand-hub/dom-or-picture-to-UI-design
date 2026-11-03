from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from src.app.services.structure.image_enrichment.repair import (
    create_edge_blend_patch,
)


def test_edge_blend_patch_preserves_size_and_neutral_color():
    image = Image.new("RGB", (100, 80), (240, 240, 240))
    patch = create_edge_blend_patch(
        image,
        {"x": 20, "y": 10, "width": 40, "height": 30},
    )

    assert patch.size == (40, 30)
    assert patch.mode == "RGB"
    red, green, blue = patch.getpixel((20, 15))
    assert 230 <= red <= 245
    assert 230 <= green <= 245
    assert 230 <= blue <= 245
    assert patch.getpixel((0, 0)) == pytest.approx((240, 240, 240), abs=2)
    assert patch.getpixel((39, 29)) == pytest.approx((240, 240, 240), abs=2)


def test_edge_blend_patch_samples_immediate_side_colors():
    image = Image.new("RGB", (100, 80), "#4c8f3a")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 10, 59, 39), fill="#ffffff")
    patch = create_edge_blend_patch(
        image,
        {"x": 20, "y": 10, "width": 40, "height": 30},
    )

    for point in ((0, 0), (39, 0), (0, 29), (39, 29)):
        red, green, blue = patch.getpixel(point)
        assert green > red
        assert green > blue


@pytest.mark.parametrize(
    "placement",
    [
        {"x": -10, "y": 0, "width": 20, "height": 20},
        {"x": 10, "y": 10, "width": 0, "height": 20},
        {"x": 10, "y": 10},
    ],
)
def test_edge_blend_patch_rejects_invalid_placement(placement):
    with pytest.raises(ValueError):
        create_edge_blend_patch(Image.new("RGB", (40, 40), "white"), placement)
