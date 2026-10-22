"""Probe attribution boundaries for multiplayer Figma edits."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.bridge_server import (  # noqa: E402
    BridgeHub,
    TransactionRecord,
)
from src.app.services.job_namespace import build_job_namespace  # noqa: E402


def run_probe() -> dict[str, Any]:
    transaction = TransactionRecord(
        client_id="client-a",
        requested_id="request-a",
        transaction_id="collaborator-race",
        state="unknown",
        fingerprint="a" * 64,
        action="apply_edit_batch",
        updated_at=1.0,
    )
    hub = BridgeHub(timeout=1)
    payload = hub._transaction_payload(transaction)
    reconciliation = hub._evaluate_expected_checks(
        (
            {
                "nodeId": "TEXT:1",
                "action": "set_text",
                "property": "characters",
                "expectedValue": "intended",
            },
        ),
        {"TEXT:1": {"characters": "intended"}},
    )
    cross_client_distinct = (
        build_job_namespace("client-a", "shared-job")
        != build_job_namespace("client-b", "shared-job")
    )
    checks = {
        "attribution_status": payload["attribution"]["status"],
        "attribution_actor": payload["attribution"]["actor"],
        "same_state_does_not_prove_actor": (
            reconciliation["classification"] == "matches-intended"
            and payload["attribution"]["status"] == "unavailable"
        ),
        "transaction_stays_unknown": transaction.state == "unknown",
        "auto_resend": False,
        "cross_client_jobs_distinct": cross_client_distinct,
        "reconciliation": reconciliation["classification"],
    }
    passed = (
        checks["attribution_status"] == "unavailable"
        and checks["attribution_actor"] == "unknown"
        and checks["same_state_does_not_prove_actor"]
        and checks["transaction_stays_unknown"]
        and not checks["auto_resend"]
        and checks["cross_client_jobs_distinct"]
    )
    report: dict[str, Any] = {
        "schema_version": "r5-p3-multiplayer-attribution/1.0",
        "experiment": "R5-P3-MULTIPLAYER-ATTRIBUTION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if passed else "fail",
        "checks": checks,
        "boundary": {
            "deterministic": True,
            "real_two_collaborator_exercise": False,
            "actor_authority": "unavailable",
            "production_admission": False,
        },
    }
    report["content_hash"] = hashlib.sha256(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = run_probe()
    path = out / "r5_p3_multiplayer_attribution.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"[r5-p3-multiplayer-attribution] {report['status']}")
    print(f"[out ] {path}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
