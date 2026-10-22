"""Stable asset identity and object-fit crop metadata."""
from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import unquote_to_bytes


_SVG_SIZE = re.compile(
    rb"""<svg\b[^>]*\bwidth=["']?([0-9.]+)(?:px)?["']?[^>]*\bheight=["']?([0-9.]+)(?:px)?["']?""",
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
        match = _SVG_SIZE.search(raw)
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
