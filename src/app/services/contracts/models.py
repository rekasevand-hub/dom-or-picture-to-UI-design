"""Immutable data models for runtime IR, coverage and release decisions."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any, Mapping

from src.app.services.contracts.enums import (
    Applicability,
    CheckStatus,
    CoverageState,
    CoverageStatus,
    Dimension,
    EvidenceAvailability,
    FieldAuthority,
    FieldDecisionStatus,
    ReleaseStatus,
    ReplayMode,
    ReplayStatus,
)


def jsonable(value: Any) -> Any:
    """Return a deterministic JSON-compatible projection of contract objects."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError("Rect width and height must be nonnegative")

    def to_dict(self) -> dict[str, float]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    kind: str
    sha256: str
    locator: str
    availability: EvidenceAvailability = EvidenceAvailability.AVAILABLE
    expires_at: str | None = None
    bytes_present: bool = True

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class FieldObservation:
    source: str
    evidence_id: str | None
    present: bool
    value: Any
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class FieldDecision:
    authority: FieldAuthority
    status: FieldDecisionStatus
    selected_value: Any = None
    release_eligible: bool = False
    cannot_promote: tuple[str, ...] = ()
    reason: str = ""
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class FieldRecord:
    field_id: str
    node_id: str
    field_type: str
    observations: tuple[FieldObservation, ...]
    decision: FieldDecision

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class Tombstone:
    tombstone_id: str
    object_key: str
    scope: str
    authority: str
    authority_version: int
    effective_at: str
    delete_status: str = "pending"
    not_deleted: bool = True

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class UnknownRecord:
    object_key: str
    field: str
    status: str
    reason: str
    winner: None = None

    def __post_init__(self) -> None:
        if self.winner is not None:
            raise ValueError("Unknown records cannot carry a winner")

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class ReferenceRecord:
    reference_id: str
    kind: str
    target: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class OrderMapping:
    dom_order: tuple[str, ...]
    screenshot_order: tuple[str, ...]
    figma_child_order: tuple[str, ...]
    basis: str = "explicit-mapping"

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class AssetRecord:
    asset_id: str
    source_url: str | None
    url_expires_at: str | None
    local_sha256: str
    local_bytes_present: bool
    local_expires_at: str | None
    mime: str

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    replay_evidence_days: int
    audit_metadata_days: int
    evidence_expires_at: str | None = None
    audit_metadata_expires_at: str | None = None
    external_url_separate: bool = True

    def __post_init__(self) -> None:
        if self.replay_evidence_days <= 0 or self.audit_metadata_days <= 0:
            raise ValueError("Retention durations must be positive")
        if self.audit_metadata_days < self.replay_evidence_days:
            raise ValueError("Audit metadata retention cannot be shorter than replay evidence")

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    allow_evidence_read: bool
    allow_materialize: bool
    allow_audit_summary: bool

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class ExecutionGraph:
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    sequence_semantics: str = "runtime-dag"

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class RuntimeIR:
    job_id: str
    schema_version: str
    policy_version: str
    capture_revision: str
    plan_revision: str
    output_revision: str
    capture_id: str
    state_signature: str
    fields: tuple[FieldRecord, ...]
    evidence: tuple[EvidenceRecord, ...]
    assets: tuple[AssetRecord, ...]
    tombstones: tuple[Tombstone, ...]
    unknowns: tuple[UnknownRecord, ...]
    order_mapping: OrderMapping
    references: tuple[ReferenceRecord, ...]
    retention: RetentionPolicy
    access_policy: AccessPolicy
    execution_graph: ExecutionGraph
    migration_chain: tuple[dict[str, Any], ...] = ()
    outer_schema: str = "runtime-ir/1.0"

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class AuditBundle:
    job_id: str
    schema_version: str
    policy_version: str
    ordered_evidence: tuple[str, ...]
    decisions: tuple[FieldRecord, ...]
    tombstones: tuple[Tombstone, ...]
    unknowns: tuple[UnknownRecord, ...]
    order_mapping: OrderMapping
    retention: RetentionPolicy
    sequence_semantics: str = "ordered-audit-only"
    outer_schema: str = "audit-bundle/1.0"
    execution_graph: None = None
    runtime_dependency_graph: None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class CoverageRegion:
    region_id: str
    object_keys: tuple[str, ...]
    source_rect: Rect
    output_rect: Rect
    coverage_state: CoverageState
    reason: str
    evidence_refs: tuple[str, ...]
    affected_dimensions: tuple[Dimension, ...] = ()
    blocked_actions: tuple[str, ...] = ()
    diagnostic_mask: bool = False

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class CoverageDimension:
    denominator: float
    covered: float
    missing: float
    unknown: float
    ratio: float
    status: CoverageStatus
    unit: str

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class PageCoverage:
    area: CoverageDimension
    objects: CoverageDimension
    text: CoverageDimension
    critical: CoverageDimension
    denominator_unchanged: bool
    generic_pass_ratio: None = None
    minimum_sample_count: None = None

    @property
    def complete(self) -> bool:
        return (
            self.denominator_unchanged
            and all(
                dimension.status is CoverageStatus.PASS
                and dimension.missing == 0
                and dimension.unknown == 0
                and dimension.covered == dimension.denominator
                for dimension in (self.area, self.objects, self.text, self.critical)
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    check_id: str
    object_key: str
    dimension: Dimension
    check_type: str
    critical: bool
    required: bool
    status: CheckStatus
    partial_allowed: bool = False
    applicability: Applicability = Applicability.REQUIRED
    evidence_refs: tuple[str, ...] = ()
    threshold_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    status: ReleaseStatus
    reason: str
    dimensions: dict[str, str]
    critical_blockers: tuple[str, ...]
    complete_export_allowed: bool
    allowed_export_mode: str
    pilot_status: str
    production_status: str

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class ReplayResult:
    mode: ReplayMode
    status: ReplayStatus
    exact_replay: bool
    pixel_identical_guaranteed: bool
    evidence_status: EvidenceAvailability | None = None
    output_hash: str | None = None
    old_capture_id: str | None = None
    new_capture_id: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class MigrationResult:
    source_version: str
    target_version: str
    source_hash: str
    migrated_hash: str
    preserved: dict[str, bool]
    migration_chain: tuple[dict[str, Any], ...]

    @property
    def all_preserved(self) -> bool:
        return bool(self.preserved) and all(self.preserved.values())

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    trace_id: str
    idempotency_key: str
    stored_at: str
    expires_at: str
    runtime_ir: Any
    audit_bundle: Any
    release_decision: Any
    storage_profile: str
    production_eligible: bool
    content_hash: str
    purge_protected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return jsonable(self)

