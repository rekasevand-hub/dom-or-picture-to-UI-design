"""Page-wide weight convergence: rendered density decides, not raw ink.

The strategy replaced a static source-side statistic because the Phase 1 probe
showed ``stroke/ink_height`` drifting ±55 % between gold and perception boxes.
These tests pin the three properties that make the render comparison safe:

* density (ink / ink-extent area) cancels font size, raw ink count does not --
  a 10 % size deficit already reads as a 20 % ink deficit;
* the ladder conversion may jump two steps in one pass (calibration runs once);
* guards (deadband, width mismatch, table headers) keep it from touching text
  whose residual belongs to another strategy.
"""

from __future__ import annotations

import numpy as np

from src.app.services.structure.fidelity.text_calibration import (
    _element_source_bbox,
    _ink_stats,
    _normalize_font_weight,
    _weight_for_ink_ratio,
    calibrate_text_weight_from_render,
)

LIGHT_BG = 255
DARK_BG = 18


def _write_text_image(
    path,
    *,
    span: int,
    strokes: int,
    stroke_width: int,
    height: int,
    background: int = LIGHT_BG,
    ink: int = 40,
    origin: tuple[int, int] = (10, 10),
    margin: int = 4,
) -> list[int]:
    """Draw ``strokes`` vertical bars spread across a fixed ``span``.

    The span is held constant on purpose: real text keeps its advance width
    when only the stroke thickens, and the strategy's width guard relies on
    that.  Bars are spread evenly so two images differing only in
    ``stroke_width`` stay pixel-aligned and share one bbox.

    Returns:
        The bbox ``[x, y, w, h]`` covering the drawn bars.
    """
    from PIL import Image

    width = origin[0] * 2 + span
    total_height = origin[1] * 2 + height
    canvas = np.full((total_height, width, 3), background, dtype=np.uint8)
    if strokes > 1:
        positions = np.linspace(0, span - stroke_width, strokes)
    else:
        positions = np.zeros(1)
    for value in positions:
        left = origin[0] + int(round(float(value)))
        canvas[origin[1] : origin[1] + height, left : left + stroke_width, :] = ink
    Image.fromarray(canvas).save(path)
    # Real owner boxes carry padding around the glyphs; the measurement insets
    # the box by 3 px, so the synthetic box needs a margin too.
    return [origin[0] - margin, origin[1] - margin, span + 2 * margin, height + 2 * margin]


def _design(bbox: list[float], weight: object = "normal", **extra) -> dict:
    element = {
        "type": "text",
        "text": "样例",
        "contentRef": "text:demo",
        "style": {"fontFamily": "Noto Sans SC", "fontSize": 20, "fontWeight": weight},
        "styleEvidence": {"evidence": {"source_bbox": bbox}},
    }
    element.update(extra)
    return {"canvas": {"width": 400, "height": 200}, "elements": [element]}


def test_normalize_weight_accepts_strings_and_numbers() -> None:
    assert _normalize_font_weight("normal") == 400
    assert _normalize_font_weight("bold") == 700
    assert _normalize_font_weight("700") == 700
    assert _normalize_font_weight(500) == 500
    assert _normalize_font_weight(450) == 400
    assert _normalize_font_weight("light") == 300
    assert _normalize_font_weight(None) is None
    assert _normalize_font_weight("") is None


def test_weight_for_ink_ratio_can_jump_two_steps() -> None:
    # rendered 10 % too light -> one step; 25 % too light -> two steps.
    assert _weight_for_ink_ratio(400, 0.90) == 500
    assert _weight_for_ink_ratio(400, 0.80) == 700
    assert _weight_for_ink_ratio(400, 1.0) == 400
    assert _weight_for_ink_ratio(700, 1.25) == 500
    assert _weight_for_ink_ratio(400, 1.25) == 300


def test_ink_stats_is_theme_agnostic(tmp_path) -> None:
    light = tmp_path / "light.png"
    dark = tmp_path / "dark.png"
    light_bbox = _write_text_image(light, span=58, strokes=3, stroke_width=2, height=20)
    _write_text_image(
        dark, span=58, strokes=3, stroke_width=2, height=20, background=DARK_BG, ink=235
    )
    from PIL import Image

    for path, expected_background in ((light, LIGHT_BG), (dark, DARK_BG)):
        del expected_background
        with Image.open(path) as image:
            array = np.asarray(image.convert("RGB"), dtype=np.int16)
        stats = _ink_stats(array, light_bbox, inset=0)
        assert stats is not None
        assert stats["count"] == 3 * 2 * 20
        assert stats["height"] == 20
        assert stats["width"] == 58
    assert _ink_stats(np.full((40, 40, 3), LIGHT_BG, dtype=np.int16), [5, 5, 20, 20]) is None


