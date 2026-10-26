"""Ordered asset strategy fusion with explicit source and display provenance."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


_GENERATED_PROVENANCE_FIELDS = (
    "generator",
    "model",
    "input_reference",
    "prompt",
    "prompt_version",
    "review_status",
)


def fuse_asset_record(
    record: Mapping[str, Any],
    *,
    generated_candidates: Sequence[Mapping[str, Any]] = (),
    prefer_generated_for_icon_crop: bool = False,
) -> dict[str, Any]:
    """Apply source > capture > generated priority without changing identity."""
    identity = _identity_decision(record)
    capture = _capture_candidate(record)
    generated_rows: list[dict[str, Any]] = []
    selected_generated: Mapping[str, Any] | None = None
    blocked_generated = False
    icon_crop_preference = (
        prefer_generated_for_icon_crop
        and str((record.get("use") or {}).get("source_kind") or "") == "icon-crop"
    )
    for index, candidate in enumerate(generated_candidates):
        row, provenance = _generated_candidate(candidate, index=index)
        candidate_preferred = (
            icon_crop_preference
            and str(candidate.get("use_class") or "") == "icon-crop"
        )
        if capture["selected"] and not candidate_preferred:
            row["status"] = "rejected"
            row["reason"] = "higher-priority-capture-available"
        elif provenance is not None and selected_generated is None:
            row["status"] = "selected"
            row["reason"] = (
                "policy-prefers-generated-icon"
                if candidate_preferred
                else "capture-display-missing"
            )
            selected_generated = candidate
            row["provenance"] = provenance
        elif provenance is not None:
            row["status"] = "rejected"
            row["reason"] = "lower-priority-generated-candidate"
            row["provenance"] = provenance
        else:
            row["status"] = "blocked"
            blocked_generated = True
        generated_rows.append(row)

    selected_generated_row = next(
        (
            row
            for row in generated_rows
            if row["status"] == "selected"
            and row["reason"] == "policy-prefers-generated-icon"
        ),
        None,
    )
    using_generated_icon_policy = selected_generated is not None and (
        selected_generated_row is not None
    )
    if capture["selected"] and not using_generated_icon_policy:
        display = {
            "selected": "screenshot-crop",
            "original": False,
            "reference_only": True,
            "generated": False,
            "fallback_used": False,
            "provenance": {
                "kind": "screenshot-crop",
                "payload_sha256": capture["payload_sha256"],
                "screenshot_sha256": capture["screenshot_sha256"],
                "display_box": capture["display_box"],
                "source_rect": capture["source_rect"],
                "object_fit": capture["object_fit"],
            },
        }
        display_chain = "screenshot-crop"
    elif selected_generated is not None:
        display_row = next(
            row
            for row in generated_rows
            if row["status"] == "selected"
            and (
                row is selected_generated_row
                if using_generated_icon_policy
                else row["reason"] == "capture-display-missing"
            )
        )
        display = {
            "selected": "generated-approximation",
            "original": False,
            "reference_only": False,
            "generated": True,
            "fallback_used": True,
            "provenance": dict(display_row["provenance"]),
        }
        display_chain = "generated-approximation"
        if using_generated_icon_policy:
            capture["candidate"]["status"] = "rejected"
            capture["candidate"]["reason"] = "generated-icon-policy"
    else:
        display = {
            "selected": "missing",
            "original": False,
            "reference_only": False,
            "generated": False,
            "fallback_used": False,
            "provenance": None,
        }
        display_chain = "missing"

    identity_chain = _identity_chain_token(identity)
    if using_generated_icon_policy:
        status = "generated-icon-display"
    elif display["selected"] == "generated-approximation":
        status = "partial-generated-display"
    elif display["selected"] == "missing" and blocked_generated:
        status = "blocked-generated-provenance"
    elif display["selected"] == "missing":
        status = "partial-missing-display"
    elif identity["selected"] == "verified-source":
        status = "resolved-source-and-capture"
    else:
        status = "partial-unresolved-identity"

    candidates = [
        identity["candidate"],
        capture["candidate"],
        *generated_rows,
    ]
    diagnostics = [row["reason"] for row in candidates if row.get("reason")]
    return {
        "schema_version": "asset-strategy-fusion/1.0",
        "asset_id": str(record.get("asset_id") or ""),
        "use_id": str((record.get("use") or {}).get("use_id") or ""),
        "identity": {
            key: value for key, value in identity.items() if key != "candidate"
        },
        "display": display,
        "candidates": candidates,
        "fallback_chain": [identity_chain, display_chain],
        "status": status,
        "diagnostics": diagnostics,
        "figma_runtime": "not-evaluated",
    }


def _identity_decision(record: Mapping[str, Any]) -> dict[str, Any]:
    source = record.get("source_identity") or {}
    replacement = record.get("replacement") or {}
    status = str(source.get("status") or "unavailable")
    verified = status == "verified-original"
    if verified:
        selected = "verified-source"
        source_tier = (
            "recovered-network"
            if source.get("source_kind") == "network-response"
            or source.get("provenance") == "network-response"
            else "dom-source"
        )
        reason = ""
    else:
        selected = status
        source_tier = "none"
        reason = f"source-identity-{status}"
    provenance = {
        key: source.get(key)
        for key in (
            "status",
            "source_kind",
            "source_url",
            "payload_sha256",
            "mime",
            "natural_size",
            "bytes_present",
            "provenance",
        )
    }
    candidate_kind = "verified-source" if verified else selected
    candidate = {
        "kind": candidate_kind,
        "status": "selected" if verified else "rejected",
        "reason": reason,
        "original": verified,
        "replaceable": verified and bool(replacement.get("allowed")),
        "payload_sha256": source.get("payload_sha256"),
    }
    return {
        "selected": selected,
        "source_tier": source_tier,
        "original": verified,
        "replaceable": verified and bool(replacement.get("allowed")),
        "provenance": provenance,
        "candidate": candidate,
    }


def _capture_candidate(record: Mapping[str, Any]) -> dict[str, Any]:
    display = record.get("display_payload") or {}
    selected = (
        display.get("status") == "available"
        and display.get("kind") == "screenshot-crop"
        and _valid_sha256(display.get("payload_sha256"))
    )
    evidence = {
        "kind": "screenshot-crop",
        "status": "selected" if selected else "missing",
        "reason": "" if selected else "screenshot-crop-unavailable",
        "original": False,
        "replaceable": False,
        "payload_sha256": display.get("payload_sha256"),
    }
    return {
        "selected": selected,
        "candidate": evidence,
        "payload_sha256": display.get("payload_sha256"),
        "screenshot_sha256": display.get("screenshot_sha256"),
        "display_box": display.get("display_box"),
        "source_rect": display.get("source_rect"),
        "object_fit": display.get("object_fit"),
    }


def _generated_candidate(
    candidate: Mapping[str, Any],
    *,
    index: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not isinstance(candidate, Mapping):
        return (
            {
                "kind": "generated-approximation",
                "candidate_index": index,
                "status": "blocked",
                "reason": "generated-candidate-not-object",
                "original": False,
                "replaceable": False,
                "payload_sha256": None,
            },
            None,
        )
    missing = [
        name
        for name in _GENERATED_PROVENANCE_FIELDS
        if not str(candidate.get(name) or "").strip()
    ]
    digest = str(candidate.get("payload_sha256") or "").lower()
    if not _valid_sha256(digest):
        missing.append("payload_sha256")
    if not candidate.get("bytes_present"):
        missing.append("bytes_present")
    row = {
        "kind": "generated-approximation",
        "candidate_index": index,
        "status": "blocked" if missing else "rejected",
        "reason": (
            "missing-generated-provenance:" + ",".join(missing) if missing else ""
        ),
        "original": False,
        "replaceable": False,
        "payload_sha256": digest or None,
    }
    if candidate.get("use_class"):
        row["use_class"] = str(candidate["use_class"])
    if missing:
        return row, None
    provenance = {
        "generator": str(candidate["generator"]),
        "model": str(candidate["model"]),
        "input_reference": str(candidate["input_reference"]),
        "prompt": str(candidate["prompt"]),
        "prompt_version": str(candidate["prompt_version"]),
        "review_status": str(candidate["review_status"]),
        "payload_sha256": digest,
    }
    if candidate.get("use_class"):
        provenance["use_class"] = str(candidate["use_class"])
    return row, provenance


def _identity_chain_token(identity: Mapping[str, Any]) -> str:
    if identity.get("selected") == "verified-source":
        return str(identity.get("source_tier"))
    return str(identity.get("selected") or "unavailable")


def _valid_sha256(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "").lower()))
