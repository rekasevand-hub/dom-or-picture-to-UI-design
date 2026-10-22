"""Fail-closed validators for runtime IR and ordered audit bundles."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from src.app.services.contracts.enums import (
    FieldAuthority,
    FieldDecisionStatus,
)
from src.app.services.contracts.migration import SUPPORTED_RUNTIME_IR_VERSIONS
from src.app.services.contracts.models import (
    AuditBundle,
)

SEMANTIC_FIELD_TYPES = {"role", "editability", "asset-source"}
TEXT_FIELDS = {"text-content", "screenshot-ocr-text"}
UNRESOLVED_STATUSES = {
    FieldDecisionStatus.DEFERRED,
    FieldDecisionStatus.EXTERNAL_CONFLICT,
    FieldDecisionStatus.UNKNOWN,
    FieldDecisionStatus.UNSUPPORTED,
    FieldDecisionStatus.TOMBSTONE,
    FieldDecisionStatus.DELETE_PENDING,
    FieldDecisionStatus.NOT_APPLICABLE,
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


class ContractValidationError(ValueError):
    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(issues)
        super().__init__("; ".join(f"{item.path}: {item.message}" for item in self.issues))


def _validate_field_mapping(field: Mapping[str, Any], path: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    decision = field.get("decision")
    if not isinstance(decision, Mapping):
        return [ValidationIssue("missing-decision", f"{path}.decision", "decision is required")]
    raw_status = decision.get("status")
    valid_statuses = {item.value for item in FieldDecisionStatus}
    if raw_status not in valid_statuses:
        issues.append(
            ValidationIssue(
                "unknown-field-status",
                f"{path}.decision.status",
                f"unknown field decision enum: {raw_status!r}",
            )
        )
    if raw_status in {item.value for item in UNRESOLVED_STATUSES}:
        if decision.get("selected_value") is not None:
            issues.append(
                ValidationIssue(
                    "unresolved-has-value",
                    f"{path}.decision.selected_value",
                    "unresolved status cannot carry a selected value",
                )
            )
    if raw_status == FieldDecisionStatus.SELECTED.value:
        if decision.get("selected_value") is None:
            issues.append(
                ValidationIssue(
                    "selected-without-value",
                    f"{path}.decision.selected_value",
                    "selected decision requires a value",
                )
            )
        if decision.get("authority") == FieldAuthority.NONE.value:
            issues.append(
                ValidationIssue(
                    "selected-without-authority",
                    f"{path}.decision.authority",
                    "selected decision requires a non-none authority",
                )
            )
    if decision.get("release_eligible") and raw_status != FieldDecisionStatus.SELECTED.value:
        issues.append(
            ValidationIssue(
                "ineligible-status-released",
                f"{path}.decision.release_eligible",
                "only selected decisions can be release eligible",
            )
        )
    if (
        decision.get("authority") == FieldAuthority.SCREENSHOT.value
        and field.get("field_type") in SEMANTIC_FIELD_TYPES
    ):
        issues.append(
            ValidationIssue(
                "screenshot-semantic-authority",
                f"{path}.decision.authority",
                "screenshot authority cannot own role, editability or asset-source",
            )
        )
    if field.get("field_type") in TEXT_FIELDS and "screenshot" in str(
        decision.get("authority", "")
    ):
        cannot_promote = set(decision.get("cannot_promote") or [])
        required = {"role", "editability", "asset-source"}
        if not required.issubset(cannot_promote):
            issues.append(
                ValidationIssue(
                    "ocr-semantic-promotion",
                    f"{path}.decision.cannot_promote",
                    "screenshot text must explicitly block semantic promotion",
                )
            )
    if raw_status != FieldDecisionStatus.TOMBSTONE.value and not field.get("observations"):
        issues.append(
            ValidationIssue(
                "winner-only-field",
                f"{path}.observations",
                "non-tombstone field must retain at least one observation",
            )
        )
    return issues


def validate_runtime_ir(
    ir: Any,
    *,
    known_captures: set[str] | None = None,
) -> list[ValidationIssue]:
    if hasattr(ir, "to_dict"):
        ir = ir.to_dict()
    if not isinstance(ir, Mapping):
        return [ValidationIssue("bad-ir", "runtime_ir", "runtime IR must be an object")]
    issues: list[ValidationIssue] = []
    if ir.get("outer_schema") != "runtime-ir/1.0":
        issues.append(ValidationIssue("bad-outer-schema", "outer_schema", "expected runtime-ir/1.0"))
    if ir.get("schema_version") not in SUPPORTED_RUNTIME_IR_VERSIONS:
        issues.append(
            ValidationIssue(
                "unknown-schema-version",
                "schema_version",
                f"unsupported schema version: {ir.get('schema_version')!r}",
            )
        )
    fields = ir.get("fields")
    if not isinstance(fields, list):
        issues.append(ValidationIssue("missing-fields", "fields", "fields must be a list"))
        return issues
    evidence_ids = {
        item.get("evidence_id")
        for item in ir.get("evidence", [])
        if isinstance(item, Mapping)
    }
    field_ids = [
        item.get("field_id")
        for item in fields
        if isinstance(item, Mapping)
    ]
    duplicates = sorted({item for item in field_ids if field_ids.count(item) > 1})
    for field_id in duplicates:
        issues.append(ValidationIssue("duplicate-field", "fields", f"duplicate field id: {field_id}"))
    tombstone_count = len(ir.get("tombstones") or [])
    for index, field in enumerate(fields):
        if not isinstance(field, Mapping):
            issues.append(ValidationIssue("bad-field", f"fields[{index}]", "field must be an object"))
            continue
        issues.extend(_validate_field_mapping(field, f"fields[{index}]"))
        for evidence_id in (field.get("decision") or {}).get("evidence_refs") or []:
            if evidence_id not in evidence_ids:
                issues.append(
                    ValidationIssue(
                        "missing-evidence-reference",
                        f"fields[{index}].decision.evidence_refs",
                        f"unknown evidence id: {evidence_id}",
                    )
                )
        if (
            (field.get("decision") or {}).get("status") == FieldDecisionStatus.TOMBSTONE.value
            and tombstone_count == 0
        ):
            issues.append(
                ValidationIssue(
                    "missing-tombstone",
                    f"fields[{index}].decision.status",
                    "tombstone decision requires a tombstone record",
                )
            )
    graph = ir.get("execution_graph")
    if not isinstance(graph, Mapping) or graph.get("sequence_semantics") != "runtime-dag":
        issues.append(
            ValidationIssue(
                "missing-runtime-dag",
                "execution_graph",
                "runtime graph must use runtime-dag semantics",
            )
        )
    else:
        nodes = tuple(graph.get("nodes") or ())
        edges = tuple(tuple(edge) for edge in graph.get("edges") or ())
        node_set = set(nodes)
        if not node_set:
            issues.append(ValidationIssue("empty-runtime-dag", "execution_graph.nodes", "runtime graph has no nodes"))
        for edge_index, edge in enumerate(edges):
            if len(edge) != 2 or edge[0] not in node_set or edge[1] not in node_set:
                issues.append(
                    ValidationIssue(
                        "unknown-graph-node",
                        f"execution_graph.edges[{edge_index}]",
                        f"edge references unknown node: {edge}",
                    )
                )
        if _has_cycle(nodes, edges):
            issues.append(
                ValidationIssue(
                    "cyclic-runtime-dag",
                    "execution_graph.edges",
                    "runtime execution graph contains a cycle",
                )
            )
    captures = known_captures or ({ir.get("capture_id")} if ir.get("capture_id") else set())
    for index, reference in enumerate(ir.get("references") or []):
        if (
            reference.get("required")
            and reference.get("kind") == "capture"
            and reference.get("target") not in captures
        ):
            issues.append(
                ValidationIssue(
                    "unresolved-reference",
                    f"references[{index}].target",
                    f"missing capture reference: {reference.get('target')!r}",
                )
            )
    retention = ir.get("retention") or {}
    replay_days = retention.get("replay_evidence_days")
    audit_days = retention.get("audit_metadata_days")
    if isinstance(replay_days, int) and isinstance(audit_days, int) and audit_days < replay_days:
        issues.append(
            ValidationIssue(
                "retention-order",
                "retention.audit_metadata_days",
                "audit metadata retention cannot be shorter than replay evidence",
            )
        )
    return issues


def validate_audit_bundle(bundle: AuditBundle | Mapping[str, Any]) -> list[ValidationIssue]:
    if isinstance(bundle, AuditBundle):
        bundle = bundle.to_dict()
    issues: list[ValidationIssue] = []
    if bundle.get("outer_schema") != "audit-bundle/1.0":
        issues.append(ValidationIssue("bad-outer-schema", "outer_schema", "expected audit-bundle/1.0"))
    if bundle.get("sequence_semantics") != "ordered-audit-only":
        issues.append(
            ValidationIssue(
                "audit-order-semantics",
                "sequence_semantics",
                "audit bundle must remain ordered-audit-only",
            )
        )
    if bundle.get("execution_graph") is not None or bundle.get("runtime_dependency_graph") is not None:
        issues.append(
            ValidationIssue(
                "audit-has-runtime-graph",
                "execution_graph",
                "audit bundle cannot carry a runtime dependency graph",
            )
        )
    ordered_evidence = bundle.get("ordered_evidence") or []
    if len(set(ordered_evidence)) != len(ordered_evidence):
        issues.append(
            ValidationIssue(
                "duplicate-audit-evidence",
                "ordered_evidence",
                "ordered evidence contains duplicates",
            )
        )
    return issues


def _has_cycle(
    nodes: Iterable[str],
    edges: Iterable[tuple[str, str]],
) -> bool:
    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        adjacency.setdefault(source, []).append(target)
        adjacency.setdefault(target, [])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for child in adjacency.get(node, []):
            if visit(child):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in adjacency)


def raise_for_issues(issues: Iterable[ValidationIssue]) -> None:
    collected = tuple(issues)
    if collected:
        raise ContractValidationError(collected)
