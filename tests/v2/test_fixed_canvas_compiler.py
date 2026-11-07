from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from src.app.services.rendering.adapter_base import paint_order
from src.app.services.structure.fidelity.fixed_canvas_compiler import (
    compile_scene_plan_to_design,
)
from src.app.services.structure.image_contract import (
    build_image_design,
    inspect_image_reference,
)


def _fixture(tmp_path: Path) -> tuple[Path, dict, dict]:
    path = tmp_path / "page.png"
    image = Image.new("RGB", (400, 240), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 399, 63), fill="#24324a")
    draw.rectangle((20, 120, 379, 220), fill="#ffffff", outline="#e0e0e0")
    draw.text((40, 20), "Title", fill="#ffffff")
    draw.text((50, 85), "auto", fill="#333333")
    draw.text((40, 135), "Name", fill="#555555")
    image.save(path)
    graph = {
        "image": str(path),
        "image_w": 400,
        "image_h": 240,
        "route": "grounding",
        "containers": [],
        "elements": [],
        "tables": [
            {
                "name": "Results",
                "bbox": [20, 120, 360, 100],
                "header_texts": ["Name", "Status"],
                "rows": [["Alpha", "Ready"]],
            }
        ],
        "imageEnrichment": {
            "mode": "apply",
            "status": "applied",
            "assets": [
                {
                    "name": "logo",
                    "kind": "logo",
                    "bbox": [330, 15, 40, 35],
                    "source": "slice",
                }
            ],
        },
        "provenance": {"route": "grounding"},
    }
    plan = {
        "schema_version": "grounding-scene-plan/1.0",
        "image_size": [400, 240],
        "coordinate_basis": "source-pixel-top-left",
        "nodes": [
            {
                "id": "header:root",
                "parent_id": None,
                "type": "container",
                "role": "header",
                "bbox": [0, 0, 400, 64],
                "content_ref": None,
                "geometry_ref": "geometry:header",
                "children": ["text:title"],
            },
            {
                "id": "text:title",
                "parent_id": "header:root",
                "type": "text",
                "role": "title",
                "bbox": [40, 20, 120, 24],
                "content_ref": "text:title",
                "geometry_ref": "geometry:title",
                "children": [],
                "text": "Title",
            },
            {
                "id": "form:root",
                "parent_id": None,
                "type": "container",
                "role": "form",
                "bbox": [20, 70, 200, 40],
                "content_ref": None,
                "geometry_ref": "geometry:form",
                "children": ["control:name"],
            },
            {
                "id": "control:name",
                "parent_id": "form:root",
                "type": "control",
                "role": "control",
                "bbox": [40, 72, 160, 32],
                "content_ref": "control:name",
                "geometry_ref": "geometry:name",
                "children": [],
                "text": "auto",
                "control_type": "input",
                "state": "enabled",
                "text_owner_ref": None,
            },
            {
                "id": "asset:logo",
                "parent_id": None,
                "type": "image",
                "role": "logo",
                "bbox": [330, 15, 40, 35],
                "content_ref": "asset:logo",
                "geometry_ref": "geometry:logo",
                "children": [],
                "source_ref": "graph.imageEnrichment.assets[0]",
                "reference_only": True,
                "original": False,
            },
            {
                "id": "table-node:0",
                "parent_id": None,
                "type": "table",
                "role": "table",
                "bbox": [20, 120, 360, 100],
                "content_ref": "table:0",
                "geometry_ref": "geometry:table",
                "children": [
                    "table-header:0:0",
                    "table-cell:0:0",
                ],
            },
            {
                "id": "table-header:0:0",
                "parent_id": "table-node:0",
                "type": "text",
                "role": "table-header",
                "bbox": [20, 120, 180, 35],
                "content_ref": "table-header:0:0",
                "geometry_ref": "geometry:th",
                "children": [],
                "text": "Name",
            },
            {
                "id": "table-cell:0:0",
                "parent_id": "table-node:0",
                "type": "text",
                "role": "table-cell",
                "bbox": [20, 155, 180, 40],
                "content_ref": "table-cell:0:0",
                "geometry_ref": "geometry:tc",
                "children": [],
                "text": "Alpha",
            },
        ],
        "suppressed": [],
    }
    return path, graph, plan


