# -*- coding: utf-8 -*-
"""P1 evidence: why the native-text gate passes 1/30 critical owners.

Read-only.  Consumes an already-finished run directory; never touches the
pipeline, the policy, the fixtures or Figma.

Three questions, answered with data:

1. **How does the gate decide "native text"?**  ``nativeText`` is exact
   membership of the whole string in the readback TEXT character set, so a
   label emitted as a wrapped node (``"5.8\\n折"``) is scored as "not native".
   The probe reports, per owner, whether an exact / whitespace-only /
   compact match exists, which separates string-identity gaps from missing
   copies.
2. **Which owner passes, and why?**
3. **Is the gate too strict or is the rendering actually wrong?**  The gate
   measures the *reference* ink with an Otsu threshold (``ink_support``) but
   the *rendered* ink with a fixed threshold of 50 (``_contrast_mask``).  Two
   methods on one comparison is a bias, not a property of the render.  The
   probe therefore re-measures three ways -- stored(Otsu) vs rendered,
   Otsu vs Otsu, fixed-50 vs fixed-50 -- and reports the pass rate of each.
   The symmetric comparison is the honest one; the gap between it and the
   gate is measurement bias.

Usage:
  python scripts/p1_native_text_gate_probe.py \
      --run-dir output/_benchmark_families/rerun/dark-card-grid \
      --label dark-card-grid [--symmetric] [--crops 3]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.app.services.evidence.native_text_quality import (  # noqa: E402
    _contrast_mask,
    _halo_bbox,
    _ink_bbox,
    _mask_edge_f1,
    _normalized_bbox,
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DIMENSIONS = ("position", "size", "coverage", "edgeF1")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", _normalize(value))


def _text_nodes(tree: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            if node.get("type") == "TEXT":
                found.append(dict(node))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(tree)
    return found


def _match_node(owner: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Best readback node for an owner, with the weak match that found it."""
    text = owner.get("text") or ""
    modes = (
        ("exact", lambda value: value == text),
        ("whitespace", lambda value: _normalize(value) == _normalize(text)),
        ("compact", lambda value: _compact(value) == _compact(text)),
        ("contains", lambda value: bool(_compact(text)) and _compact(text) in _compact(value)),
    )
    for mode, predicate in modes:
        for node in nodes:
            characters = str(node.get("characters") or "")
            if predicate(characters):
                return {
                    "mode": mode,
                    "nodeId": node.get("id"),
                    "characters": characters,
                    "fontSize": node.get("fontSize"),
                    "family": (node.get("fontName") or {}).get("family"),
                    "style": (node.get("fontName") or {}).get("style"),
                    "wght": (node.get("fontName") or {}).get("variationSettings", {}).get("wght"),
                    "width": node.get("width"),
                    "height": node.get("height"),
                }
    return {"mode": "missing"}


def _classify(owner: Mapping[str, Any]) -> str:
    if "checks" not in owner:
        status = str(owner.get("status") or "unmeasured")
        if status.startswith("unmeasurable"):
            return "unmeasurable"
        return "not-native" if not owner.get("nativeText") else status
    if not owner.get("nativeText"):
        return "not-native"
    failing = [dim for dim in DIMENSIONS if not owner.get("checks", {}).get(dim)]
    return "pass" if not failing else "fail:" + "+".join(failing)


