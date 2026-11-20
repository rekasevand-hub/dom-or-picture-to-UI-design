from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.p5_partial_release_probe import run_probe


EXPERIMENTS = Path(__file__).resolve().parents[2] / "output/_r5_experiments"


def _experiments_present() -> bool:
    """These probes replay frozen R5 experiment artefacts, which live under output/.

    Without them the probe reports "failed" - correctly, it cannot find its
    evidence - so the assertion is skipped with the reason instead of pretending
    the code regressed.
    """
    return EXPERIMENTS.is_dir()


class P5PartialReleaseProbeTests(unittest.TestCase):
    def test_detector_backed_probe_preserves_partial_and_unknown_states(self) -> None:
        if not _experiments_present():
            self.skipTest("R5 experiment artefacts are not part of this checkout")
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
