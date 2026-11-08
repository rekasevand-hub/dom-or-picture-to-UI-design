from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.production_admission_soak import (
    _lease_ttl_seconds,
    _reconnect_interval,
    build_soak_report,
    run_soak,
)


def _summary(duration: float = 3600.0) -> dict:
    return {
        "requests": 100,
        "committed": 96,
        "safe_rejections": 4,
        "failed": 0,
        "server_errors": 2,
        "rate_limits": 2,
        "reconnects": 2,
        "controlled_unknowns": 1,
        "unreconciled_unknowns": 0,
        "pending": 0,
        "scope_pending": 0,
        "journal_events": 120,
        "ledger_events": 5,
        "latency_ms": [10.0, 20.0, 30.0, 40.0, 50.0],
        "resources": {
            "start": {"rss_bytes": 100_000_000, "handles": 100},
            "end": {"rss_bytes": 110_000_000, "handles": 105},
        },
    }


class ProductionAdmissionSoakTests(unittest.TestCase):
    def test_reconnect_cadence_scales_without_storming_long_runs(self) -> None:
        self.assertAlmostEqual(_reconnect_interval(0.6), 0.2)
        self.assertEqual(_reconnect_interval(3600.0), 300.0)

    def test_lease_ttl_exceeds_bounded_soak_duration(self) -> None:
        self.assertEqual(_lease_ttl_seconds(0.6), 300.0)
        self.assertGreater(_lease_ttl_seconds(3600.0), 3600.0)

    def test_short_rehearsal_is_not_labeled_one_hour_soak(self) -> None:
        report = build_soak_report(
            duration_seconds=30.0,
            checkpoints=[
                {
                    "at_seconds": 10.0,
                    "rss_bytes": 100_000_000,
                    "handles": 100,
                },
                {
                    "at_seconds": 30.0,
                    "rss_bytes": 101_000_000,
                    "handles": 101,
                },
            ],
            summary=_summary(duration=30.0),
        )

        self.assertEqual(report["status"], "rehearsal-pass")
        self.assertFalse(report["one_hour_soak"])
        self.assertIn("duration-at-least-3600", report["failed_checks"])

    def test_one_hour_shape_requires_checkpoints_and_recovery(self) -> None:
        report = build_soak_report(
            duration_seconds=3600.0,
            checkpoints=[
                {
                    "at_seconds": 300.0,
                    "rss_bytes": 100_000_000,
                    "handles": 100,
                },
                {
                    "at_seconds": 3600.0,
                    "rss_bytes": 110_000_000,
                    "handles": 105,
                },
            ],
            summary=_summary(),
        )

        self.assertEqual(report["status"], "blocked")
        self.assertTrue(report["one_hour_soak"])
        self.assertIn("required-checkpoints", report["failed_checks"])

    def test_unreconciled_unknown_blocks_even_with_long_duration(self) -> None:
        summary = _summary()
        summary["unreconciled_unknowns"] = 1
        checkpoints = [
            {
                "at_seconds": second,
                "rss_bytes": 100_000_000,
                "handles": 100,
            }
            for second in (300.0, 900.0, 1800.0, 3600.0)
        ]

        report = build_soak_report(
            duration_seconds=3600.0,
            checkpoints=checkpoints,
            summary=summary,
        )

        self.assertEqual(report["status"], "blocked")
        self.assertIn("controlled-unknown-reconciled", report["failed_checks"])

    def test_failed_requests_block_even_when_every_outcome_is_classified(
        self,
    ) -> None:
        summary = _summary()
        summary["failed"] = 1
        checkpoints = [
            {
                "at_seconds": second,
                "rss_bytes": 100_000_000,
                "handles": 100,
            }
            for second in (300.0, 900.0, 1800.0, 3600.0)
        ]

        report = build_soak_report(
            duration_seconds=3600.0,
            checkpoints=checkpoints,
            summary=summary,
        )

        self.assertEqual(report["status"], "blocked")
        self.assertIn("zero-unexplained-failures", report["failed_checks"])

    def test_short_execution_writes_checkpointed_rehearsal_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            result = run_soak(
                output,
                duration_seconds=0.6,
                checkpoint_every_seconds=0.2,
                workers=4,
                target_rps=60,
                fault_every=4,
                journal_max_events=512,
                reconnect_interval_seconds=0.1,
            )
            persisted = json.loads((output / "result.json").read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "rehearsal-pass")
        self.assertFalse(result["one_hour_soak"])
        self.assertGreater(result["duration_seconds"], 0.6)
        self.assertEqual(result["content_hash"], persisted["content_hash"])
        self.assertTrue(result["source_hashes"]["soak_script"])
        self.assertTrue(result["source_hashes"]["bridge_server"])
        self.assertGreaterEqual(len(result["checkpoints"]), 2)
        self.assertGreater(result["summary"]["rate_limits"], 0)
        self.assertGreater(result["summary"]["server_errors"], 0)
        self.assertGreater(result["summary"]["reconnects"], 0)
        self.assertEqual(result["summary"]["failed"], 0)
        self.assertEqual(result["summary"]["unreconciled_unknowns"], 0)
        self.assertIn("error_codes", result["summary"])
        self.assertFalse(result["boundary"]["real_figma"])


if __name__ == "__main__":
    unittest.main()
