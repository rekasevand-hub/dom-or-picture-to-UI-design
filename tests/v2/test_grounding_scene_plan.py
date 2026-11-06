from __future__ import annotations

import copy

import pytest

from src.app.services.structure.fidelity.scene_plan import (
    apply_scene_plan,
    build_scene_plan,
)


def _base_graph() -> dict:
    return {
        "image": "fixture.png",
        "image_w": 400,
        "image_h": 240,
        "route": "grounding",
        "containers": [
            {
                "id": "status",
                "bbox": [8, 8, 368, 64],
                "role": "form",
                "source": "grounding",
            }
        ],
        "elements": [
            {
                "id": 10,
                "bbox": [20, 24, 16, 16],
                "type": "checkbox",
                "controlType": "checkbox",
                "controlValue": "以auto用户身份执行",
                "controlState": "checked",
                "source": "image-enrichment:control-recovery",
                "container": "status",
            }
        ],
        "tables": [],
        "provenance": {"route": "grounding"},
    }


def _geometry() -> dict:
    return {
        "schema_version": "grounding-geometry-manifest/1.0",
        "image_size": [400, 240],
        "coordinate_basis": "source-pixel-top-left",
        "items": [
            {
                "id": "geometry:page",
                "kind": "page",
                "role": "page",
                "bbox": [0, 0, 400, 240],
                "content_ref": None,
            },
            {
                "id": "geometry:status",
                "kind": "container",
                "role": "form",
                "bbox": [8, 8, 368, 64],
                "content_ref": None,
                "source_ref": "graph.containers[0]",
            },
        ],
    }


def _inventory_with_checkbox_label() -> dict:
    return {
        "schema_version": "grounding-content-inventory/1.0",
        "image_size": [400, 240],
        "items": [
            {
                "id": "control:10",
                "kind": "control",
                "text": "",
                "label": "以auto用户身份执行",
                "control_type": "checkbox",
                "state": "checked",
                "bbox": [20, 24, 16, 16],
                "role": "",
                "source_ref": "graph.elements[0]",
                "authority": "image-enrichment",
            },
            {
                "id": "text:checkbox-label",
                "kind": "text",
                "text": "以auto用户身份执行",
                "bbox": [44, 22, 180, 20],
                "role": "control-label",
                "source_ref": "graph.elements[0]",
                "authority": "grounding",
            },
        ],
        "tables": [],
        "unknowns": [],
    }


def _graph_with_duplicate_table_text() -> dict:
    graph = _base_graph()
    graph["containers"].append(
        {
            "id": "results",
            "bbox": [20, 88, 340, 128],
            "role": "table",
            "source": "grounding",
        }
    )
    graph["elements"].append(
        {
            "id": 11,
            "bbox": [36, 120, 80, 20],
            "type": "text",
            "text": "Alpha",
            "source": "grounding",
            "container": "results",
        }
    )
    graph["tables"] = [
        {
            "id": 0,
            "bbox": [20, 88, 340, 128],
            "header_texts": ["Name", "Status"],
            "rows": [["Alpha", "Ready"]],
            "source": "image-enrichment",
        }
    ]
    return graph


def _inventory_with_table_rows() -> dict:
    return {
        "schema_version": "grounding-content-inventory/1.0",
        "image_size": [400, 240],
        "items": [
            {
                "id": "text:duplicate",
                "kind": "text",
                "text": "Alpha",
                "bbox": [36, 120, 80, 20],
                "role": "",
                "source_ref": "graph.elements[1]",
                "authority": "grounding",
            },
            {
                "id": "table:0:1",
                "kind": "table-cell",
                "text": "Alpha",
                "table_id": "0",
                "row_index": 0,
                "column_index": 0,
                "bbox": [20, 128, 170, 44],
                "role": "table-cell",
                "source_ref": "graph.tables[0].rows[0][0]",
                "authority": "image-enrichment",
            },
        ],
        "tables": [
            {
                "id": "0",
                "name": "Results",
                "bbox": [20, 88, 340, 128],
                "headers": ["Name", "Status"],
                "rows": [["Alpha", "Ready"]],
                "row_count": 1,
                "column_count": 2,
                "source_ref": "graph.tables[0]",
            }
        ],
        "unknowns": [],
    }


