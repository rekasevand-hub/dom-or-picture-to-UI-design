"""Deterministic first-frame authentication probe for /plugin."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.bridge_server import BridgeHub  # noqa: E402


PLUGIN_SECRET = "probe-plugin-secret"


class _Socket:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = [json.dumps(message) for message in messages]
        self.sent: list[dict[str, Any]] = []
        self.closed_code = None

    async def recv(self) -> str:
        if not self.messages:
            raise ConnectionError("no auth message")
        return self.messages.pop(0)

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def close(self, code=None, reason=None) -> None:
        self.closed_code = code


async def run_probe() -> dict[str, Any]:
    hub = BridgeHub(timeout=1, plugin_token=PLUGIN_SECRET)
    missing = _Socket([{"type": "auth"}])
    wrong = _Socket([{"type": "auth", "token": "wrong"}])
    valid = _Socket([{"type": "auth", "token": PLUGIN_SECRET}])
    optional = BridgeHub(timeout=1)
    optional_socket = _Socket([])
    rotated = {"token": "old-token"}
    rotation_hub = BridgeHub(
        timeout=1,
        plugin_token_provider=lambda: rotated["token"],
    )
    rotation_old = _Socket([{"type": "auth", "token": "old-token"}])
    rotation_old_accepted = await rotation_hub.authenticate_plugin(rotation_old)
    rotated["token"] = "new-token"
    rotation_stale = _Socket([{"type": "auth", "token": "old-token"}])
    rotation_new = _Socket([{"type": "auth", "token": "new-token"}])
    rotation_old_rejected = not await rotation_hub.authenticate_plugin(
        rotation_stale
    )
    rotation_new_accepted = await rotation_hub.authenticate_plugin(rotation_new)
    checks = {
        "missing_rejected": not await hub.authenticate_plugin(missing),
        "wrong_rejected": not await hub.authenticate_plugin(wrong),
        "valid_accepted": await hub.authenticate_plugin(valid),
        "optional_mode_unchanged": await optional.authenticate_plugin(
            optional_socket
        ),
        "rejected_close_code": missing.closed_code,
        "valid_response": valid.sent[0]["type"] if valid.sent else "",
        "rotation_old_rejected": (
            rotation_old_accepted and rotation_old_rejected
        ),
        "rotation_new_accepted": rotation_new_accepted,
    }
    passed = (
        checks["missing_rejected"]
        and checks["wrong_rejected"]
        and checks["valid_accepted"]
        and checks["optional_mode_unchanged"]
        and checks["rejected_close_code"] == 4003
        and checks["valid_response"] == "auth-ok"
        and checks["rotation_old_rejected"]
        and checks["rotation_new_accepted"]
    )
    report: dict[str, Any] = {
        "schema_version": "r5-p3-plugin-auth/1.0",
        "experiment": "R5-P3-PLUGIN-AUTH",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if passed else "fail",
        "checks": checks,
        "boundary": {
            "deterministic": True,
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
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run_probe())
    path = out / "r5_p3_plugin_auth.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"[r5-p3-plugin-auth] {report['status']}")
    print(f"[out ] {path}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
