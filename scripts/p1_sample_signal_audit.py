"""Read-only structural signal audit for the P1 sample registry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence import (
    DEFAULT_SAMPLE_SCOPE,
    evaluate_sample_markers,
    load_sample_registry,
    validate_sample_registry,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count structural evidence signals across P1 sample captures."
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
        help="limit the audit to one source kind",
    )
    args = parser.parse_args(argv)

    registry = load_sample_registry(args.registry)
    issues = validate_sample_registry(registry)
    if issues:
        print(json.dumps({"status": "error", "issues": list(issues)}, ensure_ascii=False))
        return 2

    scenario_by_id = {
        item.scenario_id: item for item in DEFAULT_SAMPLE_SCOPE.scenarios
    }
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

    rows: list[dict[str, Any]] = []
    for sample in samples:
        capture_dir = args.sample_root / sample.sample_id
        sidecar_dir = args.sidecar_root / sample.sample_id
        row: dict[str, Any] = {
            "sample_id": sample.sample_id,
            "scenario_id": sample.scenario_id,
            "source_kind": sample.source_kind,
            "expected_page_state": sample.expected_page_state,
        }
        try:
            page_state = json.loads(
                (capture_dir / "00_page_state.json").read_text(encoding="utf-8")
            )
            dom = json.loads(
                (capture_dir / "00_dom.json").read_text(encoding="utf-8")
            )
            diagnostics = json.loads(
                (capture_dir / "00_dom_diagnostics.json").read_text(encoding="utf-8")
            )
            m0_path = capture_dir / "00_dom_m0.json"
            m0_dom = (
                json.loads(m0_path.read_text(encoding="utf-8"))
                if m0_path.is_file()
                else None
            )
            manifest = json.loads(
                (sidecar_dir / "manifest.json").read_text(encoding="utf-8")
            )
            counts = _dom_counts(dom)
            marker_audit = evaluate_sample_markers(sample, dom, page_state)
            ground_truth = _load_ground_truth(sample, _ROOT)
            early_state = _early_state(m0_dom, dom)
            row.update(
                {
                    "status": "ok",
                    "actual_page_state": page_state.get("kind"),
                    "page_state_match": page_state.get("kind")
                    == sample.expected_page_state,
                    "dom_text_chars": sum(
                        len(str(node.get("text") or "")) for node in dom
                    ),
                    "signals": counts,
                    "marker_audit": marker_audit,
                    "diagnostics": {
                        "capture_gaps": diagnostics.get("capture_gaps") or {},
                        "unsupported": diagnostics.get("unsupported") or {},
                        "closed_shadow_roots_observable": (
                            (diagnostics.get("notes") or {}).get(
                                "closed_shadow_roots_observable"
                            )
                        ),
                    },
                    "field_count": manifest.get("field_count"),
                    "unknown_count": manifest.get("unknown_count"),
                    "content_hash": manifest.get("content_hash"),
                    "asset_count": manifest.get("asset_count", 0),
                    "asset_bytes_total": manifest.get("asset_bytes_total", 0),
                    "asset_statuses": _asset_statuses(manifest.get("assets") or []),
                    "browser_engine": (manifest.get("page_state") or {}).get(
                        "browser_engine"
                    ),
                    "ground_truth": ground_truth,
                    "closed_shadow_truth": _closed_shadow_truth(
                        ground_truth, diagnostics
                    ),
                    "early_state": early_state,
                    "notes": _scenario_notes(
                        scenario_by_id[sample.scenario_id].category
                    ),
                }
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            row.update({"status": "error", "error": str(exc)})
        rows.append(row)

    summary = {
        "status": (
            "ok"
            if all(item["status"] == "ok" for item in rows)
            and all(item["marker_audit"]["status"] == "pass" for item in rows)
            else "partial"
        ),
        "registry": str(args.registry),
        "sample_count": len(rows),
        "page_state_match_count": sum(
            bool(item.get("page_state_match")) for item in rows
        ),
        "marker_pass_count": sum(
            item.get("marker_audit", {}).get("status") == "pass"
            for item in rows
        ),
        "ground_truth_sample_count": sum(
            bool(item.get("ground_truth")) for item in rows
        ),
        "early_state_sample_count": sum(
            bool((item.get("early_state") or {}).get("dom_present"))
            for item in rows
        ),
        "state_transition_pass_count": sum(
            (item.get("early_state") or {}).get("text_changed") is True
            for item in rows
        ),
        "rows": rows,
        "interpretation": (
            "Counts are captured DOM signals, not acceptance results. "
            "Closed shadow roots, M0 shells, OCR quality and original asset bytes "
            "require separate ground truth or detector runs."
        ),
    }
    args.sidecar_root.mkdir(parents=True, exist_ok=True)
    output_path = args.sidecar_root / "sample_signal_summary.json"
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": summary["status"],
        "sample_count": summary["sample_count"],
        "page_state_match_count": summary["page_state_match_count"],
        "marker_pass_count": summary["marker_pass_count"],
        "ground_truth_sample_count": summary["ground_truth_sample_count"],
        "early_state_sample_count": summary["early_state_sample_count"],
        "state_transition_pass_count": summary["state_transition_pass_count"],
        "output": str(output_path),
    }, ensure_ascii=False))
    return 0 if summary["status"] == "ok" else 1


def _dom_counts(dom: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "nodes": len(dom),
        "iframe": sum(node.get("tag") == "iframe" for node in dom),
        "shadow": sum(bool(node.get("shadow")) for node in dom),
        "canvas": sum(node.get("tag") == "canvas" for node in dom),
        "img": sum(node.get("tag") == "img" for node in dom),
        "svg": sum(node.get("tag") == "svg" for node in dom),
        "background_image": sum(bool(node.get("bgImage")) for node in dom),
        "icon_box": sum(bool(node.get("iconBox")) for node in dom),
    }


def _scenario_notes(category: str) -> list[str]:
    common = ["captured DOM signal count; not an acceptance result"]
    notes = {
        "iframe": ["child document scope is not recursively audited here"],
        "shadow-dom": ["closed shadow roots remain unobservable without external ground truth"],
        "canvas": ["canvas text quality is not checked without an OCR run"],
        "dynamic-state": ["only the settled capture is present; M0 shell is not separately captured"],
        "ocr": ["no OCR engine is executed by this audit"],
        "assets": ["original asset bytes and replaceability are not resolved here"],
        "capture-fallback": ["no credential or challenge bypass is attempted"],
    }
    return common + notes.get(category, [])


def _asset_statuses(assets: list[dict[str, Any]]) -> dict[str, int]:
    statuses: dict[str, int] = {}
    for asset in assets:
        status = str(asset.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    return statuses


def _load_ground_truth(
    sample: Any,
    project_root: Path,
) -> dict[str, Any] | None:
    locator = str(sample.locator or "")
    if locator.startswith(("http://", "https://", "file://")):
        return None
    fixture = Path(project_root) / locator
    truth_path = fixture.with_suffix(".truth.json")
    if not truth_path.is_file():
        return None
    return json.loads(truth_path.read_text(encoding="utf-8"))


def _closed_shadow_truth(
    ground_truth: dict[str, Any] | None,
    diagnostics: dict[str, Any],
) -> str:
    if not ground_truth or int(ground_truth.get("closed_shadow_roots") or 0) <= 0:
        return "not-declared"
    observable = bool(
        (diagnostics.get("notes") or {}).get("closed_shadow_roots_observable")
    )
    return "declared-but-observable" if observable else "declared-unobservable"


def _early_state(
    m0_dom: list[dict[str, Any]] | None,
    m1_dom: list[dict[str, Any]],
) -> dict[str, Any]:
    if m0_dom is None:
        return {
            "dom_present": False,
            "m0_dom_nodes": None,
            "m1_dom_nodes": len(m1_dom),
            "text_changed": None,
        }
    m0_text = _text_sequence(m0_dom)
    m1_text = _text_sequence(m1_dom)
    return {
        "dom_present": True,
        "m0_dom_nodes": len(m0_dom),
        "m1_dom_nodes": len(m1_dom),
        "m0_text": m0_text,
        "m1_text": m1_text,
        "text_changed": m0_text != m1_text,
    }


def _text_sequence(dom: list[dict[str, Any]]) -> list[str]:
    return [
        str(node.get("text") or "")
        for node in dom
        if str(node.get("text") or "").strip()
    ]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
