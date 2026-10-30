from __future__ import annotations

import copy
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SEMANTIC_MERGE_SCHEMA_VERSION = "dom-semantic-merge/1.0"
SEMANTIC_COMPONENTS_FILENAME = "20_semantic_components.json"
AUTO_MERGE_IOU = 0.94
# Exact 0.5-IoU overlaps remain visible for review; none below 0.94 auto-merges.
REVIEW_IOU = 0.50
_EXPLICIT_EVIDENCE_KINDS = {"tag", "aria-role", "list-type"}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _bbox(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return [0, 0, 0, 0]
    return [max(0, _int(item)) for item in value[:4]]


def _iou(left: Sequence[int], right: Sequence[int]) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    if lw <= 0 or lh <= 0 or rw <= 0 or rh <= 0:
        return 0.0
    ix = max(0, min(lx + lw, rx + rw) - max(lx, rx))
    iy = max(0, min(ly + lh, ry + rh) - max(ly, ry))
    intersection = ix * iy
    union = lw * lh + rw * rh - intersection
    return round(intersection / union, 6) if union > 0 else 0.0


def _authority(component: Mapping[str, Any]) -> str:
    for item in component.get("evidence") or []:
        if (
            isinstance(item, Mapping)
            and str(item.get("kind") or "") in _EXPLICIT_EVIDENCE_KINDS
        ):
            return "dom-explicit"
    return "dom-inferred"


def _external_candidate(
    candidate: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    role = str(candidate.get("role") or candidate.get("type") or "unknown").strip().lower()
    normalized = {
        "id": str(candidate.get("id") or f"external-{index}"),
        "role": role,
        "bbox": _bbox(candidate.get("bbox")),
        "confidence": round(float(candidate.get("confidence") or 0.0), 6),
        "source": str(candidate.get("source") or "external"),
    }
    for key in ("title", "text", "ariaLabel"):
        value = str(candidate.get(key) or "").strip()
        if value:
            normalized[key] = value[:500]
    meta = candidate.get("meta")
    if isinstance(meta, Mapping):
        normalized["meta"] = copy.deepcopy(dict(meta))
    return normalized


def _candidate_evidence(
    candidate: Mapping[str, Any],
    *,
    overlap: float,
    kind: str = "detector-match",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "value": {
            "id": candidate["id"],
            "role": candidate["role"],
            "source": candidate["source"],
            "confidence": candidate["confidence"],
            "overlap": overlap,
        },
        "weight": round(float(candidate["confidence"]) * overlap, 6),
    }


def _title_evidence(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    title = str(candidate.get("title") or "").strip()
    if not title:
        return []
    return [{"kind": "detector-title", "value": title, "weight": 0.2}]


def merge_semantic_candidates(
    dom_semantics: Mapping[str, Any],
    external_candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    components = [
        copy.deepcopy(dict(component))
        for component in dom_semantics.get("components") or []
        if isinstance(component, Mapping)
    ]
    candidates = [
        _external_candidate(candidate, index)
        for index, candidate in enumerate(external_candidates)
        if isinstance(candidate, Mapping)
    ]
    candidates.sort(key=lambda item: (item["bbox"][1], item["bbox"][0], item["id"]))

    for component in components:
        component["bbox"] = _bbox(component.get("bbox"))
        component["role"] = str(component.get("role") or "unknown").strip().lower()
        component["authority"] = _authority(component)
        component["domAuthority"] = component["authority"]
        component["domRole"] = component["role"]
        component["evidence"] = [
            copy.deepcopy(dict(item))
            for item in component.get("evidence") or []
            if isinstance(item, Mapping)
        ]
        component.setdefault("externalEvidence", [])

    consumed: set[str] = set()
    merged: list[dict[str, Any]] = []
    review_required: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    components.sort(
        key=lambda item: (
            item["bbox"][1],
            item["bbox"][0],
            str(item.get("id") or ""),
        )
    )
    for component in components:
        best: tuple[float, dict[str, Any]] | None = None
        for candidate in candidates:
            if candidate["id"] in consumed:
                continue
            overlap = _iou(component["bbox"], candidate["bbox"])
            rank = (overlap, candidate["confidence"])
            if best is None or rank > (
                best[0],
                best[1]["confidence"],
            ):
                best = (overlap, candidate)
        if best is None:
            continue
        overlap, candidate = best
        if overlap < REVIEW_IOU:
            continue

        if overlap < AUTO_MERGE_IOU:
            consumed.add(candidate["id"])
            review_required.append(
                {
                    **copy.deepcopy(candidate),
                    "authority": "review-required",
                    "reason": "overlap-review",
                    "overlapWith": component.get("id"),
                    "overlap": overlap,
                }
            )
            continue

        consumed.add(candidate["id"])
        component["externalEvidence"].append(copy.deepcopy(candidate))
        component["evidence"].extend(_title_evidence(candidate))
        dom_role = component["role"]
        external_role = candidate["role"]
        if dom_role == "unknown" and external_role != "unknown":
            component["role"] = external_role
            component["authority"] = "detector-match"
            component["confidence"] = min(
                0.55,
                round(float(candidate["confidence"]) * 0.55, 6),
            )
            component["detectorMatch"] = True
        elif external_role == dom_role:
            component["detectorMatch"] = True
            component["evidence"].append(
                _candidate_evidence(candidate, overlap=overlap)
            )
        else:
            component["evidence"].append(
                _candidate_evidence(
                    candidate,
                    overlap=overlap,
                    kind="detector-role-rejected",
                )
            )
            rejected.append(
                {
                    **copy.deepcopy(candidate),
                    "reason": "explicit-dom-role-conflict",
                    "keptRole": dom_role,
                    "overlapWith": component.get("id"),
                    "overlap": overlap,
                }
            )
            continue
        merged.append(
            {
                "componentId": component.get("id"),
                "candidateId": candidate["id"],
                "role": component["role"],
                "overlap": overlap,
            }
        )

    detector_only = [
        {
            **copy.deepcopy(candidate),
            "authority": "detector-match",
            "status": "detector-only",
        }
        for candidate in candidates
        if candidate["id"] not in consumed
    ]

    merged_components = components
    role_counts = Counter(
        str(item.get("role") or "unknown")
        for item in [*merged_components, *detector_only, *review_required]
    )
    authority_counts = Counter(
        str(item.get("authority") or "dom-inferred")
        for item in [*merged_components, *detector_only, *review_required]
    )
    return {
        "schema_version": SEMANTIC_MERGE_SCHEMA_VERSION,
        "components": merged_components,
        "detectorOnly": detector_only,
        "merged": merged,
        "reviewRequired": review_required,
        "rejected": rejected,
        "roleCounts": dict(sorted(role_counts.items())),
        "authorityCounts": dict(sorted(authority_counts.items())),
    }


def persist_semantic_components(
    output: str | Path,
    result: Mapping[str, Any],
) -> Path:
    destination = Path(output)
    path = (
        destination
        if destination.suffix.lower() == ".json"
        else destination / SEMANTIC_COMPONENTS_FILENAME
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