def test_element_bbox_prefers_style_evidence() -> None:
    element = {
        "x": 1,
        "y": 2,
        "width": 3,
        "height": 4,
        "styleEvidence": {"evidence": {"source_bbox": [10.0, 20.0, 30.0, 40.0]}},
    }
    assert _element_source_bbox(element) == [10.0, 20.0, 30.0, 40.0]
    assert _element_source_bbox({"x": 1, "y": 2, "width": 3, "height": 4}) == [
        1.0,
        2.0,
        3.0,
        4.0,
    ]
    assert _element_source_bbox({}) is None


def test_light_render_steps_weight_up(tmp_path) -> None:
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _write_text_image(reference, span=60, strokes=6, stroke_width=4, height=24)
    _write_text_image(rendered, span=60, strokes=6, stroke_width=3, height=24)
    design = _design(bbox)

    calibrated, report = calibrate_text_weight_from_render(
        design, str(reference), str(rendered)
    )

    assert report["adjusted_count"] == 1
    adjustment = report["adjustments"][0]
    assert adjustment["previous"] == 400
    assert adjustment["updated"] == 700  # 0.75 density ratio needs +1.33x ink
    assert calibrated["elements"][0]["style"]["fontWeight"] == 700
    # The input design is never mutated.
    assert design["elements"][0]["style"]["fontWeight"] == "normal"


def test_density_cancels_font_size(tmp_path) -> None:
    """Same stroke ratio, different glyph heights -> no weight change.

    Raw ink count would differ by 2x here and invent a weight error; density is
    the reason this strategy does not fight the size strategies.
    """
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _write_text_image(reference, span=60, strokes=5, stroke_width=3, height=32)
    _write_text_image(rendered, span=60, strokes=5, stroke_width=3, height=16)
    design = _design(bbox)

    _calibrated, report = calibrate_text_weight_from_render(
        design, str(reference), str(rendered)
    )

    assert report["status"] == "not-needed"
    assert report["skipped"]["width-mismatch"] == 0
    assert report["skipped"]["deadband"] == 1


def test_width_mismatch_is_left_to_the_size_strategies(tmp_path) -> None:
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _write_text_image(reference, span=60, strokes=4, stroke_width=2, height=20)
    _write_text_image(rendered, span=30, strokes=2, stroke_width=2, height=20)
    # The owner box is the source box, so the narrower render shows up as a
    # width mismatch -- exactly what the pipeline sees with a size error.
    design = _design(bbox)

    _calibrated, report = calibrate_text_weight_from_render(
        design, str(reference), str(rendered)
    )

    assert report["adjusted_count"] == 0
    assert report["skipped"]["width-mismatch"] == 1


def test_table_header_and_skipped_refs_are_untouched(tmp_path) -> None:
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _write_text_image(reference, span=60, strokes=6, stroke_width=4, height=24)
    _write_text_image(rendered, span=60, strokes=6, stroke_width=2, height=24)
    design = {
        "canvas": {"width": 400, "height": 200},
        "elements": [
            {
                "type": "text",
                "text": "表头",
                "contentRef": "table-header:t1:c1",
                "style": {"fontWeight": "bold"},
                "styleEvidence": {"evidence": {"source_bbox": bbox}},
            },
            {
                "type": "text",
                "text": "表单",
                "contentRef": "text:form",
                "style": {"fontWeight": "normal"},
                "styleEvidence": {"evidence": {"source_bbox": bbox}},
            },
        ],
    }

    _calibrated, report = calibrate_text_weight_from_render(
        design, str(reference), str(rendered), skip_content_refs={"text:form"}
    )

    assert report["adjusted_count"] == 0
    assert report["skipped"]["unmeasurable"] == 0


def test_deadband_keeps_small_differences(tmp_path) -> None:
    reference = tmp_path / "ref.png"
    rendered = tmp_path / "render.png"
    bbox = _write_text_image(reference, span=60, strokes=6, stroke_width=4, height=24)
    _write_text_image(rendered, span=60, strokes=6, stroke_width=4, height=24)
    design = _design(bbox)

    _calibrated, report = calibrate_text_weight_from_render(
        design, str(reference), str(rendered)
    )

    assert report["status"] == "not-needed"
    assert report["skipped"]["deadband"] == 1
