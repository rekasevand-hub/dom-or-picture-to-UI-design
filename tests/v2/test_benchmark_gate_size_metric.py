# -*- coding: utf-8 -*-
"""Gate behaviour for the size-metric scope change (2026-11-10).

The change under test:

* ``ink_ratio_median`` (rendered ink height / source ink height, same gold box)
  is the primary size metric;
* ``font_ratio_median`` is diagnostic only -- it divides two *declared* sizes
  from possibly different font families, so it must not fail a run;
* a family whose gold geometry cannot support the measurement opts out, and so
  does any family with too few measurable pairs.
"""
from __future__ import annotations

import numpy as np

from scripts.check_benchmark_families import (
    INK_RATIO_MIN_PAIRS,
    _gate,
    _ink_ratio_metrics,
    _size_metrics_scope,
)

BACKGROUND = 255
INK = 20


def _bar(size: tuple[int, int], top: int, height: int, width: int = 8) -> np.ndarray:
    """White canvas with a single dark bar -- a stand-in for one text line."""
    canvas = np.full((size[1], size[0], 3), BACKGROUND, dtype=np.int16)
    canvas[top : top + height, 20 : 20 + width] = INK
    return canvas


def _current(**overrides) -> dict:
    """A passing family measurement; overrides patch one metric."""
    base = {
        "visual": {"within30_pct": 94.0},
        "answer_key": {
            "font_ratio_median": 1.0,
            "ink_ratio_median": 1.0,
            "ink_ratio_pairs": 40,
            "dy_median": 1.0,
            "style_mismatches": 0,
            "style_compared": 10,
        },
        "structure": {"total_nodes": 100, "max_depth": 1, "image_fill_count": 3},
        "critical": {"matched": 20, "required": 20},
    }
    for key, value in overrides.items():
        if key == "answer_key":
            base["answer_key"].update(value)
        elif key == "structure":
            base["structure"].update(value)
        else:
            base[key] = value
    return base


def _baseline() -> dict:
    return {
        "within30_pct": 94.0,
        "font_ratio_median": 1.0,
        "ink_ratio_median": 1.0,
        "dy_median": 1.0,
        "critical": {"matched": 20},
        "structure": {"image_fill_count": 3, "max_depth": 1},
    }


# --------------------------------------------------------------------------- #
# ink metric itself
# --------------------------------------------------------------------------- #


def test_ink_ratio_is_rendered_over_source_height() -> None:
    source = _bar((80, 60), top=15, height=20)
    rendered = _bar((80, 60), top=15, height=10)
    metrics = _ink_ratio_metrics(
        [{"bbox": [18, 12, 20, 26]}], source, rendered
    )
    assert metrics["ink_ratio_pairs"] == 1
    assert metrics["ink_ratio_median"] == 0.5


def test_ink_ratio_skips_boxes_without_enough_ink() -> None:
    """< 3 px of ink is quantisation, not a measurement."""
    source = _bar((80, 60), top=15, height=20)
    rendered = _bar((80, 60), top=15, height=20)
    metrics = _ink_ratio_metrics(
        [{"bbox": [18, 12, 20, 26]}], source, rendered
    )
    assert metrics["ink_ratio_pairs"] == 1
    empty = _ink_ratio_metrics([{"bbox": [0, 0, 2, 2]}], source, rendered)
    assert empty["ink_ratio_pairs"] == 0
    assert empty["ink_ratio_median"] is None


def test_ink_ratio_reports_within_ten_percent_share() -> None:
    source = _bar((120, 60), top=15, height=20)
    rendered = _bar((120, 60), top=15, height=21)
    metrics = _ink_ratio_metrics([{"bbox": [18, 12, 16, 28]}], source, rendered)
    assert metrics["ink_ratio_within10pct"] == 1.0


# --------------------------------------------------------------------------- #
# evaluability
# --------------------------------------------------------------------------- #


