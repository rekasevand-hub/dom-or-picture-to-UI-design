from __future__ import annotations

import unittest

from scripts.p1_engine_condition_probe import (
    _evaluate_with_navigation_retry,
    summarize_condition_probe,
)


def _observation(
    condition: str,
    engine: str,
    ua_mode: str,
    feature_mode: str = "none",
    **targets: bool,
) -> dict:
    return {
        "condition": condition,
        "engine": engine,
        "ua_mode": ua_mode,
        "feature_mode": feature_mode,
        "targets": targets,
    }


class EngineConditionProbeTests(unittest.TestCase):
    def test_stable_feature_shim_change_is_feature_candidate(self) -> None:
        summary = summarize_condition_probe([
            _observation(
                "chromium-native",
                "chromium",
                "native",
                feature_mode="none",
                passkey=True,
            ),
            _observation(
                "chromium-native",
                "chromium",
                "native",
                feature_mode="none",
                passkey=True,
            ),
            _observation(
                "chromium-password-credential-off",
                "chromium",
                "native",
                feature_mode="password-credential-off",
                passkey=False,
            ),
            _observation(
                "chromium-password-credential-off",
                "chromium",
                "native",
                feature_mode="password-credential-off",
                passkey=False,
            ),
        ])

        result = summary["targets"]["passkey"]
        self.assertTrue(result["feature_dependency_candidate"])
        self.assertIn("feature-conditioned-candidate", result["candidates"])

    def test_transient_navigation_context_is_retried(self) -> None:
        class FakePage:
            def __init__(self) -> None:
                self.calls = 0

            def evaluate(self, _script: str):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("Execution context was destroyed")
                return {"ready": True}

        page = FakePage()

        result = _evaluate_with_navigation_retry(page, "() => ({ready:true})")

        self.assertEqual(result, {"ready": True})
        self.assertEqual(page.calls, 2)

    def test_stable_native_engine_difference_is_only_engine_candidate(self) -> None:
        summary = summarize_condition_probe([
            _observation("chromium-native", "chromium", "native", passkey=True),
            _observation("chromium-native", "chromium", "native", passkey=True),
            _observation("webkit-native", "webkit", "native", passkey=False),
            _observation("webkit-native", "webkit", "native", passkey=False),
        ])

        result = summary["targets"]["passkey"]
        self.assertTrue(result["engine_correlated_candidate"])
        self.assertFalse(result["ua_dependency_candidate"])
        self.assertFalse(summary["confirmed_root_cause"])

    def test_stable_ua_swap_change_is_ua_candidate(self) -> None:
        summary = summarize_condition_probe([
            _observation("chromium-native", "chromium", "native", passkey=False),
            _observation("chromium-native", "chromium", "native", passkey=False),
            _observation(
                "chromium-with-webkit-ua",
                "chromium",
                "webkit-ua",
                passkey=True,
            ),
            _observation(
                "chromium-with-webkit-ua",
                "chromium",
                "webkit-ua",
                passkey=True,
            ),
        ])

        result = summary["targets"]["passkey"]
        self.assertTrue(result["ua_dependency_candidate"])
        self.assertIn("ua-conditioned-candidate", result["candidates"])

    def test_repeat_variation_remains_session_variation(self) -> None:
        summary = summarize_condition_probe([
            _observation("webkit-native", "webkit", "native", passkey=True),
            _observation("webkit-native", "webkit", "native", passkey=False),
        ])

        result = summary["targets"]["passkey"]
        self.assertTrue(result["session_variation"])
        self.assertEqual(result["candidates"], ["session-variation"])
        self.assertFalse(summary["confirmed_root_cause"])

    def test_invalid_session_is_not_counted_as_target_absence(self) -> None:
        failed = _observation(
            "chromium-native",
            "chromium",
            "native",
            passkey=False,
        )
        failed["valid"] = False
        summary = summarize_condition_probe([
            failed,
            _observation("chromium-native", "chromium", "native", passkey=True),
            _observation("webkit-native", "webkit", "native", passkey=False),
        ])

        condition = summary["targets"]["passkey"]["conditions"]["chromium-native"]
        self.assertEqual(condition["count"], 1)
        self.assertTrue(condition["present"])

    def test_all_invalid_sessions_keep_targets_unresolved(self) -> None:
        failed = _observation(
            "chromium-native",
            "chromium",
            "native",
            passkey=False,
        )
        failed["valid"] = False

        summary = summarize_condition_probe([failed])

        self.assertIn("passkey", summary["targets"])
        self.assertIsNone(summary["targets"]["passkey"]["conditions"][
            "chromium-native"
        ]["present"])
        self.assertEqual(
            summary["targets"]["passkey"]["candidates"],
            ["session-variation"],
        )


if __name__ == "__main__":
    unittest.main()
