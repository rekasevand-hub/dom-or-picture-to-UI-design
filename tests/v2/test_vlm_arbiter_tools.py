"""The three upgrades to the closed loop, driven by mocks.

1. Field authority: a single line of text has no size axes — the box follows the
   glyphs, so ``dw``/``dh`` is a patch that cannot move a pixel.  Five of eight
   live patches last round were exactly that, all rolled back with an identical
   ROI (25.84 → 25.84).
2. Semantic tools: fix the words, fix a contrast, lift a node.  None of them
   moves a member, so all of them face the same four gates.
3. Whole-page sweep: name at most three flaws the pixel Top-K cannot see
   (a missing button label has almost no area), bind them to nodes, and hand
   them to the same patch pipeline.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.app.services.structure.fidelity import vlm_arbiter as arbiter


def _canvas(size=(120, 160)) -> np.ndarray:
    height, width = size
    return np.full((height, width, 3), 250, dtype=np.uint8)


def _text(box=(40, 40, 60, 20), text="错字", node_id="t1"):
    x, y, w, h = box
    return {
        "id": node_id,
        "type": "text",
        "x": float(x),
        "y": float(y),
        "width": float(w),
        "height": float(h),
        "text": text,
        "style": {"fontSize": 14.0, "fontWeightValue": 400, "textColor": "#1a1a1a"},
        "_paint": (20, 20, 20),
    }


def _order(element_type: str, kind: str, index: int = 0) -> arbiter.WorkOrder:
    return arbiter.WorkOrder(
        index=index,
        ref="ref-1",
        box=[0, 0, 20, 20],
        element_id="t1",
        kind=kind,
        element_type=element_type,
    )


# ---------------------------------------------------------------------------
# 一、字段分权
# ---------------------------------------------------------------------------


def test_a_single_line_text_order_never_gets_a_size_axis() -> None:
    order = _order("text", "text")
    parsed = arbiter.parse_round_edits(
        {"patches": [{"index": 0, "dw": 12, "dh": -6, "fontSize": 2}]},
        orders=[order],
    )

    assert parsed[0].numeric == {"fontSize": 2.0}


def test_a_wrapped_text_block_also_has_no_size_axis() -> None:
    """Every text node in this emitter is auto-sized, single line or not.

    The instruction names the single line because that is the common case; the
    authority follows the node type, and no text box takes ``dw``/``dh``.
    """
    order = _order("text", "text-block")
    parsed = arbiter.parse_round_edits(
        {"patches": [{"index": 0, "dw": 12}]}, orders=[order]
    )

    assert parsed == {}


def test_a_container_keeps_the_size_axes_and_a_button_does_not() -> None:
    container = _order("container", "geometry")
    button = _order("button", "geometry")

    assert arbiter.patch_fields_for(container) == tuple(arbiter.PATCH_LIMITS)
    assert "dw" not in arbiter.patch_fields_for(button)
    assert "letterSpacing" in arbiter.patch_fields_for(button)


def test_the_prompt_tells_the_model_which_axes_are_open() -> None:
    orders = [_order("text", "text", 0), _order("container", "geometry", 1)]
    orders[1].ref = "ref-2"
    prompt = arbiter.round_prompt(orders)

    assert "禁止填 dw/dh" in prompt
    assert "fontSize 或 letterSpacing" in prompt
    assert "setText" in prompt and "zIndex" in prompt
    assert "只能改 dx/dy/fontSize/letterSpacing/fontWeight" in prompt


def test_apply_refuses_a_size_axis_on_text_even_when_called_directly() -> None:
    """Second line of defence: a caller that forgets to filter cannot resize type."""
    element = _text()
    applied = arbiter.apply_round_edit(element, {"dw": 10})

    assert applied is None
    assert element["width"] == 60.0


# ---------------------------------------------------------------------------
# 二、语义工具
# ---------------------------------------------------------------------------


def test_set_text_rewrites_a_label() -> None:
    element = _text()
    applied = arbiter.apply_round_edit(
        element, arbiter.RoundEdit(text="正确文案"), element_type="text"
    )

    assert applied == {"setText": "正确文案"}
    assert element["text"] == "正确文案"


def test_a_text_edit_may_not_delete_the_sentence() -> None:
    """The pixel guard rewards deletion; this rule does not.

    AtomGit's A/B kept ``从Meta…设计系统：15`` in place of the full headline and
    the block error *fell* by 2.6 — blank paper scored better than the render's
    misaligned glyphs.  A reviewer would call that a deletion, not a repair.
    """
    current = "从Meta内部走出来的开源设计系统：150多个可访问组件加主题体系，"

    assert arbiter.text_edit_is_correction(current, "从Meta内部走出来的开源设计系统：15") is False
    assert arbiter.text_edit_is_correction(current, "个可访问组件加主题体系，") is False


def test_a_text_edit_may_fix_a_glyph_or_add_missing_words() -> None:
    assert arbiter.text_edit_is_correction(
        '{"error""SUCCESS","message":"SUCCESS")',
        '{"error":"SUCCESS","message":"SUCCESS"}',
    )
    # OCR 把一个标签读成一个字母：短的那一侧没有相似度可言，只能靠长度方向判断。
    assert arbiter.text_edit_is_correction("d", "PC端") is True
    # 同一句换个不相干的词，不是改错字。
    assert arbiter.text_edit_is_correction("执行时间", "创建时间xxxxx") is False


def test_set_text_is_refused_on_a_container() -> None:
    element = {"id": "c1", "type": "container", "style": {"fillColor": "#ffffff"}}
    applied = arbiter.apply_round_edit(
        element, arbiter.RoundEdit(text="不该出现"), element_type="container"
    )

    assert applied is None
    assert element.get("text") is None


def test_colour_lands_on_the_axis_the_type_owns() -> None:
    text = _text()
    assert arbiter.apply_round_edit(
        text, arbiter.RoundEdit(text_color="#ffffff"), element_type="text"
    ) == {"textColor": "#ffffff"}

    surface = {"id": "c1", "type": "container", "style": {"fillColor": "#ffffff"}}
    assert arbiter.apply_round_edit(
        surface, arbiter.RoundEdit(fill_color="#f5f5f5"), element_type="container"
    ) == {"fillColor": "#f5f5f5"}


def test_a_malformed_colour_is_ignored_rather_than_written() -> None:
    parsed = arbiter.parse_round_edits(
        {"patches": [{"index": 0, "textColor": "white", "fillColor": "#12345"}]}
    )
    assert parsed == {}


def test_z_index_lifts_a_node_out_of_an_overlay() -> None:
    element = _text()
    applied = arbiter.apply_round_edit(
        element, arbiter.RoundEdit(z_index=30), element_type="text"
    )

    assert applied == {"zIndex": 30}
    assert element["zIndex"] == 30


def test_z_index_is_refused_on_a_frame() -> None:
    """Reordering a frame among its siblings re-orders everything inside it."""
    element = _text()
    assert (
        arbiter.apply_round_edit(
            element, arbiter.RoundEdit(z_index=30), frozen=True, element_type="text"
        )
        is None
    )
    assert "zIndex" not in element


def test_an_edit_that_changes_nothing_is_not_an_edit() -> None:
    element = _text(text="一样")
    assert (
        arbiter.apply_round_edit(
            element, arbiter.RoundEdit(text="一样"), element_type="text"
        )
        is None
    )


# ---------------------------------------------------------------------------
# 三、全图语义巡检
# ---------------------------------------------------------------------------


def test_a_sweep_defect_binds_to_the_node_under_it() -> None:
    elements = [_text(box=(40, 40, 60, 20))]
    orders = arbiter.sweep_work_orders(
        elements,
        [{"kind": "typo", "bbox": [44, 42, 40, 16], "expected_text": "正确", "note": "误识"}],
    )

    assert len(orders) == 1
    assert orders[0].element_id == "t1"
    assert "typo" in orders[0].hint
    assert "正确" in orders[0].hint
    # 裁片比节点大一圈：只看缺陷本身看不出它偏了多少。
    assert orders[0].box[2] > 60


def test_the_smallest_node_wins_a_tie() -> None:
    """A typo's box is inside the row *and* inside the word; only the word can change."""
    row = {
        "id": "row-1",
        "type": "container",
        "x": 0.0,
        "y": 0.0,
        "width": 400.0,
        "height": 40.0,
        "style": {"fillColor": "#ffffff"},
    }
    word = _text(box=(40, 10, 80, 20), text="错字", node_id="word-1")
    orders = arbiter.sweep_work_orders(
        [row, word], [{"kind": "typo", "bbox": [42, 12, 60, 16], "expected_text": "正确"}]
    )

    assert [order.element_id for order in orders] == ["word-1"]


