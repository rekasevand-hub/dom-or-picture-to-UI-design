from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.p5_pilot import decide_page, run_pilot


class P5PilotContractTests(unittest.TestCase):
    def test_blocking_conditions_never_get_provisional_pass(self) -> None:
        cases = (
            {"critical_unknown": True},
            {"unauthorized_action": True},
            {"unexplained_unknown_transaction": True},
            {"missing_evidence": True},
        )
        for case in cases:
            with self.subTest(case=case):
                decision = decide_page(
                    {
                        "sample_id": "sample-blocked",
                        **case,
                    }
                )
                self.assertEqual(decision["decision"], "manual-review")
                self.assertFalse(decision["release_allowed"])
                self.assertTrue(decision["blockers"])

    def test_clean_page_can_only_be_provisional(self) -> None:
        decision = decide_page(
            {
                "sample_id": "sample-clean",
                "critical_unknown": False,
                "unauthorized_action": False,
                "unexplained_unknown_transaction": False,
                "missing_evidence": False,
            }
        )

        self.assertEqual(decision["decision"], "pilot-allowed-provisional")
        self.assertTrue(decision["release_allowed"])

    def test_frozen_registry_keeps_all_failed_samples_in_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_pilot(output)

            self.assertEqual(result["status"], "blocked-environment")
            self.assertFalse(result["pilot_verified"])
            self.assertEqual(result["denominator"], len(result["pages"]))
            self.assertTrue(all(page["decision"] == "blocked" for page in result["pages"]))
            self.assertTrue((output / "pilot_manifest.json").is_file())
            self.assertTrue((output / "partial_unknown_report.json").is_file())
            manifest = json.loads(
                (output / "pilot_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["denominator"], result["denominator"])


if __name__ == "__main__":
    unittest.main()
