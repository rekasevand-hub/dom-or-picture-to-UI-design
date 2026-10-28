from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.app.services.structure.capture_bundle import (
    CAPTURE_BUNDLE_FILENAME,
    load_capture_bundle,
)

ASSET_LEDGER_SCHEMA_VERSION = "dom-capture-assets/1.0"


def _asset_record(element: Mapping[str, Any]) -> dict[str, Any]:
    identity = element.get("assetIdentity")
    if isinstance(identity, Mapping):
        record = identity.get("asset_record")
        if isinstance(record, Mapping):
            return dict(record)
    record = element.get("asset_record")
    return dict(record) if isinstance(record, Mapping) else {}


def _status(record: Mapping[str, Any]) -> str:
    source = record.get("source_identity")
    source = source if isinstance(source, Mapping) else {}
    missing = record.get("missing")
    missing = missing if isinstance(missing, Mapping) else {}
    if bool(missing.get("is_missing")):
        return "missing"
    status = str(source.get("status") or "").lower()
    if status in {"verified-original", "verified"} and source.get("sha256") and (
        source.get("locator") or source.get("retained_path")
    ):
        return "verified"
    if status == "reference-only" or source.get("source_url"):
        return "reference-only"
    return "missing"


def build_asset_ledger(design: Mapping[str, Any]) -> dict[str, Any]:
    assets: dict[str, dict[str, Any]] = {}
    use_count = 0
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        record = _asset_record(element)
        if not record:
            continue
        source = record.get("source_identity")
        source = source if isinstance(source, Mapping) else {}
        status = _status(record)
        source_url = str(source.get("source_url") or "").strip()
        sha256 = str(source.get("sha256") or "").strip() or None
        key = source_url or sha256 or f"{element.get('id')}:{use_count}"
        use_count += 1
        row = assets.get(key)
        if row is None:
            row = {
                "source_url": source_url or None,
                "source_sha256": sha256,
                "mime": source.get("mime"),
                "natural_size": source.get("natural_size"),
                "retained_path": (
                    source.get("locator")
                    or source.get("retained_path")
                ),
                "byte_size": source.get("size_bytes"),
                "status": status,
                "use_count": 0,
            }
            assets[key] = row
        row["use_count"] += 1
        if status == "missing":
            row["status"] = "missing"
        elif status == "verified" and row["status"] == "reference-only":
            row["status"] = "verified"

    rows = list(assets.values())
    verified_count = sum(row["status"] == "verified" for row in rows)
    reference_only_count = sum(row["status"] == "reference-only" for row in rows)
    missing_count = sum(row["status"] == "missing" for row in rows)
    reference_count = len(rows)
    if reference_count == 0:
        status = "not-required"
    elif missing_count:
        status = "fail"
    elif reference_only_count:
        status = "warn"
    else:
        status = "pass"
    return {
        "schema_version": ASSET_LEDGER_SCHEMA_VERSION,
        "status": status,
        "success": status == "pass",
        "reference_count": reference_count,
        "use_count": use_count,
        "verified_count": verified_count,
        "reference_only_count": reference_only_count,
        "missing_count": missing_count,
        "assets": rows,
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_capture_bundle_assets(
    output_dir: Path,
    *,
    asset_manifest: str,
    asset_counts: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(output_dir).resolve()
    manifest = load_capture_bundle(root)
    relative = Path(asset_manifest)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("asset manifest must be a relative path inside the bundle")
    asset_path = (root / relative).resolve()
    try:
        asset_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("asset manifest is outside the capture bundle") from exc
    if not asset_path.is_file():
        raise FileNotFoundError(asset_path)
    manifest.setdefault("artifacts", {})["assets"] = {
        "path": relative.as_posix(),
        "bytes": asset_path.stat().st_size,
        "sha256": _hash_file(asset_path),
        "counts": {
            key: asset_counts.get(key)
            for key in (
                "reference_count",
                "verified_count",
                "reference_only_count",
                "missing_count",
            )
            if key in asset_counts
        },
    }
    (root / CAPTURE_BUNDLE_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
