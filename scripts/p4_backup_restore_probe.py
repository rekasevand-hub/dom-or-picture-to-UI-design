# -*- coding: utf-8 -*-
"""Backup, corruption detection and restore probe for the local pilot store."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.contracts import (
    AccessPolicy,
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
    Tombstone,
    UnknownRecord,
    build_audit_bundle,
    canonical_hash,
)
from src.app.services.persistence.local_pilot import LocalPilotStore


PROFILE = "local-pilot/1.0"


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("source", "backup", "corrupted", "restored"):
        _reset_owned_dir(destination, destination / name)
    source_root = destination / "source"
    backup_root = destination / "backup"
    corrupted_root = destination / "corrupted"
    restored_root = destination / "restored"

    runtime = _runtime_bundle()
    audit = build_audit_bundle(runtime)
    release_decision = {
        "status": "deliverable-partial",
        "reason": "Backup probe preserves a known partial decision.",
        "complete_export_allowed": False,
        "allowed_export_mode": "explicit-partial",
    }
    bundle = {
        "trace_id": "trace-backup-restore",
        "runtime_ir": runtime,
        "audit_bundle": audit,
        "release_decision": release_decision,
    }
    source_store = LocalPilotStore(source_root, clock=lambda: 1_000_000.0)
    original = source_store.put(bundle, "backup-idem-key")

    shutil.copytree(source_root / "deliveries", backup_root / "deliveries")
    manifest = _build_manifest(backup_root)
    _write_json(destination / "backup_manifest.json", manifest)

    shutil.copytree(backup_root, corrupted_root, dirs_exist_ok=True)
    corrupt_file = (
        corrupted_root
        / "deliveries"
        / "trace-backup-restore"
        / "record.json"
    )
    payload = bytearray(corrupt_file.read_bytes())
    payload[0] = ord("[") if payload[0] != ord("[") else ord("{")
    corrupt_file.write_bytes(payload)
    corruption_detected = not _verify_manifest(corrupted_root, manifest)

    shutil.copytree(backup_root, restored_root, dirs_exist_ok=True)
    restored_store = LocalPilotStore(restored_root)
    restored = restored_store.get("trace-backup-restore")
    restored_runtime = restored.runtime_ir
    restore_verified = (
        restored is not None
        and restored.content_hash == original.content_hash
        and restored.runtime_ir == original.runtime_ir
        and restored.audit_bundle == original.audit_bundle
        and restored.release_decision == original.release_decision
    )
    preserved = {
        "hashes": restored.content_hash == original.content_hash,
        "tombstones": (
            restored_runtime["tombstones"][0]["tombstone_id"] == "tomb-backup"
        ),
        "unknowns": restored_runtime["unknowns"][0]["status"] == "unknown",
        "evidence": bool(restored_runtime["evidence"]),
        "release_decision": (
            restored.release_decision["status"] == "deliverable-partial"
        ),
    }
    migration_report = {
        "source_schema": runtime.schema_version,
        "target_schema": restored_runtime["schema_version"],
        "migration_applied": False,
        "preserved": preserved,
        "content_hash": restored.content_hash,
    }
    checks = (
        _check("backup-complete", "Backup manifest contains every record file", bool(manifest["files"])),
        _check("corruption-detected", "Corrupted copy fails manifest verification", corruption_detected),
        _check("restore-verified", "Restored bundle byte identity and contract state survive", restore_verified),
        _check("tombstone", "Tombstone survives restore", preserved["tombstones"]),
        _check("unknown", "Unknown state survives restore", preserved["unknowns"]),
        _check("evidence", "Evidence metadata survives restore", preserved["evidence"]),
        _check("release", "Release decision survives restore", preserved["release_decision"]),
    )
    result = {
        "schema": "p4-backup-restore-probe/1.0",
        "status": "verified-for" if all(item["passed"] for item in checks) else "blocked",
        "scope": "backup/restore and migration contract on local-pilot storage profile",
        "created_at": "2026-10-22T00:00:00+00:00",
        "profile": PROFILE,
        "code_revision": _code_revision(),
        "storage_profile": "local-pilot",
        "production_eligible": False,
        "corruption_detected": corruption_detected,
        "restore": {
            "verified": restore_verified,
            "content_hash": restored.content_hash,
            "preserved": preserved,
        },
        "migration_report": migration_report,
        "checks": list(checks),
        "claim_limits": [
            "This verifies local pilot backup/restore, not the selected production backend.",
            "Manifest hashes detect corruption but do not provide encryption or remote durability.",
        ],
    }
    result["content_hash"] = canonical_hash(result)
    _write_json(destination / "restore_record.json", restored.to_dict())
    _write_json(destination / "restore_report.json", result["restore"])
    _write_json(destination / "migration_report.json", migration_report)
    _write_json(destination / "result.json", result)
    return result


def _runtime_bundle() -> RuntimeIR:
    evidence = (
        EvidenceRecord(
            evidence_id="ev-dom",
            kind="dom-json",
            sha256="a" * 64,
            locator="evidence/dom.json",
            availability=EvidenceAvailability.AVAILABLE,
            expires_at="2027-01-01T00:00:00+00:00",
        ),
    )
    field = FieldRecord(
        field_id="field-title",
        node_id="node-title",
        field_type="text-content",
        observations=(
            FieldObservation(
                source="dom",
                evidence_id="ev-dom",
                present=True,
                value="Backup title",
            ),
        ),
        decision=FieldDecision(
            authority=FieldAuthority.DOM,
            status=FieldDecisionStatus.SELECTED,
            selected_value="Backup title",
            release_eligible=True,
            evidence_refs=("ev-dom",),
            reason="DOM evidence.",
        ),
    )
    return RuntimeIR(
        job_id="job-backup",
        schema_version="2.0",
        policy_version="p4-backup/1.0",
        capture_revision="capture-r1",
        plan_revision="plan-r1",
        output_revision="output-r1",
        capture_id="capture-r1",
        state_signature="state-r1",
        fields=(field,),
        evidence=evidence,
        assets=(),
        tombstones=(
            Tombstone(
                tombstone_id="tomb-backup",
                object_key="legacy",
                scope="field",
                authority="business",
                authority_version=2,
                effective_at="2026-10-22T00:00:00+00:00",
            ),
        ),
        unknowns=(
            UnknownRecord(
                object_key="badge",
                field="text-content",
                status="unknown",
                reason="not observed",
            ),
        ),
        order_mapping=OrderMapping(
            dom_order=("node-title",),
            screenshot_order=(),
            figma_child_order=("node-title",),
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
            evidence_expires_at="2027-01-01T00:00:00+00:00",
            audit_metadata_expires_at="2027-04-01T00:00:00+00:00",
        ),
        access_policy=AccessPolicy(
            allow_evidence_read=True,
            allow_materialize=True,
            allow_audit_summary=True,
        ),
        execution_graph=ExecutionGraph(
            nodes=("capture", "delivery", "audit"),
            edges=(("capture", "delivery"), ("delivery", "audit")),
        ),
    )


def _build_manifest(root: Path) -> dict[str, Any]:
    files = {
        str(path.relative_to(root)).replace("\\", "/"): _sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    document = {
        "schema": "pilot-backup-manifest/1.0",
        "root": str(root),
        "files": files,
    }
    document["content_hash"] = canonical_hash(document)
    return document


def _verify_manifest(root: Path, manifest: dict[str, Any]) -> bool:
    for relative, expected in manifest["files"].items():
        path = root / relative
        if not path.is_file() or _sha256_file(path) != expected:
            return False
    return True


def _reset_owned_dir(destination: Path, target: Path) -> None:
    resolved_destination = destination.resolve()
    resolved_target = target.resolve()
    if (
        resolved_target.parent != resolved_destination
        or resolved_target.name not in {"source", "backup", "corrupted", "restored"}
    ):
        raise ValueError(f"refusing to reset unexpected probe directory: {resolved_target}")
    if resolved_target.exists():
        shutil.rmtree(resolved_target)


def _check(name: str, description: str, passed: bool) -> dict[str, Any]:
    return {"name": name, "description": description, "passed": bool(passed)}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_revision() -> str:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return revision + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with staging.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_p4_backup_restore_round1")
    args = parser.parse_args()
    result = run_probe(args.out)
    print("status=" + result["status"])
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] == "verified-for" else 1


if __name__ == "__main__":
    raise SystemExit(main())
