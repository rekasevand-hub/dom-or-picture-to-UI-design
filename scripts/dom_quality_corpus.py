"""Capture, freeze and verify the D-003 real-site DOM corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence.dom_quality_corpus import (  # noqa: E402
    build_capture_fingerprint,
    corpus_sha256,
    evaluate_capture,
    load_corpus,
    thresholds_sha256,
    validate_corpus,
)
from src.app.services.structure.capture import (  # noqa: E402
    _browser_context_options,
    capture_page_with_fallback,
)
from src.config.settings import Config  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture, freeze or verify the real-site DOM quality corpus."
    )
    parser.add_argument(
        "command",
        choices=("capture", "freeze", "verify"),
        help="capture evidence, freeze a draft manifest, or verify against a frozen baseline",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_ROOT
        / "tests"
        / "fixtures"
        / "dom_quality"
        / "real_site_corpus_v1.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "output" / "_dom_quality_corpus",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--refreeze",
        action="store_true",
        help="explicitly replace an already-frozen manifest baseline",
    )
    return parser


def ensure_output_available(path: Path, *, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()) and not overwrite:
        raise ValueError(f"output directory is not empty; pass --overwrite: {path}")


def ensure_manifest_mutable(corpus: Mapping[str, Any], *, refreeze: bool) -> None:
    if corpus.get("status") == "frozen" and not refreeze:
        raise ValueError("frozen corpus requires explicit --refreeze")


def collect_environment(corpus: Mapping[str, Any]) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    environment = corpus.get("environment") or {}
    viewport = dict(environment.get("viewport") or {})
    config = Config(
        playwright_viewport_width=int(viewport.get("width", 0)),
        playwright_viewport_height=int(viewport.get("height", 0)),
        device_scale_factor=int(environment.get("device_scale_factor") or 0),
        playwright_locale=str(environment.get("locale") or ""),
        playwright_timezone=str(environment.get("timezone") or ""),
        playwright_headless=bool(environment.get("headless")),
    )
    with sync_playwright() as playwright:
        browser_type = playwright.chromium
        executable_path = Path(browser_type.executable_path)
        browser = browser_type.launch(headless=True)
        try:
            context = browser.new_context(**_browser_context_options(config, viewport))
            page = context.new_page()
            page.set_content("<html><body>environment probe</body></html>")
            observed = page.evaluate(
                """() => ({
                    language: navigator.language,
                    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                    devicePixelRatio: window.devicePixelRatio,
                    userAgent: navigator.userAgent
                })"""
            )
            browser_version = str(browser.version)
            context.close()
        finally:
            browser.close()
    actual_locale = str(observed.get("language") or "")
    actual_timezone = str(observed.get("timezone") or "")
    actual_dpr = int(observed.get("devicePixelRatio") or 0)
    if actual_locale != config.playwright_locale:
        raise ValueError(
            f"browser locale mismatch: {actual_locale} != {config.playwright_locale}"
        )
    if actual_timezone != config.playwright_timezone:
        raise ValueError(
            f"browser timezone mismatch: {actual_timezone} != {config.playwright_timezone}"
        )
    if actual_dpr != config.device_scale_factor:
        raise ValueError(
            f"browser DPR mismatch: {actual_dpr} != {config.device_scale_factor}"
        )
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    font_names = [
        str(item.get("name"))
        for item in environment.get("font_files") or []
        if isinstance(item, Mapping) and item.get("name")
    ]
    return {
        "schema_version": "dom-quality-environment/1.0",
        "engine": "chromium",
        "browser_version": browser_version,
        "executable_path": str(executable_path),
        "executable_sha256": _file_sha256(executable_path),
        "python_version": platform.python_version(),
        "os": platform.platform(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "viewport": viewport,
        "device_scale_factor": actual_dpr,
        "locale": actual_locale,
        "timezone": actual_timezone,
        "headless": True,
        "user_agent": str(observed.get("userAgent") or ""),
        "font_files": [_font_record(fonts_dir / name) for name in font_names],
        "capture_contract": "capture_page_with_fallback+dom-quality-corpus/1.0",
    }


def compare_environment(
    frozen: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    for key in (
        "browser_version",
        "executable_sha256",
        "viewport",
        "device_scale_factor",
        "locale",
        "timezone",
        "headless",
        "font_files",
    ):
        expected = frozen.get(key)
        observed = actual.get(key)
        checks[key] = {
            "pass": observed == expected,
            "expected": expected,
            "actual": observed,
        }
    return {
        "status": "pass" if all(item["pass"] for item in checks.values()) else "fail",
        "checks": checks,
    }


def run_corpus(
    corpus: dict[str, Any],
    out_dir: Path,
    *,
    mode: str,
) -> dict[str, Any]:
    output_environment = collect_environment(corpus)
    environment_check = (
        compare_environment(corpus["environment"], output_environment)
        if mode == "verify" and corpus.get("status") == "frozen"
        else {"status": "capture", "checks": {}}
    )
    results: list[dict[str, Any]] = []
    for sample in corpus["samples"]:
        capture_dir = out_dir / str(sample["sample_id"])
        state = sample.get("state") or {}
        config = Config(
            playwright_viewport_width=int(corpus["environment"]["viewport"]["width"]),
            playwright_viewport_height=int(corpus["environment"]["viewport"]["height"]),
            device_scale_factor=int(corpus["environment"]["device_scale_factor"]),
            playwright_locale=str(corpus["environment"]["locale"]),
            playwright_timezone=str(corpus["environment"]["timezone"]),
            playwright_headless=True,
            playwright_headed_fallback=False,
            wait_networkidle_timeout=int(
                (corpus.get("network") or {}).get("network_idle_timeout_ms") or 30000
            ),
        )
        try:
            capture_page_with_fallback(
                str(sample["url"]),
                config,
                str(capture_dir),
                requested_route="auto",
                allow_real_session=False,
                browser_engine="chromium",
                capture_attempts=int(state.get("capture_attempts") or 2),
                block_cross_origin_frame_documents=bool(
                    (corpus.get("network") or {}).get(
                        "block_cross_origin_frame_documents"
                    )
                ),
            )
            fingerprint = build_capture_fingerprint(capture_dir)
            candidate = {**sample, "fingerprint": fingerprint}
            evaluation = evaluate_capture(candidate, capture_dir, corpus["thresholds"])
            if mode == "verify" and isinstance(sample.get("fingerprint"), Mapping):
                evaluation = evaluate_capture(sample, capture_dir, corpus["thresholds"])
            record = {
                "sample_id": sample["sample_id"],
                "status": evaluation["status"],
                "capture_dir": str(capture_dir),
                "fingerprint": fingerprint,
                "evaluation": evaluation,
            }
        except Exception as exc:  # noqa: BLE001 - one site must not stop the report
            record = {
                "sample_id": sample["sample_id"],
                "status": "error",
                "capture_dir": str(capture_dir),
                "error": f"{type(exc).__name__}: {exc}",
            }
        results.append(record)
    return {
        "status": (
            "pass"
            if environment_check["status"] in {"capture", "pass"}
            and results
            and all(item["status"] == "pass" for item in results)
            else "fail"
        ),
        "mode": mode,
        "corpus_id": corpus.get("corpus_id"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(out_dir),
        "environment": output_environment,
        "environment_check": environment_check,
        "sample_count": len(results),
        "pass_count": sum(item["status"] == "pass" for item in results),
        "results": results,
        "default_path_changed": False,
        "figma_write": False,
    }


def freeze_corpus(
    corpus: dict[str, Any],
    out_dir: Path,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    if summary.get("status") != "pass":
        raise ValueError("cannot freeze a corpus whose captures did not pass")
    frozen = json.loads(json.dumps(corpus))
    frozen["environment"] = summary["environment"]
    by_id = {item["sample_id"]: item for item in summary["results"]}
    for sample in frozen["samples"]:
        sample["fingerprint"] = by_id[sample["sample_id"]]["fingerprint"]
    frozen["status"] = "frozen"
    frozen["frozen_at"] = datetime.now(timezone.utc).isoformat()
    frozen["thresholds_sha256"] = thresholds_sha256(frozen)
    frozen["corpus_sha256"] = None
    frozen["corpus_sha256"] = corpus_sha256(frozen)
    errors = validate_corpus(frozen)
    if errors:
        raise ValueError("frozen corpus is invalid: " + "; ".join(errors))
    return frozen


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"name": path.name, "status": "missing"}
    return {
        "name": path.name,
        "status": "present",
        "size": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        corpus = load_corpus(args.manifest)
        errors = validate_corpus(corpus)
        if errors:
            raise ValueError("invalid corpus: " + "; ".join(errors))
        ensure_output_available(args.out, overwrite=args.overwrite)
        if args.command == "freeze":
            ensure_manifest_mutable(corpus, refreeze=args.refreeze)
        args.out.mkdir(parents=True, exist_ok=True)
        summary = run_corpus(corpus, args.out, mode=args.command)
        _write_json(args.out / "summary.json", summary)
        if args.command == "freeze" and summary["status"] == "pass":
            frozen = freeze_corpus(corpus, args.out, summary)
            _write_json(args.manifest, frozen)
            _write_json(args.out / "frozen_manifest.json", frozen)
        return 0 if summary["status"] == "pass" else 1
    except Exception as exc:  # noqa: BLE001 - CLI reports one typed failure
        print(
            json.dumps(
                {"status": "error", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
