from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.p5_evidence_audit import audit_evidence


def _write_report(path: Path, report: dict) -> dict:
    payload = {key: value for key, value in report.items() if key != "content_hash"}
    report = dict(report)
    report["content_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def _passing_report() -> dict:
    return {
        "all_requests_succeeded": True,
        "exact_cleanup_verified": True,
        "failed": 0,
        "journal_bounded": True,
        "journal_events": 100,
        "max_journal_events": 4096,
        "requested": 100,
        "setup_cleanup": {
            "cleanup_verified": True,
            "setup_verified": True,
        },
        "status": "pass",
        "succeeded": 100,
    }


def _inputs() -> dict:
    return {
        "figma_document_url": "https://www.figma.com/design/file/pilot",
        "page_name": "P5 Pilot",
        "root_frame_node_id": "59:2",
        "saved_version": "1h_test",
        "operator": "user",
    }


class P5EvidenceAuditTests(unittest.TestCase):
    def test_valid_evidence_is_eligible_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            report_path = Path(raw_dir) / "soak.json"
            inputs_path = Path(raw_dir) / "inputs.json"
            _write_report(report_path, _passing_report())
            inputs_path.write_text(
                json.dumps(_inputs(), ensure_ascii=False),
                encoding="utf-8",
            )

            audit = audit_evidence(
                report_path,
                inputs_path=inputs_path,
            )

        self.assertTrue(audit["mechanical_pass"])
        self.assertEqual(audit["claim_status"], "eligible-for-review")
        self.assertEqual(audit["failed_checks"], [])

    def test_tampered_report_content_fails_hash_verification(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            report_path = Path(raw_dir) / "soak.json"
            report = _write_report(report_path, _passing_report())
            report["succeeded"] = 99
            report_path.write_text(
                json.dumps(report, ensure_ascii=False),
                encoding="utf-8",
            )

            audit = audit_evidence(report_path)

        self.assertFalse(audit["mechanical_pass"])
        self.assertIn("content_hash_matches", audit["failed_checks"])

    def test_pending_rulings_block_claim_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            report_path = Path(raw_dir) / "soak.json"
            _write_report(report_path, _passing_report())

            audit = audit_evidence(
                report_path,
                pending_rulings=("Q8", "Q9", "Q10"),
            )

        self.assertTrue(audit["mechanical_pass"])
        self.assertEqual(audit["claim_status"], "blocked-pending-rulings")
        self.assertEqual(audit["pending_rulings"], ["Q8", "Q9", "Q10"])

    def test_incomplete_pilot_inputs_fail_evidence_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            report_path = Path(raw_dir) / "soak.json"
            inputs_path = Path(raw_dir) / "inputs.json"
            _write_report(report_path, _passing_report())
            inputs_path.write_text(
                json.dumps({"operator": "user"}),
                encoding="utf-8",
            )

            audit = audit_evidence(
                report_path,
                inputs_path=inputs_path,
            )

        self.assertFalse(audit["mechanical_pass"])
        self.assertIn("pilot_inputs_complete", audit["failed_checks"])

    def test_cleanup_or_journal_failure_blocks_mechanical_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            report_path = Path(raw_dir) / "soak.json"
            report = _passing_report()
            report["status"] = "fail"
            report["exact_cleanup_verified"] = False
            report["journal_events"] = 5000
            report["journal_bounded"] = False
            _write_report(report_path, report)

            audit = audit_evidence(report_path)

        self.assertFalse(audit["mechanical_pass"])
        self.assertIn("report_status_pass", audit["failed_checks"])
        self.assertIn("exact_cleanup_verified", audit["failed_checks"])
        self.assertIn("journal_bounded", audit["failed_checks"])


if __name__ == "__main__":
    unittest.main()
