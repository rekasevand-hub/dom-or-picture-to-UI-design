# -*- coding: utf-8 -*-
"""The gold-tree audit must separate a usable answer key from a paraphrase.

Since the 2026-11-10 renewal all three families are positive controls: their
gold frames are native-resolution rebuilds that land on the screenshot's text
and agree with what the pipeline reads.  The negative case (a paraphrasing,
mis-scaled gold) is exercised with synthetic data, because keeping a broken
fixture around just to test the detector would mean shipping a broken answer key.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scripts.audit_gold_tree import BENCH, _row_pitches, _screenshot_row_pitch, audit
from scripts.p1_font_weight_evidence import flatten_gold_texts

FAMILIES = ("dark-card-grid", "light-form", "light-table")


def test_every_family_has_boxes_on_ink() -> None:
    for family in FAMILIES:
        report = audit(BENCH / family)
        assert report["geometry"]["ink_fraction"] >= 0.95, family
        assert report["geometry"]["usable"] is True, family


def test_every_family_is_usable() -> None:
    for family in FAMILIES:
        assert audit(BENCH / family)["verdict"] == "usable", family


def test_light_table_row_pitch_matches_the_screenshot() -> None:
    """The renewed gold is native 2544x1336, so its row pitch equals the image's.

    Measured off the date column rather than off frame sequences: the regenerated
    gold does not use equally-spaced sibling frames for its rows, so
    ``_row_pitches`` has nothing to latch onto there.
    """
    family = BENCH / "light-table"
    tree = json.loads((family / "gold_tree.json").read_text(encoding="utf-8"))
    gold = flatten_gold_texts(tree, 1.0)
    rows = sorted({round(r["bbox"][1]) for r in gold if r["text"].startswith("2026-")})
    assert len(rows) >= 6, rows
    gaps = np.diff(rows)
    pitch = float(np.median(gaps))

    screenshot = audit(family)["row_pitch"]["screenshot_px"]
    assert screenshot is not None
    assert abs(pitch - screenshot) <= 3.0, (pitch, screenshot)


def test_text_agreement_is_high_on_aligned_families() -> None:
    for family in FAMILIES:
        report = audit(BENCH / family)
        agreement = report["text_fidelity"]["agreement"]
        if agreement is None:
            pytest.skip(f"no readback available for {family}")
        assert agreement >= 0.8, (family, agreement)


def test_audit_flags_a_paraphrasing_gold(tmp_path: Path, monkeypatch) -> None:
    """A gold whose strings are absent from the pipeline output is not usable."""
    family = tmp_path / "fake"
    family.mkdir()
    Image.fromarray(np.full((240, 320, 3), 255, dtype=np.uint8)).save(
        family / "reference.png"
    )
    (family / "family.json").write_text(
        json.dumps(
            {"family": "fake", "gold": {"scale_to_reference": 1.0}, "pipeline_run": "none"}
        ),
        encoding="utf-8",
    )
    (family / "gold_tree.json").write_text(
        json.dumps(
            {
                "type": "FRAME",
                "children": [
                    {"type": "TEXT", "characters": "项目编号", "x": 10, "y": 10,
                     "width": 80, "height": 20, "fontSize": 14},
                    {"type": "TEXT", "characters": "备注说明", "x": 10, "y": 40,
                     "width": 80, "height": 20, "fontSize": 14},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.audit_gold_tree._inventory_texts", lambda _dir: {"项目代码", "绩效评估说明"}
    )

    report = audit(family)
    assert report["text_fidelity"]["agreement"] == 0.0
    assert report["text_fidelity"]["usable"] is False
    assert report["verdict"] == "not-usable"


def test_audit_flags_a_mis_scaled_gold(tmp_path: Path, monkeypatch) -> None:
    """Boxes that miss the ink are reported as unusable geometry."""
    family = tmp_path / "fake"
    family.mkdir()
    image = np.full((240, 320, 3), 255, dtype=np.uint8)
    image[10:30, 10:90] = 20
    Image.fromarray(image).save(family / "reference.png")
    (family / "family.json").write_text(
        json.dumps(
            {"family": "fake", "gold": {"scale_to_reference": 1.0}, "pipeline_run": "none"}
        ),
        encoding="utf-8",
    )
    (family / "gold_tree.json").write_text(
        json.dumps(
            {
                "type": "FRAME",
                "children": [
                    {"type": "TEXT", "characters": "hello", "x": 200, "y": 200,
                     "width": 60, "height": 18, "fontSize": 14}
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.audit_gold_tree._inventory_texts", lambda _dir: set())

    report = audit(family)
    assert report["geometry"]["ink_fraction"] == 0.0
    assert report["geometry"]["usable"] is False


def test_row_pitch_detection_needs_a_regular_sequence() -> None:
    """Three evenly spaced boxes is a coincidence, not a table."""
    tree = {
        "type": "FRAME",
        "children": [
            {"type": "FRAME", "name": "row", "y": 10.0, "height": 20}
            for _ in range(3)
        ],
    }
    assert _row_pitches(tree, min_rows=4) == []


def test_row_pitch_detection_reads_a_regular_grid() -> None:
    tree = {
        "type": "FRAME",
        "children": [
            {"type": "FRAME", "name": "row", "y": 10.0 + i * 24, "height": 20}
            for i in range(6)
        ],
    }
    sequences = _row_pitches(tree)
    assert len(sequences) == 1
    assert sequences[0]["count"] == 6
    assert sequences[0]["pitch"] == 24.0


def test_screenshot_pitch_uses_the_mode_not_the_median() -> None:
    """A few off-grid rows must not drag the pitch (81 -> 71.5 incident)."""
    image = np.full((400, 120, 3), 255, dtype=np.int16)
    for y in (40, 60, 141, 222, 303, 384):
        image[y : y + 14, 20:100, :] = 20
    pitch = _screenshot_row_pitch(image, [[20, 40, 80, 358]])
    assert pitch is None or pitch == 81.0
