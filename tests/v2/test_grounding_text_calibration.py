from __future__ import annotations

from src.app.services.structure.fidelity.text_calibration import (
    calibrate_control_fonts,
)


def test_control_font_calibration_uses_rendered_text_width() -> None:
    design = {
        "elements": [
            {
                "id": "control:copy",
                "type": "button",
                "x": 448,
                "y": 503,
                "text": "复制",
                "contentRef": "control:copy",
                "style": {"fontSize": 14.25},
                "styleEvidence": {"evidence": {"ink_bbox": [462, 513, 34, 15]}},
            }
        ]
    }
    readback = {
        "type": "FRAME",
        "children": [
            {
                "type": "TEXT",
                "characters": "复制",
                "bounds": {"x": 464.5, "y": 511.5, "width": 29, "height": 17},
            }
        ],
    }

    calibrated, report = calibrate_control_fonts(design, readback)

    assert calibrated["elements"][0]["style"]["fontSize"] > 14.25
    assert report["adjusted_count"] == 1


def test_control_font_calibration_does_not_touch_body_text() -> None:
    design = {
        "elements": [
            {
                "id": "text:body",
                "type": "text",
                "x": 10,
                "y": 10,
                "text": "Body",
                "contentRef": "text:body",
                "style": {"fontSize": 12},
                "styleEvidence": {"evidence": {"ink_bbox": [10, 10, 80, 20]}},
            }
        ]
    }

    calibrated, report = calibrate_control_fonts(design, {"children": []})

    assert calibrated["elements"][0]["style"]["fontSize"] == 12
    assert report["status"] == "not-needed"
