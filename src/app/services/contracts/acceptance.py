"""Four-dimensional acceptance and page-level release decisions."""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping

from src.app.services.contracts.enums import (
    Applicability,
    CheckStatus,
    Dimension,
    ReleaseStatus,
)
from src.app.services.contracts.models import (
    AcceptanceCheck,
    PageCoverage,
    ReleaseDecision,
)

DIMENSIONS = (
    Dimension.VISUAL,
    Dimension.STRUCTURE,
    Dimension.EDIT,
    Dimension.ASSET,
)

PRODUCTION_PREREQUISITES = (
    "fault_recovery",
    "idempotency_and_reconciliation",
    "permission_and_concurrency_safety",
    "persistent_ir_and_migration",
    "environment_coverage",
    "monitoring",
)


def dimension_status(
    checks: Iterable[AcceptanceCheck],
    dimension: Dimension,
    *,
    required: bool,
) -> str:
    if not required:
        return "not-required"
    statuses = {
        item.status
        for item in checks
        if item.dimension is dimension
        and item.required
        and item.applicability is Applicability.REQUIRED
    }
    if CheckStatus.FAIL in statuses:
        return "fail"
    if statuses & {
        CheckStatus.UNKNOWN,
        CheckStatus.NO_GROUND_TRUTH,
        CheckStatus.NOT_SAMPLED,
    }:
        return "unknown"
    if CheckStatus.PARTIAL in statuses:
        return "partial"
    if statuses == {CheckStatus.PASS}:
        return "pass"
    return "unknown"


def _critical_blockers(checks: Iterable[AcceptanceCheck]) -> tuple[AcceptanceCheck, ...]:
    blockers = []
    for item in checks:
        if not item.required or not item.critical:
            continue
        if item.status in {
            CheckStatus.FAIL,
            CheckStatus.UNKNOWN,
            CheckStatus.NO_GROUND_TRUTH,
            CheckStatus.NOT_SAMPLED,
        }:
            blockers.append(item)
        elif item.status is CheckStatus.PARTIAL and not item.partial_allowed:
            blockers.append(item)
    return tuple(blockers)


