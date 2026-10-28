from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.app.services.structure.capture_bundle import (
    CAPTURE_BUNDLE_SCHEMA_VERSION,
    CaptureBundleError,
    load_capture_bundle,
    write_capture_bundle,
)


def sha256_file(name: str, root: Path | None = None) -> str:
    path = (root or Path(".")) / name
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_complete_fixture_bundle(root: Path) -> dict:
    (root / "00_screenshot.png").write_bytes(b"fixture-screenshot")
    (root / "00_dom.json").write_text(
        json.dumps([{"tag": "body", "x": 0, "y": 0, "w": 1440, "h": 900}]),
        encoding="utf-8",
    )
    (root / "00_page_state.json").write_text(
        json.dumps({"kind": "content", "screenshot_only": False}),
        encoding="utf-8",
    )
    return write_capture_bundle(
        root,
        requested_url="https://example.test/start",
        page_state={
            "final_url": "https://example.test/final",
            "kind": "content",
            "screenshot_only": False,
            "viewport": {"width": 1440, "height": 900},
            "device_scale_factor": 1,
            "canvas_size": [1440, 900],
        },
        artifact_paths={
            "screenshot": root / "00_screenshot.png",
            "dom": root / "00_dom.json",
            "page_state": root / "00_page_state.json",
        },
    )


def test_bundle_hashes_existing_artifacts_without_storage_state(tmp_path):
    (tmp_path / "00_screenshot.png").write_bytes(b"fixture-screenshot")
    (tmp_path / "00_dom.json").write_text("[]", encoding="utf-8")
    (tmp_path / "00_page_state.json").write_text(
        json.dumps({"kind": "content", "screenshot_only": False}),
        encoding="utf-8",
    )
    manifest = write_capture_bundle(
        tmp_path,
        requested_url="https://example.test/start",
        page_state={
            "final_url": "https://example.test/final",
            "kind": "content",
            "screenshot_only": False,
        },
        artifact_paths={
            "screenshot": tmp_path / "00_screenshot.png",
            "dom": tmp_path / "00_dom.json",
            "page_state": tmp_path / "00_page_state.json",
        },
    )
    assert manifest["schema_version"] == CAPTURE_BUNDLE_SCHEMA_VERSION
    assert manifest["requested_url"] == "https://example.test/start"
    assert manifest["final_url"] == "https://example.test/final"
    assert manifest["artifacts"]["dom"]["sha256"] == sha256_file(
        "00_dom.json", tmp_path
    )
    assert "storage_state" not in json.dumps(manifest).lower()


def test_load_bundle_rejects_missing_or_mutated_artifact(tmp_path):
    write_complete_fixture_bundle(tmp_path)
    (tmp_path / "00_dom.json").write_text("[]", encoding="utf-8")
    with pytest.raises(CaptureBundleError, match="sha256 mismatch"):
        load_capture_bundle(tmp_path)


def test_load_bundle_rejects_missing_artifact(tmp_path):
    write_complete_fixture_bundle(tmp_path)
    (tmp_path / "00_screenshot.png").unlink()
    with pytest.raises(CaptureBundleError, match="missing artifact"):
        load_capture_bundle(tmp_path)


def test_load_bundle_rejects_missing_required_artifact_entry(tmp_path):
    write_complete_fixture_bundle(tmp_path)
    manifest_path = tmp_path / "00_capture_bundle.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["artifacts"]["dom"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CaptureBundleError, match="required artifact"):
        load_capture_bundle(tmp_path)


def test_load_bundle_rejects_unsupported_schema(tmp_path):
    write_complete_fixture_bundle(tmp_path)
    manifest_path = tmp_path / "00_capture_bundle.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "dom-capture-bundle/99.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CaptureBundleError, match="unsupported schema"):
        load_capture_bundle(tmp_path)


def test_load_bundle_rejects_missing_required_fields(tmp_path):
    write_complete_fixture_bundle(tmp_path)
    manifest_path = tmp_path / "00_capture_bundle.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["capture"]["viewport"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CaptureBundleError, match="required field"):
        load_capture_bundle(tmp_path)


def test_load_bundle_rejects_artifact_path_traversal(tmp_path):
    write_complete_fixture_bundle(tmp_path)
    manifest_path = tmp_path / "00_capture_bundle.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["dom"]["path"] = "../00_dom.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CaptureBundleError, match="traversal"):
        load_capture_bundle(tmp_path)
