from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.app.services.contracts import (
    RetentionPolicy,
    Tombstone,
    build_audit_bundle,
)
from src.app.services.persistence.local_pilot import LocalPilotStore
from src.app.services.persistence.store import (
    IdempotencyConflict,
    PersistenceCommitError,
)
from tests.v2._delivery_fixture import delivery_sidecar


def _bundle(trace_id: str = "trace-local-1") -> dict:
    runtime = replace(
        delivery_sidecar().runtime_ir,
        tombstones=(
            Tombstone(
                tombstone_id="tomb-local",
                object_key="legacy",
                scope="field",
                authority="business",
                authority_version=1,
                effective_at="2026-10-22T00:00:00+00:00",
            ),
        ),
        retention=RetentionPolicy(
            replay_evidence_days=1,
            audit_metadata_days=1,
            evidence_expires_at="2026-10-23T00:00:00+00:00",
            audit_metadata_expires_at="2026-10-23T00:00:00+00:00",
        ),
    )
    return {
        "trace_id": trace_id,
        "runtime_ir": runtime,
        "audit_bundle": build_audit_bundle(runtime),
    }


class LocalPilotStoreTests(unittest.TestCase):
    def test_put_get_and_duplicate_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = LocalPilotStore(
                Path(raw_dir),
                clock=lambda: 1_000_000.0,
            )
            first = store.put(_bundle(), "idem-1")
            duplicate = store.put(_bundle(), "idem-1")
            loaded = store.get("trace-local-1")

            self.assertEqual(first.content_hash, duplicate.content_hash)
            self.assertEqual(loaded.trace_id, "trace-local-1")
            self.assertEqual(loaded.idempotency_key, "idem-1")
            self.assertFalse(loaded.production_eligible)
            with self.assertRaises(IdempotencyConflict):
                store.put(_bundle("trace-local-2"), "idem-1")

    def test_partial_write_leaves_no_record(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)

            def fail(stage: str) -> None:
                if stage == "before-commit":
                    raise OSError("simulated partial write")

            store = LocalPilotStore(root, before_commit=fail)

            with self.assertRaises(PersistenceCommitError):
                store.put(_bundle(), "idem-partial")

            self.assertIsNone(store.get("trace-local-1"))
            self.assertFalse(
                list((root / "deliveries").glob("trace-local-1"))
                if (root / "deliveries").exists()
                else []
            )

    def test_expired_records_are_listed_and_purged_with_tombstone_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            store = LocalPilotStore(root, clock=lambda: 1_000_000.0)
            store.put(_bundle(), "idem-expired")

            expired = store.list_expired(now="2026-10-24T00:00:00+00:00")
            result = store.purge(expired)

            self.assertEqual(len(expired), 1)
            self.assertEqual(result.purged_count, 1)
            self.assertIsNone(store.get("trace-local-1"))
            archive = root / "tombstones" / "trace-local-1.json"
            self.assertTrue(archive.is_file())
            archived = json.loads(archive.read_text(encoding="utf-8"))
            self.assertEqual(archived["tombstones"][0]["tombstone_id"], "tomb-local")

    def test_unexpired_record_is_not_listed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            store = LocalPilotStore(
                Path(raw_dir),
                clock=lambda: 1_000_000.0,
            )
            store.put(_bundle(), "idem-live")

            self.assertEqual(
                store.list_expired(now="2026-10-22T12:00:00+00:00"),
                [],
            )


if __name__ == "__main__":
    unittest.main()