def _compile(path: Path, graph: dict, plan: dict) -> dict:
    return compile_scene_plan_to_design(
        graph,
        inspect_image_reference(path),
        plan,
        image_path=str(path),
        width=400,
        height=240,
        background="#ffffff",
        sample_id="TEST",
    )


def test_compiler_emits_one_owner_per_scene_content_item(tmp_path: Path) -> None:
    path, graph, plan = _fixture(tmp_path)
    design = _compile(path, graph, plan)
    refs = [
        element.get("contentRef")
        for element in design["elements"]
        if element.get("contentRef")
    ]

    assert len(refs) == len(set(refs))
    assert set(refs) == {
        "text:title",
        "control:name",
        "asset:logo",
        "table:0",
        "table-header:0:0",
        "table-cell:0:0",
    }


def test_compiler_keeps_native_fixed_text_and_style_evidence(
    tmp_path: Path,
) -> None:
    path, graph, plan = _fixture(tmp_path)
    design = _compile(path, graph, plan)
    title = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "text:title"
    )

    assert title["type"] == "text"
    assert [title["x"], title["y"], title["width"], title["height"]] == [
        40,
        20,
        120,
        24,
    ]
    assert title["styleEvidence"]["evidence"]["status"] in {
        "observed",
        "low-contrast",
        "low-confidence",
    }
    assert "lineHeight" not in title["style"]


def test_compiler_trims_uniform_light_header_edge(tmp_path: Path) -> None:
    path = tmp_path / "header-edge.png"
    image = Image.new("RGB", (400, 240), "#f4f5f5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 399, 60), fill="#313c49")
    image.save(path)
    graph = {
        "image": str(path),
        "image_w": 400,
        "image_h": 240,
        "route": "grounding",
        "elements": [],
        "tables": [],
    }
    plan = {
        "schema_version": "grounding-scene-plan/1.0",
        "image_size": [400, 240],
        "coordinate_basis": "source-pixel-top-left",
        "nodes": [
            {
                "id": "header:root",
                "parent_id": None,
                "type": "container",
                "role": "header",
                "bbox": [0, 0, 400, 64],
                "content_ref": None,
                "geometry_ref": "geometry:header",
                "children": [],
            }
        ],
        "suppressed": [],
    }

    design = _compile(path, graph, plan)
    header = next(
        element for element in design["elements"] if element.get("id") == "header:root"
    )

    assert header["height"] == 61


def test_compiler_keeps_right_side_text_left_aligned_to_its_ink_box(
    tmp_path: Path,
) -> None:
    path, graph, plan = _fixture(tmp_path)
    plan["nodes"].append(
        {
            "id": "text:user",
            "parent_id": "header:root",
            "type": "text",
            "role": "text",
            "bbox": [260, 20, 110, 24],
            "content_ref": "text:user",
            "geometry_ref": "geometry:user",
            "children": [],
            "text": "刘治强",
        }
    )

    design = _compile(path, graph, plan)
    user = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "text:user"
    )

    assert user["x"] == 260
    assert user["style"]["textAlign"] == "left"


def test_compiler_separates_control_surface_and_value(tmp_path: Path) -> None:
    path, graph, plan = _fixture(tmp_path)
    design = _compile(path, graph, plan)
    control = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "control:name"
    )

    assert control["type"] == "input"
    assert control["controlValue"] == "auto"
    assert control["textBox"] == [52, 78, 136, 20]
    assert not any(
        element.get("text") == "auto" and element is not control
        for element in design["elements"]
    )


def test_compiler_handles_empty_control_without_nan_style(tmp_path: Path) -> None:
    path, graph, plan = _fixture(tmp_path)
    plan["nodes"].append(
        {
            "id": "control:empty",
            "parent_id": None,
            "type": "control",
            "role": "control",
            "bbox": [250, 80, 120, 32],
            "content_ref": "control:empty",
            "geometry_ref": "geometry:empty",
            "children": [],
            "text": "",
            "control_type": "input",
            "state": "enabled",
            "text_owner_ref": None,
        }
    )

    design = _compile(path, graph, plan)
    control = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "control:empty"
    )

    assert control["style"]["textColor"] == "#555555"
    assert control["style"]["fontSize"] > 0


