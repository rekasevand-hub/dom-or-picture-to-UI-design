"""Input-adaptive perception contract for the Grounding image pipeline.

The contract answers one question that the legacy pipeline never asked:

    Does every proposed native text box actually contain ink in the
    reference screenshot?

The legacy ``style_resolver`` used a single global contrast threshold and
trusted VLM bboxes verbatim.  VLM backends may answer in a 0..1000
normalized space; ``parse_vlm_json`` scales only the x axis, so on tall /
high-DPR screenshots the y axis drifts linearly and lower text boxes land
on empty background.  Those elements lose ``styleEvidence.ink_bbox`` and are
silently dropped from the native-text owner set, which turns a geometry bug
into a false ``native-text:missing:<text>`` acceptance blocker.

This module is deliberately *additive*: it only repairs boxes whose ink
support under the legacy rule is zero.  Verified boxes are never touched, so
a previously calibrated sample cannot regress.  It is truth-independent: it
uses only the reference pixels and (optionally) the OCR observations already
produced by the pipeline.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "grounding-perception-contract/1.0"

# Legacy resolve_text_style threshold.  A box with zero support here is the
# exact population the legacy code silently degraded.
LEGACY_CONTRAST_THRESHOLD = 24.0
MIN_INK_PIXELS = 2
MIN_INK_SUPPORT = 0.01
DEFAULT_DRIFT_THRESHOLD = 0.20
NORMALIZED_AXIS = 1000.0


def _hex_color(values: Sequence[float]) -> str:
    red, green, blue = (
        max(0, min(255, int(round(float(value))))) for value in list(values)[:3]
    )
    return f"#{red:02x}{green:02x}{blue:02x}"


def _has_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def _clean_bbox(
    bbox: Sequence[Any], width: int, height: int
) -> tuple[int, int, int, int] | None:
    try:
        x, y, box_width, box_height = (float(value) for value in bbox[:4])
    except (TypeError, ValueError, OverflowError):
        return None
    left = max(0, min(int(round(x)), width - 1))
    top = max(0, min(int(round(y)), height - 1))
    right = max(left + 1, min(int(round(x + box_width)), width))
    bottom = max(top + 1, min(int(round(y + box_height)), height))
    if right - left < 2 or bottom - top < 2:
        return None
    return left, top, right - left, bottom - top


def load_reference_image(image_path: str | Path) -> Any:
    """Return the reference screenshot as an int16 RGB numpy array."""
    import numpy as np
    from PIL import Image

    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with Image.open(path) as source:
        return np.asarray(source.convert("RGB"), dtype=np.int16)


def _otsu_threshold(distance: Any) -> float:
    """Pick a contrast threshold from the crop's own distance histogram."""
    import numpy as np

    flat = distance.ravel()
    if flat.size == 0:
        return LEGACY_CONTRAST_THRESHOLD
    upper = max(32.0, float(flat.max()))
    histogram, edges = np.histogram(flat, bins=64, range=(0.0, upper))
    total = float(histogram.sum())
    if total <= 0:
        return LEGACY_CONTRAST_THRESHOLD
    probability = histogram / total
    centers = (edges[:-1] + edges[1:]) / 2.0
    omega = np.cumsum(probability)
    mu = np.cumsum(probability * centers)
    mu_total = mu[-1]
    denominator = omega * (1.0 - omega)
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mu_total * omega - mu) ** 2 / denominator
    between[~np.isfinite(between)] = 0.0
    index = int(np.argmax(between[1:-1])) + 1
    threshold = float(centers[index])
    return float(min(32.0, max(6.0, threshold)))


