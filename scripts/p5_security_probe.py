# -*- coding: utf-8 -*-
"""Collect local security-boundary evidence using generated canaries only."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.bridge_server import (  # noqa: E402
    CLIENT_ID_HEADER,
    CLIENT_TOKEN_HEADER,
    BridgeHub,
)
from src.app.services.contracts import canonical_hash  # noqa: E402
from src.app.services.job_namespace import build_job_namespace  # noqa: E402
from src.app.services.structure.backends.grounding_reliability import (  # noqa: E402
    GroundingReliability,
)
from src.app.utils.redaction import redact_sensitive_text  # noqa: E402


CANARY_VALUES = (
    "probe-bearer-canary-7d2a",
    "probe-query-canary-4c1f",
    "probe-client-token-canary-9b8e",
    "probe-action-text-canary-5a3d",
)


class _Socket:
    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        inbound: list[str] | None = None,
    ) -> None:
        self.request = SimpleNamespace(headers=headers or {})
        self.inbound = list(inbound or [])
        self.sent: list[dict[str, Any]] = []
        self.closed_code: int | None = None
        self.closed_reason: str | None = None

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        if not self.inbound:
            raise TimeoutError("no inbound frame")
        return self.inbound.pop(0)

    async def close(self, code=None, reason=None) -> None:
        self.closed_code = code
        self.closed_reason = reason


class _AutoPlugin(_Socket):
    def __init__(self, hub: BridgeHub) -> None:
        super().__init__()
        self.hub = hub
        self.tasks: list[asyncio.Task[None]] = []

    async def send(self, message: str) -> None:
        payload = json.loads(message)
        self.sent.append(payload)
        self.tasks.append(asyncio.create_task(self._respond(payload)))

    async def _respond(self, payload: dict[str, Any]) -> None:
        action = payload.get("action")
        params = payload.get("params") or {}
        if action == "ownership_report":
            result = {
                "status": "reported",
                "jobId": params.get("jobId"),
                "matched": 0,
            }
        elif action == "get_node_tree":
            result = {"id": "security-node", "type": "FRAME", "children": []}
        else:
            result = {"status": "committed"}
        await self.hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": payload.get("requestId"),
                    "result": result,
                }
            )
        )


async def _probe_plugin_auth(hub: BridgeHub) -> bool:
    websocket = _Socket(
        inbound=[json.dumps({"type": "auth", "token": "wrong-plugin-token-canary"})]
    )
    authenticated = await hub.authenticate_plugin(websocket)
    return (
        not authenticated
        and websocket.closed_code == 4003
        and bool(websocket.sent)
        and websocket.sent[-1].get("code") == "PLUGIN_AUTH_FAILED"
    )


async def _probe_command_security() -> dict[str, bool]:
    with tempfile.TemporaryDirectory() as raw_dir:
        hub = BridgeHub(
            timeout=1,
            auth_token=CANARY_VALUES[0],
            client_tokens={"client-a": CANARY_VALUES[2]},
            journal_path=Path(raw_dir) / "journal.jsonl",
            max_message_bytes=256,
            max_params_depth=2,
            write_min_interval=0,
        )
        plugin = _AutoPlugin(hub)
        await hub.attach_plugin(plugin)
        try:
            missing_bearer = _Socket()
            await hub.command(
                missing_bearer,
                json.dumps(
                    {
                        "action": "bridge_transaction_status",
                        "params": {"transactionId": "missing"},
                        "clientId": "client-a",
                    }
                ),
            )
            bearer_ok = missing_bearer.sent[-1].get("code") == "UNAUTHORIZED"

            job_id = build_job_namespace("client-a", "security-job")
            valid_headers = {
                "Authorization": f"Bearer {CANARY_VALUES[0]}",
                CLIENT_ID_HEADER: "client-a",
                CLIENT_TOKEN_HEADER: CANARY_VALUES[2],
            }
            valid = _Socket(headers=valid_headers)
            await hub.command(
                valid,
                json.dumps(
                    {
                        "action": "ownership_report",
                        "params": {"jobId": job_id},
                        "clientId": "client-a",
                        "requestId": "security-valid",
                    }
                ),
            )
            invalid_headers = dict(valid_headers)
            invalid_headers[CLIENT_TOKEN_HEADER] = "wrong-generated-token"
            invalid = _Socket(headers=invalid_headers)
            await hub.command(
                invalid,
                json.dumps(
                    {
                        "action": "ownership_report",
                        "params": {"jobId": job_id},
                        "clientId": "client-a",
                        "requestId": "security-invalid",
                    }
                ),
            )
            client_isolated = (
                not valid.sent[-1].get("error")
                and invalid.sent[-1].get("code") == "CLIENT_IDENTITY_INVALID"
            )

            command_headers = {
                "Authorization": f"Bearer {CANARY_VALUES[0]}",
            }
            oversized = _Socket(headers=command_headers)
            await hub.command(
                oversized,
                json.dumps(
                    {
                        "action": "bridge_transaction_status",
                        "params": {"value": CANARY_VALUES[3] * 40},
                        "clientId": "client-a",
                    }
                ),
            )
            size_bound = oversized.sent[-1].get("code") == "REQUEST_TOO_LARGE"

            deep_client = _Socket(headers=command_headers)
            deep_params = {"transactionId": "missing"}
            cursor = deep_params
            for index in range(5):
                cursor["nested"] = {}
                cursor = cursor["nested"]
                cursor["level"] = index
            await hub.command(
                deep_client,
                json.dumps(
                    {
                        "action": "bridge_transaction_status",
                        "params": deep_params,
                        "clientId": "client-a",
                    }
                ),
            )
            depth_bound = deep_client.sent[-1].get("code") == "PARAMS_TOO_DEEP"
        finally:
            hub.close()
    return {
        "bearer": bearer_ok,
        "client": client_isolated,
        "size": size_bound,
        "depth": depth_bound,
    }


def _grounding_cache_isolated() -> bool:
    def runtime(namespace: str) -> GroundingReliability:
        return GroundingReliability(
            endpoints=("https://grounding.test/v1",),
            model="vision-test",
            cache_namespace=namespace,
        )

    first = runtime("tenant-a")
    second = runtime("tenant-b")
    return first.cache_key(b"image", "prompt") != second.cache_key(b"image", "prompt")


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)

    async def run_async() -> tuple[bool, dict[str, bool]]:
        plugin_hub = BridgeHub(plugin_token=CANARY_VALUES[2], timeout=1)
        try:
            plugin_auth = await _probe_plugin_auth(plugin_hub)
        finally:
            plugin_hub.close()
        return plugin_auth, await _probe_command_security()

    plugin_auth, command = asyncio.run(run_async())
    redacted = redact_sensitive_text(
        "Authorization: Bearer "
        + CANARY_VALUES[0]
        + " https://user:pass@example.test/v1?token="
        + CANARY_VALUES[1]
        + ' "actions":[{"text":"'
        + CANARY_VALUES[3]
        + '"}]'
    )
    logs_redacted = not any(value in redacted for value in CANARY_VALUES)
    cache_isolated = _grounding_cache_isolated()
    checks = [
        {
            "name": "plugin-auth-fail-closed",
            "description": "A wrong generated plugin token is rejected with 4003.",
            "passed": plugin_auth,
        },
        {
            "name": "bearer-auth-fail-closed",
            "description": "A missing generated command bearer token is rejected.",
            "passed": command["bearer"],
        },
        {
            "name": "client-token-isolated",
            "description": "A wrong generated per-client token cannot act as another client.",
            "passed": command["client"],
        },
        {
            "name": "message-size-bound",
            "description": "An oversized generated request fails before dispatch.",
            "passed": command["size"],
        },
        {
            "name": "parameter-depth-bound",
            "description": "Deep generated params fail before dispatch.",
            "passed": command["depth"],
        },
        {
            "name": "logs-redacted",
            "description": "Generated token, URL query and action canaries are redacted.",
            "passed": logs_redacted,
        },
        {
            "name": "grounding-cache-isolated",
            "description": "Grounding cache keys differ by tenant namespace.",
            "passed": cache_isolated,
        },
    ]
    result = {
        "schema_version": "p5-security-probe/1.0",
        "status": (
            "pass-current-scope"
            if all(item["passed"] for item in checks)
            else "blocked"
        ),
        "scope": "generated local security canaries and in-process bridge",
        "code_revision": _code_revision(),
        "plugin_code_sha256": _sha(ROOT / "figma_bridge" / "code.js"),
        "source_hashes": {
            "bridge_server": _sha(ROOT / "src/app/services/bridge_server.py"),
            "redaction": _sha(ROOT / "src/app/utils/redaction.py"),
            "grounding_reliability": _sha(
                ROOT / "src/app/services/structure/backends/grounding_reliability.py"
            ),
        },
        "checks": checks,
        "canary_count": len(CANARY_VALUES),
        "boundary": {
            "real_secrets_read": False,
            "token_source": "generated-canary",
            "real_figma": False,
            "tls_verified_here": False,
            "production_secret_manager": False,
        },
        "non_claims": [
            "production-secret-lifecycle",
            "certificate-provisioning-and-trust",
            "real-plugin-token-revocation",
            "production-admission",
        ],
        "limitations": [
            "Canaries are generated in memory and never persisted.",
            "TLS and plugin UI evidence remain in separate probes.",
            "The probe does not read .env, login state or a real token.",
        ],
    }
    result["content_hash"] = canonical_hash(result)
    _write_json(destination / "result.json", result)
    return result


def _code_revision() -> str:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return revision + ("+dirty" if dirty else "")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    staging.write_text(payload, encoding="utf-8")
    os.replace(staging, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    result = run_probe(args.out)
    print("status=" + result["status"])
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] == "pass-current-scope" else 1


if __name__ == "__main__":
    raise SystemExit(main())
