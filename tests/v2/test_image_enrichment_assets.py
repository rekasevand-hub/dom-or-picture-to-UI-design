from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.structure.image_enrichment.assets import (
    build_asset_crop_request,
    classify_full_screenshot_underlay,
    recover_visible_assets,
)


def _asset(
    name: str,
    kind: str,
    bbox: list[int],
    *,
    occluded: bool = False,
) -> dict:
    return {
        "name": name,
        "kind": kind,
        "bbox": bbox,
        "critical": False,
        "confidence": 0.9,
        "occluded": occluded,
    }


def _graph(path: Path, assets: list[dict]) -> dict:
    return {
        "image": str(path),
        "image_w": 400,
        "image_h": 300,
        "route": "grounding",
        "containers": [],
        "elements": [],
        "imageEnrichment": {"assets": assets},
        "provenance": {"route": "grounding", "fallbacks": [], "warnings": []},
    }


def _fixture(root: Path) -> tuple[Path, dict]:
    path = root / "assets.png"
    image = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 69, 49), fill="#d33b4b")
    draw.rectangle((31, 31, 49, 48), fill="#214f9c")
    for offset in range(70):
        shade = 80 + offset
        draw.rectangle((150, 40 + offset, 249, 40 + offset), fill=(shade,) * 3)
    draw.rectangle((300, 150, 359, 209), fill="#96764f")
    draw.rectangle((300, 150, 359, 179), fill="#f4f4f4")
    image.save(path)
    graph = _graph(
        path,
        [
            _asset("brand_logo", "logo", [20, 20, 70, 50]),
            _asset("grayscale_photo", "photo", [140, 30, 120, 90]),
            _asset("occluded_product", "product-image", [290, 140, 80, 80], occluded=True),
        ],
    )
    return path, graph


def test_recover_visible_assets_preserves_reference_pixels_and_missing_candidate():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        path, graph = _fixture(root)

        recovered, report = recover_visible_assets(
            graph,
            path,
            work_dir=root / "work",
        )
        crop_paths_exist = [
            Path(asset["visibleCrop"]["path"]).is_file()
            for asset in recovered["imageEnrichment"]["assets"]
        ]

    assets = {
        asset["name"]: asset for asset in recovered["imageEnrichment"]["assets"]
    }
    logo = assets["brand_logo"]
    photo = assets["grayscale_photo"]
    product = assets["occluded_product"]

    assert report["status"] == "applied"
    assert report["visible_crop_count"] == 3
    for asset in assets.values():
        assert {
            "visibleCrop",
            "generatedApproximation",
            "assetIdentity",
            "sourceResolution",
        } <= set(asset)
        assert asset["visibleCrop"]["reference_only"] is True
        assert asset["visibleCrop"]["original"] is False
        assert asset["assetIdentity"]["original"] is False
        assert len(asset["visibleCrop"]["payload_sha256"]) == 64
        assert all(crop_paths_exist)

    assert photo["kind"] == "photo"
    assert photo["visibleCrop"]["source_rect"] == [140, 30, 120, 90]
    assert product["generatedApproximation"] == {
        "status": "candidate-missing",
        "candidate": True,
        "generated": False,
        "reason": "visible pixels are occluded and generation has not run",
    }
    assert product["sourceResolution"]["display"]["status"] == "partial-reference"

    image_elements = [
        item for item in recovered["elements"] if item["type"] == "image"
    ]
    assert len(image_elements) == 3
    assert all(item.get("visibleCrop") for item in image_elements)
    assert all(item.get("sourceResolution") for item in image_elements)


def test_build_asset_crop_request_records_source_and_display_identity():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        path, _graph_value = _fixture(root)
        request = build_asset_crop_request(
            _asset("brand_logo", "logo", [20, 20, 70, 50]),
            path,
            [30, 30, 40, 20],
        )
        source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    assert request["source_image"] == str(path)
    assert request["source_sha256"] == source_sha256
    assert request["source_rect"] == [20, 20, 70, 50]
    assert request["display_box"] == [30, 30, 40, 20]
    assert request["mime"] == "image/png"
    assert request["reference_only"] is True
    assert request["original"] is False


def test_ambiguous_crop_keeps_requested_bbox_instead_of_inventing_transparency():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        path = root / "flat.png"
        Image.new("RGB", (200, 160), "#e8e8e8").save(path)
        graph = _graph(path, [_asset("flat_photo", "photo", [40, 30, 100, 70])])
        graph["image_w"] = 200
        graph["image_h"] = 160

        recovered, _report = recover_visible_assets(
            graph,
            path,
            work_dir=root / "work",
        )

    photo = recovered["imageEnrichment"]["assets"][0]
    assert photo["visibleCrop"]["source_rect"] == [40, 30, 100, 70]
    assert photo["visibleCrop"]["refinement"] == "requested-bbox-fallback"


def test_duplicate_asset_uses_one_crop_and_reports_rejection():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        path, graph = _fixture(root)
        graph["imageEnrichment"]["assets"] = [
            _asset("brand_logo", "logo", [20, 20, 70, 50]),
            _asset("brand_logo", "logo", [21, 20, 70, 50]),
        ]

        recovered, report = recover_visible_assets(
            graph,
            path,
            work_dir=root / "work",
        )

    assert len(recovered["imageEnrichment"]["assets"]) == 1
    assert report["deduplicated_count"] == 1
    assert report["deduplicated"][0]["reason"] == "duplicate-asset"


def test_full_screenshot_asset_is_reference_underlay_not_visible_image():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        path, graph = _fixture(root)
        graph["elements"] = [
            {"id": 1, "bbox": [20, 20, 100, 20], "type": "text", "text": "Title"},
            {"id": 2, "bbox": [20, 80, 100, 30], "type": "button", "text": "Submit"},
        ]
        graph["imageEnrichment"]["assets"] = [
            _asset("full_page", "screenshot", [0, 0, 400, 300])
        ]

        recovery, report = recover_visible_assets(
            graph,
            path,
            work_dir=root / "work",
        )

    assert recovery["elements"] == graph["elements"]
    assert report["underlay_count"] == 1
    assert report["underlays"][0]["name"] == "full_page"
    assert recovery["imageEnrichment"]["referenceUnderlays"] == report["underlays"]
    assert not any(item["type"] == "image" for item in recovery["elements"])


def test_underlay_classifier_rejects_crop_containing_multiple_ui_regions():
    graph = {
        "elements": [
            {"bbox": [10, 10, 40, 12], "type": "text", "text": "Title"},
            {"bbox": [10, 40, 60, 24], "type": "button", "text": "Save"},
        ]
    }
    result = classify_full_screenshot_underlay(
        {"name": "panel", "kind": "photo", "bbox": [0, 0, 100, 80]},
        graph,
        width=200,
        height=160,
    )

    assert result["is_underlay"] is True
    assert result["reason"] == "multiple-unrelated-ui-regions"
