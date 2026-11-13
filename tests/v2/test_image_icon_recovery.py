"""Small-icon recovery: must find glyphs, must not resurrect text."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure.fidelity.icon_recovery import (  # noqa: E402
    recover_small_icon_regions,
)


def _font(size: int):
    from PIL import ImageFont

    for candidate in (
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    pytest.skip("no TrueType font available")


def _toolbar_image(path: Path) -> None:
    """A label (already known) plus a banked 22px logo (unknown)."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (320, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 40), "OpenHarmony", fill=(30, 30, 30), font=_font(14))
    # 22x22 mark with internal detail so it is not a flat colour block.
    draw.rectangle((220, 36, 242, 58), fill=(196, 32, 32))
    draw.rectangle((226, 42, 236, 52), fill=(255, 255, 255))
    image.save(path)


class TestIconRecovery:
    def test_recovers_glyph_outside_known_text(self, tmp_path: Path):
        source = tmp_path / "toolbar.png"
        _toolbar_image(source)
        graph = {
            "elements": [
                {"id": 1, "type": "text", "bbox": [18, 38, 105, 24], "text": "OpenHarmony"},
            ]
        }

        recovered, report = recover_small_icon_regions(graph, source)

        assert report["status"] == "applied"
        assert report["added_count"] == 1
        box = report["added"][0]["bbox"]
        assert box[0] == pytest.approx(220, abs=3)
        assert box[1] == pytest.approx(36, abs=3)
        assert box[2] == pytest.approx(23, abs=3)
        assert report["added"][0]["type"] == "image"
        assert len(recovered["elements"]) == 2

    def test_text_only_screen_adds_nothing(self, tmp_path: Path):
        from PIL import Image, ImageDraw

        source = tmp_path / "text.png"
        image = Image.new("RGB", (320, 100), "white")
        ImageDraw.Draw(image).text(
            (20, 40), "OpenHarmony openEuler Cangjie", fill=(30, 30, 30), font=_font(14)
        )
        image.save(source)
        graph = {
            "elements": [
                {
                    "id": 1,
                    "type": "text",
                    "bbox": [18, 38, 210, 24],
                    "text": "OpenHarmony openEuler Cangjie",
                }
            ]
        }

        _recovered, report = recover_small_icon_regions(graph, source)

        assert report["added_count"] == 0
        assert report["status"] == "not-found"

    def test_known_image_is_not_duplicated(self, tmp_path: Path):
        source = tmp_path / "toolbar.png"
        _toolbar_image(source)
        graph = {
            "elements": [
                {"id": 1, "type": "text", "bbox": [18, 38, 105, 24], "text": "OpenHarmony"},
                {"id": 2, "type": "image", "bbox": [219, 35, 25, 25]},
            ]
        }

        _recovered, report = recover_small_icon_regions(graph, source)

        assert report["added_count"] == 0
