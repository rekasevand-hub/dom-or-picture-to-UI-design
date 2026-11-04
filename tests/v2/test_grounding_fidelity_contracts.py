from __future__ import annotations

import copy

import pytest

from src.app.services.structure.fidelity import (
    build_content_inventory,
    build_evidence_bundle,
    build_geometry_manifest,
)


def _reference(width: int = 1920, height: int = 826) -> dict:
    return {
        "reference_id": "IMG-TEST",
        "input": {
            "path": "fixture.png",
            "sha256": "a" * 64,
            "size": [width, height],
            "mime": "image/png",
            "single_frame": True,
        },
        "state": {
            "mode": "faithful",
            "pixels": "observed",
            "coordinate_basis": "source-pixel-top-left",
        },
    }


def _base_graph(*, width: int = 1920, height: int = 826) -> dict:
    return {
        "image": "fixture.png",
        "image_w": width,
        "image_h": height,
        "route": "grounding",
        "containers": [
            {
                "id": "C1",
                "bbox": [0, 0, width, 56],
                "role": "header",
                "source": "grounding",
                "parent": None,
                "depth": 0,
            },
            {
                "id": "C2",
                "bbox": [0, 56, 300, height - 56],
                "role": "sidebar",
                "source": "grounding",
                "parent": None,
                "depth": 0,
            },
            {
                "id": "C3",
                "bbox": [300, 56, width - 300, height - 56],
                "role": "main",
                "source": "grounding",
                "parent": None,
                "depth": 0,
            },
        ],
        "elements": [],
        "tables": [],
        "imageEnrichment": {
            "mode": "apply",
            "status": "applied",
            "assets": [],
            "backgrounds": [],
        },
        "sliceAnalysis": {
            "assets": [],
            "backgrounds": [],
            "provenance": {"authority": "candidate"},
        },
        "provenance": {
            "route": "grounding",
            "grounding_reliability": {
                "attempt_count": 1,
                "retry_count": 0,
                "status": "accepted",
            },
            "ocr_supplement": {"status": "applied", "added_count": 1},
        },
    }


def _graph_with_five_table_rows() -> dict:
    graph = _base_graph()
    graph["containers"].append(
        {
            "id": "C4",
            "bbox": [300, 550, 1600, 276],
            "role": "table",
            "source": "grounding",
            "parent": "C3",
            "depth": 1,
        }
    )
    graph["tables"] = [
        {
            "name": "Backup history",
            "bbox": [300, 550, 1600, 276],
            "header_texts": ["执行时间", "启动时间", "结果"],
            "rows": [
                ["2026-11-01 03:30:00", "2026-11-01 03:30:02", "执行成功"],
                ["2026-10-31 03:30:00", "2026-10-31 03:30:01", "执行成功"],
                ["2026-10-30 03:30:00", "2026-10-30 03:30:03", "执行成功"],
                ["2026-10-29 03:30:00", "2026-10-29 03:30:02", "执行成功"],
                ["2026-10-28 03:30:00", "2026-10-28 03:30:01", "执行成功"],
            ],
            "source": "image-enrichment",
        }
    ]
    return graph


def _graph_with_checkbox_label() -> dict:
    graph = _base_graph(width=400, height=200)
    graph["containers"] = [
        {
            "id": "C1",
            "bbox": [0, 0, 400, 200],
            "role": "form",
            "source": "grounding",
        }
    ]
    graph["elements"] = [
        {
            "id": 1,
            "bbox": [20, 40, 16, 16],
            "type": "checkbox",
            "controlType": "checkbox",
            "controlValue": "以auto用户身份执行",
            "controlState": "checked",
            "text": "",
            "source": "image-enrichment:control-recovery",
            "container": "C1",
        }
    ]
    return graph


