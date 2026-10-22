"""Atomically rotate bridge config secrets and certificate paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.bridge_config import load_bridge_config


def _set_path(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = [part for part in dotted_path.split(".") if part]
    if not parts:
        raise ValueError("updated field path is empty")
    target: dict[str, Any] = payload
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            child = {}
            target[part] = child
        target = child
    target[parts[-1]] = value


def rotate_bridge_config(
    path: str | Path,
    updates: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("bridge config root must be an object")
    for field, value in updates.items():
        _set_path(payload, str(field), value)

    fd, temp_name = tempfile.mkstemp(
        prefix=config_path.name + ".",
        suffix=".tmp",
        dir=config_path.parent,
    )
    temp_path = Path(temp_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        load_bridge_config(temp_path, environ=environ)
        os.replace(temp_path, config_path)
        if os.name != "nt":
            os.chmod(config_path, 0o600)
        try:
            directory_fd = os.open(config_path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    digest = hashlib.sha256(config_path.read_bytes()).hexdigest()
    return {
        "status": "rotated",
        "config_path": str(config_path),
        "updated_fields": sorted(str(field) for field in updates),
        "file_sha256": digest,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--plugin-token")
    parser.add_argument("--plugin-token-file")
    parser.add_argument("--shared-token")
    parser.add_argument("--shared-token-file")
    parser.add_argument("--certfile")
    parser.add_argument("--keyfile")
    parser.add_argument("--ca-file")
    parser.add_argument("--client-ca-file")
    parser.add_argument("--client-certfile")
    parser.add_argument("--client-keyfile")
    args = parser.parse_args(argv)

    updates: dict[str, Any] = {}
    if args.plugin_token is not None:
        updates["server.plugin_token"] = args.plugin_token
    if args.plugin_token_file:
        updates["server.plugin_token"] = f"file:{args.plugin_token_file}"
    if args.shared_token is not None:
        updates["server.auth_token"] = args.shared_token
        updates["client.auth_token"] = args.shared_token
    if args.shared_token_file:
        reference = f"file:{args.shared_token_file}"
        updates["server.auth_token"] = reference
        updates["client.auth_token"] = reference
    for field, value in (
        ("server.tls.certfile", args.certfile),
        ("server.tls.keyfile", args.keyfile),
        ("server.tls.ca_file", args.ca_file),
        ("client.tls.ca_file", args.client_ca_file),
        ("client.tls.certfile", args.client_certfile),
        ("client.tls.keyfile", args.client_keyfile),
    ):
        if value is not None:
            updates[field] = value
    if not updates:
        parser.error("at least one rotation option is required")

    report = rotate_bridge_config(args.config, updates)
    print(
        f"[rotate] {report['status']} "
        f"fields={','.join(report['updated_fields'])}"
    )
    print(f"[hash] {report['file_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
