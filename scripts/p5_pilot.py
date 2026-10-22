# -*- coding: utf-8 -*-
"""Bounded P5 pilot decision and frozen-registry preflight."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.contracts import canonical_hash


PROFILE = "p5-dry-run-profile/1.0"
REGISTRY = ROOT / "docs" / "v2_mentor" / "p1_sample_registry.json"
DRY_RUN_RESULT = ROOT / "output" / "_p5_dry_run_round1" / "result.json"


def decide_page(sample: dict[str, Any]) -> dict[str, Any]:
    blockers = []
    if bool(sample.get("unauthorized_action")):
        blockers.append("unauthorized-action")
    if bool(sample.get("missing_evidence")):
        blockers.append("missing-evidence")
    if bool(sample.get("critical_unknown")):
        blockers.append("critical-unknown")
    if bool(sample.get("unexplained_unknown_transaction")):
        blockers.append("unexplained-unknown-transaction")
    if blockers:
        decision = "manual-review"
        release_allowed = False
    else:
        decision = "pilot-allowed-provisional"
        release_allowed = True
    return {
        "sample_id": str(sample.get("sample_id") or ""),
        "decision": decision,
        "release_allowed": release_allowed,
        "blockers": blockers,
    }


def run_pilot(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    if not REGISTRY.is_file():
        raise FileNotFoundError(f"missing frozen sample registry: {REGISTRY}")
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    samples = list(registry.get("samples") or [])
    dry_run = (
        json.loads(DRY_RUN_RESULT.read_text(encoding="utf-8"))
        if DRY_RUN_RESULT.is_file()
        else None
    )
    staged_ready = bool(
        dry_run
        and dry_run.get("staged_rehearsal", {}).get("status") == "pass"
    )
    pages = []
    for sample in samples:
        if staged_ready:
            decision = decide_page(sample)
        else:
            decision = {
                "sample_id": sample["sample_id"],
                "decision": "blocked",
                "release_allowed": False,
                "blockers": ["staged-rehearsal-not-run", "pilot-evidence-missing"],
            }
        pages.append(
            {
                **decision,
                "scenario_id": sample.get("scenario_id"),
                "source_kind": sample.get("source_kind"),
                "locator": sample.get("locator"),
            }
        )
    unknown_entries = [
        {
            "sample_id": page["sample_id"],
            "current_state": "not-run",
            "ownership_evidence": "not-collected",
            "actor_attribution": "unknown",
            "operator_decision": "pending",
            "no_resend_justification": "No pilot write was sent.",
            "blockers": page["blockers"],
        }
        for page in pages
        if page["decision"] != "pilot-allowed-provisional"
    ]
    manifest = {
        "schema": "p5-pilot-manifest/1.0",
        "profile": PROFILE,
        "created_at": "2026-10-22T00:00:00+00:00",
        "code_revision": _code_revision(),
        "registry_path": str(REGISTRY.relative_to(ROOT)).replace("\\", "/"),
        "registry_sha256": _sha256_file(REGISTRY),
        "denominator": len(samples),
        "blocked_count": sum(page["decision"] == "blocked" for page in pages),
        "manual_review_count": sum(
            page["decision"] == "manual-review" for page in pages
        ),
        "provisional_count": sum(
            page["decision"] == "pilot-allowed-provisional" for page in pages
        ),
        "pages": pages,
        "unknown_entries": unknown_entries,
        "pilot_verified": False,
    }
    manifest["content_hash"] = canonical_hash(manifest)
    report = {
        "schema": "p5-partial-unknown-report/1.0",
        "root_name": "[BLOCKED] P5 Pilot Registry",
        "status": "blocked",
        "outside_business_flow": True,
        "entries": unknown_entries,
        "blocked_actions": [
            "cannot-claim-pilot-verified",
            "cannot-export-as-complete",
        ],
    }
    result = {
        **manifest,
        "status": "blocked-environment",
        "reason": (
            "The frozen registry was evaluated, but no real staged rehearsal or "
            "pilot run exists."
        ),
        "pilot_status": "pilot-blocked",
    }
    _write_json(destination / "pilot_manifest.json", manifest)
    _write_json(destination / "partial_unknown_report.json", report)
    _write_json(destination / "result.json", result)
    return result


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
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with staging.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_p5_pilot_round1")
    args = parser.parse_args()
    result = run_pilot(args.out)
    print("status=" + result["status"])
    print("denominator=" + str(result["denominator"]))
    print("pilot_verified=false")
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] != "blocked-environment" else 1


if __name__ == "__main__":
    raise SystemExit(main())