def test_compiler_resolves_control_text_style_from_text_bbox(
    tmp_path: Path,
) -> None:
    path, graph, plan = _fixture(tmp_path)
    plan["nodes"].append(
        {
            "id": "control:remark",
            "parent_id": None,
            "type": "control",
            "role": "control",
            "bbox": [20, 180, 300, 50],
            "content_ref": "control:remark",
            "geometry_ref": "geometry:remark",
            "children": [],
            "text": "2023年12月16日：修改成凌晨3：30执行备份",
            "text_bbox": [30, 190, 250, 20],
            "control_type": "textarea",
            "state": "enabled",
            "text_owner_ref": None,
        }
    )

    design = _compile(path, graph, plan)
    control = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "control:remark"
    )

    assert control["styleEvidence"]["evidence"]["source_bbox"] == [
        30,
        190,
        250,
        20,
    ]
    assert control["textBox"] == [30, 190, 250, 20]
    assert control["style"]["fontSize"] <= 20


def test_compiler_uses_inner_line_box_for_control_text_style(
    tmp_path: Path,
) -> None:
    path, graph, plan = _fixture(tmp_path)
    plan["nodes"].append(
        {
            "id": "control:action",
            "parent_id": None,
            "type": "control",
            "role": "control",
            "bbox": [20, 180, 120, 36],
            "content_ref": "control:action",
            "geometry_ref": "geometry:action",
            "children": [],
            "text": "Action",
            "text_bbox": None,
            "control_type": "button",
            "state": "enabled",
            "text_owner_ref": None,
        }
    )

    design = _compile(path, graph, plan)
    control = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "control:action"
    )

    assert control["styleEvidence"]["evidence"]["source_bbox"] == [
        32,
        188,
        96,
        20,
    ]
    assert control["style"]["fontSize"] <= 20


def test_compiler_expands_fixed_checkbox_label_box(tmp_path: Path) -> None:
    path, graph, plan = _fixture(tmp_path)
    plan["nodes"].append(
        {
            "id": "text:checkbox-label",
            "parent_id": None,
            "type": "text",
            "role": "control-label",
            "bbox": [250, 150, 16, 16],
            "content_ref": "text:checkbox-label",
            "geometry_ref": "geometry:checkbox-label",
            "children": [],
            "text": "以auto用户身份执行",
        }
    )

    design = _compile(path, graph, plan)
    label = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "text:checkbox-label"
    )

    assert label["x"] == 270
    assert label["width"] >= 120


def test_compiler_uses_reference_only_image_fill(tmp_path: Path) -> None:
    path, graph, plan = _fixture(tmp_path)
    design = _compile(path, graph, plan)
    image = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "asset:logo"
    )

    assert image["type"] == "image"
    assert image["imageBase64"]
    assert image["sourceResolution"]["display"]["reference_only"] is True
    assert image["sourceResolution"]["display"]["original"] is False


def test_compiler_preserves_narrow_source_chrome_right_rail(
    tmp_path: Path,
) -> None:
    path = tmp_path / "right-rail.png"
    image = Image.new("RGB", (400, 240), "#ffffff")
    ImageDraw.Draw(image).rectangle((390, 0, 399, 239), fill="#dddddd")
    image.save(path)
    graph = {
        "image": str(path),
        "image_w": 400,
        "image_h": 240,
        "route": "grounding",
        "elements": [],
        "tables": [],
    }
    plan = {
        "schema_version": "grounding-scene-plan/1.0",
        "image_size": [400, 240],
        "coordinate_basis": "source-pixel-top-left",
        "nodes": [],
        "suppressed": [],
    }

    design = _compile(path, graph, plan)
    rail = next(
        element
        for element in design["elements"]
        if element.get("id") == "source-chrome-right-rail"
    )

    assert rail["x"] == 390
    assert rail["width"] == 10
    assert rail["imageBase64"]
    assert rail["imageMVP"]["reference_only"] is True


def test_compiler_renders_icon_button_as_reference_only_source_crop(
    tmp_path: Path,
) -> None:
    path, graph, plan = _fixture(tmp_path)
    plan["nodes"].append(
        {
            "id": "control:exit",
            "parent_id": None,
            "type": "control",
            "role": "control",
            "bbox": [330, 15, 40, 35],
            "content_ref": "control:exit",
            "geometry_ref": "geometry:exit",
            "children": [],
            "text": "9",
            "text_bbox": None,
            "control_type": "icon-button",
            "state": "enabled",
            "text_owner_ref": None,
        }
    )

    design = _compile(path, graph, plan)
    icon = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "control:exit"
    )

    assert icon["type"] == "image"
    assert icon["imageBase64"]
    assert icon["controlType"] == "icon-button"
    assert icon["sourceResolution"]["display"]["reference_only"] is True
    assert icon["sourceResolution"]["display"]["original"] is False


