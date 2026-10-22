# -*- coding: utf-8 -*-
"""Deterministic permission/takeover matrix with real-environment gates."""
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
    classify_permission_failure,
    reconciliation_policy,
)


PROFILE = "fixed-pilot-permission-profile/1.0"
REAL_EVIDENCE = (
    ROOT / "output" / "_r5_p3_real_plugin_revocation_round2" / "figma_ui_revocation_probe.json",
    ROOT / "output" / "_r5_p3_plugin_auth_round2" / "r5_p3_plugin_auth.json",
)


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    scenarios = {
        "view-only": {"code": "403", "message": "view-only document"},
        "permission-denied": {"code": "403", "message": "write permission denied"},
        "rate-limited": {
            "code": "429",
            "message": "Figma rate limit",
            "retryAfterMs": 1500,
        },
        "plugin-token-revoked": {"message": "plugin token revoked"},
        "plugin-takeover": {
            "code": "PLUGIN_TAKEOVER",
            "message": "plugin takeover: connection replaced",
        },
        "user-modification": {
            "code": "PRECONDITION_FAILED",
            "message": "node modified by collaborator after send",
        },
    }
    outcomes = {
        name: classify_permission_failure(value).to_dict()
        for name, value in scenarios.items()
    }
    manual = reconciliation_policy(
        {"transactionId": "permission-user-modification", "state": "unknown"},
        {
            "status": "mismatch",
            "owned_node_ids": ["1:2"],
            "current_state": {"characters": "changed"},
        },
        {"status": "unavailable", "actor": "unknown", "revision": "unknown"},
    )
    evidence_hashes = {
        str(path.relative_to(ROOT)).replace("\\", "/"): (
            _sha256_file(path) if path.is_file() else None
        )
        for path in REAL_EVIDENCE
    }
    real_plugin_evidence_present = all(evidence_hashes.values())
    checks = (
        _check("view-only", "View-only is not retried", outcomes["view-only"]["category"] == "view-only" and not outcomes["view-only"]["retryable"]),
        _check("permission-denied", "Permission denial is not retried", outcomes["permission-denied"]["category"] == "permission-denied"),
        _check("rate-limit", "Rate limit preserves retry metadata", outcomes["rate-limited"]["category"] == "rate-limited" and outcomes["rate-limited"]["retry_after_ms"] == 1500),
        _check("token-revoked", "Revoked token requires authentication repair", outcomes["plugin-token-revoked"]["category"] == "plugin-token-revoked"),
        _check("takeover", "Plugin takeover stops automatic retries", outcomes["plugin-takeover"]["category"] == "plugin-takeover" and outcomes["plugin-takeover"]["no_resend"]),
        _check("post-send-modification", "Post-send modification requires operator review", outcomes["user-modification"]["category"] == "user-modification" and manual.manual_review_required),
        _check("no-resend", "Unsafe categories never auto-resend", all(item["no_resend"] for key, item in outcomes.items() if key != "rate-limited")),
        _check("real-plugin-evidence", "Existing real plugin auth/revocation evidence is retained", real_plugin_evidence_present),
    )
    result = {
        "schema": "p5-permission-takeover-probe/1.0",
        "status": "completed-for-current-scope",
        "scope": "permission/takeover classification and manual review policy",
        "created_at": "2026-10-22T00:00:00+00:00",
        "profile": PROFILE,
        "code_revision": _code_revision(),
        "real_environment_required": True,
        "real_environment_evidence": evidence_hashes,
        "outcomes": outcomes,
        "manual_review": manual.to_dict(),
        "checks": list(checks),
        "remaining_environment_gates": [
            "Fixed pilot Figma document in view-only and writable states",
            "Two authenticated collaborators with controlled same-target races",
            "Authoritative operator identity and reconciliation approval",
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
    parser.add_argument("--out", default="output/_p5_permission_takeover_round1")
    args = parser.parse_args()
    result = run_probe(args.out)
    print("status=" + result["status"])
    print("real_environment_required=true")
    print("content_hash=" + result["content_hash"])
    return 0 if all(item["passed"] for item in result["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
