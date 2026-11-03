from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.app.services.structure.backends.grounding_reliability import (
    GroundingReliability,
    GroundingRequestError,
    GroundingUnavailableError,
)
from src.app.services.structure.backends.grounding_vlm import GroundingVLM
from src.app.services.structure.providers.base import ProviderContext
from src.app.services.structure.providers.grounding import GroundingProvider
from src.config.settings import Config


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _TransientError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _Message:
    content = (
        '{"containers":[{"bbox":[0,0,1,0.2],"role":"banner"}],'
        '"elements":[{"bbox":[0.1,0.1,0.4,0.2],"type":"text","text":"Hello"}]}'
    )


class _Choice:
    message = _Message()


class _Usage:
    prompt_tokens = 11
    completion_tokens = 7
    total_tokens = 18

    def model_dump(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class _Response:
    choices = [_Choice()]
    usage = _Usage()


class _Completions:
    def __init__(self, owner: "_FakeOpenAI") -> None:
        self.owner = owner

    def create(self, **_kwargs):
        self.owner.calls += 1
        if self.owner.fail:
            raise _TransientError(503)
        return _Response()


class _FakeOpenAI:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_Completions(self))
        self.calls = 0
        self.fail = False


def _runtime(
    *,
    endpoints: tuple[str, ...] = ("https://primary.test/v1", "https://backup.test/v1"),
    clock: _Clock | None = None,
    max_attempts: int = 3,
    breaker_threshold: int = 3,
    breaker_cooldown: float = 30.0,
    cache_ttl: float = 300.0,
    cache_entries: int = 8,
    namespace: str = "tenant-a",
    strategy_id: str = "grounding",
    strategy_version: str = "grounding-reliability/1.0",
) -> tuple[GroundingReliability, list[float], _Clock]:
    sleeps: list[float] = []
    selected_clock = clock or _Clock()
    runtime = GroundingReliability(
        endpoints=endpoints,
        model="vision-test",
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        cache_namespace=namespace,
        max_attempts=max_attempts,
        retry_base_ms=100,
        max_backoff_ms=200,
        jitter_ratio=0.25,
        breaker_failure_threshold=breaker_threshold,
        breaker_cooldown_seconds=breaker_cooldown,
        cache_max_entries=cache_entries,
        cache_ttl_seconds=cache_ttl,
        clock=selected_clock,
        sleeper=sleeps.append,
        random_value=lambda: 0.5,
    )
    return runtime, sleeps, selected_clock