def test_compiler_renders_checked_checkbox_as_reference_only_source_crop(
    tmp_path: Path,
) -> None:
    path, graph, plan = _fixture(tmp_path)
    plan["nodes"].append(
        {
            "id": "control:checked",
            "parent_id": None,
            "type": "control",
            "role": "control",
            "bbox": [330, 15, 20, 20],
            "content_ref": "control:checked",
            "geometry_ref": "geometry:checked",
            "children": [],
            "text": "",
            "text_bbox": None,
            "control_type": "checkbox",
            "state": "checked",
            "text_owner_ref": None,
        }
    )

    design = _compile(path, graph, plan)
    checkbox = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "control:checked"
    )

    assert checkbox["type"] == "image"
    assert checkbox["controlType"] == "checkbox"
    assert checkbox["imageMVP"]["reference_only"] is True


def test_compiler_samples_border_for_button_control(tmp_path: Path) -> None:
    path, graph, plan = _fixture(tmp_path)
    plan["nodes"].append(
        {
            "id": "control:toolbar",
            "parent_id": None,
            "type": "control",
            "role": "control",
            "bbox": [20, 180, 120, 32],
            "content_ref": "control:toolbar",
            "geometry_ref": "geometry:toolbar",
            "children": [],
            "text": "Action",
            "text_bbox": None,
            "control_type": "button",
            "state": "enabled",
            "text_owner_ref": None,
        }
    )

    design = _compile(path, graph, plan)
    button = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "control:toolbar"
    )

    assert button["style"]["borderColor"].startswith("#")
    assert button["style"]["borderWidth"] == 1
    assert button["style"]["borderRadius"] == 6


def test_compiler_groups_adjacent_same_fill_buttons(tmp_path: Path) -> None:
    path, graph, plan = _fixture(tmp_path)
    for node_id, x, text in (
        ("control:copy", 20, "Copy"),
        ("control:export", 80, "Export"),
    ):
        plan["nodes"].append(
            {
                "id": node_id,
                "parent_id": None,
                "type": "control",
                "role": "control",
                "bbox": [
                    x,
                    191 if node_id == "control:export" else 190,
                    60,
                    29 if node_id == "control:export" else 30,
                ],
                "content_ref": node_id,
                "geometry_ref": f"geometry:{node_id}",
                "children": [],
                "text": text,
                "text_bbox": None,
                "control_type": "button",
                "state": "enabled",
                "text_owner_ref": None,
            }
        )

    design = _compile(path, graph, plan)
    group = next(
        element
        for element in design["elements"]
        if str(element.get("id") or "").startswith("control-group:")
    )
    members = [
        element
        for element in design["elements"]
        if element.get("contentRef") in {"control:copy", "control:export"}
    ]
    outline = next(
        element
        for element in design["elements"]
        if element.get("role") == "control-group-outline"
    )
    separators = [
        element
        for element in design["elements"]
        if element.get("role") == "control-group-separator"
    ]

    assert group["x"] == 20
    assert group["width"] == 120
    assert group["style"]["borderWidth"] == 0
    assert len(members) == 2
    assert all(member["style"]["borderWidth"] == 0 for member in members)
    assert all(member["style"]["borderRadius"] == 0 for member in members)
    assert outline["style"]["fillColor"] == "transparent"
    assert outline["style"]["borderWidth"] == 1
    assert len(separators) == 1
    assert separators[0]["x"] == 79
    assert max(design["elements"].index(member) for member in members) > (
        design["elements"].index(group)
    )
    ordered_ids = [
        element.get("id") for _index, element in paint_order(design["elements"])
    ]
    assert all(
        ordered_ids.index(member["id"]) < ordered_ids.index(outline["id"])
        for member in members
    )
    assert ordered_ids.index(outline["id"]) < ordered_ids.index(separators[0]["id"])


