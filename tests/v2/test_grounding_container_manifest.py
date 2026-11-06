from __future__ import annotations

import pytest

from src.app.services.structure.fidelity.container_manifest import (
    build_container_manifest,
)


def _scene_plan() -> dict:
    return {
        "schema_version": "grounding-scene-plan/1.0",
        "image_size": [1920, 826],
        "coordinate_basis": "source-pixel-top-left",
        "nodes": [
            {
                "id": "header:root",
                "parent_id": None,
                "type": "container",
                "role": "header",
                "bbox": [0, 0, 1920, 60],
                "content_ref": None,
                "geometry_ref": "geometry:header",
                "children": ["account:user", "form:root"],
            },
            {
                "id": "account:user",
                "parent_id": "header:root",
                "type": "control",
                "role": "account",
                "bbox": [1709, 12, 115, 39],
                "content_ref": "control:account",
                "geometry_ref": "geometry:account",
                "children": ["text:name"],
            },
            {
                "id": "text:name",
                "parent_id": "account:user",
                "type": "text",
                "role": "text",
                "bbox": [1753, 25, 48, 18],
                "content_ref": "text:name",
                "geometry_ref": "geometry:name",
                "children": [],
                "text": "刘治强",
            },
            {
                "id": "form:root",
                "parent_id": "header:root",
                "type": "container",
                "role": "form",
                "bbox": [100, 100, 800, 300],
                "content_ref": None,
                "geometry_ref": "geometry:form",
                "children": ["text:label"],
            },
            {
                "id": "text:label",
                "parent_id": "form:root",
                "type": "text",
                "role": "text",
                "bbox": [120, 130, 60, 20],
                "content_ref": "text:label",
                "geometry_ref": "geometry:label",
                "children": [],
                "text": "名称",
            },
        ],
    }


def test_root_sized_authoring_frame_keeps_distinct_source_bbox() -> None:
    manifest = build_container_manifest(
        _scene_plan(),
        authoring_frames={
            "header:root": {
                "authoring_bbox": [0, 0, 1920, 826],
                "layout_mode": "fixed-canvas-absolute",
            }
        },
    )

    header = manifest["containers"][0]
    assert header["source_bbox"] == [0, 0, 1920, 60]
    assert header["authoring_bbox"] == [0, 0, 1920, 826]
    assert header["layout_mode"] == "fixed-canvas-absolute"


def test_child_transform_is_derived_from_authoring_origin() -> None:
    manifest = build_container_manifest(
        _scene_plan(),
        authoring_frames={
            "header:root": {
                "authoring_bbox": [100, 50, 900, 400],
                "layout_mode": "fixed-canvas-absolute",
            }
        },
    )
    transform = next(
        item
        for item in manifest["child_transforms"]
        if item["owner_id"] == "account:user"
    )

    assert transform["parent_id"] == "header:root"
    assert transform["source_bbox"] == [1709, 12, 115, 39]
    assert transform["local_bbox"] == [1609, -38, 115, 39]


def test_invalid_authoring_bbox_fails_closed() -> None:
    with pytest.raises(ValueError, match="authoring_bbox"):
        build_container_manifest(
            _scene_plan(),
            authoring_frames={
                "header:root": {
                    "authoring_bbox": [0, 0, 0, 826],
                }
            },
        )


def test_container_manifest_includes_controls_that_own_children() -> None:
    manifest = build_container_manifest(_scene_plan())

    assert [item["owner_id"] for item in manifest["containers"]] == [
        "header:root",
        "account:user",
        "form:root",
    ]
    assert all(
        item["layout_mode"] == "fixed-canvas-absolute"
        for item in manifest["containers"]
    )
