from __future__ import annotations

import unittest

from scripts.p1_figma_holdout_summary import summarize_acceptance_reports


def _report(
    design_path: str,
    *,
    status: str,
    visual: str,
    evaluated: int,
) -> dict:
    return {
        "inputs": {"design": {"path": design_path}},
        "acceptance_status": status,
        "figma_evaluated_count": evaluated,
        "dimensions": {
            "structure": {"status": "pass"},
            "visual": {"status": visual},
            "edit": {"status": "pass"},
            "asset": {"status": "pass"},
        },
        "checks": {
            "visual": {
                "failed_metrics": (["bad_pixel_count"] if visual == "fail" else []),
                "metrics": {"mean": 1.0, "bad_pixel_count": 10},
            },
        },
    }


class FigmaHoldoutSummaryTests(unittest.TestCase):
    def test_summary_counts_pass_and_keeps_visual_failure(self) -> None:
        reports = [
            _report(
                r"D:\samples\holdout-frame\12_design.json",
                status="pass",
                visual="pass",
                evaluated=1,
            ),
            _report(
                r"D:\samples\holdout-remote-asset\12_design.json",
                status="blocked-fail",
                visual="fail",
                evaluated=0,
            ),
        ]

        summary = summarize_acceptance_reports(reports)

        self.assertEqual(summary["sample_count"], 2)
        self.assertEqual(summary["pass_count"], 1)
        self.assertEqual(summary["blocked_count"], 1)
        self.assertEqual(summary["figma_evaluated_count"], 1)
        self.assertEqual(
            summary["failed_samples"][0]["sample_id"],
            "holdout-remote-asset",
        )
        self.assertEqual(
            summary["failed_samples"][0]["failed_metrics"],
            ["bad_pixel_count"],
        )

    def test_summary_does_not_use_composite_score(self) -> None:
        summary = summarize_acceptance_reports([])

        self.assertFalse(summary["composite_score_used"])
        self.assertEqual(summary["sample_count"], 0)

    def test_summary_counts_declared_partial_separately(self) -> None:
        summary = summarize_acceptance_reports(
            [
                _report(
                    r"D:\samples\complete\12_design.json",
                    status="pass",
                    visual="pass",
                    evaluated=1,
                ),
                _report(
                    r"D:\samples\partial-asset\12_design.json",
                    status="partial",
                    visual="pass",
                    evaluated=1,
                ),
            ]
        )

        self.assertEqual(summary["pass_count"], 1)
        self.assertEqual(summary["partial_count"], 1)
        self.assertEqual(summary["blocked_count"], 0)
        self.assertEqual(summary["figma_evaluated_count"], 2)


if __name__ == "__main__":
    unittest.main()
