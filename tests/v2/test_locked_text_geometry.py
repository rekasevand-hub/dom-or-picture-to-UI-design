"""The three text-geometry repairs that run after the frames are locked.

They may only touch ``fontSize``: membership, boxes and paint order were already
approved by the time they run, so a change there is a bug even if the pixels look
better.  Each case below is one of the three defects that motivated the pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.structure.fidelity.fixed_canvas_compiler import (  # noqa: E402
    INLINE_SHRINK_FLOOR,
    _fit_locked_text_geometry,
)


def _text(ident: str, text: str, box, size: float) -> dict:
    x, y, width, height = box
    return {
        "id": ident,
        "type": "text",
        "text": text,
        "x": float(x),
        "y": float(y),
        "width": float(width),
        "height": float(height),
        "style": {"fontSize": size},
    }


def _frame(ident: str, box, children) -> dict:
    x, y, width, height = box
    return {
        "id": ident,
        "type": "container",
        "role": "card",
        "x": float(x),
        "y": float(y),
        "width": float(width),
        "height": float(height),
        "style": {"fillColor": "#ffffff"},
        "layoutChildren": [{"id": child} for child in children],
    }


def test_two_sizes_on_one_baseline_become_one() -> None:
    """`库存总量:1773` at 19.0 next to `可用库存:` at 22.25 is one sentence cut in two."""
    left = _text("a", "库存总量:1773", (100, 180, 156, 30), 19.0)
    right = _text("b", "可用库存:1689", (262, 180, 200, 30), 22.25)
    report = _fit_locked_text_geometry([left, right])

    assert report["unified"] >= 1
    assert left["style"]["fontSize"] == right["style"]["fontSize"]


def test_a_badge_next_to_a_heading_keeps_its_size() -> None:
    """The height ratio is what separates a fragment from a badge."""
    heading = _text("a", "模型广场", (100, 100, 400, 60), 40.0)
    badge = _text("b", "热", (508, 110, 36, 36), 20.0)
    _fit_locked_text_geometry([heading, badge])

    assert heading["style"]["fontSize"] == 40.0
    assert badge["style"]["fontSize"] == 20.0


def test_a_line_that_reaches_into_its_neighbour_shrinks() -> None:
    """wecom: `配置可信域名需完成域名归属认证` ran into `申请校验域名`."""
    long_line = _text("a", "配置可信域名需完成域名归属认证", (785, 935, 434, 42), 37.0)
    link = _text("b", "申请校验域名", (1237, 935, 176, 42), 38.0)
    report = _fit_locked_text_geometry([long_line, link])

    assert report["collisions"] == 1
    assert long_line["style"]["fontSize"] < 37.0
    assert long_line["style"]["fontSize"] >= 37.0 * INLINE_SHRINK_FLOOR
    assert link["style"]["fontSize"] == 38.0


def test_a_line_that_leaves_its_card_shrinks_into_it() -> None:
    """review: the first paragraph ran past the white card's right edge."""
    body = _text("a", "系统正在对当前内容进行安全审核。请保持页面开启。审核完成后，系统会更新", (244, 499, 846, 36), 34.0)
    card = _frame("card", (135, 159, 1076, 737), ["a"])
    report = _fit_locked_text_geometry([body, card])

    assert report["overflows"] == 1
    assert body["style"]["fontSize"] < 34.0
    assert body["style"]["fontSize"] >= 34.0 * INLINE_SHRINK_FLOOR


def test_a_chip_glyph_is_never_resized() -> None:
    """`G`, `★`, `库位` are sized by their chip, not by the room to their edge."""
    glyph = _text("a", "G", (10, 10, 12, 12), 12.25)
    chip = _frame("chip", (8, 8, 16, 16), ["a"])
    _fit_locked_text_geometry([glyph, chip])

    assert glyph["style"]["fontSize"] == 12.25


def test_the_pass_does_not_touch_structure() -> None:
    """Membership and boxes are the frame lock's business; this pass only resizes."""
    body = _text("a", "系统正在对当前内容进行安全审核。请保持页面开启。审核完成后，系统会更新", (244, 499, 846, 36), 34.0)
    card = _frame("card", (135, 159, 1076, 737), ["a"])
    before = (body["x"], body["y"], body["width"], body["height"], list(card["layoutChildren"]))
    _fit_locked_text_geometry([body, card])

    after = (body["x"], body["y"], body["width"], body["height"], list(card["layoutChildren"]))
    assert before == after
