"""Storage contracts shared by local pilot and future production backends."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

from src.app.services.contracts import (
    AuditBundle,
    DeliveryRecord,
    RuntimeIR,
    validate_audit_bundle,
    validate_runtime_ir,
)


StorageProfile = Literal["local-pilot", "production"]


class PersistenceValidationError(ValueError):
    """A delivery bundle cannot be persisted safely."""


class IdempotencyConflict(ValueError):
    """One idempotency key was reused for different content."""


class PersistenceCommitError(OSError):
    """An atomic persistence operation did not complete."""


@dataclass(frozen=True, slots=True)
class ValidatedDeliveryBundle:
    trace_id: str
    runtime_ir: RuntimeIR | Mapping[str, Any]
    audit_bundle: AuditBundle | Mapping[str, Any]
    release_decision: Any = None


class DeliveryStore(ABC):
    storage_profile: StorageProfile
    production_eligible: bool

    @abstractmethod
    def put(self, bundle: Any, idempotency_key: str) -> DeliveryRecord:
        ...

    @abstractmethod
    def get(self, trace_id: str) -> DeliveryRecord | None:
        ...

    @abstractmethod
    def list_expired(self, now: Any) -> list[DeliveryRecord]:
        ...

    @abstractmethod
    def purge(self, expired: Iterable[DeliveryRecord]) -> Any:
        ...


def validate_delivery_bundle(bundle: Any) -> ValidatedDeliveryBundle:
    runtime = (
        bundle.get("runtime_ir")
        if isinstance(bundle, Mapping)
        else getattr(bundle, "runtime_ir", None)
    )
    audit = (
        bundle.get("audit_bundle")
        if isinstance(bundle, Mapping)
        else getattr(bundle, "audit_bundle", None)
    )
    trace_id = (
        bundle.get("trace_id")
        if isinstance(bundle, Mapping)
        else getattr(bundle, "trace_id", None)
    )
    release_decision = (
        bundle.get("release_decision")
        if isinstance(bundle, Mapping)
        else getattr(bundle, "release_decision", None)
    )
    if not str(trace_id or "").strip():
        raise PersistenceValidationError("trace_id is required")
    if runtime is None or audit is None:
        raise PersistenceValidationError("runtime_ir and audit_bundle are required")
    runtime_issues = validate_runtime_ir(runtime)
    if runtime_issues:
        raise PersistenceValidationError(
            "; ".join(f"{item.code}: {item.message}" for item in runtime_issues)
        )
    audit_issues = validate_audit_bundle(audit)
    if audit_issues:
        raise PersistenceValidationError(
            "; ".join(f"{item.code}: {item.message}" for item in audit_issues)
        )
    runtime_job_id = (
        runtime.get("job_id")
        if isinstance(runtime, Mapping)
        else runtime.job_id
    )
    audit_job_id = (
        audit.get("job_id")
        if isinstance(audit, Mapping)
        else audit.job_id
    )
    if runtime_job_id != audit_job_id:
        raise PersistenceValidationError(
            "runtime IR and audit bundle must use the same job id"
        )
    if (
        isinstance(audit, Mapping)
        and audit.get("execution_graph") is not None
    ) or (
        not isinstance(audit, Mapping)
        and getattr(audit, "execution_graph", None) is not None
    ):
        raise PersistenceValidationError(
            "audit bundle cannot carry a runtime execution graph"
        )
    return ValidatedDeliveryBundle(
        trace_id=str(trace_id),
        runtime_ir=runtime,
        audit_bundle=audit,
        release_decision=release_decision,
    )
