"""Post-frame alignment: it may slide text sideways, and nothing else.

Framing already happened when this runs, so the danger is not "does it find the
column" but "does it quietly change something the frame count depends on".  The
tests therefore spend most of their budget on refusals: no vertical move, no
resize, no member leaving its frame, no move past the tolerance.
"""

from __future__ import annotations

import pytest

from src.app.services.structure.fidelity import post_frame_align as pfa


@pytest.fixture(autouse=True)
def _pass_enabled(monkeypatch):
    """These tests describe what the pass does when it is on.

    Whether it ships on is a measurement decision (it is currently off — see the
    constant's comment), so the tests turn it on rather than inheriting a
    default that is allowed to change for reasons unrelated to this behaviour.
    """
    monkeypatch.setattr(pfa, "POST_FRAME_ALIGN_ENABLED", True)
    monkeypatch.setattr(pfa, "POST_FRAME_Y_ENABLED", True)
    monkeypatch.setattr(pfa, "POST_FRAME_INK_ENABLED", True)


def text(x: float, y: float, width: float = 80, height: float = 18, ident: str = "") -> dict:
    return {"id": ident or f"t{x}-{y}", "type": "text", "x": float(x), "y": float(y),
            "width": float(width), "height": float(height), "text": "x"}


def frame(members: list[dict], *, x=0, y=0, width=600, height=300) -> dict:
    return {
        "id": "frame",
        "type": "container",
        "x": float(x),
        "y": float(y),
        "width": float(width),
        "height": float(height),
        "layoutChildren": [{"id": member["id"]} for member in members],
    }


def run(elements: list[dict]) -> dict:
    return pfa.align_frame_columns(elements)


def test_a_row_of_three_texts_snaps_to_the_shared_left_edge() -> None:
    a, b, c = text(100, 10), text(100, 50), text(103, 90)
    elements = [frame([a, b, c]), a, b, c]
    stats = run(elements)
    assert [e["x"] for e in (a, b, c)] == [100, 100, 100]
    assert stats["moved"] == 1


def test_two_texts_are_not_a_column() -> None:
    a, b = text(100, 10), text(104, 50)
    elements = [frame([a, b]), a, b]
    assert run(elements)["moved"] == 0
    assert b["x"] == 104


def test_right_aligned_dates_pin_their_right_edge_not_their_left() -> None:
    # 右缘齐、左缘随字数走：日期列。钉左缘会把整列推歪。
    a = text(500, 10, width=90)
    b = text(510, 50, width=80)
    c = text(505, 90, width=85)
    elements = [frame([a, b, c]), a, b, c]
    run(elements)
    for element in (a, b, c):
        assert element["x"] + element["width"] == 590


def test_alignment_never_touches_the_vertical_axis() -> None:
    a, b, c = text(100, 10), text(100, 50), text(103, 90)
    elements = [frame([a, b, c]), a, b, c]
    run(elements)
    assert [element["y"] for element in (a, b, c)] == [10, 50, 90]


def test_alignment_never_resizes() -> None:
    a, b, c = text(100, 10, 70), text(100, 50, 90), text(104, 90, 60)
    elements = [frame([a, b, c]), a, b, c]
    run(elements)
    assert [element["width"] for element in (a, b, c)] == [70, 90, 60]


def test_a_text_that_would_leave_its_frame_stays_put() -> None:
    # 帧右缘 600，这个字 596+80 已经在外沿；任何右移都会越界，必须拒绝。
    a, b, c = text(100, 10), text(100, 50), text(100, 90)
    near_edge = text(596, 130, width=80)
    elements = [frame([a, b, c, near_edge]), a, b, c, near_edge]
    run(elements)
    assert near_edge["x"] == 596


def test_a_gap_beyond_tolerance_is_an_indent_not_a_misalignment() -> None:
    a, b, c = text(100, 10), text(100, 50), text(112, 90)
    elements = [frame([a, b, c]), a, b, c]
    run(elements)
    assert c["x"] == 112


def test_columns_are_found_across_rows_not_inside_one() -> None:
    # 真实形态：一行一帧，帧内几个字本来就不同列。列只跨行存在。
    rows = []
    elements: list[dict] = []
    for row_index, top in enumerate((10, 60, 110, 160)):
        avatar = text(50, top, 32, 32, ident=f"a{row_index}")
        subject = text(104 if row_index == 2 else 100, top, 200, 18, ident=f"s{row_index}")
        elements.extend([avatar, subject])
        rows.append(frame([avatar, subject], x=0, y=top - 5, width=600, height=40))
    elements = rows + elements
    run(elements)
    # 第 3 行主题行漂了 4px，被拉回共同的 100。这里治的是感知毛刺，
    # 不是"缺了图标导致整行错位"——那种差距远超 5px，不归这一层管。
    assert [element["x"] for element in elements[4:] if element.get("id", "").startswith("s")] == [
        100, 100, 100, 100
    ]


def test_two_margins_stay_separate() -> None:
    # 侧栏与主区各有自己的左边距：两条标尺互不干扰。
    side = [text(50, 10), text(50, 50), text(52, 90)]
    main = [text(400, 10), text(400, 50), text(403, 90)]
    elements = (
        [frame(side, x=0, width=300), frame(main, x=350, width=300)]
        + side
        + main
    )
    elements[1]["id"] = "frame-right"
    run(elements)
    assert [element["x"] for element in side] == [50, 50, 50]
    assert [element["x"] for element in main] == [400, 400, 400]


def test_elements_outside_frames_are_left_alone() -> None:
    loner = text(500, 10)
    elements = [frame([]), loner]
    run(elements)
    assert loner["x"] == 500


def test_a_disabled_switcher_makes_the_pass_a_no_op() -> None:
    a, b, c = text(100, 10), text(100, 50), text(103, 90)
    elements = [frame([a, b, c]), a, b, c]
    original = pfa.POST_FRAME_ALIGN_ENABLED
    pfa.POST_FRAME_ALIGN_ENABLED = False
    try:
        assert run(elements)["moved"] == 0
    finally:
        pfa.POST_FRAME_ALIGN_ENABLED = original
    assert c["x"] == 103


def test_the_result_is_deterministic() -> None:
    def build() -> list[dict]:
        a, b, c = text(100, 10), text(100, 50), text(103, 90)
        return [frame([a, b, c]), a, b, c]

    first, second = build(), build()
    run(first)
    run(second)
    assert [element["x"] for element in first] == [element["x"] for element in second]
