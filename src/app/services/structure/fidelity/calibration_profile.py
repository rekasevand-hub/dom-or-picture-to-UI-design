"""Residual profile used to select image-to-Figma calibration strategies.

The profile is deliberately diagnostic-only.  It reuses the native-text
measurement primitives but never enables the frozen acceptance gate, so a
profile cannot turn a failed run into a passing one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.app.services.evidence.native_text_quality import build_native_text_quality

PROFILE_SCHEMA_VERSION = "image-calibration-profile/1.0"
RESIDUAL_KINDS = ("position", "size", "coverage", "edgeF1")
REGION_CATEGORIES = (
    "page",
    "banner",
    "header",
    "sidebar",
    "form",
    "table",
    "toolbar",
    "search",
)


def _region_category(role: Any) -> str:
    value = str(role or "").casefold()
    if "table" in value:
        return "table"
    if "toolbar" in value:
        return "toolbar"
    if "search" in value:
        return "search"
    if "form" in value:
        return "form"
    if "sidebar" in value:
        return "sidebar"
    if "banner" in value:
        return "banner"
    if "header" in value or "nav" in value:
        return "header"
    return "page"


def _element_bbox(element: Mapping[str, Any]) -> list[int] | None:
    try:
        x = int(round(float(element.get("x") or 0)))
        y = int(round(float(element.get("y") or 0)))
        width = int(round(float(element.get("width") or 0)))
        height = int(round(float(element.get("height") or 0)))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return [x, y, width, height]


def _contains(outer: Sequence[int], inner: Sequence[int]) -> bool:
    if len(outer) != 4 or len(inner) != 4:
        return False
    outer_x, outer_y, outer_w, outer_h = outer
    inner_x, inner_y, inner_w, inner_h = inner
    return (
        inner_x >= outer_x
        and inner_y >= outer_y
        and inner_x + inner_w <= outer_x + outer_w
        and inner_y + inner_h <= outer_y + outer_h
    )


def _element_kind(element: Mapping[str, Any]) -> str:
    value = str(element.get("type") or "").casefold()
    if value in {
        "button",
        "checkbox",
        "icon-button",
        "input",
        "navigation",
        "pagination",
        "radio",
        "select",
        "textarea",
        "toggle",
    }:
        return "control"
    if value == "text":
        return "text"
    return "other"


def _empty_counts() -> dict[str, int]:
    return {kind: 0 for kind in RESIDUAL_KINDS}


def build_calibration_residual_profile(
    design: Mapping[str, Any],
    readback_tree: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
    regions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Measure current native-text residuals without enabling acceptance gates."""
    quality = build_native_text_quality(
        design,
        readback_tree,
        reference_path,
        rendered_path,
        [],
        gate_policy=None,
        register_unmeasured_owners=True,
    )
    owners = [
        owner for owner in quality.get("owners") or [] if isinstance(owner, Mapping)
    ]
    elements_by_ref = {
        str(element.get("contentRef")): element
        for element in design.get("elements") or []
        if isinstance(element, Mapping) and element.get("contentRef")
    }
    region_rows = [
        {
            "role": _region_category(region.get("role") or region.get("id")),
            "bbox": list(region.get("bbox") or []),
        }
        for region in regions or []
        if isinstance(region, Mapping) and len(region.get("bbox") or []) == 4
    ]
    present_regions = {row["role"] for row in region_rows}
    present_regions.add("page")

    residuals = _empty_counts()
    by_region: dict[str, dict[str, int]] = {
        category: _empty_counts() for category in REGION_CATEGORIES
    }
    by_type: dict[str, dict[str, int]] = {
        "control": _empty_counts(),
        "text": _empty_counts(),
        "other": _empty_counts(),
    }
    measured_owner_count = 0
    failed_owner_count = 0
    for owner in owners:
        checks = owner.get("checks")
        if not isinstance(checks, Mapping):
            continue
        measured_owner_count += 1
        failed = [kind for kind in RESIDUAL_KINDS if checks.get(kind) is False]
        if not failed:
            continue
        failed_owner_count += 1
        element = elements_by_ref.get(str(owner.get("contentRef")))
        bbox = _element_bbox(element or {})
        category = "page"
        if bbox is not None:
            containing = [row for row in region_rows if _contains(row["bbox"], bbox)]
            if containing:
                category = min(
                    containing,
                    key=lambda row: int(row["bbox"][2]) * int(row["bbox"][3]),
                )["role"]
        element_kind = _element_kind(element or {})
        for kind in failed:
            residuals[kind] += 1
            by_region[category][kind] += 1
            by_type[element_kind][kind] += 1

    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "ownerCount": len(owners),
        "measuredOwnerCount": measured_owner_count,
        "failedOwnerCount": failed_owner_count,
        "residuals": residuals,
        "byRegion": by_region,
        "byType": by_type,
        "regions": sorted(present_regions),
    }