def _graph_with_layout() -> dict:
    graph = _base_graph(width=400, height=240)
    graph["containers"] = [
        {
            "id": "C1",
            "bbox": [0, 0, 400, 40],
            "role": "header",
            "source": "grounding",
        },
        {
            "id": "C2",
            "bbox": [16, 56, 368, 160],
            "role": "form",
            "source": "grounding",
        },
    ]
    graph["elements"] = [
        {
            "id": 1,
            "bbox": [32, 76, 120, 24],
            "type": "text",
            "text": "自动备份管理",
            "source": "grounding",
            "container": "C2",
        },
        {
            "id": 2,
            "bbox": [32, 116, 180, 32],
            "type": "input",
            "controlType": "input",
            "controlValue": "auto",
            "controlState": "enabled",
            "source": "image-enrichment:control-recovery",
            "container": "C2",
        },
    ]
    graph["imageEnrichment"]["assets"] = [
        {
            "name": "logo",
            "kind": "logo",
            "bbox": [8, 8, 120, 24],
            "source": "slice",
            "visibleCrop": {"payload_sha256": "b" * 64},
        }
    ]
    graph["sliceAnalysis"]["assets"] = copy.deepcopy(graph["imageEnrichment"]["assets"])
    return graph


def test_inventory_preserves_all_table_rows_and_full_timestamps() -> None:
    bundle = build_evidence_bundle(
        _graph_with_five_table_rows(),
        _reference(),
    )
    inventory = build_content_inventory(bundle)

    table = inventory["tables"][0]
    assert len(table["rows"]) == 5
    assert table["rows"][0][1] == "2026-11-01 03:30:02"
    assert table["headers"] == ["执行时间", "启动时间", "结果"]
    assert (
        len(
            [
                item
                for item in inventory["items"]
                if item.get("kind") == "table-cell"
                and item.get("table_id") == table["id"]
            ]
        )
        == 15
    )


def test_checkbox_label_and_control_have_distinct_inventory_items() -> None:
    bundle = build_evidence_bundle(
        _graph_with_checkbox_label(),
        _reference(400, 200),
    )
    inventory = build_content_inventory(bundle)

    controls = [item for item in inventory["items"] if item["kind"] == "control"]
    assert len(controls) == 1
    assert controls[0]["state"] == "checked"
    assert controls[0]["text"] == ""
    assert any(
        item["kind"] == "text" and item["text"] == "以auto用户身份执行"
        for item in inventory["items"]
    )


def test_geometry_manifest_keeps_source_pixel_boxes() -> None:
    bundle = build_evidence_bundle(_graph_with_layout(), _reference(400, 240))
    geometry = build_geometry_manifest(bundle)

    assert geometry["image_size"] == [400, 240]
    assert all(
        item["bbox"][2] > 0 and item["bbox"][3] > 0 for item in geometry["items"]
    )
    assert any(
        item["kind"] == "container" and item["role"] == "form"
        for item in geometry["items"]
    )
    assert any(item["kind"] == "control" for item in geometry["items"])
    assert any(item["kind"] == "asset" for item in geometry["items"])


def test_evidence_bundle_retains_provenance_and_source_records() -> None:
    graph = _graph_with_layout()
    reference = _reference(400, 240)
    bundle = build_evidence_bundle(graph, reference)

    assert bundle["reference"]["input"]["sha256"] == "a" * 64
    assert bundle["provenance"]["grounding_reliability"]["status"] == "accepted"
    assert bundle["sources"]["graph"]["tables"] == graph["tables"]
    assert bundle["sources"]["graph"]["sliceAnalysis"]["provenance"] == {
        "authority": "candidate"
    }
    assert any(record["kind"] == "asset" for record in bundle["records"])
    assert all(
        {
            "id",
            "kind",
            "status",
            "authority",
            "confidence",
            "bbox",
            "payload_ref",
            "reason",
        }
        <= set(record)
        for record in bundle["records"]
    )


def test_evidence_and_geometry_are_immutable_copies() -> None:
    graph = _graph_with_layout()
    reference = _reference(400, 240)
    bundle = build_evidence_bundle(graph, reference)
    inventory = build_content_inventory(bundle)
    geometry = build_geometry_manifest(bundle)

    graph["elements"][0]["text"] = "mutated"
    bundle["sources"]["graph"]["containers"][0]["role"] = "mutated"
    assert inventory["items"][0]["text"] != "mutated"
    assert geometry["items"][1]["role"] != "mutated"


def test_invalid_reference_fails_closed() -> None:
    reference = _reference()
    reference["input"]["size"] = [0, 826]

    with pytest.raises(ValueError, match="reference.*size"):
        build_evidence_bundle(_base_graph(), reference)
