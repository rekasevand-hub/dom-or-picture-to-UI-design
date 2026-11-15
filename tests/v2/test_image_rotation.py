"""Rotation has to mean the same thing at three ends: design, SVG, Figma.

The design speaks degrees anticlockwise.  SVG's `rotate()` turns clockwise, and
Figma both turns clockwise *and* pivots about the node's own origin — so a naive
`node.rotation = angle` moves the shape as well as turning it.  These tests pin
the sign, the pivot and the compensation before any of it touches a screenshot.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.app.services.structure.fidelity.rotation import (
    element_centre,
    estimate_rotation,
    figma_origin,
    normalise_angle,
    svg_transform,
)


def _centre_after(origin, size, angle) -> tuple[float, float]:
    """Where Figma would put the centre: origin + R(θ)·(w/2, h/2)."""
    theta = math.radians(-angle)
    cos = math.cos(theta)
    sin = math.sin(theta)
    half_w, half_h = size[0] / 2.0, size[1] / 2.0
    return (
        origin[0] + half_w * cos - half_h * sin,
        origin[1] + half_w * sin + half_h * cos,
    )


# --- 角度本身 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [(0, 0.0), (1.4, 0.0), (-1.9, 0.0), (2.0, 2.0), (6, 6.0), (-6, -6.0), (190, -170.0), (-190, 170.0)],
)
def test_angles_fold_into_a_named_range(raw, expected) -> None:
    assert normalise_angle(raw) == pytest.approx(expected)


def test_a_missing_angle_is_level() -> None:
    assert normalise_angle(None) == 0.0
    assert normalise_angle("nonsense") == 0.0
    assert normalise_angle(float("nan")) == 0.0


# --- 中心补偿 ---------------------------------------------------------------


def test_at_zero_degrees_the_origin_is_the_plain_top_left() -> None:
    assert figma_origin((100.0, 50.0), 40.0, 20.0, 0.0) == (80.0, 40.0)


@pytest.mark.parametrize("angle", [6.0, -6.0, 30.0, 90.0, 135.0])
def test_the_compensated_origin_keeps_the_centre(angle) -> None:
    centre = (400.0, 300.0)
    size = (200.0, 100.0)

    origin = figma_origin(centre, size[0], size[1], angle)
    landed = _centre_after(origin, size, angle)

    assert landed[0] == pytest.approx(centre[0], abs=0.01)
    assert landed[1] == pytest.approx(centre[1], abs=0.01)


def test_the_origin_actually_moves_when_the_box_turns() -> None:
    """No compensation = the shape walks; this is the bug being prevented."""
    assert figma_origin((400.0, 300.0), 200.0, 100.0, 45.0) != (300.0, 250.0)


# --- SVG 端 -----------------------------------------------------------------


def test_a_level_element_emits_no_transform() -> None:
    assert svg_transform({"x": 10, "y": 20, "width": 100, "height": 50}) == ""


def test_svg_rotates_about_the_centre_and_negates_the_sign() -> None:
    element = {"x": 10, "y": 20, "width": 100, "height": 50, "rotation": 6}
    assert svg_transform(element) == "rotate(-6 60 45)"


def test_centre_is_the_box_centre() -> None:
    assert element_centre({"x": 10, "y": 20, "width": 100, "height": 50}) == (60.0, 45.0)


def test_a_rotated_rect_keeps_its_ink_centred(tmp_path) -> None:
    """The whole point: the shape turns, the centre does not move."""
    from src.app.services.rendering.adapter_factory import build_adapter
    from src.app.utils.svg_raster import rasterize_svg
    from dataclasses import replace

    from src.config import load_config

    design = {
        "canvas": {"width": 240, "height": 200, "background": "#ffffff"},
        "elements": [
            {
                "id": "stamp",
                "type": "container",
                "role": "panel",
                "x": 70,
                "y": 60,
                "width": 100,
                "height": 80,
                "rotation": 12,
                "style": {"fillColor": "#202020", "borderRadius": 8},
            }
        ],
    }
    out = tmp_path / "rot"
    out.mkdir(parents=True, exist_ok=True)
    adapter = build_adapter("svg", replace(load_config(), output_dir=out))
    adapter.render_design(design)
    rasterize_svg(out / "prototype.svg", out / "render.png", device_scale_factor=1)

    svg = (out / "prototype.svg").read_text(encoding="utf-8")
    assert 'transform="rotate(-12 120 100)"' in svg

    pixels = np.asarray(__import__("PIL.Image", fromlist=["Image"]).open(out / "render.png").convert("L"))
    ink = np.argwhere(pixels < 128)
    assert ink.size
    centre_y, centre_x = ink.mean(axis=0)
    assert centre_x == pytest.approx(120.0, abs=1.0)
    assert centre_y == pytest.approx(100.0, abs=1.0)


# --- 从像素量倾角 -----------------------------------------------------------


def _tilted_box(tmp_path, angle: float) -> str:
    import cv2

    page = np.full((240, 320, 3), 255, dtype=np.uint8)
    box = cv2.boxPoints(((160, 120), (140, 70), angle)).astype(np.int32)
    cv2.fillPoly(page, [box], (30, 30, 30))
    path = tmp_path / f"tilt{angle}.png"
    cv2.imwrite(str(path), page[:, :, ::-1])
    return str(path)


@pytest.mark.parametrize("angle", [6.0, 12.0, -8.0])
def test_minarearect_recovers_a_boxes_tilt(tmp_path, angle) -> None:
    import cv2

    image = cv2.imread(_tilted_box(tmp_path, angle))
    measured = estimate_rotation(image, (80, 70, 160, 110))

    assert measured == pytest.approx(angle, abs=1.5)


def test_a_level_region_measures_level(tmp_path) -> None:
    import cv2

    image = cv2.imread(_tilted_box(tmp_path, 0.0))
    assert estimate_rotation(image, (80, 70, 160, 110)) == 0.0


def test_a_flat_region_has_no_angle_to_report(tmp_path) -> None:
    page = np.full((120, 120, 3), 255, dtype=np.uint8)
    path = tmp_path / "flat.png"
    import cv2

    cv2.imwrite(str(path), page[:, :, ::-1])
    assert estimate_rotation(cv2.imread(str(path)), (20, 20, 60, 60)) == 0.0


# --- 适配器到插件的契约 -----------------------------------------------------


def test_the_figma_adapter_asks_for_the_design_centre(monkeypatch) -> None:
    """The adapter must send the centre the design asked for, not the box corner."""
    from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter

    sent: list[tuple[str, dict]] = []

    class Fake(FigmaBridgeAdapter):
        def __init__(self) -> None:  # noqa: D107 - no socket in a unit test
            pass

        def _send(self, action, params=None, **kwargs):  # noqa: ANN001
            sent.append((action, dict(params or {})))
            return "1:1"

        def _record_semantic_node(self, *args, **kwargs):  # noqa: ANN002
            return None

    adapter = Fake()
    spec = {
        "x": 100,
        "y": 50,
        "width": 200,
        "height": 100,
        "rotation": 6,
        "fillColor": "#202020",
    }
    adapter.create_rectangle(spec)

    rotations = [params for action, params in sent if action == "set_rotation"]
    assert rotations, "a rotated element has to reach the bridge"
    assert rotations[0]["angle"] == pytest.approx(6.0)
    assert rotations[0]["centre"] == [pytest.approx(200.0), pytest.approx(100.0)]


def test_a_level_element_never_asks(monkeypatch) -> None:
    from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter

    sent: list[str] = []

    class Fake(FigmaBridgeAdapter):
        def __init__(self) -> None:  # noqa: D107
            pass

        def _send(self, action, params=None, **kwargs):  # noqa: ANN001
            sent.append(action)
            return "1:1"

        def _record_semantic_node(self, *args, **kwargs):  # noqa: ANN002
            return None

    adapter = Fake()
    adapter.create_rectangle({"x": 10, "y": 10, "width": 40, "height": 20})
    assert "set_rotation" not in sent
