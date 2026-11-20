from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.p5_region_compensation_probe import run_probe


EXPERIMENTS = Path(__file__).resolve().parents[2] / "output/_r5_experiments"


def _experiments_present() -> bool:
    """These probes replay frozen R5 experiment artefacts, which live under output/.

    Without them the probe reports "failed" - correctly, it cannot find its
    evidence - so the assertion is skipped with the reason instead of pretending
    the code regressed.
    """
    return EXPERIMENTS.is_dir()


class RegionCompensationProbeTests(unittest.TestCase):
    def test_probe_exercises_production_expected_path_and_region_boundary(
        self,
    ) -> None:
        if not _experiments_present():
            self.skipTest("R5 experiment artefacts are not part of this checkout")
        with tempfile.TemporaryDirectory() as raw_dir:
            result = run_probe(Path(raw_dir))

            self.assertEqual(result["status"], "completed-for-current-scope")
            self.assertTrue(all(item["passed"] for item in result["checks"]))
            self.assertEqual(
                result["evaluations"]["production-expected"]["classification"],
                "matches-intended",
            )
            self.assertEqual(
                result["evaluations"]["partial-region"]["regions"]["region-a"][
                    "classification"
                ],
                "matches-intended",
            )
            self.assertEqual(
                result["plans"]["out-of-region"]["preserved_node_ids"],
                ["1:2"],
            )
            self.assertEqual(
                result["plans"]["out-of-region"]["unknown_node_ids"],
                ["1:3"],
            )


if __name__ == "__main__":
    unittest.main()
