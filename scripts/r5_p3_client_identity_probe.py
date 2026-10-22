"""Deterministic proof that ownership client identity is token-bound."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.bridge_server import BridgeHub  # noqa: E402
from src.app.services.job_namespace import build_job_namespace  # noqa: E402


CLIENT_ID = "client-a"
CLIENT_SECRET = "probe-client-secret"


class _Socket:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.request = SimpleNamespace(headers=dict(headers or {}))

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("condition was not reached")
        await asyncio.sleep(0.01)


async def _send_rejected(hub: BridgeHub, payload: dict[str, Any], headers=None) -> str:
    client = _Socket(headers)
    await hub.command(client, json.dumps(payload))
    return str(client.sent[0].get("code") or "")


async def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        journal_path = Path(temp_dir) / "bridge-journal.jsonl"
        hub = BridgeHub(
            timeout=2,
            journal_path=journal_path,
            client_tokens={CLIENT_ID: CLIENT_SECRET},
        )
        plugin = _Socket()
        await hub.attach_plugin(plugin)
        base = {
            "action": "get_node_tree",
            "params": {"nodeId": "1:1"},
            "clientId": CLIENT_ID,
        }
        missing = await _send_rejected(hub, base)
        wrong = await _send_rejected(
            hub,
            base,
            headers={
                "X-Figma-Client-Id": CLIENT_ID,
                "X-Figma-Client-Token": "wrong-token",
            },
        )
        mismatch = await _send_rejected(
            hub,
            {
                "action": "apply_batch",
                "params": {
                    "transactionId": build_job_namespace(
                        CLIENT_ID,
                        "spoofed-job",
                    ),
                    "actions": [],
                },
                "clientId": CLIENT_ID,
            },
            headers={
                "X-Figma-Client-Id": "client-b",
                "X-Figma-Client-Token": CLIENT_SECRET,
            },
        )

        valid_client = _Socket(
            {
                "X-Figma-Client-Id": CLIENT_ID,
                "X-Figma-Client-Token": CLIENT_SECRET,
            }
        )
        valid_task = asyncio.create_task(
            hub.command(
                valid_client,
                json.dumps(
                    {
                        **base,
                        "requestId": "identity-probe-valid",
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
        await valid_task

        journal = (
            journal_path.read_text(encoding="utf-8")
            if journal_path.exists()
            else ""
        )
        checks = {
            "missing": missing,
            "wrong": wrong,
            "mismatch": mismatch,
            "valid_completed": (
                bool(valid_client.sent)
                and valid_client.sent[0].get("result") == {"id": "1:1"}
            ),
            "plugin_dispatches": len(plugin.sent),
            "journal_secret_absent": CLIENT_SECRET not in journal,
            "journal_client_present": CLIENT_ID in journal,
        }
        passed = (
            checks["missing"] == "CLIENT_IDENTITY_REQUIRED"
            and checks["wrong"] == "CLIENT_IDENTITY_INVALID"
            and checks["mismatch"] == "CLIENT_IDENTITY_MISMATCH"
            and checks["valid_completed"]
            and checks["plugin_dispatches"] == 1
            and checks["journal_secret_absent"]
            and checks["journal_client_present"]
        )
        report: dict[str, Any] = {
            "schema_version": "r5-p3-client-identity/1.0",
            "experiment": "R5-P3-CLIENT-IDENTITY",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "pass" if passed else "fail",
            "client_id": CLIENT_ID,
            "checks": checks,
            "boundary": {
                "deterministic": True,
                "real_figma": False,
                "transport_tls": False,
                "production_admission": False,
            },
        }
        report["content_hash"] = _content_hash(report)
        return report


def _content_hash(report: dict[str, Any]) -> str:
    payload = {key: value for key, value in report.items() if key != "content_hash"}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run_probe())
    path = out / "r5_p3_client_identity.json"
    _write_report(path, report)
    print(f"[r5-p3-client-identity] {report['status']}")
    print(f"[out ] {path}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
