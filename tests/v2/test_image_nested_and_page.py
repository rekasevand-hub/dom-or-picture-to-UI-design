"""The rules that stop a page from printing the same thing twice, or the wrong thing.

Three of them, all deterministic and all measured against the picture:

* `_drop_nested_texts` — a text node that prints where a bigger text node already
  prints, and that the picture's own OCR does not support at that box;
* `_restore_display_weight` — the page's biggest line is display type, and display
  type is not judged by average stroke width (a Song hero averages 0.086em and
  came out Regular);
* `_recover_page_fill` — when the four margins are two different surfaces, vote
  instead of averaging: marketplace's #1a1917 / #100f0d averaged to #151412, which
  happened to match the declared background and silently disabled the whole pass.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.app.services.structure.fidelity.fixed_canvas_compiler import (
    _drop_nested_texts,
    _recover_page_fill,
    _restore_display_weight,
)


def _text(element_id: str, text: str, x: int, y: int, w: int, h: int, size: float = 24.0):
    return {
        "id": element_id,
        "type": "text",
        "x": float(x),
        "y": float(y),
        "width": float(w),
        "height": float(h),
        "text": text,
        "style": {"fontSize": size, "textColor": "#111111"},
    }


def _ocr(text: str, x: int, y: int, w: int, h: int):
    return {"text": text, "bbox": [x, y, w, h], "confidence": 0.9}


# --- 文本套文本 -------------------------------------------------------------


def test_a_price_printed_inside_a_title_is_dropped() -> None:
    """marketplace: "¥4.64" mapped onto the band of "DeepSeek V4.1 Flash"."""
    elements = [
        _text("title", "DeepSeek V4.1 Flash", 209, 638, 415, 57, 39),
        _text("price", "¥4.64", 270, 652, 106, 36, 34),
    ]
    ocr = [_ocr("DeepSeek V4.1 Flash", 209, 638, 415, 57)]

    dropped = _drop_nested_texts(elements, ocr)

    assert dropped == 1
    assert [element["text"] for element in elements] == ["DeepSeek V4.1 Flash"]


def test_a_price_on_the_next_line_is_left_alone() -> None:
    """A value one line lower keeps its own vertical band: not a duplicate."""
    elements = [
        _text("title", "DeepSeek V4.1 Flash", 209, 638, 415, 57, 39),
        _text("price", "¥4.64", 270, 700, 106, 36, 34),
    ]
    ocr = [_ocr("DeepSeek V4.1 Flash", 209, 638, 415, 57)]

    assert _drop_nested_texts(elements, ocr) == 0
    assert len(elements) == 2


def test_words_the_picture_supports_survive() -> None:
    """inventory's table: "冻结库存" sits inside a wide value box, and OCR has it."""
    elements = [
        _text("value", "0", 1553, 1107, 210, 26, 18),
        _text("label", "冻结库存", 1548, 1106, 96, 30, 28),
    ]
    ocr = [_ocr("冻结库存", 1548, 1106, 96, 30)]

    assert _drop_nested_texts(elements, ocr) == 0


def test_one_wrong_glyph_does_not_unsupport_a_line() -> None:
    """OCR reads "输入 · 峰时" as "输入 .峰时"; the node is still the picture's."""
    elements = [
        _text("title", "输入 · 峰时", 147, 866, 200, 40, 26),
        _text("tail", "峰时", 240, 868, 60, 36, 26),
    ]
    ocr = [_ocr("输入 .峰时", 147, 866, 200, 40)]

    assert _drop_nested_texts(elements, ocr) == 0
    assert len(elements) == 2


def test_a_word_on_a_chip_sized_picture_is_dropped() -> None:
    """"¥2.00" sat on the 大厂直供 chip's own bitmap, with no OCR to back it."""
    elements = [
        _text("price", "¥2.00", 124, 664, 142, 24, 15),
        {
            "id": "chip",
            "type": "image",
            "x": 142.0,
            "y": 641.0,
            "width": 102.0,
            "height": 43.0,
            "style": {},
            "imageBase64": "AAAA",
        },
    ]
    assert _drop_nested_texts(elements, []) == 1
    assert [element["id"] for element in elements] == ["chip"]


