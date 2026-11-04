from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from src.app.services.evidence.region_quality import evaluate_region_quality


def _images_with_changed_table_only(tmp_path: Path) -> tuple[Path, Path]:
    reference = np.full((200, 200, 3), 255, dtype=np.uint8)
    render = reference.copy()
    reference[100:200, 0:200] = [245, 245, 245]
    render[100:200, 0:200] = [10, 20, 30]
    reference_path = tmp_path / "reference.png"
    render_path = tmp_path / "render.png"
    Image.fromarray(reference).save(reference_path)
    Image.fromarray(render).save(render_path)
    return reference_path, render_path


def _different_size_images(tmp_path: Path) -> tuple[Path, Path]:
    reference_path = tmp_path / "reference.png"
    render_path = tmp_path / "render.png"
    Image.new("RGB", (200, 200), "white").save(reference_path)
    Image.new("RGB", (100, 100), "white").save(render_path)
    return reference_path, render_path


def test_region_metrics_expose_local_regression(tmp_path: Path) -> None:
    reference, render = _images_with_changed_table_only(tmp_path)
    result = evaluate_region_quality(
        reference,
        render,
        [
            {"id": "form", "bbox": [0, 0, 200, 100]},
            {"id": "table", "bbox": [0, 100, 200, 100]},
        ],
    )

    assert result["status"] == "measured"
    assert result["regions"]["form"]["bad_pixel_ratio"] == 0.0
    assert result["regions"]["table"]["bad_pixel_ratio"] == 1.0
    assert result["regions"]["table"]["mae"] > result["regions"]["form"]["mae"]


def test_region_metrics_fail_on_size_mismatch(tmp_path: Path) -> None:
    result = evaluate_region_quality(*_different_size_images(tmp_path), [])

    assert result["status"] == "blocked"
    assert result["size_match"] is False


def test_region_metrics_clamp_boxes_to_canvas(tmp_path: Path) -> None:
    reference, render = _images_with_changed_table_only(tmp_path)
    result = evaluate_region_quality(
        reference,
        render,
        [{"id": "table", "role": "table", "bbox": [-20, 90, 260, 160]}],
    )

    region = result["regions"]["table"]
    assert region["bbox"] == [0, 90, 200, 110]
    assert region["role"] == "table"
    assert region["pixel_count"] == 22000


def test_region_metrics_reject_empty_and_duplicate_regions(tmp_path: Path) -> None:
    reference, render = _images_with_changed_table_only(tmp_path)
    result = evaluate_region_quality(
        reference,
        render,
        [
            {"id": "form", "bbox": [0, 0, 100, 100]},
            {"id": "form", "bbox": [0, 100, 100, 100]},
            {"id": "empty", "bbox": [20, 20, 0, 10]},
        ],
    )

    assert result["status"] == "blocked"
    assert {item["id"] for item in result["invalid_regions"]} == {
        "form",
        "empty",
    }
