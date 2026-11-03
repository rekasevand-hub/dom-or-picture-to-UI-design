"""Bounded Grounding execution with endpoint failover and recovery."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class GroundingAttempt:
    endpoint_index: int
    endpoint: str
    outcome: str
    error_category: str | None
    retryable: bool
    latency_ms: float
    breaker_state: str
    http_status: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_index": self.endpoint_index,
            "endpoint": self.endpoint,
            "outcome": self.outcome,
            "error_category": self.error_category,
            "retryable": self.retryable,
            "latency_ms": round(self.latency_ms, 3),
            "breaker_state": self.breaker_state,
            "http_status": self.http_status,
        }


@dataclass(slots=True)
class GroundingRunReport:
    model: str
    strategy_id: str
    strategy_version: str
    cache_key_prefix: str
    cache_status: str = "miss"
    attempts: list[GroundingAttempt] = field(default_factory=list)
    attempt_count: int = 0
    retry_count: int = 0
    final_endpoint_index: int | None = None
    latency_ms: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    breaker_probe: str | None = None
    error_category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "grounding-reliability-report/1.0",
            "model": self.model,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "cache_key_prefix": self.cache_key_prefix,
            "cache_status": self.cache_status,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "attempt_count": self.attempt_count,
            "retry_count": self.retry_count,
            "final_endpoint_index": self.final_endpoint_index,
            "latency_ms": round(self.latency_ms, 3),
            "usage": dict(self.usage),
            "breaker_probe": self.breaker_probe,
            "error_category": self.error_category,
        }


@dataclass(frozen=True, slots=True)
class GroundingInvocation:
    value: Any
    report: GroundingRunReport


class GroundingUnavailableError(RuntimeError):
    """All eligible Grounding endpoints are unavailable within the retry bound."""

    def __init__(
        self,
        category: str,
        report: GroundingRunReport,
        *,
        message: str = "Grounding service is unavailable",
    ) -> None:
        super().__init__(message)
        self.category = category
        self.report = report


class GroundingRequestError(ValueError):
    """A non-retryable Grounding request or response contract failure."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.report: GroundingRunReport | None = None


@dataclass(slots=True)
class _BreakerState:
    consecutive_failures: int = 0
    opened_at: float | None = None

    def select(self, now: float, cooldown: float) -> str | None:
        if self.opened_at is None:
            return "closed"
        if now - self.opened_at >= cooldown:
            return "half-open"
        return None

    def success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None

    def failure(self, now: float, threshold: int, state: str) -> None:
        self.consecutive_failures += 1
        if state == "half-open" or self.consecutive_failures >= threshold:
            self.opened_at = now


