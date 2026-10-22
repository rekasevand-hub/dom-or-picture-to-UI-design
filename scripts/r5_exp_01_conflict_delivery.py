# -*- coding: utf-8 -*-
"""R5-EXP-01: conflict-field default delivery, report and manifest consistency.

This is an offline, deterministic contract experiment.  It builds a model of
what a delivery writer is allowed to put on the business canvas, what must go
to the separate "Conflicts / Unknowns" report, and what the manifest must
record.  It does not connect to Figma.

Usage:
  C:/Users/lzq/.conda/envs/omni/python.exe scripts/r5_exp_01_conflict_delivery.py
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JOB = "JOB-R5-EXP-01-20261019"
REVISION = "rev1"
PROFILE = "r5-exp-01-conflict-delivery"
FIELD_TYPES = ("text", "color", "asset", "visibility", "geometry")
SCENARIOS = (
    "conflict-geometry-known",
    "unknown-new-node",
    "visibility-unknown",
    "authority-required-price",
    "old-value-tombstone",
)
STATE_ORDER = (
    "written",
    "winner-null",
    "deferred",
    "skipped",
    "authority-required",
    "retained-unverified",
    "carried-forward-not-seen",
    "delete-pending",
    "deleted-by-tombstone",
)
STATE_LABELS = {
    "written": "written",
    "winner-null": "winner=null",
    "deferred": "deferred",
    "skipped": "skipped",
    "authority-required": "authority-required",
    "retained-unverified": "retained-unverified",
    "carried-forward-not-seen": "carried-forward-not-seen",
    "delete-pending": "delete-pending",
    "deleted-by-tombstone": "deleted-by-tombstone",
}
STATE_COLORS = {
    "written": "#bbf7d0",
    "winner-null": "#fecaca",
    "deferred": "#fed7aa",
    "skipped": "#bfdbfe",
    "authority-required": "#ddd6fe",
    "retained-unverified": "#fef08a",
    "carried-forward-not-seen": "#fde68a",
    "delete-pending": "#d1d5db",
    "deleted-by-tombstone": "#9ca3af",
}
UNRESOLVED_STATES = {
    "winner-null",
    "deferred",
    "skipped",
    "authority-required",
    "retained-unverified",
    "carried-forward-not-seen",
    "delete-pending",
    "deleted-by-tombstone",
}
REQUIRED_REPORT_KEYS = (
    "entry_id",
    "object_id",
    "field_type",
    "scenario",
    "state",
    "observations",
    "authority_gap",
    "current_display",
    "blocked_actions",
    "next_step",
    "unlock_condition",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "content_hash"}
    return sha256_text(canonical(payload))


def atomic_write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + str(os.getpid()) + "-" + str(threading.get_ident()))
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def check(name: str, description: str, passed: bool, detail: Any = None) -> dict[str, Any]:
    return {"name": name, "description": description, "passed": bool(passed), "detail": detail}


def known_rect() -> dict[str, float]:
    return {"x": 48.0, "y": 48.0, "width": 260.0, "height": 96.0}


def alt_rect() -> dict[str, float]:
    return {"x": 52.0, "y": 52.0, "width": 252.0, "height": 88.0}


def old_rect() -> dict[str, float]:
    return {"x": 10.0, "y": 10.0, "width": 100.0, "height": 20.0}


def layout_rect() -> dict[str, float]:
    return {"x": 120.0, "y": 240.0, "width": 320.0, "height": 120.0}


def asset_value(tag: str) -> dict[str, Any]:
    return {
        "asset_id": "asset-" + tag,
        "sha256": hashlib.sha256(("r5-exp-01:" + tag).encode("utf-8")).hexdigest(),
        "mime": "image/png",
    }


def field_node_type(field_type: str) -> str:
    if field_type == "text":
        return "TEXT"
    if field_type == "visibility":
        return "FRAME"
    if field_type == "geometry":
        return "FRAME"
    if field_type == "asset":
        return "RECTANGLE"
    return "RECTANGLE"


def observations_for(field_type: str, scenario: str) -> list[dict[str, Any]]:
    if scenario == "conflict-geometry-known":
        if field_type == "text":
            return [
                {"value": "限时特价 A", "source": "dom", "role": "candidate"},
                {"value": "限时特价 B", "source": "screenshot-ocr", "role": "candidate"},
            ]
        if field_type == "color":
            return [
                {"value": "#ff0000", "source": "dom-css", "role": "candidate"},
                {"value": "#0000ff", "source": "screenshot-rendered", "role": "candidate"},
            ]
        if field_type == "asset":
            return [
                {"value": asset_value("cover-a"), "source": "dom-img", "role": "candidate"},
                {"value": asset_value("cover-b"), "source": "screenshot-crop", "role": "candidate"},
            ]
        if field_type == "visibility":
            return [
                {"value": True, "source": "dom-style", "role": "candidate"},
                {"value": False, "source": "screenshot-occlusion", "role": "candidate"},
            ]
        return [
            {"value": known_rect(), "source": "dom-rect", "role": "candidate"},
            {"value": alt_rect(), "source": "screenshot-rect", "role": "candidate"},
        ]
    if scenario == "unknown-new-node":
        return []
    if scenario == "visibility-unknown":
        if field_type == "text":
            return [{"value": "限时特价 A", "source": "dom", "role": "candidate"}]
        if field_type == "color":
            return [{"value": "#ff0000", "source": "dom-css", "role": "candidate"}]
        if field_type == "asset":
            return [{"value": asset_value("cover-a"), "source": "dom-img", "role": "candidate"}]
        if field_type == "visibility":
            return []
        return [{"value": known_rect(), "source": "dom-rect", "role": "candidate"}]
    if scenario == "authority-required-price":
        if field_type == "text":
            return [
                {"value": "¥19.90", "source": "dom", "role": "candidate"},
                {"value": "¥9.90", "source": "cache", "role": "candidate"},
            ]
        if field_type == "color":
            return [
                {"value": "#ff0000", "source": "dom-css", "role": "candidate"},
                {"value": "#00ff00", "source": "screenshot-rendered", "role": "candidate"},
            ]
        if field_type == "asset":
            return [
                {"value": asset_value("price-badge-a"), "source": "dom-img", "role": "candidate"},
                {"value": asset_value("price-badge-b"), "source": "screenshot-crop", "role": "candidate"},
            ]
        if field_type == "visibility":
            return [
                {"value": True, "source": "dom-style", "role": "candidate"},
                {"value": False, "source": "screenshot-occlusion", "role": "candidate"},
            ]
        return [
            {"value": known_rect(), "source": "dom-rect", "role": "candidate"},
            {"value": alt_rect(), "source": "screenshot-rect", "role": "candidate"},
        ]
    if scenario == "old-value-tombstone":
        if field_type == "text":
            return [{"value": "旧价格 ¥59.00", "source": "old-revision", "role": "historical"}]
        if field_type == "color":
            return [{"value": "#cccccc", "source": "old-revision", "role": "historical"}]
        if field_type == "asset":
            return [{"value": asset_value("cover-old"), "source": "old-revision", "role": "historical"}]
        if field_type == "visibility":
            return [{"value": True, "source": "old-revision", "role": "historical"}]
        return [{"value": old_rect(), "source": "old-revision", "role": "historical"}]
    return []


def scenario_state(scenario: str) -> str:
    return {
        "conflict-geometry-known": "winner-null",
        "unknown-new-node": "deferred",
        "visibility-unknown": "deferred",
        "authority-required-price": "authority-required",
        "old-value-tombstone": "delete-pending",
    }[scenario]


def scenario_display(field_type: str, scenario: str) -> str:
    if scenario == "conflict-geometry-known":
        if field_type == "text":
            return "Frame is shown without text; candidate text exists only in the report"
        if field_type == "color":
            return "Draft frame has no fill; no design color is claimed"
        if field_type == "asset":
            return "Placeholder slot is shown; no image is placed"
        if field_type == "visibility":
            return "No content node is created"
        return "No node is created; both rects stay in the report"
    if scenario == "unknown-new-node":
        if field_type == "text":
            return "Frame is shown without text; text is unknown"
        if field_type == "color":
            return "Draft frame is shown without a color"
        if field_type == "asset":
            return "Placeholder slot is shown; asset is unknown"
        if field_type == "visibility":
            return "No content node is created"
        return "No node is created; geometry is unknown"
    if scenario == "visibility-unknown":
        return "No content node is created because visibility is unknown"
    if scenario == "authority-required-price":
        return "No price content is created; both price candidates stay in the report"
    if scenario == "old-value-tombstone":
        return "Old value is not carried forward; deletion remains pending"
    return "Unresolved"


def scenario_gap(field_type: str, scenario: str) -> str:
    if scenario == "conflict-geometry-known":
        return "DOM and screenshot disagree; no field authority"
    if scenario == "unknown-new-node":
        return "No observation exists for the new node"
    if scenario == "visibility-unknown":
        return "Visibility is unknown; the render unit is blocked"
    if scenario == "authority-required-price":
        return "Business authority is required for the price field"
    if scenario == "old-value-tombstone":
        return "Authoritative tombstone exists; deletion capability or ownership is incomplete"
    return "Unknown"


def scenario_next(field_type: str, scenario: str) -> str:
    if scenario == "conflict-geometry-known":
        return "Ask the user or authority to choose one observation"
    if scenario == "unknown-new-node":
        return "Capture the missing observation or authorize a draft"
    if scenario == "visibility-unknown":
        return "Resolve visibility from the same state before creating the node"
    if scenario == "authority-required-price":
        return "Obtain business approval; do not treat the candidate as current price"
    if scenario == "old-value-tombstone":
        return "Confirm deletion scope and ownership, then delete with an explicit capability"
    return "Review manually"


def scenario_unlock(field_type: str, scenario: str) -> str:
    if scenario == "conflict-geometry-known":
        return "One authoritative observation for the field"
    if scenario == "unknown-new-node":
        return "New evidence or explicit authority for a draft placeholder"
    if scenario == "visibility-unknown":
        return "Visibility evidence for the same page state"
    if scenario == "authority-required-price":
        return "Business authority decision"
    if scenario == "old-value-tombstone":
        return "Deletion capability plus confirmed ownership/scope"
    return "Manual confirmation"


def conflict_case(field_type: str, scenario: str) -> dict[str, Any]:
    case_id = scenario + "__" + field_type
    object_id = "OBJ-" + field_type.upper() + "-" + scenario.upper()
    state = scenario_state(scenario)
    node_created = scenario in ("conflict-geometry-known", "unknown-new-node") and field_type in (
        "text",
        "color",
        "asset",
    )
    marker = ""
    if field_type == "text":
        marker = "TEXT PENDING"
    elif field_type == "color":
        marker = "COLOR PENDING"
    elif field_type == "asset":
        marker = "ASSET PENDING"
    elif field_type == "visibility":
        marker = "VISIBILITY PENDING"
    elif field_type == "geometry":
        marker = "GEOMETRY PENDING"

    card = None
    if node_created:
        card = {
            "case_id": case_id,
            "field_type": field_type,
            "scenario": scenario,
            "node_type": field_node_type(field_type),
            "created": True,
            "rect": layout_rect(),
            "text": None,
            "fill": None,
            "asset": None,
            "visibility": True,
            "placeholder": field_type in ("color", "asset"),
            "marker": marker,
        }
        if field_type == "text":
            card["fill"] = "#ffffff"
        elif field_type == "color":
            card["text"] = "Book title"
            card["fill"] = None
        elif field_type == "asset":
            card["text"] = "Cover slot"
            card["fill"] = "#f8fafc"

    observations = observations_for(field_type, scenario)
    entry = {
        "entry_id": "RPT-" + case_id,
        "object_id": object_id,
        "field_type": field_type,
        "scenario": scenario,
        "state": state,
        "observations": observations,
        "authority_gap": scenario_gap(field_type, scenario),
        "current_display": scenario_display(field_type, scenario),
        "blocked_actions": ["write-final-value", "publish-as-complete"],
        "next_step": scenario_next(field_type, scenario),
        "unlock_condition": scenario_unlock(field_type, scenario),
    }
    if scenario == "old-value-tombstone":
        entry["tombstone"] = {
            "scope": "field",
            "source": "authority-v3",
            "version": 3,
            "effective_at": "2026-10-19T00:00:00+00:00",
        }
        entry["old_value_status"] = "delete-pending"
    manifest_field = {
        "case_id": case_id,
        "object_id": object_id,
        "field_type": field_type,
        "scenario": scenario,
        "state": state,
        "winner": None,
        "written_value": None,
        "retained_value": None,
        "retained_status": None,
        "observations": observations,
        "authority_gap": entry["authority_gap"],
        "current_display": entry["current_display"],
        "blocked_actions": entry["blocked_actions"],
        "next_step": entry["next_step"],
        "unlock_condition": entry["unlock_condition"],
        "report_entry_id": entry["entry_id"],
        "canvas_present": bool(card),
        "release_eligible": False,
    }
    if scenario == "old-value-tombstone":
        manifest_field["tombstone"] = entry["tombstone"]
        manifest_field["old_value_status"] = "delete-pending"
    return {
        "case_id": case_id,
        "field_type": field_type,
        "scenario": scenario,
        "object_id": object_id,
        "state": state,
        "card": card,
        "entry": entry,
        "manifest": manifest_field,
    }


def control_case(field_type: str) -> dict[str, Any]:
    case_id = "control__" + field_type
    object_id = "OBJ-CONTROL-" + field_type.upper()
    rect = layout_rect()
    card = {
        "case_id": case_id,
        "field_type": field_type,
        "scenario": "control",
        "node_type": field_node_type(field_type),
        "created": True,
        "rect": rect,
        "text": "R5-EXP-01 Control Text",
        "fill": "#ffffff",
        "asset": None,
        "visibility": True,
        "placeholder": False,
        "marker": "WRITTEN",
    }
    if field_type == "color":
        card["fill"] = "#1d4ed8"
    elif field_type == "asset":
        card["text"] = "Cover"
        card["fill"] = "#f8fafc"
        card["asset"] = asset_value("control")
    elif field_type == "visibility":
        card["text"] = "Visible control"
        card["visibility"] = True
    elif field_type == "geometry":
        card["text"] = "Geometry control"
        card["rect"] = known_rect()

    def value_of() -> Any:
        if field_type == "text":
            return card["text"]
        if field_type == "color":
            return card["fill"]
        if field_type == "asset":
            return card["asset"]
        if field_type == "visibility":
            return card["visibility"]
        return card["rect"]

    value = value_of()
    manifest_field = {
        "case_id": case_id,
        "object_id": object_id,
        "field_type": field_type,
        "scenario": "control",
        "state": "written",
        "winner": value,
        "written_value": value,
        "retained_value": None,
        "retained_status": None,
        "observations": [{"value": value, "source": "control-fixture", "role": "authoritative"}],
        "authority_gap": None,
        "current_display": "Written to the business canvas",
        "blocked_actions": [],
        "next_step": "None",
        "unlock_condition": "None",
        "report_entry_id": None,
        "canvas_present": True,
        "release_eligible": True,
    }
    return {
        "case_id": case_id,
        "field_type": field_type,
        "scenario": "control",
        "object_id": object_id,
        "state": "written",
        "card": card,
        "entry": None,
        "manifest": manifest_field,
    }


def old_value_case(kind: str) -> dict[str, Any]:
    case_id = kind + "__text"
    object_id = "OBJ-" + kind.upper() + "-TEXT"
    value = "旧标题 A" if kind == "old-value-retained" else "旧标题 B"
    state = "retained-unverified" if kind == "old-value-retained" else "carried-forward-not-seen"
    marker = "RETAINED / UNVERIFIED" if kind == "old-value-retained" else "NOT SEEN THIS ROUND"
    card = {
        "case_id": case_id,
        "field_type": "text",
        "scenario": kind,
        "node_type": "TEXT",
        "created": True,
        "rect": layout_rect(),
        "text": value,
        "fill": "#ffffff",
        "asset": None,
        "visibility": True,
        "placeholder": False,
        "marker": marker,
    }
    entry = {
        "entry_id": "RPT-" + case_id,
        "object_id": object_id,
        "field_type": "text",
        "scenario": kind,
        "state": state,
        "observations": [{"value": value, "source": "old-revision", "role": "historical"}],
        "authority_gap": "Old value is visible but not verified in this round",
        "current_display": "Old value is retained on the canvas with an explicit status marker",
        "blocked_actions": ["publish-as-complete", "claim-current"],
        "next_step": "Re-observe or obtain authority before treating the old value as current",
        "unlock_condition": "Fresh observation or explicit authority",
        "old_value_status": state,
    }
    manifest_field = {
        "case_id": case_id,
        "object_id": object_id,
        "field_type": "text",
        "scenario": kind,
        "state": state,
        "winner": None,
        "written_value": None,
        "retained_value": value,
        "retained_status": state,
        "observations": entry["observations"],
        "authority_gap": entry["authority_gap"],
        "current_display": entry["current_display"],
        "blocked_actions": entry["blocked_actions"],
        "next_step": entry["next_step"],
        "unlock_condition": entry["unlock_condition"],
        "report_entry_id": entry["entry_id"],
        "canvas_present": True,
        "release_eligible": False,
    }
    return {
        "case_id": case_id,
        "field_type": "text",
        "scenario": kind,
        "object_id": object_id,
        "state": state,
        "card": card,
        "entry": entry,
        "manifest": manifest_field,
    }


def skipped_case() -> dict[str, Any]:
    case_id = "skipped__asset"
    object_id = "OBJ-SKIPPED-ASSET"
    entry = {
        "entry_id": "RPT-" + case_id,
        "object_id": object_id,
        "field_type": "asset",
        "scenario": "policy-skipped",
        "state": "skipped",
        "observations": [{"value": "asset-out-of-scope", "source": "policy", "role": "skipped"}],
        "authority_gap": "Asset is intentionally out of scope for this delivery",
        "current_display": "No asset node is created",
        "blocked_actions": ["write-asset", "publish-as-complete"],
        "next_step": "Wait for an explicit user request to include the asset",
        "unlock_condition": "User explicitly requests the asset",
    }
    manifest_field = {
        "case_id": case_id,
        "object_id": object_id,
        "field_type": "asset",
        "scenario": "policy-skipped",
        "state": "skipped",
        "winner": None,
        "written_value": None,
        "retained_value": None,
        "retained_status": None,
        "observations": entry["observations"],
        "authority_gap": entry["authority_gap"],
        "current_display": entry["current_display"],
        "blocked_actions": entry["blocked_actions"],
        "next_step": entry["next_step"],
        "unlock_condition": entry["unlock_condition"],
        "report_entry_id": entry["entry_id"],
        "canvas_present": False,
        "release_eligible": False,
    }
    return {
        "case_id": case_id,
        "field_type": "asset",
        "scenario": "policy-skipped",
        "object_id": object_id,
        "state": "skipped",
        "card": None,
        "entry": entry,
        "manifest": manifest_field,
    }


def build_delivery() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        for field_type in FIELD_TYPES:
            cases.append(conflict_case(field_type, scenario))
    for field_type in FIELD_TYPES:
        cases.append(control_case(field_type))
    cases.append(old_value_case("old-value-retained"))
    cases.append(old_value_case("old-value-not-seen"))
    cases.append(skipped_case())

    cards = [case["card"] for case in cases if case["card"] is not None]
    entries = [case["entry"] for case in cases if case["entry"] is not None]
    fields = [case["manifest"] for case in cases]

    counts = Counter(field["state"] for field in fields)
    written_count = counts.get("written", 0)
    unresolved_count = sum(counts.get(state, 0) for state in UNRESOLVED_STATES)
    canvas = {
        "schema": "r5-exp-01/canvas/v1",
        "job": JOB,
        "revision": REVISION,
        "profile": PROFILE,
        "page_name": "R5-EXP-01 PARTIAL delivery",
        "release_status": "deliverable-partial",
        "business_flow": {
            "cards": cards,
            "card_count": len(cards),
        },
        "report_frame": {
            "name": "Conflicts / Unknowns",
            "outside_business_flow": True,
            "entry_ids": [entry["entry_id"] for entry in entries],
        },
    }
    report = {
        "schema": "r5-exp-01/report/v1",
        "frame_name": "Conflicts / Unknowns",
        "outside_business_flow": True,
        "entries": entries,
        "entry_count": len(entries),
    }
    manifest = {
        "schema": "r5-exp-01/manifest/v1",
        "job": JOB,
        "revision": REVISION,
        "profile": PROFILE,
        "release_status": "deliverable-partial",
        "final_price": None,
        "report_frame_name": "Conflicts / Unknowns",
        "fields": fields,
        "counts": {
            "total": len(fields),
            "written": written_count,
            "unresolved": unresolved_count,
            "report_entries": len(entries),
            "state_counts": dict(sorted(counts.items())),
        },
        "rules": {
            "candidate_values_in_body": False,
            "unresolved_values_reported": True,
            "old_value_status_explicit": True,
            "deferred_or_skipped_as_success": False,
        },
    }
    return {"cases": cases, "canvas": canvas, "report": report, "manifest": manifest}


def card_value(card: dict[str, Any] | None, field_type: str) -> Any:
    if card is None:
        return None
    if field_type == "geometry":
        return card.get("rect")
    if field_type == "color":
        return card.get("fill")
    return card.get(field_type)


def validate_delivery(canvas: dict[str, Any], report: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    cards = {card["case_id"]: card for card in canvas.get("business_flow", {}).get("cards", [])}
    entries = {entry["entry_id"]: entry for entry in report.get("entries", [])}
    fields = manifest.get("fields", [])
    if report.get("frame_name") != "Conflicts / Unknowns":
        errors.append("report frame name is not Conflicts / Unknowns")
    if report.get("outside_business_flow") is not True:
        errors.append("report frame is inside the business flow")
    if canvas.get("report_frame", {}).get("outside_business_flow") is not True:
        errors.append("canvas report frame is not outside the business flow")

    seen: set[str] = set()
    for field in fields:
        case_id = field["case_id"]
        if case_id in seen:
            errors.append("duplicate case_id: " + case_id)
        seen.add(case_id)
        state = field["state"]
        card = cards.get(case_id)
        if state == "written":
            if field.get("winner") is None:
                errors.append(case_id + ": written field has no winner")
            if field.get("written_value") is None:
                errors.append(case_id + ": written field has no written_value")
            if field.get("report_entry_id") is not None:
                errors.append(case_id + ": written field still points to a report entry")
            if field.get("release_eligible") is not True:
                errors.append(case_id + ": written field is not release eligible")
            if card is None:
                errors.append(case_id + ": written field has no canvas card")
            elif card_value(card, field["field_type"]) != field.get("written_value"):
                errors.append(case_id + ": canvas value does not match written_value")
        else:
            if state not in UNRESOLVED_STATES:
                errors.append(case_id + ": unknown unresolved state " + str(state))
            if field.get("written_value") is not None:
                errors.append(case_id + ": unresolved field has written_value")
            if field.get("release_eligible") is not False:
                errors.append(case_id + ": unresolved field is release eligible")
            entry_id = field.get("report_entry_id")
            if not entry_id:
                errors.append(case_id + ": unresolved field has no report entry")
            else:
                entry = entries.get(entry_id)
                if entry is None:
                    errors.append(case_id + ": report entry is missing: " + entry_id)
                else:
                    if entry.get("state") != state:
                        errors.append(case_id + ": report state does not match manifest state")
                    for key in REQUIRED_REPORT_KEYS:
                        if key not in entry:
                            errors.append(case_id + ": report entry misses " + key)
                    if not entry.get("blocked_actions"):
                        errors.append(case_id + ": report entry has no blocked actions")
                    if not entry.get("next_step"):
                        errors.append(case_id + ": report entry has no next step")
                    if not entry.get("unlock_condition"):
                        errors.append(case_id + ": report entry has no unlock condition")
            if state in ("retained-unverified", "carried-forward-not-seen"):
                if field.get("retained_value") is None:
                    errors.append(case_id + ": retained field has no retained_value")
                if field.get("retained_status") != state:
                    errors.append(case_id + ": retained_status does not match state")
                if card is None:
                    errors.append(case_id + ": retained field has no canvas card")
                elif card.get("text") != field.get("retained_value"):
                    errors.append(case_id + ": retained canvas text does not match retained_value")
            else:
                if field.get("retained_value") is not None:
                    errors.append(case_id + ": non-retained field has retained_value")
            if field["scenario"] == "old-value-tombstone":
                if state not in ("delete-pending", "deleted-by-tombstone"):
                    errors.append(case_id + ": tombstone case has wrong state")
                if "tombstone" not in field:
                    errors.append(case_id + ": tombstone case has no tombstone record")
                if field.get("retained_value") is not None:
                    errors.append(case_id + ": tombstone case retains old value")
                if card is not None:
                    errors.append(case_id + ": tombstone case created a canvas card")
            if field["scenario"] == "visibility-unknown" and card is not None:
                errors.append(case_id + ": visibility-unknown case created a node")
            if field["scenario"] == "unknown-new-node" and field["field_type"] == "geometry" and card is not None:
                errors.append(case_id + ": unknown geometry created a node")
            if field["field_type"] == "visibility" and card is not None:
                errors.append(case_id + ": unresolved visibility case created a node")
            if field["field_type"] == "geometry" and card is not None:
                errors.append(case_id + ": disputed geometry case created a node")

    # Candidate leakage into the business canvas.
    candidate_texts: list[str] = []
    candidate_colors: list[str] = []
    candidate_assets: list[str] = []
    candidate_rects: list[dict[str, Any]] = []
    for field in fields:
        if field["state"] == "written":
            continue
        for obs in field.get("observations", []):
            if obs.get("role") != "candidate":
                continue
            value = obs.get("value")
            if field["field_type"] == "text" and isinstance(value, str):
                candidate_texts.append(value)
            elif field["field_type"] == "color" and isinstance(value, str):
                candidate_colors.append(value)
            elif field["field_type"] == "asset" and isinstance(value, dict):
                candidate_assets.append(str(value.get("asset_id")))
            elif field["field_type"] == "geometry" and isinstance(value, dict):
                candidate_rects.append(value)

    fields_by_case = {field["case_id"]: field for field in fields}
    for case_id, card in cards.items():
        field_config = fields_by_case.get(case_id)
        if field_config is None or field_config.get("state") == "written":
            continue
        text = card.get("text")
        if text:
            for candidate in candidate_texts:
                if candidate and candidate in text:
                    errors.append(card["case_id"] + ": candidate text leaked into the canvas")
        fill = card.get("fill")
        if fill:
            for candidate in candidate_colors:
                if candidate.lower() == str(fill).lower():
                    errors.append(card["case_id"] + ": candidate color leaked into the canvas")
        asset = card.get("asset")
        if isinstance(asset, dict):
            for candidate in candidate_assets:
                if candidate and candidate == asset.get("asset_id"):
                    errors.append(card["case_id"] + ": candidate asset leaked into the canvas")
        rect = card.get("rect")
        if isinstance(rect, dict):
            for candidate in candidate_rects:
                if candidate == rect:
                    errors.append(card["case_id"] + ": candidate geometry leaked into the canvas")

    price_candidates = [
        obs["value"]
        for field in fields
        if field["scenario"] == "authority-required-price" and field["field_type"] == "text"
        for obs in field.get("observations", [])
    ]
    for card in cards.values():
        text = card.get("text") or ""
        for candidate in price_candidates:
            if candidate and candidate in text:
                errors.append(card["case_id"] + ": price candidate leaked into the canvas")
    if manifest.get("final_price") is not None:
        errors.append("manifest has a final_price value")

    counts = manifest.get("counts", {})
    written_count = sum(1 for field in fields if field["state"] == "written")
    unresolved_count = len(fields) - written_count
    if counts.get("written") != written_count:
        errors.append("manifest written count is wrong")
    if counts.get("unresolved") != unresolved_count:
        errors.append("manifest unresolved count is wrong")
    if counts.get("report_entries") != len(entries):
        errors.append("manifest report entry count is wrong")
    if manifest.get("release_status") != "deliverable-partial":
        errors.append("release status is not deliverable-partial")
    if counts.get("total") != len(fields):
        errors.append("manifest total count is wrong")
    if counts.get("state_counts", {}).get("skipped", 0) > 0 and counts.get("written", 0) + counts.get("unresolved", 0) != counts.get("total", 0):
        errors.append("counts do not partition the fields")
    return errors


def mutate_once(mutation_id: str, canvas: dict[str, Any], report: dict[str, Any], manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    c = copy.deepcopy(canvas)
    r = copy.deepcopy(report)
    m = copy.deepcopy(manifest)
    cards = {card["case_id"]: card for card in c["business_flow"]["cards"]}
    entries = {entry["entry_id"]: entry for entry in r["entries"]}
    fields = {field["case_id"]: field for field in m["fields"]}

    if mutation_id == "candidate-text-in-body":
        cards["conflict-geometry-known__text"]["text"] = "限时特价 A"
        return c, r, m, "candidate text was inserted into the business canvas"
    if mutation_id == "deferred-marked-written":
        field = fields["unknown-new-node__text"]
        field["state"] = "written"
        field["winner"] = "限时特价 A"
        field["written_value"] = "限时特价 A"
        field["release_eligible"] = True
        cards["unknown-new-node__text"]["text"] = "限时特价 A"
        return c, r, m, "deferred field was relabeled as written"
    if mutation_id == "drop-report-entry":
        del entries["RPT-unknown-new-node__color"]
        r["entries"] = [e for e in r["entries"] if e["entry_id"] != "RPT-unknown-new-node__color"]
        return c, r, m, "one report entry was removed"
    if mutation_id == "manifest-only-write":
        fields["unknown-new-node__text"]["written_value"] = "限时特价 A"
        return c, r, m, "manifest claims a write that the canvas does not show"
    if mutation_id == "price-as-final":
        c["business_flow"]["cards"].append({
            "case_id": "authority-required-price__text",
            "field_type": "text",
            "scenario": "authority-required-price",
            "node_type": "TEXT",
            "created": True,
            "rect": known_rect(),
            "text": "¥19.90",
            "fill": "#ffffff",
            "asset": None,
            "visibility": True,
            "placeholder": False,
            "marker": "PRICE",
        })
        return c, r, m, "price candidate was placed on the business canvas"
    if mutation_id == "retained-marked-verified":
        field = fields["old-value-retained__text"]
        field["state"] = "written"
        field["winner"] = "旧标题 A"
        field["written_value"] = "旧标题 A"
        field["release_eligible"] = True
        return c, r, m, "retained-unverified old value was marked as written"
    if mutation_id == "unknown-visibility-node":
        c["business_flow"]["cards"].append({
            "case_id": "visibility-unknown__text",
            "field_type": "text",
            "scenario": "visibility-unknown",
            "node_type": "TEXT",
            "created": True,
            "rect": known_rect(),
            "text": None,
            "fill": "#ffffff",
            "asset": None,
            "visibility": True,
            "placeholder": False,
            "marker": "VISIBLE",
        })
        return c, r, m, "a node was created for an unknown-visibility case"
    if mutation_id == "geometry-at-origin":
        c["business_flow"]["cards"].append({
            "case_id": "conflict-geometry-known__geometry",
            "field_type": "geometry",
            "scenario": "conflict-geometry-known",
            "node_type": "FRAME",
            "created": True,
            "rect": {"x": 0.0, "y": 0.0, "width": 10.0, "height": 10.0},
            "text": None,
            "fill": "#ffffff",
            "asset": None,
            "visibility": True,
            "placeholder": False,
            "marker": "DEFAULT ORIGIN",
        })
        return c, r, m, "disputed geometry was placed at the default origin"
    if mutation_id == "screenshot-color-promoted":
        cards["conflict-geometry-known__color"]["fill"] = "#0000ff"
        return c, r, m, "screenshot color was promoted to the only fill"
    if mutation_id == "skipped-counted-success":
        field = fields["skipped__asset"]
        field["state"] = "written"
        field["winner"] = "asset-out-of-scope"
        field["written_value"] = "asset-out-of-scope"
        field["release_eligible"] = True
        return c, r, m, "skipped field was counted as written"
    if mutation_id == "report-missing-key":
        del entries["RPT-visibility-unknown__text"]["unlock_condition"]
        return c, r, m, "report entry lost its unlock condition"
    if mutation_id == "manifest-report-status-mismatch":
        entries["RPT-visibility-unknown__color"]["state"] = "written"
        return c, r, m, "report state diverged from manifest state"
    if mutation_id == "written-without-winner":
        fields["control__text"]["winner"] = None
        return c, r, m, "written control lost its winner"
    if mutation_id == "tombstone-old-value-in-canvas":
        c["business_flow"]["cards"].append({
            "case_id": "old-value-tombstone__text",
            "field_type": "text",
            "scenario": "old-value-tombstone",
            "node_type": "TEXT",
            "created": True,
            "rect": known_rect(),
            "text": "旧价格 ¥59.00",
            "fill": "#ffffff",
            "asset": None,
            "visibility": True,
            "placeholder": False,
            "marker": "OLD VALUE",
        })
        return c, r, m, "tombstoned old value was placed on the business canvas"
    if mutation_id == "report-inside-business-flow":
        r["outside_business_flow"] = False
        c["report_frame"]["outside_business_flow"] = False
        return c, r, m, "report frame was moved into the business flow"
    raise KeyError("unknown mutation: " + mutation_id)


def run_mutations(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    mutation_ids = [
        "candidate-text-in-body",
        "deferred-marked-written",
        "drop-report-entry",
        "manifest-only-write",
        "price-as-final",
        "retained-marked-verified",
        "unknown-visibility-node",
        "geometry-at-origin",
        "screenshot-color-promoted",
        "skipped-counted-success",
        "report-missing-key",
        "manifest-report-status-mismatch",
        "written-without-winner",
        "tombstone-old-value-in-canvas",
        "report-inside-business-flow",
    ]
    results = []
    for mutation_id in mutation_ids:
        c, r, m, description = mutate_once(mutation_id, baseline["canvas"], baseline["report"], baseline["manifest"])
        errors = validate_delivery(c, r, m)
        results.append({
            "mutation_id": mutation_id,
            "description": description,
            "rejected": bool(errors),
            "error_count": len(errors),
            "errors": errors[:8],
        })
    return results


def draw_matrix(manifest: dict[str, Any], path: Path) -> None:
    fig, (ax, bar) = plt.subplots(1, 2, figsize=(16, 8.5), gridspec_kw={"width_ratios": [3.2, 1.4]})
    ax.set_xlim(0, 5)
    ax.set_ylim(-0.5, 5)
    ax.set_xticks([0.5 + i for i in range(5)])
    ax.set_xticklabels([f.replace("-", "\n") for f in FIELD_TYPES], fontsize=10)
    ax.set_yticks([4.5 - i for i in range(5)])
    ax.set_yticklabels([s.replace("-", "\n") for s in SCENARIOS], fontsize=9)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fields = {field["case_id"]: field for field in manifest["fields"]}
    for row, scenario in enumerate(SCENARIOS):
        for col, field_type in enumerate(FIELD_TYPES):
            state = fields[scenario + "__" + field_type]["state"]
            patch = FancyBboxPatch((col + 0.05, 4 - row + 0.05), 0.9, 0.9, boxstyle="round,pad=0.02,rounding_size=0.05", facecolor=STATE_COLORS[state], edgecolor="#334155", linewidth=0.8)
            ax.add_patch(patch)
            ax.text(col + 0.5, 4.5 - row, STATE_LABELS[state], ha="center", va="center", fontsize=8, color="#0f172a")
    ax.set_title("R5-EXP-01  field x conflict scenario  (25 cells)", fontsize=14, pad=12)
    ax.text(2.5, -0.35, "All 25 conflict cells are unresolved; the five control fields are written separately.", ha="center", fontsize=9, color="#475569")

    counts = Counter(field["state"] for field in manifest["fields"])
    names = [state for state in STATE_ORDER if counts.get(state, 0)]
    values = [counts[state] for state in names]
    bar.barh([STATE_LABELS[s] for s in names][::-1], values[::-1], color=[STATE_COLORS[s] for s in names][::-1], edgecolor="#334155")
    for index, value in enumerate(values[::-1]):
        bar.text(value + 0.1, index, str(value), va="center", fontsize=9)
    bar.set_xlim(0, max(values) + 2)
    bar.set_title("State counts", fontsize=13)
    bar.set_xlabel("fields")
    bar.grid(axis="x", alpha=0.2)
    bar.spines["top"].set_visible(False)
    bar.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def draw_canvas(canvas: dict[str, Any], manifest: dict[str, Any], path: Path) -> None:
    fig, (left, right) = plt.subplots(1, 2, figsize=(22, 13), gridspec_kw={"width_ratios": [1.55, 1.0]})
    left.set_xlim(0, 5.3)
    left.set_ylim(-2.2, 7.2)
    left.axis("off")
    left.set_title("Business canvas: R5-EXP-01 PARTIAL", fontsize=15, loc="left")
    cards = {card["case_id"]: card for card in canvas["business_flow"]["cards"]}
    fields = {field["case_id"]: field for field in manifest["fields"]}
    for row, scenario in enumerate(SCENARIOS):
        for col, field_type in enumerate(FIELD_TYPES):
            case_id = scenario + "__" + field_type
            card = cards.get(case_id)
            state = fields[case_id]["state"]
            x = col + 0.05
            y = 6.0 - row * 1.15
            patch = FancyBboxPatch((x, y), 0.9, 0.95, boxstyle="round,pad=0.015,rounding_size=0.04", facecolor=STATE_COLORS[state], edgecolor="#334155", linewidth=0.7, linestyle="--" if card is None else "-")
            left.add_patch(patch)
            left.text(x + 0.45, y + 0.80, field_type, ha="center", va="center", fontsize=8, weight="bold")
            left.text(x + 0.45, y + 0.60, STATE_LABELS[state], ha="center", va="center", fontsize=7)
            if card is None:
                left.text(x + 0.45, y + 0.32, "DELAYED", ha="center", va="center", fontsize=8, color="#7f1d1d")
            else:
                value = card_value(card, field_type)
                display = "None" if value is None else (str(value)[:18] + ("..." if len(str(value)) > 18 else ""))
                left.text(x + 0.45, y + 0.34, "created", ha="center", va="center", fontsize=7, color="#065f46")
                left.text(x + 0.45, y + 0.17, display, ha="center", va="center", fontsize=6, color="#334155")
            left.text(x + 0.45, y - 0.10, card["marker"] if card else "NO NODE", ha="center", va="center", fontsize=5.5, color="#475569")
    left.text(0.1, -0.35, "Rows: conflict scenarios. Columns: field types. Dashed cells have no business node.", fontsize=9, color="#475569")

    # Controls strip.
    for index, field_type in enumerate(FIELD_TYPES):
        case_id = "control__" + field_type
        card = cards[case_id]
        state = fields[case_id]["state"]
        x = index + 0.05
        y = -1.55
        patch = FancyBboxPatch((x, y), 0.9, 0.95, boxstyle="round,pad=0.015,rounding_size=0.04", facecolor=STATE_COLORS[state], edgecolor="#334155", linewidth=0.8)
        left.add_patch(patch)
        left.text(x + 0.45, y + 0.76, "control " + field_type, ha="center", va="center", fontsize=7, weight="bold")
        left.text(x + 0.45, y + 0.50, "written", ha="center", va="center", fontsize=8, color="#065f46")
        value = card_value(card, field_type)
        left.text(x + 0.45, y + 0.24, str(value)[:20], ha="center", va="center", fontsize=5.5, color="#334155")
    left.text(0.1, -1.75, "Control fields: known, authoritative values are written to the canvas.", fontsize=9, color="#475569")

    right.set_xlim(0, 1)
    right.set_ylim(0, 1)
    right.axis("off")
    right.set_title("Conflicts / Unknowns report (outside business flow)", fontsize=14, loc="left")
    entries = canvas["report_frame"]["entry_ids"]
    right.text(0.0, 0.98, f"{len(entries)} entries; candidates and blocked actions are kept here", fontsize=9, color="#475569")
    y = 0.93
    step = 0.93 / max(1, len(entries))
    for entry_id in entries:
        # Look up from the manifest to avoid carrying a second report payload.
        field = next(f for f in manifest["fields"] if f.get("report_entry_id") == entry_id)
        color = STATE_COLORS[field["state"]]
        right.add_patch(Rectangle((0.0, y - step * 0.86), 0.015, step * 0.72, facecolor=color, edgecolor="none"))
        right.text(0.03, y - step * 0.18, entry_id.replace("RPT-", ""), fontsize=6.2, weight="bold", color="#0f172a")
        right.text(0.03, y - step * 0.45, STATE_LABELS[field["state"]] + " | " + field["current_display"][:72], fontsize=5.4, color="#334155")
        right.text(0.03, y - step * 0.68, "next: " + field["next_step"][:78], fontsize=5.0, color="#64748b")
        y -= step
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def draw_report(report: dict[str, Any], manifest: dict[str, Any], path: Path) -> None:
    entries = report["entries"]
    fig, ax = plt.subplots(figsize=(20, 12))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title("R5-EXP-01  Conflicts / Unknowns report", fontsize=16, loc="left")
    ax.text(0.0, 0.965, f"{len(entries)} entries; separate from the business flow; candidates are not final values.", fontsize=10, color="#475569")
    columns = [0.0, 0.18, 0.30, 0.45, 0.73, 0.87]
    headers = ["entry", "object / field", "state", "current display", "next step", "unlock"]
    for x, header in zip(columns, headers):
        ax.text(x, 0.94, header, fontsize=8, weight="bold", color="#0f172a")
    row_height = 0.90 / max(1, len(entries))
    for index, entry in enumerate(entries):
        y = 0.925 - index * row_height
        color = STATE_COLORS[entry["state"]]
        ax.add_patch(Rectangle((0.0, y - row_height * 0.78), 0.995, row_height * 0.72, facecolor=color, alpha=0.28, edgecolor="none"))
        ax.text(columns[0], y - row_height * 0.20, entry["entry_id"].replace("RPT-", ""), fontsize=6.2, weight="bold", va="top")
        ax.text(columns[1], y - row_height * 0.20, entry["object_id"][:28], fontsize=5.8, va="top")
        ax.text(columns[2], y - row_height * 0.20, STATE_LABELS[entry["state"]], fontsize=5.8, va="top")
        ax.text(columns[3], y - row_height * 0.20, entry["current_display"][:64], fontsize=5.4, va="top")
        ax.text(columns[4], y - row_height * 0.20, entry["next_step"][:56], fontsize=5.2, va="top")
        ax.text(columns[5], y - row_height * 0.20, entry["unlock_condition"][:34], fontsize=5.2, va="top")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def build_result() -> dict[str, Any]:
    delivery = build_delivery()
    canvas = delivery["canvas"]
    report = delivery["report"]
    manifest = delivery["manifest"]
    errors = validate_delivery(canvas, report, manifest)
    mutations = run_mutations(delivery)
    counts = manifest["counts"]["state_counts"]
    checks = [
        check("case-count", "33 cases: 25 conflict cells + 5 controls + 2 old-value cases + 1 skipped case", manifest["counts"]["total"] == 33, manifest["counts"]),
        check("conflict-matrix", "5 field types x 5 conflict scenarios", sum(1 for f in manifest["fields"] if f["scenario"] in SCENARIOS) == 25, {"conflict_cells": 25}),
        check("written-controls", "five authoritative control fields are written", manifest["counts"]["written"] == 5, {"written": manifest["counts"]["written"]}),
        check("unresolved-not-success", "deferred/skipped/authority-required are not counted as written", counts.get("deferred", 0) == 10 and counts.get("skipped", 0) == 1 and counts.get("authority-required", 0) == 5 and manifest["counts"]["written"] == 5, counts),
        check("report-manifest-consistency", "report entries and manifest fields agree", not errors, errors[:10]),
        check("candidate-leakage", "no candidate text/color/asset/geometry leaks into the business canvas", not any("leaked into the canvas" in error for error in errors), [e for e in errors if "leaked" in e]),
        check("price-leakage", "no authority-required price candidate appears on the business canvas", not any("price candidate leaked" in error for error in errors), [e for e in errors if "price" in e]),
        check("old-value-status", "retained-unverified and carried-forward-not-seen are explicit", counts.get("retained-unverified", 0) == 1 and counts.get("carried-forward-not-seen", 0) == 1, counts),
        check("tombstone", "tombstone cases do not carry the old value", all(f["state"] == "delete-pending" and f.get("retained_value") is None for f in manifest["fields"] if f["scenario"] == "old-value-tombstone"), {"tombstone_cases": 5}),
        check("mutations", "all negative mutations are rejected", all(item["rejected"] for item in mutations), {"rejected": sum(1 for item in mutations if item["rejected"]), "total": len(mutations)}),
    ]
    result = {
        "schema": "r5-exp-01/result/v1",
        "status": "completed-for-current-scope",
        "job": JOB,
        "revision": REVISION,
        "profile": PROFILE,
        "created_at": "2026-10-19T00:00:00+00:00",
        "summary": {
            "case_count": manifest["counts"]["total"],
            "conflict_cells": 25,
            "controls": 5,
            "written": manifest["counts"]["written"],
            "unresolved": manifest["counts"]["unresolved"],
            "report_entries": manifest["counts"]["report_entries"],
            "state_counts": counts,
            "checks_passed": sum(1 for item in checks if item["passed"]),
            "checks_total": len(checks),
            "mutations_rejected": sum(1 for item in mutations if item["rejected"]),
            "mutations_total": len(mutations),
        },
        "canvas": canvas,
        "report": report,
        "manifest": manifest,
        "checks": checks,
        "mutations": mutations,
        "limitations": [
            "This is an offline deterministic contract experiment; it does not connect to Figma.",
            "The canvas is a model of a delivery, not a real Figma frame; the PNG is a visualization of the model.",
            "The 5 x 5 matrix is a controlled fixture, not a sample of real sites, fields or user comprehension.",
            "The report and manifest are JSON models; no real Figma report frame or comment was written.",
            "The experiment does not prove that users will understand the markers or that the candidate values are correct.",
            "The experiment does not cover real permission, rate-limit, user modification, cross-version or production concurrency behavior.",
            "The experiment does not establish a production writer contract; it only rejects the listed negative mutations.",
        ],
        "not_claimed": [
            "real Figma delivery of the 25-case matrix",
            "user comprehension of the report or markers",
            "production conflict resolution",
            "final price correctness",
            "pixel or visual acceptance",
            "cross-browser or cross-version behavior",
        ],
        "hash_note": "content_hash covers the complete result document except itself; canvas/report/manifest are embedded.",
    }
    result["content_hash"] = content_hash(result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_r5_experiments/r5_exp_01_conflict_delivery")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    result = build_result()
    atomic_write_json(out_root / "result.json", result)
    atomic_write_json(out_root / "canvas.json", result["canvas"])
    atomic_write_json(out_root / "report.json", result["report"])
    atomic_write_json(out_root / "manifest.json", result["manifest"])
    atomic_write_json(out_root / "mutations.json", result["mutations"])
    draw_matrix(result["manifest"], out_root / "r5_exp_01_matrix.png")
    draw_canvas(result["canvas"], result["manifest"], out_root / "r5_exp_01_delivery_canvas.png")
    draw_report(result["report"], result["manifest"], out_root / "r5_exp_01_report.png")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print("status=" + result["status"])
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] == "completed-for-current-scope" else 1


if __name__ == "__main__":
    raise SystemExit(main())
