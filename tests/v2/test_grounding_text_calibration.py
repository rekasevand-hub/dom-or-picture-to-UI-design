from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.structure.fidelity.text_calibration import (
    calibrate_control_fonts,
    calibrate_form_fonts_from_render,
    calibrate_form_positions_from_render,
    calibrate_form_text_shape_from_render,
    calibrate_form_text_weight_from_render,
    calibrate_form_text_positions,
    calibrate_low_contrast_placeholder_from_render,
    calibrate_search_control_from_render,
    calibrate_table_fonts_from_render,
    calibrate_table_letter_spacing_from_render,
    calibrate_table_positions,
    calibrate_table_positions_from_render,
    calibrate_toolbar_font_weight_from_render,
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


def test_table_font_calibration_does_not_width_scale_single_character(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 27, 31)),
        (rendered, (20, 20, 22, 27)),
    ):
        image = Image.new("RGB", (100, 50), "white")
        ImageDraw.Draw(image).rectangle(box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "table-cell:number",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "2",
                "style": {"fontSize": 11.5},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 8, 12],
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

    assert calibrated["elements"][0]["style"]["fontSize"] == 11.5
    assert report["adjusted_count"] == 0


def test_table_font_calibration_does_not_width_scale_two_character_cell(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 37, 31)),
        (rendered, (20, 20, 26, 27)),
    ):
        image = Image.new("RGB", (100, 50), "white")
        ImageDraw.Draw(image).rectangle(box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "table-cell:number",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "10",
                "style": {"fontSize": 11.5},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 18, 12],
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

    assert calibrated["elements"][0]["style"]["fontSize"] == 11.5
    assert report["adjusted_count"] == 0


def test_table_font_calibration_single_character_inherits_group_size(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, boxes in (
        (
            reference,
            [(20, 20, 59, 27), (20, 40, 27, 47)],
        ),
        (
            rendered,
            [(20, 20, 39, 25), (20, 40, 22, 45)],
        ),
    ):
        image = Image.new("RGB", (100, 60), "white")
        draw = ImageDraw.Draw(image)
        for box in boxes:
            draw.rectangle(box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "table-cell:date",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "2026-11-01 03:30:00",
                "style": {"fontSize": 10},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 30],
                        "ink_bbox": [20, 20, 40, 8],
                    }
                },
            },
            {
                "contentRef": "table-cell:number",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "2",
                "style": {"fontSize": 10},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 30, 100, 30],
                        "ink_bbox": [20, 40, 8, 8],
                    }
                },
            },
        ]
    }

    calibrated, report = calibrate_table_fonts_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][0]["style"]["fontSize"] == 20
    assert calibrated["elements"][1]["style"]["fontSize"] == 20
    assert report["adjusted_count"] == 2


def test_table_font_calibration_does_not_group_scale_single_character_header(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, boxes in (
        (
            reference,
            [(20, 10, 59, 17), (20, 35, 27, 42)],
        ),
        (
            rendered,
            [(20, 10, 39, 15), (20, 35, 22, 38)],
        ),
    ):
        image = Image.new("RGB", (100, 60), "white")
        draw = ImageDraw.Draw(image)
        for box in boxes:
            draw.rectangle(box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "table-header:time",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "Time",
                "style": {"fontSize": 10},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 30],
                        "ink_bbox": [20, 10, 40, 8],
                    }
                },
            },
            {
                "contentRef": "table-header:index",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "#",
                "style": {"fontSize": 10.5},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 30, 100, 30],
                        "ink_bbox": [20, 35, 8, 8],
                    }
                },
            },
        ]
    }

    calibrated, report = calibrate_table_fonts_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][0]["style"]["fontSize"] == 20
    assert calibrated["elements"][1]["style"]["fontSize"] == 10.5
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


def test_table_letter_spacing_corrects_width_without_changing_height(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 119, 35)),
        (rendered, (20, 20, 109, 35)),
    ):
        image = Image.new("RGB", (160, 60), "white")
        ImageDraw.Draw(image).rectangle(box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "table-cell:json",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "ABCDEFGHIJ",
                "style": {"fontSize": 16, "letterSpacing": 0},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 160, 60],
                        "ink_bbox": [20, 20, 100, 16],
                    }
                },
            }
        ]
    }

    calibrated, report = calibrate_table_letter_spacing_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][0]["style"]["fontSize"] == 16
    assert calibrated["elements"][0]["style"]["letterSpacing"] == 1.0
    assert report["adjusted_count"] == 1


