# -*- coding: utf-8 -*-
"""Compare the current size proxy (font_ratio) with an ink-height metric.

Why: ``font_ratio`` divides two *declared* font sizes.  When the pipeline and
the gold frame render with different families, that quotient mixes a real size
difference with a font-metric difference -- measured on dark-card-grid, a text
whose size already matches still shows 0.91 of the source ink height.  This
probe reports both numbers per text so the two can be compared like for like.

Read-only: it never writes to Figma, and it measures only frozen artifacts.

Note on authority: since 2026-11-10 the *gate*
(``scripts/check_benchmark_families.py``) owns ``ink_ratio_median`` and gates on
it.  This probe stays as the diagnostic view (per-text rows, ``font_metric``).
Its pair set additionally requires both sides to declare a fontSize, so counts
and the within-10 % share can differ from the gate by a pair or two; the medians
agree.

Metrics per matched text pair (gold text <-> pipeline text with the same string
and nearest position):

  size_ratio   pipeline fontSize / gold fontSize     (the current proxy)
  ink_ratio    rendered ink height / source ink height, both measured in the
               *gold box* -- same window on both images, so box geometry
               cancels and only the glyph height remains
  ink_width_ratio / ink_count_ratio   same window, for context
  font_metric  ink_ratio / size_ratio -- the family's ink-per-point ratio
               relative to the gold.  If this is flat across the page, the
               difference is a metric difference and ``size_ratio`` is
               measuring the wrong thing.

Usage:
    python scripts/size_metric_probe.py
    python scripts/size_metric_probe.py --run-root D:/LLM-Data/Figma_auto_agent/output
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from scripts.p1_font_weight_evidence import (  # noqa: E402
    flatten_gold_texts,
    normalize_text,
)
from src.app.services.structure.fidelity.text_calibration import _ink_stats  # noqa: E402

BENCH = ROOT / "tests" / "fixtures" / "benchmark_families"
SCHEMA_VERSION = "size-metric-probe/1.0"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def flatten_readback(tree: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten TEXT nodes with absolute positions (frame-relative)."""
    records: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], ox: float = 0.0, oy: float = 0.0) -> None:
        x = ox + float(node.get("x") or 0)
        y = oy + float(node.get("y") or 0)
        if node.get("type") == "TEXT":
            records.append(
                {
                    "key": normalize_text(node.get("characters")),
                    "text": str(node.get("characters") or ""),
                    "x": x,
                    "y": y,
                    "width": float(node.get("width") or 0),
                    "height": float(node.get("height") or 0),
                    "font_size": float(node.get("fontSize") or 0) or None,
                }
            )
        for child in node.get("children") or []:
            walk(child, x, y)

    walk(tree)
    return records


