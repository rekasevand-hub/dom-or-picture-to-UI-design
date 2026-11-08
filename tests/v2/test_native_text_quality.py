from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.evidence.native_text_quality import (
    build_native_text_quality,
)


def test_native_text_quality_is_diagnostic_and_splits_chrome(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (200, 100), "white")
        ImageDraw.Draw(image).rectangle((20, 20, 60, 28), fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:label",
                "text": "Label",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 40, 8],
                    }
                },
            }
        ]
    }
    readback = {
        "type": "FRAME",
        "children": [
            {
                "type": "TEXT",
                "characters": "Label",
                "bounds": {"x": 20, "y": 20, "width": 40, "height": 8},
            }
        ],
    }

    report = build_native_text_quality(
        design,
        readback,
        str(reference),
        str(rendered),
        [{"id": "page", "role": "page", "bbox": [0, 0, 200, 100]}],
    )

    assert report["acceptance_effect"] == "none"
    assert report["summary"]["nativeTextCount"] == 1
    assert report["owners"][0]["status"] == "pass"
    assert report["owners"][0]["baseline"] == "unknown"
    assert report["chromeRegions"][0]["chromeBadPixelCount"] == 0
    assert report["chromeRegions"][0]["status"] == "pass"


def test_native_text_quality_v2_gates_critical_text_and_chrome(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (200, 100), "white")
        ImageDraw.Draw(image).rectangle((20, 20, 60, 28), fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:label",
                "text": "Label",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [20, 20, 40, 8],
                    }
                },
            }
        ]
    }
    readback = {
        "type": "FRAME",
        "children": [{"type": "TEXT", "characters": "Label"}],
    }

    report = build_native_text_quality(
        design,
        readback,
        str(reference),
        str(rendered),
        [{"id": "page", "role": "page", "bbox": [0, 0, 200, 100]}],
        gate_policy={
            "policy_id": "image-figma-mvp-product/2.0",
            "chrome_bad_pixel_ratio_max": 0.05,
            "native_text_position_px_max": 1,
            "native_text_width_tolerance_ratio": 0.02,
            "native_text_width_tolerance_floor_px": 2,
            "native_text_height_tolerance_ratio": 0.02,
            "native_text_height_tolerance_floor_px": 2,
            "native_text_ink_coverage_min": 0.90,
            "native_text_ink_coverage_max": 1.10,
            "native_text_edge_f1_min": 0.95,
            "native_text_baseline_required": False,
        },
        critical_texts=["Label"],
    )

    assert report["schema_version"] == "grounding-native-text-quality/2.0"
    assert report["acceptance_effect"] == "native-text-and-chrome-gate"
    assert report["gate"]["status"] == "pass"
    assert report["gate"]["nativeText"]["status"] == "pass"
    assert report["gate"]["nativeText"]["ownerPassRatio"] == 1.0
    assert report["gate"]["criticalText"]["matchedCount"] == 1
    assert report["gate"]["chrome"]["status"] == "pass"
    assert report["gate"]["baseline"]["status"] == "not-evaluated"


