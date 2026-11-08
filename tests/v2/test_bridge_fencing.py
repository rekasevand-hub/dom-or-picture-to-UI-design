from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.app.services.bridge_server import BridgeHub
from src.app.services.write_lease import WriterLeaseStore
from tests.v2.test_write_lease import MutableClock


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


class RespondingSocket(FakeSocket):
    def __init__(self, hub: BridgeHub) -> None:
        super().__init__()
        self.hub = hub

    async def send(self, message: str) -> None:
        await super().send(message)
        payload = self.sent[-1]
        await self.hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": payload["requestId"],
                    "result": {"status": "committed", "committed": []},
                }
            )
        )


def _write_command(request_id: str = "write-1") -> str:
    return json.dumps(
        {
            "action": "apply_edit_batch",
            "params": {
                "transactionId": request_id,
                "actions": [
                    {
                        "type": "set_visibility",
                        "nodeId": "1:1",
                        "visible": True,
                    }
                ],
            },
            "clientId": "fence-client",
            "requestId": request_id,
        }
    )


class BridgeFencingTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_write_uses_plugin_that_took_over_before_dispatch(
        self,
    ) -> None:
        with TemporaryDirectory() as raw_dir:
            hub = BridgeHub(
                timeout=1,
                journal_path=Path(raw_dir) / "bridge-journal.jsonl",
                write_min_interval=0,
            )
            original_plugin = FakeSocket()
            replacement_plugin = RespondingSocket(hub)
            await hub.attach_plugin(original_plugin)
            client = FakeSocket()
            original_acquire = hub._acquire_write_turn

            async def acquire_then_take_over(client_id: str) -> None:
                await original_acquire(client_id)
                await hub.attach_plugin(replacement_plugin)

            hub._acquire_write_turn = acquire_then_take_over
            try:
                await hub.command(client, _write_command("takeover-queued"))
            finally:
                hub._acquire_write_turn = original_acquire
                hub.close()

        self.assertFalse(client.sent[-1].get("error"))
        self.assertEqual(original_plugin.sent, [])
        self.assertEqual(len(replacement_plugin.sent), 1)

    async def test_expired_lease_blocks_before_intent_or_plugin_send(self) -> None:
        with TemporaryDirectory() as raw_dir:
            clock = MutableClock()
            store = WriterLeaseStore(
                Path(raw_dir) / "writer-lease.json",
                owner_id="bridge-writer",
                ttl_seconds=1,
                clock=clock,
            )
            journal = Path(raw_dir) / "bridge-journal.jsonl"
            hub = BridgeHub(
                timeout=1,
                journal_path=journal,
                writer_lease_store=store,
            )
            plugin = FakeSocket()
            await hub.attach_plugin(plugin)
            client = FakeSocket()
            clock.advance(2)

            await hub.command(client, _write_command())

            self.assertEqual(client.sent[-1]["code"], "WRITER_LEASE_REQUIRED")
            self.assertEqual(plugin.sent, [])
            self.assertFalse(journal.exists())
            self.assertNotIn("write-1", hub.transactions)
            hub.close()

    async def test_journal_append_failure_blocks_plugin_send(self) -> None:
        with TemporaryDirectory() as raw_dir:
            store = WriterLeaseStore(
                Path(raw_dir) / "writer-lease.json",
                owner_id="bridge-writer",
                ttl_seconds=30,
            )
            journal = Path(raw_dir) / "bridge-journal.jsonl"
            hub = BridgeHub(
                timeout=1,
                journal_path=journal,
                writer_lease_store=store,
            )
            plugin = FakeSocket()
            await hub.attach_plugin(plugin)
            client = FakeSocket()

            with patch.object(
                hub,
                "_append_journal_event",
                side_effect=OSError("journal append failed"),
            ):
                await hub.command(client, _write_command("write-journal-fail"))

            self.assertEqual(client.sent[-1]["code"], "COMMAND_FAILED")
            self.assertEqual(plugin.sent, [])
            self.assertNotIn("write-journal-fail", hub.transactions)
            hub.close()

    async def test_unknown_write_is_not_resent_after_plugin_reconnect(self) -> None:
        with TemporaryDirectory() as raw_dir:
            store = WriterLeaseStore(
                Path(raw_dir) / "writer-lease.json",
                owner_id="bridge-writer",
                ttl_seconds=30,
            )
            journal = Path(raw_dir) / "bridge-journal.jsonl"
            hub = BridgeHub(
                timeout=0.01,
                journal_path=journal,
                writer_lease_store=store,
                write_min_interval=0,
            )
            plugin = FakeSocket()
            await hub.attach_plugin(plugin)
            client = FakeSocket()

            await hub.command(client, _write_command("write-unknown"))
            self.assertEqual(client.sent[-1]["code"], "PLUGIN_TIMEOUT")
            self.assertEqual(len(plugin.sent), 1)

            replacement = FakeSocket()
            await hub.attach_plugin(replacement)
            await asyncio.sleep(0.02)

            self.assertEqual(len(plugin.sent), 1)
            self.assertEqual(replacement.sent, [])
            transaction = hub.transactions["write-unknown"]
            self.assertEqual(transaction.state, "unknown")
            hub.close()


if __name__ == "__main__":
    unittest.main()
