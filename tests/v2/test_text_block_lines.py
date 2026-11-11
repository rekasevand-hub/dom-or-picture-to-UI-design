"""Line splitting for a tilted text block.

The numbers in ``test_real_badge_geometry`` are the ones measured on
dark-card-grid: the two bands come back at 89x47 and 30x29, against gold nodes
``5.8`` (62 pt, 95x70) and ``折`` (30 pt, 30x34).
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
    measure_text_block_lines,
)

BACKGROUND = (26, 25, 23)
ACCENT = (240, 89, 67)


def _block(degrees: float, *, lines: int = 2) -> np.ndarray:
    """A two-line block (wide line above, narrow below), rotated."""
    patch = Image.new("RGB", (240, 180), BACKGROUND)
    draw = ImageDraw.Draw(patch)
    draw.rectangle((60, 60, 180, 92), fill=ACCENT)
    if lines > 1:
        draw.rectangle((60, 112, 104, 144), fill=ACCENT)
    return np.asarray(
        patch.rotate(degrees, resample=Image.BICUBIC, fillcolor=BACKGROUND)
    ).astype(np.int16)


def _box() -> list[int]:
    return [40, 40, 180, 130]


def test_tilted_block_splits_into_two_lines() -> None:
    measured = measure_text_block_lines(_block(6.0), _box())

    assert measured is not None
    assert measured["line_count"] == 2
    # A tilted block measured without levelling reports one band, which is the
    # whole reason this function deskews first.
    first, second = measured["bands"]
    assert first["width"] > second["width"]
    assert first["height"] >= 20 and second["height"] >= 20


def test_tilt_is_measured_when_not_supplied() -> None:
    measured = measure_text_block_lines(_block(6.0), _box())

    assert measured is not None
    assert abs(measured["tilt"] - 6.0) <= 1.0


def test_upright_single_line_stays_one_line() -> None:
    patch = Image.new("RGB", (240, 180), BACKGROUND)
    ImageDraw.Draw(patch).rectangle((60, 80, 190, 112), fill=ACCENT)
    upright = np.asarray(patch).astype(np.int16)

    measured = measure_text_block_lines(upright, [40, 60, 180, 70])

    assert measured is not None
    assert measured["line_count"] == 1
    assert measured["tilt"] == 0.0


def test_block_box_wraps_every_band() -> None:
    measured = measure_text_block_lines(_block(6.0), _box())

    assert measured is not None
    block = measured["block"]
    for band in measured["bands"]:
        assert band["top"] >= block["top"]
        assert band["left"] >= block["left"]
        assert band["top"] + band["height"] <= block["top"] + block["height"]
        assert band["left"] + band["width"] <= block["left"] + block["width"]


def test_blank_box_is_not_measurable() -> None:
    blank = np.tile(np.array(BACKGROUND, dtype=np.int16), (120, 160, 1))

    assert measure_text_block_lines(blank, [10, 10, 120, 80]) is None
