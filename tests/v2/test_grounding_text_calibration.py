from __future__ import annotations

from src.app.services.structure.fidelity.text_calibration import (
    calibrate_control_fonts,
    calibrate_table_positions,
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


def test_table_position_calibration_aligns_rendered_and_source_ink() -> None:
    design = {
        "elements": [
            {
                "id": "table-cell:time",
                "type": "text",
                "x": 413,
                "y": 614,
                "text": "2026-11-01 03:30:00",
                "contentRef": "table-cell:time",
                "style": {"fontSize": 11.5},
                "styleEvidence": {"evidence": {"ink_bbox": [413, 614, 151, 12]}},
            }
        ]
    }
    readback = {
        "children": [
            {
                "type": "TEXT",
                "characters": "2026-11-01 03:30:00",
                "bounds": {"x": 428, "y": 614, "width": 109, "height": 16},
            }
        ]
    }

    calibrated, report = calibrate_table_positions(design, readback)
    cell = calibrated["elements"][0]

    assert cell["x"] == 398
    assert cell["y"] == 614
    assert cell["style"]["fontSize"] == 11.5
    assert report["adjusted_count"] == 1


def test_table_position_calibration_does_not_touch_header() -> None:
    design = {
        "elements": [
            {
                "id": "table-header:time",
                "type": "text",
                "x": 388,
                "y": 550,
                "text": "Time",
                "contentRef": "table-header:time",
                "style": {"fontSize": 15.25},
                "styleEvidence": {"evidence": {"ink_bbox": [449, 566, 67, 16]}},
            }
        ]
    }

    calibrated, report = calibrate_table_positions(design, {"children": []})

    assert calibrated["elements"][0]["x"] == 388
    assert report["status"] == "not-needed"