def test_table_letter_spacing_skips_short_text(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 37, 31)),
        (rendered, (20, 20, 26, 31)),
    ):
        image = Image.new("RGB", (100, 50), "white")
        ImageDraw.Draw(image).rectangle(box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "table-cell:number",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "10",
                "style": {"fontSize": 16},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 18, 12],
                    }
                },
            }
        ]
    }

    calibrated, report = calibrate_table_letter_spacing_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][0]["style"].get("letterSpacing") is None
    assert report["adjusted_count"] == 0


def test_low_contrast_placeholder_adjusts_size_position_and_weight(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (30, 20, 79, 31)),
        (rendered, (29, 20, 80, 33)),
    ):
        image = Image.new("RGB", (120, 60), "white")
        ImageDraw.Draw(image).rectangle(box, fill="#999999")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "text:search",
                "type": "text",
                "x": 8,
                "y": 18,
                "width": 174,
                "height": 36,
                "text": "表内搜索",
                "style": {"fontSize": 24, "fontWeight": "normal"},
                "styleEvidence": {
                    "evidence": {
                        "background": "#ffffff",
                        "foreground": "#999999",
                        "contrast_delta": 102,
                        "source_bbox": [10, 10, 174, 36],
                        "ink_bbox": [11, 11, 172, 34],
                    }
                },
            }
        ]
    }
    ocr = {
        "observations": [
            {
                "text": "表内搜索",
                "bbox": [30, 20, 62, 20],
                "confidence": 0.96,
                "engine": "easyocr",
            }
        ]
    }

    calibrated, report = calibrate_low_contrast_placeholder_from_render(
        design,
        str(reference),
        str(rendered),
        ocr_supplement=ocr,
    )

    assert calibrated["elements"][0]["style"]["fontSize"] == 15.25
    assert calibrated["elements"][0]["style"]["fontWeight"] == 700
    assert calibrated["elements"][0]["x"] == 30
    assert calibrated["elements"][0]["y"] == 18
    assert calibrated["elements"][0]["styleEvidence"]["evidence"]["source_bbox"] == [
        30,
        20,
        62,
        20,
    ]
    assert report["adjusted_count"] == 1


def test_low_contrast_placeholder_skips_table_cells(tmp_path: Path) -> None:
    """A table cell's size belongs to the table, not to the 15.25/700 fallback.

    light-table: this strategy rewrote sixteen table placeholders from Regular
    to Bold once their size was clamped into its 15.75-24.25 window, taking
    ``style_mm`` from 14/105 to 30/105.
    """
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (30, 20, 79, 31)),
        (rendered, (29, 20, 80, 33)),
    ):
        image = Image.new("RGB", (120, 60), "white")
        ImageDraw.Draw(image).rectangle(box, fill="#999999")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "table-cell:abc",
                "type": "text",
                "x": 8,
                "y": 18,
                "width": 174,
                "height": 36,
                "text": "请输入0~",
                "style": {"fontSize": 21.0, "fontWeight": "normal"},
                "imageMVP": {"role": "table-cell", "candidate_type": "text"},
                "styleEvidence": {
                    "evidence": {
                        "background": "#ffffff",
                        "foreground": "#999999",
                        "contrast_delta": 102,
                        "source_bbox": [10, 10, 174, 36],
                        "ink_bbox": [11, 11, 172, 34],
                    }
                },
            }
        ]
    }

    calibrated, report = calibrate_low_contrast_placeholder_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert report["adjusted_count"] == 0
    assert report["skipped_table_cells"] == 1
    assert calibrated["elements"][0]["style"]["fontSize"] == 21.0
    assert calibrated["elements"][0]["style"]["fontWeight"] == "normal"


def test_low_contrast_placeholder_control_sets_text_box(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (30, 20, 79, 31)),
        (rendered, (29, 20, 80, 33)),
    ):
        image = Image.new("RGB", (200, 60), "white")
        ImageDraw.Draw(image).rectangle(box, fill="#999999")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "control:search",
                "type": "button",
                "x": 10,
                "y": 10,
                "width": 174,
                "height": 36,
                "text": "表内搜索",
                "textBox": None,
                "style": {"fontSize": 14.5, "fontWeight": "normal"},
                "styleEvidence": {
                    "evidence": {
                        "background": "#ffffff",
                        "foreground": "#999999",
                        "contrast_delta": 102,
                        "source_bbox": [10, 10, 174, 36],
                        "ink_bbox": [11, 11, 172, 34],
                    }
                },
            }
        ]
    }
    ocr = {
        "observations": [
            {
                "text": "表内搜索",
                "bbox": [30, 20, 62, 20],
                "confidence": 0.96,
                "engine": "easyocr",
            }
        ]
    }

    calibrated, report = calibrate_low_contrast_placeholder_from_render(
        design,
        str(reference),
        str(rendered),
        ocr_supplement=ocr,
    )

    element = calibrated["elements"][0]
    assert element["x"] == 10
    assert element["y"] == 10
    assert element["width"] == 174
    assert element["height"] == 36
    assert element["textBox"] == [30, 20, 62, 20]
    assert element["style"]["fontSize"] == 15.25
    assert element["style"]["fontWeight"] == 700
    assert report["adjusted_count"] == 1


