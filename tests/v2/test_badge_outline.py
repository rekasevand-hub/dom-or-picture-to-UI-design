"""Badge outline synthesis: replace a badge crop that carries its own label.

The geometry mirrors the two measured badges on dark-card-grid: a 105x44 red
rounded outline, 3 px stroke, with the label's glyphs baked into the crop.  The
synthetic fixture keeps the same relationship at a smaller scale so the numbers
stay readable.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.structure.fidelity.text_calibration import (
    synthesize_badge_outline,
)

BACKGROUND = (26, 25, 23)
ACCENT = (240, 89, 67)


def _screenshot(
    path: Path,
    *,
    outline: tuple[int, int, int, int, int] | None = None,
    glyphs: list[tuple[int, int, int, int]] | None = None,
    glyph_colour: tuple[int, int, int] = ACCENT,
    filled: bool = False,
    size: tuple[int, int] = (400, 300),
) -> Path:
    image = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(image)
    if outline is not None:
        x0, y0, x1, y1, radius = outline
        if filled:
            draw.rounded_rectangle(
                (x0, y0, x1 - 1, y1 - 1), radius=radius, fill=ACCENT
            )
        else:
            draw.rounded_rectangle(
                (x0, y0, x1 - 1, y1 - 1),
                radius=radius,
                outline=ACCENT,
                width=3,
            )
    for box in glyphs or []:
        draw.rectangle(box, fill=glyph_colour)
    image.save(path)
    return path


def _design(elements: list[dict], height: float = 300.0) -> dict:
    return {"canvas": {"width": 400, "height": height}, "elements": elements}


def _label(text: str, x: float, y: float, w: float, h: float) -> dict:
    return {
        "type": "text",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "text": text,
        "contentRef": f"text:{text}",
        "style": {"fontSize": 24, "textColor": "#F05943"},
    }


def _crop(x: float, y: float, w: float, h: float, payload: str = "AAAA") -> dict:
    return {
        "id": "asset:badge",
        "type": "image",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "text": "",
        "style": {},
        "imageBase64": payload,
    }


def _badge_fixture(tmp_path: Path, **kwargs) -> Path:
    """120x50 outline at (100,100) with three glyph blocks inside the label."""
    return _screenshot(
        tmp_path / "shot.png",
        outline=(100, 100, 220, 150, 10),
        glyphs=[(120, 115, 135, 135), (142, 115, 160, 135), (168, 115, 188, 135)],
        **kwargs,
    )


def test_baked_badge_becomes_a_drawn_outline(tmp_path: Path) -> None:
    image = _badge_fixture(tmp_path)
    # The crop is wider than the label (the fragment-image case needs the
    # opposite) and holds the label plus the outline.
    design = _design([_crop(95, 103, 140, 47), _label("6.6折", 115, 110, 75, 30)])

    calibrated, report = synthesize_badge_outline(design, image)

    assert report["status"] == "applied"
    assert report["adjusted_count"] == 1
    badge = report["badges"][0]
    assert badge["text"] == "6.6折"
    assert badge["bbox"] == [100.0, 100.0, 220.0, 150.0]
    assert badge["stroke"] == 3
    assert badge["borderColor"] == "#F05943"
    assert badge["fillColor"] == "#1A1917"

    element = calibrated["elements"][0]
    assert element["type"] == "rectangle"
    assert element["id"] == "asset:badge"
    assert "imageBase64" not in element
    assert element["paintDepth"] == 0
    assert element["role"] == "badge-outline"
    assert element["style"]["borderColor"] == "#F05943"
    assert element["style"]["borderWidth"] == 3
    # The estimator reads where the straight top edge begins, and anti-aliasing
    # blurs that boundary by a couple of pixels (drawn 10, measured 7 here).
    # Pinning the exact value would test PIL's rasteriser, not this rule; what
    # the assertion has to rule out is a square corner.
    assert 5 <= element["style"]["borderRadius"] <= 12
    # The label survives, in the same slot, and nothing was added or lost.
    assert calibrated["elements"][1]["text"] == "6.6折"
    assert len(calibrated["elements"]) == 2


def test_filled_pill_is_left_alone(tmp_path: Path) -> None:
    image = _screenshot(
        tmp_path / "shot.png",
        outline=(100, 100, 220, 150, 10),
        glyphs=[(120, 115, 135, 135)],
        filled=True,
    )
    design = _design([_crop(95, 103, 140, 47), _label("6.6折", 115, 110, 75, 30)])

    calibrated, report = synthesize_badge_outline(design, image)

    # No thin outline to measure: a solid pill needs its own rule, and there is
    # no evidence for one yet.  The reason is recorded, not swallowed.  A solid
    # pill fails as "stroke as deep as the blob"; one with a thin border but an
    # accent interior would fail on the interior check instead.
    assert report["status"] == "not-needed"
    assert report["skipped"][0]["reason"] == "accent area too thick to be an outline"
    assert calibrated["elements"][0]["type"] == "image"


def test_refusal_records_the_check_that_refused_it(tmp_path: Path) -> None:
    image = _screenshot(
        tmp_path / "shot.png",
        glyphs=[(120, 115, 135, 135), (142, 115, 160, 135)],
    )
    design = _design([_crop(95, 103, 140, 47), _label("6.6折", 115, 110, 75, 30)])

    _, report = synthesize_badge_outline(design, image)

    # Glyphs in the crop but nothing around them: this is the hamburger-icon
    # case on light-table, and the record has to say so.
    assert report["status"] == "not-needed"
    assert report["skipped"] == [
        {
            "text": "6.6折",
            "crop_bbox": [95.0, 103.0, 235.0, 150.0],
            "reason": "no bar left of the label",
        }
    ]


def test_border_without_baked_glyphs_is_left_alone(tmp_path: Path) -> None:
    image = _screenshot(
        tmp_path / "shot.png",
        outline=(100, 100, 220, 150, 10),
        glyphs=[(120, 115, 135, 135)],
        glyph_colour=(210, 208, 200),
    )
    design = _design([_crop(95, 103, 140, 47), _label("6.6折", 115, 110, 75, 30)])

    calibrated, report = synthesize_badge_outline(design, image)

    # A coloured frame around neutral glyphs is a button, not a baked badge.
    assert report["status"] == "not-needed"
    assert calibrated["elements"][0]["type"] == "image"


def test_crop_narrower_than_label_belongs_to_fragment_image(tmp_path: Path) -> None:
    image = _badge_fixture(tmp_path)
    design = _design([_crop(130, 103, 40, 47), _label("6.6折", 115, 110, 75, 30)])

    _, report = synthesize_badge_outline(design, image)

    assert report["adjusted_count"] == 0


def test_container_crop_holding_a_whole_table_is_not_a_badge(tmp_path: Path) -> None:
    image = _badge_fixture(tmp_path)
    design = _design(
        [_crop(10, 10, 380, 200), _label("6.6折", 115, 110, 75, 30)],
        height=300.0,
    )

    _, report = synthesize_badge_outline(design, image)

    assert report["adjusted_count"] == 0


def test_outline_far_from_the_label_is_ignored(tmp_path: Path) -> None:
    image = _screenshot(
        tmp_path / "shot.png",
        outline=(20, 20, 140, 70, 10),
        glyphs=[(250, 250, 265, 270)],
    )
    design = _design([_crop(240, 240, 140, 47), _label("6.6折", 245, 245, 75, 30)])

    _, report = synthesize_badge_outline(design, image)

    assert report["adjusted_count"] == 0


def test_missing_screenshot_is_not_fatal(tmp_path: Path) -> None:
    design = _design([_crop(95, 103, 140, 47), _label("6.6折", 115, 110, 75, 30)])

    calibrated, report = synthesize_badge_outline(
        design, tmp_path / "does-not-exist.png"
    )

    assert report["status"] == "not-needed"
    assert calibrated["elements"][0]["type"] == "image"


def test_second_pass_finds_nothing_to_do(tmp_path: Path) -> None:
    image = _badge_fixture(tmp_path)
    design = _design([_crop(95, 103, 140, 47), _label("6.6折", 115, 110, 75, 30)])

    once, _ = synthesize_badge_outline(design, image)
    twice, report = synthesize_badge_outline(once, image)

    assert report["status"] == "not-needed"
    assert twice["elements"][0]["type"] == "rectangle"
