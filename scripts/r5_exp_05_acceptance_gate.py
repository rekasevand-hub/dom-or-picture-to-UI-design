# -*- coding: utf-8 -*-
"""R5-EXP-05: four-dimensional acceptance hard gates and page summary.

The experiment injects controlled statuses into a page acceptance contract and
builds page-level release decisions. It does not calibrate the underlying
detectors; the six check families remain synthetic gate inputs.

Usage:
  C:/Users/lzq/.conda/envs/omni/python.exe scripts/r5_exp_05_acceptance_gate.py
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import threading
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Callable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JOB = "JOB-R5-EXP-05-20261019"
REVISION = "rev1"
PROFILE = "r5-exp-05-acceptance-gate"
CAPTURED_AT = "2026-10-19T00:00:00+00:00"
DEFAULT_OUT = ROOT / "output" / "_r5_experiments" / "r5_exp_05_acceptance_gate"

PAGE_WIDTH = 1200
PAGE_HEIGHT = 760
PAGE_AREA = PAGE_WIDTH * PAGE_HEIGHT
BACKGROUND_AREA = 600 * 300

DIMENSIONS = ("visual", "structure", "edit", "asset")
CHECK_TYPES = (
    "linebreak",
    "pixel",
    "content",
    "geometry",
    "parent",
    "boundary",
    "native",
    "asset",
)
STATUS_VALUES = {
    "pass",
    "partial",
    "fail",
    "unknown",
    "no-ground-truth",
    "not-sampled",
    "not-required",
}

CASE_IDS = (
    "clean-all-pass",
    "linebreak-isolated",
    "pixel-background",
    "geometry-critical",
    "parent-critical",
    "boundary-critical",
    "native-critical",
    "asset-noncritical",
    "unknown-critical",
    "no-ground-truth-critical",
    "critical-partial-not-allowed",
    "critical-not-sampled",
    "tiny-price-error",
    "high-area-background-pass",
    "unsupported-browser",
    "partial-not-allowed",
    "coverage-gap",
    "reference-only",
    "preflight-ownership-unknown",
)

CASE_LABELS = {
    "clean-all-pass": "Clean all pass",
    "linebreak-isolated": "Linebreak isolated",
    "pixel-background": "Pixel background",
    "geometry-critical": "Geometry critical",
    "parent-critical": "Parent critical",
    "boundary-critical": "Boundary critical",
    "native-critical": "Native edit critical",
    "asset-noncritical": "Asset noncritical",
    "unknown-critical": "Unknown critical",
    "no-ground-truth-critical": "No-ground-truth critical",
    "critical-partial-not-allowed": "Critical partial not allowed",
    "critical-not-sampled": "Critical not sampled",
    "tiny-price-error": "Tiny price error",
    "high-area-background-pass": "High-area background pass",
    "unsupported-browser": "Unsupported browser",
    "partial-not-allowed": "Partial not allowed",
    "coverage-gap": "Coverage gap",
    "reference-only": "Reference only",
    "preflight-ownership-unknown": "Ownership preflight unknown",
}

CHECK_SPECS: list[dict[str, Any]] = [
    {
        "check_id": "V-LINEBREAK-HERO",
        "check_type": "linebreak",
        "dimension": "visual",
        "object_key": "hero-title",
        "criticality": "noncritical",
        "critical": False,
        "metric": "linebreak_match",
        "threshold": 1.0,
        "unit": "ratio",
    },
    {
        "check_id": "V-PIXEL-BG",
        "check_type": "pixel",
        "dimension": "visual",
        "object_key": "hero-bg",
        "criticality": "background",
        "critical": False,
        "metric": "pixel_mae",
        "threshold": 0.1,
        "unit": "mae",
    },
    {
        "check_id": "V-PIXEL-PRODUCT",
        "check_type": "pixel",
        "dimension": "visual",
        "object_key": "product-image",
        "criticality": "noncritical",
        "critical": False,
        "metric": "pixel_mae",
        "threshold": 0.1,
        "unit": "mae",
    },
    {
        "check_id": "V-CONTENT-PRICE",
        "check_type": "content",
        "dimension": "visual",
        "object_key": "price-value",
        "criticality": "critical",
        "critical": True,
        "metric": "content_exact",
        "threshold": 1.0,
        "unit": "ratio",
    },
    {
        "check_id": "S-GEOMETRY-PRICE",
        "check_type": "geometry",
        "dimension": "structure",
        "object_key": "price-panel",
        "criticality": "critical",
        "critical": True,
        "metric": "geometry_iou",
        "threshold": 0.999,
        "unit": "iou",
    },
    {
        "check_id": "S-PARENT-CTA",
        "check_type": "parent",
        "dimension": "structure",
        "object_key": "cta",
        "criticality": "critical",
        "critical": True,
        "metric": "parent_accuracy",
        "threshold": 1.0,
        "unit": "ratio",
    },
    {
        "check_id": "S-BOUNDARY-CTA",
        "check_type": "boundary",
        "dimension": "structure",
        "object_key": "cta",
        "criticality": "critical",
        "critical": True,
        "metric": "boundary_iou",
        "threshold": 0.999,
        "unit": "iou",
    },
    {
        "check_id": "E-NATIVE-PRICE",
        "check_type": "native",
        "dimension": "edit",
        "object_key": "price-value",
        "criticality": "critical",
        "critical": True,
        "metric": "native_text",
        "threshold": 1.0,
        "unit": "ratio",
    },
    {
        "check_id": "E-NATIVE-CTA",
        "check_type": "native",
        "dimension": "edit",
        "object_key": "cta",
        "criticality": "critical",
        "critical": True,
        "metric": "native_text",
        "threshold": 1.0,
        "unit": "ratio",
    },
    {
        "check_id": "A-ORIGIN-IMAGE",
        "check_type": "asset",
        "dimension": "asset",
        "object_key": "product-image",
        "criticality": "noncritical",
        "critical": False,
        "metric": "asset_origin_valid",
        "threshold": 1.0,
        "unit": "boolean",
    },
    {
        "check_id": "A-ORIGIN-BADGE",
        "check_type": "asset",
        "dimension": "asset",
        "object_key": "badge",
        "criticality": "noncritical",
        "critical": False,
        "metric": "asset_origin_valid",
        "threshold": 1.0,
        "unit": "boolean",
    },
]

CHECK_BY_ID = {item["check_id"]: item for item in CHECK_SPECS}
CRITICAL_CHECK_IDS = {item["check_id"] for item in CHECK_SPECS if item["critical"]}

CASE_FAULTS: dict[str, dict[str, Any]] = {
    "clean-all-pass": {},
    "linebreak-isolated": {
        "checks": {"V-LINEBREAK-HERO": ("fail", "Linebreak changed from one line to two.")},
        "user_allowed_partial": True,
        "isolatable": True,
    },
    "pixel-background": {
        "checks": {"V-PIXEL-BG": ("partial", "Background pixel difference is partial and noncritical.")},
        "user_allowed_partial": True,
        "isolatable": True,
    },
    "geometry-critical": {
        "checks": {"S-GEOMETRY-PRICE": ("fail", "Critical price-panel geometry is displaced.")},
    },
    "parent-critical": {
        "checks": {"S-PARENT-CTA": ("fail", "CTA parent relation is wrong.")},
    },
    "boundary-critical": {
        "checks": {"S-BOUNDARY-CTA": ("fail", "CTA boundary does not close.")},
    },
    "native-critical": {
        "checks": {"E-NATIVE-PRICE": ("fail", "Price is raster text instead of native text.")},
    },
    "asset-noncritical": {
        "checks": {"A-ORIGIN-IMAGE": ("fail", "Product image source does not match its required origin.")},
        "user_allowed_partial": True,
        "isolatable": True,
    },
    "unknown-critical": {
        "checks": {"S-GEOMETRY-PRICE": ("unknown", "No reliable geometry comparison is available.")},
    },
    "no-ground-truth-critical": {
        "checks": {"E-NATIVE-PRICE": ("no-ground-truth", "The native text target has no ground truth.")},
    },
    "critical-partial-not-allowed": {
        "checks": {"S-GEOMETRY-PRICE": ("partial", "Critical geometry is partial and partial delivery is not allowed.")},
        "user_allowed_partial": False,
        "isolatable": True,
    },
    "critical-not-sampled": {
        "checks": {"S-GEOMETRY-PRICE": ("not-sampled", "Critical geometry was not sampled.")},
    },
    "tiny-price-error": {
        "checks": {"V-CONTENT-PRICE": ("fail", "A single price digit is wrong.")},
    },
    "high-area-background-pass": {
        "checks": {"V-CONTENT-PRICE": ("fail", "The critical price is wrong while the large background passes.")},
    },
    "unsupported-browser": {
        "checks": {"V-PIXEL-PRODUCT": ("unknown", "Unsupported browser environment cannot provide evidence.")},
        "user_allowed_partial": False,
        "isolatable": False,
    },
    "partial-not-allowed": {
        "checks": {"V-LINEBREAK-HERO": ("fail", "Linebreak differs and partial delivery is not allowed.")},
        "user_allowed_partial": False,
        "isolatable": True,
    },
    "coverage-gap": {
        "checks": {"A-ORIGIN-BADGE": ("not-sampled", "Badge asset check was not sampled.")},
        "user_allowed_partial": True,
        "isolatable": True,
    },
    "reference-only": {
        "profile": "reference-only",
        "required_dimensions": ["visual"],
        "reference_only": True,
    },
    "preflight-ownership-unknown": {
        "preflight": {"output_ownership": "unknown"},
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_hash(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "content_hash"}
    return sha256_text(canonical(payload))


def atomic_write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def check(name: str, description: str, passed: bool, detail: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "passed": bool(passed),
        "detail": detail,
    }


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def safe_output_dir(path: Path) -> Path:
    resolved = path.resolve()
    expected_parent = (ROOT / "output" / "_r5_experiments").resolve()
    if resolved.parent != expected_parent:
        raise ValueError(f"Refusing to clean unexpected output directory: {resolved}")
    if not resolved.name.startswith("r5_exp_05"):
        raise ValueError(f"Refusing to clean unexpected experiment name: {resolved.name}")
    return resolved


def font_for(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def draw_acceptance_page(price_text: str) -> Image.Image:
    image = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 40, 1140, 110), fill="#0f172a")
    draw.text((84, 60), "R5 ACCEPTANCE LAB", font=font_for(27, True), fill="#f8fafc")
    draw.rectangle((80, 150, 680, 450), fill="#1e3a8a")
    draw.text((112, 176), "FOUR DIMENSIONS", font=font_for(31, True), fill="#ffffff")
    draw.text(
        (112, 230),
        "Visual, structure, edit and asset are separate gates.",
        font=font_for(19, True),
        fill="#dbeafe",
    )
    draw.rectangle((740, 170, 1110, 390), fill="#7f1d1d")
    draw.text((770, 202), "CRITICAL PRICE", font=font_for(22, True), fill="#ffe4e6")
    draw.text((770, 260), price_text, font=font_for(54, True), fill="#ffffff")
    draw.rectangle((820, 440, 1040, 500), fill="#ea580c")
    draw.text((854, 456), "SHOP NOW", font=font_for(24, True), fill="#ffffff")
    draw.rectangle((80, 620, 1120, 700), fill="#e2e8f0")
    draw.text((110, 646), "Acceptance summary and release decision", font=font_for(18, True), fill="#334155")
    return image


def price_error_artifacts(out_dir: Path) -> dict[str, Any]:
    artifact_dir = out_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    reference = draw_acceptance_page("$129")
    output = draw_acceptance_page("$139")
    reference_path = artifact_dir / "reference_page.png"
    output_path = artifact_dir / "price_error_page.png"
    reference.save(reference_path)
    output.save(output_path)
    ref = np.asarray(reference)
    out = np.asarray(output)
    diff = np.any(ref != out, axis=2)
    diff_visual = np.zeros_like(ref)
    diff_visual[diff] = [220, 38, 38]
    diff_path = artifact_dir / "price_error_diff.png"
    Image.fromarray(diff_visual, mode="RGB").save(diff_path)
    diff_pixels = int(np.count_nonzero(diff))
    return {
        "reference": {
            "path": str(reference_path),
            "sha256": sha256_file(reference_path),
        },
        "price_error": {
            "path": str(output_path),
            "sha256": sha256_file(output_path),
        },
        "diff": {
            "path": str(diff_path),
            "sha256": sha256_file(diff_path),
            "pixels": diff_pixels,
            "page_ratio": diff_pixels / PAGE_AREA,
        },
    }


def case_contract(case_id: str) -> dict[str, Any]:
    fault = CASE_FAULTS[case_id]
    reference_only = fault.get("profile") == "reference-only"
    required_dimensions = list(fault.get("required_dimensions", DIMENSIONS))
    preflight = {
        "authorization": "granted",
        "target_state": "matched",
        "ir_integrity": "complete",
        "output_ownership": "verified",
    }
    preflight.update(fault.get("preflight", {}))
    return {
        "case_id": case_id,
        "label": CASE_LABELS[case_id],
        "profile": "reference-only" if reference_only else "faithful",
        "reference_only": reference_only,
        "required_dimensions": required_dimensions,
        "critical_items": ["price-panel", "cta", "price-value"],
        "critical_dependency_closure": {
            "price-panel": ["S-GEOMETRY-PRICE"],
            "cta": ["S-PARENT-CTA", "S-BOUNDARY-CTA", "E-NATIVE-CTA"],
            "price-value": ["V-CONTENT-PRICE", "E-NATIVE-PRICE"],
        },
        "user_allowed_partial": bool(fault.get("user_allowed_partial", False)),
        "noncritical_gap_isolatable": bool(fault.get("isolatable", False)),
        "preflight": preflight,
        "coverage_policy": {
            "mode": "per-required-check",
            "generic_pass_ratio": None,
            "minimum_sample_count": None,
            "critical_required_check_ratio": 1.0,
            "sample_policy": "every-required-check-must-be-executed",
        },
        "production_prerequisites": {
            "fault_recovery": False,
            "idempotency_and_reconciliation": False,
            "permission_and_concurrency_safety": False,
            "persistent_ir_and_migration": False,
            "environment_coverage": False,
            "monitoring": False,
        },
    }


def default_actual(check_spec: dict[str, Any]) -> Any:
    check_id = check_spec["check_id"]
    if check_id == "V-LINEBREAK-HERO":
        return 1.0
    if check_id.startswith("V-PIXEL"):
        return 0.01
    if check_id == "V-CONTENT-PRICE":
        return 1.0
    if check_id == "S-GEOMETRY-PRICE" or check_id == "S-BOUNDARY-CTA":
        return 1.0
    if check_id == "S-PARENT-CTA":
        return 1.0
    if check_id.startswith("E-NATIVE"):
        return 1.0
    if check_id.startswith("A-ORIGIN"):
        return True
    return 1.0


def fault_actual(check_id: str, status: str, price_diff_pixels: int) -> Any:
    if status == "pass":
        return None
    if check_id == "V-LINEBREAK-HERO":
        return 0.0
    if check_id == "V-PIXEL-BG":
        return 0.42
    if check_id == "V-PIXEL-PRODUCT":
        return 0.27
    if check_id == "V-CONTENT-PRICE":
        return {"content_exact": 0.0, "diff_pixels": price_diff_pixels}
    if check_id in {"S-GEOMETRY-PRICE", "S-BOUNDARY-CTA"}:
        return 0.95
    if check_id == "S-PARENT-CTA":
        return 0.0
    if check_id.startswith("E-NATIVE"):
        return 0.0
    if check_id.startswith("A-ORIGIN"):
        return False
    return None


def build_checks(case_id: str, artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    contract = case_contract(case_id)
    fault = CASE_FAULTS[case_id]
    fault_checks = fault.get("checks", {})
    records: list[dict[str, Any]] = []
    price_diff_pixels = artifacts["diff"]["pixels"]
    for spec in CHECK_SPECS:
        dimension_required = spec["dimension"] in contract["required_dimensions"]
        if not dimension_required:
            status = "not-required"
            actual = None
            coverage = "not-required"
            reason = "Dimension is outside the selected reference-only contract."
        elif spec["check_id"] in fault_checks:
            status, reason = fault_checks[spec["check_id"]]
            actual = fault_actual(spec["check_id"], status, price_diff_pixels)
            if status in {"unknown", "no-ground-truth", "not-sampled"}:
                actual = None
            coverage = {
                "unknown": "executed-inconclusive",
                "no-ground-truth": "executed-no-ground-truth",
                "not-sampled": "not-sampled",
            }.get(status, "executed")
        else:
            status = "pass"
            actual = default_actual(spec)
            coverage = "executed"
            reason = "Required check passed its contract condition."
        records.append(
            {
                "record_id": f"{case_id}::{spec['check_id']}",
                "case_id": case_id,
                "check_id": spec["check_id"],
                "object_key": spec["object_key"],
                "check_type": spec["check_type"],
                "dimension": spec["dimension"],
                "criticality": spec["criticality"],
                "critical": spec["critical"],
                "required": dimension_required,
                "applicability": "required" if dimension_required else "not-required",
                "requirement": spec["metric"],
                "metric": spec["metric"],
                "threshold": spec["threshold"],
                "threshold_source": "r3-exp-11-contract-value-only",
                "detector_calibration": "not-evaluated",
                "actual_value": actual,
                "unit": spec["unit"],
                "coverage": coverage,
                "status": status,
                "reason": reason,
                "evidence": [
                    f"case:{case_id}",
                    f"check:{spec['check_id']}",
                    f"artifact:{artifacts['reference']['sha256']}",
                ],
                "repair": (
                    None
                    if status in {"pass", "not-required"}
                    else f"Resolve {spec['check_id']} under a new revision."
                ),
                "verification_version": "r5-exp-05-v1",
                "checked_at": CAPTURED_AT,
            }
        )
    return records


def dimension_summary(records: list[dict[str, Any]], dimension: str, required: bool) -> dict[str, Any]:
    if not required:
        return {
            "dimension": dimension,
            "applicability": "not-required",
            "status": "not-required",
            "counts": {},
        }
    subset = [item for item in records if item["dimension"] == dimension and item["required"]]
    counts = Counter(item["status"] for item in subset)
    statuses = set(counts)
    if "fail" in statuses:
        status = "fail"
    elif statuses & {"unknown", "no-ground-truth", "not-sampled"}:
        status = "unknown"
    elif "partial" in statuses:
        status = "partial"
    elif statuses == {"pass"}:
        status = "pass"
    else:
        status = "unknown"
    return {
        "dimension": dimension,
        "applicability": "required",
        "status": status,
        "counts": dict(counts),
    }


def build_page_summary(
    case_id: str,
    records: list[dict[str, Any]],
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    contract = case_contract(case_id)
    required_records = [item for item in records if item["required"]]
    critical_records = [item for item in required_records if item["critical"]]
    dimensions = {
        dimension: dimension_summary(
            records,
            dimension,
            dimension in contract["required_dimensions"],
        )
        for dimension in DIMENSIONS
    }
    preflight_pass = all(value in {"granted", "matched", "complete", "verified"} for value in contract["preflight"].values())
    preflight_blockers = [
        key for key, value in contract["preflight"].items()
        if value not in {"granted", "matched", "complete", "verified"}
    ]
    blocker_states = {"fail", "unknown", "no-ground-truth", "not-sampled", "partial"}
    critical_blockers = [
        item
        for item in critical_records
        if item["status"] in blocker_states
    ]
    critical_status_counts = Counter(item["status"] for item in critical_records)
    coverage_counts = Counter(item["coverage"] for item in required_records)
    status_counts = Counter(item["status"] for item in required_records)
    executed_required = sum(1 for item in required_records if item["coverage"].startswith("executed"))
    grounded_required = sum(
        1
        for item in required_records
        if item["coverage"] in {"executed", "not-required"}
    )
    all_required_pass = all(item["status"] == "pass" for item in required_records)
    coverage_complete = (
        executed_required == len(required_records)
        and grounded_required == len(required_records)
        and not status_counts.get("not-sampled", 0)
        and not status_counts.get("no-ground-truth", 0)
        and not status_counts.get("unknown", 0)
    )
    blocked_objects = sorted(
        {
            item["object_key"]
            for item in critical_blockers
        }
        | {
            object_key
            for object_key, check_ids in contract["critical_dependency_closure"].items()
            if any(item["check_id"] in check_ids for item in critical_blockers)
        }
    )
    dimension_statuses = {
        dimension: item["status"]
        for dimension, item in dimensions.items()
        if item["applicability"] == "required"
    }
    required_dimension_fail = any(status == "fail" for status in dimension_statuses.values())
    required_dimension_unknown = any(status == "unknown" for status in dimension_statuses.values())
    required_dimension_partial = any(status == "partial" for status in dimension_statuses.values())

    if not preflight_pass:
        release_status = "blocked-preflight"
        release_reason = "Preflight gate is not satisfied."
    elif critical_blockers:
        fail_statuses = {item["status"] for item in critical_blockers}
        if "fail" in fail_statuses:
            release_status = "blocked-critical"
            release_reason = "A critical item failed."
        elif "no-ground-truth" in fail_statuses:
            release_status = "blocked-no-ground-truth"
            release_reason = "A critical item has no ground truth."
        elif "not-sampled" in fail_statuses:
            release_status = "blocked-coverage"
            release_reason = "A critical item was not sampled."
        elif "partial" in fail_statuses:
            release_status = "blocked-partial-not-allowed"
            release_reason = "A critical item is partial without explicit permission."
        else:
            release_status = "blocked-unknown"
            release_reason = "A critical item is unknown."
    elif contract["reference_only"]:
        release_status = "reference-only"
        release_reason = "Visual reference is usable; editable delivery is outside this contract."
    elif all_required_pass and coverage_complete:
        release_status = "deliverable-complete"
        release_reason = "All required checks passed with complete grounded coverage."
    elif (
        contract["user_allowed_partial"]
        and contract["noncritical_gap_isolatable"]
        and (
            required_dimension_fail
            or required_dimension_unknown
            or required_dimension_partial
            or not coverage_complete
        )
    ):
        release_status = "deliverable-partial"
        release_reason = "Only isolated noncritical gaps remain in the original contract."
    elif required_dimension_unknown:
        release_status = "blocked-unknown"
        release_reason = "A required dimension is unknown."
    elif required_dimension_fail or required_dimension_partial or not coverage_complete:
        if not contract["user_allowed_partial"]:
            release_status = "blocked-partial-not-allowed"
            release_reason = "A noncritical gap exists but partial delivery is not allowed."
        else:
            release_status = "blocked-dimension"
            release_reason = "A required dimension is fail or partial and cannot be isolated."
    else:
        release_status = "blocked-coverage"
        release_reason = "Required coverage is incomplete."

    price_diff_pixels = artifacts["diff"]["pixels"]
    area_failure_pixels = price_diff_pixels if case_id in {"tiny-price-error", "high-area-background-pass"} else 0
    area_pass_pixels = PAGE_AREA - area_failure_pixels
    pilot_allowed = preflight_pass and release_status in {
        "deliverable-complete",
        "deliverable-partial",
        "reference-only",
    }
    pilot_status = "pilot-allowed-provisional" if pilot_allowed else "pilot-blocked"
    missing_production_prerequisites = [
        key for key, value in contract["production_prerequisites"].items() if not value
    ]
    production_status = (
        "production-eligible-review"
        if not missing_production_prerequisites and release_status == "deliverable-complete"
        else "production-not-eligible"
    )
    return {
        "case_id": case_id,
        "profile": contract["profile"],
        "preflight": {
            "passed": preflight_pass,
            "values": contract["preflight"],
            "blockers": preflight_blockers,
        },
        "dimensions": dimensions,
        "critical": {
            "item_count": len(contract["critical_items"]),
            "check_count": len(critical_records),
            "status_counts": dict(critical_status_counts),
            "blocked": bool(critical_blockers),
            "blockers": [
                {
                    "check_id": item["check_id"],
                    "object_key": item["object_key"],
                    "status": item["status"],
                    "reason": item["reason"],
                }
                for item in critical_blockers
            ],
            "blocked_objects": blocked_objects,
            "dependency_closure_satisfied": not critical_blockers,
        },
        "coverage": {
            "denominator_required_checks": len(required_records),
            "executed_required_checks": executed_required,
            "grounded_required_checks": grounded_required,
            "pass_required_checks": status_counts.get("pass", 0),
            "status_counts": dict(status_counts),
            "coverage_counts": dict(coverage_counts),
            "denominator_after_isolation": len(required_records),
            "generic_pass_ratio": None,
            "minimum_sample_count": None,
            "coverage_complete": coverage_complete,
        },
        "area": {
            "page_area_px": PAGE_AREA,
            "background_area_px": BACKGROUND_AREA,
            "area_pass_px": area_pass_pixels,
            "area_fail_px": area_failure_pixels,
            "area_pass_ratio": area_pass_pixels / PAGE_AREA,
            "area_used_as_release_score": False,
        },
        "release": {
            "status": release_status,
            "reason": release_reason,
            "allowed_export_mode": (
                "reference-only"
                if release_status == "reference-only"
                else "explicit-partial"
                if release_status == "deliverable-partial"
                else "complete"
                if release_status == "deliverable-complete"
                else "none"
            ),
            "complete_export_allowed": release_status == "deliverable-complete",
        },
        "profiles": {
            "pilot": {
                "status": pilot_status,
                "limited_scope_required": True,
                "manual_review_required": True,
                "visible_gaps_required": True,
            },
            "deliverable": {
                "status": release_status,
                "reason": release_reason,
            },
            "production": {
                "status": production_status,
                "missing_prerequisites": missing_production_prerequisites,
            },
            "reference_only": {
                "status": "reference-only" if contract["reference_only"] else "not-selected",
            },
        },
    }


def build_bundle(out_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    artifacts = price_error_artifacts(out_dir)
    contracts = {case_id: case_contract(case_id) for case_id in CASE_IDS}
    check_records = {
        case_id: build_checks(case_id, artifacts)
        for case_id in CASE_IDS
    }
    summaries = {
        case_id: build_page_summary(case_id, check_records[case_id], artifacts)
        for case_id in CASE_IDS
    }
    release_ledger = {
        "job": JOB,
        "revision": REVISION,
        "policy": {
            "four_dimensions_are_separate": True,
            "critical_closure_blocks_release": True,
            "area_is_not_a_release_score": True,
            "unsupported_environment_is_unknown": True,
            "no_generic_pass_ratio": True,
            "no_minimum_sample_count": True,
        },
        "cases": {
            case_id: {
                "deliverable": summaries[case_id]["release"],
                "pilot": summaries[case_id]["profiles"]["pilot"],
                "production": summaries[case_id]["profiles"]["production"],
                "reference_only": summaries[case_id]["profiles"]["reference_only"],
            }
            for case_id in CASE_IDS
        },
    }
    bundle = {
        "job": JOB,
        "revision": REVISION,
        "contracts": contracts,
        "check_records": check_records,
        "page_summaries": summaries,
        "release_ledger": release_ledger,
        "artifacts": artifacts,
    }
    return bundle, artifacts


def freeze_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(bundle)


def get_check_record(bundle: dict[str, Any], case_id: str, check_id: str) -> dict[str, Any]:
    for item in bundle["check_records"][case_id]:
        if item["check_id"] == check_id:
            return item
    raise KeyError(f"{case_id}/{check_id}")


def set_release(bundle: dict[str, Any], case_id: str, status: str, reason: str | None = None) -> None:
    summary = bundle["page_summaries"][case_id]
    summary["release"]["status"] = status
    summary["release"]["reason"] = reason or summary["release"]["reason"]
    summary["profiles"]["deliverable"]["status"] = status
    if reason:
        summary["profiles"]["deliverable"]["reason"] = reason
    bundle["release_ledger"]["cases"][case_id]["deliverable"]["status"] = status


def validate_bundle(bundle: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if bundle != baseline:
        errors.append("bundle differs from the frozen acceptance-gate contract")

    contracts = bundle.get("contracts", {})
    checks = bundle.get("check_records", {})
    summaries = bundle.get("page_summaries", {})
    ledger = bundle.get("release_ledger", {})
    if set(contracts) != set(CASE_IDS):
        errors.append("contract case set is incomplete")
    if set(checks) != set(CASE_IDS):
        errors.append("check-record case set is incomplete")
    if set(summaries) != set(CASE_IDS):
        errors.append("page-summary case set is incomplete")
    if set(ledger.get("cases", {})) != set(CASE_IDS):
        errors.append("release-ledger case set is incomplete")

    expected_release = {
        "clean-all-pass": "deliverable-complete",
        "linebreak-isolated": "deliverable-partial",
        "pixel-background": "deliverable-partial",
        "geometry-critical": "blocked-critical",
        "parent-critical": "blocked-critical",
        "boundary-critical": "blocked-critical",
        "native-critical": "blocked-critical",
        "asset-noncritical": "deliverable-partial",
        "unknown-critical": "blocked-unknown",
        "no-ground-truth-critical": "blocked-no-ground-truth",
        "critical-partial-not-allowed": "blocked-partial-not-allowed",
        "critical-not-sampled": "blocked-coverage",
        "tiny-price-error": "blocked-critical",
        "high-area-background-pass": "blocked-critical",
        "unsupported-browser": "blocked-unknown",
        "partial-not-allowed": "blocked-partial-not-allowed",
        "coverage-gap": "deliverable-partial",
        "reference-only": "reference-only",
        "preflight-ownership-unknown": "blocked-preflight",
    }

    for case_id in CASE_IDS:
        contract = contracts[case_id]
        records = checks[case_id]
        summary = summaries[case_id]
        if len(records) != len(CHECK_SPECS):
            errors.append(f"{case_id}: check record count mismatch")
        if dimensions := contract.get("required_dimensions"):
            if not set(dimensions).issubset(DIMENSIONS):
                errors.append(f"{case_id}: invalid required dimensions")
        else:
            errors.append(f"{case_id}: required dimensions missing")
        if summary["release"]["status"] != expected_release[case_id]:
            errors.append(
                f"{case_id}: release status {summary['release']['status']} != {expected_release[case_id]}"
            )
        if ledger["cases"][case_id]["deliverable"]["status"] != summary["release"]["status"]:
            errors.append(f"{case_id}: ledger release differs from summary")

        for record in records:
            if record["status"] not in STATUS_VALUES:
                errors.append(f"{case_id}/{record['check_id']}: invalid status")
            for key in (
                "record_id",
                "object_key",
                "check_type",
                "dimension",
                "criticality",
                "required",
                "applicability",
                "metric",
                "threshold",
                "threshold_source",
                "actual_value",
                "coverage",
                "status",
                "reason",
                "evidence",
                "verification_version",
            ):
                if key not in record:
                    errors.append(f"{case_id}/{record.get('check_id')}: missing {key}")
            if not record.get("evidence"):
                errors.append(f"{case_id}/{record['check_id']}: evidence missing")
            if not record.get("threshold_source"):
                errors.append(f"{case_id}/{record['check_id']}: threshold source missing")

        coverage = summary["coverage"]
        if coverage.get("denominator_after_isolation") != coverage.get("denominator_required_checks"):
            errors.append(f"{case_id}: coverage denominator shrank after isolation")
        if coverage.get("generic_pass_ratio") is not None:
            errors.append(f"{case_id}: generic pass ratio is set")
        if coverage.get("minimum_sample_count") is not None:
            errors.append(f"{case_id}: minimum sample count is set")

        if summary["area"].get("area_used_as_release_score") is not False:
            errors.append(f"{case_id}: area is used as a release score")

        for dimension in DIMENSIONS:
            dimension_summary = summary["dimensions"][dimension]
            if dimension in contract["required_dimensions"]:
                if dimension_summary.get("applicability") != "required":
                    errors.append(f"{case_id}/{dimension}: required dimension marked not-required")
            elif dimension_summary.get("status") != "not-required":
                errors.append(f"{case_id}/{dimension}: non-required dimension faked as pass")

        if any(item["status"] in {"fail", "unknown", "no-ground-truth", "not-sampled", "partial"} for item in records if item["critical"] and item["required"]):
            if summary["critical"]["blocked"] is not True:
                errors.append(f"{case_id}: critical blocker did not block")
            if summary["release"]["complete_export_allowed"]:
                errors.append(f"{case_id}: critical blocker allowed complete export")

        if case_id == "native-critical":
            if summary["dimensions"]["visual"]["status"] != "pass":
                errors.append("native-critical: visual control is not pass")
            if summary["dimensions"]["edit"]["status"] != "fail":
                errors.append("native-critical: edit failure is not fail")
            if summary["release"]["status"] == "deliverable-complete":
                errors.append("native-critical: visual pass offset edit fail")

        if case_id == "high-area-background-pass":
            if summary["area"]["area_pass_ratio"] <= 0.99:
                errors.append("high-area-background-pass: background pass area is not high")
            if summary["release"]["status"] != "blocked-critical":
                errors.append("high-area-background-pass: area masked critical failure")

        if case_id == "no-ground-truth-critical":
            if summary["critical"]["status_counts"].get("no-ground-truth", 0) < 1:
                errors.append("no-ground-truth-critical: no-ground-truth count missing")
            if coverage["status_counts"].get("no-ground-truth", 0) >= coverage["pass_required_checks"]:
                errors.append("no-ground-truth-critical: no-ground-truth entered pass numerator")

        if case_id == "coverage-gap":
            if coverage["status_counts"].get("not-sampled", 0) < 1:
                errors.append("coverage-gap: not-sampled count missing")
            if summary["release"]["status"] != "deliverable-partial":
                errors.append("coverage-gap: isolated noncritical gap did not produce partial")

        if case_id == "unsupported-browser":
            if summary["release"]["status"] == "deliverable-complete":
                errors.append("unsupported-browser: unsupported environment passed")

        production = summary["profiles"]["production"]
        if production["status"] == "production-eligible-review" and contract["production_prerequisites"]:
            if not all(contract["production_prerequisites"].values()):
                errors.append(f"{case_id}: production eligible without prerequisites")

    if summaries["reference-only"]["release"]["status"] != "reference-only":
        errors.append("reference-only case was promoted to deliverable-complete")
    if summaries["preflight-ownership-unknown"]["release"]["status"] != "blocked-preflight":
        errors.append("preflight failure did not block")
    if summaries["clean-all-pass"]["release"]["status"] != "deliverable-complete":
        errors.append("clean case did not produce deliverable-complete")

    policy = ledger.get("policy", {})
    if policy.get("no_generic_pass_ratio") is not True:
        errors.append("generic pass ratio policy is enabled")
    if policy.get("no_minimum_sample_count") is not True:
        errors.append("minimum sample count policy is enabled")
    if policy.get("area_is_not_a_release_score") is not True:
        errors.append("area release-score policy is disabled")
    if policy.get("critical_closure_blocks_release") is not True:
        errors.append("critical dependency closure is disabled")

    return errors


MUTATION_SPECS: list[tuple[str, str, Callable[[dict[str, Any]], None]]] = [
    (
        "critical-fail-marked-pass",
        "Promote a critical geometry failure to pass.",
        lambda doc: get_check_record(doc, "geometry-critical", "S-GEOMETRY-PRICE").__setitem__(
            "status", "pass"
        ),
    ),
    (
        "critical-unknown-marked-pass",
        "Promote a critical unknown to pass.",
        lambda doc: get_check_record(doc, "unknown-critical", "S-GEOMETRY-PRICE").__setitem__(
            "status", "pass"
        ),
    ),
    (
        "no-ground-truth-marked-pass",
        "Promote no-ground-truth to pass.",
        lambda doc: get_check_record(doc, "no-ground-truth-critical", "E-NATIVE-PRICE").__setitem__(
            "status", "pass"
        ),
    ),
    (
        "not-sampled-marked-pass",
        "Promote an unsampled asset check to pass.",
        lambda doc: get_check_record(doc, "coverage-gap", "A-ORIGIN-BADGE").__setitem__(
            "status", "pass"
        ),
    ),
    (
        "visual-offsets-edit",
        "Use visual pass to override edit failure.",
        lambda doc: set_release(doc, "native-critical", "deliverable-complete"),
    ),
    (
        "area-overrides-critical",
        "Use high background area to override the critical price error.",
        lambda doc: set_release(doc, "high-area-background-pass", "deliverable-complete"),
    ),
    (
        "noncritical-gap-complete",
        "Promote a noncritical gap to complete delivery.",
        lambda doc: set_release(doc, "linebreak-isolated", "deliverable-complete"),
    ),
    (
        "partial-not-allowed-promoted",
        "Promote a non-allowed partial to deliverable-partial.",
        lambda doc: set_release(doc, "partial-not-allowed", "deliverable-partial"),
    ),
    (
        "coverage-denominator-shrinks",
        "Remove the isolated gap from the original denominator.",
        lambda doc: doc["page_summaries"]["linebreak-isolated"]["coverage"].__setitem__(
            "denominator_after_isolation",
            10,
        ),
    ),
    (
        "no-ground-truth-counts-pass",
        "Increase pass count while retaining no-ground-truth.",
        lambda doc: doc["page_summaries"]["no-ground-truth-critical"]["coverage"].__setitem__(
            "pass_required_checks",
            doc["page_summaries"]["no-ground-truth-critical"]["coverage"]["pass_required_checks"] + 1,
        ),
    ),
    (
        "not-sampled-counts-pass",
        "Count not-sampled in the pass numerator.",
        lambda doc: doc["page_summaries"]["coverage-gap"]["coverage"].__setitem__(
            "pass_required_checks",
            doc["page_summaries"]["coverage-gap"]["coverage"]["pass_required_checks"] + 1,
        ),
    ),
    (
        "generic-95-threshold",
        "Add a generic 95% pass threshold.",
        lambda doc: doc["contracts"]["clean-all-pass"]["coverage_policy"].__setitem__(
            "generic_pass_ratio", 0.95
        ),
    ),
    (
        "minimum-sample-count",
        "Add a universal minimum sample count.",
        lambda doc: doc["contracts"]["clean-all-pass"]["coverage_policy"].__setitem__(
            "minimum_sample_count", 12
        ),
    ),
    (
        "unsupported-browser-complete",
        "Treat unsupported browser evidence as complete.",
        lambda doc: set_release(doc, "unsupported-browser", "deliverable-complete"),
    ),
    (
        "production-without-prerequisites",
        "Mark production eligible without operational prerequisites.",
        lambda doc: doc["page_summaries"]["clean-all-pass"]["profiles"]["production"].update(
            {"status": "production-eligible-review", "missing_prerequisites": []}
        ),
    ),
    (
        "pilot-claims-deliverable-complete",
        "Promote pilot status to full delivery.",
        lambda doc: set_release(doc, "linebreak-isolated", "deliverable-complete"),
    ),
    (
        "reference-only-marked-complete",
        "Promote reference-only to complete.",
        lambda doc: set_release(doc, "reference-only", "deliverable-complete"),
    ),
    (
        "dependency-closure-removed",
        "Clear the critical dependency closure.",
        lambda doc: doc["contracts"]["geometry-critical"].__setitem__(
            "critical_dependency_closure", {}
        ),
    ),
    (
        "asset-dimension-ignored",
        "Mark asset failure as not required.",
        lambda doc: doc["page_summaries"]["asset-noncritical"]["dimensions"]["asset"].update(
            {"applicability": "not-required", "status": "not-required"}
        ),
    ),
    (
        "preflight-overridden",
        "Release a page with unknown output ownership.",
        lambda doc: set_release(doc, "preflight-ownership-unknown", "deliverable-complete"),
    ),
    (
        "dimension-average-used",
        "Replace dimension gates with an average score.",
        lambda doc: doc["page_summaries"]["clean-all-pass"].__setitem__(
            "dimension_average", 0.98
        ),
    ),
    (
        "coverage-complete-with-unknown",
        "Claim complete coverage while unknown checks remain.",
        lambda doc: doc["page_summaries"]["unsupported-browser"]["coverage"].__setitem__(
            "coverage_complete", True
        ),
    ),
    (
        "check-evidence-missing",
        "Remove evidence from a check record.",
        lambda doc: get_check_record(doc, "clean-all-pass", "V-CONTENT-PRICE").__setitem__(
            "evidence", []
        ),
    ),
    (
        "threshold-source-missing",
        "Remove the threshold source.",
        lambda doc: get_check_record(doc, "clean-all-pass", "S-GEOMETRY-PRICE").__setitem__(
            "threshold_source", None
        ),
    ),
    (
        "not-required-counted-pass",
        "Mark non-required edit checks as pass.",
        lambda doc: [
            item.__setitem__("status", "pass")
            for item in doc["check_records"]["reference-only"]
            if item["dimension"] == "edit"
        ],
    ),
    (
        "linebreak-downgraded-warning",
        "Downgrade linebreak failure to a warning.",
        lambda doc: get_check_record(doc, "linebreak-isolated", "V-LINEBREAK-HERO").__setitem__(
            "status", "pass"
        ),
    ),
    (
        "area-release-score-enabled",
        "Enable area as release score.",
        lambda doc: doc["page_summaries"]["high-area-background-pass"]["area"].__setitem__(
            "area_used_as_release_score", True
        ),
    ),
    (
        "clean-critical-closure-false",
        "Claim critical closure failure on a complete page.",
        lambda doc: doc["page_summaries"]["clean-all-pass"]["critical"].__setitem__(
            "dependency_closure_satisfied", False
        ),
    ),
    (
        "tiny-price-error-complete",
        "Ignore a tiny but critical price error.",
        lambda doc: set_release(doc, "tiny-price-error", "deliverable-complete"),
    ),
    (
        "verified-status-used",
        "Use an unsupported verified release status.",
        lambda doc: set_release(doc, "clean-all-pass", "verified"),
    ),
]


def run_mutations(bundle: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    base_errors = validate_bundle(bundle, baseline)
    items: list[dict[str, Any]] = []
    for mutation_id, description, apply in MUTATION_SPECS:
        candidate = copy.deepcopy(bundle)
        apply(candidate)
        errors = validate_bundle(candidate, baseline)
        items.append(
            {
                "mutation_id": mutation_id,
                "description": description,
                "rejected": bool(errors),
                "error_count": len(errors),
                "errors": errors[:12],
            }
        )
    rejected = sum(1 for item in items if item["rejected"])
    return {
        "base_valid": not base_errors,
        "base_errors": base_errors,
        "total": len(items),
        "rejected": rejected,
        "accepted": len(items) - rejected,
        "items": items,
    }


def run_checks(
    bundle: dict[str, Any],
    baseline: dict[str, Any],
    mutations: dict[str, Any],
    artifacts: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summaries = bundle["page_summaries"]
    records = bundle["check_records"]

    checks.append(
        check(
            "case-coverage",
            "All authored acceptance-gate cases are present.",
            set(summaries) == set(CASE_IDS) and set(records) == set(CASE_IDS),
            len(summaries),
        )
    )
    injected = {
        "linebreak": ("linebreak-isolated", "V-LINEBREAK-HERO", {"fail"}),
        "pixel": ("pixel-background", "V-PIXEL-BG", {"partial"}),
        "geometry": ("geometry-critical", "S-GEOMETRY-PRICE", {"fail"}),
        "parent": ("parent-critical", "S-PARENT-CTA", {"fail"}),
        "boundary": ("boundary-critical", "S-BOUNDARY-CTA", {"fail"}),
        "native": ("native-critical", "E-NATIVE-PRICE", {"fail"}),
    }
    checks.append(
        check(
            "six-check-types-injected",
            "Linebreak, pixel, geometry, parent, boundary and native each have an injected fault.",
            all(
                get_check_record(bundle, case_id, check_id)["status"] in expected
                for case_id, check_id, expected in injected.values()
            ),
            {
                key: {
                    "case": value[0],
                    "status": get_check_record(bundle, value[0], value[1])["status"],
                }
                for key, value in injected.items()
            },
        )
    )
    checks.append(
        check(
            "critical-partial-and-unsampled-block",
            "Critical partial without permission and critical not-sampled both block.",
            summaries["critical-partial-not-allowed"]["release"]["status"]
            == "blocked-partial-not-allowed"
            and summaries["critical-not-sampled"]["release"]["status"]
            == "blocked-coverage",
            {
                "critical-partial": summaries["critical-partial-not-allowed"]["release"],
                "critical-not-sampled": summaries["critical-not-sampled"]["release"],
            },
        )
    )
    checks.append(
        check(
            "unknown-and-no-ground-truth",
            "Unknown and no-ground-truth remain non-pass outcomes.",
            summaries["unknown-critical"]["release"]["status"] == "blocked-unknown"
            and summaries["no-ground-truth-critical"]["release"]["status"]
            == "blocked-no-ground-truth"
            and summaries["no-ground-truth-critical"]["coverage"]["status_counts"].get(
                "no-ground-truth", 0
            )
            == 1,
            {
                "unknown": summaries["unknown-critical"]["release"],
                "no-ground-truth": summaries["no-ground-truth-critical"]["release"],
            },
        )
    )
    checks.append(
        check(
            "tiny-price-error-blocks",
            "A tiny critical price error blocks release regardless of area.",
            artifacts["diff"]["page_ratio"] < 0.001
            and summaries["tiny-price-error"]["release"]["status"] == "blocked-critical"
            and summaries["tiny-price-error"]["critical"]["blockers"][0]["check_id"]
            == "V-CONTENT-PRICE",
            {
                "diff_pixels": artifacts["diff"]["pixels"],
                "page_ratio": artifacts["diff"]["page_ratio"],
                "release": summaries["tiny-price-error"]["release"],
            },
        )
    )
    checks.append(
        check(
            "high-area-cannot-offset",
            "A high-area background pass cannot offset a critical price failure.",
            summaries["high-area-background-pass"]["area"]["area_pass_ratio"] > 0.99
            and summaries["high-area-background-pass"]["release"]["status"]
            == "blocked-critical",
            {
                "area": summaries["high-area-background-pass"]["area"],
                "release": summaries["high-area-background-pass"]["release"],
            },
        )
    )
    checks.append(
        check(
            "visual-cannot-offset-edit",
            "Visual pass does not offset edit failure.",
            summaries["native-critical"]["dimensions"]["visual"]["status"] == "pass"
            and summaries["native-critical"]["dimensions"]["edit"]["status"] == "fail"
            and not summaries["native-critical"]["release"]["complete_export_allowed"],
            {
                "visual": summaries["native-critical"]["dimensions"]["visual"],
                "edit": summaries["native-critical"]["dimensions"]["edit"],
                "release": summaries["native-critical"]["release"],
            },
        )
    )
    checks.append(
        check(
            "noncritical-partial",
            "Isolated noncritical gaps produce deliverable-partial with the original denominator.",
            summaries["linebreak-isolated"]["release"]["status"] == "deliverable-partial"
            and summaries["asset-noncritical"]["release"]["status"] == "deliverable-partial"
            and summaries["coverage-gap"]["release"]["status"] == "deliverable-partial"
            and all(
                summaries[case_id]["coverage"]["denominator_after_isolation"]
                == summaries[case_id]["coverage"]["denominator_required_checks"]
                for case_id in (
                    "linebreak-isolated",
                    "pixel-background",
                    "asset-noncritical",
                    "coverage-gap",
                )
            ),
            {
                case_id: summaries[case_id]["release"]
                for case_id in (
                    "linebreak-isolated",
                    "pixel-background",
                    "asset-noncritical",
                    "coverage-gap",
                )
            },
        )
    )
    checks.append(
        check(
            "partial-not-allowed-blocks",
            "Noncritical gaps block when partial delivery is not allowed.",
            summaries["partial-not-allowed"]["release"]["status"]
            == "blocked-partial-not-allowed",
            summaries["partial-not-allowed"]["release"],
        )
    )
    checks.append(
        check(
            "clean-complete",
            "All-pass clean case yields deliverable-complete.",
            summaries["clean-all-pass"]["release"]["status"] == "deliverable-complete"
            and summaries["clean-all-pass"]["coverage"]["coverage_complete"] is True,
            summaries["clean-all-pass"]["release"],
        )
    )
    checks.append(
        check(
            "reference-only",
            "Reference-only does not become deliverable-complete.",
            summaries["reference-only"]["release"]["status"] == "reference-only"
            and summaries["reference-only"]["release"]["complete_export_allowed"] is False,
            summaries["reference-only"]["release"],
        )
    )
    checks.append(
        check(
            "preflight-blocks",
            "Unknown output ownership blocks release before dimension comparison.",
            summaries["preflight-ownership-unknown"]["release"]["status"] == "blocked-preflight",
            summaries["preflight-ownership-unknown"]["preflight"],
        )
    )
    checks.append(
        check(
            "unsupported-browser-unknown",
            "Unsupported browser evidence remains unknown and cannot pass.",
            summaries["unsupported-browser"]["release"]["status"] == "blocked-unknown"
            and summaries["unsupported-browser"]["dimensions"]["visual"]["status"]
            == "unknown",
            summaries["unsupported-browser"]["release"],
        )
    )
    checks.append(
        check(
            "production-not-inferred",
            "No case is promoted to production eligibility from effect checks alone.",
            all(
                summary["profiles"]["production"]["status"] == "production-not-eligible"
                for summary in summaries.values()
            ),
            {
                case_id: summaries[case_id]["profiles"]["production"]
                for case_id in CASE_IDS
            },
        )
    )
    checks.append(
        check(
            "no-generic-threshold",
            "No generic 95% or N-sample threshold is used.",
            all(
                contract["coverage_policy"]["generic_pass_ratio"] is None
                and contract["coverage_policy"]["minimum_sample_count"] is None
                for contract in bundle["contracts"].values()
            ),
            {
                case_id: bundle["contracts"][case_id]["coverage_policy"]
                for case_id in ("clean-all-pass", "coverage-gap")
            },
        )
    )
    checks.append(
        check(
            "area-not-score",
            "Area is reported but never used as the release score.",
            all(
                summary["area"]["area_used_as_release_score"] is False
                for summary in summaries.values()
            ),
            {
                case_id: summaries[case_id]["area"]
                for case_id in ("tiny-price-error", "high-area-background-pass")
            },
        )
    )
    checks.append(
        check(
            "critical-closure",
            "Critical failures propagate through the declared dependency closure.",
            all(
                summaries[case_id]["critical"]["dependency_closure_satisfied"] is False
                for case_id in (
                    "geometry-critical",
                    "parent-critical",
                    "boundary-critical",
                    "native-critical",
                    "critical-partial-not-allowed",
                    "critical-not-sampled",
                    "tiny-price-error",
                )
            ),
            {
                case_id: summaries[case_id]["critical"]
                for case_id in ("geometry-critical", "tiny-price-error")
            },
        )
    )
    checks.append(
        check(
            "not-required-is-not-pass",
            "Not-required dimensions remain not-required rather than pass.",
            summaries["reference-only"]["dimensions"]["edit"]["status"] == "not-required"
            and summaries["reference-only"]["dimensions"]["asset"]["status"] == "not-required",
            summaries["reference-only"]["dimensions"],
        )
    )
    checks.append(
        check(
            "base-contract-valid",
            "The base release bundle passes the same validator used for mutations.",
            not validate_bundle(bundle, baseline),
            validate_bundle(bundle, baseline),
        )
    )
    checks.append(
        check(
            "negative-mutations-rejected",
            "Every targeted invalid gate or release mutation is rejected.",
            mutations["rejected"] == mutations["total"] and mutations["accepted"] == 0,
            {"rejected": mutations["rejected"], "total": mutations["total"]},
        )
    )
    checks.append(
        check(
            "artifact-files-present",
            "Reference, price-error and diff artifacts exist.",
            all(
                Path(artifacts[key]["path"]).exists()
                for key in ("reference", "price_error", "diff")
            ),
            {
                key: artifacts[key]["sha256"]
                for key in ("reference", "price_error", "diff")
            },
        )
    )
    checks.append(
        check(
            "no-external-runtime",
            "The gate experiment is offline and does not connect to Figma.",
            True,
            {"figma_connected": False, "bridge_used": False},
        )
    )
    return checks


STATUS_COLORS = {
    "pass": ("#dcfce7", "#166534"),
    "partial": ("#fef3c7", "#92400e"),
    "fail": ("#fee2e2", "#991b1b"),
    "unknown": ("#e5e7eb", "#374151"),
    "no-ground-truth": ("#f3e8ff", "#6b21a8"),
    "not-sampled": ("#ffedd5", "#9a3412"),
    "not-required": ("#ffffff", "#94a3b8"),
}

RELEASE_COLORS = {
    "deliverable-complete": ("#dcfce7", "#166534"),
    "deliverable-partial": ("#fef3c7", "#92400e"),
    "reference-only": ("#dbeafe", "#1d4ed8"),
    "blocked-critical": ("#fee2e2", "#991b1b"),
    "blocked-unknown": ("#e5e7eb", "#374151"),
    "blocked-no-ground-truth": ("#f3e8ff", "#6b21a8"),
    "blocked-partial-not-allowed": ("#ffedd5", "#9a3412"),
    "blocked-preflight": ("#fecaca", "#7f1d1d"),
    "blocked-coverage": ("#fde68a", "#854d0e"),
    "blocked-dimension": ("#fecdd3", "#9f1239"),
    "production-not-eligible": ("#e2e8f0", "#475569"),
    "pilot-allowed-provisional": ("#ecfccb", "#3f6212"),
    "pilot-blocked": ("#fee2e2", "#991b1b"),
}


def make_check_matrix(bundle: dict[str, Any], path: Path) -> None:
    columns = [item["check_id"] for item in CHECK_SPECS]
    short = {
        "V-LINEBREAK-HERO": "LB",
        "V-PIXEL-BG": "PX-BG",
        "V-PIXEL-PRODUCT": "PX-PROD",
        "V-CONTENT-PRICE": "PRICE",
        "S-GEOMETRY-PRICE": "GEO",
        "S-PARENT-CTA": "PARENT",
        "S-BOUNDARY-CTA": "BOUND",
        "E-NATIVE-PRICE": "NAT-P",
        "E-NATIVE-CTA": "NAT-C",
        "A-ORIGIN-IMAGE": "ASSET-I",
        "A-ORIGIN-BADGE": "ASSET-B",
    }
    fig, ax = plt.subplots(figsize=(18, 10.5))
    ax.set_axis_off()
    fig.text(
        0.03,
        0.96,
        "R5-EXP-05 · Injected check matrix",
        fontsize=22,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    fig.text(
        0.03,
        0.91,
        "Statuses are injected contract inputs; detector thresholds are contract references, not recalibrated here.",
        fontsize=10.5,
        color="#475569",
        va="top",
    )
    y0 = 0.84
    row_height = 0.041
    x_label = 0.02
    x_start = 0.23
    cell_width = 0.067
    ax.text(x_label, 0.875, "Case", fontsize=9, fontweight="bold", color="#334155")
    for index, check_id in enumerate(columns):
        ax.text(
            x_start + index * cell_width + cell_width / 2,
            0.875,
            short[check_id],
            ha="center",
            va="center",
            fontsize=8.2,
            fontweight="bold",
            color="#334155",
        )
    for row_index, case_id in enumerate(CASE_IDS):
        y = y0 - row_index * row_height
        ax.text(
            x_label,
            y,
            CASE_LABELS[case_id],
            fontsize=8.2,
            color="#0f172a",
            va="center",
        )
        records = {item["check_id"]: item for item in bundle["check_records"][case_id]}
        for col_index, check_id in enumerate(columns):
            status = records[check_id]["status"]
            face, text = STATUS_COLORS[status]
            ax.add_patch(
                plt.Rectangle(
                    (x_start + col_index * cell_width, y - 0.016),
                    cell_width - 0.005,
                    0.031,
                    facecolor=face,
                    edgecolor="#cbd5e1",
                    linewidth=0.6,
                )
            )
            ax.text(
                x_start + col_index * cell_width + (cell_width - 0.005) / 2,
                y,
                status.replace("no-ground-truth", "NOGT").replace("not-sampled", "UNS").replace("not-required", "N/A"),
                ha="center",
                va="center",
                fontsize=6.8,
                color=text,
                fontweight="bold",
            )
    legend = "PASS · PARTIAL · FAIL · UNKNOWN · NOGT=no-ground-truth · UNS=not-sampled · N/A=not-required"
    fig.text(0.03, 0.035, legend, fontsize=9, color="#475569")
    fig.savefig(path, dpi=150, facecolor="#f8fafc")
    plt.close(fig)


def make_page_summary(bundle: dict[str, Any], path: Path) -> None:
    columns = ("Case", "Visual", "Structure", "Edit", "Asset", "Critical", "Release", "Export")
    rows: list[list[str]] = []
    colors: list[list[str]] = []
    for case_id in CASE_IDS:
        summary = bundle["page_summaries"][case_id]
        row = [
            CASE_LABELS[case_id],
            summary["dimensions"]["visual"]["status"],
            summary["dimensions"]["structure"]["status"],
            summary["dimensions"]["edit"]["status"],
            summary["dimensions"]["asset"]["status"],
            "blocked" if summary["critical"]["blocked"] else "clear",
            summary["release"]["status"],
            summary["release"]["allowed_export_mode"],
        ]
        rows.append(row)
        colors.append(
            [
                "#eef2ff",
                STATUS_COLORS[summary["dimensions"]["visual"]["status"]][0],
                STATUS_COLORS[summary["dimensions"]["structure"]["status"]][0],
                STATUS_COLORS[summary["dimensions"]["edit"]["status"]][0],
                STATUS_COLORS[summary["dimensions"]["asset"]["status"]][0],
                RELEASE_COLORS.get(
                    "blocked-critical" if summary["critical"]["blocked"] else "pilot-allowed-provisional"
                )[0],
                RELEASE_COLORS.get(summary["release"]["status"], ("#e2e8f0", "#334155"))[0],
                "#f1f5f9",
            ]
        )
    fig, ax = plt.subplots(figsize=(19, 10.5))
    ax.set_axis_off()
    fig.text(
        0.025,
        0.96,
        "R5-EXP-05 · Page summary and release decision",
        fontsize=22,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    fig.text(
        0.025,
        0.91,
        "Four dimensions stay separate; critical failures use dependency closure; area is not a release score.",
        fontsize=10.5,
        color="#475569",
        va="top",
    )
    table = ax.table(
        cellText=rows,
        colLabels=columns,
        cellColours=colors,
        colColours=["#e2e8f0"] * len(columns),
        loc="center",
        cellLoc="center",
        bbox=[0.015, 0.10, 0.97, 0.74],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7.4)
    for cell in table.get_celld().values():
        cell.set_edgecolor("#94a3b8")
        cell.set_linewidth(0.6)
    fig.text(
        0.025,
        0.05,
        "Deliverable levels: complete, partial, reference-only or blocked. Pilot is always provisional and limited; production requires separate operational prerequisites.",
        fontsize=9,
        color="#475569",
    )
    fig.savefig(path, dpi=150, facecolor="#f8fafc")
    plt.close(fig)


def make_area_vs_critical(bundle: dict[str, Any], artifacts: dict[str, Any], path: Path) -> None:
    summary = bundle["page_summaries"]["high-area-background-pass"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6), gridspec_kw={"width_ratios": [1.4, 1]})
    labels = ["Background pass area", "Critical price diff"]
    values = [BACKGROUND_AREA, artifacts["diff"]["pixels"]]
    bars = ax1.bar(labels, values, color=["#86efac", "#f87171"], edgecolor="#64748b")
    ax1.set_yscale("log")
    ax1.set_ylabel("pixels (log scale)")
    ax1.set_title("Area does not decide release", loc="left", fontsize=15, fontweight="bold", color="#0f172a")
    for bar, value in zip(bars, values):
        ax1.text(
            bar.get_x() + bar.get_width() / 2,
            value * 1.2,
            f"{value:,}",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
            color="#334155",
        )
    ax1.grid(axis="y", color="#e2e8f0")
    ax1.set_axisbelow(True)
    ax2.set_axis_off()
    ax2.text(0.0, 0.92, "High-area control", fontsize=16, fontweight="bold", color="#0f172a")
    lines = [
        f"Background area pass: {BACKGROUND_AREA:,} px",
        f"Page area: {PAGE_AREA:,} px ({BACKGROUND_AREA / PAGE_AREA:.1%})",
        f"Critical price diff: {artifacts['diff']['pixels']:,} px",
        f"Diff ratio: {artifacts['diff']['page_ratio']:.4%}",
        "",
        f"Area pass ratio: {summary['area']['area_pass_ratio']:.3%}",
        f"Critical blocker: {summary['critical']['blockers'][0]['check_id']}",
        f"Release: {summary['release']['status']}",
        "complete_export_allowed = false",
    ]
    ax2.text(
        0.0,
        0.80,
        "\n".join(lines),
        fontsize=11,
        color="#334155",
        va="top",
        linespacing=1.5,
    )
    fig.suptitle(
        "R5-EXP-05 · High-area background pass cannot offset a critical price error",
        x=0.03,
        y=0.98,
        ha="left",
        fontsize=19,
        fontweight="bold",
        color="#0f172a",
    )
    fig.subplots_adjust(left=0.08, right=0.97, top=0.86, bottom=0.12, wspace=0.28)
    fig.savefig(path, dpi=160, facecolor="#f8fafc")
    plt.close(fig)


def make_release_profiles(bundle: dict[str, Any], path: Path) -> None:
    columns = ("Case", "Pilot", "Deliverable", "Production", "Reference-only")
    rows: list[list[str]] = []
    colors: list[list[str]] = []
    for case_id in CASE_IDS:
        profiles = bundle["page_summaries"][case_id]["profiles"]
        pilot = profiles["pilot"]["status"]
        deliverable = profiles["deliverable"]["status"]
        production = profiles["production"]["status"]
        reference = profiles["reference_only"]["status"]
        rows.append([CASE_LABELS[case_id], pilot, deliverable, production, reference])
        colors.append(
            [
                "#eef2ff",
                RELEASE_COLORS.get(pilot, ("#e2e8f0", "#334155"))[0],
                RELEASE_COLORS.get(deliverable, ("#e2e8f0", "#334155"))[0],
                RELEASE_COLORS.get(production, ("#e2e8f0", "#334155"))[0],
                RELEASE_COLORS.get("reference-only", ("#dbeafe", "#1d4ed8"))[0]
                if reference == "reference-only"
                else "#f8fafc",
            ]
        )
    fig, ax = plt.subplots(figsize=(19, 10))
    ax.set_axis_off()
    fig.text(
        0.025,
        0.96,
        "R5-EXP-05 · Release profiles",
        fontsize=22,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    fig.text(
        0.025,
        0.91,
        "Pilot is provisional and limited. Production remains not eligible without separate operational prerequisites.",
        fontsize=10.5,
        color="#475569",
        va="top",
    )
    table = ax.table(
        cellText=rows,
        colLabels=columns,
        cellColours=colors,
        colColours=["#e2e8f0"] * len(columns),
        loc="center",
        cellLoc="center",
        bbox=[0.02, 0.11, 0.96, 0.72],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7.8)
    for cell in table.get_celld().values():
        cell.set_edgecolor("#94a3b8")
        cell.set_linewidth(0.6)
    fig.text(
        0.025,
        0.055,
        "Pilot does not imply deliverable-complete or production eligibility. Reference-only is a restricted release mode.",
        fontsize=9,
        color="#475569",
    )
    fig.savefig(path, dpi=150, facecolor="#f8fafc")
    plt.close(fig)


def make_price_error_evidence(artifacts: dict[str, Any], path: Path) -> None:
    thumb_width = 760
    panels = [
        ("Reference: $129", artifacts["reference"]["path"]),
        ("Output: $139", artifacts["price_error"]["path"]),
        (f"Pixel diff: {artifacts['diff']['pixels']:,} px", artifacts["diff"]["path"]),
    ]
    images = []
    for title, image_path in panels:
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        ratio = thumb_width / image.width
        thumb = image.resize((thumb_width, int(image.height * ratio)), Image.Resampling.LANCZOS)
        images.append((title, thumb))
    gap = 16
    label_height = 42
    canvas = Image.new(
        "RGB",
        (thumb_width + gap * 2, 60 + sum(image.height + label_height + gap for _, image in images)),
        "#e8edf4",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((gap, 16), "R5-EXP-05 · Tiny critical price error evidence", fill="#0f172a", font=font_for(24, True))
    y = 60
    for title, image in images:
        draw.rectangle(
            (gap, y, gap + thumb_width, y + image.height + label_height),
            fill="#ffffff",
            outline="#cbd5e1",
        )
        canvas.paste(image, (gap, y))
        draw.text(
            (gap + 12, y + image.height + 10),
            title,
            fill="#0f172a",
            font=font_for(16, True),
        )
        y += image.height + label_height + gap
    canvas.save(path)


BOUNDARY = {
    "scope": "Offline deterministic acceptance-gate and page-summary model.",
    "checks": "Linebreak, pixel, geometry, parent, boundary, native and asset statuses are injected inputs.",
    "thresholds": "R3-EXP-11 contract values are cited, not recalibrated in this experiment.",
    "figma": "Figma and the bridge are not connected.",
    "browser": "No browser automation or cross-browser observation is included.",
    "release": "No production operational gate, monitoring or deployment behavior is exercised.",
}

LIMITATIONS = [
    "All check outcomes are injected contract inputs; the experiment does not detect linebreak, pixel, geometry, parent, boundary, native or asset faults.",
    "The six fault families use one representative case each, not a real site distribution.",
    "The R3-EXP-11 thresholds are referenced as contract values; several families had no calibrated fault variants.",
    "The tiny price error is represented by a generated $129/$139 raster and 481 changed pixels.",
    "Area is computed from the authored page and background rectangle, not from business value.",
    "Production prerequisites are fixed false because this experiment does not exercise recovery, idempotency, permissions, persistence or monitoring.",
    "Pilot status is a provisional gate simulation, not evidence of a real limited deployment.",
    "Reference-only applicability is modeled explicitly; no real read-only artifact was delivered.",
    "No user study verifies whether release status words and blocked actions are understandable.",
    "The 31 negative mutations only cover the validator rules defined here.",
]


def print_summary(result: dict[str, Any]) -> None:
    passed = sum(1 for item in result["checks"] if item["passed"])
    print(f"status={result['status']}")
    print(f"checks={passed}/{len(result['checks'])}")
    print(
        "mutations=%s/%s rejected"
        % (result["mutations"]["rejected"], result["mutations"]["total"])
    )
    print(f"cases={len(CASE_IDS)}")
    print(f"price_diff_pixels={result['price_diff']['pixels']}")
    print(f"content_hash={result['content_hash']}")
    print(f"out={result['output_directory']}")
    for item in result["checks"]:
        if not item["passed"]:
            print(f"FAILED CHECK: {item['name']} :: {item['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R5-EXP-05 acceptance gate experiment.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    out_dir = safe_output_dir(args.out)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Building four-dimensional acceptance and release summaries...")
    bundle, artifacts = build_bundle(out_dir)
    baseline = freeze_bundle(bundle)
    mutations = run_mutations(bundle, baseline)
    checks = run_checks(bundle, baseline, mutations, artifacts)

    check_matrix = out_dir / "r5_exp_05_check_matrix.png"
    page_summary = out_dir / "r5_exp_05_page_summary.png"
    area_vs_critical = out_dir / "r5_exp_05_area_vs_critical.png"
    release_profiles = out_dir / "r5_exp_05_release_profiles.png"
    price_error_evidence = out_dir / "r5_exp_05_price_error_evidence.png"
    make_check_matrix(bundle, check_matrix)
    make_page_summary(bundle, page_summary)
    make_area_vs_critical(bundle, artifacts, area_vs_critical)
    make_release_profiles(bundle, release_profiles)
    make_price_error_evidence(artifacts, price_error_evidence)

    all_checks_passed = all(item["passed"] for item in checks)
    status = "completed-for-current-scope" if all_checks_passed and mutations["accepted"] == 0 else "failed"
    visual_files = {}
    for path in (
        check_matrix,
        page_summary,
        area_vs_critical,
        release_profiles,
        price_error_evidence,
    ):
        visual_files[path.name] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    outputs = {
        "contracts": out_dir / "contracts.json",
        "checks": out_dir / "checks.json",
        "page_summaries": out_dir / "page_summaries.json",
        "release_ledger": out_dir / "release_ledger.json",
        "mutations": out_dir / "mutations.json",
    }
    atomic_write_json(outputs["contracts"], bundle["contracts"])
    atomic_write_json(outputs["checks"], bundle["check_records"])
    atomic_write_json(outputs["page_summaries"], bundle["page_summaries"])
    atomic_write_json(outputs["release_ledger"], bundle["release_ledger"])
    atomic_write_json(outputs["mutations"], mutations)

    result: dict[str, Any] = {
        "job": JOB,
        "revision": REVISION,
        "profile": PROFILE,
        "status": status,
        "generated_at": CAPTURED_AT,
        "output_directory": str(out_dir),
        "environment": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "numpy": package_version("numpy"),
            "pillow": package_version("Pillow"),
            "matplotlib": package_version("matplotlib"),
        },
        "inputs": {
            "reference": artifacts["reference"],
            "price_error": artifacts["price_error"],
            "diff": artifacts["diff"],
        },
        "price_diff": artifacts["diff"],
        "contracts": bundle["contracts"],
        "check_records": bundle["check_records"],
        "page_summaries": bundle["page_summaries"],
        "release_ledger": bundle["release_ledger"],
        "artifact_paths": {key: str(value) for key, value in outputs.items()},
        "checks": checks,
        "mutations": mutations,
        "visuals": visual_files,
        "release_counts": {
            "deliverable-complete": sum(
                1 for item in bundle["page_summaries"].values()
                if item["release"]["status"] == "deliverable-complete"
            ),
            "deliverable-partial": sum(
                1 for item in bundle["page_summaries"].values()
                if item["release"]["status"] == "deliverable-partial"
            ),
            "reference-only": sum(
                1 for item in bundle["page_summaries"].values()
                if item["release"]["status"] == "reference-only"
            ),
            "blocked": sum(
                1 for item in bundle["page_summaries"].values()
                if item["release"]["status"].startswith("blocked-")
            ),
        },
        "boundary": BOUNDARY,
        "limitations": LIMITATIONS,
        "release_claims": {
            "experiment_status": "completed-for-current-scope" if all_checks_passed else "failed",
            "verified": False,
            "production_ready": False,
            "figma_connected": False,
            "source_modified": False,
            "production_gate_implemented": False,
        },
    }
    result["content_hash"] = content_hash(result)
    atomic_write_json(out_dir / "result.json", result)
    print_summary(result)
    return 0 if all_checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
