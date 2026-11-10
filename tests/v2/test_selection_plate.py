"""Selection-plate synthesis: recover the filled tab behind a header label.

The numbers are the ones measured on dark-card-grid: the plate behind 模型广场
spans x 544-712, y 23-87 and fills ``#CC291F``; the label box is 561,35,130,42.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.app.services.structure.fidelity.text_calibration import (
    synthesize_selection_plate,
)


def _screenshot(
    path: Path,
    *,
    plate: tuple[int, int, int, int, tuple[int, int, int]] | None = None,
    size: tuple[int, int] = (400, 300),
    background: tuple[int, int, int] = (26, 25, 23),
) -> Path:
    image = Image.new("RGB", size, background)
    if plate is not None:
        x0, y0, x1, y1, color = plate
        for y in range(y0, y1):
            for x in range(x0, x1):
                image.putpixel((x, y), color)
    image.save(path)
    return path


def _design(elements: list[dict], height: float = 600.0) -> dict:
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
        "style": {"fontSize": 24, "fontWeight": "normal"},
    }


def test_filled_tab_gets_a_plate_behind_it(tmp_path: Path) -> None:
    image = _screenshot(
        tmp_path / "shot.png", plate=(40, 12, 160, 56, (204, 41, 31))
    )
    design = _design([_label("模型广场", 55, 22, 90, 28)])

    calibrated, report = synthesize_selection_plate(design, image)

    assert report["status"] == "applied"
    assert report["adjusted_count"] == 1
    plate = report["plates"][0]
    assert plate["bbox"] == [40.0, 12.0, 160.0, 56.0]
    assert plate["fillColor"] == "#CC291F"
    first = calibrated["elements"][0]
    assert first["type"] == "rectangle"
    assert first["paintDepth"] == 0
    assert first["style"]["fillColor"] == "#CC291F"
    # The label survives, after the plate.
    assert calibrated["elements"][1]["text"] == "模型广场"
    assert len(calibrated["elements"]) == 2


def test_plain_background_gets_no_plate(tmp_path: Path) -> None:
    image = _screenshot(tmp_path / "shot.png")
    design = _design([_label("首页", 55, 22, 90, 28)])

    calibrated, report = synthesize_selection_plate(design, image)

    assert report["status"] == "not-needed"
    assert len(calibrated["elements"]) == 1


def test_label_outside_the_header_band_is_ignored(tmp_path: Path) -> None:
    image = _screenshot(
        tmp_path / "shot.png",
        plate=(40, 212, 160, 256, (204, 41, 31)),
        size=(400, 300),
    )
    design = _design([_label("正文标题", 55, 222, 90, 28)])

    _, report = synthesize_selection_plate(design, image)

    assert report["adjusted_count"] == 0


def test_existing_shape_covering_the_plate_is_respected(tmp_path: Path) -> None:
    image = _screenshot(
        tmp_path / "shot.png", plate=(40, 12, 160, 56, (204, 41, 31))
    )
    design = _design(
        [
            {
                "type": "image",
                "x": 40,
                "y": 12,
                "width": 120,
                "height": 44,
                "text": "",
                "style": {},
            },
            _label("模型广场", 55, 22, 90, 28),
        ]
    )

    calibrated, report = synthesize_selection_plate(design, image)

    assert report["adjusted_count"] == 0
    assert len(calibrated["elements"]) == 2


def test_missing_screenshot_is_not_fatal(tmp_path: Path) -> None:
    design = _design([_label("模型广场", 55, 22, 90, 28)])

    calibrated, report = synthesize_selection_plate(
        design, tmp_path / "does-not-exist.png"
    )

    assert report["status"] == "not-needed"
    assert len(calibrated["elements"]) == 1
