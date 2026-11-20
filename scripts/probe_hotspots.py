"""What is actually painted where the page is wrong.

A hotspot tells you *where*; it never tells you *which layer*.  The two are
different questions and only the second one is actionable — a 24-channel
difference under a card is either a missing fill, a doubled edge, or a picture
that should not be there, and each has a different fix.

So for every hotspot this prints the picture's colour, the render's colour, and
the elements whose boxes cover it, smallest first.  That is the list of suspects.

    python scripts/probe_hotspots.py clip_csdn
    python scripts/probe_hotspots.py clip_csdn --box 1500,540,420,140
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
for _path in (ROOT, SCRIPTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from probe_illustration_alpha import RUNS  # noqa: E402


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build(tag: str):
    import numpy as np
    from PIL import Image

    from sample_sources import bind
    from src.app.services.structure.image_contract import build_image_design

    run = ROOT / RUNS[tag] / "pipeline"
    reference = _read(run / "image_reference.json")
    graph = _read(run / "10_pagegraph.json")
    ocr_path = run / "ocr_supplement.json"
    ocr = _read(ocr_path) if ocr_path.is_file() else {}
    picture, graph, reference = bind(tag, graph, reference)
    design = build_image_design(
        graph, reference, sample_id=tag, ocr_observations=ocr.get("observations") or []
    )
    from replay_pagegraph import _render

    out = ROOT / "output" / f"_hot_{tag}" / "pipeline"
    out.mkdir(parents=True, exist_ok=True)
    render = _render(design, out)
    truth = np.asarray(Image.open(picture).convert("RGB"), dtype=np.int16)
    drawn = np.asarray(Image.open(render).convert("RGB"), dtype=np.int16)
    return design, truth, drawn


def _stats(truth, drawn, box) -> dict:
    import numpy as np

    height, width = truth.shape[:2]
    x, y, w, h = (int(value) for value in box)
    a = truth[max(0, y) : min(height, y + h), max(0, x) : min(width, x + w)]
    b = drawn[max(0, y) : min(height, y + h), max(0, x) : min(width, x + w)]
    if a.size == 0:
        return {}
    distance = np.abs(a - b).max(axis=2)
    return {
        "within30": round(float((distance <= 30).mean()) * 100, 1),
        "mean": round(float(distance.mean()), 2),
        "truth": "#%02x%02x%02x" % tuple(int(v) for v in np.median(a.reshape(-1, 3), axis=0)),
        "render": "#%02x%02x%02x" % tuple(int(v) for v in np.median(b.reshape(-1, 3), axis=0)),
    }


def _covering(elements, box, limit: int = 8) -> list[dict]:
    x, y, w, h = box
    rows = []
    for element in elements:
        ex, ey, ew, eh = (float(element.get(k) or 0) for k in ("x", "y", "width", "height"))
        if ew <= 0 or eh <= 0:
            continue
        ow = min(x + w, ex + ew) - max(x, ex)
        oh = min(y + h, ey + eh) - max(y, ey)
        if ow <= 0 or oh <= 0:
            continue
        share = (ow * oh) / float(max(1, w * h))
        if share < 0.3:
            continue
        rows.append(
            {
                "id": str(element.get("id") or "")[:34],
                "type": str(element.get("type") or ""),
                "role": str(element.get("role") or element.get("assetKind") or ""),
                "box": [int(ex), int(ey), int(ew), int(eh)],
                "cover": round(share, 2),
                "area": int(ew * eh),
                "fill": (element.get("style") or {}).get("fillColor"),
                "text": str(element.get("text") or "")[:14],
            }
        )
    rows.sort(key=lambda item: item["area"])
    return rows[:limit]


def hotspots(truth, drawn, cell: int = 96, top: int = 8) -> list[dict]:
    import numpy as np

    distance = np.abs(truth - drawn).max(axis=2)
    bad = distance > 30
    height, width = bad.shape
    rows, cols = height // cell, width // cell
    if rows < 1 or cols < 1:
        return []
    grid = bad[: rows * cell, : cols * cell].reshape(rows, cell, cols, cell).sum(axis=(1, 3))
    order = np.dstack(np.unravel_index(np.argsort(grid.ravel())[::-1], grid.shape))[0]
    found = []
    for row, col in order[: top * 2]:
        count = int(grid[row, col])
        if count < cell * cell * 0.06:
            continue
        found.append(
            {
                "box": [int(col * cell), int(row * cell), cell, cell],
                "badShare": round(count / (cell * cell) * 100, 1),
            }
        )
        if len(found) >= top:
            break
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("--box", action="append", default=[], help="x,y,w,h")
    parser.add_argument("--cells", type=int, default=8)
    args = parser.parse_args()

    design, truth, drawn = _build(args.tag)
    canvas = design["canvas"]
    print(f"== {args.tag} {canvas['width']}x{canvas['height']} bg={canvas['background']}")
    print("   overall", _stats(truth, drawn, [0, 0, canvas["width"], canvas["height"]]))
    boxes = [[int(v) for v in item.split(",")] for item in args.box]
    auto: list[list[int]] = []
    for spot in hotspots(truth, drawn, top=args.cells):
        auto.append(spot["box"])
        print(f"   hotspot {spot['box']} bad={spot['badShare']}% " f"{_stats(truth, drawn, spot['box'])}")
    boxes = boxes or auto
    for box in boxes:
        print(f"   -- box {box} {_stats(truth, drawn, box)}")
        for row in _covering(design["elements"], box):
            print(
                f"      {row['type']:<9} {row['role'][:10]:<10} {str(row['box']):<22} "
                f"cover={row['cover']:<5} area={row['area']:<7} fill={row['fill']} {row['id']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
