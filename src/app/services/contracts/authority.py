"""Field-level authority helpers, independent of collection and rendering."""
from __future__ import annotations

from src.app.services.contracts.enums import FieldAuthority, FieldDecisionStatus
from src.app.services.contracts.models import FieldDecision, FieldRecord

OCR_PROMOTION_GUARD = ("role", "editability", "asset-source")
SEMANTIC_FIELDS = frozenset({"role", "editability", "asset-source"})
TEXT_FIELDS = frozenset({"text-content", "screenshot-ocr-text"})


def authority_for_ocr(*, dom_confirmed: bool) -> FieldAuthority:
    return (
        FieldAuthority.DOM_AND_SCREENSHOT
        if dom_confirmed
        else FieldAuthority.SCREENSHOT
    )


def text_decision_from_ocr(
    *,
    value: str,
    dom_evidence_id: str | None,
    screenshot_evidence_id: str,
    confident: bool,
) -> FieldDecision:
    if not confident:
        return FieldDecision(
            authority=FieldAuthority.SCREENSHOT,
            status=FieldDecisionStatus.UNKNOWN,
            selected_value=None,
            release_eligible=False,
            cannot_promote=OCR_PROMOTION_GUARD,
            reason="OCR evidence is insufficient for promotion.",
            evidence_refs=(screenshot_evidence_id,),
        )
    if dom_evidence_id:
        return FieldDecision(
            authority=FieldAuthority.DOM_AND_SCREENSHOT,
            status=FieldDecisionStatus.SELECTED,
            selected_value=value,
            release_eligible=True,
            cannot_promote=OCR_PROMOTION_GUARD,
            reason="DOM source and screenshot confirmation agree.",
            evidence_refs=(dom_evidence_id, screenshot_evidence_id),
        )
    return FieldDecision(
        authority=FieldAuthority.SCREENSHOT,
        status=FieldDecisionStatus.CANDIDATE,
        selected_value=value,
        release_eligible=False,
        cannot_promote=OCR_PROMOTION_GUARD,
        reason="Screenshot OCR supplies a text candidate only.",
        evidence_refs=(screenshot_evidence_id,),
    )


def assert_field_authority(field: FieldRecord) -> None:
    decision = field.decision
    if (
        decision.authority is FieldAuthority.SCREENSHOT
        and field.field_type in SEMANTIC_FIELDS
    ):
        raise ValueError("Screenshot authority cannot own semantic fields")
    if field.field_type in TEXT_FIELDS and decision.authority in {
        FieldAuthority.SCREENSHOT,
        FieldAuthority.DOM_AND_SCREENSHOT,
    }:
        if not set(OCR_PROMOTION_GUARD).issubset(decision.cannot_promote):
            raise ValueError("OCR text decisions must block semantic promotion")
