"""Two different strings in one slot: drop only what is provably an OCR artefact.

light-table has seven such pairs.  Six are semantic conflicts where both
readings are plausible (``未确认(0)`` vs ``个人信息``) -- a geometry rule that
picks a winner would delete real content, so those are recorded as
``unresolved`` for adjudication.  The one provable shape is an icon glyph glued
to a label (``Q搜索`` = ``Q`` + ``搜索``).
"""

from __future__ import annotations

from src.app.services.structure.fidelity.text_calibration import (
    resolve_same_slot_conflicts,
)


def _element(text: str, x: float, y: float, width: float, height: float, size: float = 20.0) -> dict:
    return {
        "type": "text",
        "text": text,
        "contentRef": f"text:{text[:6]}",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "style": {"fontSize": size, "fontWeight": "normal"},
    }


def test_drops_the_icon_glyph_concatenation() -> None:
    design = {
        "canvas": {"width": 2544, "height": 1336},
        "elements": [
            _element("搜索", 60, 120, 116, 40),
            # OCR glued the magnifier icon to the label and read it as "Q".
            _element("Q搜索", 60, 120, 72, 40, 22.8),
        ],
    }
    calibrated, report = resolve_same_slot_conflicts(design)

    assert report["adjusted_count"] == 1
    assert report["dropped"][0]["reason"] == "ocr-concatenation"
    assert report["dropped"][0]["conflict"] == "Q搜索"
    texts = [item["text"] for item in calibrated["elements"]]
    assert texts == ["搜索"]


def test_semantic_conflicts_are_recorded_not_resolved() -> None:
    design = {
        "canvas": {"width": 2544, "height": 1336},
        "elements": [
            _element("未确认(0)", 100, 370, 204, 40, 21.8),
            _element("个人信息", 112, 373, 91, 40, 19.0),
        ],
    }
    calibrated, report = resolve_same_slot_conflicts(design)

    assert report["adjusted_count"] == 0
    assert len(report["unresolved"]) == 1
    assert report["unresolved"][0]["kept"] == "未确认(0)"
    assert report["unresolved"][0]["conflict"] == "个人信息"
    assert len(calibrated["elements"]) == 2


def test_identical_strings_are_left_to_the_duplicate_owner_pass() -> None:
    design = {
        "canvas": {"width": 2544, "height": 1336},
        "elements": [
            _element("合计", 100, 40, 120, 40),
            _element("合计", 100, 40, 120, 40),
        ],
    }
    _calibrated, report = resolve_same_slot_conflicts(design)
    assert report["adjusted_count"] == 0
    assert report["unresolved"] == []


def test_non_overlapping_texts_are_ignored() -> None:
    design = {
        "canvas": {"width": 2544, "height": 1336},
        "elements": [
            _element("搜索", 60, 120, 116, 40),
            _element("Q搜索", 600, 120, 72, 40, 22.8),
        ],
    }
    _calibrated, report = resolve_same_slot_conflicts(design)
    assert report["adjusted_count"] == 0
    assert report["unresolved"] == []


def test_cjk_suffix_is_not_treated_as_an_artefact() -> None:
    """``取消`` / ``取消确定`` are different labels, not one OCR read."""
    design = {
        "canvas": {"width": 2544, "height": 1336},
        "elements": [
            _element("取消", 100, 40, 90, 40),
            _element("取消确定", 100, 40, 140, 40),
        ],
    }
    _calibrated, report = resolve_same_slot_conflicts(design)
    assert report["adjusted_count"] == 0
    assert len(report["unresolved"]) == 1
