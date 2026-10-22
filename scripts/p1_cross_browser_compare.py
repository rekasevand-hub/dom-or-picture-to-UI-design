"""Compare Chromium and WebKit captures for controlled P1 fixtures."""
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
    evaluate_sample_markers,
    load_sample_registry,
    marker_counts,
    validate_sample_registry,
)
from src.app.services.structure.capture_state import evaluate_state_gate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare Chromium and WebKit controlled P1 captures."
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=_ROOT / "docs" / "v2_mentor" / "p1_sample_registry.json",
    )
    parser.add_argument(
        "--chromium-root",
        type=Path,
        default=_ROOT / "output" / "_p1_samples",
    )
    parser.add_argument(
        "--webkit-root",
        type=Path,
        default=_ROOT / "output" / "_p1_samples_webkit",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "output" / "_p1_evidence_shadow_webkit" / "cross_browser_summary.json",
    )
    parser.add_argument("--only", help="comma-separated controlled sample IDs")
    parser.add_argument(
        "--source-kind",
        choices=("controlled", "real"),
        default="controlled",
    )
    args = parser.parse_args(argv)

    registry = load_sample_registry(args.registry)
    issues = validate_sample_registry(registry)
    if issues:
        print(json.dumps({"status": "error", "issues": list(issues)}, ensure_ascii=False))
        return 2
    only = {item.strip() for item in (args.only or "").split(",") if item.strip()}
    samples = [
        item
        for item in registry.samples
        if item.source_kind == args.source_kind
        and (not only or item.sample_id in only)
    ]
    if not samples:
        print(json.dumps({"status": "error", "error": "no samples selected"}))
        return 2
    rows: list[dict[str, Any]] = []
    for sample in samples:
        row: dict[str, Any] = {"sample_id": sample.sample_id}
        try:
            chromium = _load_capture(args.chromium_root / sample.sample_id)
            webkit = _load_capture(args.webkit_root / sample.sample_id)
            chromium_counts = marker_counts(chromium["dom"])
            webkit_counts = marker_counts(webkit["dom"])
            state_gate = _state_gate(chromium, webkit)
            text_alignment = _align_text_nodes(chromium["dom"], webkit["dom"])
            content_comparable = (
                state_gate["chromium"]["url"] == state_gate["webkit"]["url"]
                and state_gate["chromium"]["text_sha256"]
                == state_gate["webkit"]["text_sha256"]
                and float(text_alignment.get("coverage") or 0) >= 0.95
            )
            geometry = (
                _geometry_delta(chromium["dom"], webkit["dom"])
                if state_gate["comparable"]
                else {
                    "aligned": False,
                    "skipped": True,
                    "reason": "state-gate-failed",
                }
            )
            row.update(
                {
                    "status": "compared",
                    "chromium_page_state": chromium["page_state"].get("kind"),
                    "webkit_page_state": webkit["page_state"].get("kind"),
                    "page_state_match": chromium["page_state"].get("kind")
                    == webkit["page_state"].get("kind"),
                    "node_count_match": chromium_counts["dom_nodes"]
                    == webkit_counts["dom_nodes"],
                    "text_sequence_match": _text_sequence(chromium["dom"])
                    == _text_sequence(webkit["dom"]),
                    "signal_counts_match": chromium_counts == webkit_counts,
                    "state_gate": state_gate,
                    "content_comparable": content_comparable,
                    "comparison_scope": (
                        "strict"
                        if state_gate["comparable"]
                        else "content"
                        if content_comparable
                        else "blocked"
                    ),
                    "text_alignment": text_alignment,
                    "chromium_counts": chromium_counts,
                    "webkit_counts": webkit_counts,
                    "geometry": geometry,
                    "chromium_marker_audit": evaluate_sample_markers(
                        sample, chromium["dom"], chromium["page_state"]
                    ),
                    "webkit_marker_audit": evaluate_sample_markers(
                        sample, webkit["dom"], webkit["page_state"]
                    ),
                }
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            row.update({"status": "error", "error": str(exc)})
        rows.append(row)

    summary = {
        "status": "ok" if all(item["status"] == "compared" for item in rows) else "partial",
        "browser_a": "chromium",
        "browser_b": "webkit",
        "sample_count": len(rows),
        "page_state_match_count": sum(bool(item.get("page_state_match")) for item in rows),
        "node_count_match_count": sum(bool(item.get("node_count_match")) for item in rows),
        "text_sequence_match_count": sum(
            bool(item.get("text_sequence_match")) for item in rows
        ),
        "signal_count_match_count": sum(
            bool(item.get("signal_counts_match")) for item in rows
        ),
        "state_comparable_count": sum(
            bool((item.get("state_gate") or {}).get("comparable"))
            for item in rows
        ),
        "content_comparable_count": sum(
            bool(item.get("content_comparable")) for item in rows
        ),
        "text_alignment_matched_count": sum(
            int((item.get("text_alignment") or {}).get("matched_count") or 0)
            for item in rows
        ),
        "text_alignment_coverage_avg": round(
            sum(
                float((item.get("text_alignment") or {}).get("coverage") or 0)
                for item in rows
            ) / len(rows),
            6,
        ) if rows else 0,
        "rows": rows,
        "interpretation": (
            "Strict scope requires matching URL, text hash, visible node count, "
            "and semantic structure hash. Content scope requires matching URL "
            "and text hash plus >=95% one-to-one text-node coverage; it is not "
            "whole-page equivalence. DOM-order geometry is computed only after "
            "the strict gate passes."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": summary["status"],
        "sample_count": summary["sample_count"],
        "page_state_match_count": summary["page_state_match_count"],
        "node_count_match_count": summary["node_count_match_count"],
        "text_sequence_match_count": summary["text_sequence_match_count"],
        "signal_count_match_count": summary["signal_count_match_count"],
        "state_comparable_count": summary["state_comparable_count"],
        "content_comparable_count": summary["content_comparable_count"],
        "text_alignment_matched_count": summary["text_alignment_matched_count"],
        "text_alignment_coverage_avg": summary["text_alignment_coverage_avg"],
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0 if summary["status"] == "ok" else 1


def _load_capture(root: Path) -> dict[str, Any]:
    return {
        "page_state": json.loads(
            (root / "00_page_state.json").read_text(encoding="utf-8")
        ),
        "dom": json.loads(
            (root / "00_dom.json").read_text(encoding="utf-8")
        ),
    }


def _text_sequence(dom: list[dict[str, Any]]) -> list[str]:
    return [
        str(node.get("text") or "")
        for node in dom
        if str(node.get("text") or "").strip()
    ]


def _state_gate(
    chromium: dict[str, Any],
    webkit: dict[str, Any],
) -> dict[str, Any]:
    gate = evaluate_state_gate(
        chromium.get("dom") or [],
        chromium.get("page_state") or {},
        webkit.get("dom") or [],
        webkit.get("page_state") or {},
    )
    return {
        "comparable": gate["comparable"],
        "reasons": gate["reasons"],
        "chromium": gate["left"],
        "webkit": gate["right"],
    }


def _align_text_nodes(
    chromium: list[dict[str, Any]],
    webkit: list[dict[str, Any]],
) -> dict[str, Any]:
    left = _text_nodes(chromium)
    right = _text_nodes(webkit)
    left_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    right_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in left:
        left_groups.setdefault(item["key"], []).append(item)
    for item in right:
        right_groups.setdefault(item["key"], []).append(item)
    matched: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for key in sorted(set(left_groups) & set(right_groups)):
        left_items = left_groups[key]
        right_items = right_groups[key]
        if len(left_items) == len(right_items) == 1:
            matched.append((left_items[0], right_items[0]))
            continue
        used_right: set[int] = set()
        for left_item in left_items:
            candidates = [
                (index, _center_distance(left_item, right_item))
                for index, right_item in enumerate(right_items)
                if index not in used_right
            ]
            if not candidates:
                continue
            index, distance = min(candidates, key=lambda item: item[1])
            if distance <= 64:
                matched.append((left_item, right_items[index]))
                used_right.add(index)
    deltas: list[float] = []
    for left_item, right_item in matched:
        deltas.extend(
            abs(float(left_item["node"].get(axis) or 0) - float(right_item["node"].get(axis) or 0))
            for axis in ("x", "y", "w", "h")
        )
    return {
        "method": "text-tag-nearest",
        "confidence": "heuristic",
        "matched_count": len(matched),
        "chromium_text_nodes": len(left),
        "webkit_text_nodes": len(right),
        "coverage": round(len(matched) / len(left), 6) if left else 0,
        "unmatched_chromium": len(left) - len(matched),
        "unmatched_webkit": len(right) - len(matched),
        "geometry_max": max(deltas) if deltas else None,
        "geometry_p95": (
            sorted(deltas)[min(len(deltas) - 1, int(len(deltas) * 0.95))]
            if deltas else None
        ),
        "geometry_over_2px": sum(item > 2 for item in deltas),
    }


def _text_nodes(dom: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for node in dom:
        text = str(node.get("text") or "").strip()
        if not text:
            continue
        normalized = " ".join(
            "".join(
                char.casefold() if char.isalnum() else " "
                for char in text
            ).split()
        )
        if not normalized:
            continue
        items.append(
            {
                "key": (str(node.get("tag") or ""), normalized),
                "node": node,
            }
        )
    return items


def _center_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_node = left["node"]
    right_node = right["node"]
    lx = float(left_node.get("x") or 0) + float(left_node.get("w") or 0) / 2
    ly = float(left_node.get("y") or 0) + float(left_node.get("h") or 0) / 2
    rx = float(right_node.get("x") or 0) + float(right_node.get("w") or 0) / 2
    ry = float(right_node.get("y") or 0) + float(right_node.get("h") or 0) / 2
    return abs(lx - rx) + abs(ly - ry)


def _geometry_delta(
    chromium: list[dict[str, Any]],
    webkit: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(chromium) != len(webkit):
        return {
            "aligned": False,
            "reason": "node count differs",
            "chromium_nodes": len(chromium),
            "webkit_nodes": len(webkit),
        }
    deltas: list[float] = []
    max_per_axis = {key: 0.0 for key in ("x", "y", "w", "h")}
    for left, right in zip(chromium, webkit):
        for key in max_per_axis:
            try:
                delta = abs(float(left.get(key) or 0) - float(right.get(key) or 0))
            except (TypeError, ValueError):
                delta = float("inf")
            deltas.append(delta)
            max_per_axis[key] = max(max_per_axis[key], delta)
    finite = sorted(item for item in deltas if item != float("inf"))
    return {
        "aligned": True,
        "samples": len(deltas),
        "max": max(finite) if finite else None,
        "p95": finite[min(len(finite) - 1, int(len(finite) * 0.95))] if finite else None,
        "over_1px": sum(item > 1.0 for item in deltas),
        "over_2px": sum(item > 2.0 for item in deltas),
        "max_per_axis": max_per_axis,
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
