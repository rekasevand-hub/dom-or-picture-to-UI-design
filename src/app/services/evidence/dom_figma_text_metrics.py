"""Independent Figma linebreak and projected-baseline evaluation."""

from __future__ import annotations

from typing import Any, Mapping

from src.app.services.rendering.figma_acceptance import (
    _design_elements,
    _element_type,
    _global_box,
    _iter_nodes,
    _match_element_candidate,
    _root_origin,
)


REPORT_SCHEMA = "dom-figma-text-metrics/1.0"


def build_figma_text_metrics(
    design: Mapping[str, Any],
    readback: Mapping[str, Any],
    *,
    baseline_tolerance_px: float = 1.0,
    linebreak_match_rate: float = 0.98,
    glyph_identity_policy: str = "explicit-not-evaluated",
) -> dict[str, Any]:
    """Measure text dimensions without promoting raster similarity to glyph truth."""
    nodes = list(_iter_nodes(dict(readback)))
    root_origin = _root_origin(dict(readback))
    candidates = nodes[1:]
    used: set[int] = set()
    matches: list[dict[str, Any]] = []
    expected_text_count = 0
    matched_count = 0

    for element in _design_elements(dict(design)):
        if _element_type(element) != "text" or not _canonical(element.get("text")):
            continue
        expected_text_count += 1
        candidate_index, candidate = _match_element_candidate(
            element,
            candidates,
            used,
            root_origin,
        )
        if candidate is None or candidate_index is None:
            matches.append(
                {
                    "element_id": element.get("id"),
                    "node_id": None,
                    "text": _canonical(element.get("text")),
                    "linebreak": {
                        "status": "not-evaluated",
                        "reason": "figma-text-match-missing",
                    },
                    "baseline": {
                        "status": "not-evaluated",
                        "reason": "figma-text-match-missing",
                    },
                    "glyph": {
                        "status": "not-evaluated",
                        "final_identity": "not-evaluated",
                    },
                }
            )
            continue
        used.add(candidate_index)
        matched_count += 1
        matches.append(
            _evaluate_text_match(
                element,
                candidate,
                root_origin=root_origin,
                baseline_tolerance_px=float(baseline_tolerance_px),
            )
        )

    linebreak = _summarize_linebreak(
        matches,
        total=expected_text_count,
        minimum_match_rate=float(linebreak_match_rate),
    )
    baseline = _summarize_baseline(
        matches,
        total=expected_text_count,
        tolerance_px=float(baseline_tolerance_px),
    )
    glyph = _summarize_glyph(
        matches,
        policy_status=glyph_identity_policy,
    )
    return {
        "schema_version": REPORT_SCHEMA,
        "expected_text_count": expected_text_count,
        "matched_count": matched_count,
        "unmatched_count": expected_text_count - matched_count,
        "dimensions": {
            "linebreak": linebreak,
            "baseline": baseline,
            "glyph": glyph,
        },
        "matches": matches,
        "composite_score_used": False,
    }


def _evaluate_text_match(
    element: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    root_origin: tuple[float, float],
    baseline_tolerance_px: float,
) -> dict[str, Any]:
    source_text = _canonical(element.get("text"))
    actual_text = str(candidate.get("characters") or "")
    actual_lines = actual_text.split("\n")
    expected_count, expected_lines = _expected_lines(element)
    if expected_count is None:
        linebreak = {
            "status": "not-evaluated",
            "reason": "line-count-evidence-missing",
            "expected_line_count": None,
            "actual_line_count": len(actual_lines),
        }
    else:
        content_match = True
        if expected_lines:
            content_match = [_canonical(line) for line in expected_lines] == [
                _canonical(line) for line in actual_lines
            ]
        passed = expected_count == len(actual_lines) and content_match
        linebreak = {
            "status": "pass" if passed else "fail",
            "method": ("measured-lines" if expected_lines else "browser-line-count"),
            "expected_line_count": expected_count,
            "actual_line_count": len(actual_lines),
            "line_content_match": content_match,
            "expected_lines": list(expected_lines or []),
            "actual_lines": actual_lines,
        }

    baseline = _evaluate_baseline(
        element,
        candidate,
        root_origin=root_origin,
        tolerance_px=baseline_tolerance_px,
    )
    font_name = candidate.get("fontName")
    return {
        "element_id": element.get("id"),
        "node_id": candidate.get("id"),
        "text": source_text,
        "linebreak": linebreak,
        "baseline": baseline,
        "glyph": {
            "status": "not-evaluated",
            "final_identity": "not-evaluated",
            "resolved_font": font_name if isinstance(font_name, Mapping) else None,
        },
    }


