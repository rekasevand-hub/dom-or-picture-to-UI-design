"""The pixel score has to separate "redrawn" from "pasted".

light-form carries 28-32 pasted crops out of 149 nodes, light-table 12 of 166,
dark 1 of 68. Put those within30 numbers in one table and the family that
pastes more simply scores higher. `native_only` re-scores the same pair with
every bitmap region removed from both numerator and denominator -- as a
diagnostic, never as a gate.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.app.services.evidence.image_figma_acceptance import (
    bitmap_regions,
    native_only_visual_metrics,
    visual_similarity_metrics,
)


def _image(path, blocks, *, size=(60, 60)):
    """``blocks`` maps (x0, y0, x1, y1) -> colour triple."""
    from PIL import Image

    canvas = np.full((size[1], size[0], 3), 255, dtype=np.uint8)
    for (x0, y0, x1, y1), colour in blocks.items():
        canvas[y0:y1, x0:x1] = colour
    Image.fromarray(canvas).save(path)
    return path


def test_a_pasted_region_no_longer_counts(tmp_path):
    reference = _image(tmp_path / "ref.png", {(0, 0, 30, 60): (0, 0, 0)})
    render = _image(tmp_path / "out.png", {})

    full = visual_similarity_metrics(reference, render)
    native = native_only_visual_metrics(reference, render, [(0, 0, 30, 60)])

    assert full["within30_pct"] == pytest.approx(50.0, abs=0.5)
    assert native["within30_pct"] == pytest.approx(100.0)
    assert native["covered_pixel_ratio"] == pytest.approx(0.5)
    assert native["scored_pixel_ratio"] == pytest.approx(0.5)


def test_without_regions_it_equals_the_product_metric(tmp_path):
    reference = _image(tmp_path / "ref.png", {(0, 0, 10, 10): (10, 10, 10)})
    render = _image(tmp_path / "out.png", {(0, 0, 10, 10): (200, 200, 200)})

    full = visual_similarity_metrics(reference, render)
    native = native_only_visual_metrics(reference, render, [])

    assert native["within30_pct"] == pytest.approx(full["within30_pct"])
    assert native["region_count"] == 0


def test_a_region_that_hangs_off_the_canvas_is_clipped(tmp_path):
    reference = _image(tmp_path / "ref.png", {})
    render = _image(tmp_path / "out.png", {})

    native = native_only_visual_metrics(reference, render, [(-10, -10, 40, 40)])

    assert native["status"] == "measured"
    assert native["regions_outside_canvas"] == 0
    assert native["scored_pixel_ratio"] < 1.0


def test_a_fully_covered_page_is_not_scored(tmp_path):
    reference = _image(tmp_path / "ref.png", {})
    render = _image(tmp_path / "out.png", {})

    native = native_only_visual_metrics(reference, render, [(0, 0, 60, 60)])

    assert native["status"] == "not-evaluated"
    assert native["reason"] == "no-uncovered-pixels"


def test_regions_come_from_image_fills_not_from_names():
    tree = {
        "type": "FRAME",
        "absolute": {"x": 22000, "y": 100, "width": 200, "height": 200},
        "children": [
            {
                "type": "RECTANGLE",
                "name": "logo crop",
                "absolute": {"x": 22010, "y": 130, "width": 40, "height": 20},
                "fills": [{"type": "IMAGE", "visible": True}],
            },
            {
                "type": "RECTANGLE",
                "name": "card",
                "absolute": {"x": 22000, "y": 100, "width": 200, "height": 200},
                "fills": [{"type": "SOLID", "color": "#ffffff", "visible": True}],
            },
            {
                "type": "RECTANGLE",
                "name": "hidden crop",
                "absolute": {"x": 22050, "y": 150, "width": 10, "height": 10},
                "fills": [{"type": "IMAGE", "visible": False}],
            },
        ],
    }

    assert bitmap_regions(tree) == [(10, 30, 40, 20)]
