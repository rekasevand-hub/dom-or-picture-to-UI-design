"""Deterministic per-client admission and token-bucket fairness probe."""

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
from src.app.services.bridge_config import ClientWriteLimitConfig  # noqa: E402
from src.app.services.bridge_server import BridgeHub  # noqa: E402


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.request = SimpleNamespace(headers={})

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("condition was not reached")
        await asyncio.sleep(0.01)


def _write_request(
    *,
    client_id: str,
    transaction_id: str,
) -> str:
    return json.dumps(
        {
            "action": "apply_edit_batch",
            "params": {
                "transactionId": transaction_id,
                "actions": [],
            },
            "clientId": client_id,
            "requestId": transaction_id,
        }
    )


async def _respond(hub: BridgeHub, plugin: _Socket, index: int) -> None:
    await _wait_until(lambda: len(plugin.sent) == index + 1)
    await hub.plugin_message(
        json.dumps(
            {
                "type": "response",
                "requestId": plugin.sent[index]["requestId"],
                "result": {"status": "committed", "committed": []},
            }
        )
    )


async def _run_admission_scenario() -> tuple[bool, str, bool]:
    with tempfile.TemporaryDirectory() as temp_dir:
        hub = BridgeHub(
            timeout=2,
            write_min_interval=0,
            max_write_queue=4,
            journal_path=Path(temp_dir) / "bridge-journal.jsonl",
            client_write_defaults=ClientWriteLimitConfig(
                max_inflight=1,
                burst=1,
                min_interval_ms=0,
            ),
        )
        plugin = _Socket()
        await hub.attach_plugin(plugin)
        first_a = asyncio.create_task(
            hub.command(
                _Socket(),
                _write_request(
                    client_id="client-a",
                    transaction_id="admission-a-first",
                ),
            )
        )
        await _wait_until(lambda: len(plugin.sent) == 1)

        rejected = _Socket()
        await hub.command(
            rejected,
            _write_request(
                client_id="client-a",
                transaction_id="admission-a-second",
            ),
        )
        rate_limit_code = str(rejected.sent[0].get("code") or "")
        rejected_before_transaction = "admission-a-second" not in hub.transactions

        other = _Socket()
        other_task = asyncio.create_task(
            hub.command(
                other,
                _write_request(
                    client_id="client-b",
                    transaction_id="admission-b-first",
                ),
            )
        )
        await asyncio.sleep(0)
        await _respond(hub, plugin, 0)
        await first_a
        await _respond(hub, plugin, 1)
        await other_task
        other_completed = (
            bool(other.sent)
            and other.sent[0].get("result", {}).get("status") == "committed"
        )
        hub.close()
        return (
            rate_limit_code == "BRIDGE_CLIENT_RATE_LIMITED",
            rate_limit_code,
            other_completed and rejected_before_transaction,
        )


async def _run_burst_scenario() -> bool:
    hub = BridgeHub(
        timeout=2,
        write_min_interval=0,
        max_write_queue=4,
        client_write_defaults=ClientWriteLimitConfig(
            max_inflight=2,
            burst=1,
            min_interval_ms=60,
        ),
    )
    plugin = _Socket()
    await hub.attach_plugin(plugin)
    first = asyncio.create_task(
        hub.command(
            _Socket(),
            _write_request(client_id="client-a", transaction_id="burst-a-first"),
        )
    )
    await _wait_until(lambda: len(plugin.sent) == 1)
    await _respond(hub, plugin, 0)
    await first

    second_a = asyncio.create_task(
        hub.command(
            _Socket(),
            _write_request(client_id="client-a", transaction_id="burst-a-second"),
        )
    )
    first_b = asyncio.create_task(
        hub.command(
            _Socket(),
            _write_request(client_id="client-b", transaction_id="burst-b-first"),
        )
    )
    await _wait_until(lambda: len(plugin.sent) == 2)
    deferred_client_yielded = (
        plugin.sent[1]["params"]["transactionId"] == "burst-b-first"
    )
    await _respond(hub, plugin, 1)
    await first_b
    await _respond(hub, plugin, 2)
    await second_a
    hub.close()
    return deferred_client_yielded


async def run_probe() -> dict[str, Any]:
    limited, rate_limit_code, admission_ok = await _run_admission_scenario()
    deferred = await _run_burst_scenario()
    checks = {
        "rate_limit_code": rate_limit_code,
        "rate_limited": limited,
        "other_client_completed": admission_ok,
        "rejected_before_transaction": admission_ok,
        "burst_client_deferred": deferred,
    }
    passed = (
        checks["rate_limited"]
        and checks["other_client_completed"]
        and checks["rejected_before_transaction"]
        and checks["burst_client_deferred"]
    )
    report: dict[str, Any] = {
        "schema_version": "r5-p3-client-fairness/1.0",
        "experiment": "R5-P3-CLIENT-FAIRNESS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if passed else "fail",
        "checks": checks,
        "boundary": {
            "deterministic": True,
            "real_figma": False,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run_probe())
    path = out / "r5_p3_client_fairness.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"[r5-p3-client-fairness] {report['status']}")
    print(f"[out ] {path}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
