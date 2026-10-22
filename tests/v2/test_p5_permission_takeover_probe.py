from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.p5_permission_takeover_probe import run_probe
from src.app.services.rendering.figma_adapter import classify_permission_failure


class PermissionClassificationTests(unittest.TestCase):
    def test_permission_and_rate_limit_outcomes_are_distinct(self) -> None:
        view_only = classify_permission_failure(
            {"code": "EACCES", "status": 403, "message": "view-only document"}
        )
        denied = classify_permission_failure("write permission denied")
        rate_limit = classify_permission_failure(
            {"code": "429", "message": "Figma rate limit", "retryAfterMs": 1500}
        )
        revoked = classify_permission_failure("plugin token revoked")
        takeover = classify_permission_failure("plugin takeover: connection replaced")

        self.assertEqual(view_only.category, "view-only")
        self.assertEqual(denied.category, "permission-denied")
        self.assertEqual(rate_limit.category, "rate-limited")
        self.assertTrue(rate_limit.retryable)
        self.assertEqual(rate_limit.retry_after_ms, 1500)
        self.assertEqual(revoked.category, "plugin-token-revoked")
        self.assertEqual(takeover.category, "plugin-takeover")
        for outcome in (view_only, denied, revoked, takeover):
            self.assertFalse(outcome.retryable)
            self.assertTrue(outcome.no_resend)
            self.assertTrue(outcome.manual_review)

    def test_user_modification_after_send_requires_review(self) -> None:
        outcome = classify_permission_failure(
            {"code": "PRECONDITION_FAILED", "message": "node changed by collaborator"}
        )

        self.assertEqual(outcome.category, "user-modification")
        self.assertFalse(outcome.retryable)
        self.assertTrue(outcome.no_resend)
        self.assertTrue(outcome.manual_review)

    def test_probe_reports_missing_real_environment_without_claiming_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            result = run_probe(Path(raw_dir))

            self.assertEqual(result["status"], "completed-for-current-scope")
            self.assertTrue(result["real_environment_required"])
            self.assertTrue(all(item["passed"] for item in result["checks"]))
            self.assertTrue((Path(raw_dir) / "result.json").is_file())


if __name__ == "__main__":
    unittest.main()
