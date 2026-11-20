"""When two same-span blocks are one layer, and when they are two siblings.

The rule this replaces was "skip anything over 40% of the canvas".  It is a
statement about the *result*, not about the page, so it was wrong in both
directions — and the two directions are indistinguishable from the outside,
because all the merge does is happen or not happen.  So each case here is a
picture whose answer is known by construction.

What decides is the gap: whether the surface in it stops at the blocks' own
edge.  A highlighted row inside a rail stops there (child, merge); the page's
grey showing between a search bar and the content does not (gutter, keep apart).
"""

from __future__ import annotations

import numpy as np

from src.app.services.structure.physical_perception import (
    _gutter_is_through,
    page_regions,
)

WHITE = (255, 255, 255)
GREY = (240, 240, 240)


def _page(size=(400, 400), colour=WHITE) -> np.ndarray:
    page = np.zeros((size[0], size[1], 3), dtype=np.int16)
    page[:] = colour
    return page


def _fill(page, x0, y0, x1, y1, colour):
    page[y0:y1, x0:x1] = colour
    return page


def _spans(boxes):
    return [tuple(int(value) for value in box) for box in boxes]


def test_a_pair_separated_by_the_page_surface_is_not_merged() -> None:
    """Search bar above content: 16px of the page's own grey between them."""
    page = _page(colour=GREY)
    _fill(page, 40, 40, 360, 180, WHITE)
    _fill(page, 40, 196, 360, 360, WHITE)

    regions = page_regions(page, WHITE, [], 400, 400)
    boxes = _spans(item["bbox"] for item in regions)
    assert (40, 40, 320, 140) in boxes
    assert (40, 196, 320, 164) in boxes
    assert not any(box[3] == 320 for box in boxes)


def test_a_pair_split_by_a_child_row_is_merged() -> None:
    """A highlighted menu row inside a rail: the row is the child, the rail is one layer."""
    page = _page(colour=GREY)
    _fill(page, 40, 40, 200, 180, WHITE)
    _fill(page, 40, 180, 200, 196, (232, 240, 255))  # 高亮行，宽度与轨道一致
    _fill(page, 40, 196, 200, 360, WHITE)

    regions = page_regions(page, WHITE, [], 400, 400)
    rail = [item for item in regions if item["bbox"][0] == 40 and item["bbox"][2] == 160]
    assert rail, _spans(item["bbox"] for item in regions)
    assert max(item["bbox"][3] for item in rail) == 320


def test_the_decision_does_not_depend_on_how_big_the_result_is() -> None:
    """Same picture, two sizes. The old rule merged the small one and blocked the large one."""
    for extent in (60, 260):
        top = 40
        height = top * 2 + extent * 2 + 16
        page = _page(size=(height, 400), colour=GREY)
        _fill(page, 40, top, 360, top + extent, WHITE)
        _fill(page, 40, top + extent, 360, top + extent + 16, (232, 240, 255))
        _fill(page, 40, top + extent + 16, 360, top + extent * 2 + 16, WHITE)

        regions = page_regions(page, WHITE, [], 400, height)
        merged = [
            item
            for item in regions
            if item["bbox"][0] == 40 and item["bbox"][2] == 320 and item["bbox"][3] > extent
        ]
        shares = [item["bbox"][2] * item["bbox"][3] / (height * 400) for item in merged]
        assert merged, f"extent={extent}: {_spans(item['bbox'] for item in regions)}"
        if extent == 260:
            # 大的那种合并结果超过画布 40%——正是旧硬阈值会误杀的那一类。
            assert shares and shares[0] > 0.4


def test_a_local_child_is_not_mistaken_for_a_page_band() -> None:
    """Same predicate, the other answer: the band stops where the blocks stop."""
    height, width = 120, 400
    image = np.full((height, width, 3), 255, dtype=np.int16)
    barrier = np.zeros((height, width), dtype=bool)
    image[50:64, 40:360] = (232, 240, 255)
    barrier[50:64, 40:360] = True
    first, second = (40, 20, 320, 30), (40, 64, 320, 30)
    assert not _gutter_is_through(image, first, second, "vertical")
