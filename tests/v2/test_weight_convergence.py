"""Weight convergence: stroke thickness is a separate axis from font size.

The holdout's ``检查状态`` sits at the right size and position with coverage
0.50 and a stroke ratio of 1.43 -- the glyphs are half the weight, not half
the size.  These tests pin the meter (``2 * area / perimeter``), the
size-agreement guard, and the step mapping, so a later change has to argue
with the numbers instead of the picture.
"""

from __future__ import annotations

import numpy as np

from src.app.services.structure.fidelity.text_calibration import (
    calibrate_weight_from_render,
)

BACKGROUND = 255
INK = 20


def _frame_image(
    path, thickness: int, *, width: int = 60, height: int = 20, top: int = 20
):
    """Hollow rectangle: same box, different stroke thickness.

    A solid bar cannot be used -- making it thicker also makes it taller,
    which trips the size guard instead of the weight step.
    """
    from PIL import Image

    canvas = np.full((120, 160), BACKGROUND, dtype=np.uint8)
    canvas[top : top + height, 20 : 20 + width] = INK
    canvas[
        top + thickness : top + height - thickness,
        20 + thickness : 20 + width - thickness,
    ] = BACKGROUND
    Image.fromarray(canvas).save(path)
    return [20, top, width, height]


def _design(
    size: float, ink_bbox: list[int], *, weight=None, text: str = "样例"
) -> dict:
    style: dict = {"fontSize": size}
    if weight is not None:
        style["fontWeight"] = weight
    return {
        "canvas": {"width": 160, "height": 120},
        "elements": [
            {
                "type": "text",
                "text": text,
                "contentRef": "text:demo",
                "x": ink_bbox[0],
                "y": ink_bbox[1],
                "height": ink_bbox[3],
                "style": style,
                "styleEvidence": {"evidence": {"ink_bbox": ink_bbox}},
            }
        ],
    }


def _readback(bbox: list[int], text: str = "样例") -> dict:
    return {
        "type": "FRAME",
        "id": "1:1",
        "x": 0,
        "y": 0,
        "children": [
            {
                "type": "TEXT",
                "characters": text,
                "x": bbox[0],
                "y": bbox[1],
                "width": bbox[2],
                "height": bbox[3],
                "fontSize": 20,
            }
        ],
    }


def test_thicker_source_strokes_raise_the_weight(tmp_path) -> None:
    """A 3 px frame against a 2 px frame is 1.5x the stroke, not 1.5x the size.

    Below 2 px the proxy saturates -- a 1 px outline has no interior to erode,
    so its perimeter reads as its whole area and the quotient pins at 2.  Real
    text strokes on these pages are 2-3 px, so the usable range starts there.
    """
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _frame_image(reference, 3)
    _frame_image(rendered, 2)

    calibrated, report = calibrate_weight_from_render(
        _design(20.0, bbox), str(reference), str(rendered), _readback(bbox)
    )

    assert report["adjusted_count"] == 1
    row = report["adjustments"][0]
    assert row["from"] == 400
    assert row["to"] == 700
    assert 1.4 < row["stroke_ratio"] < 1.6
    assert calibrated["elements"][0]["style"]["fontWeight"] == 700


def test_same_stroke_is_left_alone(tmp_path) -> None:
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _frame_image(reference, 2)
    _frame_image(rendered, 2)

    calibrated, report = calibrate_weight_from_render(
        _design(20.0, bbox), str(reference), str(rendered), _readback(bbox)
    )

    assert report["adjusted_count"] == 0
    assert calibrated["elements"][0]["style"]["fontSize"] == 20.0


def test_a_size_mismatch_is_not_a_weight_problem(tmp_path) -> None:
    """When the heights disagree the run is the wrong size; weight would double-correct."""
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _frame_image(reference, 1, height=26)
    _frame_image(rendered, 2, height=20)

    calibrated, report = calibrate_weight_from_render(
        _design(20.0, bbox), str(reference), str(rendered), _readback([20, 20, 60, 20])
    )

    assert report["adjusted_count"] == 0
    assert "fontWeight" not in calibrated["elements"][0]["style"]


def test_an_already_bold_owner_is_capped_at_900(tmp_path) -> None:
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _frame_image(reference, 4)
    _frame_image(rendered, 2)

    calibrated, report = calibrate_weight_from_render(
        _design(20.0, bbox, weight=700),
        str(reference),
        str(rendered),
        _readback(bbox),
    )

    assert report["adjusted_count"] == 1
    assert calibrated["elements"][0]["style"]["fontWeight"] == 900


def test_latin_runs_step_one_class_at_a_time(tmp_path) -> None:
    """Bolding Latin widens it, and the width channel then calls it a size error.

    ``REQ-OIBFZVUES`` measured 140 px at 400 and 184 px at 800 against a
    172 px source: the extra weight overshot the box it had just been sized
    to.  A CJK run keeps its advance, so only Latin is capped.
    """
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _frame_image(reference, 4)
    _frame_image(rendered, 2)

    calibrated, report = calibrate_weight_from_render(
        _design(20.0, bbox, text="REQ-OIBFZVUES"),
        str(reference),
        str(rendered),
        _readback(bbox, text="REQ-OIBFZVUES"),
    )

    assert report["adjusted_count"] == 1
    assert calibrated["elements"][0]["style"]["fontWeight"] == 700
