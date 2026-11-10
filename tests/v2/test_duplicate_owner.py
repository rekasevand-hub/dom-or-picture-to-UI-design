"""Phantom owners: a text that repeats a roomier owner from a box that cannot
hold it is a detection error, not content.

dark-card-grid: the hero search placeholder also appears in the nav row at
``[1084, 42, 58, 29]`` -- 4.2x narrower than its glyph run -- and paints across
``社区`` / ``接入文档``.  The drop is gated on *two* signals so legitimate
repeats (a CTA in header and footer, both with roomy boxes) survive.
"""

from __future__ import annotations

from src.app.services.structure.fidelity.text_calibration import (
    drop_implausible_duplicate_owners,
)


def _element(
    text: str,
    x: float,
    y: float,
    width: float,
    height: float,
    size: float,
    *,
    kind: str = "text",
) -> dict:
    return {
        "type": kind,
        "text": text,
        "contentRef": f"{kind}:{text[:6]}",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "style": {"fontSize": size, "fontWeight": "normal"},
    }


def _design(elements: list[dict]) -> dict:
    return {"canvas": {"width": 2544, "height": 1336}, "elements": elements}


def test_drops_the_phantom_nav_search_box() -> None:
    design = _design(
        [
            # Real control in the hero: 442 px for 22 characters at 16.25.
            _element("搜索模型或「商。例如 deepseek", 1706, 297, 442, 40, 16.25, kind="text"),
            # Phantom in the nav row: a 58 px box cannot hold the same string,
            # and its reading is the clean one (no OCR artefacts).
            _element("搜索模型或厂商，例如 deepseek", 1084, 42, 58, 29, 16.25, kind="input"),
            _element("Agent 优惠", 989, 35, 158, 45, 32.25),
        ]
    )
    calibrated, report = drop_implausible_duplicate_owners(design)

    assert report["adjusted_count"] == 1
    assert report["dropped"][0]["bbox"] == [1084.0, 42.0, 58.0, 29.0]
    assert report["dropped"][0]["similarity"] >= 0.85
    assert report["dropped"][0]["text_merged"] is True
    assert report["dropped"][0]["merged_text"] == "搜索模型或厂商，例如 deepseek"
    texts = [item["text"] for item in calibrated["elements"]]
    # The clean reading survives exactly once, on the roomy hero box.
    assert texts.count("搜索模型或厂商，例如 deepseek") == 1
    assert calibrated["elements"][0]["x"] == 1706
    assert "Agent 优惠" in texts
    # Input design is not mutated.
    assert len(design["elements"]) == 3


def test_cleaner_survivor_text_is_not_overwritten() -> None:
    design = _design(
        [
            _element("搜索模型或厂商，例如 deepseek", 1706, 297, 442, 40, 16.25),
            _element("搜索模型或「商。例如 deepseek", 1084, 42, 58, 29, 16.25, kind="input"),
        ]
    )
    calibrated, report = drop_implausible_duplicate_owners(design)
    assert report["adjusted_count"] == 1
    assert report["dropped"][0]["text_merged"] is False
    assert calibrated["elements"][0]["text"] == "搜索模型或厂商，例如 deepseek"


def test_legitimate_repeat_with_roomy_boxes_survives() -> None:
    design = _design(
        [
            _element("立即购买", 120, 40, 160, 44, 16.0, kind="button"),
            _element("立即购买", 120, 720, 160, 44, 16.0, kind="button"),
        ]
    )
    calibrated, report = drop_implausible_duplicate_owners(design)
    assert report["adjusted_count"] == 0
    assert len(calibrated["elements"]) == 2


def test_lone_overflowing_owner_is_kept() -> None:
    """A table placeholder with no duplicate is a size problem, not a phantom."""
    design = _design(
        [_element("请输入0~...", 1679, 510, 206, 55, 48.5, kind="text")]
    )
    calibrated, report = drop_implausible_duplicate_owners(design)
    assert report["adjusted_count"] == 0
    assert len(calibrated["elements"]) == 1


def test_two_implausible_boxes_do_not_cannibalise_each_other() -> None:
    design = _design(
        [
            _element("搜索模型或厂商", 100, 40, 30, 24, 16.0, kind="input"),
            _element("搜索模型或厂商", 900, 300, 30, 24, 16.0, kind="input"),
        ]
    )
    calibrated, report = drop_implausible_duplicate_owners(design)
    assert report["adjusted_count"] == 0
    assert len(calibrated["elements"]) == 2


def test_table_text_is_never_inspected_as_a_duplicate_source() -> None:
    design = _design(
        [
            _element("合计", 100, 40, 120, 40, 16.0),
            _element("合计", 100, 300, 120, 40, 16.0),
        ]
    )
    calibrated, report = drop_implausible_duplicate_owners(design)
    assert report["adjusted_count"] == 0
    assert len(calibrated["elements"]) == 2
