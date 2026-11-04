from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.app.services.structure.fidelity.local_repair import GroundingLocalRepairer


class _RecordingGroundingBackend:
    def __init__(self, raw: dict | None = None) -> None:
        self.raw = raw or {
            "elements": [
                {
                    "type": "text",
                    "text": "2026-11-01 03:30:00",
                    "bbox": [10, 20, 80, 30],
                }
            ]
        }
        self.calls: list[dict] = []

    def ground(self, image_path, image_w, image_h):
        self.calls.append(
            {
                "path": Path(image_path),
                "size": [image_w, image_h],
            }
        )
        return self.raw


def _fixture_image(tmp_path: Path) -> Path:
    path = tmp_path / "page.png"
    Image.new("RGB", (1920, 826), "white").save(path)
    return path


def _table_request(*, bbox: list[int]) -> dict:
    return {
        "id": "request-table",
        "kind": "table",
        "bbox": bbox,
        "target_ids": ["table-node:0"],
        "reason": "missing table rows",
        "acceptance": {"must_resolve": True},
    }


def _scene_plan() -> dict:
    return {
        "schema_version": "grounding-scene-plan/1.0",
        "image_size": [1920, 826],
        "coordinate_basis": "source-pixel-top-left",
        "nodes": [
            {
                "id": "main:main",
                "parent_id": None,
                "type": "container",
                "role": "main",
                "bbox": [300, 56, 1620, 770],
                "content_ref": None,
                "geometry_ref": "",
                "children": ["table-node:0"],
            },
            {
                "id": "table-node:0",
                "parent_id": "main:main",
                "type": "table",
                "role": "table",
                "bbox": [300, 550, 1600, 276],
                "content_ref": "0",
                "geometry_ref": "",
                "children": [],
            },
        ],
        "suppressed": [],
    }


def test_table_repair_crops_only_requested_region(tmp_path: Path) -> None:
    backend = _RecordingGroundingBackend()
    repairer = GroundingLocalRepairer(backend)
    patch = repairer.repair(
        _table_request(bbox=[300, 550, 1600, 276]),
        _fixture_image(tmp_path),
        _scene_plan(),
    )

    assert backend.calls[0]["size"] == [1600, 276]
    assert backend.calls[0]["path"].suffix == ".png"
    assert patch["region_id"] == "table"
    assert patch["target_ids"] == ["table-node:0"]


def test_repair_patch_boxes_are_translated_to_page_coordinates(
    tmp_path: Path,
) -> None:
    backend = _RecordingGroundingBackend(
        {
            "elements": [
                {
                    "type": "text",
                    "text": "2026-11-01 03:30:00",
                    "bbox": [10, 20, 80, 30],
                }
            ]
        }
    )
    patch = GroundingLocalRepairer(backend).repair(
        _table_request(bbox=[300, 550, 1600, 276]),
        _fixture_image(tmp_path),
        _scene_plan(),
    )

    node = patch["operations"][0]["node"]
    assert node["bbox"] == [310, 570, 80, 30]
    assert node["parent_id"] == "table-node:0"


def test_repair_accepts_backend_operations_and_translates_nested_boxes(
    tmp_path: Path,
) -> None:
    backend = _RecordingGroundingBackend(
        {
            "operations": [
                {
                    "op": "add_node",
                    "node": {
                        "id": "fixed-row",
                        "parent_id": "table-node:0",
                        "type": "text",
                        "role": "table-cell",
                        "bbox": [4, 6, 100, 20],
                        "content_ref": "table:0:1",
                        "geometry_ref": "",
                        "children": [],
                    },
                }
            ]
        }
    )
    patch = GroundingLocalRepairer(backend).repair(
        _table_request(bbox=[300, 550, 1600, 276]),
        _fixture_image(tmp_path),
        _scene_plan(),
    )

    assert patch["operations"][0]["node"]["bbox"] == [304, 556, 100, 20]


def test_identical_crop_and_request_are_cached(tmp_path: Path) -> None:
    backend = _RecordingGroundingBackend()
    repairer = GroundingLocalRepairer(backend)
    request = _table_request(bbox=[300, 550, 1600, 276])
    path = _fixture_image(tmp_path)

    first = repairer.repair(request, path, _scene_plan())
    second = repairer.repair(request, path, _scene_plan())

    assert first == second
    assert len(backend.calls) == 1


def test_repair_clamps_expanded_crop_to_canvas(tmp_path: Path) -> None:
    backend = _RecordingGroundingBackend()
    repairer = GroundingLocalRepairer(backend, crop_padding=20)
    patch = repairer.repair(
        _table_request(bbox=[0, 0, 100, 50]),
        _fixture_image(tmp_path),
        _scene_plan(),
    )

    assert backend.calls[0]["size"] == [120, 70]
    assert patch["crop"]["bbox"] == [0, 0, 120, 70]


def test_invalid_or_outside_region_is_rejected(tmp_path: Path) -> None:
    repairer = GroundingLocalRepairer(_RecordingGroundingBackend())
    with pytest.raises(ValueError, match="repair bbox"):
        repairer.repair(
            _table_request(bbox=[2000, 900, 10, 10]),
            _fixture_image(tmp_path),
            _scene_plan(),
        )


def test_backend_without_structural_output_returns_none(tmp_path: Path) -> None:
    repairer = GroundingLocalRepairer(_RecordingGroundingBackend({"elements": []}))
    patch = repairer.repair(
        _table_request(bbox=[300, 550, 1600, 276]),
        _fixture_image(tmp_path),
        _scene_plan(),
    )

    assert patch is None
