from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from src.app.services.structure.image_enrichment.contracts import (
    asset_match_iou,
    validate_image_truth,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_ROOT = (
    REPO_ROOT / "tests" / "fixtures" / "image_to_slice_benchmark_2026-11-02"
)


def _truth() -> dict:
    return {
        "sample_id": "sample",
        "image_sha256": "a" * 64,
        "image_size": [320, 240],
        "critical_texts": ["Submit"],
        "controls": [
            {
                "name": "Submit",
                "type": "button",
                "bbox": [20, 20, 80, 32],
                "value": "Submit",
                "state": "enabled",
                "critical": True,
            }
        ],
        "containers": [
            {
                "name": "Main",
                "role": "main",
                "bbox": [0, 0, 320, 240],
                "critical": True,
            }
        ],
        "tables": [
            {
                "name": "Results",
                "bbox": [0, 80, 320, 140],
                "header_texts": ["Name", "Status"],
                "rows": [["Alpha", "Ready"]],
                "critical": True,
            }
        ],
        "assets": [
            {
                "name": "Logo",
                "kind": "logo",
                "bbox": [4, 4, 32, 32],
                "critical": True,
                "minimum_iou": 0.8,
                "occurrence_count": 1,
            }
        ],
        "backgrounds": [
            {
                "id": "bg",
                "bbox": [0, 0, 320, 240],
                "critical": False,
                "overlays": [
                    {
                        "id": "card",
                        "name": "Card",
                        "kind": "container-overlay",
                        "bbox": [16, 16, 288, 72],
                    }
                ],
                "allowed_substitutions": [],
            }
        ],
        "visual_policy": {"mae_max": 20},
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_truth_rejects_missing_critical_assets_and_clamps_iou():
    truth = {
        "sample_id": "sample",
        "image_sha256": "a" * 64,
        "image_size": [320, 240],
        "critical_texts": ["Submit"],
        "controls": [],
        "containers": [],
        "tables": [],
        "assets": [],
        "backgrounds": [],
        "visual_policy": {"mae_max": 20},
    }
    parsed = validate_image_truth(truth)
    assert parsed["critical_assets"] == []
    assert asset_match_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert asset_match_iou([0, 0, 10, 10], [20, 20, 10, 10]) == 0.0


def test_validator_returns_normalized_copy_with_fixed_canvas_contract():
    source = _truth()
    parsed = validate_image_truth(source)

    assert parsed is not source
    assert parsed["image_sha256"] == "a" * 64
    assert parsed["critical_assets"] == ["Logo"]
    assert parsed["blocking_metrics"] == [
        "critical_text_recall",
        "critical_asset_accuracy",
        "visual_mae",
    ]
    assert parsed["product_contract"] == {
        "mode": "fixed-canvas-1:1",
        "component_reuse": False,
        "responsive_reflow": False,
        "external_provenance_required": False,
        "visible_full_screenshot_underlay": "blocked",
    }
    assert parsed["visual_policy"]["bad_pixel_threshold"] == 30
    assert parsed["visual_policy"]["underlay_visible_ratio_max"] == 0.0
    assert source["assets"][0].get("occurrence_count") == 1
    assert "critical_assets" not in source


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(image_sha256="not-a-hash"), "image_sha256"),
        (lambda value: value.update(image_size=[0, 240]), "image_size"),
        (lambda value: value.update(critical_texts=[""]), "critical_texts"),
        (
            lambda value: value["assets"][0].update(bbox=[1, 2, -3, 4]),
            "bbox",
        ),
        (
            lambda value: value["assets"][0].update(kind="sprite"),
            "asset kind",
        ),
        (
            lambda value: value["assets"][0].update(minimum_iou=1.1),
            "minimum_iou",
        ),
        (
            lambda value: value["assets"][0].update(occurrence_count=0),
            "occurrence_count",
        ),
        (
            lambda value: value["controls"][0].pop("state"),
            "control.state",
        ),
        (
            lambda value: value["controls"][0].update(type="mystery"),
            "control.type",
        ),
        (
            lambda value: value["containers"][0].update(role="mystery"),
            "container.role",
        ),
        (
            lambda value: value["tables"][0].update(rows=[[]]),
            "table.rows",
        ),
        (
            lambda value: value["backgrounds"][0]["overlays"][0].update(
                bbox=[300, 0, 40, 20]
            ),
            "bbox",
        ),
        (
            lambda value: value["visual_policy"].pop("mae_max"),
            "visual_policy.mae_max",
        ),
    ],
)
def test_validator_fails_closed_on_invalid_truth(mutate, message):
    truth = copy.deepcopy(_truth())
    mutate(truth)

    with pytest.raises(ValueError, match=message):
        validate_image_truth(truth)


