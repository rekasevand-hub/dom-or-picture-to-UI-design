"""Conservative Grounding + CV candidate fusion for the image strategy benchmark."""

from __future__ import annotations

import copy
import difflib
import re
from collections.abc import Mapping
from typing import Any


HYBRID_SCHEMA_VERSION = "image-hybrid-merge/1.0"
DUPLICATE_TEXT_OVERLAP = 0.25
DUPLICATE_VISUAL_OVERLAP = 0.8


def merge_hybrid_graph(
    grounding_graph: Mapping[str, Any],
    cv_graph: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add only non-duplicate CV candidates to a Grounding-primary graph."""
    merged = copy.deepcopy(dict(grounding_graph))
    merged["route"] = "hybrid"
    merged.setdefault("provenance", {})
    merged["provenance"]["route"] = "hybrid"
    merged["provenance"]["hybrid_primary"] = "grounding"

    existing_ids = {
        str(item.get("id"))
        for item in [
            *(merged.get("containers") or []),
            *(merged.get("elements") or []),
        ]
        if isinstance(item, Mapping)
    }
    existing_texts = [
        item
        for item in merged.get("elements") or []
        if isinstance(item, Mapping) and str(item.get("text") or "").strip()
    ]
    existing_visuals = [
        item
        for item in [
            *(merged.get("containers") or []),
            *(merged.get("elements") or []),
        ]
        if isinstance(item, Mapping)
    ]
    text_added: list[dict[str, Any]] = []
    visual_added: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    supplement_sources: list[str] = []

    for candidate in cv_graph.get("elements") or []:
        if not isinstance(candidate, Mapping):
            continue
        bbox = _bbox(candidate.get("bbox"))
        if bbox is None:
            skipped.append(
                {
                    "kind": "invalid-bbox",
                    "source": str(candidate.get("source") or ""),
                    "reason": "invalid-bbox",
                }
            )
            continue
        source = str(candidate.get("source") or "cv:unknown")
        supplement_sources.append(source)
        text = str(candidate.get("text") or "").strip()
        candidate_type = str(candidate.get("type") or "").lower()
        if text and candidate_type in {"text", "link"}:
            reason = _text_duplicate_reason(text, bbox, existing_texts)
            if reason is not None:
                skipped.append(
                    {
                        "kind": "text",
                        "source": source,
                        "bbox": bbox,
                        "text": text,
                        "reason": reason,
                    }
                )
                continue
            added = _hybrid_candidate(candidate, existing_ids, "text")
            merged.setdefault("elements", []).append(added)
            existing_ids.add(str(added["id"]))
            existing_texts.append(added)
            existing_visuals.append(added)
            text_added.append(added)
            continue

        reason = _visual_duplicate_reason(bbox, existing_visuals)
        if reason is not None:
            skipped.append(
                {
                    "kind": "visual",
                    "source": source,
                    "bbox": bbox,
                    "reason": reason,
                }
            )
            continue
        added = _hybrid_candidate(candidate, existing_ids, "visual")
        merged.setdefault("elements", []).append(added)
        existing_ids.add(str(added["id"]))
        existing_visuals.append(added)
        visual_added.append(added)

    unique_sources = list(dict.fromkeys(supplement_sources))
    report = {
        "schema_version": HYBRID_SCHEMA_VERSION,
        "status": "applied" if text_added or visual_added else "no-change",
        "primary_source": "grounding",
        "supplement_sources": unique_sources,
        "authority": "candidate",
        "promoted_to_verified": False,
        "text_added_count": len(text_added),
        "visual_added_count": len(visual_added),
        "container_added_count": 0,
        "skipped_count": len(skipped),
        "text_added": text_added,
        "visual_added": visual_added,
        "skipped": skipped,
        "ambiguities": [
            {
                "source": item["source"],
                "reason": item["reason"],
                "resolution": "retained-grounding-primary",
            }
            for item in skipped
        ],
        "limitations": [
            "Hybrid supplements remain candidates and are not verified facts.",
            "CV visual boxes do not establish semantic role or original asset identity.",
            "Duplicate suppression cannot resolve hidden or overlapping content.",
        ],
    }
    merged["provenance"]["hybrid"] = report
    return merged, report


def _hybrid_candidate(
    candidate: Mapping[str, Any],
    existing_ids: set[str],
    kind: str,
) -> dict[str, Any]:
    added = copy.deepcopy(dict(candidate))
    source = str(candidate.get("source") or "cv:unknown")
    added["source"] = source if source.startswith("hybrid:") else f"hybrid:{source}"
    added["authority"] = "hybrid-cv-candidate"
    added["verified"] = False
    added["hybridCandidateKind"] = kind
    added["hybridProvenance"] = {
        "primary": "grounding",
        "supplement": source,
        "status": "candidate",
        "verified": False,
    }
    candidate_id = str(candidate.get("id") or f"cv-{kind}")
    if candidate_id in existing_ids:
        candidate_id = f"hybrid-{kind}-{candidate_id}"
    suffix = 2
    base_id = candidate_id
    while candidate_id in existing_ids:
        candidate_id = f"{base_id}-{suffix}"
        suffix += 1
    added["id"] = candidate_id
    return added


def _text_duplicate_reason(
    text: str,
    bbox: tuple[int, int, int, int],
    existing: list[Mapping[str, Any]],
) -> str | None:
    normalized = _normalize_text(text)
    for item in existing:
        existing_bbox = _bbox(item.get("bbox"))
        if existing_bbox is None:
            continue
        overlap = _overlap_ratio(bbox, existing_bbox)
        existing_text = str(item.get("text") or "")
        existing_normalized = _normalize_text(existing_text)
        if (
            normalized == existing_normalized
            or (normalized in existing_normalized and overlap >= DUPLICATE_TEXT_OVERLAP)
        ) and overlap >= 0.25:
            return "duplicate-text"
        if (
            overlap >= 0.5
            and difflib.SequenceMatcher(
                None,
                normalized,
                existing_normalized,
            ).ratio()
            >= 0.9
        ):
            return "duplicate-text"
    return None


def _visual_duplicate_reason(
    bbox: tuple[int, int, int, int],
    existing: list[Mapping[str, Any]],
) -> str | None:
    if any(
        item_bbox is not None
        and _overlap_ratio(bbox, item_bbox) >= DUPLICATE_VISUAL_OVERLAP
        for item in existing
        if (item_bbox := _bbox(item.get("bbox"))) is not None
    ):
        return "duplicate-visual"
    return None


def _normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").casefold())


def _bbox(value: Any) -> tuple[int, int, int, int] | None:
    try:
        x, y, width, height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    if width < 1 or height < 1:
        return None
    return x, y, width, height


def _overlap_ratio(
    inner: tuple[int, int, int, int],
    outer: tuple[int, int, int, int],
) -> float:
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    left = max(ix, ox)
    top = max(iy, oy)
    right = min(ix + iw, ox + ow)
    bottom = min(iy + ih, oy + oh)
    intersection = max(0, right - left) * max(0, bottom - top)
    return intersection / max(1, iw * ih)
