"""Small OCR comparison helpers used by the P1 OCR probe."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_ocr_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()


def compare_ocr_text(
    expected_phrases: list[str] | tuple[str, ...],
    observed_text: str,
) -> dict[str, Any]:
    observed = normalize_ocr_text(observed_text)
    phrases: list[dict[str, Any]] = []
    for expected in expected_phrases:
        normalized = normalize_ocr_text(expected)
        phrases.append(
            {
                "expected": expected,
                "normalized": normalized,
                "matched": bool(normalized) and normalized in observed,
            }
        )
    matched_count = sum(item["matched"] for item in phrases)
    if not phrases:
        status = "no-expectation"
    elif matched_count == len(phrases):
        status = "matched"
    elif matched_count:
        status = "partial"
    else:
        status = "no-match"
    return {
        "status": status,
        "normalized_observed": observed,
        "matched_count": matched_count,
        "total_count": len(phrases),
        "phrases": phrases,
    }


def summarize_ocr_observations(
    observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    lines: list[dict[str, Any]] = []
    confidences: list[float] = []
    for item in observations:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        confidence = item.get("confidence")
        try:
            numeric_confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            numeric_confidence = None
        if numeric_confidence is not None:
            confidences.append(numeric_confidence)
        lines.append(
            {
                "text": text,
                "confidence": numeric_confidence,
                "bbox": item.get("bbox"),
            }
        )
    return {
        "line_count": len(lines),
        "mean_confidence": (
            round(sum(confidences) / len(confidences), 6) if confidences else None
        ),
        "min_confidence": min(confidences) if confidences else None,
        "max_confidence": max(confidences) if confidences else None,
        "lines": lines,
    }


def parse_tesseract_boxes(
    text: str,
    *,
    image_height: int,
) -> list[dict[str, Any]]:
    glyphs: list[dict[str, Any]] = []
    for line in str(text or "").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        char = parts[0]
        if not char or char.isspace():
            continue
        try:
            left, bottom, right, top = (int(value) for value in parts[1:5])
        except ValueError:
            continue
        glyphs.append(
            {
                "text": char,
                "bbox": [left, image_height - top, right - left, top - bottom],
            }
        )
    return glyphs


def compare_glyph_text(expected_text: str, observed_text: str) -> dict[str, Any]:
    expected = _glyph_identity(expected_text)
    observed = _glyph_identity(observed_text)
    return {
        "matched": bool(expected) and expected == observed,
        "expected_count": len(expected),
        "observed_count": len(observed),
        "expected_normalized": expected,
        "observed_normalized": observed,
    }


def compare_glyph_boxes(
    truth: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    observed: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    truth_items = [item for item in truth if str(item.get("text") or "").strip()]
    observed_items = [item for item in observed if str(item.get("text") or "").strip()]
    truth_text = "".join(str(item["text"]).casefold() for item in truth_items)
    observed_text = "".join(str(item["text"]).casefold() for item in observed_items)
    all_deltas: list[float] = []
    per_glyph_max: list[float] = []
    for left, right in zip(truth_items, observed_items):
        box_deltas = [
            abs(float(left["bbox"][index]) - float(right["bbox"][index]))
            for index in range(4)
        ]
        all_deltas.extend(box_deltas)
        per_glyph_max.append(max(box_deltas))
    ordered = sorted(all_deltas)
    return {
        "sequence_match": truth_text == observed_text,
        "truth_count": len(truth_items),
        "observed_count": len(observed_items),
        "compared_count": len(per_glyph_max),
        "max_delta": max(all_deltas) if all_deltas else None,
        "p95_delta": (
            ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
            if ordered else None
        ),
        "within_2px_count": sum(item <= 2 for item in per_glyph_max),
        "over_4px_count": sum(item > 4 for item in per_glyph_max),
    }


def calibrate_glyph_boxes(
    truth: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    observed: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    truth_items = [item for item in truth if str(item.get("text") or "").strip()]
    observed_items = [item for item in observed if str(item.get("text") or "").strip()]
    paired = list(zip(truth_items, observed_items))
    offsets: list[float] = []
    for index in range(4):
        deltas = sorted(
            float(right["bbox"][index]) - float(left["bbox"][index])
            for left, right in paired
        )
        offsets.append(_median(deltas))
    adjusted: list[dict[str, Any]] = []
    for item in observed_items:
        adjusted.append(
            {
                "text": item["text"],
                "bbox": [
                    float(item["bbox"][index]) - offsets[index]
                    for index in range(4)
                ],
            }
        )
    return {
        "method": "per-axis-median-bias",
        "axes": ["x", "y", "w", "h"],
        "offsets": offsets,
        "raw": compare_glyph_boxes(truth_items, observed_items),
        "calibrated": compare_glyph_boxes(truth_items, adjusted),
        "note": "Median bias is fitted and evaluated on the same glyph set; this is not holdout validation.",
    }


def compare_glyph_boxes_trusted(
    truth: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    observed: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    truth_items = [item for item in truth if str(item.get("text") or "").strip()]
    observed_items = [item for item in observed if str(item.get("text") or "").strip()]
    trusted_truth: list[dict[str, Any]] = []
    trusted_observed: list[dict[str, Any]] = []
    suspects: list[dict[str, Any]] = []
    for left, right in zip(truth_items, observed_items):
        truth_w = float(left["bbox"][2])
        truth_h = float(left["bbox"][3])
        observed_w = float(right["bbox"][2])
        observed_h = float(right["bbox"][3])
        suspect = observed_w > truth_w + 8 or observed_h > truth_h + 8
        if suspect:
            suspects.append(
                {
                    "text": left.get("text"),
                    "truth_bbox": left["bbox"],
                    "observed_bbox": right["bbox"],
                    "reason": "expanded-or-merged-box",
                }
            )
        else:
            trusted_truth.append(left)
            trusted_observed.append(right)
    return {
        "suspect_count": len(suspects),
        "suspects": suspects,
        "trusted": compare_glyph_boxes(trusted_truth, trusted_observed),
    }


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _glyph_identity(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(char for char in normalized if char.isalnum())
