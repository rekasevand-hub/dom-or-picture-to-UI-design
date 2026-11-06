"""Shared contracts for the Grounding high-fidelity controller."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

EVIDENCE_SCHEMA_VERSION = "grounding-fidelity-evidence/1.0"
INVENTORY_SCHEMA_VERSION = "grounding-content-inventory/1.0"
GEOMETRY_SCHEMA_VERSION = "grounding-geometry-manifest/1.0"
CONTAINER_MANIFEST_SCHEMA_VERSION = "grounding-container-manifest/1.0"
SCENE_PLAN_SCHEMA_VERSION = "grounding-scene-plan/1.0"
FIDELITY_SCHEMA_VERSION = "grounding-fidelity-report/1.0"


def canonical_json(value: Any) -> str:
    """Return a deterministic JSON representation for hashing and comparisons."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        canonical_json([str(part) for part in parts]).encode("utf-8")
    ).hexdigest()[:16]
    return f"{prefix}:{digest}"


def reference_size(reference: Mapping[str, Any]) -> tuple[int, int]:
    """Read and validate the immutable source canvas size."""
    if not isinstance(reference, Mapping):
        raise ValueError("reference must be an object")
    raw: Any = None
    input_value = reference.get("input")
    if isinstance(input_value, Mapping):
        raw = input_value.get("size")
    if raw is None:
        raw = reference.get("image_size")
    if raw is None and "width" in reference and "height" in reference:
        raw = [reference.get("width"), reference.get("height")]
    try:
        width, height = (int(value) for value in raw)
    except (TypeError, ValueError):
        raise ValueError("reference image size must contain width and height") from None
    if width <= 0 or height <= 0:
        raise ValueError("reference image size must be positive")
    return width, height


def reference_sha256(reference: Mapping[str, Any]) -> str:
    input_value = reference.get("input")
    value = (
        input_value.get("sha256")
        if isinstance(input_value, Mapping)
        else reference.get("image_sha256")
    )
    text = str(value or "").strip().lower()
    return text


def normalize_bbox(
    value: Any,
    width: int,
    height: int,
    *,
    clamp: bool = True,
) -> list[int] | None:
    """Normalize a box to positive source-pixel ``xywh`` coordinates."""
    if isinstance(value, Mapping):
        raw = [
            value.get("x"),
            value.get("y"),
            value.get("width"),
            value.get("height"),
        ]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        raw = list(value)
    else:
        return None
    if len(raw) != 4:
        return None
    if any(isinstance(item, bool) for item in raw):
        return None
    try:
        x, y, box_width, box_height = (int(round(float(item))) for item in raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if box_width <= 0 or box_height <= 0:
        return None
    if not clamp:
        return [x, y, box_width, box_height]
    left = max(0, min(width, x))
    top = max(0, min(height, y))
    right = max(0, min(width, x + box_width))
    bottom = max(0, min(height, y + box_height))
    if right <= left or bottom <= top:
        return None
    return [left, top, right - left, bottom - top]


def normalize_match_text(value: Any) -> str:
    """Normalize text for matching without replacing its display form."""
    return "".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def source_authority(source: Any) -> str:
    text = str(source or "").lower()
    if "ocr" in text:
        return "ocr"
    if "slice" in text:
        return "slice"
    if "image-enrichment" in text or "image_enrichment" in text:
        return "image-enrichment"
    if "cv" in text:
        return "cv"
    if "pixel" in text or "crop" in text:
        return "source-pixel"
    return "grounding"


def source_status(authority: str, record: Mapping[str, Any]) -> str:
    explicit = str(record.get("status") or "").lower()
    if explicit in {"observed", "derived", "inferred"}:
        return explicit
    if authority in {"grounding", "cv", "source-pixel"}:
        return "observed"
    return "inferred"


def evidence_record(
    *,
    record_id: str,
    kind: str,
    source: Any,
    bbox: Any,
    width: int,
    height: int,
    payload_ref: str,
    record: Mapping[str, Any] | None = None,
    default_reason: str = "",
) -> dict[str, Any]:
    source_record = record or {}
    authority = source_authority(source_record.get("source") or source)
    confidence = source_record.get("confidence", 1.0)
    try:
        confidence_value = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence_value = 0.0
    return {
        "id": record_id,
        "kind": kind,
        "status": source_status(authority, source_record),
        "authority": authority,
        "confidence": confidence_value,
        "bbox": normalize_bbox(bbox, width, height) or [0, 0, 0, 0],
        "payload_ref": payload_ref,
        "reason": str(
            source_record.get("reason")
            or source_record.get("warning")
            or default_reason
        ),
    }


def validate_evidence_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a serialized evidence bundle and return a deep copy."""
    import copy

    if not isinstance(bundle, Mapping):
        raise ValueError("evidence bundle must be an object")
    if bundle.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported evidence bundle schema_version")
    reference = bundle.get("reference")
    if not isinstance(reference, Mapping):
        raise ValueError("evidence bundle reference must be an object")
    width, height = reference_size(reference)
    records = bundle.get("records")
    if not isinstance(records, list):
        raise ValueError("evidence bundle records must be a list")
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"evidence bundle records[{index}] must be an object")
        required = {
            "id",
            "kind",
            "status",
            "authority",
            "confidence",
            "bbox",
            "payload_ref",
            "reason",
        }
        missing = required - set(record)
        if missing:
            raise ValueError(
                f"evidence bundle records[{index}] is missing "
                + ", ".join(sorted(missing))
            )
        record_id = str(record.get("id") or "")
        if not record_id or record_id in seen:
            raise ValueError(f"evidence bundle duplicate or empty id: {record_id}")
        seen.add(record_id)
        bbox = record.get("bbox")
        if bbox != [0, 0, 0, 0] and normalize_bbox(bbox, width, height) is None:
            raise ValueError(f"evidence bundle records[{index}].bbox is invalid")
    return copy.deepcopy(dict(bundle))
