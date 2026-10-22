"""Download a bounded subset of reference-only assets from one P1 sidecar."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence import (
    AssetDownloadError,
    AssetDownloadPolicy,
    download_asset,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download a bounded subset of reference-only P1 assets."
    )
    parser.add_argument("--sidecar-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--max-assets", type=int, default=3)
    parser.add_argument("--max-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)

    runtime_path = args.sidecar_dir / "runtime_ir.json"
    if not runtime_path.is_file():
        print(json.dumps({"status": "error", "error": "runtime_ir.json not found"}))
        return 2
    runtime_ir = json.loads(runtime_path.read_text(encoding="utf-8"))
    policy = AssetDownloadPolicy(
        max_assets=max(1, args.max_assets),
        max_bytes_per_asset=max(1, args.max_bytes),
        max_total_bytes=max(1, args.max_bytes) * max(1, args.max_assets),
        timeout_seconds=max(0.1, args.timeout),
    )
    out_dir = args.out or (args.sidecar_dir / "asset_downloads")
    assets_dir = out_dir / "evidence" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    candidates = [
        item
        for item in runtime_ir.get("assets") or []
        if item.get("source_url") and not item.get("local_bytes_present")
    ][: policy.max_assets]
    rows: list[dict[str, object]] = []
    total_bytes = 0
    for asset in candidates:
        asset_id = str(asset.get("asset_id") or "asset")
        row: dict[str, object] = {
            "asset_id": asset_id,
            "source_url": asset.get("source_url"),
        }
        try:
            downloaded = download_asset(str(asset["source_url"]), policy)
            size = int(downloaded["size_bytes"])
            if total_bytes + size > policy.max_total_bytes:
                raise AssetDownloadError("total-size-exceeded", "asset batch exceeded total size budget")
            target = assets_dir / f"{asset_id}{downloaded['extension']}"
            target.write_bytes(downloaded["payload"])
            total_bytes += size
            row.update(
                {
                    "status": "downloaded",
                    "final_url": downloaded["final_url"],
                    "mime": downloaded["mime"],
                    "sha256": downloaded["sha256"],
                    "size_bytes": size,
                    "locator": str(target.relative_to(out_dir)),
                }
            )
        except AssetDownloadError as exc:
            row.update({"status": "error", "error_code": exc.code, "error": str(exc)})
        rows.append(row)

    result = {
        "status": (
            "ok"
            if rows and all(item["status"] == "downloaded" for item in rows)
            else "partial" if any(item["status"] == "downloaded" for item in rows)
            else "error"
        ),
        "policy": {
            "max_assets": policy.max_assets,
            "max_bytes_per_asset": policy.max_bytes_per_asset,
            "max_total_bytes": policy.max_total_bytes,
            "timeout_seconds": policy.timeout_seconds,
            "allow_private_hosts": policy.allow_private_hosts,
        },
        "candidate_count": len(candidates),
        "downloaded_count": sum(item["status"] == "downloaded" for item in rows),
        "total_bytes": total_bytes,
        "rows": rows,
        "promotion": "asset-evidence-only; runtime_ir unchanged",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "asset_downloads.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "candidate_count": result["candidate_count"],
        "downloaded_count": result["downloaded_count"],
        "total_bytes": total_bytes,
        "output": str(out_dir / "asset_downloads.json"),
    }, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