def test_a_word_over_a_large_photo_is_kept() -> None:
    """Words over a full-bleed picture are normal; only chip-sized pictures count."""
    elements = [
        _text("caption", "秋日限定", 124, 664, 142, 24, 15),
        {
            "id": "photo",
            "type": "image",
            "x": 0.0,
            "y": 0.0,
            "width": 1200.0,
            "height": 800.0,
            "style": {},
            "imageBase64": "AAAA",
        },
    ]
    assert _drop_nested_texts(elements, []) == 0


# --- 展示标题的字重 ---------------------------------------------------------


def _hero_page(tmp_path, thickness: int) -> str:
    import cv2

    page = np.full((160, 420, 3), 26, dtype=np.uint8)
    # Four thick verticals and thin horizontals: the Song contrast that makes the
    # average stroke width lie about the weight.
    for index in range(4):
        x = 20 + index * 100
        cv2.rectangle(page, (x, 40), (x + thickness, 120), (240, 238, 232), -1)
        cv2.rectangle(page, (x, 76), (x + 80, 76 + max(2, thickness // 5)), (240, 238, 232), -1)
    path = tmp_path / f"hero{thickness}.png"
    cv2.imwrite(str(path), page[:, :, ::-1])
    return str(path)


def test_the_biggest_line_is_set_at_display_weight(tmp_path) -> None:
    elements = [_text("hero", "模型广场", 20, 40, 395, 100, 96)]
    changed = _restore_display_weight(elements, _hero_page(tmp_path, 12), 420, 160)

    assert changed == 1
    assert elements[0]["style"]["fontWeightValue"] == 800
    assert elements[0]["style"]["fontWeight"] == "bold"
    assert elements[0]["weightEvidence"]["method"] == "display-role"


def test_a_hairline_hero_is_not_bolded(tmp_path) -> None:
    """A thin display face is a design decision, and the rule has to respect it."""
    elements = [_text("hero", "模型广场", 20, 40, 395, 100, 96)]
    changed = _restore_display_weight(elements, _hero_page(tmp_path, 4), 420, 160)

    assert changed == 0
    assert elements[0]["style"].get("fontWeightValue") is None


def test_only_the_biggest_line_changes(tmp_path) -> None:
    elements = [
        _text("hero", "模型广场", 20, 40, 395, 100, 96),
        _text("body", "每百万 tokens", 20, 130, 200, 24, 24),
    ]
    _restore_display_weight(elements, _hero_page(tmp_path, 12), 420, 160)

    assert elements[0]["style"]["fontWeightValue"] == 800
    assert elements[1]["style"].get("fontWeightValue") is None


# --- 页底色：打平时看谁离声明更远 -------------------------------------------


def _page_with_edges(tmp_path, sides, top, bottom) -> str:
    import cv2

    page = np.full((120, 400, 3), 255, dtype=np.uint8)
    page[:, 0:6] = sides
    page[:, -6:] = sides
    page[0:4] = top
    page[-4:] = bottom
    path = tmp_path / "page.png"
    cv2.imwrite(str(path), page[:, :, ::-1])
    return str(path)


def test_two_different_margins_vote_instead_of_averaging(tmp_path) -> None:
    """marketplace: #1a1917 top and bottom, #100f0d down both sides."""
    path = _page_with_edges(tmp_path, (16, 15, 13), (26, 25, 23), (26, 25, 23))
    elements: list[dict] = []

    painted = _recover_page_fill(elements, path, 400, 120, "#1a1917")

    assert painted is True
    assert [element["style"]["fillColor"] for element in elements] == ["#100f0d"]
    assert elements[0]["role"] == "page-ground"


def test_a_page_that_already_matches_is_left_alone(tmp_path) -> None:
    path = _page_with_edges(tmp_path, (255, 255, 255), (255, 255, 255), (255, 255, 255))
    elements: list[dict] = []

    assert _recover_page_fill(elements, path, 400, 120, "#ffffff") is False
    assert elements == []
