from __future__ import annotations

import unittest

from scripts.bridge_journal_soak import build_soak_report


class BridgeJournalSoakTests(unittest.TestCase):
    def test_soak_report_requires_clean_pending_and_bounded_journal(self) -> None:
        report = build_soak_report(
            requested=100,
            completed=100,
            failed=0,
            pending=0,
            scope_pending=0,
            cache_entries=32,
            max_cache_entries=32,
            journal_events=32,
            max_journal_events=64,
            replay_cache_entries=32,
            elapsed_seconds=1.0,
            peak_memory_bytes=1024,
        )

        self.assertEqual(report["status"], "pass")
        self.assertGreater(report["requests_per_second"], 0)
        self.assertEqual(report["failed_checks"], [])

    def test_soak_report_fails_closed_on_pending_or_journal_leak(self) -> None:
        report = build_soak_report(
            requested=100,
            completed=99,
            failed=0,
            pending=1,
            scope_pending=1,
            cache_entries=40,
            max_cache_entries=32,
            journal_events=128,
            max_journal_events=64,
            replay_cache_entries=0,
            elapsed_seconds=1.0,
            peak_memory_bytes=2048,
        )

        self.assertEqual(report["status"], "fail")
        self.assertIn("all_requests_completed", report["failed_checks"])
        self.assertIn("pending_cleared", report["failed_checks"])
        self.assertIn("scope_pending_cleared", report["failed_checks"])
        self.assertIn("cache_bounded", report["failed_checks"])
        self.assertIn("journal_bounded", report["failed_checks"])
        self.assertIn("journal_replay_loaded", report["failed_checks"])


if __name__ == "__main__":
    unittest.main()
