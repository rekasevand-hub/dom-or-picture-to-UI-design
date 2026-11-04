"""Snap candidate controls to visible rectangles and infer basic UI state."""

from __future__ import annotations

import copy
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np

FIELD_TYPES = {
    "button",
    "icon-button",
    "input",
    "link",
    "navigation",
    "pagination",
    "select",
    "textarea",
}
CHECK_TYPES = {"checkbox", "radio", "toggle"}
CONTROL_TYPES = FIELD_TYPES | CHECK_TYPES


def _normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", text)


def _repair_ocr_label(value: Any) -> str:
    text = str(value or "").strip()
    if (
        len(text) > 2
        and text[0] in {"W", "w"}
        and text[1].isascii()
        and any("\u4e00" <= char <= "\u9fff" for char in text[2:])
    ):
        return "以" + text[1:]
    return text


def _nearby_text(
    candidates: list[tuple[Mapping[str, Any], list[int] | None]],
    control_box: list[int],
    width: int,
    height: int,
) -> tuple[str, list[int]] | None:
    best: tuple[float, str, list[int]] | None = None
    control_center_x = control_box[0] + control_box[2] / 2
    control_center_y = control_box[1] + control_box[3] / 2
    for element, box in candidates:
        if box is None:
            continue
        text_center_x = box[0] + box[2] / 2
        text_center_y = box[1] + box[3] / 2
        if not (control_box[0] <= text_center_x <= control_box[0] + control_box[2]):
            continue
        if abs(text_center_y - control_center_y) > max(
            80,
            control_box[3] * 1.5,
        ):
            continue
        distance = math.hypot(
            (text_center_x - control_center_x) / max(1, width),
            (text_center_y - control_center_y) / max(1, height),
        )
        candidate = (
            distance,
            _repair_ocr_label(element.get("text")),
            box,
        )
        if best is None or candidate[0] < best[0]:
            best = candidate
    return (best[1], list(best[2])) if best is not None else None


def _matching_text_box(
    candidates: list[tuple[Mapping[str, Any], list[int] | None]],
    value: str,
    original: list[int],
    width: int,
    height: int,
) -> list[int] | None:
    normalized = _normalized_text(value)
    if not normalized:
        return None
    matches = [
        (
            math.hypot(
                (box[0] + box[2] / 2 - (original[0] + original[2] / 2))
                / max(1, width),
                (box[1] + box[3] / 2 - (original[1] + original[3] / 2))
                / max(1, height),
            ),
            box,
        )
        for element, box in candidates
        if box is not None and _normalized_text(element.get("text")) == normalized
    ]
    return list(min(matches)[1]) if matches else None


def _bbox(value: Any, width: int, height: int) -> list[int] | None:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or len(value) != 4
    ):
        return None
    try:
        x, y, box_width, box_height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    left = max(0, min(width, x))
    top = max(0, min(height, y))
    right = max(left, min(width, x + box_width))
    bottom = max(top, min(height, y + box_height))
    if right - left < 8 or bottom - top < 8:
        return None
    return [left, top, right - left, bottom - top]


def _intersection(first: list[int], second: list[int]) -> int:
    width = max(
        0,
        min(first[0] + first[2], second[0] + second[2])
        - max(first[0], second[0]),
    )
    height = max(
        0,
        min(first[1] + first[3], second[1] + second[3])
        - max(first[1], second[1]),
    )
    return width * height


def _iou(first: list[int], second: list[int]) -> float:
    intersection = _intersection(first, second)
    union = first[2] * first[3] + second[2] * second[3] - intersection
    return intersection / union if union > 0 else 0.0


def _deduplicate(
    boxes: list[list[int]],
    *,
    preserve_contained: bool = False,
) -> list[list[int]]:
    kept: list[list[int]] = []
    for box in sorted(boxes, key=lambda item: (-item[2] * item[3], item[1], item[0])):
        contained_by_merged = any(
            preserve_contained
            and existing[2] > box[2] * 1.25
            and _intersection(box, existing) / max(1, box[2] * box[3]) >= 0.90
            for existing in kept
        )
        if contained_by_merged:
            kept.append(box)
            continue
        if any(
            _iou(box, existing) >= 0.55
            or _intersection(box, existing) / max(1, min(
                box[2] * box[3],
                existing[2] * existing[3],
            ))
            >= 0.85
            for existing in kept
        ):
            continue
        kept.append(box)
    return kept


