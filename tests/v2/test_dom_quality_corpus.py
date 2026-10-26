from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.app.services.structure import capture as capture_module
from src.app.services.evidence.dom_quality_corpus import (
    build_capture_fingerprint,
    evaluate_capture,
    load_corpus,
    thresholds_sha256,
    validate_corpus,
)
from src.config.settings import Config
from scripts.dom_quality_corpus import (
    _build_parser,
    ensure_output_available,
    ensure_manifest_mutable,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests" / "fixtures" / "dom_quality" / "real_site_corpus_v1.json"


class DomQualityCorpusDraftTests(unittest.TestCase):
    def test_draft_manifest_covers_three_required_real_sites(self) -> None:
        corpus = load_corpus(MANIFEST)
        self.assertEqual(validate_corpus(corpus), ())
        self.assertEqual(
            [sample["site"] for sample in corpus["samples"]],
            ["React", "Dushu", "Shoelace"],
        )
        self.assertEqual(
            [sample["url"] for sample in corpus["samples"]],
            [
                "https://react.dev/",
                "https://www.dushu.com/",
                "https://shoelace.style/",
            ],
        )
        excluded = corpus["excluded_sites"]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(
            excluded[0]["url"], "https://www.w3schools.com/html/html_iframe.asp"
        )
        self.assertEqual(excluded[0]["status"], "excluded-state-unstable")

    def test_validation_rejects_missing_independent_threshold(self) -> None:
        corpus = load_corpus(MANIFEST)
        broken = copy.deepcopy(corpus)
        del broken["thresholds"]["visual"]["max_bad_pixel_ratio"]
        errors = validate_corpus(broken)
        self.assertIn("thresholds.visual.max_bad_pixel_ratio is required", errors)

    def test_validation_rejects_non_https_required_sample(self) -> None:
        corpus = load_corpus(MANIFEST)
        broken = copy.deepcopy(corpus)
        broken["samples"][0]["url"] = "http://react.dev/"
        errors = validate_corpus(broken)
        self.assertIn("sample DQ-R01 url must use https", errors)

    def test_threshold_hash_changes_when_a_frozen_threshold_changes(self) -> None:
        corpus = load_corpus(MANIFEST)
        before = thresholds_sha256(corpus)
        changed = copy.deepcopy(corpus)
        changed["thresholds"]["text"]["box_tolerance_px"] = 3.0
        self.assertNotEqual(before, thresholds_sha256(changed))

    def test_browser_context_uses_configured_locale_and_timezone(self) -> None:
        config = Config(playwright_locale="en-US", playwright_timezone="UTC")
        options = capture_module._browser_context_options(
            config,
            {"width": 1440, "height": 900},
        )
        self.assertEqual(options["locale"], "en-US")
        self.assertEqual(options["timezone_id"], "UTC")
        self.assertEqual(options["device_scale_factor"], 1)


def _write_capture(
    root: Path, *, forbidden: bool = False, unstable: bool = False
) -> Path:
    capture_dir = root / "capture"
    capture_dir.mkdir()
    text = [
        "React",
        "The library for web and native user interfaces",
        "Learn React",
    ]
    if forbidden:
        text.append("Access Denied")
    dom = [
        {"tag": "h1", "text": text[0], "x": 0, "y": 0, "w": 100, "h": 30},
        {"tag": "p", "text": text[1], "x": 0, "y": 40, "w": 300, "h": 30},
        {"tag": "a", "text": text[2], "x": 0, "y": 80, "w": 80, "h": 20},
        {"tag": "img", "text": "", "x": 0, "y": 120, "w": 20, "h": 20},
        {"tag": "svg", "text": "", "x": 30, "y": 120, "w": 20, "h": 20},
    ]
    if forbidden:
        dom.append({"tag": "p", "text": text[-1], "x": 0, "y": 160, "w": 100, "h": 20})
    (capture_dir / "00_dom.json").write_text(json.dumps(dom), encoding="utf-8")
    page_state = {
        "requested_url": "https://react.dev/",
        "final_url": "https://react.dev/",
        "kind": "content",
        "browser_engine": "chromium",
        "capture_profile": "dom-quality-state-strict/1.0",
        "navigation": {"status": "ok"},
        "capture_stability": {"stable": not unstable, "stable_ms": 900},
        "frame_inventory": [],
    }
    (capture_dir / "00_page_state.json").write_text(
        json.dumps(page_state),
        encoding="utf-8",
    )
    (capture_dir / "00_screenshot.png").write_bytes(b"corpus-screenshot")
    return capture_dir


class DomQualityCorpusFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = load_corpus(MANIFEST)
        self.sample = copy.deepcopy(self.corpus["samples"][0])
        self.sample["required_markers"] = {
            "dom_nodes": 5,
            "text_nodes": 3,
            "img": 1,
            "svg": 1,
        }

    def test_fingerprint_records_raw_files_and_state_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fingerprint = build_capture_fingerprint(_write_capture(Path(tmp)))
        for key in (
            "dom_sha256",
            "page_state_sha256",
            "screenshot_sha256",
            "structure_sha256",
            "text_sha256",
            "node_count",
            "text_count",
        ):
            self.assertIn(key, fingerprint)
        self.assertEqual(fingerprint["page_state_kind"], "content")
        self.assertEqual(fingerprint["node_count"], 5)

    def test_matching_capture_passes_independent_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture_dir = _write_capture(Path(tmp))
            self.sample["fingerprint"] = build_capture_fingerprint(capture_dir)
            result = evaluate_capture(
                self.sample,
                capture_dir,
                self.corpus["thresholds"],
            )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["reasons"], [])
        self.assertTrue(all(check["pass"] for check in result["checks"].values()))

    def test_forbidden_text_and_unstable_state_fail_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture_dir = _write_capture(Path(tmp), forbidden=True, unstable=True)
            self.sample["fingerprint"] = build_capture_fingerprint(capture_dir)
            result = evaluate_capture(
                self.sample,
                capture_dir,
                self.corpus["thresholds"],
            )
        self.assertIn("forbidden-text", result["reasons"])
        self.assertIn("state-unstable", result["reasons"])
        self.assertFalse(result["checks"]["forbidden_text"]["pass"])
        self.assertFalse(result["checks"]["state"]["pass"])

    def test_node_and_text_count_drift_fail_independently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            capture_dir = _write_capture(Path(tmp))
            self.sample["fingerprint"] = build_capture_fingerprint(capture_dir)
            self.sample["fingerprint"]["node_count"] = 2
            self.sample["fingerprint"]["text_count"] = 1
            self.sample["required_markers"] = {
                "dom_nodes": 1,
                "text_nodes": 1,
                "img": 1,
                "svg": 1,
            }
            result = evaluate_capture(
                self.sample,
                capture_dir,
                self.corpus["thresholds"],
            )
        self.assertIn("node-count-drift", result["reasons"])
        self.assertIn("text-count-drift", result["reasons"])


class DomQualityCorpusCliTests(unittest.TestCase):
    def test_cli_requires_explicit_capture_freeze_or_verify_mode(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "verify",
                "--manifest",
                str(MANIFEST),
                "--out",
                "output/_corpus_test",
            ]
        )
        self.assertEqual(args.command, "verify")
        self.assertEqual(args.manifest, MANIFEST)

    def test_nonempty_output_requires_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            output.mkdir()
            (output / "existing.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                ensure_output_available(output, overwrite=False)
            ensure_output_available(output, overwrite=True)

    def test_frozen_manifest_rejects_implicit_mutation(self) -> None:
        corpus = load_corpus(MANIFEST)
        corpus["status"] = "frozen"
        with self.assertRaises(ValueError):
            ensure_manifest_mutable(corpus, refreeze=False)
        ensure_manifest_mutable(corpus, refreeze=True)


if __name__ == "__main__":
    unittest.main()
