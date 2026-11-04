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


class _TextRenderAdapter(_RecordingAdapter):
    def create_frame(self, spec):
        self.calls.append(("create_frame", dict(spec)))
        return "0:1"

    def create_text(self, spec, parent_id=None):
        self.calls.append(("create_text", dict(spec), parent_id))
        return "0:2"

    def flush(self) -> None:
        pass


class _NativeRenderAdapter(_RecordingAdapter):
    def create_frame(self, spec):
        self.calls.append(("create_frame", dict(spec)))
        return "frame:1"

    def flush(self) -> None:
        pass


class _LayoutRenderAdapter(_RecordingAdapter):
    def __init__(self) -> None:
        super().__init__()
        self._next_id = 0

    def _node_id(self) -> str:
        self._next_id += 1
        return f"node:{self._next_id}"

    def create_frame(self, spec):
        self.calls.append(("create_frame", dict(spec)))
        return self._node_id()

    def create_rectangle(self, spec, parent_id=None):
        self.calls.append(("create_rectangle", dict(spec), parent_id))
        return self._node_id()

    def create_text(self, spec, parent_id=None):
        self.calls.append(("create_text", dict(spec), parent_id))
        return self._node_id()

    def set_autolayout(self, node_id, payload):
        self.calls.append(("set_autolayout", dict(payload)))
        return {"applied": True}

    def flush(self) -> None:
        pass


