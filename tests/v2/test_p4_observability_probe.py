from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.p4_observability_probe import REQUIRED_METRICS, run_probe


class ObservabilityProbeTests(unittest.TestCase):
    def test_metric_contract_is_complete_and_discloses_no_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_probe(output)

            self.assertEqual(result["status"], "verified-for")
            self.assertEqual(set(result["metrics"]), set(REQUIRED_METRICS))
            self.assertTrue(all(item["passed"] for item in result["checks"]))
            metrics_text = (output / "metrics.json").read_text(encoding="utf-8")
            for forbidden in result["forbidden_probe_values"]:
                self.assertNotIn(forbidden, metrics_text)
            self.assertIn("dashboard", result)
            self.assertIn("alert_rules", result)


if __name__ == "__main__":
    unittest.main()
