"""Versioned enums shared by the v2 delivery contracts."""
from __future__ import annotations

from enum import Enum


class FieldAuthority(str, Enum):
    DOM = "dom"
    SCREENSHOT = "screenshot"
    DOM_AND_SCREENSHOT = "dom+screenshot"
    NONE = "none"


class FieldDecisionStatus(str, Enum):
    SELECTED = "selected"
    OBSERVED = "observed"
    CANDIDATE = "candidate"
    DEFERRED = "deferred"
    EXTERNAL_CONFLICT = "external-conflict"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    SKIPPED = "skipped"
    AUTHORITY_REQUIRED = "authority-required"
    RETAINED_UNVERIFIED = "retained-unverified"
    CARRIED_FORWARD_NOT_SEEN = "carried-forward-not-seen"
    DELETE_PENDING = "delete-pending"
    TOMBSTONE = "tombstone"
    NOT_APPLICABLE = "not-applicable"


class Dimension(str, Enum):
    VISUAL = "visual"
    STRUCTURE = "structure"
    EDIT = "edit"
    ASSET = "asset"


class CheckStatus(str, Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NO_GROUND_TRUTH = "no-ground-truth"
    NOT_SAMPLED = "not-sampled"
    NOT_REQUIRED = "not-required"


class CoverageState(str, Enum):
    DELIVERED = "delivered"
    INTENTIONAL_OMISSION = "intentional-omission"
    WRITE_FAILED = "write-failed"
    OBSERVED_ABSENT = "observed-absent"
    NOT_CAPTURED = "not-captured"
    UNKNOWN = "unknown"
    NOT_REQUIRED = "not-required"


class CoverageStatus(str, Enum):
    PASS = "pass"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    NOT_REQUIRED = "not-required"


class ReleaseStatus(str, Enum):
    DELIVERABLE_COMPLETE = "deliverable-complete"
    DELIVERABLE_PARTIAL = "deliverable-partial"
    REFERENCE_ONLY = "reference-only"
    BLOCKED_PREFLIGHT = "blocked-preflight"
    BLOCKED_CRITICAL = "blocked-critical"
    BLOCKED_UNKNOWN = "blocked-unknown"
    BLOCKED_NO_GROUND_TRUTH = "blocked-no-ground-truth"
    BLOCKED_PARTIAL_NOT_ALLOWED = "blocked-partial-not-allowed"
    BLOCKED_COVERAGE = "blocked-coverage"
    BLOCKED_DIMENSION = "blocked-dimension"
    BLOCKED_PERSISTENCE = "blocked-persistence"


class ReplayMode(str, Enum):
    AUDIT_REPLAY = "audit-replay"
    MATERIALIZE_REPLAY = "materialize-replay"
    RECAPTURE_RECONCILE = "recapture-reconcile"
    RESUME = "resume"


class ReplayStatus(str, Enum):
    COMPLETED = "completed"
    SUMMARY_ONLY = "summary-only"
    MATERIALIZED = "materialized"
    MATERIALIZED_REVALIDATION_REQUIRED = "materialized-revalidation-required"
    NEW_CAPTURE_CREATED = "new-capture-created"
    COMMITTED_AFTER_RECONCILE = "committed-after-reconcile"
    BLOCKED_EVIDENCE_UNAVAILABLE = "blocked-evidence-unavailable"
    BLOCKED_PERMISSION = "blocked-permission"
    BLOCKED_ASSET_MISSING = "blocked-asset-missing"
    BLOCKED_DUPLICATE_SIDE_EFFECT = "blocked-duplicate-side-effect"
    BLOCKED_UNKNOWN_ENUM = "blocked-unknown-enum"
    BLOCKED_UNRESOLVED_REFERENCE = "blocked-unresolved-reference"
    NOT_RUN = "not-run"
    NOT_USED = "not-used"


class EvidenceAvailability(str, Enum):
    AVAILABLE = "available"
    EVIDENCE_UNAVAILABLE = "evidence-unavailable"
    ACCESS_DENIED = "access-denied"
    NOT_CAPTURED = "not-captured"


class Applicability(str, Enum):
    REQUIRED = "required"
    NOT_REQUIRED = "not-required"
