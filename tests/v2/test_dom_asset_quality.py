from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.app.services.evidence.dom_asset_quality import (
    build_asset_quality_report,
    collect_asset_uses,
)
from scripts.dom_asset_quality import _build_parser


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests/fixtures/dom_quality/real_site_corpus_v1.json"


def _write_capture(root: Path, sample_id: str, dom: list[dict]) -> None:
    capture = root / sample_id
    capture.mkdir(parents=True)
    (capture / "00_dom.json").write_text(
        json.dumps(dom),
        encoding="utf-8",
    )
    image = Image.new("RGBA", (320, 240), (245, 245, 245, 255))
    for x in range(20, 120):
        for y in range(20, 100):
            image.putpixel((x, y), (220, 30, 50, 255))
    image.save(capture / "00_screenshot.png")


class DomAssetQualityTests(unittest.TestCase):
    def test_collect_asset_uses_separates_renderable_and_missing_images(self) -> None:
        dom = [
            {
                "tag": "img",
                "assetSrc": "https://cdn.example/shared.png",
                "naturalWidth": 100,
                "naturalHeight": 80,
                "objectFit": "cover",
                "objectPosition": "100% 50%",
                "x": 10,
                "y": 20,
                "w": 50,
                "h": 80,
            },
            {
                "tag": "img",
                "assetSrc": "https://cdn.example/broken.png",
                "naturalWidth": 0,
                "naturalHeight": 0,
                "x": 80,
                "y": 20,
                "w": 50,
                "h": 40,
            },
            {
                "tag": "svg",
                "x": 140,
                "y": 20,
                "w": 24,
                "h": 24,
            },
        ]

        uses = collect_asset_uses(dom, sample_id="DQ-T")

        self.assertEqual(len(uses), 3)
        self.assertEqual(uses[0]["source_kind"], "img")
        self.assertEqual(uses[1]["load_status"], "missing")
        self.assertEqual(uses[2]["source_kind"], "inline-svg")
        self.assertEqual(uses[0]["source_rect"], [50.0, 0.0, 50.0, 80.0])

    def test_report_keeps_source_crop_missing_and_replacement_independent(self) -> None:
        corpus = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_root = root / "capture"
            probe_root = root / "probes"
            source_png = io.BytesIO()
            Image.new("RGBA", (100, 80), (20, 60, 220, 255)).save(
                source_png,
                format="PNG",
            )
            asset_bytes = source_png.getvalue()
            sha = hashlib.sha256(asset_bytes).hexdigest()
            asset_path = probe_root / "assets" / "shared.png"
            asset_path.parent.mkdir(parents=True)
            asset_path.write_bytes(asset_bytes)
            shared = "https://cdn.example/shared.png"
            dom_one = [
                {
                    "tag": "img",
                    "assetSrc": shared,
                    "naturalWidth": 100,
                    "naturalHeight": 80,
                    "objectFit": "cover",
                    "objectPosition": "100% 50%",
                    "x": 10,
                    "y": 20,
                    "w": 50,
                    "h": 80,
                },
                {
                    "tag": "img",
                    "assetSrc": shared,
                    "naturalWidth": 100,
                    "naturalHeight": 80,
                    "objectFit": "fill",
                    "x": 80,
                    "y": 20,
                    "w": 50,
                    "h": 40,
                },
                {
                    "tag": "img",
                    "assetSrc": "https://cdn.example/ref.png",
                    "naturalWidth": 60,
                    "naturalHeight": 60,
                    "x": 10,
                    "y": 80,
                    "w": 30,
                    "h": 30,
                },
                {
                    "tag": "img",
                    "assetSrc": "https://cdn.example/broken.png",
                    "naturalWidth": 0,
                    "naturalHeight": 0,
                    "x": 80,
                    "y": 80,
                    "w": 30,
                    "h": 30,
                },
            ]
            _write_capture(capture_root, "DQ-R01", dom_one)
            _write_capture(
                capture_root,
                "DQ-R02",
                [{"tag": "svg", "x": 10, "y": 10, "w": 24, "h": 24}],
            )
            _write_capture(capture_root, "DQ-R03", [])
            probes = {
                "_root": str(probe_root),
                "rows": [
                    {
                        "source_url": shared,
                        "status": "verified-original",
                        "sha256": sha,
                        "mime": "image/png",
                        "natural_size": [100.0, 80.0],
                        "bytes_present": True,
                        "locator": "assets/shared.png",
                    }
                ],
            }

            report = build_asset_quality_report(
                corpus,
                capture_root,
                probes,
            )

        self.assertEqual(report["sample_count"], 3)
        self.assertEqual(report["assets"]["asset_count"], 4)
        self.assertEqual(report["assets"]["use_count"], 5)
        self.assertEqual(report["assets"]["missing_use_count"], 1)
        self.assertEqual(report["source_identity"]["verified_original"], 1)
        self.assertEqual(report["source_identity"]["reference_only"], 1)
        self.assertEqual(report["source_identity"]["unavailable"], 1)
        self.assertEqual(report["source_identity"]["missing"], 1)
        self.assertEqual(report["display_payload"]["screenshot_crop_uses"], 5)
        self.assertTrue(
            all(
                row["kind"] == "screenshot-crop"
                and row["original"] is False
                and row["reference_only"] is True
                for row in report["display_payload"]["rows"]
            )
        )
        self.assertEqual(report["missing"]["outcome"], "partial-not-pass")
        self.assertEqual(report["deduplication"]["shared_asset_count"], 1)
        self.assertEqual(report["deduplication"]["max_uses_per_asset"], 2)
        self.assertEqual(report["replacement"]["allowed_assets"], 1)
        self.assertEqual(
            report["replacement"]["figma_runtime"],
            "not-evaluated",
        )
        self.assertEqual(report["corpus_sha256"], corpus["corpus_sha256"])
        self.assertEqual(
            report["thresholds_sha256"],
            corpus["thresholds_sha256"],
        )
        self.assertFalse(report["composite_score_used"])
        self.assertEqual(report["generated_assets"], 0)
        self.assertEqual(len(report["samples"]), 3)

    def test_source_probe_with_unretained_bytes_fails_closed(self) -> None:
        corpus = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_root = root / "capture"
            _write_capture(
                capture_root,
                "DQ-R01",
                [
                    {
                        "tag": "img",
                        "assetSrc": "https://cdn.example/forged.png",
                        "naturalWidth": 100,
                        "naturalHeight": 80,
                        "x": 10,
                        "y": 10,
                        "w": 50,
                        "h": 40,
                    }
                ],
            )
            _write_capture(capture_root, "DQ-R02", [])
            _write_capture(capture_root, "DQ-R03", [])
            probes = {
                "_root": str(root / "probes"),
                "rows": [
                    {
                        "source_url": "https://cdn.example/forged.png",
                        "status": "verified-original",
                        "sha256": "a" * 64,
                        "mime": "image/png",
                        "natural_size": [100.0, 80.0],
                        "bytes_present": True,
                        "locator": "assets/not-retained.png",
                    }
                ],
            }

            report = build_asset_quality_report(
                corpus,
                capture_root,
                probes,
            )

        verified = [
            asset
            for asset in report["details"]["assets"]
            if asset["source_identity"]["status"] == "verified-original"
        ]
        self.assertEqual(verified, [])
        self.assertEqual(
            report["source_identity"]["blocked_incomplete_identity"],
            1,
        )

    def test_source_probe_with_forged_image_bytes_fails_closed(self) -> None:
        corpus = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_root = root / "capture"
            _write_capture(
                capture_root,
                "DQ-R01",
                [
                    {
                        "tag": "img",
                        "assetSrc": "https://cdn.example/forged.png",
                        "naturalWidth": 100,
                        "naturalHeight": 80,
                        "x": 10,
                        "y": 10,
                        "w": 50,
                        "h": 40,
                    }
                ],
            )
            _write_capture(capture_root, "DQ-R02", [])
            _write_capture(capture_root, "DQ-R03", [])
            forged = b"not-an-image"
            probe_root = root / "probes"
            target = probe_root / "assets" / "forged.png"
            target.parent.mkdir(parents=True)
            target.write_bytes(forged)
            sha = hashlib.sha256(forged).hexdigest()

            report = build_asset_quality_report(
                corpus,
                capture_root,
                {
                    "_root": str(probe_root),
                    "rows": [
                        {
                            "source_url": "https://cdn.example/forged.png",
                            "status": "verified-original",
                            "sha256": sha,
                            "mime": "image/png",
                            "natural_size": [100.0, 80.0],
                            "bytes_present": True,
                            "locator": "assets/forged.png",
                        }
                    ],
                },
            )

        verified = [
            asset
            for asset in report["details"]["assets"]
            if asset["source_identity"]["status"] == "verified-original"
        ]
        self.assertEqual(verified, [])
        self.assertEqual(
            report["source_identity"]["blocked_incomplete_identity"],
            1,
        )

    def test_cli_has_probe_and_report_subcommands(self) -> None:
        parser = _build_parser()
        probe = parser.parse_args(
            [
                "probe",
                "--manifest",
                str(MANIFEST),
                "--capture-root",
                "capture",
                "--out",
                "out",
            ]
        )
        report = parser.parse_args(
            [
                "report",
                "--manifest",
                str(MANIFEST),
                "--capture-root",
                "capture",
                "--source-probes",
                "probes.json",
                "--out",
                "out",
            ]
        )
        self.assertEqual(probe.command, "probe")
        self.assertEqual(report.command, "report")
        self.assertEqual(report.out, Path("out"))

    def test_cli_runs_as_a_direct_script(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "dom_asset_quality.py"),
                "--help",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("probe", result.stdout)
        self.assertIn("report", result.stdout)


if __name__ == "__main__":
    unittest.main()
