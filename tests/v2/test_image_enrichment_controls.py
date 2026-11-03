from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.structure.image_enrichment.controls import (
    recover_visible_controls,
)
from src.app.services.structure.image_contract import (
    build_image_design,
    inspect_image_reference,
)


def _control_graph(image_path: Path) -> dict:
    return {
        "image": str(image_path),
        "image_w": 800,
        "image_h": 300,
        "route": "grounding",
        "containers": [],
        "elements": [
            {
                "id": 1,
                "bbox": [104, 82, 205, 29],
                "type": "input",
            },
            {
                "id": 2,
                "bbox": [404, 82, 205, 29],
                "type": "input",
            },
            {
                "id": 3,
                "bbox": [103, 153, 25, 24],
                "type": "checkbox",
                "text": "Pause",
            },
            {
                "id": 4,
                "bbox": [403, 153, 25, 24],
                "type": "checkbox",
                "text": "Enabled",
            },
            {
                "id": 5,
                "bbox": [112, 86, 120, 20],
                "type": "text",
                "text": "auto_backup",
            },
            {
                "id": 6,
                "bbox": [412, 86, 120, 20],
                "type": "text",
                "text": "auto",
            },
        ],
        "imageEnrichment": {
            "mode": "apply",
            "assets": [],
            "backgrounds": [],
        },
        "provenance": {"route": "grounding"},
    }


def _control_image(path: Path) -> None:
    image = Image.new("RGB", (800, 300), "#f4f5f7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 80, 299, 111), fill="#ffffff", outline="#c8ccd2")
    draw.rectangle((400, 80, 599, 111), fill="#eef1f4", outline="#c8ccd2")
    draw.rectangle((100, 150, 119, 169), fill="#ffffff", outline="#9199a3")
    draw.rectangle((400, 150, 419, 169), fill="#1f8f58", outline="#1f8f58")
    draw.line((404, 160, 409, 165, 416, 154), fill="#ffffff", width=2)
    image.save(path)


def test_control_recovery_snaps_boxes_and_infers_value_state(tmp_path):
    image_path = tmp_path / "controls.png"
    _control_image(image_path)

    recovered, report = recover_visible_controls(
        _control_graph(image_path),
        image_path,
    )

    controls = {
        element["id"]: element
        for element in recovered["elements"]
        if element["type"] in {"input", "checkbox"}
    }
    assert controls[1]["bbox"] == [99, 79, 202, 34]
    assert controls[1]["controlValue"] == "auto_backup"
    assert controls[1]["controlState"] == "enabled"
    assert all(
        abs(actual - expected) <= 5
        for actual, expected in zip(
            controls[2]["bbox"],
            [399, 79, 202, 34],
            strict=True,
        )
    )
    assert controls[2]["controlState"] == "disabled"
    assert controls[2]["controlValue"] == "auto"
    assert controls[3]["controlState"] == "unchecked"
    assert controls[4]["controlState"] == "checked"
    assert report["status"] == "applied"
    assert report["snapped_count"] == 4
    assert len({tuple(control["bbox"]) for control in controls.values()}) == 4


def test_control_fields_survive_design_mapping(tmp_path):
    image_path = tmp_path / "controls.png"
    _control_image(image_path)
    recovered, _report = recover_visible_controls(
        _control_graph(image_path),
        image_path,
    )
    design = build_image_design(recovered, inspect_image_reference(image_path))

    mapped = {
        element["text"]: element
        for element in design["elements"]
        if element["type"] in {"input", "button"}
    }
    assert mapped["auto_backup"]["controlType"] == "input"
    assert mapped["auto_backup"]["controlValue"] == "auto_backup"
    assert mapped["auto_backup"]["controlState"] == "enabled"
    assert mapped["auto"]["controlState"] == "disabled"


def test_design_maps_late_recovered_text_into_control_value(tmp_path):
    image_path = tmp_path / "late-text.png"
    Image.new("RGB", (400, 160), "#ffffff").save(image_path)
    graph = {
        "image": str(image_path),
        "image_w": 400,
        "image_h": 160,
        "route": "grounding",
        "containers": [],
        "elements": [
            {
                "id": 1,
                "bbox": [40, 50, 200, 32],
                "type": "input",
                "text": "",
                "controlType": "input",
                "controlValue": "",
                "controlState": "enabled",
            },
            {
                "id": 2,
                "bbox": [52, 56, 120, 20],
                "type": "text",
                "text": "late_value",
                "source": "ocr-supplement",
            },
        ],
        "imageEnrichment": {"mode": "apply"},
        "provenance": {"route": "grounding"},
    }

    design = build_image_design(graph, inspect_image_reference(image_path))

    control = next(
        element for element in design["elements"] if element.get("controlType") == "input"
    )
    assert control["controlValue"] == "late_value"
    assert control["text"] == "late_value"


def test_search_placeholder_remains_text_without_becoming_input_value(tmp_path):
    image_path = tmp_path / "search.png"
    Image.new("RGB", (400, 160), "#ffffff").save(image_path)
    graph = {
        "image": str(image_path),
        "image_w": 400,
        "image_h": 160,
        "route": "grounding",
        "containers": [],
        "elements": [
            {
                "id": 1,
                "bbox": [200, 50, 160, 32],
                "type": "icon-button",
                "text": "表内搜索",
                "controlType": "icon-button",
                "controlValue": "表内搜索",
                "controlState": "enabled",
            },
            {
                "id": 2,
                "bbox": [220, 56, 70, 20],
                "type": "text",
                "text": "表内搜索",
            },
        ],
        "imageEnrichment": {"mode": "apply"},
        "provenance": {"route": "grounding"},
    }

    design = build_image_design(graph, inspect_image_reference(image_path))

    control = next(
        element
        for element in design["elements"]
        if element.get("controlType") == "input"
    )
    assert control["controlValue"] == ""
    assert control["text"] == ""
    assert any(
        element.get("type") == "text" and element.get("text") == "表内搜索"
        for element in design["elements"]
    )
