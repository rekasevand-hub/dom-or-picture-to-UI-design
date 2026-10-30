from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

VISUAL_QUALITY_SCHEMA_VERSION = "dom-visual-quality/1.0"


def _flatten_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        source = value
    elif isinstance(value, Mapping):
        roots = value.get("nodes") or value.get("children")
        source = roots if isinstance(roots, list) else [value]
    else:
        return []
    rows: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if not isinstance(node, Mapping):
            return
        rows.append(dict(node))
        for child in node.get("children") or []:
            visit(child)

    for node in source:
        visit(node)
    return rows


def _background_color(reference: Any) -> Any:
    import numpy as np

    reference = reference.astype(np.uint8)
    edge = np.concatenate(
        [
            reference[0, :, :3],
            reference[-1, :, :3],
            reference[:, 0, :3],
            reference[:, -1, :3],
        ],
        axis=0,
    )
    counts = Counter(map(tuple, edge.tolist()))
    return np.asarray(counts.most_common(1)[0][0], dtype=np.int16)


def _content_coverage(image: Any, background: Any) -> float:
    import numpy as np

    delta = np.abs(image[..., :3].astype(np.int16) - background.reshape(1, 1, 3))
    content = delta.max(axis=2) >= 10
    return float(content.mean()) if content.size else 0.0


def _expected_image_count(design: Mapping[str, Any]) -> int:
    count = 0
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        if str(element.get("type") or "").lower() in {"image", "avatar"}:
            count += 1
        elif (
            element.get("visualAssetId")
            and str(element.get("source") or "").startswith("dom:background")
            and str(element.get("displayMode") or "") != "source-crop"
        ):
            count += 1
    return count


def _image_fill_count(readback: Mapping[str, Any]) -> int:
    report = readback.get("imageFillReport")
    if isinstance(report, Mapping):
        for key in (
            "fillCount",
            "total",
            "imageFillTotal",
            "image_fill_total",
            "count",
        ):
            value = report.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return max(0, value)
        for key in ("fills", "imageFills", "image_fills"):
            value = report.get(key)
            if isinstance(value, list):
                return len(value)
    count = 0
    for node in _flatten_nodes(readback):
        fills = node.get("fills")
        if not isinstance(fills, list):
            continue
        if any(
            isinstance(fill, Mapping)
            and str(fill.get("type") or "").upper() == "IMAGE"
            for fill in fills
        ):
            count += 1
    return count


def evaluate_dom_visual_quality(
    reference_png: Path,
    rendered_png: Path,
    design: Mapping[str, Any],
    readback: Mapping[str, Any],
) -> dict[str, Any]:
    import cv2
    import numpy as np

    reference = cv2.imread(str(reference_png))
    rendered = cv2.imread(str(rendered_png))
    if reference is None or rendered is None:
        report = {
            "schema_version": VISUAL_QUALITY_SCHEMA_VERSION,
            "status": "fail",
            "reason": "image-unreadable",
            "metrics": {},
            "checks": {
                "blank_area": {"status": "fail", "reason": "image-unreadable"},
                "image_fill": {"status": "fail", "reason": "image-unreadable"},
                "visual_diff": {"status": "fail", "reason": "image-unreadable"},
                "height": {"status": "fail", "reason": "image-unreadable"},
            },
            "warnings": ["image-unreadable"],
        }
        return report

    reference_height, reference_width = reference.shape[:2]
    render_height, render_width = rendered.shape[:2]
    scored = rendered
    if (render_height, render_width) != (reference_height, reference_width):
        scored = cv2.resize(rendered, (reference_width, reference_height))

    background = _background_color(reference)
    source_coverage = _content_coverage(reference, background)
    rendered_coverage = _content_coverage(scored, background)
    blank_ratio = max(0.0, 1.0 - rendered_coverage)
    if source_coverage >= 0.10 and rendered_coverage < source_coverage * 0.25:
        blank_status = "fail"
        blank_reason = "rendered content coverage is below 25% of source"
    else:
        blank_status = "pass"
        blank_reason = None

    expected_images = _expected_image_count(design)
    observed_images = _image_fill_count(readback)
    if expected_images:
        matched_images = min(expected_images, observed_images)
        image_fill_rate = matched_images / expected_images
    else:
        matched_images = 0
        image_fill_rate = 1.0
    if expected_images and image_fill_rate == 0.0:
        image_status = "fail"
        image_reason = "expected image elements have no readback image fills"
    elif image_fill_rate < 0.5:
        image_status = "warn"
        image_reason = "fewer than half of expected images have readback fills"
    else:
        image_status = "pass"
        image_reason = None

    diff = np.abs(scored.astype(np.int16) - reference.astype(np.int16))
    max_diff = diff.max(axis=2)
    bad_pixels = int((max_diff > 30).sum())
    total_pixels = int(max_diff.size)
    bad_pixel_ratio = bad_pixels / total_pixels if total_pixels else 0.0
    mean_delta = float(diff.mean()) if diff.size else 0.0
    if mean_delta <= 8.0 and bad_pixel_ratio <= 0.15:
        visual_status = "pass"
    elif mean_delta <= 20.0 and bad_pixel_ratio <= 0.35:
        visual_status = "warn"
    else:
        visual_status = "fail"

    height_drift = render_height - reference_height
    height_ratio = abs(height_drift) / max(1, reference_height)
    if height_ratio > 0.05:
        height_status = "warn"
    else:
        height_status = "pass"

    checks = {
        "blank_area": {
            "status": blank_status,
            "reason": blank_reason,
            "sourceCoverage": source_coverage,
            "renderCoverage": rendered_coverage,
        },
        "image_fill": {
            "status": image_status,
            "reason": image_reason,
            "expected": expected_images,
            "observed": observed_images,
        },
        "visual_diff": {
            "status": visual_status,
            "meanDelta": mean_delta,
            "badPixelRatio": bad_pixel_ratio,
        },
        "height": {
            "status": height_status,
            "referenceHeight": reference_height,
            "renderHeight": render_height,
        },
        "text_box": {"status": "not-evaluated"},
    }
    warnings = [
        f"{name}: {check.get('reason')}"
        for name, check in checks.items()
        if check["status"] == "warn" and check.get("reason")
    ]
    return {
        "schema_version": VISUAL_QUALITY_SCHEMA_VERSION,
        "status": (
            "fail"
            if any(check["status"] == "fail" for check in checks.values())
            else "warn"
            if any(check["status"] == "warn" for check in checks.values())
            else "pass"
        ),
        "metrics": {
            "image_fill_rate": image_fill_rate,
            "expected_image_count": expected_images,
            "observed_image_count": observed_images,
            "source_content_coverage": source_coverage,
            "render_content_coverage": rendered_coverage,
            "blank_area_ratio": blank_ratio,
            "content_coverage_delta": rendered_coverage - source_coverage,
            "height_drift_px": height_drift,
            "height_drift_ratio": height_ratio,
            "text_box_error": None,
            "bad_pixel_ratio": bad_pixel_ratio,
            "mean_pixel_delta": mean_delta,
        },
        "checks": checks,
        "warnings": warnings,
    }
