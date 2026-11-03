from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.app.services.structure.router import (
    grounding_fallback_reason,
    route_order,
)


class APIConnectionError(Exception):
    pass


class APITimeoutError(Exception):
    pass


class RateLimitError(Exception):
    pass


class InternalServerError(Exception):
    pass


class JSONDecodeError(ValueError):
    pass


class GroundingUnavailableError(RuntimeError):
    pass


class ImageRouteFallbackTests(unittest.TestCase):
    def test_image_auto_prefers_grounding_then_cv(self) -> None:
        cfg = SimpleNamespace(vision_api_key="configured")
        self.assertEqual(
            route_order("image", None, cfg, have_dom=False),
            ["grounding", "cv"],
        )

    def test_missing_vlm_config_starts_with_cv(self) -> None:
        cfg = SimpleNamespace(vision_api_key="")
        self.assertEqual(
            route_order("image", None, cfg, have_dom=False),
            ["cv"],
        )

    def test_enrichment_mode_does_not_change_image_route_order(self) -> None:
        cfg = SimpleNamespace(
            vision_api_key="configured",
            image_enrichment_mode="apply",
        )
        self.assertEqual(
            route_order("image", None, cfg, have_dom=False),
            ["grounding", "cv"],
        )

    def test_service_unavailability_allows_fallback(self) -> None:
        for error in (
            APIConnectionError("connection refused"),
            APITimeoutError("request timed out"),
            RateLimitError("429 too many requests"),
            InternalServerError("503 service unavailable"),
            GroundingUnavailableError("all endpoints exhausted"),
        ):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(
                    grounding_fallback_reason(error),
                    "grounding-service-unavailable",
                )

    def test_malformed_or_downstream_error_does_not_switch_route(self) -> None:
        self.assertIsNone(grounding_fallback_reason(JSONDecodeError("bad JSON")))
        self.assertIsNone(grounding_fallback_reason(ValueError("empty result")))
        self.assertIsNone(
            grounding_fallback_reason(RuntimeError("renderer failed later"))
        )


if __name__ == "__main__":
    unittest.main()
