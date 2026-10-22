from __future__ import annotations

import re
import unittest
from pathlib import Path


DECISION = Path("docs/v2_mentor/R5_PRODUCTION_ADMISSION_DECISION.md")
RISK_IDS = {f"RR-{index:03d}" for index in range(1, 16)}
PREREQUISITES = {
    "identity-secret-lifecycle",
    "permission-and-takeover",
    "single-writer-fencing",
    "backup-and-restore",
    "monitoring-and-alerts",
    "incident-response",
    "production-long-soak",
}


def _table_rows(text: str, marker: str):
    lines = text.splitlines()
    header_index = next(
        index for index, line in enumerate(lines) if line.startswith(marker)
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
    return rows


class ProductionAdmissionDecisionTests(unittest.TestCase):
    def test_decision_is_not_admitted_with_blocking_evidence_gaps(self) -> None:
        text = DECISION.read_text(encoding="utf-8")

        self.assertIn("Decision: `not-admitted`", text)
        self.assertIn("P5 pilot: `not-run`", text)
        self.assertIn("Production long soak: `not-run`", text)

    def test_all_fifteen_residual_risks_are_reviewed(self) -> None:
        text = DECISION.read_text(encoding="utf-8")
        rows = _table_rows(text, "| Risk ID |")
        by_id = {row["risk_id"]: row for row in rows}

        self.assertEqual(set(by_id), RISK_IDS)
        for risk_id, row in by_id.items():
            self.assertTrue(row["owner"], risk_id)
            self.assertTrue(row["mitigation"], risk_id)
            self.assertTrue(row["evidence"], risk_id)
            self.assertTrue(row["rollback"], risk_id)
            self.assertTrue(row["expiry_or_resolution"], risk_id)
            self.assertIn(
                row["disposition"],
                {"blocking", "conditional", "accepted-with-owner", "resolved"},
                risk_id,
            )
        self.assertGreaterEqual(
            sum(row["disposition"] == "blocking" for row in rows),
            1,
        )

    def test_all_production_prerequisites_are_blocking_or_incomplete(self) -> None:
        text = DECISION.read_text(encoding="utf-8")
        rows = _table_rows(text, "| Prerequisite |")
        names = {row["prerequisite"] for row in rows}

        self.assertTrue(PREREQUISITES.issubset(names))
        for row in rows:
            if row["prerequisite"] in PREREQUISITES:
                self.assertIn(
                    row["status"],
                    {"blocked", "not-run", "current-scope", "incomplete"},
                )

    def test_release_scope_names_actions_environment_and_exclusions(self) -> None:
        text = DECISION.read_text(encoding="utf-8")

        self.assertIn("Supported environment:", text)
        self.assertIn("Supported actions:", text)
        self.assertIn("Document scope:", text)
        self.assertIn("Exclusions:", text)
        self.assertIsNone(
            re.search(r"\bverified\s*=\s*true\b", text, flags=re.IGNORECASE)
        )


if __name__ == "__main__":
    unittest.main()