def _relax_counterfactual(owners: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    measured = [o for o in owners if "checks" in o and o.get("nativeText")]
    result: dict[str, int] = {}
    for dropped in DIMENSIONS:
        kept = [dim for dim in DIMENSIONS if dim != dropped]
        result[dropped] = sum(
            1 for owner in measured if all(owner["checks"].get(dim) for dim in kept)
        )
    result["none"] = sum(
        1 for owner in measured if all(owner["checks"].get(dim) for dim in DIMENSIONS)
    )
    result["measured"] = len(measured)
    return result


def _reported_value(owner: Mapping[str, Any], dim: str) -> Any:
    if dim == "position":
        return {"dx": owner.get("deltaX"), "dy": owner.get("deltaY")}
    if dim == "size":
        return {
            "widthDelta": owner.get("widthDelta"),
            "heightDelta": owner.get("heightDelta"),
            "widthTolerance": owner.get("widthTolerance"),
            "heightTolerance": owner.get("heightTolerance"),
        }
    if dim == "coverage":
        return owner.get("inkCoverageRatio")
    return owner.get("edgeF1")


def _checks_from(
    reference_ink: list[int],
    rendered_ink: list[int],
    coverage: float | None,
    edge_f1: float | None,
    thresholds: Mapping[str, Any],
) -> dict[str, bool]:
    position_max = float(thresholds.get("positionPxMax") or 2.0)
    width_ratio = float(thresholds.get("widthToleranceRatio") or 0.03)
    width_floor = int(thresholds.get("widthToleranceFloor") or 3)
    height_ratio = float(thresholds.get("heightToleranceRatio") or 0.03)
    height_floor = int(thresholds.get("heightToleranceFloor") or 3)
    coverage_min = float(thresholds.get("inkCoverageRatioMin") or 0.75)
    coverage_max = float(thresholds.get("inkCoverageRatioMax") or 1.35)
    edge_min = float(thresholds.get("edgeF1Min") or 0.55)
    width_tolerance = max(width_floor, int(round(reference_ink[2] * width_ratio)))
    height_tolerance = max(height_floor, int(round(reference_ink[3] * height_ratio)))
    return {
        "position": abs(rendered_ink[0] - reference_ink[0]) <= position_max
        and abs(rendered_ink[1] - reference_ink[1]) <= position_max,
        "size": abs(rendered_ink[2] - reference_ink[2]) <= width_tolerance
        and abs(rendered_ink[3] - reference_ink[3]) <= height_tolerance,
        "coverage": coverage is not None and coverage_min <= coverage <= coverage_max,
        "edgeF1": edge_f1 is not None and edge_f1 >= edge_min,
    }


def _mask_pair(
    reference: np.ndarray,
    rendered: np.ndarray,
    support_bbox: list[int],
) -> tuple[Any, Any, list[int] | None, list[int] | None, float | None, float | None]:
    x, y, width, height = support_bbox
    reference_region = reference[y : y + height, x : x + width]
    rendered_region = rendered[y : y + height, x : x + width]
    reference_mask = _contrast_mask(reference_region)
    rendered_mask = _contrast_mask(rendered_region)
    reference_ink = _ink_bbox(reference_mask, support_bbox)
    rendered_ink = _ink_bbox(rendered_mask, support_bbox)
    if reference_ink is None or rendered_ink is None:
        return reference_mask, rendered_mask, reference_ink, rendered_ink, None, None
    reference_pixels = int(reference_mask.sum())
    coverage = (
        float(int(rendered_mask.sum())) / float(reference_pixels)
        if reference_pixels
        else None
    )
    edge_f1 = _mask_edge_f1(
        reference_mask, rendered_mask, reference_ink, rendered_ink, (x, y)
    )
    return reference_mask, rendered_mask, reference_ink, rendered_ink, coverage, edge_f1


def _tightness(row: Mapping[str, Any]) -> dict[str, Any]:
    """Does the reference ink bbox belong to *this* text, or to its whole cell?

    ``styleEvidence.ink_bbox`` is the union of every ink pixel inside the
    grounding box.  When grounding hands over a cell-level box (a price cell,
    a button with a leading icon) that union spans several tokens and cannot be
    matched by a single TEXT node -- no renderer can pass.  Comparing its width
    with the emitted node's width separates those cases from real defects.
    """
    reference = row.get("referenceInkBBox")
    node = row.get("readback") or {}
    node_width = node.get("width")
    if not isinstance(reference, Sequence) or len(reference) != 4 or not node_width:
        return {"ratio": None, "band": "unknown"}
    ratio = round(float(reference[2]) / float(node_width), 3)
    if 0.8 <= ratio <= 1.25:
        band = "per-text"
    elif ratio > 1.25:
        band = "multi-token"
    else:
        band = "narrower-than-node"
    return {"ratio": ratio, "band": band}


def _tightness_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    bands = Counter((row.get("referenceTightness") or {}).get("band") for row in rows)
    summary: dict[str, Any] = {"bands": dict(bands)}
    for band in ("per-text", "multi-token", "unknown"):
        subset = [
            row for row in rows
            if (row.get("referenceTightness") or {}).get("band") == band
        ]
        if not subset:
            continue
        summary[band] = {
            "owners": len(subset),
            "measured": sum(1 for row in subset if row.get("checks")),
            "pass": sum(1 for row in subset if row.get("verdict") == "pass"),
            "failingDims": dict(
                Counter(dim for row in subset for dim in row.get("failing") or [])
            ),
            "medianCoverage": _median(
                [row["metrics"]["coverage"] for row in subset
                 if isinstance(row["metrics"].get("coverage"), (int, float))]
            ),
            "medianEdgeF1": _median(
                [row["metrics"]["edgeF1"] for row in subset
                 if isinstance(row["metrics"].get("edgeF1"), (int, float))]
            ),
        }
    return summary


def _luma_mask(region: Any) -> Any:
    """Contrast mask on luminance instead of per-channel difference.

    Browser screenshots are subpixel-antialiased: a glyph edge can differ by
    >50 in one channel while luminance barely moves.  The gate's
    ``_contrast_mask`` counts those colour fringes as ink, which inflates the
    reference ink box against Figma's grayscale raster.  This mask is the
    control for that bias.
    """
    values = region.reshape(-1, 3).astype(np.float64)
    luma = values @ np.array([0.299, 0.587, 0.114])
    background = float(np.median(luma))
    return np.abs(luma - background).reshape(region.shape[0], region.shape[1]) > 50


def _symmetric_measure(
    reference: np.ndarray,
    rendered: np.ndarray,
    source_bbox: list[int],
    thresholds: Mapping[str, Any],
    halo_px: int = 2,
    mask_fn: Any = None,
) -> dict[str, Any]:
    """Measure both sides with the SAME method and the gate's own rules."""
    mask_fn = mask_fn or _contrast_mask
    height, width = reference.shape[:2]
    x, y, box_width, box_height = source_bbox
    reference_crop = reference[y : y + box_height, x : x + box_width]
    reference_mask = mask_fn(reference_crop)
    reference_ink = _ink_bbox(reference_mask, source_bbox)
    if reference_ink is None:
        return {"status": "unmeasurable-reference-ink"}
    support_bbox = _halo_bbox(reference_ink, halo_px, (height, width))
    if support_bbox is None:
        return {"status": "unmeasurable-support"}
    sx, sy, sw, sh = support_bbox
    ref_region = reference[sy : sy + sh, sx : sx + sw]
    rend_region = rendered[sy : sy + sh, sx : sx + sw]
    ref_mask = mask_fn(ref_region)
    rend_mask = mask_fn(rend_region)
    ref_ink = _ink_bbox(ref_mask, support_bbox)
    rend_ink = _ink_bbox(rend_mask, support_bbox)
    if ref_ink is None or rend_ink is None:
        return {"status": "unmeasurable-support-ink"}
    ref_pixels = int(ref_mask.sum())
    coverage = (
        float(int(rend_mask.sum())) / float(ref_pixels) if ref_pixels else None
    )
    edge = _mask_edge_f1(ref_mask, rend_mask, ref_ink, rend_ink, (sx, sy))
    checks = _checks_from(ref_ink, rend_ink, coverage, edge, thresholds)
    return {
        "status": "measured",
        "referenceInkBBox": ref_ink,
        "renderedInkBBox": rend_ink,
        "deltaX": rend_ink[0] - ref_ink[0],
        "deltaY": rend_ink[1] - ref_ink[1],
        "widthDelta": rend_ink[2] - ref_ink[2],
        "heightDelta": rend_ink[3] - ref_ink[3],
        "inkCoverageRatio": coverage,
        "edgeF1": edge,
        "checks": checks,
        "status_pass": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--symmetric", action="store_true")
    parser.add_argument(
        "--recompute",
        action="store_true",
        help="re-run the gate on the existing render with the current code",
    )
    parser.add_argument(
        "--reference",
        default="",
        help="source screenshot; defaults to tests/fixtures/benchmark_families/<label>/reference.png",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    label = args.label or run_dir.name
    acceptance = _load(run_dir / "acceptance.json")
    quality = _load(run_dir / "native_text_quality.json")
    design = _load(run_dir / "figma_design.json")
    readback_path = run_dir / "figma_ink_converged" / "readback.json"
    if not readback_path.exists():
        readback_path = run_dir / "figma" / "readback.json"
    nodes = _text_nodes(_load(readback_path))

    gate = quality.get("gate") or {}
    policy = acceptance.get("policy") or {}
    previous_gate = gate
    previous_pass = sum(
        1
        for owner in quality.get("owners") or []
        if owner.get("status") == "pass" and owner.get("ownerScope") == "critical-gate"
    )
    recomputed = None
    if args.recompute:
        from src.app.services.evidence.image_figma_acceptance import (
            IMAGE_MVP_POLICY_V21,
        )
        from src.app.services.evidence.native_text_quality import (
            build_native_text_quality,
        )

        truth_path = ROOT / "tests/fixtures/benchmark_families" / label / "truth.json"
        critical_texts = (
            json.loads(truth_path.read_text(encoding="utf-8")).get("critical_texts")
            if truth_path.exists()
            else []
        )
        recomputed = build_native_text_quality(
            design,
            _load(readback_path),
            str(ROOT / "tests/fixtures/benchmark_families" / label / "reference.png"),
            str(_export_path(run_dir)),
            [
                {"id": str(region.get("id")), "role": str(region.get("role")), "bbox": region.get("bbox")}
                for region in quality.get("chromeRegions") or []
            ],
            gate_policy=IMAGE_MVP_POLICY_V21,
            critical_texts=critical_texts or [],
            register_unmeasured_owners=True,
        )
        gate = recomputed.get("gate") or {}
        quality = recomputed
    thresholds = {
        **(gate.get("thresholds") or {}),
        "widthToleranceRatio": policy.get("native_text_width_tolerance_ratio", 0.03),
        "widthToleranceFloor": policy.get("native_text_width_tolerance_floor_px", 3),
        "heightToleranceRatio": policy.get("native_text_height_tolerance_ratio", 0.03),
        "heightToleranceFloor": policy.get("native_text_height_tolerance_floor_px", 3),
    }
    scope_refs = list((gate.get("nativeText") or {}).get("ownerRefs") or [])
    scope_ref_set = set(scope_refs)
    owners = list(quality.get("owners") or [])
    by_ref = {
        str(owner.get("contentRef") or f"owner-{index}"): owner
        for index, owner in enumerate(owners)
    }
    elements = {
        str(element.get("contentRef")): element
        for element in design.get("elements") or []
        if isinstance(element, Mapping)
    }
    scoped = [by_ref[ref] for ref in scope_refs if ref in by_ref]
    unscoped = [owner for owner in owners if str(owner.get("contentRef")) not in scope_ref_set]

    reference_image = None
    rendered_image = None
    if args.symmetric:
        from PIL import Image

        reference_path = Path(args.reference) if args.reference else (
            ROOT / "tests" / "fixtures" / "benchmark_families" / label / "reference.png"
        )
        with Image.open(reference_path) as handle:
            reference_image = np.asarray(handle.convert("RGB"), dtype=np.int16)
        with Image.open(_export_path(run_dir)) as handle:
            rendered_image = np.asarray(handle.convert("RGB"), dtype=np.int16)
        if reference_image.shape != rendered_image.shape:
            raise SystemExit(
                f"reference {reference_image.shape} != export {rendered_image.shape}"
            )

    rows: list[dict[str, Any]] = []
    for owner in scoped:
        raw_ref = str(owner.get("contentRef"))
        checks = owner.get("checks") or {}
        element = elements.get(raw_ref) or {}
        evidence = (element.get("styleEvidence") or {})
        values = evidence.get("evidence") if isinstance(evidence, Mapping) else None
        row: dict[str, Any] = {
            "contentRef": owner.get("contentRef"),
            "text": owner.get("text"),
            "type": owner.get("type"),
            "nativeText": bool(owner.get("nativeText")),
            "status": owner.get("status"),
            "verdict": _classify(owner),
            "referenceInkBBox": owner.get("referenceInkBBox"),
            "renderedInkBBox": owner.get("renderedInkBBox"),
            "checks": checks,
            "failing": [dim for dim in DIMENSIONS if "checks" in owner and not checks.get(dim)],
            "metrics": {dim: _reported_value(owner, dim) for dim in DIMENSIONS},
            "readback": _match_node(owner, nodes),
            "styleEvidence": {
                "present": bool(values),
                "keys": sorted(values) if isinstance(values, Mapping) else [],
                "hasInkBBox": bool(isinstance(values, Mapping) and values.get("ink_bbox")),
            },
        }
        if args.symmetric and reference_image is not None and isinstance(values, Mapping):
            source_bbox = _normalized_bbox(values.get("source_bbox"))
            if source_bbox is not None:
                row["symmetric"] = _symmetric_measure(
                    reference_image,
                    rendered_image,
                    source_bbox,
                    thresholds,
                )
                row["luma"] = _symmetric_measure(
                    reference_image,
                    rendered_image,
                    source_bbox,
                    thresholds,
                    mask_fn=_luma_mask,
                )
        row["referenceTightness"] = _tightness(row)
        rows.append(row)

    classification = Counter(row["verdict"] for row in rows)
    failing_dims = Counter(dim for row in rows for dim in row["failing"])
    dim_pass = {
        dim: sum(1 for row in rows if row["checks"].get(dim))
        for dim in DIMENSIONS
    }
    control = [
        owner for owner in unscoped
        if "checks" in owner and owner.get("nativeText")
    ]
    control_pass = sum(
        1 for owner in control if all(owner["checks"].get(dim) for dim in DIMENSIONS)
    )

    symmetric_summary = None
    luma_summary = None
    if args.symmetric:
        symmetric_summary = _variant_summary(rows, "symmetric")
        luma_summary = _variant_summary(rows, "luma")

    report = {
        "schema_version": "p1-native-text-gate-probe/2.0",
        "label": label,
        "run_dir": str(run_dir),
        "readback": str(readback_path.relative_to(run_dir)),
        "export": str(_export_path(run_dir).relative_to(run_dir)),
        "run_status": acceptance.get("status"),
        "policy_id": policy.get("policy_id"),
        "gate": {
            "status": gate.get("status"),
            "scope": gate.get("scope"),
            "thresholds": thresholds,
            "criticalText": gate.get("criticalText"),
            "counts": {
                "scopeOwners": len(scoped),
                "scopeNative": sum(1 for row in rows if row["nativeText"]),
                "scopePass": classification.get("pass", 0),
                "scopeMeasured": sum(1 for row in rows if row["checks"]),
                "unscopedOwners": len(unscoped),
            },
        },
        "classification": dict(classification),
        "failingDimensions": dict(failing_dims),
        "dimensionPass": dim_pass,
        "relaxCounterfactual": _relax_counterfactual(scoped),
        "readbackMatch": dict(Counter(row["readback"]["mode"] for row in rows)),
        "referenceTightness": _tightness_summary(rows),
        "controlGroup": {
            "measuredOwners": len(control),
            "passingOwners": control_pass,
            "passRate": round(control_pass / len(control), 3) if control else None,
        },
        "symmetric": symmetric_summary,
        "luma": luma_summary,
        "owners": rows,
    }

    if args.recompute:
        report["recompute"] = {
            "previousGateStatus": previous_gate.get("status"),
            "previousOwnerPass": previous_pass,
            "currentGateStatus": gate.get("status"),
            "currentOwnerPass": classification.get("pass", 0),
            "unverifiedCount": (gate.get("nativeText") or {}).get("unverifiedCount"),
        }

    print(f"=== {label} · {run_dir} ===")
    print(f"run={report['run_status']}  policy={report['policy_id']}  gate={gate.get('status')}")
    print(f"readback(gate)={report['readback']}  TEXT={len(nodes)}")
    print(
        f"scope={len(scoped)}  native={report['gate']['counts']['scopeNative']}  "
        f"measured={report['gate']['counts']['scopeMeasured']}  pass={classification.get('pass', 0)}"
    )
    if args.recompute:
        print(
            f"instrument swap: old pass={previous_pass} ({previous_gate.get('status')}) "
            f"-> new pass={classification.get('pass', 0)} ({gate.get('status')}), "
            f"unverified={(gate.get('nativeText') or {}).get('unverifiedCount')}"
        )
    print("thresholds:", json.dumps(thresholds, ensure_ascii=False))
    print("verdicts:", dict(classification))
    print("failing dims:", dict(failing_dims), " dim pass:", dim_pass)
    print("relax-one-dim:", _relax_counterfactual(scoped))
    print(
        f"control (non-critical measured={len(control)}): pass={control_pass} "
        f"({report['controlGroup']['passRate']})"
    )
    print("readback match:", dict(Counter(row["readback"]["mode"] for row in rows)))
    if symmetric_summary:
        print("symmetric(fixed-50 both sides):", json.dumps(symmetric_summary, ensure_ascii=False))
    if luma_summary:
        print("luma(fixed-50 both sides, no subpixel fringe):", json.dumps(luma_summary, ensure_ascii=False))
    print("reference tightness:", json.dumps(_tightness_summary(rows), ensure_ascii=False))
    print()
    header = "| # | text | native | verdict | tight | dx,dy | dW,dH (tol) | cov | edgeF1 | font |"
    print(header)
    print("|---|---|---|---|---|---|---|---|---|---|")
    ordered = sorted(rows, key=lambda r: (r["verdict"] != "pass", r["text"]))
    for index, row in enumerate(ordered, 1):
        metrics = row["metrics"]
        position = metrics["position"] or {}
        size = metrics["size"] or {}
        node = row["readback"]
        tight = (row.get("referenceTightness") or {}).get("ratio")
        font = (
            f"{node.get('family')}/{node.get('style')}@{node.get('fontSize')}"
            if node.get("mode") != "missing"
            else "—"
        )
        text = str(row["text"] or "")[:14]
        sym = row.get("symmetric") or {}
        sym_note = ""
        if sym.get("status") == "measured":
            sym_note = (
                f" | sym dx={sym['deltaX']} dw={sym['widthDelta']} "
                f"cov={round(sym['inkCoverageRatio'] or 0, 2)} "
                f"f1={round(sym['edgeF1'] or 0, 2)} "
                f"{'PASS' if sym['status_pass'] else ''}"
            )
        print(
            f"| {index} | {text} | {int(row['nativeText'])} | {row['verdict']} | "
            f"{tight} | {position.get('dx')},{position.get('dy')} | "
            f"{size.get('widthDelta')},{size.get('heightDelta')} "
            f"(±{size.get('widthTolerance')}/{size.get('heightTolerance')}) | "
            f"{metrics['coverage'] if metrics['coverage'] is None else round(metrics['coverage'], 3)} | "
            f"{metrics['edgeF1'] if metrics['edgeF1'] is None else round(metrics['edgeF1'], 3)} | {font}{sym_note} |"
        )

    out = Path(args.out) if args.out else ROOT / "output" / "_p1_native_gate" / f"{label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[out] {out}")
    return 0


def _export_path(run_dir: Path) -> Path:
    """The export the gate measured: the last stage's canvas, not the first."""
    converged = run_dir / "figma_ink_converged" / "export.png"
    return converged if converged.exists() else run_dir / "figma" / "export.png"


def _variant_summary(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    measured = [
        row[key] for row in rows
        if isinstance(row.get(key), Mapping) and row[key].get("status") == "measured"
    ]
    return {
        "measured": len(measured),
        "pass": sum(1 for item in measured if item["status_pass"]),
        "dimPass": {
            dim: sum(1 for item in measured if item["checks"].get(dim))
            for dim in DIMENSIONS
        },
        "medianAbsDx": _median([abs(item["deltaX"]) for item in measured]),
        "medianAbsDy": _median([abs(item["deltaY"]) for item in measured]),
        "medianAbsWidthDelta": _median([abs(item["widthDelta"]) for item in measured]),
        "medianCoverage": _median([item["inkCoverageRatio"] for item in measured]),
        "medianEdgeF1": _median([item["edgeF1"] for item in measured]),
    }


def _median(values: Sequence[float]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return round(float(np.median(clean)), 3)


if __name__ == "__main__":
    raise SystemExit(main())
