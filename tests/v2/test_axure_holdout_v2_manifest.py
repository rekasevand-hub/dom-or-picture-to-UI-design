from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests/fixtures/axure_holdout_v2/holdout_v2.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AxureHoldoutV2ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_uses_new_samples_and_excludes_all_prior_axure_samples(self) -> None:
        sample_ids = [sample["sample_id"] for sample in self.manifest["samples"]]
        excluded = set(self.manifest["tuning_exclusions"])

        self.assertEqual(
            sample_ids,
            ["AX6-DOM-TEXTFLOW", "AX6-DOM-FONTFALLBACK", "AX6-IMG-OVERLAY"],
        )
        self.assertEqual(
            excluded,
            {"DQ-R02", "IMG-MVP-01", "DQ-R01", "DQ-R03", "AX-IMG-H01"},
        )
        self.assertTrue(self.manifest["thresholds"]["forbidden_sample_substitution"])

    def test_freezes_acceptance_thresholds(self) -> None:
        thresholds = self.manifest["thresholds"]

        self.assertEqual(thresholds["critical_text_rate"], 1.0)
        self.assertEqual(thresholds["expected_asset_hash_rate"], 1.0)
        self.assertTrue(thresholds["expected_asset_count_exact"])
        self.assertEqual(thresholds["page_package_object_match_rate"], 1.0)
        self.assertEqual(thresholds["visual_within30_min_pct"], 90.0)
        self.assertTrue(thresholds["deterministic_rp_byte_identical"])
        self.assertTrue(thresholds["size_match_required"])
        self.assertFalse(thresholds["composite_score_allowed"])

    def test_every_input_and_prepared_design_hash_matches(self) -> None:
        for sample in self.manifest["samples"]:
            paths = ["truth_path", "design_path"]
            if sample["input_kind"] == "dom":
                paths.append("screenshot_path")
            else:
                paths.append("image_path")
            for path_key in paths:
                path = ROOT / sample[path_key]
                self.assertTrue(path.is_file(), f"{sample['sample_id']}:{path_key}")
                hash_key = path_key.replace("_path", "_sha256")
                self.assertEqual(
                    _sha256(path),
                    sample[hash_key].lower(),
                    f"{sample['sample_id']}:{hash_key}",
                )


if __name__ == "__main__":
    unittest.main()
