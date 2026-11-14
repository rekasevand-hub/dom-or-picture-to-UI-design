"""The four presentation rules, on synthetic cases.

Each rule answers a defect measured on the seven benchmarks, and each test
states the smallest shape that shows it.  The screenshots themselves are not
needed: these passes are geometry and strings.
"""

from __future__ import annotations

from src.app.services.structure.fidelity.fixed_canvas_compiler import (
    _audit_filled_occluders,
    _drop_coincident_texts,
    _drop_icon_descriptor_labels,
    _separate_badge_icon_text,
)


def _text(index: int, x: int, y: int, width: int, height: int, text: str, **style) -> dict:
    return {
        "id": f"text:{index}",
        "contentRef": f"text:{index}",
        "type": "text",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "text": text,
        "style": {"fontSize": 14, "textColor": "#222222", **style},
    }


def _box(
    index: int,
    x: int,
    y: int,
    width: int,
    height: int,
    fill: str | None,
    **style,
) -> dict:
    payload = dict(style)
    if fill:
        payload["fillColor"] = fill
    return {
        "id": f"container:{index}",
        "type": "container",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "style": payload,
    }


def _icon(index: int, x: int, y: int, width: int, height: int) -> dict:
    return {
        "id": f"asset:{index}",
        "type": "image",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "imageBase64": "AA==",
    }


# -- icon captions ---------------------------------------------------------


def test_an_icon_caption_without_ocr_is_dropped() -> None:
    """`search` over a magnifier is the model naming the glyph."""
    elements = [_text(0, 40, 20, 46, 20, "search"), _text(1, 200, 20, 80, 20, "登录")]
    assert _drop_icon_descriptor_labels(elements, []) == 1
    assert [element.get("text") for element in elements] == ["登录"]


def test_a_real_english_label_survives_when_ocr_reads_it() -> None:
    """A page that prints "Search" keeps it; OCR is the proof."""
    elements = [_text(0, 40, 20, 60, 20, "Search")]
    ocr = [{"text": "Search", "bbox": [40, 20, 60, 20]}]
    assert _drop_icon_descriptor_labels(elements, ocr) == 0
    assert elements[0]["text"] == "Search"


def test_an_icon_caption_inside_a_word_is_left_alone() -> None:
    """"Mailbox settings" is prose, not a glyph name."""
    elements = [_text(0, 40, 20, 160, 20, "Mailbox settings")]
    assert _drop_icon_descriptor_labels(elements, []) == 0


def test_a_large_english_block_is_not_an_icon_caption() -> None:
    """A 600px-wide paragraph that happens to start with "search" stays."""
    elements = [_text(0, 40, 20, 600, 200, "search results for the term")]
    assert _drop_icon_descriptor_labels(elements, []) == 0


# -- same-line duplicates --------------------------------------------------


def test_a_narrow_copy_of_a_row_is_dropped() -> None:
    """The 48px box that prints the whole row over its own twin."""
    elements = [
        _text(0, 574, 313, 354, 33, "库位: W0505-005 包覆5线线边库位"),
        _text(1, 492, 314, 48, 30, "库位: W0505-005 包覆5线线边库位 库存总量:31"),
    ]
    assert _drop_coincident_texts(elements, "#ffffff") == 1
    assert len(elements) == 1
    assert "库存总量" in elements[0]["text"]


def test_a_quantity_cell_is_not_a_duplicate_of_the_row_prose() -> None:
    """"100" sits inside the row's words and still has to print."""
    elements = [
        _text(0, 2492, 1157, 27, 24, "100"),
        _text(1, 574, 1157, 1292, 32, "库位: W3101-01001 库存总量: 100 可用库存: 100米"),
    ]
    assert _drop_coincident_texts(elements, "#ffffff") == 0
    assert len(elements) == 2


def test_two_copies_that_differ_by_an_ocr_digit_still_collapse() -> None:
    """W0505 / WO505 is one label read twice."""
    elements = [
        _text(0, 574, 313, 354, 33, "库位: W0505-005 包覆5线线边库位"),
        _text(1, 492, 314, 300, 30, "库位: WO505-005 包覆5线线边库位"),
    ]
    assert _drop_coincident_texts(elements, "#ffffff") == 1


def test_two_different_labels_on_one_line_are_kept() -> None:
    elements = [
        _text(0, 100, 300, 120, 24, "共 1 条数据"),
        _text(1, 400, 302, 120, 24, "10条/页"),
    ]
    assert _drop_coincident_texts(elements, "#ffffff") == 0


def test_the_readable_copy_wins_over_the_invisible_one() -> None:
    """One reading sampled the card instead of the ink: #fefffe on white."""
    elements = [
        _text(0, 100, 300, 200, 24, "库位: W2101-01001 表皮库位001", textColor="#252525"),
        _text(1, 100, 300, 200, 24, "库位: W2101-01001 表皮库位001 库存总量:412", textColor="#fefffe"),
    ]
    assert _drop_coincident_texts(elements, "#ffffff") == 1
    assert elements[0]["style"]["textColor"] == "#252525"


# -- badge icon and text ---------------------------------------------------


def test_badge_text_starts_after_its_icon() -> None:
    elements = [
        _box(0, 100, 100, 200, 40, "#f2f3f5", borderRadius=20),
        _icon(1, 112, 112, 16, 16),
        _text(2, 116, 112, 140, 16, "大厂直供"),
    ]
    assert _separate_badge_icon_text(elements) == 1
    assert elements[2]["x"] == 112 + 16 + 4


def test_a_sidebar_row_is_not_a_badge() -> None:
    """Its icon cut already holds the first pixels of the label."""
    elements = [
        _box(0, 0, 100, 276, 480, "#364150"),
        _icon(1, 100, 112, 30, 24),
        _text(2, 106, 112, 96, 20, "出库管理"),
    ]
    assert _separate_badge_icon_text(elements) == 0
    assert elements[2]["x"] == 106


# -- filled occluder audit -------------------------------------------------


def test_a_filled_block_that_buries_text_goes_behind_it() -> None:
    """The table section painted after the rows it was supposed to sit under."""
    elements = [
        _text(0, 300, 560, 200, 20, "执行时间"),
        _box(1, 160, 544, 1744, 264, "#fefefe"),
    ]
    # What batching does to it: a lifted tier puts the strip after the rows.
    elements[1]["zIndex"] = 2
    assert _audit_filled_occluders(elements, "#ffffff") == 1
    assert int(elements[1].get("zIndex") or 0) < 0


def test_a_progress_bar_keeps_its_fill() -> None:
    """A solid rounded bar is content, not a panel that hides something."""
    elements = [
        _text(0, 240, 826, 84, 26, "处理进度"),
        _box(1, 240, 860, 620, 8, "#1e6fff", borderRadius=4),
    ]
    assert _audit_filled_occluders(elements, "#fefefe") == 0
    assert elements[1]["style"]["fillColor"] == "#1e6fff"


def test_a_backdrop_fragment_is_repainted_in_the_panel_colour() -> None:
    """A dimmed-page patch measured over a white dialog hides the dialog."""
    elements = [
        _box(0, 660, 76, 1900, 1198, "#ffffff"),
        _box(1, 1895, 319, 578, 545, "#666666"),
    ]
    assert _audit_filled_occluders(elements, "#666666") == 1
    assert elements[1]["style"]["fillColor"] == "#ffffff"
