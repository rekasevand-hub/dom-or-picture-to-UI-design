"""Paint order has to use the glyph box, not the layout box.

The holdout's `< 1 分钟` is 438 px wide inside a 270 px card: the element box is
a whole cell, so the card counts as *deeper* than the text and paints over it.
The node stays in the document and the glyphs vanish from the export -- the
gate reports `failed-missing-rendered-ink` while the readback looks perfect.

These cases pin the repair: only a text whose *reference ink* is fully covered
by an opaque element that paints later moves, and it moves to just above that
element. Everything else keeps its relative order.
"""

from __future__ import annotations

from src.app.services.rendering.adapter_base import paint_order


def _text(text, x, y, w, h, ink=None) -> dict:
    element = {
        "id": f"text:{text}",
        "type": "text",
        "text": text,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "style": {"fontSize": 20},
    }
    if ink is not None:
        element["styleEvidence"] = {"evidence": {"ink_bbox": list(ink)}}
    return element


def _rect(idx, x, y, w, h, fill="#ffffff", kind="rectangle") -> dict:
    return {
        "id": f"{kind}:{idx}",
        "type": kind,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "style": {"fillColor": fill},
    }


def _page() -> dict:
    return _rect(0, 0, 0, 1200, 800, "#eef2fa", kind="container")


def _panel() -> dict:
    """The page-wide panel: it holds the card but not the wide text box."""
    return _rect(9, 134, 156, 1082, 845)


def _card() -> dict:
    return _rect(1, 829, 647, 270, 114)


def _ids(ordered):
    return [element["id"] for _index, element in ordered]


def test_a_wide_text_box_lifts_above_the_card_it_sticks_out_of():
    # Depth: card is inside panel, panel inside page -> 2. The text box is
    # 438 px wide and reaches past the panel, so it only counts the page -> 1,
    # and the card lands on top of it. The glyphs, though, are inside the card.
    text = _text("< 1 分钟", 854, 706, 438, 32, ink=(858, 713, 82, 21))

    ordered = paint_order([_page(), _card(), text, _panel()])

    assert _ids(ordered) == [
        "container:0",
        "rectangle:9",
        "rectangle:1",
        "text:< 1 分钟",
    ]


def test_a_text_whose_box_fits_its_card_stays_where_it_was():
    # Same card, but the box is the glyph box: depth 3, so it already paints
    # last and nothing has to move.
    text = _text("< 1 分钟", 858, 713, 82, 32, ink=(858, 713, 82, 21))

    ordered = paint_order([_page(), _card(), text, _panel()])

    assert _ids(ordered)[-1] == "text:< 1 分钟"
    assert _ids(ordered) == [
        "container:0",
        "rectangle:9",
        "rectangle:1",
        "text:< 1 分钟",
    ]


def test_without_ink_evidence_the_order_is_unchanged():
    # No ink box means no pixel truth: do not guess from the layout box.
    text = _text("< 1 分钟", 854, 706, 438, 32)

    ordered = paint_order([_page(), _card(), text, _panel()])

    assert _ids(ordered) == [
        "container:0",
        "text:< 1 分钟",
        "rectangle:9",
        "rectangle:1",
    ]


def test_a_transparent_fill_cannot_hide_glyphs():
    text = _text("< 1 分钟", 854, 706, 438, 32, ink=(858, 713, 82, 21))
    card = _rect(1, 829, 647, 270, 114, "transparent")

    ordered = paint_order([_page(), card, text, _panel()])

    assert _ids(ordered)[-1] == "rectangle:1"


def test_a_partial_overlap_is_not_a_burial():
    text = _text("< 1 分钟", 854, 706, 438, 32, ink=(858, 713, 82, 21))
    # Covers the left third of the glyph run only.
    card = _rect(1, 829, 647, 60, 114)

    ordered = paint_order([_page(), card, text, _panel()])

    assert _ids(ordered)[-1] == "rectangle:1"


def test_the_repair_does_not_run_twice():
    text = _text("< 1 分钟", 854, 706, 438, 32, ink=(858, 713, 82, 21))
    elements = [_page(), _card(), text, _panel()]

    assert _ids(paint_order(elements)) == _ids(paint_order(elements))


def test_untouched_elements_keep_their_relative_order():
    page = _page()
    title = _text("标题", 100, 100, 120, 24, ink=(100, 100, 120, 24))
    buried = _text("< 1 分钟", 854, 706, 438, 32, ink=(858, 713, 82, 21))
    footer = _text("页脚", 900, 900, 120, 24, ink=(900, 900, 120, 24))

    ordered = _ids(paint_order([page, title, _card(), buried, footer, _panel()]))

    assert ordered.index("text:标题") < ordered.index("text:页脚")
    assert ordered.index("text:< 1 分钟") > ordered.index("rectangle:1")
