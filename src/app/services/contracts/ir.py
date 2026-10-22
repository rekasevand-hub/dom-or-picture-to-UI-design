"""Runtime IR and audit-bundle layer boundaries."""
from __future__ import annotations

from src.app.services.contracts.models import AuditBundle, RuntimeIR
from src.app.services.contracts.validation import (
    ValidationIssue,
    validate_audit_bundle,
    validate_runtime_ir,
)


def build_audit_bundle(ir: RuntimeIR) -> AuditBundle:
    """Create an ordered audit projection without carrying runtime edges."""
    bundle = AuditBundle(
        job_id=ir.job_id,
        schema_version=ir.schema_version,
        policy_version=ir.policy_version,
        ordered_evidence=tuple(item.evidence_id for item in ir.evidence),
        decisions=ir.fields,
        tombstones=ir.tombstones,
        unknowns=ir.unknowns,
        order_mapping=ir.order_mapping,
        retention=ir.retention,
    )
    if bundle.execution_graph is not None or bundle.runtime_dependency_graph is not None:
        raise ValueError("Audit bundles cannot carry runtime graphs")
    return bundle


def validate_layers(ir: RuntimeIR) -> list[ValidationIssue]:
    issues = list(validate_runtime_ir(ir))
    issues.extend(validate_audit_bundle(build_audit_bundle(ir)))
    return issues
