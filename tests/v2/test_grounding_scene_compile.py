from __future__ import annotations

import copy
from pathlib import Path

from PIL import Image

from src.app.services.evidence.image_figma_acceptance import evaluate_image_mvp
from src.app.services.structure.image_contract import (
    _remove_unowned_control_shadows,
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
                    "id": "table-header:0:0",
                    "parent_id": "table-node:0",
                    "type": "text",
                    "role": "table-header",
                    "bbox": [20, 80, 180, 40],
                    "content_ref": "table-header:0:0",
                    "geometry_ref": "geometry:header",
                    "children": [],
                    "text": "执行时间",
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
    assert by_content["table-header:0:0"]["style"]["fontWeight"] == "bold"
    assert by_content["table-header:0:0"]["styleEvidence"]["evidence"]["status"] in {
        "observed",
        "low-contrast",
        "low-confidence",
    }
    assert by_content["control:manual"]["controlValue"] == "手动执行"


def test_scene_plan_removes_unowned_duplicate_table_text(tmp_path: Path) -> None:
    path = _image(tmp_path)
    graph = _graph(path)
    graph["scenePlan"]["nodes"].append(
        {
            "id": "table-node:0",
            "parent_id": None,
            "type": "table",
            "role": "table",
            "bbox": [20, 100, 360, 120],
            "content_ref": "table:0",
            "geometry_ref": "geometry:table",
            "children": [],
        }
    )
    graph["elements"] = [
        {
            "id": 90,
            "bbox": [20, 70, 160, 40],
            "type": "text",
            "text": "OLD TABLE HEADER",
            "source": "grounding",
            "container": None,
        }
    ]
    design = build_image_design(graph, inspect_image_reference(path))

    assert not any(
        element.get("text") == "OLD TABLE HEADER" for element in design["elements"]
    )


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
    assert label["styleEvidence"]["evidence"]["source_bbox"] == [64, 72, 180, 22]
    assert "lineHeight" not in label["style"]
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


def test_scene_input_fill_keeps_left_text_box(tmp_path: Path) -> None:
    path = _image(tmp_path)
    graph = _graph(path)
    control_node = copy.deepcopy(graph["scenePlan"]["nodes"][-1])
    control_node.update(
        {
            "id": "control:name",
            "content_ref": "control:name",
            "bbox": [100, 40, 200, 32],
            "text": "auto_backup",
            "control_type": "input",
        }
    )
    graph["scenePlan"]["nodes"] = [control_node]
    design = build_image_design(graph, inspect_image_reference(path))
    control = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "control:name"
    )

    assert control["text"] == "auto_backup"
    assert control["textBox"][0] == 112
    assert control["textBox"][1] == 50
    assert control["textBox"][2] == 176


def test_large_icon_button_owner_compiles_as_input(tmp_path: Path) -> None:
    path = _image(tmp_path)
    graph = _graph(path)
    control_node = copy.deepcopy(graph["scenePlan"]["nodes"][-1])
    control_node.update(
        {
            "id": "control:schedule",
            "content_ref": "control:schedule",
            "bbox": [100, 40, 300, 40],
            "text": "0 30 3 * * ?",
            "control_type": "icon-button",
        }
    )
    graph["scenePlan"]["nodes"] = [control_node]
    design = build_image_design(graph, inspect_image_reference(path))
    control = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "control:schedule"
    )

    assert control["type"] == "input"
    assert control["controlValue"] == "0 30 3 * * ?"
    assert control["textBox"][0] == 112


def test_unowned_control_shadow_is_removed(tmp_path: Path) -> None:
    path = _image(tmp_path)
    graph = _graph(path)
    node = copy.deepcopy(graph["scenePlan"]["nodes"][-1])
    node.update(
        {
            "id": "control:name",
            "content_ref": "control:name",
            "bbox": [100, 40, 200, 32],
            "text": "auto_backup",
            "control_type": "input",
        }
    )
    graph["scenePlan"]["nodes"] = [node]
    graph["elements"] = [
        {
            "id": 1,
            "bbox": [100, 40, 200, 32],
            "type": "input",
            "text": "auto_backup",
            "controlValue": "auto_backup",
            "source": "grounding",
            "container": None,
            "contentRef": "control:name",
        },
        {
            "id": 2,
            "bbox": [101, 41, 200, 32],
            "type": "input",
            "text": "",
            "controlValue": "",
            "source": "grounding",
            "container": None,
        },
    ]
    design = build_image_design(graph, inspect_image_reference(path))
    controls = [
        element
        for element in design["elements"]
        if element.get("type") == "input" and element.get("y") == 40
    ]

    assert len(controls) == 1
    assert controls[0]["contentRef"] == "control:name"


def test_unowned_offset_control_shadow_is_removed_by_scene_bbox() -> None:
    scene_plan = {
        "nodes": [
            {
                "id": "control:name",
                "type": "control",
                "bbox": [100, 40, 200, 32],
                "content_ref": "control:name",
            }
        ]
    }
    elements = [
        {
            "id": "owner",
            "type": "input",
            "x": 100,
            "y": 40,
            "width": 200,
            "height": 32,
            "text": "auto_backup",
            "contentRef": "control:name",
        },
        {
            "id": "shadow",
            "type": "input",
            "x": 101,
            "y": 41,
            "width": 200,
            "height": 32,
            "text": "",
        },
    ]

    filtered = _remove_unowned_control_shadows(elements, scene_plan)

    assert [element["id"] for element in filtered] == ["owner"]


def test_scene_plan_header_role_does_not_invent_unplanned_icons(
    tmp_path: Path,
) -> None:
    path = _image(tmp_path)
    graph = _graph(path)
    graph["containers"] = [
        {
            "id": "C1",
            "bbox": [0, 0, 400, 64],
            "role": "",
            "source": "grounding",
            "parent": None,
            "depth": 0,
            "elements": [],
        }
    ]
    graph["elements"] = [
        {
            "id": 1,
            "bbox": [100, 20, 90, 20],
            "type": "text",
            "text": "FlexWeaver",
            "source": "grounding",
            "container": "C1",
        }
    ]
    graph["scenePlan"]["nodes"].append(
        {
            "id": "header:C1",
            "parent_id": None,
            "type": "container",
            "role": "header",
            "bbox": [0, 0, 400, 64],
            "content_ref": None,
            "geometry_ref": "geometry:header",
            "children": [],
        }
    )
    graph["imageEnrichment"] = {"mode": "apply", "status": "applied"}
    design = build_image_design(graph, inspect_image_reference(path))
    assert design["_meta"]["mode"] == "fixed-canvas-owner-compiler"
    assert not any(
        str(element.get("id") or "").startswith("chrome-icon-")
        for element in design["elements"]
    )


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
