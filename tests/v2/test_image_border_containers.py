"""Card containers recovered from painted borders.

The detector finds closed 1px card frames and needs no OCR: it takes the text
boxes the model already produced.  These tests pin the two rules that keep it
from polluting the graph — a box must hold at least two known elements, and a
duplicate of an existing container must not be added twice.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure.fidelity.border_containers import (  # noqa: E402
    recover_border_containers,
)


def _two_cards(path: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (820, 420), "white")
    draw = ImageDraw.Draw(image)
    for left in (30, 430):
        draw.rounded_rectangle(
            (left, 40, left + 360, 380),
            radius=10,
            fill=(250, 250, 252),
            outline=(205, 210, 220),
            width=1,
        )
    image.save(path)


def _graph() -> dict:
    return {
        "image_w": 820,
        "image_h": 420,
        "containers": [
            {"id": "page", "bbox": [0, 0, 820, 420], "role": "page", "source": "grounding"},
        ],
        "elements": [
            {"id": 1, "type": "text", "bbox": [60, 80, 200, 24]},
            {"id": 2, "type": "text", "bbox": [60, 140, 260, 40]},
            {"id": 3, "type": "text", "bbox": [460, 80, 200, 24]},
            {"id": 4, "type": "text", "bbox": [460, 140, 260, 40]},
        ],
    }


class TestBorderContainers:
    def test_two_cards_are_recovered(self, tmp_path: Path):
        source = tmp_path / "cards.png"
        _two_cards(source)

        recovered, report = recover_border_containers(
            _graph(), source, width=820, height=420
        )

        assert report["status"] == "applied"
        assert report["added_count"] == 2
        cards = [c for c in recovered["containers"] if c.get("role") == "card"]
        assert len(cards) == 2
        cards.sort(key=lambda c: c["bbox"][0])
        # The detector returns the stroke's outer edge, hence the 2px slack.
        assert cards[0]["bbox"][0] == pytest.approx(30, abs=4)
        assert cards[1]["bbox"][0] == pytest.approx(430, abs=4)

    def test_each_card_yields_exactly_one_container(self, tmp_path: Path):
        source = tmp_path / "cards.png"
        _two_cards(source)

        recovered, report = recover_border_containers(
            _graph(), source, width=820, height=420
        )

        # A card whose stroke is detected twice (inner and outer edge) must
        # still collapse into one container, never two stacked frames.
        assert report["added_count"] == 2
        cards = [c for c in recovered["containers"] if c.get("role") == "card"]
        assert len(cards) == 2

    def test_existing_container_is_not_duplicated(self, tmp_path: Path):
        source = tmp_path / "cards.png"
        _two_cards(source)
        graph = _graph()
        graph["containers"].append(
            {"id": "card-copy", "bbox": [30, 40, 360, 340], "role": "card", "source": "grounding"}
        )

        recovered, report = recover_border_containers(
            graph, source, width=820, height=420
        )

        overlapping = [
            c
            for c in recovered["containers"]
            if c.get("role") == "card" and c["bbox"][0] < 400
        ]
        assert len(overlapping) == 1
        assert report["rejected"]["duplicate"] >= 1

    def test_box_without_enough_members_is_skipped(self, tmp_path: Path):
        from PIL import Image, ImageDraw

        source = tmp_path / "empty.png"
        image = Image.new("RGB", (820, 420), "white")
        ImageDraw.Draw(image).rounded_rectangle(
            (30, 40, 390, 380), radius=10, fill=(250, 250, 252), outline=(205, 210, 220), width=1
        )
        image.save(source)
        graph = _graph()
        # Only one element inside the frame: not a layout box.
        graph["elements"] = [{"id": 1, "type": "text", "bbox": [60, 80, 200, 24]}]

        _recovered, report = recover_border_containers(
            graph, source, width=820, height=420
        )

        assert report["added_count"] == 0
        assert report["rejected"]["few-members"] >= 1
