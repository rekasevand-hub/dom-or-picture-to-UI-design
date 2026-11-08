from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.fallback_observability_probe import run_probe


class FallbackObservabilityProbeTests(unittest.TestCase):
    def test_probe_emits_prewrite_fallback_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_probe(output)
            observation = json.loads(
                (output / "fallback_observability.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result["status"], "pass-current-scope")
        self.assertTrue(observation["fallback_triggered"])
        self.assertTrue(observation["fallback_selection_accepted"])
        self.assertFalse(observation["write_before_decision"])
        self.assertEqual(
            observation["fallback_quality_acceptance"],
            "not-evaluated",
        )
        self.assertIsNone(observation["estimated_cost_usd"])


if __name__ == "__main__":
    unittest.main()
