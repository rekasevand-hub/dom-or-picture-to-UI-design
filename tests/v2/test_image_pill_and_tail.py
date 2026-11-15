"""Two recoveries that only pay off when they say *no* often enough.

The capsule pass has to tell a rounded chip from a square block and from a line
of words; the tail pass has to tell a paragraph's wrapped remainder from a
standalone label that happens to repeat its last words.  Both are tested on
painted shapes, so the expected answer is arithmetic, not a screenshot.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.app.services.structure.fidelity.fixed_canvas_compiler import (
    _drop_paragraph_tails,
    _recover_pill_shapes,
)


def _capsule_page(tmp_path, *, rounded: bool = True, with_words: bool = False) -> str:
    import cv2

    page = np.full((200, 400, 3), 255, dtype=np.uint8)
    if rounded:
        # A real capsule: a straight middle and two half-round ends.
        cv2.rectangle(page, (60, 40), (140, 80), (239, 239, 239), -1)
        cv2.circle(page, (60, 60), 20, (239, 239, 239), -1)
        cv2.circle(page, (140, 60), 20, (239, 239, 239), -1)
    else:
        cv2.rectangle(page, (40, 40), (160, 80), (239, 239, 239), -1)
    if with_words:
        # Dark strokes inside the chip: still a chip, not a line of text on white.
        for x in range(52, 150, 12):
            cv2.rectangle(page, (x, 54), (x + 6, 66), (60, 60, 60), -1)
    path = tmp_path / "page.png"
    cv2.imwrite(str(path), page[:, :, ::-1])
    return str(path)


def test_a_rounded_chip_becomes_a_vector_pill(tmp_path) -> None:
    path = _capsule_page(tmp_path)
    elements: list[dict] = []

    added = _recover_pill_shapes(elements, path, 400, 200, "#ffffff")

    assert added == 1
    pill = elements[0]
    assert pill["role"] == "panel"
    assert pill["style"]["fillColor"].lower() == "#efefef"
    assert pill["style"]["borderRadius"] >= 8
    assert abs(pill["x"] - 40) <= 2 and abs(pill["y"] - 40) <= 2
    assert 118 <= pill["width"] <= 122 and 39 <= pill["height"] <= 42


def test_a_square_block_is_left_to_the_solid_pass(tmp_path) -> None:
    path = _capsule_page(tmp_path, rounded=False)
    elements: list[dict] = []

    assert _recover_pill_shapes(elements, path, 400, 200, "#ffffff") == 0
    assert elements == []


def test_a_chip_that_carries_words_is_still_a_chip(tmp_path) -> None:
    path = _capsule_page(tmp_path, with_words=True)
    elements: list[dict] = []

    assert _recover_pill_shapes(elements, path, 400, 200, "#ffffff") == 1
    assert elements[0]["id"].startswith("pill:")


def _text(x: int, y: int, width: int, height: int, text: str) -> dict:
    return {
        "id": f"text:{abs(hash(text)) % 10000}",
        "type": "text",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "text": text,
        "style": {"fontSize": 20, "textAlign": "left"},
    }


def test_a_wrapped_remainder_below_its_paragraph_is_dropped() -> None:
    paragraph = "从 Meta 内部走出来的开源设计系统，让产品团队和 AI 助手按同一套规范搭界面"
    tail = "让产品团队和 Al 助手按同一套规范搭界面"  # OCR read the capital I as l
    elements = [
        _text(1154, 343, 662, 31, paragraph),
        _text(1157, 377, 394, 30, tail),
    ]

    dropped = _drop_paragraph_tails(elements)

    assert dropped == 1
    assert [element["text"] for element in elements] == [paragraph]


def test_a_label_that_only_shares_the_words_is_kept() -> None:
    elements = [
        _text(100, 100, 600, 30, "这是一段很长的说明文字，结尾是查看详情"),
        _text(600, 160, 80, 24, "查看详情"),
    ]

    assert _drop_paragraph_tails(elements) == 0
    assert len(elements) == 2


def test_a_fragment_that_sits_above_its_paragraph_is_kept() -> None:
    paragraph = "这是一段很长的说明文字，结尾是查看详情"
    elements = [
        _text(100, 160, 600, 30, paragraph),
        _text(100, 100, 300, 24, "结尾是查看详情"),
    ]

    assert _drop_paragraph_tails(elements) == 0
    assert len(elements) == 2


def test_a_short_repeat_is_below_the_minimum_length() -> None:
    paragraph = "这是一段很长的说明文字，结尾是搭界面"
    elements = [
        _text(100, 100, 600, 30, paragraph),
        _text(100, 140, 120, 24, "搭界面"),
    ]

    assert _drop_paragraph_tails(elements) == 0
