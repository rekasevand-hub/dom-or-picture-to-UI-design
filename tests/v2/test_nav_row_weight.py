"""Header menu rows: one band of short labels at one size, above the content.

The rule exists because the six remaining Medium mismatches on dark-card-grid
sit in a single row at the top of the page.  These fixtures replay that row's
measured geometry (``pipeline/12_design.json`` of the 2026-11-10 split run), so
the numbers in the tests are observations, not invented tolerances.
"""

from __future__ import annotations

from src.app.services.structure.fidelity.text_calibration import (
    apply_nav_row_weight,
)


def _element(
    x: float,
    y: float,
    width: float,
    height: float,
    size: float,
    text: str,
    *,
    weight: object = "normal",
    kind: str = "text",
    role: str | None = None,
    control_type: str | None = None,
) -> dict:
    element = {
        "type": kind,
        "text": text,
        "contentRef": f"{kind}:{text}",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "style": {"fontSize": size, "fontWeight": weight},
    }
    if role:
        element["imageMVP"] = {"role": role, "candidate_type": kind}
    if control_type:
        element["controlType"] = control_type
    return element


def _design(elements: list[dict], height: float = 1336) -> dict:
    return {
        "canvas": {"width": 2544, "height": height},
        "elements": elements,
    }


def _dark_header_row() -> list[dict]:
    """The measured dark-card-grid header: five labels plus one button label."""
    return [
        _element(132, 37, 321, 37, 25.75, "ACCTOKEN"),
        _element(443, 35, 70, 42, 27.5, "首页"),
        _element(743, 37, 98, 40, 27.5, "创作"),
        _element(865, 37, 70, 40, 27.5, "价格"),
        _element(989, 35, 158, 45, 32.25, "Agent 优惠"),
        # Menu label written as a control; controlType says navigation.
        _element(
            1205,
            42,
            59,
            29,
            27.5,
            "社区",
            kind="button",
            role="control",
            control_type="navigation",
        ),
        _element(1317, 32, 133, 49, 27.5, "接入文档"),
    ]


def _weights(design: dict) -> dict[str, object]:
    return {
        element["text"]: element["style"]["fontWeight"]
        for element in design["elements"]
    }


def test_promotes_the_dark_header_row_to_medium() -> None:
    design = _design(
        _dark_header_row()
        + [
            # Same band, but a button control (not navigation) and a search
            # control: both are structural non-members, not text patterns.
            _element(
                2378,
                43,
                55,
                27,
                27.5,
                "控制台",
                kind="button",
                role="control",
                control_type="button",
            ),
            _element(
                1706,
                42,
                442,
                40,
                13.75,
                "搜索模型或厂商，例如 deepseek",
                kind="input",
                role="control",
                control_type="input",
            ),
        ]
    )
    calibrated, report = apply_nav_row_weight(design)

    assert report["status"] == "applied"
    assert report["adjusted_count"] == 7
    assert len(report["rows"]) == 1
    assert report["rows"][0]["modal_font_size"] == 27.5
    assert report["rows"][0]["promoted_count"] == 7
    weights = _weights(calibrated)
    for label in ("首页", "创作", "价格", "Agent 优惠", "社区", "接入文档", "ACCTOKEN"):
        assert weights[label] == 500
    # Small button and input never enter the row.
    assert weights["控制台"] == "normal"
    assert weights["搜索模型或厂商，例如 deepseek"] == "normal"
    # Input design is untouched.
    assert _weights(design)["首页"] == "normal"


def test_two_items_are_not_a_menu() -> None:
    _calibrated, report = apply_nav_row_weight(
        _design(
            [
                _element(100, 30, 80, 40, 27.5, "首页"),
                _element(300, 30, 80, 40, 27.5, "价格"),
            ]
        )
    )
    assert report["status"] == "not-needed"
    assert report["adjusted_count"] == 0


def test_rows_below_the_header_band_are_left_alone() -> None:
    row = [
        _element(300 + 180 * index, 700, 80, 40, 27.5, f"项{index}")
        for index in range(4)
    ]
    _calibrated, report = apply_nav_row_weight(_design(row))
    assert report["adjusted_count"] == 0


def test_mixed_sizes_do_not_form_a_menu() -> None:
    design = _design(
        [
            _element(300, 30, 80, 40, 27.5, "首页"),
            _element(500, 30, 80, 40, 40.0, "创作"),
            _element(700, 30, 80, 40, 52.0, "价格"),
        ]
    )
    _calibrated, report = apply_nav_row_weight(design)
    assert report["adjusted_count"] == 0


def test_control_and_table_owners_are_skipped() -> None:
    design = _design(
        [
            _element(300, 30, 80, 40, 27.5, "首页", role="control"),
            _element(500, 30, 80, 40, 27.5, "创作", role="table-cell"),
            _element(700, 30, 80, 40, 27.5, "价格", role="table-header"),
        ]
    )
    _calibrated, report = apply_nav_row_weight(design)
    assert report["adjusted_count"] == 0
    assert report["skipped_non_free_text"] == 3


def test_only_regular_is_promoted() -> None:
    design = _design(
        [
            _element(300, 30, 80, 40, 27.5, "首页"),
            _element(500, 30, 80, 40, 27.5, "创作", weight="bold"),
            _element(700, 30, 80, 40, 27.5, "价格", weight=300),
            _element(900, 30, 80, 40, 27.5, "社区"),
        ]
    )
    calibrated, report = apply_nav_row_weight(design)
    assert report["adjusted_count"] == 2
    weights = _weights(calibrated)
    assert weights["创作"] == "bold"
    assert weights["价格"] == 300


def test_long_texts_are_not_labels() -> None:
    """A sentence in the header band is a title, not a menu item."""
    design = _design(
        [
            _element(300, 30, 80, 40, 27.5, "首页"),
            _element(500, 30, 80, 40, 27.5, "价格"),
            _element(700, 30, 300, 40, 27.5, "官方价、社区价和来源，一行看全。峰谷、分档都写明白"),
        ]
    )
    _calibrated, report = apply_nav_row_weight(design)
    assert report["adjusted_count"] == 0


def test_band_and_member_count_are_configurable() -> None:
    design = _design(
        [
            _element(300, 500, 80, 40, 27.5, "首页"),
            _element(500, 500, 80, 40, 27.5, "价格"),
            _element(700, 500, 80, 40, 27.5, "社区"),
        ]
    )
    _calibrated, report = apply_nav_row_weight(design, top_band_ratio=0.5)
    assert report["adjusted_count"] == 3
