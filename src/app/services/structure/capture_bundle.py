from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CAPTURE_BUNDLE_SCHEMA_VERSION = "dom-capture-bundle/1.0"
CAPTURE_BUNDLE_FILENAME = "00_capture_bundle.json"

_REQUIRED_MANIFEST_FIELDS = (
    "schema_version",
    "requested_url",
    "final_url",
    "page_state",
    "capture",
    "artifacts",
    "warnings",
)
_REQUIRED_CAPTURE_FIELDS = (
    "viewport",
    "device_scale_factor",
    "canvas_size",
)
_REQUIRED_ARTIFACTS = ("screenshot", "dom", "page_state")


class CaptureBundleError(RuntimeError):
    """Raised when a capture bundle is incomplete, unsafe, or modified."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_artifact_path(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(root)
        except ValueError as exc:
            raise CaptureBundleError(
                f"artifact path is outside the capture bundle: {path}"
            ) from exc
    if ".." in candidate.parts:
        raise CaptureBundleError(f"artifact path traversal is not allowed: {path}")
    return candidate


def _artifact_entry(root: Path, path: str | Path) -> dict[str, Any]:
    relative = _relative_artifact_path(root, path)
    absolute = root / relative
    if not absolute.is_file():
        raise CaptureBundleError(f"missing artifact: {relative.as_posix()}")
    return {
        "path": relative.as_posix(),
        "bytes": absolute.stat().st_size,
        "sha256": _sha256(absolute),
    }


def _safe_page_state(page_state: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in (
        "kind",
        "confidence",
        "reason",
        "screenshot_only",
        "fallback_used",
        "requested_route",
        "effective_route",
    ):
        if key in page_state:
            safe[key] = page_state[key]
    return safe


def _capture_metadata(page_state: Mapping[str, Any]) -> dict[str, Any]:
    viewport = page_state.get("viewport")
    if not isinstance(viewport, Mapping):
        viewport = {
            "width": page_state.get("width"),
            "height": page_state.get("height"),
        }
    canvas_size = page_state.get("canvas_size")
    if not isinstance(canvas_size, (list, tuple)) or len(canvas_size) != 2:
        canvas_size = [
            page_state.get("width"),
            page_state.get("height"),
        ]
    return {
        "viewport": {
            "width": viewport.get("width"),
            "height": viewport.get("height"),
        },
        "device_scale_factor": page_state.get("device_scale_factor"),
        "canvas_size": [canvas_size[0], canvas_size[1]],
    }


def write_capture_bundle(
    output_dir: Path,
    *,
    requested_url: str,
    page_state: Mapping[str, Any],
    artifact_paths: Mapping[str, str | Path | None],
    asset_manifest: str | Path | None = None,
    asset_counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, Any]] = {}
    for role, path in artifact_paths.items():
        if path is None:
            continue
        if not Path(path).is_file():
            continue
        artifacts[role] = _artifact_entry(root, path)

    warnings = [
        str(item)
        for item in page_state.get("warnings", [])
        if str(item).strip()
    ]
    if asset_manifest:
        manifest_path = Path(asset_manifest)
        if not manifest_path.is_absolute():
            manifest_path = root / manifest_path
        if manifest_path.is_file():
            artifacts["assets"] = _artifact_entry(root, manifest_path)
        else:
            warnings.append(f"missing asset manifest: {manifest_path.name}")
    if asset_counts:
        ledger = _artifact_entry(root, asset_manifest) if asset_manifest else {}
        if ledger:
            ledger["counts"] = {
                key: asset_counts.get(key)
                for key in (
                    "reference_count",
                    "verified_count",
                    "reference_only_count",
                    "missing_count",
                )
                if key in asset_counts
            }
            artifacts["assets"] = ledger

    manifest: dict[str, Any] = {
        "schema_version": CAPTURE_BUNDLE_SCHEMA_VERSION,
        "requested_url": requested_url,
        "final_url": str(page_state.get("final_url") or requested_url),
        "page_state": _safe_page_state(page_state),
        "capture": _capture_metadata(page_state),
        "artifacts": artifacts,
        "warnings": warnings,
    }
    manifest_path = root / CAPTURE_BUNDLE_FILENAME
    temp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(manifest_path)
    return manifest


def _validate_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise CaptureBundleError("capture bundle manifest must be a JSON object")
    for field in _REQUIRED_MANIFEST_FIELDS:
        if field not in manifest:
            raise CaptureBundleError(f"capture bundle required field is missing: {field}")
    if manifest["schema_version"] != CAPTURE_BUNDLE_SCHEMA_VERSION:
        raise CaptureBundleError(
            "unsupported schema: "
            f"{manifest['schema_version']!r}; expected {CAPTURE_BUNDLE_SCHEMA_VERSION!r}"
        )
    capture = manifest["capture"]
    if not isinstance(capture, dict):
        raise CaptureBundleError("capture bundle required field is invalid: capture")
    for field in _REQUIRED_CAPTURE_FIELDS:
        if field not in capture:
            raise CaptureBundleError(
                f"capture bundle required field is missing: capture.{field}"
            )
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, dict) or not artifacts:
        raise CaptureBundleError("capture bundle required field is invalid: artifacts")
    for role in _REQUIRED_ARTIFACTS:
        if role not in artifacts:
            raise CaptureBundleError(f"capture bundle required artifact is missing: {role}")
    return manifest


def load_capture_bundle(output_dir: Path) -> dict[str, Any]:
    root = Path(output_dir).resolve()
    manifest_path = root / CAPTURE_BUNDLE_FILENAME
    if not manifest_path.is_file():
        raise CaptureBundleError(f"missing capture bundle: {manifest_path.name}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureBundleError(f"invalid capture bundle manifest: {exc}") from exc
    manifest = _validate_manifest(manifest)

    for role, entry in manifest["artifacts"].items():
        if not isinstance(entry, dict):
            raise CaptureBundleError(f"invalid artifact entry: {role}")
        path_value = entry.get("path")
        expected_hash = entry.get("sha256")
        if not isinstance(path_value, str) or not path_value:
            raise CaptureBundleError(f"artifact path is missing: {role}")
        if not isinstance(expected_hash, str) or not expected_hash:
            raise CaptureBundleError(f"artifact sha256 is missing: {role}")
        relative = _relative_artifact_path(root, path_value)
        artifact_path = (root / relative).resolve()
        try:
            artifact_path.relative_to(root)
        except ValueError as exc:
            raise CaptureBundleError(
                f"artifact path is outside the capture bundle: {path_value}"
            ) from exc
        if not artifact_path.is_file():
            raise CaptureBundleError(f"missing artifact: {relative.as_posix()}")
        actual_hash = _sha256(artifact_path)
        if actual_hash != expected_hash:
            raise CaptureBundleError(
                f"sha256 mismatch for {relative.as_posix()}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        expected_bytes = entry.get("bytes")
        if isinstance(expected_bytes, int) and artifact_path.stat().st_size != expected_bytes:
            raise CaptureBundleError(
                f"byte size mismatch for {relative.as_posix()}: "
                f"expected {expected_bytes}, got {artifact_path.stat().st_size}"
            )
    return manifest
