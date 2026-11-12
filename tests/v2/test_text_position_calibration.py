"""Text position: the element box is a layout box, the run is not.

On the content-review holdout the native gate fails twelve owners on
``position``, and the error splits in two clusters (``dx`` -5 on the left
column, +2 on the right).  The cause is not a missing padding constant: inside
one card the left slack of the grounding box runs 2, 4, 5, 6, 7 and 13 px.
These tests pin the per-element translation and the guards that keep the
window from latching onto a neighbour.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.app.services.structure.fidelity.text_calibration import (
    _text_run_box,
    _text_run_width,
    calibrate_text_positions_from_render,
)

BACKGROUND = 255
INK = 20


def _image(path, runs, *, width: int = 320, height: int = 120):
    """Paint solid blocks; each block stands in for one glyph run."""
    from PIL import Image

    canvas = np.full((height, width), BACKGROUND, dtype=np.uint8)
    for x, y, w, h in runs:
        canvas[y : y + h, x : x + w] = INK
    Image.fromarray(canvas).save(path)
    return path


def _design(
    box=(40, 30, 200, 20), *, size: float = 20, element_type: str = "text"
) -> dict:
    return {
        "canvas": {"width": 320, "height": 120},
        "elements": [
            {
                "type": element_type,
                "text": "样例标签",
                "contentRef": "text:demo",
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "style": {"fontSize": size},
            }
        ],
    }


def test_moves_the_run_onto_the_reference(tmp_path):
    reference = _image(tmp_path / "ref.png", [(46, 32, 60, 14)])
    rendered = _image(tmp_path / "cur.png", [(40, 32, 60, 14)])
    design = _design()

    calibrated, report = calibrate_text_positions_from_render(
        design, str(reference), str(rendered)
    )

    element = calibrated["elements"][0]
    assert (element["x"], element["y"]) == (46, 30)
    assert report["status"] == "applied"
    assert report["adjusted_count"] == 1
    # The input design is not mutated; the pipeline may keep the old frame.
    assert design["elements"][0]["x"] == 40


def test_moves_on_both_axes(tmp_path):
    reference = _image(tmp_path / "ref.png", [(46, 35, 60, 14)])
    rendered = _image(tmp_path / "cur.png", [(40, 31, 60, 14)])

    calibrated, _ = calibrate_text_positions_from_render(
        _design(), str(reference), str(rendered)
    )

    element = calibrated["elements"][0]
    assert (element["x"], element["y"]) == (46, 34)


def test_leaves_an_aligned_run_alone(tmp_path):
    reference = _image(tmp_path / "ref.png", [(46, 32, 60, 14)])
    rendered = _image(tmp_path / "cur.png", [(46, 32, 60, 14)])

    calibrated, report = calibrate_text_positions_from_render(
        _design(), str(reference), str(rendered)
    )

    assert calibrated["elements"][0]["x"] == 40
    assert report["status"] == "not-needed"
    assert report["adjusted_count"] == 0


def test_skips_a_run_narrower_than_a_glyph(tmp_path):
    # A 4 px speck at 20 pt is a stroke fragment or a rule, not a run.
    reference = _image(tmp_path / "ref.png", [(46, 32, 4, 14)])
    rendered = _image(tmp_path / "cur.png", [(40, 32, 60, 14)])

    calibrated, report = calibrate_text_positions_from_render(
        _design(), str(reference), str(rendered)
    )

    assert calibrated["elements"][0]["x"] == 40
    assert report["skipped"][0]["reason"] == "run-too-short"


def test_skips_when_the_heights_disagree(tmp_path):
    # Different line heights mean the two windows are not the same run.
    reference = _image(tmp_path / "ref.png", [(46, 28, 60, 26)])
    rendered = _image(tmp_path / "cur.png", [(40, 32, 60, 14)])

    calibrated, report = calibrate_text_positions_from_render(
        _design(), str(reference), str(rendered)
    )

    assert calibrated["elements"][0]["x"] == 40
    assert report["skipped"][0]["reason"] == "height-mismatch"


def test_skips_a_jump_beyond_three_quarters_of_an_em(tmp_path):
    # 60 px at 20 pt is three ems: the window found a neighbour.
    reference = _image(tmp_path / "ref.png", [(100, 32, 60, 14)])
    rendered = _image(tmp_path / "cur.png", [(40, 32, 60, 14)])

    calibrated, report = calibrate_text_positions_from_render(
        _design(), str(reference), str(rendered)
    )

    assert calibrated["elements"][0]["x"] == 40
    assert report["skipped"][0]["reason"] == "delta-too-large"


def test_skips_when_the_render_has_no_ink(tmp_path):
    reference = _image(tmp_path / "ref.png", [(46, 32, 60, 14)])
    rendered = _image(tmp_path / "cur.png", [])

    calibrated, report = calibrate_text_positions_from_render(
        _design(), str(reference), str(rendered)
    )

    assert calibrated["elements"][0]["x"] == 40
    assert report["skipped"][0]["reason"] == "no-run"


def test_ignores_shapes_that_only_carry_text(tmp_path):
    reference = _image(tmp_path / "ref.png", [(46, 32, 60, 14)])
    rendered = _image(tmp_path / "cur.png", [(40, 32, 60, 14)])

    calibrated, report = calibrate_text_positions_from_render(
        _design(element_type="rectangle"), str(reference), str(rendered)
    )

    assert calibrated["elements"][0]["x"] == 40
    assert report["adjusted_count"] == 0


def test_run_width_is_the_width_of_the_run_box(tmp_path):
    image = _image(tmp_path / "one.png", [(46, 32, 60, 14)])
    from PIL import Image

    gray = np.asarray(Image.open(image).convert("L"), dtype=np.int16)

    box = _text_run_box(gray, [40, 30, 200, 20], 20.0)

    assert box == (46, 32, 60, 14)
    assert _text_run_width(gray, [40, 30, 200, 20], 20.0) == box[2]


def test_a_neighbour_to_the_right_does_not_move_the_run(tmp_path):
    # The window reaches into the next column, as ``请求编号``'s cell does.
    reference = _image(tmp_path / "ref.png", [(46, 32, 60, 14), (200, 32, 60, 14)])
    rendered = _image(tmp_path / "cur.png", [(46, 32, 60, 14)])

    calibrated, report = calibrate_text_positions_from_render(
        _design(), str(reference), str(rendered)
    )

    assert report["adjusted_count"] == 0
    assert calibrated["elements"][0]["x"] == 40


@pytest.mark.parametrize("missing", ["reference", "rendered"])
def test_missing_image_is_an_error_not_a_silent_pass(tmp_path, missing):
    reference = _image(tmp_path / "ref.png", [(46, 32, 60, 14)])
    rendered = _image(tmp_path / "cur.png", [(40, 32, 60, 14)])
    target = tmp_path / "absent.png"

    with pytest.raises(OSError):
        if missing == "reference":
            calibrate_text_positions_from_render(_design(), str(target), str(rendered))
        else:
            calibrate_text_positions_from_render(_design(), str(reference), str(target))
