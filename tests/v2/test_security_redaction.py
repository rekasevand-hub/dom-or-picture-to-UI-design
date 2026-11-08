from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path

from src.app.services.bridge_server import BridgeHub, _message_log_summary
from src.app.utils.redaction import (
    redact_sensitive_text,
    redact_url,
    safe_exception_message,
)


class _Client:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


class _Plugin:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class SecurityRedactionTests(unittest.TestCase):
    def test_redacts_bearer_headers_urls_json_and_action_payloads(self) -> None:
        text = (
            "Authorization: Bearer bearer-canary "
            "url=https://user-canary:password-canary@example.test/v1"
            "?api_key=query-canary&safe=1 "
            'payload={"client_token":"json-canary","plugin_token":"plugin-canary",'
            '"actions":[{"params":{"text":"RAW_TEXT_CANARY"}}]}'
        )

        redacted = redact_sensitive_text(text)

        for canary in (
            "bearer-canary",
            "user-canary",
            "password-canary",
            "query-canary",
            "json-canary",
            "plugin-canary",
            "RAW_TEXT_CANARY",
        ):
            self.assertNotIn(canary, redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_url_redaction_keeps_only_scheme_host_port_path(self) -> None:
        self.assertEqual(
            redact_url(
                "https://user:pass@example.test:8443/v1/models" "?token=canary#fragment"
            ),
            "https://example.test:8443/v1/models",
        )

    def test_safe_exception_message_is_bounded_and_redacted(self) -> None:
        rendered = safe_exception_message(
            RuntimeError("secret-token-canary " + ("x" * 2000))
        )
        self.assertNotIn("secret-token-canary", rendered)
        self.assertLessEqual(len(rendered), 600)

    def test_raw_bridge_frame_log_summary_excludes_payload_and_token(self) -> None:
        summary = _message_log_summary(
            json.dumps(
                {
                    "type": "auth",
                    "token": "frame-token-canary",
                    "requestId": "safe-request-id",
                    "params": {"actions": [{"params": {"text": "frame-text-canary"}}]},
                }
            )
        )
        self.assertIn("type=auth", summary)
        self.assertIn("requestId=safe-request-id", summary)
        self.assertNotIn("frame-token-canary", summary)
        self.assertNotIn("frame-text-canary", summary)
        self.assertNotIn("params", summary)

    def test_bridge_failure_log_does_not_leak_exception_secret(self) -> None:
        capture = _LogCapture()
        logger = logging.getLogger("src.app.services.bridge_server")
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(capture)
        try:
            with tempfile.TemporaryDirectory() as raw_dir:
                hub = BridgeHub(timeout=1, journal_path=Path(raw_dir) / "journal.jsonl")

                async def run_case() -> None:
                    await hub.attach_plugin(_Plugin())
                    client = _Client()
                    original = hub._record_intent

                    def fail(**_kwargs):
                        raise RuntimeError(
                            "Authorization: Bearer secret-token-canary "
                            "https://user:pass@example.test?api_key=query-canary"
                        )

                    hub._record_intent = fail
                    try:
                        await hub.command(
                            client,
                            json.dumps(
                                {
                                    "action": "apply_edit_batch",
                                    "params": {
                                        "transactionId": "redaction-write",
                                        "actions": [],
                                    },
                                    "clientId": "redaction-client",
                                    "requestId": "redaction-request",
                                }
                            ),
                        )
                    finally:
                        hub._record_intent = original
                        hub.close()

                import asyncio

                asyncio.run(run_case())
        finally:
            logger.setLevel(previous_level)
            logger.removeHandler(capture)

        joined = "\n".join(capture.messages)
        self.assertTrue(joined)
        self.assertNotIn("secret-token-canary", joined)
        self.assertNotIn("query-canary", joined)
        self.assertNotIn("user:pass", joined)


if __name__ == "__main__":
    unittest.main()
