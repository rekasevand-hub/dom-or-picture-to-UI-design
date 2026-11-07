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

    observations = [
        item
        for item in (ocr_supplement or {}).get("observations") or []
        if isinstance(item, Mapping)
        and float(item.get("confidence") or 0) >= 0.9
        and normalize_bbox(item.get("bbox"), width, height) is not None
    ]
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