def _geometry_with_table_grid() -> dict:
    geometry = _geometry()
    geometry["items"].append(
        {
            "id": "geometry:table",
            "kind": "table",
            "role": "table",
            "bbox": [20, 88, 340, 128],
            "content_ref": "0",
            "source_ref": "graph.tables[0]",
        }
    )
    return geometry


def _graph_with_slice_assets() -> dict:
    graph = _base_graph()
    graph["imageEnrichment"] = {
        "mode": "apply",
        "assets": [
            {
                "name": "brand_logo",
                "kind": "logo",
                "bbox": [260, 16, 120, 32],
                "source": "slice",
            }
        ],
    }
    graph["sliceAnalysis"] = {
        "assets": [
            {
                "name": "brand_logo",
                "kind": "logo",
                "bbox": [260, 16, 120, 32],
                "source": "slice",
            }
        ]
    }
    return graph


def _inventory_with_reference_assets() -> dict:
    return {
        "schema_version": "grounding-content-inventory/1.0",
        "image_size": [400, 240],
        "items": [
            {
                "id": "asset:brand-logo",
                "kind": "asset",
                "text": "brand_logo",
                "asset_kind": "logo",
                "bbox": [260, 16, 120, 32],
                "reference_only": True,
                "original": False,
                "source_ref": "graph.sliceAnalysis.assets[0]",
                "authority": "slice",
            }
        ],
        "tables": [],
        "unknowns": [],
    }


def _geometry_with_asset_boxes() -> dict:
    geometry = _geometry()
    geometry["items"].append(
        {
            "id": "geometry:brand-logo",
            "kind": "asset",
            "role": "logo",
            "bbox": [260, 16, 120, 32],
            "content_ref": "asset:brand-logo",
        }
    )
    return geometry


def test_checkbox_label_has_one_text_owner() -> None:
    plan = build_scene_plan(
        _base_graph(),
        _inventory_with_checkbox_label(),
        _geometry(),
    )

    labels = [
        node for node in plan["nodes"] if node["content_ref"] == "text:checkbox-label"
    ]
    assert len(labels) == 1
    assert labels[0]["parent_id"] == "form:status"
    assert labels[0]["role"] == "control-label"
    control = next(
        node for node in plan["nodes"] if node["content_ref"] == "control:10"
    )
    assert control["text_owner_ref"] == "text:checkbox-label"


def test_table_cell_has_exactly_one_owner() -> None:
    plan = build_scene_plan(
        _graph_with_duplicate_table_text(),
        _inventory_with_table_rows(),
        _geometry_with_table_grid(),
    )

    owners = [node for node in plan["nodes"] if node["content_ref"] == "table:0:1"]
    assert len(owners) == 1
    assert owners[0]["type"] == "text"
    assert owners[0]["parent_id"] == "table-node:0"
    assert any(item["source_ref"] == "graph.elements[1]" for item in plan["suppressed"])


def test_slice_asset_cannot_create_a_second_layout_tree() -> None:
    plan = build_scene_plan(
        _graph_with_slice_assets(),
        _inventory_with_reference_assets(),
        _geometry_with_asset_boxes(),
    )

    assets = [
        node
        for node in plan["nodes"]
        if str(node.get("content_ref") or "").startswith("asset:")
    ]
    assert len(assets) == 1
    assert assets[0]["type"] == "image"
    assert assets[0]["reference_only"] is True
    assert assets[0]["original"] is False
    assert all(node["type"] != "container" for node in assets)


def test_brand_logo_owner_suppresses_overlapping_text() -> None:
    inventory = {
        "schema_version": "grounding-content-inventory/1.0",
        "image_size": [400, 240],
        "items": [
            {
                "id": "asset:brand",
                "kind": "asset",
                "text": "chrome_brand",
                "bbox": [90, 16, 160, 24],
                "role": "ui-icon",
                "reference_only": True,
                "original": False,
                "source_ref": "graph.imageEnrichment.assets[0]",
                "authority": "source-pixel",
            },
            {
                "id": "text:brand",
                "kind": "text",
                "text": "FlexWeaver",
                "bbox": [108, 18, 140, 20],
                "role": "text",
                "source_ref": "graph.elements[0]",
                "authority": "grounding",
            },
        ],
        "tables": [],
        "unknowns": [],
    }
    plan = build_scene_plan(_base_graph(), inventory, _geometry())

    assert any(node["content_ref"] == "asset:brand" for node in plan["nodes"])
    assert not any(node["content_ref"] == "text:brand" for node in plan["nodes"])
    assert any(
        item["content_ref"] == "text:brand" and item["replacement_ref"] == "asset:brand"
        for item in plan["suppressed"]
    )


