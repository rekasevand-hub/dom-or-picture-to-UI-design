from __future__ import annotations

import json
from pathlib import Path

from src.app.services.structure.capture_asset_ledger import (
    build_asset_ledger,
    update_capture_bundle_assets,
)
from src.app.services.structure.capture_bundle import write_capture_bundle


def _element(record: dict) -> dict:
    return {
        "id": "image",
        "type": "image",
        "assetIdentity": {"asset_record": record},
    }


def _record(
    source_url: str | None,
    *,
    status: str,
    sha256: str | None = None,
    locator: str | None = None,
    missing: bool = False,
) -> dict:
    return {
        "source_identity": {
            "source_url": source_url,
            "status": status,
            "sha256": sha256,
            "mime": "image/png" if sha256 else None,
            "natural_size": [320, 180] if sha256 else None,
            "locator": locator,
            "size_bytes": 1234 if sha256 else None,
        },
        "missing": {
            "is_missing": missing,
            "status": "missing-display" if missing else "loaded",
        },
    }


def test_ledger_distinguishes_verified_reference_only_and_missing():
    design = {
        "elements": [
            _element(
                _record(
                    "https://example.test/verified.png",
                    status="verified-original",
                    sha256="a" * 64,
                    locator="assets/verified.png",
                )
            ),
            _element(
                _record(
                    "https://example.test/remote.png",
                    status="reference-only",
                )
            ),
            _element(
                _record(None, status="blocked-missing-source", missing=True)
            ),
        ]
    }

    ledger = build_asset_ledger(design)

    assert ledger["schema_version"] == "dom-capture-assets/1.0"
    assert ledger["reference_count"] == 3
    assert ledger["verified_count"] == 1
    assert ledger["reference_only_count"] == 1
    assert ledger["missing_count"] == 1
    assert {row["status"] for row in ledger["assets"]} == {
        "verified",
        "reference-only",
        "missing",
    }


def test_duplicate_source_urls_share_one_retained_asset_row():
    record = _record(
        "https://example.test/shared.png",
        status="verified-original",
        sha256="b" * 64,
        locator="assets/shared.png",
    )
    ledger = build_asset_ledger(
        {"elements": [_element(record), _element(record)]}
    )

    assert ledger["verified_count"] == 1
    assert ledger["use_count"] == 2
    assert len(ledger["assets"]) == 1
    assert ledger["assets"][0]["source_sha256"] == "b" * 64


def test_zero_image_references_is_not_reported_as_success():
    ledger = build_asset_ledger({"elements": []})

    assert ledger["reference_count"] == 0
    assert ledger["status"] == "not-required"
    assert ledger["success"] is False
    assert ledger["assets"] == []


def test_update_capture_bundle_assets_hashes_manifest_and_counts(tmp_path):
    for name, payload in (
        ("00_screenshot.png", b"png"),
        ("00_dom.json", b"[]"),
        ("00_page_state.json", b"{}"),
    ):
        (tmp_path / name).write_bytes(payload)
    manifest = write_capture_bundle(
        tmp_path,
        requested_url="https://example.test/",
        page_state={
            "final_url": "https://example.test/",
            "kind": "content",
            "screenshot_only": False,
        },
        artifact_paths={
            "screenshot": tmp_path / "00_screenshot.png",
            "dom": tmp_path / "00_dom.json",
            "page_state": tmp_path / "00_page_state.json",
        },
    )
    ledger = build_asset_ledger({"elements": []})
    (tmp_path / "00_assets.json").write_text(
        json.dumps(ledger),
        encoding="utf-8",
    )

    updated = update_capture_bundle_assets(
        tmp_path,
        asset_manifest="00_assets.json",
        asset_counts=ledger,
    )

    assert updated["artifacts"]["assets"]["path"] == "00_assets.json"
    assert updated["artifacts"]["assets"]["counts"]["reference_count"] == 0
    assert updated["requested_url"] == manifest["requested_url"]
