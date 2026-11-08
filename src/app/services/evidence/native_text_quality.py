"""Measure native text and chrome separately without changing acceptance."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any


def _text_nodes(readback: Any) -> list[Mapping[str, Any]]:
    nodes: list[Mapping[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            if value.get("type") == "TEXT" and value.get("characters"):
                nodes.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(readback)
    return nodes


def _normalized_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, width, height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    return [x, y, width, height] if width > 0 and height > 0 else None


def _halo_bbox(
    bbox: list[int],
    halo_px: int,
    image_shape: tuple[int, int],
) -> list[int] | None:
    height, width = image_shape
    x, y, box_width, box_height = bbox
    left = max(0, x - halo_px)
    top = max(0, y - halo_px)
    right = min(width, x + box_width + halo_px)
    bottom = min(height, y + box_height + halo_px)
    if right <= left or bottom <= top:
        return None
    return [left, top, right - left, bottom - top]


def _contrast_mask(region: Any) -> Any:
    import numpy as np

    values = region.reshape(-1, 3)
    background = np.median(values, axis=0)
    return np.max(np.abs(region - background), axis=2) > 50


def _ink_bbox(mask: Any, bbox: list[int]) -> list[int] | None:
    import numpy as np

    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    x, y, _width, _height = bbox
    return [
        x + int(xs.min()),
        y + int(ys.min()),
        int(xs.max()) - int(xs.min()) + 1,
        int(ys.max()) - int(ys.min()) + 1,
    ]


def _edge_mask(mask: Any) -> Any:
    import numpy as np

    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    eroded = np.ones_like(mask, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            eroded &= padded[
                1 + dy : 1 + dy + mask.shape[0],
                1 + dx : 1 + dx + mask.shape[1],
            ]
    return mask & ~eroded


def _dilate(mask: Any) -> Any:
    import numpy as np

    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    output = np.zeros_like(mask, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            output |= padded[
                1 + dy : 1 + dy + mask.shape[0],
                1 + dx : 1 + dx + mask.shape[1],
            ]
    return output


def _edge_f1(reference_mask: Any, rendered_mask: Any) -> float | None:
    reference_edge = _edge_mask(reference_mask)
    rendered_edge = _edge_mask(rendered_mask)
    if not reference_edge.any() and not rendered_edge.any():
        return 1.0
    if not reference_edge.any() or not rendered_edge.any():
        return 0.0
    matched_reference = reference_edge & _dilate(rendered_edge)
    matched_rendered = rendered_edge & _dilate(reference_edge)
    precision = float(matched_rendered.sum()) / float(rendered_edge.sum())
    recall = float(matched_reference.sum()) / float(reference_edge.sum())
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _mask_edge_f1(
    reference_mask: Any,
    rendered_mask: Any,
    reference_ink: list[int],
    rendered_ink: list[int],
    origin: tuple[int, int],
) -> float | None:
    union_x = min(reference_ink[0], rendered_ink[0])
    union_y = min(reference_ink[1], rendered_ink[1])
    union_right = max(
        reference_ink[0] + reference_ink[2],
        rendered_ink[0] + rendered_ink[2],
    )
    union_bottom = max(
        reference_ink[1] + reference_ink[3],
        rendered_ink[1] + rendered_ink[3],
    )
    x, y = origin
    return _edge_f1(
        reference_mask[
            union_y - y : union_bottom - y,
            union_x - x : union_right - x,
        ],
        rendered_mask[
            union_y - y : union_bottom - y,
            union_x - x : union_right - x,
        ],
    )


def _region_mask(shape: tuple[int, int], bbox: list[int]) -> Any:
    import numpy as np

    mask = np.zeros(shape, dtype=bool)
    x, y, width, height = bbox
    mask[
        max(0, y) : min(shape[0], y + height),
        max(0, x) : min(shape[1], x + width),
    ] = True
    return mask


def _number(value: Any, default: float) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_gate_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _critical_text_matches(expected: Any, actual: Any) -> bool:
    expected_text = _normalize_gate_text(expected)
    actual_text = _normalize_gate_text(actual)
    if not expected_text or not actual_text:
        return False
    if expected_text in actual_text:
        return True
    if any("\u4e00" <= char <= "\u9fff" for char in expected_text):
        compact_expected = re.sub(r"\s+", "", expected_text)
        compact_actual = re.sub(r"\s+", "", actual_text)
        return compact_expected in compact_actual
    return False


def _boxes_adjacent(
    left: Sequence[int],
    right: Sequence[int],
    *,
    max_gap_px: int,
) -> bool:
    """Whether two ink boxes are close enough to form one logical label."""
    left_x, left_y, left_width, left_height = left
    right_x, right_y, right_width, right_height = right
    horizontal_gap = max(
        right_x - (left_x + left_width),
        left_x - (right_x + right_width),
    )
    vertical_gap = max(
        right_y - (left_y + left_height),
        left_y - (right_y + right_height),
    )
    vertical_overlap = min(
        left_y + left_height,
        right_y + right_height,
    ) - max(left_y, right_y)
    horizontal_overlap = min(
        left_x + left_width,
        right_x + right_width,
    ) - max(left_x, right_x)
    same_line = horizontal_gap <= max_gap_px and vertical_overlap >= max(
        1, min(left_height, right_height) // 2
    )
    stacked = vertical_gap <= max_gap_px and horizontal_overlap >= max(
        1, min(left_width, right_width) // 2
    )
    return same_line or stacked


def _cluster_is_adjacent(
    indexes: Sequence[int],
    owners: Sequence[Mapping[str, Any]],
    *,
    max_gap_px: int,
) -> bool:
    boxes = [owners[index].get("referenceInkBBox") for index in indexes]
    if any(not isinstance(box, Sequence) or len(box) != 4 for box in boxes):
        return False
    count = len(indexes)
    adjacency: list[list[int]] = [[] for _ in range(count)]
    for left in range(count):
        for right in range(left + 1, count):
            if _boxes_adjacent(boxes[left], boxes[right], max_gap_px=max_gap_px):
                adjacency[left].append(right)
                adjacency[right].append(left)
    visited: set[int] = set()
    stack = [0]
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(adjacency[node])
    return len(visited) == count


def _logical_cluster_for_expected(
    expected: Any,
    owners: Sequence[Mapping[str, Any]],
    *,
    exclude: set[int],
    max_cluster_size: int = 4,
    max_gap_px: int = 8,
) -> list[int] | None:
    """Find adjacent native owners whose concatenated text equals ``expected``."""
    expected_text = _normalize_gate_text(expected)
    if not expected_text:
        return None
    candidates = [
        index
        for index, owner in enumerate(owners)
        if index not in exclude
        and owner.get("nativeText")
        and _normalize_gate_text(owner.get("text"))
        and isinstance(owner.get("referenceInkBBox"), Sequence)
        and len(owner["referenceInkBBox"]) == 4
    ]
    compact_expected = re.sub(r"\s+", "", expected_text)
    for size in range(2, min(max_cluster_size, len(candidates)) + 1):
        for combo in combinations(candidates, size):
            if not _cluster_is_adjacent(
                combo,
                owners,
                max_gap_px=max_gap_px,
            ):
                continue
            ordered = sorted(
                combo,
                key=lambda index: (
                    owners[index]["referenceInkBBox"][1],
                    owners[index]["referenceInkBBox"][0],
                ),
            )
            combined = "".join(
                _normalize_gate_text(owners[index]["text"]) for index in ordered
            )
            if re.sub(r"\s+", "", combined) == compact_expected:
                return list(ordered)
    return None


def _unmeasurable_owner(
    element: Mapping[str, Any],
    text: str,
    native_characters: set[str],
    reason: str,
) -> dict[str, Any]:
    """Register native copy that exists but cannot be measured.

    Deliberately omits ``checks`` so the owner is never mistaken for a
    measured one, and uses a non-``pass`` status so it can never satisfy the
    gate.  ``nativeText`` comes from the readback tree, not from a guess.
    """
    return {
        "contentRef": element.get("contentRef"),
        "text": text,
        "type": element.get("type"),
        "nativeText": text in native_characters,
        "ownerScope": "diagnostic-only",
        "status": "unmeasurable-missing-evidence",
        "registrationReason": reason,
        "registrationSource": "inventory-emission-contract/1.0",
        "baseline": "unknown",
    }


def _evaluate_native_text_gate(
    owners: Sequence[Mapping[str, Any]],
    chrome_regions: Sequence[Mapping[str, Any]],
    *,
    critical_texts: Sequence[str],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    critical = list(
        dict.fromkeys(
            str(value).strip() for value in critical_texts if str(value).strip()
        )
    )
    matched_owner_indexes: set[int] = set()
    missing_critical: list[str] = []
    logical_clusters: list[dict[str, Any]] = []
    for expected in critical:
        matches = [
            index
            for index, owner in enumerate(owners)
            if _critical_text_matches(expected, owner.get("text"))
        ]
        if matches:
            matched_owner_indexes.update(matches)
            continue
        cluster = _logical_cluster_for_expected(
            expected,
            owners,
            exclude=matched_owner_indexes,
        )
        if cluster is not None:
            matched_owner_indexes.update(cluster)
            logical_clusters.append(
                {
                    "text": expected,
                    "ownerRefs": [
                        str(owners[index].get("contentRef") or f"owner-{index}")
                        for index in cluster
                    ],
                }
            )
            continue
        missing_critical.append(expected)
    if critical:
        scope_indexes = sorted(matched_owner_indexes)
        scope = "critical-text-owners"
    else:
        scope_indexes = [
            index for index, owner in enumerate(owners) if "checks" in owner
        ]
        scope = "all-measured-owners"
    scoped_indexes = set(scope_indexes)
    owner_scope = "critical-gate" if critical else "all-measured-gate"
    for index, owner in enumerate(owners):
        owner["ownerScope"] = (
            owner_scope if index in scoped_indexes else "diagnostic-only"
        )

    text_blockers: list[str] = []
    for expected in missing_critical:
        text_blockers.append(f"native-text:missing:{expected}")
    for index in scope_indexes:
        owner = owners[index]
        owner_ref = str(owner.get("contentRef") or f"owner-{index}")
        if not owner.get("nativeText"):
            text_blockers.append(f"native-text:not-native:{owner_ref}")
            continue
        if owner.get("status") != "pass":
            text_blockers.append(f"native-text:owner:{owner_ref}")
    baseline_required = bool(policy.get("native_text_baseline_required", False))
    baseline_evidence_count = sum(
        owner.get("baseline") not in {None, "", "unknown"} for owner in owners
    )
    baseline_status = "pass" if baseline_evidence_count else "not-evaluated"
    if baseline_required and not baseline_evidence_count:
        text_blockers.append("native-text:baseline-evidence")
    if not owners:
        text_blockers.append("native-text:missing")
    text_blockers = list(dict.fromkeys(text_blockers))

    chrome_threshold = _number(
        policy.get("chrome_bad_pixel_ratio_max"),
        0.05,
    )
    chrome_blockers: list[str] = []
    if not chrome_regions:
        chrome_blockers.append("chrome-visual:missing")
    for region in chrome_regions:
        region_id = str(region.get("id") or region.get("role") or "unknown")
        ratio = _number(region.get("chromeBadPixelRatio"), 1.0)
        if ratio > chrome_threshold or region.get("status") == "fail":
            chrome_blockers.append(f"chrome-visual:{region_id}")
    chrome_blockers = list(dict.fromkeys(chrome_blockers))
    blockers = list(dict.fromkeys([*text_blockers, *chrome_blockers]))

    text_pass_count = sum(
        owners[index].get("nativeText") and owners[index].get("status") == "pass"
        for index in scope_indexes
    )
    owner_refs = [
        str(owners[index].get("contentRef") or f"owner-{index}")
        for index in scope_indexes
    ]
    return {
        "schema_version": "grounding-native-text-gate/2.0",
        "status": "fail" if blockers else "pass",
        "scope": scope,
        "thresholds": {
            "chromeBadPixelRatioMax": chrome_threshold,
            "positionPxMax": _number(
                policy.get("native_text_position_px_max"),
                1.0,
            ),
            "inkCoverageRatioMin": _number(
                policy.get("native_text_ink_coverage_min"),
                0.90,
            ),
            "inkCoverageRatioMax": _number(
                policy.get("native_text_ink_coverage_max"),
                1.10,
            ),
            "edgeF1Min": _number(policy.get("native_text_edge_f1_min"), 0.95),
        },
        "criticalText": {
            "requiredCount": len(critical),
            "matchedCount": len(critical) - len(missing_critical),
            "missing": missing_critical,
            "logicalClusters": logical_clusters,
        },
        "nativeText": {
            "status": "fail" if text_blockers else "pass",
            "ownerCount": len(scope_indexes),
            "ownerPassCount": int(text_pass_count),
            "ownerPassRatio": (
                float(text_pass_count) / float(len(scope_indexes))
                if scope_indexes
                else 0.0
            ),
            "ownerRefs": owner_refs,
            "unscopedOwnerCount": len(owners) - len(scope_indexes),
            "blockers": text_blockers,
        },
        "chrome": {
            "status": "fail" if chrome_blockers else "pass",
            "regionCount": len(chrome_regions),
            "blockers": chrome_blockers,
        },
        "baseline": {
            "status": baseline_status,
            "required": baseline_required,
            "evidenceCount": baseline_evidence_count,
        },
        "blockers": blockers,
    }


def build_native_text_quality(
    design: Mapping[str, Any],
    readback_tree: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
    regions: list[Mapping[str, Any]],
    *,
    halo_px: int = 2,
    bad_pixel_threshold: int = 30,
    gate_policy: Mapping[str, Any] | None = None,
    critical_texts: Sequence[str] | None = None,
    register_unmeasured_owners: bool = False,
) -> dict[str, Any]:
    """Build diagnostic text/chrome metrics; never changes acceptance status.

    ``register_unmeasured_owners`` is an opt-in emission-contract repair.  By
    default an element without measurable ink evidence is silently skipped, so
    critical-text matching treats existing native copy as absent.  When
    enabled, such elements are registered with an explicit ``unmeasurable-
    missing-evidence`` status instead.  They are never counted as passing.
    """
    import numpy as np
    from PIL import Image

    with Image.open(reference_path) as source:
        reference = np.asarray(source.convert("RGB"), dtype=np.int16)
    with Image.open(rendered_path) as source:
        rendered = np.asarray(source.convert("RGB"), dtype=np.int16)
    if reference.shape != rendered.shape:
        raise ValueError("reference and rendered image sizes must match")
    height, width = reference.shape[:2]
    bad = np.max(np.abs(reference - rendered), axis=2) > bad_pixel_threshold
    gate_enabled = isinstance(gate_policy, Mapping)
    policy = gate_policy if gate_enabled else {}
    position_max = _number(policy.get("native_text_position_px_max"), 1.0)
    width_ratio = _number(
        policy.get("native_text_width_tolerance_ratio"),
        0.02,
    )
    width_floor = int(_number(policy.get("native_text_width_tolerance_floor_px"), 2.0))
    height_ratio = _number(
        policy.get("native_text_height_tolerance_ratio"),
        0.02,
    )
    height_floor = int(
        _number(policy.get("native_text_height_tolerance_floor_px"), 2.0)
    )
    coverage_min = _number(policy.get("native_text_ink_coverage_min"), 0.90)
    coverage_max = _number(policy.get("native_text_ink_coverage_max"), 1.10)
    edge_min = _number(policy.get("native_text_edge_f1_min"), 0.95)
    chrome_threshold = _number(
        policy.get("chrome_bad_pixel_ratio_max"),
        0.05,
    )
    native_characters = {
        str(node.get("characters") or "") for node in _text_nodes(readback_tree)
    }
    text_mask = np.zeros((height, width), dtype=bool)
    owners: list[dict[str, Any]] = []
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        text = str(element.get("text") or element.get("controlValue") or "")
        if not text or str(element.get("type") or "") == "image":
            continue
        evidence = element.get("styleEvidence")
        values = evidence.get("evidence") if isinstance(evidence, Mapping) else None
        if not isinstance(values, Mapping):
            if register_unmeasured_owners:
                owners.append(
                    _unmeasurable_owner(
                        element, text, native_characters, "missing-style-evidence"
                    )
                )
            continue
        source_bbox = _normalized_bbox(values.get("source_bbox"))
        reference_ink = _normalized_bbox(values.get("ink_bbox"))
        if source_bbox is None or reference_ink is None:
            if register_unmeasured_owners:
                owners.append(
                    _unmeasurable_owner(
                        element, text, native_characters, "missing-ink-evidence"
                    )
                )
            continue
        x, y, box_width, box_height = source_bbox
        source_region = rendered[y : y + box_height, x : x + box_width]
        reference_region = reference[y : y + box_height, x : x + box_width]
        rendered_mask = _contrast_mask(source_region)
        reference_mask = _contrast_mask(reference_region)
        rendered_ink = _ink_bbox(rendered_mask, source_bbox)
        if rendered_ink is None:
            owners.append(
                {
                    "contentRef": element.get("contentRef"),
                    "text": text,
                    "nativeText": text in native_characters,
                    "ownerScope": "diagnostic-only",
                    "status": "failed-missing-rendered-ink",
                }
            )
            continue
        delta_x = rendered_ink[0] - reference_ink[0]
        delta_y = rendered_ink[1] - reference_ink[1]
        width_tolerance = max(
            width_floor,
            int(round(reference_ink[2] * width_ratio)),
        )
        height_tolerance = max(
            height_floor,
            int(round(reference_ink[3] * height_ratio)),
        )
        height_delta = rendered_ink[3] - reference_ink[3]
        width_delta = rendered_ink[2] - reference_ink[2]
        source_reference_pixels = int(reference_mask.sum())
        source_rendered_pixels = int(rendered_mask.sum())
        source_coverage = (
            float(source_rendered_pixels) / float(source_reference_pixels)
            if source_reference_pixels
            else None
        )
        source_edge_f1 = _mask_edge_f1(
            reference_mask,
            rendered_mask,
            reference_ink,
            rendered_ink,
            (x, y),
        )
        support_bbox = _halo_bbox(reference_ink, halo_px, (height, width))
        if support_bbox is None:
            support_coverage = None
            support_edge_f1 = None
            support_reference_ink = None
            support_rendered_ink = None
        else:
            support_x, support_y, support_width, support_height = support_bbox
            support_reference_region = reference[
                support_y : support_y + support_height,
                support_x : support_x + support_width,
            ]
            support_rendered_region = rendered[
                support_y : support_y + support_height,
                support_x : support_x + support_width,
            ]
            support_reference_mask = _contrast_mask(support_reference_region)
            support_rendered_mask = _contrast_mask(support_rendered_region)
            support_reference_ink = _ink_bbox(support_reference_mask, support_bbox)
            support_rendered_ink = _ink_bbox(support_rendered_mask, support_bbox)
            support_reference_pixels = int(support_reference_mask.sum())
            support_rendered_pixels = int(support_rendered_mask.sum())
            support_coverage = (
                float(support_rendered_pixels) / float(support_reference_pixels)
                if support_reference_pixels
                else None
            )
            support_edge_f1 = (
                _mask_edge_f1(
                    support_reference_mask,
                    support_rendered_mask,
                    support_reference_ink,
                    support_rendered_ink,
                    (support_x, support_y),
                )
                if support_reference_ink is not None
                and support_rendered_ink is not None
                else None
            )
        geometry_checks = {
            "position": abs(delta_x) <= position_max and abs(delta_y) <= position_max,
            "size": abs(width_delta) <= width_tolerance
            and abs(height_delta) <= height_tolerance,
            "coverage": support_coverage is not None
            and coverage_min <= support_coverage <= coverage_max,
            "edgeF1": support_edge_f1 is not None and support_edge_f1 >= edge_min,
        }
        owners.append(
            {
                "contentRef": element.get("contentRef"),
                "text": text,
                "type": element.get("type"),
                "nativeText": text in native_characters,
                "ownerScope": "diagnostic-only",
                "referenceInkBBox": reference_ink,
                "renderedInkBBox": rendered_ink,
                "deltaX": delta_x,
                "deltaY": delta_y,
                "widthDelta": width_delta,
                "heightDelta": height_delta,
                "widthTolerance": width_tolerance,
                "heightTolerance": height_tolerance,
                "metricsBasis": "reference-ink-halo",
                "supportBBox": support_bbox,
                "supportReferenceInkBBox": support_reference_ink,
                "supportRenderedInkBBox": support_rendered_ink,
                "sourceCoverageRatio": source_coverage,
                "sourceEdgeF1": source_edge_f1,
                "inkCoverageRatio": support_coverage,
                "edgeF1": support_edge_f1,
                "baseline": "unknown",
                "checks": geometry_checks,
                "geometryStatus": ("pass" if all(geometry_checks.values()) else "fail"),
                "status": (
                    "pass"
                    if text in native_characters
                    and geometry_checks["position"]
                    and geometry_checks["size"]
                    and geometry_checks["coverage"]
                    and geometry_checks["edgeF1"]
                    else "fail"
                ),
            }
        )
        mask_x = max(0, reference_ink[0] - halo_px)
        mask_y = max(0, reference_ink[1] - halo_px)
        mask_right = min(width, reference_ink[0] + reference_ink[2] + halo_px)
        mask_bottom = min(height, reference_ink[1] + reference_ink[3] + halo_px)
        text_mask[mask_y:mask_bottom, mask_x:mask_right] = True
    chrome_regions = []
    for region in regions:
        bbox = _normalized_bbox(region.get("bbox"))
        if bbox is None:
            continue
        region_mask = _region_mask((height, width), bbox)
        chrome_mask = region_mask & ~text_mask
        pixel_count = int(chrome_mask.sum())
        bad_count = int((bad & chrome_mask).sum())
        chrome_regions.append(
            {
                "id": str(region.get("id") or region.get("role") or ""),
                "role": str(region.get("role") or ""),
                "bbox": bbox,
                "chromePixelCount": pixel_count,
                "chromeBadPixelCount": bad_count,
                "chromeBadPixelRatio": (
                    float(bad_count) / float(pixel_count) if pixel_count else None
                ),
                "status": (
                    "pass"
                    if pixel_count
                    and float(bad_count) / float(pixel_count) <= chrome_threshold
                    else "fail"
                ),
            }
        )
    measured = [owner for owner in owners if "checks" in owner]
    summary = {
        "ownerCount": len(owners),
        "nativeTextCount": sum(bool(owner.get("nativeText")) for owner in owners),
        "positionPassCount": sum(
            bool(owner.get("checks", {}).get("position")) for owner in owners
        ),
        "sizePassCount": sum(
            bool(owner.get("checks", {}).get("size")) for owner in owners
        ),
        "coveragePassCount": sum(
            bool(owner.get("checks", {}).get("coverage")) for owner in owners
        ),
        "edgeF1PassCount": sum(
            bool(owner.get("checks", {}).get("edgeF1")) for owner in owners
        ),
        "baselineEvidenceCount": 0,
        "measuredOwnerCount": len(measured),
    }
    proposed_text_gate = {
        "positionPxMax": position_max,
        "widthErrorPxMax": f"max({width_floor}, {width_ratio:.0%} reference width)",
        "heightErrorPxMax": f"max({height_floor}, {height_ratio:.0%} reference height)",
        "inkCoverageRatioMin": coverage_min,
        "inkCoverageRatioMax": coverage_max,
        "edgeF1Min": edge_min,
        "baselinePxMax": 1,
    }
    report = {
        "schema_version": (
            "grounding-native-text-quality/2.0"
            if gate_enabled
            else "grounding-native-text-quality/1.0"
        ),
        "status": ("measured-gate" if gate_enabled else "measured-diagnostic-only"),
        "acceptance_effect": (
            "native-text-and-chrome-gate" if gate_enabled else "none"
        ),
        "haloPx": halo_px,
        "badPixelThreshold": bad_pixel_threshold,
        "summary": summary,
        "owners": owners,
        "chromeRegions": chrome_regions,
        "proposedTextGate": proposed_text_gate,
        "limitations": [
            "Baseline evidence is unavailable for every owner in this diagnostic.",
            (
                "Native text and chrome use independent quality gates in policy 2.0."
                if gate_enabled
                else "Native text/chrome split metrics do not change the frozen raw acceptance."
            ),
            "Reference ink masks are screenshot-derived candidates, not original glyph outlines.",
        ],
    }
    if gate_enabled:
        report["gate"] = _evaluate_native_text_gate(
            owners,
            chrome_regions,
            critical_texts=critical_texts or [],
            policy=policy,
        )
    return report
