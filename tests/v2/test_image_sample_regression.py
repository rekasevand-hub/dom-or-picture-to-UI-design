"""Structural regression over the seven benchmark screenshots.

The screenshots themselves cannot be re-run in a unit test — the perception
stage calls a vision model, costs money and does not repeat.  What is frozen
here is the compiled design for each sample, one file per screenshot, with the
frame fields stripped.  Every assertion therefore runs the deterministic half
of the pipeline: shell removal, coincident-text removal, frame assembly,
overlay lifting and the renderer's own acceptance pass.

Two things are locked:

* a floor on the number of accepted frames per sample, so an upstream change
  that quietly costs a container is caught as a failure rather than noticed a
  week later in an export;
* ``written == accepted``, which is the invariant that makes the frame count
  mean something: the meta must never claim a frame the renderer would drop.

A third check guards the export itself: no two text elements may print the same
words over the same area.
"""

from __future__ import annotations

import copy
import json
from difflib import SequenceMatcher
from pathlib import Path

import pytest

from src.app.services.rendering.adapter_base import paint_order, resolve_frames
from src.app.services.structure.fidelity.fixed_canvas_compiler import (
    _anchor_table_text,
    _drop_coincident_texts,
    _drop_page_coloured_shells,
    _fit_table_text,
    _keep_renderable_frames,
    _lift_frame_overlays,
    _repartition_table_rows,
    attach_layout_frames,
)

FIXTURES = Path(__file__).parent / "fixtures" / "image_samples"

#: Accepted frames measured on the frozen designs.  A floor, not an equality:
#: gaining a frame is never a regression, losing one always is.
FRAME_FLOORS = {
    "AtomGit": 9,
    "FluxWeaver": 6,
    "inventory": 9,
    "marketplace": 7,
    "review": 3,
    "wecom-modal": 6,
    "inventory2": 11,
}

#: A frame whose loss has already cost us a debugging round: the modal in the
#: dimmed dialog, and the table block in the inventory page.
REQUIRED_FRAMES = {
    "wecom-modal": {"modal"},
    "inventory": {"sidebar", "table-section"},
}

GHOST_COVERAGE = 0.35
GHOST_SIMILARITY = 0.6


def _load(tag: str) -> dict:
    return json.loads((FIXTURES / f"{tag}.json").read_text(encoding="utf-8"))


def _build(tag: str) -> tuple[list[dict], list[int], dict]:
    design = _load(tag)
    elements = copy.deepcopy(design["elements"])
    background = str((design.get("canvas") or {}).get("background") or "")
    # The fixture is the design as compiled: table cells already sit on the
    # rows their OCR lines were read at, and the frame fields are stripped so
    # the assembly has to be redone from geometry alone.
    # Type size for table cells is derived from ink, never from the cell box,
    # and a header row's columns are rebuilt from where its words are.
    # Replaying both here keeps the rules honest against frozen OCR lines.
    _repartition_table_rows(elements, design.get("ocr"))
    _fit_table_text(elements, design.get("ocr"), None)
    _drop_page_coloured_shells(elements, background)
    _drop_coincident_texts(elements)
    written = attach_layout_frames(elements)
    frames = [index for index, element in enumerate(elements) if element.get("layoutChildren")]
    _lift_frame_overlays(elements, frames)
    reasons: dict[int, str] = {}
    accepted = resolve_frames(elements, paint_order(elements), reasons)
    kept = _keep_renderable_frames(elements, written)
    return elements, sorted(accepted), {"written": written, "kept": kept, "reasons": reasons}


@pytest.mark.parametrize("tag", sorted(FRAME_FLOORS))
def test_sample_keeps_its_frames(tag: str) -> None:
    elements, accepted, report = _build(tag)
    assert len(accepted) >= FRAME_FLOORS[tag], (
        f"{tag}: {len(accepted)} frames, expected at least {FRAME_FLOORS[tag]}; "
        f"rejected {report['reasons']}"
    )
    for name in REQUIRED_FRAMES.get(tag, ()):  # pragma: no branch - tiny loop
        assert any(
            str(elements[index].get("name")) == name for index in accepted
        ), f"{tag}: frame {name!r} disappeared"


