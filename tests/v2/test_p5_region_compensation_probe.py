from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.p5_region_compensation_probe import run_probe


class RegionCompensationProbeTests(unittest.TestCase):
    def test_probe_exercises_production_expected_path_and_region_boundary(
        self,
    ) -> None:
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
