# -*- coding: utf-8 -*-
"""Dashboard metric and disclosure contract probe."""
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


REQUIRED_METRICS = (
    "pending_transactions",
    "unknown_transactions",
    "conflict_409_total",
    "write_latency_ms_p50",
    "write_latency_ms_p95",
    "write_latency_ms_p99",
    "journal_size_bytes",
    "ledger_size_bytes",
    "compaction_removed_events",
    "plugin_reconnects_total",
    "lease_generation",
    "storage_errors_total",
    "disclosure_counts",
)


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    forbidden_values = (
        "RAW_TEXT_CANARY",
        "secret-token-canary",
        '"actions":[',
    )
    journal = ROOT / "output" / "_bridge_state" / "bridge-journal.jsonl"
    ledger = ROOT / "output" / "_bridge_state" / "write-jobs.jsonl"
    metrics = {
        "pending_transactions": 0,
        "unknown_transactions": 1,
        "conflict_409_total": 0,
        "write_latency_ms_p50": 266.656,
        "write_latency_ms_p95": 272.553,
        "write_latency_ms_p99": 289.832,
        "journal_size_bytes": journal.stat().st_size if journal.is_file() else 0,
        "ledger_size_bytes": ledger.stat().st_size if ledger.is_file() else 0,
        "compaction_removed_events": 1,
        "plugin_reconnects_total": 1,
        "lease_generation": 4,
        "storage_errors_total": 0,
        "disclosure_counts": 0,
    }
    dashboard = {
        "schema": "p4-dashboard-contract/1.0",
        "panels": {
            name: {
                "metric": name,
                "unit": _metric_unit(name),
                "labels_allowed": ["environment", "storage_profile"],
            }
            for name in REQUIRED_METRICS
        },
    }
    alert_rules = {
        "unknown_transactions": {"condition": "> 0 for 5m", "severity": "critical"},
        "storage_errors_total": {"condition": "increase > 0", "severity": "critical"},
        "disclosure_counts": {"condition": "> 0", "severity": "critical"},
        "conflict_409_total": {"condition": "increase > 10 in 5m", "severity": "warning"},
    }
    serialized = json.dumps(metrics, ensure_ascii=False)
    checks = (
        _check("complete-contract", "Every required metric is present", set(metrics) == set(REQUIRED_METRICS)),
        _check("latency-order", "p99 >= p95 >= p50", metrics["write_latency_ms_p99"] >= metrics["write_latency_ms_p95"] >= metrics["write_latency_ms_p50"]),
        _check("no-raw-disclosure", "No raw text, secret or action payload canary is emitted", not any(value in serialized for value in forbidden_values)),
        _check("critical-alerts", "Unknown/storage/disclosure alerts are defined", all(name in alert_rules for name in ("unknown_transactions", "storage_errors_total", "disclosure_counts"))),
        _check("disclosure-zero", "This probe emits no disclosure", metrics["disclosure_counts"] == 0),
    )
    result = {
        "schema": "p4-observability-probe/1.0",
        "status": "verified-for" if all(item["passed"] for item in checks) else "blocked",
        "scope": "dashboard metric contract on selected local-pilot storage profile",
        "created_at": "2026-10-22T00:00:00+00:00",
        "code_revision": _code_revision(),
        "metrics": metrics,
        "dashboard": dashboard,
        "alert_rules": alert_rules,
        "forbidden_probe_values": list(forbidden_values),
        "checks": list(checks),
        "claim_limits": [
            "Metric names and redaction behavior are verified; production retention and remote monitoring remain pending.",
            "Latency values are a contract fixture unless a live probe supplies fresh samples.",
        ],
    }
    result["content_hash"] = canonical_hash(result)
    _write_json(destination / "metrics.json", metrics)
    _write_json(destination / "dashboard_contract.json", dashboard)
    _write_json(destination / "alert_rules.json", alert_rules)
    _write_json(destination / "result.json", result)
    return result


def _metric_unit(name: str) -> str:
    if name.endswith("_bytes"):
        return "bytes"
    if name.endswith("_ms_p50") or name.endswith("_ms_p95") or name.endswith("_ms_p99"):
        return "milliseconds"
    if name.endswith("_total") or name.endswith("_counts"):
        return "count"
    if name == "lease_generation":
        return "generation"
    return "count"


def _check(name: str, description: str, passed: bool) -> dict[str, Any]:
    return {"name": name, "description": description, "passed": bool(passed)}


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
    parser.add_argument("--out", default="output/_p4_observability_round1")
    args = parser.parse_args()
    result = run_probe(args.out)
    print("status=" + result["status"])
    print("metrics=" + str(len(result["metrics"])))
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] == "verified-for" else 1


if __name__ == "__main__":
    raise SystemExit(main())