def ink_support(
    image: Any,
    bbox: Sequence[Any],
    *,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Measure ink inside a source-pixel bbox and return pixel evidence.

    The background is estimated from the crop border.  The contrast threshold
    is derived from the crop histogram when not supplied, which makes the
    measurement work on both light and dark themes.
    """
    import numpy as np

    height, width = image.shape[:2]
    cleaned = _clean_bbox(bbox, width, height)
    result: dict[str, Any] = {
        "bbox": None,
        "ink_bbox": None,
        "inkPixelCount": 0,
        "inkSupport": 0.0,
        "threshold": threshold or 0.0,
        "background": "#000000",
        "foreground": "#ffffff",
    }
    if cleaned is None:
        return result
    x, y, box_width, box_height = cleaned
    crop = image[y : y + box_height, x : x + box_width]
    ring = np.concatenate(
        [crop[0, :, :], crop[-1, :, :], crop[:, 0, :], crop[:, -1, :]],
        axis=0,
    )
    background_rgb = np.median(ring, axis=0)
    distance = np.abs(crop - background_rgb.reshape(1, 1, 3)).max(axis=2)
    effective = threshold if threshold is not None else _otsu_threshold(distance)
    mask = distance >= effective
    # Suppress borders / rules that span most of the box.
    mask[mask.sum(axis=1) >= max(4, int(round(box_width * 0.8))), :] = False
    mask[:, mask.sum(axis=0) >= max(4, int(round(box_height * 0.8)))] = False
    count = int(mask.sum())
    result.update(
        {
            "bbox": [x, y, box_width, box_height],
            "threshold": round(float(effective), 3),
            "background": _hex_color(background_rgb),
            "inkPixelCount": count,
            "inkSupport": round(float(count / float(mask.size)), 6),
        }
    )
    if count < MIN_INK_PIXELS:
        return result
    ys, xs = np.where(mask)
    ink_left, ink_top = int(xs.min()), int(ys.min())
    ink_right, ink_bottom = int(xs.max()) + 1, int(ys.max()) + 1
    strong = mask & (
        distance >= max(effective, float(np.percentile(distance[mask], 75)))
    )
    if not strong.any():
        strong = mask
    foreground_rgb = np.median(crop[strong], axis=0)
    result["ink_bbox"] = [
        x + ink_left,
        y + ink_top,
        ink_right - ink_left,
        ink_bottom - ink_top,
    ]
    result["inkBox"] = result["ink_bbox"]
    result["foreground"] = _hex_color(foreground_rgb)
    result["contrastDelta"] = round(float(distance[strong].mean()), 3)
    return result


def _text_like_ink(
    measurement: Mapping[str, Any],
    bbox: Sequence[Any],
) -> bool:
    """Reject a solid fill or a 2px border masquerading as text ink."""
    ink_bbox = measurement.get("ink_bbox")
    if not isinstance(ink_bbox, list) or len(ink_bbox) != 4:
        return False
    try:
        _x, _y, box_width, box_height = (
            float(value) for value in bbox[:4]
        )
        ink_width, ink_height = float(ink_bbox[2]), float(ink_bbox[3])
    except (TypeError, ValueError):
        return False
    if box_width <= 0 or box_height <= 0:
        return False
    if ink_height < max(5.0, 0.30 * box_height):
        return False
    if ink_width >= 0.98 * box_width and ink_height >= 0.98 * box_height:
        return False
    if measurement.get("inkSupport", 0.0) > 0.65:
        return False
    return int(measurement.get("inkPixelCount") or 0) >= 6


def candidate_bboxes(
    bbox: Sequence[Any],
    image_width: int,
    image_height: int,
) -> list[tuple[str, list[float]]]:
    """Enumerate plausible inverse coordinate transforms for one VLM box."""
    x, y, width, height = (float(value) for value in bbox[:4])
    sx = image_width / NORMALIZED_AXIS
    sy = image_height / NORMALIZED_AXIS
    candidates: list[tuple[str, list[float]]] = [("identity", [x, y, width, height])]
    if image_height > NORMALIZED_AXIS:
        candidates.append(("y-axis-1000", [x, y * sy, width, height]))
        candidates.append(
            ("y+height-1000", [x, y * sy, width, height * sy])
        )
    if image_width > NORMALIZED_AXIS:
        candidates.append(
            ("x-axis-1000", [x * sx, y, width * sx, height])
        )
        candidates.append(
            ("xywh-1000", [x * sx, y * sy, width * sx, height * sy])
        )
    return candidates


def _normalize_text(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u3400-\u9fff]", "", text).lower()


def _ocr_candidates(
    text: str, ocr_observations: Sequence[Mapping[str, Any]]
) -> list[tuple[float, list[float], str]]:
    target = _normalize_text(text)
    if not target:
        return []
    scored: list[tuple[float, list[float], str]] = []
    for observation in ocr_observations:
        if not isinstance(observation, Mapping):
            continue
        observed = str(observation.get("text") or "")
        candidate = _normalize_text(observed)
        if not candidate:
            continue
        similarity = SequenceMatcher(None, target, candidate).ratio()
        if similarity < 0.6:
            continue
        bbox = observation.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        scored.append(
            (similarity, [float(value) for value in bbox], observed)
        )
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[:3]


def recover_text_evidence(
    image: Any,
    bbox: Sequence[Any],
    *,
    text: str = "",
    ocr_observations: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Recover a usable source bbox and ink bbox for a broken text element.

    Selection is evidence-driven: every candidate inverse transform (and
    optional OCR re-localization) is scored against the reference pixels, and
    the best supported candidate wins.  No sample-specific constants are used.
    """
    height, width = image.shape[:2]
    direct = ink_support(image, bbox)
    if (
        direct["inkPixelCount"] >= MIN_INK_PIXELS
        and direct["inkSupport"] >= MIN_INK_SUPPORT
        and _text_like_ink(direct, bbox)
    ):
        return {
            "status": "recovered",
            "provenance": "adaptive-contrast",
            "bbox": direct["bbox"],
            "evidence": direct,
            "candidatesChecked": 1,
            "score": direct["inkSupport"],
        }

    def measure(
        proposals: Sequence[tuple[str, list[float]]],
    ) -> list[tuple[float, int, str, dict[str, Any]]]:
        ranked: list[tuple[float, int, str, dict[str, Any]]] = []
        for label, proposed in proposals:
            measurement = ink_support(image, proposed)
            if measurement["inkPixelCount"] < MIN_INK_PIXELS:
                continue
            cleaned = _clean_bbox(proposed, width, height)
            if cleaned is None:
                continue
            original_area = max(1.0, float(bbox[2]) * float(bbox[3]))
            proposed_area = float(cleaned[2]) * float(cleaned[3])
            area_penalty = min(
                1.0, original_area / max(1.0, proposed_area) + 0.25
            )
            score = measurement["inkSupport"] * area_penalty
            if not _text_like_ink(measurement, proposed):
                score *= 0.35
            ranked.append(
                (
                    score,
                    measurement["inkPixelCount"],
                    label,
                    measurement,
                )
            )
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return ranked

    # Stage 1: inverse coordinate transforms.  These preserve the VLM x axis,
    # which is reliable, and therefore outrank OCR re-localization.
    transforms = [
        (label, proposed)
        for label, proposed in candidate_bboxes(bbox, width, height)
        if label != "identity"  # already tested by the direct measurement
    ]
    ranked = measure(transforms)
    checked = len(transforms)
    if ranked and ranked[0][0] >= MIN_INK_SUPPORT:
        score, _count, label, measurement = ranked[0]
        return {
            "status": "recovered",
            "provenance": label,
            "bbox": measurement["bbox"],
            "evidence": measurement,
            "candidatesChecked": checked,
            "score": round(float(score), 6),
        }

    # Stage 2: only when transforms fail, re-localize from OCR observations.
    ocr_proposals: list[tuple[str, list[float]]] = []
    for similarity, ocr_bbox, observed in _ocr_candidates(
        text, ocr_observations or []
    ):
        if similarity < 0.7:
            continue
        # VLM x is trustworthy; reject a match that jumps to another column.
        if abs(float(ocr_bbox[0]) - float(bbox[0])) > max(
            80.0, float(bbox[2]) * 1.5
        ):
            continue
        ocr_proposals.append(
            (f"ocr-relocalized:{similarity:.2f}:{observed[:16]}", ocr_bbox)
        )
    checked += len(ocr_proposals)
    ranked = measure(ocr_proposals)
    if ranked and ranked[0][0] >= MIN_INK_SUPPORT:
        score, _count, label, measurement = ranked[0]
        return {
            "status": "recovered",
            "provenance": label,
            "bbox": measurement["bbox"],
            "evidence": measurement,
            "candidatesChecked": checked,
            "score": round(float(score), 6),
        }
    return {
        "status": "unverified",
        "provenance": "no-ink-candidate" if not ranked else "weak-ink-candidate",
        "bbox": direct["bbox"],
        "evidence": direct,
        "candidatesChecked": checked,
        "bestCandidate": ranked[0][2] if ranked else None,
    }


def _text_elements(design: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        element
        for element in design.get("elements") or []
        if isinstance(element, Mapping)
        and str(element.get("type") or "") != "image"
        and str(element.get("text") or "").strip()
    ]


def _raster_ratio(design: Mapping[str, Any], width: int, height: int) -> float:
    import numpy as np

    coverage = np.zeros((height, width), dtype=bool)
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping) or element.get("type") != "image":
            continue
        cleaned = _clean_bbox(
            [
                element.get("x") or 0,
                element.get("y") or 0,
                element.get("width") or 0,
                element.get("height") or 0,
            ],
            width,
            height,
        )
        if cleaned is None:
            continue
        x, y, box_width, box_height = cleaned
        coverage[y : y + box_height, x : x + box_width] = True
    return round(float(coverage.mean()), 6)


