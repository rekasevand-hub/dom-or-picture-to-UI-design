"""Figma Plugin WebSocket bridge with correlated request routing."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import math
import os
import ssl
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from src.app.services.bridge_config import (
    BridgeServerConfig,
    BridgeTlsServerConfig,
    ClientWriteLimitConfig,
    load_bridge_config,
)
from src.app.services.attribution import (
    AttributionEvidence,
    AttributionProvider,
    UnavailableAttributionProvider,
)
from src.app.services.job_namespace import (
    JOB_NAMESPACE_PREFIX,
    JobNamespaceError,
    parse_job_namespace,
)
from src.app.services.write_lease import (
    WriterLease,
    WriterLeaseError,
    WriterLeaseStore,
)
from src.app.services.rendering.figma_adapter import classify_permission_failure

try:
    import websockets
    import websockets.server
    from websockets.exceptions import ConnectionClosed
except ImportError as exc:
    raise ImportError("websockets 未安装，请执行 pip install websockets") from exc

logger = logging.getLogger(__name__)

CLIENT_ID_HEADER = "X-Figma-Client-Id"
CLIENT_TOKEN_HEADER = "X-Figma-Client-Token"

READ_ONLY_ACTIONS = frozenset(
    {
        "export_frame",
        "font_probe",
        "font_report",
        "font_strict_probe",
        "get_node_tree",
        "image_fill_report",
        "ownership_report",
    }
)


@dataclass(frozen=True)
class WritePacingPolicy:
    min_interval: float
    queue_timeout: float
    max_queue: int


class JournalLockError(RuntimeError):
    pass


class _JournalFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(
                    handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
        except OSError as exc:
            handle.close()
            raise JournalLockError(
                f"another bridge process owns journal lock {self.path}"
            ) from exc
        metadata = json.dumps(
            {
                "pid": os.getpid(),
                "acquiredAt": time.time(),
            },
            sort_keys=True,
        ).encode("utf-8")
        handle.seek(0)
        handle.truncate()
        handle.write(metadata)
        handle.flush()
        os.fsync(handle.fileno())
        self.handle = handle

    def release(self) -> None:
        handle = self.handle
        if handle is None:
            return
        self.handle = None
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()


@dataclass(frozen=True)
class CompletedResponse:
    completed_at: float
    fingerprint: str
    response: dict[str, Any]
    action: str = ""
    transaction_id: str = ""


@dataclass
class PendingCommand:
    future: asyncio.Future[dict[str, Any]]
    client_id: str
    requested_id: str
    fingerprint: str


@dataclass(frozen=True)
class TransactionRecord:
    client_id: str
    requested_id: str
    transaction_id: str
    state: str
    fingerprint: str
    action: str
    updated_at: float
    response: dict[str, Any] | None = None
    recovered: bool = False
    reconciliation_targets: tuple[str, ...] = ()
    expected_checks: tuple[dict[str, Any], ...] = ()
    ownership_job_id: str = ""
    expected_created_nodes: int = 0
    ownership_readback: dict[str, Any] | None = None
    ownership_reconciliation: dict[str, Any] | None = None
    ownership_readback_at: float | None = None
    reconciliation: dict[str, Any] | None = None
    readback: dict[str, Any] | None = None
    readback_at: float | None = None


class BridgeHub:
    """Correlate one Figma plugin socket with concurrent command clients."""

    def __init__(
        self,
        timeout: float = 30.0,
        idempotency_ttl: float = 60.0,
        *,
        max_inflight: int = 64,
        max_message_bytes: int = 1_048_576,
        max_params_depth: int = 16,
        max_cache_entries: int = 1024,
        journal_path: str | Path | None = None,
        max_journal_events: int = 4096,
        exclusive_journal_lock: bool = False,
        auth_token: str | None = None,
        plugin_token: str | None = None,
        plugin_token_provider: Callable[[], str | None] | None = None,
        plugin_token_recheck_seconds: float = 1.0,
        write_min_interval: float = 0.05,
        write_queue_timeout: float = 5.0,
        max_write_queue: int = 16,
        allow_legacy_job_ids: bool = False,
        client_tokens: Mapping[str, str] | None = None,
        client_write_defaults: ClientWriteLimitConfig | None = None,
        client_write_limits: Mapping[str, ClientWriteLimitConfig] | None = None,
        attribution_provider: AttributionProvider | None = None,
        writer_lease_store: WriterLeaseStore | None = None,
    ) -> None:
        if max_inflight <= 0:
            raise ValueError("max_inflight must be positive")
        if max_message_bytes <= 0:
            raise ValueError("max_message_bytes must be positive")
        if max_params_depth <= 0:
            raise ValueError("max_params_depth must be positive")
        if max_cache_entries <= 0:
            raise ValueError("max_cache_entries must be positive")
        if max_journal_events <= 0:
            raise ValueError("max_journal_events must be positive")
        if write_min_interval < 0:
            raise ValueError("write_min_interval must be non-negative")
        if write_queue_timeout <= 0:
            raise ValueError("write_queue_timeout must be positive")
        if max_write_queue <= 0:
            raise ValueError("max_write_queue must be positive")
        if plugin_token_recheck_seconds <= 0:
            raise ValueError("plugin_token_recheck_seconds must be positive")
        self.timeout = timeout
        self.idempotency_ttl = idempotency_ttl
        self.max_inflight = max_inflight
        self.max_message_bytes = max_message_bytes
        self.max_params_depth = max_params_depth
        self.max_cache_entries = max_cache_entries
        self.max_journal_events = max_journal_events
        self.write_min_interval = float(write_min_interval)
        self.write_queue_timeout = float(write_queue_timeout)
        self.max_write_queue = max_write_queue
        self.allow_legacy_job_ids = bool(allow_legacy_job_ids)
        self.client_tokens = _normalize_client_tokens(client_tokens)
        self.client_write_defaults = (
            client_write_defaults
            or ClientWriteLimitConfig(
                max_inflight=max_write_queue,
                burst=max_write_queue,
                min_interval_ms=0,
            )
        )
        self.client_write_limits = dict(client_write_limits or {})
        self.attribution_provider = (
            attribution_provider or UnavailableAttributionProvider()
        )
        self._validate_client_write_limit(self.client_write_defaults)
        for client_id, limit in self.client_write_limits.items():
            if not str(client_id or "").strip():
                raise ValueError("client write limit client id must be non-empty")
            self._validate_client_write_limit(limit)
        self.auth_token = str(auth_token).strip() if auth_token is not None else None
        if self.auth_token == "":
            raise ValueError("auth_token must not be empty")
        self.plugin_token = (
            str(plugin_token).strip() if plugin_token is not None else None
        )
        if self.plugin_token == "":
            self.plugin_token = None
        self.plugin_token_provider = plugin_token_provider
        self.plugin_token_recheck_seconds = float(plugin_token_recheck_seconds)
        self.journal_path = (
            Path(journal_path).expanduser().resolve()
            if journal_path is not None
            else None
        )
        self._journal_lock = (
            _JournalFileLock(
                self.journal_path.with_name(self.journal_path.name + ".lock")
            )
            if self.journal_path is not None and exclusive_journal_lock
            else None
        )
        if self._journal_lock is not None:
            self._journal_lock.acquire()
        self._writer_lease_store = writer_lease_store
        self.writer_lease: WriterLease | None = None
        if self._writer_lease_store is not None:
            try:
                self.writer_lease = self._writer_lease_store.acquire()
            except Exception:
                if self._journal_lock is not None:
                    self._journal_lock.release()
                raise
        self.plugin_ws: Any | None = None
        self.pending: dict[str, PendingCommand] = {}
        self.completed: dict[tuple[str, str], CompletedResponse] = {}
        self.transactions: dict[str, TransactionRecord] = {}
        self.scope_pending: set[tuple[str, str]] = set()
        self.send_lock = asyncio.Lock()
        self.state_lock = asyncio.Lock()
        self._write_turn_lock = asyncio.Lock()
        self._write_admitted = 0
        self._client_write_admitted: dict[str, int] = {}
        self._client_write_tokens: dict[str, float] = {}
        self._client_write_refilled_at: dict[str, float] = {}
        self._write_not_before = 0.0
        self._write_degraded_reason: str | None = None
        self._journal_intents: dict[tuple[str, str], dict[str, Any]] = {}
        self._journal_event_count = 0
        self._reconcile_task: asyncio.Task[None] | None = None
        self._plugin_token_watch_task: asyncio.Task[None] | None = None
        self._plugin_authenticated_tokens: dict[int, str] = {}
        self._load_journal()

    def close(self) -> None:
        if self._writer_lease_store is not None and self.writer_lease is not None:
            try:
                self._writer_lease_store.release(self.writer_lease)
            except WriterLeaseError:
                pass
            self.writer_lease = None
        if self._journal_lock is not None:
            self._journal_lock.release()

    async def attach_plugin(self, websocket: Any) -> None:
        async with self.state_lock:
            if (
                self._plugin_token_watch_task is not None
                and not self._plugin_token_watch_task.done()
            ):
                self._plugin_token_watch_task.cancel()
            self._plugin_token_watch_task = None
            previous = self.plugin_ws
            if previous is not None and previous is not websocket:
                try:
                    await previous.close(
                        code=4002,
                        reason="replaced by a newer plugin connection",
                    )
                except Exception:  # noqa: BLE001 - stale socket is best effort
                    pass
            self.plugin_ws = websocket
            authenticated_token = self._plugin_authenticated_tokens.pop(
                id(websocket),
                self.plugin_token,
            )
            self._write_degraded_reason = None
            self._write_not_before = 0.0
            logger.info("Figma 插件已连接")
            self._reconcile_task = asyncio.create_task(
                self._reconcile_unknown_transactions()
            )
            if (
                self.plugin_token_provider is not None
                and authenticated_token
            ):
                self._plugin_token_watch_task = asyncio.create_task(
                    self._watch_plugin_token(websocket, authenticated_token)
                )

    async def authenticate_plugin(self, websocket: Any) -> bool:
        expected_token = self.plugin_token
        if self.plugin_token_provider is not None:
            try:
                expected_token = self.plugin_token_provider()
            except Exception:  # noqa: BLE001 - auth provider failure is fail-closed
                expected_token = ""
            expected_token = (
                str(expected_token).strip()
                if expected_token is not None
                else None
            )
        if expected_token is None:
            return True
        try:
            raw = await asyncio.wait_for(
                websocket.recv(),
                timeout=min(self.timeout, 10.0),
            )
            payload = json.loads(str(raw))
            token = (
                str(payload.get("token") or "")
                if isinstance(payload, dict)
                and payload.get("type") == "auth"
                else ""
            )
        except (asyncio.TimeoutError, TypeError, ValueError):
            token = ""
        if not expected_token or not token or not hmac.compare_digest(
            token,
            expected_token,
        ):
            await websocket.send(
                json.dumps(
                    {
                        "type": "auth-error",
                        "code": "PLUGIN_AUTH_FAILED",
                    }
                )
            )
            await websocket.close(code=4003, reason="plugin authentication failed")
            return False
        if expected_token:
            self._plugin_authenticated_tokens[id(websocket)] = expected_token
        await websocket.send(json.dumps({"type": "auth-ok"}))
        return True

    async def _watch_plugin_token(
        self,
        websocket: Any,
        authenticated_token: str,
    ) -> None:
        while True:
            await asyncio.sleep(self.plugin_token_recheck_seconds)
            try:
                current = (
                    self.plugin_token_provider()
                    if self.plugin_token_provider is not None
                    else self.plugin_token
                )
                normalized = (
                    str(current).strip() if current is not None else None
                )
            except Exception:  # noqa: BLE001 - config failure revokes plugin
                normalized = None
            if normalized != authenticated_token:
                try:
                    await websocket.close(
                        code=4004,
                        reason="plugin token rotated or revoked",
                    )
                finally:
                    await self.detach_plugin(
                        websocket,
                        reason="plugin token rotated or revoked",
                    )
                return

    async def detach_plugin(self, websocket: Any, *, reason: str) -> None:
        async with self.state_lock:
            if self.plugin_ws is not websocket:
                return
            self.plugin_ws = None
            self._plugin_authenticated_tokens.pop(id(websocket), None)
            watch = self._plugin_token_watch_task
            self._plugin_token_watch_task = None
            if (
                watch is not None
                and watch is not asyncio.current_task()
                and not watch.done()
            ):
                watch.cancel()
            if self._reconcile_task is not None and not self._reconcile_task.done():
                self._reconcile_task.cancel()
            for pending in self.pending.values():
                if not pending.future.done():
                    pending.future.set_exception(
                        ConnectionError(f"Figma plugin disconnected: {reason}")
                    )
            logger.info("Figma 插件已断开: %s", reason)

    async def plugin_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            logger.warning("忽略非 JSON 插件消息")
            return
        if not isinstance(payload, dict):
            logger.warning("忽略非对象插件消息")
            return
        if payload.get("type") == "auth":
            logger.debug("忽略可选模式下的插件 auth 帧")
            return
        if payload.get("type") != "response":
            logger.warning("忽略非 response 插件消息")
            return
        request_id = str(payload.get("requestId") or "")
        pending = self.pending.get(request_id)
        if pending is None and not request_id and len(self.pending) == 1:
            pending = next(iter(self.pending.values()))
        if pending is None or pending.future.done():
            logger.warning("忽略未知或过期响应 requestId=%s", request_id)
            return
        pending.future.set_result(payload)

    async def command(self, websocket: Any, message: str) -> None:
        requested_id = ""
        cache_key: tuple[str, str] | None = None
        wire_request_id = ""
        fingerprint = ""
        write_turn_acquired = False
        try:
            if not self._authorized(websocket):
                raise ProtocolError(
                    "UNAUTHORIZED",
                    "valid bearer token is required for /command",
                )
            if len(message.encode("utf-8")) > self.max_message_bytes:
                raise ProtocolError(
                    "REQUEST_TOO_LARGE",
                    f"request exceeds {self.max_message_bytes} bytes",
                )
            payload = json.loads(message)
            if not isinstance(payload, dict):
                raise ProtocolError(
                    "INVALID_COMMAND",
                    "command must be a JSON object",
                )
            action = str(payload.get("action") or "").strip()
            if not action:
                raise ProtocolError(
                    "INVALID_COMMAND",
                    "command action is required",
                )
            if len(action) > 128:
                raise ProtocolError(
                    "INVALID_COMMAND",
                    "command action exceeds 128 characters",
                )
            params = payload.get("params") or {}
            if not isinstance(params, dict):
                raise ProtocolError(
                    "INVALID_PARAMS",
                    "command params must be a JSON object",
                )
            transaction_id = self._transaction_id(action, params)
            if self._json_depth(params) > self.max_params_depth:
                raise ProtocolError(
                    "PARAMS_TOO_DEEP",
                    f"command params exceed depth {self.max_params_depth}",
                )

            requested_id = str(payload.get("requestId") or "").strip()
            client_id = str(payload.get("clientId") or "default").strip()
            if not client_id or len(client_id) > 128:
                raise ProtocolError(
                    "INVALID_CLIENT_ID",
                    "clientId must be 1..128 characters",
                )
            if len(requested_id) > 256:
                raise ProtocolError(
                    "INVALID_REQUEST_ID",
                    "requestId exceeds 256 characters",
                )
            self._require_client_identity(websocket, client_id)
            self._validate_ownership_namespace(
                action,
                params,
                client_id=client_id,
            )
            if action == "bridge_transaction_status":
                transaction_id = str(params.get("transactionId") or "").strip()
                transaction = self.transactions.get(transaction_id)
                if transaction is None:
                    raise ProtocolError(
                        "TRANSACTION_NOT_FOUND",
                        f"unknown transaction: {transaction_id}",
                    )
                if transaction.action == "apply_batch":
                    self._validate_ownership_job_value(
                        transaction_id,
                        client_id=client_id,
                    )
                await websocket.send(
                    json.dumps(
                        {
                            "type": "response",
                            "requestId": requested_id or None,
                            "result": {
                                "transaction": self._transaction_payload(transaction)
                            },
                        },
                        ensure_ascii=False,
                    )
                )
                return

            fingerprint = self._fingerprint(action, params)
            if requested_id:
                cache_key = (client_id, requested_id)
                cached = self._cached_response(cache_key)
                if cached is not None:
                    if cached.fingerprint != fingerprint:
                        raise ProtocolError(
                            "IDEMPOTENCY_KEY_CONFLICT",
                            "requestId was already used with different payload",
                        )
                    await websocket.send(
                        json.dumps(
                            cached.response,
                            ensure_ascii=False,
                        )
                    )
                    return
                if cache_key in self.scope_pending:
                    raise ProtocolError(
                        "REQUEST_IN_FLIGHT",
                        f"request already in flight: {requested_id}",
                    )
            if action in {"apply_batch", "apply_edit_batch"} and transaction_id:
                existing_transaction = self.transactions.get(transaction_id)
                if existing_transaction is not None:
                    raise ProtocolError(
                        "TRANSACTION_ID_CONFLICT",
                        (
                            "transaction id is already recorded; use its original "
                            "request id or reconcile it explicitly"
                        ),
                    )
            if len(self.pending) >= self.max_inflight:
                raise ProtocolError(
                    "BRIDGE_BACKPRESSURE",
                    f"bridge has {self.max_inflight} requests in flight",
                )

            plugin = self.plugin_ws
            if plugin is None:
                raise ProtocolError(
                    "PLUGIN_DISCONNECTED",
                    "Figma plugin is not connected",
                )
            if cache_key is not None:
                self.scope_pending.add(cache_key)
            if self._is_write_action(action):
                self._assert_writer_lease()
                await self._acquire_write_turn(client_id)
                write_turn_acquired = True

            wire_request_id = self._wire_request_id(client_id, requested_id)
            future: asyncio.Future[dict[str, Any]] = (
                asyncio.get_running_loop().create_future()
            )
            self.pending[wire_request_id] = PendingCommand(
                future=future,
                client_id=client_id,
                requested_id=requested_id,
                fingerprint=fingerprint,
            )
            if cache_key is not None:
                if self._is_write_action(action):
                    self._assert_writer_lease()
                self._record_intent(
                    cache_key,
                    fingerprint,
                    action=action,
                    transaction_id=transaction_id,
                    params=params,
                )
            outgoing = {
                "action": action,
                "params": params,
                "requestId": wire_request_id,
            }
            async with self.send_lock:
                if self.plugin_ws is not plugin:
                    raise ProtocolError(
                        "PLUGIN_CONNECTION_CHANGED",
                        "Figma plugin connection changed",
                    )
                if write_turn_acquired:
                    self._assert_writer_lease()
                if write_turn_acquired:
                    self._write_not_before = (
                        time.monotonic() + self.write_min_interval
                    )
                await plugin.send(json.dumps(outgoing, ensure_ascii=False))
            response = await asyncio.wait_for(future, timeout=self.timeout)
            normalized = self._normalize_response(
                response,
                user_request_id=requested_id or wire_request_id,
            )
            if not normalized.get("error") and cache_key is not None:
                self._store_completed(
                    cache_key,
                    fingerprint,
                    normalized,
                    action=action,
                    transaction_id=transaction_id,
                )
            await websocket.send(json.dumps(normalized, ensure_ascii=False))
        except asyncio.TimeoutError:
            if write_turn_acquired:
                self._write_degraded_reason = (
                    "previous write timed out; reconnect the Figma plugin "
                    "before issuing more writes"
                )
            error = ProtocolError(
                "PLUGIN_TIMEOUT",
                "Figma plugin response timeout; write outcome is unknown",
                outcome="unknown",
            )
            if cache_key is not None and fingerprint:
                self._store_completed(
                    cache_key,
                    fingerprint,
                    self._error_payload(
                        requested_id,
                        error,
                    ),
                    action=action,
                    transaction_id=transaction_id,
                )
            await self._send_error(
                websocket,
                requested_id or wire_request_id,
                error.code,
                error.message,
                outcome=error.outcome,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - protocol errors return to client
            logger.info("命令失败 requestId=%s: %s", requested_id, exc)
            code = exc.code if isinstance(exc, ProtocolError) else "COMMAND_FAILED"
            outcome = exc.outcome if isinstance(exc, ProtocolError) else "unknown"
            if (
                code
                in {
                    "PLUGIN_DISCONNECTED",
                    "PLUGIN_CONNECTION_CHANGED",
                }
                and cache_key is not None
                and fingerprint
            ):
                self._store_completed(
                    cache_key,
                    fingerprint,
                    self._error_payload(
                        requested_id,
                        ProtocolError(code, str(exc), outcome="unknown"),
                    ),
                    action=action,
                    transaction_id=transaction_id,
                )
            await self._send_error(
                websocket,
                requested_id or wire_request_id,
                code,
                str(exc),
                outcome=outcome,
                retry_after_ms=getattr(exc, "retry_after_ms", None),
            )
        finally:
            if write_turn_acquired:
                self._release_write_turn(client_id)
            if wire_request_id:
                self.pending.pop(wire_request_id, None)
            if cache_key is not None:
                self.scope_pending.discard(cache_key)

    @staticmethod
    def _is_write_action(action: str) -> bool:
        return action not in READ_ONLY_ACTIONS

    def _assert_writer_lease(self) -> None:
        if self._writer_lease_store is None or self.writer_lease is None:
            return
        try:
            self._writer_lease_store.assert_current(self.writer_lease)
        except WriterLeaseError as exc:
            raise ProtocolError(
                "WRITER_LEASE_REQUIRED",
                f"current writer lease is required: {exc}",
                outcome="not-applied",
            ) from exc

    async def _acquire_write_turn(self, client_id: str) -> None:
        self._raise_if_write_degraded()
        if self._write_admitted >= self.max_write_queue:
            raise ProtocolError(
                "BRIDGE_WRITE_BACKPRESSURE",
                f"write queue has {self.max_write_queue} admitted requests",
                retry_after_ms=self._write_retry_after_ms(),
            )
        limit = self._client_write_limit(client_id)
        admitted_for_client = self._client_write_admitted.get(client_id, 0)
        if admitted_for_client >= limit.max_inflight:
            raise ProtocolError(
                "BRIDGE_CLIENT_RATE_LIMITED",
                (
                    f"client {client_id!r} has {admitted_for_client} admitted "
                    f"writes; limit is {limit.max_inflight}"
                ),
                outcome="not-applied",
                retry_after_ms=self._client_retry_after_ms(limit),
            )
        self._write_admitted += 1
        self._client_write_admitted[client_id] = admitted_for_client + 1
        deadline = time.monotonic() + self.write_queue_timeout
        try:
            await self._wait_for_write_dispatch(client_id, limit, deadline)
        except BaseException:
            self._decrement_write_admission(client_id)
            raise

    async def _wait_for_write_dispatch(
        self,
        client_id: str,
        limit: ClientWriteLimitConfig,
        deadline: float,
    ) -> None:
        while True:
            self._raise_if_write_degraded()
            now = time.monotonic()
            tokens = self._refill_client_tokens(client_id, limit, now)
            if tokens < 1:
                remaining_deadline = deadline - now
                if remaining_deadline <= 0:
                    raise ProtocolError(
                        "BRIDGE_CLIENT_RATE_LIMITED",
                        f"client {client_id!r} exceeded its write rate",
                        outcome="not-applied",
                        retry_after_ms=self._client_retry_after_ms(limit),
                    )
                interval = limit.min_interval_ms / 1000
                wait = max(0.001, (1 - tokens) * interval)
                await asyncio.sleep(min(wait, remaining_deadline))
                continue
            remaining_deadline = deadline - now
            if remaining_deadline <= 0:
                raise ProtocolError(
                    "BRIDGE_WRITE_BACKPRESSURE",
                    "write dispatch wait timed out before plugin send",
                    outcome="not-applied",
                    retry_after_ms=self._write_retry_after_ms(),
                )
            try:
                await asyncio.wait_for(
                    self._write_turn_lock.acquire(),
                    timeout=remaining_deadline,
                )
            except asyncio.TimeoutError as exc:
                raise ProtocolError(
                    "BRIDGE_WRITE_BACKPRESSURE",
                    "write dispatch wait timed out before plugin send",
                    outcome="not-applied",
                    retry_after_ms=self._write_retry_after_ms(),
                ) from exc
            acquired = True
            try:
                self._raise_if_write_degraded()
                now = time.monotonic()
                tokens = self._refill_client_tokens(client_id, limit, now)
                if tokens < 1:
                    continue
                while True:
                    remaining = self._write_not_before - time.monotonic()
                    if remaining <= 0:
                        break
                    await asyncio.sleep(remaining)
                self._client_write_tokens[client_id] = tokens - 1
                self._write_not_before = (
                    time.monotonic() + self.write_min_interval
                )
                acquired = False
                return
            finally:
                if acquired:
                    self._write_turn_lock.release()

    def _release_write_turn(self, client_id: str) -> None:
        self._write_turn_lock.release()
        self._decrement_write_admission(client_id)

    def _decrement_write_admission(self, client_id: str) -> None:
        self._write_admitted -= 1
        remaining = self._client_write_admitted.get(client_id, 1) - 1
        if remaining > 0:
            self._client_write_admitted[client_id] = remaining
        else:
            self._client_write_admitted.pop(client_id, None)

    def _client_write_limit(self, client_id: str) -> ClientWriteLimitConfig:
        return self.client_write_limits.get(
            client_id,
            self.client_write_defaults,
        )

    def _refill_client_tokens(
        self,
        client_id: str,
        limit: ClientWriteLimitConfig,
        now: float,
    ) -> float:
        last = self._client_write_refilled_at.get(client_id, now)
        capacity = float(limit.burst)
        tokens = self._client_write_tokens.get(client_id, capacity)
        if limit.min_interval_ms > 0:
            elapsed = max(0.0, now - last)
            tokens = min(
                capacity,
                tokens + (elapsed * 1000 / limit.min_interval_ms),
            )
        else:
            tokens = capacity
        self._client_write_tokens[client_id] = tokens
        self._client_write_refilled_at[client_id] = now
        return tokens

    @staticmethod
    def _client_retry_after_ms(limit: ClientWriteLimitConfig) -> int:
        if limit.min_interval_ms <= 0:
            return 10
        return max(1, math.ceil(limit.min_interval_ms))

    @staticmethod
    def _validate_client_write_limit(limit: ClientWriteLimitConfig) -> None:
        if limit.max_inflight <= 0:
            raise ValueError("client max_inflight must be positive")
        if limit.burst <= 0:
            raise ValueError("client burst must be positive")
        if limit.min_interval_ms < 0:
            raise ValueError("client min_interval_ms must be non-negative")

    def _raise_if_write_degraded(self) -> None:
        if self._write_degraded_reason is None:
            return
        raise ProtocolError(
            "BRIDGE_WRITE_BACKPRESSURE",
            self._write_degraded_reason,
            outcome="not-applied",
            retry_after_ms=self._write_retry_after_ms(),
        )

    def _write_retry_after_ms(self) -> int:
        return max(10, math.ceil(self.write_min_interval * 1000))

    def _authorized(self, websocket: Any) -> bool:
        if self.auth_token is None:
            return True
        request = getattr(websocket, "request", None)
        headers = getattr(request, "headers", None)
        if headers is None:
            return False
        authorization = str(headers.get("Authorization") or "")
        expected = f"Bearer {self.auth_token}"
        return hmac.compare_digest(authorization, expected)

    def _require_client_identity(self, websocket: Any, client_id: str) -> None:
        if not self.client_tokens:
            return
        request = getattr(websocket, "request", None)
        headers = getattr(request, "headers", None)
        if headers is None:
            raise ProtocolError(
                "CLIENT_IDENTITY_REQUIRED",
                "server-side client identity headers are required",
            )
        header_client_id = str(headers.get(CLIENT_ID_HEADER) or "").strip()
        token = str(headers.get(CLIENT_TOKEN_HEADER) or "")
        if not header_client_id or not token:
            raise ProtocolError(
                "CLIENT_IDENTITY_REQUIRED",
                "server-side client identity headers are required",
            )
        if header_client_id != client_id:
            raise ProtocolError(
                "CLIENT_IDENTITY_MISMATCH",
                "client identity header does not match command clientId",
            )
        expected = self.client_tokens.get(client_id, "")
        if not expected or not hmac.compare_digest(token, expected):
            raise ProtocolError(
                "CLIENT_IDENTITY_INVALID",
                "client identity token is invalid",
            )

    def _cached_response(
        self,
        cache_key: tuple[str, str],
    ) -> CompletedResponse | None:
        cached = self.completed.get(cache_key)
        if cached is None:
            return None
        if time.time() - cached.completed_at <= self.idempotency_ttl:
            return cached
        self.completed.pop(cache_key, None)
        return None

    def _store_completed(
        self,
        cache_key: tuple[str, str],
        fingerprint: str,
        response: dict[str, Any],
        *,
        action: str = "",
        transaction_id: str = "",
    ) -> None:
        now = time.time()
        self._evict_completed(now)
        completed = CompletedResponse(
            completed_at=now,
            fingerprint=fingerprint,
            response=response,
            action=action,
            transaction_id=transaction_id,
        )
        self._append_journal_event(self._terminal_event(cache_key, completed))
        self.completed[cache_key] = completed
        self._journal_intents.pop(cache_key, None)
        if transaction_id:
            previous = self.transactions.get(transaction_id)
            self.transactions[transaction_id] = TransactionRecord(
                client_id=cache_key[0],
                requested_id=cache_key[1],
                transaction_id=transaction_id,
                state=self._transaction_state(action, response),
                fingerprint=fingerprint,
                action=action,
                updated_at=now,
                response=response,
                reconciliation_targets=(
                    previous.reconciliation_targets if previous is not None else ()
                ),
                expected_checks=(
                    previous.expected_checks if previous is not None else ()
                ),
                ownership_job_id=(
                    previous.ownership_job_id if previous is not None else ""
                ),
                expected_created_nodes=(
                    previous.expected_created_nodes
                    if previous is not None
                    else 0
                ),
                ownership_readback=(
                    previous.ownership_readback
                    if previous is not None
                    else None
                ),
                ownership_reconciliation=(
                    previous.ownership_reconciliation
                    if previous is not None
                    else None
                ),
                ownership_readback_at=(
                    previous.ownership_readback_at
                    if previous is not None
                    else None
                ),
                reconciliation=(
                    previous.reconciliation if previous is not None else None
                ),
                readback=previous.readback if previous is not None else None,
                readback_at=previous.readback_at if previous is not None else None,
            )
        self._evict_completed(now)
        self._maybe_compact_journal()

    def _record_intent(
        self,
        cache_key: tuple[str, str],
        fingerprint: str,
        *,
        action: str,
        transaction_id: str,
        params: dict[str, Any],
    ) -> None:
        now = time.time()
        reconciliation_targets = self._reconciliation_targets(action, params)
        expected_checks = self._expected_checks(action, params)
        ownership_job_id = self._ownership_job_id(action, params)
        expected_created_nodes = self._expected_created_nodes(action, params)
        event = {
            "version": 1,
            "event": "intent",
            "clientId": cache_key[0],
            "requestId": cache_key[1],
            "fingerprint": fingerprint,
            "action": action,
            "transactionId": transaction_id,
            "reconciliationTargets": list(reconciliation_targets),
            "expectedChecks": list(expected_checks),
            "ownershipJobId": ownership_job_id,
            "expectedCreatedNodes": expected_created_nodes,
            "recordedAt": now,
        }
        self._append_journal_event(event)
        if self.journal_path is not None:
            self._journal_intents[cache_key] = event
        if transaction_id:
            self.transactions[transaction_id] = TransactionRecord(
                client_id=cache_key[0],
                requested_id=cache_key[1],
                transaction_id=transaction_id,
                state="inflight",
                fingerprint=fingerprint,
                action=action,
                updated_at=now,
                reconciliation_targets=reconciliation_targets,
                expected_checks=expected_checks,
                ownership_job_id=ownership_job_id,
                expected_created_nodes=expected_created_nodes,
            )

    def _terminal_event(
        self,
        cache_key: tuple[str, str],
        completed: CompletedResponse,
    ) -> dict[str, Any]:
        previous = (
            self.transactions.get(completed.transaction_id)
            if completed.transaction_id
            else None
        )
        return {
            "version": 1,
            "event": "terminal",
            "clientId": cache_key[0],
            "requestId": cache_key[1],
            "fingerprint": completed.fingerprint,
            "action": completed.action,
            "transactionId": completed.transaction_id,
            "reconciliationTargets": (
                list(previous.reconciliation_targets) if previous is not None else []
            ),
            "expectedChecks": (
                list(previous.expected_checks) if previous is not None else []
            ),
            "ownershipJobId": (
                previous.ownership_job_id if previous is not None else ""
            ),
            "expectedCreatedNodes": (
                previous.expected_created_nodes if previous is not None else 0
            ),
            "ownershipReconciliation": (
                previous.ownership_reconciliation
                if previous is not None
                else None
            ),
            "reconciliation": (
                previous.reconciliation if previous is not None else None
            ),
            "recordedAt": completed.completed_at,
            "transactionState": (
                self._transaction_state(
                    completed.action,
                    completed.response,
                )
                if completed.transaction_id
                else ""
            ),
            "response": completed.response,
        }

    def _append_journal_event(self, event: dict[str, Any]) -> None:
        if self.journal_path is None:
            return
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.journal_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._journal_event_count += 1

    def _load_journal(self) -> None:
        if self.journal_path is None or not self.journal_path.exists():
            return
        latest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        latest_by_transaction: dict[str, dict[str, Any]] = {}
        try:
            with self.journal_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    self._journal_event_count += 1
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except (TypeError, ValueError):
                        logger.warning("忽略损坏的 bridge journal 行")
                        continue
                    if (
                        not isinstance(event, dict)
                        or event.get("version") != 1
                        or event.get("event") not in {"intent", "terminal", "readback"}
                    ):
                        logger.warning("忽略不支持的 bridge journal 记录")
                        continue
                    client_id = str(event.get("clientId") or "")
                    requested_id = str(event.get("requestId") or "")
                    if not client_id or not requested_id:
                        logger.warning("忽略缺少幂等键的 bridge journal 记录")
                        continue
                    if event.get("action") == "apply_batch":
                        ownership_job_id = str(
                            event.get("ownershipJobId")
                            or event.get("transactionId")
                            or ""
                        )
                        try:
                            self._validate_ownership_job_value(
                                ownership_job_id,
                                client_id=client_id,
                            )
                        except ProtocolError as exc:
                            logger.warning(
                                "忽略 ownership namespace 无效的 journal 记录: %s",
                                exc,
                            )
                            continue
                    key = (client_id, requested_id)
                    if event.get("event") != "readback":
                        latest_by_key[key] = event
                    transaction_id = str(event.get("transactionId") or "")
                    if transaction_id:
                        latest_by_transaction[transaction_id] = event
        except OSError as exc:
            raise RuntimeError(
                f"cannot read bridge journal {self.journal_path}: {exc}"
            ) from exc

        now = time.time()
        for key, event in latest_by_key.items():
            fingerprint = str(event.get("fingerprint") or "")
            action = str(event.get("action") or "")
            transaction_id = str(event.get("transactionId") or "")
            recorded_at = float(event.get("recordedAt") or 0)
            if event.get("event") == "intent":
                if fingerprint:
                    self.completed[key] = CompletedResponse(
                        completed_at=recorded_at,
                        fingerprint=fingerprint,
                        response=self._recovered_unknown_payload(key[1]),
                        action=action,
                        transaction_id=transaction_id,
                    )
                continue
            response = event.get("response")
            if not isinstance(response, dict) or not fingerprint:
                logger.warning("忽略缺少 terminal payload 的 bridge journal 记录")
                continue
            if now - recorded_at <= self.idempotency_ttl:
                self.completed[key] = CompletedResponse(
                    completed_at=recorded_at,
                    fingerprint=fingerprint,
                    response=response,
                    action=action,
                    transaction_id=transaction_id,
                )

        for transaction_id, event in latest_by_transaction.items():
            client_id = str(event.get("clientId") or "")
            requested_id = str(event.get("requestId") or "")
            action = str(event.get("action") or "")
            fingerprint = str(event.get("fingerprint") or "")
            targets = event.get("reconciliationTargets")
            reconciliation_targets = tuple(
                str(target) for target in targets or [] if str(target)
            )
            raw_expected_checks = event.get("expectedChecks")
            expected_checks = tuple(
                dict(check)
                for check in raw_expected_checks or []
                if isinstance(check, dict)
            )
            ownership_job_id = str(event.get("ownershipJobId") or "")
            expected_created_nodes = int(event.get("expectedCreatedNodes") or 0)
            reconciliation = None
            readback = None
            readback_at = None
            ownership_readback = None
            ownership_reconciliation = None
            ownership_readback_at = None
            if event.get("event") == "readback":
                state = str(event.get("state") or "unknown")
                response = None
                raw_readback = event.get("readback")
                readback = raw_readback if isinstance(raw_readback, dict) else None
                raw_reconciliation = event.get("reconciliation")
                reconciliation = (
                    raw_reconciliation if isinstance(raw_reconciliation, dict) else None
                )
                readback_at = float(event.get("recordedAt") or 0)
                raw_ownership_readback = event.get("ownershipReadback")
                ownership_readback = (
                    raw_ownership_readback
                    if isinstance(raw_ownership_readback, dict)
                    else None
                )
                raw_ownership_reconciliation = event.get(
                    "ownershipReconciliation"
                )
                ownership_reconciliation = (
                    raw_ownership_reconciliation
                    if isinstance(raw_ownership_reconciliation, dict)
                    else None
                )
                if ownership_readback is not None:
                    ownership_readback_at = readback_at
            elif event.get("event") == "intent":
                state = "unknown"
                response = self._recovered_unknown_payload(requested_id)
            else:
                response = event.get("response")
                if not isinstance(response, dict):
                    response = None
                state = str(
                    event.get("transactionState")
                    or self._transaction_state(action, response or {})
                )
            self.transactions[transaction_id] = TransactionRecord(
                client_id=client_id,
                requested_id=requested_id,
                transaction_id=transaction_id,
                state=state,
                fingerprint=fingerprint,
                action=action,
                updated_at=float(event.get("recordedAt") or 0),
                response=response,
                recovered=True,
                reconciliation_targets=reconciliation_targets,
                expected_checks=expected_checks,
                ownership_job_id=ownership_job_id,
                expected_created_nodes=expected_created_nodes,
                ownership_readback=ownership_readback,
                ownership_reconciliation=ownership_reconciliation,
                ownership_readback_at=ownership_readback_at,
                reconciliation=reconciliation,
                readback=readback,
                readback_at=readback_at,
            )
        self._evict_completed(now)
        logger.info(
            "bridge journal loaded: events=%s completed=%s transactions=%s path=%s",
            self._journal_event_count,
            len(self.completed),
            len(self.transactions),
            self.journal_path,
        )

    @staticmethod
    def _recovered_unknown_payload(request_id: str) -> dict[str, Any]:
        return {
            "type": "response",
            "requestId": request_id,
            "error": ("REQUEST_OUTCOME_UNKNOWN: bridge restarted before completion"),
            "code": "REQUEST_OUTCOME_UNKNOWN",
            "outcome": "unknown",
            "recoveredAfterRestart": True,
        }

    @staticmethod
    def _transaction_id(action: str, params: dict[str, Any]) -> str:
        if action not in {"apply_batch", "apply_edit_batch"}:
            return ""
        return str(params.get("transactionId") or "").strip()

    @staticmethod
    def _ownership_job_id(action: str, params: dict[str, Any]) -> str:
        if action != "apply_batch":
            return ""
        return str(params.get("transactionId") or "").strip()

    def _validate_ownership_namespace(
        self,
        action: str,
        params: dict[str, Any],
        *,
        client_id: str,
    ) -> None:
        if action == "apply_batch":
            value = str(params.get("transactionId") or "").strip()
        elif action in {"cleanup_owned_job", "ownership_report"}:
            value = str(params.get("jobId") or "").strip()
        else:
            return
        self._validate_ownership_job_value(value, client_id=client_id)

    def _validate_ownership_job_value(
        self,
        value: str,
        *,
        client_id: str,
    ) -> None:
        normalized = str(value or "").strip()
        if not normalized:
            raise ProtocolError(
                "INVALID_JOB_NAMESPACE",
                "ownership job id is required",
            )
        if not normalized.startswith(JOB_NAMESPACE_PREFIX):
            if self.allow_legacy_job_ids and not normalized.startswith("r5job:"):
                return
            raise ProtocolError(
                "INVALID_JOB_NAMESPACE",
                "ownership job id must use r5job:v1:<client>:<raw>",
            )
        try:
            parsed = parse_job_namespace(normalized)
        except JobNamespaceError as exc:
            raise ProtocolError(
                "INVALID_JOB_NAMESPACE",
                str(exc),
            ) from exc
        if parsed.client_id != str(client_id or "").strip():
            raise ProtocolError(
                "JOB_NAMESPACE_CLIENT_MISMATCH",
                "ownership job id belongs to a different client",
            )

    @staticmethod
    def _expected_created_nodes(action: str, params: dict[str, Any]) -> int:
        if action != "apply_batch":
            return 0
        actions = params.get("actions")
        if not isinstance(actions, list):
            return 0
        create_actions = {
            "create_frame",
            "create_rectangle",
            "create_ellipse",
            "create_text",
            "create_image",
        }
        return sum(
            1
            for item in actions
            if isinstance(item, dict)
            and str(item.get("action") or "") in create_actions
        )

    def _transaction_payload(
        self,
        transaction: TransactionRecord,
    ) -> dict[str, Any]:
        try:
            attribution = self.attribution_provider.resolve(transaction)
            if not isinstance(attribution, AttributionEvidence):
                raise TypeError("attribution provider returned an invalid result")
        except Exception as exc:  # noqa: BLE001 - attribution is fail-closed
            attribution = AttributionEvidence(
                status="unavailable",
                actor="unknown",
                revision="unknown",
                source="attribution-provider",
                reason=f"attribution provider failed: {exc}",
            )
        return {
            "transactionId": transaction.transaction_id,
            "state": transaction.state,
            "action": transaction.action,
            "clientId": transaction.client_id,
            "requestId": transaction.requested_id,
            "fingerprint": transaction.fingerprint,
            "reconciliationTargets": list(transaction.reconciliation_targets),
            "expectedChecks": list(transaction.expected_checks),
            "ownershipJobId": transaction.ownership_job_id,
            "expectedCreatedNodes": transaction.expected_created_nodes,
            "ownershipReadback": transaction.ownership_readback,
            "ownershipReconciliation": transaction.ownership_reconciliation,
            "ownershipReadbackAt": transaction.ownership_readback_at,
            "reconciliation": transaction.reconciliation,
            "readback": transaction.readback,
            "readbackAt": transaction.readback_at,
            "recovered": transaction.recovered,
            "attribution": attribution.to_dict(),
        }

    @staticmethod
    def _reconciliation_targets(
        action: str,
        params: dict[str, Any],
    ) -> tuple[str, ...]:
        if action != "apply_edit_batch":
            return ()
        targets: list[str] = []
        actions = params.get("actions")
        if not isinstance(actions, list):
            return ()
        for item in actions:
            if not isinstance(item, dict):
                continue
            item_params = item.get("params")
            if not isinstance(item_params, dict):
                continue
            node_id = str(item_params.get("nodeId") or "").strip()
            if node_id and node_id not in targets:
                targets.append(node_id)
            children = item_params.get("children")
            if isinstance(children, list):
                for child in children:
                    if not isinstance(child, dict):
                        continue
                    child_id = str(child.get("childId") or "").strip()
                    if child_id and child_id not in targets:
                        targets.append(child_id)
        return tuple(targets)

    @staticmethod
    def _expected_checks(
        action: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        if action != "apply_edit_batch":
            return ()
        checks: list[dict[str, Any]] = []
        actions = params.get("actions")
        if not isinstance(actions, list):
            return ()
        for item in actions:
            if not isinstance(item, dict):
                continue
            item_action = str(item.get("action") or "")
            item_params = item.get("params")
            if not isinstance(item_params, dict):
                continue
            node_id = str(item_params.get("nodeId") or "").strip()
            if not node_id:
                continue
            if item_action == "set_text" and isinstance(
                item_params.get("text"),
                str,
            ):
                checks.append(
                    {
                        "nodeId": node_id,
                        "action": item_action,
                        "property": "characters",
                        "expectedSha256": BridgeHub._sha256_text(item_params["text"]),
                        "regionId": str(item_params.get("regionId") or ""),
                    }
                )
            elif item_action == "set_name" and isinstance(
                item_params.get("name"),
                str,
            ):
                checks.append(
                    {
                        "nodeId": node_id,
                        "action": item_action,
                        "property": "name",
                        "expectedSha256": BridgeHub._sha256_text(item_params["name"]),
                        "regionId": str(item_params.get("regionId") or ""),
                    }
                )
            elif item_action in {"set_visible", "set_visibility"} and isinstance(
                item_params.get("visible"),
                bool,
            ):
                checks.append(
                    {
                        "nodeId": node_id,
                        "action": item_action,
                        "property": "visible",
                        "expectedValue": item_params["visible"],
                        "regionId": str(item_params.get("regionId") or ""),
                    }
                )
            if item_action == "replace_image_fill" and isinstance(
                item_params.get("imageBase64"),
                str,
            ):
                try:
                    payload = base64.b64decode(
                        item_params["imageBase64"],
                        validate=True,
                    )
                except (ValueError, TypeError):
                    payload = b""
                checks.append(
                    {
                        "nodeId": node_id,
                        "action": item_action,
                        "property": "imageFillSha256",
                        "expectedSha256": hashlib.sha256(payload).hexdigest(),
                        "fillIndex": int(item_params.get("fillIndex", 0)),
                        "regionId": str(item_params.get("regionId") or ""),
                    }
                )
            if item_action in {"set_layout_flow", "set_autolayout"}:
                layout = item_params.get("layout")
                if isinstance(layout, dict):
                    checks.append(
                        {
                            "nodeId": node_id,
                            "action": item_action,
                            "property": "layoutSnapshot",
                            "expectedValue": BridgeHub._expected_layout_snapshot(
                                layout
                            ),
                            "regionId": str(
                                item_params.get("regionId") or ""
                            ),
                        }
                    )
            bounds = {
                key: item_params.get(key)
                for key in ("x", "y", "width", "height")
                if isinstance(item_params.get(key), (int, float))
            }
            if len(bounds) == 4:
                checks.append(
                    {
                        "nodeId": node_id,
                        "action": item_action,
                        "property": "bounds",
                        "expectedValue": bounds,
                        "regionId": str(item_params.get("regionId") or ""),
                    }
                )
            if item_action in {"set_text_runs", "set_text"} and isinstance(
                item_params.get("textRuns"),
                list,
            ):
                checks.append(
                    {
                        "nodeId": node_id,
                        "action": item_action,
                        "property": "textRuns",
                        "expectedValue": item_params["textRuns"],
                        "regionId": str(item_params.get("regionId") or ""),
                    }
                )
            if item_action == "set_bounds" and item_params.get("regionId"):
                checks.append(
                    {
                        "nodeId": node_id,
                        "action": item_action,
                        "property": "regionMembership",
                        "expectedValue": {
                            "regionId": str(item_params["regionId"]),
                            "member": True,
                        },
                        "regionId": str(item_params["regionId"]),
                    }
                )
        return tuple(checks)

    @staticmethod
    def _expected_layout_snapshot(layout: dict[str, Any]) -> dict[str, Any]:
        aliases = {
            "mode": "layoutMode",
            "wrap": "layoutWrap",
            "primaryAlign": "primaryAxisAlignItems",
            "counterAlign": "counterAxisAlignItems",
        }
        return {
            aliases.get(name, name): value
            for name, value in layout.items()
        }

    @staticmethod
    def _sha256_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _evaluate_expected_checks(
        self,
        expected_checks: tuple[dict[str, Any], ...],
        readback: dict[str, Any],
    ) -> dict[str, Any]:
        results = []
        matched = 0
        mismatched = 0
        unknown = 0
        for check in expected_checks:
            node_id = str(check.get("nodeId") or "")
            property_name = str(check.get("property") or "")
            node = readback.get(node_id)
            result = {
                "nodeId": node_id,
                "action": check.get("action"),
                "property": property_name,
            }
            if not isinstance(node, dict) or node.get("error"):
                result["status"] = "unknown"
                unknown += 1
                results.append(result)
                continue
            if property_name not in node:
                result["status"] = "unknown"
                unknown += 1
                results.append(result)
                continue
            actual = node.get(property_name)
            if "expectedSha256" in check:
                if property_name == "imageFillSha256":
                    fill_index = str(check.get("fillIndex", 0))
                    if isinstance(actual, dict):
                        actual = actual.get(fill_index)
                    elif fill_index != "0":
                        actual = None
                if not isinstance(actual, str):
                    result["status"] = "unknown"
                    unknown += 1
                    results.append(result)
                    continue
                actual_hash = (
                    actual
                    if property_name == "imageFillSha256"
                    else self._sha256_text(actual)
                )
                is_match = hmac.compare_digest(
                    actual_hash,
                    str(check["expectedSha256"]),
                )
                result["actualSha256"] = actual_hash
                result["expectedSha256"] = check["expectedSha256"]
            else:
                is_match = self._expected_value_matches(
                    property_name,
                    check.get("expectedValue"),
                    actual,
                )
                result["actualValue"] = actual
                result["expectedValue"] = check.get("expectedValue")
            region_id = str(check.get("regionId") or "")
            if region_id:
                result["regionId"] = region_id
            result["status"] = "matched" if is_match else "mismatched"
            if is_match:
                matched += 1
            else:
                mismatched += 1
            results.append(result)

        classification = self._expected_classification(
            matched,
            mismatched,
            unknown,
            len(expected_checks),
        )
        regions: dict[str, dict[str, Any]] = {}
        for result in results:
            region_id = str(result.get("regionId") or "")
            if not region_id:
                continue
            region = regions.setdefault(
                region_id,
                {"matched": 0, "mismatched": 0, "unknown": 0},
            )
            status = result["status"]
            if status in region:
                region[status] += 1
        for region_id, counts in regions.items():
            counts["classification"] = self._expected_classification(
                counts["matched"],
                counts["mismatched"],
                counts["unknown"],
                counts["matched"] + counts["mismatched"] + counts["unknown"],
            )
        return {
            "classification": classification,
            "matched": matched,
            "mismatched": mismatched,
            "unknown": unknown,
            "checks": results,
            "regions": regions,
        }

    @staticmethod
    def _expected_value_matches(property_name: str, expected: Any, actual: Any) -> bool:
        if property_name == "layoutSnapshot" and isinstance(expected, dict):
            return isinstance(actual, dict) and all(
                actual.get(name) == value for name, value in expected.items()
            )
        if property_name == "textRuns" and isinstance(expected, list):
            if not isinstance(actual, list) or len(actual) != len(expected):
                return False
            for expected_run, actual_run in zip(expected, actual, strict=True):
                if isinstance(expected_run, dict):
                    if not isinstance(actual_run, dict) or not all(
                        actual_run.get(name) == value
                        for name, value in expected_run.items()
                    ):
                        return False
                elif expected_run != actual_run:
                    return False
            return True
        if property_name == "regionMembership" and isinstance(expected, dict):
            return isinstance(actual, dict) and all(
                actual.get(name) == value for name, value in expected.items()
            )
        return actual == expected

    @staticmethod
    def _expected_classification(
        matched: int,
        mismatched: int,
        unknown: int,
        total: int,
    ) -> str:
        if total == 0:
            return "indeterminate"
        if matched == total:
            return "matches-intended"
        if matched > 0:
            return "partial-match"
        if mismatched > 0:
            return "does-not-match-intended"
        return "indeterminate"

    @staticmethod
    def _evaluate_ownership_readback(
        expected_created_nodes: int,
        readback: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(readback, dict):
            return {
                "classification": "indeterminate",
                "expected": expected_created_nodes,
                "matched": 0,
                "reason": "ownership readback is unavailable",
            }
        raw_matched = readback.get("matched", 0)
        try:
            matched = max(0, int(raw_matched))
        except (TypeError, ValueError):
            matched = 0
        if readback.get("status") != "reported" or expected_created_nodes <= 0:
            classification = "indeterminate"
        elif matched == expected_created_nodes:
            classification = "matches-intended"
        elif matched == 0:
            classification = "does-not-match-intended"
        elif matched < expected_created_nodes:
            classification = "partial-match"
        else:
            classification = "indeterminate"
        return {
            "classification": classification,
            "expected": expected_created_nodes,
            "matched": matched,
            "jobId": readback.get("jobId"),
            "owner": readback.get("owner"),
        }

    async def _reconcile_unknown_transactions(self) -> None:
        candidates = [
            transaction
            for transaction in self.transactions.values()
            if transaction.state == "unknown"
            and (
                (
                    transaction.reconciliation_targets
                    and transaction.readback is None
                )
                or (
                    transaction.ownership_job_id
                    and transaction.ownership_readback is None
                )
            )
        ]
        for transaction in candidates:
            if self.plugin_ws is None:
                return
            readback = transaction.readback
            reconciliation = transaction.reconciliation
            if (
                transaction.reconciliation_targets
                and readback is None
            ):
                readback = {}
                for node_id in transaction.reconciliation_targets:
                    try:
                        result = await self._plugin_read_node_tree(
                            node_id,
                            expected_checks=transaction.expected_checks,
                        )
                        readback[node_id] = (
                            result
                            if isinstance(result, dict)
                            else {"error": "READBACK_RESULT_NOT_OBJECT"}
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        readback[node_id] = {
                            "error": str(exc),
                            "code": getattr(exc, "code", "READBACK_FAILED"),
                        }
                reconciliation = self._evaluate_expected_checks(
                    transaction.expected_checks,
                    readback,
                )
            ownership_readback = transaction.ownership_readback
            ownership_reconciliation = transaction.ownership_reconciliation
            if (
                transaction.ownership_job_id
                and ownership_readback is None
            ):
                try:
                    ownership_readback = await self._plugin_call(
                        "ownership_report",
                        {"jobId": transaction.ownership_job_id},
                    )
                    if not isinstance(ownership_readback, dict):
                        ownership_readback = {
                            "status": "error",
                            "error": "OWNERSHIP_READBACK_RESULT_NOT_OBJECT",
                        }
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    ownership_readback = {
                        "status": "error",
                        "error": str(exc),
                        "code": getattr(exc, "code", "READBACK_FAILED"),
                    }
                ownership_reconciliation = self._evaluate_ownership_readback(
                    transaction.expected_created_nodes,
                    ownership_readback,
                )
            now = time.time()
            event = {
                "version": 1,
                "event": "readback",
                "clientId": transaction.client_id,
                "requestId": transaction.requested_id,
                "fingerprint": transaction.fingerprint,
                "action": transaction.action,
                "transactionId": transaction.transaction_id,
                "state": transaction.state,
                "reconciliationTargets": list(transaction.reconciliation_targets),
                "expectedChecks": list(transaction.expected_checks),
                "readback": readback,
                "reconciliation": reconciliation,
                "ownershipJobId": transaction.ownership_job_id,
                "expectedCreatedNodes": transaction.expected_created_nodes,
                "ownershipReadback": ownership_readback,
                "ownershipReconciliation": ownership_reconciliation,
                "recordedAt": now,
            }
            try:
                self._append_journal_event(event)
            except OSError as exc:
                logger.error("transaction readback journal append failed: %s", exc)
                return
            self.transactions[transaction.transaction_id] = replace(
                transaction,
                readback=readback,
                reconciliation=reconciliation,
                readback_at=(
                    now
                    if readback is not None
                    and transaction.readback is None
                    else transaction.readback_at
                ),
                ownership_readback=ownership_readback,
                ownership_reconciliation=ownership_reconciliation,
                ownership_readback_at=(
                    now
                    if ownership_readback is not None
                    and transaction.ownership_readback is None
                    else transaction.ownership_readback_at
                ),
            )
            self._maybe_compact_journal()

    async def _plugin_read_node_tree(
        self,
        node_id: str,
        *,
        expected_checks: tuple[dict[str, Any], ...] = (),
    ) -> Any:
        result = await self._plugin_call(
            "get_node_tree",
            {"nodeId": node_id, "depth": 3},
        )
        needs_image_bytes = any(
            str(check.get("nodeId") or "") == node_id
            and check.get("property") == "imageFillSha256"
            for check in expected_checks
        )
        if not needs_image_bytes or not isinstance(result, dict):
            return result
        try:
            report = await self._plugin_call(
                "image_fill_report",
                {"nodeId": node_id},
            )
            hashes = self._image_fill_hashes(report, node_id)
        except Exception as exc:  # noqa: BLE001 - expected state stays unknown
            result["imageFillReadbackError"] = str(exc)
            return result
        if hashes:
            result["imageFillSha256"] = hashes
        return result

    @staticmethod
    def _image_fill_hashes(report: Any, node_id: str) -> dict[str, str]:
        if not isinstance(report, dict):
            return {}
        hashes: dict[str, str] = {}
        for fill in report.get("fills") or ():
            if not isinstance(fill, dict):
                continue
            if str(fill.get("nodeId") or "") != node_id:
                continue
            encoded = fill.get("byteBase64")
            if not isinstance(encoded, str) or not encoded:
                continue
            try:
                payload = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                continue
            fill_index = str(fill.get("fillIndex", 0))
            hashes[fill_index] = hashlib.sha256(payload).hexdigest()
        return hashes

    async def _plugin_call(
        self,
        action: str,
        params: dict[str, Any],
    ) -> Any:
        plugin = self.plugin_ws
        if plugin is None:
            raise ProtocolError(
                "PLUGIN_DISCONNECTED",
                "Figma plugin is not connected",
            )
        if len(self.pending) >= self.max_inflight:
            raise ProtocolError(
                "BRIDGE_BACKPRESSURE",
                f"bridge has {self.max_inflight} requests in flight",
            )
        wire_request_id = f"__bridge__:{uuid.uuid4().hex}"
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self.pending[wire_request_id] = PendingCommand(
            future=future,
            client_id="__bridge__",
            requested_id="",
            fingerprint="",
        )
        try:
            outgoing = {
                "action": action,
                "params": params,
                "requestId": wire_request_id,
            }
            async with self.send_lock:
                if self.plugin_ws is not plugin:
                    raise ProtocolError(
                        "PLUGIN_CONNECTION_CHANGED",
                        "Figma plugin connection changed",
                    )
                await plugin.send(json.dumps(outgoing, ensure_ascii=False))
            response = await asyncio.wait_for(future, timeout=self.timeout)
            if response.get("error"):
                raise RuntimeError(str(response["error"]))
            return response.get("result")
        finally:
            self.pending.pop(wire_request_id, None)

    @staticmethod
    def _transaction_state(
        action: str,
        response: dict[str, Any],
    ) -> str:
        if response.get("outcome") == "unknown" or response.get("code") in {
            "PLUGIN_TIMEOUT",
            "PLUGIN_DISCONNECTED",
            "PLUGIN_CONNECTION_CHANGED",
            "REQUEST_OUTCOME_UNKNOWN",
        }:
            return "unknown"
        result = response.get("result")
        if isinstance(result, dict):
            status = str(result.get("status") or "")
            if status in {
                "committed",
                "rejected",
                "rolled-back",
                "rollback-incomplete",
            }:
                return status
        if response.get("error"):
            return "rejected"
        if action in {"apply_batch", "apply_edit_batch"}:
            return "committed"
        return "completed"

    def _maybe_compact_journal(self) -> None:
        if (
            self.journal_path is None
            or self._journal_event_count <= self.max_journal_events
        ):
            return
        try:
            self._compact_journal()
        except OSError as exc:
            logger.error("bridge journal compaction failed: %s", exc)

    def _compact_journal(self) -> None:
        if self.journal_path is None:
            return
        events = list(self._journal_intents.values())
        represented_transactions: set[str] = set()
        for key, completed in sorted(
            self.completed.items(),
            key=lambda item: item[1].completed_at,
        ):
            events.append(self._terminal_event(key, completed))
            if completed.transaction_id:
                represented_transactions.add(completed.transaction_id)
        for transaction_id, transaction in sorted(
            self.transactions.items(),
            key=lambda item: item[1].updated_at,
        ):
            if (
                transaction_id not in represented_transactions
                and transaction.state != "inflight"
            ):
                events.append(
                    {
                        "version": 1,
                        "event": "terminal",
                        "clientId": transaction.client_id,
                        "requestId": transaction.requested_id,
                        "fingerprint": transaction.fingerprint,
                        "action": transaction.action,
                        "transactionId": transaction.transaction_id,
                        "reconciliationTargets": list(
                            transaction.reconciliation_targets
                        ),
                        "expectedChecks": list(transaction.expected_checks),
                        "ownershipJobId": transaction.ownership_job_id,
                        "expectedCreatedNodes": transaction.expected_created_nodes,
                        "ownershipReconciliation": (
                            transaction.ownership_reconciliation
                        ),
                        "reconciliation": transaction.reconciliation,
                        "recordedAt": transaction.updated_at,
                        "transactionState": transaction.state,
                        "response": transaction.response
                        or self._recovered_unknown_payload(
                            transaction.requested_id,
                        ),
                    }
                )
            if (
                transaction.readback is not None
                or transaction.ownership_readback is not None
            ):
                events.append(
                    {
                        "version": 1,
                        "event": "readback",
                        "clientId": transaction.client_id,
                        "requestId": transaction.requested_id,
                        "fingerprint": transaction.fingerprint,
                        "action": transaction.action,
                        "transactionId": transaction.transaction_id,
                        "state": transaction.state,
                        "reconciliationTargets": list(
                            transaction.reconciliation_targets
                        ),
                        "expectedChecks": list(transaction.expected_checks),
                        "ownershipJobId": transaction.ownership_job_id,
                        "expectedCreatedNodes": transaction.expected_created_nodes,
                        "readback": transaction.readback,
                        "reconciliation": transaction.reconciliation,
                        "ownershipReadback": transaction.ownership_readback,
                        "ownershipReconciliation": (
                            transaction.ownership_reconciliation
                        ),
                        "recordedAt": (
                            transaction.ownership_readback_at
                            or transaction.readback_at
                            or transaction.updated_at
                        ),
                    }
                )

        protected = [
            event for event in events if self._journal_event_is_protected(event)
        ]
        if len(protected) > self.max_journal_events:
            raise OSError(
                "bridge journal protected events exceed max_journal_events: "
                f"{len(protected)} > {self.max_journal_events}"
            )
        optional = [
            event for event in events if not self._journal_event_is_protected(event)
        ]
        optional.sort(
            key=lambda event: float(event.get("recordedAt") or 0),
            reverse=True,
        )
        events = protected + optional[: self.max_journal_events - len(protected)]
        events.sort(key=lambda event: float(event.get("recordedAt") or 0))

        temporary_path = self.journal_path.with_name(self.journal_path.name + ".tmp")
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            for event in events:
                handle.write(
                    json.dumps(
                        event,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._replace_journal_file(temporary_path, self.journal_path)
        self._journal_event_count = len(events)

    @staticmethod
    def _journal_event_is_protected(event: dict[str, Any]) -> bool:
        if event.get("event") == "intent":
            return True
        state = str(
            event.get("transactionState")
            or event.get("state")
            or ""
        )
        if not state and isinstance(event.get("response"), dict):
            state = BridgeHub._transaction_state(
                str(event.get("action") or ""),
                event["response"],
            )
        return state not in {"committed", "rejected", "completed"}

    @staticmethod
    def _replace_journal_file(source: Path, target: Path) -> None:
        try:
            for attempt in range(1, 6):
                try:
                    os.replace(source, target)
                    return
                except OSError as exc:
                    sharing_violation = (
                        getattr(exc, "winerror", None) in {5, 32}
                        or exc.errno in {13, 32}
                    )
                    if not sharing_violation or attempt == 5:
                        raise
                    time.sleep(0.02 * attempt)
        finally:
            try:
                source.unlink(missing_ok=True)
            except OSError:
                pass

    def _evict_completed(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        expired = [
            key
            for key, item in self.completed.items()
            if now - item.completed_at > self.idempotency_ttl
        ]
        for key in expired:
            self.completed.pop(key, None)
        while len(self.completed) > self.max_cache_entries:
            oldest = min(
                self.completed,
                key=lambda key: self.completed[key].completed_at,
            )
            self.completed.pop(oldest, None)
        self._evict_terminal_transactions(now)

    def _evict_terminal_transactions(self, now: float) -> None:
        terminal_states = {"committed", "rejected", "completed"}
        expired = [
            transaction_id
            for transaction_id, transaction in self.transactions.items()
            if transaction.state in terminal_states
            and now - transaction.updated_at > self.idempotency_ttl
            and (transaction.client_id, transaction.requested_id)
            not in self.completed
        ]
        for transaction_id in expired:
            self.transactions.pop(transaction_id, None)

    @staticmethod
    def _wire_request_id(client_id: str, requested_id: str) -> str:
        if not requested_id:
            return uuid.uuid4().hex
        if client_id == "default":
            return requested_id
        return f"{client_id}:{requested_id}"

    @staticmethod
    def _fingerprint(action: str, params: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"action": action, "params": params},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _json_depth(self, value: Any, depth: int = 0) -> int:
        if isinstance(value, dict):
            if not value:
                return depth + 1
            return max(self._json_depth(item, depth + 1) for item in value.values())
        if isinstance(value, list):
            if not value:
                return depth + 1
            return max(self._json_depth(item, depth + 1) for item in value)
        return depth

    @staticmethod
    def _normalize_response(
        response: dict[str, Any],
        *,
        user_request_id: str,
    ) -> dict[str, Any]:
        normalized = {
            key: value for key, value in response.items() if key != "requestId"
        }
        normalized["requestId"] = user_request_id
        if normalized.get("error"):
            normalized["permissionOutcome"] = classify_permission_failure(
                normalized
            ).to_dict()
        return normalized

    @staticmethod
    def _error_payload(
        request_id: str,
        error: ProtocolError,
    ) -> dict[str, Any]:
        payload = {
            "type": "response",
            "requestId": request_id,
            "error": f"{error.code}: {error.message}",
            "code": error.code,
            "outcome": error.outcome,
        }
        if error.retry_after_ms is not None:
            payload["retryAfterMs"] = error.retry_after_ms
        return payload

    async def _send_error(
        self,
        websocket: Any,
        request_id: str,
        code: str,
        error: str,
        *,
        outcome: str = "not-applied",
        retry_after_ms: int | None = None,
    ) -> None:
        payload = {
            "type": "response",
            "requestId": request_id or None,
            "error": f"{code}: {error}",
            "code": code,
            "outcome": outcome,
        }
        if retry_after_ms is not None:
            payload["retryAfterMs"] = retry_after_ms
        await websocket.send(
            json.dumps(
                payload,
                ensure_ascii=False,
            )
        )


class ProtocolError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        outcome: str = "not-applied",
        retry_after_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.outcome = outcome
        self.retry_after_ms = retry_after_ms


def _default_journal_path(
    environ: Mapping[str, str] | None = None,
    *,
    configured: Path | None = None,
) -> Path | None:
    values = os.environ if environ is None else environ
    raw = str(values.get("FIGMA_BRIDGE_JOURNAL", "")).strip()
    if raw.lower() in {"off", "memory", "none", "disabled"}:
        return None
    if raw:
        path = Path(raw).expanduser()
        return path if path.is_absolute() else Path.cwd() / path
    return configured


def _default_auth_token(
    environ: Mapping[str, str] | None = None,
    *,
    configured: str | None = None,
) -> str | None:
    values = os.environ if environ is None else environ
    token = str(values.get("FIGMA_BRIDGE_TOKEN", "")).strip()
    return token or configured


def _server_ssl_context(
    config: BridgeTlsServerConfig,
) -> ssl.SSLContext | None:
    if not config.enabled:
        return None
    if config.certfile is None or config.keyfile is None:
        raise ValueError("TLS server certfile and keyfile are required")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(config.certfile), str(config.keyfile))
    if config.ca_file is not None:
        context.load_verify_locations(cafile=str(config.ca_file))
    if config.require_client_cert:
        context.verify_mode = ssl.CERT_REQUIRED
    return context


def _write_pacing_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    defaults: WritePacingPolicy | None = None,
) -> WritePacingPolicy:
    values = os.environ if environ is None else environ
    default = defaults or WritePacingPolicy(
        min_interval=0.05,
        queue_timeout=5.0,
        max_queue=16,
    )
    min_interval_ms = float(
        str(
            values.get(
                "FIGMA_BRIDGE_WRITE_MIN_INTERVAL_MS",
                default.min_interval * 1000,
            )
        ).strip()
        or str(default.min_interval * 1000)
    )
    queue_timeout = float(
        str(
            values.get(
                "FIGMA_BRIDGE_WRITE_QUEUE_TIMEOUT",
                default.queue_timeout,
            )
        ).strip()
        or str(default.queue_timeout)
    )
    max_queue = int(
        str(
            values.get(
                "FIGMA_BRIDGE_WRITE_QUEUE_LIMIT",
                default.max_queue,
            )
        ).strip()
        or str(default.max_queue)
    )
    if not math.isfinite(min_interval_ms) or min_interval_ms < 0:
        raise ValueError(
            "FIGMA_BRIDGE_WRITE_MIN_INTERVAL_MS must be finite and non-negative"
        )
    if not math.isfinite(queue_timeout) or queue_timeout <= 0:
        raise ValueError(
            "FIGMA_BRIDGE_WRITE_QUEUE_TIMEOUT must be finite and positive"
        )
    if max_queue <= 0:
        raise ValueError("FIGMA_BRIDGE_WRITE_QUEUE_LIMIT must be positive")
    return WritePacingPolicy(
        min_interval=min_interval_ms / 1000,
        queue_timeout=queue_timeout,
        max_queue=max_queue,
    )


def _bridge_timeout_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    default: float = 30.0,
) -> float:
    values = os.environ if environ is None else environ
    raw = str(values.get("FIGMA_BRIDGE_TIMEOUT", default)).strip() or str(default)
    timeout = float(raw)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("FIGMA_BRIDGE_TIMEOUT must be finite and positive")
    return timeout


def _allow_legacy_job_ids_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    default: bool = False,
) -> bool:
    values = os.environ if environ is None else environ
    raw = str(
        values.get("FIGMA_BRIDGE_ALLOW_LEGACY_JOB_IDS", "0")
    ).strip().lower()
    if raw == "":
        return default
    if raw in {"0", "false", "no"}:
        return False
    if raw in {"1", "true", "yes"}:
        return True
    raise ValueError(
        "FIGMA_BRIDGE_ALLOW_LEGACY_JOB_IDS must be a boolean"
    )


def _client_tokens_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    default: Mapping[str, str] | None = None,
) -> dict[str, str]:
    values = os.environ if environ is None else environ
    raw = str(values.get("FIGMA_BRIDGE_CLIENT_TOKENS", "")).strip()
    if not raw:
        return _normalize_client_tokens(default)
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "FIGMA_BRIDGE_CLIENT_TOKENS must be a JSON object"
        ) from exc
    return _normalize_client_tokens(payload)


def _normalize_client_tokens(
    tokens: Mapping[str, str] | None,
) -> dict[str, str]:
    if tokens is None:
        return {}
    if not isinstance(tokens, Mapping):
        raise ValueError("client tokens must be a mapping")
    normalized: dict[str, str] = {}
    for raw_client_id, raw_token in tokens.items():
        client_id = str(raw_client_id or "").strip()
        token = str(raw_token or "").strip()
        if not client_id or len(client_id) > 128:
            raise ValueError("client token clientId must be 1..128 characters")
        if not token:
            raise ValueError(f"client token for {client_id!r} must not be empty")
        normalized[client_id] = token
    return normalized


def _hub_from_server_config(
    config: BridgeServerConfig,
    *,
    environ: Mapping[str, str] | None = None,
    allow_env_overrides: bool = False,
    config_path: str | Path | None = None,
) -> BridgeHub:
    values = (
        os.environ if environ is None else environ
    ) if allow_env_overrides else {}
    pacing = _write_pacing_from_env(
        values,
        defaults=WritePacingPolicy(
            min_interval=config.write_pacing.min_interval_ms / 1000,
            queue_timeout=config.write_pacing.queue_timeout_seconds,
            max_queue=config.write_pacing.max_queue,
        ),
    )
    writer_lease_store = (
        WriterLeaseStore(
            config.writer_lease.path,
            owner_id=config.writer_lease.owner_id,
            ttl_seconds=config.writer_lease.ttl_seconds,
        )
        if config.writer_lease.enabled and config.writer_lease.path is not None
        else None
    )
    return BridgeHub(
        timeout=_bridge_timeout_from_env(values, default=config.timeout),
        idempotency_ttl=config.idempotency_ttl,
        max_inflight=config.max_inflight,
        max_message_bytes=config.max_message_bytes,
        max_params_depth=config.max_params_depth,
        max_cache_entries=config.max_cache_entries,
        max_journal_events=config.max_journal_events,
        journal_path=_default_journal_path(
            values,
            configured=config.journal_path,
        ),
        exclusive_journal_lock=config.exclusive_journal_lock,
        auth_token=_default_auth_token(
            values,
            configured=config.auth_token,
        ),
        plugin_token=config.plugin_token,
        plugin_token_provider=(
            (lambda: load_bridge_config(config_path).server.plugin_token)
            if config_path is not None
            else None
        ),
        plugin_token_recheck_seconds=config.plugin_token_recheck_seconds,
        write_min_interval=pacing.min_interval,
        write_queue_timeout=pacing.queue_timeout,
        max_write_queue=pacing.max_queue,
        allow_legacy_job_ids=_allow_legacy_job_ids_from_env(
            values,
            default=config.allow_legacy_job_ids,
        ),
        client_tokens=_client_tokens_from_env(
            values,
            default=config.client_tokens,
        ),
        client_write_defaults=config.client_write_defaults,
        client_write_limits=config.client_write_limits,
        writer_lease_store=writer_lease_store,
    )


_bridge_config = load_bridge_config()
_hub: BridgeHub | None = None


def _get_hub() -> BridgeHub:
    global _hub
    if _hub is None:
        _hub = _hub_from_server_config(
            _bridge_config.server,
            allow_env_overrides=_bridge_config.allow_env_overrides,
            config_path=_bridge_config.config_path,
        )
    return _hub


def _close_hub() -> None:
    global _hub
    if _hub is not None:
        _hub.close()
        _hub = None


async def _plugin_handler(
    websocket: websockets.server.WebSocketServerProtocol,
) -> None:
    hub = _get_hub()
    if not await hub.authenticate_plugin(websocket):
        return
    await hub.attach_plugin(websocket)
    try:
        try:
            async for message in websocket:
                logger.info("收到插件消息: %s", str(message)[:200])
                await hub.plugin_message(str(message))
        except ConnectionClosed:
            pass
    finally:
        await hub.detach_plugin(websocket, reason="plugin socket closed")


async def _command_handler(
    websocket: websockets.server.WebSocketServerProtocol,
) -> None:
    hub = _get_hub()
    async for message in websocket:
        logger.info("收到 Python 命令: %s", str(message)[:200])
        await hub.command(websocket, str(message))


async def _route(websocket: websockets.server.WebSocketServerProtocol) -> None:
    path = websocket.request.path
    if path == "/plugin":
        await _plugin_handler(websocket)
    elif path == "/command":
        await _command_handler(websocket)
    else:
        await websocket.close(code=4001, reason="未知路径")


async def _run(host: str | None = None, port: int | None = None) -> None:
    host = host or _bridge_config.server.host
    port = port or _bridge_config.server.port
    ssl_context = _server_ssl_context(_bridge_config.server.tls)
    scheme = "wss" if ssl_context is not None else "ws"
    logger.info("启动 Figma 桥接服务器: %s://%s:%s", scheme, host, port)
    try:
        async with websockets.serve(
            _route,
            host,
            port,
            ssl=ssl_context,
        ):
            await asyncio.Future()
    finally:
        _close_hub()


def start(host: str | None = None, port: int | None = None) -> None:
    try:
        asyncio.run(_run(host, port))
    except KeyboardInterrupt:
        logger.info("收到中断信号，桥接服务器已停止")
    finally:
        _close_hub()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    start()