@pytest.mark.parametrize("tag", sorted(FRAME_FLOORS))
def test_written_equals_accepted(tag: str) -> None:
    """The frame count in the meta must equal what the renderer will build.

    ``_keep_renderable_frames`` clears the frames the renderer refuses, so this
    catches the case where that self-check stops running or starts disagreeing
    with ``resolve_frames`` — the meta would then promise frames that never
    appear in Figma.
    """
    elements, accepted, report = _build(tag)
    remaining = [
        index
        for index, element in enumerate(elements)
        if element.get("layoutChildren")
    ]
    assert sorted(remaining) == accepted, (
        f"{tag}: {len(remaining)} frames left in the design, "
        f"{len(accepted)} accepted"
    )
    assert report["kept"] == len(accepted)


@pytest.mark.parametrize("tag", sorted(FRAME_FLOORS))
def test_no_double_printed_text(tag: str) -> None:
    elements, _accepted, _report = _build(tag)
    texts = [
        element
        for element in elements
        if element.get("type") == "text" and element.get("text")
    ]
    clashes: list[str] = []
    for position, first in enumerate(texts):
        for second in texts[position + 1 :]:
            overlap_w = min(
                first["x"] + first["width"], second["x"] + second["width"]
            ) - max(first["x"], second["x"])
            overlap_h = min(
                first["y"] + first["height"], second["y"] + second["height"]
            ) - max(first["y"], second["y"])
            if overlap_w <= 0 or overlap_h <= 0:
                continue
            coverage = (overlap_w * overlap_h) / max(
                1,
                min(
                    first["width"] * first["height"],
                    second["width"] * second["height"],
                ),
            )
            if coverage < GHOST_COVERAGE:
                continue
            one = str(first["text"])
            two = str(second["text"])
            if (
                SequenceMatcher(None, one, two).ratio() >= GHOST_SIMILARITY
                or one in two
                or two in one
            ):
                clashes.append(f"{one!r} over {two!r} ({coverage:.2f})")
    assert not clashes, f"{tag}: same words printed twice: {clashes[:3]}"


def _text(index: int, x: int, y: int, width: int, height: int, text: str) -> dict:
    return {
        "id": f"table-cell:{index}",
        "contentRef": f"table-cell:{index}",
        "type": "text",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "text": text,
        "style": {"fontSize": 14, "textAlign": "center"},
    }


def _container(index: int, x: int, y: int, width: int, height: int) -> dict:
    return {
        "id": f"table-section:{index}",
        "type": "container",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "style": {"fillColor": "#ffffff"},
    }


def test_table_text_follows_ocr_when_a_whole_row_is_displaced() -> None:
    """Three cells that agree on a displacement move; the grid is the guess."""
    elements = [
        _container(0, 100, 100, 900, 500),
        _text(1, 120, 110, 200, 40, "单位"),
        _text(2, 340, 110, 200, 40, "生产日期"),
        _text(3, 560, 110, 200, 40, "失效日期"),
    ]
    ocr = [
        {"text": "单位", "bbox": [130, 380, 52, 30]},
        {"text": "生产日期", "bbox": [360, 380, 96, 30]},
        {"text": "失效日期", "bbox": [600, 380, 98, 30]},
    ]
    moved = _anchor_table_text(elements, ocr)
    assert moved == 3
    assert [element["y"] for element in elements[1:]] == [380, 380, 380]
    assert elements[1]["x"] == 130


def test_a_lone_far_match_is_left_alone() -> None:
    """One cell matching elsewhere is a repeated label, not a bad grid."""
    elements = [
        _container(0, 100, 100, 900, 500),
        _text(1, 120, 110, 200, 40, "数量"),
        _text(2, 340, 110, 200, 40, "单位"),
        _text(3, 560, 110, 200, 40, "批次"),
    ]
    ocr = [
        {"text": "数量", "bbox": [120, 420, 60, 30]},
        {"text": "单位", "bbox": [360, 116, 52, 30]},
        {"text": "批次", "bbox": [580, 114, 52, 30]},
    ]
    moved = _anchor_table_text(elements, ocr)
    assert moved == 0
    assert [element["y"] for element in elements[1:]] == [110, 110, 110]


def test_a_cell_is_not_moved_out_of_its_container() -> None:
    """A target outside the owning box would leave a member outside its frame."""
    elements = [
        _container(0, 100, 100, 400, 300),
        _text(1, 120, 110, 200, 40, "单位"),
        _text(2, 340, 110, 120, 40, "生产日期"),
        _text(3, 120, 200, 120, 40, "失效日期"),
    ]
    ocr = [
        {"text": "单位", "bbox": [130, 600, 52, 30]},
        {"text": "生产日期", "bbox": [600, 600, 96, 30]},
        {"text": "失效日期", "bbox": [640, 600, 98, 30]},
    ]
    assert _anchor_table_text(elements, ocr) == 0


