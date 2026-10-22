"""Run one bounded S06 navigation timeline diagnostic."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure.capture_outcome import classify_capture_outcome
from src.app.services.structure.capture_state import evaluate_state_gate


DEFAULT_URL = "https://www.dushu.com/"
FAILED_NAVIGATION_STATES = {"browser-navigation-failed", "navigation-failed"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded Chromium/WebKit navigation timeline probe."
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--screenshot-timeout-ms", type=int, default=10000)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=_ROOT / "output" / "_p1_navigation_timeline",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=(
            _ROOT
            / "output"
            / "_p1_navigation_timeline"
            / "s06_timeline_round1.json"
        ),
    )
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    attempts = max(1, int(args.attempts))
    run_id = "timeline-S06-round1"
    sidecar_root = args.out_root / "sidecars"
    capture_root = args.out_root / "captures"
    summary_path = sidecar_root / run_id / "pair_summary.json"
    command = [
        sys.executable,
        str(_ROOT / "scripts" / "p1_dual_browser_capture.py"),
        "--url",
        str(args.url),
        "--sample-id",
        run_id,
        "--out-root",
        str(capture_root),
        "--sidecar-root",
        str(sidecar_root),
        "--timeout-ms",
        str(max(1000, int(args.timeout_ms))),
        "--screenshot-timeout-ms",
        str(max(1000, int(args.screenshot_timeout_ms))),
        "--retries",
        str(attempts - 1),
    ]
    completed = None
    timed_out = False
    subprocess_error = None
    timeout_seconds = max(120, attempts * 180)
    if not args.reuse_existing:
        try:
            completed = subprocess.run(
                command,
                cwd=str(_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            subprocess_error = (
                f"TimeoutExpired: child capture exceeded {timeout_seconds}s"
            )
            completed = exc
    pair: dict[str, Any]
    recovered = False
    if summary_path.is_file():
        pair = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        attempts_data = recover_partial_attempts(
            sidecar_root / run_id,
            capture_run_root=capture_root / run_id,
        )
        if not attempts_data:
            error = subprocess_error or (
                (completed.stderr or completed.stdout or "").strip()[-1600:]
                if isinstance(completed, subprocess.CompletedProcess)
                else "pair summary missing"
            )
            raise SystemExit(error or "pair summary missing")
        recovered = True
        pair = {
            "state_attempts": attempts_data,
            "selected_state_attempt": _select_recovered_attempt(attempts_data),
        }
    summary = summarize_navigation_attempts(
        list(pair.get("state_attempts") or []),
        selected_attempt=pair.get("selected_state_attempt"),
    )
    result = {
        "schema_version": "p1-navigation-timeline-probe/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_id": "P1-S06-R1",
        "url": str(args.url),
        "run_id": run_id,
        "pair_summary": str(summary_path),
        "fixed_budget": {
            "attempts": attempts,
            "timeout_ms": int(args.timeout_ms),
            "screenshot_timeout_ms": int(args.screenshot_timeout_ms),
            "max_timeline_events_per_engine_attempt": 128,
            "outer_timeout_seconds": timeout_seconds,
        },
        "collection": {
            "timed_out": timed_out,
            "reuse_existing": bool(args.reuse_existing),
            "recovered_from_partial_sidecars": recovered,
            "error": subprocess_error,
            "diagnostic_incomplete": recovered or timed_out,
        },
        "summary": summary,
        "note": (
            "This diagnostic separates navigation failure from a committed DOM "
            "difference. It does not add global retries or change the default "
            "capture policy."
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


def summarize_navigation_attempts(
    attempts: Sequence[dict[str, Any]],
    *,
    selected_attempt: int | None = None,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    by_attempt: dict[int, dict[str, Any]] = {}
    for item in attempts:
        if not isinstance(item, dict):
            continue
        attempt = _optional_int(item.get("attempt"))
        if attempt is None:
            continue
        engines = {
            str(engine): _engine_timeline(record)
            for engine, record in (item.get("engines") or {}).items()
            if isinstance(record, dict)
        }
        reasons = list((item.get("state_gate") or {}).get("reasons") or [])
        reason, classification = _classify_attempt(
            engines,
            gate_reasons=reasons,
            comparable=bool((item.get("state_gate") or {}).get("comparable")),
        )
        record = {
            "attempt": attempt,
            "classification": classification,
            "reason": reason,
            "state_gate_reasons": reasons,
            "engines": engines,
        }
        records.append(record)
        by_attempt[attempt] = record

    primary = by_attempt.get(_optional_int(selected_attempt))
    if primary is None and records:
        primary = records[0]
    request_events = [
        event
        for record in records
        for engine in record["engines"].values()
        for event in engine["request_failed"]
    ]
    response_statuses = sorted({
        status
        for record in records
        for engine in record["engines"].values()
        for status in engine["response_statuses"]
    })
    classification = (
        primary["classification"] if primary is not None else "capture-failed"
    )
    return {
        "classification": classification,
        "primary_attempt": primary["attempt"] if primary is not None else None,
        "selected_attempt_reason": (
            primary["reason"] if primary is not None else "capture-failed"
        ),
        "stable_dom_difference_claimed": classification == "stable-dom-difference",
        "request_failed_count": len(request_events),
        "request_failed": request_events,
        "response_statuses": response_statuses,
        "attempts": records,
        "note": (
            "Only the capture contract's selected attempt is primary. Later "
            "committed attempts are retained as supplementary evidence."
        ),
    }


def recover_partial_attempts(
    sidecar_run_root: Path,
    *,
    capture_run_root: Path | None = None,
) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    source_roots = [
        path
        for path in (sidecar_run_root, capture_run_root)
        if path is not None and path.is_dir()
    ]
    if not source_roots:
        return attempts
    attempt_names = sorted({
        path.name
        for root in source_roots
        for path in root.glob("_attempt_*")
        if path.is_dir()
    })
    for attempt_name in attempt_names:
        suffix = attempt_name.rsplit("_", 1)[-1]
        attempt = _optional_int(suffix)
        if attempt is None:
            continue
        engines: dict[str, dict[str, Any]] = {}
        dom_paths: dict[str, Path] = {}
        state_paths: dict[str, Path] = {}
        for engine in ("chromium", "webkit"):
            engine_root = _first_engine_root(
                source_roots,
                attempt_name,
                engine,
            )
            state_path = engine_root / "00_page_state.json"
            dom_path = engine_root / "00_dom.json"
            if state_path.is_file():
                state = _read_json(state_path)
                engines[engine] = {
                    "status": "ok",
                    "navigation": state.get("navigation") or {},
                    "page_state": state,
                    "frame_summary": state.get("frame_summary") or {},
                }
                if dom_path.is_file():
                    dom_paths[engine] = dom_path
                    state_paths[engine] = state_path
            else:
                engines[engine] = {
                    "status": "error",
                    "error": "recovered page_state missing",
                    "navigation": {"status": "capture-failed"},
                    "page_state": {},
                    "frame_summary": {},
                }
        gate: dict[str, Any] = {
            "comparable": False,
            "reasons": ["capture-artifacts-missing"],
        }
        if (
            {"chromium", "webkit"}.issubset(dom_paths)
            and {"chromium", "webkit"}.issubset(state_paths)
        ):
            evaluated = evaluate_state_gate(
                _read_json(dom_paths["chromium"]),
                _read_json(state_paths["chromium"]),
                _read_json(dom_paths["webkit"]),
                _read_json(state_paths["webkit"]),
                require_stability=True,
            )
            gate = {
                "comparable": evaluated["comparable"],
                "reasons": evaluated["reasons"],
                "chromium": evaluated["left"],
                "webkit": evaluated["right"],
            }
        attempts.append({
            "attempt": attempt,
            "recovered": True,
            "state_gate": gate,
            "engines": engines,
        })
    return attempts


def _first_engine_root(
    roots: Sequence[Path],
    attempt_name: str,
    engine: str,
) -> Path:
    for root in reversed(roots):
        candidate = root / attempt_name / engine
        if (candidate / "00_page_state.json").is_file():
            return candidate
    return roots[-1] / attempt_name / engine


def _select_recovered_attempt(
    attempts: Sequence[dict[str, Any]],
) -> int | None:
    if not attempts:
        return None
    for item in attempts:
        outcome = classify_capture_outcome(
            item.get("state_gate") or {},
            item.get("engines") or {},
            None,
            content_comparable=False,
        )
        if outcome["execution_status"] == "ready":
            return _optional_int(item.get("attempt"))
    return _optional_int(attempts[0].get("attempt"))


def _engine_timeline(record: dict[str, Any]) -> dict[str, Any]:
    page_state = record.get("page_state") or {}
    timeline = page_state.get("navigation_timeline") or {}
    events = [
        dict(event)
        for event in (timeline.get("events") or [])
        if isinstance(event, dict)
    ]
    counts = Counter(str(event.get("kind") or "") for event in events)
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
        "status": record.get("status"),
        "navigation": dict(record.get("navigation") or {}),
        "stable": bool(
            (page_state.get("capture_stability") or {}).get("stable")
        ),
        "timeline_available": bool(timeline),
        "timeline_truncated": bool(timeline.get("truncated")),
        "event_counts": dict(sorted(counts.items())),
        "request_failed": request_failed,
        "responses": responses,
        "response_statuses": [
            int(event["status"])
            for event in responses
            if _optional_int(event.get("status")) is not None
        ],
        "document_commits": commits,
        "frame_generations": dict(timeline.get("frames") or {}),
    }


def _classify_attempt(
    engines: dict[str, dict[str, Any]],
    *,
    gate_reasons: list[str],
    comparable: bool,
) -> tuple[str, str]:
    failed = [
        engine
        for engine, record in engines.items()
        if str((record.get("navigation") or {}).get("status") or "")
        in FAILED_NAVIGATION_STATES
    ]
    if failed:
        return "navigation-failed-before-comparable-dom", "navigation-failure"
    if (
        "state-unstable" in gate_reasons
        or any(not record.get("stable") for record in engines.values())
    ):
        return "navigation-committed-state-unstable", "state-unstable"
    if comparable:
        return "navigation-committed-equivalent-state", "equivalent-state"
    return (
        "navigation-committed-stable-dom-difference",
        "stable-dom-difference",
    )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
