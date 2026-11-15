"""Rebuilding a paragraph from its OCR lines, and the referee's paper trail."""

from __future__ import annotations

import numpy as np
import pytest

from src.app.services.structure.fidelity.fixed_canvas_compiler import _reflow_paragraphs
from src.app.services.structure.fidelity.vlm_arbiter import (
    Candidate,
    GateResult,
    Ticket,
    TicketFile,
    build_candidates,
    execute,
    render_key,
)


def _node(x, y, w, h, text, size=20.0):
    return {
        "id": "text:card",
        "type": "text",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "text": text,
        "style": {"fontSize": size, "textAlign": "left"},
    }


def _ocr(lines):
    return [
        {"text": text, "bbox": list(box)} for text, box in lines
    ]


CARD = "从 Meta 内部走出来的开源设计系统：150 多个可访问组件加主题体系，让产品团队和 AI 助手按同一套规范搭界面"


def test_a_flat_paragraph_takes_the_lines_the_picture_has() -> None:
    elements = [_node(1154, 343, 662, 31, CARD)]
    ocr = _ocr(
        [
            ("从 Meta 内部走出来的开源设计系统:  150多个可访问组件加主题体系,", (1154, 343, 662, 31)),
            ("让产品团队和 Al 助手按同一套规范搭界面", (1154, 378, 394, 30)),
        ]
    )

    assert _reflow_paragraphs(elements, ocr) == 1
    node = elements[0]
    assert node["lines"][0].startswith("从 Meta")
    assert node["lines"][1].startswith("让产品团队和 AI")
    assert node["height"] == pytest.approx(65.0)
    assert node["lineHeight"] == pytest.approx(35.0)
    assert node["textAnchor"] == "start"
    assert node["text"] == CARD  # the model's wording survives the rebuild


def test_the_meta_row_below_is_not_swallowed() -> None:
    elements = [_node(1154, 343, 662, 31, CARD)]
    ocr = _ocr(
        [
            ("从 Meta 内部走出来的开源设计系统:  150多个可访问组件加主题体系,", (1154, 343, 662, 31)),
            ("让产品团队和 Al 助手按同一套规范搭界面", (1154, 378, 394, 30)),
            ("TSX", (1160, 420, 40, 24)),
        ]
    )

    _reflow_paragraphs(elements, ocr)

    assert len(elements[0]["lines"]) == 2


def test_a_paragraph_whose_words_do_not_match_is_left_flat() -> None:
    elements = [_node(100, 100, 600, 31, "这是一段完全不同的说明文字，原图里并不是它，长度也够长")]
    ocr = _ocr([("另一段毫不相干的话，用来验证匹配门槛是否起作用", (100, 100, 600, 31))])

    assert _reflow_paragraphs(elements, ocr) == 0
    assert "lines" not in elements[0]


def test_a_short_label_is_not_a_paragraph() -> None:
    elements = [_node(100, 100, 60, 31, "热门推荐")]
    ocr = _ocr([("热门推荐", (100, 100, 60, 31)), ("下一行", (100, 140, 60, 30))])

    assert _reflow_paragraphs(elements, ocr) == 0


def _canvas():
    truth = np.full((60, 120, 3), 255, dtype=np.int16)
    drawn = truth.copy()
    drawn[20:40, 20:100] = 0
    truth[20:40, 20:100] = 0
    truth[20:40, 20:60] = 0
    drawn[20:40, 20:60] = 0
    truth[20:40, 60:100] = 200
    return truth, drawn


def test_candidates_are_numbered_and_worst_first() -> None:
    truth, drawn = _canvas()
    regions = [[20, 20, 80, 20, 5], [0, 0, 4, 4, 5]]

    candidates = build_candidates(truth, drawn, regions)

    assert candidates
    assert isinstance(candidates[0], Candidate)
    assert candidates[0].error >= candidates[-1].error


def test_tickets_freeze_and_replay_only_on_the_same_render(tmp_path) -> None:
    truth, drawn = _canvas()
    path = tmp_path / "15_arbiter_tickets.json"
    key = "picture-render"
    frozen = TicketFile(key=key, tickets=[Ticket(type="STYLE_MISMATCH", node_id="text:card", fix="bold")])
    frozen.save(path)

    assert len(TicketFile.load(path, key).tickets) == 1
    assert TicketFile.load(path, "other-render").tickets == []


def test_a_style_ticket_bolds_the_node_it_names() -> None:
    truth, drawn = _canvas()
    elements = [_node(10, 10, 80, 20, "价格")]
    ticket = Ticket(type="STYLE_MISMATCH", node_id="text:card", fix="bold")

    assert execute(ticket, elements, truth, drawn)
    assert elements[0]["style"]["fontWeightValue"] == 700


def test_a_style_ticket_for_a_node_that_is_gone_does_nothing() -> None:
    truth, drawn = _canvas()
    elements = [_node(10, 10, 80, 20, "价格")]

    assert execute(Ticket(type="STYLE_MISMATCH", node_id="text:ghost", fix="bold"), elements, truth, drawn) is None


def test_a_text_ticket_builds_a_node_from_the_pixels_there() -> None:
    truth, drawn = _canvas()
    elements: list[dict] = []
    ticket = Ticket(
        type="MISSING_OR_FADED_TEXT",
        roi_bbox=[20, 20, 80, 20],
        expected_text="库位",
    )

    assert execute(ticket, elements, truth, drawn)
    node = elements[0]
    assert node["text"] == "库位"
    assert node["style"]["textColor"].startswith("#")
    assert 18 <= node["style"]["fontSize"] <= 20


def test_an_unknown_ticket_is_rejected_before_it_touches_anything() -> None:
    with pytest.raises(ValueError):
        Ticket(type="NICE_IDEA", node_id="x").validate()


def _gate(**overrides) -> GateResult:
    values = dict(
        roi_before=80.0,
        roi_after=90.0,
        global_before=93.0,
        global_after=93.1,
        frames=13,
        frames_floor=9,
        written_equals_accepted=True,
        patch_share=4.0,
    )
    values.update(overrides)
    return GateResult(**values)


def test_the_gate_accepts_a_ticket_that_improves_its_block_and_not_the_page() -> None:
    assert _gate().passed
    assert _gate().failures == []


@pytest.mark.parametrize(
    "overrides, failure",
    [
        ({"roi_after": 70.0}, "roi-worse"),
        ({"global_after": 92.5}, "page-worse"),
        ({"frames": 7}, "frames-lost"),
        ({"written_equals_accepted": False}, "frames-disagree"),
        ({"patch_share": 9.0}, "patch-budget"),
    ],
)
def test_the_gate_names_the_rule_that_failed(overrides, failure) -> None:
    gate = _gate(**overrides)
    assert not gate.passed
    assert failure in gate.failures


def test_the_key_changes_when_the_render_changes(tmp_path) -> None:
    drawn = tmp_path / "render.png"
    drawn.write_bytes(b"one")
    first = render_key("a" * 40, drawn)
    drawn.write_bytes(b"two")
    assert render_key("a" * 40, drawn) != first
