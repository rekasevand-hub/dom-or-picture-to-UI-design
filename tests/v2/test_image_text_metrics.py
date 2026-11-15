"""The text metric calibrator, measured against pictures it cannot cheat.

Each test paints a stand-in for a line of type — solid blocks on a flat page —
so that the expected ink bounds are arithmetic rather than a rendering.  What is
being tested is the decision: which boxes are measured, what shift and scale are
derived, and which boxes are left alone because the window was ambiguous.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.app.services.structure.fidelity.text_metrics import (
    BASELINE_EM,
    DEFAULT_INK_EM,
    calibrate_arrays,
)


def _page(width: int = 400, height: int = 120) -> np.ndarray:
    return np.full((height, width, 3), 255, dtype=np.int16)


def _blocks(page: np.ndarray, left: int, top: int, widths, height: int) -> None:
    """Paint a line of "glyphs": blocks separated by one-pixel gaps."""
    x = left
    for width in widths:
        page[top : top + height, x : x + width, :] = 0
        x += width + 2


def _text(x: float, y: float, width: float, height: float, text: str = "标题", **style):
    return {
        "id": f"text:{text}",
        "type": "text",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "text": text,
        "style": {"fontSize": style.pop("fontSize", 20), **style},
    }


def test_a_label_that_sits_left_of_its_ink_is_moved_right() -> None:
    truth = _page()
    drawn = _page()
    _blocks(truth, 100, 40, (20, 20, 20, 20), 20)
    _blocks(drawn, 96, 40, (20, 20, 20, 20), 20)

    element = _text(96, 40, 86, 20)
    report = calibrate_arrays([element], truth, drawn)

    assert report.corrected == 1
    correction = report.corrections[0]
    assert correction.dx == pytest.approx(4.0)
    assert correction.dy == pytest.approx(0.0)
    assert element["x"] == pytest.approx(100.0)


def test_a_line_that_is_narrow_and_short_is_scaled_up() -> None:
    truth = _page()
    drawn = _page()
    _blocks(truth, 100, 40, (24, 24, 24, 24), 24)
    _blocks(drawn, 100, 42, (21, 21, 21, 21), 21)

    element = _text(100, 40, 102, 22, fontSize=20)
    report = calibrate_arrays([element], truth, drawn)

    correction = report.corrections[0]
    # 24/21 tall and 102/90 wide, weighted 0.7 height + 0.3 width.
    assert correction.scale == pytest.approx(0.7 * 24 / 21 + 0.3 * 102 / 90, abs=0.01)
    assert element["style"]["fontSize"] > 20


def test_a_size_change_that_width_and_height_disagree_on_is_not_made() -> None:
    truth = _page()
    drawn = _page()
    # Same height, much wider: that is tracking, not type size.  The 3px shift
    # is still measured, so the box moves even though the type does not.
    _blocks(truth, 103, 40, (26, 26, 26, 26), 20)
    _blocks(drawn, 100, 40, (18, 18, 18, 18), 20)

    element = _text(100, 40, 110, 20, fontSize=20)
    report = calibrate_arrays([element], truth, drawn)

    assert element["style"]["fontSize"] == 20
    assert element["x"] == pytest.approx(103.0)
    assert report.partial.get("width-height-disagree") == 1


def test_a_neighbour_welded_to_the_box_is_left_alone() -> None:
    truth = _page()
    drawn = _page()
    _blocks(truth, 100, 40, (20, 20, 20, 20), 20)
    _blocks(drawn, 96, 40, (20, 20, 20, 20), 20)
    # One pixel past the box's right edge: no window narrow enough to exclude it
    # without cutting the box's own ink, so the box is not measured at all.
    _blocks(truth, 227, 40, (20,), 20)
    _blocks(drawn, 223, 40, (20,), 20)

    element = _text(96, 40, 130, 20)
    report = calibrate_arrays([element], truth, drawn)

    assert report.corrected == 0
    assert report.skipped.get("ink-touches-edge")


def test_a_filled_surface_is_not_a_line_of_words() -> None:
    truth = _page()
    drawn = _page()
    truth[20:100, 60:340, :] = 40
    drawn[20:100, 60:340, :] = 40

    element = _text(60, 20, 280, 80)
    report = calibrate_arrays([element], truth, drawn)

    assert report.corrected == 0
    assert report.skipped.get("filled-surface") == 1


def test_a_paragraph_is_shifted_but_never_resized() -> None:
    truth = _page(height=160)
    drawn = _page(height=160)
    # Two lines, same count on both sides, one 3px to the left.
    _blocks(truth, 100, 40, (30, 30, 30), 16)
    _blocks(truth, 100, 62, (30, 30, 30), 16)
    _blocks(drawn, 97, 40, (30, 30, 30), 16)
    _blocks(drawn, 97, 62, (30, 30, 30), 16)

    element = _text(97, 40, 120, 40)
    report = calibrate_arrays([element], truth, drawn)

    correction = report.corrections[0]
    assert correction.dx == pytest.approx(3.0)
    assert correction.dy == 0.0
    assert correction.scale == 1.0


def test_the_calibration_never_adds_or_drops_a_text() -> None:
    truth = _page()
    drawn = _page()
    _blocks(truth, 100, 40, (20, 20, 20), 20)
    _blocks(drawn, 96, 40, (20, 20, 20), 20)

    elements = [_text(96, 40, 68, 20, text="第一处"), _text(200, 40, 60, 20, text="第二处")]
    before = [(element["type"], element["text"]) for element in elements]
    calibrate_arrays(elements, truth, drawn)

    assert [(element["type"], element["text"]) for element in elements] == before
    assert len(elements) == 2


def test_a_box_without_ink_is_skipped_rather_than_invented() -> None:
    truth = _page()
    drawn = _page()

    element = _text(100, 40, 80, 20)
    report = calibrate_arrays([element], truth, drawn)

    assert report.corrected == 0
    assert report.skipped.get("no-ink") == 1
    assert element["x"] == 100


def test_the_baseline_compensation_uses_the_measured_em() -> None:
    """A learned ink-em below the adapter's 0.375em moves the box the other way."""
    truth = _page()
    drawn = _page()
    _blocks(truth, 100, 40, (24, 24, 24, 24), 24)
    _blocks(drawn, 100, 42, (21, 21, 21, 21), 21)

    element = _text(100, 40, 102, 22, fontSize=20)
    report = calibrate_arrays([element], truth, drawn)

    assert report.ink_em != DEFAULT_INK_EM  # learned from this render
    delta = element["style"]["fontSize"] - 20
    expected = 40 + correction_dy(report) + (report.ink_em - BASELINE_EM) * delta
    assert element["y"] == pytest.approx(expected, abs=0.2)


def correction_dy(report) -> float:
    return report.corrections[0].dy
