"""Build and persist the opt-in P0 delivery bundle."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from src.app.services.contracts import (
    DIMENSIONS,
    AcceptanceCheck,
    AuditBundle,
    DeliveryProfile,
    Dimension,
    PageCoverage,
    ReleaseDecision,
    RuntimeIR,
    ValidationIssue,
    build_audit_bundle,
    canonical_hash,
    evaluate_release,
    validate_audit_bundle,
    validate_runtime_ir,
)

if TYPE_CHECKING:
    from src.app.services.evidence.adapter import EvidenceSidecar


DELIVERY_POLICY_VERSION = "p5-delivery/1.0"


@dataclass(frozen=True, slots=True)
class DeliveryAcceptance:
    checks: tuple[AcceptanceCheck, ...]
    coverage: PageCoverage
    preflight_passed: bool
    user_allowed_partial: bool
    noncritical_gap_isolatable: bool
    required_dimensions: tuple[Dimension, ...] = DIMENSIONS
    reference_only: bool = False
    production_prerequisites: Mapping[str, bool] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContractDeliveryBundle:
    runtime_ir: RuntimeIR
    audit_bundle: AuditBundle
    release_decision: ReleaseDecision
    trace_id: str
    design_sha256: str
    delivery_profile: DeliveryProfile
    manifest: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "delivery_profile": self.delivery_profile,
            "trace_id": self.trace_id,
            "design_sha256": self.design_sha256,
            "runtime_ir": self.runtime_ir.to_dict(),
            "audit_bundle": self.audit_bundle.to_dict(),
            "release_decision": self.release_decision.to_dict(),
            "manifest": dict(self.manifest),
        }


class DeliveryContractError(ValueError):
    def __init__(
        self,
        issues: tuple[ValidationIssue, ...],
        *,
        trace_id: str | None = None,
    ) -> None:
        self.issues = issues
        self.trace_id = trace_id
        prefix = f"{trace_id}: " if trace_id else ""
        super().__init__(
            prefix
            + "; ".join(
                f"{issue.path}: {issue.message}" for issue in self.issues
            )
        )


def build_runtime_delivery(
    capture_sidecar: EvidenceSidecar,
    design: Mapping[str, Any],
    acceptance: DeliveryAcceptance,
    *,
    delivery_profile: DeliveryProfile = "contract-v2",
) -> ContractDeliveryBundle:
    if delivery_profile != "contract-v2":
        raise ValueError("runtime delivery bundles require delivery_profile=contract-v2")

    source_ir = capture_sidecar.runtime_ir
    issues = list(validate_runtime_ir(source_ir))
    if issues:
        raise DeliveryContractError(tuple(issues))
    audit_issues = list(validate_audit_bundle(capture_sidecar.audit_bundle))
    if audit_issues:
        raise DeliveryContractError(tuple(audit_issues))
    if capture_sidecar.audit_bundle.job_id != source_ir.job_id:
        raise DeliveryContractError(
            (
                ValidationIssue(
                    "audit-job-mismatch",
                    "audit_bundle.job_id",
                    "runtime IR and audit bundle must use the same job id",
                ),
            )
        )

    design_sha256 = canonical_hash(design)
    trace_id = "trace-" + canonical_hash(
        {
            "job_id": source_ir.job_id,
            "capture_revision": source_ir.capture_revision,
            "design_sha256": design_sha256,
            "delivery_policy": DELIVERY_POLICY_VERSION,
        }
    )[:16]
    plan_revision = f"plan-{design_sha256[:16]}:r1"
    output_revision = f"output-{design_sha256[:16]}:r1"
    runtime_ir = replace(
        source_ir,
        policy_version=DELIVERY_POLICY_VERSION,
        plan_revision=plan_revision,
        output_revision=output_revision,
    )
    runtime_issues = list(validate_runtime_ir(runtime_ir))
    if runtime_issues:
        raise DeliveryContractError(tuple(runtime_issues), trace_id=trace_id)

    audit_bundle = build_audit_bundle(runtime_ir)
    audit_issues = list(validate_audit_bundle(audit_bundle))
    if audit_issues:
        raise DeliveryContractError(tuple(audit_issues), trace_id=trace_id)

    release_decision = evaluate_release(
        checks=acceptance.checks,
        coverage=acceptance.coverage,
        required_dimensions=acceptance.required_dimensions,
        preflight_passed=acceptance.preflight_passed,
        user_allowed_partial=acceptance.user_allowed_partial,
        noncritical_gap_isolatable=acceptance.noncritical_gap_isolatable,
        reference_only=acceptance.reference_only,
        production_prerequisites=acceptance.production_prerequisites,
    )
    if (
        release_decision.complete_export_allowed
        and release_decision.status.value != "deliverable-complete"
    ):
        raise DeliveryContractError(
            (
                ValidationIssue(
                    "inconsistent-release-decision",
                    "release_decision.complete_export_allowed",
                    "complete export can only be enabled by deliverable-complete",
                ),
            ),
            trace_id=trace_id,
        )

    manifest = {
        "schema": "contract-delivery-manifest/1.0",
        "delivery_profile": delivery_profile,
        "policy_version": DELIVERY_POLICY_VERSION,
        "trace_id": trace_id,
        "job_id": runtime_ir.job_id,
        "capture_id": runtime_ir.capture_id,
        "capture_revision": runtime_ir.capture_revision,
        "plan_revision": runtime_ir.plan_revision,
        "output_revision": runtime_ir.output_revision,
        "design_sha256": design_sha256,
        "runtime_ir_sha256": canonical_hash(runtime_ir.to_dict()),
        "audit_bundle_sha256": canonical_hash(audit_bundle.to_dict()),
        "release_decision": release_decision.to_dict(),
    }
    manifest["content_hash"] = canonical_hash(manifest)
    return ContractDeliveryBundle(
        runtime_ir=runtime_ir,
        audit_bundle=audit_bundle,
        release_decision=release_decision,
        trace_id=trace_id,
        design_sha256=design_sha256,
        delivery_profile=delivery_profile,
        manifest=manifest,
    )


def emit_runtime_delivery(
    bundle: ContractDeliveryBundle,
    output_dir: str | Path,
) -> dict[str, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "runtime_ir": destination / "runtime_ir.json",
        "audit_bundle": destination / "audit_bundle.json",
        "delivery_manifest": destination / "delivery_manifest.json",
    }
    _write_json(paths["runtime_ir"], bundle.runtime_ir.to_dict())
    _write_json(paths["audit_bundle"], bundle.audit_bundle.to_dict())
    _write_json(paths["delivery_manifest"], bundle.manifest)
    return paths


def _write_json(path: Path, value: Any) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        staging.write_text(payload, encoding="utf-8")
        with staging.open("rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)
