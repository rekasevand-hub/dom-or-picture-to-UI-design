"""Make the OCR line box the geometric authority for every text owner.

The model names what is on screen; it cannot measure where.  On a 1920px
screenshot its normalised boxes drift 10-40px and often span two columns, so a
title from the left card starts inside the right one and no container tree can
be built from it.

This stage implements the geometry-first half of the agreed split:

1. Every text owner is matched against the OCR lines that read the same string
   (similarity >= 0.65, or one containing the other).  On a match the owner
   keeps its meaning but takes the OCR line's pixel box -- ``textBoxAuthority``
   records that the geometry is no longer the model's.
2. A block-shaped owner that swallows two or more independent text owners is a
   region label, not a line of copy; it is dropped so its children survive.
3. Whatever overlap survives is resolved by non-maximum suppression, keeping
   the owner with measured geometry.

Nothing here renames visible copy: the model's wording wins unless the OCR line
contains it and is longer (``yx`` -> ``astryx``).
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from src.app.services.structure.fidelity.contracts import (
    normalize_match_text,
    owner_text_similarity,
)

MATCH_SIMILARITY = 0.65
MAX_CENTER_DISTANCE = 60
NMS_IOU = 0.55
SWALLOW_MIN_CHILDREN = 2
SWALLOW_HEIGHT_RATIO = 1.8

_TEXT_TYPES = {"text", "link", "button", "input", "control"}


def _bbox_of(item: Mapping[str, Any]) -> list[int] | None:
    bbox = item.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        values = [int(round(float(value))) for value in bbox]
    except (TypeError, ValueError):
        return None
    if values[2] <= 0 or values[3] <= 0:
        return None
    return values


def _center(box: Sequence[int]) -> tuple[float, float]:
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def _center_distance(left: Sequence[int], right: Sequence[int]) -> float:
    lx, ly = _center(left)
    rx, ry = _center(right)
    return ((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5


def _iou(left: Sequence[int], right: Sequence[int]) -> float:
    ax, ay, aw, ah = (float(v) for v in left)
    bx, by, bw, bh = (float(v) for v in right)
    overlap_w = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    overlap_h = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    intersection = overlap_w * overlap_h
    if intersection <= 0:
        return 0.0
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def _contains(outer: Sequence[int], inner: Sequence[int], margin: int = 4) -> bool:
    return (
        outer[0] - margin <= inner[0]
        and outer[1] - margin <= inner[1]
        and inner[0] + inner[2] <= outer[0] + outer[2] + margin
        and inner[1] + inner[3] <= outer[1] + outer[3] + margin
    )


def _substring_pair(left: str, right: str) -> bool:
    a = normalize_match_text(left)
    b = normalize_match_text(right)
    if not a or not b:
        return False
    return a in b or b in a


def _ocr_wording_is_better(model_text: str, ocr_text: str) -> bool:
    """Take the OCR wording only when it strictly extends the model's."""
    model = normalize_match_text(model_text)
    ocr = normalize_match_text(ocr_text)
    if not model or not ocr or model == ocr:
        return False
    if model in ocr:
        return True
    return False


def _text_owners(elements: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        element
        for element in elements
        if str(element.get("type") or "").lower() in _TEXT_TYPES
        and str(element.get("text") or "").strip()
        and _bbox_of(element) is not None
    ]


def _container_key(
    box: Sequence[int],
    containers: Sequence[Mapping[str, Any]],
) -> tuple[int, int, int, int] | None:
    """Innermost container holding the box centre, identified by its geometry.

    Container ids are assigned later in the pipeline, so the bbox doubles as
    the identity here.
    """
    cx, cy = _center(box)
    best: tuple[int, int, int, int] | None = None
    best_area: int | None = None
    for container in containers:
        candidate = _bbox_of(container)
        if candidate is None:
            continue
        if not (
            candidate[0] <= cx <= candidate[0] + candidate[2]
            and candidate[1] <= cy <= candidate[1] + candidate[3]
        ):
            continue
        area = candidate[2] * candidate[3]
        if best_area is None or area < best_area:
            best, best_area = tuple(candidate), area
    return best


