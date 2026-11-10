# -*- coding: utf-8 -*-
"""Audit a gold tree before it is allowed to become an answer key.

Why: a gold frame from Figma Make is a *reconstruction*, and two independent
failures show up in practice (see docs/v2_mentor/20261110_font_weight_evidence.md
§5.5):

  1. geometry drift -- the boxes do not land on the screenshot's text, so any
     box-based measurement (ink height, font ratio) reads background instead of
     glyphs;
  2. text rewriting -- the model paraphrases instead of transcribing
     (``项目代码`` -> ``项目编号``), which silently kills every metric that pairs
     texts by exact string.

Both are invisible in the Figma canvas.  This script measures them and prints a
verdict, so "the new gold looks better" becomes a number.

Usage:
    python scripts/audit_gold_tree.py --family light-table
    python scripts/audit_gold_tree.py --family light-table --gold /path/new.json
    python scripts/audit_gold_tree.py --family dark-card-grid --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from scripts.p1_font_weight_evidence import (  # noqa: E402
    flatten_gold_texts,
    normalize_text,
)
from src.app.services.structure.fidelity.text_calibration import (  # noqa: E402
    _ink_stats,
)

BENCH = ROOT / "tests" / "fixtures" / "benchmark_families"

#: A gold box must land on ink this often before its geometry is trustworthy.
INK_FRACTION_USABLE = 0.80
#: Share of gold strings that must also exist in the pipeline inventory.  Below
#: this the gold is paraphrasing, not transcribing, and string-paired metrics
#: (style, font ratio) are meaningless for the family.
TEXT_AGREEMENT_USABLE = 0.80
#: Equally spaced sibling frames are read as table rows; the coefficient of
#: variation of their gaps must stay under this to count as a regular sequence.
PITCH_CV_MAX = 0.02


def _structure(tree: dict[str, Any]) -> dict[str, Any]:
    types: Counter[str] = Counter()
    depth = 0

    def walk(node: dict[str, Any], level: int = 0) -> None:
        nonlocal depth
        depth = max(depth, level)
        types[str(node.get("type"))] += 1
        for child in node.get("children") or []:
            walk(child, level + 1)

    walk(tree)
    return {
        "nodes": sum(types.values()),
        "depth": depth,
        "text": types.get("TEXT", 0),
        "frames": types.get("FRAME", 0),
    }


def _row_pitches(tree: dict[str, Any], min_rows: int = 4) -> list[dict[str, Any]]:
    """Find equally spaced sibling FRAME sequences -- i.e. table rows.

    Reported per sequence so a caller can compare against the screenshot's own
    row pitch.  A sequence shorter than ``min_rows`` is ignored: three boxes
    evenly spaced is a coincidence, twelve is a table.
    """
    sequences: list[dict[str, Any]] = []

    def scan(node: dict[str, Any]) -> None:
        children = [c for c in (node.get("children") or []) if c.get("type") == "FRAME"]
        if len(children) >= min_rows:
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for child in children:
                groups[f"{child.get('name')}|{round(float(child.get('height') or 0), 1)}"].append(child)
            for key, members in groups.items():
                if len(members) < min_rows:
                    continue
                members.sort(key=lambda c: float(c.get("y") or 0))
                ys = [float(c.get("y") or 0) for c in members]
                gaps = np.diff(ys)
                if gaps.size == 0 or float(gaps.mean()) <= 0:
                    continue
                cv = float(gaps.std() / gaps.mean())
                if cv > PITCH_CV_MAX:
                    continue
                sequences.append(
                    {
                        "parent": node.get("name"),
                        "name": key.split("|")[0],
                        "count": len(members),
                        "pitch": round(float(gaps.mean()), 2),
                        "cv": round(cv, 4),
                        "height": round(float(members[0].get("height") or 0), 1),
                    }
                )
        for child in node.get("children") or []:
            scan(child)

    scan(tree)
    return sequences


def _screenshot_row_pitch(reference: np.ndarray, gold_boxes: Sequence[Sequence[float]]) -> float | None:
    """Median gap between text lines of the screenshot inside the gold's span.

    Restricting to the gold's own vertical span keeps page chrome (tabs, tool
    bar) out of the measurement -- those rows have different spacing and would
    drag the median.
    """
    if not gold_boxes:
        return None
    top = int(min(box[1] for box in gold_boxes))
    bottom = int(max(box[1] + box[3] for box in gold_boxes))
    top, bottom = max(0, top), min(reference.shape[0], bottom)
    if bottom - top < 60:
        return None
    gray = reference[top:bottom].mean(axis=2)
    dark = (gray < 140).sum(axis=1)
    threshold = max(20.0, float(dark.max()) * 0.08)
    centres: list[float] = []
    index = 0
    while index < dark.size:
        if dark[index] >= threshold:
            end = index
            while end + 1 < dark.size and dark[end + 1] >= threshold:
                end += 1
            centres.append(top + (index + end) / 2.0)
            index = end + 1
        else:
            index += 1
    if len(centres) < 4:
        return None
    gaps = np.diff(np.asarray(centres))
    gaps = gaps[gaps > 4]
    if gaps.size == 0:
        return None
    # Mode, not median: the span also contains header/sub-header rows whose
    # spacing has nothing to do with the data grid, and there are few of them
    # but they are enough to drag a median (81 px -> 71.5 px on light-table).
    # The grid pitch repeats once per row, so it wins the frequency count.
    rounded = np.round(gaps).astype(int)
    values, counts = np.unique(rounded, return_counts=True)
    if counts.size and counts.max() >= 3:
        return float(values[int(np.argmax(counts))])
    return round(float(np.median(gaps)), 2)


def _inventory_texts(family_dir: Path) -> set[str]:
    """Strings the pipeline itself emitted for this family (frozen run)."""
    meta = json.loads((family_dir / "family.json").read_text(encoding="utf-8"))
    run = ROOT / str(meta.get("pipeline_run") or "")
    candidates = sorted(run.glob("figma*/readback.json"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        candidates = sorted(run.glob("**/readback.json"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        # The registered run often holds only ``pipeline/`` (the stage dirs are
        # large and stay in the main repo); the perception-frozen rerun is then
        # the closest thing to "what the pipeline emits today".
        rerun = ROOT / "output" / "_benchmark_families" / "rerun" / family_dir.name
        candidates = sorted(
            rerun.glob("figma*/readback.json"), key=lambda p: p.stat().st_mtime
        )
    if not candidates:
        return set()
    tree = json.loads(candidates[-1].read_text(encoding="utf-8"))
    keys: set[str] = set()

    def walk(node: dict[str, Any]) -> None:
        if node.get("type") == "TEXT":
            key = normalize_text(node.get("characters"))
            if key:
                keys.add(key)
        for child in node.get("children") or []:
            walk(child)

    walk(tree)
    return keys


def audit(family_dir: Path, gold_path: Path | None = None) -> dict[str, Any]:
    """Measure geometry, row pitch and text fidelity; return a verdict."""
    meta = json.loads((family_dir / "family.json").read_text(encoding="utf-8"))
    scale = float((meta.get("gold") or {}).get("scale_to_reference") or 1.0)
    source = gold_path or (family_dir / "gold_tree.json")
    tree = json.loads(source.read_text(encoding="utf-8"))
    gold = flatten_gold_texts(tree, scale)

    reference = np.asarray(
        Image.open(family_dir / "reference.png").convert("RGB"), dtype=np.int16
    )
    on_ink = 0
    for record in gold:
        if _ink_stats(reference, record["bbox"]):
            on_ink += 1
    ink_fraction = on_ink / len(gold) if gold else 0.0

    pitches = _row_pitches(tree)
    screenshot_pitch = _screenshot_row_pitch(reference, [r["bbox"] for r in gold])

    inventory = _inventory_texts(family_dir)
    gold_keys = {r["key"] for r in gold if r["key"]}
    overlap = gold_keys & inventory if inventory else set()
    text_agreement = len(overlap) / len(gold_keys) if gold_keys and inventory else None

    verdict: list[str] = []
    if ink_fraction < INK_FRACTION_USABLE:
        verdict.append(f"geometry: {ink_fraction:.1%} of boxes on ink < {INK_FRACTION_USABLE:.0%}")
    if text_agreement is not None and text_agreement < TEXT_AGREEMENT_USABLE:
        verdict.append(
            f"text: only {text_agreement:.1%} of gold strings appear in the pipeline "
            f"output < {TEXT_AGREEMENT_USABLE:.0%} (gold is paraphrasing)"
        )
    if screenshot_pitch and pitches:
        worst = min(
            pitches,
            key=lambda s: abs(s["pitch"] * scale - screenshot_pitch),
        )
        delta = worst["pitch"] * scale - screenshot_pitch
        verdict.append(
            f"row pitch: gold {worst['pitch']}x{scale:.3f}={worst['pitch'] * scale:.1f}px "
            f"vs screenshot {screenshot_pitch}px ({delta:+.1f})"
        )

    return {
        "family": meta.get("family") or family_dir.name,
        "gold_source": str(source),
        "scale_to_reference": scale,
        "structure": _structure(tree),
        "geometry": {
            "ink_fraction": round(ink_fraction, 3),
            "texts_on_ink": on_ink,
            "texts": len(gold),
            "usable": ink_fraction >= INK_FRACTION_USABLE,
        },
        "text_fidelity": {
            "gold_strings": len(gold_keys),
            "pipeline_strings": len(inventory),
            "agreement": round(text_agreement, 3) if text_agreement is not None else None,
            "usable": text_agreement is None
            or text_agreement >= TEXT_AGREEMENT_USABLE,
        },
        "row_pitch": {
            "gold_sequences": pitches,
            "screenshot_px": screenshot_pitch,
        },
        "notes": verdict,
        "verdict": "usable" if not any(
            [
                ink_fraction < INK_FRACTION_USABLE,
                text_agreement is not None and text_agreement < TEXT_AGREEMENT_USABLE,
            ]
        ) else "not-usable",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", action="append", help="restrict to family name(s)")
    parser.add_argument(
        "--gold",
        default=None,
        help="audit this gold tree instead of the family's frozen one",
    )
    parser.add_argument("--json", default=None, help="write the full report here")
    args = parser.parse_args(argv)

    family_dirs = sorted(
        (d for d in BENCH.iterdir() if d.is_dir() and (d / "family.json").is_file()),
        key=lambda d: d.name,
    )
    if args.family:
        wanted = set(args.family)
        family_dirs = [d for d in family_dirs if d.name in wanted]

    reports = []
    for family_dir in family_dirs:
        gold_path = Path(args.gold) if args.gold else None
        report = audit(family_dir, gold_path)
        reports.append(report)
        g, t = report["geometry"], report["text_fidelity"]
        print(f"\n===== {report['family']} =====")
        print(f"  structure      nodes={report['structure']['nodes']} "
              f"text={report['structure']['text']} depth={report['structure']['depth']}")
        print(f"  geometry       {g['texts_on_ink']}/{g['texts']} on ink "
              f"= {g['ink_fraction']:.1%}  usable={g['usable']}")
        agreement = "n/a" if t["agreement"] is None else f"{t['agreement']:.1%}"
        print(f"  text fidelity  {t['gold_strings']} gold / {t['pipeline_strings']} pipeline "
              f"strings, agreement={agreement}  usable={t['usable']}")
        for seq in report["row_pitch"]["gold_sequences"]:
            scaled = seq["pitch"] * report["scale_to_reference"]
            print(f"  row sequence   {seq['name']} x{seq['count']}  pitch={seq['pitch']} "
                  f"({scaled:.1f}px physical)  cv={seq['cv']}")
        print(f"  screenshot     row pitch={report['row_pitch']['screenshot_px']}px")
        for note in report["notes"]:
            print(f"  ! {note}")
        print(f"  VERDICT        {report['verdict']}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[out] {args.json}")
    return 0 if all(r["verdict"] == "usable" for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
