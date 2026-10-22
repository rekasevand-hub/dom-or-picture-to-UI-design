"""Coverage arithmetic with explicit units and fixed denominators."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from src.app.services.contracts.enums import CoverageStatus
from src.app.services.contracts.models import (
    CoverageDimension,
    CoverageRegion,
    PageCoverage,
    Rect,
)


@dataclass(frozen=True, slots=True)
class CoverageInput:
    denominator: float
    covered: float
    missing: float = 0
    unknown: float = 0
    unit: str = "count"
    required: bool = True


def _rect_value(rect: Rect | Mapping[str, float], key: str) -> float:
    if isinstance(rect, Rect):
        return float(getattr(rect, key))
    return float(rect[key])


def rect_union_area(rectangles: Iterable[Rect | Mapping[str, float]]) -> float:
    """Return the exact area of the union of axis-aligned rectangles."""
    items = list(rectangles)
    if not items:
        return 0.0
    xs = sorted(
        {
            edge
            for item in items
            for edge in (
                _rect_value(item, "x"),
                _rect_value(item, "x") + _rect_value(item, "width"),
            )
        }
    )
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals: list[tuple[float, float]] = []
        for item in items:
            item_left = _rect_value(item, "x")
            item_right = item_left + _rect_value(item, "width")
            if item_left <= left and item_right >= right:
                top = _rect_value(item, "y")
                intervals.append((top, top + _rect_value(item, "height")))
        if not intervals:
            continue
        intervals.sort()
        merged: list[list[float]] = []
        for start, end in intervals:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        area += (right - left) * sum(end - start for start, end in merged)
    return area


def coverage_status(
    denominator: float,
    covered: float,
    missing: float,
    unknown: float,
    *,
    required: bool = True,
) -> CoverageStatus:
    if not required:
        return CoverageStatus.NOT_REQUIRED
    if unknown > 0:
        return CoverageStatus.UNKNOWN
    if missing > 0 or covered < denominator:
        return CoverageStatus.PARTIAL
    return CoverageStatus.PASS


def coverage_dimension(value: CoverageInput) -> CoverageDimension:
    if value.denominator < 0:
        raise ValueError("Coverage denominator must be nonnegative")
    if min(value.covered, value.missing, value.unknown) < 0:
        raise ValueError("Coverage counts must be nonnegative")
    accounted = value.covered + value.missing + value.unknown
    if accounted > value.denominator + 1e-9:
        raise ValueError(
            "covered + missing + unknown cannot exceed the coverage denominator"
        )
    ratio = 0.0 if value.denominator == 0 else value.covered / value.denominator
    return CoverageDimension(
        denominator=value.denominator,
        covered=value.covered,
        missing=value.missing,
        unknown=value.unknown,
        ratio=round(ratio, 8),
        status=coverage_status(
            value.denominator,
            value.covered,
            value.missing,
            value.unknown,
            required=value.required,
        ),
        unit=value.unit,
    )


def build_page_coverage(
    *,
    area: CoverageInput,
    objects: CoverageInput,
    text: CoverageInput,
    critical: CoverageInput,
    denominator_unchanged: bool = True,
) -> PageCoverage:
    return PageCoverage(
        area=coverage_dimension(area),
        objects=coverage_dimension(objects),
        text=coverage_dimension(text),
        critical=coverage_dimension(critical),
        denominator_unchanged=bool(denominator_unchanged),
    )


def fixed_denominator_diff(
    *,
    denominator_pixels: int,
    excluded_diagnostic_pixels: int,
    valid_compare_pixels: int,
    masked_diff_pixels: int,
) -> dict[str, float | bool]:
    """Reconcile a masked diff without shrinking the original denominator."""
    if denominator_pixels <= 0:
        raise ValueError("denominator_pixels must be positive")
    if min(excluded_diagnostic_pixels, valid_compare_pixels, masked_diff_pixels) < 0:
        raise ValueError("pixel counts must be nonnegative")
    if valid_compare_pixels + excluded_diagnostic_pixels != denominator_pixels:
        raise ValueError("valid comparison plus excluded mask must equal the denominator")
    if masked_diff_pixels > valid_compare_pixels:
        raise ValueError("masked diff cannot exceed the valid comparison area")
    return {
        "denominator_pixels": denominator_pixels,
        "denominator_after_mask": denominator_pixels,
        "masked_diff_ratio": masked_diff_pixels / denominator_pixels,
        "denominator_unchanged": True,
    }


def coverage_region_summary(
    regions: Iterable[CoverageRegion],
) -> dict[str, float | int | dict[str, int]]:
    """Summarize region states without collapsing unknown into absence."""
    items = tuple(regions)
    counts: dict[str, int] = {}
    area_by_state: dict[str, float] = {}
    for region in items:
        state = region.coverage_state.value
        counts[state] = counts.get(state, 0) + 1
        area_by_state[state] = rect_union_area(
            [
                existing.source_rect
                for existing in items
                if existing.coverage_state is region.coverage_state
            ]
        )
    return {
        "region_count": len(items),
        "state_counts": counts,
        "area_by_state": area_by_state,
        "union_area": rect_union_area([item.source_rect for item in items]),
        "not_captured_count": counts.get("not-captured", 0),
        "unknown_count": counts.get("unknown", 0),
    }
