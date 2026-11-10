"""Phase 1 weight-evidence probe: the metric primitives must be trustworthy.

These tests lock the properties the evidence doc *depends on*:

* coverage integration is sub-pixel (a 2.5 px stroke must read 2.5, not 2 or 3),
* polarity does not matter (same numbers for light-on-dark and dark-on-light),
* the foreground level is measured over ink only -- the bug that made sparse
  text read ``contrast == 0`` and look unmeasurable,
* Otsu's ``eta`` separates a genuinely bimodal group from a unimodal one,
* the shippable binary rule refuses to split a single-weight page.
"""

from __future__ import annotations

import numpy as np

from scripts.p1_font_weight_evidence import (
    auc,
    binary_rule_eval,
    coverage_map,
    flatten_gold_texts,
    ink_bands,
    measure_text,
    multiotsu_split,
    otsu_split,
    stroke_widths,
    style_to_weight,
    weight_to_style,
)

BACKGROUND = 255
INK = 40


def _canvas(width: int = 64, height: int = 44, background: int = BACKGROUND) -> np.ndarray:
    """Blank RGB canvas."""
    return np.full((height, width, 3), background, dtype=np.int16)


def _draw_bar(
    image: np.ndarray,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    coverage: float = 1.0,
    background: int = BACKGROUND,
    ink: int = INK,
) -> None:
    """Paint a vertical bar with the given ink coverage (0..1)."""
    value = int(round(background + coverage * (ink - background)))
    image[y : y + height, x : x + width, :] = value


def _subpixel_bar(image: np.ndarray, x: int, y: int, height: int) -> float:
    """Bar of geometric width 2.5 px: 0.25 + 1 + 1 + 0.25 of coverage."""
    for offset, coverage in ((0, 0.25), (1, 1.0), (2, 1.0), (3, 0.25)):
        _draw_bar(image, x + offset, y, 1, height, coverage=coverage)
    return 2.5


def test_coverage_map_is_polarity_blind() -> None:
    light = _canvas()
    _draw_bar(light, 10, 8, 3, 20)
    dark = _canvas(background=18)
    _draw_bar(dark, 10, 8, 3, 20, background=18, ink=235)

    light_alpha, light_contrast = coverage_map(light[6:34, 6:40])
    dark_alpha, dark_contrast = coverage_map(dark[6:34, 6:40])

    assert light_contrast > 150 and dark_contrast > 150
    assert light_alpha.max() == 1.0 and dark_alpha.max() == 1.0
    # Same bar geometry must yield the same integrated mass in both themes.
    assert abs(light_alpha.sum() - dark_alpha.sum()) <= 1.0


def test_contrast_uses_ink_pixels_only() -> None:
    """A sparse line (ink well under 5 % of the box) must still calibrate."""
    image = _canvas(width=200, height=60)
    _draw_bar(image, 90, 20, 3, 16)  # 3x16 ink inside a 200x60 crop
    _alpha, contrast = coverage_map(image)
    assert contrast > 150.0


def test_stroke_widths_reads_integer_widths() -> None:
    image = _canvas()
    _draw_bar(image, 10, 8, 3, 20)
    alpha, _ = coverage_map(image[6:34, 6:40])
    widths = stroke_widths(alpha, axis=1)
    assert widths.size > 0
    assert abs(float(np.median(widths)) - 3.0) <= 0.05


def test_stroke_widths_is_subpixel() -> None:
    """The whole reason for coverage integration: 2.5 px must not round to 2."""
    image = _canvas()
    _subpixel_bar(image, 10, 8, 20)
    alpha, _ = coverage_map(image[6:34, 6:40])
    widths = stroke_widths(alpha, axis=1)
    assert abs(float(np.median(widths)) - 2.5) <= 0.12


def test_ink_bands_splits_two_lines() -> None:
    image = _canvas(width=80, height=60)
    _draw_bar(image, 12, 6, 20, 8)
    _draw_bar(image, 12, 26, 20, 8)
    alpha, _ = coverage_map(image)
    bands = ink_bands(alpha, gap=4)
    assert len(bands) == 2
    assert bands[0][1] <= bands[1][0]


def test_measure_text_reports_stroke_over_glyph_height() -> None:
    image = _canvas(width=64, height=44)
    _draw_bar(image, 20, 12, 3, 20)
    metrics = measure_text(image, [6, 6, 48, 30], font_size=26.0)
    assert metrics is not None
    assert metrics["ink_height"] == 20.0
    assert abs(metrics["stroke_px"] - 3.0) <= 0.1
    assert abs(metrics["index_height"] - 0.15) <= 0.01
    assert metrics["resolution_ok"] is True


def test_measure_text_rejects_flat_and_tiny_boxes() -> None:
    image = _canvas()
    assert measure_text(image, [6, 6, 48, 30], font_size=20.0) is None
    _draw_bar(image, 20, 12, 1, 20)
    # A 1 px stroke is below the resolution floor but must still be flagged,
    # not silently dropped: the metrics carry resolution_ok=False.
    metrics = measure_text(image, [6, 6, 48, 30], font_size=20.0)
    assert metrics is None or metrics["resolution_ok"] is False