def test_apply_scene_plan_suppresses_duplicate_and_preserves_source() -> None:
    graph = _graph_with_duplicate_table_text()
    plan = build_scene_plan(
        graph,
        _inventory_with_table_rows(),
        _geometry_with_table_grid(),
    )
    applied = apply_scene_plan(graph, plan)

    assert applied["scenePlan"]["schema_version"] == plan["schema_version"]
    assert [item["id"] for item in applied["elements"]] == [10]
    assert graph["elements"][1]["text"] == "Alpha"
    assert applied["containers"][0]["sceneOwnerId"] == "form:status"
    assert applied["tables"][0]["sceneOwnerId"] == "table-node:0"


def test_apply_keeps_control_owner_when_label_shares_source() -> None:
    graph = _base_graph()
    plan = build_scene_plan(
        graph,
        _inventory_with_checkbox_label(),
        _geometry(),
    )
    applied = apply_scene_plan(graph, plan)

    control = applied["elements"][0]
    assert control["contentRef"] == "control:10"
    assert control["textOwnerRef"] == "text:checkbox-label"


def test_plan_rejects_duplicate_content_owners() -> None:
    plan = build_scene_plan(
        _base_graph(),
        _inventory_with_checkbox_label(),
        _geometry(),
    )
    malformed = copy.deepcopy(plan)
    malformed["nodes"].append(copy.deepcopy(malformed["nodes"][-1]))
    malformed["nodes"][-1]["id"] = "duplicate-owner"

    with pytest.raises(ValueError, match="duplicate content owner"):
        apply_scene_plan(_base_graph(), malformed)


def test_plan_keeps_source_pixel_boxes_without_translation() -> None:
    plan = build_scene_plan(
        _base_graph(),
        _inventory_with_checkbox_label(),
        _geometry(),
    )

    assert plan["image_size"] == [400, 240]
    assert plan["coordinate_basis"] == "source-pixel-top-left"
    label = next(
        node for node in plan["nodes"] if node["content_ref"] == "text:checkbox-label"
    )
    assert label["bbox"] == [44, 22, 180, 20]


def test_overlapping_table_header_suppresses_ocr_text_owner() -> None:
    graph = _graph_with_duplicate_table_text()
    inventory = _inventory_with_table_rows()
    inventory["items"].append(
        {
            "id": "table-header:time",
            "kind": "table-header",
            "text": "执行时间",
            "table_id": "0",
            "row_index": None,
            "column_index": 0,
            "bbox": [20, 88, 170, 40],
            "role": "table-cell",
            "source_ref": "graph.tables[0].header_texts[0]",
            "authority": "image-enrichment",
        }
    )
    inventory["items"].append(
        {
            "id": "text:ocr-noise",
            "kind": "text",
            "text": "执行#间",
            "bbox": [30, 96, 100, 20],
            "role": "",
            "source_ref": "graph.elements[0]",
            "authority": "ocr",
        }
    )
    plan = build_scene_plan(graph, inventory, _geometry_with_table_grid())

    assert not any(node["content_ref"] == "text:ocr-noise" for node in plan["nodes"])
    header = next(
        node for node in plan["nodes"] if node["content_ref"] == "table-header:time"
    )
    assert header.get("text_bbox") is None
    assert any(
        item["content_ref"] == "text:ocr-noise"
        and item["reason"] == "overlapping-text-owner"
        for item in plan["suppressed"]
    )


def test_table_header_does_not_absorb_ocr_text_bbox() -> None:
    inventory = _inventory_with_table_rows()
    inventory["items"].append(
        {
            "id": "table-header:time",
            "kind": "table-header",
            "text": "执行时间",
            "table_id": "0",
            "row_index": None,
            "column_index": 0,
            "bbox": [20, 88, 170, 40],
            "role": "table-cell",
            "source_ref": "graph.tables[0].header_texts[0]",
            "authority": "image-enrichment",
        }
    )
    inventory["items"].append(
        {
            "id": "text:table-header-ocr",
            "kind": "text",
            "text": "执行时间",
            "bbox": [42, 96, 80, 20],
            "role": "",
            "source_ref": "graph.elements[0]",
            "authority": "ocr",
        }
    )

    plan = build_scene_plan(
        _graph_with_duplicate_table_text(),
        inventory,
        _geometry_with_table_grid(),
    )
    header = next(
        node for node in plan["nodes"] if node["content_ref"] == "table-header:time"
    )

    assert header.get("text_bbox") is None


