from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from src.app.services.evidence.dom_strategy_fusion import build_fusion_report
from scripts.dom_strategy_fusion import _build_parser


ROOT = Path(__file__).resolve().parents[2]


def _asset(asset_id: str, status: str, *, replaceable: bool = False) -> dict:
    return {
        "asset_id": asset_id,
        "source_identity": {
            "status": status,
            "source_kind": "data-uri"
            if status == "verified-original"
            else "remote-url",
            "payload_sha256": "a" * 64 if status == "verified-original" else None,
            "bytes_present": status == "verified-original",
        },
        "replacement": {
            "allowed": replaceable,
            "mode": "source-bytes" if replaceable else "none",
            "figma_runtime": "not-evaluated",
        },
    }


def _use(asset_id: str, use_id: str, *, display: bool = True) -> dict:
    return {
        "asset_id": asset_id,
        "use_id": use_id,
        "node_index": int(use_id.rsplit(":", 2)[1]),
        "source_kind": "img",
        "display_box": [0, 0, 100, 80],
        "display_payload": {
            "status": "available" if display else "missing",
            "kind": "screenshot-crop" if display else "none",
            "payload_sha256": "b" * 64 if display else None,
            "screenshot_sha256": "c" * 64,
            "display_box": [0, 0, 100, 80],
            "source_rect": [0, 0, 100, 80],
            "object_fit": "fill",
            "original": False,
            "reference_only": display,
        },
        "missing": {
            "is_missing": not display,
            "outcome": "pass" if display else "partial-not-pass",
        },
    }


def _asset_report() -> dict:
    verified = "asset:sha256:" + "a" * 64
    reference = "asset:ref:" + "d" * 64
    unavailable = "asset:unverified:1111111111111111"
    missing = "asset:unverified:2222222222222222"
    return {
        "corpus_id": "dom-quality-real-sites/1.0",
        "corpus_sha256": "e" * 64,
        "thresholds_sha256": "f" * 64,
        "details": {
            "assets": [
                _asset(verified, "verified-original", replaceable=True),
                _asset(reference, "reference-only"),
                _asset(unavailable, "unavailable"),
                _asset(missing, "missing"),
            ],
            "uses": [
                _use(verified, "DQ-R01:1:img"),
                _use(verified, "DQ-R01:2:img"),
                _use(reference, "DQ-R02:3:img"),
                _use(unavailable, "DQ-R03:4:svg"),
                _use(missing, "DQ-R01:5:img", display=False),
            ],
        },
    }


class DomStrategyFusionReportTests(unittest.TestCase):
    def test_report_accounts_for_every_use_and_separates_dimensions(self) -> None:
        report = build_fusion_report(_asset_report())

        self.assertEqual(report["use_count"], 5)
        self.assertEqual(report["decision_count"], 5)
        self.assertTrue(report["all_uses_accounted"])
        self.assertEqual(report["source_identity"]["verified_source_uses"], 2)
        self.assertEqual(report["source_identity"]["reference_only_uses"], 1)
        self.assertEqual(report["source_identity"]["unavailable_uses"], 1)
        self.assertEqual(report["source_identity"]["missing_uses"], 1)
        self.assertEqual(report["display_payload"]["screenshot_crop_uses"], 4)
        self.assertEqual(report["display_payload"]["missing_display_uses"], 1)
        self.assertEqual(
            report["generated_approximation"]["selected_uses"],
            0,
        )
        self.assertEqual(report["fallback"]["generated_fallback_uses"], 0)
        self.assertEqual(report["fallback"]["missing_display_uses"], 1)
        self.assertEqual(report["figma_runtime"], "not-evaluated")
        self.assertFalse(report["composite_score_used"])
        self.assertEqual(report["corpus_sha256"], "e" * 64)
        self.assertEqual(report["thresholds_sha256"], "f" * 64)

    def test_report_has_deterministic_fallback_chain_counts(self) -> None:
        first = build_fusion_report(_asset_report())
        second = build_fusion_report(_asset_report())

        self.assertEqual(first, second)
        self.assertEqual(
            first["fallback"]["chain_counts"]["dom-source>screenshot-crop"],
            2,
        )
        self.assertEqual(
            first["fallback"]["chain_counts"]["missing>missing"],
            1,
        )

    def test_report_rejects_duplicate_use_ids(self) -> None:
        document = _asset_report()
        document["details"]["uses"][1]["use_id"] = document["details"]["uses"][0][
            "use_id"
        ]

        with self.assertRaises(ValueError):
            build_fusion_report(document)

    def test_cli_parser_and_direct_execution(self) -> None:
        args = _build_parser().parse_args(
            [
                "--asset-report",
                "asset.json",
                "--out",
                "fusion",
            ]
        )
        self.assertEqual(args.out, Path("fusion"))

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "dom_strategy_fusion.py"),
                "--help",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--asset-report", result.stdout)


if __name__ == "__main__":
    unittest.main()
