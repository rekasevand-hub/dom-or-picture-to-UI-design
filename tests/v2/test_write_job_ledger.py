from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.app.services.job_namespace import (
    JobNamespaceError,
    build_job_namespace,
    parse_job_namespace,
)
from src.app.services.rendering.write_job_ledger import (
    OwnedBatchCoordinator,
    ResumeAction,
    WriteJobLedger,
    WriteJobRecord,
    WriteJobState,
    plan_resume,
)


def _record(
    state: WriteJobState,
    *,
    expected_created_nodes: int = 2,
) -> WriteJobRecord:
    job_id = build_job_namespace("client-1", "job-1")
    return WriteJobRecord(
        job_id=job_id,
        transaction_id=job_id,
        client_id="client-1",
        request_id="request-1",
        fingerprint="a" * 64,
        expected_created_nodes=expected_created_nodes,
        state=state,
    )


class WriteJobLedgerContractTests(unittest.TestCase):
    def test_planned_job_is_safe_to_retry(self) -> None:
        decision = plan_resume(_record(WriteJobState.PLANNED), None)

        self.assertEqual(decision.action, ResumeAction.SAFE_RETRY)
        self.assertTrue(decision.resend_allowed)
        self.assertFalse(decision.requires_human)

    def test_unknown_complete_ownership_reconciles_without_resend(self) -> None:
        decision = plan_resume(
            _record(WriteJobState.UNKNOWN),
            {"status": "reported", "matched": 2},
        )

        self.assertEqual(decision.action, ResumeAction.RECONCILE_NO_RESEND)
        self.assertFalse(decision.resend_allowed)
        self.assertFalse(decision.requires_human)

    def test_unknown_partial_ownership_requires_manual_review(self) -> None:
        decision = plan_resume(
            _record(WriteJobState.UNKNOWN),
            {"status": "reported", "matched": 1},
        )

        self.assertEqual(decision.action, ResumeAction.MANUAL_REVIEW)
        self.assertFalse(decision.resend_allowed)
        self.assertTrue(decision.requires_human)

    def test_unknown_absent_ownership_requires_manual_review(self) -> None:
        decision = plan_resume(
            _record(WriteJobState.UNKNOWN),
            {"status": "reported", "matched": 0},
        )

        self.assertEqual(decision.action, ResumeAction.MANUAL_REVIEW)
        self.assertFalse(decision.resend_allowed)
        self.assertTrue(decision.requires_human)

    def test_rollback_incomplete_requires_manual_review(self) -> None:
        decision = plan_resume(
            _record(WriteJobState.ROLLBACK_INCOMPLETE),
            None,
        )

        self.assertEqual(decision.action, ResumeAction.MANUAL_REVIEW)
        self.assertFalse(decision.resend_allowed)
        self.assertTrue(decision.requires_human)

    def test_terminal_jobs_need_no_resume_action(self) -> None:
        for state in (
            WriteJobState.COMMITTED,
            WriteJobState.REJECTED,
            WriteJobState.ROLLED_BACK,
        ):
            with self.subTest(state=state):
                decision = plan_resume(_record(state), None)
                self.assertEqual(decision.action, ResumeAction.NONE)
                self.assertFalse(decision.resend_allowed)
                self.assertFalse(decision.requires_human)

    def test_record_serializes_without_runtime_objects(self) -> None:
        value = _record(WriteJobState.UNKNOWN).to_dict()

        self.assertEqual(value["state"], "unknown")
        self.assertEqual(
            value["job_id"],
            build_job_namespace("client-1", "job-1"),
        )


