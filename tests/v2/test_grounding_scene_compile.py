from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.app.services.evidence.image_figma_acceptance import evaluate_image_mvp
from src.app.services.structure.image_contract import (
    build_image_design,
    inspect_image_reference,
)


def _image(tmp_path: Path) -> Path:
    path = tmp_path / "page.png"
    Image.new("RGB", (400, 240), "#ffffff").save(path)
    return path


def _graph(path: Path) -> dict:
    return {
        "image": str(path),
        "image_w": 400,
        "image_h": 240,
        "route": "grounding",
        "containers": [],
        "elements": [],
        "scenePlan": {
            "schema_version": "grounding-scene-plan/1.0",
            "image_size": [400, 240],
            "coordinate_basis": "source-pixel-top-left",
            "nodes": [
                {
                    "id": "text:title",
                    "parent_id": None,
                    "type": "text",
                    "role": "text",
                    "bbox": [20, 20, 160, 24],
                    "content_ref": "text:title",
                    "geometry_ref": "geometry:title",
                    "children": [],
                    "text": "自动备份管理",
                },
                {
                    "id": "text:checkbox-label",
                    "parent_id": None,
                    "type": "text",
                    "role": "control-label",
                    "bbox": [64, 72, 180, 22],
                    "content_ref": "text:checkbox-label",
                    "geometry_ref": "geometry:label",
                    "children": [],
                    "text": "以auto用户身份执行",
                },
                {
                    "id": "table-cell:0:0",
                    "parent_id": "table-node:0",
                    "type": "text",
                    "role": "table-cell",
                    "bbox": [20, 120, 180, 40],
                    "content_ref": "table-cell:0:0",
                    "geometry_ref": "geometry:cell",
                    "children": [],
                    "text": "2026-11-01 03:30:00",
                },
                {
                    "id": "control:manual",
                    "parent_id": None,
                    "type": "control",
                    "role": "control",
                    "bbox": [180, 180, 100, 32],
                    "content_ref": "control:manual",
                    "geometry_ref": "geometry:manual",
                    "children": [],
                    "text": "手动执行",
                    "control_type": "button",
                    "state": "enabled",
                    "text_owner_ref": None,
                },
            ],
            "suppressed": [],
        },
        "provenance": {"route": "grounding"},
    }


def test_scene_plan_text_nodes_are_compiled_as_native_text(tmp_path: Path) -> None:
    path = _image(tmp_path)
    design = build_image_design(_graph(path), inspect_image_reference(path))

    by_content = {
        str(element.get("contentRef")): element
        for element in design["elements"]
        if element.get("contentRef")
    }
    assert by_content["text:title"]["type"] == "text"
    assert by_content["text:title"]["text"] == "自动备份管理"
    assert by_content["text:checkbox-label"]["text"] == "以auto用户身份执行"
    assert by_content["table-cell:0:0"]["text"] == "2026-11-01 03:30:00"
    assert by_content["control:manual"]["controlValue"] == "手动执行"


def test_scene_text_keeps_source_geometry_and_editable_style(tmp_path: Path) -> None:
    path = _image(tmp_path)
    design = build_image_design(_graph(path), inspect_image_reference(path))
    label = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "text:checkbox-label"
    )

    assert [label["x"], label["y"], label["width"], label["height"]] == [
        64,
        72,
        180,
        22,
    ]
    assert label["style"]["fontFamily"]
    assert label["style"]["fontSize"] > 0
    assert label["imageMVP"]["source"] == "scene-plan"


def test_scene_control_owner_keeps_native_text(tmp_path: Path) -> None:
    path = _image(tmp_path)
    design = build_image_design(_graph(path), inspect_image_reference(path))
    control = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "control:manual"
    )

    assert control["type"] == "button"
    assert control["controlValue"] == "手动执行"


def test_empty_existing_control_is_filled_from_scene_plan(tmp_path: Path) -> None:
    path = _image(tmp_path)
    graph = _graph(path)
    graph["elements"] = [
        {
            "id": 9,
            "bbox": [180, 180, 100, 32],
            "type": "button",
            "controlType": "button",
            "text": "",
            "controlValue": "",
            "source": "grounding",
            "container": None,
            "contentRef": "control:manual",
        }
    ]
    design = build_image_design(graph, inspect_image_reference(path))
    control = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "control:manual"
    )

    assert control["controlValue"] == "手动执行"
    assert control["text"] == "手动执行"


def test_acceptance_asset_count_uses_truth_assets() -> None:
    result = evaluate_image_mvp(
        design={
            "elements": [
                {
                    "id": "logo",
                    "type": "image",
                    "imageBase64": "ZmFrZQ==",
                },
                {
                    "id": "decorative-image",
                    "type": "image",
                    "imageBase64": "ZmFrZTI=",
                },
            ]
        },
        truth={
            "critical_texts": ["Title"],
            "assets": [{"name": "Logo"}],
        },
        readback_tree={
            "type": "FRAME",
            "children": [
                {"type": "TEXT", "characters": "Title"},
                {
                    "type": "RECTANGLE",
                    "fills": [{"type": "IMAGE", "imageHash": "fill"}],
                },
            ],
        },
        visual_metrics={"size_match": True, "within30_pct": 100.0},
        text_probe={"status": "pass"},
        asset_probe={"status": "pass"},
        image_ir={
            "assets": [
                {
                    "reference_only": True,
                    "original": False,
                    "generated": False,
                }
            ]
        },
    )

    assert result["dimensions"]["asset"]["status"] == "pass"
