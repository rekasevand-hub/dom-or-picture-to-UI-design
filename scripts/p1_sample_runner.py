"""Capture and adapt the P1 sample registry without entering the render path."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence import (
    EvidenceAdapterError,
    load_sample_registry,
    locate_sample,
    validate_sample_registry,
    write_evidence_sidecar,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture and build P1 evidence sidecars for a sample registry."
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=_ROOT / "docs" / "v2_mentor" / "p1_sample_registry.json",
    )
    parser.add_argument(
        "--sample-root",
        type=Path,
        default=_ROOT / "output" / "_p1_samples",
    )
    parser.add_argument(
        "--sidecar-root",
        type=Path,
        default=_ROOT / "output" / "_p1_evidence_shadow",
    )
    parser.add_argument("--only", help="comma-separated sample IDs")
    parser.add_argument(
        "--source-kind",
        choices=("controlled", "real"),
        help="limit the run to one source kind",
    )
    parser.add_argument("--captured-at")
    parser.add_argument(
        "--browser-engine",
        default="chromium",
        choices=("chromium", "webkit", "firefox"),
    )
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--allow-real-session", action="store_true")
    parser.add_argument("--capture-early-state", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="read existing capture/sidecar artifacts and only rebuild run_summary.json",
    )
    args = parser.parse_args(argv)

    registry = load_sample_registry(args.registry)
    issues = validate_sample_registry(registry)
    if issues:
        print(json.dumps({"status": "error", "issues": list(issues)}, ensure_ascii=False))
        return 2
    only = {item.strip() for item in (args.only or "").split(",") if item.strip()}
    samples = [
        sample
        for sample in registry.samples
        if (not only or sample.sample_id in only)
        and (not args.source_kind or sample.source_kind == args.source_kind)
    ]
    if not samples:
        print(json.dumps({"status": "error", "error": "no samples selected"}))
        return 2

    captured_at = (
        datetime.fromisoformat(args.captured_at)
        if args.captured_at
        else datetime.now(timezone.utc)
    )
    from src.app.services.structure.capture import capture_page_with_fallback
    from src.config.settings import Config

    config = Config(
        playwright_browser=args.browser_engine,
        playwright_headless=True,
        playwright_headed_fallback=args.allow_real_session,
        wait_networkidle_timeout=max(1000, args.timeout_ms),
    )
    results: list[dict[str, object]] = []
    for sample in samples:
        record: dict[str, object] = {
            "sample_id": sample.sample_id,
            "scenario_id": sample.scenario_id,
            "source_kind": sample.source_kind,
            "expected_page_state": sample.expected_page_state,
        }
        capture_dir = args.sample_root / sample.sample_id
        sidecar_dir = args.sidecar_root / sample.sample_id
        try:
            if args.summary_only:
                page_state_path = capture_dir / "00_page_state.json"
                manifest_path = sidecar_dir / "manifest.json"
                if not page_state_path.is_file() or not manifest_path.is_file():
                    raise FileNotFoundError(
                        f"missing capture or sidecar for {sample.sample_id}"
                    )
                page_state = json.loads(
                    page_state_path.read_text(encoding="utf-8")
                )
                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
                actual_state = str(page_state.get("kind") or "unknown")
                record.update(
                    {
                        "status": (
                            "ok"
                            if actual_state == sample.expected_page_state
                            else "page-state-mismatch"
                        ),
                        "actual_page_state": actual_state,
                        "capture_dir": str(capture_dir),
                        "sidecar_dir": str(sidecar_dir),
                        "field_count": manifest.get("field_count"),
                        "unknown_count": manifest.get("unknown_count"),
                        "content_hash": manifest.get("content_hash"),
                    }
                )
                results.append(record)
                continue
            if not (capture_dir / "00_page_state.json").is_file():
                capture_page_with_fallback(
                    locate_sample(sample, _ROOT),
                    config,
                    str(capture_dir),
                    requested_route="auto",
                    allow_real_session=args.allow_real_session,
                    browser_engine=args.browser_engine,
                    capture_early_state=args.capture_early_state,
                )
            page_state = json.loads(
                (capture_dir / "00_page_state.json").read_text(encoding="utf-8")
            )
            actual_state = str(page_state.get("kind") or "unknown")
            sidecar = write_evidence_sidecar(
                capture_dir,
                sidecar_dir,
                captured_at=captured_at,
                job_id=f"p1-sample-{sample.sample_id.lower()}",
                overwrite=args.overwrite,
            )
            record.update(
                {
                    "status": (
                        "ok"
                        if actual_state == sample.expected_page_state
                        else "page-state-mismatch"
                    ),
                    "actual_page_state": actual_state,
                    "capture_dir": str(capture_dir),
                    "sidecar_dir": str(sidecar_dir),
                    "field_count": len(sidecar.runtime_ir.fields),
                    "unknown_count": len(sidecar.runtime_ir.unknowns),
                    "content_hash": sidecar.manifest.get("content_hash"),
                }
            )
        except Exception as exc:  # noqa: BLE001 - one sample must not stop the batch
            record.update({
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            })
        results.append(record)

    summary = {
        "status": "ok" if all(item["status"] == "ok" for item in results) else "partial",
        "registry": str(args.registry),
        "scope_version": registry.scope_version,
        "browser": args.browser_engine,
        "sample_count": len(results),
        "ok_count": sum(item["status"] == "ok" for item in results),
        "results": results,
        "shadow_mode": True,
        "default_path_changed": False,
        "figma_write": False,
    }
    args.sidecar_root.mkdir(parents=True, exist_ok=True)
    result_path = args.sidecar_root / "run_summary.json"
    result_path.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
