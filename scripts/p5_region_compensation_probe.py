# -*- coding: utf-8 -*-
"""Expected-state and region compensation probe for supported pilot actions."""
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
from src.app.services.rendering.figma_adapter import (
    evaluate_expected_region,
    plan_region_compensation,
)
from src.app.services.rendering.write_job_ledger import CompensationScope


PROFILE = "fixed-pilot-region-compensation/1.0"
REAL_FAULT_EVIDENCE = ROOT / "output" / "_p3_runtime_fault_round1" / "figma_runtime_fault_probe.json"


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    expected = {
        "imageFillSha256": "a" * 64,
        "layoutSnapshot": {"layoutMode": "HORIZONTAL", "itemSpacing": 12},
        "bounds": {"x": 10, "y": 20, "width": 100, "height": 40},
        "textRuns": [{"characters": "Title", "fontSize": 20}],
        "regionMembership": {"regionId": "region-a", "member": True},
    }
    matched = evaluate_expected_region(expected, expected)
    partial = evaluate_expected_region(
        expected,
        {
            **expected,
            "bounds": {"x": 11, "y": 20, "width": 100, "height": 40},
        },
    )
    conflict = evaluate_expected_region(
        expected,
        {
            **expected,
            "textRuns": [{"characters": "Other", "fontSize": 20}],
            "regionMembership": {"regionId": "region-b", "member": False},
        },
    )
    scope = CompensationScope(
        job_id="job-a",
        region_id="region-a",
        node_ids=("1:1", "1:2", "1:3"),
        user_takeover_state="none",
    )
    plan = plan_region_compensation(
        scope,
        owned_nodes={
            "1:1": {"job_id": "job-a", "owner": "figma_auto_agent"},
            "1:2": {"job_id": "job-b", "owner": "figma_auto_agent"},
            "1:3": {"job_id": "job-a", "owner": "figma_auto_agent"},
        },
    )
    takeover = plan_region_compensation(
        CompensationScope(
            job_id="job-a",
            region_id="region-a",
            node_ids=("1:1", "1:2"),
            user_takeover_state="modified",
        ),
        owned_nodes={
            "1:1": {"job_id": "job-a", "owner": "figma_auto_agent"},
            "1:2": {"job_id": "job-a", "owner": "figma_auto_agent"},
        },
    )
    unknown_owner = plan_region_compensation(
        CompensationScope(
            job_id="job-a",
            region_id="region-a",
            node_ids=("1:1", "1:9"),
            user_takeover_state="none",
        ),
        owned_nodes={
            "1:1": {"job_id": "job-a", "owner": "figma_auto_agent"},
        },
    )
    fault_sha = (
        _sha256_file(REAL_FAULT_EVIDENCE)
        if REAL_FAULT_EVIDENCE.is_file()
        else None
    )
    checks = (
        _check("image-layout-bounds-text-region", "Expected checks cover all five evidence families", len(matched.checks) == 5),
        _check("full-match", "All expected evidence can match", matched.classification == "matches-intended"),
        _check("partial-failure", "Bounds drift produces partial-match", partial.classification == "partial-match" and partial.checks["bounds"] == "mismatched"),
        _check("conflict", "Text/region conflict is visible", conflict.classification == "partial-match" and conflict.checks["textRuns"] == "mismatched"),
        _check("owned-scope", "Compensation removes only exact job-owned nodes", plan.remove_node_ids == ("1:1", "1:3") and plan.preserved_node_ids == ("1:2",)),
        _check("takeover", "User takeover blocks compensation", takeover.status == "rollback-incomplete/manual-review" and not takeover.remove_node_ids),
        _check("unknown-ownership", "Missing ownership evidence requires review", unknown_owner.status == "rollback-incomplete/manual-review" and unknown_owner.unknown_node_ids == ("1:9",)),
        _check("real-fault-evidence", "Existing real Figma rollback evidence is retained", bool(fault_sha)),
    )
    result = {
        "schema": "p5-region-compensation-probe/1.0",
        "status": "completed-for-current-scope",
        "scope": "expected-state and region compensation for supported pilot actions",
        "created_at": "2026-10-22T00:00:00+00:00",
        "profile": PROFILE,
        "code_revision": _code_revision(),
        "real_environment_required": True,
        "real_environment_evidence": {
            "runtime_fault_probe_sha256": fault_sha,
        },
        "expected": expected,
        "evaluations": {
            "matched": matched.to_dict(),
            "partial": partial.to_dict(),
            "conflict": conflict.to_dict(),
        },
        "plans": {
            "normal": plan.to_dict(),
            "takeover": takeover.to_dict(),
            "unknown-owner": unknown_owner.to_dict(),
        },
        "checks": list(checks),
        "remaining_environment_gates": [
            "Real Figma upload interruption",
            "Real collaborator takeover during a mutating batch",
            "Real concurrent deletion of an owned child node",
        ],
    }
    result["content_hash"] = canonical_hash(result)
    _write_json(destination / "result.json", result)
    _write_json(destination / "manifest.json", result)
    return result


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
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with staging.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_p5_region_compensation_round1")
    args = parser.parse_args()
    result = run_probe(args.out)
    print("status=" + result["status"])
    print("real_environment_required=true")
    print("content_hash=" + result["content_hash"])
    return 0 if all(item["passed"] for item in result["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
