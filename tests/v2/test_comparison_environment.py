from __future__ import annotations

import unittest

from src.app.services.evidence.comparison_environment import (
    ComparisonEnvironmentError,
    freeze_comparison_environment,
    validate_comparison_environment,
)


def _run(
    *,
    viewport: tuple[int, int] = (1440, 900),
    dpr: int = 1,
    screenshot_size: tuple[int, int] = (1440, 7080),
    design_canvas: tuple[int, int] = (1440, 7080),
) -> dict:
    return {
        "capture": {
            "viewport": {"width": viewport[0], "height": viewport[1]},
            "device_scale_factor": dpr,
            "canvas_size": list(screenshot_size),
        },
        "screenshot_size": list(screenshot_size),
        "design_canvas": list(design_canvas),
    }


class ComparisonEnvironmentTests(unittest.TestCase):
    def test_matching_capture_environment_passes(self) -> None:
        expected = freeze_comparison_environment(
            viewport=(1440, 900),
            device_scale_factor=1,
            profile_id="desktop",
        )

        report = validate_comparison_environment(
            {"dom": _run(), "grounding": _run()},
            expected,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["profile_id"], "desktop")
        self.assertEqual(report["issues"], [])

    def test_viewport_breakpoint_mismatch_fails_closed(self) -> None:
        expected = freeze_comparison_environment(
            viewport=(1440, 900),
            device_scale_factor=1,
        )
        mobile = _run(
            viewport=(848, 2052),
            dpr=3,
            screenshot_size=(2544, 23838),
            design_canvas=(848, 7946),
        )

        with self.assertRaises(ComparisonEnvironmentError) as raised:
            validate_comparison_environment({"dom": mobile}, expected)

        codes = [issue["code"] for issue in raised.exception.report["issues"]]
        self.assertIn("VIEWPORT_MISMATCH", codes)
        self.assertIn("DEVICE_SCALE_FACTOR_MISMATCH", codes)

    def test_design_canvas_must_match_screenshot_divided_by_dpr(self) -> None:
        expected = freeze_comparison_environment(
            viewport=(848, 2052),
            device_scale_factor=3,
        )
        truncated = _run(
            viewport=(848, 2052),
            dpr=3,
            screenshot_size=(2544, 23838),
            design_canvas=(848, 2052),
        )

        with self.assertRaises(ComparisonEnvironmentError) as raised:
            validate_comparison_environment({"dom": truncated}, expected)

        self.assertIn(
            "DESIGN_CANVAS_MISMATCH",
            [issue["code"] for issue in raised.exception.report["issues"]],
        )

    def test_reference_image_breakpoint_must_match_frozen_viewport(self) -> None:
        with self.assertRaises(ComparisonEnvironmentError) as raised:
            freeze_comparison_environment(
                viewport=(1440, 900),
                device_scale_factor=3,
                reference_size=(2544, 6156),
            )

        self.assertIn(
            "REFERENCE_BREAKPOINT_MISMATCH",
            [issue["code"] for issue in raised.exception.report["issues"]],
        )

    def test_missing_capture_metadata_is_not_treated_as_default(self) -> None:
        expected = freeze_comparison_environment(
            viewport=(1440, 900),
            device_scale_factor=1,
        )
        missing = {
            "capture": {},
            "screenshot_size": [1440, 7080],
            "design_canvas": [1440, 7080],
        }

        with self.assertRaises(ComparisonEnvironmentError) as raised:
            validate_comparison_environment({"dom": missing}, expected)

        self.assertEqual(
            [issue["code"] for issue in raised.exception.report["issues"]],
            ["MISSING_VIEWPORT", "MISSING_DEVICE_SCALE_FACTOR"],
        )


if __name__ == "__main__":
    unittest.main()
