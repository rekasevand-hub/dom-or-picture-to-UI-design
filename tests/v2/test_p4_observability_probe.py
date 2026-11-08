from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.p4_observability_probe import REQUIRED_METRICS, run_probe


class ObservabilityProbeTests(unittest.TestCase):
    def test_metric_contract_is_complete_and_discloses_no_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_probe(
                output,
                fallback_observations=[
                    {
                        "grounding_unavailable": True,
                        "fallback_triggered": True,
                        "fallback_selection_accepted": True,
                        "fallback_latency_ms": 700.0,
                        "token_usage": {"total_tokens": 12},
                        "write_before_decision": False,
                    },
                    {
                        "grounding_unavailable": True,
                        "fallback_triggered": True,
                        "fallback_selection_accepted": False,
                        "fallback_latency_ms": 900.0,
                        "token_usage": {"total_tokens": 20},
                        "write_before_decision": False,
                    },
                ],
            )

            self.assertEqual(result["status"], "verified-for")
            self.assertEqual(set(result["metrics"]), set(REQUIRED_METRICS))
            self.assertTrue(all(item["passed"] for item in result["checks"]))
            metrics_text = (output / "metrics.json").read_text(encoding="utf-8")
            for forbidden in result["forbidden_probe_values"]:
                self.assertNotIn(forbidden, metrics_text)
            self.assertIn("dashboard", result)
            self.assertIn("alert_rules", result)
            self.assertEqual(result["metrics"]["grounding_unavailable_total"], 2)
            self.assertEqual(result["metrics"]["fallback_trigger_total"], 2)
            self.assertEqual(
                result["metrics"]["fallback_selection_accepted_total"],
                1,
            )
            self.assertEqual(
                result["metrics"]["fallback_write_before_block_total"],
                0,
            )
            self.assertEqual(
                result["metrics"]["fallback_token_usage_total"],
                32,
            )
            self.assertEqual(
                result["metrics"]["fallback_latency_ms_p50"],
                700.0,
            )
            self.assertIn(
                "fallback_write_before_block_total",
                result["alert_rules"],
            )


if __name__ == "__main__":
    unittest.main()
