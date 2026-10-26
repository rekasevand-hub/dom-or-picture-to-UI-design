"""Audit P5 evidence without promoting pending policy rulings."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "p5-evidence-audit/1.0"
REQUIRED_INPUTS = (
    "figma_document_url",
    "operator",
    "page_name",
    "root_frame_node_id",
    "saved_version",
)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def audit_evidence(
    report_path: str | Path,
    *,
    inputs_path: str | Path | None = None,
    max_journal_events: int | None = None,
    pending_rulings: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    report_file = Path(report_path).resolve()
    report = _load_object(report_file, "soak report")
    checks: dict[str, bool] = {}
    observed: dict[str, Any] = {}

    expected_hash = report.get("content_hash")
    payload = {
        key: value for key, value in report.items() if key != "content_hash"
    }
    calculated_hash = _canonical_hash(payload)
    checks["content_hash_matches"] = (
        isinstance(expected_hash, str)
        and expected_hash == calculated_hash
    )
    observed["report_content_hash"] = expected_hash
    observed["calculated_content_hash"] = calculated_hash

    requested = report.get("requested")
    succeeded = report.get("succeeded")
    failed = report.get("failed")
    checks["request_counts_present"] = all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (requested, succeeded, failed)
    )
    checks["all_requests_succeeded"] = (
        checks["request_counts_present"]
        and requested > 0
        and succeeded == requested
        and failed == 0
        and report.get("all_requests_succeeded") is True
    )
    checks["report_status_pass"] = report.get("status") == "pass"

    setup_cleanup = report.get("setup_cleanup")
    if not isinstance(setup_cleanup, dict):
        setup_cleanup = {}
    checks["owned_setup_verified"] = (
        setup_cleanup.get("setup_verified") is True
    )
    checks["exact_cleanup_verified"] = (
        setup_cleanup.get("cleanup_verified") is True
        and report.get("exact_cleanup_verified") is True
    )

    journal_events = report.get("journal_events")
    report_max = report.get("max_journal_events")
    effective_max = max_journal_events
    if effective_max is None and isinstance(report_max, int):
        effective_max = report_max
    journal_inputs_valid = (
        isinstance(journal_events, int)
        and not isinstance(journal_events, bool)
        and isinstance(effective_max, int)
        and not isinstance(effective_max, bool)
        and effective_max > 0
    )
    calculated_bounded = (
        journal_inputs_valid
        and 0 <= journal_events <= effective_max
    )
    reported_bounded = report.get("journal_bounded")
    checks["journal_bound_inputs_present"] = journal_inputs_valid
    checks["journal_bounded"] = calculated_bounded
    checks["journal_bound_consistent"] = (
        reported_bounded is None or reported_bounded is calculated_bounded
    )
    observed["journal_events"] = journal_events
    observed["max_journal_events"] = effective_max

    if inputs_path is not None:
        input_file = Path(inputs_path).resolve()
        pilot_inputs = _load_object(input_file, "pilot inputs")
        missing_inputs = [
            key for key in REQUIRED_INPUTS if not _nonempty_string(pilot_inputs.get(key))
        ]
        checks["pilot_inputs_complete"] = not missing_inputs
        observed["pilot_inputs_path"] = str(input_file)
        observed["missing_pilot_inputs"] = missing_inputs

    failed_checks = [name for name, passed in checks.items() if not passed]
    mechanical_pass = not failed_checks
    normalized_rulings = list(
        dict.fromkeys(
            str(item).strip()
            for item in pending_rulings
            if str(item).strip()
        )
    )
    if not mechanical_pass:
        claim_status = "blocked-mechanical"
    elif normalized_rulings:
        claim_status = "blocked-pending-rulings"
    else:
        claim_status = "eligible-for-review"

    return {
        "schema": SCHEMA,
        "report_path": str(report_file),
        "report_status": report.get("status"),
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "journal_events": journal_events,
        "max_journal_events": effective_max,
        "checks": checks,
        "failed_checks": failed_checks,
        "observed": observed,
        "mechanical_pass": mechanical_pass,
        "pending_rulings": normalized_rulings,
        "claim_status": claim_status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--inputs", default=None)
    parser.add_argument("--max-journal-events", type=int, default=None)
    parser.add_argument("--pending-ruling", action="append", default=[])
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    audit = audit_evidence(
        args.report,
        inputs_path=args.inputs,
        max_journal_events=args.max_journal_events,
        pending_rulings=args.pending_ruling,
    )
    if args.out:
        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(
        f"mechanical_pass={audit['mechanical_pass']} "
        f"claim_status={audit['claim_status']}"
    )
    if audit["failed_checks"]:
        print("failed_checks=" + ",".join(audit["failed_checks"]))
    return 0 if audit["mechanical_pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
