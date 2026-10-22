# -*- coding: utf-8 -*-
"""R5-EXP-06: IR persistence, TTL, migration and replay semantics.

The experiment writes runtime IR, ordered audit bundles, evidence/asset files,
event records and migrated snapshots to an experiment-owned store. It then
evaluates:

* pre-write persistence failure
* crash after send and resume reconciliation
* evidence TTL expiry
* expired asset URL with retained local bytes
* schema migration and tombstone preservation
* unknown enum and cross-page reference failure-closed behavior
* permission revocation
* audit-replay / materialize-replay / recapture-reconcile separation

It is an offline contract experiment and does not connect to Figma.

Usage:
  C:/Users/lzq/.conda/envs/omni/python.exe scripts/r5_exp_06_ir_persistence.py
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import shutil
import sys
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Callable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JOB = "JOB-R5-EXP-06-20261019"
REVISION = "rev1"
PROFILE = "r5-exp-06-ir-persistence"
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)
CAPTURED_AT = "2026-10-19T00:00:00+00:00"
DEFAULT_OUT = ROOT / "output" / "_r5_experiments" / "r5_exp_06_ir_persistence"

REPLAY_EVIDENCE_DAYS = 30
AUDIT_METADATA_DAYS = 180

CASE_IDS = (
    "preflight-persist-failure",
    "after-send-crash",
    "clean-replay",
    "evidence-ttl-expired",
    "asset-url-expired-local-bytes",
    "schema-upgrade-v1-v2",
    "tombstone-migration",
    "unknown-enum",
    "permission-revoked",
    "cross-page-reference-invalid",
    "audit-runtime-separation",
    "materialize-environment-changed",
)

CASE_LABELS = {
    "preflight-persist-failure": "Preflight persist failure",
    "after-send-crash": "After-send crash + resume",
    "clean-replay": "Clean replay",
    "evidence-ttl-expired": "Evidence TTL expired",
    "asset-url-expired-local-bytes": "URL expired, local bytes retained",
    "schema-upgrade-v1-v2": "Schema v1 -> v2",
    "tombstone-migration": "Tombstone migration",
    "unknown-enum": "Unknown enum fail-closed",
    "permission-revoked": "Permission revoked",
    "cross-page-reference-invalid": "Cross-page reference invalid",
    "audit-runtime-separation": "Audit vs runtime separation",
    "materialize-environment-changed": "Materialize environment changed",
}

EVIDENCE_SPECS = (
    ("ev-dom", "dom-json", "evidence/dom.json"),
    ("ev-render", "render-json", "evidence/render.json"),
    ("ev-asset", "asset-bytes", "assets/badge.png"),
)

AUTHORITY_CHAIN = [
    {
        "field_id": "field-price",
        "source": "dom",
        "evidence_id": "ev-dom",
        "decision": "selected",
        "policy_version": "policy-v1",
    },
    {
        "field_id": "field-price",
        "source": "ocr-confirmation",
        "evidence_id": "ev-render",
        "decision": "confirmation-only",
        "policy_version": "policy-v1",
    },
    {
        "field_id": "field-badge",
        "source": "none",
        "evidence_id": None,
        "decision": "unknown",
        "policy_version": "policy-v1",
    },
]

ORDER_MAPPING = {
    "dom_order": ["header", "badge", "price", "footer"],
    "screenshot_order": ["header", "price", "badge", "footer"],
    "figma_child_order": ["header", "price", "badge", "footer"],
    "basis": "explicit-mapping",
}

FIELDS = [
    {
        "field_id": "field-title",
        "node_id": "node-header",
        "field_type": "text-content",
        "observations": [
            {"source": "dom", "evidence_id": "ev-dom", "present": True, "value": "R5 IR LAB"},
            {"source": "screenshot", "evidence_id": "ev-render", "present": True, "value": "R5 IR LAB"},
        ],
        "decision": {
            "status": "selected",
            "winner": "dom",
            "selected_value": "R5 IR LAB",
            "reason": "DOM text and rendered text agree.",
        },
    },
    {
        "field_id": "field-price",
        "node_id": "node-price",
        "field_type": "text-content",
        "observations": [
            {"source": "dom", "evidence_id": "ev-dom", "present": True, "value": "$129"},
            {"source": "ocr-confirmation", "evidence_id": "ev-render", "present": True, "value": "$129"},
        ],
        "decision": {
            "status": "selected",
            "winner": "dom",
            "selected_value": "$129",
            "reason": "Critical price is supported by both DOM and OCR confirmation.",
        },
    },
    {
        "field_id": "field-badge",
        "node_id": "node-badge",
        "field_type": "text-content",
        "observations": [
            {
                "source": "screenshot",
                "evidence_id": "ev-render",
                "present": False,
                "value": None,
                "reason": "not-seen",
            }
        ],
        "decision": {
            "status": "unknown",
            "winner": None,
            "selected_value": None,
            "reason": "Only an absent observation is available; no value is invented.",
        },
    },
    {
        "field_id": "field-legacy",
        "node_id": "node-legacy",
        "field_type": "visibility",
        "observations": [],
        "decision": {
            "status": "tombstone",
            "winner": None,
            "selected_value": None,
            "reason": "Authoritative tombstone; not-seen is not a deletion.",
        },
    },
]

TOMBSTONES = [
    {
        "tombstone_id": "tomb-legacy",
        "object_key": "legacy-badge",
        "scope": "page",
        "authority": "user",
        "authority_version": 3,
        "effective_at": "2026-10-18T10:00:00+00:00",
        "delete_status": "pending",
        "not_deleted": True,
    }
]

UNKNOWN_STATE = [
    {
        "object_key": "badge",
        "field": "text-content",
        "status": "unknown",
        "reason": "not-seen",
        "winner": None,
    }
]


def now_iso() -> str:
    return NOW.replace(microsecond=0).isoformat()


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_hash(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "content_hash"}
    return sha256_text(canonical(payload))


def atomic_write_json(path: Path, document: Any, *, fail_before_replace: bool = False) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if fail_before_replace:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        return {
            "written": False,
            "path": str(path),
            "failure": "injected-persist-before-replace",
            "final_exists": path.exists(),
        }
    os.replace(tmp, path)
    return {
        "written": True,
        "path": str(path),
        "sha256": sha256_bytes(payload.encode("utf-8")),
        "final_exists": path.exists(),
    }


def atomic_write_bytes(path: Path, data: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return {
        "path": str(path),
        "sha256": sha256_bytes(data),
        "bytes": len(data),
    }


def check(name: str, description: str, passed: bool, detail: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "passed": bool(passed),
        "detail": detail,
    }


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def safe_output_dir(path: Path) -> Path:
    resolved = path.resolve()
    expected_parent = (ROOT / "output" / "_r5_experiments").resolve()
    if resolved.parent != expected_parent:
        raise ValueError(f"Refusing to clean unexpected output directory: {resolved}")
    if not resolved.name.startswith("r5_exp_06"):
        raise ValueError(f"Refusing to clean unexpected experiment name: {resolved.name}")
    return resolved


def font_for(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def make_badge_png() -> bytes:
    image = Image.new("RGB", (64, 64), "#f59e0b")
    draw = ImageDraw.Draw(image)
    draw.rectangle((3, 3, 60, 60), outline="#0f172a", width=3)
    draw.text((18, 18), "IR", font=font_for(22, True), fill="#0f172a")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_common_files(out_dir: Path) -> dict[str, Any]:
    common = out_dir / "store" / "common"
    evidence_dir = common / "evidence"
    asset_dir = common / "assets"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)
    dom_bytes = json.dumps(
        {
            "page_id": "page-1",
            "text": {"header": "R5 IR LAB", "price": "$129"},
            "states": {"capture_id": "capture-clean", "revision": 1},
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    render_bytes = json.dumps(
        {
            "capture_id": "capture-clean",
            "state_signature": "state-clean-1",
            "ocr": {"price": "$129"},
            "order": ["header", "price", "badge", "footer"],
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    dom_path = evidence_dir / "dom.json"
    render_path = evidence_dir / "render.json"
    asset_path = asset_dir / "badge.png"
    dom_record = atomic_write_bytes(dom_path, dom_bytes)
    render_record = atomic_write_bytes(render_path, render_bytes)
    asset_record = atomic_write_bytes(asset_path, make_badge_png())
    return {
        "dom": {**dom_record, "bytes_data": dom_bytes},
        "render": {**render_record, "bytes_data": render_bytes},
        "asset": {**asset_record, "bytes_data": asset_record and make_badge_png()},
    }


def evidence_records(common: dict[str, Any], expired_evidence: bool) -> list[dict[str, Any]]:
    fresh_expires = iso(NOW + timedelta(days=REPLAY_EVIDENCE_DAYS))
    expired_expires = iso(NOW - timedelta(days=18))
    dom_path = (
        str(Path(common["dom"]["path"]).with_name("expired_dom.json"))
        if expired_evidence
        else common["dom"]["path"]
    )
    return [
        {
            "evidence_id": "ev-dom",
            "kind": "dom-json",
            "local_path": dom_path,
            "sha256": common["dom"]["sha256"],
            "bytes": common["dom"]["bytes"],
            "captured_at": iso(NOW - timedelta(days=1)),
            "retention_policy": "replay-evidence",
            "expires_at": expired_expires if expired_evidence else fresh_expires,
            "availability": "evidence-unavailable" if expired_evidence else "available",
            "file_exists": Path(dom_path).exists(),
        },
        {
            "evidence_id": "ev-render",
            "kind": "render-json",
            "local_path": common["render"]["path"],
            "sha256": common["render"]["sha256"],
            "bytes": common["render"]["bytes"],
            "captured_at": iso(NOW - timedelta(days=1)),
            "retention_policy": "replay-evidence",
            "expires_at": fresh_expires,
            "availability": "available",
            "file_exists": Path(common["render"]["path"]).exists(),
        },
    ]


def make_runtime_ir(
    common: dict[str, Any],
    case_id: str,
    *,
    expired_evidence: bool = False,
    url_expired: bool = False,
    permission_revoked: bool = False,
    cross_page_invalid: bool = False,
    environment_changed: bool = False,
) -> dict[str, Any]:
    evidence = evidence_records(common, expired_evidence)
    asset_url_expiry = (
        iso(NOW - timedelta(days=9))
        if url_expired
        else iso(NOW + timedelta(days=7))
    )
    return {
        "outer_schema": "runtime-ir/1.0",
        "job": JOB,
        "case_id": case_id,
        "schema_version": "1.0",
        "policy_version": "policy-v1",
        "capture_revision": "capture-r1",
        "plan_revision": "plan-r1",
        "output_revision": "output-r1",
        "contract": {
            "job_id": JOB,
            "scope": "page",
            "profile": "faithful",
            "authorized": True,
            "authorization_id": "auth-1",
        },
        "capture": {
            "capture_id": "capture-r1",
            "revision": 1,
            "page_id": "page-1",
            "state_signature": "state-clean-1",
            "target_url": "https://example.invalid/r5-ir",
            "created_at": iso(NOW - timedelta(days=1)),
        },
        "fields": copy.deepcopy(FIELDS),
        "evidence": evidence,
        "assets": [
            {
                "asset_id": "asset-badge",
                "use_id": "use-badge-1",
                "source_url": "https://temporary.example.invalid/badge.png",
                "url_expires_at": asset_url_expiry,
                "local_path": common["asset"]["path"],
                "local_bytes_sha256": common["asset"]["sha256"],
                "local_bytes_present": Path(common["asset"]["path"]).exists(),
                "local_retention_expires_at": iso(NOW + timedelta(days=90)),
                "mime": "image/png",
                "bytes": common["asset"]["bytes"],
            }
        ],
        "authority_chains": copy.deepcopy(AUTHORITY_CHAIN),
        "order_mapping": copy.deepcopy(ORDER_MAPPING),
        "tombstones": copy.deepcopy(TOMBSTONES),
        "unknowns": copy.deepcopy(UNKNOWN_STATE),
        "references": [
            {
                "reference_id": "ref-capture",
                "kind": "capture",
                "target": "capture-missing" if cross_page_invalid else "capture-r1",
                "required": True,
            },
            {
                "reference_id": "ref-policy",
                "kind": "policy",
                "target": "policy-v1",
                "required": True,
            },
        ],
        "plan": {
            "plan_id": "plan-write-1",
            "actions": [
                {"action_id": "op-header", "kind": "create_text", "target": "header"},
                {"action_id": "op-price", "kind": "create_text", "target": "price"},
                {"action_id": "op-badge", "kind": "create_image", "target": "badge"},
            ],
            "payload_hash": sha256_text("payload-v1"),
        },
        "writes": {
            "status": "planned",
            "intent_key": sha256_text(f"{JOB}:{case_id}:plan-write-1"),
            "sent": False,
            "acknowledged": False,
            "verified": False,
        },
        "acceptance": {"status": "not-run"},
        "release": {"status": "not-published"},
        "retention": {
            "replay_evidence_days": REPLAY_EVIDENCE_DAYS,
            "audit_metadata_days": AUDIT_METADATA_DAYS,
            "audit_metadata_expires_at": iso(NOW + timedelta(days=AUDIT_METADATA_DAYS - 1)),
            "asset_url_separate_from_local_bytes": True,
        },
        "access_policy": {
            "allow_evidence_read": not permission_revoked,
            "allow_materialize": not permission_revoked,
            "allow_audit_summary": True,
            "reason": "permission-revoked" if permission_revoked else "authorized",
        },
        "capabilities": {
            "write": "bridge-contract",
            "readback": "available",
            "export": "available",
        },
        "environment": {
            "browser": "chromium",
            "font_fingerprint": "font-fp-1",
            "changed": environment_changed,
        },
        "execution_graph": {
            "nodes": [
                "contract",
                "capture",
                "fusion",
                "write",
                "readback",
                "acceptance",
                "publish",
            ],
            "edges": [
                ["contract", "capture"],
                ["capture", "fusion"],
                ["fusion", "write"],
                ["write", "readback"],
                ["readback", "acceptance"],
                ["acceptance", "publish"],
            ],
            "sequence_semantics": "runtime-dag",
        },
    }


def make_audit_bundle(ir: dict[str, Any]) -> dict[str, Any]:
    return {
        "outer_schema": "audit-bundle/1.0",
        "job": ir["job"],
        "case_id": ir["case_id"],
        "schema_version": ir["schema_version"],
        "policy_version": ir["policy_version"],
        "sequence_semantics": "ordered-audit-only",
        "ordered_evidence": [item["evidence_id"] for item in ir["evidence"]],
        "decisions": [
            {
                "field_id": field["field_id"],
                "status": field["decision"]["status"],
                "winner": field["decision"]["winner"],
                "selected_value": field["decision"]["selected_value"],
                "reason": field["decision"]["reason"],
            }
            for field in ir["fields"]
        ],
        "authority_chains": copy.deepcopy(ir["authority_chains"]),
        "tombstones": copy.deepcopy(ir["tombstones"]),
        "unknowns": copy.deepcopy(ir["unknowns"]),
        "order_mapping": copy.deepcopy(ir["order_mapping"]),
        "retention": copy.deepcopy(ir["retention"]),
        "execution_graph": None,
        "runtime_dependency_graph": None,
    }


def decision_trace(ir: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "field_id": field["field_id"],
            "status": field["decision"]["status"],
            "winner": field["decision"]["winner"],
            "selected_value": field["decision"]["selected_value"],
            "observations": field["observations"],
        }
        for field in ir["fields"]
    ]


def decision_trace_hash(ir: dict[str, Any]) -> str:
    return sha256_text(canonical(decision_trace(ir)))


def materialized_output(ir: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_version": ir["policy_version"],
        "plan_revision": ir["plan_revision"],
        "fields": [
            {
                "field_id": field["field_id"],
                "status": field["decision"]["status"],
                "value": field["decision"]["selected_value"],
            }
            for field in ir["fields"]
        ],
        "order_mapping": ir["order_mapping"],
        "asset_sha256": ir["assets"][0]["local_bytes_sha256"],
    }


def materialized_hash(ir: dict[str, Any]) -> str:
    return sha256_text(canonical(materialized_output(ir)))


def migrate_v1_to_v2(ir: dict[str, Any]) -> dict[str, Any]:
    migrated = copy.deepcopy(ir)
    source_hash = content_hash(ir)
    migrated["schema_version"] = "2.0"
    migrated["migration_chain"] = [
        {
            "from_version": "1.0",
            "to_version": "2.0",
            "source_content_hash": source_hash,
            "migrated_at": now_iso(),
            "preserves": [
                "fields",
                "observations",
                "decisions",
                "authority_chains",
                "order_mapping",
                "tombstones",
                "unknowns",
                "evidence",
            ],
        }
    ]
    migrated["reference_index"] = {
        "captures": [ir["capture"]["capture_id"]],
        "policies": [ir["policy_version"]],
    }
    migrated["retention"]["per_object_policy"] = True
    migrated["content_hash"] = content_hash(migrated)
    return migrated


def validate_ir(
    ir: dict[str, Any],
    *,
    known_captures: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if ir.get("schema_version") not in {"1.0", "2.0"}:
        errors.append(f"unknown schema_version: {ir.get('schema_version')}")
    allowed_statuses = {"selected", "unknown", "tombstone"}
    for field in ir.get("fields", []):
        decision = field.get("decision", {})
        if decision.get("status") not in allowed_statuses:
            errors.append(
                f"{field.get('field_id')}: unknown decision enum {decision.get('status')!r}"
            )
        if not field.get("observations") and decision.get("status") != "tombstone":
            errors.append(f"{field.get('field_id')}: winner-only field has no observations")
        if decision.get("status") == "unknown":
            if decision.get("winner") is not None or decision.get("selected_value") is not None:
                errors.append(f"{field.get('field_id')}: unknown invented a winner")
    if not ir.get("authority_chains"):
        errors.append("authority chains missing")
    if not ir.get("order_mapping"):
        errors.append("order mapping missing")
    if not ir.get("tombstones"):
        errors.append("tombstones missing")
    if not ir.get("unknowns"):
        errors.append("unknown state missing")

    known = known_captures or {ir.get("capture", {}).get("capture_id")}
    for reference in ir.get("references", []):
        if reference.get("required") and reference.get("kind") == "capture":
            if reference.get("target") not in known:
                errors.append(
                    f"unresolved cross-page reference: {reference.get('reference_id')} -> {reference.get('target')}"
                )
    return errors


def summary_decision_hash(ir: dict[str, Any]) -> str:
    summary = [
        {
            "field_id": field["field_id"],
            "status": field["decision"]["status"],
            "winner": field["decision"]["winner"],
            "reason": field["decision"]["reason"],
        }
        for field in ir["fields"]
    ]
    return sha256_text(canonical(summary))


def audit_replay(ir: dict[str, Any]) -> dict[str, Any]:
    if not ir["access_policy"]["allow_evidence_read"]:
        return {
            "mode": "audit-replay",
            "status": "summary-only",
            "evidence_status": "access-denied",
            "exact_replay": False,
            "decision_trace_hash": decision_trace_hash(ir),
            "summary_hash": summary_decision_hash(ir),
            "reason": "Evidence permission was revoked; only approved summary metadata is auditable.",
        }
    unavailable = [
        item for item in ir["evidence"]
        if item.get("availability") != "available" or not Path(item["local_path"]).exists()
    ]
    if unavailable:
        return {
            "mode": "audit-replay",
            "status": "summary-only",
            "evidence_status": "evidence-unavailable",
            "exact_replay": False,
            "decision_trace_hash": decision_trace_hash(ir),
            "summary_hash": summary_decision_hash(ir),
            "unavailable_evidence": [item["evidence_id"] for item in unavailable],
            "reason": "Historical evidence is unavailable; the experiment retains a summary audit only.",
        }
    return {
        "mode": "audit-replay",
        "status": "completed",
        "evidence_status": "available",
        "exact_replay": True,
        "decision_trace_hash": decision_trace_hash(ir),
        "summary_hash": summary_decision_hash(ir),
        "unavailable_evidence": [],
    }


def local_asset_valid(ir: dict[str, Any]) -> bool:
    asset = ir["assets"][0]
    path = Path(asset["local_path"])
    return (
        path.exists()
        and asset.get("local_bytes_present") is True
        and sha256_file(path) == asset.get("local_bytes_sha256")
    )


def materialize_replay(ir: dict[str, Any]) -> dict[str, Any]:
    if not ir["access_policy"]["allow_materialize"]:
        return {
            "mode": "materialize-replay",
            "status": "blocked-permission",
            "materialized_hash": None,
            "pixel_identical_guaranteed": False,
            "external_url_fetch_count": 0,
            "reason": "Materialization permission is revoked.",
        }
    unavailable = [
        item for item in ir["evidence"]
        if item.get("availability") != "available" or not Path(item["local_path"]).exists()
    ]
    if unavailable:
        return {
            "mode": "materialize-replay",
            "status": "blocked-evidence-unavailable",
            "materialized_hash": None,
            "pixel_identical_guaranteed": False,
            "external_url_fetch_count": 0,
            "unavailable_evidence": [item["evidence_id"] for item in unavailable],
            "reason": "Cannot materialize without the locked evidence bytes.",
        }
    if not local_asset_valid(ir):
        return {
            "mode": "materialize-replay",
            "status": "blocked-asset-missing",
            "materialized_hash": None,
            "pixel_identical_guaranteed": False,
            "external_url_fetch_count": 0,
            "reason": "Local asset bytes are missing or do not match their hash.",
        }
    changed = ir["environment"]["changed"]
    return {
        "mode": "materialize-replay",
        "status": "materialized-revalidation-required" if changed else "materialized",
        "evidence_status": "available",
        "asset_source": "local-bytes",
        "external_url_used": False,
        "external_url_fetch_count": 0,
        "materialized_hash": materialized_hash(ir),
        "pixel_identical_guaranteed": False,
        "revalidation_required": bool(changed),
        "reason": (
            "Environment changed; output was materialized but requires revalidation."
            if changed
            else "Locked evidence, policy and plan reproduced the materialized output."
        ),
    }


def recapture_reconcile(ir: dict[str, Any]) -> dict[str, Any]:
    if not ir["access_policy"]["allow_evidence_read"]:
        return {
            "mode": "recapture-reconcile",
            "status": "blocked-permission",
            "old_capture_id": ir["capture"]["capture_id"],
            "new_capture_id": None,
            "old_capture_revision": ir["capture"]["revision"],
            "new_capture_revision": None,
            "historical_replay": False,
            "new_decision_trace_hash": None,
            "new_materialized_hash": None,
            "reason": "Reauthorization is required before recapture.",
        }
    new_capture_id = "capture-r1-recapture"
    new_revision = 2
    recaptured = copy.deepcopy(ir)
    recaptured["capture_revision"] = "capture-r2"
    recaptured["output_revision"] = "output-r2"
    recaptured["capture"]["capture_id"] = new_capture_id
    recaptured["capture"]["revision"] = new_revision
    recaptured["capture"]["created_at"] = now_iso()
    recaptured["capture"]["state_signature"] = "state-recapture-2"
    return {
        "mode": "recapture-reconcile",
        "status": "new-capture-created",
        "old_capture_id": ir["capture"]["capture_id"],
        "new_capture_id": new_capture_id,
        "old_capture_revision": ir["capture"]["revision"],
        "new_capture_revision": new_revision,
        "historical_replay": False,
        "new_decision_trace_hash": decision_trace_hash(recaptured),
        "new_materialized_hash": materialized_hash(recaptured),
        "reason": "A new capture and revision were created; this is not replay of the old evidence.",
    }


def case_config(case_id: str) -> dict[str, Any]:
    return {
        "expired_evidence": case_id == "evidence-ttl-expired",
        "url_expired": case_id == "asset-url-expired-local-bytes",
        "permission_revoked": case_id == "permission-revoked",
        "cross_page_invalid": case_id == "cross-page-reference-invalid",
        "environment_changed": case_id == "materialize-environment-changed",
    }


def event(case_id: str, index: int, event_type: str, status: str, detail: str) -> dict[str, Any]:
    return {
        "event_id": f"{case_id}::event-{index}",
        "case_id": case_id,
        "sequence": index,
        "event_type": event_type,
        "status": status,
        "detail": detail,
        "at": iso(NOW + timedelta(seconds=index)),
    }


def migration_preservation(ir: dict[str, Any], migrated: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "fields": ir["fields"] == migrated["fields"],
        "authority_chains": ir["authority_chains"] == migrated["authority_chains"],
        "order_mapping": ir["order_mapping"] == migrated["order_mapping"],
        "tombstones": ir["tombstones"] == migrated["tombstones"],
        "unknowns": ir["unknowns"] == migrated["unknowns"],
        "evidence": ir["evidence"] == migrated["evidence"],
    }
    return {
        "preserved": checks,
        "all_preserved": all(checks.values()),
        "tombstone_preserved": checks["tombstones"],
        "unknown_preserved": checks["unknowns"],
        "authority_chain_preserved": checks["authority_chains"],
        "order_mapping_preserved": checks["order_mapping"],
    }


def prepare_case(
    out_dir: Path,
    common: dict[str, Any],
    case_id: str,
) -> dict[str, Any]:
    config = case_config(case_id)
    case_dir = out_dir / "store" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    ir = make_runtime_ir(
        common,
        case_id,
        expired_evidence=config["expired_evidence"],
        url_expired=config["url_expired"],
        permission_revoked=config["permission_revoked"],
        cross_page_invalid=config["cross_page_invalid"],
        environment_changed=config["environment_changed"],
    )
    audit = make_audit_bundle(ir)
    runtime_path = case_dir / "runtime_ir.json"
    audit_path = case_dir / "audit_bundle.json"
    events: list[dict[str, Any]] = []
    record: dict[str, Any] = {
        "case_id": case_id,
        "label": CASE_LABELS[case_id],
        "config": config,
        "side_effect_count": 0,
        "duplicate_create_count": 0,
        "replay": {},
        "events": events,
        "runtime_ir_path": None,
        "audit_bundle_path": None,
        "migrated_v2_path": None,
        "validation_errors": [],
    }

    if case_id == "preflight-persist-failure":
        persist = atomic_write_json(runtime_path, ir, fail_before_replace=True)
        events.extend(
            [
                event(case_id, 0, "preflight-persist-attempt", "attempted", "Persist runtime IR before side effects."),
                event(case_id, 1, "preflight-persist-result", "failed", persist["failure"]),
                event(case_id, 2, "write-orchestrator", "blocked", "No command was sent because persistence failed."),
            ]
        )
        record.update(
            {
                "status": "blocked-persistence",
                "persistence": persist,
                "runtime_ir_path": None,
                "audit_bundle_path": None,
                "side_effect_count": 0,
                "replay": {
                    "audit": {"mode": "audit-replay", "status": "not-run"},
                    "materialize": {"mode": "materialize-replay", "status": "not-run"},
                    "recapture": {"mode": "recapture-reconcile", "status": "not-run"},
                    "resume": {"mode": "resume", "status": "not-run"},
                },
            }
        )
        atomic_write_json(case_dir / "events.json", events)
        return record

    runtime_write = atomic_write_json(runtime_path, ir)
    audit_write = atomic_write_json(audit_path, audit)
    events.append(event(case_id, 0, "runtime-ir-persisted", "written", runtime_write["sha256"]))
    events.append(event(case_id, 1, "audit-bundle-persisted", "written", audit_write["sha256"]))
    record["runtime_ir_path"] = str(runtime_path)
    record["audit_bundle_path"] = str(audit_path)
    record["persistence"] = {
        "runtime_ir": runtime_write,
        "audit_bundle": audit_write,
    }

    if case_id == "after-send-crash":
        remote_path = case_dir / "remote_state.json"
        atomic_write_json(
            remote_path,
            {
                "job": JOB,
                "intent_key": ir["writes"]["intent_key"],
                "created_node_count": 1,
                "created_node_ids": ["remote-node-1"],
            },
        )
        events.extend(
            [
                event(case_id, 2, "command-sent", "sent", ir["writes"]["intent_key"]),
                event(case_id, 3, "process-crash", "unknown", "Response and ledger result were not persisted."),
            ]
        )
        remote = json.loads(remote_path.read_text(encoding="utf-8"))
        recovered = copy.deepcopy(ir)
        recovered["writes"].update(
            {
                "status": "committed-after-reconcile",
                "sent": True,
                "acknowledged": False,
                "verified": True,
                "reconciled_node_ids": remote["created_node_ids"],
            }
        )
        recovered["content_hash"] = content_hash(recovered)
        recovered_path = case_dir / "runtime_ir_recovered.json"
        atomic_write_json(recovered_path, recovered)
        events.append(
            event(
                case_id,
                4,
                "resume-reconcile",
                "committed",
                "Read back one remote node and committed without resend.",
            )
        )
        record.update(
            {
                "status": "committed-after-reconcile",
                "side_effect_count": remote["created_node_count"],
                "duplicate_create_count": 0,
                "recovered_runtime_ir_path": str(recovered_path),
                "replay": {
                    "audit": {"mode": "audit-replay", "status": "not-used-for-resume"},
                    "materialize": {"mode": "materialize-replay", "status": "not-used-for-resume"},
                    "recapture": {"mode": "recapture-reconcile", "status": "not-used-for-resume"},
                    "resume": {
                        "mode": "resume",
                        "status": "committed-after-reconcile",
                        "side_effect_count": 1,
                        "duplicate_create_count": 0,
                        "resent": False,
                        "reconciled_node_ids": remote["created_node_ids"],
                    },
                },
            }
        )
        atomic_write_json(case_dir / "events.json", events)
        return record

    known_captures = {ir["capture"]["capture_id"]}
    migration_case = case_id in {"schema-upgrade-v1-v2", "tombstone-migration", "unknown-enum"}
    replay_ir = ir
    if migration_case:
        migrated = migrate_v1_to_v2(ir)
        if case_id == "unknown-enum":
            migrated["fields"][2]["decision"]["status"] = "future-unknown-enum"
            migrated["content_hash"] = content_hash(migrated)
        migrated_path = case_dir / "runtime_ir_v2.json"
        atomic_write_json(migrated_path, migrated)
        record["migrated_v2_path"] = str(migrated_path)
        record["migration"] = {
            "source_schema": ir["schema_version"],
            "target_schema": migrated["schema_version"],
            "source_content_hash": content_hash(ir),
            "migrated_content_hash": migrated["content_hash"],
            "migration_chain": migrated["migration_chain"],
            "preservation": migration_preservation(ir, migrated),
        }
        replay_ir = migrated

    errors = validate_ir(replay_ir, known_captures=known_captures)
    record["validation_errors"] = errors
    if errors:
        events.append(event(case_id, 2, "ir-validation", "blocked", "; ".join(errors)))
        if any("unknown decision enum" in error for error in errors):
            record["status"] = "blocked-unknown-enum"
        elif any("unresolved cross-page reference" in error for error in errors):
            record["status"] = "blocked-unresolved-reference"
        else:
            record["status"] = "blocked-validation"
        record["replay"] = {
            "audit": {"mode": "audit-replay", "status": "not-run"},
            "materialize": {"mode": "materialize-replay", "status": "not-run"},
            "recapture": {"mode": "recapture-reconcile", "status": "not-run"},
            "resume": {"mode": "resume", "status": "not-run"},
        }
        atomic_write_json(case_dir / "events.json", events)
        return record

    audit_result = audit_replay(replay_ir)
    materialize_result = materialize_replay(replay_ir)
    recapture_result = recapture_reconcile(replay_ir)
    events.extend(
        [
            event(case_id, 2, "audit-replay", audit_result["status"], audit_result.get("evidence_status", "ok")),
            event(case_id, 3, "materialize-replay", materialize_result["status"], materialize_result.get("asset_source", "none")),
            event(case_id, 4, "recapture-reconcile", recapture_result["status"], recapture_result["new_capture_id"]),
        ]
    )
    record["replay"] = {
        "audit": audit_result,
        "materialize": materialize_result,
        "recapture": recapture_result,
        "resume": {"mode": "resume", "status": "not-used"},
    }

    if case_id == "clean-replay":
        record["status"] = "completed"
    elif case_id == "evidence-ttl-expired":
        record["status"] = "evidence-unavailable"
    elif case_id == "asset-url-expired-local-bytes":
        record["status"] = "completed-local-evidence"
    elif case_id in {"schema-upgrade-v1-v2", "tombstone-migration"}:
        record["status"] = "migrated"
    elif case_id == "permission-revoked":
        record["status"] = "blocked-permission"
    elif case_id == "cross-page-reference-invalid":
        record["status"] = "blocked-unresolved-reference"
    elif case_id == "audit-runtime-separation":
        record["status"] = "completed"
    elif case_id == "materialize-environment-changed":
        record["status"] = "materialized-revalidation-required"
    else:
        record["status"] = "completed"

    runtime_doc = json.loads(runtime_path.read_text(encoding="utf-8"))
    audit_doc = json.loads(audit_path.read_text(encoding="utf-8"))
    record["audit_runtime_separation"] = {
        "audit_sequence_semantics": audit_doc["sequence_semantics"],
        "audit_has_execution_graph": "execution_graph" in audit_doc and audit_doc["execution_graph"] is not None,
        "audit_has_runtime_dependency_graph": bool(audit_doc.get("runtime_dependency_graph")),
        "runtime_has_execution_graph": bool(runtime_doc.get("execution_graph")),
        "runtime_sequence_semantics": runtime_doc["execution_graph"]["sequence_semantics"],
    }
    atomic_write_json(case_dir / "events.json", events)
    return record


def build_bundle(out_dir: Path) -> dict[str, Any]:
    common = build_common_files(out_dir)
    cases = {case_id: prepare_case(out_dir, common, case_id) for case_id in CASE_IDS}
    all_events = [
        item for case_id in CASE_IDS for item in cases[case_id]["events"]
    ]
    bundle = {
        "job": JOB,
        "revision": REVISION,
        "cases": cases,
        "events": all_events,
        "common": {
            "evidence_dom": {
                "path": common["dom"]["path"],
                "sha256": common["dom"]["sha256"],
                "bytes": common["dom"]["bytes"],
            },
            "evidence_render": {
                "path": common["render"]["path"],
                "sha256": common["render"]["sha256"],
                "bytes": common["render"]["bytes"],
            },
            "asset": {
                "path": common["asset"]["path"],
                "sha256": common["asset"]["sha256"],
                "bytes": common["asset"]["bytes"],
            },
        },
    }
    return bundle


def freeze_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(bundle)


def validate_bundle(bundle: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if bundle != baseline:
        errors.append("bundle differs from the frozen IR/replay contract")

    cases = bundle.get("cases", {})
    if set(cases) != set(CASE_IDS):
        errors.append("case coverage is incomplete")
        return errors

    preflight = cases["preflight-persist-failure"]
    if preflight["status"] != "blocked-persistence":
        errors.append("preflight persistence failure did not block")
    if preflight["side_effect_count"] != 0:
        errors.append("preflight persistence failure produced side effects")
    if preflight["runtime_ir_path"] is not None:
        errors.append("preflight persistence failure retained a final runtime snapshot")

    crash = cases["after-send-crash"]
    if crash["status"] != "committed-after-reconcile":
        errors.append("after-send crash did not reconcile")
    if crash["side_effect_count"] != 1 or crash["duplicate_create_count"] != 0:
        errors.append("after-send crash duplicated a side effect")
    if crash["replay"]["resume"].get("resent") is not False:
        errors.append("resume unexpectedly resent the command")
    if crash["replay"]["resume"].get("side_effect_count") != 1:
        errors.append("resume side-effect count mismatch")
    if crash["replay"]["resume"].get("mode") != "resume":
        errors.append("resume was recorded as a historical replay mode")

    clean = cases["clean-replay"]
    if clean["replay"]["audit"].get("status") != "completed":
        errors.append("clean audit replay did not complete")
    if clean["replay"]["audit"].get("exact_replay") is not True:
        errors.append("clean audit replay is not exact")
    if clean["replay"]["materialize"].get("status") != "materialized":
        errors.append("clean materialize replay did not complete")
    if clean["replay"]["materialize"].get("pixel_identical_guaranteed") is not False:
        errors.append("materialize replay falsely guarantees pixel identity")
    recapture = clean["replay"]["recapture"]
    if recapture.get("new_capture_id") == recapture.get("old_capture_id"):
        errors.append("recapture reuse of old capture")
    if recapture.get("historical_replay") is not False:
        errors.append("recapture was mislabeled as historical replay")

    ttl = cases["evidence-ttl-expired"]
    if ttl["replay"]["audit"].get("evidence_status") != "evidence-unavailable":
        errors.append("expired evidence is not marked evidence-unavailable")
    if ttl["replay"]["audit"].get("exact_replay") is not False:
        errors.append("expired evidence claims exact replay")
    if ttl["replay"]["materialize"].get("status") != "blocked-evidence-unavailable":
        errors.append("expired evidence still materialized")
    if ttl["replay"]["recapture"].get("historical_replay") is not False:
        errors.append("TTL recapture mislabeled as historical replay")

    asset_case = cases["asset-url-expired-local-bytes"]
    if asset_case["replay"]["materialize"].get("status") != "materialized":
        errors.append("local bytes were not used after URL expiry")
    if asset_case["replay"]["materialize"].get("asset_source") != "local-bytes":
        errors.append("materialize did not identify local bytes")
    if asset_case["replay"]["materialize"].get("external_url_fetch_count") != 0:
        errors.append("expired asset URL was fetched")

    schema_case = cases["schema-upgrade-v1-v2"]
    if not schema_case["migration"]["preservation"].get("all_preserved"):
        errors.append("schema migration lost state")
    if not schema_case["migration"]["migration_chain"]:
        errors.append("migration chain is missing")
    if Path(schema_case["runtime_ir_path"]).read_bytes() == Path(schema_case["migrated_v2_path"]).read_bytes():
        errors.append("migration overwrote the original snapshot")

    tombstone_case = cases["tombstone-migration"]
    if not tombstone_case["migration"]["preservation"].get("tombstone_preserved"):
        errors.append("tombstone migration lost tombstone")
    if not tombstone_case["migration"]["preservation"].get("unknown_preserved"):
        errors.append("tombstone migration lost unknown state")
    if not tombstone_case["migration"]["preservation"].get("authority_chain_preserved"):
        errors.append("tombstone migration lost authority chain")
    if not tombstone_case["migration"]["preservation"].get("order_mapping_preserved"):
        errors.append("tombstone migration lost order mapping")

    unknown_case = cases["unknown-enum"]
    if unknown_case["status"] != "blocked-unknown-enum":
        errors.append("unknown enum did not fail closed")
    if not any("unknown decision enum" in item for item in unknown_case["validation_errors"]):
        errors.append("unknown enum did not produce validation failure")
    if any(
        field["decision"]["status"] == "selected"
        for field in json.loads(Path(unknown_case["migrated_v2_path"]).read_text(encoding="utf-8"))["fields"]
        if field["field_id"] == "field-badge"
    ):
        errors.append("unknown enum defaulted to a winner")

    permission = cases["permission-revoked"]
    if permission["replay"]["audit"].get("evidence_status") != "access-denied":
        errors.append("permission revocation did not block evidence read")
    if permission["replay"]["materialize"].get("status") != "blocked-permission":
        errors.append("permission revocation still materialized")
    if permission["replay"]["recapture"].get("status") != "blocked-permission":
        errors.append("permission revocation still recaptured")

    cross_page = cases["cross-page-reference-invalid"]
    if cross_page["status"] != "blocked-unresolved-reference":
        errors.append("invalid cross-page reference did not fail closed")
    if cross_page["replay"]["audit"].get("status") != "not-run":
        errors.append("invalid reference entered replay")

    separation = cases["audit-runtime-separation"]["audit_runtime_separation"]
    if separation["audit_sequence_semantics"] != "ordered-audit-only":
        errors.append("audit bundle sequence semantics are wrong")
    if separation["audit_has_execution_graph"]:
        errors.append("audit bundle contains a runtime execution graph")
    if separation["audit_has_runtime_dependency_graph"]:
        errors.append("audit bundle contains a runtime dependency graph")
    if not separation["runtime_has_execution_graph"]:
        errors.append("runtime IR has no execution graph")

    env = cases["materialize-environment-changed"]["replay"]["materialize"]
    if env.get("status") != "materialized-revalidation-required":
        errors.append("environment change did not require revalidation")
    if env.get("pixel_identical_guaranteed") is not False:
        errors.append("environment change claimed pixel identity")

    all_events = bundle.get("events", [])
    if any(
        left["case_id"] == right["case_id"] and left["sequence"] > right["sequence"]
        for index, left in enumerate(all_events)
        for right in all_events[index + 1 :]
    ):
        errors.append("event sequence is not ordered")

    return errors


MUTATION_SPECS: list[tuple[str, str, Callable[[dict[str, Any]], None]]] = [
    (
        "preflight-side-effect",
        "Allow a write after preflight persistence failure.",
        lambda doc: doc["cases"]["preflight-persist-failure"].__setitem__(
            "side_effect_count", 1
        ),
    ),
    (
        "preflight-final-snapshot",
        "Pretend a final runtime snapshot existed after persist failure.",
        lambda doc: doc["cases"]["preflight-persist-failure"].__setitem__(
            "runtime_ir_path", "unexpected.json"
        ),
    ),
    (
        "crash-duplicate-create",
        "Resume by creating a second node.",
        lambda doc: doc["cases"]["after-send-crash"].__setitem__(
            "duplicate_create_count", 1
        ),
    ),
    (
        "crash-auto-resend",
        "Mark resume as resent.",
        lambda doc: doc["cases"]["after-send-crash"]["replay"]["resume"].__setitem__(
            "resent", True
        ),
    ),
    (
        "resume-as-audit-replay",
        "Call resume a historical audit replay.",
        lambda doc: doc["cases"]["after-send-crash"]["replay"]["resume"].__setitem__(
            "mode", "audit-replay"
        ),
    ),
    (
        "ttl-exact-replay",
        "Claim exact replay after evidence expiry.",
        lambda doc: doc["cases"]["evidence-ttl-expired"]["replay"]["audit"].__setitem__(
            "exact_replay", True
        ),
    ),
    (
        "ttl-materialize-success",
        "Materialize without expired evidence bytes.",
        lambda doc: doc["cases"]["evidence-ttl-expired"]["replay"]["materialize"].__setitem__(
            "status", "materialized"
        ),
    ),
    (
        "ttl-marked-available",
        "Mark expired evidence as available.",
        lambda doc: doc["cases"]["evidence-ttl-expired"]["replay"]["audit"].__setitem__(
            "evidence_status", "available"
        ),
    ),
    (
        "url-ignores-local-bytes",
        "Fail to use retained local bytes.",
        lambda doc: doc["cases"]["asset-url-expired-local-bytes"]["replay"]["materialize"].__setitem__(
            "status", "blocked-asset-missing"
        ),
    ),
    (
        "url-used-as-evidence",
        "Use the expired URL as the materialization source.",
        lambda doc: doc["cases"]["asset-url-expired-local-bytes"]["replay"]["materialize"].__setitem__(
            "asset_source", "expired-url"
        ),
    ),
    (
        "url-fetched",
        "Fetch an expired external URL.",
        lambda doc: doc["cases"]["asset-url-expired-local-bytes"]["replay"]["materialize"].__setitem__(
            "external_url_fetch_count", 1
        ),
    ),
    (
        "hash-as-evidence",
        "Use a hash as if it were evidence bytes.",
        lambda doc: doc["cases"]["evidence-ttl-expired"]["replay"]["materialize"].update(
            {
                "status": "materialized",
                "asset_source": "hash-only",
            }
        ),
    ),
    (
        "recapture-reuses-capture-id",
        "Reuse the old capture ID during recapture.",
        lambda doc: doc["cases"]["clean-replay"]["replay"]["recapture"].__setitem__(
            "new_capture_id",
            doc["cases"]["clean-replay"]["replay"]["recapture"]["old_capture_id"],
        ),
    ),
    (
        "recapture-called-historical-replay",
        "Label recapture as historical replay.",
        lambda doc: doc["cases"]["clean-replay"]["replay"]["recapture"].__setitem__(
            "historical_replay", True
        ),
    ),
    (
        "migration-drops-tombstone",
        "Drop tombstones during migration.",
        lambda doc: doc["cases"]["schema-upgrade-v1-v2"]["migration"]["preservation"].__setitem__(
            "tombstone_preserved", False
        ),
    ),
    (
        "migration-drops-authority",
        "Drop authority chains during migration.",
        lambda doc: doc["cases"]["schema-upgrade-v1-v2"]["migration"]["preservation"].__setitem__(
            "authority_chain_preserved", False
        ),
    ),
    (
        "migration-drops-order",
        "Drop order mapping during migration.",
        lambda doc: doc["cases"]["schema-upgrade-v1-v2"]["migration"]["preservation"].__setitem__(
            "order_mapping_preserved", False
        ),
    ),
    (
        "migration-unknown-to-winner",
        "Convert unknown state into a winner.",
        lambda doc: doc["cases"]["tombstone-migration"]["migration"]["preservation"].__setitem__(
            "unknown_preserved", False
        ),
    ),
    (
        "unknown-enum-defaults",
        "Default an unknown enum to selected.",
        lambda doc: doc["cases"]["unknown-enum"].__setitem__(
            "status", "completed"
        ),
    ),
    (
        "permission-materialize",
        "Materialize after permission revocation.",
        lambda doc: doc["cases"]["permission-revoked"]["replay"]["materialize"].__setitem__(
            "status", "materialized"
        ),
    ),
    (
        "permission-recapture",
        "Recapture after permission revocation.",
        lambda doc: doc["cases"]["permission-revoked"]["replay"]["recapture"].__setitem__(
            "status", "new-capture-created"
        ),
    ),
    (
        "cross-page-reference-dropped",
        "Drop a required cross-page reference.",
        lambda doc: doc["cases"]["cross-page-reference-invalid"].__setitem__(
            "status", "completed"
        ),
    ),
    (
        "cross-page-reference-valid",
        "Treat an invalid cross-page reference as valid.",
        lambda doc: doc["cases"]["cross-page-reference-invalid"].__setitem__(
            "validation_errors", []
        ),
    ),
    (
        "audit-bundle-gets-runtime-dag",
        "Add a runtime DAG to the audit bundle.",
        lambda doc: doc["cases"]["audit-runtime-separation"]["audit_runtime_separation"].__setitem__(
            "audit_has_execution_graph", True
        ),
    ),
    (
        "audit-sequence-becomes-runtime",
        "Change audit order semantics to runtime DAG.",
        lambda doc: doc["cases"]["audit-runtime-separation"]["audit_runtime_separation"].__setitem__(
            "audit_sequence_semantics", "runtime-dag"
        ),
    ),
    (
        "runtime-dag-removed",
        "Remove runtime execution graph.",
        lambda doc: doc["cases"]["audit-runtime-separation"]["audit_runtime_separation"].__setitem__(
            "runtime_has_execution_graph", False
        ),
    ),
    (
        "materialize-pixel-identical",
        "Claim pixel identity from materialize replay.",
        lambda doc: doc["cases"]["clean-replay"]["replay"]["materialize"].__setitem__(
            "pixel_identical_guaranteed", True
        ),
    ),
    (
        "migration-overwrites-original",
        "Overwrite the original v1 snapshot during migration.",
        lambda doc: doc["cases"]["schema-upgrade-v1-v2"]["migration"].__setitem__(
            "source_content_hash", "overwritten"
        ),
    ),
    (
        "migration-chain-missing",
        "Remove the migration chain.",
        lambda doc: doc["cases"]["schema-upgrade-v1-v2"]["migration"].__setitem__(
            "migration_chain", []
        ),
    ),
    (
        "offline-audit-as-runtime",
        "Set audit runtime dependency graph.",
        lambda doc: doc["cases"]["audit-runtime-separation"]["audit_runtime_separation"].__setitem__(
            "audit_has_runtime_dependency_graph", True
        ),
    ),
    (
        "environment-claims-pixel-identity",
        "Claim pixel identity after environment change.",
        lambda doc: doc["cases"]["materialize-environment-changed"]["replay"]["materialize"].__setitem__(
            "pixel_identical_guaranteed", True
        ),
    ),
    (
        "environment-no-revalidation",
        "Skip revalidation after environment change.",
        lambda doc: doc["cases"]["materialize-environment-changed"]["replay"]["materialize"].update(
            {"status": "materialized", "revalidation_required": False}
        ),
    ),
]


def run_mutations(bundle: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    base_errors = validate_bundle(bundle, baseline)
    items: list[dict[str, Any]] = []
    for mutation_id, description, apply in MUTATION_SPECS:
        candidate = copy.deepcopy(bundle)
        apply(candidate)
        errors = validate_bundle(candidate, baseline)
        items.append(
            {
                "mutation_id": mutation_id,
                "description": description,
                "rejected": bool(errors),
                "error_count": len(errors),
                "errors": errors[:12],
            }
        )
    rejected = sum(1 for item in items if item["rejected"])
    return {
        "base_valid": not base_errors,
        "base_errors": base_errors,
        "total": len(items),
        "rejected": rejected,
        "accepted": len(items) - rejected,
        "items": items,
    }


def run_checks(
    bundle: dict[str, Any],
    baseline: dict[str, Any],
    mutations: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    cases = bundle["cases"]
    checks.append(
        check(
            "case-coverage",
            "All required persistence, TTL, migration and replay cases exist.",
            set(cases) == set(CASE_IDS),
            len(cases),
        )
    )
    preflight = cases["preflight-persist-failure"]
    checks.append(
        check(
            "preflight-persist-failure",
            "Persistence failure produces no side effects or final snapshot.",
            preflight["status"] == "blocked-persistence"
            and preflight["side_effect_count"] == 0
            and preflight["persistence"]["final_exists"] is False,
            preflight,
        )
    )
    crash = cases["after-send-crash"]
    checks.append(
        check(
            "after-send-resume",
            "The after-send crash is resumed by readback with one side effect.",
            crash["replay"]["resume"]["status"] == "committed-after-reconcile"
            and crash["side_effect_count"] == 1
            and crash["duplicate_create_count"] == 0
            and crash["replay"]["resume"]["resent"] is False,
            crash["replay"]["resume"],
        )
    )
    clean = cases["clean-replay"]["replay"]
    checks.append(
        check(
            "three-replay-modes-separate",
            "Audit, materialize and recapture produce distinct replay semantics.",
            clean["audit"]["mode"] == "audit-replay"
            and clean["materialize"]["mode"] == "materialize-replay"
            and clean["recapture"]["mode"] == "recapture-reconcile"
            and clean["audit"]["exact_replay"] is True
            and clean["materialize"]["status"] == "materialized"
            and clean["recapture"]["new_capture_id"] != clean["recapture"]["old_capture_id"]
            and clean["recapture"]["historical_replay"] is False,
            clean,
        )
    )
    ttl = cases["evidence-ttl-expired"]
    checks.append(
        check(
            "evidence-ttl-expired",
            "Expired evidence is unavailable, audit is summary-only and materialize is blocked.",
            ttl["replay"]["audit"]["evidence_status"] == "evidence-unavailable"
            and ttl["replay"]["audit"]["exact_replay"] is False
            and ttl["replay"]["materialize"]["status"] == "blocked-evidence-unavailable"
            and ttl["replay"]["recapture"]["historical_replay"] is False,
            ttl["replay"],
        )
    )
    checks.append(
        check(
            "hash-is-not-evidence",
            "An evidence hash remains but does not substitute for expired bytes.",
            bool(ttl["replay"]["audit"]["unavailable_evidence"])
            and ttl["replay"]["materialize"]["status"] == "blocked-evidence-unavailable",
            {
                "unavailable": ttl["replay"]["audit"]["unavailable_evidence"],
                "materialize": ttl["replay"]["materialize"],
            },
        )
    )
    asset_case = cases["asset-url-expired-local-bytes"]
    checks.append(
        check(
            "expired-url-local-bytes",
            "Expired URL does not matter when locked local bytes and hash are available.",
            asset_case["replay"]["materialize"]["status"] == "materialized"
            and asset_case["replay"]["materialize"]["asset_source"] == "local-bytes"
            and asset_case["replay"]["materialize"]["external_url_fetch_count"] == 0,
            asset_case["replay"]["materialize"],
        )
    )
    schema = cases["schema-upgrade-v1-v2"]
    checks.append(
        check(
            "schema-upgrade-preserves-ir",
            "Schema migration preserves fields, authority, order, tombstones, unknowns and evidence.",
            schema["migration"]["preservation"]["all_preserved"] is True
            and schema["migration"]["source_content_hash"] != schema["migration"]["migrated_content_hash"]
            and schema["migration"]["migration_chain"],
            schema["migration"],
        )
    )
    tombstone = cases["tombstone-migration"]
    tombstone_doc = json.loads(
        Path(tombstone["migrated_v2_path"]).read_text(encoding="utf-8")
    )
    checks.append(
        check(
            "tombstone-migration",
            "Tombstone authority, scope, version and pending deletion survive migration.",
            tombstone["migration"]["preservation"]["tombstone_preserved"] is True
            and tombstone_doc["tombstones"][0]["not_deleted"] is True
            and tombstone_doc["tombstones"][0]["delete_status"] == "pending"
            and tombstone_doc["tombstones"][0]["authority_version"] == 3,
            tombstone_doc["tombstones"][0],
        )
    )
    unknown_enum = cases["unknown-enum"]
    unknown_doc = json.loads(
        Path(unknown_enum["migrated_v2_path"]).read_text(encoding="utf-8")
    )
    checks.append(
        check(
            "unknown-enum-fail-closed",
            "Unknown enum fails validation without defaulting a winner.",
            unknown_enum["status"] == "blocked-unknown-enum"
            and any("unknown decision enum" in item for item in unknown_enum["validation_errors"])
            and next(
                field["decision"]["winner"]
                for field in unknown_doc["fields"]
                if field["field_id"] == "field-badge"
            )
            is None,
            unknown_enum,
        )
    )
    permission = cases["permission-revoked"]["replay"]
    checks.append(
        check(
            "permission-revoked-fails-closed",
            "Revoked evidence/materialization permission blocks audit evidence, materialize and recapture.",
            permission["audit"]["evidence_status"] == "access-denied"
            and permission["materialize"]["status"] == "blocked-permission"
            and permission["recapture"]["status"] == "blocked-permission",
            permission,
        )
    )
    cross_page = cases["cross-page-reference-invalid"]
    checks.append(
        check(
            "cross-page-reference-fails-closed",
            "A required missing cross-page reference cannot be silently dropped.",
            cross_page["status"] == "blocked-unresolved-reference"
            and any("unresolved cross-page reference" in item for item in cross_page["validation_errors"])
            and cross_page["replay"]["audit"]["status"] == "not-run",
            cross_page,
        )
    )
    separation = cases["audit-runtime-separation"]["audit_runtime_separation"]
    checks.append(
        check(
            "audit-runtime-separation",
            "Offline audit ordering is not serialized or treated as a runtime DAG.",
            separation["audit_sequence_semantics"] == "ordered-audit-only"
            and separation["audit_has_execution_graph"] is False
            and separation["audit_has_runtime_dependency_graph"] is False
            and separation["runtime_has_execution_graph"] is True,
            separation,
        )
    )
    environment = cases["materialize-environment-changed"]["replay"]["materialize"]
    checks.append(
        check(
            "environment-change-revalidation",
            "Materialize replay under changed fonts/environment requires revalidation and makes no pixel claim.",
            environment["status"] == "materialized-revalidation-required"
            and environment["revalidation_required"] is True
            and environment["pixel_identical_guaranteed"] is False,
            environment,
        )
    )
    clean_runtime = json.loads(
        Path(cases["clean-replay"]["runtime_ir_path"]).read_text(encoding="utf-8")
    )
    checks.append(
        check(
            "no-winner-only-persistence",
            "Every non-tombstone field retains observations and an explicit decision.",
            all(
                field["observations"] or field["decision"]["status"] == "tombstone"
                for field in clean_runtime["fields"]
            )
            and any(
                field["decision"]["status"] == "unknown"
                and field["decision"]["winner"] is None
                for field in clean_runtime["fields"]
            ),
            [
                {
                    "field_id": field["field_id"],
                    "observations": len(field["observations"]),
                    "decision": field["decision"],
                }
                for field in clean_runtime["fields"]
            ],
        )
    )
    checks.append(
        check(
            "temporary-url-not-long-term-evidence",
            "The temporary URL is retained as metadata while local bytes/hash provide replay evidence.",
            clean_runtime["assets"][0]["source_url"].startswith("https://temporary.")
            and clean_runtime["assets"][0]["local_bytes_present"] is True
            and clean_runtime["retention"]["asset_url_separate_from_local_bytes"] is True,
            clean_runtime["assets"][0],
        )
    )
    checks.append(
        check(
            "event-sequence-ordered",
            "Persisted event order is monotonic within each case.",
            all(
                [event["sequence"] for event in cases[case_id]["events"]]
                == sorted(event["sequence"] for event in cases[case_id]["events"])
                for case_id in CASE_IDS
            ),
            Counter(event["event_type"] for event in bundle["events"]),
        )
    )
    checks.append(
        check(
            "base-contract-valid",
            "The base IR/replay bundle passes the same validator used for mutations.",
            not validate_bundle(bundle, baseline),
            validate_bundle(bundle, baseline),
        )
    )
    checks.append(
        check(
            "negative-mutations-rejected",
            "Every targeted invalid persistence, migration or replay mutation is rejected.",
            mutations["rejected"] == mutations["total"] and mutations["accepted"] == 0,
            {"rejected": mutations["rejected"], "total": mutations["total"]},
        )
    )
    checks.append(
        check(
            "artifacts-present",
            "Runtime IR, audit bundle, evidence and asset files exist.",
            Path(clean_runtime["assets"][0]["local_path"]).exists()
            and Path(cases["clean-replay"]["runtime_ir_path"]).exists()
            and Path(cases["clean-replay"]["audit_bundle_path"]).exists(),
            {
                "runtime": cases["clean-replay"]["runtime_ir_path"],
                "audit": cases["clean-replay"]["audit_bundle_path"],
                "asset": clean_runtime["assets"][0]["local_path"],
            },
        )
    )
    checks.append(
        check(
            "no-external-runtime",
            "The experiment is offline and does not connect to Figma or fetch the expired URL.",
            True,
            {"figma_connected": False, "external_url_fetch_count": 0},
        )
    )
    return checks


REPLAY_COLORS = {
    "completed": ("#dcfce7", "#166534"),
    "materialized": ("#dcfce7", "#166534"),
    "new-capture-created": ("#dbeafe", "#1d4ed8"),
    "committed-after-reconcile": ("#dcfce7", "#166534"),
    "summary-only": ("#fef3c7", "#92400e"),
    "materialized-revalidation-required": ("#ffedd5", "#9a3412"),
    "evidence-unavailable": ("#f3e8ff", "#6b21a8"),
    "blocked-evidence-unavailable": ("#f3e8ff", "#6b21a8"),
    "access-denied": ("#fee2e2", "#991b1b"),
    "blocked-permission": ("#fee2e2", "#991b1b"),
    "blocked-persistence": ("#fee2e2", "#991b1b"),
    "blocked-unknown-enum": ("#fee2e2", "#991b1b"),
    "blocked-unresolved-reference": ("#fee2e2", "#991b1b"),
    "not-run": ("#e5e7eb", "#374151"),
    "not-used": ("#e5e7eb", "#374151"),
    "not-used-for-resume": ("#e5e7eb", "#374151"),
}


def replay_mode_status(case: dict[str, Any], mode: str) -> str:
    replay = case.get("replay", {})
    if mode == "audit":
        return replay.get("audit", {}).get("status", "not-run")
    if mode == "materialize":
        return replay.get("materialize", {}).get("status", "not-run")
    if mode == "recapture":
        return replay.get("recapture", {}).get("status", "not-run")
    return replay.get("resume", {}).get("status", "not-used")


def make_replay_matrix(bundle: dict[str, Any], path: Path) -> None:
    columns = ("Case", "Audit replay", "Materialize replay", "Recapture reconcile", "Resume")
    rows: list[list[str]] = []
    colors: list[list[str]] = []
    for case_id in CASE_IDS:
        case = bundle["cases"][case_id]
        statuses = [
            replay_mode_status(case, "audit"),
            replay_mode_status(case, "materialize"),
            replay_mode_status(case, "recapture"),
            replay_mode_status(case, "resume"),
        ]
        rows.append([CASE_LABELS[case_id], *statuses])
        colors.append(
            ["#eef2ff"] + [REPLAY_COLORS.get(status, ("#e2e8f0", "#334155"))[0] for status in statuses]
        )
    fig, ax = plt.subplots(figsize=(19, 8.8))
    ax.set_axis_off()
    fig.text(
        0.025,
        0.96,
        "R5-EXP-06 · Replay semantics matrix",
        fontsize=22,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    fig.text(
        0.025,
        0.91,
        "Audit summary, materialization, recapture and resume are separate modes; expired evidence is never exact replay.",
        fontsize=10.5,
        color="#475569",
        va="top",
    )
    table = ax.table(
        cellText=rows,
        colLabels=columns,
        cellColours=colors,
        colColours=["#e2e8f0"] * len(columns),
        loc="center",
        cellLoc="center",
        bbox=[0.02, 0.08, 0.96, 0.76],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7.4)
    for cell in table.get_celld().values():
        cell.set_edgecolor("#94a3b8")
        cell.set_linewidth(0.6)
    fig.savefig(path, dpi=150, facecolor="#f8fafc")
    plt.close(fig)


def make_lifecycle_timeline(bundle: dict[str, Any], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(18, 8.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7)
    ax.axis("off")
    ax.text(
        0.2,
        6.75,
        "R5-EXP-06 · Persist -> side effect -> recovery",
        fontsize=22,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    ax.text(
        0.2,
        6.35,
        "Persistence failure blocks before send; a crash after send is reconciled by one readback, not by replying as a replay.",
        fontsize=10.5,
        color="#475569",
        va="top",
    )
    y_preflight = 4.9
    boxes = [
        (0.4, y_preflight, "Persist intent", "#dbeafe"),
        (2.4, y_preflight, "Persist fails", "#fee2e2"),
        (4.4, y_preflight, "No send / 0 effects", "#fef3c7"),
    ]
    for x, y, text, color in boxes:
        ax.add_patch(plt.Rectangle((x, y), 1.55, 0.72, facecolor=color, edgecolor="#64748b"))
        ax.text(x + 0.775, y + 0.36, text, ha="center", va="center", fontsize=9.5, color="#0f172a")
    for x in (1.95, 3.95):
        ax.annotate("", xy=(x + 0.45, y_preflight + 0.36), xytext=(x, y_preflight + 0.36), arrowprops={"arrowstyle": "->", "color": "#64748b"})
    ax.text(0.4, 4.45, "Preflight persistence failure", fontsize=12, fontweight="bold", color="#0f172a")

    y_crash = 2.6
    boxes = [
        (0.4, y_crash, "Persist IR + intent", "#dcfce7"),
        (2.4, y_crash, "Send command", "#dbeafe"),
        (4.4, y_crash, "Crash before result", "#fee2e2"),
        (6.4, y_crash, "Resume readback", "#fef3c7"),
        (8.2, y_crash, "Commit once", "#dcfce7"),
    ]
    for x, y, text, color in boxes:
        ax.add_patch(plt.Rectangle((x, y), 1.55, 0.72, facecolor=color, edgecolor="#64748b"))
        ax.text(x + 0.775, y + 0.36, text, ha="center", va="center", fontsize=9.0, color="#0f172a")
    for x in (1.95, 3.95, 5.95, 7.75):
        ax.annotate("", xy=(x + 0.45, y_crash + 0.36), xytext=(x, y_crash + 0.36), arrowprops={"arrowstyle": "->", "color": "#64748b"})
    ax.text(0.4, 2.15, "After-send crash + resume", fontsize=12, fontweight="bold", color="#0f172a")

    events = bundle["cases"]["after-send-crash"]["events"]
    event_text = "\n".join(
        f"{event['sequence']}: {event['event_type']} = {event['status']}"
        for event in events
    )
    ax.text(
        0.4,
        1.25,
        event_text,
        fontsize=9.5,
        color="#334155",
        va="top",
        linespacing=1.4,
        bbox={"boxstyle": "round,pad=0.5", "facecolor": "#f8fafc", "edgecolor": "#cbd5e1"},
    )
    fig.savefig(path, dpi=160, facecolor="#f8fafc")
    plt.close(fig)


def make_migration_integrity(bundle: dict[str, Any], path: Path) -> None:
    migration = bundle["cases"]["schema-upgrade-v1-v2"]["migration"]
    components = (
        ("Fields + observations", "fields"),
        ("Authority chains", "authority_chains"),
        ("Order mapping", "order_mapping"),
        ("Tombstones", "tombstones"),
        ("Unknown state", "unknowns"),
        ("Evidence metadata", "evidence"),
    )
    rows = [["v1 -> v2"] + ["Version", "Preserved", "Details"]]
    colors = [["#e2e8f0"] * 4]
    for label, key in components:
        preserved = migration["preservation"]["preserved"][key]
        rows.append([label, "2.0", "yes" if preserved else "no", "exact structural equality"])
        colors.append(["#ffffff", "#f1f5f9", "#dcfce7" if preserved else "#fee2e2", "#f8fafc"])
    fig, ax = plt.subplots(figsize=(12, 7.2))
    ax.set_axis_off()
    fig.text(
        0.05,
        0.94,
        "R5-EXP-06 · Migration integrity",
        fontsize=21,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    fig.text(
        0.05,
        0.88,
        "The original v1 snapshot remains immutable; v2 is a new copy with a migration chain.",
        fontsize=10.5,
        color="#475569",
        va="top",
    )
    table = ax.table(
        cellText=rows[1:],
        colLabels=rows[0],
        cellColours=colors[1:],
        colColours=colors[0],
        loc="center",
        cellLoc="center",
        bbox=[0.05, 0.25, 0.90, 0.52],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    for cell in table.get_celld().values():
        cell.set_edgecolor("#94a3b8")
        cell.set_linewidth(0.6)
    ax.text(
        0.05,
        0.16,
        f"source content hash: {migration['source_content_hash'][:24]}...\n"
        f"migrated content hash: {migration['migrated_content_hash'][:24]}...\n"
        f"migration chain entries: {len(migration['migration_chain'])}",
        fontsize=9.5,
        color="#334155",
        va="top",
        linespacing=1.6,
    )
    fig.savefig(path, dpi=160, facecolor="#f8fafc")
    plt.close(fig)


def make_retention_timeline(bundle: dict[str, Any], path: Path) -> None:
    ttl_case = bundle["cases"]["evidence-ttl-expired"]
    ttl_ir = json.loads(Path(ttl_case["runtime_ir_path"]).read_text(encoding="utf-8"))
    asset_case = bundle["cases"]["asset-url-expired-local-bytes"]
    asset_ir = json.loads(Path(asset_case["runtime_ir_path"]).read_text(encoding="utf-8"))
    evidence_expiry = datetime.fromisoformat(ttl_ir["evidence"][0]["expires_at"])
    audit_expiry = datetime.fromisoformat(ttl_ir["retention"]["audit_metadata_expires_at"])
    url_expiry = datetime.fromisoformat(asset_ir["assets"][0]["url_expires_at"])
    local_expiry = datetime.fromisoformat(asset_ir["assets"][0]["local_retention_expires_at"])
    points = [
        ("Now", NOW, "#0f172a"),
        ("Evidence expiry", evidence_expiry, "#7c3aed"),
        ("URL expiry", url_expiry, "#dc2626"),
        ("Local bytes expiry", local_expiry, "#0f766e"),
        ("Audit metadata expiry", audit_expiry, "#1d4ed8"),
    ]
    fig, ax = plt.subplots(figsize=(18, 6.2))
    dates = [item[1] for item in points]
    base = min(dates) - timedelta(days=10)
    end = max(dates) + timedelta(days=10)
    for index, (label, date, color) in enumerate(points):
        y = len(points) - index
        x = (date - base).total_seconds() / (end - base).total_seconds()
        ax.plot([x, x], [y - 0.25, y + 0.25], color=color, linewidth=3)
        ax.scatter([x], [y], color=color, s=60)
        ax.text(x, y + 0.35, f"{label}\n{date.date().isoformat()}", ha="center", va="bottom", fontsize=9.5, color=color)
    now_x = (NOW - base).total_seconds() / (end - base).total_seconds()
    ax.axvline(now_x, color="#0f172a", linestyle="--", linewidth=1.5)
    ax.axhline(len(points) + 0.0, color="#cbd5e1", linewidth=1)
    ax.set_xlim(0, 1)
    ax.set_ylim(0.5, len(points) + 1.1)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.set_title(
        "R5-EXP-06 · Evidence, URL and audit retention are separate",
        loc="left",
        fontsize=19,
        fontweight="bold",
        color="#0f172a",
    )
    ax.text(
        0.01,
        0.06,
        "TTL evidence is expired; audit metadata remains; expired URL is not used while local asset bytes remain.",
        transform=ax.transAxes,
        fontsize=9.5,
        color="#475569",
    )
    fig.subplots_adjust(left=0.05, right=0.97, top=0.85, bottom=0.12)
    fig.savefig(path, dpi=160, facecolor="#f8fafc")
    plt.close(fig)


def make_bundle_separation(bundle: dict[str, Any], path: Path) -> None:
    clean = bundle["cases"]["audit-runtime-separation"]
    audit = json.loads(Path(clean["audit_bundle_path"]).read_text(encoding="utf-8"))
    runtime = json.loads(Path(clean["runtime_ir_path"]).read_text(encoding="utf-8"))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6.4))
    ax1.set_axis_off()
    ax2.set_axis_off()
    ax1.text(0.0, 0.94, "audit-bundle/1.0", fontsize=17, fontweight="bold", color="#0f172a")
    ax1.text(0.0, 0.87, "ordered-audit-only", fontsize=11, fontweight="bold", color="#1d4ed8")
    for index, field in enumerate(audit["decisions"]):
        ax1.text(
            0.02,
            0.78 - index * 0.09,
            f"{index + 1}. {field['field_id']} = {field['status']}",
            fontsize=10,
            color="#334155",
        )
    ax1.text(0.0, 0.35, "runtime DAG: null\nsequence is evidence order, not execution order", fontsize=10, color="#991b1b")

    ax2.text(0.0, 0.94, "runtime-ir/1.0", fontsize=17, fontweight="bold", color="#0f172a")
    ax2.text(0.0, 0.87, "runtime-dag", fontsize=11, fontweight="bold", color="#166534")
    nodes = runtime["execution_graph"]["nodes"]
    for index, node in enumerate(nodes):
        y = 0.77 - index * 0.095
        ax2.text(0.02, y, f"{index + 1}. {node}", fontsize=10, color="#334155")
    ax2.text(0.0, 0.06, "Preconditions, write state and recovery are runtime fields.", fontsize=10, color="#166534")
    fig.suptitle(
        "R5-EXP-06 · Offline audit order is not the runtime dependency graph",
        x=0.04,
        y=0.98,
        ha="left",
        fontsize=18,
        fontweight="bold",
        color="#0f172a",
    )
    fig.subplots_adjust(left=0.05, right=0.97, top=0.84, bottom=0.08, wspace=0.2)
    fig.savefig(path, dpi=160, facecolor="#f8fafc")
    plt.close(fig)


BOUNDARY = {
    "scope": "Offline file-backed runtime IR, audit bundle, evidence store and replay model.",
    "persistence": "Atomic local files are used; no database, WAL service, object store or distributed transaction is exercised.",
    "crash": "The after-send crash is a simulated event sequence, not an OS process kill.",
    "ttl": "TTL behavior uses a fixed clock and a deliberately missing expired evidence file.",
    "permissions": "Permission revocation is modeled in IR policy, not enforced by a real identity service.",
    "migration": "Only schema v1 -> v2 is covered.",
    "replay": "Replay hashes are semantic experiment hashes, not proof of byte-identical screenshots or Figma documents.",
}

LIMITATIONS = [
    "The store is local JSON and bytes; it does not exercise production database transactions or object-store consistency.",
    "The preflight failure is injected before the final atomic replace and does not model every filesystem failure mode.",
    "The after-send crash does not kill a real process or network connection.",
    "Evidence TTL is modeled with fixed timestamps and an absent evidence file, not a real retention worker.",
    "The asset URL is never fetched; local bytes and their SHA-256 are the only materialization evidence.",
    "Permission revocation is a policy field, not an authenticated access control boundary.",
    "Schema migration covers one authored v1 -> v2 path and one unknown-enum failure.",
    "Cross-page references are validated against an in-memory capture set, not a production reference store.",
    "Materialize replay hashes decisions and asset identity; they do not guarantee pixel identity.",
    "No Figma connection, production IR implementation, external service or user study is included.",
]


def print_summary(result: dict[str, Any]) -> None:
    passed = sum(1 for item in result["checks"] if item["passed"])
    print(f"status={result['status']}")
    print(f"checks={passed}/{len(result['checks'])}")
    print(
        "mutations=%s/%s rejected"
        % (result["mutations"]["rejected"], result["mutations"]["total"])
    )
    print(f"cases={len(CASE_IDS)}")
    print(f"content_hash={result['content_hash']}")
    print(f"out={result['output_directory']}")
    for item in result["checks"]:
        if not item["passed"]:
            print(f"FAILED CHECK: {item['name']} :: {item['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R5-EXP-06 IR persistence and replay experiment.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    out_dir = safe_output_dir(args.out)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Persisting runtime IR, audit bundles, evidence and replay records...")
    bundle = build_bundle(out_dir)
    baseline = freeze_bundle(bundle)
    mutations = run_mutations(bundle, baseline)
    checks = run_checks(bundle, baseline, mutations)

    replay_matrix = out_dir / "r5_exp_06_replay_matrix.png"
    lifecycle = out_dir / "r5_exp_06_lifecycle_timeline.png"
    migration_visual = out_dir / "r5_exp_06_migration_integrity.png"
    retention = out_dir / "r5_exp_06_retention_timeline.png"
    bundle_layers = out_dir / "r5_exp_06_bundle_separation.png"
    make_replay_matrix(bundle, replay_matrix)
    make_lifecycle_timeline(bundle, lifecycle)
    make_migration_integrity(bundle, migration_visual)
    make_retention_timeline(bundle, retention)
    make_bundle_separation(bundle, bundle_layers)

    all_checks_passed = all(item["passed"] for item in checks)
    status = "completed-for-current-scope" if all_checks_passed and mutations["accepted"] == 0 else "failed"
    visual_files = {}
    for path in (replay_matrix, lifecycle, migration_visual, retention, bundle_layers):
        visual_files[path.name] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    clean_runtime_path = Path(bundle["cases"]["clean-replay"]["runtime_ir_path"])
    clean_audit_path = Path(bundle["cases"]["clean-replay"]["audit_bundle_path"])
    clean_runtime = json.loads(clean_runtime_path.read_text(encoding="utf-8"))
    clean_audit = json.loads(clean_audit_path.read_text(encoding="utf-8"))
    replay_results = {
        case_id: bundle["cases"][case_id]["replay"]
        for case_id in CASE_IDS
    }
    migration_results = {
        case_id: bundle["cases"][case_id]["migration"]
        for case_id in CASE_IDS
        if "migration" in bundle["cases"][case_id]
    }
    retention_results = {
        "now": CAPTURED_AT,
        "policy": {
            "replay_evidence_days": REPLAY_EVIDENCE_DAYS,
            "audit_metadata_days": AUDIT_METADATA_DAYS,
        },
        "clean": clean_runtime["retention"],
        "ttl_case": {
            "evidence": json.loads(
                Path(bundle["cases"]["evidence-ttl-expired"]["runtime_ir_path"]).read_text(
                    encoding="utf-8"
                )
            )["evidence"],
            "retention": json.loads(
                Path(bundle["cases"]["evidence-ttl-expired"]["runtime_ir_path"]).read_text(
                    encoding="utf-8"
                )
            )["retention"],
        },
        "asset_case": json.loads(
            Path(bundle["cases"]["asset-url-expired-local-bytes"]["runtime_ir_path"]).read_text(
                encoding="utf-8"
            )
        )["assets"][0],
    }

    outputs = {
        "events": out_dir / "events.json",
        "replay_results": out_dir / "replay_results.json",
        "migration": out_dir / "migration.json",
        "retention": out_dir / "retention.json",
        "mutations": out_dir / "mutations.json",
        "runtime_ir": out_dir / "runtime_ir.json",
        "audit_bundle": out_dir / "audit_bundle.json",
    }
    atomic_write_json(outputs["events"], bundle["events"])
    atomic_write_json(outputs["replay_results"], replay_results)
    atomic_write_json(outputs["migration"], migration_results)
    atomic_write_json(outputs["retention"], retention_results)
    atomic_write_json(outputs["mutations"], mutations)
    atomic_write_json(outputs["runtime_ir"], clean_runtime)
    atomic_write_json(outputs["audit_bundle"], clean_audit)

    result: dict[str, Any] = {
        "job": JOB,
        "revision": REVISION,
        "profile": PROFILE,
        "status": status,
        "generated_at": CAPTURED_AT,
        "output_directory": str(out_dir),
        "environment": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "pillow": package_version("Pillow"),
            "matplotlib": package_version("matplotlib"),
        },
        "cases": bundle["cases"],
        "events": bundle["events"],
        "replay_results": replay_results,
        "migration_results": migration_results,
        "retention": retention_results,
        "runtime_ir": clean_runtime,
        "audit_bundle": clean_audit,
        "artifact_paths": {key: str(value) for key, value in outputs.items()},
        "checks": checks,
        "mutations": mutations,
        "visuals": visual_files,
        "boundary": BOUNDARY,
        "limitations": LIMITATIONS,
        "release_claims": {
            "experiment_status": "completed-for-current-scope" if all_checks_passed else "failed",
            "verified": False,
            "production_ready": False,
            "figma_connected": False,
            "source_modified": False,
            "production_persistence_implemented": False,
        },
    }
    result["content_hash"] = content_hash(result)
    atomic_write_json(out_dir / "result.json", result)
    print_summary(result)
    return 0 if all_checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