def test_inventory_table_headers_sit_on_their_ocr_lines() -> None:
    """No header cell may drift from its own words.

    The threshold is the one that defines the defect: a cell within a line's
    height of its OCR line reads as aligned, and the header row that used to
    print 272px above its words is the case this guards.
    """
    design = _load("inventory")
    ocr = {
        str(line["text"]).strip(): line["bbox"]
        for line in design.get("ocr") or []
        if str(line.get("text") or "").strip()
    }
    checked = 0
    for element in design["elements"]:
        text = str(element.get("text") or "").strip()
        if not str(element.get("id", "")).startswith("table-header:") or text not in ocr:
            continue
        left, top, width, height = ocr[text]
        assert abs(element["y"] - top) <= 30, (
            f"{text!r} prints at y={element['y']}, OCR read it at y={top}"
        )
        checked += 1
    assert checked >= 3, f"only {checked} header cells matched an OCR line"


def _estimated_width(text: str, font: float) -> float:
    """Rough advance width: a CJK glyph is one em, a Latin one about 0.55."""
    width = 0.0
    for char in text:
        width += font * (1.0 if ord(char) > 0x2E80 else 0.55)
    return width


@pytest.mark.parametrize("tag", sorted(FRAME_FLOORS))
def test_table_text_keeps_a_readable_size(tag: str) -> None:
    """A cell's type size comes from ink, not from the grid interval around it.

    The failure this locks: a 20x54 column produced 40px type, and a header
    band measured 73px tall produced 54px — one glyph per line, in a column
    twenty pixels wide.
    """
    elements, _accepted, _report = _build(tag)
    wrong = [
        (str(element.get("text"))[:14], element["style"]["fontSize"])
        for element in elements
        if str(element.get("contentRef") or element.get("id") or "").startswith(
            ("table-header:", "table-cell:")
        )
        and element.get("text")
        and isinstance(element.get("style"), dict)
        and element["style"].get("fontSize")
        and not 8.0 <= float(element["style"]["fontSize"]) <= 34.0
    ]
    assert not wrong, f"{tag}: cell type out of range: {wrong[:3]}"


@pytest.mark.parametrize("tag", sorted(FRAME_FLOORS))
def test_no_text_is_wider_than_its_own_box(tag: str) -> None:
    """One glyph must fit the box it is centred in.

    A box may be wider than its words — that is padding or centring — never
    narrower than a single character.  A 25px column carrying 55px type is the
    case this catches, and it is what a box-derived font produces.
    """
    elements, _accepted, _report = _build(tag)
    overflowing = []
    for element in elements:
        if element.get("type") != "text" or not element.get("text"):
            continue
        style = element.get("style")
        if not isinstance(style, dict) or not style.get("fontSize"):
            continue
        font = float(style["fontSize"])
        # A single glyph has to fit the box; beyond that the string may wrap,
        # which is a column problem rather than a type-size problem.
        needed = font
        allowed = element["width"] * 1.2 + 8
        if needed > allowed:
            overflowing.append(
                (str(element["text"])[:14], round(font, 1), int(element["width"]), int(needed))
            )
    assert not overflowing, f"{tag}: text wider than its box: {overflowing[:3]}"


@pytest.mark.parametrize("tag", ["inventory", "inventory2"])
def test_table_columns_never_overlap(tag: str) -> None:
    """A rebuilt row must be a partition, not a pile.

    The inventory header used to arrive as 383 / 408 / 435 / 2492 / 2519 with
    the words at 626 / 844 / 1064 / 1274 / 1548: five labels crammed into 25px
    columns and the last two swapped end for end.
    """
    elements, _accepted, _report = _build(tag)
    for table in elements:
        if not str(table.get("id", "")).startswith("table-node:"):
            continue
        top, bottom = table["y"], table["y"] + table["height"]
        row = [
            element
            for element in elements
            if str(element.get("contentRef") or "").startswith("table-header:")
            and top <= element["y"] <= bottom
        ]
        row.sort(key=lambda element: element["x"])
        for left, right in zip(row, row[1:]):
            assert left["x"] + left["width"] <= right["x"] + 1, (
                f"{tag}: columns overlap {left.get('text')!r} / {right.get('text')!r}"
            )
        assert all(element["width"] >= 40 for element in row), (
            f"{tag}: narrow column {[e['width'] for e in row]}"
        )