def _theme(image: Any) -> dict[str, Any]:
    luma = image.mean(axis=2)
    mean = float(luma.mean())
    return {
        "theme": "dark" if mean < 110 else "light",
        "meanLuma": round(mean, 3),
    }


def _apply_recovery(
    element: dict[str, Any], recovery: Mapping[str, Any]
) -> None:
    """Write recovered pixel evidence back into one design element."""
    evidence = recovery["evidence"]
    bbox = evidence["bbox"]
    ink_bbox = evidence["ink_bbox"]
    if not bbox or not ink_bbox:
        return
    element["x"] = float(bbox[0])
    element["y"] = float(bbox[1])
    element["width"] = float(bbox[2])
    element["height"] = float(bbox[3])
    style = element.setdefault("style", {})
    style_evidence = element.get("styleEvidence")
    if not isinstance(style_evidence, dict):
        style_evidence = {}
        element["styleEvidence"] = style_evidence
    values = style_evidence.get("evidence")
    if not isinstance(values, dict):
        values = {}
        style_evidence["evidence"] = values
    values.update(
        {
            "status": "recovered",
            "reason": f"perception-contract:{recovery['provenance']}",
            "source_bbox": list(bbox),
            "ink_bbox": list(ink_bbox),
            "ink_bbox_source": recovery["provenance"],
            "background": evidence["background"],
            "foreground": evidence["foreground"],
            "contrast_delta": evidence.get("contrastDelta", 0.0),
            "ink_pixel_count": evidence["inkPixelCount"],
            "script": "cjk" if _has_cjk(str(element.get("text") or "")) else "latin",
        }
    )
    # Theme-aware typography: derive size from the measured ink, never from a
    # hard-coded light-theme grey.
    ink_height = max(1, int(ink_bbox[3]))
    style["fontSize"] = max(8.0, min(96.0, round(ink_height * 0.95 * 4) / 4))
    style["textColor"] = evidence["foreground"]
    style["confidence"] = min(0.65, float(style.get("confidence") or 0.2) + 0.35)
    style_evidence["confidence"] = style["confidence"]
    style_evidence["schema_version"] = SCHEMA_VERSION


