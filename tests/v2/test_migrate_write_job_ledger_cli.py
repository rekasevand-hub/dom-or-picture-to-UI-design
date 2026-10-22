from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.migrate_write_job_ledger import main


def _event(*, client_id: str, state: str, fingerprint: str) -> dict[str, object]:
    return {
        "version": 2,
        "event": "state",
        "job_id": "legacy-job",
        "transaction_id": "legacy-job",
        "client_id": client_id,
        "request_id": "request-1",
        "fingerprint": fingerprint,
        "expected_created_nodes": 1,
        "state": state,
        "updated_at": 1000.0,
        "action": "create_text",
        "text": "MUST_NOT_APPEAR",
        "secret": "MUST_NOT_APPEAR",
    }


class MigrateWriteJobLedgerCliTests(unittest.TestCase):
    def _write_source(self, root: Path) -> tuple[Path, Path]:
        source = root / "legacy.jsonl"
        source.write_text(
            json.dumps(_event(client_id="legacy-a", state="committed", fingerprint="a" * 64))
            + "\n",
            encoding="utf-8",
        )
        mapping = root / "mapping.json"
        mapping.write_text(
            json.dumps({"legacy-a": "client-a"}),
            encoding="utf-8",
        )
        return source, mapping

    def test_cli_defaults_to_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, mapping = self._write_source(root)
            target = root / "migrated.jsonl"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--source",
                        str(source),
                        "--target",
                        str(target),
                        "--client-map",
                        str(mapping),
                    ]
                )

            report = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(report["status"], "dry-run")
            self.assertFalse(target.exists())
            serialized = json.dumps(report)
            self.assertNotIn("legacy-job", serialized)
            self.assertNotIn("legacy-a", serialized)
            self.assertNotIn("MUST_NOT_APPEAR", serialized)

    def test_cli_apply_writes_atomically_validated_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, mapping = self._write_source(root)
            target = root / "migrated.jsonl"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--source",
                        str(source),
                        "--target",
                        str(target),
                        "--client-map",
                        str(mapping),
                        "--apply",
                    ]
                )

            report = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(report["status"], "applied")
            self.assertTrue(target.exists())
            self.assertNotIn("MUST_NOT_APPEAR", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
