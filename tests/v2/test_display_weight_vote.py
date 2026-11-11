"""Gold-box sampling for the weight vote.

The one thing that has to be right before any of this means anything is where a
gold text node actually sits on the page: ``x``/``y`` in the export are
**parent relative**, and reading them directly puts every row of a list on the
same coordinates (``模型广场`` was measured in the top-left corner of the page,
because that is where its parent's origin is).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from p1_display_weight_vote import _is_rotated, _text_nodes  # noqa: E402


def _tree() -> dict:
    return {
        "type": "FRAME",
        "x": 0,
        "y": 0,
        "children": [
            {
                "type": "FRAME",
                "x": 100,
                "y": 50,
                "children": [
                    {"type": "TEXT", "x": 10, "y": 5, "width": 20, "height": 10},
                    {"type": "TEXT", "x": 40, "y": 5, "width": 20, "height": 10},
                ],
            }
        ],
    }


def test_page_position_sums_the_parent_offsets() -> None:
    found = _text_nodes(_tree(), 1.0)

    assert [(round(x), round(y)) for _node, x, y in found] == [(110, 55), (140, 55)]


def test_page_position_is_scaled() -> None:
    found = _text_nodes(_tree(), 2.0)

    assert [(round(x), round(y)) for _node, x, y in found] == [(220, 110), (280, 110)]


def test_nested_frames_accumulate_but_the_root_offset_is_dropped() -> None:
    # The root *is* the gold frame: its x/y is where that frame sits on the
    # Figma canvas (26 000-odd), so it has to be zeroed or every sample lands
    # off-page.  Frames below it are ordinary parents and do accumulate.
    nested = {
        "type": "FRAME",
        "x": 5,
        "y": 7,
        "children": [
            {"type": "FRAME", "x": 10, "y": 20, "children": [_text(1, 1)]},
        ],
    }

    found = _text_nodes(nested, 1.0)

    assert [(round(x), round(y)) for _node, x, y in found] == [(11, 21)]


def _text(x: float, y: float) -> dict:
    return {"type": "TEXT", "x": x, "y": y, "width": 10, "height": 10}


def test_rotation_is_detected_from_the_axis_aligned_box() -> None:
    straight = {
        "type": "TEXT",
        "width": 95,
        "height": 70,
        "absolute": {"width": 95, "height": 70},
    }
    tilted = {
        "type": "TEXT",
        "width": 95,
        "height": 70,
        "absolute": {"width": 101.8, "height": 79.5},
    }

    assert _is_rotated(straight) is False
    assert _is_rotated(tilted) is True
    assert _is_rotated({"type": "TEXT"}) is False
