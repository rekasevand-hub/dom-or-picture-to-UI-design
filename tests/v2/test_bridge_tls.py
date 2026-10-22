from __future__ import annotations

import datetime as dt
import ipaddress
import json
import ssl
import tempfile
import unittest
from pathlib import Path

import websockets
from websockets.exceptions import ConnectionClosed
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from src.app.services.bridge_config import (
    BridgeTlsServerConfig,
    load_bridge_config,
)
from src.app.services.bridge_server import BridgeHub
from src.app.services.bridge_server import _server_ssl_context
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter


def _write_test_certificate(directory: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]
    )
    now = dt.datetime.now(dt.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = directory / "server.crt"
    key_path = directory / "server.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class BridgeTlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_tls_plugin_auth_round_trip_and_token_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cert_path, key_path = _write_test_certificate(Path(temp_dir))
            server_ssl = _server_ssl_context(
                BridgeTlsServerConfig(
                    enabled=True,
                    certfile=cert_path,
                    keyfile=key_path,
                    ca_file=None,
                    require_client_cert=False,
                )
            )
            client_ssl = ssl.create_default_context(cafile=str(cert_path))
            current_token = {"value": "plugin-old"}
            hub = BridgeHub(
                timeout=2,
                plugin_token_provider=lambda: current_token["value"],
                plugin_token_recheck_seconds=0.01,
            )

            async def route(websocket) -> None:
                if websocket.request.path == "/plugin":
                    if not await hub.authenticate_plugin(websocket):
                        return
                    await hub.attach_plugin(websocket)
                    try:
                        try:
                            async for message in websocket:
                                await hub.plugin_message(str(message))
                        except ConnectionClosed:
                            pass
                    finally:
                        await hub.detach_plugin(
                            websocket,
                            reason="test plugin closed",
                        )
                    return
                async for message in websocket:
                    await hub.command(websocket, str(message))

            async def exchange(plugin, command, request_id: str) -> None:
                await command.send(
                    json.dumps(
                        {
                            "action": "get_node_tree",
                            "params": {"nodeId": "1:1"},
                            "clientId": "client-a",
                            "requestId": request_id,
                        }
                    )
                )
                outgoing = json.loads(await plugin.recv())
                await plugin.send(
                    json.dumps(
                        {
                            "type": "response",
                            "requestId": outgoing["requestId"],
                            "result": {"id": "1:1"},
                        }
                    )
                )
                incoming = json.loads(await command.recv())
                self.assertEqual(incoming["result"], {"id": "1:1"})

            async with websockets.serve(
                route,
                "127.0.0.1",
                0,
                ssl=server_ssl,
            ) as server:
                port = server.sockets[0].getsockname()[1]
                async with (
                    websockets.connect(
                        f"wss://127.0.0.1:{port}/plugin",
                        ssl=client_ssl,
                    ) as plugin,
                    websockets.connect(
                        f"wss://127.0.0.1:{port}/command",
                        ssl=client_ssl,
                    ) as command,
                ):
                    await plugin.send(
                        json.dumps(
                            {
                                "type": "auth",
                                "token": "plugin-old",
                            }
                        )
                    )
                    self.assertEqual(
                        json.loads(await plugin.recv())["type"],
                        "auth-ok",
                    )
                    await exchange(plugin, command, "tls-auth-first")
                    current_token["value"] = "plugin-new"
                    with self.assertRaises(ConnectionClosed):
                        await plugin.recv()

                async with (
                    websockets.connect(
                        f"wss://127.0.0.1:{port}/plugin",
                        ssl=client_ssl,
                    ) as plugin,
                    websockets.connect(
                        f"wss://127.0.0.1:{port}/command",
                        ssl=client_ssl,
                    ) as command,
                ):
                    await plugin.send(
                        json.dumps(
                            {
                                "type": "auth",
                                "token": "plugin-new",
                            }
                        )
                    )
                    self.assertEqual(
                        json.loads(await plugin.recv())["type"],
                        "auth-ok",
                    )
                    await exchange(plugin, command, "tls-auth-second")
            hub.close()

    async def test_local_wss_handshake_with_trusted_test_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cert_path, key_path = _write_test_certificate(Path(temp_dir))
            server_tls = BridgeTlsServerConfig(
                enabled=True,
                certfile=cert_path,
                keyfile=key_path,
                ca_file=None,
                require_client_cert=False,
            )
            server_ssl = _server_ssl_context(server_tls)

            async def echo(websocket) -> None:
                message = await websocket.recv()
                await websocket.send(message)

            client_ssl = ssl.create_default_context(cafile=str(cert_path))
            async with websockets.serve(
                echo,
                "127.0.0.1",
                0,
                ssl=server_ssl,
            ) as server:
                port = server.sockets[0].getsockname()[1]
                async with websockets.connect(
                    f"wss://127.0.0.1:{port}",
                    ssl=client_ssl,
                ) as client:
                    await client.send("tls-ok")
                    self.assertEqual(await client.recv(), "tls-ok")

    def test_adapter_uses_wss_and_ssl_options_when_tls_enabled(self) -> None:
        calls = []

        class FakeWebSocketModule:
            @staticmethod
            def create_connection(url, **options):
                calls.append((url, options))
                return object()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cert_path, key_path = _write_test_certificate(root)
            payload = {
                "schema_version": "figma-bridge-config/1.0",
                "allow_env_overrides": False,
                "ledger": {
                    "path": "write-jobs.jsonl",
                    "max_events": 128,
                    "terminal_retention_days": 30,
                    "compact_min_events": 16,
                    "allow_legacy_read": False,
                },
                "security": {
                    "require_secret_references": False,
                    "require_secure_file_permissions": False,
                },
                "server": {
                    "host": "127.0.0.1",
                    "port": 8765,
                    "timeout": 30,
                    "idempotency_ttl": 60,
                    "journal_path": "bridge.jsonl",
                    "max_inflight": 8,
                    "max_message_bytes": 4096,
                    "max_params_depth": 6,
                    "max_cache_entries": 32,
                    "max_journal_events": 64,
                    "exclusive_journal_lock": False,
                    "auth_token": "",
                    "plugin_token": "",
                    "plugin_token_recheck_seconds": 0.5,
                    "client_tokens": {},
                    "allow_legacy_job_ids": False,
                    "client_write_defaults": {
                        "max_inflight": 4,
                        "burst": 4,
                        "min_interval_ms": 0,
                    },
                    "client_write_limits": {},
                    "write_pacing": {
                        "min_interval_ms": 0,
                        "queue_timeout_seconds": 1,
                        "max_queue": 4,
                    },
                    "tls": {
                        "enabled": True,
                        "certfile": str(cert_path),
                        "keyfile": str(key_path),
                        "ca_file": "",
                        "require_client_cert": False,
                    },
                },
                "client": {
                    "url": "wss://127.0.0.1:8765",
                    "timeout": 5,
                    "client_id": "",
                    "client_token": "",
                    "auth_token": "",
                    "allow_legacy_job_ids": False,
                    "tls": {
                        "enabled": True,
                        "verify": True,
                        "ca_file": str(cert_path),
                        "certfile": "",
                        "keyfile": "",
                    },
                },
            }
            path = root / "figma_bridge.config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            load_bridge_config(path, environ={})
            adapter = FigmaBridgeAdapter(config_path=path)
            adapter._websocket = FakeWebSocketModule

            adapter.connect()

            self.assertEqual(calls[0][0], "wss://127.0.0.1:8765/command")
            self.assertEqual(calls[0][1]["sslopt"]["ca_certs"], str(cert_path))
            self.assertEqual(calls[0][1]["sslopt"]["cert_reqs"], ssl.CERT_REQUIRED)


if __name__ == "__main__":
    unittest.main()
