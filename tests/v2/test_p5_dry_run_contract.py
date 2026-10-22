from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.p5_dry_run import run_dry_run
from src.config.settings import Config


class P5DryRunContractTests(unittest.TestCase):
    def test_default_remains_legacy_while_p5_is_explicit(self) -> None:
        self.assertEqual(Config().delivery_profile, "legacy")

        with tempfile.TemporaryDirectory() as raw_dir:
            result = run_dry_run(Path(raw_dir), deterministic_writes=20)

            self.assertEqual(result["delivery_profile"], "contract-v2")
            self.assertTrue(result["profile"]["p5_command_explicit"])
            self.assertEqual(result["deterministic"]["status"], "pass")
            self.assertEqual(result["staged_rehearsal"]["status"], "not-run")
            self.assertEqual(result["status"], "blocked-environment")

    def test_frozen_manifest_contains_thresholds_and_operator_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_dry_run(output, deterministic_writes=20)

            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["delivery_profile"], "contract-v2")
            self.assertIn("code_revision", manifest)
            self.assertIn("plugin_build", manifest)
            self.assertIn("chromium_version", manifest)
            self.assertIn("allowed_actions", manifest)
            self.assertEqual(manifest["thresholds"]["max_unknown"], 0)
            self.assertTrue(manifest["manual_review_owner_required"])
            self.assertEqual(manifest["figma_document"], "unassigned")
            self.assertEqual(result["deterministic"]["writers"], 4)
            self.assertTrue(result["deterministic"]["no_automatic_resend"])
            self.assertTrue(result["deterministic"]["cleanup_exact"])


if __name__ == "__main__":
    unittest.main()
