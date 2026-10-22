"""Evaluate canonical Chromium DOM -> SVG output against authored truth."""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import math
import os
import platform
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.utils.pixel_metrics import compare_images
from src.app.services.evidence import AssetDownloadPolicy, download_asset


DEFAULT_MANIFEST = _ROOT / "tests" / "fixtures" / "p1" / "canonical" / "manifest.json"
FONT_FILES = (
    "segoeui.ttf",
    "msyh.ttc",
    "arial.ttf",
    "simhei.ttf",
)


class _QuietHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run canonical Chromium output fidelity checks."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=_ROOT / "output" / "_p1_canonical_output_fidelity",
    )
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    visual_policy = _load_visual_policy(manifest)
    environment = collect_canonical_environment(manifest)
    sample_results = []
    for sample in manifest.get("samples") or []:
        if not isinstance(sample, dict):
            continue
        sample_results.append(
            evaluate_sample(
                sample,
                args.out_root,
                environment,
                args.reuse_existing,
                visual_policy,
            )
        )
    result = {
        "schema_version": "p1-canonical-output-fidelity/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(args.manifest),
        "canonical_engine": "chromium",
        "environment": environment,
        "visual_policy": visual_policy,
        "samples": sample_results,
        "summary": summarize_samples(sample_results),
        "gate_policy": {
            "content": "required",
            "critical_geometry": "required-1px-starting-threshold",
            "assets": "required-when-declared",
            "native_text": "required-when-declared",
            "visual": "measured-not-gated",
            "figma": "not-evaluated-without-real-write-readback-render",
            "composite_score_used": False,
        },
        "note": (
            "The legacy cross-browser strict count is diagnostic under this "
            "canonical-output contract. SVG and Figma are evaluated separately."
        ),
    }
    out = args.out_root / "round1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "summary": result["summary"],
                "output": str(out),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["summary"]["failed_count"] == 0 else 1


