# -*- coding: utf-8 -*-
"""Fixed output-fidelity hard-gate matrix for P5 Task 3."""
from __future__ import annotations

import argparse
import copy
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

from src.app.services.contracts import canonical_hash
from src.app.services.rendering.figma_acceptance import accept_output
from src.app.services.rendering.text_wrap import TextAcceptance
from src.app.services.structure.asset_metadata import resolve_asset_identity


PROFILE = "fixed-chromium-and-figma-plugin/1.0"
REAL_EVIDENCE = ROOT / "output" / "_p1_figma_canonical_frame_round3"
REAL_ACCEPTANCE = ROOT / "output" / "_p1_figma_acceptance_frame_round15" / "figma_acceptance.json"
EDIT_PROBE = ROOT / "output" / "_p1_figma_edit_probe_round5" / "figma_edit_probe.json"
TRUTH = ROOT / "tests" / "fixtures" / "p1" / "canonical" / "holdout" / "frame.truth.json"
VISUAL_POLICY = ROOT / "tests" / "fixtures" / "p1" / "canonical" / "figma_visual_policy.json"


def run_matrix(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    _require_files(
        REAL_EVIDENCE / "12_design.json",
        REAL_EVIDENCE / "readback_tree.json",
        REAL_EVIDENCE / "font_report.json",
        REAL_ACCEPTANCE,
        EDIT_PROBE,
        TRUTH,
        VISUAL_POLICY,
    )
    design = _load_json(REAL_EVIDENCE / "12_design.json")
    readback = _load_json(REAL_EVIDENCE / "readback_tree.json")
    font_report = _load_json(REAL_EVIDENCE / "font_report.json")
    truth = _load_json(TRUTH)
    edit_probe = _load_json(EDIT_PROBE)
    acceptance_evidence = _load_json(REAL_ACCEPTANCE)
    visual_metrics = (
        acceptance_evidence.get("checks", {}).get("visual", {}).get("metrics")
    )
    if not isinstance(visual_metrics, dict):
        raise ValueError("real Figma acceptance artifact has no visual metrics")
    visual_policy = _load_json(VISUAL_POLICY)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            chromium_version = browser.version
        finally:
            browser.close()

    plugin_build = {
        "code_sha256": _sha256_file(ROOT / "figma_bridge" / "code.js"),
        "manifest_sha256": _sha256_file(ROOT / "figma_bridge" / "manifest.json"),
        "manifest": _load_json(ROOT / "figma_bridge" / "manifest.json"),
    }

    cases: list[dict[str, Any]] = []
    baseline_bundle = {
        "design": design,
        "truth": truth,
        "readback_tree": readback,
        "font_report": font_report,
        "edit_probe": edit_probe,
        "visual_metrics": visual_metrics,
        "visual_policy": visual_policy,
        "text_components": TextAcceptance(
            content="pass",
            linebreak="not-evaluated",
            box="pass",
            baseline="not-evaluated",
            glyph="not-evaluated",
        ),
    }
    cases.append(
        _case(
            "real-readback-baseline",
            baseline_bundle,
            expected_status="blocked-unknown",
            description="Real Figma readback passes visual/structure/edit while unresolved text components stay blocking.",
        )
    )

    missing_font_readback = copy.deepcopy(readback)
    for node in _iter_nodes(missing_font_readback):
        if node.get("type") == "TEXT" and node.get("characters") == "Holdout frame sample":
            node["fontName"] = {"family": "Inter", "style": "Bold"}
            break
    missing_font_bundle = {
        **baseline_bundle,
        "readback_tree": missing_font_readback,
        "text_components": TextAcceptance(
            content="pass",
            linebreak="pass",
            box="pass",
            baseline="pass",
            glyph="pass",
        ),
    }
    cases.append(
        _case(
            "visual-pass-font-fail",
            missing_font_bundle,
            expected_status="blocked-fail",
            description="A visual pass cannot offset a real readback font-family failure.",
        )
    )

    linebreak_bundle = {
        **baseline_bundle,
        "text_components": TextAcceptance(
            content="pass",
            linebreak="partial",
            box="pass",
            baseline="pass",
            glyph="pass",
        ),
    }
    cases.append(
        _case(
            "text-linebreak-partial",
            linebreak_bundle,
            expected_status="blocked-partial",
            description="Linebreak partial remains visible even when other text components pass.",
        )
    )

    remote_design = {
        "canvas": {"width": 300, "height": 200, "background": "#ffffff"},
        "elements": [
            {
                "id": "hero",
                "type": "image",
                "x": 10,
                "y": 10,
                "width": 120,
                "height": 80,
                "assetIdentity": {
                    "source_url": "https://cdn.example/hero.png",
                    "status": "reference-only",
                },
            }
        ],
    }
    remote_readback = {
        "id": "1:1",
        "type": "FRAME",
        "x": 0,
        "y": 0,
        "width": 300,
        "height": 200,
        "absolute": {"x": 0, "y": 0, "width": 300, "height": 200},
        "children": [],
    }
    remote_bundle = {
        "design": remote_design,
        "truth": {
            "expected_texts": [],
            "expected_asset_count": 1,
            "native_text_required": False,
        },
        "readback_tree": remote_readback,
        "visual_metrics": visual_metrics,
        "visual_policy": visual_policy,
        "text_components": TextAcceptance(
            content="pass",
            linebreak="pass",
            box="pass",
            baseline="pass",
            glyph="pass",
        ),
    }
    cases.append(
        _case(
            "remote-url-only-asset",
            remote_bundle,
            expected_status="blocked-fail",
            description="A remote URL without payload bytes cannot authorize asset replacement.",
        )
    )

    expired_retained = resolve_asset_identity(
        source_url="https://cdn.example/expired.png",
        payload_sha256="a" * 64,
        natural_size=(640, 480),
        url_expired=True,
        retained_bytes_present=True,
    )
    expired_blocked = resolve_asset_identity(
        source_url="https://cdn.example/expired.png",
        payload_sha256="a" * 64,
        natural_size=(640, 480),
        url_expired=True,
        retained_bytes_present=False,
    )
    evidence_hashes = {
        "design": _sha256_file(REAL_EVIDENCE / "12_design.json"),
        "readback_tree": _sha256_file(REAL_EVIDENCE / "readback_tree.json"),
        "font_report": _sha256_file(REAL_EVIDENCE / "font_report.json"),
        "figma_acceptance": _sha256_file(REAL_ACCEPTANCE),
        "edit_probe": _sha256_file(EDIT_PROBE),
    }
    checks = (
        _check("chromium-version", "Chromium build is recorded", bool(chromium_version)),
        _check("plugin-build", "Plugin code and manifest hashes are fixed", bool(plugin_build["code_sha256"])),
        _check("real-figma-evidence", "Real Figma readback and edit evidence are present", all(evidence_hashes.values())),
        _check("case-statuses", "Every matrix case matches its expected hard-gate status", all(item["matched"] for item in cases)),
        _check("visual-not-compensating", "Visual pass does not offset font or asset failure", all(
            item["decision"]["dimensions"]["visual"]["status"] == "pass"
            for item in cases
            if item["case_id"] in {"visual-pass-font-fail", "remote-url-only-asset"}
        )),
        _check("font-independent", "Font failure is reported in edit dimension", next(
            item for item in cases if item["case_id"] == "visual-pass-font-fail"
        )["decision"]["dimensions"]["edit"]["status"] == "fail"),
        _check("asset-independent", "Remote reference is reported in asset dimension", next(
            item for item in cases if item["case_id"] == "remote-url-only-asset"
        )["decision"]["dimensions"]["asset"]["status"] == "fail"),
        _check("text-components", "Linebreak partial remains independent", next(
            item for item in cases if item["case_id"] == "text-linebreak-partial"
        )["decision"]["text"]["linebreak"] == "partial"),
        _check("asset-expiry", "Expired URL uses retained bytes or fails closed", expired_retained.status == "retained-bytes" and expired_blocked.status == "blocked-expired-url"),
    )
    result = {
        "schema": "p5-output-fidelity-matrix/1.0",
        "status": "verified-for" if all(item["passed"] for item in checks) else "blocked",
        "scope": "canonical asset/font/text hard-gate matrix on fixed Chromium and plugin build",
        "created_at": "2026-10-22T00:00:00+00:00",
        "profile": PROFILE,
        "environment": {
            "os": "Windows 11",
            "python": sys.version.split()[0],
            "chromium_version": chromium_version,
            "viewport": [900, 700],
            "device_scale_factor": 1,
        },
        "plugin_build": plugin_build,
        "code_revision": _code_revision(),
        "thresholds": {
            "visual": visual_policy,
            "font_size_tolerance_px": 0.1,
            "structure_position_tolerance_px": 1.0,
            "structure_size_tolerance_px": 2.0,
        },
        "evidence": evidence_hashes,
        "cases": cases,
        "asset_expiry": {
            "retained": expired_retained.to_dict(),
            "blocked": expired_blocked.to_dict(),
        },
        "checks": list(checks),
        "claim_limits": [
            "The matrix verifies hard-gate behavior, not that every output sample is complete.",
            "The real readback evidence is sourced from the fixed P1 frame artifact.",
            "Glyph identity, Firefox and variable-font axis precision remain separate claims.",
        ],
    }
    result["content_hash"] = canonical_hash(result)
    _write_json(destination / "result.json", result)
    _write_json(destination / "matrix.json", {"cases": cases, "checks": checks})
    return result


def _case(
    case_id: str,
    bundle: dict[str, Any],
    *,
    expected_status: str,
    description: str,
) -> dict[str, Any]:
    decision = accept_output(bundle, PROFILE)
    return {
        "case_id": case_id,
        "description": description,
        "expected_status": expected_status,
        "actual_status": decision.status,
        "matched": decision.status == expected_status,
        "decision": decision.to_dict(),
    }


def _iter_nodes(node: dict[str, Any]):
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children") or []:
        yield from _iter_nodes(child)


def _check(name: str, description: str, passed: bool) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "passed": bool(passed),
    }


def _require_files(*paths: Path) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing fixed evidence: " + ", ".join(missing))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    parser.add_argument("--out", default="output/_p5_output_fidelity_round1")
    args = parser.parse_args()
    result = run_matrix(args.out)
    print(json.dumps({"cases": len(result["cases"]), "checks": len(result["checks"])}, indent=2))
    print("status=" + result["status"])
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] == "verified-for" else 1


if __name__ == "__main__":
    raise SystemExit(main())
