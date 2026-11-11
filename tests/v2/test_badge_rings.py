"""Concentric-outline badges: two strokes, and a frame that is tilted.

dark-card-grid's large discount badges are drawn as two nested red rounded
rectangles (6 px outside, 4 px gap, 3 px inside) and rotated 6 degrees.  Both
facts broke the first version of the rule in ways that looked like geometry
bugs: measuring the *nearest* stroke gave the inner frame's width against the
outer frame's height (132x152 for a 152x152 badge), and measuring the corner
radius on the topmost row of a tilted shape reads half the width, because that
row only touches a corner.

The fixture keeps the relationship at a readable scale: 180x180 outside, 160x160
inside, 6 and 3 px strokes, tilted 6 degrees.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.structure.fidelity.text_calibration import (
    synthesize_badge_outline,
)

BACKGROUND = (26, 25, 23)
ACCENT = (240, 89, 67)
SIDE = 420
TILT = 6.0
OUTER = (120, 120, 300, 300, 16)
INNER = (130, 130, 290, 290, 8)
LABEL = (160, 170, 260, 250)


def _tilted_shot(path: Path) -> Path:
    """Two concentric outlines with baked glyphs, rotated ``TILT`` degrees."""
    image = Image.new("RGB", (SIDE, SIDE), BACKGROUND)
    draw = ImageDraw.Draw(image)
    for x0, y0, x1, y1, radius, width in (
        (*OUTER, 6),
        (*INNER, 3),
    ):
        draw.rounded_rectangle(
            (x0, y0, x1 - 1, y1 - 1), radius=radius, outline=ACCENT, width=width
        )
    for box in ((180, 185, 215, 220), (225, 185, 245, 220), (185, 225, 235, 240)):
        draw.rectangle(box, fill=ACCENT)
    rotated = image.rotate(TILT, resample=Image.BICUBIC, expand=True, fillcolor=BACKGROUND)
    rotated.save(path)
    return path


def _rotated_box(box: tuple[int, int, int, int], size: int) -> list[float]:
    """Where ``box`` lands after the same rotation, as an axis-aligned box."""
    radians = math.radians(TILT)
    centre = size / 2
    points = []
    for x, y in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])):
        dx, dy = x - centre, y - centre
        points.append(
            (
                centre + dx * math.cos(radians) + dy * math.sin(radians),
                centre - dx * math.sin(radians) + dy * math.cos(radians),
            )
        )
    grown = int(round(math.ceil(size * (abs(math.cos(radians)) + abs(math.sin(radians))))))
    offset = (grown - size) / 2
    xs = [point[0] + offset for point in points]
    ys = [point[1] + offset for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _design(label_box: list[float]) -> dict:
    width = label_box[2] - label_box[0]
    height = label_box[3] - label_box[1]
    return {
        "canvas": {"width": 480, "height": 480},
        "elements": [
            {
                "id": "asset:badge",
                "type": "image",
                "x": label_box[0] - 18,
                "y": label_box[1] - 6,
                "width": width + 36,
                "height": height + 12,
                "text": "",
                "style": {},
                "imageBase64": "AAAA",
            },
            {
                "type": "text",
                "x": label_box[0],
                "y": label_box[1],
                "width": width,
                "height": height,
                "text": "5.8折",
                "contentRef": "text:5.8折",
                "style": {"fontSize": 40, "textColor": "#F05943"},
            },
        ],
    }


def test_two_concentric_strokes_become_two_rings(tmp_path: Path) -> None:
    image = _tilted_shot(tmp_path / "shot.png")
    design = _design(_rotated_box(LABEL, SIDE))

    calibrated, report = synthesize_badge_outline(design, image)

    assert report["status"] == "applied"
    badge = report["badges"][0]
    assert len(badge["rings"]) == 2, "both strokes are part of the badge"
    outer, inner = badge["rings"]
    assert outer["stroke"] == 6
    assert inner["stroke"] == 3
    # Sizes come from where the strokes cross the label's centre row and column,
    # which is the outline's own box.  Two pixels of slack covers anti-aliasing.
    assert abs((outer["bbox"][2] - outer["bbox"][0]) - 180) <= 3
    assert abs((outer["bbox"][3] - outer["bbox"][1]) - 180) <= 3
    assert abs((inner["bbox"][2] - inner["bbox"][0]) - 160) <= 3
    # A radius read on the wrong row is half the width, so anything near 90 is
    # the failure this test exists for.
    assert 10 <= outer["radius"] <= 22
    assert inner["radius"] <= 14


def test_the_frame_carries_its_tilt(tmp_path: Path) -> None:
    image = _tilted_shot(tmp_path / "shot.png")
    design = _design(_rotated_box(LABEL, SIDE))

    calibrated, report = synthesize_badge_outline(design, image)

    assert abs(report["badges"][0]["rotation"] - TILT) <= 0.4
    assert report["badges"][0]["deskewed"] is True
    for element in calibrated["elements"][:2]:
        assert element["type"] == "rectangle"
        assert abs(float(element["rotation"]) - TILT) <= 0.4


def test_the_second_ring_is_its_own_element(tmp_path: Path) -> None:
    image = _tilted_shot(tmp_path / "shot.png")
    design = _design(_rotated_box(LABEL, SIDE))

    calibrated, report = synthesize_badge_outline(design, image)

    elements = calibrated["elements"]
    # In place, plus one new node for the inner stroke, then the untouched label.
    assert len(elements) == 3
    assert elements[0]["id"] == "asset:badge"
    assert elements[1]["id"] == "asset:badge:ring1"
    assert elements[2]["text"] == "5.8折"
    assert elements[1]["style"]["borderWidth"] == report["badges"][0]["rings"][1]["stroke"]
    # Same centre: a concentric stroke is not offset from the badge.
    for axis in ("x", "y"):
        first = float(elements[0][axis]) + float(elements[0]["width" if axis == "x" else "height"]) / 2
        second = float(elements[1][axis]) + float(elements[1]["width" if axis == "x" else "height"]) / 2
        assert abs(first - second) <= 1.5


def test_an_upright_single_stroke_keeps_the_old_shape(tmp_path: Path) -> None:
    image = Image.new("RGB", (400, 300), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((100, 100, 219, 149), radius=10, outline=ACCENT, width=3)
    for box in ((120, 115, 135, 135), (142, 115, 160, 135)):
        draw.rectangle(box, fill=ACCENT)
    shot = tmp_path / "upright.png"
    image.save(shot)
    design = _design([115.0, 110.0, 190.0, 140.0])

    calibrated, report = synthesize_badge_outline(design, shot)

    badge = report["badges"][0]
    assert len(badge["rings"]) == 1
    assert badge["rotation"] == 0.0
    assert badge["deskewed"] is False
    # No second stroke, so nothing was added: the element count is untouched.
    assert len(calibrated["elements"]) == 2
