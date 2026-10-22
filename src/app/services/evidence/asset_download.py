"""Bounded, opt-in download helper for reference-only P1 assets."""
from __future__ import annotations

import hashlib
import ipaddress
import socket
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class AssetDownloadPolicy:
    max_assets: int = 5
    max_bytes_per_asset: int = 2 * 1024 * 1024
    max_total_bytes: int = 20 * 1024 * 1024
    timeout_seconds: float = 10.0
    max_redirects: int = 3
    allow_private_hosts: bool = False
    allowed_mime_prefixes: tuple[str, ...] = ("image/",)
    user_agent: str = "FigmaAutoAgent-P1/1.0"

    def __post_init__(self) -> None:
        if self.max_assets <= 0:
            raise ValueError("max_assets must be positive")
        if self.max_bytes_per_asset <= 0:
            raise ValueError("max_bytes_per_asset must be positive")
        if self.max_total_bytes < self.max_bytes_per_asset:
            raise ValueError("max_total_bytes cannot be smaller than max_bytes_per_asset")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class AssetDownloadError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def validate_remote_asset_url(
    url: str,
    policy: AssetDownloadPolicy,
    *,
    resolver: Callable[..., list[Any]] = socket.getaddrinfo,
) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise AssetDownloadError("unsupported-scheme", f"unsupported URL scheme: {parsed.scheme}")
    host = parsed.hostname
    if not host:
        raise AssetDownloadError("missing-host", "asset URL has no hostname")
    if policy.allow_private_hosts:
        return value
    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        try:
            resolved = resolver(host, None, type=socket.SOCK_STREAM)
            addresses = [
                ipaddress.ip_address(item[4][0])
                for item in resolved
                if item and item[4]
            ]
        except (OSError, ValueError) as exc:
            raise AssetDownloadError("dns-failed", f"cannot resolve asset host {host!r}") from exc
    if not addresses:
        raise AssetDownloadError("dns-empty", f"asset host resolved to no addresses: {host!r}")
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise AssetDownloadError(
                "private-address",
                f"asset host resolves to a non-public address: {address}",
            )
    return value


def inspect_asset_payload(
    payload: bytes,
    *,
    content_type: str,
    policy: AssetDownloadPolicy,
) -> dict[str, Any]:
    if len(payload) > policy.max_bytes_per_asset:
        raise AssetDownloadError(
            "size-exceeded",
            f"asset exceeds max_bytes_per_asset: {len(payload)}",
        )
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type == "image/jpg":
        normalized_type = "image/jpeg"
    detected = _detect_mime(payload)
    if detected is None:
        raise AssetDownloadError("unsupported-mime", "asset bytes do not match a supported image type")
    if not normalized_type:
        raise AssetDownloadError("mime-missing", "asset response has no MIME type")
    if not any(normalized_type.startswith(prefix) for prefix in policy.allowed_mime_prefixes):
        raise AssetDownloadError("mime-not-allowed", f"asset MIME is not allowed: {normalized_type}")
    if detected != normalized_type:
        raise AssetDownloadError(
            "mime-mismatch",
            f"asset MIME mismatch: header={normalized_type}, bytes={detected}",
        )
    return {
        "mime": detected,
        "extension": _asset_extension(detected),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def download_asset(
    url: str,
    policy: AssetDownloadPolicy,
) -> dict[str, Any]:
    source_url = validate_remote_asset_url(url, policy)
    redirect_handler = _ValidatingRedirectHandler(policy)
    opener = urllib.request.build_opener(redirect_handler)
    request = urllib.request.Request(
        source_url,
        headers={
            "User-Agent": policy.user_agent,
            "Accept": "image/*",
        },
    )
    try:
        with opener.open(request, timeout=policy.timeout_seconds) as response:
            final_url = validate_remote_asset_url(response.geturl(), policy)
            content_type = response.headers.get("Content-Type", "")
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > policy.max_bytes_per_asset:
                        raise AssetDownloadError(
                            "size-exceeded",
                            f"Content-Length exceeds max_bytes_per_asset: {content_length}",
                        )
                except ValueError:
                    pass
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > policy.max_bytes_per_asset:
                    raise AssetDownloadError(
                        "size-exceeded",
                        f"asset exceeded max_bytes_per_asset: >{policy.max_bytes_per_asset}",
                    )
                chunks.append(chunk)
            payload = b"".join(chunks)
    except AssetDownloadError:
        raise
    except Exception as exc:  # noqa: BLE001 - network failures are typed evidence
        raise AssetDownloadError("download-failed", f"{type(exc).__name__}: {exc}") from exc
    inspected = inspect_asset_payload(
        payload,
        content_type=content_type,
        policy=policy,
    )
    return {
        "source_url": source_url,
        "final_url": final_url,
        "payload": payload,
        **inspected,
    }


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, policy: AssetDownloadPolicy):
        self.policy = policy
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirect_count += 1
        if self.redirect_count > self.policy.max_redirects:
            raise AssetDownloadError("too-many-redirects", "asset download exceeded max redirects")
        validate_remote_asset_url(newurl, self.policy)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _detect_mime(payload: bytes) -> str | None:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    head = payload[:4096].decode("utf-8", errors="ignore").lstrip().lower()
    if head.startswith("<?xml") and "<svg" in head:
        return "image/svg+xml"
    if head.startswith("<svg") or "<svg" in head[:512]:
        return "image/svg+xml"
    return None


def _asset_extension(mime: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }.get(mime, ".bin")
