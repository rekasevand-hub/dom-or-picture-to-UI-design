from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.app.services.bridge_config import load_bridge_config
from src.app.services.job_namespace import build_job_namespace
from src.app.services.rendering.write_job_ledger import (
    LegacyLedgerMigrationError,
    LedgerIntegrityError,
    WriteJobLedger,
    WriteJobState,
    migrate_legacy_write_job_ledger,
)


def _event(
    job_id: str,
    *,
    client_id: str,
    state: str,
    updated_at: float,
    fingerprint: str = "a" * 64,
    **extra: object,
) -> dict[str, object]:
    return {
        "version": 2,
        "event": "state",
        "job_id": job_id,
        "transaction_id": job_id,
        "client_id": client_id,
        "request_id": f"request-{state}",
        "fingerprint": fingerprint,
        "expected_created_nodes": 1,
        "state": state,
        "node_ids": [],
        "bridge_state": "",
        "ownership_classification": "",
        "resume_action": "",
        "resume_requires_human": False,
        "cleanup_status": "",
        "cleanup_matched": 0,
        "cleanup_removed": 0,
        "cleanup_failed_count": 0,
        "reason": "",
        "updated_at": updated_at,
        "raw_job_id": "",
        "namespace_version": "",
        **extra,
    }


def _write_events(path: Path, events: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for event in events
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _line_events(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class LedgerCompactionTests(unittest.TestCase):
    def test_old_nonterminal_events_are_never_automatically_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            old = 1_000.0
            states = (
                "planned",
                "inflight",
                "unknown",
                "resume-required",
                "rollback-incomplete",
            )
            events: list[dict[str, object]] = []
            for index, state in enumerate(states):
                job_id = build_job_namespace("client-a", f"job-{index}")
                events.extend(
                    [
                        _event(
                            job_id,
                            client_id="client-a",
                            state="planned",
                            updated_at=old,
                        ),
                        _event(
                            job_id,
                            client_id="client-a",
                            state=state,
                            updated_at=old + 1,
                        ),
                    ]
                )
            _write_events(path, events)
            ledger = WriteJobLedger(
                path,
                max_events=3,
                terminal_retention_days=1,
                compact_min_events=2,
            )

            result = ledger.compact(now=100_000.0, force=True)

            self.assertEqual(result.status, "unchanged")
            self.assertEqual(len(_line_events(path)), len(events))
            for index, state in enumerate(states):
                job_id = build_job_namespace("client-a", f"job-{index}")
                self.assertEqual(ledger.load(job_id).state.value, state)

    def test_old_terminal_history_collapses_to_latest_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            job_id = build_job_namespace("client-a", "terminal")
            events = [
                _event(
                    job_id,
                    client_id="client-a",
                    state="planned",
                    updated_at=1_000.0,
                ),
                _event(
                    job_id,
                    client_id="client-a",
                    state="inflight",
                    updated_at=1_001.0,
                ),
                _event(
                    job_id,
                    client_id="client-a",
                    state="committed",
                    updated_at=1_002.0,
                    cleanup_status="cleaned",
                    cleanup_matched=2,
                    cleanup_removed=2,
                    cleanup_failed_count=0,
                    resume_action="none",
                ),
            ]
            _write_events(path, events)
            ledger = WriteJobLedger(
                path,
                max_events=2,
                terminal_retention_days=1,
                compact_min_events=2,
            )

            result = ledger.compact(now=100_000.0, force=True)

            self.assertEqual(result.status, "compacted")
            self.assertEqual(result.compacted_jobs, 1)
            compacted = _line_events(path)
            self.assertEqual(len(compacted), 1)
            self.assertTrue(compacted[0]["compacted"])
            self.assertEqual(compacted[0]["history_events"], 3)
            record = ledger.load(job_id)
            self.assertEqual(record.state, WriteJobState.COMMITTED)
            self.assertEqual(record.cleanup_status, "cleaned")
            self.assertEqual(record.cleanup_removed, 2)
            self.assertEqual(record.fingerprint, "a" * 64)

            replay = ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="client-a",
                request_id="request-committed",
                expected_created_nodes=1,
                fingerprint="a" * 64,
            )
            self.assertEqual(replay.cleanup_removed, 2)
            with self.assertRaises(ValueError):
                ledger.begin_job(
                    job_id=job_id,
                    transaction_id=job_id,
                    client_id="client-a",
                    request_id="request-committed",
                    expected_created_nodes=1,
                    fingerprint="b" * 64,
                )

    def test_terminal_history_inside_retention_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            job_id = build_job_namespace("client-a", "recent")
            events = [
                _event(
                    job_id,
                    client_id="client-a",
                    state="planned",
                    updated_at=99_900.0,
                ),
                _event(
                    job_id,
                    client_id="client-a",
                    state="committed",
                    updated_at=99_901.0,
                ),
            ]
            _write_events(path, events)
            ledger = WriteJobLedger(
                path,
                terminal_retention_days=7,
                compact_min_events=2,
            )

            result = ledger.compact(now=100_000.0, force=True)

            self.assertEqual(result.status, "unchanged")
            self.assertEqual(len(_line_events(path)), 2)

    def test_automatic_compaction_preserves_latest_terminal_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            ledger = WriteJobLedger(
                path,
                max_events=2,
                terminal_retention_days=0,
                compact_min_events=2,
            )
            job_id = build_job_namespace("client-a", "automatic")
            ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="client-a",
                request_id="request-automatic",
                expected_created_nodes=1,
                fingerprint="a" * 64,
            )
            ledger.mark_inflight(job_id)

            record = ledger.record_bridge_outcome(job_id, "committed")

            self.assertEqual(record.state, WriteJobState.COMMITTED)
            compacted = _line_events(path)
            self.assertEqual(len(compacted), 1)
            self.assertTrue(compacted[0]["compacted"])
            self.assertEqual(ledger.load(job_id).state, WriteJobState.COMMITTED)

    def test_terminal_compaction_preserves_resume_decision_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            job_id = build_job_namespace("client-a", "resume-terminal")
            _write_events(
                path,
                [
                    _event(
                        job_id,
                        client_id="client-a",
                        state="planned",
                        updated_at=1.0,
                    ),
                    _event(
                        job_id,
                        client_id="client-a",
                        state="committed",
                        updated_at=2.0,
                        resume_action="none",
                        resume_requires_human=False,
                        reason="terminal resume decision",
                    ),
                ],
            )
            ledger = WriteJobLedger(path, compact_min_events=2)

            ledger.compact(now=100_000.0, force=True)

            record = ledger.load(job_id)
            self.assertEqual(record.resume_action, "none")
            self.assertFalse(record.resume_requires_human)
            self.assertEqual(record.reason, "terminal resume decision")

    def test_compaction_minimum_is_enforced_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            job_id = build_job_namespace("client-a", "small")
            _write_events(
                path,
                [
                    _event(
                        job_id,
                        client_id="client-a",
                        state="committed",
                        updated_at=1.0,
                    )
                ],
            )
            ledger = WriteJobLedger(path, compact_min_events=10)

            result = ledger.compact(now=100_000.0)

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.reason, "below-compact-minimum")

    def test_replace_failure_keeps_original_ledger_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            job_id = build_job_namespace("client-a", "atomic")
            _write_events(
                path,
                [
                    _event(
                        job_id,
                        client_id="client-a",
                        state="planned",
                        updated_at=1.0,
                    ),
                    _event(
                        job_id,
                        client_id="client-a",
                        state="committed",
                        updated_at=2.0,
                    ),
                ],
            )
            original = path.read_bytes()
            ledger = WriteJobLedger(
                path,
                terminal_retention_days=0,
                compact_min_events=2,
            )

            with patch(
                "src.app.services.rendering.write_job_ledger.os.replace",
                side_effect=OSError("injected replace failure"),
            ):
                with self.assertRaises(OSError):
                    ledger.compact(now=100_000.0, force=True)

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_interior_corruption_fails_closed_without_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            job_id = build_job_namespace("client-a", "corrupt")
            planned = json.dumps(
                _event(
                    job_id,
                    client_id="client-a",
                    state="planned",
                    updated_at=1.0,
                ),
                sort_keys=True,
                separators=(",", ":"),
            )
            committed = json.dumps(
                _event(
                    job_id,
                    client_id="client-a",
                    state="committed",
                    updated_at=2.0,
                ),
                sort_keys=True,
                separators=(",", ":"),
            )
            path.write_text(
                f"{planned}\n{{broken}}\n{committed}\n",
                encoding="utf-8",
            )
            original = path.read_bytes()
            ledger = WriteJobLedger(path, compact_min_events=2)

            with self.assertRaises(LedgerIntegrityError):
                ledger.compact(now=100_000.0, force=True)

            self.assertEqual(path.read_bytes(), original)

    def test_trailing_torn_event_is_ignored_during_compaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            job_id = build_job_namespace("client-a", "torn")
            planned = json.dumps(
                _event(
                    job_id,
                    client_id="client-a",
                    state="planned",
                    updated_at=1.0,
                ),
                sort_keys=True,
                separators=(",", ":"),
            )
            path.write_text(f'{planned}\n{{"event":"state"', encoding="utf-8")
            ledger = WriteJobLedger(path, compact_min_events=2)

            result = ledger.compact(now=100_000.0, force=True)

            self.assertEqual(result.status, "compacted")
            self.assertEqual(ledger.load(job_id).state, WriteJobState.PLANNED)
            self.assertEqual(len(_line_events(path)), 1)


