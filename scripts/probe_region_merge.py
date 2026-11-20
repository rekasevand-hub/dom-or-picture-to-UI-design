"""Every same-span merge candidate, and what is actually between the two blocks.

The rule this replaces ("skip anything bigger than 40% of the canvas") failed in
both directions, and neither failure is visible from the outside: the merge just
happens or just does not.  So the numbers are printed per candidate:

    fill   share of the gap band that is *not* page colour
    across fraction of canvas columns/rows the band's content covers
    verdict  what the geometric rule does with it

    python scripts/probe_region_merge.py                 # seven + holdouts
    python scripts/probe_region_merge.py clip_csdn       # one
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

SOURCES = {
    "AtomGit": ("samples/image_screenshots/AtomGit.jpg", "output/_v2_fit_AtomGit"),
    "FluxWeaver": ("samples/image_screenshots/FluxWeaver.png", "output/_v2_fit_FluxWeaver"),
    "inventory": ("samples/image_screenshots/inventory.png", "output/_v2_fit_inventory"),
    "inventory2": ("samples/image_screenshots/inventory2.png", "output/_v2_fit_inventory2"),
    "marketplace": ("samples/image_screenshots/marketplace.png", "output/_v2_fit_marketplace"),
    "review": ("samples/image_screenshots/review.jpg", "output/_v2_fit_review"),
    "wecom-modal": ("samples/image_screenshots/wecom-modal.png", "output/_v2_fit_wecom-modal"),
    "clip_csdn": ("C:/Users/lzq/.workbuddy/clipboard-images/clipboard-2026-11-16T16-39-15-451Z-9feb821c.jpg", "output/_csdn_final"),
    "erp": ("samples/holdout/holdout_erp.png", None),
    "gmail": ("samples/holdout/holdout_gmail.png", None),
    "worklog": ("samples/holdout/holdout_worklog.png", None),
}


def _text_boxes(tag: str, run: str | None) -> list[list[int]]:
    if not run:
        return []
    path = ROOT / run / "pipeline" / "ocr_supplement.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    boxes: list[list[int]] = []
    for item in data.get("observations") or []:
        box = item.get("bbox") or item.get("box")
        if box and len(box) >= 4:
            boxes.append([int(v) for v in box[:4]])
    return boxes


def probe(tag: str) -> dict:
    import numpy as np
    from PIL import Image

    from src.app.services.structure.physical_perception import (
        PAGE_REGION_MERGE_GAP,
        _gutter_is_through,
        _page_region_boxes,
        page_colour,
    )

    picture, run = SOURCES[tag]
    image = np.asarray(Image.open(ROOT / picture if not Path(picture).is_absolute() else picture).convert("RGB"), dtype=np.int16)
    height, width = image.shape[:2]
    page = page_colour(image)
    regions = _page_region_boxes(image, page, _text_boxes(tag, run), width, height)
    delta = np.abs(image - np.asarray(page, dtype=np.int16).reshape(1, 1, 3)).max(axis=2)
    barrier = delta >= 8
    gap_limit = PAGE_REGION_MERGE_GAP * max(width, height)

    rows = []
    for i in range(len(regions)):
        for j in range(i + 1, len(regions)):
            a, b = regions[i]["bbox"], regions[j]["bbox"]
            for axis in ("vertical", "horizontal"):
                if axis == "vertical":
                    if abs(a[0] - b[0]) > 2 or abs(a[2] - b[2]) > 2:
                        continue
                    gap = max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3])
                    start, end = min(a[1] + a[3], b[1] + b[3]), max(a[1], b[1])
                    strip = barrier[start:end, a[0] : a[0] + a[2]]
                    across = barrier[start:end, :].mean(axis=0)
                else:
                    if abs(a[1] - b[1]) > 2 or abs(a[3] - b[3]) > 2:
                        continue
                    gap = max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2])
                    start, end = min(a[0] + a[2], b[0] + b[2]), max(a[0], b[0])
                    strip = barrier[a[1] : a[1] + a[3], start:end]
                    across = barrier[:, start:end].mean(axis=1)
                if gap < 0 or gap > gap_limit or strip.size == 0:
                    continue
                fill = float(strip.mean())
                through = float((across >= 0.8).mean())
                blocked = _gutter_is_through(image, a, b, axis)
                # 间隙底色 vs 块外侧底色：相等说明那是页面自己的面，越过了块边界。
                deltas = []
                for side in ("low", "high"):
                    if axis == "vertical":
                        if side == "low":
                            strip = image[start:end, max(0, a[0] - 16) : a[0]]
                            if a[0] <= 0:
                                continue
                        else:
                            strip = image[start:end, a[0] + a[2] : min(width, a[0] + a[2] + 16)]
                    else:
                        if side == "low":
                            strip = image[max(0, a[1] - 16) : a[1], start:end]
                            if a[1] <= 0:
                                continue
                        else:
                            strip = image[a[1] + a[3] : min(height, a[1] + a[3] + 16), start:end]
                    if strip.size == 0:
                        continue
                    if axis == "vertical":
                        core = image[start:end, a[0] : a[0] + a[2]]
                    else:
                        core = image[a[1] : a[1] + a[3], start:end]
                    if core.size == 0:
                        continue
                    hull = np.median(core.reshape(-1, 3), axis=0)
                    other = np.median(strip.reshape(-1, 3), axis=0)
                    deltas.append(int(np.abs(hull - other).max()))
                rows.append(
                    {
                        "axis": axis,
                        "gap": int(gap),
                        "a": a,
                        "b": b,
                        "fill": round(fill, 3),
                        "across": round(through, 3),
                        "fill": round(fill, 3),
                        "edge": deltas,
                        "through": bool(blocked),
                        "mergedHeight": int(max(a[1] + a[3], b[1] + b[3]) - min(a[1], b[1]))
                        if axis == "vertical"
                        else None,
                    }
                )
    return {"tag": tag, "canvas": [width, height], "regions": len(regions), "candidates": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tags", nargs="*")
    args = parser.parse_args()
    for tag in args.tags or list(SOURCES):
        report = probe(tag)
        print(f"== {report['tag']}  {report['canvas'][0]}x{report['canvas'][1]}  regions={report['regions']}")
        for row in report["candidates"]:
            verdict = "BLOCK" if row["through"] else "merge"
            why = "same-surface" if row["through"] else "-"
            print(
                f"   {row['axis']:<10} gap={row['gap']:>3} fill={row['fill']:>5} "
                f"across={row['across']:>5} edge={row['edge']} h={row['mergedHeight']} {row['a']} + {row['b']} "
                f"-> {verdict} ({why})",
                flush=True,
            )
        if not report["candidates"]:
            print("   (no candidate)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
