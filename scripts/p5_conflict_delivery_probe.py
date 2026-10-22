# -*- coding: utf-8 -*-
"""Authored Chromium probe for conflict/unknown delivery."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.contracts import (
    FieldDecisionStatus,
    FieldObservation,
    Tombstone,
    canonical_hash,
)
from src.app.services.delivery.conflicts import build_conflict_report
from src.app.services.delivery.field_resolution import FieldClaim, resolve_fields


PROFILE = "fixed-authored-chromium/1.0"
JOB_ID = "p5-conflict-delivery-round1"


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 900, "height": 700})
            page.set_content(
                """
                <!doctype html>
                <html lang="zh-CN">
                  <body style="margin:0;background:#eef2f7;font-family:Arial">
                    <main style="padding:32px">
                      <h1 id="title">限时特价 A</h1>
                      <div id="swatch" style="width:120px;height:48px;background:#2563eb"></div>
                      <p id="price">¥19.90</p>
                    </main>
                  </body>
                </html>
                """,
                wait_until="load",
            )
            dom = page.evaluate(
                """
                () => {
                  const title = document.querySelector('#title');
                  const swatch = document.querySelector('#swatch');
                  const price = document.querySelector('#price');
                  const titleStyle = getComputedStyle(title);
                  const swatchStyle = getComputedStyle(swatch);
                  return {
                    title: title.textContent,
                    titleVisible: titleStyle.visibility === 'visible' &&
                      titleStyle.display !== 'none',
                    swatchColor: swatchStyle.backgroundColor,
                    price: price.textContent.trim(),
                    viewport: {
                      width: window.innerWidth,
                      height: window.innerHeight
                    }
                  };
                }
                """
            )
            screenshot = destination / "screenshot.png"
            page.screenshot(path=str(screenshot), full_page=True)
            chromium_version = browser.version
        finally:
            browser.close()

    observations_path = destination / "dom_observations.json"
    _write_json(observations_path, dom)
    screenshot_sha256 = _sha256_file(screenshot)

    conflict_candidate_text = "限时特价 B"
    ocr_candidate_text = "OCR 候选标题"
    claims = (
        FieldClaim(
            field_id="selected-title",
            node_id="title",
            field_type="text-content",
            observations=(
                FieldObservation(
                    source="dom",
                    evidence_id="ev-dom-title",
                    present=True,
                    value=dom["title"],
                ),
            ),
        ),
        FieldClaim(
            field_id="conflict-title",
            node_id="title-conflict",
            field_type="text-content",
            observations=(
                FieldObservation(
                    source="dom",
                    evidence_id="ev-dom-title-conflict",
                    present=True,
                    value=dom["title"],
                ),
                FieldObservation(
                    source="authored-screenshot-observation",
                    evidence_id="ev-screenshot-title-conflict",
                    present=True,
                    value=conflict_candidate_text,
                ),
            ),
        ),
        FieldClaim(
            field_id="unknown-color",
            node_id="card",
            field_type="color",
            observations=(),
        ),
        FieldClaim(
            field_id="unknown-visibility",
            node_id="card",
            field_type="visibility",
            observations=(),
            status_hint=FieldDecisionStatus.DEFERRED,
        ),
        FieldClaim(
            field_id="price",
            node_id="price",
            field_type="price",
            observations=(
                FieldObservation(
                    source="dom",
                    evidence_id="ev-dom-price",
                    present=True,
                    value=dom["price"],
                ),
            ),
        ),
        FieldClaim(
            field_id="ocr-candidate",
            node_id="ocr-title",
            field_type="text-content",
            observations=(
                FieldObservation(
                    source="screenshot-ocr",
                    evidence_id="ev-authored-ocr",
                    present=True,
                    value=ocr_candidate_text,
                ),
            ),
            ocr_confident=True,
        ),
        FieldClaim(
            field_id="tombstone-price",
            node_id="old-price",
            field_type="text-content",
            observations=(
                FieldObservation(
                    source="old-revision",
                    evidence_id="ev-old-price",
                    present=True,
                    value="旧价格 ¥59.00",
                ),
            ),
            tombstone=Tombstone(
                tombstone_id="tomb-price",
                object_key="old-price",
                scope="field",
                authority="business",
                authority_version=3,
                effective_at="2026-10-22T00:00:00+00:00",
            ),
        ),
        FieldClaim(
            field_id="skipped-asset",
            node_id="promo-asset",
            field_type="asset",
            observations=(),
            status_hint=FieldDecisionStatus.SKIPPED,
            skip_reason="Asset replacement is outside this authored probe.",
        ),
    )
    resolution = resolve_fields(claims, PROFILE)
    report = build_conflict_report(resolution)
    resolution_path = destination / "conflict_resolution.json"
    report_path = destination / "report.json"
    _write_json(resolution_path, resolution.to_dict())
    _write_json(report_path, report.to_dict())

    unresolved_text = (
        conflict_candidate_text,
        ocr_candidate_text,
        "旧价格 ¥59.00",
        dom["price"],
    )
    content_json = json.dumps(resolution.content, ensure_ascii=False)
    checks = (
        _check("chromium-launched", "Chromium launched and reported a build", bool(chromium_version)),
        _check("screenshot-captured", "Authored page screenshot is non-empty", screenshot.stat().st_size > 0),
        _check("dom-observed", "Title, color and price were observed from real Chromium DOM", bool(dom["title"] and dom["swatchColor"] and dom["price"])),
        _check("text-conflict", "Disagreeing text observations remain unresolved", _state(resolution, "conflict-title") == "external-conflict"),
        _check("unknown-deferred-distinct", "Unknown color and deferred visibility remain distinct", _state(resolution, "unknown-color") == "unknown" and _state(resolution, "unknown-visibility") == "deferred"),
        _check("price-authority", "DOM price remains authority-required", _state(resolution, "price") == "authority-required"),
        _check("ocr-candidate", "OCR text remains candidate-only", _state(resolution, "ocr-candidate") == "candidate"),
        _check("tombstone", "Tombstoned old value remains delete-pending", _state(resolution, "tombstone-price") == "delete-pending"),
        _check("skipped", "Out-of-scope asset remains skipped", _state(resolution, "skipped-asset") == "skipped"),
        _check("no-unresolved-content", "Unresolved values never enter final node content", not any(value in content_json for value in unresolved_text)),
        _check("report-complete", "Every unresolved field has a complete report entry", len(report.entries) == 7 and all(_entry_complete(item.to_dict()) for item in report.entries)),
    )
    all_passed = all(item["passed"] for item in checks)
    result = {
        "schema": "p5-conflict-delivery-probe/1.0",
        "status": "verified-for" if all_passed else "blocked",
        "scope": "conflict/unknown delivery on fixed authored Chromium profile",
        "job_id": JOB_ID,
        "created_at": "2026-10-22T00:00:00+00:00",
        "environment": {
            "os": "Windows 11",
            "python": sys.version.split()[0],
            "browser_engine": "chromium",
            "chromium_version": chromium_version,
            "viewport": dom["viewport"],
            "device_scale_factor": 1,
        },
        "code_revision": _code_revision(),
        "plugin_build": "not-used",
        "profile": PROFILE,
        "thresholds": {
            "text_conflict": "exact disagreement",
            "ocr_candidate": "candidate-only without DOM confirmation",
            "price_authority": "business source required",
        },
        "evidence": {
            "screenshot": screenshot.name,
            "screenshot_sha256": screenshot_sha256,
            "dom_observations": observations_path.name,
            "resolution": resolution_path.name,
            "report": report_path.name,
        },
        "dom": dom,
        "conflict_candidate_text": conflict_candidate_text,
        "ocr_candidate_text": ocr_candidate_text,
        "content": resolution.content,
        "counts": resolution.counts,
        "checks": list(checks),
    }
    result["content_hash"] = canonical_hash(result)
    _write_json(destination / "result.json", result)
    _write_json(destination / "manifest.json", result)
    return result


def _state(resolution, field_id: str) -> str:
    return next(
        field.decision.status.value
        for field in resolution.fields
        if field.field_id == field_id
    )


def _entry_complete(entry: dict[str, Any]) -> bool:
    required = {
        "entry_id",
        "field_id",
        "node_id",
        "field_type",
        "status",
        "observations",
        "authority_gap",
        "current_display",
        "blocked_actions",
        "next_step",
        "unlock_condition",
        "winner",
    }
    return (
        required.issubset(entry)
        and entry["winner"] is None
        and all(entry[key] for key in required - {"winner"})
    )


def _check(name: str, description: str, passed: bool) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "passed": bool(passed),
    }


def _code_revision() -> str:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return revision + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with staging.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_p5_conflict_delivery_round1")
    args = parser.parse_args()
    result = run_probe(args.out)
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))
    print("status=" + result["status"])
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] == "verified-for" else 1


if __name__ == "__main__":
    raise SystemExit(main())
