from __future__ import annotations

import unittest

from scripts.figma_bridge_soak_probe import (
    build_real_soak_report,
    summarize_latencies,
)
from scripts.bridge_write_backpressure_soak import build_write_pacing_report


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
        )

        self.assertEqual(report["mode"], "write")
        self.assertEqual(report["status"], "pass")

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
