"""Blocking acceptance metrics for Grounding image enrichment."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.app.services.rendering.adapter_base import paint_order
from src.app.services.structure.image_contract import audit_native_reconstruction

SCHEMA_VERSION = "grounding-image-enrichment-quality/1.0"
REPORT_SCHEMA_VERSION = "grounding-image-enrichment-acceptance/1.0"
CONTROL_TYPES = {
    "button",
    "checkbox",
    "icon-button",
    "input",
    "link",
    "navigation",
    "pagination",
    "radio",
    "select",
    "textarea",
    "toggle",
}


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)


def _display_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _table_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _bbox(value: Any) -> list[int] | None:
    try:
        x, y, width, height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return [x, y, width, height]


def _element_bbox(element: Mapping[str, Any]) -> list[int] | None:
    if element.get("bbox") is not None:
        return _bbox(element.get("bbox"))
    return _bbox(
        [
            element.get("x"),
            element.get("y"),
            element.get("width"),
            element.get("height"),
        ]
    )


def _intersection(first: list[int], second: list[int]) -> int:
    width = max(
        0,
        min(first[0] + first[2], second[0] + second[2]) - max(first[0], second[0]),
    )
    height = max(
        0,
        min(first[1] + first[3], second[1] + second[3]) - max(first[1], second[1]),
    )
    return width * height


def _iou(first: list[int] | None, second: list[int] | None) -> float:
    if first is None or second is None:
        return 0.0
    intersection = _intersection(first, second)
    union = first[2] * first[3] + second[2] * second[3] - intersection
    return intersection / union if union > 0 else 0.0


def _contains(outer: list[int], inner: list[int]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[0] + inner[2] <= outer[0] + outer[2]
        and inner[1] + inner[3] <= outer[1] + outer[3]
    )


def _design_elements(design: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item) for item in design.get("elements") or [] if isinstance(item, Mapping)
    ]


def _text_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in elements
        if str(item.get("type") or "").lower()
        in {"text", "button", "input", "select", "textarea"}
        and _display_text(item.get("text") or item.get("controlValue"))
    ]


def _critical_text_metrics(
    truth: Mapping[str, Any],
    design: Mapping[str, Any],
) -> dict[str, Any]:
    expected = [_display_text(item) for item in truth.get("critical_texts") or []]
    actual = [
        _normalize(item.get("text") or item.get("controlValue"))
        for item in _text_elements(_design_elements(design))
    ]
    rows = []
    for text in expected:
        normalized = _normalize(text)
        rows.append(
            {
                "text": text,
                "present": any(normalized in candidate for candidate in actual),
            }
        )
    matched = sum(row["present"] for row in rows)
    return {
        "status": "pass" if matched == len(rows) else "fail",
        "required_count": len(rows),
        "matched_count": matched,
        "recall": matched / len(rows) if rows else 1.0,
        "rows": rows,
    }


def _control_type(element: Mapping[str, Any]) -> str:
    image_meta = element.get("imageMVP")
    return str(
        element.get("controlType")
        or element.get("kind")
        or (
            image_meta.get("candidate_type")
            if isinstance(image_meta, Mapping)
            else None
        )
        or element.get("type")
        or ""
    ).lower()


def _control_value(element: Mapping[str, Any]) -> str:
    return _display_text(
        element.get("controlValue")
        if element.get("controlValue") is not None
        else element.get("value")
        if element.get("value") is not None
        else element.get("text")
    )


def _control_state(element: Mapping[str, Any]) -> str:
    image_meta = element.get("imageMVP")
    return str(
        element.get("controlState")
        or element.get("state")
        or (image_meta.get("state") if isinstance(image_meta, Mapping) else "")
        or ""
    ).lower()


def _control_metrics(
    truth: Mapping[str, Any],
    design: Mapping[str, Any],
) -> dict[str, Any]:
    expected = [
        item
        for item in truth.get("controls") or []
        if isinstance(item, Mapping) and item.get("critical")
    ]
    candidates = [
        item
        for item in _design_elements(design)
        if _control_type(item) in CONTROL_TYPES
        or any(
            item.get(key) is not None
            for key in ("controlType", "controlValue", "controlState")
        )
    ]
    rows = []
    for control in expected:
        target_bbox = _bbox(control.get("bbox"))
        target_type = str(control.get("type") or "").lower()
        target_value = _normalize(control.get("value"))
        target_state = str(control.get("state") or "").lower()
        ranked = []
        for candidate in candidates:
            candidate_bbox = _element_bbox(candidate)
            iou = _iou(target_bbox, candidate_bbox)
            same_type = _control_type(candidate) == target_type
            same_value = _normalize(_control_value(candidate)) == target_value
            ranked.append(
                (
                    2 * int(same_type) + int(same_value) + iou,
                    iou,
                    same_type,
                    same_value,
                    candidate,
                )
            )
        best = max(
            ranked,
            key=lambda item: (item[0], item[1]),
            default=None,
        )
        matched = bool(best and (best[1] >= 0.4 or (best[2] and best[3])))
        candidate = best[-1] if best else {}
        value_ok = matched and _normalize(_control_value(candidate)) == target_value
        state_ok = matched and _control_state(candidate) == target_state
        rows.append(
            {
                "name": str(control.get("name") or ""),
                "matched": matched,
                "value_ok": value_ok,
                "state_ok": state_ok,
                "bbox_iou": round(best[1], 6) if best else 0.0,
            }
        )
    matched_count = sum(row["matched"] for row in rows)
    return {
        "status": (
            "pass"
            if all(
                row["matched"] and row["value_ok"] and row["state_ok"] for row in rows
            )
            else "fail"
        ),
        "required_count": len(rows),
        "matched_count": matched_count,
        "recall": matched_count / len(rows) if rows else 1.0,
        "value_accuracy": (
            sum(row["value_ok"] for row in rows) / len(rows) if rows else 1.0
        ),
        "state_accuracy": (
            sum(row["state_ok"] for row in rows) / len(rows) if rows else 1.0
        ),
        "bbox_iou": (
            sum(row["bbox_iou"] for row in rows if row["matched"]) / matched_count
            if matched_count
            else 1.0
        ),
        "rows": rows,
    }


def _container_metrics(
    truth: Mapping[str, Any],
    design: Mapping[str, Any],
) -> dict[str, Any]:
    expected = [
        item
        for item in truth.get("containers") or []
        if isinstance(item, Mapping) and item.get("critical")
    ]
    candidates = [
        item
        for item in _design_elements(design)
        if str(item.get("type") or "").lower() == "container"
    ]
    rows = []
    for container in expected:
        target_bbox = _bbox(container.get("bbox"))
        target_role = str(container.get("role") or "").lower()
        best = None
        for candidate in candidates:
            image_meta = candidate.get("imageMVP")
            role = str(
                candidate.get("role")
                or (image_meta.get("role") if isinstance(image_meta, Mapping) else "")
            ).lower()
            iou = _iou(target_bbox, _element_bbox(candidate))
            score = (2 * int(role == target_role) + iou, iou)
            if best is None or score > best[0]:
                best = (score, candidate)
        iou = best[0][1] if best else 0.0
        matched = bool(best and iou >= 0.5)
        rows.append(
            {
                "name": str(container.get("name") or ""),
                "matched": matched,
                "bbox_iou": round(iou, 6),
            }
        )
    matched_count = sum(row["matched"] for row in rows)
    return {
        "status": "pass" if matched_count == len(rows) else "fail",
        "required_count": len(rows),
        "matched_count": matched_count,
        "recall": matched_count / len(rows) if rows else 1.0,
        "bbox_iou": (
            sum(row["bbox_iou"] for row in rows if row["matched"]) / matched_count
            if matched_count
            else 1.0
        ),
        "rows": rows,
    }


def _table_metrics(
    truth: Mapping[str, Any],
    design: Mapping[str, Any],
) -> dict[str, Any]:
    tables = [
        item
        for item in truth.get("tables") or []
        if isinstance(item, Mapping) and item.get("critical")
    ]
    texts = _text_elements(_design_elements(design))
    rows = []
    for table in tables:
        table_bbox = _bbox(table.get("bbox"))
        headers = [_display_text(item) for item in table.get("header_texts") or []]
        inside = [
            item
            for item in texts
            if table_bbox is not None
            and _element_bbox(item) is not None
            and (
                _intersection(table_bbox, _element_bbox(item) or [0, 0, 0, 0])
                / max(
                    1,
                    (_element_bbox(item) or [0, 0, 0, 0])[2]
                    * (_element_bbox(item) or [0, 0, 0, 0])[3],
                )
                >= 0.5
            )
        ]
        normalized_inside = {_table_text(item.get("text")) for item in inside}
        header_matches = sum(
            _table_text(header) in normalized_inside for header in headers
        )
        header_elements = [
            item
            for item in inside
            if _table_text(item.get("text"))
            in {_table_text(header) for header in headers}
        ]
        if header_elements:
            header_boxes = [
                _element_bbox(item) or [0, 0, 0, 0] for item in header_elements
            ]
            header_top = min(box[1] for box in header_boxes)
            heights = sorted(box[3] for box in header_boxes if box[3] > 0)
            header_height = heights[len(heights) // 2] if heights else 0
            header_bottom = header_top + header_height
        else:
            header_bottom = table_bbox[1] if table_bbox else 0
        body = [
            item
            for item in inside
            if item not in header_elements
            and (_element_bbox(item) or [0, 0, 0, 0])[1] >= header_bottom
        ]
        bands: list[float] = []
        for item in sorted(
            body,
            key=lambda candidate: (_element_bbox(candidate) or [0, 0, 0, 0])[1],
        ):
            box = _element_bbox(item) or [0, 0, 0, 0]
            center = box[1] + box[3] / 2
            if not bands or abs(center - bands[-1]) > max(4, box[3] * 0.5):
                bands.append(center)
        expected_rows = len(table.get("rows") or [])
        visible_normalized = {
            _normalize(item.get("text"))
            for item in inside
            if _normalize(item.get("text"))
        }
        matched_rows = 0
        for expected_row in table.get("rows") or []:
            tokens = [
                _normalize(cell) for cell in expected_row or [] if _normalize(cell)
            ]
            required = min(2, len(tokens))
            matched = sum(
                any(token in visible for visible in visible_normalized)
                for token in tokens
            )
            if required and matched >= required:
                matched_rows += 1
        row_recall = matched_rows / expected_rows if expected_rows else 1.0
        rows.append(
            {
                "name": str(table.get("name") or ""),
                "header_recall": header_matches / len(headers) if headers else 1.0,
                "expected_rows": expected_rows,
                "observed_rows": matched_rows,
                "row_recall": row_recall,
            }
        )
    return {
        "status": (
            "pass"
            if all(
                row["header_recall"] == 1.0 and row["row_recall"] == 1.0 for row in rows
            )
            else "fail"
        ),
        "header_recall": (
            sum(row["header_recall"] for row in rows) / len(rows) if rows else 1.0
        ),
        "row_recall": (
            sum(row["row_recall"] for row in rows) / len(rows) if rows else 1.0
        ),
        "rows": rows,
    }


def _asset_kind(element: Mapping[str, Any]) -> str:
    image_meta = element.get("imageMVP")
    return str(
        element.get("assetKind")
        or element.get("kind")
        or (image_meta.get("assetKind") if isinstance(image_meta, Mapping) else "")
        or "image"
    ).lower()


def _generated_flags(element: Mapping[str, Any]) -> tuple[bool, bool]:
    image_meta = element.get("imageMVP")
    generated_meta = element.get("generatedApproximation")
    resolution = element.get("sourceResolution")
    display = (
        resolution.get("display") if isinstance(resolution, Mapping) else {}
    ) or {}
    identity = (
        resolution.get("identity") if isinstance(resolution, Mapping) else {}
    ) or {}
    generated = bool(
        (image_meta.get("generated") if isinstance(image_meta, Mapping) else False)
        or (
            generated_meta.get("generated")
            if isinstance(generated_meta, Mapping)
            else False
        )
        or (display.get("generated") if isinstance(display, Mapping) else False)
    )
    original = bool(
        (identity.get("original") if isinstance(identity, Mapping) else False)
        or (
            (element.get("assetIdentity") or {}).get("original")
            if isinstance(element.get("assetIdentity"), Mapping)
            else False
        )
        or (
            (element.get("displayPayload") or {}).get("original")
            if isinstance(element.get("displayPayload"), Mapping)
            else False
        )
        or (
            image_meta.get("originalAssetClaimed")
            if isinstance(image_meta, Mapping)
            else False
        )
    )
    return generated, original


def _asset_metrics(
    truth: Mapping[str, Any],
    design: Mapping[str, Any],
) -> dict[str, Any]:
    expected = [
        item
        for item in truth.get("assets") or []
        if isinstance(item, Mapping) and item.get("critical")
    ]
    candidates = [
        item
        for item in _design_elements(design)
        if str(item.get("type") or "").lower() in {"image", "avatar"}
        and item.get("imageBase64")
    ]
    rows = []
    for asset in expected:
        target_bbox = _bbox(asset.get("bbox"))
        target_kind = str(asset.get("kind") or "").lower()
        minimum_iou = float(asset.get("minimum_iou") or 0.0)
        best_iou = 0.0
        matched = False
        for candidate in candidates:
            identity = candidate.get("assetIdentity")
            identity_bbox = (
                _bbox(identity.get("bbox")) if isinstance(identity, Mapping) else None
            )
            iou = _iou(
                target_bbox,
                identity_bbox or _element_bbox(candidate),
            )
            kind_ok = not target_kind or _asset_kind(candidate) == target_kind
            if kind_ok and iou >= minimum_iou:
                best_iou = max(best_iou, iou)
                matched = True
        rows.append(
            {
                "name": str(asset.get("name") or ""),
                "matched": matched,
                "bbox_iou": round(best_iou, 6),
            }
        )
    generated_count = 0
    observed_count = 0
    false_original = []
    for element in candidates:
        generated, original = _generated_flags(element)
        if generated:
            generated_count += 1
            if original:
                false_original.append(
                    {
                        "id": element.get("id"),
                        "asset": element.get("assetName") or element.get("name"),
                    }
                )
        else:
            observed_count += 1
    matched_count = sum(row["matched"] for row in rows)
    return {
        "status": "pass" if matched_count == len(rows) else "fail",
        "required_count": len(rows),
        "matched_count": matched_count,
        "recall": matched_count / len(rows) if rows else 1.0,
        "bbox_iou": (
            sum(row["bbox_iou"] for row in rows if row["matched"]) / matched_count
            if matched_count
            else 1.0
        ),
        "generated_count": generated_count,
        "observed_count": observed_count,
        "generated_falsely_original": false_original,
        "rows": rows,
    }


def _flatten_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        roots = value.get("nodes") or value.get("children") or [value]
    elif isinstance(value, list):
        roots = value
    else:
        return []
    rows: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if not isinstance(node, Mapping):
            return
        rows.append(dict(node))
        for child in node.get("children") or []:
            visit(child)

    for root in roots:
        visit(root)
    return rows


def _readback_native_counts(
    design: Mapping[str, Any],
    readback: Mapping[str, Any],
) -> dict[str, Any]:
    elements = _design_elements(design)
    expected_text = sum(
        bool(
            _display_text(
                element.get("text")
                if str(element.get("type") or "") == "input"
                else element.get("text") or element.get("controlValue")
            )
        )
        and not element.get("imageBase64")
        for element in elements
    )
    expected_images = sum(bool(element.get("imageBase64")) for element in elements)
    report = readback.get("nativeRenderReport")
    if isinstance(report, Mapping):
        actual = report.get("actual")
        if isinstance(actual, Mapping):
            actual_text = int(actual.get("native_text") or 0)
            actual_images = int(actual.get("image_fills") or 0)
        else:
            actual_text = int(report.get("native_text") or 0)
            actual_images = int(report.get("image_fills") or 0)
    elif "native_text_count" in readback or "image_fill_count" in readback:
        actual_text = int(readback.get("native_text_count") or 0)
        actual_images = int(readback.get("image_fill_count") or 0)
    else:
        nodes = _flatten_nodes(readback)
        actual_text = sum(
            str(node.get("type") or "").upper() == "TEXT" for node in nodes
        )
        actual_images = 0
        for node in nodes:
            fills = node.get("fills")
            if isinstance(fills, list) and any(
                isinstance(fill, Mapping)
                and str(fill.get("type") or "").upper() == "IMAGE"
                for fill in fills
            ):
                actual_images += 1
    return {
        "status": (
            "pass"
            if actual_text == expected_text and actual_images == expected_images
            else "fail"
        ),
        "expected_native_text": expected_text,
        "actual_native_text": actual_text,
        "expected_image_fills": expected_images,
        "actual_image_fills": actual_images,
    }


def _visible_underlay_ratio(
    design: Mapping[str, Any],
    readback: Mapping[str, Any],
) -> float:
    for key in ("visible_underlay_ratio", "underlay_visible_ratio"):
        if isinstance(readback.get(key), (int, float)):
            return max(0.0, float(readback[key]))
    audit = audit_native_reconstruction(design)
    if audit["status"] == "pass":
        return 0.0
    canvas = design.get("canvas") or {}
    width = int(canvas.get("width") or 0)
    height = int(canvas.get("height") or 0)
    if width <= 0 or height <= 0:
        return 1.0
    elements = _design_elements(design)
    ordered = paint_order(elements)
    underlay_ids = {item.get("id") for item in audit.get("underlays") or []}
    masks_by_id: dict[str, Any] = {}
    import numpy as np

    def paints_pixels(element: Mapping[str, Any]) -> bool:
        if element.get("imageBase64"):
            return True
        style = element.get("style")
        fill = (
            style.get("fillColor")
            if isinstance(style, Mapping)
            else element.get("fillColor")
        )
        if fill and str(fill).lower() not in {"transparent", "none"}:
            return True
        element_type = str(element.get("type") or "").lower()
        return element_type in {
            "avatar",
            "button",
            "circle",
            "image",
            "input",
            "rectangle",
            "text",
        } and bool(
            _display_text(element.get("text") or element.get("controlValue"))
            or element_type in {"avatar", "circle", "image", "rectangle"}
        )

    for position, (_index, element) in enumerate(ordered):
        element_id = str(element.get("id") or "")
        if element_id not in underlay_ids:
            continue
        mask = np.zeros((height, width), dtype=bool)
        box = _element_bbox(element)
        if box is None:
            continue
        left = max(0, box[0])
        top = max(0, box[1])
        right = min(width, box[0] + box[2])
        bottom = min(height, box[1] + box[3])
        mask[top:bottom, left:right] = True
        for _later_index, later in ordered[position + 1 :]:
            if not paints_pixels(later):
                continue
            later_box = _element_bbox(later)
            if later_box is None:
                continue
            left = max(0, later_box[0])
            top = max(0, later_box[1])
            right = min(width, later_box[0] + later_box[2])
            bottom = min(height, later_box[1] + later_box[3])
            mask[top:bottom, left:right] = False
        masks_by_id[element_id] = mask
    if not masks_by_id:
        return 0.0
    combined = np.zeros((height, width), dtype=bool)
    for mask in masks_by_id.values():
        combined |= mask
    return float(combined.sum()) / float(width * height)


def _background_color(reference: Any) -> Any:
    import numpy as np

    edge = np.concatenate(
        [
            reference[0, :, :],
            reference[-1, :, :],
            reference[:, 0, :],
            reference[:, -1, :],
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


def _visual_metrics(
    truth: Mapping[str, Any],
    design: Mapping[str, Any],
    rendered_png: Path,
) -> dict[str, Any]:
    import cv2
    import numpy as np

    reference_value = (
        truth.get("reference_image_path")
        or truth.get("source_image")
        or design.get("image")
        or ((design.get("_meta") or {}).get("imagePath"))
    )
    if not reference_value:
        return {
            "status": "not-evaluated",
            "reason": "reference-image-missing",
            "grayscale_mae": None,
            "bad_pixel_ratio": 1.0,
            "content_coverage": 0.0,
            "source_content_coverage": 0.0,
            "size_match": False,
        }
    reference = cv2.imread(str(reference_value))
    rendered = cv2.imread(str(rendered_png))
    if reference is None or rendered is None:
        return {
            "status": "not-evaluated",
            "reason": "image-unreadable",
            "grayscale_mae": None,
            "bad_pixel_ratio": 1.0,
            "content_coverage": 0.0,
            "source_content_coverage": 0.0,
            "size_match": False,
        }
    reference_size = (reference.shape[1], reference.shape[0])
    rendered_size = (rendered.shape[1], rendered.shape[0])
    scored = rendered
    if rendered_size != reference_size:
        scored = cv2.resize(rendered, reference_size)
    gray_reference = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    gray_rendered = cv2.cvtColor(scored, cv2.COLOR_BGR2GRAY)
    grayscale_mae = float(
        np.abs(gray_rendered.astype(np.int16) - gray_reference.astype(np.int16)).mean()
    )
    max_diff = np.abs(scored.astype(np.int16) - reference.astype(np.int16)).max(axis=2)
    threshold = int((truth.get("visual_policy") or {}).get("bad_pixel_threshold") or 30)
    bad_ratio = float((max_diff > threshold).mean())
    background = _background_color(reference)
    source_coverage = _content_coverage(reference, background)
    content_coverage = _content_coverage(scored, background)
    return {
        "status": "measured",
        "reference": str(reference_value),
        "render": str(rendered_png),
        "reference_size": list(reference_size),
        "render_size": list(rendered_size),
        "size_match": rendered_size == reference_size,
        "grayscale_mae": grayscale_mae,
        "bad_pixel_threshold": threshold,
        "bad_pixel_ratio": bad_ratio,
        "content_coverage": content_coverage,
        "source_content_coverage": source_coverage,
    }


def evaluate_image_enrichment(
    truth: dict,
    design: dict,
    readback: dict,
    rendered_png: Path,
) -> dict[str, Any]:
    """Evaluate one enriched reconstruction against all blocking metrics."""

    if not isinstance(truth, Mapping):
        raise ValueError("truth must be an object")
    if not isinstance(design, Mapping):
        raise ValueError("design must be an object")
    if not isinstance(readback, Mapping):
        readback = {}
    output = Path(rendered_png)
    policy = dict(truth.get("visual_policy") or {})
    text = _critical_text_metrics(truth, design)
    controls = _control_metrics(truth, design)
    containers = _container_metrics(truth, design)
    tables = _table_metrics(truth, design)
    assets = _asset_metrics(truth, design)
    native = _readback_native_counts(design, readback)
    underlay_ratio = _visible_underlay_ratio(design, readback)
    visual = _visual_metrics(truth, design, output)
    blockers: list[str] = []
    if text["status"] != "pass":
        blockers.append("critical-text")
    if controls["status"] != "pass":
        if controls["recall"] < 1.0:
            blockers.append("critical-control")
        if controls["value_accuracy"] < 1.0:
            blockers.append("control-value")
        if controls["state_accuracy"] < 1.0:
            blockers.append("control-state")
        if any(row["matched"] and row["bbox_iou"] < 0.5 for row in controls["rows"]):
            blockers.append("control-bbox")
    if containers["status"] != "pass":
        blockers.append("container-structure")
    if tables["status"] != "pass":
        blockers.append("table-structure")
    if assets["status"] != "pass":
        blockers.append("critical-asset")
    if assets["generated_falsely_original"]:
        blockers.append("generated-asset-falsely-original")
    if native["status"] != "pass":
        blockers.append("native-readback")
    if underlay_ratio > float(policy.get("underlay_visible_ratio_max") or 0.0):
        blockers.append("full-screenshot-underlay")
    if visual["status"] != "measured":
        blockers.append("visual-unreadable")
    else:
        content_min = float(policy.get("content_coverage_min") or 0.02)
        source_floor = (
            visual["source_content_coverage"] * 0.25
            if visual["source_content_coverage"] >= 0.10
            else 0.0
        )
        if visual["content_coverage"] < max(content_min, source_floor):
            blockers.append("content-coverage")
        if visual["grayscale_mae"] > float(policy.get("mae_max") or float("inf")):
            blockers.append("visual-mae")
        if visual["bad_pixel_ratio"] > float(policy.get("bad_pixel_ratio_max") or 1.0):
            blockers.append("bad-pixel-ratio")
        if not visual["size_match"]:
            blockers.append("fixed-canvas-size")
    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_id": str(truth.get("sample_id") or ""),
        "status": "pass" if not blockers else "blocked-fail",
        "blockers": blockers,
        "metrics": {
            "critical_text_recall": text["recall"],
            "critical_control_recall": controls["recall"],
            "control_value_accuracy": controls["value_accuracy"],
            "control_state_accuracy": controls["state_accuracy"],
            "control_bbox_iou": controls["bbox_iou"],
            "critical_container_recall": containers["recall"],
            "container_bbox_iou": containers["bbox_iou"],
            "table_header_recall": tables["header_recall"],
            "table_row_recall": tables["row_recall"],
            "critical_asset_recall": assets["recall"],
            "critical_asset_bbox_iou": assets["bbox_iou"],
            "native_text_expected": native["expected_native_text"],
            "native_text_actual": native["actual_native_text"],
            "image_fill_expected": native["expected_image_fills"],
            "image_fill_actual": native["actual_image_fills"],
            "grayscale_mae": visual.get("grayscale_mae"),
            "bad_pixel_ratio": visual.get("bad_pixel_ratio", 1.0),
            "bad_pixel_threshold": visual.get("bad_pixel_threshold", 30),
            "visible_underlay_ratio": underlay_ratio,
            "content_coverage": visual.get("content_coverage", 0.0),
            "source_content_coverage": visual.get("source_content_coverage", 0.0),
            "generated_asset_count": assets["generated_count"],
            "observed_asset_count": assets["observed_count"],
        },
        "details": {
            "text": text,
            "controls": controls,
            "containers": containers,
            "tables": tables,
            "assets": assets,
            "native": native,
            "visual": visual,
        },
        "policy": policy,
        "product_non_gates": {
            "component_instance_reuse": "not-required",
            "root_responsive_reflow": "not-required",
            "external_provenance_file": "not-required",
        },
    }


def write_image_enrichment_report(
    runs: list[dict],
    output: Path,
) -> dict[str, Any]:
    """Write deterministic JSON and Markdown acceptance summaries."""

    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    normalized = [
        json.loads(json.dumps(run, ensure_ascii=False, default=str))
        for run in runs
        if isinstance(run, Mapping)
    ]
    passed = sum(str(run.get("status") or "") == "pass" for run in normalized)
    failed = len(normalized) - passed
    status = (
        "pass" if normalized and failed == 0 else "mixed" if passed else "blocked-fail"
    )
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
        "run_count": len(normalized),
        "passed_count": passed,
        "failed_count": failed,
        "runs": normalized,
        "decision": "pass" if status == "pass" else "do-not-adopt-yet",
    }
    (destination / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Grounding Image Enrichment Acceptance",
        "",
        f"Status: **{status}**",
        "",
        "| Sample | Mode | Status | Blockers |",
        "| --- | --- | --- | --- |",
    ]
    for run in normalized:
        lines.append(
            "| {sample} | {mode} | {status} | {blockers} |".format(
                sample=str(run.get("sample_id") or "unknown"),
                mode=str(run.get("mode") or "unknown"),
                status=str(run.get("status") or "unknown"),
                blockers=", ".join(str(item) for item in run.get("blockers") or [])
                or "-",
            )
        )
    lines.extend(
        [
            "",
            "Visual similarity is never sufficient without critical content, structure, asset identity, native editability and underlay gates.",
            "",
        ]
    )
    (destination / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report
