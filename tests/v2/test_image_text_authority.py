"""OCR line geometry is authoritative over the model's box guesses.

Two behaviours matter: a matched owner takes the OCR pixel box (even when the
model placed it in the wrong column), and duplicates that survive are removed
rather than drawn on top of each other.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure.fidelity.text_authority import (  # noqa: E402
    apply_text_geometry_authority,
)


def _run(elements, observations, containers=None):
    graph = {
        "elements": elements,
        "containers": containers or [{"bbox": [0, 0, 1920, 1008]}],
    }
    return apply_text_geometry_authority(graph, observations, width=1920, height=1008)


class TestGeometryAuthority:
    def test_matched_owner_takes_the_ocr_box(self):
        elements = [{"id": 1, "type": "text", "text": "astryx", "bbox": [656, 296, 128, 36]}]
        observations = [{"text": "astryX", "bbox": [1260, 300, 74, 26], "confidence": 0.9}]

        out, report = _run(elements, observations)

        assert report["snapped"] == 1
        assert out["elements"][0]["bbox"] == [1260, 300, 74, 26]
        assert out["elements"][0]["textBoxAuthority"] == "ocr-line"

    def test_same_container_matches_across_a_large_drift(self):
        # The model dropped the title into the wrong spot; both boxes still sit
        # inside the same card, so the distance gate must not block the match.
        containers = [{"bbox": [0, 0, 1920, 1008]}, {"bbox": [1135, 268, 729, 242]}]
        elements = [{"id": 1, "type": "text", "text": "astryx", "bbox": [1200, 290, 120, 30]}]
        observations = [{"text": "astryX", "bbox": [1200, 450, 74, 26], "confidence": 0.8}]

        out, report = _run(elements, observations, containers)

        assert report["snapped"] == 1
        assert out["elements"][0]["bbox"] == [1200, 450, 74, 26]

    def test_far_and_unrelated_owner_is_left_alone(self):
        elements = [{"id": 1, "type": "text", "text": "CodingPlan", "bbox": [73, 566, 123, 33]}]
        observations = [{"text": "完全不同的文字", "bbox": [1400, 900, 80, 24], "confidence": 0.9}]

        out, report = _run(elements, observations)

        assert report["snapped"] == 0
        assert out["elements"][0]["bbox"] == [73, 566, 123, 33]

    def test_ocr_wording_replaces_a_truncated_model_label(self):
        elements = [{"id": 1, "type": "text", "text": "yx", "bbox": [656, 296, 60, 36]}]
        observations = [{"text": "astryx", "bbox": [660, 298, 120, 34], "confidence": 0.9}]

        out, _report = _run(elements, observations)

        assert out["elements"][0]["text"] == "astryx"

    def test_block_swallowing_several_labels_is_dropped(self):
        elements = [
            {"id": 1, "type": "link", "text": "大模型", "bbox": [23, 337, 263, 83]},
            {"id": 2, "type": "text", "text": "智能体开发", "bbox": [78, 352, 112, 30]},
            {"id": 3, "type": "text", "text": "Buidancr", "bbox": [171, 384, 71, 26]},
        ]

        out, report = _run(elements, [])

        remaining = [element["text"] for element in out["elements"]]
        assert "大模型" not in remaining
        assert "智能体开发" in remaining and "Buidancr" in remaining
        assert report["dropped_blocks"] == 1

    def test_duplicate_labels_collapse(self):
        elements = [
            {"id": 1, "type": "text", "text": "CodingPlan", "bbox": [73, 566, 123, 33]},
            {"id": 2, "type": "text", "text": "昇腾生态", "bbox": [75, 568, 120, 30]},
        ]

        out, report = _run(elements, [])

        assert len(out["elements"]) == 1
        assert report["nms_dropped"] == 1

    def test_disjoint_labels_are_all_kept(self):
        elements = [
            {"id": 1, "type": "text", "text": "alpha", "bbox": [10, 10, 100, 24]},
            {"id": 2, "type": "text", "text": "beta", "bbox": [10, 60, 100, 24]},
            {"id": 3, "type": "text", "text": "gamma", "bbox": [300, 10, 100, 24]},
        ]

        out, report = _run(elements, [])

        assert len(out["elements"]) == 3
        assert report["nms_dropped"] == 0