def test_family_can_declare_size_metrics_not_evaluable() -> None:
    meta = {"size_metrics": {"evaluable": False, "reason": "gold geometry"}}
    evaluable, reason = _size_metrics_scope({"ink_ratio_pairs": 40}, meta)
    assert evaluable is False
    assert reason == "gold geometry"


def test_too_few_pairs_opts_out_even_without_a_declaration() -> None:
    evaluable, reason = _size_metrics_scope(
        {"ink_ratio_pairs": INK_RATIO_MIN_PAIRS - 1}, None
    )
    assert evaluable is False
    assert "measurable pairs" in reason


def test_enough_pairs_is_evaluable() -> None:
    evaluable, reason = _size_metrics_scope({"ink_ratio_pairs": 40}, {})
    assert evaluable is True
    assert reason is None


# --------------------------------------------------------------------------- #
# gate decisions
# --------------------------------------------------------------------------- #


def test_font_ratio_drift_alone_does_not_fail_the_gate() -> None:
    """18 % off on the declared-size quotient is a font metric, not a size error."""
    regressions, notes = _gate(
        "dark-card-grid", _current(answer_key={"font_ratio_median": 1.18}), _baseline()
    )
    assert regressions == []
    assert any("font_ratio drift" in note for note in notes)


def test_ink_ratio_drift_beyond_slack_fails_the_gate() -> None:
    regressions, _notes = _gate(
        "dark-card-grid", _current(answer_key={"ink_ratio_median": 1.20}), _baseline()
    )
    assert len(regressions) == 1
    assert "ink_ratio" in regressions[0]


def test_ink_ratio_improvement_passes() -> None:
    baseline = _baseline()
    baseline["ink_ratio_median"] = 0.95
    regressions, _notes = _gate(
        "dark-card-grid", _current(answer_key={"ink_ratio_median": 1.0}), baseline
    )
    assert regressions == []


def test_not_evaluable_family_skips_both_size_checks() -> None:
    """light-table shape: a wild ink ratio must be reported, not failed."""
    meta = {"size_metrics": {"evaluable": False, "reason": "gold geometry"}}
    regressions, notes = _gate(
        "light-table",
        _current(answer_key={"ink_ratio_median": 0.60, "ink_ratio_pairs": 11}),
        _baseline(),
        meta,
    )
    assert regressions == []
    assert any("not evaluated" in note for note in notes)


def test_pixel_regression_still_fails_independently_of_size_scope() -> None:
    regressions, _notes = _gate(
        "light-form", _current(visual={"within30_pct": 91.0}), _baseline()
    )
    assert len(regressions) == 1
    assert "within30" in regressions[0]


def test_missing_ink_baseline_is_a_note_not_a_failure() -> None:
    baseline = _baseline()
    del baseline["ink_ratio_median"]
    regressions, notes = _gate("light-form", _current(), baseline)
    assert regressions == []
    assert any("no baseline" in note for note in notes)


def test_slack_boundary_is_inclusive() -> None:
    """A value exactly 0.05 away must pass -- floats would otherwise fail it.

    ``abs(0.95 - 1.0)`` is ``0.050000000000000044`` in binary floating point, so
    a strict ``>`` makes the documented "may drift 0.05" exclusive at the exact
    boundary.  Both edges are checked, because the bug is asymmetric in
    practice: 0.95 lands just above, 1.05 just below.
    """
    for value in (0.95, 1.05):
        regressions, _notes = _gate(
            "light-form", _current(answer_key={"ink_ratio_median": value}), _baseline()
        )
        assert regressions == [], f"{value} should sit inside the 0.05 slack"


def test_slack_boundary_plus_one_step_still_fails() -> None:
    """The epsilon must not swallow a real regression."""
    regressions, _notes = _gate(
        "light-form", _current(answer_key={"ink_ratio_median": 0.949}), _baseline()
    )
    assert len(regressions) == 1
