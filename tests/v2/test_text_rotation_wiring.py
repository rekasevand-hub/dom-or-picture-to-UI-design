"""Rotation wiring: the field has to survive from measurement to pixels.

Two ends are covered here because they fail differently:

* ``apply_text_rotation`` decides **whether** a block is tilted and writes the
  field.  Its failure mode is a false positive -- rotating straight text.
* ``SVGMockAdapter`` turns the field into a ``<g transform="rotate(...)">``
  around the box centre, which is the same pivot Figma's ``node.rotation``
  uses.  Its failure mode is a silent no-op: the design says rotated, the
  render looks straight, and the ink loop then chases a ghost.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.rendering.svg_adapter import SVGMockAdapter  # noqa: E402
from src.app.services.structure.fidelity.text_calibration import (  # noqa: E402
    apply_text_rotation,
)

BACKGROUND = (26, 25, 23)
ACCENT = (240, 89, 67)


def _screenshot(path: Path, degrees: float) -> Path:
    """Three bars on a dark page, rotated by ``degrees`` counter-clockwise."""
    image = Image.new("RGB", (300, 220), BACKGROUND)
    draw = ImageDraw.Draw(image)
    for top, bottom, left, right in (
        (70, 86, 40, 250),
        (110, 126, 40, 210),
        (150, 166, 40, 230),
    ):
        draw.rectangle((left, top, right, bottom), fill=ACCENT)
    image.rotate(degrees, resample=Image.BICUBIC, fillcolor=BACKGROUND).save(path)
    return path


def _design(rotation: float | None = None) -> dict:
    element = {
        "type": "text",
        "x": 40,
        "y": 70,
        "width": 210,
        "height": 100,
        "text": "5.8折",
        "style": {"fontSize": 34},
    }
    if rotation is not None:
        element["rotation"] = rotation
    return {"canvas": {"width": 300, "height": 220}, "elements": [element]}


def test_tilted_block_gets_the_measured_angle(tmp_path: Path) -> None:
    image = _screenshot(tmp_path / "shot.png", 5.0)

    calibrated, report = apply_text_rotation(_design(), image)

    assert report["status"] == "applied"
    assert report["adjusted_count"] == 1
    assert abs(report["rotations"][0]["angle"] - 5.0) <= 0.75
    assert calibrated["elements"][0]["rotation"] == report["rotations"][0]["angle"]
    # Evidence travels with the decision, per the repo's auditability rule.
    assert report["rotations"][0]["ink"] > 30
    assert report["rotations"][0]["bbox"] == [40.0, 70.0, 210.0, 100.0]


def test_upright_block_gets_no_field(tmp_path: Path) -> None:
    image = _screenshot(tmp_path / "shot.png", 0.0)

    calibrated, report = apply_text_rotation(_design(), image)

    assert report["status"] == "not-needed"
    assert "rotation" not in calibrated["elements"][0]


def test_stale_rotation_is_cleared(tmp_path: Path) -> None:
    image = _screenshot(tmp_path / "shot.png", 0.0)

    calibrated, report = apply_text_rotation(_design(rotation=7.0), image)

    # A second pass over an unchanged screenshot must not keep an old angle:
    # otherwise a re-measurement that says "upright" would silently do nothing.
    assert "rotation" not in calibrated["elements"][0]
    assert report["cleared"] == ["5.8折"]


def test_missing_screenshot_is_not_fatal(tmp_path: Path) -> None:
    calibrated, report = apply_text_rotation(
        _design(rotation=7.0), tmp_path / "does-not-exist.png"
    )

    assert report["status"] == "not-needed"
    # Nothing measured means nothing decided -- the stale field is left alone
    # rather than cleared on the strength of a failed read.
    assert calibrated["elements"][0]["rotation"] == 7.0


def test_svg_wraps_the_element_and_keeps_the_centre(tmp_path: Path) -> None:
    adapter = SVGMockAdapter(tmp_path / "out.svg")
    element = {
        "type": "rectangle",
        "x": 100,
        "y": 50,
        "width": 80,
        "height": 40,
        "style": {"fillColor": "#F05943"},
        "rotation": 6.0,
    }

    adapter.render_design({"canvas": {"width": 300, "height": 220}, "elements": [element]})

    groups = [node for node in adapter.elements if node.tag == "g"]
    assert len(groups) == 1
    # Centre of the box, not of the canvas: Figma rotates a node about its own
    # centre, so a different pivot here would put the same angle in two places.
    assert groups[0].get("transform") == "rotate(6 140 70)"


def test_svg_without_rotation_stays_bare(tmp_path: Path) -> None:
    adapter = SVGMockAdapter(tmp_path / "out.svg")
    element = {
        "type": "rectangle",
        "x": 100,
        "y": 50,
        "width": 80,
        "height": 40,
        "style": {"fillColor": "#F05943"},
    }

    adapter.render_design({"canvas": {"width": 300, "height": 220}, "elements": [element]})

    assert not [node for node in adapter.elements if node.tag == "g"]
