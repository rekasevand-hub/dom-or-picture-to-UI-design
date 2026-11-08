# -*- coding: utf-8 -*-
"""Controlled evidence for bounded Grounding failover and recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.contracts import canonical_hash  # noqa: E402
from src.app.services.structure.backends.grounding_reliability import (  # noqa: E402
    GroundingReliability,
    GroundingRequestError,
    GroundingUnavailableError,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class _Unavailable503(RuntimeError):
    status_code = 503


class _Unavailable429(RuntimeError):
    status_code = 429


def _runtime(
    *,
    endpoints: tuple[str, ...] = ("https://primary.test/v1", "https://backup.test/v1"),
    max_attempts: int = 3,
    breaker_threshold: int = 3,
    cooldown: float = 10.0,
    namespace: str = "probe",
    clock: _Clock | None = None,
) -> GroundingReliability:
    return GroundingReliability(
        endpoints=endpoints,
        model="vision-probe",
        cache_namespace=namespace,
        max_attempts=max_attempts,
        retry_base_ms=10,
        max_backoff_ms=20,
        jitter_ratio=0.25,
        breaker_failure_threshold=breaker_threshold,
        breaker_cooldown_seconds=cooldown,
        cache_max_entries=8,
        cache_ttl_seconds=60,
        clock=clock,
        sleeper=lambda _seconds: None,
        random_value=lambda: 0.5,
    )


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)

    failover_calls: list[str] = []
    failover = _runtime()

    def failover_invoke(endpoint: str) -> dict[str, Any]:
        failover_calls.append(endpoint)
        if endpoint.startswith("https://primary"):
            raise _Unavailable503("controlled 503")
        return {"containers": [], "elements": [{"type": "text"}]}

    failover_result = failover.run(
        image_bytes=b"failover-image",
        prompt="failover prompt",
        invoke=failover_invoke,
    )

    bounded_calls: list[str] = []
    bounded = _runtime(max_attempts=3)

    def bounded_invoke(endpoint: str) -> dict[str, Any]:
        bounded_calls.append(endpoint)
        raise _Unavailable429("controlled 429")

    bounded_error = None
    try:
        bounded.run(
            image_bytes=b"bounded-image",
            prompt="bounded prompt",
            invoke=bounded_invoke,
        )
    except GroundingUnavailableError as exc:
        bounded_error = exc.report

    breaker_clock = _Clock()
    breaker = _runtime(
        endpoints=("https://primary.test/v1",),
        max_attempts=1,
        breaker_threshold=2,
        cooldown=10.0,
        clock=breaker_clock,
    )
    breaker_calls = 0

    def breaker_fail(_endpoint: str) -> dict[str, Any]:
        nonlocal breaker_calls
        breaker_calls += 1
        raise _Unavailable503("controlled breaker failure")

    for _ in range(2):
        try:
            breaker.run(
                image_bytes=b"breaker-image",
                prompt="breaker prompt",
                invoke=breaker_fail,
            )
        except GroundingUnavailableError:
            pass
    calls_before_open = breaker_calls
    try:
        breaker.run(
            image_bytes=b"breaker-image",
            prompt="breaker prompt",
            invoke=breaker_fail,
        )
    except GroundingUnavailableError as exc:
        open_report = exc.report
    breaker_clock.value += 10.0
    recovered = breaker.run(
        image_bytes=b"breaker-image",
        prompt="breaker prompt",
        invoke=lambda _endpoint: {"containers": [], "elements": []},
    )

    malformed_calls: list[str] = []
    malformed = _runtime()

    def malformed_invoke(endpoint: str) -> dict[str, Any]:
        malformed_calls.append(endpoint)
        raise GroundingRequestError("response-invalid", "controlled malformed JSON")

    malformed_blocked = False
    try:
        malformed.run(
            image_bytes=b"malformed-image",
            prompt="malformed prompt",
            invoke=malformed_invoke,
        )
    except GroundingRequestError:
        malformed_blocked = True

    cached = _runtime(endpoints=("https://primary.test/v1",))
    cache_calls = 0

    def cache_invoke(_endpoint: str) -> dict[str, Any]:
        nonlocal cache_calls
        cache_calls += 1
        return {"containers": [], "elements": [{"text": "cached"}]}

    cached.run(
        image_bytes=b"cache-image",
        prompt="cache prompt",
        invoke=cache_invoke,
    )
    cache_hit = cached.run(
        image_bytes=b"cache-image",
        prompt="cache prompt",
        invoke=cache_invoke,
    )
    other_namespace = _runtime(namespace="other")
    cache_isolated = cached.cache_key(
        b"cache-image", "cache prompt"
    ) != other_namespace.cache_key(b"cache-image", "cache prompt")

    checks = [
        {
            "name": "endpoint-failover",
            "description": "A transient primary failure selects the backup.",
            "passed": (
                failover_result.report.final_endpoint_index == 1
                and len(failover_calls) == 2
            ),
        },
        {
            "name": "bounded-retry",
            "description": "A failing call stops at the configured attempt bound.",
            "passed": (
                bounded_error is not None
                and len(bounded_calls) == 3
                and bounded_error.attempt_count == 3
                and len(bounded_error.attempts) == 3
            ),
        },
        {
            "name": "breaker-recovers",
            "description": "An open breaker skips, then a half-open probe recovers.",
            "passed": (
                calls_before_open == 2
                and breaker_calls == 2
                and open_report.attempts[0].error_category == "circuit-open"
                and recovered.report.breaker_probe == "half-open"
            ),
        },
        {
            "name": "malformed-does-not-fallback",
            "description": "Malformed Grounding output is not routed to CV.",
            "passed": (
                malformed_blocked and malformed_calls == ["https://primary.test/v1"]
            ),
        },
        {
            "name": "cache-hit-and-isolation",
            "description": "A bounded cache hit avoids invocation and namespaces differ.",
            "passed": (
                cache_hit.report.cache_status == "hit"
                and cache_calls == 1
                and cache_isolated
            ),
        },
    ]
    report = {
        "schema_version": "grounding-reliability-probe/1.0",
        "status": (
            "pass-current-scope"
            if all(item["passed"] for item in checks)
            else "blocked"
        ),
        "scope": "controlled in-process Grounding endpoint faults",
        "code_revision": _code_revision(),
        "source_hashes": {
            "reliability": _sha(
                ROOT / "src/app/services/structure/backends/grounding_reliability.py"
            ),
            "vlm": _sha(ROOT / "src/app/services/structure/backends/grounding_vlm.py"),
            "config": _sha(ROOT / "src/config/settings.py"),
        },
        "observed": {
            "failover": failover_result.report.to_dict(),
            "bounded_retry": bounded_error.to_dict() if bounded_error else None,
            "breaker": {
                "calls_before_open_probe": calls_before_open,
                "calls_after_open_probe": breaker_calls,
                "cooldown_probe": recovered.report.to_dict(),
            },
            "malformed_calls": malformed_calls,
            "cache_calls": cache_calls,
            "cache_hit": cache_hit.report.to_dict(),
        },
        "checks": checks,
        "boundary": {
            "real_network": False,
            "real_grounding_service": False,
            "real_figma": False,
            "production_pricing": False,
        },
        "non_claims": [
            "no-real-grounding-service",
            "no-production-endpoint-latency",
            "no-production-pricing",
            "production-admission",
        ],
        "limitations": [
            "Endpoint failures are controlled callback exceptions.",
            "The report does not prove availability of any external provider.",
            "Token usage and cost are not measured on a live service.",
        ],
    }
    report["content_hash"] = canonical_hash(report)
    _write_json(destination / "result.json", report)
    return report


def _code_revision() -> str:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return revision + ("+dirty" if dirty else "")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    staging.write_text(payload, encoding="utf-8")
    os.replace(staging, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    result = run_probe(args.out)
    print("status=" + result["status"])
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] == "pass-current-scope" else 1


if __name__ == "__main__":
    raise SystemExit(main())