def test_grounded_control_label_beats_overlapping_ocr_variant() -> None:
    inventory = _inventory_with_checkbox_label()
    inventory["items"].append(
        {
            "id": "text:ocr-label",
            "kind": "text",
            "text": "Wauto用户身份执行",
            "bbox": [44, 22, 180, 20],
            "role": "control-label",
            "source_ref": "graph.elements[0]",
            "authority": "ocr",
        }
    )
    plan = build_scene_plan(_base_graph(), inventory, _geometry())

    refs = {node["content_ref"] for node in plan["nodes"]}
    assert "text:checkbox-label" in refs
    assert "text:ocr-label" not in refs
    assert any(
        item["content_ref"] == "text:ocr-label"
        and item["replacement_ref"] == "text:checkbox-label"
        for item in plan["suppressed"]
    )


def test_control_value_absorbs_duplicate_text_inside_its_box() -> None:
    inventory = {
        "schema_version": "grounding-content-inventory/1.0",
        "image_size": [400, 240],
        "items": [
            {
                "id": "control:name",
                "kind": "control",
                "text": "auto_backup",
                "control_type": "input",
                "state": "enabled",
                "bbox": [100, 40, 200, 32],
                "role": "",
                "source_ref": "graph.elements[0]",
                "authority": "image-enrichment",
            },
            {
                "id": "text:duplicate-value",
                "kind": "text",
                "text": "auto_backup",
                "bbox": [112, 46, 100, 20],
                "role": "",
                "source_ref": "graph.elements[1]",
                "authority": "ocr",
            },
        ],
        "tables": [],
        "unknowns": [],
    }
    geometry = _geometry()
    geometry["items"].append(
        {
            "id": "geometry:name",
            "kind": "control",
            "role": "input",
            "bbox": [100, 40, 200, 32],
            "content_ref": "control:name",
        }
    )
    plan = build_scene_plan(_base_graph(), inventory, geometry)

    refs = {node["content_ref"] for node in plan["nodes"]}
    assert "control:name" in refs
    assert "text:duplicate-value" not in refs


def test_control_value_absorbs_similar_ocr_text_with_its_geometry() -> None:
    inventory = {
        "schema_version": "grounding-content-inventory/1.0",
        "image_size": [400, 240],
        "items": [
            {
                "id": "control:remark",
                "kind": "control",
                "text": "2023年12月16日：修改成凌晨3：30执行备份",
                "control_type": "textarea",
                "state": "enabled",
                "bbox": [100, 40, 260, 72],
                "role": "",
                "source_ref": "graph.elements[0]",
                "authority": "image-enrichment",
            },
            {
                "id": "text:remark-ocr",
                "kind": "text",
                "text": "2023年12月16日: 修改成麦晨3: 30执行备份",
                "bbox": [112, 52, 180, 20],
                "role": "",
                "source_ref": "graph.elements[1]",
                "authority": "ocr",
            },
        ],
        "tables": [],
        "unknowns": [],
    }
    geometry = _geometry()
    geometry["items"].append(
        {
            "id": "geometry:remark",
            "kind": "control",
            "role": "textarea",
            "bbox": [100, 40, 260, 72],
            "content_ref": "control:remark",
        }
    )
    plan = build_scene_plan(_base_graph(), inventory, geometry)

    control = next(
        node for node in plan["nodes"] if node["content_ref"] == "control:remark"
    )
    assert control["text_bbox"] == [112, 52, 180, 20]
    assert not any(node["content_ref"] == "text:remark-ocr" for node in plan["nodes"])
    assert any(
        item["content_ref"] == "text:remark-ocr"
        and item["reason"] == "control-value-owner-authoritative"
        and item["replacement_ref"] == "control:remark"
        for item in plan["suppressed"]
    )


