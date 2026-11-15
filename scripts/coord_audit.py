"""Compare the design's absolute coordinates with what Figma reports back.

The design speaks absolute page coordinates.  Figma speaks child-relative ones,
and the bridge converts between the two in three places (parent at creation,
auto-layout snapshot, readback).  Any of those can drop an offset, so this walks
the readback tree, sums the ancestors, and diffs the result against the plan.

Usage:
    python scripts/coord_audit.py marketplace            # table + summary
    python scripts/coord_audit.py --suffix _f5           # pick another run
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TAGS = ["AtomGit", "inventory", "marketplace"]


@dataclass
class Node:
    """One readback node, placed on the page."""

    id: str
    kind: str
    name: str
    text: str
    x: float
    y: float
    width: float
    height: float
    layout: str = ""
    absolute_children: int = 0
    child_count: int = 0


def flatten(tree: dict, nodes: list[Node], ox: float = 0.0, oy: float = 0.0) -> None:
    """Walk the tree, carrying the parent's origin.

    Figma reports `x`/`y` relative to the parent frame.  `absoluteBoundingBox` is
    available too but the readback does not always carry it, so the sum is the
    number a reader can check by hand.
    """
    if not isinstance(tree, dict):
        return
    x = ox + float(tree.get("x") or 0)
    y = oy + float(tree.get("y") or 0)
    kind = str(tree.get("type") or "")
    children = tree.get("children") or []
    if kind:
        nodes.append(
            Node(
                id=str(tree.get("id") or ""),
                kind=kind,
                name=str(tree.get("name") or ""),
                text=str(tree.get("characters") or ""),
                x=x,
                y=y,
                width=float(tree.get("width") or 0),
                height=float(tree.get("height") or 0),
                layout=str(tree.get("layoutMode") or ""),
                absolute_children=sum(
                    1
                    for child in children
                    if str(child.get("layoutPositioning") or "") == "ABSOLUTE"
                ),
                child_count=len(children),
            )
        )
    for child in children:
        flatten(child, nodes, x, y)


def design_nodes(design: dict) -> list[dict]:
    return [
        element
        for element in design.get("elements") or []
        if element.get("type") in ("text", "container") and not element.get("imageBase64")
    ]


def match(elements: list[dict], back: list[Node]) -> list[dict]:
    """Pair each design element with the readback node that prints it.

    Text is matched on its characters first (they are unique enough in a page and
    they survive the round trip); everything else on name, then nearest.  A
    mismatched pair would show up as a huge dx, so the pairing is also filtered
    by distance afterwards.
    """
    by_text: dict[str, list[Node]] = {}
    by_name: dict[str, list[Node]] = {}
    for node in back:
        if node.kind == "TEXT" and node.text:
            by_text.setdefault(node.text, []).append(node)
        by_name.setdefault(node.name, []).append(node)

    pairs: list[dict] = []
    used: set[str] = set()
    for element in elements:
        target_x = float(element.get("x") or 0)
        target_y = float(element.get("y") or 0)
        wanted_text = str(element.get("text") or "").strip()
        pool: list[Node] = []
        if element.get("type") == "text" and wanted_text:
            pool = [n for n in by_text.get(wanted_text, []) if n.id not in used]
        if not pool:
            name = str(element.get("name") or "")
            pool = [
                n
                for n in by_name.get(name, [])
                if n.id not in used and n.kind != "TEXT"
            ]
        if not pool:
            # Nearest node of the same kind, within a generous radius.
            pool = [
                n
                for n in back
                if n.id not in used
                and (n.kind == "TEXT") == (element.get("type") == "text")
                and abs(n.x - target_x) < 400
                and abs(n.y - target_y) < 200
            ]
        if not pool:
            pairs.append({"element": element, "node": None})
            continue
        best = min(pool, key=lambda n: abs(n.x - target_x) + abs(n.y - target_y))
        used.add(best.id)
        pairs.append({"element": element, "node": best})
    return pairs


def audit(tag: str, suffix: str, verbose: int = 12) -> dict:
    source = ROOT / "output" / f"{suffix}_{tag}" / "pipeline"
    design = json.loads((source / "12_design.json").read_text(encoding="utf-8"))
    tree_path = source / "readback_tree.json"
    if not tree_path.is_file():
        return {"tag": tag, "error": "no readback_tree.json"}
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    back: list[Node] = []
    flatten(tree, back)

    pairs = match(design_nodes(design), back)
    rows = []
    for pair in pairs:
        element, node = pair["element"], pair["node"]
        if node is None:
            rows.append(
                {
                    "id": str(element.get("id") or ""),
                    "kind": str(element.get("type") or ""),
                    "text": str(element.get("text") or "")[:18],
                    "missing": True,
                }
            )
            continue
        align = str((element.get("style") or {}).get("textAlign") or "left").lower()
        rows.append(
            {
                "id": str(element.get("id") or ""),
                "kind": str(element.get("type") or ""),
                "text": str(element.get("text") or "")[:18],
                "align": align,
                "dx": round(node.x - float(element.get("x") or 0), 1),
                "dy": round(node.y - float(element.get("y") or 0), 1),
                "dw": round(node.width - float(element.get("width") or 0), 1),
                "dh": round(node.height - float(element.get("height") or 0), 1),
                "missing": False,
            }
        )

    moved = [row for row in rows if not row["missing"]]
    bad = [row for row in moved if abs(row["dx"]) > 1 or abs(row["dy"]) > 1]
    moved.sort(key=lambda row: -(abs(row["dy"]) + abs(row["dx"])))
    frames = [node for node in back if node.kind == "FRAME"]
    auto = [node for node in frames if node.layout in ("HORIZONTAL", "VERTICAL")]
    summary = {
        "tag": tag,
        "pairs": len(rows),
        "missing": sum(1 for row in rows if row["missing"]),
        "within1": sum(1 for row in moved if abs(row["dx"]) <= 1 and abs(row["dy"]) <= 1),
        "worse10": sum(1 for row in moved if abs(row["dx"]) > 10 or abs(row["dy"]) > 10),
        "medianDy": sorted(row["dy"] for row in moved)[len(moved) // 2] if moved else 0,
        "frames": len(frames),
        "autoLayoutFrames": len(auto),
        "autoUnguarded": [
            {"name": node.name, "id": node.id, "layout": node.layout,
             "absolute": node.absolute_children, "children": node.child_count}
            for node in auto
            if node.absolute_children < node.child_count
        ],
        "alignedOutliers": [
            {
                "text": row["text"],
                "align": row["align"],
                "dx": row["dx"],
                "dw": row["dw"],
                # A wide box with right/centre alignment moves the *ink*, not the
                # node: dx plus dw is zero when the right edges agree.
                # right:  dx + dw == 0   centre: dx + dw/2 == 0
                "explainedByAlign": abs(row["dx"] + row["dw"]) <= 4
                if row["align"] in ("right", "end")
                else abs(row["dx"] + row["dw"] / 2) <= 4,
            }
            for row in moved
            if (abs(row["dx"]) > 1 or abs(row["dy"]) > 1)
            and (
                abs(row["dx"] + row["dw"]) <= 4
                if row["align"] in ("right", "end")
                else abs(row["dx"] + row["dw"] / 2) <= 4
            )
        ],
        "worst": moved[:verbose],
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tags", nargs="*", default=None)
    parser.add_argument("--suffix", default="_f5", help="run directory prefix")
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    reports = [audit(tag, args.suffix) for tag in (args.tags or TAGS)]
    for report in reports:
        if report.get("error"):
            print(f"{report['tag']}: {report['error']}")
            continue
        print(
            f"\n=== {report['tag']}  pairs={report['pairs']}  missing={report['missing']}  "
            f"within1px={report['within1']}/{report['pairs']}  "
            f">10px={report['worse10']}  median dy={report['medianDy']}"
        )
        print(
            f"    frames={report['frames']}  auto-layout={report['autoLayoutFrames']}  "
            f"unguarded={len(report['autoUnguarded'])}"
        )
        for item in report["autoUnguarded"][:6]:
            print(
                f"      auto {item['layout']:9s} abs={item['absolute']}/{item['children']} "
                f"{item['name']!r} {item['id']}"
            )
        if report["alignedOutliers"]:
            print(
                f"    aligned-cases={len(report['alignedOutliers'])} "
                "(wide box, ink starts later: dx + dw == 0)"
            )
        print(f"    {'dx':>7} {'dy':>7} {'dw':>7} {'dh':>7}  text")
        for row in report["worst"]:
            print(
                f"    {row['dx']:>7.1f} {row['dy']:>7.1f} {row['dw']:>7.1f} {row['dh']:>7.1f}  "
                f"{row['text'][:20]!r}"
            )
    if args.json:
        Path(args.json).write_text(
            json.dumps(reports, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"\nwritten: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
