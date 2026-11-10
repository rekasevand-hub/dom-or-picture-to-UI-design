"""Table cells state their own type scale; a 48.5 pt placeholder is an artefact.

light-table: 62 cells at 15.2 / 20 / 21 pt, plus 16 placeholders at 48.5 pt
whose size was inherited from the 55 px input box.  The clamp only touches
``table-cell`` owners and only above 1.6x the cells' median, so a hero number or
a KPI card keeps its size.
"""

from __future__ import annotations

from src.app.services.structure.fidelity.text_calibration import (
    clamp_table_cell_font_outliers,
)


def _cell(text: str, size: float, *, role: str = "table-cell", kind: str = "text") -> dict:
    return {
        "type": kind,
        "text": text,
        "contentRef": f"table-cell:{text[:6]}:{size}",
        "x": 0,
        "y": 0,
        "width": 206,
        "height": 55,
        "style": {"fontSize": size, "fontWeight": "normal"},
        "imageMVP": {"role": role},
    }


def _design(elements: list[dict]) -> dict:
    return {"canvas": {"width": 2544, "height": 1336}, "elements": elements}


def test_clamps_placeholder_outliers_to_the_cell_median() -> None:
    design = _design(
        [_cell(f"c{index}", 15.2) for index in range(16)]
        + [_cell(f"d{index}", 20.0) for index in range(14)]
        + [_cell(f"e{index}", 21.0) for index in range(34)]
        + [_cell("(选填)", 48.5) for _ in range(8)]
        + [_cell("请输入0~...", 48.5) for _ in range(8)]
    )
    calibrated, report = clamp_table_cell_font_outliers(design)

    assert report["median_size"] == 21.0
    assert report["adjusted_count"] == 16
    assert {item["previous"] for item in report["adjustments"]} == {48.5}
    assert {item["updated"] for item in report["adjustments"]} == {21.0}
    sizes = [item["style"]["fontSize"] for item in calibrated["elements"]]
    assert sizes.count(48.5) == 0
    # Input design is untouched.
    assert design["elements"][-1]["style"]["fontSize"] == 48.5


def test_uniform_table_is_a_no_op() -> None:
    design = _design([_cell(f"c{index}", 21.0) for index in range(10)])
    _calibrated, report = clamp_table_cell_font_outliers(design)
    assert report["status"] == "not-needed"
    assert report["adjusted_count"] == 0


def test_free_text_at_the_same_size_is_not_touched() -> None:
    """A hero number may legitimately be 48 pt."""
    design = _design(
        [_cell(f"c{index}", 21.0) for index in range(6)]
        + [
            {
                "type": "text",
                "text": "¥1.16",
                "x": 0,
                "y": 0,
                "width": 270,
                "height": 48,
                "style": {"fontSize": 48.5, "fontWeight": "normal"},
                "imageMVP": {"role": "text"},
            }
        ]
    )
    calibrated, report = clamp_table_cell_font_outliers(design)
    assert report["adjusted_count"] == 0
    assert calibrated["elements"][-1]["style"]["fontSize"] == 48.5


def test_boundary_is_exclusive() -> None:
    design = _design(
        [_cell(f"c{index}", 20.0) for index in range(6)] + [_cell("edge", 32.0)]
    )
    _calibrated, report = clamp_table_cell_font_outliers(design)
    assert report["adjusted_count"] == 0  # 32.0 == 1.6 x 20.0 is still the top of the band


def test_too_few_cells_have_no_median() -> None:
    design = _design([_cell("a", 21.0), _cell("b", 48.5), _cell("c", 21.0)])
    _calibrated, report = clamp_table_cell_font_outliers(design)
    assert report["status"] == "not-needed"
    assert report["adjusted_count"] == 0


def test_idempotent() -> None:
    design = _design(
        [_cell(f"c{index}", 21.0) for index in range(6)] + [_cell("p", 48.5)]
    )
    once, first = clamp_table_cell_font_outliers(design)
    twice, second = clamp_table_cell_font_outliers(once)
    assert first["adjusted_count"] == 1
    assert second["adjusted_count"] == 0
    assert [item["style"]["fontSize"] for item in twice["elements"]] == [
        item["style"]["fontSize"] for item in once["elements"]
    ]
