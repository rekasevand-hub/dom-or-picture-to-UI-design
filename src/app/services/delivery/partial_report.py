"""User-visible PARTIAL report and machine manifest projection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from src.app.services.contracts import (
    AcceptanceCheck,
    CheckStatus,
    CoverageRegion,
    CoverageState,
    PageCoverage,
    canonical_hash,
    coverage_region_summary,
)


BLOCKING_CHECK_STATUSES = {
    CheckStatus.FAIL,
    CheckStatus.UNKNOWN,
    CheckStatus.NO_GROUND_TRUTH,
    CheckStatus.NOT_SAMPLED,
}
BLOCKING_REGION_STATES = {
    CoverageState.UNKNOWN,
    CoverageState.NOT_CAPTURED,
}


@dataclass(frozen=True, slots=True)
class PartialReport:
    profile: str
    status: str
    reason: str
    root_name: str
    report_name: str
    coverage: dict[str, dict[str, Any]]
    checks: tuple[AcceptanceCheck, ...]
    regions: tuple[CoverageRegion, ...]
    coverage_state_counts: dict[str, int]
    critical_blockers: tuple[str, ...]
    denominator_unchanged: bool
    outside_business_flow: bool
    manifest: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "partial-report/1.0",
            "profile": self.profile,
            "status": self.status,
            "reason": self.reason,
            "root_name": self.root_name,
            "report_name": self.report_name,
            "coverage": self.coverage,
            "checks": [item.to_dict() for item in self.checks],
            "regions": [item.to_dict() for item in self.regions],
            "coverage_state_counts": dict(self.coverage_state_counts),
            "critical_blockers": list(self.critical_blockers),
            "denominator_unchanged": self.denominator_unchanged,
            "outside_business_flow": self.outside_business_flow,
            "manifest": dict(self.manifest),
        }


def build_partial_report(
    page_coverage: PageCoverage,
    checks: Iterable[AcceptanceCheck],
    *,
    regions: Iterable[CoverageRegion] = (),
    profile: str = "fixed-pilot/1.0",
) -> PartialReport:
    if not str(profile or "").strip():
        raise ValueError("partial reports require a non-empty profile")
    check_items = tuple(checks)
    region_items = tuple(regions)
    region_summary = coverage_region_summary(region_items)
    critical_blockers = tuple(
        item.check_id
        for item in check_items
        if item.required
        and (
            (item.critical and item.status in BLOCKING_CHECK_STATUSES)
            or (
                item.critical
                and item.status is CheckStatus.PARTIAL
                and not item.partial_allowed
            )
        )
    )
    blocking_regions = tuple(
        region.region_id
        for region in region_items
        if region.coverage_state in BLOCKING_REGION_STATES
    )
    all_required_pass = all(
        item.status is CheckStatus.PASS
        for item in check_items
        if item.required
    )
    coverage = {
        key: getattr(page_coverage, key).to_dict()
        for key in ("area", "objects", "text", "critical")
    }
    if (
        critical_blockers
        or blocking_regions
        or not page_coverage.denominator_unchanged
    ):
        status = "blocked"
        reason = _blocked_reason(critical_blockers, blocking_regions, page_coverage)
    elif all_required_pass and page_coverage.complete:
        status = "complete"
        reason = "All required checks passed with complete grounded coverage."
    else:
        status = "partial"
        reason = (
            "The original contract has unresolved or noncritical gaps; "
            "complete export remains blocked."
        )
    root_prefix = {
        "complete": "[COMPLETE]",
        "partial": "[PARTIAL]",
        "blocked": "[BLOCKED]",
    }[status]
    root_name = f"{root_prefix} Business Content"
    report_name = "Coverage / Gaps Report"
    manifest = {
        "schema": "partial-delivery-manifest/1.0",
        "profile": str(profile),
        "status": status,
        "reason": reason,
        "root_name": root_name,
        "report_name": report_name,
        "outside_business_flow": True,
        "coverage": coverage,
        "coverage_state_counts": region_summary["state_counts"],
        "coverage_region_summary": region_summary,
        "critical_blockers": list(critical_blockers),
        "blocking_regions": list(blocking_regions),
        "denominator_unchanged": page_coverage.denominator_unchanged,
        "complete_export_allowed": False,
        "blocked_actions": _blocked_actions(status),
    }
    manifest["content_hash"] = canonical_hash(manifest)
    return PartialReport(
        profile=str(profile),
        status=status,
        reason=reason,
        root_name=root_name,
        report_name=report_name,
        coverage=coverage,
        checks=check_items,
        regions=region_items,
        coverage_state_counts=dict(region_summary["state_counts"]),
        critical_blockers=critical_blockers,
        denominator_unchanged=page_coverage.denominator_unchanged,
        outside_business_flow=True,
        manifest=manifest,
    )


def _blocked_reason(
    critical_blockers: tuple[str, ...],
    blocking_regions: tuple[str, ...],
    coverage: PageCoverage,
) -> str:
    if any("not-captured" in region_id for region_id in blocking_regions) or (
        coverage.critical.unknown > 0
    ):
        return "The report contains not-captured or unknown coverage."
    if critical_blockers:
        return "A critical required check blocks release: " + ", ".join(
            critical_blockers
        )
    if not coverage.denominator_unchanged:
        return "The contract denominator changed after masking."
    return "The original contract remains blocked."


def _blocked_actions(status: str) -> list[str]:
    if status == "complete":
        return []
    return [
        "cannot-claim-complete-delivery",
        "cannot-export-as-complete",
    ]