def test_compiler_adds_table_decoration_without_text_copy(tmp_path: Path) -> None:
    path, graph, plan = _fixture(tmp_path)
    design = _compile(path, graph, plan)
    grid = [
        element
        for element in design["elements"]
        if str(element.get("id") or "").startswith("table-grid-")
    ]

    assert grid
    assert all(not element.get("text") for element in grid)
    table_texts = [
        element.get("text")
        for element in design["elements"]
        if str(element.get("contentRef") or "").startswith("table-")
    ]
    assert table_texts == ["Name", "Alpha"]


def test_compiler_uses_source_grid_for_table_decorations(
    tmp_path: Path,
) -> None:
    path, graph, plan = _fixture(tmp_path)
    table = next(node for node in plan["nodes"] if node["type"] == "table")
    table["grid"] = {
        "x_boundaries": [20, 80, 380],
        "y_boundaries": [120, 150, 220],
    }

    design = _compile(path, graph, plan)
    verticals = [
        element["x"]
        for element in design["elements"]
        if str(element.get("id") or "").startswith("table-grid-vertical-0-")
    ]
    horizontals = [
        element["y"]
        for element in design["elements"]
        if str(element.get("id") or "").startswith("table-grid-horizontal-0-")
    ]
    header = next(
        element
        for element in design["elements"]
        if element.get("id") == "table-grid-header-0"
    )

    assert verticals == [20, 80, 380]
    assert horizontals == [120, 150, 220]
    assert header["height"] == 30


def test_compiler_aligns_and_vertically_places_table_header_text(
    tmp_path: Path,
) -> None:
    path, graph, plan = _fixture(tmp_path)
    design = _compile(path, graph, plan)
    header = next(
        element
        for element in design["elements"]
        if element.get("contentRef") == "table-header:0:0"
    )

    assert header["style"]["textAlign"] == "center"
    assert header["x"] == 20
    assert header["width"] == 180
    assert header["y"] == 137
    assert header["height"] >= 12


def test_compiler_uses_table_text_bbox_for_fixed_placement(
    tmp_path: Path,
) -> None:
    path, graph, plan = _fixture(tmp_path)
    cell = next(
        node for node in plan["nodes"] if node.get("content_ref") == "table-cell:0:0"
    )
    cell["text_bbox"] = [42, 166, 92, 18]

    design = _compile(path, graph, plan)
    element = next(
        item
        for item in design["elements"]
        if item.get("contentRef") == "table-cell:0:0"
    )

    assert element["x"] == 42
    assert element["y"] == 166
    assert element["style"]["textAlign"] == "left"
    assert element["styleEvidence"]["evidence"]["source_bbox"] == [
        42,
        166,
        92,
        18,
    ]


def test_compiler_matches_table_decorations_by_table_ordinal(
    tmp_path: Path,
) -> None:
    path, graph, plan = _fixture(tmp_path)
    graph["tables"].append(
        {
            "name": "Second",
            "bbox": [20, 200, 360, 40],
            "header_texts": ["A", "B", "C"],
            "rows": [["1", "2", "3"]],
        }
    )
    plan["nodes"].append(
        {
            "id": "table-node:1",
            "parent_id": None,
            "type": "table",
            "role": "table",
            "bbox": [20, 200, 360, 40],
            "content_ref": "table:1",
            "geometry_ref": "geometry:second-table",
            "children": [],
        }
    )

    design = _compile(path, graph, plan)
    first_table_verticals = [
        element
        for element in design["elements"]
        if str(element.get("id") or "").startswith("table-grid-vertical-0-")
    ]
    second_table_verticals = [
        element
        for element in design["elements"]
        if str(element.get("id") or "").startswith("table-grid-vertical-1-")
    ]

    assert len(first_table_verticals) == 3
    assert len(second_table_verticals) == 4


def test_high_fidelity_build_skips_legacy_recovery_stages(
    tmp_path: Path,
) -> None:
    path, graph, plan = _fixture(tmp_path)
    graph["scenePlan"] = plan
    graph["imageEnrichment"]["mode"] = "apply"

    with patch(
        "src.app.services.structure.image_contract._recover_surface_bands",
        side_effect=AssertionError("legacy recovery must not run"),
    ):
        design = build_image_design(graph, inspect_image_reference(path))

    assert design["_meta"]["mode"] == "fixed-canvas-owner-compiler"