def match_pairs(
    gold: Sequence[dict[str, Any]], pipe: Sequence[dict[str, Any]]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Pair gold and pipeline texts by string, nearest position, one-to-one."""
    pools: dict[str, list[int]] = {}
    for index, record in enumerate(pipe):
        pools.setdefault(record["key"], []).append(index)
    used: set[int] = set()
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for record in gold:
        best: tuple[float, int] | None = None
        for index in pools.get(record["key"], []):
            if index in used:
                continue
            other = pipe[index]
            distance = abs(other["x"] - record["bbox"][0]) + abs(
                other["y"] - record["bbox"][1]
            )
            if best is None or distance < best[0]:
                best = (distance, index)
        if best is None:
            continue
        used.add(best[1])
        pairs.append((record, pipe[best[1]]))
    return pairs


def subpixel_ink_height(image: np.ndarray, box: Sequence[float]) -> float | None:
    """Ink height at the half-coverage level, interpolated between rows.

    Hypothesis: the integer ink height of a 24-32 px glyph quantises to 1 px
    (3-4 %), the same order as the size difference being measured, so a
    coverage-weighted height should be sharper.

    Measured: it is not.  Within-10 % agreement dropped (dark 0.57 -> 0.35,
    light-form 0.87 -> 0.69) because per-row coverage over a sparse text line
    fluctuates as much as the quantisation it was meant to remove.  Kept only
    as a diagnostic column; the integer ``ink_ratio`` is the usable one.
    """
    height, width = image.shape[:2]
    x, y, box_w, box_h = (int(round(float(value))) for value in list(box)[:4])
    x, y = max(0, x), max(0, y)
    right, bottom = min(width, x + box_w), min(height, y + box_h)
    if right - x < 3 or bottom - y < 3:
        return None
    crop = image[y:bottom, x:right].astype(np.int16)
    border = np.concatenate(
        [crop[0, :, :], crop[-1, :, :], crop[:, 0, :], crop[:, -1, :]], axis=0
    )
    background = np.median(border, axis=0)
    distance = np.abs(crop - background.reshape(1, 1, 3)).max(axis=2).astype(np.float64)
    strong = distance[distance > 8.0]
    if strong.size == 0:
        return None
    contrast = float(np.percentile(strong, 95))
    if contrast <= 0:
        return None
    alpha = np.clip(distance / contrast, 0.0, 1.0)
    alpha[alpha < 0.2] = 0.0
    rows = alpha.sum(axis=1)
    if rows.max() <= 0:
        return None
    # Effective coverage height: each row contributes at most one row-height,
    # scaled by how much of the peak coverage it carries.  A hard-edged bar
    # therefore reads exactly its pixel height, and an anti-aliased edge
    # contributes its fractional share -- no interpolation, which used to add a
    # phantom half pixel on step edges.
    half = 0.5 * rows.max()
    if half <= 0:
        return None
    return float(np.clip(rows / half, 0.0, 1.0).sum())


def measure_pair(
    reference: np.ndarray, rendered: np.ndarray, gold_record: dict[str, Any]
) -> dict[str, Any] | None:
    """Ink statistics of one gold box on both images."""
    box = gold_record["bbox"]
    source = _ink_stats(reference, box)
    render = _ink_stats(rendered, box)
    if (
        source is None
        or render is None
        or source["height"] < 3
        or render["height"] < 3
    ):
        return None
    source_sub = subpixel_ink_height(reference, box)
    render_sub = subpixel_ink_height(rendered, box)
    return {
        "source_ink": source,
        "render_ink": render,
        "ink_ratio": render["height"] / float(source["height"]),
        "subpixel_ratio": (render_sub / source_sub)
        if source_sub and render_sub and source_sub >= 3 and render_sub >= 3
        else None,
        "ink_width_ratio": render["width"] / float(max(1, source["width"])),
        "ink_count_ratio": render["count"] / float(max(1, source["count"])),
    }


def _median(values: Sequence[float]) -> float | None:
    return round(float(np.median(values)), 3) if values else None


def _spread(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    array = np.asarray(values, dtype=np.float64)
    return {
        "n": int(array.size),
        "median": round(float(np.median(array)), 3),
        "p10": round(float(np.percentile(array, 10)), 3),
        "p90": round(float(np.percentile(array, 90)), 3),
        "within10pct": round(float((np.abs(array - 1.0) <= 0.10).mean()), 3),
    }


def probe_family(family_dir: Path, run_root: Path) -> dict[str, Any] | None:
    """Measure one family's matched pairs and summarise both metrics."""
    from PIL import Image

    meta = json.loads((family_dir / "family.json").read_text(encoding="utf-8"))
    scale = float(meta.get("gold", {}).get("scale_to_reference") or 1.0)
    run_dir = run_root / Path(str(meta.get("pipeline_run") or "")).name
    readback = run_dir / "figma_ink_converged" / "readback.json"
    export = run_dir / "figma_ink_converged" / "export.png"
    if not readback.is_file() or not export.is_file():
        print(f"[skip] {family_dir.name}: missing {readback} or {export}")
        return None

    gold = flatten_gold_texts(
        json.loads((family_dir / "gold_tree.json").read_text(encoding="utf-8")), scale
    )
    pipe = flatten_readback(json.loads(readback.read_text(encoding="utf-8")))
    with Image.open(family_dir / "reference.png") as handle:
        reference = np.asarray(handle.convert("RGB"), dtype=np.int16)
    with Image.open(export) as handle:
        rendered = np.asarray(handle.convert("RGB"), dtype=np.int16)

    rows: list[dict[str, Any]] = []
    for gold_record, pipe_record in match_pairs(gold, pipe):
        measured = measure_pair(reference, rendered, gold_record)
        if measured is None:
            continue
        gold_size = gold_record.get("font_size")
        pipe_size = pipe_record.get("font_size")
        if not gold_size or not pipe_size:
            continue
        size_ratio = float(pipe_size) / float(gold_size)
        rows.append(
            {
                "text": gold_record["text"][:32],
                "gold_size": round(float(gold_size), 2),
                "pipe_size": round(float(pipe_size), 2),
                "size_ratio": round(size_ratio, 3),
                "ink_ratio": round(float(measured["ink_ratio"]), 3),
                "subpixel_ratio": round(float(measured["subpixel_ratio"]), 3)
                if measured.get("subpixel_ratio")
                else None,
                "ink_width_ratio": round(float(measured["ink_width_ratio"]), 3),
                "ink_count_ratio": round(float(measured["ink_count_ratio"]), 3),
                "font_metric": round(float(measured["ink_ratio"]) / size_ratio, 3)
                if size_ratio
                else None,
            }
        )
    if not rows:
        return None

    size_ratios = [row["size_ratio"] for row in rows]
    ink_ratios = [row["ink_ratio"] for row in rows]
    metrics = [row["font_metric"] for row in rows if row["font_metric"]]
    parity = [row["ink_ratio"] for row in rows if 0.95 <= row["size_ratio"] <= 1.05]
    correlation = None
    if len(rows) >= 3:
        correlation = round(
            float(np.corrcoef(np.asarray(size_ratios), np.asarray(ink_ratios))[0, 1]), 3
        )
    return {
        "family": meta.get("family") or family_dir.name,
        "run_dir": str(run_dir),
        "matched": len(rows),
        "size_ratio": _spread(size_ratios),
        "ink_ratio": _spread(ink_ratios),
        "font_metric": _spread(metrics),
        "ink_ratio_at_size_parity": {
            "n": len(parity),
            "median": _median(parity),
        },
        "subpixel_ratio": _spread(
            [row["subpixel_ratio"] for row in rows if row["subpixel_ratio"]]
        ),
        "correlation_size_vs_ink": correlation,
        "rows": rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", action="append", help="restrict to family name(s)")
    parser.add_argument(
        "--run-root",
        default=None,
        help="root holding the frozen runs (default: <repo>/output)",
    )
    parser.add_argument(
        "--out",
        default="output/_size_metric/size_metric.json",
        help="report output path",
    )
    args = parser.parse_args(argv)

    family_dirs = sorted(
        (d for d in BENCH.iterdir() if d.is_dir() and (d / "gold_tree.json").is_file()),
        key=lambda d: d.name,
    )
    if args.family:
        wanted = set(args.family)
        family_dirs = [d for d in family_dirs if d.name in wanted]
    run_root = Path(args.run_root).resolve() if args.run_root else ROOT / "output"

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_root": str(run_root),
        "families": {},
    }
    print(f"[probe] {len(family_dirs)} family(ies), run_root={run_root}")
    for family_dir in family_dirs:
        data = probe_family(family_dir, run_root)
        if data is None:
            continue
        report["families"][data["family"]] = data
        size = data["size_ratio"]
        ink = data["ink_ratio"]
        metric = data["font_metric"]
        parity = data["ink_ratio_at_size_parity"]
        print(f"\n===== {data['family']} ({data['matched']} pairs) =====")
        print(
            f"  font_ratio (size)  median={size.get('median')}  "
            f"p10-p90={size.get('p10')}..{size.get('p90')}  "
            f"within10%={size.get('within10pct')}"
        )
        print(
            f"  ink_height_ratio   median={ink.get('median')}  "
            f"p10-p90={ink.get('p10')}..{ink.get('p90')}  "
            f"within10%={ink.get('within10pct')}"
        )
        print(
            f"  font_metric (ink/size) median={metric.get('median')}  "
            f"p10-p90={metric.get('p10')}..{metric.get('p90')}"
        )
        sub = data["subpixel_ratio"]
        print(
            f"  subpixel ink ratio median={sub.get('median')}  "
            f"p10-p90={sub.get('p10')}..{sub.get('p90')}  "
            f"within10%={sub.get('within10pct')}"
        )
        print(
            f"  ink at size parity (0.95-1.05): n={parity['n']} "
            f"median={parity['median']}   corr(size,ink)={data['correlation_size_vs_ink']}"
        )

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[out] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