class FigmaAdapterEditTests(unittest.TestCase):
    def test_multiline_rich_text_falls_back_to_wrapped_plain_lines(self) -> None:
        adapter = _TextRenderAdapter()
        text = "这是一段很长的富文本内容，" * 12
        design = {
            "canvas": {"width": 300, "height": 120, "background": "#ffffff"},
            "elements": [
                {
                    "id": "long-rich",
                    "type": "text",
                    "text": text,
                    "x": 10,
                    "y": 10,
                    "width": 140,
                    "height": 48,
                    "textEmLines": 20,
                    "clipToBounds": True,
                    "richRuns": [
                        {
                            "start": 0,
                            "end": len(text),
                            "text": text,
                            "style": {"fontSize": "14px", "fontWeight": "700"},
                        }
                    ],
                    "style": {
                        "fontFamily": "Arial",
                        "fontSize": 14,
                        "lineHeight": 24,
                        "maxLines": 2,
                        "textColor": "#252933",
                    },
                }
            ],
        }

        adapter.render_design(design)

        text_spec = next(
            params
            for action, params, *_rest in adapter.calls
            if action == "create_text"
        )
        self.assertEqual(len(text_spec["lines"]), 2)
        self.assertTrue(text_spec["lines"][-1].endswith("…"))
        self.assertFalse(text_spec.get("richRuns"))
        self.assertTrue(text_spec["boundedText"])

    def test_none_layout_frame_does_not_send_autolayout_command(self) -> None:
        adapter = _LayoutRenderAdapter()
        design = {
            "canvas": {"width": 200, "height": 120, "background": "#ffffff"},
            "elements": [
                {
                    "id": "parent",
                    "type": "container",
                    "x": 10,
                    "y": 10,
                    "width": 120,
                    "height": 60,
                    "text": "",
                    "style": {"fillColor": "#ffffff"},
                    "layout": {"mode": "NONE", "itemSpacing": 0},
                    "layoutChildren": [{"id": "child"}],
                },
                {
                    "id": "child",
                    "type": "text",
                    "x": 16,
                    "y": 16,
                    "width": 80,
                    "height": 20,
                    "text": "Child",
                    "style": {"fontSize": 14, "textColor": "#333333"},
                },
            ],
        }

        adapter.render_design(design)

        self.assertFalse(
            any(action == "set_autolayout" for action, *_rest in adapter.calls)
        )

    def test_multi_run_single_line_keeps_element_origin(self) -> None:
        adapter = _TextRenderAdapter()
        design = {
            "canvas": {"width": 200, "height": 80, "background": "#ffffff"},
            "elements": [
                {
                    "id": "plus",
                    "type": "text",
                    "text": "Plus 会员",
                    "x": 1361,
                    "y": 15,
                    "width": 56,
                    "height": 19,
                    "textEmBox": [1385, 15, 32, 19],
                    "textEmLines": 1,
                    "richRuns": [
                        {
                            "start": 0,
                            "end": 4,
                            "text": "Plus",
                            "style": {"fontSize": "14px"},
                        },
                        {
                            "start": 4,
                            "end": 7,
                            "text": " 会员",
                            "style": {"fontSize": "14px"},
                        },
                    ],
                    "style": {
                        "fontFamily": "Arial",
                        "fontSize": 14,
                        "textColor": "#ffa116",
                    },
                }
            ],
        }

        adapter.render_design(design)

        text_spec = next(
            params
            for action, params, *_rest in adapter.calls
            if action == "create_text"
        )
        self.assertEqual(text_spec["x"], 1361)
        self.assertEqual(text_spec["y"], 15)
        self.assertTrue(text_spec["singleLine"])

    def test_single_line_text_uses_measured_x_and_disables_bounded_wrap(
        self,
    ) -> None:
        adapter = _TextRenderAdapter()
        design = {
            "canvas": {"width": 200, "height": 80, "background": "#ffffff"},
            "elements": [
                {
                    "id": "tag-label",
                    "type": "text",
                    "text": "相关标签",
                    "x": 70,
                    "y": 152,
                    "width": 82,
                    "height": 24,
                    "textEmBox": [96, 156, 48, 16],
                    "textEmLines": 1,
                    "singleLine": True,
                    "lines": ["相关标", "签"],
                    "richRuns": [
                        {
                            "start": 0,
                            "end": 4,
                            "text": "相关标签",
                            "style": {"fontSize": "12px"},
                        }
                    ],
                    "style": {
                        "fillColor": "#f0f0f0",
                        "fontFamily": "Arial",
                        "fontSize": 12,
                        "lineHeight": 16,
                        "textColor": "#18181b",
                    },
                }
            ],
        }

        adapter.render_design(design)

        text_spec = next(
            params
            for action, params, *_rest in adapter.calls
            if action == "create_text"
        )
        self.assertEqual(text_spec["x"], 96)
        self.assertEqual(text_spec["y"], 156)
        self.assertTrue(text_spec["singleLine"])
        self.assertNotIn("lines", text_spec)
        self.assertFalse(text_spec.get("boundedText", False))

    def test_single_line_text_uses_measured_line_box_without_css_line_height(
        self,
    ) -> None:
        adapter = _TextRenderAdapter()
        design = {
            "canvas": {"width": 500, "height": 120, "background": "#ffffff"},
            "elements": [
                {
                    "id": "footer",
                    "type": "text",
                    "text": "Copyright",
                    "x": 135,
                    "y": 51,
                    "width": 300,
                    "height": 30,
                    "textEmBox": [190, 56, 120, 19],
                    "textEmLines": 1,
                    "style": {
                        "fontFamily": "Arial",
                        "fontSize": 14,
                        "lineHeight": 30,
                        "textAlign": "center",
                        "textColor": "#999999",
                    },
                }
            ],
        }

        adapter.render_design(design)

        text_spec = adapter.calls[-1][1]
        self.assertEqual(text_spec["y"], 56)
        self.assertNotIn("lineHeight", text_spec)

    def test_multi_line_text_keeps_css_line_height_and_element_origin(
        self,
    ) -> None:
        adapter = _TextRenderAdapter()
        design = {
            "canvas": {"width": 500, "height": 120, "background": "#ffffff"},
            "elements": [
                {
                    "id": "summary",
                    "type": "text",
                    "text": "first\\nsecond",
                    "x": 20,
                    "y": 30,
                    "width": 200,
                    "height": 38,
                    "textEmBox": [20, 30, 190, 34],
                    "textEmLines": 2,
                    "style": {
                        "fontFamily": "Arial",
                        "fontSize": 12,
                        "lineHeight": 18,
                        "textAlign": "start",
                        "textColor": "#333333",
                    },
                }
            ],
        }

        adapter.render_design(design)

        text_spec = adapter.calls[-1][1]
        self.assertEqual(text_spec["y"], 30)
        self.assertEqual(text_spec["lineHeight"], 18)

    def test_measured_multiline_text_keeps_expanded_element_origin(self) -> None:
        adapter = _TextRenderAdapter()
        design = {
            "canvas": {"width": 1100, "height": 500, "background": "#ffffff"},
            "elements": [
                {
                    "id": "heading",
                    "type": "text",
                    "text": "Add interactivity wherever you need it",
                    "x": 432,
                    "y": 2884,
                    "width": 576,
                    "height": 127,
                    "textEmBox": [513, 2884, 413, 67],
                    "textEmLines": 2,
                    "measuredLines": [
                        {
                            "text": "Add interactivity",
                            "box": [513, 2884, 413, 67],
                        },
                        {
                            "text": "wherever you need it",
                            "box": [465, 2944, 510, 67],
                        },
                    ],
                    "style": {
                        "fontFamily": "Arial",
                        "fontSize": 52,
                        "lineHeight": 59,
                        "textAlign": "center",
                        "textColor": "#23272f",
                    },
                }
            ],
        }

        adapter.render_design(design)

        text_spec = adapter.calls[-1][1]
        self.assertEqual(text_spec["x"], 432)
        self.assertEqual(text_spec["y"], 2884)
        self.assertEqual(text_spec["width"], 576)
        self.assertEqual(
            text_spec["lines"],
            ["Add interactivity", "wherever you need it"],
        )

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

    def test_compensation_removes_only_scope_nodes_and_keeps_incomplete_manual(
        self,
    ) -> None:
        scope = CompensationScope(
            job_id="job-a",
            region_id="region-1",
            node_ids=("1:1", "1:2"),
            user_takeover_state="none",
        )
        plan = plan_region_compensation(
            scope,
            owned_nodes={
                "1:1": {
                    "job_id": "job-a",
                    "region_id": "region-1",
                    "owner": "figma_auto_agent",
                },
                "1:2": {
                    "job_id": "job-b",
                    "region_id": "region-1",
                    "owner": "figma_auto_agent",
                },
                "1:3": {
                    "job_id": "job-a",
                    "region_id": "region-1",
                    "owner": "figma_auto_agent",
                },
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
                "1:1": {
                    "job_id": "job-a",
                    "region_id": "region-1",
                    "owner": "figma_auto_agent",
                },
                "1:2": {
                    "job_id": "job-a",
                    "region_id": "region-1",
                    "owner": "figma_auto_agent",
                },
            },
        )

        self.assertEqual(plan.remove_node_ids, ("1:1",))
        self.assertEqual(plan.preserved_node_ids, ("1:2",))
        self.assertEqual(plan.status, "compensable")
        self.assertEqual(takeover.status, "rollback-incomplete/manual-review")
        self.assertEqual(takeover.remove_node_ids, ())

    def test_compensation_requires_exact_job_owner_and_region_markers(self) -> None:
        scope = CompensationScope(
            job_id="job-a",
            region_id="region-a",
            node_ids=("1:1", "1:2", "1:3"),
            user_takeover_state="none",
        )

        plan = plan_region_compensation(
            scope,
            owned_nodes={
                "1:1": {
                    "job_id": "job-a",
                    "region_id": "region-a",
                    "owner": "figma_auto_agent",
                },
                "1:2": {
                    "job_id": "job-a",
                    "region_id": "region-b",
                    "owner": "figma_auto_agent",
                },
                "1:3": {
                    "job_id": "job-a",
                    "owner": "figma_auto_agent",
                },
            },
        )

        self.assertEqual(plan.status, "rollback-incomplete/manual-review")
        self.assertEqual(plan.remove_node_ids, ())
        self.assertEqual(plan.preserved_node_ids, ("1:2",))
        self.assertEqual(plan.unknown_node_ids, ("1:3",))

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

    def test_native_figma_render_keeps_text_and_image_payload_counts(self) -> None:
        adapter = _NativeRenderAdapter()
        design = {
            "canvas": {"width": 320, "height": 180, "background": "#ffffff"},
            "elements": [
                {
                    "id": "title",
                    "type": "text",
                    "text": "Native title",
                    "x": 10,
                    "y": 10,
                    "width": 140,
                    "height": 24,
                    "style": {"fontSize": 16, "textColor": "#111111"},
                },
                {
                    "id": "hero",
                    "type": "image",
                    "x": 10,
                    "y": 50,
                    "width": 120,
                    "height": 80,
                    "imageBase64": "aW1hZ2UtYnl0ZXM=",
                    "imageMVP": {"generated": True},
                },
            ],
        }

        adapter.render_design(design)

        text_calls = [
            params for action, params in adapter.calls if action == "create_text"
        ]
        image_calls = [
            params for action, params in adapter.calls if action == "create_image"
        ]
        self.assertEqual(text_calls[0]["text"], "Native title")
        self.assertEqual(image_calls[0]["imageBase64"], "aW1hZ2UtYnl0ZXM=")
        report = adapter.native_render_report()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["expected"]["native_text"], 1)
        self.assertEqual(report["actual"]["native_text"], 1)
        self.assertEqual(report["expected"]["image_fills"], 1)
        self.assertEqual(report["actual"]["image_fills"], 1)

    def test_native_figma_render_rejects_full_screenshot_underlay(self) -> None:
        adapter = _NativeRenderAdapter()
        design = {
            "canvas": {"width": 320, "height": 180, "background": "#ffffff"},
            "elements": [
                {
                    "id": "full-underlay",
                    "type": "image",
                    "x": 0,
                    "y": 0,
                    "width": 320,
                    "height": 180,
                    "imageBase64": "aW1hZ2U=",
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "underlay"):
            adapter.render_design(design)

        self.assertEqual(adapter.calls, [])

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
                        "error": ("BRIDGE_WRITE_BACKPRESSURE: write queue is full"),
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

    def test_empty_bridge_response_is_reported_as_unknown_outcome(self) -> None:
        class FakeWebSocket:
            def send(self, message):
                self.request = json.loads(message)

            def recv(self):
                return ""

        adapter = FigmaBridgeAdapter("ws://localhost:8765")
        adapter.ws = FakeWebSocket()

        with self.assertRaises(FigmaBridgeError) as raised:
            adapter.set_text("12:34", "Edited")

        self.assertEqual(raised.exception.code, "BRIDGE_EMPTY_RESPONSE")
        self.assertEqual(raised.exception.outcome, "unknown")
        self.assertIsNone(adapter.ws)

    def test_closed_bridge_connection_is_reported_as_unknown_outcome(self) -> None:
        class ClosedConnection(RuntimeError):
            pass

        class FakeWebSocketModule:
            WebSocketConnectionClosedException = ClosedConnection

        class FakeWebSocket:
            def send(self, message):
                self.request = json.loads(message)

            def recv(self):
                raise ClosedConnection("connection closed")

        adapter = FigmaBridgeAdapter("ws://localhost:8765")
        adapter._websocket = FakeWebSocketModule
        adapter.ws = FakeWebSocket()

        with self.assertRaises(FigmaBridgeError) as raised:
            adapter.set_text("12:34", "Edited")

        self.assertEqual(raised.exception.code, "BRIDGE_DISCONNECTED")
        self.assertEqual(raised.exception.outcome, "unknown")
        self.assertIsNone(adapter.ws)


if __name__ == "__main__":
    unittest.main()
