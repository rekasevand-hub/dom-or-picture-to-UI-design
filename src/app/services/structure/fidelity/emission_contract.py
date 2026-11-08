"""Inventory emission contract: identity-based content preservation checks.

The compiler emits one Figma element per scene-plan node, but content can still
be lost *before* compilation (a scene-plan suppression whose replacement does
not carry the same visible text) and *after* rendering (a native TEXT element
that is silently skipped by the diagnostic owner builder).  Both defects make
``criticalText.matchedCount`` fall without any blocker naming the lost owner.

This module makes those two boundaries explicit:

* ``suppression_text_equivalent`` is the single source of truth used both by
  the scene planner and by the audit.  A suppression may only replace an owner
  when the visible text is equivalent.  Geometric overlap alone is not proof
  of duplicate content.
* ``audit_emission`` tracks every inventory item by ``contentRef`` through
  scene plan -> design -> gate owners and reports classified violations.
* ``register_unmeasured_owners`` builds a *diagnostic copy* of the native text
  quality report that includes unmeasurable-but-native owners.  It never
  recomputes the frozen gate and never writes back to the acceptance report.

All functions are pure.  This module is a contract/audit layer, not part of
the frozen formal acceptance policy.
"""

from __future__ import annotations

import copy
import os
from collections import Counter
from collections.abc import Mapping
from typing import Any

from src.app.services.structure.fidelity.contracts import (
    normalize_match_text,
    owner_text_similarity,
)

SCHEMA_VERSION = "inventory-emission-contract/1.0"

# OCR rows are supplementary observations, not authoritative content owners.
# A grounded owner may replace a nearby OCR variant of the same string; a
# grounded label must never be replaced by a different grounded label.
OCR_DERIVED_AUTHORITIES = frozenset({"ocr", "ocr-supplement", "easyocr"})
OCR_VARIANT_SIMILARITY = 0.80

# Inventory kinds whose *text* is expected to survive as a visible owner.
# ``asset`` is deliberately excluded: it is an image fill, not editable copy.
TEXT_BEARING_KINDS = frozenset(
    {"text", "control", "table-cell", "table-header"}
)

UNMEASURABLE_STATUS = "unmeasurable-missing-evidence"
LEGACY_SUPPRESSION_ENV = "SCENE_PLAN_LEGACY_OVERLAP_SUPPRESSION"


def legacy_overlap_suppression_enabled() -> bool:
    """Escape hatch for A/B comparison; the safe behaviour is the default."""
    return str(os.getenv(LEGACY_SUPPRESSION_ENV, "")).strip().lower() in {
        "1",
        "true",
        "yes",
    }


def suppression_text_equivalent(left: Any, right: Any) -> bool:
    """Whether one visible text may legitimately replace another owner.

    Strict normalized equality is intentional.  Substring / containment is
    NOT equivalence: ``本期好价 折扣都按官方价实时算`` and
    ``折扣都按官方价实时算`` differ by a visible label, and suppressing the
    former loses that label.  Punctuation-only variants are already folded by
    ``normalize_match_text`` (NFKC + casefold + whitespace removal).
    """
    normalized_left = normalize_match_text(left)
    normalized_right = normalize_match_text(right)
    if not normalized_left or not normalized_right:
        return False
    return normalized_left == normalized_right


