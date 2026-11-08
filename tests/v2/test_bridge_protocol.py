from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import websockets

from src.app.services.job_namespace import build_job_namespace
from src.app.services.bridge_config import ClientWriteLimitConfig
from src.app.services.bridge_server import (
    BridgeHub,
    CompletedResponse,
    JournalLockError,
    TransactionRecord,
    _allow_legacy_job_ids_from_env,
    _bridge_timeout_from_env,
    _client_tokens_from_env,
    _write_pacing_from_env,
    websocket_frame_limit,
)


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.sent_at: list[float] = []
        self.closed_code = None

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))
        self.sent_at.append(time.monotonic())

    async def close(self, code=None, reason=None) -> None:
        self.closed_code = code


class PluginAuthSocket(FakeSocket):
    def __init__(self, responses: list[str]) -> None:
        super().__init__()
        self.responses = list(responses)
        self.closed_code = None

    async def recv(self) -> str:
        if not self.responses:
            raise ConnectionError("no more plugin auth messages")
        return self.responses.pop(0)

    async def close(self, code=None, reason=None) -> None:
        self.closed_code = code


class AuthSocket(FakeSocket):
    def __init__(
        self,
        authorization: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        resolved_headers = dict(headers or {})
        if authorization is not None:
            resolved_headers["Authorization"] = authorization
        self.request = SimpleNamespace(headers=resolved_headers)


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("condition was not reached")
        await asyncio.sleep(0.01)


class WritePacingConfigTests(unittest.TestCase):
    def test_bridge_timeout_uses_default_and_environment_override(self) -> None:
        self.assertEqual(_bridge_timeout_from_env({}), 30.0)
        self.assertEqual(
            _bridge_timeout_from_env({"FIGMA_BRIDGE_TIMEOUT": "0.001"}),
            0.001,
        )

    def test_bridge_timeout_rejects_nonpositive_or_nonfinite_values(self) -> None:
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _bridge_timeout_from_env({"FIGMA_BRIDGE_TIMEOUT": value})

    def test_write_pacing_uses_safe_defaults(self) -> None:
        policy = _write_pacing_from_env({})

        self.assertEqual(policy.min_interval, 0.05)
        self.assertEqual(policy.queue_timeout, 5.0)
        self.assertEqual(policy.max_queue, 16)

    def test_write_pacing_reads_environment_overrides(self) -> None:
        policy = _write_pacing_from_env(
            {
                "FIGMA_BRIDGE_WRITE_MIN_INTERVAL_MS": "25",
                "FIGMA_BRIDGE_WRITE_QUEUE_TIMEOUT": "2.5",
                "FIGMA_BRIDGE_WRITE_QUEUE_LIMIT": "8",
            }
        )

        self.assertEqual(policy.min_interval, 0.025)
        self.assertEqual(policy.queue_timeout, 2.5)
        self.assertEqual(policy.max_queue, 8)

    def test_write_pacing_rejects_invalid_environment(self) -> None:
        with self.assertRaises(ValueError):
            _write_pacing_from_env(
                {"FIGMA_BRIDGE_WRITE_MIN_INTERVAL_MS": "-1"}
            )
        with self.assertRaises(ValueError):
            _write_pacing_from_env(
                {"FIGMA_BRIDGE_WRITE_QUEUE_TIMEOUT": "0"}
            )
        with self.assertRaises(ValueError):
            _write_pacing_from_env(
                {"FIGMA_BRIDGE_WRITE_QUEUE_LIMIT": "0"}
            )

    def test_legacy_job_namespace_compatibility_requires_env_opt_in(self) -> None:
        self.assertFalse(_allow_legacy_job_ids_from_env({}))
        self.assertFalse(
            _allow_legacy_job_ids_from_env(
                {"FIGMA_BRIDGE_ALLOW_LEGACY_JOB_IDS": "0"}
            )
        )
        self.assertTrue(
            _allow_legacy_job_ids_from_env(
                {"FIGMA_BRIDGE_ALLOW_LEGACY_JOB_IDS": "1"}
            )
        )
        with self.assertRaises(ValueError):
            _allow_legacy_job_ids_from_env(
                {"FIGMA_BRIDGE_ALLOW_LEGACY_JOB_IDS": "maybe"}
            )

    def test_client_token_configuration_requires_valid_json_mapping(self) -> None:
        self.assertEqual(_client_tokens_from_env({}), {})
        self.assertEqual(
            _client_tokens_from_env(
                {
                    "FIGMA_BRIDGE_CLIENT_TOKENS": (
                        '{"client-a":"token-a","client-b":"token-b"}'
                    )
                }
            ),
            {"client-a": "token-a", "client-b": "token-b"},
        )
        for value in ("not-json", "[]", '{"client-a":""}', '{"": "token"}'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _client_tokens_from_env(
                        {"FIGMA_BRIDGE_CLIENT_TOKENS": value}
                    )


class OwnershipReconciliationTests(unittest.TestCase):
    def test_expected_checks_cover_image_layout_bounds_text_and_region(self) -> None:
        checks = BridgeHub._expected_checks(
            "apply_edit_batch",
            {
                "actions": [
                    {
                        "action": "replace_image_fill",
                        "params": {
                            "nodeId": "1:1",
                            "imageBase64": "aW1hZ2U=",
                        },
                    },
                    {
                        "action": "set_layout_flow",
                        "params": {
                            "nodeId": "1:2",
                            "layout": {"layoutMode": "HORIZONTAL"},
                        },
                    },
                    {
                        "action": "set_bounds",
                        "params": {
                            "nodeId": "1:3",
                            "x": 1,
                            "y": 2,
                            "width": 30,
                            "height": 40,
                            "regionId": "region-a",
                        },
                    },
                    {
                        "action": "set_text",
                        "params": {
                            "nodeId": "1:4",
                            "text": "Title",
                            "textRuns": [{"characters": "Title"}],
                        },
                    },
                ]
            },
        )
        properties = {check["property"] for check in checks}

        self.assertTrue(
            {
                "imageFillSha256",
                "layoutSnapshot",
                "bounds",
                "regionMembership",
                "textRuns",
            }.issubset(properties)
        )

    def test_expected_checks_normalize_layout_and_keep_region_context(self) -> None:
        checks = BridgeHub._expected_checks(
            "apply_edit_batch",
            {
                "actions": [
                    {
                        "action": "set_layout_flow",
                        "params": {
                            "nodeId": "1:2",
                            "regionId": "region-a",
                            "layout": {
                                "mode": "HORIZONTAL",
                                "primaryAlign": "CENTER",
                            },
                        },
                    },
                    {
                        "action": "set_bounds",
                        "params": {
                            "nodeId": "1:3",
                            "regionId": "region-a",
                            "x": 1,
                            "y": 2,
                            "width": 30,
                            "height": 40,
                        },
                    },
                    {
                        "action": "replace_image_fill",
                        "params": {
                            "nodeId": "1:1",
                            "imageBase64": "aW1hZ2U=",
                            "fillIndex": 1,
                            "regionId": "region-a",
                        },
                    },
                ]
            },
        )
        layout = next(
            check for check in checks if check["property"] == "layoutSnapshot"
        )
        image = next(
            check for check in checks if check["property"] == "imageFillSha256"
        )

        self.assertEqual(
            layout["expectedValue"],
            {
                "layoutMode": "HORIZONTAL",
                "primaryAxisAlignItems": "CENTER",
            },
        )
        self.assertEqual(layout["regionId"], "region-a")
        self.assertEqual(image["fillIndex"], 1)
        self.assertEqual(image["regionId"], "region-a")

    def test_reconciliation_reports_partial_region_failures(self) -> None:
        hub = BridgeHub(timeout=2)
        checks = (
            {
                "nodeId": "1:1",
                "action": "set_text",
                "property": "characters",
                "regionId": "region-a",
                "expectedValue": "same",
            },
            {
                "nodeId": "1:2",
                "action": "set_text",
                "property": "characters",
                "regionId": "region-b",
                "expectedValue": "intended",
            },
        )

        reconciliation = hub._evaluate_expected_checks(
            checks,
            {
                "1:1": {"characters": "same"},
                "1:2": {"characters": "changed"},
            },
        )

        self.assertEqual(reconciliation["classification"], "partial-match")
        self.assertEqual(
            reconciliation["regions"]["region-a"]["classification"],
            "matches-intended",
        )
        self.assertEqual(
            reconciliation["regions"]["region-b"]["classification"],
            "does-not-match-intended",
        )

    def test_ownership_reconciliation_is_conservative(self) -> None:
        complete = BridgeHub._evaluate_ownership_readback(
            2,
            {"status": "reported", "matched": 2},
        )
        partial = BridgeHub._evaluate_ownership_readback(
            2,
            {"status": "reported", "matched": 1},
        )
        absent = BridgeHub._evaluate_ownership_readback(
            2,
            {"status": "reported", "matched": 0},
        )
        unavailable = BridgeHub._evaluate_ownership_readback(2, None)

        self.assertEqual(complete["classification"], "matches-intended")
        self.assertEqual(partial["classification"], "partial-match")
        self.assertEqual(absent["classification"], "does-not-match-intended")
        self.assertEqual(unavailable["classification"], "indeterminate")

    def test_transaction_payload_marks_collaborator_attribution_unavailable(
        self,
    ) -> None:
        hub = BridgeHub(timeout=1)
        payload = hub._transaction_payload(
            TransactionRecord(
                client_id="client-a",
                requested_id="request-a",
                transaction_id="tx-a",
                state="unknown",
                fingerprint="a" * 64,
                action="apply_edit_batch",
                updated_at=1.0,
            )
        )

        self.assertEqual(payload["attribution"]["status"], "unavailable")
        self.assertEqual(payload["attribution"]["actor"], "unknown")
        self.assertEqual(payload["attribution"]["revision"], "unknown")


class BridgeProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_readback_uses_actual_image_bytes_for_expected_hash(
        self,
    ) -> None:
        hub = BridgeHub(timeout=2)
        calls: list[tuple[str, dict]] = []
        payload = b"image"
        expected_hash = hashlib.sha256(payload).hexdigest()

        async def fake_plugin_call(action: str, params: dict):
            calls.append((action, params))
            if action == "get_node_tree":
                return {
                    "id": "1:1",
                    "regionMembership": {
                        "regionId": "region-a",
                        "member": True,
                    },
                }
            if action == "image_fill_report":
                return {
                    "nodeId": "1:1",
                    "fills": [
                        {
                            "nodeId": "1:1",
                            "fillIndex": 0,
                            "byteBase64": base64.b64encode(payload).decode(
                                "ascii"
                            ),
                        }
                    ],
                }
            raise AssertionError(action)

        hub._plugin_call = fake_plugin_call
        expected_checks = (
            {
                "nodeId": "1:1",
                "action": "replace_image_fill",
                "property": "imageFillSha256",
                "expectedSha256": expected_hash,
                "fillIndex": 0,
            },
            {
                "nodeId": "1:1",
                "action": "set_bounds",
                "property": "regionMembership",
                "expectedValue": {
                    "regionId": "region-a",
                    "member": True,
                },
                "regionId": "region-a",
            },
        )

        readback = await hub._plugin_read_node_tree(
            "1:1",
            expected_checks=expected_checks,
        )
        reconciliation = hub._evaluate_expected_checks(
            expected_checks,
            {"1:1": readback},
        )

        self.assertEqual(calls[0][0], "get_node_tree")
        self.assertEqual(calls[1][0], "image_fill_report")
        self.assertEqual(
            readback["imageFillSha256"],
            {"0": expected_hash},
        )
        self.assertEqual(reconciliation["classification"], "matches-intended")

    async def test_wrong_plugin_token_cannot_replace_active_plugin(self) -> None:
        hub = BridgeHub(timeout=2, plugin_token="plugin-secret")
        active = FakeSocket()
        wrong = PluginAuthSocket([json.dumps({"type": "auth", "token": "wrong"})])
        valid = PluginAuthSocket(
            [json.dumps({"type": "auth", "token": "plugin-secret"})]
        )
        await hub.attach_plugin(active)

        self.assertFalse(await hub.authenticate_plugin(wrong))
        self.assertIs(hub.plugin_ws, active)
        self.assertIsNone(active.closed_code)

        self.assertTrue(await hub.authenticate_plugin(valid))
        await hub.attach_plugin(valid)
        self.assertEqual(active.closed_code, 4002)
        self.assertIs(hub.plugin_ws, valid)

    async def test_plugin_token_provider_rotates_on_new_connection(self) -> None:
        current = {"token": "old-token"}
        hub = BridgeHub(
            timeout=2,
            plugin_token_provider=lambda: current["token"],
        )
        old = PluginAuthSocket([json.dumps({"type": "auth", "token": "old-token"})])
        self.assertTrue(await hub.authenticate_plugin(old))

        current["token"] = "new-token"
        stale = PluginAuthSocket(
            [json.dumps({"type": "auth", "token": "old-token"})]
        )
        fresh = PluginAuthSocket(
            [json.dumps({"type": "auth", "token": "new-token"})]
        )
        self.assertFalse(await hub.authenticate_plugin(stale))
        self.assertTrue(await hub.authenticate_plugin(fresh))

    async def test_plugin_token_rotation_revokes_active_connection(self) -> None:
        current = {"token": "old-token"}
        hub = BridgeHub(
            timeout=2,
            plugin_token_provider=lambda: current["token"],
            plugin_token_recheck_seconds=0.01,
        )
        active = PluginAuthSocket(
            [json.dumps({"type": "auth", "token": "old-token"})]
        )
        self.assertTrue(await hub.authenticate_plugin(active))
        await hub.attach_plugin(active)

        current["token"] = "new-token"
        await _wait_until(lambda: hub.plugin_ws is None)

        self.assertEqual(active.closed_code, 4004)

    async def test_plugin_auth_requires_configured_token(self) -> None:
        hub = BridgeHub(timeout=2, plugin_token="plugin-secret")
        missing = PluginAuthSocket([json.dumps({"type": "auth"})])
        wrong = PluginAuthSocket(
            [json.dumps({"type": "auth", "token": "wrong"})]
        )
        valid = PluginAuthSocket(
            [json.dumps({"type": "auth", "token": "plugin-secret"})]
        )

        self.assertFalse(await hub.authenticate_plugin(missing))
        self.assertFalse(await hub.authenticate_plugin(wrong))
        self.assertTrue(await hub.authenticate_plugin(valid))
        self.assertEqual(missing.closed_code, 4003)
        self.assertEqual(wrong.closed_code, 4003)
        self.assertEqual(missing.sent[0]["type"], "auth-error")
        self.assertEqual(wrong.sent[0]["type"], "auth-error")
        self.assertEqual(valid.sent[0]["type"], "auth-ok")

    async def test_plugin_auth_is_optional_without_configured_token(self) -> None:
        hub = BridgeHub(timeout=2)
        socket = PluginAuthSocket([])

        self.assertTrue(await hub.authenticate_plugin(socket))
        self.assertEqual(socket.sent, [])

    async def test_optional_plugin_auth_frame_is_ignored_after_attach(self) -> None:
        hub = BridgeHub(timeout=2)

        await hub.plugin_message(json.dumps({"type": "auth", "token": ""}))

        self.assertEqual(hub.pending, {})

    async def test_per_client_admission_prevents_one_client_queue_monopoly(
        self,
    ) -> None:
        hub = BridgeHub(
            timeout=2,
            write_min_interval=0,
            max_write_queue=4,
            client_write_defaults=ClientWriteLimitConfig(
                max_inflight=1,
                burst=1,
                min_interval_ms=0,
            ),
        )
        plugin = FakeSocket()
        await hub.attach_plugin(plugin)
        first = asyncio.create_task(
            hub.command(
                FakeSocket(),
                json.dumps(
                    {
                        "action": "apply_edit_batch",
                        "params": {
                            "transactionId": "client-a-first",
                            "actions": [],
                        },
                        "clientId": "client-a",
                        "requestId": "client-a-first",
                    }
                ),
            )
        )
        await _wait_until(lambda: len(plugin.sent) == 1)

        rejected = FakeSocket()
        await hub.command(
            rejected,
            json.dumps(
                {
                    "action": "apply_edit_batch",
                    "params": {
                        "transactionId": "client-a-second",
                        "actions": [],
                    },
                    "clientId": "client-a",
                    "requestId": "client-a-second",
                }
            ),
        )
        self.assertEqual(
            rejected.sent[0]["code"],
            "BRIDGE_CLIENT_RATE_LIMITED",
        )
        self.assertEqual(rejected.sent[0]["outcome"], "not-applied")
        self.assertEqual(len(plugin.sent), 1)
        self.assertNotIn("client-a-second", hub.transactions)

        second_client = FakeSocket()
        second = asyncio.create_task(
            hub.command(
                second_client,
                json.dumps(
                    {
                        "action": "apply_edit_batch",
                        "params": {
                            "transactionId": "client-b-first",
                            "actions": [],
                        },
                        "clientId": "client-b",
                        "requestId": "client-b-first",
                    }
                ),
            )
        )
        await asyncio.sleep(0)
        self.assertEqual(len(plugin.sent), 1)

        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[0]["requestId"],
                    "result": {"status": "committed", "committed": []},
                }
            )
        )
        await first
        await _wait_until(lambda: len(plugin.sent) == 2)
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[1]["requestId"],
                    "result": {"status": "committed", "committed": []},
                }
            )
        )
        await second

        self.assertIn("result", second_client.sent[0])

    async def test_client_rate_limit_does_not_block_other_client_burst(
        self,
    ) -> None:
        hub = BridgeHub(
            timeout=2,
            write_min_interval=0,
            max_write_queue=4,
            client_write_defaults=ClientWriteLimitConfig(
                max_inflight=2,
                burst=1,
                min_interval_ms=100,
            ),
        )
        plugin = FakeSocket()
        await hub.attach_plugin(plugin)

        async def send(request_id: str, transaction_id: str, client_id: str):
            client = FakeSocket()
            task = asyncio.create_task(
                hub.command(
                    client,
                    json.dumps(
                        {
                            "action": "apply_edit_batch",
                            "params": {
                                "transactionId": transaction_id,
                                "actions": [],
                            },
                            "clientId": client_id,
                            "requestId": request_id,
                        }
                    ),
                )
            )
            return client, task

        _, first = await send("first-a", "first-a", "client-a")
        await _wait_until(lambda: len(plugin.sent) == 1)
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[0]["requestId"],
                    "result": {"status": "committed", "committed": []},
                }
            )
        )
        await first

        _, second_a = await send("second-a", "second-a", "client-a")
        _, first_b = await send("first-b", "first-b", "client-b")
        await _wait_until(lambda: len(plugin.sent) == 2)

        self.assertEqual(
            plugin.sent[1]["params"]["transactionId"],
            "first-b",
        )
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[1]["requestId"],
                    "result": {"status": "committed", "committed": []},
                }
            )
        )
        await first_b
        await _wait_until(lambda: len(plugin.sent) == 3)
        self.assertEqual(
            plugin.sent[2]["params"]["transactionId"],
            "second-a",
        )
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[2]["requestId"],
                    "result": {"status": "committed", "committed": []},
                }
            )
        )
        await second_a

    async def test_apply_batch_rejects_legacy_job_id_before_dispatch(self) -> None:
        hub = BridgeHub(timeout=2)
        plugin = FakeSocket()
        client = FakeSocket()
        await hub.attach_plugin(plugin)

        await hub.command(
            client,
            json.dumps(
                {
                    "action": "apply_batch",
                    "params": {
                        "transactionId": "legacy-job",
                        "actions": [],
                    },
                    "clientId": "client-a",
                    "requestId": "legacy-request",
                }
            ),
        )

        self.assertEqual(plugin.sent, [])
        self.assertEqual(client.sent[0]["code"], "INVALID_JOB_NAMESPACE")
        self.assertEqual(client.sent[0]["outcome"], "not-applied")

    async def test_apply_batch_rejects_another_clients_namespace(self) -> None:
        hub = BridgeHub(timeout=2)
        plugin = FakeSocket()
        client = FakeSocket()
        await hub.attach_plugin(plugin)
        namespaced = build_job_namespace("client-a", "shared-raw")

        await hub.command(
            client,
            json.dumps(
                {
                    "action": "apply_batch",
                    "params": {
                        "transactionId": namespaced,
                        "actions": [],
                    },
                    "clientId": "client-b",
                    "requestId": "mismatch-request",
                }
            ),
        )

        self.assertEqual(plugin.sent, [])
        self.assertEqual(client.sent[0]["code"], "JOB_NAMESPACE_CLIENT_MISMATCH")

    async def test_ownership_transaction_id_cannot_be_reused_with_new_request(
        self,
    ) -> None:
        hub = BridgeHub(timeout=2, idempotency_ttl=60, write_min_interval=0)
        plugin = FakeSocket()
        await hub.attach_plugin(plugin)
        namespaced = build_job_namespace("client-a", "reused-job")
        first = asyncio.create_task(
            hub.command(
                FakeSocket(),
                json.dumps(
                    {
                        "action": "apply_batch",
                        "params": {
                            "transactionId": namespaced,
                            "actions": [
                                {
                                    "action": "create_frame",
                                    "params": {"name": "First"},
                                }
                            ],
                        },
                        "clientId": "client-a",
                        "requestId": "first-request",
                    }
                ),
            )
        )
        await _wait_until(lambda: len(plugin.sent) == 1)
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[0]["requestId"],
                    "result": {"status": "committed", "committed": []},
                }
            )
        )
        await first

        second = FakeSocket()
        await hub.command(
            second,
            json.dumps(
                {
                    "action": "apply_batch",
                    "params": {
                        "transactionId": namespaced,
                        "actions": [
                            {
                                "action": "create_frame",
                                "params": {"name": "First"},
                            }
                        ],
                    },
                    "clientId": "client-a",
                    "requestId": "second-request",
                }
            ),
        )

        self.assertEqual(len(plugin.sent), 1)
        self.assertEqual(second.sent[0]["code"], "TRANSACTION_ID_CONFLICT")
        self.assertEqual(second.sent[0]["outcome"], "not-applied")

    async def test_cleanup_rejects_legacy_job_id_before_dispatch(self) -> None:
        hub = BridgeHub(timeout=2)
        plugin = FakeSocket()
        client = FakeSocket()
        await hub.attach_plugin(plugin)

        await hub.command(
            client,
            json.dumps(
                {
                    "action": "cleanup_owned_job",
                    "params": {"jobId": "legacy-job"},
                    "clientId": "client-a",
                    "requestId": "legacy-cleanup",
                }
            ),
        )

        self.assertEqual(plugin.sent, [])
        self.assertEqual(client.sent[0]["code"], "INVALID_JOB_NAMESPACE")

    async def test_legacy_job_ids_require_explicit_bridge_opt_in(self) -> None:
        hub = BridgeHub(timeout=2, allow_legacy_job_ids=True)
        plugin = FakeSocket()
        client = FakeSocket()
        await hub.attach_plugin(plugin)

        task = asyncio.create_task(
            hub.command(
                client,
                json.dumps(
                    {
                        "action": "apply_batch",
                        "params": {
                            "transactionId": "legacy-job",
                            "actions": [],
                        },
                        "clientId": "client-a",
                        "requestId": "legacy-request",
                    }
                ),
            )
        )
        await _wait_until(lambda: len(plugin.sent) == 1)
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[0]["requestId"],
                    "result": {"status": "committed", "committed": []},
                }
            )
        )
        await task

        self.assertEqual(plugin.sent[0]["params"]["transactionId"], "legacy-job")

    async def test_responses_are_correlated_per_concurrent_client(self) -> None:
        hub = BridgeHub(timeout=2)
        plugin = FakeSocket()
        first = FakeSocket()
        second = FakeSocket()
        await hub.attach_plugin(plugin)

        tasks = [
            asyncio.create_task(
                hub.command(
                    first,
                    json.dumps(
                        {
                            "action": "get_node_tree",
                            "params": {"nodeId": "first"},
                        }
                    ),
                )
            ),
            asyncio.create_task(
                hub.command(
                    second,
                    json.dumps(
                        {
                            "action": "get_node_tree",
                            "params": {"nodeId": "second"},
                        }
                    ),
                )
            ),
        ]
        await _wait_until(lambda: len(plugin.sent) == 2)
        request_ids = [message["requestId"] for message in plugin.sent]
        self.assertEqual(len(set(request_ids)), 2)

        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": request_ids[1],
                    "result": "second-result",
                }
            )
        )
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": request_ids[0],
                    "result": "first-result",
                }
            )
        )
        await asyncio.gather(*tasks)

        self.assertEqual(first.sent[0]["result"], "first-result")
        self.assertEqual(second.sent[0]["result"], "second-result")
        self.assertEqual(first.sent[0]["requestId"], request_ids[0])
        self.assertEqual(second.sent[0]["requestId"], request_ids[1])

    async def test_plugin_disconnect_fails_pending_commands_closed(self) -> None:
        hub = BridgeHub(timeout=2)
        plugin = FakeSocket()
        client = FakeSocket()
        await hub.attach_plugin(plugin)
        task = asyncio.create_task(
            hub.command(
                client,
                json.dumps(
                    {
                        "action": "slow",
                        "params": {},
                    }
                ),
            )
        )
        await _wait_until(lambda: len(plugin.sent) == 1)

        await hub.detach_plugin(plugin, reason="test-disconnect")
        await task

        self.assertIn("disconnected", client.sent[0]["error"].lower())
        self.assertEqual(
            client.sent[0]["requestId"],
            plugin.sent[0]["requestId"],
        )

    async def test_completed_request_id_is_idempotent_within_ttl(self) -> None:
        hub = BridgeHub(timeout=2, idempotency_ttl=60)
        plugin = FakeSocket()
        first = FakeSocket()
        second = FakeSocket()
        await hub.attach_plugin(plugin)
        request = json.dumps(
            {
                "action": "write_once",
                "params": {"value": 1},
                "requestId": "stable-request",
            }
        )

        first_task = asyncio.create_task(hub.command(first, request))
        await _wait_until(lambda: len(plugin.sent) == 1)
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": "stable-request",
                    "result": {"written": True},
                }
            )
        )
        await first_task

        await hub.command(second, request)

        self.assertEqual(len(plugin.sent), 1)
        self.assertEqual(first.sent[0]["result"], {"written": True})
        self.assertEqual(second.sent[0]["result"], {"written": True})

    async def test_same_request_id_is_isolated_between_clients(self) -> None:
        hub = BridgeHub(timeout=2)
        plugin = FakeSocket()
        first = FakeSocket()
        second = FakeSocket()
        await hub.attach_plugin(plugin)

        tasks = [
            asyncio.create_task(
                hub.command(
                    first,
                    json.dumps(
                        {
                            "action": "get_node_tree",
                            "params": {"client": "first"},
                            "clientId": "client-first",
                            "requestId": "shared-id",
                        }
                    ),
                )
            ),
            asyncio.create_task(
                hub.command(
                    second,
                    json.dumps(
                        {
                            "action": "get_node_tree",
                            "params": {"client": "second"},
                            "clientId": "client-second",
                            "requestId": "shared-id",
                        }
                    ),
                )
            ),
        ]
        await _wait_until(lambda: len(plugin.sent) == 2)
        for sent in plugin.sent:
            await hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": sent["requestId"],
                        "result": sent["params"]["client"],
                    }
                )
            )
        await asyncio.gather(*tasks)

        self.assertEqual(first.sent[0]["result"], "first")
        self.assertEqual(second.sent[0]["result"], "second")
        self.assertEqual(first.sent[0]["requestId"], "shared-id")
        self.assertEqual(second.sent[0]["requestId"], "shared-id")
        self.assertNotEqual(plugin.sent[0]["requestId"], plugin.sent[1]["requestId"])

    async def test_idempotency_key_reuse_with_different_payload_fails_closed(
        self,
    ) -> None:
        hub = BridgeHub(timeout=2, idempotency_ttl=60)
        plugin = FakeSocket()
        client = FakeSocket()
        await hub.attach_plugin(plugin)
        first_request = json.dumps(
            {
                "action": "write",
                "params": {"value": 1},
                "clientId": "client-a",
                "requestId": "stable-request",
            }
        )

        task = asyncio.create_task(hub.command(client, first_request))
        await _wait_until(lambda: len(plugin.sent) == 1)
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[0]["requestId"],
                    "result": {"written": True},
                }
            )
        )
        await task

        await hub.command(
            client,
            json.dumps(
                {
                    "action": "write",
                    "params": {"value": 2},
                    "clientId": "client-a",
                    "requestId": "stable-request",
                }
            ),
        )

        self.assertEqual(len(plugin.sent), 1)
        self.assertIn("IDEMPOTENCY_KEY_CONFLICT", client.sent[-1]["error"])

    async def test_backpressure_rejects_excess_inflight_commands(self) -> None:
        hub = BridgeHub(timeout=2, max_inflight=1)
        plugin = FakeSocket()
        first = FakeSocket()
        second = FakeSocket()
        await hub.attach_plugin(plugin)
        task = asyncio.create_task(
            hub.command(
                first,
                json.dumps(
                    {
                        "action": "slow",
                        "params": {},
                    }
                ),
            )
        )
        await _wait_until(lambda: len(plugin.sent) == 1)

        await hub.command(
            second,
            json.dumps(
                {
                    "action": "slow",
                    "params": {},
                }
            ),
        )

        self.assertIn("BRIDGE_BACKPRESSURE", second.sent[0]["error"])
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[0]["requestId"],
                    "result": {"ok": True},
                }
            )
        )
        await task

    async def test_concurrent_writes_are_serialized_with_minimum_interval(
        self,
    ) -> None:
        hub = BridgeHub(
            timeout=2,
            write_min_interval=0.03,
            write_queue_timeout=1,
            max_write_queue=4,
        )
        plugin = FakeSocket()
        await hub.attach_plugin(plugin)
        tasks = [
            asyncio.create_task(
                hub.command(
                    FakeSocket(),
                    json.dumps(
                        {
                            "action": "apply_edit_batch",
                            "params": {
                                "transactionId": f"write-{index}",
                                "actions": [],
                            },
                            "clientId": f"client-{index}",
                            "requestId": f"write-{index}",
                        }
                    ),
                )
            )
            for index in range(3)
        ]

        await _wait_until(lambda: len(plugin.sent) == 1)
        await asyncio.sleep(0.01)
        self.assertEqual(len(plugin.sent), 1)

        for index in range(3):
            await _wait_until(lambda: len(plugin.sent) == index + 1)
            await hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": plugin.sent[index]["requestId"],
                        "result": {
                            "status": "committed",
                            "committed": [],
                        },
                    }
                )
            )
        await asyncio.gather(*tasks)

        gaps = [
            plugin.sent_at[index + 1] - plugin.sent_at[index]
            for index in range(len(plugin.sent_at) - 1)
        ]
        self.assertTrue(gaps)
        self.assertTrue(all(gap >= 0.025 for gap in gaps), gaps)

    async def test_write_queue_timeout_is_safe_before_plugin_dispatch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            hub = BridgeHub(
                timeout=2,
                journal_path=journal_path,
                write_min_interval=0,
                write_queue_timeout=0.05,
                max_write_queue=2,
            )
            plugin = FakeSocket()
            first_client = FakeSocket()
            queued_client = FakeSocket()
            await hub.attach_plugin(plugin)
            first = asyncio.create_task(
                hub.command(
                    first_client,
                    json.dumps(
                        {
                            "action": "apply_edit_batch",
                            "params": {
                                "transactionId": "write-first",
                                "actions": [],
                            },
                            "clientId": "client-first",
                            "requestId": "write-first",
                        }
                    ),
                )
            )
            await _wait_until(lambda: len(plugin.sent) == 1)

            await hub.command(
                queued_client,
                json.dumps(
                    {
                        "action": "apply_edit_batch",
                        "params": {
                            "transactionId": "write-queued",
                            "actions": [],
                        },
                        "clientId": "client-queued",
                        "requestId": "write-queued",
                    }
                ),
            )

            self.assertEqual(
                queued_client.sent[0]["code"],
                "BRIDGE_WRITE_BACKPRESSURE",
            )
            self.assertEqual(queued_client.sent[0]["outcome"], "not-applied")
            self.assertGreaterEqual(queued_client.sent[0]["retryAfterMs"], 1)
            self.assertEqual(len(plugin.sent), 1)

            await hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": plugin.sent[0]["requestId"],
                        "result": {
                            "status": "committed",
                            "committed": [],
                        },
                    }
                )
            )
            await first

            lines = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(lines), 2)
            self.assertEqual(hub.pending, {})
            self.assertEqual(hub.scope_pending, set())

    async def test_full_write_queue_rejects_before_creating_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            hub = BridgeHub(
                timeout=2,
                journal_path=journal_path,
                write_min_interval=0,
                write_queue_timeout=1,
                max_write_queue=1,
            )
            plugin = FakeSocket()
            await hub.attach_plugin(plugin)
            first = asyncio.create_task(
                hub.command(
                    FakeSocket(),
                    json.dumps(
                        {
                            "action": "apply_edit_batch",
                            "params": {
                                "transactionId": "queue-owner",
                                "actions": [],
                            },
                            "clientId": "queue-owner",
                            "requestId": "queue-owner",
                        }
                    ),
                )
            )
            await _wait_until(lambda: len(plugin.sent) == 1)

            rejected = FakeSocket()
            await hub.command(
                rejected,
                json.dumps(
                    {
                        "action": "apply_edit_batch",
                        "params": {
                            "transactionId": "queue-rejected",
                            "actions": [],
                        },
                        "clientId": "queue-rejected",
                        "requestId": "queue-rejected",
                    }
                ),
            )

            self.assertEqual(
                rejected.sent[0]["code"],
                "BRIDGE_WRITE_BACKPRESSURE",
            )
            self.assertEqual(rejected.sent[0]["outcome"], "not-applied")
            self.assertEqual(len(plugin.sent), 1)

            await hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": plugin.sent[0]["requestId"],
                        "result": {
                            "status": "committed",
                            "committed": [],
                        },
                    }
                )
            )
            await first
            lines = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(lines), 2)

    async def test_read_commands_bypass_the_write_dispatch_gate(self) -> None:
        hub = BridgeHub(
            timeout=2,
            write_min_interval=5,
            write_queue_timeout=1,
            max_write_queue=2,
        )
        plugin = FakeSocket()
        write_client = FakeSocket()
        read_client = FakeSocket()
        await hub.attach_plugin(plugin)
        write_task = asyncio.create_task(
            hub.command(
                write_client,
                json.dumps(
                    {
                        "action": "apply_edit_batch",
                        "params": {
                            "transactionId": "slow-write",
                            "actions": [],
                        },
                        "clientId": "write-client",
                        "requestId": "slow-write",
                    }
                ),
            )
        )
        await _wait_until(lambda: len(plugin.sent) == 1)

        read_task = asyncio.create_task(
            hub.command(
                read_client,
                json.dumps(
                    {
                        "action": "get_node_tree",
                        "params": {"nodeId": "1:1"},
                        "clientId": "read-client",
                        "requestId": "read-during-write",
                    }
                ),
            )
        )
        await _wait_until(lambda: len(plugin.sent) == 2)
        self.assertEqual(plugin.sent[1]["action"], "get_node_tree")

        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[1]["requestId"],
                    "result": {"id": "1:1"},
                }
            )
        )
        await read_task
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[0]["requestId"],
                    "result": {
                        "status": "committed",
                        "committed": [],
                    },
                }
            )
        )
        await write_task

    async def test_write_timeout_blocks_new_writes_until_plugin_reconnect(
        self,
    ) -> None:
        hub = BridgeHub(
            timeout=0.03,
            write_min_interval=0,
            write_queue_timeout=1,
            max_write_queue=4,
        )
        plugin = FakeSocket()
        await hub.attach_plugin(plugin)
        await hub.command(
            FakeSocket(),
            json.dumps(
                {
                    "action": "apply_edit_batch",
                    "params": {
                        "transactionId": "timeout-write",
                        "actions": [],
                    },
                    "clientId": "timeout-client",
                    "requestId": "timeout-write",
                }
            ),
        )

        blocked_client = FakeSocket()
        await hub.command(
            blocked_client,
            json.dumps(
                {
                    "action": "apply_edit_batch",
                    "params": {
                        "transactionId": "blocked-write",
                        "actions": [],
                    },
                    "clientId": "blocked-client",
                    "requestId": "blocked-write",
                }
            ),
        )

        self.assertEqual(
            blocked_client.sent[0]["code"],
            "BRIDGE_WRITE_BACKPRESSURE",
        )
        self.assertEqual(blocked_client.sent[0]["outcome"], "not-applied")
        self.assertEqual(len(plugin.sent), 1)

        replacement = FakeSocket()
        await hub.attach_plugin(replacement)
        retry = asyncio.create_task(
            hub.command(
                FakeSocket(),
                json.dumps(
                    {
                        "action": "apply_edit_batch",
                        "params": {
                            "transactionId": "retry-write",
                            "actions": [],
                        },
                        "clientId": "retry-client",
                        "requestId": "retry-write",
                    }
                ),
            )
        )
        await _wait_until(lambda: len(replacement.sent) == 1)
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": replacement.sent[0]["requestId"],
                    "result": {
                        "status": "committed",
                        "committed": [],
                    },
                }
            )
        )
        await retry

    async def test_request_size_limit_fails_before_plugin_dispatch(self) -> None:
        hub = BridgeHub(timeout=2, max_message_bytes=128)
        plugin = FakeSocket()
        client = FakeSocket()
        await hub.attach_plugin(plugin)

        await hub.command(
            client,
            json.dumps(
                {
                    "action": "write",
                    "params": {"value": "x" * 256},
                }
            ),
        )

        self.assertEqual(plugin.sent, [])
        self.assertIn("REQUEST_TOO_LARGE", client.sent[0]["error"])

    async def test_completed_cache_is_bounded(self) -> None:
        hub = BridgeHub(timeout=2, max_cache_entries=2)
        plugin = FakeSocket()
        await hub.attach_plugin(plugin)
        for index in range(3):
            client = FakeSocket()
            task = asyncio.create_task(
                hub.command(
                    client,
                    json.dumps(
                        {
                            "action": "read",
                            "params": {"index": index},
                            "requestId": f"request-{index}",
                        }
                    ),
                )
            )
            await _wait_until(lambda: len(plugin.sent) == index + 1)
            await hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": plugin.sent[-1]["requestId"],
                        "result": index,
                    }
                )
            )
            await task

        self.assertEqual(len(hub.completed), 2)

    async def test_timeout_is_cached_as_unknown_to_prevent_blind_retry(
        self,
    ) -> None:
        hub = BridgeHub(timeout=0.02, idempotency_ttl=60)
        plugin = FakeSocket()
        client = FakeSocket()
        await hub.attach_plugin(plugin)
        request = json.dumps(
            {
                "action": "write",
                "params": {"value": 1},
                "clientId": "timeout-client",
                "requestId": "timeout-request",
            }
        )

        await hub.command(client, request)
        await hub.command(client, request)

        self.assertEqual(len(plugin.sent), 1)
        self.assertEqual(client.sent[-1]["code"], "PLUGIN_TIMEOUT")
        self.assertEqual(client.sent[-1]["outcome"], "unknown")

    async def test_completed_idempotency_survives_hub_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            request = json.dumps(
                {
                    "action": "write_once",
                    "params": {"value": 1},
                    "clientId": "durable-client",
                    "requestId": "durable-request",
                }
            )

            first_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            first_plugin = FakeSocket()
            first_client = FakeSocket()
            await first_hub.attach_plugin(first_plugin)
            first_task = asyncio.create_task(first_hub.command(first_client, request))
            await _wait_until(lambda: len(first_plugin.sent) == 1)
            await first_hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": first_plugin.sent[0]["requestId"],
                        "result": {"written": True},
                    }
                )
            )
            await first_task

            restarted_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            restarted_plugin = FakeSocket()
            restarted_client = FakeSocket()
            await restarted_hub.attach_plugin(restarted_plugin)
            await restarted_hub.command(restarted_client, request)

            self.assertEqual(restarted_plugin.sent, [])
            self.assertEqual(restarted_client.sent[0]["result"], {"written": True})
            self.assertEqual(
                restarted_client.sent[0]["requestId"],
                "durable-request",
            )

    async def test_inflight_intent_recovers_as_unknown_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            request = json.dumps(
                {
                    "action": "write_once",
                    "params": {"value": 2},
                    "clientId": "crash-client",
                    "requestId": "crash-request",
                }
            )

            crashed_hub = BridgeHub(
                timeout=30,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            crashed_plugin = FakeSocket()
            crashed_client = FakeSocket()
            await crashed_hub.attach_plugin(crashed_plugin)
            crashed_task = asyncio.create_task(
                crashed_hub.command(crashed_client, request)
            )
            await _wait_until(lambda: len(crashed_plugin.sent) == 1)
            crashed_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await crashed_task

            restarted_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            restarted_plugin = FakeSocket()
            restarted_client = FakeSocket()
            await restarted_hub.attach_plugin(restarted_plugin)
            await restarted_hub.command(restarted_client, request)

            self.assertEqual(restarted_plugin.sent, [])
            self.assertEqual(
                restarted_client.sent[0]["code"],
                "REQUEST_OUTCOME_UNKNOWN",
            )
            self.assertEqual(restarted_client.sent[0]["outcome"], "unknown")

    async def test_transaction_terminal_state_survives_hub_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            request = json.dumps(
                {
                    "action": "apply_edit_batch",
                    "params": {
                        "transactionId": "tx-recover",
                        "actions": [],
                    },
                    "clientId": "transaction-client",
                    "requestId": "transaction-request",
                }
            )

            first_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            first_plugin = FakeSocket()
            first_client = FakeSocket()
            await first_hub.attach_plugin(first_plugin)
            first_task = asyncio.create_task(first_hub.command(first_client, request))
            await _wait_until(lambda: len(first_plugin.sent) == 1)
            await first_hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": first_plugin.sent[0]["requestId"],
                        "result": {
                            "status": "rolled-back",
                            "transactionId": "tx-recover",
                        },
                    }
                )
            )
            await first_task

            restarted_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )

            self.assertEqual(
                restarted_hub.transactions["tx-recover"].state,
                "rolled-back",
            )
            self.assertEqual(
                restarted_hub.transactions["tx-recover"].fingerprint,
                first_hub._fingerprint(
                    "apply_edit_batch",
                    {
                        "transactionId": "tx-recover",
                        "actions": [],
                    },
                ),
            )

    async def test_journal_replay_ignores_truncated_trailing_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            request = json.dumps(
                {
                    "action": "read",
                    "params": {"value": 4},
                    "clientId": "journal-client",
                    "requestId": "journal-request",
                }
            )

            first_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            first_plugin = FakeSocket()
            first_client = FakeSocket()
            await first_hub.attach_plugin(first_plugin)
            first_task = asyncio.create_task(first_hub.command(first_client, request))
            await _wait_until(lambda: len(first_plugin.sent) == 1)
            await first_hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": first_plugin.sent[0]["requestId"],
                        "result": {"value": 4},
                    }
                )
            )
            await first_task
            with journal_path.open("a", encoding="utf-8") as handle:
                handle.write('{"version":1')

            with self.assertLogs(
                "src.app.services.bridge_server",
                level="WARNING",
            ):
                restarted_hub = BridgeHub(
                    timeout=2,
                    idempotency_ttl=60,
                    journal_path=journal_path,
                )
            restarted_plugin = FakeSocket()
            restarted_client = FakeSocket()
            await restarted_hub.attach_plugin(restarted_plugin)
            await restarted_hub.command(restarted_client, request)

            self.assertEqual(restarted_plugin.sent, [])
            self.assertEqual(restarted_client.sent[0]["result"], {"value": 4})

    async def test_fingerprint_conflict_survives_hub_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            first_request = json.dumps(
                {
                    "action": "write",
                    "params": {"value": 1},
                    "clientId": "conflict-client",
                    "requestId": "conflict-request",
                }
            )
            first_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            first_plugin = FakeSocket()
            first_client = FakeSocket()
            await first_hub.attach_plugin(first_plugin)
            first_task = asyncio.create_task(
                first_hub.command(first_client, first_request)
            )
            await _wait_until(lambda: len(first_plugin.sent) == 1)
            await first_hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": first_plugin.sent[0]["requestId"],
                        "result": {"written": True},
                    }
                )
            )
            await first_task

            restarted_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            restarted_plugin = FakeSocket()
            restarted_client = FakeSocket()
            await restarted_hub.attach_plugin(restarted_plugin)
            await restarted_hub.command(
                restarted_client,
                json.dumps(
                    {
                        "action": "write",
                        "params": {"value": 2},
                        "clientId": "conflict-client",
                        "requestId": "conflict-request",
                    }
                ),
            )

            self.assertEqual(restarted_plugin.sent, [])
            self.assertIn(
                "IDEMPOTENCY_KEY_CONFLICT",
                restarted_client.sent[0]["error"],
            )

    async def test_journal_compaction_keeps_recent_completed_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                max_cache_entries=2,
                journal_path=journal_path,
                max_journal_events=3,
            )
            plugin = FakeSocket()
            await hub.attach_plugin(plugin)
            for index in range(4):
                client = FakeSocket()
                task = asyncio.create_task(
                    hub.command(
                        client,
                        json.dumps(
                            {
                                "action": "read",
                                "params": {"index": index},
                                "clientId": "compact-client",
                                "requestId": f"compact-{index}",
                            }
                        ),
                    )
                )
                await _wait_until(lambda: len(plugin.sent) == index + 1)
                await hub.plugin_message(
                    json.dumps(
                        {
                            "type": "response",
                            "requestId": plugin.sent[-1]["requestId"],
                            "result": index,
                        }
                    )
                )
                await task

            lines = [
                line
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertLessEqual(len(lines), 2)
            replayed = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                max_cache_entries=2,
                journal_path=journal_path,
            )
            self.assertEqual(len(replayed.completed), 2)

    async def test_journal_compaction_drops_expired_terminal_transactions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            hub = BridgeHub(
                timeout=2,
                idempotency_ttl=1,
                max_cache_entries=2,
                journal_path=journal_path,
                max_journal_events=8,
            )
            expired_at = time.time() - 120
            for index in range(12):
                transaction_id = f"expired-write-{index}"
                response = {
                    "type": "response",
                    "result": {
                        "status": "committed",
                        "transactionId": transaction_id,
                        "committed": [],
                    },
                }
                hub.transactions[transaction_id] = TransactionRecord(
                    client_id="expired-client",
                    requested_id=f"expired-request-{index}",
                    transaction_id=transaction_id,
                    state="committed",
                    fingerprint=f"fingerprint-{index}",
                    action="apply_edit_batch",
                    updated_at=expired_at,
                    response=response,
                )
                hub.completed[("expired-client", f"expired-request-{index}")] = (
                    CompletedResponse(
                        completed_at=expired_at,
                        fingerprint=f"fingerprint-{index}",
                        response=response,
                        action="apply_edit_batch",
                        transaction_id=transaction_id,
                    )
                )

            hub._evict_completed()
            hub._compact_journal()

            lines = [
                line
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertLessEqual(len(lines), hub.max_journal_events)
            self.assertEqual(hub.transactions, {})

    async def test_journal_compaction_preserves_expired_unknown_transaction(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            hub = BridgeHub(
                timeout=2,
                idempotency_ttl=1,
                journal_path=journal_path,
                max_journal_events=8,
            )
            expired_at = time.time() - 120
            for transaction_id, state in (
                ("expired-committed", "committed"),
                ("expired-unknown", "unknown"),
            ):
                hub.transactions[transaction_id] = TransactionRecord(
                    client_id="protected-client",
                    requested_id=f"request-{transaction_id}",
                    transaction_id=transaction_id,
                    state=state,
                    fingerprint=f"fingerprint-{transaction_id}",
                    action="apply_edit_batch",
                    updated_at=expired_at,
                    response={
                        "type": "response",
                        "requestId": f"request-{transaction_id}",
                        "result": {
                            "status": state,
                            "transactionId": transaction_id,
                        },
                    },
                )

            hub._evict_completed()
            hub._compact_journal()

            replayed = BridgeHub(
                timeout=2,
                idempotency_ttl=1,
                journal_path=journal_path,
                max_journal_events=8,
            )
            self.assertNotIn("expired-committed", replayed.transactions)
            self.assertIn("expired-unknown", replayed.transactions)
            self.assertEqual(
                replayed.transactions["expired-unknown"].state,
                "unknown",
            )

    async def test_journal_compaction_retries_transient_windows_replace_lock(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            hub = BridgeHub(
                timeout=2,
                journal_path=journal_path,
                max_journal_events=8,
            )
            hub._store_completed(
                ("windows-lock-client", "windows-lock-request"),
                "fingerprint",
                {
                    "type": "response",
                    "requestId": "windows-lock-request",
                    "result": {"ok": True},
                },
                action="read",
            )
            real_replace = os.replace
            attempts = 0

            def flaky_replace(source, target):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError(
                        13,
                        "Access is denied",
                        str(target),
                    )
                return real_replace(source, target)

            with patch(
                "src.app.services.bridge_server.os.replace",
                side_effect=flaky_replace,
            ):
                hub._compact_journal()

            self.assertEqual(attempts, 3)
            self.assertEqual(
                len(
                    [
                        line
                        for line in journal_path.read_text(
                            encoding="utf-8"
                        ).splitlines()
                        if line.strip()
                    ]
                ),
                1,
            )

    async def test_journal_lock_is_exclusive_until_hub_closes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            first_hub = BridgeHub(
                timeout=2,
                journal_path=journal_path,
                exclusive_journal_lock=True,
            )
            second_hub = None
            try:
                with self.assertRaises(JournalLockError):
                    BridgeHub(
                        timeout=2,
                        journal_path=journal_path,
                        exclusive_journal_lock=True,
                    )

                first_hub.close()
                second_hub = BridgeHub(
                    timeout=2,
                    journal_path=journal_path,
                    exclusive_journal_lock=True,
                )
                self.assertEqual(second_hub.journal_path, journal_path.resolve())
            finally:
                first_hub.close()
                if second_hub is not None:
                    second_hub.close()

    async def test_unknown_transaction_readback_is_automatic_and_persistent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            request = json.dumps(
                {
                    "action": "apply_edit_batch",
                    "params": {
                        "transactionId": "tx-readback",
                        "actions": [
                            {
                                "action": "set_text",
                                "params": {
                                    "nodeId": "TEXT:1",
                                    "text": "temporary",
                                },
                            },
                            {
                                "action": "set_name",
                                "params": {
                                    "nodeId": "TEXT:2",
                                    "name": "temporary-name",
                                },
                            },
                        ],
                    },
                    "clientId": "readback-client",
                    "requestId": "readback-request",
                }
            )

            crashed_hub = BridgeHub(
                timeout=30,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            crashed_plugin = FakeSocket()
            crashed_client = FakeSocket()
            await crashed_hub.attach_plugin(crashed_plugin)
            crashed_task = asyncio.create_task(
                crashed_hub.command(crashed_client, request)
            )
            await _wait_until(lambda: len(crashed_plugin.sent) == 1)
            crashed_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await crashed_task
            crashed_hub.close()

            restarted_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            restarted_plugin = FakeSocket()
            await restarted_hub.attach_plugin(restarted_plugin)
            for index in range(2):
                await _wait_until(lambda: len(restarted_plugin.sent) == index + 1)
                outgoing = restarted_plugin.sent[index]
                self.assertEqual(outgoing["action"], "get_node_tree")
                node_id = outgoing["params"]["nodeId"]
                result = {"id": node_id, "type": "TEXT"}
                if node_id == "TEXT:1":
                    result["characters"] = "temporary"
                else:
                    result["name"] = "temporary-name"
                await restarted_hub.plugin_message(
                    json.dumps(
                        {
                            "type": "response",
                            "requestId": outgoing["requestId"],
                            "result": result,
                        }
                    )
                )
            await _wait_until(
                lambda: restarted_hub.transactions["tx-readback"].readback is not None
            )

            status_client = FakeSocket()
            await restarted_hub.command(
                status_client,
                json.dumps(
                    {
                        "action": "bridge_transaction_status",
                        "params": {"transactionId": "tx-readback"},
                        "requestId": "status-request",
                    }
                ),
            )
            transaction = status_client.sent[0]["result"]["transaction"]
            self.assertEqual(transaction["state"], "unknown")
            self.assertEqual(
                transaction["reconciliationTargets"],
                ["TEXT:1", "TEXT:2"],
            )
            self.assertEqual(
                transaction["readback"]["TEXT:1"]["characters"],
                "temporary",
            )
            self.assertEqual(
                transaction["reconciliation"]["classification"],
                "matches-intended",
            )
            self.assertEqual(
                transaction["reconciliation"]["matched"],
                2,
            )
            restarted_hub.close()

            replayed_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            self.addCleanup(replayed_hub.close)
            self.assertEqual(
                replayed_hub.transactions["tx-readback"].readback["TEXT:2"]["name"],
                "temporary-name",
            )

    async def test_unknown_create_batch_reads_back_ownership_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            transaction_id = build_job_namespace(
                "ownership-readback-client",
                "tx-create-readback",
            )
            request = json.dumps(
                {
                    "action": "apply_batch",
                    "params": {
                        "transactionId": transaction_id,
                        "actions": [
                            {
                                "action": "create_frame",
                                "params": {"name": "Owned root"},
                            },
                            {
                                "action": "create_rectangle",
                                "params": {"name": "Owned child"},
                            },
                        ],
                    },
                    "clientId": "ownership-readback-client",
                    "requestId": "ownership-readback-request",
                }
            )
            crashed_hub = BridgeHub(
                timeout=30,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            crashed_plugin = FakeSocket()
            await crashed_hub.attach_plugin(crashed_plugin)
            crashed_task = asyncio.create_task(
                crashed_hub.command(FakeSocket(), request)
            )
            await _wait_until(lambda: len(crashed_plugin.sent) == 1)
            crashed_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await crashed_task
            crashed_hub.close()

            restarted_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            restarted_plugin = FakeSocket()
            await restarted_hub.attach_plugin(restarted_plugin)
            await _wait_until(lambda: len(restarted_plugin.sent) == 1)
            outgoing = restarted_plugin.sent[0]
            self.assertEqual(outgoing["action"], "ownership_report")
            self.assertEqual(outgoing["params"]["jobId"], transaction_id)
            await restarted_hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": outgoing["requestId"],
                        "result": {
                            "status": "reported",
                            "jobId": transaction_id,
                            "owner": "figma_auto_agent",
                            "matched": 2,
                            "nodes": [
                                {"nodeId": "FRAME:1"},
                                {"nodeId": "RECTANGLE:2"},
                            ],
                        },
                    }
                )
            )
            await _wait_until(
                lambda: restarted_hub.transactions[
                    transaction_id
                ].ownership_readback
                is not None
            )

            status_client = FakeSocket()
            await restarted_hub.command(
                status_client,
                json.dumps(
                    {
                        "action": "bridge_transaction_status",
                        "params": {"transactionId": transaction_id},
                        "clientId": "ownership-readback-client",
                        "requestId": "ownership-status-request",
                    }
                ),
            )
            transaction = status_client.sent[0]["result"]["transaction"]
            self.assertEqual(transaction["state"], "unknown")
            self.assertEqual(transaction["ownershipJobId"], transaction_id)
            self.assertEqual(transaction["expectedCreatedNodes"], 2)
            self.assertEqual(transaction["ownershipReadback"]["matched"], 2)
            self.assertEqual(
                transaction["ownershipReconciliation"]["classification"],
                "matches-intended",
            )
            restarted_hub.close()

            replayed_hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            self.addCleanup(replayed_hub.close)
            self.assertEqual(
                replayed_hub.transactions[transaction_id].ownership_readback[
                    "matched"
                ],
                2,
            )

    async def test_same_raw_job_id_is_isolated_across_clients_after_replay(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            first_job = build_job_namespace("client-a", "shared-raw")
            second_job = build_job_namespace("client-b", "shared-raw")
            hub = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
                write_min_interval=0,
            )
            plugin = FakeSocket()
            await hub.attach_plugin(plugin)
            first = asyncio.create_task(
                hub.command(
                    FakeSocket(),
                    json.dumps(
                        {
                            "action": "apply_batch",
                            "params": {
                                "transactionId": first_job,
                                "actions": [
                                    {
                                        "action": "create_frame",
                                        "params": {"name": "A"},
                                    }
                                ],
                            },
                            "clientId": "client-a",
                            "requestId": "shared-request",
                        }
                    ),
                )
            )
            second = asyncio.create_task(
                hub.command(
                    FakeSocket(),
                    json.dumps(
                        {
                            "action": "apply_batch",
                            "params": {
                                "transactionId": second_job,
                                "actions": [
                                    {
                                        "action": "create_frame",
                                        "params": {"name": "B"},
                                    }
                                ],
                            },
                            "clientId": "client-b",
                            "requestId": "shared-request",
                        }
                    ),
                )
            )

            for index, transaction_id in enumerate((first_job, second_job)):
                await _wait_until(lambda: len(plugin.sent) == index + 1)
                outgoing = plugin.sent[index]
                self.assertEqual(outgoing["params"]["transactionId"], transaction_id)
                await hub.plugin_message(
                    json.dumps(
                        {
                            "type": "response",
                            "requestId": outgoing["requestId"],
                            "result": {
                                "status": "committed",
                                "transactionId": transaction_id,
                                "committed": [],
                            },
                        }
                    )
                )
            await asyncio.gather(first, second)
            self.assertNotEqual(
                plugin.sent[0]["requestId"],
                plugin.sent[1]["requestId"],
            )
            hub.close()

            replayed = BridgeHub(
                timeout=2,
                idempotency_ttl=60,
                journal_path=journal_path,
            )
            self.addCleanup(replayed.close)
            self.assertEqual(replayed.transactions[first_job].client_id, "client-a")
            self.assertEqual(replayed.transactions[second_job].client_id, "client-b")
            self.assertEqual(
                replayed.transactions[first_job].state,
                "committed",
            )
            self.assertEqual(
                replayed.transactions[second_job].state,
                "committed",
            )

    async def test_command_requires_configured_bearer_token(self) -> None:
        hub = BridgeHub(timeout=2, auth_token="secret-token")
        plugin = FakeSocket()
        client = AuthSocket()
        await hub.attach_plugin(plugin)

        await hub.command(
            client,
            json.dumps(
                {
                    "action": "write",
                    "params": {"value": 1},
                }
            ),
        )

        self.assertEqual(plugin.sent, [])
        self.assertEqual(client.sent[0]["code"], "UNAUTHORIZED")

    async def test_command_rejects_wrong_bearer_token(self) -> None:
        hub = BridgeHub(timeout=2, auth_token="secret-token")
        plugin = FakeSocket()
        client = AuthSocket("Bearer wrong-token")
        await hub.attach_plugin(plugin)

        await hub.command(
            client,
            json.dumps(
                {
                    "action": "write",
                    "params": {"value": 1},
                }
            ),
        )

        self.assertEqual(plugin.sent, [])
        self.assertEqual(client.sent[0]["code"], "UNAUTHORIZED")

    async def test_command_accepts_matching_bearer_token(self) -> None:
        hub = BridgeHub(timeout=2, auth_token="secret-token")
        plugin = FakeSocket()
        client = AuthSocket("Bearer secret-token")
        await hub.attach_plugin(plugin)
        task = asyncio.create_task(
            hub.command(
                client,
                json.dumps(
                    {
                        "action": "write",
                        "params": {"value": 1},
                    }
                ),
            )
        )
        await _wait_until(lambda: len(plugin.sent) == 1)
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[0]["requestId"],
                    "result": {"written": True},
                }
            )
        )
        await task

        self.assertEqual(client.sent[0]["result"], {"written": True})

    async def test_configured_client_identity_rejects_missing_credentials(
        self,
    ) -> None:
        hub = BridgeHub(timeout=2, client_tokens={"client-a": "token-a"})
        plugin = FakeSocket()
        client = AuthSocket()
        await hub.attach_plugin(plugin)

        await hub.command(
            client,
            json.dumps(
                {
                    "action": "get_node_tree",
                    "params": {"nodeId": "1:1"},
                    "clientId": "client-a",
                }
            ),
        )

        self.assertEqual(plugin.sent, [])
        self.assertEqual(client.sent[0]["code"], "CLIENT_IDENTITY_REQUIRED")

    async def test_configured_client_identity_rejects_wrong_token(self) -> None:
        hub = BridgeHub(timeout=2, client_tokens={"client-a": "token-a"})
        plugin = FakeSocket()
        client = AuthSocket(
            headers={
                "X-Figma-Client-Id": "client-a",
                "X-Figma-Client-Token": "token-b",
            }
        )
        await hub.attach_plugin(plugin)

        await hub.command(
            client,
            json.dumps(
                {
                    "action": "get_node_tree",
                    "params": {"nodeId": "1:1"},
                    "clientId": "client-a",
                }
            ),
        )

        self.assertEqual(plugin.sent, [])
        self.assertEqual(client.sent[0]["code"], "CLIENT_IDENTITY_INVALID")

    async def test_configured_client_identity_rejects_header_payload_mismatch(
        self,
    ) -> None:
        hub = BridgeHub(timeout=2, client_tokens={"client-a": "token-a"})
        plugin = FakeSocket()
        client = AuthSocket(
            headers={
                "X-Figma-Client-Id": "client-b",
                "X-Figma-Client-Token": "token-a",
            }
        )
        await hub.attach_plugin(plugin)

        await hub.command(
            client,
            json.dumps(
                {
                    "action": "apply_batch",
                    "params": {
                        "transactionId": build_job_namespace(
                            "client-a",
                            "spoofed-job",
                        ),
                        "actions": [],
                    },
                    "clientId": "client-a",
                }
            ),
        )

        self.assertEqual(plugin.sent, [])
        self.assertEqual(client.sent[0]["code"], "CLIENT_IDENTITY_MISMATCH")

    async def test_configured_client_identity_accepts_bound_token(self) -> None:
        hub = BridgeHub(timeout=2, client_tokens={"client-a": "token-a"})
        plugin = FakeSocket()
        client = AuthSocket(
            headers={
                "X-Figma-Client-Id": "client-a",
                "X-Figma-Client-Token": "token-a",
            }
        )
        await hub.attach_plugin(plugin)
        task = asyncio.create_task(
            hub.command(
                client,
                json.dumps(
                    {
                        "action": "get_node_tree",
                        "params": {"nodeId": "1:1"},
                        "clientId": "client-a",
                        "requestId": "client-auth-read",
                    }
                ),
            )
        )
        await _wait_until(lambda: len(plugin.sent) == 1)
        await hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": plugin.sent[0]["requestId"],
                    "result": {"id": "1:1"},
                }
            )
        )
        await task

        self.assertEqual(client.sent[0]["result"], {"id": "1:1"})

    async def test_client_identity_token_is_not_written_to_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "bridge-journal.jsonl"
            hub = BridgeHub(
                timeout=2,
                journal_path=journal_path,
                client_tokens={"client-a": "client-secret-a"},
            )
            plugin = FakeSocket()
            client = AuthSocket(
                headers={
                    "X-Figma-Client-Id": "client-a",
                    "X-Figma-Client-Token": "client-secret-a",
                }
            )
            await hub.attach_plugin(plugin)
            task = asyncio.create_task(
                hub.command(
                    client,
                    json.dumps(
                        {
                            "action": "get_node_tree",
                            "params": {"nodeId": "1:1"},
                            "clientId": "client-a",
                            "requestId": "secure-read",
                        }
                    ),
                )
            )
            await _wait_until(lambda: len(plugin.sent) == 1)
            await hub.plugin_message(
                json.dumps(
                    {
                        "type": "response",
                        "requestId": plugin.sent[0]["requestId"],
                        "result": {"id": "1:1"},
                    }
                )
            )
            await task

            journal = journal_path.read_text(encoding="utf-8")
            self.assertNotIn("client-secret-a", journal)
            self.assertIn("client-a", journal)

    async def test_expected_checks_hash_sensitive_values(self) -> None:
        hub = BridgeHub(timeout=2)
        checks = hub._expected_checks(
            "apply_edit_batch",
            {
                "transactionId": "tx-sensitive",
                "actions": [
                    {
                        "action": "set_text",
                        "params": {
                            "nodeId": "TEXT:1",
                            "text": "private text",
                        },
                    },
                    {
                        "action": "set_name",
                        "params": {
                            "nodeId": "TEXT:1",
                            "name": "private name",
                        },
                    },
                    {
                        "action": "set_visibility",
                        "params": {
                            "nodeId": "TEXT:1",
                            "visible": False,
                        },
                    },
                ],
            },
        )

        encoded = json.dumps(checks)
        self.assertNotIn("private text", encoded)
        self.assertNotIn("private name", encoded)
        self.assertEqual(len(checks[0]["expectedSha256"]), 64)
        self.assertEqual(len(checks[1]["expectedSha256"]), 64)
        self.assertIs(checks[2]["expectedValue"], False)

    async def test_reconciliation_classifies_partial_intent_match(self) -> None:
        hub = BridgeHub(timeout=2)
        checks = (
            {
                "nodeId": "TEXT:1",
                "action": "set_text",
                "property": "characters",
                "expectedSha256": hub._sha256_text("intended"),
            },
            {
                "nodeId": "TEXT:1",
                "action": "set_visibility",
                "property": "visible",
                "expectedValue": True,
            },
        )

        reconciliation = hub._evaluate_expected_checks(
            checks,
            {"TEXT:1": {"characters": "intended", "visible": False}},
        )

        self.assertEqual(reconciliation["classification"], "partial-match")
        self.assertEqual(reconciliation["matched"], 1)
        self.assertEqual(reconciliation["mismatched"], 1)

    async def test_real_websocket_round_trip_correlates_response(self) -> None:
        hub = BridgeHub(timeout=2)

        async def plugin_handler(websocket) -> None:
            await hub.attach_plugin(websocket)
            try:
                async for message in websocket:
                    await hub.plugin_message(str(message))
            finally:
                await hub.detach_plugin(websocket, reason="test-close")

        async def command_handler(websocket) -> None:
            async for message in websocket:
                await hub.command(websocket, str(message))

        async def route(websocket) -> None:
            if websocket.request.path == "/command":
                await command_handler(websocket)
            else:
                await plugin_handler(websocket)

        async with websockets.serve(route, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with (
                websockets.connect(
                    f"ws://127.0.0.1:{port}",
                ) as plugin,
                websockets.connect(
                    f"ws://127.0.0.1:{port}/command",
                ) as client,
            ):
                command = asyncio.create_task(
                    client.send(
                        json.dumps(
                            {
                                "action": "round_trip",
                                "params": {"value": 7},
                                "clientId": "real-socket-client",
                                "requestId": "real-request",
                            }
                        )
                    )
                )
                await command
                outgoing = json.loads(
                    await asyncio.wait_for(
                        plugin.recv(),
                        timeout=2,
                    )
                )
                await plugin.send(
                    json.dumps(
                        {
                            "type": "response",
                            "requestId": outgoing["requestId"],
                            "result": {"value": outgoing["params"]["value"]},
                        }
                    )
                )
                incoming = json.loads(
                    await asyncio.wait_for(
                        client.recv(),
                        timeout=2,
                    )
                )

        self.assertEqual(incoming["requestId"], "real-request")
        self.assertEqual(incoming["result"], {"value": 7})


class BridgeMessageLimitTests(unittest.TestCase):
    def test_transport_limit_includes_headroom_over_application_limit(self) -> None:
        self.assertEqual(
            websocket_frame_limit(1_048_576),
            1_048_576 + 65_536,
        )

    def test_default_hub_accepts_observed_large_image_message(self) -> None:
        hub = BridgeHub()
        self.assertGreater(hub.max_message_bytes, 1_049_242)


if __name__ == "__main__":
    unittest.main()
