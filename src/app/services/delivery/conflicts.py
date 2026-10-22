"""Project unresolved fields into a user-visible conflict/unknown report."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.app.services.contracts import (
    FieldDecisionStatus,
    canonical_hash,
    jsonable,
)
from src.app.services.delivery.field_resolution import (
    FieldResolution,
    ResolvedField,
)


REQUIRED_REPORT_FIELDS = (
    "entry_id",
    "field_id",
    "node_id",
    "field_type",
    "status",
    "observations",
    "authority_gap",
    "current_display",
    "blocked_actions",
    "next_step",
    "unlock_condition",
    "winner",
)


@dataclass(frozen=True, slots=True)
class ConflictEntry:
    entry_id: str
    field_id: str
    node_id: str
    field_type: str
    status: FieldDecisionStatus
    observations: tuple[dict[str, Any], ...]
    authority_gap: str
    current_display: str
    blocked_actions: tuple[str, ...]
    next_step: str
    unlock_condition: str
    winner: None = None
    tombstone: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "field_id": self.field_id,
            "node_id": self.node_id,
            "field_type": self.field_type,
            "status": self.status.value,
            "observations": [dict(item) for item in self.observations],
            "authority_gap": self.authority_gap,
            "current_display": self.current_display,
            "blocked_actions": list(self.blocked_actions),
            "next_step": self.next_step,
            "unlock_condition": self.unlock_condition,
            "winner": self.winner,
            "tombstone": self.tombstone,
        }


@dataclass(frozen=True, slots=True)
class ConflictReport:
    profile: str
    entries: tuple[ConflictEntry, ...]
    content: dict[str, dict[str, Any]]
    counts: dict[str, int]
    outside_business_flow: bool
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "conflict-report/1.0",
            "profile": self.profile,
            "entries": [item.to_dict() for item in self.entries],
            "content": jsonable(self.content),
            "counts": dict(self.counts),
            "outside_business_flow": self.outside_business_flow,
            "content_hash": self.content_hash,
        }


def build_conflict_report(resolution: FieldResolution) -> ConflictReport:
    entries = tuple(
        _project_entry(field)
        for field in resolution.fields
        if field.unresolved
    )
    payload = {
        "profile": resolution.profile,
        "entries": [entry.to_dict() for entry in entries],
        "content": resolution.content,
        "outside_business_flow": True,
    }
    return ConflictReport(
        profile=resolution.profile,
        entries=entries,
        content=dict(resolution.content),
        counts=dict(resolution.counts),
        outside_business_flow=True,
        content_hash=canonical_hash(payload),
    )


def _project_entry(field: ResolvedField) -> ConflictEntry:
    status = field.decision.status
    return ConflictEntry(
        entry_id=f"RPT-{field.field_id}",
        field_id=field.field_id,
        node_id=field.node_id,
        field_type=field.field_type,
        status=status,
        observations=_project_observations(field),
        authority_gap=_authority_gap(field),
        current_display=_current_display(field),
        blocked_actions=_blocked_actions(field),
        next_step=_next_step(field),
        unlock_condition=_unlock_condition(field),
        tombstone=field.tombstone.to_dict() if field.tombstone else None,
    )


def _project_observations(field: ResolvedField) -> tuple[dict[str, Any], ...]:
    if not field.claim.observations:
        return (
            {
                "source": "capture",
                "evidence_id": None,
                "present": False,
                "value": None,
                "reason": "not-observed",
            },
        )
    return tuple(
        {
            "source": item.source,
            "evidence_id": item.evidence_id,
            "present": item.present,
            "value": jsonable(item.value),
            "reason": item.reason,
        }
        for item in field.claim.observations
    )


def _authority_gap(field: ResolvedField) -> str:
    status = field.decision.status
    if status is FieldDecisionStatus.EXTERNAL_CONFLICT:
        return "Observations disagree and no configured authority resolves the field."
    if status is FieldDecisionStatus.AUTHORITY_REQUIRED:
        return "The field requires an explicit business or inventory authority."
    if status in {
        FieldDecisionStatus.DELETE_PENDING,
        FieldDecisionStatus.TOMBSTONE,
    }:
        return "An authoritative tombstone requires scoped deletion evidence."
    if status is FieldDecisionStatus.CANDIDATE:
        return "OCR supplies a candidate without DOM confirmation."
    if status is FieldDecisionStatus.DEFERRED:
        return "The dependent state is unresolved."
    if status is FieldDecisionStatus.SKIPPED:
        return field.claim.skip_reason or "The field is outside the current scope."
    if status is FieldDecisionStatus.UNSUPPORTED:
        return "The current profile does not support this field."
    return "No authoritative observation is available."


def _current_display(field: ResolvedField) -> str:
    status = field.decision.status
    if status in {
        FieldDecisionStatus.DELETE_PENDING,
        FieldDecisionStatus.TOMBSTONE,
    }:
        return "Old value is not carried forward; deletion remains pending."
    if status is FieldDecisionStatus.SKIPPED:
        return "Field is intentionally omitted from the business content."
    if field.field_type in {"text-content", "screenshot-ocr-text"}:
        return "Text field is empty; candidate text remains only in this report."
    if field.field_type in {"color", "background"}:
        return "Node has no claimed fill color."
    if field.field_type == "visibility":
        return "No content node is created while visibility remains unresolved."
    if field.field_type in {"asset", "asset-source", "asset-hint"}:
        return "Placeholder only; no asset bytes or final source are placed."
    if field.field_type in {"geometry", "text-box"}:
        return "No disputed geometry is placed at a default location."
    if field.field_type in {"price", "amount", "currency"}:
        return "No price is rendered; candidates remain in this report."
    return "No unresolved value is written to business content."


def _blocked_actions(field: ResolvedField) -> tuple[str, ...]:
    actions = ["write-final-value", "publish-as-complete"]
    if field.tombstone is not None:
        actions.append("delete-without-ownership-proof")
    return tuple(actions)


def _next_step(field: ResolvedField) -> str:
    status = field.decision.status
    if status is FieldDecisionStatus.EXTERNAL_CONFLICT:
        return "Select an authoritative observation or ask the operator."
    if status is FieldDecisionStatus.AUTHORITY_REQUIRED:
        return "Obtain business authority before writing the field."
    if status in {
        FieldDecisionStatus.DELETE_PENDING,
        FieldDecisionStatus.TOMBSTONE,
    }:
        return "Confirm deletion scope and ownership, then reconcile explicitly."
    if status is FieldDecisionStatus.CANDIDATE:
        return "Obtain DOM confirmation or a higher-confidence observation."
    if status is FieldDecisionStatus.DEFERRED:
        return "Resolve the dependent page state before delivery."
    if status is FieldDecisionStatus.SKIPPED:
        return "Keep the omission visible unless scope changes."
    return "Capture the missing observation or request manual review."


def _unlock_condition(field: ResolvedField) -> str:
    status = field.decision.status
    if status is FieldDecisionStatus.EXTERNAL_CONFLICT:
        return "One authoritative observation for the field."
    if status is FieldDecisionStatus.AUTHORITY_REQUIRED:
        return "Explicit business authority decision."
    if status in {
        FieldDecisionStatus.DELETE_PENDING,
        FieldDecisionStatus.TOMBSTONE,
    }:
        return "Verified deletion capability and ownership."
    if status is FieldDecisionStatus.CANDIDATE:
        return "DOM confirmation for the same capture state."
    if status is FieldDecisionStatus.DEFERRED:
        return "A stable state with a complete observation."
    if status is FieldDecisionStatus.SKIPPED:
        return "Explicit scope change plus fresh evidence."
    return "A fresh, authoritative observation."
