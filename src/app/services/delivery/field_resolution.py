"""Field-level authority fusion for conflict-safe delivery."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable, Mapping

from src.app.services.contracts import (
    FieldAuthority,
    FieldDecision,
    FieldDecisionStatus,
    FieldObservation,
    FieldRecord,
    Tombstone,
    assert_field_authority,
    canonical_hash,
    jsonable,
    text_decision_from_ocr,
)


TEXT_FIELDS = frozenset({"text-content", "screenshot-ocr-text"})
PRICE_FIELDS = frozenset({"price", "amount", "currency"})
UNRESOLVED_STATUSES = frozenset(
    {
        FieldDecisionStatus.DEFERRED,
        FieldDecisionStatus.EXTERNAL_CONFLICT,
        FieldDecisionStatus.UNKNOWN,
        FieldDecisionStatus.UNSUPPORTED,
        FieldDecisionStatus.SKIPPED,
        FieldDecisionStatus.AUTHORITY_REQUIRED,
        FieldDecisionStatus.RETAINED_UNVERIFIED,
        FieldDecisionStatus.CARRIED_FORWARD_NOT_SEEN,
        FieldDecisionStatus.DELETE_PENDING,
        FieldDecisionStatus.TOMBSTONE,
        FieldDecisionStatus.NOT_APPLICABLE,
    }
)


class FieldResolutionError(ValueError):
    """Raised when an observation cannot be represented without overstating authority."""


@dataclass(frozen=True, slots=True)
class FieldClaim:
    field_id: str
    node_id: str
    field_type: str
    observations: tuple[FieldObservation, ...]
    status_hint: FieldDecisionStatus | None = None
    required_authority: str | None = None
    tombstone: Tombstone | None = None
    ocr_confident: bool = False
    skip_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.field_id or not self.node_id or not self.field_type:
            raise ValueError("field_id, node_id and field_type are required")
        normalized = tuple(_coerce_observation(item) for item in self.observations)
        object.__setattr__(self, "observations", normalized)


@dataclass(frozen=True, slots=True)
class ResolvedField:
    claim: FieldClaim
    decision: FieldDecision
    winner: Any | None
    candidate_value: Any | None

    @property
    def field_id(self) -> str:
        return self.claim.field_id

    @property
    def node_id(self) -> str:
        return self.claim.node_id

    @property
    def field_type(self) -> str:
        return self.claim.field_type

    @property
    def tombstone(self) -> Tombstone | None:
        return self.claim.tombstone

    @property
    def unresolved(self) -> bool:
        return (
            self.decision.status in UNRESOLVED_STATUSES
            or self.decision.status is FieldDecisionStatus.CANDIDATE
            or self.decision.status is FieldDecisionStatus.OBSERVED
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "node_id": self.node_id,
            "field_type": self.field_type,
            "status": self.decision.status.value,
            "winner": jsonable(self.winner),
            "candidate_value": jsonable(self.candidate_value),
            "release_eligible": self.decision.release_eligible,
            "observations": [item.to_dict() for item in self.claim.observations],
            "tombstone": (
                self.claim.tombstone.to_dict() if self.claim.tombstone else None
            ),
            "decision": self.decision.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class FieldResolution:
    profile: str
    fields: tuple[ResolvedField, ...]
    content: Mapping[str, Mapping[str, Any]]
    counts: Mapping[str, int]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "field-resolution/1.0",
            "profile": self.profile,
            "fields": [field.to_dict() for field in self.fields],
            "content": jsonable(self.content),
            "counts": dict(self.counts),
            "content_hash": self.content_hash,
        }


def resolve_fields(
    observations: Iterable[FieldClaim | FieldRecord | Mapping[str, Any]],
    profile: str,
) -> FieldResolution:
    if not str(profile or "").strip():
        raise FieldResolutionError("a non-empty resolution profile is required")
    claims = tuple(_coerce_claim(item) for item in observations)
    if len({claim.field_id for claim in claims}) != len(claims):
        raise FieldResolutionError("duplicate field ids are not allowed")

    resolved = tuple(_resolve_claim(claim) for claim in claims)
    content: dict[str, dict[str, Any]] = {}
    for field in resolved:
        if field.winner is None or not field.decision.release_eligible:
            continue
        node = content.setdefault(field.node_id, {})
        if field.field_type in node:
            raise FieldResolutionError(
                f"duplicate content field: {field.node_id}/{field.field_type}"
            )
        node[field.field_type] = field.winner

    counts: dict[str, int] = {}
    for field in resolved:
        status = field.decision.status.value
        counts[status] = counts.get(status, 0) + 1
    payload = {
        "profile": str(profile),
        "fields": [field.to_dict() for field in resolved],
        "content": content,
    }
    return FieldResolution(
        profile=str(profile),
        fields=resolved,
        content=content,
        counts=counts,
        content_hash=canonical_hash(payload),
    )


def _resolve_claim(claim: FieldClaim) -> ResolvedField:
    decision = _decision_for_claim(claim)
    record = FieldRecord(
        field_id=claim.field_id,
        node_id=claim.node_id,
        field_type=claim.field_type,
        observations=claim.observations,
        decision=decision,
    )
    try:
        assert_field_authority(record)
    except ValueError as exc:
        raise FieldResolutionError(str(exc)) from exc

    selected = (
        decision.selected_value
        if decision.status is FieldDecisionStatus.SELECTED
        else None
    )
    candidate = (
        decision.selected_value
        if decision.status is FieldDecisionStatus.CANDIDATE
        else None
    )
    return ResolvedField(
        claim=claim,
        decision=decision,
        winner=selected,
        candidate_value=candidate,
    )


def _decision_for_claim(claim: FieldClaim) -> FieldDecision:
    if claim.tombstone is not None:
        return FieldDecision(
            authority=FieldAuthority.NONE,
            status=FieldDecisionStatus.DELETE_PENDING,
            selected_value=None,
            release_eligible=False,
            reason="An authoritative tombstone blocks carrying the old value forward.",
        )
    if claim.status_hint is not None:
        status = (
            FieldDecisionStatus.DELETE_PENDING
            if claim.status_hint is FieldDecisionStatus.TOMBSTONE
            else claim.status_hint
        )
        if status in UNRESOLVED_STATUSES:
            return FieldDecision(
                authority=FieldAuthority.NONE,
                status=status,
                selected_value=None,
                release_eligible=False,
                reason=claim.skip_reason or f"Field is explicitly {status.value}.",
            )

    required_authority = claim.required_authority
    if claim.field_type in PRICE_FIELDS and required_authority is None:
        required_authority = "business"
    if required_authority and not any(
        _source_family(item.source) == required_authority
        for item in claim.observations
        if item.present
    ):
        return FieldDecision(
            authority=FieldAuthority.NONE,
            status=FieldDecisionStatus.AUTHORITY_REQUIRED,
            selected_value=None,
            release_eligible=False,
            reason=f"Field requires {required_authority} authority.",
        )

    present = tuple(item for item in claim.observations if item.present)
    if not present:
        return FieldDecision(
            authority=FieldAuthority.NONE,
            status=FieldDecisionStatus.UNKNOWN,
            selected_value=None,
            release_eligible=False,
            reason="No authoritative observation is available.",
        )

    if claim.field_type in TEXT_FIELDS and all(
        _source_family(item.source) == "screenshot" for item in present
    ):
        first = present[0]
        return text_decision_from_ocr(
            value=str(first.value),
            dom_evidence_id=None,
            screenshot_evidence_id=first.evidence_id or "screenshot-ocr",
            confident=claim.ocr_confident,
        )

    values = tuple(item.value for item in present)
    if any(value != values[0] for value in values[1:]):
        return FieldDecision(
            authority=FieldAuthority.NONE,
            status=FieldDecisionStatus.EXTERNAL_CONFLICT,
            selected_value=None,
            release_eligible=False,
            reason="Observations disagree and no configured authority resolves them.",
            evidence_refs=tuple(
                item.evidence_id for item in present if item.evidence_id
            ),
        )

    families = {_source_family(item.source) for item in present}
    if families == {"screenshot"}:
        authority = FieldAuthority.SCREENSHOT
    elif families == {"dom"}:
        authority = FieldAuthority.DOM
    else:
        authority = FieldAuthority.DOM_AND_SCREENSHOT
    return FieldDecision(
        authority=authority,
        status=FieldDecisionStatus.SELECTED,
        selected_value=values[0],
        release_eligible=True,
        cannot_promote=(
            ("role", "editability", "asset-source")
            if authority is FieldAuthority.SCREENSHOT
            and claim.field_type in TEXT_FIELDS
            else ()
        ),
        reason="All present observations agree for this authored profile.",
        evidence_refs=tuple(
            item.evidence_id for item in present if item.evidence_id
        ),
    )


def _source_family(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized.startswith("dom"):
        return "dom"
    if "screenshot" in normalized or "ocr" in normalized:
        return "screenshot"
    if normalized in {
        "business",
        "inventory",
        "cms",
        "price-authority",
    }:
        return normalized
    return "other"


def _coerce_claim(item: FieldClaim | FieldRecord | Mapping[str, Any]) -> FieldClaim:
    if isinstance(item, FieldClaim):
        return item
    if isinstance(item, FieldRecord):
        status = item.decision.status
        return FieldClaim(
            field_id=item.field_id,
            node_id=item.node_id,
            field_type=item.field_type,
            observations=item.observations,
            status_hint=status if status in UNRESOLVED_STATUSES else None,
        )
    if isinstance(item, Mapping):
        return FieldClaim(
            field_id=str(item["field_id"]),
            node_id=str(item["node_id"]),
            field_type=str(item["field_type"]),
            observations=tuple(item.get("observations") or ()),
            status_hint=_coerce_status(item.get("status_hint")),
            required_authority=item.get("required_authority"),
            tombstone=item.get("tombstone"),
            ocr_confident=bool(item.get("ocr_confident")),
            skip_reason=item.get("skip_reason"),
        )
    raise TypeError(f"unsupported field claim: {type(item).__name__}")


def _coerce_observation(item: FieldObservation | Mapping[str, Any]) -> FieldObservation:
    if isinstance(item, FieldObservation):
        return item
    if isinstance(item, Mapping):
        return FieldObservation(
            source=str(item.get("source") or ""),
            evidence_id=item.get("evidence_id"),
            present=bool(item.get("present", True)),
            value=item.get("value"),
            reason=item.get("reason"),
        )
    raise TypeError(f"unsupported field observation: {type(item).__name__}")


def _coerce_status(value: Any) -> FieldDecisionStatus | None:
    if value is None:
        return None
    if isinstance(value, FieldDecisionStatus):
        return value
    return FieldDecisionStatus(str(value))
