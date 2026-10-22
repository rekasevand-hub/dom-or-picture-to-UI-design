"""Run a bounded persistent-journal soak against the real BridgeHub path."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.bridge_server import BridgeHub  # noqa: E402


def build_soak_report(
    *,
    requested: int,
    completed: int,
    failed: int,
    pending: int,
    scope_pending: int,
    cache_entries: int,
    max_cache_entries: int,
    journal_events: int,
    max_journal_events: int,
    replay_cache_entries: int,
    elapsed_seconds: float,
    peak_memory_bytes: int,
) -> dict[str, Any]:
    checks = {
        "all_requests_completed": (
            requested > 0 and completed == requested and failed == 0
        ),
        "pending_cleared": pending == 0,
        "scope_pending_cleared": scope_pending == 0,
        "cache_bounded": 0 <= cache_entries <= max_cache_entries,
        "journal_bounded": 0 < journal_events <= max_journal_events,
        "journal_replay_loaded": 0 < replay_cache_entries <= max_cache_entries,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    requests_per_second = requested / elapsed_seconds if elapsed_seconds > 0 else 0.0
    return {
        "schema_version": "p4-bridge-journal-soak/1.0",
        "experiment": "P4-BRIDGE-JOURNAL-SOAK",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested": requested,
        "completed": completed,
        "failed": failed,
        "pending": pending,
        "scope_pending": scope_pending,
        "cache_entries": cache_entries,
        "max_cache_entries": max_cache_entries,
        "journal_events": journal_events,
        "max_journal_events": max_journal_events,
        "replay_cache_entries": replay_cache_entries,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "requests_per_second": round(requests_per_second, 3),
        "peak_memory_bytes": peak_memory_bytes,
        **checks,
        "failed_checks": failed_checks,
        "status": "pass" if not failed_checks else "fail",
    }


async def run_soak(
    *,
    requested: int,
    concurrency: int,
    max_cache_entries: int,
    max_journal_events: int,
    journal_path: Path,
) -> dict[str, Any]:
    if requested <= 0:
        raise ValueError("requests must be positive")
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    if journal_path.exists():
        journal_path.unlink()
    hub = BridgeHub(
        timeout=10,
        idempotency_ttl=3600,
        max_cache_entries=max_cache_entries,
        journal_path=journal_path,
        max_journal_events=max_journal_events,
    )
    plugin = _EchoPlugin(hub)
    await hub.attach_plugin(plugin)
    semaphore = asyncio.Semaphore(concurrency)

    async def execute(index: int) -> dict[str, Any]:
        async with semaphore:
            client = _SinkSocket()
            await hub.command(
                client,
                json.dumps(
                    {
                        "action": "soak_echo",
                        "params": {
                            "index": index,
                            "payload": "x" * 32,
                        },
                        "clientId": "p4-soak-client",
                        "requestId": f"p4-soak-{index}",
                    }
                ),
            )
            return client.sent[0]

    tracemalloc.start()
    started = time.perf_counter()
    responses = await asyncio.gather(*(execute(index) for index in range(requested)))
    elapsed = time.perf_counter() - started
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    completed = sum(
        1
        for expected_index, response in enumerate(responses)
        if (response.get("result") or {}).get("index") == expected_index
        and (response.get("result") or {}).get("echo") == "x" * 32
    )
    failed = requested - completed
    cache_entries = len(hub.completed)
    pending = len(hub.pending)
    scope_pending = len(hub.scope_pending)
    hub.close()

    lines = [
        line
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    replayed = BridgeHub(
        timeout=10,
        idempotency_ttl=3600,
        max_cache_entries=max_cache_entries,
        journal_path=journal_path,
    )
    replay_cache_entries = len(replayed.completed)
    replayed.close()
    return build_soak_report(
        requested=requested,
        completed=completed,
        failed=failed,
        pending=pending,
        scope_pending=scope_pending,
        cache_entries=cache_entries,
        max_cache_entries=max_cache_entries,
        journal_events=len(lines),
        max_journal_events=max_journal_events,
        replay_cache_entries=replay_cache_entries,
        elapsed_seconds=elapsed,
        peak_memory_bytes=peak_memory,
    )


class _EchoPlugin:
    def __init__(self, hub: BridgeHub) -> None:
        self.hub = hub

    async def send(self, message: str) -> None:
        payload = json.loads(message)
        await self.hub.plugin_message(
            json.dumps(
                {
                    "type": "response",
                    "requestId": payload["requestId"],
                    "result": {
                        "echo": payload["params"]["payload"],
                        "index": payload["params"]["index"],
                    },
                }
            )
        )


class _SinkSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--max-cache-entries", type=int, default=128)
    parser.add_argument("--max-journal-events", type=int, default=256)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    journal_path = out / "bridge-journal.jsonl"
    report = asyncio.run(
        run_soak(
            requested=args.requests,
            concurrency=args.concurrency,
            max_cache_entries=args.max_cache_entries,
            max_journal_events=args.max_journal_events,
            journal_path=journal_path,
        )
    )
    _write_report(out / "bridge_journal_soak.json", report)
    print(
        f"[soak] {report['status']} "
        f"rps={report['requests_per_second']} "
        f"journal={report['journal_events']}"
    )
    print(f"[out ] {out / 'bridge_journal_soak.json'}")
    return 0 if report["status"] == "pass" else 1


def _write_report(path: Path, report: dict[str, Any]) -> None:
    payload = {key: value for key, value in report.items() if key != "content_hash"}
    report["content_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
