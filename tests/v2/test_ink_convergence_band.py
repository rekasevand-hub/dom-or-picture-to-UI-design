"""Ink convergence: the band and the clamp are load-bearing, not incidental.

Both were challenged on 2026-11-10 and both were reinstated by measurement:
tightening the band to 1 +/- 0.05 moved dark's font_ratio only 0.906 -> 0.919
and regressed light-table 94.07 -> 93.33; dropping the clamp (treating 0.7/1.5
ratios as measurement failures) regressed light-table further to 93.44.  These
tests pin the behaviour that survived, so a future "cleanup" has to argue with
the numbers.
"""

from __future__ import annotations

import numpy as np

from src.app.services.structure.fidelity.text_calibration import (
    calibrate_ink_convergence_from_render,
)

BACKGROUND = 255
INK = 20


def _bar_image(path, height: int, *, width: int = 60, top: int = 20) -> list[int]:
    """One solid bar; returns the tight bbox the loop is expected to measure."""
    from PIL import Image

    canvas = np.full((120, 160), BACKGROUND, dtype=np.uint8)
    canvas[top : top + height, 20 : 20 + width] = INK
    Image.fromarray(canvas).save(path)
    return [20, top, width, height]


def _design(size: float, ink_bbox: list[int], text: str = "样例") -> dict:
    return {
        "canvas": {"width": 160, "height": 120},
        "elements": [
            {
                "type": "text",
                "text": text,
                "contentRef": "text:demo",
                "x": ink_bbox[0],
                "y": ink_bbox[1],
                "style": {"fontSize": size},
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


def test_matched_owner_is_untouched(tmp_path) -> None:
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _bar_image(reference, 20)
    _bar_image(rendered, 20)

    calibrated, report = calibrate_ink_convergence_from_render(
        _design(20.0, bbox), str(reference), str(rendered), _readback(bbox)
    )

    assert report["adjusted_count"] == 0
    assert report["skipped_count"] == 1
    assert calibrated["elements"][0]["style"]["fontSize"] == 20.0


def test_ten_percent_deficit_is_inside_the_band(tmp_path) -> None:
    """0.91 ink is deliberately tolerated: it is font metrics, not size.

    Chasing it cost light-table 0.6 pp of within30, so the band stays.
    """
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _bar_image(reference, 20)
    _bar_image(rendered, 22)

    calibrated, report = calibrate_ink_convergence_from_render(
        _design(20.0, bbox), str(reference), str(rendered), _readback(bbox)
    )

    assert report["adjusted_count"] == 0
    assert calibrated["elements"][0]["style"]["fontSize"] == 20.0


def test_large_deficit_is_corrected(tmp_path) -> None:
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _bar_image(reference, 20)
    _bar_image(rendered, 24)

    calibrated, report = calibrate_ink_convergence_from_render(
        _design(20.0, bbox), str(reference), str(rendered), _readback(bbox)
    )

    assert report["adjusted_count"] == 1
    assert report["adjustments"][0]["ratio"] == 0.833
    assert calibrated["elements"][0]["style"]["fontSize"] == 16.75


def test_extreme_ratio_is_clamped_not_dropped(tmp_path) -> None:
    """The 0.7 / 1.5 clamp edits were correcting genuinely oversized text."""
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _bar_image(reference, 8)
    _bar_image(rendered, 40)

    calibrated, report = calibrate_ink_convergence_from_render(
        _design(20.0, bbox), str(reference), str(rendered), _readback(bbox)
    )

    assert report["adjusted_count"] == 1
    assert report["adjustments"][0]["ratio"] == 0.7
    assert calibrated["elements"][0]["style"]["fontSize"] == 14.0


def test_unmatched_text_is_counted_not_applied(tmp_path) -> None:
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _bar_image(reference, 20)
    _bar_image(rendered, 24)

    calibrated, report = calibrate_ink_convergence_from_render(
        _design(20.0, bbox, text="源里的字"),
        str(reference),
        str(rendered),
        _readback(bbox, text="渲染里的字"),
    )

    assert report["adjusted_count"] == 0
    assert report["unmatched_count"] == 1
    assert calibrated["elements"][0]["style"]["fontSize"] == 20.0