def test_a_missing_text_claim_must_survive_the_pixels() -> None:
    """"Missing" usually means "rendered too small to read in a 0.75 scale panel"."""
    truth = _canvas((60, 120))
    truth[20:40, 10:90] = (20, 20, 20)
    drawn_same = truth.copy()
    drawn_blank = np.full((60, 120, 3), 250, dtype=np.uint8)

    box = [10, 20, 80, 20]

    assert arbiter.still_missing(drawn_same, truth, box) is False
    assert arbiter.still_missing(drawn_blank, truth, box) is True


def test_the_sweep_reports_what_it_dismissed() -> None:
    truth = _canvas((60, 120))
    truth[20:40, 10:90] = (20, 20, 20)
    elements = [_text(box=(10, 20, 80, 20), text="这里有字")]

    report = arbiter._sweep_round(
        elements,
        truth,
        truth.copy(),  # 渲染图上有墨 → "缺字"不成立
        propose_sweep=lambda prompt, panels: {
            "defects": [{"kind": "missing-text", "bbox": [10, 20, 80, 20]}]
        },
        start=0,
        existing=set(),
    )

    assert report["defects"] == []
    assert report["report"]["dismissed"] == 1
    assert report["report"]["dismissedKinds"] == ["missing-text"]


def test_a_sweep_defect_that_matches_nothing_is_dropped() -> None:
    elements = [_text(box=(40, 40, 60, 20))]
    orders = arbiter.sweep_work_orders(
        elements, [{"kind": "missing-icon", "bbox": [900, 900, 10, 10]}]
    )

    assert orders == []


