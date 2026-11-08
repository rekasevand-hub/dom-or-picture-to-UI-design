from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.p5_collaboration_bridge_probe import run_probe


class P5CollaborationBridgeProbeTests(unittest.TestCase):
    def test_probe_proves_current_scope_collaboration_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_probe(output)
            persisted = json.loads((output / "result.json").read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "pass-current-scope")
        self.assertEqual(persisted["content_hash"], result["content_hash"])
        self.assertTrue(result["source_hashes"]["bridge_server"])
        self.assertTrue(result["source_hashes"]["write_lease"])
        self.assertTrue(result["source_hashes"]["write_job_ledger"])
        checks = {item["name"]: item["passed"] for item in result["checks"]}
        self.assertTrue(checks["two-clients-committed"])
        self.assertTrue(checks["serialized-plugin-writes"])
        self.assertTrue(checks["duplicate-request-single-dispatch"])
        self.assertTrue(checks["takeover-closes-old-plugin"])
        self.assertTrue(checks["unknown-not-resent"])
        self.assertTrue(checks["ownership-readback-reconciled"])
        self.assertTrue(checks["journal-preserved"])
        self.assertFalse(result["boundary"]["real_figma"])
        self.assertEqual(
            result["boundary"]["transport"],
            "deterministic-fake-plugin",
        )
        self.assertIn("real-collaborator-attribution", result["non_claims"])


if __name__ == "__main__":
    unittest.main()
