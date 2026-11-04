from __future__ import annotations

import base64
import io
import json
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.evidence.image_enrichment_quality import (
    evaluate_image_enrichment,
    write_image_enrichment_report,
)


def _png() -> str:
    output = io.BytesIO()
    Image.new("RGB", (40, 40), "#2f6fed").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _reference(path: Path) -> None:
    image = Image.new("RGB", (320, 200), "#ffffff")
    draw = ImageDraw.Draw(image)
    draw.text((10, 10), "Title", fill="#111111")
    draw.rectangle((10, 40, 89, 69), fill="#2f6fed")
    draw.text((20, 48), "Save", fill="#ffffff")
    draw.rectangle((10, 70, 309, 169), outline="#333333")
    draw.text((20, 80), "Name", fill="#111111")
    draw.text((120, 80), "Status", fill="#111111")
    draw.text((20, 110), "Alpha", fill="#333333")
    draw.text((120, 110), "Ready", fill="#333333")
    draw.rectangle((250, 10, 289, 49), fill="#2f6fed")
    image.save(path)


def _truth(path: Path) -> dict:
    return {
        "sample_id": "sample",
        "image_sha256": "a" * 64,
        "image_size": [320, 200],
        "reference_image_path": str(path),
        "critical_texts": [
            "Title",
            "Save",
            "Name",
            "Status",
            "Alpha",
            "Ready",
        ],
        "controls": [
            {
                "name": "Save",
                "type": "button",
                "bbox": [10, 40, 80, 30],
                "value": "Save",
                "state": "enabled",
                "critical": True,
            }
        ],
        "containers": [
            {
                "name": "Page",
                "role": "page",
                "bbox": [0, 0, 320, 200],
                "critical": True,
            },
            {
                "name": "Table",
                "role": "table",
                "bbox": [10, 70, 300, 100],
                "critical": True,
            },
        ],
        "tables": [
            {
                "name": "Results",
                "bbox": [10, 70, 300, 100],
                "header_texts": ["Name", "Status"],
                "rows": [["Alpha", "Ready"]],
                "critical": True,
            }
        ],
        "assets": [
            {
                "name": "Logo",
                "kind": "logo",
                "bbox": [250, 10, 40, 40],
                "critical": True,
                "minimum_iou": 0.8,
                "occurrence_count": 1,
            }
        ],
        "backgrounds": [],
        "visual_policy": {
            "mae_max": 20.0,
            "bad_pixel_threshold": 30,
            "bad_pixel_ratio_max": 0.15,
            "underlay_visible_ratio_max": 0.0,
            "content_coverage_min": 0.02,
        },
    }


def _design() -> dict:
    return {
        "name": "Quality",
        "canvas": {"width": 320, "height": 200, "background": "#ffffff"},
        "elements": [
            {
                "id": "page",
                "type": "container",
                "x": 0,
                "y": 0,
                "width": 320,
                "height": 200,
                "imageMVP": {"role": "page"},
            },
            {
                "id": "title",
                "type": "text",
                "text": "Title",
                "x": 10,
                "y": 10,
                "width": 80,
                "height": 20,
            },
            {
                "id": "save",
                "type": "button",
                "text": "Save",
                "controlType": "button",
                "controlValue": "Save",
                "controlState": "enabled",
                "x": 10,
                "y": 40,
                "width": 80,
                "height": 30,
            },
            {
                "id": "table",
                "type": "container",
                "x": 10,
                "y": 70,
                "width": 300,
                "height": 100,
                "imageMVP": {"role": "table"},
            },
            {
                "id": "h1",
                "type": "text",
                "text": "Name",
                "x": 20,
                "y": 80,
                "width": 70,
                "height": 20,
            },
            {
                "id": "h2",
                "type": "text",
                "text": "Status",
                "x": 120,
                "y": 80,
                "width": 70,
                "height": 20,
            },
            {
                "id": "r1",
                "type": "text",
                "text": "Alpha",
                "x": 20,
                "y": 110,
                "width": 70,
                "height": 20,
            },
            {
                "id": "r2",
                "type": "text",
                "text": "Ready",
                "x": 120,
                "y": 110,
                "width": 70,
                "height": 20,
            },
            {
                "id": "logo",
                "type": "image",
                "x": 250,
                "y": 10,
                "width": 40,
                "height": 40,
                "imageBase64": _png(),
                "assetName": "Logo",
                "assetKind": "logo",
                "imageMVP": {"generated": False},
                "sourceResolution": {
                    "identity": {"selected": "unavailable", "original": False},
                    "display": {"selected": "screenshot-crop", "generated": False},
                },
            },
        ],
        "_meta": {"imageMVP": {"referenceUnderlays": []}},
    }


def _readback() -> dict:
    return {
        "nativeRenderReport": {
            "expected": {"native_text": 6, "image_fills": 1},
            "actual": {"native_text": 6, "image_fills": 1},
        }
    }


