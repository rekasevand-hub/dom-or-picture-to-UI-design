from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from src.app.services.structure.fidelity.decoration_pixels import (
    ReferencePixels,
    control_palette,
    page_background,
    panel_decorations,
    solid_decorations,
)


def _page(path: Path) -> ReferencePixels:
    pixels = ReferencePixels.load(path)
    assert pixels is not None
    return pixels


def test_panels_separate_a_white_card_from_a_white_page(tmp_path: Path) -> None:
    """A 1px border is enough to split a card out of the page it sits on.

    Both are white, so any threshold on colour alone merges them; quantising
    first makes the border its own value and the components separate.
    """
    path = tmp_path / "page.png"
    image = Image.new("RGB", (240, 180), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 200, 150), outline="#e7e7ec", width=1)
    draw.rectangle((60, 70, 110, 90), fill="#333333")  # content inside the card
    image.save(path)

    panels = _page(path).panels(
        content_boxes=[[60, 70, 50, 20]],
        min_area=800,
    )

    boxes = [panel["bbox"] for panel in panels]
    # The component is the card *interior*: the 1px border is its own value.
    assert [41, 41, 159, 109] in boxes
    card = next(panel for panel in panels if panel["bbox"] == [41, 41, 159, 109])
    assert card["border"] is not None


def test_panels_ignore_gradient_tiles_without_content(tmp_path: Path) -> None:
    """A page gradient makes ~50px flat tiles; they hold nothing, so skip them."""
    path = tmp_path / "gradient.png"
    image = Image.new("RGB", (240, 180), "#ffffff")
    array = np.asarray(image).astype(np.int16)
    for y in range(180):
        for x in range(240):
            if x < 120:
                array[y, x] = (200 + x // 6, 210 + y // 8, 240)
    Image.fromarray(array.astype(np.uint8)).save(path)

    panels = _page(path).panels(content_boxes=[], min_area=800)

    assert panels == []


def test_solid_blocks_keep_a_bar_and_drop_a_text_blob(tmp_path: Path) -> None:
    path = tmp_path / "bars.png"
    image = Image.new("RGB", (240, 160), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 40, 200, 50), fill="#2a94e9")  # progress bar
    draw.rectangle((30, 96, 37, 156), fill="#19b7d5")  # accent bar
    for index in range(6):  # something that looks like blue text
        draw.rectangle((60 + index * 18, 110, 68 + index * 18, 128), fill="#99b0e4")
    image.save(path)

    blocks = _page(path).solid_blocks()
    boxes = [block["bbox"] for block in blocks]

    assert [20, 40, 181, 11] in boxes
    assert [30, 96, 8, 61] in boxes
    assert all(not (55 <= box[0] <= 160 and 100 <= box[1] <= 128) for box in boxes)


def test_page_background_uses_the_area_no_element_covers(tmp_path: Path) -> None:
    path = tmp_path / "page.png"
    image = Image.new("RGB", (200, 200), "#edf2fa")
    ImageDraw.Draw(image).rectangle((20, 20, 180, 180), fill="#ffffff")
    image.save(path)

    measured = page_background(
        _page(path),
        content_boxes=[[20, 20, 161, 161]],
        current="#ffffff",
    )

    # Trimmed median: the outermost tenth cannot drag the tone.
    assert measured == "#edf2fa"


def test_page_background_keeps_the_current_colour_when_nothing_is_exposed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "page.png"
    image = Image.new("RGB", (120, 120), "#333333")
    image.save(path)

    measured = page_background(
        _page(path),
        content_boxes=[[0, 0, 120, 120]],
        current="#ffffff",
    )

    assert measured == "#ffffff"


def test_panel_decorations_skip_an_area_an_image_already_covers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "page.png"
    image = Image.new("RGB", (240, 180), "#f4f7fc")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 120, 120), outline="#dfe4ee", width=1)
    draw.rectangle((150, 40, 210, 120), outline="#dfe4ee", width=1)
    image.save(path)

    pixels = _page(path)
    with_cover = panel_decorations(
        pixels,
        content_boxes=[[45, 45, 10, 10]],
        covered_boxes=[[40, 40, 81, 81]],
        limit=4,
    )
    boxes = [element for element in with_cover if element["role"] == "panel"]

    assert boxes, "the uncovered panel must still be emitted"
    assert all(
        not (element["x"] <= 42 and element["y"] <= 42)
        for element in boxes
    )


def test_solid_decorations_skip_a_bar_inside_an_image(tmp_path: Path) -> None:
    path = tmp_path / "bars.png"
    image = Image.new("RGB", (200, 120), "#ffffff")
    ImageDraw.Draw(image).rectangle((20, 30, 160, 40), fill="#2a94e9")
    image.save(path)

    pixels = _page(path)
    assert solid_decorations(pixels, covered=[]) != []
    assert solid_decorations(pixels, covered=[[20, 30, 141, 11]]) == []


def test_control_palette_reads_a_label_on_a_dark_page(tmp_path: Path) -> None:
    """A nav label is not a chip: most of its box is glyph, not surface.

    ``控制台`` rendered as ``fillColor #eff5e8 / textColor #1a1917`` -- the
    inverse of the screenshot, because the most common colour inside a tight
    text box is the *text*.
    """
    path = tmp_path / "dark.png"
    image = Image.new("RGB", (200, 100), "#1a1917")
    draw = ImageDraw.Draw(image)
    for index in range(4):  # glyph strokes inside the box only
        draw.rectangle((30 + index * 16, 30, 38 + index * 16, 50), fill="#eceae4")
    image.save(path)

    palette = control_palette(_page(path), [20, 20, 80, 40])

    assert palette["hasSurface"] is False
    assert palette["surface"] == "#181814"
    assert palette["ink"] == "#ece8e4"


def test_control_palette_reads_a_filled_button(tmp_path: Path) -> None:
    """A real button owns its fill, so the fill is the surface, not the text."""
    path = tmp_path / "button.png"
    image = Image.new("RGB", (200, 100), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 99, 59), fill="#4c64ec")
    for index in range(3):
        draw.rectangle((34 + index * 14, 34, 42 + index * 14, 46), fill="#ffffff")
    image.save(path)

    palette = control_palette(_page(path), [20, 20, 80, 40])

    assert palette["hasSurface"] is True
    assert palette["surface"] == "#4c64ec"
    assert palette["ink"] == "#fcfcfc"


def test_control_palette_keeps_a_chip_that_differs_from_the_page(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chip.png"
    image = Image.new("RGB", (200, 100), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 99, 59), fill="#e9ecf2")
    image.save(path)

    palette = control_palette(_page(path), [20, 20, 80, 40])

    assert palette["hasSurface"] is True
    assert palette["surface"] == "#e8ecf0"