class LegacyLedgerMigrationTests(unittest.TestCase):
    def _legacy_events(self) -> list[dict[str, object]]:
        old = 1_000.0
        return [
            _event(
                "shared-raw",
                client_id="legacy-a",
                state="committed",
                updated_at=old,
                fingerprint="a" * 64,
                action="create_text",
                text="MUST_NOT_LEAK",
                secret="MUST_NOT_LEAK_EITHER",
            ),
            _event(
                "shared-raw",
                client_id="legacy-b",
                state="unknown",
                updated_at=old + 1,
                fingerprint="b" * 64,
            ),
        ]

    def test_dry_run_hashes_candidate_without_writing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "legacy.jsonl"
            target = root / "migrated.jsonl"
            _write_events(source, self._legacy_events())
            original = source.read_bytes()

            result = migrate_legacy_write_job_ledger(
                source,
                target,
                client_mapping={
                    "legacy-a": "client-a",
                    "legacy-b": "client-b",
                },
                dry_run=True,
            )
            report = result.to_dict()

            self.assertEqual(result.status, "dry-run")
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(
                result.source_sha256,
                hashlib.sha256(original).hexdigest(),
            )
            self.assertEqual(result.target_sha256, result.candidate_sha256)
            serialized = json.dumps(report, sort_keys=True)
            self.assertNotIn("shared-raw", serialized)
            self.assertNotIn("MUST_NOT_LEAK", serialized)
            self.assertNotIn("legacy-a", serialized)
            self.assertEqual(
                set(report),
                {
                    "status",
                    "dry_run",
                    "fields",
                    "counts",
                    "source_sha256",
                    "candidate_sha256",
                    "target_sha256",
                    "report_sha256",
                },
            )
            self.assertIn("fingerprint", report["fields"])

    def test_apply_migrates_same_raw_id_for_two_clients(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "legacy.jsonl"
            target = root / "migrated.jsonl"
            _write_events(source, self._legacy_events())

            result = migrate_legacy_write_job_ledger(
                source,
                target,
                client_mapping={
                    "legacy-a": "client-a",
                    "legacy-b": "client-b",
                },
                dry_run=False,
            )

            self.assertEqual(result.status, "applied")
            ledger = WriteJobLedger(target)
            first_id = build_job_namespace("client-a", "shared-raw")
            second_id = build_job_namespace("client-b", "shared-raw")
            self.assertEqual(ledger.load(first_id).state, WriteJobState.COMMITTED)
            self.assertEqual(ledger.load(second_id).state, WriteJobState.UNKNOWN)
            migrated = _line_events(target)
            self.assertEqual(len(migrated), 2)
            for event in migrated:
                self.assertTrue(str(event["job_id"]).startswith("r5job:v1:"))
                self.assertEqual(event["raw_job_id"], "shared-raw")
                self.assertEqual(event["namespace_version"], "v1")
                self.assertNotIn("action", event)
                self.assertNotIn("text", event)
                self.assertNotIn("secret", event)

    def test_mapping_collision_fails_closed_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "legacy.jsonl"
            target = root / "migrated.jsonl"
            _write_events(source, self._legacy_events())
            original = source.read_bytes()

            with self.assertRaises(LegacyLedgerMigrationError):
                migrate_legacy_write_job_ledger(
                    source,
                    target,
                    client_mapping={
                        "legacy-a": "same-client",
                        "legacy-b": "same-client",
                    },
                    dry_run=False,
                )

            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(target.exists())

    def test_same_client_conflicting_fingerprint_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "legacy.jsonl"
            target = root / "migrated.jsonl"
            events = [
                _event(
                    "job-conflict",
                    client_id="legacy-a",
                    state="planned",
                    updated_at=1.0,
                    fingerprint="a" * 64,
                ),
                _event(
                    "job-conflict",
                    client_id="legacy-a",
                    state="committed",
                    updated_at=2.0,
                    fingerprint="b" * 64,
                ),
            ]
            _write_events(source, events)
            original = source.read_bytes()

            with self.assertRaises(LegacyLedgerMigrationError):
                migrate_legacy_write_job_ledger(
                    source,
                    target,
                    client_mapping={"legacy-a": "client-a"},
                    dry_run=True,
                )

            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(target.exists())

    def test_missing_explicit_client_mapping_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "legacy.jsonl"
            target = root / "migrated.jsonl"
            _write_events(source, self._legacy_events())

            with self.assertRaises(LegacyLedgerMigrationError):
                migrate_legacy_write_job_ledger(
                    source,
                    target,
                    client_mapping={"legacy-a": "client-a"},
                    dry_run=True,
                )

            self.assertFalse(target.exists())

    def test_existing_target_requires_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "legacy.jsonl"
            target = root / "migrated.jsonl"
            _write_events(source, self._legacy_events())
            target.write_text("existing-target\n", encoding="utf-8")
            existing = target.read_bytes()
            source_bytes = source.read_bytes()

            with self.assertRaises(LegacyLedgerMigrationError):
                migrate_legacy_write_job_ledger(
                    source,
                    target,
                    client_mapping={
                        "legacy-a": "client-a",
                        "legacy-b": "client-b",
                    },
                    dry_run=False,
                )

            self.assertEqual(target.read_bytes(), existing)
            self.assertEqual(source.read_bytes(), source_bytes)


class LedgerConfigIntegrationTests(unittest.TestCase):
    def test_write_job_ledger_can_be_built_from_unified_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "figma_bridge.config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "figma-bridge-config/1.0",
                        "allow_env_overrides": False,
                        "ledger": {
                            "path": "state/write-jobs.jsonl",
                            "max_events": 64,
                            "terminal_retention_days": 7,
                            "compact_min_events": 8,
                            "allow_legacy_read": True,
                        },
                        "security": {
                            "require_secret_references": False,
                            "require_secure_file_permissions": False,
                        },
                        "server": {
                            "host": "127.0.0.1",
                            "port": 8765,
                            "timeout": 30,
                            "idempotency_ttl": 60,
                            "journal_path": "bridge.jsonl",
                            "max_inflight": 8,
                            "max_message_bytes": 4096,
                            "max_params_depth": 6,
                            "max_cache_entries": 32,
                            "max_journal_events": 64,
                            "exclusive_journal_lock": False,
                            "auth_token": "",
                            "plugin_token": "",
                            "plugin_token_recheck_seconds": 0.5,
                            "client_tokens": {},
                            "allow_legacy_job_ids": False,
                            "client_write_defaults": {
                                "max_inflight": 4,
                                "burst": 4,
                                "min_interval_ms": 0,
                            },
                            "client_write_limits": {},
                            "write_pacing": {
                                "min_interval_ms": 0,
                                "queue_timeout_seconds": 1,
                                "max_queue": 4,
                            },
                            "tls": {
                                "enabled": False,
                                "certfile": "",
                                "keyfile": "",
                                "ca_file": "",
                                "require_client_cert": False,
                            },
                        },
                        "client": {
                            "url": "ws://127.0.0.1:8765",
                            "timeout": 5,
                            "client_id": "",
                            "client_token": "",
                            "auth_token": "",
                            "allow_legacy_job_ids": False,
                            "tls": {
                                "enabled": False,
                                "verify": True,
                                "ca_file": "",
                                "certfile": "",
                                "keyfile": "",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = load_bridge_config(path, environ={})

            ledger = WriteJobLedger.from_bridge_config(config)

            self.assertEqual(ledger.path, config.ledger.path)
            self.assertEqual(ledger.max_events, 64)
            self.assertEqual(ledger.terminal_retention_days, 7)
            self.assertEqual(ledger.compact_min_events, 8)
            self.assertTrue(ledger.allow_legacy_job_ids)


if __name__ == "__main__":
    unittest.main()
