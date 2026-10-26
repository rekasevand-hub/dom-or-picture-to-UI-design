from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests/fixtures/axure_holdout_v3/holdout_v3.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AxureHoldoutV3ManifestTests(unittest.TestCase):
    def _manifest(self) -> dict:
        self.assertTrue(MANIFEST.is_file(), f"missing manifest: {MANIFEST}")
        return json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_uses_fresh_samples_and_excludes_all_prior_axure_samples(self) -> None:
        manifest = self._manifest()
        sample_ids = [sample["sample_id"] for sample in manifest["samples"]]

        self.assertEqual(
            sample_ids,
            ["AX8-DOM-IFRAME", "AX8-DOM-PARTIAL-ASSET", "AX8-DOM-MOBILE320"],
        )
        self.assertEqual(
            set(manifest["tuning_exclusions"]),
            {
                "DQ-R02",
                "IMG-MVP-01",
                "DQ-R01",
                "DQ-R03",
                "AX-IMG-H01",
                "AX6-DOM-TEXTFLOW",
                "AX6-DOM-FONTFALLBACK",
                "AX6-IMG-OVERLAY",
            },
        )
        self.assertTrue(manifest["thresholds"]["forbidden_sample_substitution"])

    def test_freezes_acceptance_thresholds(self) -> None:
        thresholds = self._manifest()["thresholds"]

        self.assertEqual(thresholds["critical_text_rate"], 1.0)
        self.assertEqual(thresholds["expected_asset_hash_rate"], 1.0)
        self.assertTrue(thresholds["expected_asset_count_exact"])
        self.assertEqual(thresholds["page_package_object_match_rate"], 1.0)
        self.assertTrue(thresholds["deterministic_rp_byte_identical"])
        self.assertTrue(thresholds["size_match_required"])
        self.assertEqual(thresholds["visual_within30_min_pct"], 90.0)
        self.assertFalse(thresholds["composite_score_allowed"])

    def test_every_frozen_input_hash_matches(self) -> None:
        for sample in self._manifest()["samples"]:
            for path_key in ("design_path", "screenshot_path", "truth_path"):
                path = ROOT / sample[path_key]
                self.assertTrue(path.is_file(), f"{sample['sample_id']}:{path_key}")
                hash_key = path_key.replace("_path", "_sha256")
                self.assertEqual(
                    _sha256(path),
                    sample[hash_key].lower(),
                    f"{sample['sample_id']}:{hash_key}",
                )

    def test_partial_asset_separates_declared_from_renderable_assets(self) -> None:
        sample = next(
            item
            for item in self._manifest()["samples"]
            if item["sample_id"] == "AX8-DOM-PARTIAL-ASSET"
        )

        self.assertEqual(sample["declared_asset_count"], 2)
        self.assertEqual(sample["expected_asset_count"], 1)
        self.assertEqual(sample["missing_asset_count"], 1)


if __name__ == "__main__":
    unittest.main()