class WriteJobLedgerPersistenceTests(unittest.TestCase):
    def test_ledger_rejects_legacy_job_id_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")

            with self.assertRaises(JobNamespaceError):
                ledger.begin_job(
                    job_id="legacy-job",
                    transaction_id="legacy-job",
                    client_id="client-1",
                    request_id="request-1",
                    expected_created_nodes=1,
                    fingerprint="a" * 64,
                )

    def test_ledger_rejects_namespace_for_another_client(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            job_id = build_job_namespace("client-a", "shared-raw")

            with self.assertRaises(JobNamespaceError):
                ledger.begin_job(
                    job_id=job_id,
                    transaction_id=job_id,
                    client_id="client-b",
                    request_id="request-1",
                    expected_created_nodes=1,
                    fingerprint="a" * 64,
                )

    def test_legacy_ledger_is_readable_only_with_explicit_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            legacy = WriteJobLedger(path, allow_legacy_job_ids=True)
            legacy.begin_job(
                job_id="legacy-job",
                transaction_id="legacy-job",
                client_id="client-1",
                request_id="request-1",
                expected_created_nodes=1,
                fingerprint="a" * 64,
            )

            self.assertIsNone(WriteJobLedger(path).load("legacy-job"))
            recovered = WriteJobLedger(
                path,
                allow_legacy_job_ids=True,
            ).load("legacy-job")
            self.assertIsNotNone(recovered)
            self.assertEqual(recovered.namespace_version, "legacy")

    def test_job_states_survive_ledger_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            ledger = WriteJobLedger(path)
            job_id = build_job_namespace("client-1", "job-persist")
            ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="client-1",
                request_id="request-1",
                expected_created_nodes=2,
                fingerprint="b" * 64,
            )
            ledger.mark_inflight(job_id)
            ledger.record_ownership(
                job_id,
                {"status": "reported", "matched": 2},
                "matches-intended",
            )
            ledger.record_bridge_outcome(job_id, "unknown")

            recovered = WriteJobLedger(path).load(job_id)

            self.assertIsNotNone(recovered)
            self.assertEqual(recovered.state, WriteJobState.UNKNOWN)
            self.assertEqual(recovered.ownership_classification, "matches-intended")
            self.assertEqual(recovered.expected_created_nodes, 2)

    def test_duplicate_job_id_conflict_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            job_id = build_job_namespace("client-1", "job-duplicate")
            ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="client-1",
                request_id="request-1",
                expected_created_nodes=1,
                fingerprint="c" * 64,
            )

            replayed = ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="client-1",
                request_id="request-1",
                expected_created_nodes=1,
                fingerprint="c" * 64,
            )
            self.assertEqual(replayed.job_id, job_id)
            with self.assertRaises(ValueError):
                ledger.begin_job(
                    job_id=job_id,
                    transaction_id=job_id,
                    client_id="client-1",
                    request_id="request-1",
                    expected_created_nodes=1,
                    fingerprint="d" * 64,
                )

    def test_malformed_trailing_event_does_not_hide_valid_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            ledger = WriteJobLedger(path)
            job_id = build_job_namespace("client-1", "job-torn")
            ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="client-1",
                request_id="request-1",
                expected_created_nodes=1,
                fingerprint="e" * 64,
            )
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"event":"state","job_id":"job-torn"')
                handle.flush()

            recovered = WriteJobLedger(path).load(job_id)

            self.assertIsNotNone(recovered)
            self.assertEqual(recovered.state, WriteJobState.PLANNED)

    def test_ledger_does_not_store_action_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            ledger = WriteJobLedger(path)
            job_id = build_job_namespace("client-1", "job-safe")
            ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="client-1",
                request_id="request-1",
                expected_created_nodes=1,
                fingerprint="f" * 64,
            )

            events = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

            self.assertNotIn("actions", events[0])
            self.assertNotIn("params", events[0])


