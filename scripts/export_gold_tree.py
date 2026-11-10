# -*- coding: utf-8 -*-
"""Re-export a benchmark family's ``gold_tree.json`` from the live Figma node.

The frozen gold trees are plain ``get_node_tree`` readbacks (every plugin field
is kept: ``layoutSnapshot``, ``bounds``, ``grid*`` ...).  Re-exporting is
therefore a straight dump with validation, not a transformation -- keeping the
schema byte-for-byte compatible is what lets ``check_benchmark_families.py``
consume the result without changes.

Refuses to write when the dump disagrees with the frozen reference screenshot:
a gold frame whose size does not match ``reference.png`` would silently break
``scale_to_reference`` and poison every answer-key metric.

Usage
-----
    python scripts/export_gold_tree.py --node 12:1223 \
        --out tests/fixtures/benchmark_families/light-form/gold_tree.json --dry-run

    python scripts/export_gold_tree.py --node 12:1223 \
        --out tests/fixtures/benchmark_families/light-form/gold_tree.json --force

Requires the bridge server and a connected Figma plugin.
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


def _connect() -> Any:
    """Open a command connection to the bridge."""
    from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter

    adapter = FigmaBridgeAdapter()
    adapter.connect()
    return adapter


def summarize(tree: dict[str, Any]) -> dict[str, Any]:
    """Node/text/depth statistics of a readback tree."""
    types: Counter[str] = Counter()
    texts: list[dict[str, Any]] = []
    max_depth = 0

    def walk(node: dict[str, Any], depth: int = 0) -> None:
        nonlocal max_depth
        max_depth = max(max_depth, depth)
        types[str(node.get("type"))] += 1
        if node.get("type") == "TEXT":
            texts.append(node)
        for child in node.get("children") or []:
            walk(child, depth + 1)

    walk(tree)
    return {
        "nodes": sum(types.values()),
        "max_depth": max_depth,
        "types": dict(types),
        "texts": len(texts),
    }


def reference_size(out_path: Path) -> tuple[int, int] | None:
    """Size of the family's ``reference.png`` (the geometry the gold must match)."""
    reference = out_path.parent / "reference.png"
    if not reference.is_file():
        return None
    from PIL import Image

    with Image.open(reference) as image:
        return image.size


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, help="Figma node id of the gold frame")
    parser.add_argument("--out", required=True, help="path to gold_tree.json")
    parser.add_argument("--depth", type=int, default=10, help="readback depth (default 10)")
    parser.add_argument(
        "--force", action="store_true", help="write even if the target already exists"
    )
    parser.add_argument("--dry-run", action="store_true", help="measure only, never write")
    args = parser.parse_args(argv)

    out_path = Path(args.out)
    if out_path.exists() and not args.force and not args.dry_run:
        print(f"[abort] {out_path} exists; pass --force to overwrite")
        return 2

    previous = None
    if out_path.is_file():
        previous = summarize(json.loads(out_path.read_text(encoding="utf-8")))

    adapter = _connect()
    try:
        tree = adapter._send("get_node_tree", {"nodeId": args.node, "depth": args.depth})
    finally:
        try:
            adapter.ws.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

    current = summarize(tree)
    size = reference_size(out_path)
    frame = (tree.get("width"), tree.get("height"))

    print(f"[node ] {args.node} · {tree.get('name')} · {tree.get('type')}")
    print(f"[shape] {frame[0]}x{frame[1]}  nodes={current['nodes']} "
          f"texts={current['texts']} depth={current['max_depth']}")
    print(f"[types] {current['types']}")
    if previous:
        print(f"[prior] nodes={previous['nodes']} texts={previous['texts']} "
              f"depth={previous['max_depth']}")
        if previous["texts"] != current["texts"]:
            print(f"[warn ] text count changed {previous['texts']} -> {current['texts']}")

    if size and frame[0] and frame[1]:
        if (int(frame[0]), int(frame[1])) != size:
            print(
                f"[abort] gold frame {frame[0]}x{frame[1]} != reference.png "
                f"{size[0]}x{size[1]}; scale_to_reference would be wrong"
            )
            return 2
        print(f"[ok   ] frame size matches reference.png {size[0]}x{size[1]}")

    if args.dry_run:
        print("[dry  ] no file written")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = out_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(out_path)
    print(f"[out  ] {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
