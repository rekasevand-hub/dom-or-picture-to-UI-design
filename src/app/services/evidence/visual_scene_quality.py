"""Strict scene-hygiene and visual target gate for teacher-informed layouts."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2
import numpy as np

DEFAULT_POLICY = {
    "mae_max": 6.0,
    "bad_pixel_ratio_max": 0.05,
    "duplicate_text_overlap_count_max": 0,
    "text_overflow_ratio_max": 0.02,
    "explicit_font_ratio_min": 0.95,
    "vector_icon_count_min": 1,
}


def _text(value: Any) -> str:
    return re.sub(
        r"\s+",
        "",
        unicodedata.normalize("NFKC", str(value or "")).casefold(),
    )


def _box(element: Mapping[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(element.get("x") or 0),
        float(element.get("y") or 0),
        float(element.get("width") or 0),
        float(element.get("height") or 0),
    )


def _overlap(first: Mapping[str, Any], second: Mapping[str, Any]) -> float:
    ax, ay, aw, ah = _box(first)
    bx, by, bw, bh = _box(second)
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    smaller = min(aw * ah, bw * bh)
    return intersection / smaller if smaller > 0 else 0.0


def _visual(
    rendered_png: Path,
    reference_png: Path,
) -> dict[str, Any]:
    reference = cv2.imread(str(reference_png))
    rendered = cv2.imread(str(rendered_png))
    if reference is None or rendered is None:
        return {
            "status": "unreadable",
            "mae": 255.0,
            "bad_pixel_ratio": 1.0,
        }
    if rendered.shape[:2] != reference.shape[:2]:
        rendered = cv2.resize(
            rendered,
            (reference.shape[1], reference.shape[0]),
        )
    gray_reference = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    gray_rendered = cv2.cvtColor(rendered, cv2.COLOR_BGR2GRAY)
    mae = float(
        np.abs(gray_rendered.astype(np.int16) - gray_reference.astype(np.int16)).mean()
    )
    max_delta = np.abs(rendered.astype(np.int16) - reference.astype(np.int16)).max(
        axis=2
    )
    return {
        "status": "measured",
        "mae": mae,
        "bad_pixel_ratio": float((max_delta > 30).mean()),
        "size_match": rendered.shape[:2] == reference.shape[:2],
    }


def evaluate_visual_scene(
    design: Mapping[str, Any],
    rendered_png: str | Path,
    reference_png: str | Path,
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy_value = {**DEFAULT_POLICY, **dict(policy or {})}
    elements = [
        dict(element)
        for element in design.get("elements") or []
        if isinstance(element, Mapping)
    ]
    text_elements = [
        element
        for element in elements
        if str(element.get("controlValue") or element.get("text") or "").strip()
        and _box(element)[2] > 0
        and _box(element)[3] > 0
    ]
    duplicate_overlap_count = 0
    for index, element in enumerate(text_elements):
        normalized = _text(element.get("controlValue") or element.get("text"))
        for other in text_elements[index + 1 :]:
            if (
                normalized
                and normalized == _text(other.get("controlValue") or other.get("text"))
                and _overlap(element, other) >= 0.5
            ):
                duplicate_overlap_count += 1
    width = int((design.get("canvas") or {}).get("width") or 0)
    height = int((design.get("canvas") or {}).get("height") or 0)
    overflow_count = sum(
        1
        for element in text_elements
        if (_box(element)[0] < 0 or _box(element)[0] + _box(element)[2] > width)
    )
    clipped_vertical_count = sum(
        1
        for element in text_elements
        if (_box(element)[1] < 0 or _box(element)[1] + _box(element)[3] > height)
    )
    explicit_font_count = sum(
        bool((element.get("style") or {}).get("fontFamily"))
        for element in text_elements
    )
    explicit_font_ratio = (
        explicit_font_count / len(text_elements) if text_elements else 1.0
    )
    text_overflow_ratio = overflow_count / len(text_elements) if text_elements else 0.0
    vector_count = sum(bool(element.get("vectorSvg")) for element in elements)
    visual = _visual(Path(rendered_png), Path(reference_png))
    blockers: list[str] = []
    if duplicate_overlap_count > int(policy_value["duplicate_text_overlap_count_max"]):
        blockers.append("duplicate-text-overlap")
    if text_overflow_ratio > float(policy_value["text_overflow_ratio_max"]):
        blockers.append("text-overflow")
    if explicit_font_ratio < float(policy_value["explicit_font_ratio_min"]):
        blockers.append("font-selection-missing")
    if vector_count < int(policy_value["vector_icon_count_min"]):
        blockers.append("vector-icons-missing")
    if visual["mae"] > float(policy_value["mae_max"]):
        blockers.append("visual-mae")
    if visual["bad_pixel_ratio"] > float(policy_value["bad_pixel_ratio_max"]):
        blockers.append("bad-pixel-ratio")
    return {
        "schema_version": "visual-scene-quality/1.0",
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "metrics": {
            "duplicate_text_overlap_count": duplicate_overlap_count,
            "text_elements": len(text_elements),
            "text_overflow_count": overflow_count,
            "text_overflow_ratio": text_overflow_ratio,
            "clipped_vertical_count": clipped_vertical_count,
            "explicit_font_ratio": explicit_font_ratio,
            "vector_icon_count": vector_count,
            "mae": visual["mae"],
            "bad_pixel_ratio": visual["bad_pixel_ratio"],
        },
        "policy": dict(policy_value),
    }