def test_the_sweep_does_not_re_nominate_a_node_the_pixels_already_found() -> None:
    elements = [_text(box=(40, 40, 60, 20))]
    defects = [{"kind": "overlap", "bbox": [40, 40, 60, 20]}]
    orders = arbiter.sweep_work_orders(elements, defects, start=3, exclude={"t1"})

    assert orders == []


def test_sweep_answers_are_capped_and_validated() -> None:
    payload = {
        "defects": [
            {"kind": "typo", "bbox": [1, 2, 3, 4], "expected_text": "A"},
            {"kind": "nonsense", "bbox": [1, 2, 3, 4]},
            {"kind": "overlap", "bbox": [1, 2]},
            {"kind": "missing-text", "bbox": [5, 5, 20, 10]},
            {"kind": "color", "bbox": [6, 6, 20, 10]},
        ]
    }
    defects = arbiter.parse_sweep_defects(payload)

    assert [item["kind"] for item in defects] == ["typo", "missing-text", "color"]


def test_the_loop_turns_a_sweep_defect_into_a_kept_semantic_patch() -> None:
    """A typo has no area, so the pixel nominator sees nothing. The sweep does.

    The painter prints the block only when the words are right, which makes
    "setText improved the pixels" a measurable fact instead of an opinion.
    """
    truth = _canvas()
    truth[40:60, 40:100] = (20, 20, 20)
    elements = [_text(text="错字")]

    def draw(items):
        canvas = _canvas()
        for item in items:
            if item.get("type") == "text" and item.get("text") == "正确文案":
                x, y, w, h = (int(item[key]) for key in ("x", "y", "width", "height"))
                canvas[y : y + h, x : x + w] = (20, 20, 20)
        return canvas

    seen: dict = {}

    def propose(orders, strips):
        seen["orders"] = orders
        return {"patches": [{"index": 0, "setText": "正确文案"}]}

    def sweep(prompt, panels):
        seen["prompt"] = prompt
        seen["panels"] = panels
        return {"defects": [{"kind": "typo", "bbox": [40, 40, 60, 20], "expected_text": "正确文案"}]}

    # k=0：把像素提名关掉，证明这一轮工单**只**来自整页巡检。
    report = arbiter.refine(
        elements, truth, draw, propose=propose, propose_sweep=sweep, rounds=1, k=0
    )

    assert report["kept"] == 1
    assert elements[0]["text"] == "正确文案"
    assert seen["orders"][0].hint.startswith("typo")
    # 巡检只给一次整页并排（三段 1:1；页面比 MACRO_WIDTH 宽时再加一张整页缩略），
    # 不是逐块。
    assert 3 <= len(seen["panels"]) <= 4
    assert report["sweeps"][0]["named"] == 1