def test_complete_fixture_clears_all_blocking_gates():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        reference = root / "reference.png"
        render = root / "render.png"
        _reference(reference)
        Image.open(reference).save(render)

        result = evaluate_image_enrichment(
            _truth(reference),
            _design(),
            _readback(),
            render,
        )

    assert result["status"] == "pass"
    assert result["blockers"] == []
    assert result["metrics"]["critical_text_recall"] == 1.0
    assert result["metrics"]["critical_asset_recall"] == 1.0
    assert result["metrics"]["table_header_recall"] == 1.0
    assert result["metrics"]["grayscale_mae"] == 0.0
    assert result["metrics"]["visible_underlay_ratio"] == 0.0


def test_blank_output_fails_even_with_low_visual_error():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        reference = root / "reference.png"
        render = root / "render.png"
        _reference(reference)
        Image.new("RGB", (320, 200), "#ffffff").save(render)
        blank_design = {
            "canvas": {"width": 320, "height": 200, "background": "#ffffff"},
            "elements": [],
            "_meta": {"imageMVP": {"referenceUnderlays": []}},
        }

        result = evaluate_image_enrichment(
            _truth(reference),
            blank_design,
            {},
            render,
        )

    assert result["status"] == "blocked-fail"
    assert "critical-text" in result["blockers"]
    assert "content-coverage" in result["blockers"]
    assert result["metrics"]["grayscale_mae"] < 20.0
    assert result["metrics"]["content_coverage"] < 0.02


def test_generated_asset_marked_original_is_a_blocker():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        reference = root / "reference.png"
        render = root / "render.png"
        _reference(reference)
        Image.open(reference).save(render)
        design = _design()
        logo = next(item for item in design["elements"] if item["id"] == "logo")
        logo["imageMVP"]["generated"] = True
        logo["sourceResolution"]["identity"]["original"] = True

        result = evaluate_image_enrichment(
            _truth(reference),
            design,
            _readback(),
            render,
        )

    assert result["status"] == "blocked-fail"
    assert "generated-asset-falsely-original" in result["blockers"]


def test_visible_full_screenshot_underlay_is_a_blocker():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        reference = root / "reference.png"
        render = root / "render.png"
        _reference(reference)
        Image.open(reference).save(render)
        design = _design()
        design["elements"].insert(
            0,
            {
                "id": "underlay",
                "type": "image",
                "x": 0,
                "y": 0,
                "width": 320,
                "height": 200,
                "imageBase64": _png(),
            },
        )
        readback = _readback()
        readback["nativeRenderReport"]["expected"]["image_fills"] = 2
        readback["nativeRenderReport"]["actual"]["image_fills"] = 2

        result = evaluate_image_enrichment(
            _truth(reference),
            design,
            readback,
            render,
        )

    assert result["status"] == "blocked-fail"
    assert "full-screenshot-underlay" in result["blockers"]
    assert result["metrics"]["visible_underlay_ratio"] > 0


def test_native_readback_count_mismatch_is_a_blocker():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        reference = root / "reference.png"
        render = root / "render.png"
        _reference(reference)
        Image.open(reference).save(render)
        readback = _readback()
        readback["nativeRenderReport"]["actual"]["native_text"] = 0
        readback["nativeRenderReport"]["actual"]["image_fills"] = 0

        result = evaluate_image_enrichment(
            _truth(reference),
            _design(),
            readback,
            render,
        )

    assert "native-readback" in result["blockers"]


def test_equal_control_candidates_do_not_compare_dicts():
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        reference = root / "reference.png"
        render = root / "render.png"
        _reference(reference)
        Image.open(reference).save(render)
        design = _design()
        save = next(item for item in design["elements"] if item["id"] == "save")
        duplicate = json.loads(json.dumps(save))
        duplicate["id"] = "save-duplicate"
        design["elements"].append(duplicate)
        readback = _readback()
        readback["nativeRenderReport"]["expected"]["native_text"] = 7
        readback["nativeRenderReport"]["actual"]["native_text"] = 7

        result = evaluate_image_enrichment(
            _truth(reference),
            design,
            readback,
            render,
        )

    assert result["details"]["controls"]["status"] == "pass"


def test_report_writer_preserves_failures_and_writes_json_markdown():
    runs = [
        {
            "sample_id": "sample",
            "mode": "off",
            "status": "blocked-fail",
            "blockers": ["critical-text"],
        },
        {"sample_id": "sample", "mode": "apply", "status": "pass", "blockers": []},
    ]
    with tempfile.TemporaryDirectory() as raw_dir:
        output = Path(raw_dir)
        report = write_image_enrichment_report(runs, output)
        saved = json.loads((output / "report.json").read_text("utf-8"))
        markdown = (output / "report.md").read_text("utf-8")

    assert report["status"] == "mixed"
    assert saved["status"] == "mixed"
    assert saved["runs"][0]["status"] == "blocked-fail"
    assert "| sample | off |" in markdown
    assert "critical-text" in markdown
