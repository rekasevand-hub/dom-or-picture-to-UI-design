# -*- coding: utf-8 -*-
"""Read-only structure audit: how far is this output from editable?

The roadmap's Phase 5 starts here (``IMPLEMENTATION_ROADMAP_2026-11-08.md``
§7.4 step 1): quantify the L1 floor and the §7.5 metrics before touching any
emission logic, so "结构还差多少" is a number instead of an impression.

Nothing here writes, renders, or connects to Figma -- it reads a finished run
directory and reports.

Usage:
  python scripts/audit_structure.py --run-dir output/_p25_mech2 --label holdout
  python scripts/audit_structure.py --run-dir ... --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONTAINMENT_TOLERANCE_PX = 2
LEAF_TYPES = {"TEXT", "RECTANGLE", "ELLIPSE", "VECTOR", "IMAGE"}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _readback_path(run_dir: Path) -> Path:
    acceptance_path = run_dir / "acceptance.json"
    if acceptance_path.is_file():
        acceptance = _load(acceptance_path)
        relative = (acceptance.get("artifacts") or {}).get("readback")
        if relative:
            candidate = run_dir / str(relative).replace("\\", "/")
            if candidate.is_file():
                return candidate
    candidates = sorted(run_dir.glob("figma*/readback.json"))
    if not candidates:
        raise SystemExit(f"no readback.json under {run_dir}")
    return candidates[-1]


def _box(node: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    absolute = node.get("absolute") or {}
    try:
        x = float(absolute.get("x") or 0)
        y = float(absolute.get("y") or 0)
        width = float(absolute.get("width") or 0)
        height = float(absolute.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return (x, y, width, height)


def _contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
    tolerance: float = CONTAINMENT_TOLERANCE_PX,
) -> bool:
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[0] + inner[2] <= outer[0] + outer[2] + tolerance
        and inner[1] + inner[3] <= outer[1] + outer[3] + tolerance
    )


def audit(run_dir: Path) -> dict[str, Any]:
    readback = _load(_readback_path(run_dir))
    design_path = run_dir / "figma_design.json"
    design = _load(design_path) if design_path.is_file() else {}
    acceptance_path = run_dir / "acceptance.json"
    acceptance = _load(acceptance_path) if acceptance_path.is_file() else {}

    types: dict[str, int] = {}
    max_depth = 0
    autolayout = 0
    overflow: list[dict[str, Any]] = []
    orphan_leaves: list[dict[str, Any]] = []
    node_count = 0

    def walk(node: Mapping[str, Any], depth: int, parent: Mapping[str, Any] | None):
        nonlocal max_depth, autolayout, node_count
        node_count += 1
        max_depth = max(max_depth, depth)
        node_type = str(node.get("type") or "UNKNOWN")
        types[node_type] = types.get(node_type, 0) + 1
        layout_mode = str(node.get("layoutMode") or "NONE").upper()
        if layout_mode not in {"NONE", ""}:
            autolayout += 1
        if parent is not None:
            outer, inner = _box(parent), _box(node)
            if outer and inner and not _contains(outer, inner):
                overflow.append(
                    {
                        "node": str(node.get("name") or node.get("id"))[:24],
                        "parent": str(parent.get("name") or parent.get("id"))[:24],
                        "nodeBox": [round(value) for value in inner],
                        "parentBox": [round(value) for value in outer],
                    }
                )
        children = [
            child for child in node.get("children") or [] if isinstance(child, Mapping)
        ]
        if depth == 1 and not children and node_type in LEAF_TYPES:
            orphan_leaves.append(str(node.get("name") or node.get("id"))[:24])
        for child in children:
            walk(child, depth + 1, node)

    walk(readback, 0, None)

    design_elements = [
        element
        for element in design.get("elements") or []
        if isinstance(element, Mapping)
    ]
    design_text = [
        element
        for element in design_elements
        if str(element.get("type")) == "text" and str(element.get("text") or "").strip()
    ]
    visual = acceptance.get("visual") or {}
    runtime = acceptance.get("runtime") or {}

    return {
        "label": "",
        "run": str(run_dir),
        "pixel": {
            "within30": visual.get("within30_pct"),
            "nativeOnlyWithin30": (visual.get("native_only") or {}).get("within30_pct"),
        },
        "runtime": {
            "bridgeBuild": runtime.get("bridgeBuild"),
            "buildMatches": runtime.get("buildMatches"),
        },
        # L1 -- the floor, required of every family
        "l1": {
            "singleRootFrame": str(readback.get("type")) == "FRAME",
            "orphanLeafCount": len(orphan_leaves),
            "nativeTextRatio": (
                round(types.get("TEXT", 0) / len(design_text), 3)
                if design_text
                else None
            ),
            "readbackNodes": node_count - 1,
            "designElements": len(design_elements),
            "silentDrops": (node_count - 1) - len(design_elements),
            "overflowCount": len(overflow),
        },
        # §7.5 -- the structure scoreboard
        "structure": {
            "depth": max_depth,
            "frames": types.get("FRAME", 0) - 1,
            "autolayoutNodes": autolayout,
            "autolayoutRatio": round(autolayout / max(1, node_count - 1), 4),
            "nodeTypes": dict(sorted(types.items(), key=lambda item: -item[1])),
        },
        "examples": {
            "orphanLeaves": orphan_leaves[:6],
            "overflow": overflow[:6],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)

    reports = []
    for value in args.run_dir:
        run_dir = Path(value)
        report = audit(run_dir)
        report["label"] = run_dir.name
        reports.append(report)

    header = "%-22s %7s %7s %6s %5s %5s %5s %5s %6s %6s" % (
        "run",
        "within30",
        "native",
        "depth",
        "FRAME",
        "AL",
        "孤儿",
        "溢出",
        "回读",
        "设计",
    )
    print(header)
    print("-" * len(header))
    for report in reports:
        l1, structure, pixel = report["l1"], report["structure"], report["pixel"]
        print(
            "%-22s %7s %7s %6d %5d %5d %5d %5d %6d %6d"
            % (
                report["label"][:22],
                f"{pixel['within30']:.2f}"
                if isinstance(pixel["within30"], (int, float))
                else "-",
                f"{pixel['nativeOnlyWithin30']:.2f}"
                if isinstance(pixel["nativeOnlyWithin30"], (int, float))
                else "-",
                structure["depth"],
                structure["frames"],
                structure["autolayoutNodes"],
                l1["orphanLeafCount"],
                l1["overflowCount"],
                l1["readbackNodes"],
                l1["designElements"],
            )
        )

    print()
    print("L1（结构底线，任何族都不例外）")
    for report in reports:
        l1 = report["l1"]
        print(
            "  %-22s 单一根 Frame=%s  原生文字比例=%s  静默丢弃=%d  父子溢出=%d  孤立顶层叶子=%d"
            % (
                report["label"][:22],
                "是" if l1["singleRootFrame"] else "否",
                l1["nativeTextRatio"],
                l1["silentDrops"],
                l1["overflowCount"],
                l1["orphanLeafCount"],
            )
        )

    if args.json:
        Path(args.json).write_text(
            json.dumps(reports, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
