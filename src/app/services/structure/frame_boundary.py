"""Fielded comparison for rendered frame boundaries."""
from __future__ import annotations

from typing import Any

from src.app.services.structure.capture_state import normalize_capture_url


RENDERED_FRAME_BOUNDARY_SCOPE = "rendered-frame-boundary-strict/1.0"
FRAME_BOUNDARY_SCHEMA = "p1-rendered-frame-boundary/1.0"
IDENTITY_FIELDS = [
    "scope_path",
    "parent_chain",
    "visible_index",
    "depth",
]
GEOMETRY_FIELDS = ["x", "y", "width", "height"]


def compare_rendered_frame_boundaries(
    left_page_state: dict[str, Any],
    right_page_state: dict[str, Any],
) -> dict[str, Any]:
    left = build_frame_boundary_snapshot(left_page_state)
    right = build_frame_boundary_snapshot(right_page_state)
    reasons: list[str] = []
    if not left["inventory_observable"] or not right["inventory_observable"]:
        reasons.append("frame-boundary-inventory-unobservable")
    left_records = left["by_identity"]
    right_records = right["by_identity"]
    left_keys = set(left_records)
    right_keys = set(right_records)
    identity_matches = left_keys & right_keys
    if left_keys != right_keys:
        reasons.append("frame-topology-difference")

    for identity in sorted(identity_matches):
        left_frame = left_records[identity]
        right_frame = right_records[identity]
        if left_frame["parent_chain"] != right_frame["parent_chain"]:
            reasons.append("frame-parent-chain-difference")
        if left_frame["host"]["geometry"] != right_frame["host"]["geometry"]:
            reasons.append("frame-host-geometry-difference")
        if left_frame["visibility"] != right_frame["visibility"]:
            reasons.append("frame-visibility-difference")
        if left_frame["boundary"] != right_frame["boundary"]:
            reasons.append("frame-sandbox-opaque-boundary-difference")
        left_generation = left_frame["document"]["generation"]
        right_generation = right_frame["document"]["generation"]
        if left_generation is None or right_generation is None:
            reasons.append("frame-document-generation-unobservable")
        elif left_generation != right_generation:
            reasons.append("frame-document-generation-difference")
        left_phase = left_frame["document"]["navigation_phase"]
        right_phase = right_frame["document"]["navigation_phase"]
        if not left_phase or not right_phase or "unknown" in {
            left_phase,
            right_phase,
        }:
            reasons.append("frame-navigation-phase-unobservable")
        elif left_phase != right_phase:
            reasons.append("frame-navigation-phase-difference")
        if left_frame["observation"]["url"] != right_frame["observation"]["url"]:
            reasons.append("frame-url-observation-difference")
        if left_frame["observation"]["src"] != right_frame["observation"]["src"]:
            reasons.append("frame-src-observation-difference")

    reasons = _dedupe(reasons)
    observation_complete = (
        left["boundary_observation_complete"]
        and right["boundary_observation_complete"]
    )
    comparable = not reasons
    return {
        "schema_version": FRAME_BOUNDARY_SCHEMA,
        "profile_id": RENDERED_FRAME_BOUNDARY_SCOPE,
        "comparable": comparable,
        "reasons": reasons,
        "identity_fields": list(IDENTITY_FIELDS),
        "geometry_fields": list(GEOMETRY_FIELDS),
        "identity_match_count": len(identity_matches),
        "left_frame_count": len(left_keys),
        "right_frame_count": len(right_keys),
        "left": left,
        "right": right,
        "boundary_observation_complete": observation_complete,
        "excluded": {
            "left": left["exclusions"],
            "right": right["exclusions"],
        },
        "unobservable": _dedupe_objects([
            *left["unobservable"],
            *right["unobservable"],
        ]),
        "opaque_contents_observable": False,
        "claims": (
            ["rendered-frame-boundary-equivalent"]
            if comparable
            else []
        ),
        "note": (
            "URL and source are observed attributes, not frame identity. "
            "Opaque-frame internals are not observable and are never equated "
            "from placeholders or boundary matches."
        ),
    }


