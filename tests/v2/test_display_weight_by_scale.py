"""Display-scale weight: the page's own type scale decides the hierarchy.

This is the structural rule that replaced both pixel routes (static stroke
index, rendered-vs-source ink density).  It must stay purely structural: no
text matching, no per-sample constants, and no overriding a deliberate Light
decision made by another strategy.
"""

from __future__ import annotations

from src.app.services.structure.fidelity.text_calibration import (
    apply_display_weight_by_scale,
)


def _element(size: float, weight: object = "normal", **extra) -> dict:
    element = {
        "type": "text",
        "text": f"t{size}",
        "contentRef": f"text:{int(size * 10)}",
        "style": {"fontSize": size, "fontWeight": weight},
    }
    element.update(extra)
    return element


def _design(elements: list[dict]) -> dict:
    return {"canvas": {"width": 800, "height": 600}, "elements": elements}


def test_promotes_display_scale_to_bold() -> None:
    design = _design(
        [_element(16) for _ in range(6)] + [_element(40), _element(46)]
    )
    calibrated, report = apply_display_weight_by_scale(design)

    assert report["body_size"] == 16
    assert report["adjusted_count"] == 2
    weights = [
        element["style"]["fontWeight"]
        for element in calibrated["elements"]
        if element["style"]["fontSize"] > 16
    ]
    assert weights == [700, 700]
    assert {a["previous"] for a in report["adjustments"]} == {400}
    # The body copies stay Regular and the input design is untouched.
    assert all(
        element["style"]["fontWeight"] == "normal"
        for element in calibrated["elements"][:6]
    )
    assert design["elements"][6]["style"]["fontWeight"] == "normal"


def test_near_body_sizes_are_left_alone() -> None:
    """Heading-adjacent sizes are ambiguous; only display scale is promoted."""
    design = _design(
        [_element(16) for _ in range(6)] + [_element(20), _element(24), _element(28)]
    )
    _calibrated, report = apply_display_weight_by_scale(design)
    assert report["adjusted_count"] == 0


def test_explicit_light_is_never_overridden() -> None:
    design = _design([_element(16) for _ in range(6)] + [_element(40, weight=300)])
    calibrated, report = apply_display_weight_by_scale(design)
    assert report["adjusted_count"] == 0
    assert calibrated["elements"][-1]["style"]["fontWeight"] == 300


def test_already_bold_is_idempotent() -> None:
    design = _design([_element(16) for _ in range(6)] + [_element(40, weight="bold")])
    _calibrated, report = apply_display_weight_by_scale(design)
    assert report["adjusted_count"] == 0


def test_table_headers_keep_their_own_rule() -> None:
    header = _element(40, contentRef="table-header:t1:c1")
    design = _design([_element(16) for _ in range(6)] + [header])
    _calibrated, report = apply_display_weight_by_scale(design)
    assert report["adjusted_count"] == 0


def test_too_few_sizes_is_not_needed() -> None:
    design = _design([_element(16), _element(40)])
    _calibrated, report = apply_display_weight_by_scale(design)
    assert report["status"] == "not-needed"
    assert report["adjusted_count"] == 0


def test_threshold_is_configurable_for_experiments() -> None:
    design = _design([_element(16) for _ in range(6)] + [_element(24)])
    _calibrated, report = apply_display_weight_by_scale(design, display_threshold=1.4)
    assert report["adjusted_count"] == 1


def test_table_cells_are_never_promoted() -> None:
    """light-table shape: a cell's fontSize is inflated from the input box.

    ``(选填)`` / ``请输入0~`` measured at 48.5-78.75 pt inside 26 px boxes; the
    role, not the number, is what disqualifies them.
    """
    cell = _element(
        48.5,
        contentRef="table-cell:abc",
        imageMVP={"role": "table-cell", "candidate_type": "text"},
    )
    design = _design([_element(16) for _ in range(6)] + [cell])
    _calibrated, report = apply_display_weight_by_scale(design)
    assert report["adjusted_count"] == 0
    assert report["skipped_non_free_text"] == 1


def test_control_owned_text_is_never_promoted() -> None:
    control = _element(
        48.5, contentRef="text:ctl", imageMVP={"role": "control", "candidate_type": "text"}
    )
    design = _design([_element(16) for _ in range(6)] + [control])
    _calibrated, report = apply_display_weight_by_scale(design)
    assert report["adjusted_count"] == 0
