from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs" / "v2_mentor" / "DOM_QUALITY_GAP_REGISTER_2026-10-25.md"


class DomQualityGapRegisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = REGISTER.read_text(encoding="utf-8")

    def test_index_and_gap_sections_have_the_same_unique_ids(self) -> None:
        index_ids = re.findall(r"^\| (DOM-GAP-\d{3}) \|", self.text, re.MULTILINE)
        section_ids = re.findall(r"^### (DOM-GAP-\d{3})", self.text, re.MULTILINE)

        self.assertTrue(index_ids)
        self.assertEqual(len(index_ids), len(set(index_ids)))
        self.assertEqual(len(section_ids), len(set(section_ids)))
        self.assertEqual(index_ids, section_ids)

    def test_source_coverage_names_all_required_inputs(self) -> None:
        for source in ("R1", "R2", "R3-D", "P1", "P2", "P3"):
            self.assertIn(f"| {source} |", self.text)

    def test_required_gap_statuses_are_explained(self) -> None:
        for status in (
            "not-implemented",
            "implemented-not-verified",
            "verified-bounded-fixture",
            "blocked-environment",
            "out-of-current-scope",
        ):
            self.assertIn(f"`{status}`", self.text)

    def test_key_evidence_paths_are_linked(self) -> None:
        for path in (
            "README.md",
            "docs/v2_mentor/R2_EXP_01_DOM_FLOW_PERTURBATION.md",
            "docs/v2_mentor/P1_CANONICAL_OUTPUT_FIDELITY.md",
            "docs/v2_mentor/P3_GRID_COMPLEX_HOLDOUT.md",
        ):
            self.assertIn(path, self.text)


if __name__ == "__main__":
    unittest.main()