def build_frame_boundary_snapshot(page_state: dict[str, Any]) -> dict[str, Any]:
    raw_inventory = page_state.get("frame_inventory")
    inventory_observable = isinstance(raw_inventory, list)
    inventory = raw_inventory if inventory_observable else []
    records: dict[str, dict[str, Any]] = {}
    exclusions: list[dict[str, Any]] = []
    unobservable: list[dict[str, Any]] = []
    complete = inventory_observable
    for frame in inventory:
        if not isinstance(frame, dict):
            continue
        if frame.get("rendered") is not True:
            exclusions.append({
                "path": str(frame.get("path") or ""),
                "reason": "not-rendered",
                "width": _number(frame.get("width")),
                "height": _number(frame.get("height")),
                "display": str(frame.get("display") or ""),
                "visibility": str(frame.get("visibility") or ""),
                "opacity": _number(frame.get("opacity")),
            })
            continue
        scope_path = str(frame.get("scope_path") or frame.get("path") or "")
        if not scope_path:
            complete = False
            continue
        parent_chain = _parent_chain(scope_path)
        generation = _optional_int(frame.get("document_generation"))
        navigation_phase = str(frame.get("navigation_phase") or "unknown")
        sandbox_tokens = sorted({
            str(item)
            for item in (frame.get("sandbox_tokens") or [])
            if str(item)
        })
        opaque = bool(frame.get("opaque_frame"))
        record = {
            "identity": {
                "scope_path": scope_path,
                "parent_chain": parent_chain,
                "visible_index": _optional_int(frame.get("visible_index")),
                "depth": _optional_int(frame.get("depth")),
            },
            "parent_chain": parent_chain,
            "host": {
                "geometry": {
                    name: _number(frame.get(name))
                    for name in GEOMETRY_FIELDS
                },
            },
            "visibility": {
                "display": str(frame.get("display") or ""),
                "visibility": str(frame.get("visibility") or ""),
                "opacity": _number(frame.get("opacity")),
            },
            "boundary": {
                "sandbox_present": bool(frame.get("sandbox_present")),
                "sandbox_tokens": sandbox_tokens,
                "same_origin": frame.get("same_origin"),
                "accessible": bool(frame.get("accessible")),
                "opaque_frame": opaque,
                "opaque_reason": frame.get("opaque_reason"),
            },
            "document": {
                "generation": generation,
                "navigation_phase": navigation_phase,
                "navigation_state": str(frame.get("navigation_state") or ""),
            },
            "observation": {
                "url": str(frame.get("url") or ""),
                "url_key": normalize_capture_url(str(frame.get("url") or "")),
                "src": str(frame.get("src") or ""),
            },
        }
        records[scope_path] = record
        if generation is None or navigation_phase == "unknown":
            complete = False
        if opaque:
            unobservable.append({
                "scope": scope_path,
                "opaque_reason": frame.get("opaque_reason"),
                "scope_limited_to_boundary": True,
            })
    return {
        "inventory_observable": inventory_observable,
        "boundary_observation_complete": complete,
        "frame_count": len(records),
        "frames": [records[key] for key in sorted(records)],
        "by_identity": records,
        "exclusions": exclusions,
        "unobservable": unobservable,
    }


def _parent_chain(scope_path: str) -> list[str]:
    parts = [part for part in scope_path.split("/") if part]
    if not parts or parts[0] != "root":
        return []
    result = [parts[0]]
    current = parts[0]
    for part in parts[1:-1]:
        current = f"{current}/{part}"
        result.append(current)
    return result


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _dedupe_objects(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for value in values:
        key = tuple(sorted(
            (name, str(content))
            for name, content in value.items()
        ))
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return sorted(result, key=lambda item: str(item.get("scope") or ""))
