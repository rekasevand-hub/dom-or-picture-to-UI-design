"""Materialize downloaded asset bytes into a new, auditable P1 sidecar."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.app.services.contracts import (
    canonical_hash,
    jsonable,
    validate_audit_bundle,
    validate_runtime_ir,
)


class AssetMaterializeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MaterializedAssetSidecar:
    output_dir: Path
    runtime_ir: dict[str, Any]
    audit_bundle: dict[str, Any]
    manifest: dict[str, Any]
    materialization: dict[str, Any]


def materialize_downloaded_assets(
    sidecar_dir: str | Path,
    downloads_dir: str | Path,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> MaterializedAssetSidecar:
    source = Path(sidecar_dir).resolve()
    downloads = Path(downloads_dir).resolve()
    destination = Path(output_dir).resolve()
    if destination == source or source in destination.parents:
        raise AssetMaterializeError("materialized output cannot be inside the source sidecar")
    if destination == downloads:
        raise AssetMaterializeError("materialized output cannot be the downloads directory")

    runtime_ir = _read_object(source / "runtime_ir.json")
    audit_bundle = _read_object(source / "audit_bundle.json")
    manifest = _read_object(source / "manifest.json")
    download_report = _read_object(downloads / "asset_downloads.json")
    issues = list(validate_runtime_ir(runtime_ir)) + list(validate_audit_bundle(audit_bundle))
    if issues:
        raise AssetMaterializeError(f"source sidecar validation failed: {issues}")

    rows = [
        item for item in download_report.get("rows") or []
        if isinstance(item, dict) and item.get("status") == "downloaded"
    ]
    retention = runtime_ir.get("retention") or {}
    expires_at = retention.get("evidence_expires_at")
    downloaded_bytes = 0
    materialized_rows: list[dict[str, Any]] = []

    if destination.exists() and any(destination.iterdir()):
        if not overwrite:
            raise AssetMaterializeError(f"materialized output already exists: {destination}")
        _assert_existing_sidecar(destination)
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.materialize-", dir=destination.parent)
    )
    try:
        if (source / "evidence").is_dir():
            shutil.copytree(source / "evidence", staging / "evidence", dirs_exist_ok=True)
        else:
            (staging / "evidence").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(downloads / "asset_downloads.json", staging / "evidence" / "asset_downloads.json")

        for row in rows:
            asset_id = str(row.get("asset_id") or "")
            if not asset_id:
                raise AssetMaterializeError("downloaded row has no asset_id")
            source_file = downloads / str(row.get("locator") or "")
            if not source_file.is_file():
                raise AssetMaterializeError(f"downloaded asset file missing: {source_file}")
            sha = str(row.get("sha256") or "")
            if _sha256_file(source_file) != sha:
                raise AssetMaterializeError(f"downloaded asset hash mismatch: {asset_id}")
            mime = str(row.get("mime") or "")
            size_bytes = int(row.get("size_bytes") or source_file.stat().st_size)
            target_name = source_file.name
            target = staging / "evidence" / "assets" / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, target)
            locator = f"evidence/assets/{target_name}"
            asset = _find_asset(runtime_ir["assets"], asset_id)
            asset.update(
                {
                    "local_sha256": sha,
                    "local_bytes_present": True,
                    "local_expires_at": expires_at,
                    "mime": mime,
                }
            )
            if not asset.get("source_url"):
                asset["source_url"] = row.get("source_url")
            evidence_id = f"ev-{asset_id}"
            _upsert_evidence(
                runtime_ir["evidence"],
                {
                    "evidence_id": evidence_id,
                    "kind": "asset-bytes-materialized",
                    "sha256": sha,
                    "locator": locator,
                    "availability": "available",
                    "expires_at": expires_at,
                    "bytes_present": True,
                },
            )
            _update_manifest_asset(manifest, asset_id, row, locator)
            downloaded_bytes += size_bytes
            materialized_rows.append(
                {
                    **row,
                    "locator": locator,
                    "local_bytes_present": True,
                }
            )

        report_sha = _sha256_file(downloads / "asset_downloads.json")
        _upsert_evidence(
            runtime_ir["evidence"],
            {
                "evidence_id": "ev-asset-download-report",
                "kind": "asset-download-report",
                "sha256": report_sha,
                "locator": "evidence/asset_downloads.json",
                "availability": "available",
                "expires_at": expires_at,
                "bytes_present": True,
            },
        )
        audit_bundle["ordered_evidence"] = [
            item["evidence_id"] for item in runtime_ir["evidence"]
        ]
        materialization = {
            "schema_version": "p1-asset-materialization/1.0",
            "downloaded_count": len(materialized_rows),
            "downloaded_bytes": downloaded_bytes,
            "report_sha256": report_sha,
            "source_downloads": str(downloads),
            "promotion": "asset-evidence-only; decisions unchanged",
        }
        manifest["materialized"] = True
        manifest["runtime_ir_changed"] = True
        manifest["materialization"] = materialization
        manifest["assets"] = [
            item for item in manifest.get("assets") or []
            if isinstance(item, dict)
        ]
        manifest["asset_bytes_total"] = sum(
            int(item.get("size_bytes") or 0)
            for item in manifest["assets"]
            if item.get("bytes_present")
        )
        manifest.pop("content_hash", None)
        manifest["content_hash"] = canonical_hash(manifest)

        materialized_issues = (
            list(validate_runtime_ir(runtime_ir))
            + list(validate_audit_bundle(audit_bundle))
        )
        if materialized_issues:
            raise AssetMaterializeError(
                f"materialized sidecar validation failed: {materialized_issues}"
            )
        _write_json(staging / "runtime_ir.json", runtime_ir)
        _write_json(staging / "audit_bundle.json", audit_bundle)
        _write_json(staging / "manifest.json", manifest)
        _write_json(
            staging / "materialization.json",
            {
                **materialization,
                "rows": materialized_rows,
            },
        )
        if destination.exists():
            destination.rmdir()
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return MaterializedAssetSidecar(
        output_dir=destination,
        runtime_ir=runtime_ir,
        audit_bundle=audit_bundle,
        manifest=manifest,
        materialization=materialization,
    )


def _find_asset(assets: list[dict[str, Any]], asset_id: str) -> dict[str, Any]:
    for item in assets:
        if isinstance(item, dict) and item.get("asset_id") == asset_id:
            return item
    raise AssetMaterializeError(f"asset not found in runtime IR: {asset_id}")


def _update_manifest_asset(
    manifest: dict[str, Any],
    asset_id: str,
    row: dict[str, Any],
    locator: str,
) -> None:
    for item in manifest.get("assets") or []:
        if isinstance(item, dict) and item.get("asset_id") == asset_id:
            item.update(
                {
                    "status": "materialized-local-bytes",
                    "mime": row.get("mime"),
                    "sha256": row.get("sha256"),
                    "size_bytes": row.get("size_bytes"),
                    "source_url": row.get("source_url") or item.get("source_url"),
                    "locator": locator,
                    "bytes_present": True,
                }
            )
            return
    raise AssetMaterializeError(f"asset not found in manifest: {asset_id}")


def _upsert_evidence(items: list[dict[str, Any]], record: dict[str, Any]) -> None:
    evidence_id = record["evidence_id"]
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("evidence_id") == evidence_id:
            items[index] = record
            return
    items.append(record)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetMaterializeError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise AssetMaterializeError(f"JSON file is not an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(jsonable(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _assert_existing_sidecar(path: Path) -> None:
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise AssetMaterializeError(f"refusing to overwrite non-sidecar directory: {path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetMaterializeError(f"refusing to overwrite unreadable sidecar: {path}") from exc
    if manifest.get("sidecar_schema") != "evidence-sidecar/1.0":
        raise AssetMaterializeError(f"refusing to overwrite non-sidecar directory: {path}")
