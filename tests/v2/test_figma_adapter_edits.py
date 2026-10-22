from __future__ import annotations

import json
import unittest

from src.app.services.job_namespace import (
    JobNamespaceError,
    build_job_namespace,
)
from src.app.services.rendering.figma_adapter import (
    FigmaBridgeAdapter,
    FigmaBridgeError,
    evaluate_expected_region,
    plan_region_compensation,
)
from src.app.services.rendering.write_job_ledger import CompensationScope


class _RecordingAdapter(FigmaBridgeAdapter):
    def __init__(self) -> None:
        self.calls = []
        self.client_id = "adapter-client"
        self.allow_legacy_job_ids = False

    def _send(self, action, params, *, request_id=None):
        self.calls.append((action, params))
        return {"ok": True}


class FigmaAdapterEditTests(unittest.TestCase):
    def test_expected_region_checks_are_independent(self) -> None:
        expected = {
            "imageFillSha256": "a" * 64,
            "layoutSnapshot": {
                "layoutMode": "HORIZONTAL",
                "itemSpacing": 12,
            },
            "bounds": {"x": 10, "y": 20, "width": 100, "height": 40},
            "textRuns": [{"characters": "Title", "fontSize": 20}],
            "regionMembership": True,
        }
        readback = {
            **expected,
            "bounds": {"x": 11, "y": 20, "width": 100, "height": 40},
        }

        result = evaluate_expected_region(expected, readback)

        self.assertEqual(result.classification, "partial-match")
        self.assertEqual(
            result.checks["imageFillSha256"],
            "matched",
        )
        self.assertEqual(result.checks["bounds"], "mismatched")
        self.assertEqual(result.checks["layoutSnapshot"], "matched")

    def test_compensation_removes_only_scope_nodes_and_keeps_incomplete_manual(self) -> None:
        scope = CompensationScope(
            job_id="job-a",
            region_id="region-1",
            node_ids=("1:1", "1:2"),
            user_takeover_state="none",
        )
        plan = plan_region_compensation(
            scope,
            owned_nodes={
                "1:1": {"job_id": "job-a", "owner": "figma_auto_agent"},
                "1:2": {"job_id": "job-b", "owner": "figma_auto_agent"},
                "1:3": {"job_id": "job-a", "owner": "figma_auto_agent"},
            },
        )
        takeover = plan_region_compensation(
            CompensationScope(
                job_id="job-a",
                region_id="region-1",
                node_ids=("1:1", "1:2"),
                user_takeover_state="modified",
            ),
            owned_nodes={
                "1:1": {"job_id": "job-a", "owner": "figma_auto_agent"},
                "1:2": {"job_id": "job-a", "owner": "figma_auto_agent"},
            },
        )

        self.assertEqual(plan.remove_node_ids, ("1:1",))
        self.assertEqual(plan.preserved_node_ids, ("1:2",))
        self.assertEqual(plan.status, "compensable")
        self.assertEqual(takeover.status, "rollback-incomplete/manual-review")
        self.assertEqual(takeover.remove_node_ids, ())

    def test_set_text_targets_explicit_node(self) -> None:
        adapter = _RecordingAdapter()

        result = adapter.set_text("12:34", "Edited")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            adapter.calls,
            [("set_text", {"nodeId": "12:34", "text": "Edited"})],
        )

    def test_replace_image_fill_targets_explicit_node(self) -> None:
        adapter = _RecordingAdapter()

        result = adapter.replace_image_fill(
            "56:78",
            "image-bytes",
            fill_index=0,
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            adapter.calls,
            [
                (
                    "replace_image_fill",
                    {
                        "nodeId": "56:78",
                        "imageBase64": "image-bytes",
                        "fillIndex": 0,
                    },
                )
            ],
        )

    def test_create_image_preserves_parent_id_from_spec(self) -> None:
        adapter = _RecordingAdapter()

        adapter.create_image(
            {
                "name": "Image",
                "parentId": "9:9",
                "width": 10,
                "height": 10,
                "imageBase64": "image-bytes",
            }
        )

        self.assertEqual(adapter.calls[0][0], "create_image")
        self.assertEqual(adapter.calls[0][1]["parentId"], "9:9")

    def test_image_fill_report_targets_explicit_root(self) -> None:
        adapter = _RecordingAdapter()

        result = adapter.image_fill_report("45:67")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            adapter.calls,
            [("image_fill_report", {"nodeId": "45:67"})],
        )

    def test_apply_edit_batch_uses_explicit_transaction_id(self) -> None:
        adapter = _RecordingAdapter()
        actions = [
            {
                "action": "set_text",
                "params": {"nodeId": "12:34", "text": "Edited"},
            }
        ]

        result = adapter.apply_edit_batch(actions, transaction_id="tx-edit")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            adapter.calls,
            [
                (
                    "apply_edit_batch",
                    {"transactionId": "tx-edit", "actions": actions},
                )
            ],
        )

    def test_transaction_status_uses_bridge_local_query(self) -> None:
        adapter = _RecordingAdapter()

        result = adapter.transaction_status("tx-edit")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            adapter.calls,
            [("bridge_transaction_status", {"transactionId": "tx-edit"})],
        )

    def test_cleanup_owned_job_uses_explicit_job_id(self) -> None:
        adapter = _RecordingAdapter()
        job_id = build_job_namespace("adapter-client", "job-123")

        result = adapter.cleanup_owned_job(job_id)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            adapter.calls,
            [("cleanup_owned_job", {"jobId": job_id})],
        )

    def test_ownership_report_uses_explicit_job_id(self) -> None:
        adapter = _RecordingAdapter()
        job_id = build_job_namespace("adapter-client", "job-123")

        result = adapter.ownership_report(job_id)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            adapter.calls,
            [("ownership_report", {"jobId": job_id})],
        )

    def test_ownership_commands_reject_legacy_job_id_by_default(self) -> None:
        adapter = _RecordingAdapter()

        for method in (
            adapter.cleanup_owned_job,
            adapter.ownership_report,
        ):
            with self.subTest(method=method.__name__):
                with self.assertRaises(JobNamespaceError):
                    method("job-123")
        self.assertEqual(adapter.calls, [])

    def test_apply_batch_rejects_legacy_job_id_by_default(self) -> None:
        adapter = _RecordingAdapter()

        with self.assertRaises(JobNamespaceError):
            adapter.apply_batch(
                [{"action": "create_frame", "params": {"name": "Owned"}}],
                transaction_id="legacy-job",
            )

        self.assertEqual(adapter.calls, [])

    def test_apply_batch_rejects_namespace_for_another_client(self) -> None:
        adapter = _RecordingAdapter()
        job_id = build_job_namespace("another-client", "job-123")

        with self.assertRaises(JobNamespaceError):
            adapter.apply_batch([], transaction_id=job_id)

        self.assertEqual(adapter.calls, [])

    def test_apply_batch_uses_bounded_request_id_for_max_namespace(self) -> None:
        class FakeWebSocket:
            def send(self, message):
                self.payload = json.loads(message)

            def recv(self):
                return json.dumps(
                    {
                        "type": "response",
                        "requestId": self.payload["requestId"],
                        "result": {"status": "committed", "committed": []},
                    }
                )

        client_id = "c" * 128
        raw_job_id = "r" * 256
        job_id = build_job_namespace(client_id, raw_job_id)
        adapter = FigmaBridgeAdapter(
            "ws://localhost:8765",
            client_id=client_id,
        )
        adapter.ws = FakeWebSocket()

        adapter.apply_batch([], transaction_id=job_id)

        self.assertEqual(adapter.ws.payload["params"]["transactionId"], job_id)
        self.assertLessEqual(len(adapter.ws.payload["requestId"]), 256)
        self.assertNotEqual(adapter.ws.payload["requestId"], job_id)

    def test_command_connection_sends_bearer_token_header(self) -> None:
        calls = []

        class FakeWebSocketModule:
            @staticmethod
            def create_connection(url, **options):
                calls.append((url, options))
                return object()

        adapter = FigmaBridgeAdapter(
            "ws://localhost:8765",
            auth_token="secret-token",
        )
        adapter._websocket = FakeWebSocketModule

        adapter.connect()

        self.assertEqual(calls[0][0], "ws://localhost:8765/command")
        self.assertEqual(
            calls[0][1]["header"]["Authorization"],
            "Bearer secret-token",
        )

    def test_command_connection_sends_bound_client_identity_headers(self) -> None:
        calls = []

        class FakeWebSocketModule:
            @staticmethod
            def create_connection(url, **options):
                calls.append((url, options))
                return object()

        adapter = FigmaBridgeAdapter(
            "ws://localhost:8765",
            client_id="client-a",
            client_token="client-token-a",
        )
        adapter._websocket = FakeWebSocketModule

        adapter.connect()

        headers = calls[0][1]["header"]
        self.assertEqual(headers["X-Figma-Client-Id"], "client-a")
        self.assertEqual(headers["X-Figma-Client-Token"], "client-token-a")

    def test_client_token_requires_explicit_client_id(self) -> None:
        for client_id in (None, "", "   "):
            with self.subTest(client_id=client_id):
                with self.assertRaises(ValueError):
                    FigmaBridgeAdapter(
                        "ws://localhost:8765",
                        client_id=client_id,
                        client_token="client-token-a",
                    )

    def test_backpressure_error_preserves_code_and_safe_outcome(self) -> None:
        class FakeWebSocket:
            def send(self, message):
                self.request = json.loads(message)

            def recv(self):
                return json.dumps(
                    {
                        "type": "response",
                        "requestId": self.request["requestId"],
                        "error": (
                            "BRIDGE_WRITE_BACKPRESSURE: "
                            "write queue is full"
                        ),
                        "code": "BRIDGE_WRITE_BACKPRESSURE",
                        "outcome": "not-applied",
                        "retryAfterMs": 37,
                    }
                )

        adapter = FigmaBridgeAdapter("ws://localhost:8765")
        adapter.ws = FakeWebSocket()

        with self.assertRaises(FigmaBridgeError) as raised:
            adapter.set_text("12:34", "Edited")

        self.assertEqual(raised.exception.code, "BRIDGE_WRITE_BACKPRESSURE")
        self.assertEqual(raised.exception.outcome, "not-applied")
        self.assertEqual(raised.exception.retry_after_ms, 37)


if __name__ == "__main__":
    unittest.main()