def test_control_text_owner_must_be_geometrically_local() -> None:
    inventory = {
        "schema_version": "grounding-content-inventory/1.0",
        "image_size": [400, 240],
        "items": [
            {
                "id": "control:name",
                "kind": "control",
                "text": "自动备份",
                "control_type": "input",
                "state": "enabled",
                "bbox": [100, 40, 200, 32],
                "role": "",
                "source_ref": "graph.elements[0]",
                "authority": "image-enrichment",
            },
            {
                "id": "text:far-title",
                "kind": "text",
                "text": "自动备份",
                "bbox": [100, 150, 120, 20],
                "role": "title",
                "source_ref": "graph.elements[0]",
                "authority": "grounding",
            },
        ],
        "tables": [],
        "unknowns": [],
    }
    geometry = _geometry()
    geometry["items"].extend(
        [
            {
                "id": "geometry:name",
                "kind": "control",
                "role": "input",
                "bbox": [100, 40, 200, 32],
                "content_ref": "control:name",
            },
            {
                "id": "geometry:far-title",
                "kind": "text",
                "role": "title",
                "bbox": [100, 150, 120, 20],
                "content_ref": "text:far-title",
            },
        ]
    )
    plan = build_scene_plan(_base_graph(), inventory, geometry)

    control = next(
        node for node in plan["nodes"] if node["content_ref"] == "control:name"
    )
    assert control["text_owner_ref"] is None


def test_table_misclassified_text_control_uses_table_text_owner() -> None:
    inventory = _inventory_with_table_rows()
    inventory["items"].append(
        {
            "id": "control:fake-result",
            "kind": "control",
            "text": "Alpha",
            "control_type": "input",
            "state": "enabled",
            "bbox": [20, 128, 170, 44],
            "role": "",
            "source_ref": "graph.elements[0]",
            "authority": "grounding",
        }
    )
    geometry = _geometry_with_table_grid()
    geometry["items"][-1]["grid"] = {
        "x_boundaries": [20, 190, 360],
        "y_boundaries": [88, 128, 172, 216],
    }
    plan = build_scene_plan(
        _graph_with_duplicate_table_text(),
        inventory,
        geometry,
    )

    refs = {node["content_ref"] for node in plan["nodes"]}
    assert "control:fake-result" not in refs
    assert any(
        item["content_ref"] == "control:fake-result"
        and item["reason"] == "table-text-owner-authoritative"
        for item in plan["suppressed"]
    )


def test_table_toolbar_button_is_moved_above_grid() -> None:
    graph = _graph_with_duplicate_table_text()
    inventory = {
        "schema_version": "grounding-content-inventory/1.0",
        "image_size": [400, 240],
        "items": [
            {
                "id": "control:pause",
                "kind": "control",
                "text": "暂停自动刷新",
                "control_type": "button",
                "state": "enabled",
                "bbox": [30, 130, 120, 36],
                "role": "",
                "source_ref": "graph.elements[0]",
                "authority": "grounding",
            }
        ],
        "tables": [
            {
                "id": "0",
                "name": "Results",
                "bbox": [20, 88, 340, 128],
                "headers": ["Name", "Status"],
                "rows": [["Alpha", "Ready"]],
                "row_count": 1,
                "column_count": 2,
                "source_ref": "graph.tables[0]",
            }
        ],
        "unknowns": [],
    }
    geometry = _geometry_with_table_grid()
    geometry["items"][-1]["grid"] = {
        "x_boundaries": [20, 190, 360],
        "y_boundaries": [88, 128, 172, 216],
    }
    plan = build_scene_plan(graph, inventory, geometry)

    control = next(
        node for node in plan["nodes"] if node["content_ref"] == "control:pause"
    )
    assert control["bbox"][1] < 88
    assert control["bbox"][0] == 20


def test_table_node_preserves_detected_grid_evidence() -> None:
    geometry = _geometry_with_table_grid()
    geometry["items"][-1]["grid"] = {
        "x_boundaries": [20, 80, 360],
        "y_boundaries": [88, 120, 216],
    }
    plan = build_scene_plan(
        _graph_with_duplicate_table_text(),
        _inventory_with_table_rows(),
        geometry,
    )

    table = next(node for node in plan["nodes"] if node["type"] == "table")
    assert table["grid"] == {
        "x_boundaries": [20, 80, 360],
        "y_boundaries": [88, 120, 216],
    }