def test_native_text_quality_v2_blocks_missing_critical_owner(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        Image.new("RGB", (40, 30), "white").save(path)
    report = build_native_text_quality(
        {"elements": []},
        {"type": "FRAME", "children": []},
        str(reference),
        str(rendered),
        [{"id": "page", "role": "page", "bbox": [0, 0, 40, 30]}],
        gate_policy={
            "policy_id": "image-figma-mvp-product/2.0",
            "chrome_bad_pixel_ratio_max": 0.05,
        },
        critical_texts=["Missing"],
    )

    assert report["gate"]["status"] == "fail"
    assert "native-text:missing:Missing" in report["gate"]["blockers"]


def test_native_text_quality_marks_gate_scope_and_diagnostic_only_owners(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (120, 80), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 39, 17), fill="black")
        draw.rectangle((70, 10, 99, 17), fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:critical",
                "text": "Critical",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 50, 30],
                        "ink_bbox": [10, 10, 30, 8],
                    }
                },
            },
            {
                "type": "text",
                "contentRef": "text:diagnostic",
                "text": "Diagnostic",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [60, 0, 50, 30],
                        "ink_bbox": [70, 10, 30, 8],
                    }
                },
            },
        ]
    }
    readback = {
        "type": "FRAME",
        "children": [
            {"type": "TEXT", "characters": "Critical"},
            {"type": "TEXT", "characters": "Diagnostic"},
        ],
    }

    report = build_native_text_quality(
        design,
        readback,
        str(reference),
        str(rendered),
        [{"id": "page", "role": "page", "bbox": [0, 0, 120, 80]}],
        gate_policy={
            "policy_id": "image-figma-mvp-product/2.0",
            "chrome_bad_pixel_ratio_max": 0.05,
        },
        critical_texts=["Critical"],
    )

    owners = {owner["contentRef"]: owner for owner in report["owners"]}
    assert owners["text:critical"]["ownerScope"] == "critical-gate"
    assert owners["text:diagnostic"]["ownerScope"] == "diagnostic-only"
    assert report["gate"]["nativeText"]["ownerRefs"] == ["text:critical"]
    assert report["gate"]["nativeText"]["unscopedOwnerCount"] == 1


def test_native_text_quality_matches_adjacent_logical_cluster(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (200, 100), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 49, 28), fill="black")
        draw.rectangle((52, 20, 71, 28), fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:price",
                "text": "5.8",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [15, 15, 35, 19],
                        "ink_bbox": [20, 20, 30, 9],
                    }
                },
            },
            {
                "type": "text",
                "contentRef": "text:unit",
                "text": "折",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [50, 15, 22, 19],
                        "ink_bbox": [52, 20, 20, 9],
                    }
                },
            },
        ]
    }
    readback = {
        "type": "FRAME",
        "children": [
            {"type": "TEXT", "characters": "5.8"},
            {"type": "TEXT", "characters": "折"},
        ],
    }

    report = build_native_text_quality(
        design,
        readback,
        str(reference),
        str(rendered),
        [{"id": "page", "role": "page", "bbox": [0, 0, 200, 100]}],
        gate_policy={
            "policy_id": "image-figma-mvp-product/2.0",
            "chrome_bad_pixel_ratio_max": 0.05,
        },
        critical_texts=["5.8折"],
    )

    assert report["gate"]["criticalText"]["matchedCount"] == 1
    assert report["gate"]["criticalText"]["missing"] == []
    assert report["gate"]["criticalText"]["logicalClusters"] == [
        {
            "text": "5.8折",
            "ownerRefs": ["text:price", "text:unit"],
        }
    ]
    assert report["gate"]["status"] == "pass"


def test_native_text_quality_rejects_distant_logical_cluster(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (200, 100), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 49, 28), fill="black")
        draw.rectangle((120, 20, 139, 28), fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:price",
                "text": "5.8",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [15, 15, 35, 19],
                        "ink_bbox": [20, 20, 30, 9],
                    }
                },
            },
            {
                "type": "text",
                "contentRef": "text:unit",
                "text": "折",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [115, 15, 30, 19],
                        "ink_bbox": [120, 20, 20, 9],
                    }
                },
            },
        ]
    }
    readback = {
        "type": "FRAME",
        "children": [
            {"type": "TEXT", "characters": "5.8"},
            {"type": "TEXT", "characters": "折"},
        ],
    }

    report = build_native_text_quality(
        design,
        readback,
        str(reference),
        str(rendered),
        [{"id": "page", "role": "page", "bbox": [0, 0, 200, 100]}],
        gate_policy={
            "policy_id": "image-figma-mvp-product/2.0",
            "chrome_bad_pixel_ratio_max": 0.05,
        },
        critical_texts=["5.8折"],
    )

    assert report["gate"]["criticalText"]["matchedCount"] == 0
    assert report["gate"]["criticalText"]["missing"] == ["5.8折"]
    assert report["gate"]["criticalText"]["logicalClusters"] == []


