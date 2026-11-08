from __future__ import annotations

import unittest

from scripts.figma_bridge_soak_probe import (
    _cleanup_owned_soak_nodes,
    _setup_owned_soak_nodes,
    apply_journal_bound,
    build_real_soak_report,
    summarize_latencies,
)
from scripts.bridge_write_backpressure_soak import build_write_pacing_report
from src.app.services.rendering.figma_adapter import FigmaBridgeError


class FigmaBridgeSoakProbeTests(unittest.TestCase):
    def test_latency_summary_reports_stable_percentiles(self) -> None:
        summary = summarize_latencies([40, 10, 30, 20])

        self.assertEqual(summary["count"], 4)
        self.assertEqual(summary["min_ms"], 10.0)
        self.assertEqual(summary["max_ms"], 40.0)
        self.assertEqual(summary["p50_ms"], 20.0)
        self.assertEqual(summary["p95_ms"], 40.0)

    def test_real_soak_report_fails_on_request_errors(self) -> None:
        report = build_real_soak_report(
            requested=100,
            succeeded=99,
            failed=1,
            duration_seconds=10.0,
            concurrency=4,
            latencies_ms=[10, 20, 30],
            errors=["timeout"],
        )

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["requests_per_second"], 10.0)
        self.assertTrue(report["failed_checks"])

    def test_real_soak_report_passes_clean_readback_run(self) -> None:
        report = build_real_soak_report(
            requested=100,
            succeeded=100,
            failed=0,
            duration_seconds=10.0,
            concurrency=4,
            latencies_ms=[10, 20, 30],
            errors=[],
        )

        self.assertEqual(report["status"], "fail")
        self.assertIn("owned_setup_verified", report["failed_checks"])
        self.assertIn("exact_cleanup_verified", report["failed_checks"])

    def test_real_soak_report_passes_only_after_independent_cleanup_verification(
        self,
    ) -> None:
        report = build_real_soak_report(
            requested=100,
            succeeded=100,
            failed=0,
            duration_seconds=10.0,
            concurrency=4,
            latencies_ms=[10, 20, 30],
            errors=[],
            setup_cleanup={
                "setup_verified": True,
                "cleanup_verified": True,
            },
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["failed_checks"], [])

    def test_real_soak_report_tracks_write_mode(self) -> None:
        report = build_real_soak_report(
            requested=20,
            succeeded=20,
            failed=0,
            duration_seconds=5.0,
            concurrency=2,
            latencies_ms=[10, 20],
            errors=[],
            mode="write",
            setup_cleanup={
                "setup_verified": True,
                "cleanup_verified": True,
            },
        )

        self.assertEqual(report["mode"], "write")
        self.assertEqual(report["status"], "pass")

    def test_owned_soak_setup_and_cleanup_verify_exact_node_absence(self) -> None:
        class FakeAdmin:
            client_id = "p4-real-soak-admin"

            def __init__(self):
                self.jobs = {}
                self.cleaned = set()
                self.next_id = 1
                self.connect_count = 0

            def connect(self):
                self.connect_count += 1

            def disconnect(self):
                return None

            def apply_batch(self, actions, *, transaction_id=None):
                node_id = f"node-{self.next_id}"
                self.next_id += 1
                self.jobs[node_id] = transaction_id
                return {
                    "status": "committed",
                    "transactionId": transaction_id,
                    "committed": [
                        {
                            "index": 0,
                            "action": actions[0]["action"],
                            "result": node_id,
                        }
                    ],
                }

            def ownership_report(self, job_id):
                nodes = [
                    {"nodeId": node_id, "jobId": owner}
                    for node_id, owner in self.jobs.items()
                    if owner == job_id and node_id not in self.cleaned
                ]
                return {"status": "reported", "matched": len(nodes), "nodes": nodes}

            def cleanup_owned_job(self, job_id):
                if self.connect_count == 1:
                    raise ConnectionAbortedError(
                        "stale admin connection during cleanup"
                    )
                matched = [
                    node_id
                    for node_id, owner in self.jobs.items()
                    if owner == job_id and node_id not in self.cleaned
                ]
                self.cleaned.update(matched)
                return {
                    "status": "cleaned",
                    "jobId": job_id,
                    "matched": len(matched),
                    "removed": len(matched),
                    "failed": [],
                }

            def _send(self, action, params, *, request_id=None):
                self.assert_action = action
                self.page_tree_depth = params.get("depth")
                return {
                    "id": "0:1",
                    "name": "P5 Pilot",
                    "type": "PAGE",
                    "children": [
                        {"id": "59:2", "name": "P5-PILOT-ROOT", "type": "FRAME"}
                    ],
                }

        admin = FakeAdmin()
        setup = _setup_owned_soak_nodes(admin, "cleanup-test", mode="write")

        cleanup = _cleanup_owned_soak_nodes(admin, setup)

        self.assertTrue(setup["verified"])
        self.assertTrue(cleanup["verified"])
        self.assertEqual(cleanup["ownership_reports"][0]["matched"], 0)
        self.assertEqual(admin.assert_action, "get_node_tree")
        self.assertEqual(admin.page_tree_depth, 1)
        self.assertGreaterEqual(admin.connect_count, 2)

    def test_owned_soak_cleanup_fails_when_ownership_remains(self) -> None:
        class FakeAdmin:
            client_id = "p4-real-soak-admin"

            def connect(self):
                return None

            def disconnect(self):
                return None

            def apply_batch(self, actions, *, transaction_id=None):
                return {
                    "status": "committed",
                    "transactionId": transaction_id,
                    "committed": [
                        {
                            "index": 0,
                            "action": actions[0]["action"],
                            "result": "59:9"
                            if actions[0]["action"] == "create_frame"
                            else "59:10",
                        }
                    ],
                }

            def ownership_report(self, job_id):
                return {"status": "reported", "matched": 1, "nodes": []}

            def cleanup_owned_job(self, job_id):
                return {
                    "status": "partial",
                    "jobId": job_id,
                    "matched": 1,
                    "removed": 0,
                    "failed": [{"nodeId": "59:9", "error": "locked"}],
                }

            def _send(self, action, params, *, request_id=None):
                return {
                    "id": "0:1",
                    "name": "P5 Pilot",
                    "type": "PAGE",
                    "children": [],
                }

        admin = FakeAdmin()
        setup = _setup_owned_soak_nodes(admin, "cleanup-failure", mode="write")

        cleanup = _cleanup_owned_soak_nodes(admin, setup)

        self.assertFalse(cleanup["verified"])
        self.assertTrue(cleanup["failed_checks"])

    def test_cleanup_retries_page_readback_after_plugin_reconnect(self) -> None:
        class FakeAdmin:
            client_id = "p4-real-soak-admin"

            def __init__(self):
                self.jobs = {}
                self.cleaned = set()
                self.next_id = 1
                self.connect_count = 0
                self.page_read_attempts = 0

            def connect(self):
                self.connect_count += 1

            def disconnect(self):
                return None

            def apply_batch(self, actions, *, transaction_id=None):
                node_id = f"node-{self.next_id}"
                self.next_id += 1
                self.jobs[node_id] = transaction_id
                return {
                    "status": "committed",
                    "transactionId": transaction_id,
                    "committed": [
                        {
                            "index": 0,
                            "action": actions[0]["action"],
                            "result": node_id,
                        }
                    ],
                }

            def ownership_report(self, job_id):
                nodes = [
                    {"nodeId": node_id, "jobId": owner}
                    for node_id, owner in self.jobs.items()
                    if owner == job_id and node_id not in self.cleaned
                ]
                return {"status": "reported", "matched": len(nodes), "nodes": nodes}

            def cleanup_owned_job(self, job_id):
                matched = [
                    node_id
                    for node_id, owner in self.jobs.items()
                    if owner == job_id and node_id not in self.cleaned
                ]
                self.cleaned.update(matched)
                return {
                    "status": "cleaned",
                    "jobId": job_id,
                    "matched": len(matched),
                    "removed": len(matched),
                    "failed": [],
                }

            def _send(self, action, params, *, request_id=None):
                self.page_read_attempts += 1
                if self.page_read_attempts == 1:
                    raise FigmaBridgeError(
                        "Figma plugin disconnected: plugin socket closed",
                        code="COMMAND_FAILED",
                        outcome="unknown",
                        request_id="cleanup-readback",
                    )
                return {
                    "id": "0:1",
                    "name": "P5 Pilot",
                    "type": "PAGE",
                    "children": [
                        {"id": "59:2", "name": "P5-PILOT-ROOT", "type": "FRAME"}
                    ],
                }

        admin = FakeAdmin()
        setup = _setup_owned_soak_nodes(admin, "cleanup-reconnect", mode="write")
        cleanup = _cleanup_owned_soak_nodes(admin, setup)

        self.assertTrue(cleanup["verified"])
        self.assertEqual(admin.page_read_attempts, 2)
        self.assertGreaterEqual(admin.connect_count, 2)

    def test_real_soak_report_fails_when_journal_exceeds_bound(self) -> None:
        report = build_real_soak_report(
            requested=100,
            succeeded=100,
            failed=0,
            duration_seconds=10.0,
            concurrency=4,
            latencies_ms=[10, 20, 30],
            errors=[],
            setup_cleanup={
                "setup_verified": True,
                "cleanup_verified": True,
            },
        )

        bounded = apply_journal_bound(
            report,
            journal_events=5000,
            max_journal_events=4096,
        )

        self.assertEqual(bounded["status"], "fail")
        self.assertFalse(bounded["journal_bounded"])
        self.assertIn("journal_bounded", bounded["failed_checks"])

    def test_write_pacing_report_accepts_safe_rejections(self) -> None:
        report = build_write_pacing_report(
            requested=100,
            completed=100,
            safe_rejections=20,
            retries=20,
            failed=0,
            unknown=0,
            duration_seconds=2.0,
            latencies_ms=[10, 20, 30],
            max_plugin_write_inflight=1,
            min_dispatch_gap_ms=50.1,
            max_write_queue=16,
            min_write_interval_ms=50,
            write_queue_timeout_seconds=5,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["requests_per_second"], 50.0)

    def test_write_pacing_report_fails_on_unknown_outcome(self) -> None:
        report = build_write_pacing_report(
            requested=100,
            completed=99,
            safe_rejections=5,
            retries=6,
            failed=1,
            unknown=1,
            duration_seconds=2.0,
            latencies_ms=[10, 20, 30],
            max_plugin_write_inflight=1,
            min_dispatch_gap_ms=50.1,
            max_write_queue=16,
            min_write_interval_ms=50,
            write_queue_timeout_seconds=5,
        )

        self.assertEqual(report["status"], "fail")
        self.assertIn("no_unknown_outcomes", report["failed_checks"])


if __name__ == "__main__":
    unittest.main()
