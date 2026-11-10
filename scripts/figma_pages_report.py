# -*- coding: utf-8 -*-
"""Read-only Figma document report: pages, top-level frames, text styles.

Why this exists
---------------
The Phase 1 weight evidence was built from frozen files (``gold_tree.json``
and the run's ``10_content_inventory.json``).  Those files are exactly what the
gate measures, but they can *drift* from the live Figma document -- a frame can
be re-generated, a gold tree can be re-exported with a different scale, a
weight can be edited by hand.  Before trusting (or refuting) the evidence, the
live document must be inspected and compared against the frozen copies.

This tool never writes to Figma: it only issues ``get_node_tree``.

Usage
-----
    python scripts/figma_pages_report.py
    python scripts/figma_pages_report.py --texts "模型广场"
    python scripts/figma_pages_report.py --texts "日工时确认 · 截图重建" --json out.json
    python scripts/figma_pages_report.py --pages            # list pages only

Requires the bridge server (``python -m src.app.services.bridge_server``) and
the Figma development plugin to be connected.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DOCUMENT_ID = "0:0"


def _connect() -> Any:
    """Open a command connection to the bridge (adapter owns its lifecycle)."""
    from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter

    adapter = FigmaBridgeAdapter()
    adapter.connect()
    return adapter


def _walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a readback tree into a list of nodes (parents before children)."""
    flat: list[dict[str, Any]] = []

    def visit(current: dict[str, Any]) -> None:
        flat.append(current)
        for child in current.get("children") or []:
            visit(child)

    visit(node)
    return flat


def _text_style(node: dict[str, Any]) -> tuple[str, str, Any]:
    """Return ``(family, style, wght)`` for a TEXT node."""
    runs = node.get("textRuns") or []
    font = (runs[0].get("fontName") if runs else node.get("fontName")) or {}
    variation = font.get("variationSettings") or {}
    wght = variation.get("wght")
    if wght is None and isinstance(runs[0].get("fontWeight") if runs else None, (int, float)):
        wght = runs[0].get("fontWeight")
    return (
        str(font.get("family") or ""),
        str(font.get("style") or ""),
        wght,
    )


def list_pages(adapter: Any) -> list[dict[str, Any]]:
    """Return pages with their top-level frames (name/id/size only)."""
    tree = adapter._send("get_node_tree", {"nodeId": DOCUMENT_ID, "depth": 2})
    pages = []
    for page in tree.get("children") or []:
        frames = [
            {
                "id": child.get("id"),
                "name": child.get("name"),
                "type": child.get("type"),
                "width": child.get("width"),
                "height": child.get("height"),
                "x": child.get("x"),
                "y": child.get("y"),
            }
            for child in page.get("children") or []
        ]
        pages.append({"id": page.get("id"), "name": page.get("name"), "frames": frames})
    return pages


def find_frame(pages: Sequence[dict[str, Any]], needle: str) -> dict[str, Any] | None:
    """Locate a top-level frame by exact name, then by substring."""
    candidates = [frame for page in pages for frame in page["frames"]]
    for frame in candidates:
        if frame["name"] == needle:
            return frame
    for frame in candidates:
        if needle in str(frame["name"] or ""):
            return frame
    return None


def text_report(adapter: Any, frame_id: str, depth: int) -> dict[str, Any]:
    """Summarise every TEXT node inside ``frame_id`` with its resolved style."""
    tree = adapter._send("get_node_tree", {"nodeId": frame_id, "depth": depth})
    nodes = _walk(tree)
    texts = [node for node in nodes if node.get("type") == "TEXT"]
    styles = Counter()
    rows = []
    for node in texts:
        family, style, wght = _text_style(node)
        styles[f"{family}|{style}"] += 1
        rows.append(
            {
                "id": node.get("id"),
                "characters": node.get("characters"),
                "fontSize": node.get("fontSize"),
                "family": family,
                "style": style,
                "wght": wght,
                "x": node.get("x"),
                "y": node.get("y"),
                "width": node.get("width"),
                "height": node.get("height"),
            }
        )
    type_counts = Counter(str(node.get("type")) for node in nodes)
    max_depth = 0

    def measure(node: dict[str, Any], level: int) -> None:
        nonlocal max_depth
        max_depth = max(max_depth, level)
        for child in node.get("children") or []:
            measure(child, level + 1)

    measure(tree, 0)
    return {
        "frame": {"id": tree.get("id"), "name": tree.get("name")},
        "node_types": dict(type_counts),
        "max_depth": max_depth,
        "text_count": len(texts),
        "styles": dict(styles),
        "texts": rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", action="store_true", help="list pages only")
    parser.add_argument(
        "--texts",
        action="append",
        default=[],
        help="frame name (or unique substring) whose TEXT nodes should be dumped",
    )
    parser.add_argument("--depth", type=int, default=12, help="readback depth (default 12)")
    parser.add_argument("--json", default=None, help="write the full report to this path")
    args = parser.parse_args(argv)

    adapter = _connect()
    try:
        pages = list_pages(adapter)
        print(f"[document] {len(pages)} page(s)")
        for page in pages:
            print(f"\n== page {page['id']} · {page['name']} · {len(page['frames'])} frame(s)")
            for frame in page["frames"]:
                size = f"{frame['width']}x{frame['height']}" if frame["width"] else "?"
                print(
                    f"   {str(frame['id']):<12} {str(frame['type']):<8} {size:<12} "
                    f"@({frame['x']},{frame['y']})  {frame['name']}"
                )

        report: dict[str, Any] = {"pages": pages, "frames": {}}
        if args.texts:
            for needle in args.texts:
                frame = find_frame(pages, needle)
                if frame is None:
                    print(f"\n[fail] frame not found: {needle}")
                    continue
                print(f"\n===== {frame['name']} ({frame['id']}) =====")
                detail = text_report(adapter, str(frame["id"]), args.depth)
                report["frames"][frame["name"]] = detail
                print(
                    f"  nodes={sum(detail['node_types'].values())} depth={detail['max_depth']} "
                    f"texts={detail['text_count']}"
                )
                for key, count in sorted(detail["styles"].items()):
                    print(f"    {key:<28} {count}")
                for row in detail["texts"][:200]:
                    print(
                        f"    {str(row['wght'] or ''):<4} {str(row['fontSize'] or ''):<6} "
                        f"{str(row['style']):<12} {str(row['characters'])[:34]!r}"
                    )
            if args.json:
                out = Path(args.json)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"\n[out] {out}")
        return 0
    finally:
        try:
            adapter.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass


if __name__ == "__main__":
    raise SystemExit(main())
