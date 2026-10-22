"""Local wss handshake probe for the configured bridge TLS contract."""

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
from datetime import timezone
from pathlib import Path
from typing import Any

import websockets
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.bridge_config import BridgeTlsServerConfig  # noqa: E402
from src.app.services.bridge_server import _server_ssl_context  # noqa: E402


def _certificate_and_key(directory: Path) -> tuple[Path, Path, str]:
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
    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    cert_path.write_bytes(cert_bytes)
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    fingerprint = x509.Certificate.fingerprint(certificate, hashes.SHA256()).hex()
    return cert_path, key_path, fingerprint


async def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        cert_path, key_path, fingerprint = _certificate_and_key(Path(temp_dir))
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

        async def echo(websocket) -> None:
            await websocket.send(await websocket.recv())

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
                await client.send("r5-p3-tls")
                round_trip = await client.recv() == "r5-p3-tls"

        checks = {
            "handshake": True,
            "round_trip": round_trip,
            "certificate_sha256": fingerprint,
        }
        report: dict[str, Any] = {
            "schema_version": "r5-p3-tls/1.0",
            "experiment": "R5-P3-TLS",
            "generated_at": dt.datetime.now(timezone.utc).isoformat(),
            "status": "pass" if checks["round_trip"] else "fail",
            "checks": checks,
            "boundary": {
                "local_loopback": True,
                "system_ca": False,
                "plugin_authentication": False,
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
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run_probe())
    path = out / "r5_p3_tls_probe.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"[r5-p3-tls] {report['status']}")
    print(f"[out ] {path}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