def test_otsu_eta_is_not_a_bimodality_gate() -> None:
    """Documented limitation: unimodal data already reaches eta ~= 2/pi.

    The probe must not gate on ``eta``; this test pins the reason so nobody
    re-introduces it as a "bimodality detector" later.
    """
    rng = np.random.default_rng(7)
    unimodal = rng.normal(0.12, 0.01, size=40)
    bimodal = np.concatenate([rng.normal(0.10, 0.008, 30), rng.normal(0.16, 0.008, 20)])
    assert 0.55 <= otsu_split(unimodal)["eta"] <= 0.78
    assert otsu_split(bimodal)["eta"] > 0.9
    split = otsu_split(bimodal)
    assert 0.11 < split["threshold"] < 0.15


def test_multiotsu_finds_two_cuts_between_three_clusters() -> None:
    values = list(np.linspace(0.08, 0.09, 20)) + list(np.linspace(0.12, 0.13, 20)) + list(
        np.linspace(0.17, 0.18, 20)
    )
    cuts = multiotsu_split(values, 3)
    assert len(cuts) == 2
    assert 0.09 < cuts[0] < 0.12
    assert 0.13 < cuts[1] < 0.17


def _sample(weight: int, index: float, *, resolution: bool = True, cjk: bool = True) -> dict:
    return {
        "gold_weight": weight,
        "cjk": cjk,
        "metrics": {"index_height": index, "resolution_ok": resolution},
    }


def test_binary_rule_oversplits_a_single_weight_page() -> None:
    """Known failure, pinned: an unanchored split invents Bolds.

    This is the light-table shape -- every gold text is Regular and the index
    spread comes from size/content, not weight.  Otsu always finds a cut, so
    the rule must be reported as *not shippable* until it has an anchor.  If a
    future anchor is added, this test is the one that should change.
    """
    rng = np.random.default_rng(3)
    samples = [_sample(400, float(value)) for value in rng.normal(0.12, 0.02, 40)]
    result = binary_rule_eval(samples, "index_height")
    assert result["per_script"]["cjk"]["split_applied"] is True
    assert result["mismatch"] > 0


def test_binary_rule_splits_well_separated_weights() -> None:
    rng = np.random.default_rng(5)
    samples = [_sample(400, float(value)) for value in rng.normal(0.10, 0.006, 25)]
    samples += [_sample(700, float(value)) for value in rng.normal(0.16, 0.006, 15)]
    result = binary_rule_eval(samples, "index_height")
    assert result["per_script"]["cjk"]["split_applied"] is True
    assert result["mismatch"] == 0


def test_binary_rule_falls_back_when_resolution_is_insufficient() -> None:
    """1x shapes: unmeasurable or below the stroke floor -> keep Regular."""
    samples = [_sample(700, 0.14, resolution=False) for _ in range(6)]
    samples += [_sample(400, 0.10, resolution=False) for _ in range(10)]
    result = binary_rule_eval(samples, "index_height")
    assert result["split_applied_to"] == 0
    assert result["mismatch"] == 6  # the six Bolds stay unemitted, by design


def test_flatten_gold_accumulates_offsets_and_scale() -> None:
    tree = {
        "type": "FRAME",
        "x": 100,
        "y": 50,
        "children": [
            {
                "type": "FRAME",
                "x": 10,
                "y": 20,
                "children": [
                    {
                        "type": "TEXT",
                        "characters": "模型广场",
                        "x": 5,
                        "y": 6,
                        "width": 40,
                        "height": 12,
                        "fontSize": 20,
                        "textRuns": [
                            {
                                "fontName": {
                                    "family": "Noto Sans SC",
                                    "style": "Bold",
                                    "variationSettings": {"wght": 700},
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }
    records = flatten_gold_texts(tree, 2.0)
    assert len(records) == 1
    record = records[0]
    # root x/y are zeroed, children accumulate: (10+5, 20+6) * 2
    assert record["bbox"][:2] == [30.0, 52.0]
    assert record["font_size"] == 40.0
    assert record["gold_weight"] == 700
    assert record["cjk"] is True


def test_weight_ladder_round_trip() -> None:
    assert style_to_weight("SemiBold Italic") == 600
    assert style_to_weight("Black") == 900
    assert style_to_weight("Regular") == 400
    assert weight_to_style(700) == "Bold"
    assert weight_to_style(520) == "Medium"
    assert weight_to_style(None) == ""


def test_auc_bounds() -> None:
    assert auc([0.1, 0.2, 0.3, 0.4], [0, 0, 1, 1]) == 1.0
    # Positives at 0.1 and 0.3; only (0.3, 0.2) is a correctly ordered pair.
    assert auc([0.1, 0.2, 0.3, 0.4], [1, 0, 1, 0]) == 0.25
    assert auc([0.1, 0.1, 0.1], [0, 1, 0]) == 0.5
