"""Run the P1 evidence adapter without entering the normal render path."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.contracts import jsonable
from src.app.services.evidence import (
    DEFAULT_SAMPLE_SCOPE,
    EvidenceAdapterError,
    adapt_capture,
    write_evidence_sidecar,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a local P1 evidence sidecar from one capture directory."
    )
    parser.add_argument("capture_dir", nargs="?", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--job-id")
    parser.add_argument("--captured-at")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-sample-scope", action="store_true")
    args = parser.parse_args(argv)

    if args.print_sample_scope:
        print(json.dumps(jsonable(DEFAULT_SAMPLE_SCOPE), ensure_ascii=False, indent=2))
        return 0
    if args.capture_dir is None:
        parser.error("capture_dir is required unless --print-sample-scope is used")
    if args.out is None and not args.dry_run:
        parser.error("--out is required unless --dry-run is used")

    captured_at = (
        datetime.fromisoformat(args.captured_at)
        if args.captured_at
        else None
    )
    try:
        if args.dry_run:
            sidecar = adapt_capture(
                args.capture_dir,
                captured_at=captured_at,
                job_id=args.job_id,
            )
        else:
            sidecar = write_evidence_sidecar(
                args.capture_dir,
                args.out,
                captured_at=captured_at,
                job_id=args.job_id,
                overwrite=args.overwrite,
            )
    except EvidenceAdapterError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2

    summary = {
        "status": "ok",
        "capture_id": sidecar.runtime_ir.capture_id,
        "job_id": sidecar.runtime_ir.job_id,
        "field_count": len(sidecar.runtime_ir.fields),
        "unknown_count": len(sidecar.runtime_ir.unknowns),
        "content_hash": sidecar.manifest.get("content_hash"),
        "shadow_mode": True,
        "default_path_changed": False,
        "figma_write": False,
        "output_dir": str(sidecar.output_dir) if sidecar.output_dir else None,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
