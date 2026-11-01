"""Recover frozen asset URLs through the page's browser context."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import ipaddress
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import urlparse

from PIL import Image

from src.app.services.structure.asset_fusion import fuse_asset_record
from src.app.services.structure.asset_metadata import (
    attach_verified_source_identity,
)


RequestGet = Callable[..., Mapping[str, Any]]
_RASTER_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class AssetRecoveryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def recover_network_assets(
    design: Mapping[str, Any],
    *,
    page_url: str,
    output_dir: str | Path,
    request_get: RequestGet | None = None,
    max_assets: int = 80,
    max_bytes_per_asset: int = 2 * 1024 * 1024,
    max_total_bytes: int = 40 * 1024 * 1024,
    timeout_ms: int = 15000,
) -> dict[str, Any]:
    """Recover only referenced HTTPS image URLs and retain verified bytes."""
    if request_get is None:
        with _browser_request_transport(page_url, timeout_ms=timeout_ms) as transport:
            return _recover_with_transport(
                design,
                page_url=page_url,
                output_dir=output_dir,
                request_get=transport,
                max_assets=max_assets,
                max_bytes_per_asset=max_bytes_per_asset,
                max_total_bytes=max_total_bytes,
                timeout_ms=timeout_ms,
            )
    return _recover_with_transport(
        design,
        page_url=page_url,
        output_dir=output_dir,
        request_get=request_get,
        max_assets=max_assets,
        max_bytes_per_asset=max_bytes_per_asset,
        max_total_bytes=max_total_bytes,
        timeout_ms=timeout_ms,
    )


def _recover_with_transport(
    design: Mapping[str, Any],
    *,
    page_url: str,
    output_dir: str | Path,
    request_get: RequestGet,
    max_assets: int,
    max_bytes_per_asset: int,
    max_total_bytes: int,
    timeout_ms: int,
) -> dict[str, Any]:
    destination = Path(output_dir)
    assets_dir = destination / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    urls, expected_sizes = _source_urls(design)
    rows: list[dict[str, Any]] = []
    verified: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for source_url in urls[: max(0, int(max_assets))]:
        try:
            _validate_source_url(source_url)
            response = request_get(
                source_url,
                referer=page_url,
                timeout_ms=timeout_ms,
            )
            status = int(response.get("status") or 0)
            if status != 200:
                raise AssetRecoveryError(
                    "http-status",
                    f"source returned HTTP {status}",
                )
            headers = response.get("headers") or {}
            content_type = str(headers.get("content-type") or "").lower()
            if not content_type.startswith("image/"):
                raise AssetRecoveryError(
                    "non-image-content-type",
                    f"unexpected content type: {content_type or '(missing)'}",
                )
            body = response.get("body")
            if not isinstance(body, bytes) or not body:
                raise AssetRecoveryError(
                    "empty-response-body",
                    "source response body is empty",
                )
            if len(body) > max_bytes_per_asset:
                raise AssetRecoveryError(
                    "asset-size-exceeded",
                    f"source exceeds {max_bytes_per_asset} bytes",
                )
            if total_bytes + len(body) > max_total_bytes:
                raise AssetRecoveryError(
                    "total-size-exceeded",
                    f"source total exceeds {max_total_bytes} bytes",
                )
            mime, natural_size = _image_identity(body)
            if mime is None or natural_size is None:
                raise AssetRecoveryError(
                    "decode-failed",
                    "source bytes are not a supported raster image",
                )
            expected = expected_sizes.get(source_url)
            if expected is not None and not _natural_size_matches(
                natural_size,
                expected,
            ):
                raise AssetRecoveryError(
                    "natural-size-mismatch",
                    f"decoded size {natural_size} != DOM size {expected}",
                )
            digest = hashlib.sha256(body).hexdigest()
            extension = _RASTER_EXTENSIONS.get(mime, ".img")
            target = assets_dir / f"{digest}{extension}"
            if not target.exists():
                target.write_bytes(body)
            if _file_sha256(target) != digest:
                raise AssetRecoveryError(
                    "retained-hash-mismatch",
                    "retained source bytes do not match the response hash",
                )
            total_bytes += len(body)
            locator = f"assets/{target.name}"
            verified[source_url] = {
                "sha256": digest,
                "mime": mime,
                "natural_size": list(natural_size),
                "locator": locator,
                "size_bytes": len(body),
            }
            rows.append(
                {
                    "source_url": source_url,
                    "status": "verified-original",
                    **verified[source_url],
                    "bytes_present": True,
                    "error_code": None,
                    "error": "",
                }
            )
        except (AssetRecoveryError, OSError, TypeError, ValueError) as exc:
            rows.append(
                {
                    "source_url": source_url,
                    "status": "reference-only",
                    "sha256": None,
                    "mime": None,
                    "natural_size": None,
                    "locator": None,
                    "size_bytes": None,
                    "bytes_present": False,
                    "error_code": getattr(exc, "code", type(exc).__name__),
                    "error": str(exc),
                }
            )
    upgraded = copy.deepcopy(dict(design))
    _apply_verified_sources(upgraded, verified, output_dir=destination)
    status_counts = {
        "verified-original": len(verified),
        "reference-only": len(rows) - len(verified),
    }
    result = {
        "schema_version": "dom-network-asset-recovery/1.0",
        "page_url": page_url,
        "status_counts": status_counts,
        "verified_url_count": len(verified),
        "recovered_use_count": sum(
            str(
                ((item.get("assetIdentity") or {}).get("asset_record") or {})
                .get("source_identity", {})
                .get("status")
            )
            == "verified-original"
            for item in upgraded.get("elements") or []
            if isinstance(item, Mapping) and item.get("type") == "image"
        ),
        "rows": rows,
        "design": upgraded,
    }
    (destination / "source_probes.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _source_urls(
    design: Mapping[str, Any],
) -> tuple[list[str], dict[str, tuple[float, float]]]:
    urls: list[str] = []
    expected_sizes: dict[str, tuple[float, float]] = {}
    seen: set[str] = set()
    for item in design.get("elements") or []:
        if not isinstance(item, Mapping) or item.get("type") != "image":
            continue
        record = (item.get("assetIdentity") or {}).get("asset_record") or {}
        source = record.get("source_identity") or {}
        if source.get("status") != "reference-only":
            continue
        url = str(source.get("source_url") or "").strip()
        if not url:
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
        size = source.get("natural_size")
        if (
            url not in expected_sizes
            and isinstance(size, (list, tuple))
            and len(size) == 2
        ):
            try:
                expected_sizes[url] = (float(size[0]), float(size[1]))
            except (TypeError, ValueError):
                pass
    return urls, expected_sizes


def _apply_verified_sources(
    design: dict[str, Any],
    verified: Mapping[str, Mapping[str, Any]],
    *,
    output_dir: Path,
) -> None:
    for item in design.get("elements") or []:
        if not isinstance(item, dict) or item.get("type") != "image":
            continue
        identity = item.get("assetIdentity") or {}
        record = identity.get("asset_record") or {}
        source = record.get("source_identity") or {}
        url = str(source.get("source_url") or "").strip()
        recovered = verified.get(url)
        if not isinstance(recovered, Mapping):
            continue
        upgraded = attach_verified_source_identity(
            record,
            payload_sha256=str(recovered["sha256"]),
            mime=str(recovered["mime"]),
            natural_size=recovered["natural_size"],
            retained_locator=str(recovered["locator"]),
        )
        item["assetIdentity"] = {**identity, "asset_record": upgraded}
        item["displayPayload"] = dict(upgraded["display_payload"])
        item["replacement"] = dict(upgraded["replacement"])
        item["sourceResolution"] = fuse_asset_record(upgraded)
        locator = Path(str(recovered["locator"]))
        payload_path = output_dir / locator
        if payload_path.is_file():
            item["imageBase64"] = _display_image_base64(
                payload_path.read_bytes(),
                mime=str(recovered["mime"]),
            )
        item.pop("displaySourceCrop", None)
        item.pop("generatedImageRequired", None)
        item.pop("generationReferenceImageBase64", None)
        item.pop("sourceCropContamination", None)
        item.pop("imagePrompt", None)


def _display_image_base64(payload: bytes, *, mime: str) -> str:
    if mime in {"image/png", "image/jpeg"}:
        return base64.b64encode(payload).decode("ascii")
    with Image.open(io.BytesIO(payload)) as source:
        image = source.convert("RGBA" if "A" in source.getbands() else "RGB")
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def _validate_source_url(source_url: str) -> None:
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AssetRecoveryError(
            "invalid-source-url",
            "source URL must use HTTPS and include a hostname",
        )
    host = parsed.hostname.lower()
    if host == "localhost":
        raise AssetRecoveryError("private-host", "private hosts are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise AssetRecoveryError("private-host", "private hosts are not allowed")


def _natural_size_matches(
    actual: tuple[float, float],
    expected: tuple[float, float],
) -> bool:
    if all(
        abs(a - b) <= 1.0
        for a, b in zip(actual, expected, strict=True)
    ):
        return True
    actual_width, actual_height = actual
    expected_width, expected_height = expected
    if min(actual_width, actual_height, expected_width, expected_height) <= 0:
        return False
    actual_ratio = actual_width / actual_height
    expected_ratio = expected_width / expected_height
    return abs(actual_ratio - expected_ratio) <= expected_ratio * 0.03


def _image_identity(payload: bytes) -> tuple[str | None, tuple[float, float] | None]:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            mime = str(Image.MIME.get(str(image.format or "").upper()) or "")
            if mime not in _RASTER_EXTENSIONS:
                return None, None
            return mime, (float(image.width), float(image.height))
    except Exception:
        return None, None


@contextmanager
def _browser_request_transport(
    page_url: str,
    *,
    timeout_ms: int,
) -> Iterator[RequestGet]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                viewport={"width": 1440, "height": 900},
            )
            page = context.new_page()
            page.goto(
                page_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            def request_get(
                source_url: str,
                *,
                referer: str,
                timeout_ms: int,
            ) -> dict[str, Any]:
                response = page.request.get(
                    source_url,
                    headers={"Referer": referer},
                    timeout=timeout_ms,
                )
                return {
                    "status": response.status,
                    "headers": response.headers,
                    "body": response.body(),
                }

            yield request_get
            context.close()
        finally:
            browser.close()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
