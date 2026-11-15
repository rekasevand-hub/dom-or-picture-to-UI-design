# -*- coding: utf-8 -*-
"""Where the residual error actually lives, in four classes.

A single percentage says how bad a render is; it never says what to fix.  This
splits the failing pixels by the thing that owns them, in a fixed priority, so
the next hour goes to the biggest box rather than the loudest one:

    (a) text    — inside a text node's box: glyph shape and antialiasing
    (b) panel   — inside a filled container: fill, radius, a missing 1px border
    (c) graphic — inside an image or a recovered mark: logo, icon, stamp, patch
    (d) ground  — everything else: the page itself, gradients included

Priority is (a) → (b) → (c) → (d) and each pixel is counted once, so the four
shares add up to 100% of the failures.

    python scripts/error_attribution.py AtomGit inventory review
    python scripts/error_attribution.py --suffix _rf --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sample_sources import locate  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLASSES = ("text", "panel", "graphic", "ground")
#: A glyph's box is measured tight; the antialiasing that fails lives 1-2px out.
TEXT_PAD = 2


def _boxes(design: dict) -> dict[str, list[tuple[int, int, int, int]]]:
    text: list[tuple[int, int, int, int]] = []
    panel: list[tuple[int, int, int, int]] = []
    graphic: list[tuple[int, int, int, int]] = []
    for element in design.get("elements") or []:
        try:
            x, y, w, h = (int(element[key]) for key in ("x", "y", "width", "height"))
        except (KeyError, TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        role = str(element.get("role") or "")
        if element.get("type") == "text" and element.get("text"):
            text.append((x - TEXT_PAD, y - TEXT_PAD, w + 2 * TEXT_PAD, h + 2 * TEXT_PAD))
        elif element.get("imageBase64") or role in ("mark", "patch"):
            graphic.append((x, y, w, h))
        elif element.get("type") == "container" and (element.get("style") or {}).get(
            "fillColor"
        ):
            panel.append((x, y, w, h))
    return {"text": text, "panel": panel, "graphic": graphic}


def _mask(boxes: list[tuple[int, int, int, int]], shape) -> "object":
    import numpy as np

    mask = np.zeros(shape, dtype=bool)
    height, width = shape
    for x, y, w, h in boxes:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return mask


def attribute(tag: str, suffix: str) -> dict:
    import numpy as np
    from PIL import Image

    out = ROOT / "output" / f"{suffix}_{tag}" / "pipeline"
    design = json.loads((out / "12_design.json").read_text(encoding="utf-8"))
    reference = json.loads(
        (ROOT / "output" / f"_v2_fit_{tag}" / "pipeline" / "image_reference.json").read_text(
            encoding="utf-8"
        )
    )
    truth = np.asarray(Image.open(locate(tag, reference["input"]["path"])).convert("RGB"), dtype=np.int16)
    drawn = np.asarray(Image.open(out / "render.png").convert("RGB"), dtype=np.int16)
    if truth.shape != drawn.shape:
        return {"tag": tag, "error": "shape mismatch"}
    distance = np.abs(truth - drawn).max(axis=2)
    canvas = distance.size

    groups = _boxes(design)
    masks = {
        "text": _mask(groups["text"], distance.shape),
        "panel": _mask(groups["panel"], distance.shape),
        "graphic": _mask(groups["graphic"], distance.shape),
    }

    result: dict = {"tag": tag, "canvas": int(canvas)}
    for label, limit in (("within30", 30), ("within15", 15)):
        failing = distance > limit
        remaining = failing.copy()
        rows = {}
        for name in CLASSES:
            if name == "ground":
                owner = remaining
            else:
                owner = remaining & masks[name]
            remaining = remaining & ~owner
            rows[name] = int(owner.sum())
        total = int(failing.sum())
        result[label] = {
            "failing": total,
            "share_of_canvas": round(total / canvas * 100, 2),
            "classes": {
                name: {
                    "pixels": rows[name],
                    "share": round(rows[name] / max(1, total) * 100, 1),
                }
                for name in CLASSES
            },
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tags", nargs="*", default=None)
    parser.add_argument("--suffix", default="_rf")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    tags = args.tags or ["AtomGit", "inventory", "review"]

    results = [attribute(tag, args.suffix) for tag in tags]
    for limit in ("within30", "within15"):
        print(f"\n== {limit} ==")
        print(f"{'sample':12s} {'failing':>9s} {'%canvas':>8s} " + " ".join(f"{name:>8s}" for name in CLASSES))
        for row in results:
            if "error" in row:
                print(f"{row['tag']:12s} {row['error']}")
                continue
            block = row[limit]
            shares = " ".join(f"{block['classes'][name]['share']:7.1f}%" for name in CLASSES)
            print(f"{row['tag']:12s} {block['failing']:>9d} {block['share_of_canvas']:7.2f}% {shares}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n-> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
