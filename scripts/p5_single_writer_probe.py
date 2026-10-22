# -*- coding: utf-8 -*-
"""Controlled Windows probe for the local single-writer lease."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.bridge_server import BridgeHub
from src.app.services.contracts import canonical_hash
from src.app.services.write_lease import (
    WriterLeaseCommitError,
    WriterLeaseConflict,
    WriterLeaseLost,
    WriterLeaseStore,
)


PROFILE = "controlled-windows-single-writer/1.0"


class Clock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


def run_probe(output: str | Path) -> dict[str, Any]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    working = destination / "run"
    _reset_run_dir(destination, working)
    working.mkdir(parents=True, exist_ok=True)
    lease_path = working / "writer-lease.json"
    ready_path = working / "holder-ready.txt"

    child = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            str(lease_path),
            str(ready_path),
            "1.5",
        ],
        cwd=ROOT,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        holder_ready = ready_path.exists()
        contention_rejected = False
        if holder_ready:
            contender = WriterLeaseStore(
                lease_path,
                owner_id="probe-contender",
                ttl_seconds=30,
            )
            try:
                contender.acquire()
            except WriterLeaseConflict:
                contention_rejected = True
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)

    clock = Clock()
    store = WriterLeaseStore(
        lease_path,
        owner_id="probe-primary",
        ttl_seconds=10,
        clock=clock,
    )
    lease = store.acquire()
    wrong_generation_rejected = False
    try:
        store.assert_current(replace(lease, generation=lease.generation + 1))
    except WriterLeaseLost:
        wrong_generation_rejected = True
    clock.advance(11)
    expired_rejected = False
    try:
        store.assert_current(lease)
    except WriterLeaseLost:
        expired_rejected = True
    resumed = store.acquire()
    pause_resume_generation = resumed.generation

    before_partition = lease_path.read_bytes()
    clock.advance(11)

    def fail_commit(stage: str) -> None:
        if stage == "before-commit":
            raise OSError("simulated partition")

    partition_store = WriterLeaseStore(
        lease_path,
        owner_id="probe-partition",
        ttl_seconds=10,
        clock=clock,
        before_commit=fail_commit,
    )
    partition_rejected = False
    try:
        partition_store.acquire()
    except WriterLeaseCommitError:
        partition_rejected = True
    partition_preserved = lease_path.read_bytes() == before_partition
    recovered = WriterLeaseStore(
        lease_path,
        owner_id="probe-recovered",
        ttl_seconds=10,
        clock=clock,
    ).acquire()

    journal_failure = asyncio.run(_journal_failure_probe(working / "journal-failure"))
    unknown_resend = asyncio.run(_unknown_resend_probe(working / "unknown-resend"))
    checks = (
        _check("two-process-conflict", "Second local process cannot acquire the lease", contention_rejected),
        _check("wrong-generation", "Wrong generation token is rejected", wrong_generation_rejected),
        _check("expired-token", "Expired token is rejected", expired_rejected),
        _check("pause-resume", "Resume advances the lease generation", pause_resume_generation > lease.generation),
        _check("partition-commit", "Failed partition commit is rejected and state is preserved", partition_rejected and partition_preserved),
        _check("journal-failure", "Journal append failure occurs before plugin send", journal_failure["no_plugin_send"] and journal_failure["no_transaction"]),
        _check("unknown-no-resend", "Unknown write is not resent after plugin reconnect", unknown_resend["apply_batch_send_count"] == 1 and unknown_resend["transaction_state"] == "unknown"),
    )
    result = {
        "schema": "p5-single-writer-probe/1.0",
        "status": "verified-for" if all(item["passed"] for item in checks) else "blocked",
        "scope": "single-writer fence on controlled Windows host",
        "created_at": "2026-10-22T00:00:00+00:00",
        "profile": PROFILE,
        "environment": {
            "os": "Windows 11",
            "python": sys.version.split()[0],
            "topology": "one local host, one bridge process, one plugin writer",
        },
        "code_revision": _code_revision(),
        "plugin_build": {
            "code_sha256": _sha256_file(ROOT / "figma_bridge" / "code.js"),
            "manifest_sha256": _sha256_file(ROOT / "figma_bridge" / "manifest.json"),
        },
        "lease": {
            "first_generation": lease.generation,
            "resumed_generation": pause_resume_generation,
            "recovered_generation": recovered.generation,
            "owner_id": lease.owner_id,
            "ttl_seconds": 10,
        },
        "journal_failure": journal_failure,
        "unknown_resend": unknown_resend,
        "checks": list(checks),
        "claim_limits": [
            "This is a local single-host lease, not a distributed fencing service.",
            "The probe does not prove network-filesystem semantics or cross-host ownership.",
            "The plugin is simulated for dispatch ordering; real Figma writes are outside this probe.",
        ],
    }
    result["content_hash"] = canonical_hash(result)
    _write_json(destination / "result.json", result)
    _write_json(
        destination / "lease-state.json",
        {
            "path": str(lease_path),
            "sha256": _sha256_file(lease_path),
            "generation": recovered.generation,
        },
    )
    return result


async def _journal_failure_probe(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    store = WriterLeaseStore(
        output / "lease.json",
        owner_id="journal-failure-writer",
        ttl_seconds=30,
    )
    journal = output / "journal.jsonl"
    hub = BridgeHub(
        timeout=0.2,
        journal_path=journal,
        writer_lease_store=store,
        write_min_interval=0,
    )
    plugin = FakeSocket()
    client = FakeSocket()
    await hub.attach_plugin(plugin)
    original = hub._append_journal_event

    def fail(event: dict[str, Any]) -> None:
        raise OSError("simulated journal append failure")

    hub._append_journal_event = fail
    try:
        await hub.command(
            client,
            json.dumps(
                {
                    "action": "set_visibility",
                    "params": {"nodeId": "1:1", "visible": True},
                    "clientId": "probe",
                    "requestId": "journal-failure-request",
                }
            ),
        )
    finally:
        hub._append_journal_event = original
        hub.close()
    return {
        "response_code": (client.sent[-1].get("code") if client.sent else None),
        "plugin_send_count": len(plugin.sent),
        "no_plugin_send": len(plugin.sent) == 0,
        "no_transaction": "journal-failure-request" not in hub.transactions,
        "journal_created": journal.exists(),
    }


async def _unknown_resend_probe(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    store = WriterLeaseStore(
        output / "lease.json",
        owner_id="unknown-write-writer",
        ttl_seconds=30,
    )
    hub = BridgeHub(
        timeout=0.01,
        journal_path=output / "journal.jsonl",
        writer_lease_store=store,
        write_min_interval=0,
    )
    first_plugin = FakeSocket()
    first_client = FakeSocket()
    await hub.attach_plugin(first_plugin)
    await hub.command(
        first_client,
        json.dumps(
            {
                "action": "apply_edit_batch",
                "params": {"transactionId": "unknown-write", "actions": []},
                "clientId": "probe",
                "requestId": "unknown-write",
            }
        ),
    )
    replacement = FakeSocket()
    await hub.attach_plugin(replacement)
    await asyncio.sleep(0.02)
    transaction = hub.transactions["unknown-write"]
    apply_batch_send_count = sum(
        item.get("action") == "apply_edit_batch"
        for item in first_plugin.sent + replacement.sent
    )
    hub.close()
    return {
        "response_code": first_client.sent[-1].get("code"),
        "apply_batch_send_count": apply_batch_send_count,
        "transaction_state": transaction.state,
    }


def _worker(lease_path: str, ready_path: str, duration: str) -> int:
    store = WriterLeaseStore(
        lease_path,
        owner_id="probe-process-holder",
        ttl_seconds=30,
    )
    lease = store.acquire()
    Path(ready_path).write_text(str(lease.generation), encoding="utf-8")
    time.sleep(float(duration))
    store.release(lease)
    return 0


def _check(name: str, description: str, passed: bool) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "passed": bool(passed),
    }


def _reset_run_dir(destination: Path, working: Path) -> None:
    resolved_destination = destination.resolve()
    resolved_working = working.resolve()
    if (
        resolved_working.parent != resolved_destination
        or resolved_working.name != "run"
    ):
        raise ValueError(f"refusing to reset unexpected probe directory: {resolved_working}")
    if resolved_working.exists():
        shutil.rmtree(resolved_working)


def _code_revision() -> str:
    try:
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
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with staging.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_p5_single_writer_round1")
    parser.add_argument("--worker", nargs=3, metavar=("LEASE", "READY", "DURATION"))
    args = parser.parse_args()
    if args.worker:
        return _worker(*args.worker)
    result = run_probe(args.out)
    print(json.dumps({"checks": len(result["checks"])}, indent=2))
    print("status=" + result["status"])
    print("content_hash=" + result["content_hash"])
    return 0 if result["status"] == "verified-for" else 1


if __name__ == "__main__":
    raise SystemExit(main())
