"""Dry-run or atomically apply legacy write-job ledger migration."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.rendering.write_job_ledger import (  # noqa: E402
    LegacyLedgerMigrationError,
    migrate_legacy_write_job_ledger,
)


def _read_mapping(path: str | Path) -> dict[str, str]:
    mapping_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise LegacyLedgerMigrationError(
            "client mapping file is not valid JSON"
        ) from exc
    if not isinstance(payload, dict) or not payload:
        raise LegacyLedgerMigrationError(
            "client mapping file must be a non-empty object"
        )
    mapping: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise LegacyLedgerMigrationError(
                "client mapping keys and values must be strings"
            )
        mapping[key] = value
    return mapping


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
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
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--client-map", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args(argv)

    try:
        mapping = _read_mapping(args.client_map)
        result = migrate_legacy_write_job_ledger(
            args.source,
            args.target,
            client_mapping=mapping,
            dry_run=not args.apply,
            overwrite=args.overwrite,
        )
        report = result.to_dict()
        if args.report:
            _atomic_write_json(Path(args.report).resolve(), report)
    except (LegacyLedgerMigrationError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
