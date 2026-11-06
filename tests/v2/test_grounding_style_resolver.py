from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.app.services.structure.fidelity.style_resolver import (
    resolve_text_style,
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
    ):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _dark_text_image(path: Path) -> None:
    image = Image.new("RGB", (240, 80), "#ffffff")
    ImageDraw.Draw(image).text(
        (20, 20),
        "auto_backup",
        fill="#333333",
        font=_font(20),
    )
    image.save(path)


def _light_text_image(path: Path) -> None:
    image = Image.new("RGB", (240, 80), "#24324a")
    ImageDraw.Draw(image).text(
        (20, 20),
        "FlexWeaver",
        fill="#ffffff",
        font=_font(20),
    )
    image.save(path)


def test_resolver_samples_dark_text_size_and_color(tmp_path: Path) -> None:
    path = tmp_path / "dark.png"
    _dark_text_image(path)

    result = resolve_text_style(
        path,
        "auto_backup",
        [12, 12, 200, 45],
    )

    assert result["fontFamily"] == "Open Sans"
    assert 14 <= result["fontSize"] <= 24
    assert result["textColor"].lower() in {"#222222", "#333333", "#404040"}
    assert result["textAlign"] == "left"
    assert result["evidence"]["script"] == "latin"
    assert result["confidence"] >= 0.6


def test_resolver_handles_light_text_on_dark_background(tmp_path: Path) -> None:
    path = tmp_path / "light.png"
    _light_text_image(path)

    result = resolve_text_style(
        path,
        "FlexWeaver",
        [12, 12, 200, 45],
    )

    red, green, blue = (
        int(result["textColor"][index : index + 2], 16) for index in (1, 3, 5)
    )
    assert (red + green + blue) / 3 >= 180
    assert result["evidence"]["background"].lower() == "#24324a"


def test_resolver_routes_cjk_to_noto_sans_sc() -> None:
    result = resolve_text_style(
        Path(
            r"tests/fixtures/image_to_slice_benchmark_2026-11-02/IMG-FLEXWEAVER-ADMIN.png"
        ),
        "执行时间",
        [448, 565, 70, 20],
        role="table-header",
        parent_bbox=[388, 549, 189, 50],
    )

    assert result["fontFamily"] == "Noto Sans SC"
    assert result["textAlign"] == "center"
    assert result["fontWeight"] == "bold"


def test_resolver_uses_parent_geometry_for_alignment(tmp_path: Path) -> None:
    path = tmp_path / "dark.png"
    _dark_text_image(path)

    result = resolve_text_style(
        path,
        "auto_backup",
        [70, 20, 100, 20],
        parent_bbox=[20, 10, 200, 40],
    )

    assert result["textAlign"] == "center"
    assert result["evidence"]["parent_center_delta"] <= 5


def test_resolver_exposes_low_confidence_when_no_ink_is_found(
    tmp_path: Path,
) -> None:
    path = tmp_path / "blank.png"
    Image.new("RGB", (240, 80), "#ffffff").save(path)

    result = resolve_text_style(
        path,
        "missing",
        [100, 30, 80, 20],
    )

    assert result["confidence"] < 0.5
    assert result["evidence"]["status"] == "low-confidence"
