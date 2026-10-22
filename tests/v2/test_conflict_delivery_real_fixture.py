from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.p5_conflict_delivery_probe import run_probe


class ConflictDeliveryRealFixtureTests(unittest.TestCase):
    def test_authored_chromium_probe_keeps_unresolved_values_out_of_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_probe(output)

            self.assertEqual(
                result["status"],
                "verified-for",
            )
            self.assertTrue(result["environment"]["chromium_version"])
            self.assertTrue(result["evidence"]["screenshot_sha256"])
            self.assertTrue(all(item["passed"] for item in result["checks"]))
            self.assertNotIn(
                result["conflict_candidate_text"],
                json.dumps(result["content"], ensure_ascii=False),
            )
            self.assertNotIn(
                result["ocr_candidate_text"],
                json.dumps(result["content"], ensure_ascii=False),
            )
            for name in (
                "result.json",
                "report.json",
                "conflict_resolution.json",
                "dom_observations.json",
                "screenshot.png",
            ):
                self.assertTrue((output / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
