"""Independent content, linebreak, box, baseline and glyph evaluation."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


REPORT_SCHEMA = "dom-text-quality/1.0"
FINAL_GLYPH_IDENTITY = "not-evaluated"


def canonical_text(value: Any) -> str:
    """Remove layout whitespace without changing visible characters."""
    return "".join(str(value or "").split())


def evaluate_text_nodes(
    dom: Sequence[Mapping[str, Any]],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    text_thresholds = thresholds.get("text") or {}
    box_tolerance = float(text_thresholds.get("box_tolerance_px") or 2.0)
    baseline_tolerance = float(text_thresholds.get("baseline_tolerance_px") or 1.0)
    style_evidence = _collect_font_style_evidence(dom)
    nodes = [
        _evaluate_node(
            index,
            node,
            box_tolerance=box_tolerance,
            baseline_tolerance=baseline_tolerance,
            style_evidence=style_evidence,
        )
        for index, node in enumerate(dom)
        if isinstance(node, Mapping) and canonical_text(node.get("text"))
    ]
    dimensions = {
        "content": _summarize_hard_dimension(nodes, "content", total=len(nodes)),
        "linebreak": _summarize_hard_dimension(
            nodes,
            "linebreak",
            total=len(nodes),
            threshold=float(text_thresholds.get("linebreak_match_rate") or 0.98),
        ),
        "box": _summarize_hard_dimension(nodes, "box", total=len(nodes)),
        "baseline": _summarize_baseline(nodes),
        "glyph": _summarize_glyph(nodes),
    }
    hard_fail = any(
        dimensions[name]["status"] == "fail" for name in ("content", "linebreak", "box")
    )
    return {
        "schema_version": REPORT_SCHEMA,
        "status": "fail" if hard_fail else "partial",
        "composite_score_used": False,
        "text_node_count": len(nodes),
        "dimensions": dimensions,
        "nodes": nodes,
    }


def _evaluate_node(
    index: int,
    node: Mapping[str, Any],
    *,
    box_tolerance: float,
    baseline_tolerance: float,
    style_evidence: Mapping[tuple[str, ...], tuple[str, ...]],
) -> dict[str, Any]:
    source_text = canonical_text(node.get("text"))
    lines = [
        str(line.get("text") or "")
        for line in node.get("textLines") or []
        if isinstance(line, Mapping) and canonical_text(line.get("text"))
    ]
    measured_text = canonical_text("".join(lines)) if lines else source_text
    content_pass = measured_text == source_text
    source_truncated = False
    if not content_pass and measured_text.startswith(source_text):
        content_pass = True
        source_truncated = True
    content = {
        "status": "pass" if content_pass else "fail",
        "expected": source_text,
        "actual": measured_text,
        "source_truncated": source_truncated,
        "method": "measured-lines" if lines else "source-text",
    }

    line_count = int(node.get("textEmLines") or 0)
    if lines and line_count > 0:
        linebreak_pass = len(lines) == line_count and all(lines)
        linebreak = {
            "status": "pass" if linebreak_pass else "fail",
            "method": "measured-lines",
            "line_count": len(lines),
            "expected_line_count": line_count,
            "lines": lines,
        }
    elif line_count == 1 and "\n" not in str(node.get("text") or ""):
        linebreak = {
            "status": "pass",
            "method": "measured-single-line",
            "line_count": 1,
            "expected_line_count": 1,
            "lines": [],
        }
    else:
        linebreak = {
            "status": "not-evaluated",
            "method": "missing-line-evidence",
            "line_count": len(lines),
            "expected_line_count": line_count,
            "lines": lines,
        }

    box = _evaluate_box(node, tolerance=box_tolerance)
    baseline = _evaluate_baseline(
        node,
        tolerance=baseline_tolerance,
    )
    glyph = _evaluate_glyph(node, style_evidence)
    return {
        "index": index,
        "text": source_text,
        "content": content,
        "linebreak": linebreak,
        "box": box,
        "baseline": baseline,
        "glyph": glyph,
        "paint_boxes": [
            list(line.get("box") or [])
            for line in node.get("textLines") or []
            if isinstance(line, Mapping)
        ],
    }


def _evaluate_box(node: Mapping[str, Any], *, tolerance: float) -> dict[str, Any]:
    em_box = node.get("textEmBox")
    if not isinstance(em_box, (list, tuple)) or len(em_box) != 4:
        return {"status": "not-evaluated", "reason": "textEmBox-missing"}
    try:
        x, y, width, height = (float(value) for value in em_box)
        node_x = float(node.get("x") or 0)
        node_y = float(node.get("y") or 0)
        node_w = float(node.get("w") or 0)
        node_h = float(node.get("h") or 0)
    except (TypeError, ValueError):
        return {"status": "not-evaluated", "reason": "textEmBox-invalid"}
    left_delta = x - node_x
    top_delta = y - node_y
    right_delta = (node_x + node_w) - (x + width)
    bottom_delta = (node_y + node_h) - (y + height)
    horizontal_pass = left_delta >= -tolerance and right_delta >= -tolerance
    vertical_overlap = min(y + height, node_y + node_h) - max(y, node_y)
    passed = width > 0 and height > 0 and horizontal_pass and vertical_overlap > 0
    return {
        "status": "pass" if passed else "fail",
        "textEmBox": [x, y, width, height],
        "nodeBox": [node_x, node_y, node_w, node_h],
        "max_horizontal_delta": max(abs(left_delta), abs(right_delta)),
        "vertical_paint_overflow_top": max(0.0, -top_delta),
        "vertical_paint_overflow_bottom": max(0.0, -bottom_delta),
        "vertical_overlap_px": max(0.0, vertical_overlap),
        "tolerance": tolerance,
    }


def _evaluate_baseline(
    node: Mapping[str, Any],
    *,
    tolerance: float,
) -> dict[str, Any]:
    baseline = node.get("textBaseline")
    if not isinstance(baseline, Mapping):
        return {"status": "not-evaluated", "reason": "textBaseline-missing"}
    method = str(baseline.get("method") or "")
    if method != "canvas-font-metrics":
        return {
            "status": "not-evaluated",
            "reason": "baseline-method-not-browser-derived",
            "method": method,
        }
    try:
        y = float(baseline.get("y"))
        node_y = float(node.get("y") or 0)
        node_h = float(node.get("h") or 0)
    except (TypeError, ValueError):
        return {"status": "not-evaluated", "reason": "textBaseline-invalid"}
    inside = node_y - tolerance <= y <= node_y + node_h + tolerance
    return {
        "status": "derived" if inside else "partial",
        "y": y,
        "ascent": baseline.get("ascent"),
        "descent": baseline.get("descent"),
        "method": method,
        "lineCount": baseline.get("lineCount"),
        "inside_box": inside,
    }


def _evaluate_glyph(
    node: Mapping[str, Any],
    style_evidence: Mapping[tuple[str, ...], tuple[str, ...]],
) -> dict[str, Any]:
    fonts = [
        dict(item)
        for item in node.get("platformFonts") or []
        if isinstance(item, Mapping) and item.get("familyName")
    ]
    evidence_source = "direct"
    if not fonts:
        inherited = style_evidence.get(_font_style_key(node), ())
        if inherited:
            fonts = [
                {"familyName": family, "evidenceSource": "style-representative"}
                for family in inherited
            ]
            evidence_source = "style-representative"
        else:
            evidence_source = "missing"
    faces = {str(item.get("familyName")) for item in fonts}
    if not faces:
        face_status = "not-evaluated"
    elif len(faces) > 1:
        face_status = "ambiguous"
    elif evidence_source == "style-representative":
        face_status = "representative-face-observed"
    else:
        face_status = "face-observed"
    return {
        "face_status": face_status,
        "platform_fonts": fonts,
        "evidence_source": evidence_source,
        "font_family_resolution": node.get("fontFamilyResolution"),
        "final_identity": FINAL_GLYPH_IDENTITY,
    }


def _summarize_hard_dimension(
    nodes: Sequence[Mapping[str, Any]],
    name: str,
    *,
    total: int,
    threshold: float = 1.0,
) -> dict[str, Any]:
    evaluated = [
        node[name] for node in nodes if node[name].get("status") in {"pass", "fail"}
    ]
    passed = sum(item["status"] == "pass" for item in evaluated)
    coverage = len(evaluated) / total if total else 0.0
    rate = passed / len(evaluated) if evaluated else 0.0
    if not evaluated:
        status = "not-evaluated"
    elif rate < threshold:
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
        "coverage": coverage,
        "match_rate": rate,
        "minimum_match_rate": threshold,
    }


def _summarize_baseline(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    derived = [
        node["baseline"] for node in nodes if node["baseline"].get("y") is not None
    ]
    invalid = [item for item in derived if item.get("status") != "derived"]
    return {
        "status": (
            "not-evaluated" if not derived else "partial" if invalid else "derived"
        ),
        "derived_count": len(derived),
        "invalid_count": len(invalid),
        "coverage": len(derived) / len(nodes) if nodes else 0.0,
        "method": "canvas-font-metrics",
        "claim": "derived-browser-baseline",
    }


def _summarize_glyph(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    face_observed = sum(
        node["glyph"]["face_status"] == "face-observed" for node in nodes
    )
    representative = sum(
        node["glyph"]["face_status"] == "representative-face-observed" for node in nodes
    )
    ambiguous = sum(node["glyph"]["face_status"] == "ambiguous" for node in nodes)
    missing = sum(node["glyph"]["face_status"] == "not-evaluated" for node in nodes)
    return {
        "status": "partial" if nodes else "not-evaluated",
        "direct_face_count": face_observed,
        "representative_face_count": representative,
        "ambiguous_count": ambiguous,
        "missing_evidence_count": missing,
        "coverage": (
            (face_observed + representative + ambiguous) / len(nodes) if nodes else 0.0
        ),
        "final_identity": FINAL_GLYPH_IDENTITY,
        "claim": "browser-face-and-glyph-count-only",
    }


def _collect_font_style_evidence(
    dom: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, ...], tuple[str, ...]]:
    evidence: dict[tuple[str, ...], set[str]] = {}
    for node in dom:
        if not isinstance(node, Mapping):
            continue
        key = _font_style_key(node)
        for font in node.get("platformFonts") or []:
            if not isinstance(font, Mapping):
                continue
            family = str(font.get("familyName") or "").strip()
            if family:
                evidence.setdefault(key, set()).add(family)
    return {key: tuple(sorted(families)) for key, families in evidence.items()}


def _font_style_key(node: Mapping[str, Any]) -> tuple[str, ...]:
    requested = str(
        node.get("fontFamilyRequested") or node.get("fontFamily") or ""
    ).strip()
    return (
        requested,
        str(node.get("fontWeight") or "normal").strip(),
        str(node.get("fontSize") or "16px").strip(),
        str(node.get("fontStyle") or "normal").strip(),
    )
