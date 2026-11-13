"""Card-level containers recovered from painted borders.

Grounding reports the page skeleton (sidebar / header / main / card-grid) but
skips the repeated cards inside the grid, so the fixed-canvas compiler has no
parent to nest the card contents into and every Layout frame bails.  The
border detector already finds those card frames at 1px accuracy and needs no
OCR: it accepts the text boxes the model already produced.

This pass is additive and conservative.  A detected box becomes a container
only when it is a real layout box (holds at least two known elements), is not
a duplicate of an existing container, and is big enough to be a card rather
than a button.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.app.services.structure.graph import add_container

MIN_MEMBERS = 2
MIN_WIDTH = 120
MIN_HEIGHT = 56
MAX_AREA_RATIO = 0.92
DUPLICATE_IOU = 0.75
INNER_OUTER_IOU = 0.55
MAX_ADDED = 24

_MEMBER_TYPES = {
    "text",
    "link",
    "button",
    "input",
    "control",
    "image",
    "avatar",
    "icon-button",
}


def _iou(left: Sequence[int], right: Sequence[int]) -> float:
    ax, ay, aw, ah = (float(v) for v in left)
    bx, by, bw, bh = (float(v) for v in right)
    overlap_width = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    overlap_height = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    intersection = overlap_width * overlap_height
    if intersection <= 0:
        return 0.0
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def _pixel_bbox(item: Mapping[str, Any], width: int, height: int) -> list[int] | None:
    bbox = item.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        values = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    if max(values) <= 1.0 and min(values) >= 0.0:
        values = [
            values[0] * width,
            values[1] * height,
            values[2] * width,
            values[3] * height,
        ]
    x, y, box_width, box_height = (int(round(value)) for value in values)
    if box_width <= 0 or box_height <= 0:
        return None
    return [x, y, box_width, box_height]


def _member_count(box: Sequence[int], members: Sequence[Sequence[int]]) -> int:
    x, y, width, height = box
    count = 0
    for element in members:
        centre_x = element[0] + element[2] / 2
        centre_y = element[1] + element[3] / 2
        if x <= centre_x <= x + width and y <= centre_y <= y + height:
            count += 1
    return count


def _detector_minimums(width: int) -> dict[str, int]:
    """The package is calibrated for 2K screenshots; scale down for smaller ones."""
    if width >= 2400:
        return {"bridge_radius": 32, "min_w": 40, "min_h": 22}
    if width >= 1600:
        return {"bridge_radius": 24, "min_w": 30, "min_h": 15}
    return {"bridge_radius": 18, "min_w": 26, "min_h": 13}


def recover_border_containers(
    graph: Mapping[str, Any],
    image_path: str | Path,
    *,
    width: int,
    height: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Append card containers detected from the screenshot's painted borders."""
    recovered = copy.deepcopy(dict(graph))
    schema = "image-border-containers/1.0"
    base_report: dict[str, Any] = {
        "schema_version": schema,
        "source": "border-recovery:container_borders_v2_4",
    }

    try:
        from src.app.services.structure.providers.cv import (
            resolve_container_pipeline_root,
        )

        root = resolve_container_pipeline_root()
    except (ImportError, FileNotFoundError) as exc:
        return recovered, {
            **base_report,
            "status": "unavailable",
            "reason": str(exc),
            "added_count": 0,
            "added": [],
        }

    pipeline_path = str(root / "container_pipeline")
    if pipeline_path not in sys.path:
        sys.path.insert(0, pipeline_path)
    try:
        import cv2
        from container_borders_v2_4 import detect_boxes
    except ImportError as exc:
        return recovered, {
            **base_report,
            "status": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
            "added_count": 0,
            "added": [],
        }

    elements = [
        element
        for element in recovered.get("elements") or []
        if isinstance(element, Mapping)
        and str(element.get("type") or "").lower() in _MEMBER_TYPES
    ]
    member_boxes = [
        box
        for box in (_pixel_bbox(element, width, height) for element in elements)
        if box is not None
    ]
    text_boxes = [
        (box[0], box[1], box[0] + box[2], box[1] + box[3])
        for element, box in zip(elements, member_boxes)
        if str(element.get("type") or "").lower()
        in {"text", "link", "button", "input", "control"}
        and box[2] >= 4
        and box[3] >= 4
    ]

    image = cv2.imread(str(image_path))
    if image is None:
        return recovered, {
            **base_report,
            "status": "unreadable",
            "added_count": 0,
            "added": [],
        }
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    try:
        detected = detect_boxes(
            rgb,
            text_boxes=text_boxes or None,
            **_detector_minimums(width),
        )["boxes"]
    except Exception as exc:  # noqa: BLE001 - detector is optional enrichment
        return recovered, {
            **base_report,
            "status": "detector-failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "added_count": 0,
            "added": [],
        }

    existing = [
        box
        for box in (
            _pixel_bbox(container, width, height)
            for container in recovered.get("containers") or []
            if isinstance(container, Mapping)
        )
        if box is not None
    ]
    canvas_area = max(1, width * height)

    candidates: list[tuple[int, list[int]]] = []
    rejected: dict[str, int] = {"too-small": 0, "too-large": 0, "few-members": 0, "duplicate": 0}
    for box in detected:
        rectangle = [
            int(box.get("x") or 0),
            int(box.get("y") or 0),
            int(box.get("w") or 0),
            int(box.get("h") or 0),
        ]
        x, y, box_width, box_height = rectangle
        if box_width < MIN_WIDTH or box_height < MIN_HEIGHT:
            rejected["too-small"] += 1
            continue
        if box_width * box_height / canvas_area > MAX_AREA_RATIO:
            rejected["too-large"] += 1
            continue
        if _member_count(rectangle, member_boxes) < MIN_MEMBERS:
            rejected["few-members"] += 1
            continue
        if any(_iou(rectangle, other) > DUPLICATE_IOU for other in existing):
            rejected["duplicate"] += 1
            continue
        candidates.append((box_width * box_height, rectangle))

    # The detector reports both the inner and the outer edge of the same card;
    # keep the larger one and drop anything mostly inside it.
    candidates.sort(key=lambda item: item[0], reverse=True)
    accepted: list[list[int]] = []
    for _area, rectangle in candidates:
        if len(accepted) >= MAX_ADDED:
            break
        if any(_iou(rectangle, other) > INNER_OUTER_IOU for other in accepted):
            continue
        accepted.append(rectangle)

    if not accepted:
        return recovered, {
            **base_report,
            "status": "not-found",
            "detected": len(detected),
            "rejected": rejected,
            "added_count": 0,
            "added": [],
        }

    for index, rectangle in enumerate(accepted):
        add_container(
            recovered,
            rectangle,
            role="card",
            source="border-recovery:container_borders_v2_4",
            name=f"Card {index + 1}",
            confidence=0.8,
        )
    return recovered, {
        **base_report,
        "status": "applied",
        "detected": len(detected),
        "rejected": rejected,
        "added_count": len(accepted),
        "added": accepted,
        "limitations": [
            "Only closed 1px borders become containers; borderless cards rely on model containers.",
            "Nested card-in-card layouts may collapse to the outer box.",
        ],
    }