def _best_ocr_match(
    element: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    used: set[int],
    containers: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Pick the OCR line that reads the same string.

    Proximity is an OR with co-membership, not an AND: when the model drops a
    title into the wrong column the centre distance is meaningless, but both
    boxes still sit inside the same card.
    """
    text = str(element.get("text") or "")
    box = _bbox_of(element)
    if box is None:
        return None
    own_container = _container_key(box, containers)
    best: Mapping[str, Any] | None = None
    best_score = 0.0
    for observation in observations:
        if id(observation) in used:
            continue
        candidate_text = str(observation.get("text") or "")
        candidate_box = _bbox_of(observation)
        if not candidate_text or candidate_box is None:
            continue
        similarity = owner_text_similarity(text, candidate_text)
        contains = _substring_pair(text, candidate_text)
        if similarity < MATCH_SIMILARITY and not contains:
            continue
        distance = _center_distance(box, candidate_box)
        same_container = (
            own_container is not None
            and _container_key(candidate_box, containers) == own_container
        )
        if distance > MAX_CENTER_DISTANCE and not same_container:
            continue
        # Same-container matches still prefer the closest line.
        score = max(similarity, 0.7 if contains else 0.0) - distance / 800.0
        if same_container:
            score += 0.15
        if score > best_score:
            best, best_score = observation, score
    return best


def _swallowing_blocks(owners: Sequence[Mapping[str, Any]]) -> set[int]:
    """Indices of block-shaped owners that contain several real text owners."""
    boxes = [_bbox_of(owner) for owner in owners]
    heights = sorted(box[3] for box in boxes if box is not None)
    if not heights:
        return set()
    median_height = heights[len(heights) // 2]
    threshold = max(24.0, median_height * SWALLOW_HEIGHT_RATIO)
    flagged: set[int] = set()
    for index, box in enumerate(boxes):
        if box is None or box[3] < threshold:
            continue
        inside = [
            other
            for other_index, other in enumerate(boxes)
            if other is not None
            and other_index != index
            and _contains(box, other)
        ]
        if len(inside) >= SWALLOW_MIN_CHILDREN:
            flagged.add(index)
    return flagged


def _nms_victims(owners: Sequence[Mapping[str, Any]]) -> set[int]:
    """Drop the weaker owner of every high-overlap pair."""
    ranked = sorted(
        range(len(owners)),
        key=lambda index: (
            1 if owners[index].get("textBoxAuthority") == "ocr-line" else 0,
            -(_bbox_of(owners[index]) or [0, 0, 1, 1])[2]
            * (_bbox_of(owners[index]) or [0, 0, 1, 1])[3],
            len(normalize_match_text(owners[index].get("text"))),
        ),
        reverse=True,
    )
    kept: list[int] = []
    victims: set[int] = set()
    for index in ranked:
        box = _bbox_of(owners[index])
        if box is None:
            continue
        if any(
            _iou(box, _bbox_of(owners[other]) or [0, 0, 0, 0]) >= NMS_IOU
            for other in kept
        ):
            victims.add(index)
            continue
        kept.append(index)
    return victims


def _contained_fragments(owners: Sequence[Mapping[str, Any]]) -> set[int]:
    """Indices of owners whose text is a fragment of a longer owner above it.

    OCR reads a wrapped paragraph one line at a time while the model returns
    the whole string.  Both survive: the full paragraph renders, then the
    second OCR line renders on top of it.  A shorter text whose box sits inside
    a longer text's box is that fragment, and the complete copy wins.
    """
    boxes = [_bbox_of(owner) for owner in owners]
    texts = [normalize_match_text(owner.get("text")) for owner in owners]
    doomed: set[int] = set()
    for index, box in enumerate(boxes):
        if box is None or not texts[index]:
            continue
        for other_index, other_box in enumerate(boxes):
            if other_index == index or other_index in doomed or other_box is None:
                continue
            other_text = texts[other_index]
            if len(other_text) <= len(texts[index]):
                continue
            # Substring matching is too strict: OCR reads "AI" as "Al" and the
            # fragment then looks unrelated.  Compare character coverage.
            mine = set(texts[index])
            theirs = set(other_text)
            if not mine:
                continue
            if len(mine & theirs) / len(mine) < 0.85:
                continue
            overlap_w = min(
                box[0] + box[2], other_box[0] + other_box[2]
            ) - max(box[0], other_box[0])
            overlap_h = min(
                box[1] + box[3], other_box[1] + other_box[3]
            ) - max(box[1], other_box[1])
            if overlap_w <= 0 or overlap_h <= 0:
                continue
            covered = (overlap_w * overlap_h) / max(1, box[2] * box[3])
            if covered >= 0.6:
                doomed.add(index)
                break
    return doomed


def apply_text_geometry_authority(
    graph: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
    *,
    width: int,
    height: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Adopt OCR pixel boxes for matched text owners, then dedupe overlaps."""
    del width, height  # boxes are already in source pixels
    resolved = copy.deepcopy(dict(graph))
    schema = "text-geometry-authority/1.0"
    ocr_lines = [
        dict(observation)
        for observation in observations
        if isinstance(observation, Mapping)
        and str(observation.get("text") or "").strip()
        and _bbox_of(observation) is not None
    ]
    elements = resolved.get("elements")
    if not isinstance(elements, list):
        return resolved, {
            "schema_version": schema,
            "status": "not-needed",
            "ocr_lines": len(ocr_lines),
            "snapped": 0,
            "rewritten": 0,
            "dropped_blocks": 0,
            "nms_dropped": 0,
        }

    owners = _text_owners(elements)
    containers = [
        container
        for container in resolved.get("containers") or []
        if isinstance(container, Mapping)
    ]
    used: set[int] = set()
    snapped = 0
    rewritten = 0
    for owner in owners:
        match = _best_ocr_match(owner, ocr_lines, used, containers)
        if match is None:
            continue
        used.add(id(match))
        owner["bbox"] = list(_bbox_of(match) or owner["bbox"])
        owner["textBoxAuthority"] = "ocr-line"
        owner["ocrConfidence"] = round(float(match.get("confidence") or 0.0), 4)
        if _ocr_wording_is_better(
            str(owner.get("text") or ""), str(match.get("text") or "")
        ):
            owner["text"] = str(match.get("text") or "")
            rewritten += 1
        snapped += 1

    # Recompute owners: the snap above changed boxes, not membership.
    owners = _text_owners(elements)
    fragments = _contained_fragments(owners)
    swallow = _swallowing_blocks(
        [owner for index, owner in enumerate(owners) if index not in fragments]
    )
    surviving = [
        owner
        for index, owner in enumerate(owners)
        if index not in fragments and index not in swallow
    ]
    # ``_swallowing_blocks`` indexes the filtered list; map back to real owners.
    swallowed_owners = [
        owner for index, owner in enumerate(owners) if index not in fragments
    ]
    nms = _nms_victims(surviving)

    doomed_ids: set[int] = {id(owners[index]) for index in fragments}
    doomed_ids.update(
        id(swallowed_owners[index]) for index in swallow
    )
    doomed_ids.update(id(surviving[index]) for index in nms)

    dropped_blocks = len(swallow)
    nms_dropped = len(nms) + len(fragments)
    if doomed_ids:
        resolved["elements"] = [
            element for element in elements if id(element) not in doomed_ids
        ]

    return resolved, {
        "schema_version": schema,
        "status": "applied" if (snapped or doomed_ids) else "not-needed",
        "ocr_lines": len(ocr_lines),
        "snapped": snapped,
        "rewritten": rewritten,
        "dropped_blocks": dropped_blocks,
        "nms_dropped": nms_dropped,
        "dropped_fragments": len(fragments),
        "matched_lines_used": len(used),
        "policy": {
            "match_similarity": MATCH_SIMILARITY,
            "max_center_distance": MAX_CENTER_DISTANCE,
            "nms_iou": NMS_IOU,
            "wording": "model-wins-unless-ocr-extends-it",
        },
    }
