"""Rotation measurement: read the tilt off pixels, and off the gold boxes.

Two independent pieces are pinned here:

* ``measure_element_rotation`` -- projection-profile deskew.  Synthetic bars
  are rotated by a known angle, so the assertion is on accuracy, not on a
  recorded number.
* ``solve_tilt`` -- the gold-tree oracle.  Figma reports a node's own size and
  its axis-aligned box; for a tilt ``t`` they differ by ``w·cos t + h·sin t``.
  The numbers in the last test are real: dark-card-grid's ``5.8`` node.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.structure.fidelity.text_calibration import (  # noqa: E402
    measure_element_rotation,
)

from scripts.p1_text_rotation_evidence import solve_tilt  # noqa: E402

BACKGROUND = (26, 25, 23)
ACCENT = (240, 89, 67)


def _tilted_lines(degrees: float, size: tuple[int, int] = (240, 180)) -> np.ndarray:
    """Three horizontal bars rotated by ``degrees`` counter-clockwise."""
    patch = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(patch)
    for top, bottom, left, right in (
        (60, 72, 40, 200),
        (88, 100, 40, 170),
        (116, 128, 40, 185),
    ):
        draw.rectangle((left, top, right, bottom), fill=ACCENT)
    rotated = patch.rotate(degrees, resample=Image.BICUBIC, fillcolor=BACKGROUND)
    return np.asarray(rotated).astype(np.int16)


def _box() -> list[int]:
    return [20, 40, 200, 110]


def test_tilt_is_recovered_in_both_directions() -> None:
    for degrees in (-7.0, -6.0, -3.0, 3.0, 4.0, 6.0):
        measured = measure_element_rotation(_tilted_lines(degrees), _box())
        assert measured is not None
        assert abs(measured["angle"] - degrees) <= 0.75, (degrees, measured)


def test_upright_text_stays_at_zero() -> None:
    measured = measure_element_rotation(_tilted_lines(0.0), _box())

    assert measured is not None
    # The raw angle may wobble by a degree from anti-aliasing; the dead zone is
    # what keeps that from rotating the page.
    assert abs(measured["raw"]) < 2.5
    assert measured["angle"] == 0.0


def test_sign_convention_is_counter_clockwise() -> None:
    # PIL rotates counter-clockwise for a positive angle, and so does Figma's
    # ``rotation`` property; the estimator has to agree with both or a wire-up
    # would flip every tilt.
    measured = measure_element_rotation(_tilted_lines(6.0), _box())

    assert measured is not None
    assert measured["angle"] > 0


def test_deskew_gain_grows_with_tilt() -> None:
    upright = measure_element_rotation(_tilted_lines(0.0), _box())
    tilted = measure_element_rotation(_tilted_lines(6.0), _box())

    assert upright is not None and tilted is not None
    # ``gain`` is the profile variance at the best angle over the variance at
    # zero: levelling a tilted block must find more structure, not less.
    assert tilted["gain"] > 1.1
    assert upright["gain"] <= 1.05


def test_empty_box_is_not_measurable() -> None:
    blank = np.tile(
        np.array(BACKGROUND, dtype=np.int16), (120, 160, 1)
    )

    assert measure_element_rotation(blank, [10, 10, 100, 60]) is None


def test_solve_tilt_matches_the_real_gold_node() -> None:
    # dark-card-grid `5.8`: own box 95x70, axis-aligned box 101.8x79.5.
    # The oracle lands at 5.97, not 6.00: the box it is fed is rounded to 0.1 px,
    # and that quantisation carries about 0.05 degrees.
    assert abs((solve_tilt(95, 70, 101.8, 79.5) or 0.0) - 6.0) <= 0.1


def test_solve_tilt_returns_none_for_an_upright_node() -> None:
    assert solve_tilt(120, 30, 120, 30) is None
