from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "compare_routes.py"


def _write_run(
    root: Path,
    route: str,
    *,
    viewport: tuple[int, int],
    dpr: int,
    screenshot_size: tuple[int, int],
    canvas_size: tuple[int, int],
) -> None:
    out = root / route
    out.mkdir(parents=True)
    screenshot = out / "00_screenshot.png"
    Image.new("RGB", screenshot_size, "white").save(screenshot)
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "route": route,
                "image": str(screenshot),
                "capture": {
                    "viewport": {
                        "width": viewport[0],
                        "height": viewport[1],
                    },
                    "device_scale_factor": dpr,
                    "canvas_size": list(screenshot_size),
                },
            }
        ),
        encoding="utf-8",
    )
    (out / "10_pagegraph.json").write_text(
        json.dumps({"route": route, "containers": [], "elements": []}),
        encoding="utf-8",
    )
    (out / "12_design.json").write_text(
        json.dumps({"canvas": {"width": canvas_size[0], "height": canvas_size[1]}}),
        encoding="utf-8",
    )


class CompareRoutesEnvironmentTests(unittest.TestCase):
    def test_check_only_validates_existing_runs_before_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run(
                root,
                "dom",
                viewport=(1440, 900),
                dpr=1,
                screenshot_size=(1440, 7080),
                canvas_size=(1440, 7080),
            )
            _write_run(
                root,
                "cv",
                viewport=(1440, 900),
                dpr=1,
                screenshot_size=(1440, 7080),
                canvas_size=(1440, 7080),
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--base-out",
                    str(root),
                    "--routes",
                    "dom,cv",
                    "--viewport",
                    "1440x900",
                    "--device-scale-factor",
                    "1",
                    "--check-only",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            environment = json.loads(
                (root / "comparison_environment.json").read_text(encoding="utf-8")
            )
            self.assertEqual(environment["status"], "pass")
            self.assertTrue((root / "summary.json").is_file())

    def test_check_only_rejects_breakpoint_mismatch_before_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run(
                root,
                "dom",
                viewport=(1440, 900),
                dpr=1,
                screenshot_size=(1440, 7080),
                canvas_size=(1440, 7080),
            )
            _write_run(
                root,
                "cv",
                viewport=(848, 2052),
                dpr=3,
                screenshot_size=(2544, 23838),
                canvas_size=(848, 7946),
            )
            stale_summary = root / "summary.json"
            stale_summary.write_text('{"stale": true}', encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--base-out",
                    str(root),
                    "--routes",
                    "dom,cv",
                    "--viewport",
                    "1440x900",
                    "--device-scale-factor",
                    "1",
                    "--check-only",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("VIEWPORT_MISMATCH", completed.stderr)
            self.assertFalse(stale_summary.exists())
            environment = json.loads(
                (root / "comparison_environment.json").read_text(encoding="utf-8")
            )
            self.assertEqual(environment["status"], "fail")

    def test_image_comparison_does_not_fabricate_browser_viewport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            Image.new("RGB", (2544, 6156), "white").save(source)
            _write_run(
                root,
                "grounding",
                viewport=(1440, 900),
                dpr=1,
                screenshot_size=(2544, 6156),
                canvas_size=(2544, 6156),
            )
            _write_run(
                root,
                "cv",
                viewport=(1440, 900),
                dpr=1,
                screenshot_size=(2544, 6156),
                canvas_size=(2544, 6156),
            )
            for route in ("grounding", "cv"):
                manifest_path = root / route / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["image"] = str(source)
                manifest["capture"] = None
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--base-out",
                    str(root),
                    "--image",
                    str(source),
                    "--routes",
                    "grounding,cv",
                    "--check-only",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            environment = json.loads(
                (root / "comparison_environment.json").read_text(encoding="utf-8")
            )
            self.assertEqual(environment["status"], "not-applicable-image-input")
            self.assertEqual(
                environment["reason"],
                "image-input-has-no-browser-viewport",
            )

    def test_reference_image_breakpoint_mismatch_fails_before_run_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "reference.png"
            Image.new("RGB", (2544, 6156), "white").save(reference)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--base-out",
                    str(root / "compare"),
                    "--routes",
                    "dom,cv",
                    "--viewport",
                    "1440x900",
                    "--device-scale-factor",
                    "3",
                    "--reference-image",
                    str(reference),
                    "--check-only",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("REFERENCE_BREAKPOINT_MISMATCH", completed.stderr)
            self.assertFalse((root / "compare" / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