def test_truth_requires_blocking_content():
    truth = copy.deepcopy(_truth())
    truth["critical_texts"] = []
    truth["assets"] = []
    truth["controls"] = []
    truth["containers"] = []
    truth["tables"] = []

    with pytest.raises(ValueError, match="blocking content"):
        validate_image_truth(truth)


def test_validator_rejects_overlay_outside_its_background():
    truth = copy.deepcopy(_truth())
    truth["backgrounds"][0]["bbox"] = [16, 16, 288, 100]
    truth["backgrounds"][0]["overlays"][0]["bbox"] = [4, 20, 40, 20]

    with pytest.raises(ValueError, match="overlay.*background"):
        validate_image_truth(truth)


def test_asset_match_iou_supports_partial_overlap_and_rejects_bad_boxes():
    assert asset_match_iou([0, 0, 10, 10], [5, 0, 10, 10]) == pytest.approx(
        50 / 150
    )
    assert asset_match_iou([0, 0, 10, 10], [10, 0, 10, 10]) == 0.0

    with pytest.raises(ValueError, match="bbox"):
        asset_match_iou([0, 0, 0, 10], [0, 0, 10, 10])
    with pytest.raises(ValueError, match="bbox"):
        asset_match_iou([0, 0, 10, 10], [0, 0, True, 10])


def test_frozen_truth_files_match_hashes_dimensions_and_manifest():
    manifest = json.loads((BENCHMARK_ROOT / "manifest.json").read_text("utf-8"))
    samples = {sample["id"]: sample for sample in manifest["samples"]}

    assert set(samples) == {
        "IMG-ARTICLE",
        "IMG-ACCTOKEN-API",
        "IMG-FLEXWEAVER-ADMIN",
    }

    for sample_id, sample in samples.items():
        image_path = REPO_ROOT / sample["path"]
        truth_path = BENCHMARK_ROOT / "truth" / f"{sample_id}.truth.json"
        truth = validate_image_truth(json.loads(truth_path.read_text("utf-8")))

        assert truth["sample_id"] == sample_id
        assert truth["image_sha256"] == sample["sha256"] == _sha256(image_path)
        assert truth["image_size"] == [sample["width"], sample["height"]]
        with Image.open(image_path) as image:
            assert list(image.size) == truth["image_size"]
        assert truth["product_contract"]["mode"] == "fixed-canvas-1:1"
        assert truth["product_contract"]["responsive_reflow"] is False
        assert truth["critical_texts"]
        assert truth["critical_assets"]
        assert truth["controls"]
        assert truth["containers"]
        assert truth["visual_policy"]["mae_max"] > 0
        assert truth["backgrounds"] == []

    assert samples["IMG-ARTICLE"]["height"] == 6156
    assert (
        json.loads(
            (BENCHMARK_ROOT / "truth" / "IMG-ARTICLE.truth.json").read_text(
                "utf-8"
            )
        )["image_size"]
        == [2544, 6156]
    )


def test_manifest_records_outstanding_background_capable_input():
    manifest = json.loads((BENCHMARK_ROOT / "manifest.json").read_text("utf-8"))
    requirements = {
        item["id"]: item for item in manifest.get("input_requirements", [])
    }
    photo_overlay = requirements["IMG-PHOTO-OVERLAY"]

    assert photo_overlay["status"] == "required"
    assert photo_overlay["outstanding"] is True
    assert photo_overlay["path"] is None
    assert photo_overlay["evidence_status"] == "not-supplied"
    assert photo_overlay["synthetic_fixture_role"] == "test-only-not-product-evidence"
