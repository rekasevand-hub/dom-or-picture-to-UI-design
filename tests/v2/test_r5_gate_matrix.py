from __future__ import annotations

import re
import unittest
from pathlib import Path


MATRIX_PATH = Path("docs/v2_mentor/R5_GATE_MATRIX.md")

REQUIRED_BLOCKERS = {
    "P5-CONTRACT-PROFILE",
    "P5-CONFLICT-DELIVERY",
    "P5-OUTPUT-FIDELITY",
    "P5-PARTIAL-GATE",
    "P5-SINGLE-WRITER",
    "P5-LOCAL-STORE",
    "P5-FROZEN-REHEARSAL",
    "PROD-PERMISSION-TAKEOVER",
    "PROD-EXPECTED-STATE-COMPENSATION",
    "PROD-SECURITY-LIFECYCLE",
    "PROD-BACKUP-RESTORE-MONITORING",
    "PROD-PRODUCTION-STORE",
    "PROD-LONG-SOAK",
    "PROD-ADMISSION",
    "COND-FIREFOX",
    "COND-VARIABLE-FONT-AXIS",
    "COND-GLYPH-FALLBACK",
    "COND-CROSS-BROWSER-DOM",
    "COND-ADAPTIVE-AUTOLAYOUT",
    "COND-MULTI-TENANT-CROSS-HOST",
    "RR-001",
    "RR-002",
    "RR-003",
    "RR-004",
    "RR-005",
    "RR-006",
    "RR-007",
    "RR-008",
    "RR-009",
    "RR-010",
    "RR-011",
    "RR-012",
    "RR-013",
    "RR-014",
    "RR-015",
}

REQUIRED_COLUMNS = {
    "id",
    "gate",
    "claim",
    "environment",
    "evidence",
    "owner",
    "blocking",
    "status",
}

STATUS_VOCABULARY = (
    "current-scope",
    "pilot-verified",
    "verified-for:<scope>",
    "production-admitted",
)


def parse_main_table(text: str) -> tuple[list[str], list[dict[str, str]]]:
    lines = text.splitlines()
    try:
        header_index = next(
            index
            for index, line in enumerate(lines)
            if line.startswith("| ID | Gate | Claim |")
        )
    except StopIteration as exc:
        raise AssertionError("missing main gate table header") from exc

    header = [cell.strip().lower() for cell in lines[header_index].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(header):
            raise AssertionError(f"malformed gate row: {line}")
        rows.append(dict(zip(header, cells, strict=True)))
    return header, rows


class GateMatrixContractTests(unittest.TestCase):
    def test_every_blocker_has_one_complete_gate_row(self) -> None:
        text = MATRIX_PATH.read_text(encoding="utf-8")
        header, rows = parse_main_table(text)

        self.assertEqual(set(header), REQUIRED_COLUMNS)
        ids = [row["id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)), "gate ids must be unique")
        self.assertEqual(set(ids), REQUIRED_BLOCKERS)
        self.assertIn("P5_GATE", {row["gate"] for row in rows})
        self.assertIn("PRODUCTION_GATE", {row["gate"] for row in rows})

        for row in rows:
            self.assertEqual(
                set(row),
                REQUIRED_COLUMNS,
                f"{row['id']} must expose exactly the gate contract fields",
            )
            for field in REQUIRED_COLUMNS:
                self.assertTrue(row[field], f"{row['id']} has empty {field}")
            self.assertIn(
                row["gate"],
                {"P5_GATE", "PRODUCTION_GATE"},
                f"{row['id']} is not assigned to a frozen gate",
            )

    def test_conditional_claims_do_not_block_the_fixed_pilot(self) -> None:
        text = MATRIX_PATH.read_text(encoding="utf-8")
        _, rows = parse_main_table(text)

        conditional_rows = [row for row in rows if row["blocking"] == "conditional"]
        self.assertEqual(
            {row["id"] for row in conditional_rows},
            {
                "COND-FIREFOX",
                "COND-VARIABLE-FONT-AXIS",
                "COND-GLYPH-FALLBACK",
                "COND-CROSS-BROWSER-DOM",
                "COND-ADAPTIVE-AUTOLAYOUT",
                "COND-MULTI-TENANT-CROSS-HOST",
                "RR-001",
                "RR-002",
                "RR-003",
                "RR-004",
            },
        )
        for row in conditional_rows:
            self.assertEqual(row["status"], "conditional")

    def test_verification_vocabulary_is_explicit_and_not_project_wide(self) -> None:
        text = MATRIX_PATH.read_text(encoding="utf-8")

        for status in STATUS_VOCABULARY:
            self.assertIn(f"`{status}`", text)
        self.assertIsNone(
            re.search(r"\bverified\s*=\s*true\b", text, flags=re.IGNORECASE),
            "the gate matrix must not claim project-wide verified=true",
        )


if __name__ == "__main__":
    unittest.main()