def test_native_text_quality_logical_cluster_requires_native_owners(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (200, 100), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 49, 28), fill="black")
        draw.rectangle((52, 20, 71, 28), fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:price",
                "text": "5.8",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [15, 15, 35, 19],
                        "ink_bbox": [20, 20, 30, 9],
                    }
                },
            },
            {
                "type": "text",
                "contentRef": "text:unit",
                "text": "折",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [50, 15, 22, 19],
                        "ink_bbox": [52, 20, 20, 9],
                    }
                },
            },
        ]
    }
    readback = {
        "type": "FRAME",
        "children": [
            {"type": "TEXT", "characters": "5.8"},
        ],
    }

    report = build_native_text_quality(
        design,
        readback,
        str(reference),
        str(rendered),
        [{"id": "page", "role": "page", "bbox": [0, 0, 200, 100]}],
        gate_policy={
            "policy_id": "image-figma-mvp-product/2.0",
            "chrome_bad_pixel_ratio_max": 0.05,
        },
        critical_texts=["5.8折"],
    )

    assert report["gate"]["criticalText"]["matchedCount"] == 0
    assert report["gate"]["criticalText"]["missing"] == ["5.8折"]
    assert report["gate"]["criticalText"]["logicalClusters"] == []


def test_native_text_quality_support_domain_excludes_nontext_ink(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    reference_image = Image.new("RGB", (120, 60), "white")
    reference_draw = ImageDraw.Draw(reference_image)
    reference_draw.rectangle((0, 0, 119, 1), fill="black")
    reference_draw.rectangle((30, 20, 69, 27), fill="black")
    reference_image.save(reference)
    rendered_image = Image.new("RGB", (120, 60), "white")
    ImageDraw.Draw(rendered_image).rectangle((30, 20, 69, 27), fill="black")
    rendered_image.save(rendered)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:label",
                "text": "Label",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 120, 60],
                        "ink_bbox": [30, 20, 40, 8],
                    }
                },
            }
        ]
    }

    report = build_native_text_quality(
        design,
        {"type": "FRAME", "children": [{"type": "TEXT", "characters": "Label"}]},
        str(reference),
        str(rendered),
        [{"id": "page", "role": "page", "bbox": [0, 0, 120, 60]}],
        gate_policy={
            "policy_id": "image-figma-mvp-product/2.0",
            "chrome_bad_pixel_ratio_max": 0.05,
        },
        critical_texts=["Label"],
    )

    owner = report["owners"][0]
    assert owner["sourceCoverageRatio"] < 0.90
    assert owner["inkCoverageRatio"] == 1.0
    assert owner["metricsBasis"] == "reference-ink-halo"
    assert owner["status"] == "pass"


def test_native_text_quality_support_domain_blocks_over_ink(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    reference_image = Image.new("RGB", (100, 50), "white")
    ImageDraw.Draw(reference_image).rectangle(
        (30, 20, 31, 29),
        fill="black",
    )
    reference_image.save(reference)
    rendered_image = Image.new("RGB", (100, 50), "white")
    rendered_draw = ImageDraw.Draw(rendered_image)
    rendered_draw.rectangle((30, 20, 31, 29), fill="black")
    rendered_draw.rectangle((33, 20, 34, 29), fill="black")
    rendered_image.save(rendered)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:label",
                "text": "Label",
                "styleEvidence": {
                    "evidence": {
                        "source_bbox": [0, 0, 100, 50],
                        "ink_bbox": [30, 20, 2, 10],
                    }
                },
            }
        ]
    }

    report = build_native_text_quality(
        design,
        {"type": "FRAME", "children": [{"type": "TEXT", "characters": "Label"}]},
        str(reference),
        str(rendered),
        [{"id": "page", "role": "page", "bbox": [0, 0, 100, 50]}],
        gate_policy={
            "policy_id": "image-figma-mvp-product/2.0",
            "chrome_bad_pixel_ratio_max": 0.05,
        },
        critical_texts=["Label"],
    )

    owner = report["owners"][0]
    assert owner["inkCoverageRatio"] > 1.10
    assert owner["checks"]["coverage"] is False
    assert owner["status"] == "fail"