def _expected_lines(
    element: Mapping[str, Any],
) -> tuple[int | None, list[str] | None]:
    lines = element.get("lines")
    if isinstance(lines, list) and lines:
        return len(lines), [str(line) for line in lines]
    try:
        count = int(element.get("textEmLines") or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0:
        return count, None
    source = str(element.get("text") or "")
    if "\n" in source:
        return source.count("\n") + 1, source.split("\n")
    return None, None


def _evaluate_baseline(
    element: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    root_origin: tuple[float, float],
    tolerance_px: float,
) -> dict[str, Any]:
    baseline = element.get("textBaseline")
    if not isinstance(baseline, Mapping):
        return {
            "status": "not-evaluated",
            "reason": "textBaseline-missing",
        }
    if str(baseline.get("method") or "") != "canvas-font-metrics":
        return {
            "status": "not-evaluated",
            "reason": "baseline-method-not-browser-derived",
            "method": baseline.get("method"),
        }
    try:
        source_y = float(baseline["y"])
        ascent = float(baseline["ascent"])
    except (KeyError, TypeError, ValueError):
        return {
            "status": "not-evaluated",
            "reason": "textBaseline-invalid",
        }
    actual_y = float(_global_box(dict(candidate), root_origin)["y"])
    projected_y = actual_y + ascent
    delta = projected_y - source_y
    return {
        "status": "pass" if abs(delta) <= tolerance_px else "fail",
        "method": "figma-node-origin-plus-browser-ascent",
        "source_baseline_y": source_y,
        "projected_baseline_y": projected_y,
        "delta_px": delta,
        "tolerance_px": tolerance_px,
        "ascent": ascent,
        "descent": baseline.get("descent"),
        "line_count": baseline.get("lineCount"),
    }


def _summarize_linebreak(
    matches: list[Mapping[str, Any]],
    *,
    total: int,
    minimum_match_rate: float,
) -> dict[str, Any]:
    rows = [row["linebreak"] for row in matches]
    evaluated = [
        row for row in rows if str(row.get("status") or "") in {"pass", "fail"}
    ]
    passed = sum(row.get("status") == "pass" for row in evaluated)
    coverage = len(evaluated) / total if total else 0.0
    match_rate = passed / len(evaluated) if evaluated else 0.0
    if not evaluated:
        status = "not-evaluated"
    elif match_rate < minimum_match_rate:
        status = "fail"
    elif coverage < 1.0:
        status = "partial"
    else:
        status = "pass"
    return {
        "status": status,
        "evaluated_count": len(evaluated),
        "pass_count": passed,
        "fail_count": len(evaluated) - passed,
        "not_evaluated_count": total - len(evaluated),
        "coverage": coverage,
        "match_rate": match_rate,
        "minimum_match_rate": minimum_match_rate,
    }


def _summarize_baseline(
    matches: list[Mapping[str, Any]],
    *,
    total: int,
    tolerance_px: float,
) -> dict[str, Any]:
    rows = [row["baseline"] for row in matches]
    evaluated = [
        row for row in rows if str(row.get("status") or "") in {"pass", "fail"}
    ]
    passed = sum(row.get("status") == "pass" for row in evaluated)
    failed = len(evaluated) - passed
    coverage = len(evaluated) / total if total else 0.0
    if failed:
        status = "fail"
    elif not evaluated:
        status = "not-evaluated"
    elif coverage < 1.0:
        status = "partial"
    else:
        status = "pass"
    return {
        "status": status,
        "evaluated_count": len(evaluated),
        "pass_count": passed,
        "fail_count": failed,
        "not_evaluated_count": total - len(evaluated),
        "coverage": coverage,
        "tolerance_px": tolerance_px,
        "method": "figma-node-origin-plus-browser-ascent",
        "claim": "projected-browser-baseline",
    }


def _summarize_glyph(
    matches: list[Mapping[str, Any]],
    *,
    policy_status: str,
) -> dict[str, Any]:
    with_font = sum(
        isinstance(row.get("glyph", {}).get("resolved_font"), Mapping)
        for row in matches
    )
    return {
        "status": "not-evaluated",
        "evaluated_count": 0,
        "resolved_font_count": with_font,
        "final_identity": "not-evaluated",
        "policy_status": policy_status,
        "claim": "figma-font-name-only",
    }


def _canonical(value: Any) -> str:
    return "".join(str(value or "").split())
