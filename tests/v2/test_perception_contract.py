"""Regression tests for the input-adaptive perception contract."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from src.app.services.structure.fidelity.perception_contract import (
    LEGACY_CONTRAST_THRESHOLD,
    evaluate_native_fidelity,
    ink_support,
    recover_text_evidence,
    run_perception_contract,
)


def _image(size: tuple[int, int], background: tuple[int, int, int]):
    return Image.new("RGB", size, background)


def _draw_text(
    image: Image.Image,
    xy: tuple[int, int],
    text: str,
    color: tuple[int, int, int],
) -> None:
    ImageDraw.Draw(image).text(xy, text, fill=color)


def test_adaptive_threshold_detects_low_contrast_dark_theme_text(tmp_path) -> None:
    """Legacy fixed threshold misses light-on-low-contrast text."""
    image = _image((320, 120), (26, 25, 23))
    _draw_text(image, (20, 40), "Seedance 2.0", (40, 39, 37))
    array = np.asarray(image, dtype=np.int16)
    bbox = [12, 32, 200, 40]

    legacy = ink_support(array, bbox, threshold=LEGACY_CONTRAST_THRESHOLD)
    adaptive = ink_support(array, bbox)

    assert legacy["inkPixelCount"] == 0
    assert adaptive["inkPixelCount"] > 0
    assert adaptive["ink_bbox"] is not None
    assert adaptive["threshold"] < LEGACY_CONTRAST_THRESHOLD


def test_normalized_y_axis_is_recovered_from_pixel_evidence() -> None:
    """VLM returns y in 0..1000 space; the inverse transform must be chosen."""
    height, width = 1336, 2544
    image = _image((width, height), (26, 25, 23))
    _draw_text(image, (150, 840), "INPUT PEAK 1.16", (235, 232, 225))
    array = np.asarray(image, dtype=np.int16)
    # 840 / 1336 * 1000 = 629 -> what the VLM reports as "y"
    broken_bbox = [148, 629, 260, 20]

    recovery = recover_text_evidence(array, broken_bbox, text="INPUT PEAK 1.16")

    assert recovery["status"] == "recovered"
    assert recovery["provenance"] in {"y-axis-1000", "y+height-1000"}
    assert recovery["bbox"][1] >= 800
    assert recovery["evidence"]["ink_bbox"] is not None


def test_verified_design_is_never_mutated(tmp_path) -> None:
    """A calibrated sample with isolated defects must not be repaired."""
    image = _image((320, 200), (255, 255, 255))
    _draw_text(image, (20, 40), "Verified", (30, 30, 30))
    path = tmp_path / "reference.png"
    image.save(path)

    design = {
        "canvas": {"width": 320, "height": 200},
        "elements": [
            {
                "id": "text:ok",
                "type": "text",
                "x": 20,
                "y": 40,
                "width": 120,
                "height": 24,
                "text": "Verified",
                "contentRef": "text:ok",
                "style": {"fontSize": 16.0, "textColor": "#1e1e1e"},
                "styleEvidence": {
                    "evidence": {
                        "status": "observed",
                        "source_bbox": [12, 32, 140, 36],
                        "ink_bbox": [20, 40, 80, 16],
                    }
                },
            }
        ],
    }
    repaired, report = run_perception_contract(design, path, mode="adaptive")

    assert report["status"] == "verified"
    assert report["policy"]["applyRepair"] is False
    assert repaired["elements"] == design["elements"]


def test_systematic_coordinate_drift_triggers_repair(tmp_path) -> None:
    """Many boxes explained by one inverse transform must be repaired."""
    height, width = 1336, 1200
    image = _image((width, height), (26, 25, 23))
    for index in range(4):
        _draw_text(
            image,
            (60, 400 + index * 200),
            f"ROW-{index}",
            (230, 228, 220),
        )
    path = tmp_path / "tall.png"
    image.save(path)
    elements = []
    for index in range(4):
        # VLM reported y in the 0..1000 normalized space.
        normalized_y = int((400 + index * 200) / height * 1000)
        elements.append(
            {
                "id": f"text:{index}",
                "type": "text",
                "x": 55,
                "y": normalized_y,
                "width": 180,
                "height": 24,
                "text": f"ROW-{index}",
                "contentRef": f"text:{index}",
                "style": {"fontSize": 16.0, "textColor": "#555555"},
                "styleEvidence": {
                    "evidence": {
                        "status": "low-confidence",
                        "reason": "text-ink-not-found",
                        "source_bbox": [55, normalized_y, 180, 24],
                    }
                },
            }
        )
    design = {"canvas": {"width": width, "height": height}, "elements": elements}
    ocr = {
        "observations": [
            {
                "text": f"ROW-{index}",
                "bbox": [55, 400 + index * 200, 180, 24],
                "confidence": 0.9,
            }
            for index in range(4)
        ]
    }
    repaired, report = run_perception_contract(
        design, path, ocr_supplement=ocr, mode="adaptive"
    )

    assert report["policy"]["systematicCoordinateDrift"] is True
    assert report["repair"]["applied"] is True
    assert report["counts"]["unverified"] == 0
    for element in repaired["elements"]:
        assert element["styleEvidence"]["evidence"]["ink_bbox"] is not None
        assert element["y"] > 350


def test_native_fidelity_excludes_raster_underlay(tmp_path) -> None:
    """Pixel error on a literal screenshot crop must not inflate the metric."""
    reference = _image((100, 60), (20, 20, 20))
    _draw_text(reference, (10, 10), "AAA", (240, 240, 240))
    export = _image((100, 60), (20, 20, 20))
    _draw_text(export, (10, 10), "BBB", (240, 240, 240))
    reference_path = tmp_path / "reference.png"
    export_path = tmp_path / "export.png"
    reference.save(reference_path)
    export.save(export_path)
    design = {
        "elements": [
            {
                "type": "image",
                "x": 0,
                "y": 30,
                "width": 100,
                "height": 30,
            }
        ]
    }
    result = evaluate_native_fidelity(design, reference_path, export_path)

    assert result["status"] == "measured"
    assert result["rasterUnderlayRatio"] > 0.4
    assert result["nativeOnlyBadPixelRatio"] > 0.0
    assert (
        result["nativeOnlyBadPixelRatio"]
        >= result["overallBadPixelRatio"]
    )
