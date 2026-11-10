"""Fragment-image rule: a crop that carries the first letters of a label.

Geometry below is taken from the benchmark runs, not invented:

* dark-card-grid: the 102x43 logo crops at (1333, 1293) and (148, 647) hold the
  first letters of ``Qwen3.8 Flash`` / ``DeepSeek V4.1 Flash``;
* light-form: four nested crops at (760..820, 245..249) sit on ``执行成功``;
* light-card-grid badges (``8.5折``) are wider than their label and stay.
"""

from __future__ import annotations

import copy

from src.app.services.structure.fidelity.text_calibration import (
    drop_text_fragment_images,
)


def _image(x: float, y: float, width: float, height: float, ref: str = "asset:x") -> dict:
    return {
        "type": "image",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "text": "",
        "contentRef": ref,
        "style": {},
    }


def _text(
    text: str, x: float, y: float, width: float, height: float, kind: str = "text"
) -> dict:
    return {
        "type": kind,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "text": text,
        "contentRef": f"{kind}:{text}",
        "style": {"fontSize": 30, "fontWeight": "normal"},
    }


def _design(elements: list[dict]) -> dict:
    return {"canvas": {"width": 2544, "height": 1336}, "elements": elements}


def test_logo_crop_holding_the_first_letters_is_dropped() -> None:
    design = _design(
        [
            _image(1333, 1293, 102, 43),
            _text("Qwen3.8 Flash", 1394, 1293, 213, 43),
        ]
    )

    calibrated, report = drop_text_fragment_images(design)

    assert report["status"] == "applied"
    assert report["adjusted_count"] == 1
    assert report["dropped"][0]["overlapped_text"] == "Qwen3.8 Flash"
    assert [item["type"] for item in calibrated["elements"]] == ["text"]


def test_crop_that_starts_at_the_text_origin_is_dropped() -> None:
    """Kimi K3: the crop begins exactly where the wordmark begins."""
    design = _design(
        [
            _image(148, 1293, 102, 43),
            _text("Kimi K3", 148, 1293, 116, 45),
        ]
    )

    calibrated, report = drop_text_fragment_images(design)

    assert report["adjusted_count"] == 1
    assert report["dropped"][0]["overlap_ratio"] == 1.0
    assert calibrated["elements"][0]["type"] == "text"


def test_badge_background_wider_than_its_label_survives() -> None:
    """8.5折: the badge ends past the label, so it is a background, not a crop."""
    design = _design(
        [
            _image(1099, 1293, 153, 43),
            _text("8.5折", 1118, 1306, 57, 29),
        ]
    )

    calibrated, report = drop_text_fragment_images(design)

    assert report["status"] == "not-needed"
    assert len(calibrated["elements"]) == 2


def test_icon_inside_a_text_box_is_dropped() -> None:
    """light-form 执行成功: 48x23 crop sits on the first two glyphs."""
    design = _design(
        [
            _image(820, 245, 48, 23),
            _text("执行成功", 760, 248, 123, 17),
        ]
    )

    _, report = drop_text_fragment_images(design)

    assert report["adjusted_count"] == 1
    assert report["dropped"][0]["bbox"] == [820.0, 245.0, 868.0, 268.0]


def test_full_bleed_image_is_never_dropped() -> None:
    """A 1744x448 panel is wider than every label inside it."""
    design = _design(
        [
            _image(0, 0, 1744, 448),
            _text("SUCCESS", 100, 30, 123, 20),
        ]
    )

    _, report = drop_text_fragment_images(design)

    assert report["adjusted_count"] == 0


def test_price_shorter_than_the_crop_is_not_a_fragment() -> None:
    """¥2.00 next to a 43 px logo crop: the crop ends past the price."""
    design = _design(
        [
            _image(148, 647, 102, 43),
            _text("¥2.00", 124, 664, 39, 21),
        ]
    )

    _, report = drop_text_fragment_images(design)

    assert report["adjusted_count"] == 0


def test_input_design_is_not_mutated() -> None:
    design = _design(
        [
            _image(1333, 1293, 102, 43),
            _text("Qwen3.8 Flash", 1394, 1293, 213, 43),
        ]
    )
    before = copy.deepcopy(design)

    drop_text_fragment_images(design)

    assert design == before
