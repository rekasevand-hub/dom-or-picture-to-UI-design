from __future__ import annotations

import re
import unittest
from pathlib import Path


MATRIX = Path("docs/v2_mentor/PRODUCTION_VERIFICATION_MATRIX.md")
REQUIRED_COLUMNS = {
    "claim_id",
    "dimension",
    "claim",
    "environment",
    "code_revision",
    "plugin_build",
    "test_set",
    "thresholds",
    "evidence_hash",
    "status",
    "residual_unknown",
}
REQUIRED_CLAIMS = {
    "PV-01",
    "PV-02",
    "PV-03",
    "PV-04",
    "PV-05",
    "PV-06",
    "PV-07",
    "PV-08",
    "PV-09",
}


def _rows(text: str):
    lines = text.splitlines()
    header_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("| Claim ID | Dimension |")
    )
    header = [
        cell.strip().lower().replace(" ", "_")
        for cell in lines[header_index].strip("|").split("|")
    ]
    rows = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append(dict(zip(header, cells, strict=True)))
    return header, rows


class ProductionVerificationMatrixTests(unittest.TestCase):
    def test_every_claim_has_bounded_evidence_fields(self) -> None:
        text = MATRIX.read_text(encoding="utf-8")
        header, rows = _rows(text)

        self.assertEqual(set(header), REQUIRED_COLUMNS)
        self.assertEqual({row["claim_id"] for row in rows}, REQUIRED_CLAIMS)
        for row in rows:
            self.assertTrue(row["environment"])
            self.assertTrue(row["code_revision"])
            self.assertTrue(row["plugin_build"])
            self.assertTrue(row["test_set"])
            self.assertTrue(row["thresholds"])
            self.assertTrue(row["evidence_hash"])
            self.assertTrue(row["residual_unknown"])
            if row["status"].startswith("verified-for"):
                self.assertRegex(row["evidence_hash"], r"\b[0-9a-f]{16,64}\b")

    def test_matrix_has_no_project_wide_verification_claim(self) -> None:
        text = MATRIX.read_text(encoding="utf-8")

        self.assertIsNone(
            re.search(r"\bverified\s*=\s*true\b", text, flags=re.IGNORECASE)
        )
        self.assertIn("production-not-admitted", text)


if __name__ == "__main__":
    unittest.main()
