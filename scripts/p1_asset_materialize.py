"""Materialize downloaded P1 asset bytes into a new auditable sidecar copy."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence import materialize_downloaded_assets


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge downloaded P1 asset evidence into a new sidecar."
    )
    parser.add_argument("--sidecar-dir", type=Path, required=True)
    parser.add_argument("--downloads-dir", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    sidecar_dir = args.sidecar_dir.resolve()
    downloads_dir = (args.downloads_dir or (sidecar_dir / "asset_downloads")).resolve()
    out_dir = (args.out or sidecar_dir.with_name(sidecar_dir.name + "_materialized")).resolve()
    try:
        result = materialize_downloaded_assets(
            sidecar_dir,
            downloads_dir,
            out_dir,
            overwrite=args.overwrite,
        )
    except Exception as exc:  # noqa: BLE001 - report materialization failure as JSON
        print(json.dumps({
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False))
        return 2

    print(json.dumps({
        "status": "ok",
        "output_dir": str(result.output_dir),
        "downloaded_count": result.materialization["downloaded_count"],
        "downloaded_bytes": result.materialization["downloaded_bytes"],
        "content_hash": result.manifest.get("content_hash"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
