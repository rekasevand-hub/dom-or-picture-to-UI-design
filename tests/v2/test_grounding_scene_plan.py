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
