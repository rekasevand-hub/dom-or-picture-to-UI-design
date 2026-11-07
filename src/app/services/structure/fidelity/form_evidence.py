"""Reconcile deterministic form evidence from source observations."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from src.app.services.structure.fidelity.contracts import (
    normalize_bbox,
    normalize_match_text,
    owner_text_similarity,
    stable_id,
)

_DATE_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2})(\d{1,2}:\d{2}:\d{2})$")
_FORM_LABELS = {"执行时间", "执行者"}
_INVALID_CHECKBOX_LABELS = {"", "0", "1", "false", "true", "unchecked", "checked"}


def _overlap_over_smaller(left: list[int], right: list[int]) -> float:
    x = max(0, min(left[0] + left[2], right[0] + right[2]) - max(left[0], right[0]))
    y = max(0, min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1]))
    intersection = x * y
    smaller = min(left[2] * left[3], right[2] * right[3])
    return intersection / smaller if smaller else 0.0


def _repair_datetime(value: Any) -> str:
    text = str(value or "")
    match = _DATE_TIME.fullmatch(text)
    return f"{match.group(1)} {match.group(2)}" if match else text


def _nearby_checkbox_label_observation(
    checkbox_bbox: list[int],
    observations: list[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    checkbox_center_y = checkbox_bbox[1] + checkbox_bbox[3] / 2
    candidates = []
    for observation in observations:
        text = str(observation.get("text") or "").strip()
        bbox = observation.get("bbox")
        if (
            not text
            or not isinstance(bbox, list)
            or len(bbox) != 4
            or bbox[2] < 40
            or bbox[3] < 12
        ):
            continue
        center_y = float(bbox[1]) + float(bbox[3]) / 2
        gap = max(
            float(checkbox_bbox[0]) - (float(bbox[0]) + float(bbox[2])),
            float(bbox[0]) - (float(checkbox_bbox[0]) + float(checkbox_bbox[2])),
        )
        if abs(center_y - checkbox_center_y) <= 12 and -4 <= gap <= 32:
            candidates.append((max(0.0, gap), observation))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _recognize_checkbox_label(image_path: str, bbox: list[int]) -> str:
    import numpy as np
    from PIL import Image

    from src.app.services.ocr.tesseract_engine import TesseractEngine

    x, y, width, height = bbox
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        crop = image.crop(
            (
                max(0, x - 2),
                max(0, y - 2),
                min(image.width, x + width + 2),
                min(image.height, y + height + 2),
            )
        )
    recognized = TesseractEngine(lang="chi_sim+eng").recognize(np.asarray(crop))
    return " ".join(
        line.strip() for line in recognized.splitlines() if line.strip()
    ).strip()


def reconcile_form_evidence(
    graph: Mapping[str, Any],
    ocr_supplement: Mapping[str, Any] | None,
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Repair duplicate schedule controls and high-confidence form text evidence."""
    reconciled = copy.deepcopy(dict(graph))
    elements = [
        copy.deepcopy(element)
        for element in reconciled.get("elements") or []
        if isinstance(element, Mapping)
    ]
    removed_ids: set[str] = set()
    corrected: list[dict[str, Any]] = []

    schedule_controls: list[dict[str, Any]] = []
    for element in elements:
        text = str(element.get("controlValue") or element.get("text") or "")
        bbox = normalize_bbox(element.get("bbox"), width, height)
        control_type = str(
            element.get("controlType") or element.get("type") or ""
        ).lower()
        if bbox is not None and "*" in text and bbox[2] >= 350:
            schedule_controls.append(
                {
                    "element": element,
                    "bbox": bbox,
                    "text": text,
                    "control_type": control_type,
                }
            )
    if len(schedule_controls) > 1:
        schedule_controls.sort(
            key=lambda item: (
                len(item["text"].split()),
                item["control_type"] == "input",
                len(item["text"]),
            ),
            reverse=True,
        )
        kept = schedule_controls[0]
        for duplicate in schedule_controls[1:]:
            duplicate_element = duplicate["element"]
            duplicate_id = str(duplicate_element.get("id") or "")
            removed_ids.add(duplicate_id)
            duplicate_text = str(duplicate["text"])
            for element in elements:
                if str(element.get("id") or "") in removed_ids:
                    continue
                element_text = str(element.get("text") or "")
                bbox = normalize_bbox(element.get("bbox"), width, height)
                if (
                    bbox is not None
                    and _overlap_over_smaller(kept["bbox"], bbox) >= 0.45
                    and owner_text_similarity(element_text, duplicate_text) >= 0.7
                ):
                    removed_ids.add(str(element.get("id") or ""))
            corrected.append(
                {
                    "reason": "duplicate-schedule-control",
                    "kept_ref": f"graph.elements[{elements.index(kept['element'])}]",
                    "removed_ref": f"graph.elements[{elements.index(duplicate_element)}]",
                    "removed_text": duplicate_text,
                }
            )

    checkbox_observations = [
        item
        for item in (ocr_supplement or {}).get("observations") or []
        if isinstance(item, Mapping)
        and float(item.get("confidence") or 0) >= 0.45
        and normalize_bbox(item.get("bbox"), width, height) is not None
    ]
    observations = [
        item
        for item in checkbox_observations
        if float(item.get("confidence") or 0) >= 0.9
    ]
    image_path = str(reconciled.get("image") or "")
    if image_path:
        for element in elements:
            control_type = str(
                element.get("controlType") or element.get("type") or ""
            ).lower()
            current_label = _repair_datetime(
                element.get("label")
                or element.get("controlValue")
                or element.get("text")
                or ""
            )
            if (
                control_type != "checkbox"
                or current_label.strip().lower() not in _INVALID_CHECKBOX_LABELS
            ):
                continue
            checkbox_bbox = normalize_bbox(element.get("bbox"), width, height)
            if checkbox_bbox is None:
                continue
            observation = _nearby_checkbox_label_observation(
                checkbox_bbox,
                checkbox_observations,
            )
            if observation is None:
                continue
            label_bbox = normalize_bbox(observation.get("bbox"), width, height)
            if label_bbox is None:
                continue
            recognized = _recognize_checkbox_label(image_path, label_bbox)
            if (
                not normalize_match_text(recognized)
                or owner_text_similarity(
                    recognized,
                    observation.get("text") or "",
                )
                < 0.6
            ):
                continue
            element["controlValue"] = recognized
            element["label"] = recognized
            label = next(
                (
                    candidate
                    for candidate in elements
                    if str(candidate.get("type") or "").lower() in {"text", "link"}
                    and normalize_bbox(candidate.get("bbox"), width, height)
                    == label_bbox
                ),
                None,
            )
            if label is not None:
                label["text"] = recognized
                label["role"] = "control-label"
                label["source"] = "ocr-supplement:easyocr+tesseract"
            corrected.append(
                {
                    "reason": "checkbox-label-tesseract",
                    "content_ref": f"graph.elements[{elements.index(element)}]",
                    "bbox": label_bbox,
                    "text": recognized,
                }
            )
    for element in elements:
        text = _repair_datetime(
            element.get("controlValue") or element.get("text") or ""
        )
        if "controlValue" in element and str(element["controlValue"]) != text:
            element["controlValue"] = text
            corrected.append(
                {
                    "reason": "datetime-spacing",
                    "content_ref": f"graph.elements[{elements.index(element)}]",
                    "value": text,
                }
            )
        if "text" in element and str(element["text"]) != text:
            element["text"] = text
        if str(element.get("type") or "").lower() not in {"text", "link"}:
            continue
        current_bbox = normalize_bbox(element.get("bbox"), width, height)
        normalized_text = normalize_match_text(text)
        if current_bbox is None or not normalized_text:
            continue
        matches = [
            observation
            for observation in observations
            if normalize_match_text(observation.get("text")) == normalized_text
        ]
        if not matches:
            continue
        observation = max(
            matches,
            key=lambda item: float(item.get("confidence") or 0),
        )
        observation_bbox = normalize_bbox(observation.get("bbox"), width, height)
        if observation_bbox is None:
            continue
        if current_bbox[1] < 200 or observation_bbox[1] < 200:
            continue
        if abs(observation_bbox[1] - current_bbox[1]) > 96:
            continue
        if _overlap_over_smaller(current_bbox, observation_bbox) >= 0.25:
            continue
        element["bbox"] = observation_bbox
        if normalized_text in {"执行成功", "success"}:
            element["role"] = "form-status"
        corrected.append(
            {
                "reason": "high-confidence-ocr-bbox",
                "content_ref": f"graph.elements[{elements.index(element)}]",
                "text": text,
                "bbox": observation_bbox,
            }
        )

    existing_label_texts = {
        normalize_match_text(element.get("text"))
        for element in elements
        if str(element.get("role") or "") == "form-label"
    }
    for observation in observations:
        text = str(observation.get("text") or "")
        normalized_text = normalize_match_text(text)
        if normalized_text not in _FORM_LABELS:
            continue
        if normalized_text in existing_label_texts:
            continue
        bbox = normalize_bbox(observation.get("bbox"), width, height)
        if bbox is None:
            continue
        label_id = stable_id("text", "form-label", text, bbox)
        elements.append(
            {
                "id": label_id,
                "type": "text",
                "text": text,
                "bbox": bbox,
                "role": "form-label",
                "source": "ocr_supplement",
                "authority": "ocr",
                "confidence": float(observation.get("confidence") or 0),
            }
        )
        existing_label_texts.add(normalized_text)
        corrected.append(
            {
                "reason": "missing-form-label",
                "content_ref": label_id,
                "text": text,
                "bbox": bbox,
            }
        )

    reconciled["elements"] = [
        element
        for element in elements
        if str(element.get("id") or "") not in removed_ids
    ]
    provenance = reconciled.setdefault("provenance", {})
    provenance["formEvidenceReconciliation"] = {
        "removed_count": len(removed_ids),
        "corrections": corrected,
    }
    return reconciled
