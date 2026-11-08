"""Evidence-driven coordinate-space contract for VLM grounding output.

VLM backends may answer in 0..1000 normalized coordinates, in source pixels,
or in a mixture of both within one response.  The legacy parser guessed the x
axis from ``max(x) <= 1000`` and hard-coded ``y_scale = 1.0``, which produces a
vertical drift proportional to image height.

This module replaces the guess with a measurable invariant: for every candidate
inverse transform, transform the proposed text boxes and score how many of them
actually land on ink in the reference screenshot.  The best supported transform
wins.  Individual boxes are then allowed to opt out when the identity
transform has stronger pixel evidence, which handles mixed-coordinate replies.

The module has no dependency on the grounding backend: the pixel scorer is
built from the shared perception-contract primitive and injected by the caller.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

COORDINATE_CONTRACT_VERSION = "grounding-coordinate-space/1.1"
NORMALIZED_AXIS = 1000.0
MIN_INK_SUPPORT = 0.01
MIN_SCORED_BOXES = 3


class InkScorer(Protocol):
    def __call__(self, bbox: Sequence[Any]) -> float: ...


@dataclass(frozen=True)
class AxisScales:
    x: float
    y: float
    label: str


@dataclass
class CoordinateSpaceDecision:
    x_scale: float
    y_scale: float
    provenance: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": COORDINATE_CONTRACT_VERSION,
            "xScale": round(float(self.x_scale), 6),
            "yScale": round(float(self.y_scale), 6),
            "provenance": self.provenance,
            "evidence": dict(self.evidence),
        }


def candidate_scales(image_w: int, image_h: int) -> list[AxisScales]:
    sx = float(image_w) / NORMALIZED_AXIS
    sy = float(image_h) / NORMALIZED_AXIS
    return [
        AxisScales(1.0, 1.0, "identity"),
        AxisScales(sx, 1.0, "x-1000"),
        AxisScales(1.0, sy, "y-1000"),
        AxisScales(sx, sy, "xywh-1000"),
    ]


def _as_xywh(value: Any) -> list[float] | None:
    if isinstance(value, Mapping):
        raw = [
            value.get("x"),
            value.get("y"),
            value.get("width"),
            value.get("height"),
        ]
    elif isinstance(value, (list, tuple)) and len(value) == 4:
        raw = list(value)
    else:
        return None
    try:
        numbers = [float(item) for item in raw]
    except (TypeError, ValueError, OverflowError):
        return None
    if numbers[2] <= 0 or numbers[3] <= 0:
        return None
    return numbers


def _clip_bbox(
    bbox: list[float], image_w: int, image_h: int
) -> list[int] | None:
    x, y, width, height = bbox
    left = max(0.0, min(x, float(image_w - 1)))
    top = max(0.0, min(y, float(image_h - 1)))
    right = max(left + 1.0, min(x + width, float(image_w)))
    bottom = max(top + 1.0, min(y + height, float(image_h)))
    if right - left < 2 or bottom - top < 2:
        return None
    return [
        int(round(left)),
        int(round(top)),
        int(round(right - left)),
        int(round(bottom - top)),
    ]


def scaled_bbox(
    raw_bbox: Any,
    scales: AxisScales,
    image_w: int,
    image_h: int,
) -> list[int] | None:
    xywh = _as_xywh(raw_bbox)
    if xywh is None:
        return None
    x, y, width, height = xywh
    return _clip_bbox(
        [x * scales.x, y * scales.y, width * scales.x, height * scales.y],
        image_w,
        image_h,
    )


def _text_boxes(source_items: Sequence[Any]) -> list[Any]:
    """Only compact text-like boxes are reliable ink evidence."""
    boxes: list[Any] = []
    for item in source_items:
        if not isinstance(item, Mapping):
            continue
        box = item.get("bbox")
        if not isinstance(box, Mapping):
            continue
        try:
            width = float(box.get("width") or 0)
            height = float(box.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        # A whole-page container is not a text ink probe.
        if width > 1400 or height > 200:
            continue
        boxes.append(box)
    return boxes


def infer_coordinate_space(
    source_items: Sequence[Any],
    image_w: int,
    image_h: int,
    ink_scorer: InkScorer | None,
) -> CoordinateSpaceDecision:
    """Choose the inverse transform best supported by reference pixels."""
    boxes = _text_boxes(source_items)
    fallback = CoordinateSpaceDecision(
        1.0,
        1.0,
        "no-ink-scorer",
        {"scoredBoxes": 0, "reason": "pixel-evidence-unavailable"},
    )
    if ink_scorer is None or len(boxes) < MIN_SCORED_BOXES:
        return fallback

    ranked: list[tuple[int, float, AxisScales]] = []
    for scales in candidate_scales(image_w, image_h):
        supports: list[float] = []
        for box in boxes:
            transformed = scaled_bbox(box, scales, image_w, image_h)
            if transformed is None:
                supports.append(0.0)
                continue
            try:
                supports.append(float(ink_scorer(transformed)))
            except (TypeError, ValueError, OSError):
                supports.append(0.0)
        supported = sum(1 for value in supports if value >= MIN_INK_SUPPORT)
        mean_support = sum(supports) / max(1, len(supports))
        ranked.append((supported, mean_support, scales))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    supported, mean_support, best = ranked[0]
    identity = next(item for item in ranked if item[2].label == "identity")
    evidence = {
        "scoredBoxes": len(boxes),
        "supportedBoxes": supported,
        "meanInkSupport": round(mean_support, 6),
        "identitySupportedBoxes": identity[0],
        "candidateScores": [
            {
                "label": scales.label,
                "supportedBoxes": count,
                "meanInkSupport": round(mean, 6),
            }
            for count, mean, scales in ranked
        ],
    }
    # Require a real improvement over identity before declaring a transform.
    if best.label != "identity" and (
        supported < MIN_SCORED_BOXES
        or supported <= identity[0]
        or mean_support <= identity[1]
    ):
        evidence["reason"] = "no-transform-outperforms-identity"
        return CoordinateSpaceDecision(1.0, 1.0, "identity", evidence)
    evidence["reason"] = "pixel-evidence-selected"
    return CoordinateSpaceDecision(best.x, best.y, best.label, evidence)


def resolve_bbox(
    raw_bbox: Any,
    decision: CoordinateSpaceDecision,
    image_w: int,
    image_h: int,
    ink_scorer: InkScorer | None,
) -> tuple[list[int] | None, str]:
    """Resolve one box, allowing per-item override for mixed-coordinate replies."""
    scales = AxisScales(decision.x_scale, decision.y_scale, decision.provenance)
    transformed = scaled_bbox(raw_bbox, scales, image_w, image_h)
    if ink_scorer is None or decision.provenance == "identity":
        return transformed, decision.provenance
    identity = scaled_bbox(
        raw_bbox, AxisScales(1.0, 1.0, "identity"), image_w, image_h
    )
    if transformed is None or identity is None:
        return transformed, decision.provenance
    # A box that is already in source pixels will overflow the canvas once the
    # normalized inverse transform is applied.  That is a stronger and cheaper
    # signal than ink support for large containers and backgrounds.
    xywh = _as_xywh(raw_bbox)
    if xywh is not None:
        x, y, width, height = xywh
        overflow = max(0.0, (x + width) * scales.x - image_w) + max(
            0.0, (y + height) * scales.y - image_h
        )
        if overflow > max(image_w, image_h) * 0.25:
            return identity, "identity-override-bounds"
    try:
        transformed_support = float(ink_scorer(transformed))
        identity_support = float(ink_scorer(identity))
    except (TypeError, ValueError, OSError):
        return transformed, decision.provenance
    # Prefer the globally selected transform unless identity is decisively
    # better.  A marginal difference usually means neighbouring content, not
    # a genuinely different coordinate space for this box.
    if (
        identity_support >= MIN_INK_SUPPORT
        and identity_support > transformed_support * 1.5 + 0.02
    ):
        return identity, "identity-override-ink"
    return transformed, decision.provenance


def build_ink_scorer(image_path: str | Path) -> InkScorer | None:
    """Build a source-pixel ink scorer from the shared perception primitive."""
    try:
        from src.app.services.structure.fidelity.perception_contract import (
            ink_support,
            load_reference_image,
        )

        image = load_reference_image(image_path)
    except (FileNotFoundError, ImportError, ValueError, OSError):
        return None

    def scorer(bbox: Sequence[Any]) -> float:
        measurement = ink_support(image, bbox)
        return float(measurement.get("inkSupport") or 0.0)

    return scorer


def legacy_axis_scales(
    raw_x_values: Sequence[float], image_w: int
) -> tuple[float, float, str]:
    """Deprecated compatibility path for callers without reference pixels.

    Kept only so existing parse-only tests and offline tooling keep their
    historical behaviour.  Real grounding calls always supply an image path and
    therefore use :func:`infer_coordinate_space`.
    """
    x_scale = (
        image_w / NORMALIZED_AXIS
        if image_w > NORMALIZED_AXIS
        and raw_x_values
        and max(raw_x_values) <= NORMALIZED_AXIS
        else 1.0
    )
    return x_scale, 1.0, "legacy-heuristic"


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
