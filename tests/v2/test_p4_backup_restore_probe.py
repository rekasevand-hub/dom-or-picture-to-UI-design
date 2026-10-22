from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.p4_backup_restore_probe import run_probe


class BackupRestoreProbeTests(unittest.TestCase):
    def test_corruption_is_detected_and_restore_preserves_contract_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_probe(output)

            self.assertEqual(result["status"], "verified-for")
            self.assertTrue(result["corruption_detected"])
            self.assertTrue(result["restore"]["verified"])
            self.assertTrue(all(item["passed"] for item in result["checks"]))
            restored = json.loads(
                (output / "restore_record.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                restored["runtime_ir"]["tombstones"][0]["tombstone_id"],
                "tomb-backup",
            )
            self.assertEqual(
                restored["runtime_ir"]["unknowns"][0]["status"],
                "unknown",
            )
            self.assertTrue(restored["runtime_ir"]["evidence"])
            self.assertEqual(
                restored["release_decision"]["status"],
                "deliverable-partial",
            )
            for name in (
                "backup_manifest.json",
                "restore_report.json",
                "migration_report.json",
                "result.json",
            ):
                self.assertTrue((output / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
