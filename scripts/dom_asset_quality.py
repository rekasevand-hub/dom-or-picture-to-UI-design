"""Probe and report frozen DOM asset identity evidence."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence.asset_download import (  # noqa: E402
    AssetDownloadError,
    AssetDownloadPolicy,
    download_asset,
)
from src.app.services.evidence.dom_asset_quality import (  # noqa: E402
    build_asset_quality_report,
    collect_asset_uses,
)
from src.app.services.evidence.dom_quality_corpus import (  # noqa: E402
    load_corpus,
    validate_corpus,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded DOM asset source probe and quality report."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe = subparsers.add_parser("probe")
    _add_common(probe)
    probe.add_argument("--max-assets", type=int, default=80)
    probe.add_argument("--max-bytes-per-asset", type=int, default=2 * 1024 * 1024)
    probe.add_argument("--max-total-bytes", type=int, default=40 * 1024 * 1024)
    probe.add_argument("--timeout", type=float, default=10.0)

    report = subparsers.add_parser("report")
    _add_common(report)
    report.add_argument("--source-probes", type=Path, required=True)
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)


def probe_sources(
    corpus: Mapping[str, Any],
    capture_root: str | Path,
    output_dir: str | Path,
    *,
    max_assets: int = 80,
    max_bytes_per_asset: int = 2 * 1024 * 1024,
    max_total_bytes: int = 40 * 1024 * 1024,
    timeout: float = 10.0,
) -> dict[str, Any]:
    destination = Path(output_dir)
    assets_dir = destination / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    candidates = _remote_asset_candidates(corpus, Path(capture_root))
    policy = AssetDownloadPolicy(
        max_assets=max_assets,
        max_bytes_per_asset=max_bytes_per_asset,
        max_total_bytes=max_total_bytes,
        timeout_seconds=timeout,
    )
    rows: list[dict[str, Any]] = []
    total_bytes = 0
    for source_url in candidates[: max(0, max_assets)]:
        try:
            downloaded = download_asset(source_url, policy)
            payload = downloaded.pop("payload")
            if total_bytes + len(payload) > max_total_bytes:
                raise AssetDownloadError(
                    "total-size-exceeded",
                    f"total source bytes would exceed {max_total_bytes}",
                )
            dimensions = _image_dimensions(payload, downloaded["mime"])
            if dimensions is None:
                raise AssetDownloadError(
                    "dimensions-unavailable",
                    "decoded image dimensions are unavailable",
                )
            digest = str(downloaded["sha256"])
            extension = str(downloaded["extension"])
            target = assets_dir / f"{digest}{extension}"
            if not target.exists():
                target.write_bytes(payload)
            if _file_sha256(target) != digest:
                raise AssetDownloadError(
                    "retained-hash-mismatch",
                    "retained source bytes do not match the probe hash",
                )
            total_bytes += len(payload)
            rows.append(
                {
                    **downloaded,
                    "status": "verified-original",
                    "natural_size": list(dimensions),
                    "bytes_present": True,
                    "locator": f"assets/{target.name}",
                }
            )
        except (AssetDownloadError, OSError, TypeError, ValueError) as exc:
            rows.append(
                {
                    "source_url": source_url,
                    "status": "reference-only",
                    "sha256": None,
                    "mime": None,
                    "natural_size": None,
                    "size_bytes": None,
                    "bytes_present": False,
                    "locator": None,
                    "error_code": getattr(exc, "code", type(exc).__name__),
                    "error": str(exc),
                }
            )
    document = {
        "schema_version": "dom-asset-source-probes/1.0",
        "corpus_id": corpus.get("corpus_id"),
        "corpus_sha256": corpus.get("corpus_sha256"),
        "policy": {
            "max_assets": max_assets,
            "max_bytes_per_asset": max_bytes_per_asset,
            "max_total_bytes": max_total_bytes,
            "timeout_seconds": timeout,
            "allow_private_hosts": False,
        },
        "status_counts": _status_counts(rows),
        "rows": rows,
    }
    _write_json(destination / "source_probes.json", document)
    return document


def report_assets(
    corpus: Mapping[str, Any],
    capture_root: str | Path,
    source_probes_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    probes_path = Path(source_probes_path).resolve()
    probes = json.loads(probes_path.read_text(encoding="utf-8"))
    if not isinstance(probes, dict):
        raise ValueError("source probes must be a JSON object")
    probes["_root"] = str(probes_path.parent)
    report = build_asset_quality_report(corpus, capture_root, probes)
    _write_json(Path(output_dir) / "summary.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    corpus = load_corpus(args.manifest)
    errors = validate_corpus(corpus)
    if errors:
        raise SystemExit("invalid frozen corpus: " + "; ".join(errors))
    if args.command == "probe":
        document = probe_sources(
            corpus,
            args.capture_root,
            args.out,
            max_assets=args.max_assets,
            max_bytes_per_asset=args.max_bytes_per_asset,
            max_total_bytes=args.max_total_bytes,
            timeout=args.timeout,
        )
        print(json.dumps(document["status_counts"], ensure_ascii=False))
        return 0
    report = report_assets(
        corpus,
        args.capture_root,
        args.source_probes,
        args.out,
    )
    print(json.dumps(report["dimensions"], ensure_ascii=False))
    return 0


def _remote_asset_candidates(
    corpus: Mapping[str, Any],
    capture_root: Path,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for sample in corpus.get("samples") or []:
        if not isinstance(sample, Mapping):
            continue
        sample_id = str(sample.get("sample_id") or "")
        dom_path = capture_root / sample_id / "00_dom.json"
        if not dom_path.is_file():
            continue
        dom = json.loads(dom_path.read_text(encoding="utf-8"))
        if not isinstance(dom, list):
            continue
        for use in collect_asset_uses(dom, sample_id=sample_id):
            source = str(use.get("source") or "")
            if source.startswith(("http://", "https://")) and source not in seen:
                seen.add(source)
                urls.append(source)
    return urls


def _image_dimensions(payload: bytes, mime: str) -> tuple[float, float] | None:
    if mime == "image/svg+xml":
        from src.app.services.structure.asset_metadata import parse_data_uri_asset

        import base64

        encoded = base64.b64encode(payload).decode("ascii")
        parsed = parse_data_uri_asset(f"data:image/svg+xml;base64,{encoded}")
        size = parsed.get("natural_size")
        if size:
            return float(size[0]), float(size[1])
        return None
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return float(image.width), float(image.height)
    except Exception:
        return None


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
