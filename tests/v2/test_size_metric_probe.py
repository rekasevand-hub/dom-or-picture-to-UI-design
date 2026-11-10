"""Size-metric probe: pairing and ink measurement must be deterministic.

The probe decides whether ``font_ratio`` should be replaced by an ink-height
ratio, so its two building blocks are pinned here: one-to-one pairing by string
and position, and an ink-height measurement that survives sparse text.
"""

from __future__ import annotations

import numpy as np

from scripts.size_metric_probe import (
    flatten_readback,
    match_pairs,
    measure_pair,
    subpixel_ink_height,
)

BACKGROUND = 255
INK = 20


def _gold(text: str, x: float, y: float, size: float = 20.0) -> dict:
    return {
        "text": text,
        "key": "".join(text.split()).casefold(),
        "bbox": [x, y, 40.0, 20.0],
        "font_size": size,
    }


def _pipe(text: str, x: float, y: float, size: float = 20.0) -> dict:
    return {
        "text": text,
        "key": "".join(text.split()).casefold(),
        "x": x,
        "y": y,
        "width": 40.0,
        "height": 20.0,
        "font_size": size,
    }


def test_flatten_readback_accumulates_offsets() -> None:
    tree = {
        "type": "FRAME",
        "x": 0,
        "y": 0,
        "children": [
            {
                "type": "FRAME",
                "x": 10,
                "y": 20,
                "children": [
                    {"type": "TEXT", "characters": "模型 广场", "x": 5, "y": 6, "fontSize": 26}
                ],
            }
        ],
    }
    records = flatten_readback(tree)
    assert len(records) == 1
    assert records[0]["x"] == 15.0 and records[0]["y"] == 26.0
    assert records[0]["key"] == "模型广场"
    assert records[0]["font_size"] == 26.0


def test_match_pairs_is_one_to_one_and_nearest() -> None:
    gold = [_gold("首页", 10, 10), _gold("首页", 100, 10)]
    pipe = [_pipe("首页", 104, 12), _pipe("首页", 12, 9)]
    pairs = match_pairs(gold, pipe)

    assert len(pairs) == 2
    assert {pair[0]["bbox"][0] for pair in pairs} == {10, 100}
    assert {pair[1]["x"] for pair in pairs} == {12, 104}


def test_match_pairs_drops_unmatched() -> None:
    pairs = match_pairs([_gold("独有", 10, 10)], [_pipe("别的", 10, 10)])
    assert pairs == []


def test_subpixel_ink_height_reads_the_bar_height() -> None:
    canvas = np.full((80, 120), BACKGROUND, dtype=np.uint8)
    canvas[20:44, 30:36] = INK  # 24 px tall, thin (ink stays a minority)
    image = np.stack([canvas] * 3, axis=2).astype(np.int16)

    height = subpixel_ink_height(image, [24, 14, 72, 36])
    assert height is not None
    assert abs(height - 24.0) <= 0.6


def test_measure_pair_reports_ratios_and_skips_flat_boxes() -> None:
    reference = np.full((80, 120, 3), BACKGROUND, dtype=np.int16)
    reference[20:40, 30:36] = INK
    rendered = np.full((80, 120, 3), BACKGROUND, dtype=np.int16)
    rendered[20:30, 30:36] = INK  # half the height

    measured = measure_pair(reference, rendered, {"bbox": [24, 14, 72, 36]})
    assert measured is not None
    assert measured["ink_ratio"] == 0.5

    flat = np.full((80, 120, 3), BACKGROUND, dtype=np.int16)
    assert measure_pair(flat, rendered, {"bbox": [24, 14, 72, 36]}) is None