class GroundingReliabilityTests(unittest.TestCase):
    def test_transient_failure_fails_over_to_backup_endpoint(self) -> None:
        runtime, sleeps, _clock = _runtime()
        calls: list[str] = []

        def invoke(endpoint: str) -> dict[str, object]:
            calls.append(endpoint)
            if endpoint == "https://primary.test/v1":
                raise _TransientError(503)
            return {"containers": [], "elements": [{"type": "text"}]}

        result = runtime.run(
            image_bytes=b"same-image",
            prompt="grounding prompt",
            invoke=invoke,
        )

        self.assertEqual(
            calls,
            [
                "https://primary.test/v1",
                "https://backup.test/v1",
            ],
        )
        self.assertEqual(len(sleeps), 1)
        self.assertGreaterEqual(sleeps[0], 0.075)
        self.assertLessEqual(sleeps[0], 0.125)
        self.assertEqual(result.value["elements"][0]["type"], "text")
        self.assertEqual(result.report.final_endpoint_index, 1)
        self.assertEqual(result.report.retry_count, 1)
        self.assertEqual(result.report.cache_status, "miss")

    def test_retry_count_is_finite_and_backoff_is_capped(self) -> None:
        runtime, sleeps, _clock = _runtime(max_attempts=3)
        calls: list[str] = []

        def invoke(endpoint: str) -> dict[str, object]:
            calls.append(endpoint)
            raise _TransientError(503)

        with self.assertRaises(GroundingUnavailableError) as caught:
            runtime.run(image_bytes=b"unavailable", prompt="prompt", invoke=invoke)

        self.assertEqual(len(calls), 3)
        self.assertEqual(len(sleeps), 2)
        self.assertTrue(all(0.075 <= value <= 0.25 for value in sleeps))
        self.assertEqual(caught.exception.report.attempt_count, 3)
        self.assertEqual(caught.exception.category, "service-unavailable")

    def test_open_breaker_skips_endpoint_until_half_open_probe_succeeds(self) -> None:
        clock = _Clock()
        runtime, sleeps, _clock = _runtime(
            endpoints=("https://primary.test/v1",),
            clock=clock,
            max_attempts=1,
            breaker_threshold=2,
            breaker_cooldown=10.0,
        )
        calls = 0

        def failing(_endpoint: str) -> dict[str, object]:
            nonlocal calls
            calls += 1
            raise _TransientError(503)

        for _ in range(2):
            with self.assertRaises(GroundingUnavailableError):
                runtime.run(image_bytes=b"image", prompt="prompt", invoke=failing)

        with self.assertRaises(GroundingUnavailableError) as open_error:
            runtime.run(image_bytes=b"image", prompt="prompt", invoke=failing)
        self.assertEqual(calls, 2)
        self.assertEqual(
            open_error.exception.report.attempts[0].error_category, "circuit-open"
        )

        clock.advance(10.0)

        def recovered(_endpoint: str) -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"containers": [], "elements": []}

        result = runtime.run(image_bytes=b"image", prompt="prompt", invoke=recovered)
        self.assertEqual(calls, 3)
        self.assertEqual(result.report.breaker_probe, "half-open")
        self.assertEqual(sleeps, [])

    def test_malformed_response_does_not_fail_over_or_retry(self) -> None:
        runtime, _sleeps, _clock = _runtime()
        calls: list[str] = []

        def invoke(endpoint: str) -> dict[str, object]:
            calls.append(endpoint)
            raise GroundingRequestError("response-invalid", "invalid JSON")

        with self.assertRaises(GroundingRequestError):
            runtime.run(image_bytes=b"malformed", prompt="prompt", invoke=invoke)

        self.assertEqual(calls, ["https://primary.test/v1"])

    def test_cache_key_covers_every_required_input_dimension(self) -> None:
        base, _sleeps, _clock = _runtime(namespace="tenant-a")
        image_key = base.cache_key(b"image-a", "prompt-a")
        self.assertNotEqual(
            image_key,
            base.cache_key(b"image-b", "prompt-a"),
        )
        self.assertNotEqual(
            image_key,
            base.cache_key(b"image-a", "prompt-b"),
        )
        other_model, _sleeps2, _clock2 = _runtime(namespace="tenant-a")
        other_model.model = "vision-other"
        self.assertNotEqual(
            image_key,
            other_model.cache_key(b"image-a", "prompt-a"),
        )
        other_strategy, _sleeps3, _clock3 = _runtime(
            namespace="tenant-a",
            strategy_id="grounding-other",
        )
        self.assertNotEqual(
            image_key,
            other_strategy.cache_key(b"image-a", "prompt-a"),
        )
        other_version, _sleeps4, _clock4 = _runtime(
            namespace="tenant-a",
            strategy_version="grounding-reliability/2.0",
        )
        self.assertNotEqual(
            image_key,
            other_version.cache_key(b"image-a", "prompt-a"),
        )
        other_tenant, _sleeps5, _clock5 = _runtime(namespace="tenant-b")
        self.assertNotEqual(
            image_key,
            other_tenant.cache_key(b"image-a", "prompt-a"),
        )

    def test_cache_hit_is_bounded_copy_and_isolated_by_expiry(self) -> None:
        clock = _Clock()
        runtime, _sleeps, _clock = _runtime(
            endpoints=("https://primary.test/v1",),
            clock=clock,
            cache_ttl=5.0,
            cache_entries=2,
        )
        calls = 0

        def invoke(_endpoint: str) -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"containers": [], "elements": [{"type": "text", "text": "cached"}]}

        first = runtime.run(image_bytes=b"image", prompt="prompt", invoke=invoke)
        first.value["elements"][0]["text"] = "mutated"
        second = runtime.run(image_bytes=b"image", prompt="prompt", invoke=invoke)
        self.assertEqual(calls, 1)
        self.assertEqual(second.value["elements"][0]["text"], "cached")
        self.assertEqual(second.report.cache_status, "hit")

        clock.advance(6.0)
        runtime.run(image_bytes=b"image", prompt="prompt", invoke=invoke)
        self.assertEqual(calls, 2)

    def test_cache_lru_evicts_oldest_entry(self) -> None:
        runtime, _sleeps, _clock = _runtime(
            endpoints=("https://primary.test/v1",),
            cache_entries=2,
        )
        calls = 0

        def invoke(_endpoint: str) -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"containers": [], "elements": [], "call": calls}

        runtime.run(image_bytes=b"one", prompt="prompt", invoke=invoke)
        runtime.run(image_bytes=b"two", prompt="prompt", invoke=invoke)
        runtime.run(image_bytes=b"three", prompt="prompt", invoke=invoke)
        runtime.run(image_bytes=b"one", prompt="prompt", invoke=invoke)
        self.assertEqual(calls, 4)

    def test_cached_value_is_a_deep_copy(self) -> None:
        runtime, _sleeps, _clock = _runtime(
            endpoints=("https://primary.test/v1",),
        )
        original = {"containers": [], "elements": [{"type": "text"}]}
        runtime.run(
            image_bytes=b"image",
            prompt="prompt",
            invoke=lambda _endpoint: copy.deepcopy(original),
        )
        original["elements"][0]["type"] = "image"
        cached = runtime.run(
            image_bytes=b"image",
            prompt="prompt",
            invoke=lambda _endpoint: {"containers": [], "elements": []},
        )
        self.assertEqual(cached.value["elements"][0]["type"], "text")

    def test_cache_hit_does_not_replay_provider_token_usage(self) -> None:
        runtime, _sleeps, _clock = _runtime(
            endpoints=("https://primary.test/v1",),
        )
        first = runtime.run(
            image_bytes=b"image",
            prompt="prompt",
            invoke=lambda _endpoint: (
                {"containers": [], "elements": []},
                {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            ),
        )
        second = runtime.run(
            image_bytes=b"image",
            prompt="prompt",
            invoke=lambda _endpoint: {"containers": [], "elements": []},
        )
        self.assertEqual(first.report.usage["total_tokens"], 10)
        self.assertEqual(second.report.usage, {})

    def test_grounding_vlm_fails_over_and_records_usage(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            image_path = Path(raw_dir) / "image.png"
            image_path.write_bytes(b"fake-png-bytes")
            runtime, sleeps, _clock = _runtime()
            clients: dict[str, _FakeOpenAI] = {}

            def factory(base_url: str, _timeout: float) -> _FakeOpenAI:
                client = _FakeOpenAI()
                client.fail = base_url.startswith("https://primary")
                clients[base_url] = client
                return client

            cfg = SimpleNamespace(
                vision_base_urls=(
                    "https://primary.test/v1",
                    "https://backup.test/v1",
                ),
                vision_model="vision-test",
                vision_timeout=7,
                vision_api_key="generated-test-key",
                vision_max_image_bytes=1024,
                vision_max_response_bytes=1024,
            )
            backend = GroundingVLM(
                cfg,
                runtime=runtime,
                client_factory=factory,
            )

            graph = backend.ground(str(image_path), 200, 100)

        self.assertEqual(graph["elements"][0]["text"], "Hello")
        self.assertEqual(backend.last_report.final_endpoint_index, 1)
        self.assertEqual(backend.last_report.usage["total_tokens"], 18)
        self.assertEqual(
            [client.calls for client in clients.values()],
            [1, 1],
        )
        self.assertEqual(len(sleeps), 1)

    def test_grounding_vlm_uses_cache_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            image_path = Path(raw_dir) / "image.png"
            image_path.write_bytes(b"cache-image")
            runtime, _sleeps, _clock = _runtime()
            calls = 0

            def factory(_base_url: str, _timeout: float) -> _FakeOpenAI:
                nonlocal calls
                calls += 1
                return _FakeOpenAI()

            cfg = SimpleNamespace(
                vision_base_urls=("https://primary.test/v1",),
                vision_model="vision-test",
                vision_timeout=7,
                vision_api_key="generated-test-key",
                vision_max_image_bytes=1024,
                vision_max_response_bytes=1024,
            )
            first = GroundingVLM(cfg, runtime=runtime, client_factory=factory)
            first.ground(str(image_path), 200, 100)
            second = GroundingVLM(cfg, runtime=runtime, client_factory=factory)
            second.ground(str(image_path), 200, 100)

        self.assertEqual(calls, 1)
        self.assertEqual(second.last_report.cache_status, "hit")

    def test_provider_provenance_contains_reliability_report(self) -> None:
        class _Backend:
            last_report = SimpleNamespace(
                to_dict=lambda: {
                    "attempt_count": 2,
                    "retry_count": 1,
                    "cache_status": "miss",
                }
            )

            def ground(self, _image_path, _width, _height):
                return {
                    "containers": [{"bbox": [0, 0, 100, 20], "role": "banner"}],
                    "elements": [
                        {"bbox": [5, 5, 50, 10], "type": "text", "text": "Hello"}
                    ],
                }

        backend = _Backend()
        with patch(
            "src.app.services.structure.providers.grounding._default_backend",
            return_value=backend,
        ):
            graph = GroundingProvider(SimpleNamespace()).run(
                ProviderContext(
                    image_path="image.png",
                    image_w=100,
                    image_h=100,
                    route="grounding",
                    output_dir=".",
                )
            )

        self.assertEqual(
            graph["provenance"]["grounding_reliability"]["retry_count"],
            1,
        )

    def test_config_reads_bounded_redundancy_settings(self) -> None:
        values = {
            "VISION_BASE_URLS": (
                "https://one.test/v1, https://two.test/v1, https://three.test/v1"
            ),
            "VISION_MAX_ATTEMPTS": "3",
            "VISION_RETRY_BASE_MS": "125",
            "VISION_MAX_BACKOFF_MS": "2000",
            "VISION_BREAKER_FAILURE_THRESHOLD": "4",
            "VISION_BREAKER_COOLDOWN_SECONDS": "15",
            "VISION_CACHE_MAX_ENTRIES": "12",
            "VISION_CACHE_TTL_SECONDS": "60",
            "VISION_MAX_IMAGE_BYTES": "4096",
            "VISION_MAX_RESPONSE_BYTES": "8192",
            "VISION_CACHE_NAMESPACE": "test-tenant",
        }
        with patch.dict(os.environ, values, clear=False):
            cfg = Config(
                figma_bridge_url="ws://localhost:8765",
                delivery_profile="legacy",
            )

        self.assertEqual(
            cfg.vision_base_urls,
            (
                "https://one.test/v1",
                "https://two.test/v1",
                "https://three.test/v1",
            ),
        )
        self.assertEqual(cfg.vision_max_attempts, 3)
        self.assertEqual(cfg.vision_retry_base_ms, 125)
        self.assertEqual(cfg.vision_max_backoff_ms, 2000)
        self.assertEqual(cfg.vision_breaker_failure_threshold, 4)
        self.assertEqual(cfg.vision_breaker_cooldown_seconds, 15)
        self.assertEqual(cfg.vision_cache_max_entries, 12)
        self.assertEqual(cfg.vision_cache_ttl_seconds, 60)
        self.assertEqual(cfg.vision_max_image_bytes, 4096)
        self.assertEqual(cfg.vision_max_response_bytes, 8192)
        self.assertEqual(cfg.vision_cache_namespace, "test-tenant")


if __name__ == "__main__":
    unittest.main()
