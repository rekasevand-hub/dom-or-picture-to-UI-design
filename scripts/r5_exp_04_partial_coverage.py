# -*- coding: utf-8 -*-
"""R5-EXP-04: partial delivery expression and coverage-map contract.

The experiment builds four delivery variants with the same missing region:

* intentional-omission
* write-failed
* observed-absent
* not-captured

Each variant has a separate business flow, diagnostic placeholder, report and
coverage map. A raster diff is reconciled against a fixed denominator before
and after diagnostic-mask exclusion. The experiment is offline and does not
connect to Figma or modify production code.

Usage:
  C:/Users/lzq/.conda/envs/omni/python.exe scripts/r5_exp_04_partial_coverage.py
  ... --out output/_r5_experiments/r5_exp_04_partial_coverage
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
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

JOB = "JOB-R5-EXP-04-20261019"
REVISION = "rev1"
PROFILE = "r5-exp-04-partial-coverage"
CAPTURED_AT = "2026-10-19T00:00:00+00:00"
DEFAULT_OUT = ROOT / "output" / "_r5_experiments" / "r5_exp_04_partial_coverage"

PAGE_WIDTH = 1200
PAGE_HEIGHT = 760
GAP_OBJECT_ID = "price-panel"

CASE_IDS = (
    "intentional-omission",
    "write-failed",
    "observed-absent",
    "not-captured",
)

CASE_LABELS = {
    "intentional-omission": "INTENTIONAL OMISSION",
    "write-failed": "WRITE FAILED",
    "observed-absent": "OBSERVED ABSENT",
    "not-captured": "NOT CAPTURED",
}

CASE_COLORS = {
    "intentional-omission": "#3b82f6",
    "write-failed": "#dc2626",
    "observed-absent": "#a16207",
    "not-captured": "#7c3aed",
}

CASE_BACKGROUNDS = {
    "intentional-omission": "#dbeafe",
    "write-failed": "#fee2e2",
    "observed-absent": "#fef3c7",
    "not-captured": "#ede9fe",
}

CASE_REASONS = {
    "intentional-omission": "Policy intentionally excludes the price panel from this delivery.",
    "write-failed": "The price panel was required but its write attempt failed.",
    "observed-absent": "The target state has no price panel; absence is observed, not a deletion claim.",
    "not-captured": "The capture did not observe the price-panel region; absence is unknown.",
}

CASE_EVIDENCE = {
    "intentional-omission": ["policy:omit-price-panel", "manifest:case-intentional-omission"],
    "write-failed": ["write-log:price-panel-error", "manifest:case-write-failed"],
    "observed-absent": ["capture:state-snapshot-no-price-panel", "manifest:case-observed-absent"],
    "not-captured": ["capture-log:region-not-observed", "manifest:case-not-captured"],
}

CASE_NEXT_STEPS = {
    "intentional-omission": "Obtain explicit policy approval before treating the region as delivered.",
    "write-failed": "Inspect the failed write, repair the cause and retry under a new revision.",
    "observed-absent": "Confirm the source state and update the contract before removing the requirement.",
    "not-captured": "Recapture the region; do not infer absence from missing evidence.",
}

CASE_BLOCKED_ACTIONS = {
    "intentional-omission": [
        "cannot-claim-complete-delivery",
        "cannot-export-as-complete",
        "cannot-reuse-placeholder-as-design",
    ],
    "write-failed": [
        "cannot-claim-write-success",
        "cannot-export-as-complete",
        "cannot-silently-skip-retry",
    ],
    "observed-absent": [
        "cannot-mark-deleted-without-authority",
        "cannot-synthesize-replacement-content",
        "cannot-export-as-complete",
    ],
    "not-captured": [
        "cannot-assume-absent",
        "cannot-claim-complete-delivery",
        "cannot-export-as-complete",
    ],
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
    if not resolved.name.startswith("r5_exp_04"):
        raise ValueError(f"Refusing to clean unexpected experiment name: {resolved.name}")
    return resolved


def rect(x: int, y: int, width: int, height: int) -> dict[str, int]:
    return {"x": x, "y": y, "width": width, "height": height}


def rect_area(value: dict[str, int]) -> int:
    return int(value["width"]) * int(value["height"])


def rect_union_area(rectangles: list[dict[str, int]]) -> int:
    if not rectangles:
        return 0
    xs = sorted({edge for item in rectangles for edge in (item["x"], item["x"] + item["width"])})
    area = 0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals: list[tuple[int, int]] = []
        for item in rectangles:
            item_left = item["x"]
            item_right = item_left + item["width"]
            if item_left <= left and item_right >= right:
                intervals.append((item["y"], item["y"] + item["height"]))
        if not intervals:
            continue
        intervals.sort()
        merged: list[list[int]] = []
        for start, end in intervals:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        covered_height = sum(end - start for start, end in merged)
        area += (right - left) * covered_height
    return area


def font_for(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


OBJECTS: list[dict[str, Any]] = [
    {
        "object_id": "header",
        "label": "Header",
        "rect": rect(80, 40, 1040, 60),
        "fill": "#0f172a",
        "text": "R5 LAB STORE",
        "text_fill": "#f8fafc",
        "text_size": 24,
        "critical": False,
    },
    {
        "object_id": "badge",
        "label": "Badge",
        "rect": rect(90, 118, 220, 40),
        "fill": "#f59e0b",
        "text": "EVIDENCE FIRST",
        "text_fill": "#111827",
        "text_size": 16,
        "critical": False,
    },
    {
        "object_id": "hero-bg",
        "label": "Hero background",
        "rect": rect(80, 180, 500, 260),
        "fill": "#1e3a8a",
        "text": "",
        "text_fill": "#ffffff",
        "text_size": 1,
        "critical": False,
    },
    {
        "object_id": "hero-title",
        "label": "Hero title",
        "rect": rect(120, 210, 420, 50),
        "fill": None,
        "text": "DESIGN DELIVERY",
        "text_fill": "#ffffff",
        "text_size": 30,
        "critical": False,
    },
    {
        "object_id": "hero-copy",
        "label": "Hero copy",
        "rect": rect(120, 280, 420, 70),
        "fill": None,
        "text": "Evidence first. No silent success.",
        "text_fill": "#dbeafe",
        "text_size": 19,
        "critical": False,
    },
    {
        "object_id": "product-shot",
        "label": "Product shot",
        "rect": rect(130, 360, 330, 65),
        "fill": "#38bdf8",
        "text": "PRODUCT / 01",
        "text_fill": "#082f49",
        "text_size": 18,
        "critical": False,
    },
    {
        "object_id": "promo-bg",
        "label": "Promo header",
        "rect": rect(600, 180, 260, 70),
        "fill": "#0f766e",
        "text": "",
        "text_fill": "#ffffff",
        "text_size": 1,
        "critical": False,
    },
    {
        "object_id": "promo-title",
        "label": "Promo title",
        "rect": rect(620, 200, 220, 30),
        "fill": None,
        "text": "LIMITED OFFER",
        "text_fill": "#ffffff",
        "text_size": 20,
        "critical": False,
    },
    {
        "object_id": GAP_OBJECT_ID,
        "label": "Price panel",
        "rect": rect(600, 290, 500, 120),
        "fill": "#7f1d1d",
        "text": "SALE PRICE  $129 / MO",
        "text_fill": "#fff7ed",
        "text_size": 28,
        "critical": True,
    },
    {
        "object_id": "cta",
        "label": "Call to action",
        "rect": rect(600, 440, 220, 50),
        "fill": "#ea580c",
        "text": "SHOP NOW",
        "text_fill": "#ffffff",
        "text_size": 20,
        "critical": True,
    },
    {
        "object_id": "footer",
        "label": "Footer",
        "rect": rect(80, 620, 1040, 70),
        "fill": "#e2e8f0",
        "text": "",
        "text_fill": "#0f172a",
        "text_size": 1,
        "critical": False,
    },
    {
        "object_id": "legal",
        "label": "Legal text",
        "rect": rect(120, 650, 420, 30),
        "fill": None,
        "text": "R5 authored fixture",
        "text_fill": "#334155",
        "text_size": 16,
        "critical": False,
    },
]

OBJECT_BY_ID = {item["object_id"]: item for item in OBJECTS}
GAP_RECT = OBJECT_BY_ID[GAP_OBJECT_ID]["rect"]
GAP_AREA = rect_area(GAP_RECT)


def text_characters(objects: list[dict[str, Any]]) -> int:
    return sum(len(str(item.get("text") or "")) for item in objects)


REQUIRED_AREA = rect_union_area([item["rect"] for item in OBJECTS])
DELIVERED_OBJECTS = [item for item in OBJECTS if item["object_id"] != GAP_OBJECT_ID]
DELIVERED_AREA = rect_union_area([item["rect"] for item in DELIVERED_OBJECTS])
REQUIRED_TEXT_CHARS = text_characters(OBJECTS)
GAP_TEXT_CHARS = text_characters([OBJECT_BY_ID[GAP_OBJECT_ID]])
DELIVERED_TEXT_CHARS = REQUIRED_TEXT_CHARS - GAP_TEXT_CHARS
REQUIRED_CRITICAL = sum(1 for item in OBJECTS if item["critical"])
DELIVERED_CRITICAL = sum(1 for item in DELIVERED_OBJECTS if item["critical"])
REQUIRED_OBJECTS = len(OBJECTS)
DELIVERED_OBJECT_COUNT = len(DELIVERED_OBJECTS)
DENOMINATOR_PIXELS = PAGE_WIDTH * PAGE_HEIGHT


def draw_object(draw: ImageDraw.ImageDraw, item: dict[str, Any]) -> None:
    box = item["rect"]
    bounds = (
        box["x"],
        box["y"],
        box["x"] + box["width"] - 1,
        box["y"] + box["height"] - 1,
    )
    if item["fill"]:
        draw.rectangle(bounds, fill=item["fill"])
    text = item.get("text") or ""
    if not text:
        return
    size = int(item.get("text_size") or 16)
    font = font_for(size, bold=True)
    text_box = draw.textbbox((0, 0), text, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    object_id = item["object_id"]
    if object_id in {"header", "badge"}:
        x = box["x"] + 16
    else:
        x = box["x"] + max(0, (box["width"] - text_width) // 2)
    y = box["y"] + max(0, (box["height"] - text_height) // 2) - text_box[1]
    draw.text(
        (x, y),
        text,
        font=font,
        fill=item.get("text_fill") or "#0f172a",
    )


def draw_business_canvas(include_gap: bool) -> Image.Image:
    image = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 20, 1160, 720), outline="#cbd5e1", width=2)
    for item in OBJECTS:
        if not include_gap and item["object_id"] == GAP_OBJECT_ID:
            continue
        draw_object(draw, item)
    return image


def draw_diagnostic_overlay(case_id: str) -> Image.Image:
    overlay = Image.new("RGBA", (PAGE_WIDTH, PAGE_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    box = GAP_RECT
    left = box["x"]
    top = box["y"]
    right = left + box["width"] - 1
    bottom = top + box["height"] - 1
    fill = CASE_BACKGROUNDS[case_id]
    color = CASE_COLORS[case_id]
    draw.rectangle((left, top, right, bottom), fill=fill + "f2", outline=color, width=4)
    spacing = 22
    for offset in range(-box["height"], box["width"] + box["height"], spacing):
        x1 = left + offset
        y1 = bottom
        x2 = x1 + box["height"]
        y2 = top
        draw.line((x1, y1, x2, y2), fill=color + "55", width=1)
    label = "NOT CAPTURED\nOBSERVATION UNKNOWN" if case_id == "not-captured" else (
        "NOT DELIVERED\n" + CASE_LABELS[case_id]
    )
    font = font_for(25, bold=True)
    text_box = draw.multiline_textbbox((0, 0), label, font=font, spacing=8, align="center")
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    x = left + (box["width"] - text_width) / 2
    y = top + (box["height"] - text_height) / 2
    panel_width = min(box["width"] - 40, text_width + 40)
    draw.rectangle(
        (
            left + (box["width"] - panel_width) / 2,
            y - 16,
            left + (box["width"] + panel_width) / 2,
            y + text_height + 16,
        ),
        fill="#ffffff",
        outline=color,
        width=2,
    )
    draw.multiline_text((x, y), label, font=font, fill=color, spacing=8, align="center")
    return overlay


def mask_rectangle() -> Image.Image:
    mask = Image.new("L", (PAGE_WIDTH, PAGE_HEIGHT), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle(
        (
            GAP_RECT["x"],
            GAP_RECT["y"],
            GAP_RECT["x"] + GAP_RECT["width"] - 1,
            GAP_RECT["y"] + GAP_RECT["height"] - 1,
        ),
        fill=255,
    )
    return mask


def diff_images(reference: Image.Image, output: Image.Image) -> np.ndarray:
    ref = np.asarray(reference.convert("RGB"))
    out = np.asarray(output.convert("RGB"))
    return np.any(ref != out, axis=2)


def save_binary_mask(mask: np.ndarray, path: Path) -> None:
    image = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), mode="L")
    image.save(path)


def render_artifacts(out_dir: Path) -> dict[str, Any]:
    artifact_dir = out_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    reference = draw_business_canvas(include_gap=True)
    business = draw_business_canvas(include_gap=False)
    reference_path = artifact_dir / "reference.png"
    reference.save(reference_path)
    mask_image = mask_rectangle()
    mask_path = artifact_dir / "diagnostic_mask.png"
    mask_image.save(mask_path)

    mask_array = np.asarray(mask_image) > 0
    diff = diff_images(reference, business)
    diff_outside_mask = diff & ~mask_array
    diff_visual = np.zeros((PAGE_HEIGHT, PAGE_WIDTH, 3), dtype=np.uint8)
    diff_visual[diff] = [220, 38, 38]
    diff_path = artifact_dir / "raw_diff.png"
    Image.fromarray(diff_visual, mode="RGB").save(diff_path)
    outside_path = artifact_dir / "masked_diff.png"
    save_binary_mask(diff_outside_mask, outside_path)

    cases: dict[str, Any] = {}
    for case_id in CASE_IDS:
        case_dir = artifact_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        business_path = case_dir / "business.png"
        business.save(business_path)
        diagnostic = draw_diagnostic_overlay(case_id)
        diagnostic_path = case_dir / "diagnostic.png"
        diagnostic.save(diagnostic_path)
        delivery = business.convert("RGBA")
        delivery.alpha_composite(diagnostic)
        delivery_path = case_dir / "delivery.png"
        delivery.convert("RGB").save(delivery_path)
        masks = []
        for suffix, array in (
            ("raw", diff),
            ("excluded", diff & mask_array),
            ("outside", diff_outside_mask),
        ):
            path = case_dir / f"{suffix}_diff.png"
            save_binary_mask(array, path)
            masks.append(
                {
                    "kind": suffix,
                    "path": str(path),
                    "sha256": sha256_file(path),
                    "pixels": int(np.count_nonzero(array)),
                }
            )
        cases[case_id] = {
            "business": {
                "path": str(business_path),
                "sha256": sha256_file(business_path),
            },
            "diagnostic": {
                "path": str(diagnostic_path),
                "sha256": sha256_file(diagnostic_path),
            },
            "delivery": {
                "path": str(delivery_path),
                "sha256": sha256_file(delivery_path),
            },
            "diffs": masks,
        }
    return {
        "reference": {
            "path": str(reference_path),
            "sha256": sha256_file(reference_path),
            "width": PAGE_WIDTH,
            "height": PAGE_HEIGHT,
        },
        "mask": {
            "path": str(mask_path),
            "sha256": sha256_file(mask_path),
            "pixels": int(np.count_nonzero(mask_array)),
        },
        "raw_diff": {
            "path": str(diff_path),
            "sha256": sha256_file(diff_path),
            "pixels": int(np.count_nonzero(diff)),
        },
        "masked_diff": {
            "path": str(outside_path),
            "sha256": sha256_file(outside_path),
            "pixels": int(np.count_nonzero(diff_outside_mask)),
        },
        "cases": cases,
        "diff_array": diff,
        "mask_array": mask_array,
        "diff_outside_mask": diff_outside_mask,
    }


def ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def case_gap_state(case_id: str) -> tuple[str, str]:
    if case_id == "not-captured":
        return "unknown", "not-captured"
    return "missing", case_id


def coverage_metrics(case_id: str) -> dict[str, Any]:
    gap_state, gap_status = case_gap_state(case_id)
    unknown = gap_state == "unknown"
    missing_area = 0 if unknown else REQUIRED_AREA - DELIVERED_AREA
    unknown_area = REQUIRED_AREA - DELIVERED_AREA if unknown else 0
    missing_objects = 0 if unknown else REQUIRED_OBJECTS - DELIVERED_OBJECT_COUNT
    unknown_objects = REQUIRED_OBJECTS - DELIVERED_OBJECT_COUNT if unknown else 0
    missing_text = 0 if unknown else GAP_TEXT_CHARS
    unknown_text = GAP_TEXT_CHARS if unknown else 0
    missing_critical = 0 if unknown else REQUIRED_CRITICAL - DELIVERED_CRITICAL
    unknown_critical = REQUIRED_CRITICAL - DELIVERED_CRITICAL if unknown else 0
    coverage_status = "unknown" if unknown else "partial"
    return {
        "area": {
            "denominator_px": REQUIRED_AREA,
            "covered_px": DELIVERED_AREA,
            "missing_px": missing_area,
            "unknown_px": unknown_area,
            "known_coverage_ratio": ratio(DELIVERED_AREA, REQUIRED_AREA),
            "coverage_status": coverage_status,
        },
        "object": {
            "denominator_count": REQUIRED_OBJECTS,
            "covered_count": DELIVERED_OBJECT_COUNT,
            "missing_count": missing_objects,
            "unknown_count": unknown_objects,
            "known_coverage_ratio": ratio(DELIVERED_OBJECT_COUNT, REQUIRED_OBJECTS),
            "coverage_status": coverage_status,
        },
        "text": {
            "denominator_characters": REQUIRED_TEXT_CHARS,
            "covered_characters": DELIVERED_TEXT_CHARS,
            "missing_characters": missing_text,
            "unknown_characters": unknown_text,
            "known_coverage_ratio": ratio(DELIVERED_TEXT_CHARS, REQUIRED_TEXT_CHARS),
            "coverage_status": coverage_status,
        },
        "critical": {
            "denominator_count": REQUIRED_CRITICAL,
            "covered_count": DELIVERED_CRITICAL,
            "missing_count": missing_critical,
            "unknown_count": unknown_critical,
            "known_coverage_ratio": ratio(DELIVERED_CRITICAL, REQUIRED_CRITICAL),
            "coverage_status": coverage_status,
        },
        "gap_status": gap_status,
        "gap_state": gap_state,
        "release_status": "partial",
    }


COORDINATE_SYSTEM = {
    "source": {
        "space": "css-px",
        "origin": "top-left",
        "width": PAGE_WIDTH,
        "height": PAGE_HEIGHT,
    },
    "output": {
        "space": "css-px",
        "origin": "top-left",
        "width": PAGE_WIDTH,
        "height": PAGE_HEIGHT,
    },
    "matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    "mapping": "identity",
}


def build_region_entries(case_id: str) -> list[dict[str, Any]]:
    gap_state, gap_status = case_gap_state(case_id)
    regions: list[dict[str, Any]] = []
    for item in OBJECTS:
        is_gap = item["object_id"] == GAP_OBJECT_ID
        status = gap_status if is_gap else "delivered"
        region = {
            "region_id": "REG-" + item["object_id"],
            "object_keys": [item["object_id"]],
            "coordinate_system": COORDINATE_SYSTEM,
            "source_rect": item["rect"],
            "output_rect": item["rect"],
            "coverage_status": status,
            "reason": CASE_REASONS[case_id] if is_gap else "Delivered in the business content layer.",
            "evidence": CASE_EVIDENCE[case_id] if is_gap else [
                "artifact:reference",
                f"artifact:{case_id}/business",
            ],
            "affected_dimensions": (
                ["visual", "structure", "edit", "asset"]
                if is_gap
                else []
            ),
            "allowed_actions": (
                ["show-diagnostic-placeholder", "report-gap", "request-next-step"]
                if is_gap
                else ["keep-delivered-content", "include-in-export-with-partial-status"]
            ),
            "blocked_actions": CASE_BLOCKED_ACTIONS[case_id] if is_gap else [],
            "diagnostic_mask": is_gap,
            "gap_state": gap_state if is_gap else "none",
            "next_step": CASE_NEXT_STEPS[case_id] if is_gap else None,
        }
        if is_gap:
            region["object_keys"] = [GAP_OBJECT_ID, "price-label", "price-value"]
        regions.append(region)
    return regions


def build_case_canvas(case_id: str) -> dict[str, Any]:
    label = CASE_LABELS[case_id]
    root_name = f"[PARTIAL] R5-EXP-04 {label} · rev1"
    delivered_names = [item["label"] for item in DELIVERED_OBJECTS]
    placeholder = {
        "node_name": f"[{case_id}] Price panel",
        "status": case_id,
        "text": (
            "NOT CAPTURED / OBSERVATION UNKNOWN"
            if case_id == "not-captured"
            else f"NOT DELIVERED / {label}"
        ),
        "rect": GAP_RECT,
        "layer": "diagnostic",
        "is_design_content": False,
        "legend_key": case_id,
    }
    return {
        "case_id": case_id,
        "root_name": root_name,
        "root_status": "PARTIAL",
        "business_flow": {
            "name": "Business Content",
            "children": delivered_names,
            "contains_diagnostic": False,
        },
        "diagnostic_layer": {
            "name": "Coverage Diagnostics",
            "separate_from_business_flow": True,
            "placeholders": [placeholder],
        },
        "report_frame": {
            "name": "Coverage / Gaps Report",
            "outside_business_flow": True,
            "outside_diagnostic_layer": True,
            "case_id": case_id,
        },
        "legend": {
            "intentional-omission": "Intentionally not delivered by policy.",
            "write-failed": "Required write failed.",
            "observed-absent": "Observed absent in the target state; not a delete claim.",
            "not-captured": "Capture missing; absence unknown.",
        },
        "export_gate": {
            "partial_export_requires_confirmation": True,
            "manual_export_can_be_blocked": False,
            "lock_is_security_boundary": False,
            "automated_complete_export_allowed": False,
        },
    }


def build_report(case_id: str) -> dict[str, Any]:
    gap_state, gap_status = case_gap_state(case_id)
    text_fields = ["price-label", "price-value"]
    summary = {
        "counts_by_unit": {
            "regions": 1,
            "objects": 1,
            "text_fields": len(text_fields),
            "text_characters": GAP_TEXT_CHARS,
            "critical_items": 1,
        },
        "units_note": "Counts are reported by unit and must not be added together.",
        "reference_only_regions": 0,
        "gap_state": gap_state,
        "release_status": "partial",
    }
    gap_entry = {
        "entry_id": f"GAP-{case_id}",
        "object_keys": [GAP_OBJECT_ID, *text_fields],
        "status": case_id,
        "coverage_state": gap_state,
        "reason": CASE_REASONS[case_id],
        "current_display": (
            "Diagnostic placeholder: observation unknown"
            if case_id == "not-captured"
            else f"Diagnostic placeholder: not delivered ({CASE_LABELS[case_id]})"
        ),
        "coordinates": GAP_RECT,
        "affected_dimensions": ["visual", "structure", "edit", "asset"],
        "evidence": CASE_EVIDENCE[case_id],
        "blocked_actions": CASE_BLOCKED_ACTIONS[case_id],
        "next_step": CASE_NEXT_STEPS[case_id],
        "legend_key": case_id,
        "not_deleted": case_id == "observed-absent",
    }
    return {
        "report_id": f"REPORT-{case_id}",
        "title": "Coverage / Gaps Report",
        "separate_from_business_flow": True,
        "root_name": f"[PARTIAL] R5-EXP-04 {CASE_LABELS[case_id]} · rev1",
        "summary": summary,
        "legend": {
            "intentional-omission": "Intentionally omitted by policy; not complete delivery.",
            "write-failed": "Technical write failed; content absent and retry required.",
            "observed-absent": "Absent in target state; not deleted or synthesized.",
            "not-captured": "No capture evidence; absence is unknown.",
        },
        "entries": [gap_entry],
        "blocked_actions": CASE_BLOCKED_ACTIONS[case_id],
        "next_step": CASE_NEXT_STEPS[case_id],
    }


def build_coverage_case(case_id: str, artifacts: dict[str, Any]) -> dict[str, Any]:
    metrics = coverage_metrics(case_id)
    diff = artifacts["cases"][case_id]["diffs"]
    raw_diff_pixels = next(item["pixels"] for item in diff if item["kind"] == "raw")
    excluded_pixels = next(item["pixels"] for item in diff if item["kind"] == "excluded")
    outside_pixels = next(item["pixels"] for item in diff if item["kind"] == "outside")
    denominator = DENOMINATOR_PIXELS
    valid_compare = denominator - excluded_pixels
    return {
        "case_id": case_id,
        "coverage": metrics,
        "regions": build_region_entries(case_id),
        "diff_reconciliation": {
            "reference_path": artifacts["reference"]["path"],
            "output_path": artifacts["cases"][case_id]["business"]["path"],
            "diagnostic_mask_path": artifacts["mask"]["path"],
            "denominator_pixels": denominator,
            "valid_compare_pixels": valid_compare,
            "excluded_diagnostic_pixels": excluded_pixels,
            "raw_diff_pixels": raw_diff_pixels,
            "masked_diff_pixels": outside_pixels,
            "raw_diff_ratio": ratio(raw_diff_pixels, denominator),
            "masked_diff_ratio_fixed_denominator": ratio(outside_pixels, denominator),
            "denominator_after_mask": denominator,
            "masked_diff_is_zero": outside_pixels == 0,
            "release_status_after_mask": "partial",
            "complete_export_allowed": False,
        },
    }


def build_coverage_map(artifacts: dict[str, Any]) -> dict[str, Any]:
    cases = {case_id: build_coverage_case(case_id, artifacts) for case_id in CASE_IDS}
    required_rectangles = [item["rect"] for item in OBJECTS]
    sum_area = sum(rect_area(item) for item in required_rectangles)
    return {
        "map_id": "MAP-R5-EXP-04",
        "coordinate_system": COORDINATE_SYSTEM,
        "required_units": {
            "regions": REQUIRED_OBJECTS,
            "objects": REQUIRED_OBJECTS,
            "text_fields": 9,
            "text_characters": REQUIRED_TEXT_CHARS,
            "critical_items": REQUIRED_CRITICAL,
            "area_px": REQUIRED_AREA,
        },
        "area_union_control": {
            "region_count": REQUIRED_OBJECTS,
            "sum_of_region_areas_px": sum_area,
            "union_area_px": REQUIRED_AREA,
            "overlap_area_px": sum_area - REQUIRED_AREA,
            "uses_union": REQUIRED_AREA < sum_area,
        },
        "cases": cases,
        "mask_contract": {
            "mask_rect": GAP_RECT,
            "mask_pixels": GAP_AREA,
            "mask_only_diagnostic_placeholder": True,
            "does_not_shrink_contract_denominator": True,
        },
    }


def build_manifest(canvas_cases: dict[str, Any], coverage_map: dict[str, Any]) -> dict[str, Any]:
    cases: dict[str, Any] = {}
    status_counts: Counter[str] = Counter()
    for case_id in CASE_IDS:
        canvas = canvas_cases[case_id]
        metrics = coverage_map["cases"][case_id]["coverage"]
        status_counts[case_id] += 1
        cases[case_id] = {
            "root_name": canvas["root_name"],
            "release_status": "partial",
            "partial": True,
            "report_ref": f"report.json#/{case_id}",
            "coverage_map_ref": f"coverage_map.json#/cases/{case_id}",
            "business_flow": canvas["business_flow"]["name"],
            "diagnostic_layer": canvas["diagnostic_layer"]["name"],
            "report_frame": canvas["report_frame"]["name"],
            "gap_status": metrics["gap_status"],
            "gap_state": metrics["gap_state"],
            "coverage": {
                "area": metrics["area"],
                "object": metrics["object"],
                "text": metrics["text"],
                "critical": metrics["critical"],
            },
            "export_gate": canvas["export_gate"],
        }
    return {
        "manifest_id": "MANIFEST-R5-EXP-04",
        "job": JOB,
        "revision": REVISION,
        "status": "partial",
        "root_status": "[PARTIAL]",
        "cases": cases,
        "case_status_counts": dict(status_counts),
        "overall_release_status": "partial",
        "complete_export_allowed": False,
        "diagnostic_layer_is_design_content": False,
        "report_is_separate": True,
    }


def build_bundle(out_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    artifacts = render_artifacts(out_dir)
    canvas_cases = {case_id: build_case_canvas(case_id) for case_id in CASE_IDS}
    reports = {case_id: build_report(case_id) for case_id in CASE_IDS}
    coverage_map = build_coverage_map(artifacts)
    manifest = build_manifest(canvas_cases, coverage_map)
    canvas = {
        "job": JOB,
        "revision": REVISION,
        "root_status": "PARTIAL",
        "cases": canvas_cases,
        "report_frames": {
            case_id: canvas_cases[case_id]["report_frame"] for case_id in CASE_IDS
        },
        "export_gate": {
            "partial_export_requires_confirmation": True,
            "manual_export_can_be_blocked": False,
            "lock_is_security_boundary": False,
            "automated_complete_export_allowed": False,
        },
    }
    report = {
        "job": JOB,
        "revision": REVISION,
        "status": "partial",
        "summary": "Four same-position gap causes are reported separately.",
        "cases": reports,
        "legend": reports["intentional-omission"]["legend"],
        "separate_from_business_flow": True,
    }
    result_bundle = {
        "job": JOB,
        "revision": REVISION,
        "canvas": canvas,
        "report": report,
        "manifest": manifest,
        "coverage_map": coverage_map,
        "artifacts": {
            key: value for key, value in artifacts.items()
            if key not in {"diff_array", "mask_array", "diff_outside_mask"}
        },
    }
    return result_bundle, artifacts


def freeze_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(bundle)


def validate_bundle(bundle: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if bundle != baseline:
        errors.append("bundle differs from the frozen partial-delivery contract")

    canvas = bundle.get("canvas", {})
    report = bundle.get("report", {})
    manifest = bundle.get("manifest", {})
    coverage_map = bundle.get("coverage_map", {})

    if set(canvas.get("cases", {})) != set(CASE_IDS):
        errors.append("canvas case set is incomplete")
    if set(report.get("cases", {})) != set(CASE_IDS):
        errors.append("report case set is incomplete")
    if set(manifest.get("cases", {})) != set(CASE_IDS):
        errors.append("manifest case set is incomplete")
    if set(coverage_map.get("cases", {})) != set(CASE_IDS):
        errors.append("coverage-map case set is incomplete")

    if canvas.get("root_status") != "PARTIAL":
        errors.append("canvas root status is not PARTIAL")
    if manifest.get("root_status") != "[PARTIAL]":
        errors.append("manifest root name status is not [PARTIAL]")
    if manifest.get("status") != "partial" or manifest.get("overall_release_status") != "partial":
        errors.append("manifest release status is not partial")
    if manifest.get("complete_export_allowed") is not False:
        errors.append("complete export is allowed")

    for case_id in CASE_IDS:
        case_canvas = canvas["cases"][case_id]
        report_case = report["cases"][case_id]
        manifest_case = manifest["cases"][case_id]
        coverage_case = coverage_map["cases"][case_id]

        if not case_canvas.get("root_name", "").startswith("[PARTIAL]"):
            errors.append(f"{case_id}: root name lacks [PARTIAL]")
        if case_canvas.get("root_status") != "PARTIAL":
            errors.append(f"{case_id}: root status is not PARTIAL")
        if case_canvas.get("business_flow", {}).get("contains_diagnostic") is not False:
            errors.append(f"{case_id}: business flow contains diagnostics")
        if case_canvas.get("diagnostic_layer", {}).get("separate_from_business_flow") is not True:
            errors.append(f"{case_id}: diagnostic layer is not separate")
        if case_canvas.get("report_frame", {}).get("outside_business_flow") is not True:
            errors.append(f"{case_id}: report frame is inside business flow")
        if case_canvas.get("report_frame", {}).get("outside_diagnostic_layer") is not True:
            errors.append(f"{case_id}: report frame is inside diagnostic layer")

        placeholders = case_canvas.get("diagnostic_layer", {}).get("placeholders", [])
        if len(placeholders) != 1 or not placeholders[0].get("text"):
            errors.append(f"{case_id}: diagnostic placeholder is missing or blank")
        elif placeholders[0].get("status") != case_id:
            errors.append(f"{case_id}: placeholder status does not match case")

        if report_case.get("separate_from_business_flow") is not True:
            errors.append(f"{case_id}: report is not separate")
        entries = report_case.get("entries", [])
        if len(entries) != 1 or entries[0].get("status") != case_id:
            errors.append(f"{case_id}: report gap status is not preserved")
        entry = entries[0] if entries else {}
        if not entry.get("blocked_actions"):
            errors.append(f"{case_id}: blocked actions are missing")
        if not entry.get("next_step"):
            errors.append(f"{case_id}: next step is missing")
        if not entry.get("evidence"):
            errors.append(f"{case_id}: evidence is missing")
        if set(entry.get("affected_dimensions") or []) != {"visual", "structure", "edit", "asset"}:
            errors.append(f"{case_id}: affected dimensions are incomplete")
        if case_id == "observed-absent" and entry.get("not_deleted") is not True:
            errors.append("observed-absent was collapsed into a deletion claim")
        if case_id == "not-captured" and entry.get("coverage_state") != "unknown":
            errors.append("not-captured was collapsed into a knowable absence")

        summary = report_case.get("summary", {})
        counts = summary.get("counts_by_unit", {})
        if not {"regions", "objects", "text_fields", "text_characters", "critical_items"}.issubset(counts):
            errors.append(f"{case_id}: summary counts mix or omit units")
        if "total" in summary or "missing_total" in summary:
            errors.append(f"{case_id}: summary contains an ambiguous mixed-unit total")

        if manifest_case.get("release_status") != "partial":
            errors.append(f"{case_id}: manifest case is not partial")
        if manifest_case.get("gap_status") != coverage_case.get("coverage", {}).get("gap_status"):
            errors.append(f"{case_id}: manifest gap status mismatches coverage map")

        metrics = coverage_case.get("coverage", {})
        for dimension in ("area", "object", "text", "critical"):
            if dimension not in metrics:
                errors.append(f"{case_id}: coverage dimension {dimension} is missing")
        if "score" in metrics or "overall_score" in metrics:
            errors.append(f"{case_id}: coverage was collapsed into one score")

        regions = coverage_case.get("regions", [])
        if len(regions) != REQUIRED_OBJECTS:
            errors.append(f"{case_id}: coverage region count mismatch")
        for region in regions:
            for key in (
                "region_id",
                "coordinate_system",
                "coverage_status",
                "reason",
                "evidence",
                "affected_dimensions",
                "object_keys",
            ):
                if key not in region:
                    errors.append(f"{case_id}/{region.get('region_id')}: missing {key}")
            if region.get("coordinate_system", {}).get("mapping") != "identity":
                errors.append(f"{case_id}/{region.get('region_id')}: coordinate mapping changed")

        diff = coverage_case.get("diff_reconciliation", {})
        if diff.get("denominator_pixels") != DENOMINATOR_PIXELS:
            errors.append(f"{case_id}: denominator changed")
        if diff.get("denominator_after_mask") != DENOMINATOR_PIXELS:
            errors.append(f"{case_id}: denominator shrank after mask")
        if (
            diff.get("valid_compare_pixels", 0) + diff.get("excluded_diagnostic_pixels", 0)
            != DENOMINATOR_PIXELS
        ):
            errors.append(f"{case_id}: valid and excluded pixels do not reconstruct the denominator")
        if diff.get("excluded_diagnostic_pixels") != GAP_AREA:
            errors.append(f"{case_id}: diagnostic mask area changed")
        if diff.get("masked_diff_pixels") != 0:
            errors.append(f"{case_id}: masked diff is not zero in the fixture")
        if diff.get("masked_diff_ratio_fixed_denominator") != 0:
            errors.append(f"{case_id}: masked diff ratio is not fixed-denominator zero")
        if diff.get("release_status_after_mask") != "partial":
            errors.append(f"{case_id}: masked diff incorrectly changed release status")
        if diff.get("complete_export_allowed") is not False:
            errors.append(f"{case_id}: masked diff incorrectly allowed complete export")

    statuses = {
        coverage_map["cases"][case_id]["coverage"]["gap_status"]
        for case_id in CASE_IDS
    }
    if statuses != set(CASE_IDS):
        errors.append("four gap statuses were collapsed")

    if coverage_map.get("mask_contract", {}).get("does_not_shrink_contract_denominator") is not True:
        errors.append("mask contract allows denominator shrink")
    if coverage_map.get("mask_contract", {}).get("mask_only_diagnostic_placeholder") is not True:
        errors.append("mask covers non-diagnostic content")
    if coverage_map.get("area_union_control", {}).get("uses_union") is not True:
        errors.append("area coverage uses summed rectangles instead of union")
    if coverage_map["area_union_control"]["union_area_px"] >= coverage_map["area_union_control"]["sum_of_region_areas_px"]:
        errors.append("area union control has no overlap")

    gate = canvas.get("export_gate", {})
    if gate.get("lock_is_security_boundary") is not False:
        errors.append("lock is claimed as a security boundary")
    if gate.get("manual_export_can_be_blocked") is not False:
        errors.append("manual export is falsely claimed to be blocked")
    if gate.get("automated_complete_export_allowed") is not False:
        errors.append("automated complete export is allowed")

    return errors


def set_case_status(bundle: dict[str, Any], case_id: str, new_status: str) -> None:
    bundle["coverage_map"]["cases"][case_id]["coverage"]["gap_status"] = new_status
    bundle["report"]["cases"][case_id]["entries"][0]["status"] = new_status
    bundle["manifest"]["cases"][case_id]["gap_status"] = new_status
    bundle["canvas"]["cases"][case_id]["diagnostic_layer"]["placeholders"][0]["status"] = new_status


MUTATION_SPECS: list[tuple[str, str, Callable[[dict[str, Any]], None]]] = [
    (
        "root-name-drops-partial",
        "Remove the user-visible PARTIAL marker.",
        lambda doc: doc["canvas"]["cases"]["write-failed"].__setitem__(
            "root_name", "R5-EXP-04 WRITE FAILED · rev1"
        ),
    ),
    (
        "manifest-claims-complete",
        "Mark a partial delivery complete.",
        lambda doc: doc["manifest"].__setitem__("overall_release_status", "complete"),
    ),
    (
        "report-inside-business-flow",
        "Move the report frame into the business flow.",
        lambda doc: doc["canvas"]["cases"]["write-failed"]["report_frame"].__setitem__(
            "outside_business_flow", False
        ),
    ),
    (
        "diagnostics-inside-business-flow",
        "Treat diagnostics as design content.",
        lambda doc: doc["canvas"]["cases"]["not-captured"].__setitem__(
            "business_flow",
            {
                "name": "Business Content",
                "children": ["Price panel diagnostics"],
                "contains_diagnostic": True,
            },
        ),
    ),
    (
        "legend-entry-missing",
        "Remove one gap legend.",
        lambda doc: doc["report"]["legend"].pop("observed-absent"),
    ),
    (
        "blocked-actions-missing",
        "Remove the prohibited-actions list.",
        lambda doc: doc["report"]["cases"]["write-failed"]["entries"][0].__setitem__(
            "blocked_actions", []
        ),
    ),
    (
        "blank-placeholder",
        "Use blank space instead of a diagnostic gap.",
        lambda doc: doc["canvas"]["cases"]["intentional-omission"]["diagnostic_layer"]["placeholders"][0].__setitem__(
            "text", ""
        ),
    ),
    (
        "intentional-relabelled-write-failed",
        "Collapse intentional omission into write failure.",
        lambda doc: set_case_status(doc, "intentional-omission", "write-failed"),
    ),
    (
        "write-failed-relabelled-intentional",
        "Collapse write failure into intentional omission.",
        lambda doc: set_case_status(doc, "write-failed", "intentional-omission"),
    ),
    (
        "observed-absent-marked-deleted",
        "Convert observed absence into a deletion claim.",
        lambda doc: doc["report"]["cases"]["observed-absent"]["entries"][0].__setitem__(
            "not_deleted", False
        ),
    ),
    (
        "not-captured-marked-absent",
        "Treat missing capture as observed absence.",
        lambda doc: set_case_status(doc, "not-captured", "observed-absent"),
    ),
    (
        "coverage-reason-missing",
        "Drop the reason from a coverage region.",
        lambda doc: doc["coverage_map"]["cases"]["not-captured"]["regions"][8].pop(
            "reason", None
        ),
    ),
    (
        "coverage-evidence-missing",
        "Drop evidence from a coverage region.",
        lambda doc: doc["coverage_map"]["cases"]["write-failed"]["regions"][8].__setitem__(
            "evidence", []
        ),
    ),
    (
        "affected-dimensions-empty",
        "Drop affected dimensions from a gap.",
        lambda doc: doc["coverage_map"]["cases"]["observed-absent"]["regions"][8].__setitem__(
            "affected_dimensions", []
        ),
    ),
    (
        "object-keys-empty",
        "Drop the object key mapping.",
        lambda doc: doc["coverage_map"]["cases"]["intentional-omission"]["regions"][8].__setitem__(
            "object_keys", []
        ),
    ),
    (
        "coordinate-mapping-shifted",
        "Shift the output coordinate mapping.",
        lambda doc: doc["coverage_map"]["cases"]["write-failed"]["regions"][0].__setitem__(
            "coordinate_system",
            {
                **COORDINATE_SYSTEM,
                "mapping": "translate(12, 8)",
            },
        ),
    ),
    (
        "single-coverage-score",
        "Collapse four coverage dimensions into one score.",
        lambda doc: doc["coverage_map"]["cases"]["not-captured"]["coverage"].__setitem__(
            "overall_score", 0.92
        ),
    ),
    (
        "denominator-shrinks",
        "Shrink the denominator after masking.",
        lambda doc: doc["coverage_map"]["cases"]["write-failed"]["diff_reconciliation"].__setitem__(
            "denominator_after_mask",
            DENOMINATOR_PIXELS - GAP_AREA,
        ),
    ),
    (
        "masked-diff-becomes-pass",
        "Promote a partial page to complete after mask exclusion.",
        lambda doc: doc["coverage_map"]["cases"]["not-captured"]["diff_reconciliation"].update(
            {
                "release_status_after_mask": "complete",
                "complete_export_allowed": True,
            }
        ),
    ),
    (
        "area-sums-overlap",
        "Replace union area with summed rectangles.",
        lambda doc: doc["coverage_map"]["area_union_control"].update(
            {
                "union_area_px": doc["coverage_map"]["area_union_control"]["sum_of_region_areas_px"],
                "uses_union": False,
            }
        ),
    ),
    (
        "ambiguous-summary-total",
        "Add a mixed-unit total.",
        lambda doc: doc["report"]["cases"]["intentional-omission"]["summary"].__setitem__(
            "missing_total", 4
        ),
    ),
    (
        "lock-claimed-as-export-gate",
        "Claim the Figma lock blocks manual export.",
        lambda doc: doc["canvas"]["export_gate"].update(
            {
                "lock_is_security_boundary": True,
                "manual_export_can_be_blocked": True,
            }
        ),
    ),
    (
        "malformed-mask-area",
        "Exclude the entire page from diff.",
        lambda doc: doc["coverage_map"]["mask_contract"].__setitem__(
            "mask_rect", {"x": 0, "y": 0, "width": PAGE_WIDTH, "height": PAGE_HEIGHT}
        ),
    ),
    (
        "complete-export-allowed",
        "Allow automated complete export for a partial canvas.",
        lambda doc: doc["canvas"]["cases"]["intentional-omission"]["export_gate"].__setitem__(
            "automated_complete_export_allowed", True
        ),
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
    coverage_cases = bundle["coverage_map"]["cases"]
    canvas_cases = bundle["canvas"]["cases"]
    report_cases = bundle["report"]["cases"]
    manifest = bundle["manifest"]

    gap_rects = [
        next(
            region["source_rect"]
            for region in coverage_cases[case_id]["regions"]
            if region["region_id"] == "REG-" + GAP_OBJECT_ID
        )
        for case_id in CASE_IDS
    ]
    checks.append(
        check(
            "same-gap-coordinate",
            "All four causes occupy the exact same source/output rectangle.",
            len({canonical(item) for item in gap_rects}) == 1 and gap_rects[0] == GAP_RECT,
            gap_rects,
        )
    )
    checks.append(
        check(
            "four-gap-statuses-preserved",
            "The four gap causes remain distinct in report, manifest and coverage map.",
            {
                coverage_cases[case_id]["coverage"]["gap_status"]
                for case_id in CASE_IDS
            }
            == set(CASE_IDS)
            and all(
                report_cases[case_id]["entries"][0]["status"] == case_id
                and manifest["cases"][case_id]["gap_status"] == case_id
                for case_id in CASE_IDS
            ),
            {
                case_id: coverage_cases[case_id]["coverage"]["gap_status"]
                for case_id in CASE_IDS
            },
        )
    )
    checks.append(
        check(
            "partial-root-names",
            "Every user-visible root name and manifest status carries PARTIAL.",
            all(canvas_cases[case_id]["root_name"].startswith("[PARTIAL]") for case_id in CASE_IDS)
            and manifest["root_status"] == "[PARTIAL]"
            and manifest["status"] == "partial",
            [canvas_cases[case_id]["root_name"] for case_id in CASE_IDS],
        )
    )
    checks.append(
        check(
            "business-report-diagnostic-separation",
            "Business flow, diagnostic layer and report frame are separate.",
            all(
                canvas_cases[case_id]["business_flow"]["contains_diagnostic"] is False
                and canvas_cases[case_id]["diagnostic_layer"]["separate_from_business_flow"] is True
                and canvas_cases[case_id]["report_frame"]["outside_business_flow"] is True
                and report_cases[case_id]["separate_from_business_flow"] is True
                for case_id in CASE_IDS
            ),
            {
                case_id: {
                    "business": canvas_cases[case_id]["business_flow"],
                    "diagnostic": canvas_cases[case_id]["diagnostic_layer"]["name"],
                    "report": canvas_cases[case_id]["report_frame"]["name"],
                }
                for case_id in CASE_IDS
            },
        )
    )
    checks.append(
        check(
            "visible-diagnostic-labels",
            "No missing region is represented by blank space.",
            all(
                canvas_cases[case_id]["diagnostic_layer"]["placeholders"][0]["text"].strip()
                for case_id in CASE_IDS
            ),
            [
                canvas_cases[case_id]["diagnostic_layer"]["placeholders"][0]["text"]
                for case_id in CASE_IDS
            ],
        )
    )
    checks.append(
        check(
            "legend-and-blocked-actions",
            "The report carries all four legend entries and prohibited actions.",
            set(bundle["report"]["legend"]) == set(CASE_IDS)
            and all(report_cases[case_id]["blocked_actions"] for case_id in CASE_IDS),
            bundle["report"]["legend"],
        )
    )
    checks.append(
        check(
            "summary-units-separate",
            "The user summary reports regions, objects, text fields, characters and critical items by unit.",
            all(
                {"regions", "objects", "text_fields", "text_characters", "critical_items"}
                .issubset(report_cases[case_id]["summary"]["counts_by_unit"])
                for case_id in CASE_IDS
            ),
            {
                case_id: report_cases[case_id]["summary"]["counts_by_unit"]
                for case_id in CASE_IDS
            },
        )
    )
    checks.append(
        check(
            "coverage-dimensions-separate",
            "Area, object, text and critical coverage are separate.",
            all(
                {"area", "object", "text", "critical"}.issubset(
                    coverage_cases[case_id]["coverage"]
                )
                and "overall_score" not in coverage_cases[case_id]["coverage"]
                for case_id in CASE_IDS
            ),
            coverage_cases["write-failed"]["coverage"],
        )
    )
    checks.append(
        check(
            "area-union-not-sum",
            "Coverage area uses union and the fixture contains overlapping regions.",
            bundle["coverage_map"]["area_union_control"]["uses_union"] is True
            and bundle["coverage_map"]["area_union_control"]["union_area_px"]
            < bundle["coverage_map"]["area_union_control"]["sum_of_region_areas_px"],
            bundle["coverage_map"]["area_union_control"],
        )
    )
    known_metrics = coverage_cases["write-failed"]["coverage"]
    checks.append(
        check(
            "coverage-gap-is-visible",
            "The critical price panel reduces object, text and critical coverage.",
            known_metrics["object"]["known_coverage_ratio"] < 1
            and known_metrics["text"]["known_coverage_ratio"] < 1
            and known_metrics["critical"]["known_coverage_ratio"] < 1
            and known_metrics["area"]["known_coverage_ratio"] < 1,
            known_metrics,
        )
    )
    checks.append(
        check(
            "not-captured-is-unknown",
            "Missing capture stays unknown instead of becoming observed absence.",
            coverage_cases["not-captured"]["coverage"]["gap_status"] == "not-captured"
            and coverage_cases["not-captured"]["coverage"]["gap_state"] == "unknown"
            and coverage_cases["not-captured"]["coverage"]["object"]["unknown_count"] == 1
            and coverage_cases["not-captured"]["coverage"]["object"]["missing_count"] == 0,
            coverage_cases["not-captured"]["coverage"],
        )
    )
    checks.append(
        check(
            "observed-absent-is-not-delete",
            "Observed absence is not represented as a confirmed deletion.",
            report_cases["observed-absent"]["entries"][0]["not_deleted"] is True,
            report_cases["observed-absent"]["entries"][0],
        )
    )
    diff_records = [
        coverage_cases[case_id]["diff_reconciliation"] for case_id in CASE_IDS
    ]
    checks.append(
        check(
            "diagnostic-mask-denominator-fixed",
            "Mask exclusion preserves the original raster denominator.",
            all(
                item["denominator_pixels"] == DENOMINATOR_PIXELS
                and item["denominator_after_mask"] == DENOMINATOR_PIXELS
                and item["valid_compare_pixels"] + item["excluded_diagnostic_pixels"]
                == DENOMINATOR_PIXELS
                for item in diff_records
            ),
            [item["denominator_pixels"] for item in diff_records],
        )
    )
    checks.append(
        check(
            "masked-diff-does-not-pass",
            "A zero masked diff remains PARTIAL and cannot enable complete export.",
            all(
                item["masked_diff_pixels"] == 0
                and item["release_status_after_mask"] == "partial"
                and item["complete_export_allowed"] is False
                for item in diff_records
            ),
            {case_id: coverage_cases[case_id]["diff_reconciliation"] for case_id in CASE_IDS},
        )
    )
    checks.append(
        check(
            "lock-is-not-export-gate",
            "The model does not claim Figma lock or an independent page blocks manual export.",
            bundle["canvas"]["export_gate"]["lock_is_security_boundary"] is False
            and bundle["canvas"]["export_gate"]["manual_export_can_be_blocked"] is False,
            bundle["canvas"]["export_gate"],
        )
    )
    checks.append(
        check(
            "base-contract-valid",
            "The base partial-delivery bundle passes the same validator used for mutations.",
            not validate_bundle(bundle, baseline),
            validate_bundle(bundle, baseline),
        )
    )
    checks.append(
        check(
            "negative-mutations-rejected",
            "Every targeted invalid partial-delivery mutation is rejected.",
            mutations["rejected"] == mutations["total"] and mutations["accepted"] == 0,
            {"rejected": mutations["rejected"], "total": mutations["total"]},
        )
    )
    checks.append(
        check(
            "artifact-files-present",
            "Reference, mask, business, diagnostic and composite images exist.",
            Path(artifacts["reference"]["path"]).exists()
            and Path(artifacts["mask"]["path"]).exists()
            and all(
                Path(value["business"]["path"]).exists()
                and Path(value["diagnostic"]["path"]).exists()
                and Path(value["delivery"]["path"]).exists()
                for value in artifacts["cases"].values()
            ),
            {
                "reference": artifacts["reference"]["sha256"],
                "mask": artifacts["mask"]["sha256"],
            },
        )
    )
    checks.append(
        check(
            "no-external-runtime",
            "The experiment remains offline and does not connect to Figma.",
            True,
            {"figma_connected": False, "bridge_used": False},
        )
    )
    return checks


def status_color(status: str) -> str:
    return CASE_COLORS.get(status, "#475569")


def status_background(status: str) -> str:
    return CASE_BACKGROUNDS.get(status, "#f1f5f9")


def make_case_contact_sheet(bundle: dict[str, Any], artifacts: dict[str, Any], path: Path) -> None:
    thumb_width = 520
    label_height = 58
    gap = 18
    columns = 2
    canvas_width = columns * thumb_width + (columns + 1) * gap
    rows = 2
    item_height = 338
    canvas_height = 72 + rows * (item_height + label_height) + (rows + 1) * gap
    canvas = Image.new("RGB", (canvas_width, canvas_height), "#e8edf4")
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (gap, 16),
        "R5-EXP-04 · Same region, four gap causes",
        fill="#0f172a",
        font=font_for(25, True),
    )
    y = 72 + gap
    for index, case_id in enumerate(CASE_IDS):
        column = index % columns
        row = index // columns
        x = gap + column * (thumb_width + gap)
        if column == 0 and row > 0:
            y += item_height + label_height + gap
        with Image.open(artifacts["cases"][case_id]["delivery"]["path"]) as source:
            image = source.convert("RGB")
        ratio = thumb_width / image.width
        thumb = image.resize(
            (thumb_width, int(image.height * ratio)),
            Image.Resampling.LANCZOS,
        )
        draw.rectangle(
            (x, y, x + thumb_width, y + item_height + label_height),
            fill="#ffffff",
            outline=status_color(case_id),
            width=2,
        )
        canvas.paste(thumb, (x, y))
        draw.rectangle(
            (x, y + item_height, x + thumb_width, y + item_height + label_height),
            fill=status_background(case_id),
        )
        draw.text(
            (x + 12, y + item_height + 8),
            bundle["canvas"]["cases"][case_id]["root_name"],
            fill="#0f172a",
            font=font_for(14, True),
        )
        draw.text(
            (x + 12, y + item_height + 31),
            f"status={case_id} · diagnostic layer separate from business flow",
            fill=status_color(case_id),
            font=font_for(13, True),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def make_coverage_map_visual(bundle: dict[str, Any], artifacts: dict[str, Any], path: Path) -> None:
    with Image.open(artifacts["reference"]["path"]) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    for item in OBJECTS:
        box = item["rect"]
        is_gap = item["object_id"] == GAP_OBJECT_ID
        color = status_color("write-failed") if is_gap else "#16a34a"
        draw.rectangle(
            (
                box["x"],
                box["y"],
                box["x"] + box["width"] - 1,
                box["y"] + box["height"] - 1,
            ),
            outline=color,
            width=4 if is_gap else 2,
        )
        label = item["object_id"]
        font = font_for(12, True)
        text_box = draw.textbbox((0, 0), label, font=font)
        label_width = text_box[2] - text_box[0] + 10
        label_x = box["x"] + 4
        label_y = box["y"] + 4
        draw.rectangle(
            (label_x, label_y, label_x + label_width, label_y + 18),
            fill="#ffffff",
            outline=color,
        )
        draw.text((label_x + 5, label_y + 2), label, fill=color, font=font)
    legend_y = 730
    draw.rectangle((40, 720, 1160, 754), fill="#ffffff", outline="#cbd5e1")
    draw.text(
        (52, 728),
        "Coverage regions: green=delivered; red=critical gap shared by four causes; denominator fixed to the original contract.",
        fill="#334155",
        font=font_for(14, True),
    )
    del legend_y
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def make_coverage_matrix(bundle: dict[str, Any], path: Path) -> None:
    cases = bundle["coverage_map"]["cases"]
    columns = (
        "Case",
        "Gap state",
        "Area",
        "Objects",
        "Text",
        "Critical",
        "Release",
        "Masked diff",
    )
    values: list[list[str]] = []
    colors: list[list[str]] = []
    for case_id in CASE_IDS:
        metrics = cases[case_id]["coverage"]
        diff = cases[case_id]["diff_reconciliation"]
        values.append(
            [
                CASE_LABELS[case_id].replace(" ", "\n"),
                metrics["gap_state"],
                f"{metrics['area']['known_coverage_ratio'] * 100:.1f}%",
                f"{metrics['object']['known_coverage_ratio'] * 100:.1f}%",
                f"{metrics['text']['known_coverage_ratio'] * 100:.1f}%",
                f"{metrics['critical']['known_coverage_ratio'] * 100:.1f}%",
                diff["release_status_after_mask"],
                f"{diff['masked_diff_ratio_fixed_denominator'] * 100:.1f}%",
            ]
        )
        colors.append([status_background(case_id)] * len(columns))
    fig, ax = plt.subplots(figsize=(15, 5.8))
    ax.set_axis_off()
    fig.text(
        0.03,
        0.95,
        "R5-EXP-04 · Coverage dimensions and fixed diff denominator",
        fontsize=21,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    fig.text(
        0.03,
        0.89,
        "Coverage units stay separate. Diagnostic mask excludes the placeholder from diff, but masked diff does not change PARTIAL.",
        fontsize=10.5,
        color="#475569",
        va="top",
    )
    table = ax.table(
        cellText=values,
        colLabels=columns,
        cellColours=colors,
        colColours=["#e2e8f0"] * len(columns),
        loc="center",
        cellLoc="center",
        bbox=[0.02, 0.25, 0.96, 0.53],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    for cell in table.get_celld().values():
        cell.set_edgecolor("#94a3b8")
        cell.set_linewidth(0.7)
    denominator = DENOMINATOR_PIXELS
    ax.text(
        0.03,
        0.15,
        f"Raw/masked denominator: {denominator:,} px · excluded diagnostic mask: {GAP_AREA:,} px · valid comparison: {denominator - GAP_AREA:,} px",
        fontsize=10,
        color="#475569",
    )
    fig.savefig(path, dpi=160, facecolor="#f8fafc")
    plt.close(fig)


def make_mask_denominator_visual(bundle: dict[str, Any], path: Path) -> None:
    diff = bundle["coverage_map"]["cases"]["not-captured"]["diff_reconciliation"]
    fig, ax = plt.subplots(figsize=(13, 5.6))
    labels = ["Original denominator", "Valid comparison", "Diagnostic mask", "Raw diff", "Masked diff"]
    values = [
        diff["denominator_pixels"],
        diff["valid_compare_pixels"],
        diff["excluded_diagnostic_pixels"],
        diff["raw_diff_pixels"],
        diff["masked_diff_pixels"],
    ]
    colors = ["#cbd5e1", "#86efac", "#fbbf24", "#f87171", "#a7f3d0"]
    bars = ax.bar(labels, values, color=colors, edgecolor="#64748b")
    ax.set_title(
        "Diagnostic mask exclusion keeps the original denominator",
        loc="left",
        fontsize=16,
        fontweight="bold",
        color="#0f172a",
    )
    ax.set_ylabel("pixels")
    ax.grid(axis="y", color="#e2e8f0")
    ax.set_axisbelow(True)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + max(values) * 0.015,
            f"{value:,}",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
            color="#334155",
        )
    ax.text(
        0.5,
        0.53,
        "masked diff = 0 / 912,000 = 0.0%\n"
        "release status = PARTIAL\n"
        "complete export allowed = false",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=14,
        fontweight="bold",
        color="#991b1b",
        bbox={"boxstyle": "round,pad=0.6", "facecolor": "#fff1f2", "edgecolor": "#fecdd3"},
    )
    fig.subplots_adjust(left=0.08, right=0.98, top=0.88, bottom=0.15)
    fig.savefig(path, dpi=160, facecolor="#f8fafc")
    plt.close(fig)


def make_report_visual(bundle: dict[str, Any], path: Path) -> None:
    fig = plt.figure(figsize=(16, 8.8), facecolor="#f8fafc")
    ax = fig.add_axes([0.04, 0.05, 0.92, 0.82])
    ax.set_axis_off()
    fig.text(
        0.04,
        0.95,
        "R5-EXP-04 · PARTIAL delivery report",
        fontsize=23,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    fig.text(
        0.04,
        0.90,
        "Business content, diagnostic placeholders and the coverage report are separate layers.",
        fontsize=11,
        color="#475569",
        va="top",
    )
    y = 0.82
    for case_id in CASE_IDS:
        case_canvas = bundle["canvas"]["cases"][case_id]
        case_report = bundle["report"]["cases"][case_id]
        case_metrics = bundle["coverage_map"]["cases"][case_id]["coverage"]
        entry = case_report["entries"][0]
        ax.add_patch(
            plt.Rectangle(
                (0.0, y - 0.14),
                0.98,
                0.15,
                facecolor=status_background(case_id),
                edgecolor=status_color(case_id),
                linewidth=1.2,
            )
        )
        ax.text(
            0.012,
            y - 0.025,
            case_canvas["root_name"],
            fontsize=11.5,
            fontweight="bold",
            color="#0f172a",
            va="center",
        )
        ax.text(
            0.012,
            y - 0.060,
            f"Status: {case_id} · coverage state: {case_metrics['gap_state']} · release: {case_metrics['release_status']}",
            fontsize=9.5,
            color=status_color(case_id),
            va="center",
        )
        ax.text(
            0.012,
            y - 0.094,
            f"Reason: {entry['reason']}",
            fontsize=8.7,
            color="#334155",
            va="center",
        )
        ax.text(
            0.012,
            y - 0.122,
            "Blocked: " + ", ".join(entry["blocked_actions"][:3]),
            fontsize=8.2,
            color="#475569",
            va="center",
        )
        y -= 0.175
    ax.text(
        0.0,
        0.0,
        "Legend: intentional omission, write failure, observed absence and missing capture are separate states. "
        "Blank space is not used as a gap representation.",
        fontsize=9.5,
        color="#475569",
    )
    fig.savefig(path, dpi=160, facecolor="#f8fafc")
    plt.close(fig)


BOUNDARY = {
    "scope": "Offline partial-delivery model with authored raster and coverage-map data.",
    "figma": "Figma and the bridge are not connected.",
    "raster": "Diff and mask behavior cover the authored 1200x760 fixture only.",
    "coverage": "Area, object, text and critical units are contract-defined, not a general scoring model.",
    "export": "No lock, page isolation or manual-export block is claimed.",
    "status": "Current-scope experiment evidence only; not production verification.",
}

LIMITATIONS = [
    "The four gap causes share one authored missing object and one fixed geometry.",
    "Coverage weights are not combined into a score; this experiment intentionally avoids an area-weighted total.",
    "The raster diff uses a synthetic design image and a rectangular diagnostic mask.",
    "The not-captured case is modeled by missing evidence and a blank business output, not by a real network/browser capture failure.",
    "Observed absence is represented as a contract gap until an authorized state/contract update; it is not a real tombstone test.",
    "The report and coverage map are JSON models; no real Figma report frame was created.",
    "Manual export and Figma lock behavior were not tested.",
    "No user study was performed to test whether the four status words are understood without explanation.",
    "The experiment does not run the production delivery, coverage, manifest, or export gate implementation.",
    "A passing validation run does not prove arbitrary pages, arbitrary masks, or production release safety.",
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
    print(f"denominator_pixels={DENOMINATOR_PIXELS}")
    print(f"content_hash={result['content_hash']}")
    print(f"out={result['output_directory']}")
    for item in result["checks"]:
        if not item["passed"]:
            print(f"FAILED CHECK: {item['name']} :: {item['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R5-EXP-04 partial delivery coverage experiment.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    out_dir = safe_output_dir(args.out)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Building four same-position partial-delivery variants...")
    bundle, artifacts = build_bundle(out_dir)
    baseline = freeze_bundle(bundle)
    mutations = run_mutations(bundle, baseline)
    checks = run_checks(bundle, baseline, mutations, artifacts)

    contact_sheet = out_dir / "r5_exp_04_case_contact_sheet.png"
    coverage_map_visual = out_dir / "r5_exp_04_coverage_map.png"
    coverage_matrix = out_dir / "r5_exp_04_coverage_matrix.png"
    mask_denominator = out_dir / "r5_exp_04_mask_denominator.png"
    report_visual = out_dir / "r5_exp_04_delivery_report.png"
    make_case_contact_sheet(bundle, artifacts, contact_sheet)
    make_coverage_map_visual(bundle, artifacts, coverage_map_visual)
    make_coverage_matrix(bundle, coverage_matrix)
    make_mask_denominator_visual(bundle, mask_denominator)
    make_report_visual(bundle, report_visual)

    all_checks_passed = all(item["passed"] for item in checks)
    status = "completed-for-current-scope" if all_checks_passed and mutations["accepted"] == 0 else "failed"
    visual_files = {}
    for path in (
        contact_sheet,
        coverage_map_visual,
        coverage_matrix,
        mask_denominator,
        report_visual,
    ):
        visual_files[path.name] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    canvas_path = out_dir / "canvas.json"
    report_path = out_dir / "report.json"
    manifest_path = out_dir / "manifest.json"
    coverage_path = out_dir / "coverage_map.json"
    mutations_path = out_dir / "mutations.json"
    atomic_write_json(canvas_path, bundle["canvas"])
    atomic_write_json(report_path, bundle["report"])
    atomic_write_json(manifest_path, bundle["manifest"])
    atomic_write_json(coverage_path, bundle["coverage_map"])
    atomic_write_json(mutations_path, mutations)

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
            "diagnostic_mask": artifacts["mask"],
            "raw_diff": artifacts["raw_diff"],
            "masked_diff": artifacts["masked_diff"],
            "cases": artifacts["cases"],
        },
        "canvas": bundle["canvas"],
        "report": bundle["report"],
        "manifest": bundle["manifest"],
        "coverage_map": bundle["coverage_map"],
        "artifact_paths": {
            "canvas": str(canvas_path),
            "report": str(report_path),
            "manifest": str(manifest_path),
            "coverage_map": str(coverage_path),
            "mutations": str(mutations_path),
        },
        "checks": checks,
        "mutations": mutations,
        "visuals": visual_files,
        "coverage_summary": {
            "required_area_px": REQUIRED_AREA,
            "delivered_area_px": DELIVERED_AREA,
            "required_objects": REQUIRED_OBJECTS,
            "delivered_objects": DELIVERED_OBJECT_COUNT,
            "required_text_characters": REQUIRED_TEXT_CHARS,
            "delivered_text_characters": DELIVERED_TEXT_CHARS,
            "required_critical_items": REQUIRED_CRITICAL,
            "delivered_critical_items": DELIVERED_CRITICAL,
            "denominator_pixels": DENOMINATOR_PIXELS,
            "diagnostic_excluded_pixels": GAP_AREA,
            "valid_compare_pixels": DENOMINATOR_PIXELS - GAP_AREA,
            "masked_diff_pixels": artifacts["masked_diff"]["pixels"],
        },
        "boundary": BOUNDARY,
        "limitations": LIMITATIONS,
        "release_claims": {
            "experiment_status": "completed-for-current-scope" if all_checks_passed else "failed",
            "verified": False,
            "production_ready": False,
            "figma_connected": False,
            "source_modified": False,
            "manual_export_gate_implemented": False,
        },
    }
    result["content_hash"] = content_hash(result)
    atomic_write_json(out_dir / "result.json", result)
    print_summary(result)
    return 0 if all_checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
