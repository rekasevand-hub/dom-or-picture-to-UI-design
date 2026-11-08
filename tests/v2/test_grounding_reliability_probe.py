from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.grounding_reliability_probe import run_probe


class GroundingReliabilityProbeTests(unittest.TestCase):
    def test_probe_emits_failover_recovery_and_finite_retry_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_probe(output)
            persisted = json.loads((output / "result.json").read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "pass-current-scope")
        self.assertEqual(result["content_hash"], persisted["content_hash"])
        checks = {item["name"]: item["passed"] for item in result["checks"]}
        self.assertTrue(checks["endpoint-failover"])
        self.assertTrue(checks["bounded-retry"])
        self.assertTrue(checks["breaker-recovers"])
        self.assertTrue(checks["malformed-does-not-fallback"])
        self.assertTrue(checks["cache-hit-and-isolation"])
        self.assertFalse(result["boundary"]["real_network"])
        self.assertIn("no-real-grounding-service", result["non_claims"])


if __name__ == "__main__":
    unittest.main()
