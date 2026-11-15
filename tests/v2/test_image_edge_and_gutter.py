"""Reading a card's own edge, and the page gap between two columns.

Both rules are about the picture contradicting the plan's boxes, and both were
wrong in the same way at first: the sample landed *on* the thing it was looking
for.  ``_outside_color`` read y-2..y-4, which for a card measured inside its own
1px stroke is the stroke → the border probe rejected it as background, and every
dark card came out with no edge.  And a "gutter" read as a whole empty column
catches the page above the cards, not the gap between them.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.app.services.structure.fidelity.pixel_probe import (
    detect_border,
    estimate_corner_radius,
    sample_container_decoration,
    separated_by_page,
)


def _card_page(tmp_path, *, page=(16, 15, 13), fill=(26, 25, 23), border=(44, 43, 39)):
    """A dark card with a 1px stroke, three pixels outside its measured box."""
    import cv2

    image = np.zeros((240, 320, 3), dtype=np.uint8)
    image[:, :] = page
    cv2.rectangle(image, (48, 60), (272, 200), border, -1)
    cv2.rectangle(image, (49, 61), (271, 199), fill, -1)
    path = tmp_path / "card.png"
    cv2.imwrite(str(path), image[:, :, ::-1])
    return str(path), image[:, :, ::-1].astype(np.int16)


def test_the_outside_sample_misses_a_one_pixel_border(tmp_path) -> None:
    from src.app.services.structure.fidelity.pixel_probe import _outside_color, load_rgb

    path, pixels = _card_page(tmp_path)
    # The plan measured the inside of the stroke: box starts at (49, 61).
    outside = _outside_color(load_rgb(path), (49, 61, 222, 138))

    assert outside is not None
    assert max(abs(a - b) for a, b in zip(outside, (16, 15, 13))) <= 4


def test_a_border_two_pixels_outside_the_box_is_found(tmp_path) -> None:
    from src.app.services.structure.fidelity.pixel_probe import load_rgb

    path, _pixels = _card_page(tmp_path)
    border = detect_border(load_rgb(path), (49, 61, 222, 138), "#1a1917")

    assert border is not None
    assert border["width"] == 1
    red = int(border["color"][1:3], 16)
    assert abs(red - 44) <= 4


def test_a_card_ten_channels_off_its_page_still_gets_a_radius(tmp_path) -> None:
    """The fixed tolerance called this card background; half the gap does not."""
    import cv2

    page = np.full((240, 320, 3), 255, dtype=np.uint8)
    page[:, :] = (16, 15, 13)
    # A 20px radius, drawn as a mask so the corner is genuinely rounded — and
    # *only* as a mask: painting a square first would fill the corners back in.
    mask = np.zeros((240, 320), dtype=np.uint8)
    cv2.rectangle(mask, (60, 80), (260, 200), 255, -1)
    cv2.rectangle(mask, (80, 60), (240, 200), 255, -1)
    cv2.circle(mask, (80, 80), 20, 255, -1)
    cv2.circle(mask, (240, 80), 20, 255, -1)
    page[mask > 0] = (26, 25, 23)
    path = tmp_path / "rounded.png"
    cv2.imwrite(str(path), page[:, :, ::-1])

    from src.app.services.structure.fidelity.pixel_probe import load_rgb

    radius = estimate_corner_radius(load_rgb(path), (60, 60, 200, 140), fill="#1a1917")
    assert radius >= 12


def test_decoration_reports_both_radius_and_border(tmp_path) -> None:
    path, _pixels = _card_page(tmp_path)
    decoration = sample_container_decoration(path, (49, 61, 222, 138), "#1a1917")

    assert decoration.get("borderRadius", 0) >= 0
    assert decoration.get("borderColor")


# --- 列间 Gutter ------------------------------------------------------------


def _two_columns(tmp_path, *, gap=(150, 200), page=(255, 255, 255), card=(250, 250, 250)):
    import cv2

    image = np.zeros((200, 400, 3), dtype=np.uint8)
    image[:, :] = page
    cv2.rectangle(image, (20, 40), (gap[0], 160), card, -1)
    cv2.rectangle(image, (gap[1], 40), (380, 160), card, -1)
    path = tmp_path / "columns.png"
    cv2.imwrite(str(path), image[:, :, ::-1])
    return str(path), image[:, :, ::-1].astype(np.int16)


def test_a_page_column_between_two_boxes_separates_them(tmp_path) -> None:
    path, pixels = _two_columns(tmp_path)
    assert separated_by_page(pixels, "#ffffff", (20, 40, 130, 120), (200, 40, 180, 120))


def test_cards_one_pixel_apart_are_not_separated(tmp_path) -> None:
    path, pixels = _two_columns(tmp_path, gap=(150, 151))
    assert not separated_by_page(pixels, "#ffffff", (20, 40, 130, 120), (151, 40, 229, 120))


def test_distant_boxes_are_not_gutter_tested(tmp_path) -> None:
    """No shared rows means no strip to read: the caller decides, not this."""
    _path, pixels = _two_columns(tmp_path)
    assert not separated_by_page(pixels, "#ffffff", (20, 40, 130, 20), (200, 180, 180, 20))


def test_the_paragraph_chain_refuses_to_cross_a_page_strip() -> None:
    from src.app.services.structure.fidelity.fixed_canvas_compiler import _reflow_chain

    seed = {"text": "从 Meta 设计系统出发，把组件规范搭成可检索", "key": "从meta设计系统出发把组件规范搭成可检索", "box": (100, 100, 300, 30)}
    # Same row band, different column: the words continue the sentence by
    # accident, the picture says they are a separate block.
    other = {"text": "起 ¥23.00", "key": "起¥23.00", "box": (520, 104, 120, 26)}
    node_key = "从meta设计系统出发把组件规范搭成可检索起¥23.00"

    crossed = _reflow_chain([seed, other], seed, seed["box"], node_key)
    assert [item["key"] for item in crossed] == [seed["key"]]

    blocked = _reflow_chain(
        [seed, other], seed, seed["box"], node_key, separated=lambda a, b: True
    )
    assert [item["key"] for item in blocked] == [seed["key"]]
