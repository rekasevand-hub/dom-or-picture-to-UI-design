from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.p5_collaboration_race_probe import run_probe
from src.app.services.rendering.figma_adapter import reconciliation_policy


class CollaborationReconciliationTests(unittest.TestCase):
    def test_slotted_transaction_objects_are_supported(self) -> None:
        class SlottedTransaction:
            __slots__ = ("transactionId", "state")

            def __init__(self) -> None:
                self.transactionId = "tx-slotted"
                self.state = "unknown"

        decision = reconciliation_policy(
            SlottedTransaction(),
            {"status": "matches", "owned_node_ids": ["1:9"]},
            {"status": "unavailable", "actor": "unknown", "revision": "unknown"},
        )

        self.assertEqual(decision.transaction_state, "unknown")
        self.assertEqual(decision.recommendation, "operator-confirm-no-resend")

    def test_matching_state_does_not_infer_actor_or_revision(self) -> None:
        decision = reconciliation_policy(
            {
                "transactionId": "tx-1",
                "state": "unknown",
                "action": "apply_edit_batch",
            },
            {
                "status": "matches",
                "owned_node_ids": ["1:2"],
                "current_state": {"characters": "Same value"},
            },
            {
                "status": "unavailable",
                "actor": "unknown",
                "revision": "unknown",
            },
        )

        self.assertEqual(decision.action, "manual-review")
        self.assertFalse(decision.resend_allowed)
        self.assertEqual(decision.actor, "unknown")
        self.assertEqual(decision.revision, "unknown")
        self.assertEqual(decision.transaction_state, "unknown")

    def test_conflicting_state_and_deletion_remain_manual(self) -> None:
        conflict = reconciliation_policy(
            {"transactionId": "tx-2", "state": "unknown"},
            {"status": "mismatch", "current_state": {"characters": "Other"}},
            {"status": "unavailable", "actor": "unknown", "revision": "unknown"},
        )
        deleted = reconciliation_policy(
            {"transactionId": "tx-3", "state": "unknown"},
            {"status": "node-deleted", "owned_node_ids": ["1:3"]},
            {"status": "unavailable", "actor": "unknown", "revision": "unknown"},
        )

        self.assertEqual(conflict.recommendation, "operator-resolve-conflict")
        self.assertEqual(deleted.recommendation, "rollback-incomplete-manual-review")
        self.assertFalse(conflict.resend_allowed)
        self.assertFalse(deleted.resend_allowed)

    def test_probe_keeps_collaboration_claims_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            result = run_probe(Path(raw_dir))

            self.assertEqual(result["status"], "completed-for-current-scope")
            self.assertTrue(result["real_environment_required"])
            self.assertTrue(all(item["passed"] for item in result["checks"]))
            self.assertTrue((Path(raw_dir) / "result.json").is_file())


if __name__ == "__main__":
    unittest.main()
