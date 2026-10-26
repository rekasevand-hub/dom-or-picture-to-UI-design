"""Stable asset identity and object-fit crop metadata."""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote_to_bytes


_SVG_SIZE = re.compile(
    rb"""<svg\b[^>]*\bwidth=["']?([0-9.]+)(?:px)?["']?[^>]*\bheight=["']?([0-9.]+)(?:px)?["']?""",
    re.IGNORECASE,
)
_SVG_VIEWBOX = re.compile(
    rb"""<svg\b[^>]*\bviewBox=["']?\s*[0-9.+-]+\s+[0-9.+-]+\s+([0-9.]+)\s+([0-9.]+)["']?""",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AssetIdentity:
    source_url: str | None
    payload_sha256: str | None
    natural_size: tuple[float, float] | None
    replacement_mode: str
    status: str

    @property
    def replacement_allowed(self) -> bool:
        return self.status in {"ready", "retained-bytes"}

    def to_dict(self) -> dict:
        return {
            "source_url": self.source_url,
            "payload_sha256": self.payload_sha256,
            "natural_size": list(self.natural_size) if self.natural_size else None,
            "replacement_mode": self.replacement_mode,
            "status": self.status,
            "replacement_allowed": self.replacement_allowed,
        }


def resolve_asset_identity(
    *,
    source_url: str | None = None,
    payload_sha256: str | None = None,
    natural_size: tuple[float, float] | list[float] | None = None,
    url_expired: bool = False,
    retained_bytes_present: bool = False,
) -> AssetIdentity:
    """Classify whether an asset can be replaced without trusting a URL alone."""
    normalized_size = _normalize_natural_size(natural_size)
    digest = str(payload_sha256 or "").strip().lower() or None
    if digest is not None and not re.fullmatch(r"[0-9a-f]{64}", digest):
        digest = None
    if digest is None and normalized_size is None:
        return AssetIdentity(
            source_url=source_url or None,
            payload_sha256=None,
            natural_size=None,
            replacement_mode="reference-only" if source_url else "unavailable",
            status="reference-only" if source_url else "blocked-missing-source",
        )
    if digest is None or normalized_size is None:
        return AssetIdentity(
            source_url=source_url or None,
            payload_sha256=digest,
            natural_size=normalized_size,
            replacement_mode="incomplete-identity",
            status="blocked-incomplete-identity",
        )
    if url_expired:
        mode = "retained-bytes" if retained_bytes_present else "blocked-expired-url"
        status = "retained-bytes" if retained_bytes_present else "blocked-expired-url"
        return AssetIdentity(
            source_url=source_url or None,
            payload_sha256=digest,
            natural_size=normalized_size,
            replacement_mode=mode,
            status=status,
        )
    return AssetIdentity(
        source_url=source_url or None,
        payload_sha256=digest,
        natural_size=normalized_size,
        replacement_mode="original-bytes",
        status="ready",
    )


def build_asset_record(
    *,
    sample_id: str,
    node_index: int,
    source_kind: str,
    source: str | None,
    natural_size: tuple[float, float] | list[float] | None,
    source_payload_sha256: str | None = None,
    mime: str | None = None,
    source_bytes_present: bool = False,
    source_provenance: str | None = None,
    display_box: tuple[float, float, float, float] | list[float] | None = None,
    display_payload_sha256: str | None = None,
    screenshot_sha256: str | None = None,
    source_rect: tuple[float, float, float, float] | list[float] | None = None,
    object_fit: str = "fill",
    load_status: str = "loaded",
) -> dict[str, Any]:
    """Describe one asset use without conflating source and display bytes."""
    normalized_source = str(source or "").strip() or None
    normalized_mime = str(mime or "").strip().lower() or None
    normalized_size = _normalize_natural_size(natural_size)
    digest = _normalize_sha256(source_payload_sha256)
    display_digest = _normalize_sha256(display_payload_sha256)
    screenshot_digest = _normalize_sha256(screenshot_sha256)
    normalized_display_box = _normalize_box(display_box)
    normalized_source_rect = _normalize_box(source_rect)
    source_kind_value = str(source_kind or "unknown")
    sample = str(sample_id or "unknown")
    index = int(node_index)
    use_id = f"{sample}:{index}:{source_kind_value}"

    missing_source = str(load_status or "").lower() in {
        "missing",
        "failed",
        "error",
        "broken",
    }
    source_identity = _source_identity_record(
        source=normalized_source,
        payload_sha256=digest,
        mime=normalized_mime,
        natural_size=normalized_size,
        bytes_present=bool(source_bytes_present),
        provenance=source_provenance,
        missing_source=missing_source,
    )
    if source_identity["status"] == "verified-original":
        asset_id = f"asset:sha256:{digest}"
    elif source_identity["status"] == "reference-only":
        asset_id = f"asset:ref:{_sha256(normalized_source.encode('utf-8'))}"
    else:
        asset_id = f"asset:unverified:{_sha256(use_id.encode('utf-8'))[:16]}"

    display_available = display_digest is not None
    display_payload = {
        "status": "available" if display_available else "missing",
        "kind": "screenshot-crop" if display_available else "none",
        "payload_sha256": display_digest,
        "screenshot_sha256": screenshot_digest,
        "display_box": normalized_display_box,
        "source_rect": normalized_source_rect,
        "object_fit": str(object_fit or "fill").strip().lower(),
        "original": False,
        "reference_only": True,
    }
    is_missing = missing_source or not display_available
    missing = {
        "is_missing": is_missing,
        "status": (
            "missing-source"
            if missing_source
            else "missing-display"
            if not display_available
            else "loaded"
        ),
        "reason": (
            "The source image did not load."
            if missing_source
            else "No display region or screenshot crop is available."
            if not display_available
            else ""
        ),
        "outcome": "partial-not-pass" if is_missing else "pass",
    }
    replacement_allowed = source_identity["status"] == "verified-original"
    replacement = {
        "allowed": replacement_allowed,
        "mode": "source-bytes" if replacement_allowed else "none",
        "reason": (
            "Verified original source bytes are retained and can replace the "
            "node fill."
            if replacement_allowed
            else "Screenshot crops and reference-only URLs are not replaceable "
            "original assets."
        ),
        "figma_runtime": "not-evaluated",
    }
    return {
        "schema_version": "dom-asset-record/1.0",
        "asset_id": asset_id,
        "source_identity": source_identity,
        "display_payload": display_payload,
        "replacement": replacement,
        "missing": missing,
        "use": {
            "use_id": use_id,
            "node_index": index,
            "source_kind": source_kind_value,
            "display_box": normalized_display_box,
        },
    }


def deduplicate_asset_records(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Group source identities while retaining every display use."""
    assets: dict[str, dict[str, Any]] = {}
    uses: list[dict[str, Any]] = []
    missing_uses: list[dict[str, Any]] = []
    for record in records:
        asset_id = str(record.get("asset_id") or "")
        if not asset_id:
            continue
        assets.setdefault(
            asset_id,
            {
                "asset_id": asset_id,
                "source_identity": dict(record.get("source_identity") or {}),
                "replacement": dict(record.get("replacement") or {}),
            },
        )
        use = {
            **dict(record.get("use") or {}),
            "asset_id": asset_id,
            "display_payload": dict(record.get("display_payload") or {}),
            "missing": dict(record.get("missing") or {}),
        }
        uses.append(use)
        if bool((record.get("missing") or {}).get("is_missing")):
            missing_uses.append(use)
    status_counts: dict[str, int] = {}
    for asset in assets.values():
        status = str((asset.get("source_identity") or {}).get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "asset_count": len(assets),
        "use_count": len(uses),
        "missing_use_count": len(missing_uses),
        "assets": list(assets.values()),
        "uses": uses,
        "missing_uses": missing_uses,
        "status_counts": status_counts,
    }


def attach_display_payload(
    record: dict[str, Any],
    *,
    payload_sha256: str | None,
    screenshot_sha256: str | None = None,
    display_box: tuple[float, float, float, float] | list[float] | None,
) -> dict[str, Any]:
    """Attach the actual rendered payload without changing source identity."""
    updated = {
        **record,
        "source_identity": dict(record.get("source_identity") or {}),
        "replacement": dict(record.get("replacement") or {}),
        "missing": dict(record.get("missing") or {}),
        "use": dict(record.get("use") or {}),
    }
    payload_digest = _normalize_sha256(payload_sha256)
    normalized_box = _normalize_box(display_box)
    previous_display = record.get("display_payload") or {}
    available = payload_digest is not None or normalized_box is not None
    updated["display_payload"] = {
        **dict(previous_display),
        "status": "available" if available else "missing",
        "kind": "screenshot-crop" if available else "none",
        "payload_sha256": payload_digest,
        "screenshot_sha256": _normalize_sha256(screenshot_sha256),
        "display_box": normalized_box,
        "original": False,
        "reference_only": True,
    }
    missing_source = (
        bool(updated["missing"].get("is_missing"))
        and str(updated["missing"].get("status")) == "missing-source"
    )
    missing_display = not available
    updated["missing"] = {
        **updated["missing"],
        "is_missing": missing_source or missing_display,
        "status": (
            "missing-source"
            if missing_source
            else "missing-display"
            if missing_display
            else "loaded"
        ),
        "outcome": (
            "partial-not-pass" if missing_source or missing_display else "pass"
        ),
    }
    return updated


def attach_verified_source_identity(
    record: dict[str, Any],
    *,
    payload_sha256: str,
    mime: str,
    natural_size: tuple[float, float] | list[float] | None,
    provenance: str = "network-response",
    retained_locator: str | None = None,
) -> dict[str, Any]:
    """Upgrade source identity only when retained, validated bytes exist."""
    digest = _normalize_sha256(payload_sha256)
    normalized_mime = str(mime or "").strip().lower()
    normalized_size = _normalize_natural_size(natural_size)
    if (
        digest is None
        or not normalized_mime.startswith("image/")
        or normalized_size is None
    ):
        raise ValueError("verified source requires sha256, image MIME and size")
    updated = {
        **record,
        "source_identity": dict(record.get("source_identity") or {}),
        "display_payload": dict(record.get("display_payload") or {}),
        "replacement": dict(record.get("replacement") or {}),
        "missing": dict(record.get("missing") or {}),
        "use": dict(record.get("use") or {}),
    }
    source = updated["source_identity"]
    source.update(
        {
            "status": "verified-original",
            "source_kind": "network-response",
            "payload_sha256": digest,
            "mime": normalized_mime,
            "natural_size": list(normalized_size),
            "bytes_present": True,
            "provenance": provenance,
            "reason": "",
        }
    )
    if retained_locator:
        source["retained_bytes_locator"] = retained_locator
    updated["asset_id"] = f"asset:sha256:{digest}"
    updated["replacement"] = {
        **updated["replacement"],
        "allowed": True,
        "mode": "source-bytes",
        "reason": (
            "Verified original source bytes are retained and can replace the "
            "node fill."
        ),
    }
    display_available = (
        updated["display_payload"].get("status") == "available"
    ) and _normalize_sha256(
        updated["display_payload"].get("payload_sha256")
    ) is not None
    updated["missing"] = {
        **updated["missing"],
        "is_missing": not display_available,
        "status": "loaded" if display_available else "missing-display",
        "reason": "" if display_available else "No display payload is available.",
        "outcome": "pass" if display_available else "partial-not-pass",
    }
    return updated


def _source_identity_record(
    *,
    source: str | None,
    payload_sha256: str | None,
    mime: str | None,
    natural_size: tuple[float, float] | None,
    bytes_present: bool,
    provenance: str | None,
    missing_source: bool,
) -> dict[str, Any]:
    source_url = (
        source if source and source.startswith(("http://", "https://")) else None
    )
    if missing_source:
        return {
            "status": "missing",
            "source_kind": "none",
            "source_url": source_url,
            "payload_sha256": payload_sha256,
            "mime": mime,
            "natural_size": list(natural_size) if natural_size else None,
            "bytes_present": False,
            "provenance": provenance,
            "reason": "The source image did not load.",
        }
    if source is None and payload_sha256 is None:
        return {
            "status": "unavailable",
            "source_kind": "none",
            "source_url": None,
            "payload_sha256": None,
            "mime": mime,
            "natural_size": list(natural_size) if natural_size else None,
            "bytes_present": False,
            "provenance": provenance,
            "reason": "No source asset identity is available.",
        }
    if not bytes_present and source_url is not None and payload_sha256 is None:
        return {
            "status": "reference-only",
            "source_kind": "remote-url",
            "source_url": source_url,
            "payload_sha256": None,
            "mime": mime,
            "natural_size": list(natural_size) if natural_size else None,
            "bytes_present": False,
            "provenance": "remote-url",
            "reason": "A URL alone does not prove original asset bytes.",
        }
    missing_fields = []
    if payload_sha256 is None:
        missing_fields.append("sha256")
    if mime is None:
        missing_fields.append("mime")
    if natural_size is None:
        missing_fields.append("natural-size")
    if not bytes_present:
        missing_fields.append("retained-bytes")
    if mime is not None and not mime.startswith("image/"):
        missing_fields.append("image-mime")
    if missing_fields:
        return {
            "status": "blocked-incomplete-identity",
            "source_kind": (
                "network-response"
                if provenance == "network-response"
                else "data-uri"
                if source and source.startswith("data:")
                else "unknown"
            ),
            "source_url": source_url,
            "payload_sha256": payload_sha256,
            "mime": mime,
            "natural_size": list(natural_size) if natural_size else None,
            "bytes_present": bytes_present,
            "provenance": provenance,
            "reason": "Incomplete identity: " + ", ".join(missing_fields),
        }
    source_identity_kind = (
        "network-response"
        if provenance == "network-response" or source_url is not None
        else "data-uri"
    )
    return {
        "status": "verified-original",
        "source_kind": source_identity_kind,
        "source_url": source_url,
        "payload_sha256": payload_sha256,
        "mime": mime,
        "natural_size": list(natural_size),
        "bytes_present": True,
        "provenance": provenance or source_identity_kind,
        "reason": "",
    }


def _normalize_box(
    value: tuple[float, float, float, float] | list[float] | None,
) -> list[float] | None:
    try:
        if value is None or len(value) != 4:
            return None
        values = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if not all(number == number and abs(number) != float("inf") for number in values):
        return None
    return [round(number, 3) for number in values]


def _normalize_sha256(value: str | None) -> str | None:
    digest = str(value or "").strip().lower() or None
    if digest is None or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return None
    return digest


def parse_data_uri_asset(source: str) -> dict:
    """Decode a data URI and return identity facts without writing bytes."""
    value = str(source or "")
    if not value.lower().startswith("data:") or "," not in value:
        return {
            "source_kind": "non-data-uri",
            "source": value,
            "sha256": _sha256(value.encode("utf-8")) if value else None,
            "mime": None,
            "byte_length": None,
            "natural_size": None,
            "bytes": None,
        }
    header, payload = value.split(",", 1)
    is_base64 = ";base64" in header.lower()
    mime = header[5:].split(";", 1)[0] or "application/octet-stream"
    try:
        raw = (
            base64.b64decode(payload, validate=False)
            if is_base64
            else unquote_to_bytes(payload)
        )
    except Exception:
        raw = b""
    natural_size = None
    if mime.lower() == "image/svg+xml":
        match = _SVG_SIZE.search(raw) or _SVG_VIEWBOX.search(raw)
        if match:
            natural_size = [float(match.group(1)), float(match.group(2))]
    return {
        "source_kind": "data-uri",
        "source": value,
        "sha256": _sha256(raw),
        "mime": mime,
        "byte_length": len(raw),
        "natural_size": natural_size,
        "bytes": raw,
    }


def object_fit_source_rect(
    *,
    display_size: list[float] | tuple[float, float],
    natural_size: list[float] | tuple[float, float],
    object_fit: str,
    object_position: str,
) -> dict:
    """Map a CSS replaced element to its source rectangle for cover/contain."""
    dw, dh = _positive_pair(display_size)
    nw, nh = _positive_pair(natural_size)
    fit = str(object_fit or "fill").strip().lower()
    x_ratio, y_ratio = _position_ratios(object_position)
    if dw <= 0 or dh <= 0 or nw <= 0 or nh <= 0:
        return {
            "source_rect": None,
            "scale": None,
            "object_fit": fit,
            "object_position": str(object_position or ""),
        }
    if fit == "cover":
        scale = max(dw / nw, dh / nh)
    elif fit == "contain":
        scale = min(dw / nw, dh / nh)
    else:
        scale = 1.0
    source_w = min(nw, dw / scale) if scale > 0 else nw
    source_h = min(nh, dh / scale) if scale > 0 else nh
    source_x = max(0.0, nw - source_w) * x_ratio
    source_y = max(0.0, nh - source_h) * y_ratio
    return {
        "source_rect": [
            round(source_x, 3),
            round(source_y, 3),
            round(source_w, 3),
            round(source_h, 3),
        ],
        "scale": round(scale, 6),
        "object_fit": fit,
        "object_position": str(object_position or ""),
    }


def _position_ratios(value: str) -> tuple[float, float]:
    parts = str(value or "50% 50%").split()
    if len(parts) == 1:
        parts *= 2
    return _position_component(parts[0], axis="x"), _position_component(
        parts[1],
        axis="y",
    )


def _position_component(value: str, *, axis: str) -> float:
    token = str(value or "center").strip().lower()
    if token in {"left", "top"}:
        return 0.0
    if token in {"right", "bottom"}:
        return 1.0
    if token == "center":
        return 0.5
    if token.endswith("%"):
        try:
            return min(1.0, max(0.0, float(token[:-1]) / 100.0))
        except ValueError:
            pass
    try:
        number = float(token)
    except ValueError:
        return 0.5
    return min(1.0, max(0.0, number))


def _positive_pair(value) -> tuple[float, float]:
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError):
        return 0.0, 0.0


def _normalize_natural_size(
    value: tuple[float, float] | list[float] | None,
) -> tuple[float, float] | None:
    width, height = _positive_pair(value)
    if width <= 0 or height <= 0:
        return None
    return round(width, 6), round(height, 6)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
