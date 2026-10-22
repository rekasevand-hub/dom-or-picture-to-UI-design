"""Pure replay and resume contracts.

These functions describe replay eligibility and guarantees. They do not read
files, fetch URLs or connect to Figma.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.app.services.contracts.enums import (
    EvidenceAvailability,
    ReplayMode,
    ReplayStatus,
)
from src.app.services.contracts.models import ReplayResult


@dataclass(frozen=True, slots=True)
class ReplayInput:
    evidence_available: bool
    permission_granted: bool
    local_asset_present: bool
    local_hash_matches: bool
    environment_changed: bool
    decision_trace_hash: str
    materialized_hash: str


def audit_replay(value: ReplayInput) -> ReplayResult:
    if not value.permission_granted:
        return ReplayResult(
            mode=ReplayMode.AUDIT_REPLAY,
            status=ReplayStatus.SUMMARY_ONLY,
            exact_replay=False,
            pixel_identical_guaranteed=False,
            evidence_status=EvidenceAvailability.ACCESS_DENIED,
            output_hash=value.decision_trace_hash,
            reason="Evidence permission is revoked; only approved summary metadata is available.",
        )
    if not value.evidence_available:
        return ReplayResult(
            mode=ReplayMode.AUDIT_REPLAY,
            status=ReplayStatus.SUMMARY_ONLY,
            exact_replay=False,
            pixel_identical_guaranteed=False,
            evidence_status=EvidenceAvailability.EVIDENCE_UNAVAILABLE,
            output_hash=value.decision_trace_hash,
            reason="The historical evidence bytes are unavailable; a hash cannot replace them.",
        )
    return ReplayResult(
        mode=ReplayMode.AUDIT_REPLAY,
        status=ReplayStatus.COMPLETED,
        exact_replay=True,
        pixel_identical_guaranteed=False,
        evidence_status=EvidenceAvailability.AVAILABLE,
        output_hash=value.decision_trace_hash,
        reason="The locked decision chain and evidence can be audited exactly.",
    )


def materialize_replay(value: ReplayInput) -> ReplayResult:
    if not value.permission_granted:
        return ReplayResult(
            mode=ReplayMode.MATERIALIZE_REPLAY,
            status=ReplayStatus.BLOCKED_PERMISSION,
            exact_replay=False,
            pixel_identical_guaranteed=False,
            evidence_status=EvidenceAvailability.ACCESS_DENIED,
            reason="Materialization permission is revoked.",
        )
    if not value.evidence_available:
        return ReplayResult(
            mode=ReplayMode.MATERIALIZE_REPLAY,
            status=ReplayStatus.BLOCKED_EVIDENCE_UNAVAILABLE,
            exact_replay=False,
            pixel_identical_guaranteed=False,
            evidence_status=EvidenceAvailability.EVIDENCE_UNAVAILABLE,
            reason="Materialization requires the locked evidence bytes.",
        )
    if not value.local_asset_present or not value.local_hash_matches:
        return ReplayResult(
            mode=ReplayMode.MATERIALIZE_REPLAY,
            status=ReplayStatus.BLOCKED_ASSET_MISSING,
            exact_replay=False,
            pixel_identical_guaranteed=False,
            evidence_status=EvidenceAvailability.AVAILABLE,
            reason="Local asset bytes are missing or do not match the locked hash.",
        )
    return ReplayResult(
        mode=ReplayMode.MATERIALIZE_REPLAY,
        status=(
            ReplayStatus.MATERIALIZED_REVALIDATION_REQUIRED
            if value.environment_changed
            else ReplayStatus.MATERIALIZED
        ),
        exact_replay=False,
        pixel_identical_guaranteed=False,
        evidence_status=EvidenceAvailability.AVAILABLE,
        output_hash=value.materialized_hash,
        reason=(
            "The output changed environment fingerprint and requires revalidation."
            if value.environment_changed
            else "Locked evidence, policy and plan reproduced the materialized output."
        ),
    )


def recapture_reconcile(
    *,
    old_capture_id: str,
    new_capture_id: str,
    old_revision: int,
    new_revision: int,
    permission_granted: bool,
    recaptured_hash: str,
) -> ReplayResult:
    if not permission_granted:
        return ReplayResult(
            mode=ReplayMode.RECAPTURE_RECONCILE,
            status=ReplayStatus.BLOCKED_PERMISSION,
            exact_replay=False,
            pixel_identical_guaranteed=False,
            evidence_status=EvidenceAvailability.ACCESS_DENIED,
            old_capture_id=old_capture_id,
            reason="Reauthorization is required before recapture.",
        )
    if not new_capture_id or new_capture_id == old_capture_id:
        raise ValueError("Recapture requires a new capture id")
    if new_revision <= old_revision:
        raise ValueError("Recapture requires a newer capture revision")
    return ReplayResult(
        mode=ReplayMode.RECAPTURE_RECONCILE,
        status=ReplayStatus.NEW_CAPTURE_CREATED,
        exact_replay=False,
        pixel_identical_guaranteed=False,
        evidence_status=EvidenceAvailability.AVAILABLE,
        output_hash=recaptured_hash,
        old_capture_id=old_capture_id,
        new_capture_id=new_capture_id,
        reason="A new capture and revision were created; this is not historical replay.",
    )


def resume_after_send(*, side_effect_count: int, duplicate_create_count: int) -> ReplayResult:
    if side_effect_count < 0 or duplicate_create_count < 0:
        raise ValueError("Resume counts must be nonnegative")
    if duplicate_create_count:
        return ReplayResult(
            mode=ReplayMode.RESUME,
            status=ReplayStatus.BLOCKED_DUPLICATE_SIDE_EFFECT,
            exact_replay=False,
            pixel_identical_guaranteed=False,
            reason="Resume produced duplicate side effects and requires manual reconciliation.",
        )
    return ReplayResult(
        mode=ReplayMode.RESUME,
        status=ReplayStatus.COMMITTED_AFTER_RECONCILE,
        exact_replay=False,
        pixel_identical_guaranteed=False,
        reason="Remote state was reconciled without resend.",
    )
