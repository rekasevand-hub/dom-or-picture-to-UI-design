from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.r5_p3_ledger_lifecycle_probe import run_probe


class R5P3LedgerLifecycleProbeTests(unittest.TestCase):
    def test_probe_emits_deterministic_sanitized_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = run_probe(Path(temp_dir))

            self.assertEqual(report["status"], "pass")
            self.assertTrue(report["checks"]["migration_dry_run_no_target"])
            self.assertTrue(report["checks"]["cross_client_same_raw_distinct"])
            self.assertTrue(report["checks"]["nonterminal_states_preserved"])
            self.assertTrue(report["checks"]["cleanup_receipt_preserved"])
            self.assertTrue(report["checks"]["duplicate_fingerprint_conflict_preserved"])
            self.assertTrue(report["checks"]["migration_report_sanitized"])
            serialized = json.dumps(report)
            self.assertNotIn("shared-legacy-job", serialized)
            self.assertNotIn("MUST_NOT_LEAK", serialized)
            self.assertIn("report_sha256", report)


if __name__ == "__main__":
    unittest.main()
