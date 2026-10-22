"""Combined wss + plugin-auth + token-rotation reconnect probe."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import ipaddress
import json
import ssl
import sys
import tempfile
from pathlib import Path
from typing import Any

import websockets
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from websockets.exceptions import ConnectionClosed

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.bridge_config import BridgeTlsServerConfig  # noqa: E402
from src.app.services.bridge_server import (  # noqa: E402
    BridgeHub,
    _server_ssl_context,
)


def _certificate(directory: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
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


async def _exchange(plugin, command, request_id: str) -> bool:
    await command.send(
        json.dumps(
            {
                "action": "get_node_tree",
                "params": {"nodeId": "1:1"},
                "clientId": "probe-client",
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
    return incoming.get("result") == {"id": "1:1"}


async def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        cert_path, key_path = _certificate(Path(temp_dir))
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
                    await hub.detach_plugin(websocket, reason="probe closed")
                return
            async for message in websocket:
                await hub.command(websocket, str(message))

        first_round_trip = False
        old_token_revoked = False
        second_round_trip = False
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
                    json.dumps({"type": "auth", "token": "plugin-old"})
                )
                auth_ok = json.loads(await plugin.recv()).get("type") == "auth-ok"
                first_round_trip = await _exchange(
                    plugin,
                    command,
                    "combined-first",
                )
                current_token["value"] = "plugin-new"
                try:
                    await plugin.recv()
                except ConnectionClosed as exc:
                    old_token_revoked = bool(
                        exc.rcvd and exc.rcvd.code == 4004
                    )

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
                    json.dumps({"type": "auth", "token": "plugin-new"})
                )
                auth_new = json.loads(await plugin.recv()).get("type") == "auth-ok"
                second_round_trip = (
                    auth_new
                    and await _exchange(plugin, command, "combined-second")
                )

        checks = {
            "tls_handshake": True,
            "plugin_auth": auth_ok,
            "command_round_trip": first_round_trip and second_round_trip,
            "old_token_revoked": old_token_revoked,
            "new_token_reconnected": second_round_trip,
        }
        passed = all(checks.values())
        report: dict[str, Any] = {
            "schema_version": "r5-p3-tls-plugin-auth/1.0",
            "experiment": "R5-P3-TLS-PLUGIN-AUTH",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "status": "pass" if passed else "fail",
            "checks": checks,
            "boundary": {
                "local_loopback": True,
                "real_figma": False,
                "production_admission": False,
            },
        }
        report["content_hash"] = hashlib.sha256(
            json.dumps(
                report,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        hub.close()
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run_probe())
    path = out / "r5_p3_tls_plugin_auth.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"[r5-p3-tls-plugin-auth] {report['status']}")
    print(f"[out ] {path}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