def test_low_contrast_search_control_calibrates_text_and_glyph_spacing(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (30, 20, 85, 31)),
        (rendered, (28, 19, 86, 32)),
    ):
        image = Image.new("RGB", (220, 70), "white")
        ImageDraw.Draw(image).rectangle(box, fill="#999999")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "control:search",
                "type": "button",
                "x": 10,
                "y": 10,
                "width": 174,
                "height": 36,
                "text": "表内搜索",
                "controlValue": "表内搜索",
                "textBox": [27, 11, 62, 20],
                "styleEvidence": {
                    "evidence": {
                        "background": "#ffffff",
                        "foreground": "#999999",
                        "contrast_delta": 102,
                        "source_bbox": [5, 5, 100, 40],
                        "ink_bbox": [30, 20, 56, 12],
                    }
                },
            },
            {
                "contentRef": "control:refresh",
                "type": "button",
                "x": 10,
                "y": 40,
                "width": 80,
                "height": 24,
                "text": "刷新",
                "textBox": [12, 42, 40, 18],
                "styleEvidence": {
                    "evidence": {
                        "background": "#ffffff",
                        "foreground": "#999999",
                        "contrast_delta": 102,
                        "source_bbox": [10, 40, 80, 24],
                        "ink_bbox": [30, 45, 20, 10],
                    }
                },
            },
        ]
    }

    calibrated, report = calibrate_search_control_from_render(
        design,
        str(reference),
        str(rendered),
    )

    search = calibrated["elements"][0]
    assert search["x"] == 10
    assert search["y"] == 10
    assert search["width"] == 174
    assert search["height"] == 36
    assert search["textBox"] == [28, 11, 62, 20]
    assert search["style"]["letterSpacing"] == -0.25
    assert calibrated["elements"][1] == design["elements"][1]
    assert report == {
        "schema_version": "grounding-search-control-post-calibration/1.0",
        "status": "applied",
        "adjusted_count": 1,
        "adjustments": [
            {
                "contentRef": "control:search",
                "text": "表内搜索",
                "previousTextBox": [27, 11, 62, 20],
                "updatedTextBox": [28, 11, 62, 20],
                "referenceInkBBox": [30, 20, 56, 12],
                "renderedInkBBox": [28, 19, 59, 14],
                "xDelta": 2,
                "yDelta": 1,
                "widthDelta": -3,
                "heightDelta": -2,
                "positionCorrectionX": 1,
                "positionCorrectionY": 0,
                "widthCorrectionPx": -1,
                "previousLetterSpacing": 0.0,
                "updatedLetterSpacing": -0.25,
            }
        ],
    }


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


def test_form_font_calibration_skips_textarea_width_scaling(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 59, 27)),
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
                "contentRef": "control:remark",
                "type": "input",
                "controlType": "textarea",
                "x": 0,
                "y": 0,
                "text": "remark",
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

    assert calibrated["elements"][1]["style"]["fontSize"] == 10
    assert report["adjusted_count"] == 0


def test_form_text_weight_calibration_uses_excess_ink_coverage(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 49, 27)),
        (rendered, (20, 20, 49, 35)),
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
                "contentRef": "text:label",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "Label",
                "style": {"fontWeight": 400, "textColor": "#595959"},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 30, 8],
                    }
                },
            },
            {
                "contentRef": "table-header:label",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "Label",
                "style": {"fontWeight": "bold", "textColor": "#595959"},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 30, 8],
                    }
                },
            },
        ]
    }

    calibrated, report = calibrate_form_text_weight_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][1]["style"]["fontWeight"] == 300
    assert calibrated["elements"][2]["style"]["fontWeight"] == "bold"
    assert report["adjusted_count"] == 1


