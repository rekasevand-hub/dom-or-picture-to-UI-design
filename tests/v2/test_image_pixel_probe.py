"""Pixel probes: multi-line type scale, container borders and corner radius.

These probes carry the geometry that used to be lost between the scene plan
and the renderer, so they are guarded with synthetic screenshots whose true
type scale and radius are known exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure.fidelity.pixel_probe import (  # noqa: E402
    detect_border,
    estimate_corner_radius,
    ink_line_bands,
    line_metrics,
    load_rgb,
    sample_container_decoration,
)
from src.app.services.structure.fidelity.style_resolver import (  # noqa: E402
    resolve_text_style,
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
    pytest.skip("no TrueType font available for synthetic screenshots")


def _paragraph_image(path: Path, *, font_size: int, lines: int, pitch: int) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (460, 40 + lines * pitch), "white")
    draw = ImageDraw.Draw(image)
    font = _font(font_size)
    for index in range(lines):
        draw.text(
            (24, 16 + index * pitch),
            "The quick brown fox jumps over",
            fill=(32, 32, 32),
            font=font,
        )
    image.save(path)


def _rounded_card(path: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (340, 240), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (24, 24, 316, 216),
        radius=12,
        fill=(245, 247, 250),
        outline=(208, 215, 226),
        width=1,
    )
    image.save(path)


class TestInkLineBands:
    def test_three_line_paragraph_splits_into_three_bands(self, tmp_path: Path):
        source = tmp_path / "paragraph.png"
        _paragraph_image(source, font_size=15, lines=3, pitch=24)

        image = load_rgb(source)
        import numpy as np

        crop = image[:, :]
        mask = np.abs(crop - 255).max(axis=2) > 24
        bands = ink_line_bands(mask)
        metrics = line_metrics(bands)

        assert metrics["lineCount"] == 3
        assert metrics["linePitch"] == pytest.approx(24, abs=2)

    def test_font_size_uses_single_line_height_not_block_height(self, tmp_path: Path):
        source = tmp_path / "paragraph.png"
        _paragraph_image(source, font_size=15, lines=3, pitch=24)
        block = [10, 8, 440, 96]

        style = resolve_text_style(source, "The quick brown fox jumps over", block)

        # Whole-block height would report ~24-76px; the real type is 15px.
        assert style["fontSize"] <= 20
        assert style["evidence"]["line_count"] >= 2
        assert style["lineHeightPolicy"] in {"observed", "auto"}

    def test_single_line_is_unchanged(self, tmp_path: Path):
        source = tmp_path / "single.png"
        _paragraph_image(source, font_size=15, lines=1, pitch=24)
        block = [10, 8, 440, 32]

        style = resolve_text_style(source, "The quick brown fox jumps over", block)

        assert style["fontSize"] == pytest.approx(15, abs=4)
        assert "lineHeight" not in style


class TestContainerDecoration:
    def test_border_and_radius_are_sampled(self, tmp_path: Path):
        source = tmp_path / "card.png"
        _rounded_card(source)

        decoration = sample_container_decoration(
            source, (24, 24, 292, 192), "#f5f7fa"
        )

        assert decoration.get("borderWidth") == 1
        assert decoration.get("borderColor", "").lower() in {"#d0d7e2", "#d0d7e1"}
        assert decoration.get("borderRadius") == 12

    def test_flat_fill_reports_no_border(self, tmp_path: Path):
        from PIL import Image, ImageDraw

        source = tmp_path / "flat.png"
        image = Image.new("RGB", (240, 160), "white")
        ImageDraw.Draw(image).rectangle((20, 20, 220, 140), fill=(240, 240, 240))
        image.save(source)

        decoration = sample_container_decoration(source, (20, 20, 200, 120), "#f0f0f0")

        assert "borderWidth" not in decoration
        assert "borderColor" not in decoration

    def test_capsule_button_gets_pill_radius(self, tmp_path: Path):
        from PIL import Image, ImageDraw

        source = tmp_path / "pill.png"
        image = Image.new("RGB", (200, 80), "white")
        ImageDraw.Draw(image).rounded_rectangle(
            (20, 20, 180, 60), radius=20, fill=(20, 20, 20)
        )
        image.save(source)

        radius = estimate_corner_radius(load_rgb(source), (20, 20, 160, 40))

        assert radius == 999