def evaluate_release(
    *,
    checks: Iterable[AcceptanceCheck],
    coverage: PageCoverage,
    required_dimensions: Iterable[Dimension] = DIMENSIONS,
    preflight_passed: bool,
    user_allowed_partial: bool,
    noncritical_gap_isolatable: bool,
    reference_only: bool = False,
    production_prerequisites: Mapping[str, bool] | None = None,
) -> ReleaseDecision:
    checks = tuple(checks)
    required = set(required_dimensions)
    dimensions = {
        dimension.value: dimension_status(
            checks,
            dimension,
            required=dimension in required,
        )
        for dimension in DIMENSIONS
    }
    blockers = _critical_blockers(checks)
    blocker_statuses = {item.status for item in blockers}

    if not preflight_passed:
        status = ReleaseStatus.BLOCKED_PREFLIGHT
        reason = "Preflight gate is not satisfied."
    elif blockers:
        if CheckStatus.FAIL in blocker_statuses:
            status = ReleaseStatus.BLOCKED_CRITICAL
            reason = "A critical required check failed."
        elif CheckStatus.NO_GROUND_TRUTH in blocker_statuses:
            status = ReleaseStatus.BLOCKED_NO_GROUND_TRUTH
            reason = "A critical required check has no ground truth."
        elif CheckStatus.NOT_SAMPLED in blocker_statuses:
            status = ReleaseStatus.BLOCKED_COVERAGE
            reason = "A critical required check was not sampled."
        elif CheckStatus.PARTIAL in blocker_statuses:
            status = ReleaseStatus.BLOCKED_PARTIAL_NOT_ALLOWED
            reason = "A critical item is partial without explicit permission."
        else:
            status = ReleaseStatus.BLOCKED_UNKNOWN
            reason = "A critical required check is unknown."
    elif reference_only:
        if dimensions[Dimension.VISUAL.value] == "pass":
            status = ReleaseStatus.REFERENCE_ONLY
            reason = "The visual reference is usable; editable delivery is outside this contract."
        else:
            status = ReleaseStatus.BLOCKED_DIMENSION
            reason = "Reference-only visual evidence is incomplete."
    else:
        all_required_pass = all(
            item.status is CheckStatus.PASS
            for item in checks
            if item.required and item.applicability is Applicability.REQUIRED
        )
        required_statuses = {
            dimensions[dimension.value]
            for dimension in required
        }
        if all_required_pass and coverage.complete:
            status = ReleaseStatus.DELIVERABLE_COMPLETE
            reason = "All required checks passed with complete grounded coverage."
        elif (
            user_allowed_partial
            and noncritical_gap_isolatable
            and (
                not all_required_pass
                or not coverage.complete
                or required_statuses - {"pass"}
            )
        ):
            status = ReleaseStatus.DELIVERABLE_PARTIAL
            reason = "Only isolated noncritical gaps remain in the original contract."
        elif "unknown" in required_statuses:
            status = ReleaseStatus.BLOCKED_UNKNOWN
            reason = "A required dimension is unknown."
        elif not user_allowed_partial and not all_required_pass:
            status = ReleaseStatus.BLOCKED_PARTIAL_NOT_ALLOWED
            reason = "A noncritical gap exists but partial delivery is not allowed."
        elif not coverage.complete:
            status = ReleaseStatus.BLOCKED_COVERAGE
            reason = "Required coverage is incomplete."
        else:
            status = ReleaseStatus.BLOCKED_DIMENSION
            reason = "A required dimension is fail or partial."

    production = {
        key: False
        for key in PRODUCTION_PREREQUISITES
    }
    if production_prerequisites:
        production.update(
            {key: bool(value) for key, value in production_prerequisites.items() if key in production}
        )
    production_eligible = (
        status is ReleaseStatus.DELIVERABLE_COMPLETE
        and all(production.values())
    )
    pilot_allowed = status in {
        ReleaseStatus.DELIVERABLE_COMPLETE,
        ReleaseStatus.DELIVERABLE_PARTIAL,
        ReleaseStatus.REFERENCE_ONLY,
    }
    allowed_export_mode = {
        ReleaseStatus.DELIVERABLE_COMPLETE: "complete",
        ReleaseStatus.DELIVERABLE_PARTIAL: "explicit-partial",
        ReleaseStatus.REFERENCE_ONLY: "reference-only",
    }.get(status, "none")
    return ReleaseDecision(
        status=status,
        reason=reason,
        dimensions=dimensions,
        critical_blockers=tuple(item.check_id for item in blockers),
        complete_export_allowed=status is ReleaseStatus.DELIVERABLE_COMPLETE,
        allowed_export_mode=allowed_export_mode,
        pilot_status=(
            "pilot-allowed-provisional"
            if pilot_allowed
            else "pilot-blocked"
        ),
        production_status=(
            "production-eligible-review"
            if production_eligible
            else "production-not-eligible"
        ),
    )


def dimension_counts(checks: Iterable[AcceptanceCheck]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for dimension in DIMENSIONS:
        counter = Counter(
            item.status.value
            for item in checks
            if item.dimension is dimension and item.required
        )
        result[dimension.value] = dict(counter)
    return result


def assert_release_invariants(decision: ReleaseDecision) -> None:
    """Reject release objects whose export flags contradict their status."""
    if (
        decision.complete_export_allowed
        and decision.status is not ReleaseStatus.DELIVERABLE_COMPLETE
    ):
        raise ValueError("complete export requires deliverable-complete status")
    if (
        decision.allowed_export_mode == "complete"
        and not decision.complete_export_allowed
    ):
        raise ValueError("complete export mode requires complete_export_allowed")
    if (
        decision.allowed_export_mode == "explicit-partial"
        and decision.status is not ReleaseStatus.DELIVERABLE_PARTIAL
    ):
        raise ValueError("explicit-partial mode requires deliverable-partial status")
    if decision.allowed_export_mode == "none" and decision.complete_export_allowed:
        raise ValueError("complete export cannot use export mode none")
