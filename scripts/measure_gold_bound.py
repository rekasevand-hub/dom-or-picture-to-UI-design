# -*- coding: utf-8 -*-
"""Phase 4: measure the achievable bound of the native-text gate on the golds.

The native gate (edgeF1 >= 0.95, ink coverage 0.9-1.1, 1px position) was
calibrated by intuition.  This script runs the SAME metric machinery on the
three Figma Make gold reconstructions: each gold TEXT node is measured
against the source ink at its own position, exactly the way pipeline owners
are measured.  The gold's own score distribution is the empirical achievable
bound — the honest ceiling for any generator, and the calibration reference
for the gate.

Usage:
  python scripts/measure_gold_bound.py [--out output/_benchmark_families/gold_bound.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.app.services.evidence.native_text_quality import (  # noqa: E402
    _contrast_mask,
    _ink_bbox,
    _mask_edge_f1,
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FAMILIES = [
    {
        "family": "light-form",
        "reference": "tests/fixtures/benchmark_families/light-form/reference.png",
        "gold_tree": "tests/fixtures/benchmark_families/light-form/gold_tree.json",
        "gold_export": "output/_bridge_inspect/flexweaver_gold_export.png",
        "scale": 1.0,
    },
    {
        "family": "light-table",
        "reference": "tests/fixtures/benchmark_families/light-table/reference.png",
        "gold_tree": "tests/fixtures/benchmark_families/light-table/gold_tree.json",
        "gold_export": "output/_bridge_inspect/timesheet_gold_export_2544.png",
        "scale": 1.0,
    },
    {
        "family": "dark-card-grid",
        "reference": "tests/fixtures/benchmark_families/dark-card-grid/reference.png",
        "gold_tree": "tests/fixtures/benchmark_families/dark-card-grid/gold_tree.json",
        "gold_export": "output/_bridge_inspect/acctoken_gold_export.png",
        "scale": 1.0,
    },
]


def _load_gray(path: str) -> np.ndarray:
    with Image.open(path) as handle:
        return np.asarray(handle.convert("RGB"), dtype=np.int16)


def _flatten_text_nodes(tree: dict) -> list[dict]:
    tree = dict(tree)
    tree["x"], tree["y"] = 0, 0
    nodes: list[dict[str, Any]] = []

    def walk(node: dict, ox: float = 0.0, oy: float = 0.0) -> None:
        x = ox + float(node.get("x") or 0)
        y = oy + float(node.get("y") or 0)
        if node.get("type") == "TEXT" and str(node.get("characters") or "").strip():
            nodes.append(
                {
                    "text": str(node.get("characters")),
                    "x": x,
                    "y": y,
                    "width": float(node.get("width") or 0),
                    "height": float(node.get("height") or 0),
                }
            )
        for child in node.get("children") or []:
            walk(child, x, y)

    walk(tree)
    return nodes


def _measure_owner(
    reference: np.ndarray,
    rendered: np.ndarray,
    box: tuple[float, float, float, float],
) -> dict | None:
    """Measure one owner the same way native_text_quality does."""
    x, y, w, h = (int(round(v)) for v in box)
    if w < 4 or h < 4:
        return None
    ref_region = reference[y : y + h, x : x + w]
    rend_region = rendered[y : y + h, x : x + w]
    if ref_region.size == 0 or rend_region.size == 0:
        return None
    ref_mask = _contrast_mask(ref_region)
    rend_mask = _contrast_mask(rend_region)
    ref_ink = _ink_bbox(ref_mask, [x, y, w, h])
    rend_ink = _ink_bbox(rend_mask, [x, y, w, h])
    if ref_ink is None or rend_ink is None:
        return None
    ref_px = int(ref_mask.sum())
    rend_px = int(rend_mask.sum())
    edge_f1 = _mask_edge_f1(ref_mask, rend_mask, ref_ink, rend_ink, (x, y))
    coverage = (rend_px / ref_px) if ref_px else None
    return {
        "dx": rend_ink[0] - ref_ink[0],
        "dy": rend_ink[1] - ref_ink[1],
        "width_delta": rend_ink[2] - ref_ink[2],
        "height_delta": rend_ink[3] - ref_ink[3],
        "coverage": round(coverage, 4) if coverage is not None else None,
        "edge_f1": round(edge_f1, 4) if edge_f1 is not None else None,
    }


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return round(ordered[index], 4)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output/_benchmark_families/gold_bound.json")
    args = parser.parse_args()

    report: dict = {
        "schema_version": "gold-native-bound/1.0",
        "title": "Achievable bound of the native text gate, measured on the Figma Make golds",
        "method": (
            "For each gold TEXT node, measure reference ink (source crop) and "
            "rendered ink (gold export crop) with the native_text_quality "
            "masks, then compute the same position/size/coverage/edgeF1 checks."
        ),
        "families": [],
    }
    for family in FAMILIES:
        reference = _load_gray(str(ROOT / family["reference"]))
        rendered = _load_gray(str(ROOT / family["gold_export"]))
        tree = json.loads(
            (ROOT / family["gold_tree"]).read_text(encoding="utf-8")
        )
        nodes = _flatten_text_nodes(tree)
        rows: list[dict] = []
        for node in nodes:
            box = (
                node["x"] * family["scale"],
                node["y"] * family["scale"],
                node["width"] * family["scale"],
                node["height"] * family["scale"],
            )
            measured = _measure_owner(reference, rendered, box)
            if measured is None:
                continue
            measured["text"] = node["text"][:18]
            rows.append(measured)
        f1s = [r["edge_f1"] for r in rows if r["edge_f1"] is not None]
        covs = [r["coverage"] for r in rows if r["coverage"] is not None]
        dys = [abs(r["dy"]) for r in rows]
        heights = [abs(r["height_delta"]) for r in rows]
        summary = {
            "family": family["family"],
            "owners_measured": len(rows),
            "edge_f1": {
                "median": _pct(f1s, 0.5),
                "p25": _pct(f1s, 0.25),
                "p10": _pct(f1s, 0.10),
                "pass_ge_095": sum(1 for v in f1s if v >= 0.95),
                "pass_ge_090": sum(1 for v in f1s if v >= 0.90),
                "pass_ge_080": sum(1 for v in f1s if v >= 0.80),
            },
            "ink_coverage": {
                "median": _pct(covs, 0.5),
                "in_09_11": sum(1 for v in covs if 0.9 <= v <= 1.1),
                "in_08_12": sum(1 for v in covs if 0.8 <= v <= 1.2),
            },
            "abs_dy_median": _pct(dys, 0.5),
            "abs_dy_le_1": sum(1 for v in dys if v <= 1.0),
            "abs_height_delta_median": _pct(heights, 0.5),
            "abs_height_delta_le_2": sum(1 for v in heights if v <= 2.0),
        }
        report["families"].append({"summary": summary, "owners": rows})
        print(f"=== {family['family']}: {len(rows)} owners ===")
        print(f"  edgeF1  median={summary['edge_f1']['median']}  p25={summary['edge_f1']['p25']}  >=0.95: {summary['edge_f1']['pass_ge_095']}/{len(f1s)}  >=0.80: {summary['edge_f1']['pass_ge_080']}/{len(f1s)}")
        print(f"  coverage median={summary['ink_coverage']['median']}  in[0.9,1.1]: {summary['ink_coverage']['in_09_11']}/{len(covs)}")
        print(f"  |dy| median={summary['abs_dy_median']}  <=1px: {summary['abs_dy_le_1']}/{len(rows)}  |dh| med={summary['abs_height_delta_median']} <=2: {summary['abs_height_delta_le_2']}/{len(rows)}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[out] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