def evaluate_sample(
    sample: dict[str, Any],
    out_root: Path,
    environment: dict[str, Any],
    reuse_existing: bool,
    visual_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sample_id = str(sample.get("sample_id") or "")
    sample_root = out_root / "samples" / sample_id
    source = _ROOT / str(sample.get("source") or "")
    truth_path = _ROOT / str(sample.get("truth") or "")
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    command_result = None
    remote_assets: list[dict[str, Any]] = []
    remote_base = None
    server = None
    if sample.get("remote_asset_directory"):
        server, remote_base = _start_remote_asset_server(
            _ROOT / str(sample["remote_asset_directory"])
        )
    try:
        prepared_source = _prepare_sample_source(
            source,
            sample_root,
            remote_base,
        )
        if not (reuse_existing and (sample_root / "render.png").is_file()):
            command_result = run_dom_svg_capture(
                prepared_source,
                sample_root,
                environment,
            )
        if remote_base and truth.get("expected_remote_assets"):
            remote_assets = _download_expected_remote_assets(
                truth.get("expected_remote_assets") or [],
                remote_base,
            )
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
    design_path = sample_root / "12_design.json"
    reference_path = sample_root / "00_screenshot.png"
    render_path = sample_root / "render.png"
    page_state_path = sample_root / "00_page_state.json"
    svg_path = sample_root / "prototype.svg"
    missing = [
        path.name
        for path in (
            design_path,
            reference_path,
            render_path,
            page_state_path,
            svg_path,
        )
        if not path.is_file()
    ]
    if missing:
        return {
            "sample_id": sample_id,
            "source": str(source),
            "out_dir": str(sample_root),
            "capture": {"status": "fail", "missing_artifacts": missing},
            "svg": {"status": "not-evaluated", "missing_artifacts": missing},
            "figma": {
                "status": "not-evaluated",
                "reason": "real-write-readback-render-not-run",
            },
            "command_returncode": (
                command_result.returncode if command_result is not None else None
            ),
            "command_stdout": (
                (command_result.stdout or "")[-4000:]
                if command_result is not None
                else None
            ),
            "command_stderr": (
                (command_result.stderr or "")[-4000:]
                if command_result is not None
                else None
            ),
            "failed": True,
        }
    design = json.loads(design_path.read_text(encoding="utf-8"))
    page_state = json.loads(page_state_path.read_text(encoding="utf-8"))
    design_result = evaluate_design_against_truth(design, truth)
    if truth.get("expected_remote_assets"):
        design_result["remote_assets"] = verify_remote_asset_evidence(
            remote_assets,
            truth.get("expected_remote_assets") or [],
        )
    visual = evaluate_visual_fidelity(
        reference_path,
        render_path,
        exclusion_regions=truth.get("visual_exclusion_regions") or [],
    )
    visual_class = str(truth.get("visual_class") or "")
    if visual_policy and visual_class:
        thresholds = (visual_policy.get("classes") or {}).get(visual_class)
        if isinstance(thresholds, dict):
            visual.update(apply_visual_policy(visual, thresholds))
    capture = evaluate_capture(page_state)
    svg_status = _svg_status(
        capture=capture,
        design_result=design_result,
    )
    expected_status = design_result.get("expected_output_status") or "pass"
    failed = (
        (command_result is not None and command_result.returncode != 0)
        or svg_status == "fail"
        or visual.get("status") == "fail"
        or (expected_status == "pass" and svg_status != "pass")
    )
    return {
        "sample_id": sample_id,
        "source": str(source),
        "out_dir": str(sample_root),
        "command_returncode": (
            command_result.returncode if command_result is not None else None
        ),
        "command_stdout": (
            (command_result.stdout or "")[-4000:]
            if command_result is not None
            else None
        ),
        "command_stderr": (
            (command_result.stderr or "")[-4000:]
            if command_result is not None
            else None
        ),
        "capture": capture,
        "design": design_result,
        "remote_asset_downloads": remote_assets,
        "visual": visual,
        "svg": {
            "status": svg_status,
            "path": str(svg_path),
            "scope": "content+geometry+assets+native-text",
        },
        "figma": {
            "status": "not-evaluated",
            "reason": "real-write-readback-render-not-run",
        },
        "failed": failed,
    }


def evaluate_design_against_truth(
    design: dict[str, Any],
    truth: dict[str, Any],
) -> dict[str, Any]:
    elements = [
        item for item in (design.get("elements") or []) if isinstance(item, dict)
    ]
    text_elements = [
        item
        for item in elements
        if str(item.get("type") or "") == "text" and str(item.get("text") or "").strip()
    ]
    actual_texts = [_normalize_text(item.get("text")) for item in text_elements]
    expected_texts = [
        _normalize_text(item)
        for item in (truth.get("expected_texts") or [])
        if _normalize_text(item)
    ]
    matched_texts = [
        expected
        for expected in expected_texts
        if any(actual == expected or expected in actual for actual in actual_texts)
    ]
    missing_texts = [
        expected for expected in expected_texts if expected not in matched_texts
    ]
    forbidden_present = [
        _normalize_text(item)
        for item in (truth.get("expected_absent_texts") or [])
        if any(_normalize_text(item) in actual for actual in actual_texts)
    ]
    coverage = len(matched_texts) / len(expected_texts) if expected_texts else 1.0
    content_pass = not missing_texts and not forbidden_present

    geometry_rows = []
    for expected_box in truth.get("critical_boxes") or []:
        text = _normalize_text(expected_box.get("text"))
        actual = next(
            (
                item
                for item in text_elements
                if _normalize_text(item.get("text")) == text
            ),
            None,
        )
        tolerance = float(expected_box.get("tolerance_px", 1))
        row = {
            "text": text,
            "tolerance_px": tolerance,
            "expected": {
                key: float(expected_box.get(key))
                for key in ("x", "y", "width", "height")
            },
            "actual": None,
            "passed": False,
        }
        if actual is not None:
            actual_box = {
                key: float(actual.get(key)) for key in ("x", "y", "width", "height")
            }
            max_delta = max(
                abs(actual_box[key] - row["expected"][key]) for key in row["expected"]
            )
            row["actual"] = actual_box
            row["max_delta_px"] = max_delta
            row["passed"] = max_delta <= tolerance
        geometry_rows.append(row)
    geometry_pass = all(item["passed"] for item in geometry_rows)

    font_rows = []
    for marker in truth.get("expected_font_markers") or []:
        text = _normalize_text(marker.get("text"))
        actual = next(
            (
                item
                for item in text_elements
                if _normalize_text(item.get("text")) == text
            ),
            None,
        )
        family = ""
        if actual is not None:
            family = str(
                actual.get("fontFamily")
                or (actual.get("style") or {}).get("fontFamily")
                or ""
            )
        needle = str(marker.get("family_contains") or "")
        passed = bool(needle) and needle.lower() in family.lower()
        font_rows.append(
            {
                "text": text,
                "family_contains": needle,
                "actual_font_family": family,
                "passed": passed,
            }
        )
    font_pass = all(item["passed"] for item in font_rows)

    expected_assets = int(truth.get("expected_asset_count", 0) or 0)
    minimum_assets = int(truth.get("minimum_asset_count", expected_assets) or 0)
    asset_elements = [
        item
        for item in elements
        if str(item.get("type") or "") == "image"
        and (item.get("imageBase64") or item.get("fillColor") or item.get("asset"))
    ]
    actual_assets = len(asset_elements)
    expected_output_status = str(truth.get("expected_output_status") or "pass")
    asset_region_rows = []
    for region in truth.get("expected_asset_regions") or []:
        tolerance = float(region.get("tolerance_px", 1))
        expected_box = {
            key: float(region.get(key)) for key in ("x", "y", "width", "height")
        }
        candidate = None
        for item in asset_elements:
            actual_box = {
                key: float(item.get(key)) for key in ("x", "y", "width", "height")
            }
            if all(
                abs(actual_box[key] - expected_box[key]) <= tolerance
                for key in expected_box
            ):
                candidate = item
                break
        requires_bytes = bool(region.get("require_local_bytes"))
        has_bytes = bool(
            candidate
            and (
                candidate.get("imageBase64")
                or candidate.get("asset")
                or candidate.get("fillColor")
            )
        )
        identity = candidate.get("assetIdentity") or {} if candidate is not None else {}
        crop = candidate.get("sourceCrop") or {} if candidate is not None else {}
        expected_sha = str(region.get("expected_content_sha256") or "")
        identity_passed = (
            not expected_sha
            or str(identity.get("content_sha256") or "") == expected_sha
        )
        expected_natural = region.get("expected_natural_size")
        if expected_natural:
            identity_passed = identity_passed and _numeric_list_close(
                identity.get("natural_size"),
                expected_natural,
                tolerance=1.0,
            )
        expected_rect = region.get("expected_source_rect")
        expected_fit = str(region.get("expected_object_fit") or "")
        crop_passed = (
            not expected_rect
            or _numeric_list_close(
                crop.get("source_rect"),
                expected_rect,
                tolerance=1.0,
            )
        ) and (not expected_fit or str(crop.get("object_fit") or "") == expected_fit)
        asset_region_rows.append(
            {
                "name": str(region.get("name") or ""),
                "expected": expected_box,
                "tolerance_px": tolerance,
                "found": candidate is not None,
                "require_local_bytes": requires_bytes,
                "has_local_bytes": has_bytes,
                "identity_passed": identity_passed,
                "crop_passed": crop_passed,
                "passed": (
                    candidate is not None
                    and (not requires_bytes or has_bytes)
                    and identity_passed
                    and crop_passed
                ),
            }
        )
    regions_pass = all(row["passed"] for row in asset_region_rows)
    if actual_assets >= expected_assets:
        asset_status = "pass"
    elif actual_assets >= minimum_assets and expected_output_status == "partial":
        asset_status = "partial"
    else:
        asset_status = "fail"
    if not regions_pass:
        asset_status = "fail"

    native_text_required = bool(truth.get("native_text_required"))
    native_text_count = len(text_elements)
    editability_status = (
        "pass" if not native_text_required or native_text_count > 0 else "fail"
    )
    return {
        "content": {
            "status": "pass" if content_pass else "fail",
            "expected_text_count": len(expected_texts),
            "matched_text_count": len(matched_texts),
            "text_coverage": coverage,
            "missing_texts": missing_texts,
            "forbidden_present": forbidden_present,
        },
        "geometry": {
            "status": "pass" if geometry_pass else "fail",
            "critical_box_count": len(geometry_rows),
            "rows": geometry_rows,
        },
        "font": {
            "status": "pass" if font_pass else "fail",
            "scope": "declared-font-family-not-final-glyph-identity",
            "marker_count": len(font_rows),
            "rows": font_rows,
        },
        "assets": {
            "status": asset_status,
            "expected_asset_count": expected_assets,
            "minimum_asset_count": minimum_assets,
            "actual_asset_element_count": actual_assets,
            "missing_asset_count": max(0, expected_assets - actual_assets),
            "scope": ("displayed-box-and-local-bytes-not-source-crop-identity"),
            "region_rows": asset_region_rows,
        },
        "editability": {
            "status": editability_status,
            "scope": "native-text-only",
            "native_text_count": native_text_count,
            "not_evaluated": ["parent-layout-propagation"],
        },
        "expected_output_status": expected_output_status,
        "expected_limitations": list(truth.get("expected_limitations") or []),
        "composite_score_used": False,
    }


def evaluate_visual_fidelity(
    reference_path: Path,
    render_path: Path,
    *,
    exclusion_regions: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    import cv2
    import numpy as np

    reference = cv2.imread(str(reference_path))
    render = cv2.imread(str(render_path))
    if reference is None or render is None:
        return {
            "status": "not-evaluated",
            "reason": "image-unreadable",
        }
    size_match = reference.shape[:2] == render.shape[:2]
    scored_render = render
    if not size_match:
        scored_render = cv2.resize(
            render,
            (reference.shape[1], reference.shape[0]),
        )
    raw_diff = np.abs(scored_render.astype(np.int16) - reference.astype(np.int16))
    diff = raw_diff.max(axis=2)
    height, width = diff.shape
    valid = np.ones((height, width), dtype=bool)
    exclusions = []
    for region in exclusion_regions or []:
        try:
            x = max(0, int(round(float(region.get("x")))))
            y = max(0, int(round(float(region.get("y")))))
            w = max(0, int(round(float(region.get("width")))))
            h = max(0, int(round(float(region.get("height")))))
        except (TypeError, ValueError):
            continue
        x1 = min(width, x + w)
        y1 = min(height, y + h)
        if x1 <= x or y1 <= y:
            continue
        valid[y:y1, x:x1] = False
        exclusions.append(dict(region))
    valid_count = int(valid.sum())
    gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    ink = (gray < 200) & valid
    values = raw_diff[valid]
    ink_values = raw_diff[..., 0][ink]
    report = {
        "mean": float(values.mean()) if valid_count else 0.0,
        "ink_mean": float(ink_values.mean()) if ink.any() else 0.0,
        "over30_pct": (float((diff[valid] > 30).mean() * 100) if valid_count else 0.0),
        "ink_px": int(ink.sum()),
    }
    bands = []
    for index in range(4):
        y0 = round(index * height / 4)
        y1 = round((index + 1) * height / 4)
        band_valid = valid[y0:y1]
        bands.append(
            {
                "index": index,
                "y0": y0,
                "y1": y1,
                "mean_max_channel_delta": (
                    float(diff[y0:y1][band_valid].mean()) if band_valid.any() else 0.0
                ),
            }
        )
    return {
        "status": "measured-not-gated",
        "reference": str(reference_path),
        "render": str(render_path),
        "reference_shape": list(reference.shape),
        "render_shape": list(render.shape),
        "size_match": size_match,
        "mean": report["mean"],
        "ink_mean": report["ink_mean"],
        "over30_pct": report["over30_pct"],
        "ink_px": report["ink_px"],
        "diff_pixel_count": int(((diff > 0) & valid).sum()),
        "bad_pixel_count": int(((diff > 30) & valid).sum()),
        "excluded_regions": exclusions,
        "excluded_region_pixel_count": (height * width) - valid_count,
        "bands": bands,
        "threshold_state": "not-calibrated",
    }


def apply_visual_policy(
    metrics: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    base_bad_pixel_limit = int(policy.get("max_bad_pixel_count", 2**63 - 1))
    reference_area = int(policy.get("bad_pixel_count_reference_area", 0) or 0)
    shape = metrics.get("reference_shape") or []
    actual_area = (
        int(shape[0]) * int(shape[1])
        if isinstance(shape, (list, tuple)) and len(shape) >= 2
        else 0
    )
    area_scale = (
        actual_area / reference_area if reference_area > 0 and actual_area > 0 else 1.0
    )
    effective_bad_pixel_limit = math.ceil(base_bad_pixel_limit * area_scale)
    gate_bad_pixel_count = bool(policy.get("gate_bad_pixel_count", True))
    failed: list[str] = []
    checks = {
        "mean": float(metrics.get("mean") or 0.0)
        <= float(policy.get("max_mean", float("inf"))),
        "ink_mean": float(metrics.get("ink_mean") or 0.0)
        <= float(policy.get("max_ink_mean", float("inf"))),
        "over30_pct": float(metrics.get("over30_pct") or 0.0)
        <= float(policy.get("max_over30_pct", float("inf"))),
    }
    if gate_bad_pixel_count:
        checks["bad_pixel_count"] = (
            int(metrics.get("bad_pixel_count") or 0) <= effective_bad_pixel_limit
        )
    if policy.get("require_size_match") and not metrics.get("size_match"):
        checks["size_match"] = False
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "status": "pass" if not failed else "fail",
        "policy_id": str(policy.get("policy_id") or ""),
        "failed_metrics": failed,
        "checks": checks,
        "gate_bad_pixel_count": gate_bad_pixel_count,
        "bad_pixel_count_area_scale": area_scale,
        "effective_max_bad_pixel_count": effective_bad_pixel_limit,
        "composite_score_used": False,
    }


def verify_remote_asset_evidence(
    rows: Sequence[dict[str, Any]],
    expected: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {
        str(row.get("asset_id") or ""): row for row in rows if isinstance(row, dict)
    }
    checks = []
    for item in expected:
        asset_id = str(item.get("asset_id") or "")
        row = by_id.get(asset_id) or {}
        url = str(row.get("final_url") or row.get("source_url") or "")
        suffix = str(item.get("url_suffix") or "")
        expected_mime = str(item.get("mime") or "")
        expected_sha = str(item.get("sha256") or "")
        checks.append(
            {
                "asset_id": asset_id,
                "status_passed": row.get("status") == "downloaded",
                "url_passed": bool(suffix) and url.endswith(suffix),
                "mime_passed": (
                    not expected_mime or str(row.get("mime") or "") == expected_mime
                ),
                "sha256_passed": (
                    not expected_sha or str(row.get("sha256") or "") == expected_sha
                ),
            }
        )
    return {
        "status": "pass"
        if checks
        and all(
            all(value for key, value in row.items() if key.endswith("_passed"))
            for row in checks
        )
        else "fail",
        "expected_count": len(expected),
        "rows": checks,
    }


def evaluate_capture(page_state: dict[str, Any]) -> dict[str, Any]:
    navigation = page_state.get("navigation") or {}
    stability = page_state.get("capture_stability") or {}
    kind = str(page_state.get("kind") or "")
    status = (
        "pass"
        if kind == "content"
        and navigation.get("status") in {"ok", "redirected"}
        and stability.get("stable") is True
        else "fail"
    )
    return {
        "status": status,
        "page_state": kind,
        "navigation": navigation.get("status"),
        "stable": stability.get("stable"),
        "stable_ms": stability.get("stable_ms"),
        "screenshot_only": bool(page_state.get("screenshot_only")),
    }


def collect_canonical_environment(manifest: dict[str, Any]) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    env = manifest.get("environment") or {}
    viewport = env.get("viewport") or {"width": 900, "height": 700}
    dpr = int(env.get("device_scale_factor", 1))
    locale = str(env.get("locale", "zh-CN"))
    timezone = str(env.get("timezone", "Asia/Shanghai"))
    browser_version = None
    executable_path = None
    with sync_playwright() as playwright:
        browser_type = playwright.chromium
        executable_path = str(browser_type.executable_path)
        browser = browser_type.launch(headless=True)
        try:
            browser_version = str(browser.version)
        finally:
            browser.close()
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    font_records = [_font_record(fonts_dir / name) for name in FONT_FILES]
    return {
        "schema_version": "p1-canonical-environment/1.0",
        "engine": "chromium",
        "browser_version": browser_version,
        "executable_path": executable_path,
        "python_version": platform.python_version(),
        "os": platform.platform(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "viewport": viewport,
        "device_scale_factor": dpr,
        "locale": locale,
        "timezone": timezone,
        "headless": True,
        "font_files": font_records,
        "capture_contract": "capture_page_with_fallback+dom-direct-svg",
    }


def run_dom_svg_capture(
    source: Path,
    out_dir: Path,
    environment: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    url = source.resolve().as_uri()
    command = [
        sys.executable,
        "-m",
        "src.main",
        "--url",
        url,
        "--route",
        "dom",
        "--tool",
        "svg",
        "--output-dir",
        str(out_dir),
        "--no-headed-fallback",
    ]
    viewport = environment.get("viewport") or {}
    child_env = os.environ.copy()
    child_env.update(
        {
            "PLAYWRIGHT_BROWSER": "chromium",
            "PLAYWRIGHT_HEADLESS": "true",
            "PLAYWRIGHT_HEADED_FALLBACK": "false",
            "PLAYWRIGHT_VIEWPORT_WIDTH": str(int(viewport.get("width", 900))),
            "PLAYWRIGHT_VIEWPORT_HEIGHT": str(int(viewport.get("height", 700))),
            "DEVICE_SCALE_FACTOR": str(int(environment.get("device_scale_factor", 1))),
            "WAIT_NETWORKIDLE_TIMEOUT": "15000",
        }
    )
    return subprocess.run(
        command,
        cwd=str(_ROOT),
        env=child_env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _start_remote_asset_server(
    directory: Path,
) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(
        _QuietHTTPHandler,
        directory=str(directory),
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _prepare_sample_source(
    source: Path,
    sample_root: Path,
    remote_base: str | None,
) -> Path:
    if not remote_base:
        return source
    text = source.read_text(encoding="utf-8")
    if "__REMOTE_ASSET_BASE__" not in text:
        return source
    generated = sample_root / "_source" / source.name
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text(
        text.replace("__REMOTE_ASSET_BASE__", remote_base),
        encoding="utf-8",
    )
    return generated


def _download_expected_remote_assets(
    expected: Sequence[dict[str, Any]],
    base_url: str,
) -> list[dict[str, Any]]:
    policy = AssetDownloadPolicy(
        max_assets=max(1, len(expected)),
        max_bytes_per_asset=2 * 1024 * 1024,
        max_total_bytes=max(1, len(expected)) * 2 * 1024 * 1024,
        timeout_seconds=5.0,
        allow_private_hosts=True,
    )
    rows = []
    for item in expected:
        asset_id = str(item.get("asset_id") or "")
        suffix = str(item.get("url_suffix") or "")
        url = base_url.rstrip("/") + "/" + suffix.lstrip("/")
        row: dict[str, Any] = {
            "asset_id": asset_id,
            "source_url": url,
        }
        try:
            downloaded = download_asset(url, policy)
            row.update(
                {
                    "status": "downloaded",
                    "final_url": downloaded["final_url"],
                    "mime": downloaded["mime"],
                    "sha256": downloaded["sha256"],
                    "size_bytes": downloaded["size_bytes"],
                }
            )
        except Exception as exc:  # noqa: BLE001 - evidence retains failure
            row.update(
                {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        rows.append(row)
    return rows


def summarize_samples(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sample_count": len(samples),
        "svg_pass_count": sum(
            (item.get("svg") or {}).get("status") == "pass" for item in samples
        ),
        "svg_partial_count": sum(
            (item.get("svg") or {}).get("status") == "partial" for item in samples
        ),
        "failed_count": sum(bool(item.get("failed")) for item in samples),
        "figma_evaluated_count": sum(
            (item.get("figma") or {}).get("status") != "not-evaluated"
            for item in samples
        ),
        "visual_gated_count": sum(
            (item.get("visual") or {}).get("status") in {"pass", "fail"}
            for item in samples
        ),
        "visual_pass_count": sum(
            (item.get("visual") or {}).get("status") == "pass" for item in samples
        ),
        "visual_fail_count": sum(
            (item.get("visual") or {}).get("status") == "fail" for item in samples
        ),
        "composite_score_used": False,
    }


def _svg_status(
    *,
    capture: dict[str, Any],
    design_result: dict[str, Any],
) -> str:
    if capture.get("status") != "pass":
        return "fail"
    for dimension in ("content", "geometry", "font", "editability"):
        if (design_result.get(dimension) or {}).get("status") != "pass":
            return "fail"
    asset_status = (design_result.get("assets") or {}).get("status")
    expected = design_result.get("expected_output_status") or "pass"
    if expected == "partial":
        return "partial" if asset_status in {"pass", "partial"} else "fail"
    if asset_status != "pass":
        return "fail"
    if (
        design_result.get("remote_assets")
        and design_result["remote_assets"].get("status") != "pass"
    ):
        return "fail"
    return "pass"


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _numeric_list_close(
    actual: Any,
    expected: Any,
    *,
    tolerance: float,
) -> bool:
    try:
        actual_values = [float(value) for value in actual]
        expected_values = [float(value) for value in expected]
    except (TypeError, ValueError):
        return False
    return len(actual_values) == len(expected_values) and all(
        abs(actual_value - expected_value) <= tolerance
        for actual_value, expected_value in zip(
            actual_values,
            expected_values,
        )
    )


def _load_visual_policy(manifest: dict[str, Any]) -> dict[str, Any] | None:
    relative = manifest.get("visual_policy_path")
    if not relative:
        return None
    path = _ROOT / str(relative)
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def _font_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "name": path.name,
            "status": "missing",
        }
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "name": path.name,
        "status": "present",
        "size": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