class OwnedBatchCoordinatorTests(unittest.TestCase):
    class _Adapter:
        client_id = "adapter-client"

        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []
            self.response: dict[str, Any] | Exception = {
                "status": "committed",
                "transactionId": "job-owned",
                "committed": [
                    {"index": 0, "action": "create_frame", "result": "FRAME:1"},
                ],
            }
            self.status_response: dict[str, Any] = {
                "state": "unknown",
                "transactionId": "job-owned",
            }
            self.ownership_response: dict[str, Any] = {
                "status": "reported",
                "jobId": "job-owned",
                "owner": "figma_auto_agent",
                "matched": 1,
                "nodes": [{"nodeId": "FRAME:1"}],
            }

        def apply_batch(self, actions, *, transaction_id=None):
            self.calls.append(("apply_batch", (actions, transaction_id)))
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

        def transaction_status(self, transaction_id):
            self.calls.append(("transaction_status", transaction_id))
            return self.status_response

        def ownership_report(self, job_id):
            self.calls.append(("ownership_report", job_id))
            return self.ownership_response

        def cleanup_owned_job(self, job_id):
            self.calls.append(("cleanup_owned_job", job_id))
            return {
                "status": "cleaned",
                "jobId": job_id,
                "owner": "figma_auto_agent",
                "matched": 1,
                "removed": 1,
                "failed": [],
            }

    def test_coordinator_persists_planned_intent_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write-jobs.jsonl"
            ledger = WriteJobLedger(path)
            adapter = self._Adapter()
            coordinator = OwnedBatchCoordinator(adapter, ledger)

            record = coordinator.create_owned_batch(
                "job-owned",
                [
                    {
                        "action": "create_frame",
                        "params": {"name": "Owned"},
                    }
                ],
                request_id="request-owned",
            )

            events = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events[0]["state"], "planned")
            self.assertEqual(events[1]["state"], "inflight")
            self.assertEqual(adapter.calls[0][0], "apply_batch")
            self.assertEqual(record.state, WriteJobState.COMMITTED)
            self.assertEqual(record.node_ids, ("FRAME:1",))

    def test_create_uses_client_scoped_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            adapter = self._Adapter()
            coordinator = OwnedBatchCoordinator(adapter, ledger)

            record = coordinator.create_owned_batch(
                "shared-raw",
                [{"action": "create_frame", "params": {"name": "Owned"}}],
            )

            parsed = parse_job_namespace(record.job_id)
            self.assertEqual(parsed.client_id, "adapter-client")
            self.assertEqual(parsed.raw_job_id, "shared-raw")
            self.assertEqual(record.transaction_id, record.job_id)
            self.assertEqual(
                adapter.calls[0],
                ("apply_batch", ([{"action": "create_frame", "params": {"name": "Owned"}}], record.job_id)),
            )

    def test_same_raw_job_id_from_two_clients_creates_distinct_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            first_adapter = self._Adapter()
            second_adapter = self._Adapter()
            first_adapter.client_id = "client-a"
            second_adapter.client_id = "client-b"

            first = OwnedBatchCoordinator(first_adapter, ledger).create_owned_batch(
                "shared-raw",
                [{"action": "create_frame", "params": {"name": "First"}}],
            )
            second = OwnedBatchCoordinator(second_adapter, ledger).create_owned_batch(
                "shared-raw",
                [{"action": "create_frame", "params": {"name": "Second"}}],
            )

            self.assertNotEqual(first.job_id, second.job_id)
            self.assertEqual(
                first_adapter.calls[0][1][1],
                first.job_id,
            )
            self.assertEqual(
                second_adapter.calls[0][1][1],
                second.job_id,
            )
            self.assertIsNotNone(ledger.load(first.job_id))
            self.assertIsNotNone(ledger.load(second.job_id))

    def test_resume_rejects_bare_job_id_before_bridge_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            adapter = self._Adapter()
            coordinator = OwnedBatchCoordinator(adapter, ledger)

            with self.assertRaises(JobNamespaceError):
                coordinator.resume_job("legacy-job")
            self.assertEqual(adapter.calls, [])

    def test_coordinator_records_exception_as_unknown_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            adapter = self._Adapter()
            adapter.response = TimeoutError("injected timeout")
            coordinator = OwnedBatchCoordinator(adapter, ledger)

            record = coordinator.create_owned_batch(
                "job-owned",
                [
                    {
                        "action": "create_frame",
                        "params": {"name": "Owned"},
                    }
                ],
            )

            self.assertEqual(record.state, WriteJobState.UNKNOWN)
            self.assertEqual(
                sum(1 for call in adapter.calls if call[0] == "apply_batch"),
                1,
            )

    def test_duplicate_owned_batch_does_not_dispatch_second_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            adapter = self._Adapter()
            coordinator = OwnedBatchCoordinator(adapter, ledger)
            actions = [{"action": "create_frame", "params": {"name": "Owned"}}]

            first = coordinator.create_owned_batch(
                "same-job",
                actions,
                request_id="request-same",
            )
            second = coordinator.create_owned_batch(
                "same-job",
                actions,
                request_id="request-same",
            )

            self.assertEqual(first.job_id, second.job_id)
            self.assertEqual(second.state, WriteJobState.COMMITTED)
            self.assertEqual(
                sum(1 for call in adapter.calls if call[0] == "apply_batch"),
                1,
            )

    def test_ledger_failure_prevents_adapter_dispatch(self) -> None:
        class FailingLedger:
            def begin_job(self, **kwargs):
                del kwargs
                raise OSError("ledger unavailable")

            def mark_inflight(self, job_id):
                del job_id
                raise AssertionError("must not mark inflight")

        adapter = self._Adapter()
        coordinator = OwnedBatchCoordinator(adapter, FailingLedger())

        with self.assertRaises(OSError):
            coordinator.create_owned_batch(
                "job-owned",
                [{"action": "create_frame", "params": {}}],
            )
        self.assertEqual(adapter.calls, [])

    def test_resume_unknown_complete_ownership_does_not_resend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            adapter = self._Adapter()
            job_id = build_job_namespace("adapter-client", "job-owned")
            adapter.status_response = {
                "transaction": {
                    "state": "unknown",
                    "transactionId": job_id,
                    "ownershipReadback": {
                        "status": "reported",
                        "jobId": job_id,
                        "owner": "figma_auto_agent",
                        "matched": 1,
                        "nodes": [{"nodeId": "FRAME:1"}],
                    },
                    "ownershipReconciliation": {
                        "classification": "matches-intended",
                    },
                }
            }
            coordinator = OwnedBatchCoordinator(adapter, ledger)
            ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="adapter-client",
                request_id="request",
                expected_created_nodes=1,
                fingerprint="a" * 64,
            )
            ledger.mark_inflight(job_id)
            ledger.record_bridge_outcome(job_id, "unknown")
            adapter.calls.clear()

            decision = coordinator.resume_job(job_id)

            self.assertEqual(decision.action, ResumeAction.RECONCILE_NO_RESEND)
            self.assertFalse(decision.resend_allowed)
            self.assertEqual(
                sum(1 for call in adapter.calls if call[0] == "apply_batch"),
                0,
            )
            self.assertEqual(
                [call for call in adapter.calls if call[0] == "ownership_report"],
                [],
            )
            record = ledger.load(job_id)
            self.assertEqual(record.resume_action, "reconcile-no-resend")

    def test_resume_partial_ownership_requires_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            adapter = self._Adapter()
            job_id = build_job_namespace("adapter-client", "job-owned")
            adapter.ownership_response = {
                "status": "reported",
                "jobId": job_id,
                "owner": "figma_auto_agent",
                "matched": 0,
                "nodes": [],
            }
            coordinator = OwnedBatchCoordinator(adapter, ledger)
            ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="adapter-client",
                request_id="request",
                expected_created_nodes=1,
                fingerprint="a" * 64,
            )
            ledger.mark_inflight(job_id)
            ledger.record_bridge_outcome(job_id, "unknown")

            decision = coordinator.resume_job(job_id)

            self.assertEqual(decision.action, ResumeAction.MANUAL_REVIEW)
            self.assertTrue(decision.requires_human)
            record = ledger.load(job_id)
            self.assertEqual(record.state, WriteJobState.RESUME_REQUIRED)

    def test_resume_committed_job_needs_no_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            adapter = self._Adapter()
            job_id = build_job_namespace("adapter-client", "job-owned")
            adapter.status_response = {
                "state": "committed",
                "transactionId": job_id,
            }
            coordinator = OwnedBatchCoordinator(adapter, ledger)
            ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="adapter-client",
                request_id="request",
                expected_created_nodes=1,
                fingerprint="a" * 64,
            )
            ledger.mark_inflight(job_id)

            decision = coordinator.resume_job(job_id)

            self.assertEqual(decision.action, ResumeAction.NONE)
            self.assertFalse(decision.resend_allowed)

    def test_cleanup_is_scoped_to_exact_job_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            adapter = self._Adapter()
            coordinator = OwnedBatchCoordinator(adapter, ledger)
            job_id = build_job_namespace("adapter-client", "job-owned")
            ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="adapter-client",
                request_id="request",
                expected_created_nodes=1,
                fingerprint="a" * 64,
            )
            ledger.mark_inflight(job_id)
            ledger.record_bridge_outcome(
                job_id,
                "committed",
                {"status": "committed", "transactionId": job_id},
            )

            plan = coordinator.plan_cleanup(job_id)
            self.assertTrue(plan["allowed"])
            result = coordinator.cleanup_job(job_id)

            self.assertEqual(result.cleanup_status, "cleaned")
            self.assertEqual(result.cleanup_removed, 1)
            self.assertEqual(
                adapter.calls,
                [("cleanup_owned_job", job_id)],
            )

    def test_failed_cleanup_requires_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            adapter = self._Adapter()
            adapter.cleanup_owned_job = lambda job_id: {
                "status": "partial",
                "jobId": job_id,
                "matched": 1,
                "removed": 0,
                "failed": [{"nodeId": "FRAME:1", "error": "locked"}],
            }
            coordinator = OwnedBatchCoordinator(adapter, ledger)
            job_id = build_job_namespace("adapter-client", "job-owned")
            ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="adapter-client",
                request_id="request",
                expected_created_nodes=1,
                fingerprint="a" * 64,
            )
            ledger.mark_inflight(job_id)
            ledger.record_bridge_outcome(
                job_id,
                "committed",
                {"status": "committed", "transactionId": job_id},
            )

            result = coordinator.cleanup_job(job_id)

            self.assertEqual(result.state, WriteJobState.RESUME_REQUIRED)
            self.assertEqual(result.cleanup_failed_count, 1)

    def test_cleanup_of_unknown_job_blocks_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = WriteJobLedger(Path(temp_dir) / "write-jobs.jsonl")
            adapter = self._Adapter()
            coordinator = OwnedBatchCoordinator(adapter, ledger)
            job_id = build_job_namespace("adapter-client", "job-unknown")
            ledger.begin_job(
                job_id=job_id,
                transaction_id=job_id,
                client_id="adapter-client",
                request_id="request",
                expected_created_nodes=1,
                fingerprint="a" * 64,
            )
            ledger.mark_inflight(job_id)
            ledger.record_bridge_outcome(job_id, "unknown")

            plan = coordinator.plan_cleanup(job_id)

            self.assertFalse(plan["allowed"])
            self.assertEqual(plan["reason"], "cleanup-requires-manual-review")
            with self.assertRaises(ValueError):
                coordinator.cleanup_job(job_id)
            self.assertEqual(adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