def suppression_allowed(suppressed: Any, replacement: Any) -> bool:
    """Whether ``replacement`` may legitimately stand in for ``suppressed``.

    This is the single criterion shared by the scene planner and the audit.
    Two rules, in order:

    1. Equivalent visible text -> duplicate owner, suppression is safe.
    2. The suppressed item is an OCR-derived observation and reads as a noisy
       variant of the replacement -> the authoritative owner wins.  This
       preserves the project's existing OCR de-duplication behaviour.

    Anything else -- in particular two *different* grounded labels whose
    bounding boxes happen to overlap -- must keep both owners.
    """
    if not isinstance(suppressed, Mapping) or not isinstance(replacement, Mapping):
        return False
    if suppression_text_equivalent(
        suppressed.get("text") or suppressed.get("controlValue"),
        replacement.get("text") or replacement.get("controlValue"),
    ):
        return True
    authority = str(suppressed.get("authority") or "").strip().lower()
    if authority not in OCR_DERIVED_AUTHORITIES:
        return False
    return (
        owner_text_similarity(
            suppressed.get("text") or suppressed.get("controlValue"),
            replacement.get("text") or replacement.get("controlValue"),
        )
        >= OCR_VARIANT_SIMILARITY
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text_of(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    return str(value.get("text") or value.get("controlValue") or "").strip()


def _ref(value: Any, key: str) -> str:
    if not isinstance(value, Mapping):
        return ""
    return str(value.get(key) or "")


def _is_text_bearing(item: Any) -> bool:
    if not isinstance(item, Mapping):
        return False
    if str(item.get("kind") or "") not in TEXT_BEARING_KINDS:
        return False
    return bool(_text_of(item))


def audit_emission(
    *,
    inventory: Mapping[str, Any] | None,
    scene_plan: Mapping[str, Any] | None,
    design: Mapping[str, Any] | None,
    quality: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Audit content preservation across four artefact layers by identity."""
    inventory = _mapping(inventory)
    scene_plan = _mapping(scene_plan)
    design = _mapping(design)
    quality = _mapping(quality)

    items = [item for item in inventory.get("items") or [] if isinstance(item, Mapping)]
    items_by_ref = {_ref(item, "id"): item for item in items if _ref(item, "id")}
    nodes = [node for node in scene_plan.get("nodes") or [] if isinstance(node, Mapping)]
    suppressed = [
        row for row in scene_plan.get("suppressed") or [] if isinstance(row, Mapping)
    ]
    elements = [
        element for element in design.get("elements") or []
        if isinstance(element, Mapping)
    ]
    owners = [
        owner for owner in quality.get("owners") or [] if isinstance(owner, Mapping)
    ]

    inventory_refs = Counter(_ref(item, "id") for item in items if _ref(item, "id"))
    node_refs = Counter(
        _ref(node, "content_ref") for node in nodes if _ref(node, "content_ref")
    )
    element_refs = Counter(
        _ref(element, "contentRef")
        for element in elements
        if _ref(element, "contentRef")
    )
    owner_refs = Counter(
        _ref(owner, "contentRef") for owner in owners if _ref(owner, "contentRef")
    )
    nodes_by_ref = {
        _ref(node, "content_ref"): node for node in nodes if _ref(node, "content_ref")
    }
    elements_by_ref = {
        _ref(element, "contentRef"): element
        for element in elements
        if _ref(element, "contentRef")
    }
    suppressed_by_ref = {
        _ref(row, "content_ref"): row
        for row in suppressed
        if _ref(row, "content_ref")
    }

    violations: list[dict[str, Any]] = []

    # Invariant 1: content identity is unique in every layer.
    duplicates = {
        layer: {key: count for key, count in counter.items() if count > 1}
        for layer, counter in (
            ("inventory", inventory_refs),
            ("scenePlanNodes", node_refs),
            ("designElements", element_refs),
            ("gateOwners", owner_refs),
        )
    }
    for layer, entries in duplicates.items():
        for ref, count in entries.items():
            violations.append(
                {
                    "type": "duplicate-emission",
                    "layer": layer,
                    "contentRef": ref,
                    "count": count,
                    "detail": "one contentRef must have exactly one owner",
                }
            )

    # Invariant 2: every inventory item either has a plan node or an explicit
    # suppression record.  A silent disappearance is always a defect.
    for ref, item in items_by_ref.items():
        if ref in node_refs or ref in suppressed_by_ref:
            continue
        violations.append(
            {
                "type": "unaccounted-inventory-item",
                "contentRef": ref,
                "text": _text_of(item),
                "kind": str(item.get("kind") or ""),
                "detail": "item is neither a plan node nor explicitly suppressed",
            }
        )

    # Invariant 3: a text-bearing suppression must point to an existing owner
    # carrying equivalent visible text.  This is the defect that silently
    # dropped labels such as '本期好价', '数据看板' and '钱包'.
    for ref, row in suppressed_by_ref.items():
        item = items_by_ref.get(ref)
        if not _is_text_bearing(item):
            continue
        text = _text_of(item)
        replacement_ref = _ref(row, "replacement_ref")
        replacement_node = nodes_by_ref.get(replacement_ref) or {}
        replacement_element = elements_by_ref.get(replacement_ref) or {}
        replacement_text = _text_of(replacement_node) or _text_of(
            replacement_element
        )
        replacement = {**replacement_element, **replacement_node}
        if not replacement_ref or not (replacement_node or replacement_element):
            violations.append(
                {
                    "type": "suppression-replacement-missing",
                    "contentRef": ref,
                    "text": text,
                    "reason": str(row.get("reason") or ""),
                    "replacementRef": replacement_ref,
                }
            )
            continue
        if not suppression_allowed(item, replacement):
            violations.append(
                {
                    "type": "unequivalent-suppression",
                    "contentRef": ref,
                    "text": text,
                    "reason": str(row.get("reason") or ""),
                    "replacementRef": replacement_ref,
                    "replacementText": replacement_text,
                    "detail": (
                        "geometric overlap is not content equivalence; "
                        "the suppressed label has no equivalent owner"
                    ),
                }
            )

    # Invariant 4: a text-bearing plan node emits exactly one design element.
    for ref, node in nodes_by_ref.items():
        if str(node.get("type") or "") not in {"text", "control", "table"}:
            continue
        if not _text_of(node):
            continue
        if element_refs.get(ref, 0) == 1:
            continue
        violations.append(
            {
                "type": "plan-design-emission-mismatch",
                "contentRef": ref,
                "text": _text_of(node),
                "elementCount": element_refs.get(ref, 0),
            }
        )

    # Invariant 5: every visible native text element has one gate owner, even
    # when it cannot be measured.  An unmeasurable owner must be reported, not
    # silently skipped, otherwise critical text matching treats it as absent.
    for ref, element in elements_by_ref.items():
        if str(element.get("type") or "") == "image":
            continue
        text = _text_of(element)
        if not text or owner_refs.get(ref, 0) >= 1:
            continue
        violations.append(
            {
                "type": "unregistered-native-owner",
                "contentRef": ref,
                "text": text,
                "elementType": str(element.get("type") or ""),
                "hasStyleEvidence": isinstance(element.get("styleEvidence"), Mapping),
                "detail": (
                    "native element is absent from native_text_quality.owners; "
                    "critical text matching cannot see it"
                ),
            }
        )

    gate = _mapping(quality.get("gate"))
    critical = _mapping(gate.get("criticalText"))
    critical_missing = {
        normalize_match_text(value) for value in critical.get("missing") or []
    }
    correlated = sorted(
        {
            str(violation["text"])
            for violation in violations
            if violation["type"]
            in {"unequivalent-suppression", "unregistered-native-owner"}
            and normalize_match_text(violation.get("text")) in critical_missing
        }
    )

    by_type = Counter(str(violation["type"]) for violation in violations)
    invariants = [
        {
            "id": "identity-unique",
            "status": "fail" if any(duplicates.values()) else "pass",
            "violations": by_type.get("duplicate-emission", 0),
        },
        {
            "id": "suppression-accounted",
            "status": (
                "fail" if by_type.get("unaccounted-inventory-item") else "pass"
            ),
            "violations": by_type.get("unaccounted-inventory-item", 0),
        },
        {
            "id": "suppression-equivalent",
            "status": (
                "fail"
                if by_type.get("unequivalent-suppression")
                or by_type.get("suppression-replacement-missing")
                else "pass"
            ),
            "violations": (
                by_type.get("unequivalent-suppression", 0)
                + by_type.get("suppression-replacement-missing", 0)
            ),
        },
        {
            "id": "plan-design-parity",
            "status": (
                "fail" if by_type.get("plan-design-emission-mismatch") else "pass"
            ),
            "violations": by_type.get("plan-design-emission-mismatch", 0),
        },
        {
            "id": "native-owner-registered",
            "status": (
                "fail" if by_type.get("unregistered-native-owner") else "pass"
            ),
            "violations": by_type.get("unregistered-native-owner", 0),
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "violations-detected" if violations else "pass",
        "counts": {
            "inventoryItems": len(items),
            "textBearingItems": sum(_is_text_bearing(item) for item in items),
            "scenePlanNodes": len(nodes),
            "suppressedOwners": len(suppressed),
            "designElements": len(elements),
            "gateOwners": len(owners),
            "violations": len(violations),
        },
        "violationsByType": dict(sorted(by_type.items())),
        "invariants": invariants,
        "violations": violations,
        "criticalMissingCorrelation": correlated,
        "limitations": [
            "Diagnostic contract only; it does not change the frozen formal "
            "acceptance policy or backfill any metric.",
            "Equivalence is strict normalized text equality. OCR noise in a "
            "suppressed item can therefore be reported as a violation even "
            "when no real visible label was lost.",
            "Correlation with criticalText.missing is an observation, not a "
            "prediction that fixing the violation will change a gate result.",
            "No full-screenshot underlay check is performed here; that is a "
            "separate editability invariant.",
        ],
    }


def register_unmeasured_owners(
    quality: Mapping[str, Any] | None,
    design: Mapping[str, Any] | None,
    readback: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a diagnostic copy of ``quality`` with unregistered owners added.

    The gate is deliberately NOT recomputed: this copy is evidence about
    registration loss, not a replacement acceptance result.  ``nativeText`` is
    only set when a readback tree is supplied; otherwise it stays ``None``.
    """
    result = copy.deepcopy(dict(_mapping(quality)))
    design = _mapping(design)
    owners = [owner for owner in result.get("owners") or [] if isinstance(owner, Mapping)]
    registered = {
        _ref(owner, "contentRef") for owner in owners if _ref(owner, "contentRef")
    }

    native_characters: set[str] | None = None
    if readback is not None:
        characters: set[str] = set()

        def walk(node: Any) -> None:
            if not isinstance(node, Mapping):
                return
            if node.get("type") == "TEXT":
                value = str(node.get("characters") or "")
                if value:
                    characters.add(value)
            for child in node.get("children") or []:
                walk(child)

        walk(readback)
        native_characters = characters

    added: list[dict[str, Any]] = []
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        if str(element.get("type") or "") == "image":
            continue
        text = _text_of(element)
        ref = _ref(element, "contentRef")
        if not text or not ref or ref in registered:
            continue
        owner: dict[str, Any] = {
            "contentRef": ref,
            "text": text,
            "nativeText": (
                text in native_characters if native_characters is not None else None
            ),
            "ownerScope": "diagnostic-only",
            "status": UNMEASURABLE_STATUS,
            "registrationSource": SCHEMA_VERSION,
            "note": (
                "Registered by the emission contract. Measurements are "
                "unavailable; this owner is NOT counted as passing."
            ),
        }
        owners.append(owner)
        registered.add(ref)
        added.append(owner)
    result["owners"] = owners
    result["registrationRepair"] = {
        "schema_version": SCHEMA_VERSION,
        "addedCount": len(added),
        "gateRecomputed": False,
        "note": (
            "Diagnostic copy only. The frozen acceptance report is unchanged; "
            "unmeasurable owners are never counted as passing."
        ),
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "addedCount": len(added),
        "added": [
            {
                "contentRef": owner["contentRef"],
                "text": owner["text"],
                "nativeText": owner["nativeText"],
            }
            for owner in added
        ],
        "gateRecomputed": False,
    }
    return result, summary


def critical_missing_overlap(
    audit: Mapping[str, Any], quality: Mapping[str, Any] | None
) -> list[str]:
    """Names present both as emission violations and as critical misses."""
    gate = _mapping(_mapping(quality).get("gate"))
    critical = _mapping(gate.get("criticalText"))
    missing = {
        normalize_match_text(value) for value in critical.get("missing") or []
    }
    found: set[str] = set()
    for violation in audit.get("violations") or []:
        if not isinstance(violation, Mapping):
            continue
        text = str(violation.get("text") or "")
        if text and normalize_match_text(text) in missing:
            found.add(text)
    return sorted(found)
