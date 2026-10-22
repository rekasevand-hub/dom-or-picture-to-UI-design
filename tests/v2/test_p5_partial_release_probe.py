from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.p5_partial_release_probe import run_probe


class P5PartialReleaseProbeTests(unittest.TestCase):
    def test_detector_backed_probe_preserves_partial_and_unknown_states(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_probe(output)

            self.assertEqual(result["status"], "verified-for")
            self.assertTrue(all(item["passed"] for item in result["checks"]))
            self.assertEqual(
                set(result["coverage_state_counts"]),
                {
                    "intentional-omission",
                    "write-failed",
                    "observed-absent",
                    "not-captured",
                },
            )
            self.assertFalse(result["release"]["complete_export_allowed"])
            self.assertTrue((output / "result.json").is_file())
            self.assertTrue((output / "partial_report.json").is_file())
            self.assertTrue((output / "manifest.json").is_file())
            report = json.loads(
                (output / "partial_report.json").read_text(encoding="utf-8")
            )
            self.assertTrue(report["root_name"].startswith("[PARTIAL]"))
            self.assertTrue(report["outside_business_flow"])


if __name__ == "__main__":
    unittest.main()
