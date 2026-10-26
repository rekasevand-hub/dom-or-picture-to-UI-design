# -*- coding: utf-8 -*-
"""Conservative collaboration-race and manual-review policy probe."""
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
from src.app.services.rendering.figma_adapter import reconciliation_policy


PROFILE = "fixed-pilot-collaboration-profile/1.0"
ATTRIBUTION_EVIDENCE = (
    ROOT / "output" / "_r5_p3_multiplayer_attribution_round2" / "r5_p3_multiplayer_attribution.json"
)


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    attribution_sha = (
        _sha256_file(ATTRIBUTION_EVIDENCE)
        if ATTRIBUTION_EVIDENCE.is_file()
        else None
    )
    unavailable = {
        "status": "unavailable",
        "actor": "unknown",
        "revision": "unknown",
    }
    races = {
        "same-target-same-state": reconciliation_policy(
            {"transactionId": "race-1", "state": "unknown"},
            {
                "status": "matches",
                "owned_node_ids": ["1:2"],
                "current_state": {"characters": "same"},
            },
            unavailable,
        ),
        "same-target-conflict": reconciliation_policy(
            {"transactionId": "race-2", "state": "unknown"},
            {
                "status": "mismatch",
                "owned_node_ids": ["1:2"],
                "current_state": {"characters": "other"},
            },
            unavailable,
        ),
        "concurrent-node-deletion": reconciliation_policy(
            {"transactionId": "race-3", "state": "unknown"},
            {"status": "node-deleted", "owned_node_ids": ["1:3"]},
            unavailable,
        ),
        "partial-owned-state": reconciliation_policy(
            {"transactionId": "race-4", "state": "unknown"},
            {"status": "partial-match", "owned_node_ids": ["1:4", "1:5"]},
            unavailable,
        ),
        "authoritative-attribution": reconciliation_policy(
            {"transactionId": "race-5", "state": "unknown"},
            {"status": "matches", "owned_node_ids": ["1:6"]},
            {
                "status": "authoritative",
                "actor": "operator-a",
                "revision": "revision-42",
            },
        ),
    }
    checks = (
        _check("same-state-no-attribution", "Matching state does not infer actor or revision", races["same-target-same-state"].actor == "unknown" and races["same-target-same-state"].revision == "unknown"),
        _check("same-state-no-resend", "Matching state still requires operator resolution", not races["same-target-same-state"].resend_allowed and races["same-target-same-state"].manual_review_required),
        _check("conflict-manual", "Conflicting state is routed to operator review", races["same-target-conflict"].recommendation == "operator-resolve-conflict"),
        _check("deletion-manual", "Concurrent deletion is rollback-incomplete/manual-review", races["concurrent-node-deletion"].recommendation == "rollback-incomplete-manual-review"),
        _check("owned-evidence", "Owned node evidence is preserved", races["partial-owned-state"].owned_node_ids == ("1:4", "1:5")),
        _check("partial-state-manual", "Partial state requires operator reconciliation", races["partial-owned-state"].recommendation == "operator-reconcile-partial-state"),
        _check("authoritative-attribution", "Authoritative attribution is preserved when supplied", races["authoritative-attribution"].actor == "operator-a" and races["authoritative-attribution"].revision == "revision-42"),
        _check("no-inferred-attribution", "Unavailable-attribution races keep unknown actor/revision", all(item.actor == "unknown" and item.revision == "unknown" for key, item in races.items() if key != "authoritative-attribution")),
        _check("real-attribution-evidence", "Existing real multiplayer attribution artifact is retained", bool(attribution_sha)),
    )
    result = {
        "schema": "p5-collaboration-race-probe/1.0",
        "status": (
            "completed-for-current-scope"
            if all(item["passed"] for item in checks)
            else "failed"
        ),
        "scope": "conservative collaboration reconciliation and attribution boundary",
        "created_at": "2026-10-22T00:00:00+00:00",
        "profile": PROFILE,
        "code_revision": _code_revision(),
        "real_environment_required": True,
        "real_environment_evidence": {
            "multiplayer_attribution_sha256": attribution_sha,
        },
        "races": {key: value.to_dict() for key, value in races.items()},
        "checks": list(checks),
        "remaining_environment_gates": [
            "Two real Figma collaborator accounts",
            "Controlled edit and deletion timing on the same owned node",
            "Operator identity, evidence preservation and no-resend approval",
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
    parser.add_argument("--out", default="output/_p5_collaboration_race_round1")
    args = parser.parse_args()
    result = run_probe(args.out)
    print("status=" + result["status"])
    print("real_environment_required=true")
    print("content_hash=" + result["content_hash"])
    return 0 if all(item["passed"] for item in result["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
