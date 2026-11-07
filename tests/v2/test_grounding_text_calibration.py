from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.structure.fidelity.text_calibration import (
    calibrate_control_fonts,
    calibrate_form_fonts_from_render,
    calibrate_form_positions_from_render,
    calibrate_form_text_positions,
    calibrate_table_fonts_from_render,
    calibrate_table_positions,
    calibrate_table_positions_from_render,
    calibrate_toolbar_letter_spacing_from_render,
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


def test_table_font_calibration_uses_reference_and_render_ink(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 59, 27)),
        (rendered, (20, 20, 39, 25)),
    ):
        image = Image.new("RGB", (100, 50), "white")
        ImageDraw.Draw(image).rectangle(box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "table-cell:time",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "2026-11-01 03:30:00",
                "style": {"fontSize": 10},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 40, 8],
                    }
                },
            }
        ]
    }

    calibrated, report = calibrate_table_fonts_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][0]["style"]["fontSize"] == 20
    assert report["adjusted_count"] == 1


def test_table_position_calibration_uses_render_ink(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 59, 27)),
        (rendered, (30, 25, 69, 32)),
    ):
        image = Image.new("RGB", (100, 50), "white")
        ImageDraw.Draw(image).rectangle(box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "table-cell:time",
                "type": "text",
                "x": 100,
                "y": 100,
                "text": "2026-11-01 03:30:00",
                "style": {"fontSize": 16},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 40, 8],
                    }
                },
            }
        ]
    }

    calibrated, report = calibrate_table_positions_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][0]["x"] == 90
    assert calibrated["elements"][0]["y"] == 95
    assert report["adjusted_count"] == 1


def test_form_font_calibration_groups_by_type_size_and_script(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 49, 27)),
        (rendered, (20, 20, 39, 25)),
    ):
        image = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(image).rectangle(box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "id": "form",
                "type": "container",
                "role": "form-section",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 100,
            },
            {
                "contentRef": "text:form",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "Form label",
                "style": {"fontSize": 10},
                "styleEvidence": {
                    "evidence": {
                        "script": "cjk",
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 30, 8],
                    }
                },
            },
        ]
    }

    calibrated, report = calibrate_form_fonts_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][1]["style"]["fontSize"] == 15
    assert report["adjusted_count"] == 1


def test_form_position_calibration_moves_text_box_only(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 59, 27)),
        (rendered, (30, 25, 69, 32)),
    ):
        image = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(image).rectangle(box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "id": "form",
                "type": "container",
                "role": "form-section",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 100,
            },
            {
                "contentRef": "control:form",
                "type": "input",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 40,
                "text": "auto",
                "textBox": [10, 10, 60, 20],
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 40, 8],
                    }
                },
            },
        ]
    }
    readback = {
        "children": [
            {
                "type": "TEXT",
                "characters": "auto",
                "bounds": {"x": 10, "y": 10, "width": 20, "height": 16},
            }
        ]
    }

    calibrated, report = calibrate_form_positions_from_render(
        design,
        readback,
        str(reference),
        str(rendered),
    )
    control = calibrated["elements"][1]

    assert control["x"] == 0
    assert control["y"] == 0
    assert control["textBox"] == [0, 5, 20, 16]
    assert report["adjusted_count"] == 1


def test_toolbar_letter_spacing_uses_ink_width_delta(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 69, 32)),
        (rendered, (20, 20, 59, 32)),
    ):
        image = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(image).rectangle(box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "id": "toolbar",
                "type": "container",
                "role": "table-header-controls",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 50,
            },
            {
                "contentRef": "control:toolbar",
                "type": "button",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 40,
                "text": "ABCDEF",
                "style": {"fontSize": 16},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 50, 12],
                    }
                },
            },
        ]
    }

    calibrated, report = calibrate_toolbar_letter_spacing_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][1]["style"]["letterSpacing"] == 2.0
    assert report["adjusted_count"] == 1


def test_form_text_position_calibration_uses_target_ink() -> None:
    design = {
        "elements": [
            {
                "id": "form-label",
                "type": "text",
                "x": 1366,
                "y": 142,
                "text": "执行时间",
                "contentRef": "form-label",
                "style": {"fontSize": 15.25},
                "imageMVP": {"role": "form-label"},
                "styleEvidence": {"evidence": {"ink_bbox": [1371, 147, 67, 16]}},
            },
            {
                "id": "header",
                "type": "text",
                "x": 461,
                "y": 24,
                "text": "自动备份",
                "contentRef": "header",
                "style": {"fontSize": 15.25},
                "imageMVP": {"role": "text"},
                "styleEvidence": {"evidence": {"ink_bbox": [462, 26, 65, 16]}},
            },
        ]
    }
    readback = {
        "children": [
            {
                "type": "TEXT",
                "characters": "执行时间",
                "bounds": {"x": 1366, "y": 142, "width": 61, "height": 18},
            },
            {
                "type": "TEXT",
                "characters": "自动备份",
                "bounds": {"x": 461, "y": 24, "width": 61, "height": 18},
            },
        ]
    }

    calibrated, report = calibrate_form_text_positions(design, readback)

    assert calibrated["elements"][0]["x"] == 1371
    assert calibrated["elements"][0]["y"] == 147
    assert calibrated["elements"][1]["x"] == 461
    assert calibrated["elements"][1]["y"] == 24
    assert report["adjusted_count"] == 1
