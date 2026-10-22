"""Capture one URL concurrently in Chromium and WebKit, then gate comparison."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence import write_evidence_sidecar
from src.app.services.structure.capture import (
    CAPTURE_STATE_JS,
    capture_page_with_fallback,
)
from src.app.services.structure.capture_state import evaluate_state_gate, text_delta
from src.app.services.structure.capture_outcome import classify_capture_outcome
from src.app.services.structure.frame_boundary import (
    RENDERED_FRAME_BOUNDARY_SCOPE,
    compare_rendered_frame_boundaries,
)
from src.app.services.structure.frame_barrier import FrameBarrierGate
from src.app.services.structure.frames import capture_frame_state
from src.config.settings import Config
from scripts.p1_cross_browser_compare import _align_text_nodes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run concurrent Chromium/WebKit captures for one URL."
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=_ROOT / "output" / "_p1_dual_capture",
    )
    parser.add_argument(
        "--sidecar-root",
        type=Path,
        default=_ROOT / "output" / "_p1_dual_sidecars",
    )
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--screenshot-timeout-ms", type=int, default=10000)
    parser.add_argument("--snapshot-sync-timeout-ms", type=int, default=3000)
    parser.add_argument(
        "--snapshot-barrier",
        action="store_true",
        help=(
            "release both final DOM snapshots through a barrier; keep this off "
            "when one browser may fail navigation independently"
        ),
    )
    parser.add_argument(
        "--frame-barrier",
        action="store_true",
        help=(
            "synchronize one rendered frame-tree probe before the final DOM "
            "snapshot; experimental and disabled by default"
        ),
    )
    parser.add_argument(
        "--first-party-frame-profile",
        action="store_true",
        help=(
            "block cross-origin frame document requests and mark the result as "
            "first-party-frame-strict/1.0; experimental"
        ),
    )
    parser.add_argument(
        "--rendered-frame-boundary-profile",
        action="store_true",
        help=(
            "compare rendered frame boundaries under "
            "rendered-frame-boundary-strict/1.0; experimental"
        ),
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
    help="extra synchronized pairs to try while capture execution is not ready",
    )
    parser.add_argument("--captured-at")
    args = parser.parse_args(argv)
    if args.first_party_frame_profile and args.rendered_frame_boundary_profile:
        raise SystemExit(
            "--first-party-frame-profile and --rendered-frame-boundary-profile "
            "must run as separate scopes"
        )

    captured_at = (
        datetime.fromisoformat(args.captured_at)
        if args.captured_at
        else datetime.now(timezone.utc)
    )
    sample_out = args.out_root / args.sample_id
    sample_sidecar = args.sidecar_root / args.sample_id
    configs = {
        engine: Config(
            playwright_browser=engine,
            playwright_headless=True,
            playwright_headed_fallback=False,
            wait_networkidle_timeout=max(1000, args.timeout_ms),
        )
        for engine in ("chromium", "webkit")
    }

    attempts = max(1, int(args.retries) + 1)
    history: list[dict[str, Any]] = []
    accepted_candidate: dict[str, Any] | None = None
    for attempt in range(1, attempts + 1):
        start_barrier = threading.Barrier(2)
        snapshot_barrier = threading.Barrier(2)
        frame_gate = FrameBarrierGate(
            timeout_s=max(1, args.snapshot_sync_timeout_ms / 1000)
        )
        attempt_root = sample_out / f"_attempt_{attempt:02d}"
        attempt_sidecar = sample_sidecar / f"_attempt_{attempt:02d}"

        def run(engine: str) -> dict[str, Any]:
            capture_dir = attempt_root / engine
            sidecar_dir = attempt_sidecar / engine
            record: dict[str, Any] = {
                "engine": engine,
                "capture_dir": str(capture_dir),
                "sidecar_dir": str(sidecar_dir),
                "state_attempt": attempt,
            }
            try:
                start_barrier.wait(timeout=max(5, args.timeout_ms / 1000))
                captured = capture_page_with_fallback(
                    args.url,
                    configs[engine],
                    str(capture_dir),
                    requested_route="auto",
                    allow_real_session=False,
                    browser_engine=engine,
                    capture_attempts=1,
                    screenshot_timeout_ms=max(1000, args.screenshot_timeout_ms),
                    snapshot_sync=lambda page: _snapshot_barrier(
                        engine,
                        page,
                        frame_gate=frame_gate,
                        snapshot_barrier=snapshot_barrier,
                        use_frame_barrier=args.frame_barrier,
                        use_snapshot_barrier=args.snapshot_barrier,
                        timeout_s=max(1, args.snapshot_sync_timeout_ms / 1000),
                    ),
                    block_cross_origin_frame_documents=(
                        args.first_party_frame_profile
                    ),
                    capture_navigation_timeline=True,
                )
                record["page_state"] = captured.get("page_state") or {}
                record["navigation"] = captured.get("navigation") or {}
                record["frame_summary"] = captured.get("frame_summary") or {}
                record["frame_barrier"] = (
                    (captured.get("capture_stability") or {}).get("frame_barrier")
                )
                record["capture_profile"] = captured.get("capture_profile")
                record["frame_request_policy"] = captured.get("frame_request_policy")
                sidecar = write_evidence_sidecar(
                    capture_dir,
                    sidecar_dir,
                    captured_at=captured_at,
                    job_id=(
                        f"p1-dual-{args.sample_id}-attempt-{attempt}-{engine}"
                    ),
                    overwrite=True,
                )
                record["status"] = "ok"
                record["field_count"] = len(sidecar.runtime_ir.fields)
                record["content_hash"] = sidecar.manifest.get("content_hash")
            except Exception as exc:  # noqa: BLE001
                record.update({
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                })
            return record

        with ThreadPoolExecutor(max_workers=2) as pool:
            records = list(pool.map(run, ("chromium", "webkit")))
        by_engine = {item["engine"]: item for item in records}
        candidate = _inspect_attempt(
            attempt,
            attempt_root,
            by_engine,
            use_rendered_frame_boundary=args.rendered_frame_boundary_profile,
        )
        history.append(candidate)
        if candidate["execution_status"] == "ready":
            accepted_candidate = candidate
            break
        if attempt < attempts:
            time.sleep(_retry_delay_ms(attempt - 1) / 1000)

    selected = accepted_candidate or _select_accepted_attempt(history)
    selected_attempt = int(selected["attempt"])
    selected_records = list(selected["engines"].values())
    gate = selected["state_gate"]
    legacy_gate = selected.get("legacy_state_gate") or gate
    by_engine = selected["engines"]
    selected_root = sample_out / f"_attempt_{selected_attempt:02d}"
    geometry = (
        _geometry_delta(
            _read_json(selected_root / "chromium" / "00_dom.json"),
            _read_json(selected_root / "webkit" / "00_dom.json"),
        )
        if legacy_gate["comparable"]
        else {"aligned": False, "skipped": True, "reason": "state-gate-failed"}
    )
    result = {
        "schema_version": "p1-dual-browser-capture/1.5",
        "sample_id": args.sample_id,
        "url": args.url,
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
        "status": (
            "ok"
            if all(item["status"] == "ok" for item in selected_records)
            else "partial"
        ),
        "engines": by_engine,
        "state_gate": gate,
        "execution_status": selected["execution_status"],
        "execution_reasons": selected["execution_reasons"],
        "comparison_result": selected["comparison_result"],
        "comparison_reasons": selected["comparison_reasons"],
        "limitations": selected["limitations"],
        "failure_classification": selected["failure_classification"],
        "text_delta": selected["text_delta"],
        "text_alignment": selected["text_alignment"],
        "content_comparable": selected["content_comparable"],
        "comparison_scope": selected["comparison_scope"],
        "comparison_profile": selected["comparison_profile"],
        "legacy_state_gate": legacy_gate,
        "legacy_comparison_result": selected.get("legacy_comparison_result"),
        "legacy_comparison_reasons": selected.get("legacy_comparison_reasons") or [],
        "rendered_frame_boundary": selected.get("rendered_frame_boundary"),
        "geometry": geometry,
        "selected_state_attempt": selected_attempt,
        "selection_rule": "first-ready-attempt",
        "frame_barrier_enabled": bool(args.frame_barrier),
        "capture_profile": _capture_profile_id(by_engine),
        "state_attempts": history,
        "note": (
            "The first stable pair is compared without choosing a later easier "
            "round. Execution readiness and comparison result are separate. "
            "Content scope is text-only, never whole-page equivalence."
        ),
    }
    sample_sidecar.mkdir(parents=True, exist_ok=True)
    out_path = sample_sidecar / "pair_summary.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "sample_id": args.sample_id,
        "execution_status": result["execution_status"],
        "comparison_result": result["comparison_result"],
        "state_comparable": gate["comparable"],
        "gate_reasons": gate["reasons"],
        "content_comparable": result["content_comparable"],
        "comparison_scope": result["comparison_scope"],
        "geometry_max": geometry.get("max"),
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


def _inspect_attempt(
    attempt: int,
    attempt_root: Path,
    by_engine: dict[str, dict[str, Any]],
    *,
    use_rendered_frame_boundary: bool = False,
) -> dict[str, Any]:
    chromium_dom_path = attempt_root / "chromium" / "00_dom.json"
    webkit_dom_path = attempt_root / "webkit" / "00_dom.json"
    chromium_state_path = attempt_root / "chromium" / "00_page_state.json"
    webkit_state_path = attempt_root / "webkit" / "00_page_state.json"
    gate = _gate_captures(
        chromium_dom_path,
        webkit_dom_path,
        chromium_state_path,
        webkit_state_path,
    )
    legacy_gate = gate
    page_states = {}
    if chromium_state_path.is_file() and webkit_state_path.is_file():
        page_states = {
            "chromium": _read_json(chromium_state_path),
            "webkit": _read_json(webkit_state_path),
        }
    alignment: dict[str, Any] | None = None
    delta: dict[str, Any] | None = None
    if chromium_dom_path.is_file() and webkit_dom_path.is_file():
        chromium_dom = _read_json(chromium_dom_path)
        webkit_dom = _read_json(webkit_dom_path)
        alignment = _align_text_nodes(chromium_dom, webkit_dom)
        delta = text_delta(chromium_dom, webkit_dom)
    content_comparable = _content_comparable(gate, alignment)
    capture_profile = _capture_profile_id(by_engine)
    legacy_outcome = classify_capture_outcome(
        legacy_gate,
        by_engine,
        delta,
        content_comparable=content_comparable,
        profile_id=capture_profile,
    )
    boundary = None
    if use_rendered_frame_boundary:
        boundary = (
            _boundary_gate(
                page_states.get("chromium") or {},
                page_states.get("webkit") or {},
            )
            if page_states
            else _boundary_gate({}, {})
        )
        gate = boundary
        profile_id = RENDERED_FRAME_BOUNDARY_SCOPE
    else:
        profile_id = capture_profile
    outcome = classify_capture_outcome(
        gate,
        by_engine,
        delta,
        content_comparable=(
            False if use_rendered_frame_boundary else content_comparable
        ),
        profile_id=profile_id,
    )
    comparison_scope = _comparison_scope(
        gate,
        content_comparable=content_comparable,
        profile_id=profile_id,
        use_rendered_frame_boundary=use_rendered_frame_boundary,
    )
    return {
        "attempt": attempt,
        "status": (
            "ok"
            if all(item["status"] == "ok" for item in by_engine.values())
            else "partial"
        ),
        "state_gate": gate,
        "legacy_state_gate": legacy_gate,
        "legacy_outcome": legacy_outcome,
        "legacy_comparison_result": legacy_outcome["comparison_result"],
        "legacy_comparison_reasons": legacy_outcome["comparison_reasons"],
        "execution_status": outcome["execution_status"],
        "execution_reasons": outcome["execution_reasons"],
        "comparison_result": outcome["comparison_result"],
        "comparison_reasons": outcome["comparison_reasons"],
        "limitations": outcome["limitations"],
        "outcome": outcome,
        "capture_profile": capture_profile,
        "comparison_profile": profile_id,
        "rendered_frame_boundary": boundary,
        "failure_classification": _classify_failure(gate, by_engine, delta),
        "text_delta": delta,
        "text_alignment": alignment,
        "content_comparable": (
            False if use_rendered_frame_boundary else content_comparable
        ),
        "legacy_content_comparable": content_comparable,
        "comparison_scope": comparison_scope,
        "engines": by_engine,
    }


def _snapshot_barrier(
    engine: str,
    page: Any,
    *,
    frame_gate: FrameBarrierGate,
    snapshot_barrier: threading.Barrier,
    use_frame_barrier: bool,
    use_snapshot_barrier: bool,
    timeout_s: float,
) -> dict[str, Any] | None:
    if not use_frame_barrier and not use_snapshot_barrier:
        return None
    result: dict[str, Any] = {}
    if use_frame_barrier:
        frames = capture_frame_state(
            page,
            CAPTURE_STATE_JS,
            include_unrendered=False,
        )
        result.update(frame_gate.sync(engine, frames))
    if use_snapshot_barrier:
        snapshot_barrier.wait(timeout=max(1, timeout_s))
        result["snapshot_synchronized"] = True
    return result


def _select_accepted_attempt(
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    if not history:
        raise ValueError("attempt history must not be empty")
    for candidate in history:
        if candidate.get("execution_status") == "ready":
            return candidate
    return history[0]


def _capture_profile_id(engines: dict[str, dict[str, Any]]) -> str:
    values = {
        str(item.get("capture_profile") or "")
        for item in engines.values()
        if isinstance(item, dict)
    }
    if values == {"first-party-frame-strict/1.0"}:
        return "first-party-frame-strict/1.0"
    return "rendered-frame-state-strict/1.0"


def _retry_delay_ms(attempt_index: int, *, base_ms: int = 250, cap_ms: int = 2000) -> int:
    index = max(0, int(attempt_index))
    base = max(1, int(base_ms))
    cap = max(base, int(cap_ms))
    return min(cap, base * (2 ** min(index, 16)))


def _classify_failure(
    gate: dict[str, Any],
    engines: dict[str, dict[str, Any]],
    delta: dict[str, Any] | None,
) -> str | None:
    if gate.get("comparable"):
        return None
    for engine in engines.values():
        navigation = engine.get("navigation") or {}
        if navigation.get("status") == "browser-navigation-failed":
            return "browser-navigation-failed"
    if (delta or {}).get("classification") == "dynamic-glyph":
        return "dynamic-glyph"
    if "frame-inventory-mismatch" in (gate.get("reasons") or []):
        return "frame-scope-mismatch"
    if any(
        str(reason).startswith("frame-")
        for reason in (gate.get("reasons") or [])
    ):
        return "frame-boundary-difference"
    return "dom-state-difference"


def _boundary_gate(
    left_page_state: dict[str, Any],
    right_page_state: dict[str, Any],
) -> dict[str, Any]:
    boundary = compare_rendered_frame_boundaries(
        left_page_state,
        right_page_state,
    )
    return {
        "comparable": boundary["comparable"],
        "reasons": list(boundary["reasons"]),
        "comparison_profile": RENDERED_FRAME_BOUNDARY_SCOPE,
        "boundary_observation_complete": boundary[
            "boundary_observation_complete"
        ],
        "chromium": {
            "frame_count": boundary["left_frame_count"],
        },
        "webkit": {
            "frame_count": boundary["right_frame_count"],
        },
        "boundary": boundary,
    }


def _comparison_scope(
    gate: dict[str, Any],
    *,
    content_comparable: bool,
    profile_id: str,
    use_rendered_frame_boundary: bool,
) -> str:
    if use_rendered_frame_boundary:
        return RENDERED_FRAME_BOUNDARY_SCOPE
    if gate.get("comparable"):
        return "strict"
    if content_comparable:
        return "content"
    return "blocked"


def _content_comparable(
    gate: dict[str, Any],
    alignment: dict[str, Any] | None,
) -> bool:
    if gate.get("comparable"):
        return True
    if "chromium" not in gate or "webkit" not in gate:
        return False
    return bool(
        gate["chromium"].get("url") == gate["webkit"].get("url")
        and gate["chromium"].get("text_sha256")
        == gate["webkit"].get("text_sha256")
        and float((alignment or {}).get("coverage") or 0) >= 0.95
    )


def _gate_captures(
    chromium_dom_path: Path,
    webkit_dom_path: Path,
    chromium_state_path: Path,
    webkit_state_path: Path,
) -> dict[str, Any]:
    if not all(path.is_file() for path in (
        chromium_dom_path,
        webkit_dom_path,
        chromium_state_path,
        webkit_state_path,
    )):
        return {"comparable": False, "reasons": ["capture-artifacts-missing"]}
    gate = evaluate_state_gate(
        _read_json(chromium_dom_path),
        _read_json(chromium_state_path),
        _read_json(webkit_dom_path),
        _read_json(webkit_state_path),
        require_stability=True,
    )
    return {
        "comparable": gate["comparable"],
        "reasons": gate["reasons"],
        "chromium": gate["left"],
        "webkit": gate["right"],
    }


def _geometry_delta(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    if len(left) != len(right):
        return {
            "aligned": False,
            "reason": "node count differs",
            "chromium_nodes": len(left),
            "webkit_nodes": len(right),
        }
    deltas = []
    for a, b in zip(left, right):
        for key in ("x", "y", "w", "h"):
            deltas.append(abs(float(a.get(key) or 0) - float(b.get(key) or 0)))
    ordered = sorted(deltas)
    return {
        "aligned": True,
        "samples": len(deltas),
        "max": max(deltas) if deltas else None,
        "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else None,
        "over_1px": sum(item > 1 for item in deltas),
        "over_2px": sum(item > 2 for item in deltas),
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