class GroundingReliability:
    """Retry one endpoint at a time and never exceed ``max_attempts`` calls."""

    def __init__(
        self,
        *,
        endpoints: Sequence[str],
        model: str,
        strategy_id: str = "grounding",
        strategy_version: str = "grounding-reliability/1.0",
        cache_namespace: str = "default",
        max_attempts: int = 3,
        retry_base_ms: float = 250.0,
        max_backoff_ms: float = 4000.0,
        jitter_ratio: float = 0.25,
        breaker_failure_threshold: int = 3,
        breaker_cooldown_seconds: float = 30.0,
        cache_max_entries: int = 64,
        cache_ttl_seconds: float = 300.0,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
        random_value: Callable[[], float] | None = None,
    ) -> None:
        normalized = tuple(str(item).strip().rstrip("/") for item in endpoints)
        if not normalized or any(not item for item in normalized):
            raise ValueError("at least one non-empty Grounding endpoint is required")
        if not str(model or "").strip():
            raise ValueError("Grounding model is required")
        if not str(strategy_id or "").strip():
            raise ValueError("Grounding strategy id is required")
        if not str(strategy_version or "").strip():
            raise ValueError("Grounding strategy version is required")
        if not str(cache_namespace or "").strip():
            raise ValueError("Grounding cache namespace is required")
        if max_attempts <= 0 or max_attempts > 10:
            raise ValueError("max_attempts must be in 1..10")
        if retry_base_ms < 0 or max_backoff_ms < 0:
            raise ValueError("Grounding backoff must be non-negative")
        if not 0 <= jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be in 0..1")
        if breaker_failure_threshold <= 0:
            raise ValueError("breaker_failure_threshold must be positive")
        if breaker_cooldown_seconds <= 0:
            raise ValueError("breaker_cooldown_seconds must be positive")
        if cache_max_entries <= 0:
            raise ValueError("cache_max_entries must be positive")
        if cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds must be positive")
        self.endpoints = normalized
        self.model = str(model).strip()
        self.strategy_id = str(strategy_id).strip()
        self.strategy_version = str(strategy_version).strip()
        self.cache_namespace = str(cache_namespace).strip()
        self.max_attempts = int(max_attempts)
        self.retry_base_ms = float(retry_base_ms)
        self.max_backoff_ms = float(max_backoff_ms)
        self.jitter_ratio = float(jitter_ratio)
        self.breaker_failure_threshold = int(breaker_failure_threshold)
        self.breaker_cooldown_seconds = float(breaker_cooldown_seconds)
        self.cache_max_entries = int(cache_max_entries)
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._random = random_value or __import__("random").random
        self._breakers = [_BreakerState() for _ in self.endpoints]
        self._cache: OrderedDict[
            str,
            tuple[float, Any, dict[str, Any]],
        ] = OrderedDict()
        self._lock = threading.Lock()

    def cache_key(
        self,
        image_bytes: bytes,
        prompt: str | Mapping[str, Any] | Sequence[Any],
    ) -> str:
        material = {
            "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
            "model": self.model,
            "prompt_sha256": hashlib.sha256(
                _canonical_prompt(prompt).encode("utf-8")
            ).hexdigest(),
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "cache_namespace": self.cache_namespace,
        }
        return hashlib.sha256(
            json.dumps(
                material,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def run(
        self,
        *,
        image_bytes: bytes,
        prompt: str | Mapping[str, Any] | Sequence[Any],
        invoke: Callable[[str], Any],
    ) -> GroundingInvocation:
        started = self._clock()
        key = self.cache_key(image_bytes, prompt)
        report = GroundingRunReport(
            model=self.model,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            cache_key_prefix=key[:16],
        )
        cached = self._cache_get(key)
        if cached is not None:
            value, _usage = cached
            report.cache_status = "hit"
            report.latency_ms = max(0.0, (self._clock() - started) * 1000)
            report.usage = {}
            return GroundingInvocation(value=copy.deepcopy(value), report=report)

        cursor = 0
        last_category = "service-unavailable"
        actual_attempts = 0
        skipped: set[int] = set()
        while actual_attempts < self.max_attempts:
            now = self._clock()
            selected: tuple[int, str] | None = None
            for offset in range(len(self.endpoints)):
                index = (cursor + offset) % len(self.endpoints)
                breaker_state = self._breakers[index].select(
                    now,
                    self.breaker_cooldown_seconds,
                )
                if breaker_state is not None:
                    selected = (index, breaker_state)
                    break
                if index not in skipped:
                    report.attempts.append(
                        GroundingAttempt(
                            endpoint_index=index,
                            endpoint=_safe_endpoint(self.endpoints[index]),
                            outcome="skipped",
                            error_category="circuit-open",
                            retryable=True,
                            latency_ms=0.0,
                            breaker_state="open",
                        )
                    )
                    skipped.add(index)
            if selected is None:
                report.error_category = "circuit-open"
                self._finish_unavailable(report, started, "circuit-open")

            endpoint_index, breaker_state = selected
            cursor = (endpoint_index + 1) % len(self.endpoints)
            actual_attempts += 1
            report.attempt_count = actual_attempts
            attempt_started = self._clock()
            if breaker_state == "half-open":
                report.breaker_probe = "half-open"
            try:
                raw = invoke(self.endpoints[endpoint_index])
                value, usage = _coerce_result(raw)
            except GroundingRequestError as exc:
                report.attempts.append(
                    GroundingAttempt(
                        endpoint_index=endpoint_index,
                        endpoint=_safe_endpoint(self.endpoints[endpoint_index]),
                        outcome="request-error",
                        error_category=exc.category,
                        retryable=False,
                        latency_ms=max(
                            0.0,
                            (self._clock() - attempt_started) * 1000,
                        ),
                        breaker_state=breaker_state,
                    )
                )
                report.error_category = exc.category
                exc.report = report
                raise
            except Exception as exc:  # noqa: BLE001 - classified below
                category, status, retryable = _classify_exception(exc)
                if category in {"request-invalid", "response-invalid"}:
                    report.attempts.append(
                        GroundingAttempt(
                            endpoint_index=endpoint_index,
                            endpoint=_safe_endpoint(self.endpoints[endpoint_index]),
                            outcome="request-error",
                            error_category=category,
                            retryable=False,
                            latency_ms=max(
                                0.0,
                                (self._clock() - attempt_started) * 1000,
                            ),
                            breaker_state=breaker_state,
                            http_status=status,
                        )
                    )
                    report.error_category = category
                    error = GroundingRequestError(category, str(exc))
                    error.report = report
                    raise error from exc
                last_category = category
                self._breakers[endpoint_index].failure(
                    self._clock(),
                    self.breaker_failure_threshold,
                    breaker_state,
                )
                report.attempts.append(
                    GroundingAttempt(
                        endpoint_index=endpoint_index,
                        endpoint=_safe_endpoint(self.endpoints[endpoint_index]),
                        outcome="unavailable",
                        error_category=category,
                        retryable=retryable,
                        latency_ms=max(
                            0.0,
                            (self._clock() - attempt_started) * 1000,
                        ),
                        breaker_state=breaker_state,
                        http_status=status,
                    )
                )
                report.retry_count = max(0, actual_attempts - 1)
                if actual_attempts >= self.max_attempts:
                    break
                if retryable:
                    delay = self._backoff(actual_attempts)
                    self._sleeper(delay)
                continue

            self._breakers[endpoint_index].success()
            report.attempts.append(
                GroundingAttempt(
                    endpoint_index=endpoint_index,
                    endpoint=_safe_endpoint(self.endpoints[endpoint_index]),
                    outcome="success",
                    error_category=None,
                    retryable=False,
                    latency_ms=max(
                        0.0,
                        (self._clock() - attempt_started) * 1000,
                    ),
                    breaker_state=breaker_state,
                )
            )
            report.final_endpoint_index = endpoint_index
            report.retry_count = max(0, actual_attempts - 1)
            report.usage = dict(usage)
            report.latency_ms = max(0.0, (self._clock() - started) * 1000)
            self._cache_put(key, value, usage)
            return GroundingInvocation(
                value=copy.deepcopy(value),
                report=report,
            )

        self._finish_unavailable(report, started, last_category)

    def _finish_unavailable(
        self,
        report: GroundingRunReport,
        started: float,
        category: str,
    ) -> None:
        report.error_category = category
        report.retry_count = max(0, report.attempt_count - 1)
        report.latency_ms = max(0.0, (self._clock() - started) * 1000)
        product_category = (
            "circuit-open" if category == "circuit-open" else "service-unavailable"
        )
        raise GroundingUnavailableError(product_category, report)

    def _backoff(self, failed_attempt: int) -> float:
        nominal = min(
            self.max_backoff_ms,
            self.retry_base_ms * (2 ** max(0, failed_attempt - 1)),
        )
        jitter = 1.0 + self.jitter_ratio * ((self._random() * 2.0) - 1.0)
        return max(0.0, nominal * jitter) / 1000.0

    def _cache_get(self, key: str) -> tuple[Any, dict[str, Any]] | None:
        now = self._clock()
        with self._lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            expires_at, value, usage = cached
            if expires_at <= now:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return copy.deepcopy(value), dict(usage)

    def _cache_put(self, key: str, value: Any, usage: Mapping[str, Any]) -> None:
        with self._lock:
            self._cache[key] = (
                self._clock() + self.cache_ttl_seconds,
                copy.deepcopy(value),
                dict(usage),
            )
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_max_entries:
                self._cache.popitem(last=False)


def _coerce_result(raw: Any) -> tuple[Any, dict[str, Any]]:
    if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[1], Mapping):
        return raw[0], dict(raw[1])
    if isinstance(raw, Mapping) and "_grounding_usage" in raw:
        value = copy.deepcopy(dict(raw))
        usage = value.pop("_grounding_usage")
        return value, dict(usage) if isinstance(usage, Mapping) else {}
    return raw, {}


def _canonical_prompt(
    prompt: str | Mapping[str, Any] | Sequence[Any],
) -> str:
    if isinstance(prompt, str):
        return prompt
    return json.dumps(
        prompt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _safe_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        host = parsed.hostname or "unknown"
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return f"{parsed.scheme}://{host}{parsed.path}".rstrip("/")
    return value.split("?", 1)[0].split("#", 1)[0]


def _classify_exception(exc: BaseException) -> tuple[str, int | None, bool]:
    status = _status_code(exc)
    name = type(exc).__name__.lower()
    text = str(exc or "").lower()
    if status in {401, 403}:
        return "authentication", status, False
    if status == 429:
        return "rate-limit", status, True
    if status is not None and 500 <= status <= 599:
        return "server", status, True
    if status in {408, 425}:
        return "timeout", status, True
    if status is not None and 400 <= status <= 499:
        return "request-invalid", status, False
    if any(
        token in name
        for token in (
            "connection",
            "timeout",
        )
    ) or any(
        token in text
        for token in (
            "connection refused",
            "connection reset",
            "request timed out",
            "timed out",
            "temporarily unavailable",
            "service unavailable",
        )
    ):
        return "connection", status, True
    if "ratelimit" in name or "rate limit" in text:
        return "rate-limit", status, True
    if isinstance(exc, (json.JSONDecodeError, ValueError, TypeError)):
        return "response-invalid", status, False
    return "request-invalid", status, False


def _status_code(exc: BaseException) -> int | None:
    candidates = [
        getattr(exc, "status_code", None),
        getattr(exc, "code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ]
    for value in candidates:
        try:
            status = int(value)
        except (TypeError, ValueError):
            continue
        if 100 <= status <= 599:
            return status
    return None