def run_perception_contract(
    design: Mapping[str, Any],
    image_path: str | Path,
    *,
    ocr_supplement: Mapping[str, Any] | None = None,
    mode: str = "adaptive",
    drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate and (optionally) repair perception evidence.

    Returns ``(design_out, report)``.  ``design`` is never mutated.  In
    ``report`` mode the returned design is identical to the input; in
    ``adaptive`` mode repair is applied only when the perception-defect ratio
    exceeds ``drift_threshold``.
    """
    if mode not in {"off", "report", "adaptive"}:
        raise ValueError(f"unsupported perception contract mode: {mode}")
    image = load_reference_image(image_path)
    height, width = image.shape[:2]
    observations: list[Mapping[str, Any]] = []
    if isinstance(ocr_supplement, Mapping):
        raw = ocr_supplement.get("observations")
        if isinstance(raw, list):
            observations = [item for item in raw if isinstance(item, Mapping)]
    elements = _text_elements(design)
    items: list[dict[str, Any]] = []
    broken: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for element in elements:
        style_evidence = element.get("styleEvidence")
        values = (
            style_evidence.get("evidence")
            if isinstance(style_evidence, Mapping)
            else None
        )
        bbox = (
            values.get("source_bbox")
            if isinstance(values, Mapping)
            else None
        )
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            bbox = [
                element.get("x") or 0,
                element.get("y") or 0,
                element.get("width") or 0,
                element.get("height") or 0,
            ]
        ink_bbox = values.get("ink_bbox") if isinstance(values, Mapping) else None
        measured = ink_support(image, bbox)
        has_ink = isinstance(ink_bbox, list) and len(ink_bbox) == 4
        if (
            has_ink
            and measured["inkPixelCount"] >= MIN_INK_PIXELS
            and measured["inkSupport"] >= MIN_INK_SUPPORT
        ):
            items.append(
                {
                    "contentRef": element.get("contentRef"),
                    "text": str(element.get("text") or ""),
                    "status": "verified",
                    "inkSupport": measured["inkSupport"],
                }
            )
            continue
        recovery = recover_text_evidence(
            image,
            bbox,
            text=str(element.get("text") or ""),
            ocr_observations=observations,
        )
        items.append(
            {
                "contentRef": element.get("contentRef"),
                "text": str(element.get("text") or ""),
                "status": recovery["status"],
                "fromBBox": list(bbox),
                "toBBox": recovery["bbox"],
                "provenance": recovery["provenance"],
                "inkSupport": recovery["evidence"]["inkSupport"],
                "candidatesChecked": recovery["candidatesChecked"],
            }
        )
        broken.append((element, recovery))

    raster_ratio = _raster_ratio(design, width, height)
    verified_count = sum(
        1 for item in items if item["status"] == "verified"
    )
    repaired = sum(1 for item in items if item["status"] == "recovered")
    unresolved = sum(1 for item in items if item["status"] == "unverified")
    total = max(1, len(items))
    broken_ratio = round(len(broken) / total, 6)
    unverified_ratio = round(unresolved / total, 6)
    # Architecture-level drift signal: one inverse coordinate transform that
    # explains a coherent majority of broken boxes is a systematic contract
    # violation (VLM returned a different coordinate space).  Isolated small
    # / low-contrast boxes on an otherwise calibrated sample are NOT drift,
    # so they must not trigger a repair that could regress that sample.
    transform_labels = (
        "y-axis-1000",
        "y+height-1000",
        "x-axis-1000",
        "xywh-1000",
    )
    transform_counts = {
        label: sum(
            1 for item in items if item.get("provenance") == label
        )
        for label in transform_labels
    }
    dominant_transform = max(
        transform_counts, key=lambda label: transform_counts[label]
    )
    dominant_count = transform_counts[dominant_transform]
    systematic_drift = (
        dominant_count >= 3
        and dominant_count / max(1, len(broken)) >= 0.5
    )
    drift = systematic_drift or broken_ratio > drift_threshold
    apply_repair = mode == "adaptive" and drift
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "repaired"
            if apply_repair
            else "drift-detected"
            if drift
            else "verified"
        ),
        "mode": mode,
        "reference": {"size": [width, height], **_theme(image)},
        "policy": {
            "driftThreshold": drift_threshold,
            "legacyContrastThreshold": LEGACY_CONTRAST_THRESHOLD,
            "systematicCoordinateDrift": systematic_drift,
            "dominantTransform": dominant_transform,
            "dominantTransformCount": dominant_count,
            "transformCounts": transform_counts,
            "applyRepair": apply_repair,
            "reason": (
                "systematic-coordinate-space-drift"
                if systematic_drift
                else "perception-defect-ratio-exceeds-threshold"
                if broken_ratio > drift_threshold
                else "ink-evidence-coverage-within-threshold"
            ),
        },
        "counts": {
            "textElements": len(elements),
            "verified": verified_count,
            "broken": len(broken),
            "recovered": repaired,
            "unverified": unresolved,
            "rasterElements": sum(
                1
                for element in design.get("elements") or []
                if isinstance(element, Mapping)
                and element.get("type") == "image"
            ),
        },
        "ratios": {
            "inkEvidenceCoverage": round(verified_count / total, 6),
            "perceptionDefectRatio": broken_ratio,
            "unverifiedRatio": unverified_ratio,
            "recoveredRatio": round(repaired / total, 6),
            "rasterUnderlayRatio": raster_ratio,
        },
        "items": items,
        "limitations": [
            "Diagnostic only: this contract does not change the frozen formal acceptance policy.",
            "Recovered bboxes are selected by reference-pixel ink support, not by the truth manifest.",
            "Verified elements are never modified, so a previously calibrated sample cannot regress.",
        ],
    }
    if mode != "adaptive" or not apply_repair:
        return dict(design), report
    design_out = copy.deepcopy(dict(design))
    by_ref = {
        str(element.get("contentRef") or index): index
        for index, element in enumerate(design_out.get("elements") or [])
        if isinstance(element, Mapping)
    }
    for element, recovery in broken:
        if recovery["status"] != "recovered":
            continue
        key = str(element.get("contentRef") or "")
        index = by_ref.get(key)
        if index is None:
            continue
        target = design_out["elements"][index]
        _apply_recovery(target, recovery)
    report["repair"] = {
        "applied": True,
        "elementsUpdated": repaired,
        "unresolved": len(broken) - repaired,
    }
    return design_out, report


def evaluate_native_fidelity(
    design: Mapping[str, Any],
    reference_path: str | Path,
    export_path: str | Path,
    *,
    bad_pixel_threshold: int = 30,
) -> dict[str, Any]:
    """Measure pixel fidelity excluding source-pixel raster underlays.

    ``within30`` on a page that is half covered by a literal screenshot crop
    overstates reconstruction quality.  This diagnostic reports the error on
    natively rebuilt pixels separately; it is not an acceptance verdict.
    """
    import numpy as np
    from PIL import Image

    reference = load_reference_image(reference_path)
    with Image.open(export_path) as source:
        rendered = np.asarray(source.convert("RGB"), dtype=np.int16)
    if rendered.shape != reference.shape:
        rendered = np.asarray(
            Image.fromarray(rendered.astype("uint8")).resize(
                (reference.shape[1], reference.shape[0])
            ),
            dtype=np.int16,
        )
    bad = np.max(np.abs(reference - rendered), axis=2) > bad_pixel_threshold
    height, width = bad.shape[:2]
    raster = np.zeros((height, width), dtype=bool)
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping) or element.get("type") != "image":
            continue
        cleaned = _clean_bbox(
            [
                element.get("x") or 0,
                element.get("y") or 0,
                element.get("width") or 0,
                element.get("height") or 0,
            ],
            width,
            height,
        )
        if cleaned is None:
            continue
        x, y, box_width, box_height = cleaned
        raster[y : y + box_height, x : x + box_width] = True
    native = ~raster
    return {
        "schema_version": "grounding-native-fidelity/1.0",
        "status": "measured",
        "badPixelThreshold": bad_pixel_threshold,
        "overallBadPixelRatio": round(float(bad.mean()), 6),
        "rasterUnderlayRatio": round(float(raster.mean()), 6),
        "nativeOnlyBadPixelRatio": (
            round(float(bad[native].mean()), 6) if native.any() else None
        ),
        "rasterRegionBadPixelRatio": (
            round(float(bad[raster].mean()), 6) if raster.any() else None
        ),
        "limitations": [
            "Diagnostic only; not part of the frozen acceptance decision.",
            "Raster underlay rectangles are excluded from the native-only metric.",
        ],
    }
