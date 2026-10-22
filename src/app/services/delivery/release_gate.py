"""Release decisions and hard export assertions for PARTIAL delivery."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from src.app.services.contracts import (
    DIMENSIONS,
    CheckStatus,
    Dimension,
    ReleaseDecision,
    ReleaseStatus,
    assert_release_invariants,
    evaluate_release,
)
from src.app.services.delivery.partial_report import PartialReport


@dataclass(frozen=True, slots=True)
class ReleaseGateProfile:
    profile_id: str
    preflight_passed: bool
    user_allowed_partial: bool
    noncritical_gap_isolatable: bool
    required_dimensions: tuple[Dimension, ...] = DIMENSIONS
    reference_only: bool = False
    production_prerequisites: Mapping[str, bool] | None = None


class ExportNotAllowed(PermissionError):
    def __init__(self, decision: ReleaseDecision) -> None:
        self.decision = decision
        super().__init__(
            f"complete export is blocked: {decision.status.value} "
            f"({decision.reason})"
        )


def release_decision(
    report: PartialReport,
    profile: ReleaseGateProfile | str,
) -> ReleaseDecision:
    gate = _coerce_profile(profile)
    decision = evaluate_release(
        checks=report.checks,
        coverage=_page_coverage_from_report(report),
        required_dimensions=gate.required_dimensions,
        preflight_passed=gate.preflight_passed,
        user_allowed_partial=gate.user_allowed_partial,
        noncritical_gap_isolatable=gate.noncritical_gap_isolatable,
        reference_only=gate.reference_only,
        production_prerequisites=gate.production_prerequisites,
    )
    if report.status == "blocked":
        blocked_status = (
            ReleaseStatus.BLOCKED_CRITICAL
            if report.critical_blockers
            else ReleaseStatus.BLOCKED_UNKNOWN
        )
        decision = replace(
            decision,
            status=blocked_status,
            reason=report.reason,
            complete_export_allowed=False,
            allowed_export_mode="none",
            pilot_status="pilot-blocked",
        )
    elif report.status == "partial":
        decision = replace(
            decision,
            status=ReleaseStatus.DELIVERABLE_PARTIAL
            if decision.status is not ReleaseStatus.DELIVERABLE_PARTIAL
            else decision.status,
            complete_export_allowed=False,
            allowed_export_mode="explicit-partial",
            pilot_status="pilot-allowed-provisional",
        )
    elif report.status == "complete":
        if decision.status is not ReleaseStatus.DELIVERABLE_COMPLETE:
            raise ValueError("complete partial report did not produce a complete release")
    assert_release_invariants(decision)
    return decision


def assert_export_allowed(
    decision: ReleaseDecision,
    *,
    allow_partial: bool = False,
) -> None:
    assert_release_invariants(decision)
    if decision.complete_export_allowed and decision.allowed_export_mode == "complete":
        return
    if (
        allow_partial
        and decision.status is ReleaseStatus.DELIVERABLE_PARTIAL
        and decision.allowed_export_mode == "explicit-partial"
    ):
        return
    raise ExportNotAllowed(decision)


def _coerce_profile(profile: ReleaseGateProfile | str) -> ReleaseGateProfile:
    if isinstance(profile, ReleaseGateProfile):
        return profile
    if not str(profile or "").strip():
        raise ValueError("release profile is required")
    return ReleaseGateProfile(
        profile_id=str(profile),
        preflight_passed=True,
        user_allowed_partial=True,
        noncritical_gap_isolatable=True,
    )


def _page_coverage_from_report(report: PartialReport):
    from src.app.services.contracts import (
        CoverageDimension,
        CoverageStatus,
        PageCoverage,
    )

    values = {}
    for key in ("area", "objects", "text", "critical"):
        row = report.coverage[key]
        values[key] = CoverageDimension(
            denominator=float(row["denominator"]),
            covered=float(row["covered"]),
            missing=float(row["missing"]),
            unknown=float(row["unknown"]),
            ratio=float(row["ratio"]),
            status=CoverageStatus(str(row["status"])),
            unit=str(row["unit"]),
        )
    return PageCoverage(
        area=values["area"],
        objects=values["objects"],
        text=values["text"],
        critical=values["critical"],
        denominator_unchanged=report.denominator_unchanged,
    )
