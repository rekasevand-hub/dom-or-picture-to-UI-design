from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests/fixtures/axure_holdout/holdout_v1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AxureHoldoutManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_freezes_required_samples_and_excludes_tuning_inputs(self) -> None:
        sample_ids = [sample["sample_id"] for sample in self.manifest["samples"]]
        excluded = {row["sample_id"] for row in self.manifest["tuning_exclusions"]}

        self.assertEqual(sample_ids, ["DQ-R01", "DQ-R03", "AX-IMG-H01"])
        self.assertEqual(excluded, {"DQ-R02", "IMG-MVP-01"})
        self.assertTrue(self.manifest["thresholds"]["forbidden_sample_substitution"])

    def test_freezes_thresholds_before_measurement(self) -> None:
        thresholds = self.manifest["thresholds"]

        self.assertEqual(thresholds["critical_text_rate"], 1.0)
        self.assertEqual(thresholds["page_package_object_match_rate"], 1.0)
        self.assertEqual(thresholds["expected_image_hash_rate"], 1.0)
        self.assertEqual(thresholds["visual_within30_min_pct"], 90.0)
        self.assertTrue(thresholds["deterministic_rp_byte_identical"])
        self.assertTrue(thresholds["size_match_required"])
        self.assertFalse(thresholds["composite_score_allowed"])

    def test_every_declared_input_exists_with_the_frozen_hash(self) -> None:
        for sample in self.manifest["samples"]:
            if sample["input_kind"] == "dom":
                declared = [
                    ("corpus_manifest", "corpus_manifest_sha256"),
                    ("dom_path", "dom_sha256"),
                    ("screenshot_path", "screenshot_sha256"),
                ]
            else:
                declared = [
                    ("image_path", "image_sha256"),
                    ("truth_path", "truth_sha256"),
                ]
            for path_key, hash_key in declared:
                path = ROOT / sample[path_key]
                self.assertTrue(path.is_file(), sample["sample_id"] + ":" + path_key)
                self.assertEqual(
                    _sha256(path),
                    sample[hash_key].lower(),
                    sample["sample_id"] + ":" + hash_key,
                )


if __name__ == "__main__":
    unittest.main()
