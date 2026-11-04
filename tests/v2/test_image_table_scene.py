from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.structure.image_enrichment.table_scene import (
    detect_table_grid,
    normalize_table_design,
)


def _table_image(path: Path) -> None:
    image = Image.new("RGB", (420, 320), "#ffffff")
    draw = ImageDraw.Draw(image)
    for x in (20, 80, 180, 320, 400):
        draw.line((x, 20, x, 300), fill="#d3d7dc", width=1)
    for y in (20, 60, 100, 140, 180, 220, 260, 300):
        draw.line((20, y, 400, y), fill="#d3d7dc", width=1)
    image.save(path)


def test_table_grid_detection_returns_native_rows_and_columns(tmp_path):
    image_path = tmp_path / "table.png"
    _table_image(image_path)

    grid = detect_table_grid(image_path, [20, 20, 380, 280])

    assert grid is not None
    assert grid["x_boundaries"][0] == 0
    assert len(grid["x_boundaries"]) >= 4
    assert len(grid["y_boundaries"]) >= 7


def test_table_normalization_keeps_one_owner_per_cell(tmp_path):
    image_path = tmp_path / "table.png"
    _table_image(image_path)
    graph = {
        "containers": [
            {
                "id": "C1",
                "role": "table-section",
                "bbox": [20, 20, 380, 280],
            }
        ]
    }
    elements = [
        {
            "id": "1",
            "type": "button",
            "x": 20,
            "y": 60,
            "width": 380,
            "height": 40,
            "text": "2026-11-01 03:30:00",
            "controlValue": "2026-11-01 03:30:00",
        },
        {
            "id": "2",
            "type": "text",
            "x": 90,
            "y": 66,
            "width": 180,
            "height": 24,
            "text": "2026-11-01 03:30:00",
        },
        {
            "id": "3",
            "type": "text",
            "x": 210,
            "y": 66,
            "width": 80,
            "height": 24,
            "text": "auto",
        },
    ]

    normalized = normalize_table_design(
        elements,
        image_path,
        graph,
        canvas_size=(420, 320),
    )

    visible = [
        element
        for element in normalized
        if element.get("text") or element.get("controlValue")
    ]
    assert len(visible) == 2
    assert {element["text"] for element in visible} == {
        "2026-11-01 03:30:00",
        "auto",
    }
    assert all(element["type"] == "text" for element in visible)


def test_table_model_rows_override_duplicate_ocr_candidates(tmp_path):
    image_path = tmp_path / "table.png"
    _table_image(image_path)
    graph = {
        "containers": [
            {
                "id": "C1",
                "role": "table-section",
                "bbox": [20, 20, 380, 280],
            }
        ],
        "tables": [
            {
                "name": "Results",
                "bbox": [20, 20, 380, 280],
                "header_texts": ["#", "Time", "Result"],
                "rows": [["1", "03:30", "ok"], ["2", "04:30", "ok"]],
            }
        ],
    }
    elements = [
        {
            "id": "noise",
            "type": "button",
            "x": 20,
            "y": 60,
            "width": 380,
            "height": 40,
            "text": "wrong row",
        }
    ]

    normalized = normalize_table_design(
        [
            *elements,
            {
                "id": "late-duplicate",
                "type": "text",
                "x": 90,
                "y": 302,
                "width": 180,
                "height": 16,
                "text": "late duplicate",
            },
        ],
        image_path,
        graph,
        canvas_size=(420, 320),
    )

    texts = [element["text"] for element in normalized if element.get("text")]
    assert "wrong row" not in texts
    assert "late duplicate" not in texts
    assert {"#", "Time", "Result", "1", "03:30", "ok", "2", "04:30"} <= set(texts)
    row_tops = sorted(
        {
            round(element["y"])
            for element in normalized
            if element.get("text") in {"1", "03:30", "2", "04:30"}
        }
    )
    assert row_tops == [68, 108]


def test_table_model_bbox_can_start_below_visible_header(tmp_path):
    image_path = tmp_path / "table.png"
    _table_image(image_path)
    graph = {
        "containers": [
            {
                "id": "C1",
                "role": "table-section",
                "bbox": [20, 60, 380, 60],
            }
        ],
        "tables": [
            {
                "name": "Results",
                "bbox": [20, 60, 380, 60],
                "header_texts": ["#", "Time", "Duration"],
                "rows": [["1", "03:30", "10"]],
            }
        ],
    }

    normalized = normalize_table_design(
        [],
        image_path,
        graph,
        canvas_size=(420, 320),
    )

    positions = {
        element["text"]: round(element["y"])
        for element in normalized
        if element.get("text")
    }
    assert positions == {
        "#": 28,
        "Time": 28,
        "Duration": 28,
        "1": 68,
        "03:30": 68,
        "10": 68,
    }
    header = next(element for element in normalized if element.get("text") == "Time")
    assert header["x"] == 80
    assert header["width"] == 100
    assert header["style"]["textAlign"] == "center"


def test_table_normalization_adds_native_grid_lines(tmp_path):
    image_path = tmp_path / "table.png"
    _table_image(image_path)
    graph = {
        "containers": [
            {
                "id": "C1",
                "role": "table-section",
                "bbox": [20, 20, 380, 280],
            }
        ],
        "tables": [
            {
                "name": "Results",
                "bbox": [20, 20, 380, 280],
                "header_texts": ["#", "Time", "Result"],
                "rows": [["1", "03:30", "ok"]],
            }
        ],
    }

    normalized = normalize_table_design(
        [],
        image_path,
        graph,
        canvas_size=(420, 320),
    )

    horizontal = [
        element
        for element in normalized
        if element.get("role") == "table-grid-horizontal"
    ]
    vertical = [
        element
        for element in normalized
        if element.get("role") == "table-grid-vertical"
    ]
    assert len(horizontal) == 3
    assert len(vertical) == 4
    assert all(element["style"]["fillColor"] == "#e7ecf1" for element in horizontal)


def test_table_normalization_uses_cell_ink_geometry(tmp_path):
    image_path = tmp_path / "table.png"
    _table_image(image_path)
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.text((30, 30), "#", fill="#333333")
    draw.text((90, 30), "Time", fill="#333333")
    draw.text((190, 30), "Result", fill="#333333")
    draw.text((90, 70), "03:30", fill="#333333")
    image.save(image_path)
    graph = {
        "containers": [
            {
                "id": "C1",
                "role": "table-section",
                "bbox": [20, 20, 380, 280],
            }
        ],
        "tables": [
            {
                "name": "Results",
                "bbox": [20, 20, 380, 280],
                "header_texts": ["#", "Time", "Result"],
                "rows": [["1", "03:30", "ok"]],
            }
        ],
    }

    normalized = normalize_table_design(
        [],
        image_path,
        graph,
        canvas_size=(420, 320),
    )

    header = {
        element["text"]: element
        for element in normalized
        if element.get("source") == "grounding-table-model"
        and element["text"] in {"#", "Time", "Result"}
    }
    assert 28 <= header["#"]["x"] <= 31
    assert header["#"]["width"] < 40
    assert header["Time"]["width"] < 100
    assert header["#"]["style"]["textColor"] == "#555555"
    body_text = next(
        element for element in normalized if element.get("id") == "table-model-1-1"
    )
    assert body_text["width"] >= 80
