"""Font-metric evidence: the helpers that decide what the numbers mean.

The script itself renders through Chromium, so these cover the parts that can
go wrong silently: measuring ink relative to its box (an absolute coordinate
made this metric read 2810 %), aligning a sample to the gold's sizes before
comparing fonts, and reading a numeric weight in the mock.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT, ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from p1_source_font_metrics import _align_to_gold, _ink_metrics, _score  # noqa: E402
from src.app.services.rendering.svg_adapter import _font_weight  # noqa: E402

BACKGROUND = (26, 25, 23)
ACCENT = (240, 89, 67)


def _canvas(box: tuple[int, int, int, int]) -> np.ndarray:
    """Dark canvas with one accent block at ``box``."""
    image = np.full((200, 200, 3), BACKGROUND, dtype=np.int16)
    left, top, right, bottom = box
    image[top:bottom, left:right] = ACCENT
    return image


def test_ink_is_reported_relative_to_the_box() -> None:
    image = _canvas((60, 60, 90, 80))
    # The box is offset from the ink, so an absolute reading would say 60/60.
    measured = _ink_metrics(image, [40, 40, 80, 60], inset=0)

    assert measured is not None
    assert (measured["left"], measured["top"]) == (20, 20)
    assert (measured["width"], measured["height"]) == (30, 20)
    assert measured["count"] == 30 * 20


def test_ink_ignores_a_candidate_that_is_outside_the_box() -> None:
    image = _canvas((150, 150, 190, 190))
    # Nothing inside the box: the metric has to say "no ink" rather than report
    # whatever else the canvas happens to hold.
    assert _ink_metrics(image, [10, 10, 40, 40], inset=0) is None


def test_score_is_zero_for_an_exact_match() -> None:
    source = {"top": 4, "left": 0, "width": 80, "height": 40, "count": 500}

    assert _score(source, dict(source)) == {
        "width": 0.0,
        "height": 0.0,
        "count": 0.0,
        "top": 0.0,
    }


def test_score_charges_every_metric() -> None:
    source = {"top": 4, "left": 0, "width": 80, "height": 40, "count": 500}
    candidate = {"top": 12, "left": 0, "width": 88, "height": 40, "count": 500}

    score = _score(source, candidate)

    assert score["width"] == 0.1
    assert score["height"] == 0.0
    assert score["top"] == 0.2


def test_alignment_takes_the_gold_sizes_not_the_design_ones() -> None:
    element = {
        "text": "5.8折",
        "lines": ["5.8", "折"],
        "lineSizes": [64, 30],
        "style": {"fontSize": 50.5, "lineHeight": 72},
    }
    faces = {"5.8": {"size": 62.0, "height": 70.0}, "折": {"size": 30.0, "height": 34.0}}

    assert _align_to_gold(element, faces) is True
    # The design says 64/50.5; the source's own typesetting says 62.
    assert element["lineSizes"] == [62, 30]
    assert element["style"]["fontSize"] == 62.0
    # Line boxes come from the gold's own height/size ratio (70/62, 34/30).
    assert element["lineHeight"] == 70


def test_alignment_is_refused_when_a_line_has_no_gold_node() -> None:
    element = {"text": "?", "lines": ["5.8", "?"], "lineSizes": [64, 30], "style": {}}

    assert _align_to_gold(element, {"5.8": {"size": 62.0, "height": 70.0}}) is False
    assert element["lineSizes"] == [64, 30], "a partial alignment would mix two scales"


def test_font_weight_reads_a_numeric_design_value() -> None:
    assert _font_weight({"fontWeight": 700}) == "700"
    assert _font_weight({"fontWeight": 500}) == "500"
    # Explicit value wins over the design's field, which is how a candidate is
    # rendered at a weight the design does not use.
    assert _font_weight({"fontWeight": 700, "fontWeightValue": 400}) == "400"
    assert _font_weight({"fontWeight": "bold"}) == "bold"
    assert _font_weight({}) is None
    assert _font_weight({"fontWeight": "semibold"}) is None
