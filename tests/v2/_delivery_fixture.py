from __future__ import annotations

from dataclasses import dataclass

from src.app.services.contracts import (
    AcceptanceCheck,
    AccessPolicy,
    Applicability,
    AuditBundle,
    CheckStatus,
    CoverageInput,
    Dimension,
    EvidenceAvailability,
    EvidenceRecord,
    ExecutionGraph,
    FieldAuthority,
    FieldDecision,
    FieldDecisionStatus,
    FieldObservation,
    FieldRecord,
    OrderMapping,
    ReferenceRecord,
    RetentionPolicy,
    RuntimeIR,
    build_audit_bundle,
    build_page_coverage,
)
from src.app.services.delivery.runtime_delivery import DeliveryAcceptance
from src.app.services.evidence.adapter import EvidenceSidecar


def delivery_design() -> dict:
    return {
        "canvas": {"width": 320, "height": 200, "background": "#ffffff"},
        "elements": [
            {
                "id": "card",
                "type": "rectangle",
                "x": 12,
                "y": 16,
                "width": 296,
                "height": 168,
                "fillColor": "#f2f4f7",
            },
            {
                "id": "title",
                "type": "text",
                "x": 28,
                "y": 32,
                "width": 180,
                "height": 32,
                "text": "Contract delivery",
                "fontSize": 20,
                "fillColor": "#ffffff",
                "textColor": "#111827",
            },
        ],
    }


def delivery_sidecar() -> EvidenceSidecar:
    evidence = (
        EvidenceRecord(
            evidence_id="ev-dom",
            kind="dom-json",
            sha256="a" * 64,
            locator="evidence/dom.json",
            availability=EvidenceAvailability.AVAILABLE,
        ),
    )
    field = FieldRecord(
        field_id="field-title",
        node_id="dom:0001",
        field_type="text-content",
        observations=(
            FieldObservation(
                source="dom",
                evidence_id="ev-dom",
                present=True,
                value="Contract delivery",
            ),
        ),
        decision=FieldDecision(
            authority=FieldAuthority.DOM,
            status=FieldDecisionStatus.SELECTED,
            selected_value="Contract delivery",
            release_eligible=True,
            evidence_refs=("ev-dom",),
            reason="DOM text is authoritative for the authored fixture.",
        ),
    )
    runtime_ir = RuntimeIR(
        job_id="job-delivery-fixture",
        schema_version="2.0",
        policy_version="p5-delivery/1.0",
        capture_revision="capture-r1",
        plan_revision="plan-pending",
        output_revision="output-pending",
        capture_id="capture-r1",
        state_signature="state-r1",
        fields=(field,),
        evidence=evidence,
        assets=(),
        tombstones=(),
        unknowns=(),
        order_mapping=OrderMapping(
            dom_order=("dom:0000", "dom:0001"),
            screenshot_order=("dom:0000", "dom:0001"),
            figma_child_order=("dom:0000", "dom:0001"),
        ),
        references=(
            ReferenceRecord(
                reference_id="capture",
                kind="capture",
                target="capture-r1",
            ),
        ),
        retention=RetentionPolicy(
            replay_evidence_days=30,
            audit_metadata_days=180,
        ),
        access_policy=AccessPolicy(
            allow_evidence_read=True,
            allow_materialize=True,
            allow_audit_summary=True,
        ),
        execution_graph=ExecutionGraph(
            nodes=("capture", "fusion", "write", "publish"),
            edges=(
                ("capture", "fusion"),
                ("fusion", "write"),
                ("write", "publish"),
            ),
        ),
    )
    audit_bundle: AuditBundle = build_audit_bundle(runtime_ir)
    return EvidenceSidecar(
        runtime_ir=runtime_ir,
        audit_bundle=audit_bundle,
        manifest={"sidecar_schema": "evidence-sidecar/1.0"},
    )


def delivery_acceptance() -> DeliveryAcceptance:
    checks = tuple(
        AcceptanceCheck(
            check_id=f"{dimension.value}-pass",
            object_key="page",
            dimension=dimension,
            check_type="authored-fixture",
            critical=True,
            required=True,
            status=CheckStatus.PASS,
            applicability=Applicability.REQUIRED,
            evidence_refs=("ev-dom",),
            threshold_source="authored-delivery-fixture",
        )
        for dimension in (
            Dimension.VISUAL,
            Dimension.STRUCTURE,
            Dimension.EDIT,
            Dimension.ASSET,
        )
    )
    coverage = build_page_coverage(
        area=CoverageInput(64000, 64000, unit="px"),
        objects=CoverageInput(2, 2, unit="count"),
        text=CoverageInput(18, 18, unit="characters"),
        critical=CoverageInput(2, 2, unit="count"),
    )
    return DeliveryAcceptance(
        checks=checks,
        coverage=coverage,
        preflight_passed=True,
        user_allowed_partial=False,
        noncritical_gap_isolatable=False,
    )


@dataclass
class RecordingAdapter:
    actions: list[dict]
    connected: bool = False

    def connect(self) -> None:
        self.connected = True
        self.actions.append({"operation": "connect"})

    def disconnect(self) -> None:
        self.connected = False
        self.actions.append({"operation": "disconnect"})

    def render_design(self, design: dict) -> None:
        self.actions.append({"operation": "render_design", "design": design})

    def create_frame(self, spec: dict) -> str:
        self.actions.append({"operation": "create_frame", "spec": spec})
        return "frame-1"

    def create_rectangle(self, spec: dict, parent_id: str | None = None) -> str:
        self.actions.append(
            {
                "operation": "create_rectangle",
                "spec": spec,
                "parent_id": parent_id,
            }
        )
        return "rectangle-1"

    def create_ellipse(self, spec: dict, parent_id: str | None = None) -> str:
        self.actions.append(
            {
                "operation": "create_ellipse",
                "spec": spec,
                "parent_id": parent_id,
            }
        )
        return "ellipse-1"

    def create_text(self, spec: dict, parent_id: str | None = None) -> str:
        self.actions.append(
            {"operation": "create_text", "spec": spec, "parent_id": parent_id}
        )
        return "text-1"

    def create_image(self, spec: dict, parent_id: str | None = None) -> str:
        self.actions.append(
            {"operation": "create_image", "spec": spec, "parent_id": parent_id}
        )
        return "image-1"

    def flush(self) -> None:
        self.actions.append({"operation": "flush"})