def _visible_rectangles(
    image_path: Path,
) -> tuple[list[list[int]], list[list[int]], np.ndarray]:
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"unable to read control source image: {image_path}")
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 10, 50)
    edges = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        np.ones((3, 3), dtype=np.uint8),
    )
    contours, _hierarchy = cv2.findContours(
        edges,
        cv2.RETR_LIST,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    fields: list[list[int]] = []
    checks: list[list[int]] = []
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        if x <= 1 or y <= 1 or x + box_width >= width - 1:
            continue
        if y + box_height >= height - 1:
            continue
        ratio = box_width / box_height if box_height else 0.0
        if 18 <= box_width <= 36 and 18 <= box_height <= 36 and 0.75 <= ratio <= 1.33:
            checks.append([x, y, box_width, box_height])
        elif (
            48 <= box_width <= width
            and 22 <= box_height <= 160
            and 1.1 <= ratio <= 40
        ):
            fields.append([x, y, box_width, box_height])
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturated = (
        (hsv[..., 1] >= 65) & (hsv[..., 2] >= 70)
    ).astype(np.uint8) * 255
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        saturated,
        8,
    )
    for index in range(1, count):
        x, y, box_width, box_height, area = (
            int(value) for value in stats[index, :5]
        )
        if (
            8 <= box_width <= 36
            and 8 <= box_height <= 36
            and area >= 20
            and y >= 100
        ):
            margin_x = max(4, box_width // 4)
            margin_y = max(4, box_height // 4)
            checks.append(
                [
                    max(0, x - margin_x),
                    max(0, y - margin_y),
                    min(width - x + margin_x, box_width + margin_x * 2),
                    min(height - y + margin_y, box_height + margin_y * 2),
                ]
            )
    return (
        _deduplicate(fields, preserve_contained=True),
        _deduplicate(checks),
        image,
    )


def _nearest_box(
    target: list[int],
    candidates: list[list[int]],
    width: int,
    height: int,
    *,
    excluded: set[tuple[int, int, int, int]] | None = None,
) -> list[int] | None:
    best: tuple[float, list[int]] | None = None
    target_center = (
        target[0] + target[2] / 2,
        target[1] + target[3] / 2,
    )
    for candidate in candidates:
        if excluded is not None and tuple(candidate) in excluded:
            continue
        center = (
            candidate[0] + candidate[2] / 2,
            candidate[1] + candidate[3] / 2,
        )
        distance = math.hypot(
            (center[0] - target_center[0]) / max(1, width),
            (center[1] - target_center[1]) / max(1, height),
        )
        overlap = _iou(target, candidate)
        score = distance - overlap * 0.25
        if best is None or score < best[0]:
            best = (score, candidate)
    if best is None or best[0] > 0.28:
        return None
    return list(best[1])


def _interior_metrics(
    image: np.ndarray,
    box: list[int],
) -> tuple[float, float, float]:
    x, y, width, height = box
    margin_x = max(2, width // 12)
    margin_y = max(2, height // 5)
    crop = image[
        y + margin_y : y + height - margin_y,
        x + margin_x : x + width - margin_x,
    ]
    if crop.size == 0:
        return 255.0, 0.0, 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    brightness = float(np.median(gray))
    saturated_ratio = float(
        ((hsv[..., 1] >= 65) & (hsv[..., 2] >= 70)).mean()
    )
    dark_ratio = float((gray < 180).mean())
    return brightness, saturated_ratio, dark_ratio


def _control_state(
    control_type: str,
    existing: Any,
    image: np.ndarray,
    box: list[int],
) -> str:
    normalized = str(existing or "").strip().lower()
    allowed = (
        {"checked", "unchecked", "mixed"}
        if control_type in CHECK_TYPES
        else {"enabled", "disabled"}
    )
    if normalized == "mixed" and "mixed" in allowed:
        return normalized
    if control_type in {"button", "icon-button", "link", "navigation", "pagination"}:
        return "enabled"
    brightness, saturated_ratio, dark_ratio = _interior_metrics(image, box)
    if control_type in CHECK_TYPES:
        return (
            "checked"
            if saturated_ratio >= 0.05 or dark_ratio >= 0.04
            else "unchecked"
        )
    return "disabled" if brightness < 252.0 else "enabled"


def _element_bbox(element: Mapping[str, Any], width: int, height: int) -> list[int] | None:
    return _bbox(element.get("bbox"), width, height)


def _row_groups(
    entries: list[tuple[Any, list[int]]],
    tolerance: float,
) -> list[list[tuple[Any, list[int]]]]:
    groups: list[list[tuple[Any, list[int]]]] = []
    centers: list[float] = []
    for entry in sorted(entries, key=lambda item: (item[1][1], item[1][0])):
        center = entry[1][1] + entry[1][3] / 2
        if not groups or abs(center - centers[-1]) > tolerance:
            groups.append([entry])
            centers.append(center)
        else:
            groups[-1].append(entry)
            centers[-1] = sum(
                box[1] + box[3] / 2 for _item, box in groups[-1]
            ) / len(groups[-1])
    return groups


def _calibrated_field_rows(
    elements: list[dict[str, Any]],
    fields: list[list[int]],
    width: int,
    height: int,
) -> dict[int, list[int]]:
    controls = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        control_type = str(
            element.get("controlType") or element.get("type") or ""
        ).lower()
        if control_type not in {
            "input",
            "radio",
            "select",
            "textarea",
            "toggle",
        }:
            continue
        box = _bbox(
            element.get("controlSourceBbox") or element.get("bbox"),
            width,
            height,
        )
        if box is not None and box[1] < height * 0.52:
            controls.append((element, box))
    candidates = [
        (None, box.copy())
        for box in fields
        if box[1] >= 110 and box[1] < height * 0.52 and box[2] >= 80
    ]
    control_groups = _row_groups(controls, max(18, height * 0.03))
    field_groups = _row_groups(candidates, max(18, height * 0.03))
    if not control_groups or len(control_groups) != len(field_groups):
        return {}
    targets: dict[int, list[int]] = {}
    for control_group, field_group in zip(control_groups, field_groups, strict=True):
        available = [box for _item, box in field_group]
        for element, control_box in sorted(
            control_group,
            key=lambda item: item[1][0],
        ):
            if not available:
                break
            best = min(
                available,
                key=lambda candidate: abs(
                    candidate[0] + candidate[2] / 2
                    - (control_box[0] + control_box[2] / 2)
                ),
            )
            available.remove(best)
            targets[id(element)] = list(best)
    return targets


def _seed_checkbox_elements(
    graph: dict[str, Any],
    image_path: Path,
    image: np.ndarray,
    width: int,
    height: int,
    checks: list[list[int]],
    used_checks: set[tuple[int, int, int, int]],
) -> tuple[list[dict[str, Any]], int]:
    existing = {
        tuple(element.get("bbox") or [])
        for element in graph.get("elements") or []
        if isinstance(element, Mapping)
    }
    added: list[dict[str, Any]] = []
    enrichment = graph.get("imageEnrichment")
    assets = enrichment.get("assets") if isinstance(enrichment, Mapping) else []
    next_id = (
        max(
            [
                int(element.get("id"))
                for element in graph.get("elements") or []
                if str(element.get("id") or "").isdigit()
            ]
            or [0]
        )
        + 1
    )
    for asset in assets or []:
        if not isinstance(asset, Mapping):
            continue
        name = str(asset.get("name") or "").lower()
        if "checkbox" not in name and not (
            name.startswith("check") and str(asset.get("kind") or "") == "icon"
        ):
            continue
        candidate = _bbox(asset.get("bbox"), width, height)
        if candidate is None:
            continue
        snapped = _nearest_box(
            candidate,
            checks,
            width,
            height,
            excluded=used_checks,
        )
        if snapped is None or tuple(snapped) in existing:
            continue
        existing.add(tuple(snapped))
        used_checks.add(tuple(snapped))
        state = _control_state(
            "checkbox",
            asset.get("controlState"),
            image,
            snapped,
        )
        added.append(
            {
                "id": next_id,
                "bbox": snapped,
                "type": "checkbox",
                "text": name.removeprefix("checkbox_").replace("_", " "),
                "controlType": "checkbox",
                "controlValue": "",
                "controlState": state,
                "source": "image-enrichment:control-recovery",
            }
        )
        next_id += 1
    return added, len(added)


def recover_visible_controls(
    graph: dict,
    image_path: Path,
    *,
    add_from_assets: bool = True,
    text_observations: list[Mapping[str, Any]] | None = None,
) -> tuple[dict, dict[str, Any]]:
    """Snap model controls to visible geometry and add recoverable checkboxes."""

    if not isinstance(graph, Mapping):
        raise ValueError("graph must be an object")
    source = Path(image_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    recovered = copy.deepcopy(dict(graph))
    width = int(recovered.get("image_w") or 0)
    height = int(recovered.get("image_h") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("graph image dimensions must be positive")
    fields, checks, image = _visible_rectangles(source)
    row_targets = _calibrated_field_rows(
        recovered.get("elements") or [],
        fields,
        width,
        height,
    )
    text_candidates = [
        (element, _element_bbox(element, width, height))
        for element in recovered.get("elements") or []
        if isinstance(element, Mapping)
        and str(element.get("type") or "").lower() == "text"
        and str(element.get("text") or "").strip()
    ]
    for observation in text_observations or []:
        text = str(observation.get("text") or "").strip()
        box = _bbox(observation.get("bbox"), width, height)
        if text and box is not None:
            text_candidates.append(({"text": text}, box))
    snapped_count = 0
    used_fields: set[tuple[int, int, int, int]] = set()
    used_checks: set[tuple[int, int, int, int]] = set()
    for element in recovered.get("elements") or []:
        if not isinstance(element, dict):
            continue
        control_type = str(
            element.get("controlType") or element.get("type") or ""
        ).lower()
        if control_type not in CONTROL_TYPES:
            continue
        original = _bbox(
            element.get("controlSourceBbox") or element.get("bbox"),
            width,
            height,
        )
        if original is None:
            continue
        element.setdefault("controlSourceBbox", list(original))
        element["controlType"] = control_type
        control_value = str(
            element.get("controlValue") or element.get("value") or element.get("text") or ""
        )
        nearby = (
            _nearby_text(text_candidates, original, width, height)
            if control_type not in CHECK_TYPES
            else None
        )
        text_box = None
        if nearby is not None and (
            not control_value
            or _normalized_text(nearby[0]) == _normalized_text(control_value)
        ):
            control_value, text_box = nearby
        elif control_value:
            text_box = _matching_text_box(
                text_candidates,
                control_value,
                original,
                width,
                height,
            )
        target = text_box or original
        candidates = checks if control_type in CHECK_TYPES else fields
        if text_box is not None:
            center_x = text_box[0] + text_box[2] / 2
            center_y = text_box[1] + text_box[3] / 2
            containing = [
                candidate
                for candidate in candidates
                if candidate[0] <= center_x <= candidate[0] + candidate[2]
                and candidate[1] <= center_y <= candidate[1] + candidate[3]
            ]
            if containing:
                candidates = containing
        used = used_checks if control_type in CHECK_TYPES else used_fields
        snapped = row_targets.get(id(element))
        if snapped is None:
            snapped = _nearest_box(
                target,
                candidates,
                width,
                height,
                excluded=used,
            )
        if snapped is not None:
            element["bbox"] = snapped
            snapped_count += 1
            used.add(tuple(snapped))
        else:
            snapped = original
        if not control_value and control_type not in CHECK_TYPES:
            control_value = _inside_text(text_candidates, snapped, width, height)
        element["controlValue"] = control_value
        element["controlState"] = _control_state(
            control_type,
            element.get("controlState") or element.get("state"),
            image,
            snapped,
        )
    added, added_count = (
        _seed_checkbox_elements(
            recovered,
            source,
            image,
            width,
            height,
            checks,
            used_checks,
        )
        if add_from_assets
        else ([], 0)
    )
    if added:
        recovered.setdefault("elements", []).extend(added)
    for element in recovered.get("elements") or []:
        if (
            not isinstance(element, dict)
            or str(element.get("controlType") or "").lower() not in CHECK_TYPES
            or str(element.get("controlState") or "").lower() != "checked"
            or str(element.get("controlValue") or "").strip()
        ):
            continue
        box = _element_bbox(element, width, height)
        if box is not None:
            element["controlValue"] = _adjacent_text(
                text_candidates,
                box,
                width,
                height,
            )
    report = {
        "schema_version": "image-control-recovery/1.0",
        "status": "applied" if snapped_count or added_count else "not-needed",
        "field_candidate_count": len(fields),
        "checkbox_candidate_count": len(checks),
        "snapped_count": snapped_count,
        "added_count": added_count,
    }
    enrichment = recovered.setdefault("imageEnrichment", {})
    if isinstance(enrichment, dict):
        enrichment["controlRecovery"] = copy.deepcopy(report)
    return recovered, report


def _adjacent_text(
    candidates: list[tuple[Mapping[str, Any], list[int] | None]],
    control_box: list[int],
    width: int,
    height: int,
) -> str:
    control_y = control_box[1] + control_box[3] / 2
    ranked: list[tuple[float, str]] = []
    for element, box in candidates:
        if box is None:
            continue
        text_y = box[1] + box[3] / 2
        if abs(text_y - control_y) > max(12, control_box[3] * 0.75):
            continue
        left_gap = control_box[0] - (box[0] + box[2])
        right_gap = box[0] - (control_box[0] + control_box[2])
        gap = max(0, left_gap, right_gap)
        if gap > 260:
            continue
        ranked.append((gap, _repair_ocr_label(element.get("text"))))
    return min(ranked)[1] if ranked else ""


def _inside_text(
    candidates: list[tuple[Mapping[str, Any], list[int] | None]],
    control_box: list[int],
    width: int,
    height: int,
) -> str:
    ranked = []
    control_area = control_box[2] * control_box[3]
    for element, box in candidates:
        if box is None:
            continue
        overlap = _intersection(control_box, box)
        if overlap / max(1, box[2] * box[3]) < 0.80:
            continue
        ranked.append(
            (
                overlap / max(1, control_area),
                -box[1],
                -box[0],
                str(element.get("text") or "").strip(),
            )
        )
    return max(ranked)[-1] if ranked else ""
