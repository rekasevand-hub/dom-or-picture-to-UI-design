"""Run a bounded navigation-only timeline probe without DOM or sidecars."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure.capture_state import classify_capture_navigation
from src.app.services.structure.navigation_timeline import NavigationTimeline


DEFAULT_URL = "https://www.dushu.com/"
ENGINES = ("chromium", "webkit")
NAVIGATION_FAILED = {"browser-navigation-failed", "navigation-failed"}
NAVIGATION_OK = {"ok", "redirected"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a lightweight navigation-only timeline diagnostic."
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--settle-ms", type=int, default=800)
    parser.add_argument("--reuse-existing", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        default=(
            _ROOT
            / "output"
            / "_p1_navigation_only"
            / "s06_round1.json"
        ),
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--worker-engine",
        choices=ENGINES,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--worker-attempt", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        if (
            not args.worker_engine
            or args.worker_attempt is None
            or args.result is None
        ):
            raise SystemExit("worker mode requires engine, attempt and result")
        _worker_main(args)
        return 0

    attempts = max(1, int(args.attempts))
    if args.reuse_existing:
        observations = load_observation_file(args.out)
    else:
        tasks = [
            (attempt, engine)
            for attempt in range(1, attempts + 1)
            for engine in ENGINES
        ]
        with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as pool:
            futures = [
                pool.submit(_run_worker, args, attempt, engine, index)
                for index, (attempt, engine) in enumerate(tasks)
            ]
            observations = [future.result() for future in futures]
    summary = summarize_navigation_only(observations)
    result = {
        "schema_version": "p1-navigation-only-probe/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_id": "P1-S06-R1",
        "url": str(args.url),
        "fixed_budget": {
            "attempts": attempts,
            "timeout_ms": max(1000, int(args.timeout_ms)),
            "settle_ms": max(0, int(args.settle_ms)),
            "workers": max(1, int(args.workers)),
            "max_timeline_events_per_engine_attempt": 128,
        },
        "observations": observations,
        "summary": summary,
        "note": (
            "Navigation-only diagnostic. It records document requests, failures, "
            "responses and commits without DOM capture or sidecar materialization."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "classification": summary["classification"],
        "primary_attempt": summary["primary_attempt"],
        "request_failed_count": summary["request_failed_count"],
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0


def summarize_navigation_only(
    observations: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    normalized = [
        _normalize_observation(item)
        for item in observations
        if isinstance(item, dict)
    ]
    grouped: dict[int, dict[str, dict[str, Any]]] = {}
    for item in normalized:
        attempt = _optional_int(item.get("attempt"))
        if attempt is None:
            continue
        grouped.setdefault(attempt, {})[str(item.get("engine") or "")] = item
    primary_attempt = min(grouped) if grouped else None
    primary = grouped.get(primary_attempt, {})
    primary_items = list(primary.values())
    primary_complete = all(
        engine in primary and primary[engine]["valid"]
        for engine in ENGINES
    )
    invalid = any(not item["valid"] for item in primary_items)
    failed = any(
        item["navigation"].get("status") in NAVIGATION_FAILED
        for item in primary_items
    )
    succeeded = bool(primary_items) and all(
        item["navigation"].get("status") in NAVIGATION_OK
        for item in primary_items
    )
    primary_document_failures = any(
        item["request_failed"] for item in primary_items
    )
    if invalid or not primary_complete:
        classification = "capture-failure"
    elif failed:
        classification = "navigation-failure"
    elif succeeded:
        classification = (
            "navigation-comparable-with-document-failures"
            if primary_document_failures
            else "navigation-comparable"
        )
    else:
        classification = "capture-failure"

    later_recovered = any(
        attempt > (primary_attempt or 0)
        and all(
            engine in records
            and records[engine]["valid"]
            and records[engine]["navigation"].get("status") in NAVIGATION_OK
            for engine in ENGINES
        )
        for attempt, records in grouped.items()
    )
    later_failed = any(
        any(
            record["navigation"].get("status") in NAVIGATION_FAILED
            for record in records.values()
        )
        for attempt, records in grouped.items()
        if attempt > (primary_attempt or 0)
    )
    request_failed = [
        event
        for item in normalized
        for event in item["request_failed"]
    ]
    return {
        "classification": classification,
        "primary_attempt": primary_attempt,
        "primary_engines": primary,
        "later_navigation_recovered": later_recovered,
        "later_navigation_failed": later_failed,
        "valid_count": sum(item["valid"] for item in normalized),
        "observation_count": len(normalized),
        "request_failed_count": len(request_failed),
        "request_failed": request_failed,
        "response_count": sum(
            len(item["responses"]) for item in normalized
        ),
        "commit_count": sum(
            len(item["document_commits"]) for item in normalized
        ),
        "dom_difference_evaluated": False,
        "stable_dom_difference_claimed": False,
        "note": (
            "The primary attempt follows source order and is not replaced when a "
            "later attempt recovers navigation."
        ),
    }


def load_observation_file(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    observations = value.get("observations") if isinstance(value, dict) else None
    if not isinstance(observations, list):
        raise ValueError("navigation-only observation list is missing")
    return [
        dict(item)
        for item in observations
        if isinstance(item, dict)
    ]


def _run_worker(
    args: argparse.Namespace,
    attempt: int,
    engine: str,
    index: int,
) -> dict[str, Any]:
    result_path = (
        args.out.parent
        / ".navigation-only-workers"
        / f"observation-{index:03d}.json"
    )
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--worker-engine",
        engine,
        "--worker-attempt",
        str(attempt),
        "--url",
        str(args.url),
        "--timeout-ms",
        str(max(1000, int(args.timeout_ms))),
        "--settle-ms",
        str(max(0, int(args.settle_ms))),
        "--result",
        str(result_path),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=max(10, int(args.timeout_ms) / 1000 + 20),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _failed_observation(engine, attempt, "worker-timeout")
    if completed.returncode != 0 or not result_path.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()[-1000:]
        return _failed_observation(engine, attempt, detail or "worker-failed")
    try:
        value = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _failed_observation(
            engine,
            attempt,
            f"{type(exc).__name__}: {exc}",
        )
    return value if isinstance(value, dict) else _failed_observation(
        engine,
        attempt,
        "invalid-worker-result",
    )


def _worker_main(args: argparse.Namespace) -> None:
    from playwright.sync_api import sync_playwright

    engine = str(args.worker_engine)
    attempt = int(args.worker_attempt)
    observation: dict[str, Any]
    try:
        with sync_playwright() as playwright:
            browser = getattr(playwright, engine).launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                )
                try:
                    page = context.new_page()
                    timeline = NavigationTimeline(page, max_events=128)
                    response_status = None
                    error = None
                    try:
                        response = page.goto(
                            str(args.url),
                            wait_until="domcontentloaded",
                            timeout=max(1000, int(args.timeout_ms)),
                        )
                        if response is not None:
                            response_status = response.status
                    except Exception as exc:  # noqa: BLE001 - navigation evidence
                        error = f"{type(exc).__name__}: {exc}"
                    page.wait_for_timeout(max(0, int(args.settle_ms)))
                    final_url = page.url
                    title = ""
                    ready_state = ""
                    body_text_length = None
                    try:
                        title = page.title()
                    except Exception:
                        pass
                    try:
                        document = page.evaluate(r"""() => ({
                          readyState: String(document.readyState || ''),
                          bodyTextLength: document.body
                            ? String(document.body.innerText || '').length
                            : 0,
                        })""")
                        if isinstance(document, dict):
                            ready_state = str(document.get("readyState") or "")
                            body_text_length = _optional_int(
                                document.get("bodyTextLength")
                            )
                    except Exception as exc:  # noqa: BLE001 - keep nav evidence
                        if error is None:
                            error = f"{type(exc).__name__}: {exc}"
                    navigation = classify_capture_navigation(
                        str(args.url),
                        final_url,
                        error=error,
                        navigation_budget_exhausted=True,
                    )
                    observation = {
                        "engine": engine,
                        "attempt": attempt,
                        "valid": True,
                        "navigation": navigation,
                        "http_status": response_status,
                        "final_url": final_url,
                        "title": title,
                        "ready_state": ready_state,
                        "body_text_length": body_text_length,
                        "timeline": timeline.snapshot(),
                        "error": error if navigation["status"] not in NAVIGATION_OK else None,
                    }
                finally:
                    context.close()
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - worker failure stays evidence
        observation = _failed_observation(
            engine,
            attempt,
            f"{type(exc).__name__}: {exc}",
        )
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(observation, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _normalize_observation(item: dict[str, Any]) -> dict[str, Any]:
    timeline = item.get("timeline") or {}
    events = [
        dict(event)
        for event in (timeline.get("events") or [])
        if isinstance(event, dict)
    ]
    request_failed = [
        event for event in events
        if event.get("kind") == "document-request-failed"
    ]
    responses = [
        event for event in events
        if event.get("kind") == "document-response"
    ]
    commits = [
        event for event in events
        if event.get("kind") == "document-commit"
    ]
    return {
        "engine": str(item.get("engine") or ""),
        "attempt": _optional_int(item.get("attempt")),
        "valid": bool(item.get("valid")),
        "navigation": dict(item.get("navigation") or {}),
        "http_status": _optional_int(item.get("http_status")),
        "final_url": str(item.get("final_url") or ""),
        "title": str(item.get("title") or ""),
        "ready_state": str(item.get("ready_state") or ""),
        "body_text_length": _optional_int(item.get("body_text_length")),
        "timeline_truncated": bool(timeline.get("truncated")),
        "request_failed": request_failed,
        "responses": responses,
        "document_commits": commits,
        "frame_generations": dict(timeline.get("frames") or {}),
        "error": item.get("error"),
    }


def _failed_observation(
    engine: str,
    attempt: int,
    error: str,
) -> dict[str, Any]:
    return {
        "engine": engine,
        "attempt": attempt,
        "valid": False,
        "navigation": {"status": "capture-failed"},
        "http_status": None,
        "final_url": "",
        "title": "",
        "ready_state": "",
        "body_text_length": None,
        "timeline": {"events": [], "frames": {}},
        "error": error,
    }


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
