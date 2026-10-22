from __future__ import annotations

import unittest

from scripts.r5_p3_resume_soak import build_r5_p3_soak_report, run_soak
from scripts.figma_r5_p3_resume_probe import build_real_resume_report
from src.app.services.job_namespace import parse_job_namespace


class R5P3ResumeSoakReportTests(unittest.TestCase):
    def test_real_resume_report_requires_unknown_and_no_resend(self) -> None:
        report = build_real_resume_report(
            job_id="job-real",
            bridge_state="unknown",
            ownership_classification="matches-intended",
            resume_action="reconcile-no-resend",
            resend_allowed=False,
            cleanup_removed=1,
            post_cleanup_matched=0,
            unknown_count=1,
            duplicate_side_effects=0,
        )

        self.assertEqual(report["status"], "pass")

    def test_real_resume_report_fails_on_resend(self) -> None:
        report = build_real_resume_report(
            job_id="job-real",
            bridge_state="unknown",
            ownership_classification="matches-intended",
            resume_action="safe-retry",
            resend_allowed=True,
            cleanup_removed=1,
            post_cleanup_matched=0,
            unknown_count=1,
            duplicate_side_effects=1,
        )

        self.assertEqual(report["status"], "fail")
        self.assertIn("no_resend_or_duplicate_side_effect", report["failed_checks"])

    def test_reports_zero_duplicate_side_effects_as_pass(self) -> None:
        report = build_r5_p3_soak_report(
            jobs=6,
            committed=1,
            reconciled=1,
            manual_review=3,
            duplicate_side_effects=0,
            duplicate_job_conflicts=1,
            cleanup_success=1,
            cleanup_failed=1,
            plugin_write_calls=1,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["failed_checks"], [])

    def test_fails_on_duplicate_side_effects(self) -> None:
        report = build_r5_p3_soak_report(
            jobs=6,
            committed=2,
            reconciled=1,
            manual_review=3,
            duplicate_side_effects=1,
            duplicate_job_conflicts=1,
            cleanup_success=1,
            cleanup_failed=1,
            plugin_write_calls=3,
        )

        self.assertEqual(report["status"], "fail")
        self.assertIn("no_duplicate_side_effects", report["failed_checks"])

    def test_soak_isolates_same_raw_id_across_clients(self) -> None:
        report = run_soak()

        self.assertEqual(report["status"], "pass")
        isolation = report["namespace_isolation"]
        self.assertEqual(isolation["raw_job_id"], "shared-raw")
        self.assertTrue(isolation["distinct"])
        self.assertEqual(isolation["client_a"], "client-a")
        self.assertEqual(isolation["client_b"], "client-b")
        self.assertEqual(
            parse_job_namespace(isolation["job_a"]).raw_job_id,
            "shared-raw",
        )
        self.assertEqual(
            parse_job_namespace(isolation["job_b"]).raw_job_id,
            "shared-raw",
        )
        self.assertEqual(report["duplicate_side_effects"], 0)


if __name__ == "__main__":
    unittest.main()
