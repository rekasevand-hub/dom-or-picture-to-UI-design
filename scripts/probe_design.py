"""Read one compiled design and answer the four questions a bad render asks.

    python scripts/probe_design.py output/_phys_FluxWeaver
    python scripts/probe_design.py output/_phys_AtomGit --text 智能体开发
    python scripts/probe_design.py output/_phys_FluxWeaver --pills --fonts

* ``--frames``  containers that ended up as frames, with role and radius
* ``--pills``   boxes whose corner radius is at least half their height — a
                capsule, whatever the element claims to be
* ``--text``    every node overlapping the words given, in paint order, so an
                occluder is identified by name instead of guessed at
* ``--fonts``   text nodes grouped by size, flagging rows whose sizes disagree
                with their own line

Paint order comes from the renderer's own key, which is what the export obeys.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _design(out: Path) -> dict:
    for name in ("pipeline/12_design.json", "figma_design.json"):
        path = out / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise SystemExit(f"no design under {out}")


def _rect(element) -> tuple[float, float, float, float]:
    return tuple(float(element.get(k) or 0) for k in ("x", "y", "width", "height"))


def _overlap(a, b) -> tuple[float, float]:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return (max(0.0, w), max(0.0, h))


def _order(elements):
    from src.app.services.rendering.adapter_base import paint_order

    return [(index, element) for index, element in paint_order(elements)]


def show_frames(elements) -> None:
    frames = [item for item in elements if item.get("layoutChildren")]
    print(f"[frames] {len(frames)}")
    for item in frames:
        box = _rect(item)
        radius = (item.get("style") or {}).get("borderRadius")
        print(
            f"   {item.get('role') or item.get('type'):<12} "
            f"({int(box[0])},{int(box[1])}) {int(box[2])}x{int(box[3])} "
            f"r={radius} kids={len(item['layoutChildren'])} {str(item.get('name') or '')[:18]}"
        )


def show_pills(elements) -> None:
    print("[pills] radius >= 0.45 * height")
    for element in elements:
        x, y, w, h = _rect(element)
        if h <= 0 or w <= 0:
            continue
        radius = (element.get("style") or {}).get("borderRadius")
        try:
            radius = float(radius)
        except (TypeError, ValueError):
            continue
        if radius >= 0.45 * h:
            print(
                f"   {element.get('role') or element.get('type'):<14} "
                f"({int(x)},{int(y)}) {int(w)}x{int(h)} r={radius:g} "
                f"aspect={w / h:.1f} kids={len(element.get('layoutChildren') or [])} "
                f"{str(element.get('id') or '')[:26]}"
            )


def show_text(elements, needle: str) -> None:
    hits = [
        (index, element)
        for index, element in enumerate(elements)
        if needle in str(element.get("text") or "")
    ]
    if not hits:
        print(f"[text] no node contains {needle!r}")
        return
    ranks = {index: rank for rank, (index, _e) in enumerate(_order(elements))}
    print(f"[text] {len(hits)} node(s) contain {needle!r}")
    for index, hit in hits:
        box = _rect(hit)
        print(
            f"   HIT rank={ranks.get(index)} {hit.get('type')}/{hit.get('role')} "
            f"({int(box[0])},{int(box[1])}) {int(box[2])}x{int(box[3])} "
            f"size={(hit.get('style') or {}).get('fontSize')} color={(hit.get('style') or {}).get('color') or (hit.get('style') or {}).get('fillColor')} "
            f"{str(hit.get('text'))[:20]!r}"
        )
        for other_index, other in enumerate(elements):
            if other_index == index:
                continue
            ow, oh = _overlap(box, _rect(other))
            if ow <= 0 or oh <= 0:
                continue
            share = (ow * oh) / max(1.0, box[2] * box[3])
            if share < 0.05:
                continue
            print(
                f"      {'ABOVE' if ranks.get(other_index, 0) > ranks.get(index, 0) else 'below'} "
                f"rank={ranks.get(other_index)} {other.get('type')}/{other.get('role')} "
                f"({int(_rect(other)[0])},{int(_rect(other)[1])}) "
                f"{int(_rect(other)[2])}x{int(_rect(other)[3])} "
                f"cover={share:.2f} fill={(other.get('style') or {}).get('fillColor')} "
                f"radius={(other.get('style') or {}).get('borderRadius')} "
                f"{str(other.get('id') or '')[:24]}"
            )


def show_fonts(elements) -> None:
    rows: dict[int, list[tuple[float, str, tuple]]] = {}
    for element in elements:
        if element.get("type") != "text" or not str(element.get("text") or "").strip():
            continue
        size = float((element.get("style") or {}).get("fontSize") or 0)
        if size <= 0:
            continue
        x, y, w, h = _rect(element)
        band = int(round(y / 12.0))
        rows.setdefault(band, []).append((size, str(element.get("text"))[:18], (int(x), int(y))))
    print("[fonts] bands whose sizes disagree by > 1.5x")
    for band in sorted(rows):
        sizes = sorted({round(size, 1) for size, _t, _p in rows[band]})
        if len(sizes) < 2 or sizes[-1] <= sizes[0] * 1.5:
            continue
        print(f"   y~{band * 12}: {sizes}")
        for size, text, pos in sorted(rows[band]):
            print(f"      {size:>6.1f} {pos} {text!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--text", default=None)
    ap.add_argument("--frames", action="store_true")
    ap.add_argument("--pills", action="store_true")
    ap.add_argument("--fonts", action="store_true")
    args = ap.parse_args()
    design = _design(Path(args.out))
    elements = design.get("elements") or []
    print(f"{args.out}: elements={len(elements)}")
    if args.frames or not (args.pills or args.text or args.fonts):
        show_frames(elements)
    if args.pills:
        show_pills(elements)
    if args.text:
        show_text(elements, args.text)
    if args.fonts:
        show_fonts(elements)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