def test_form_text_shape_calibration_keeps_matched_and_reduces_mismatch(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    reference_image = Image.new("RGB", (200, 120), "white")
    reference_draw = ImageDraw.Draw(reference_image)
    reference_draw.rectangle((20, 20, 79, 35), fill="black")
    reference_draw.rectangle((20, 70, 79, 85), fill="black")
    reference_image.save(reference)
    rendered_image = Image.new("RGB", (200, 120), "white")
    rendered_draw = ImageDraw.Draw(rendered_image)
    rendered_draw.rectangle((20, 20, 79, 35), fill="black")
    rendered_draw.rectangle((20, 68, 79, 89), fill="black")
    rendered_image.save(rendered)
    design = {
        "elements": [
            {
                "id": "form",
                "type": "container",
                "role": "form-section",
                "x": 0,
                "y": 0,
                "width": 200,
                "height": 120,
            },
            {
                "contentRef": "text:matched",
                "type": "text",
                "x": 0,
                "y": 0,
                "text": "执行成功",
                "style": {"fontSize": 18, "fontWeight": "normal"},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 60, 16],
                    }
                },
            },
            {
                "contentRef": "text:mismatch",
                "type": "text",
                "x": 0,
                "y": 50,
                "text": "名称",
                "style": {"fontSize": 18, "fontWeight": "normal"},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 50, 100, 50],
                        "ink_bbox": [20, 70, 60, 16],
                    }
                },
            },
        ]
    }

    calibrated, report = calibrate_form_text_shape_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][1]["style"]["fontSize"] == 18
    assert calibrated["elements"][1]["style"]["fontWeight"] == "normal"
    assert calibrated["elements"][2]["style"]["fontSize"] == 17.5
    assert calibrated["elements"][2]["style"]["fontWeight"] == 300
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


def test_toolbar_font_weight_uses_ink_coverage(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path, box in (
        (reference, (20, 20, 59, 27)),
        (rendered, (20, 20, 59, 35)),
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
                "text": "Weighted",
                "style": {"fontWeight": "normal"},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 40, 8],
                        "ink_pixel_count": 320,
                    }
                },
            },
        ]
    }

    calibrated, report = calibrate_toolbar_font_weight_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][1]["style"]["fontWeight"] == 300
    assert report["adjusted_count"] == 1


def test_toolbar_font_weight_uses_light_text_evidence(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (100, 100), "white")
        ImageDraw.Draw(image).rectangle((20, 20, 59, 27), fill="black")
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
                "contentRef": "control:toolbar-light",
                "type": "button",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 40,
                "text": "Light text",
                "style": {"fontWeight": "normal", "textColor": "#ffffff"},
                "styleEvidence": {
                    "evidence": {
                        "foreground": "#ffffff",
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 40, 8],
                    }
                },
            },
        ]
    }

    calibrated, report = calibrate_toolbar_font_weight_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][1]["style"]["fontWeight"] == 500
    assert report["adjustments"][0]["selectionBasis"] == "light-text"


def test_toolbar_font_weight_finds_marked_cluster_and_uses_demi_light(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (260, 100), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 59, 35), fill="black")
        draw.rectangle((120, 20, 159, 35), fill="black")
        draw.rectangle((20, 70, 59, 85), fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "contentRef": "control:toolbar-pause",
                "type": "button",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 50,
                "text": "暂停自动刷新",
                "imageMVP": {"role": "toolbar-control"},
                "style": {"fontWeight": "normal", "textColor": "#333333"},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 40, 16],
                    }
                },
            },
            {
                "contentRef": "control:toolbar-copy",
                "type": "button",
                "x": 100,
                "y": 0,
                "width": 100,
                "height": 50,
                "text": "复制",
                "imageMVP": {"role": "control"},
                "style": {"fontWeight": "normal", "textColor": "#333333"},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [100, 0, 100, 50],
                        "ink_bbox": [120, 20, 40, 16],
                    }
                },
            },
            {
                "contentRef": "control:distant",
                "type": "button",
                "x": 0,
                "y": 50,
                "width": 100,
                "height": 50,
                "text": "手动执行",
                "imageMVP": {"role": "control"},
                "style": {"fontWeight": "normal", "textColor": "#333333"},
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 50, 100, 50],
                        "ink_bbox": [20, 70, 40, 16],
                    }
                },
            },
        ]
    }

    calibrated, report = calibrate_toolbar_font_weight_from_render(
        design,
        str(reference),
        str(rendered),
    )

    assert calibrated["elements"][0]["style"]["fontWeight"] == 350
    assert calibrated["elements"][1]["style"]["fontWeight"] == 350
    assert calibrated["elements"][2]["style"]["fontWeight"] == "normal"
    assert report["adjusted_count"] == 2


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
