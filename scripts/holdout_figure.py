"""Figures for a holdout: the whole page side by side, and the worst blocks blown up.

The reported numbers say *how much* is wrong; these two pictures say *where*.
A hotspot montage is four 2× crops, each left original / right export, so the
attribution in the report can be checked by eye instead of taken on trust.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _label(image, text: str, scale: int = 1):
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22 * scale)
    except OSError:
        font = ImageFont.load_default()
    w = 15 * len(text) * scale // 2 + 12
    draw.rectangle((0, 0, w, 30 * scale), fill=(0, 0, 0))
    draw.text((6, 4 * scale), text, fill=(255, 255, 255), font=font)
    return image


def compose(out: Path, draw_name: str, spots: list[dict], zoom: int = 2) -> list[Path]:
    import numpy as np
    from PIL import Image

    truth = np.asarray(Image.open(out / "00_screenshot.png").convert("RGB"))
    drawn = np.asarray(Image.open(out / draw_name).convert("RGB"))
    made = []
    gap = np.full((truth.shape[0], 14, 3), 255, dtype=np.uint8)
    whole = np.concatenate(
        [
            np.asarray(_label(Image.fromarray(truth), "ORIGINAL")),
            gap,
            np.asarray(_label(Image.fromarray(drawn), draw_name.split(".")[0].upper())),
        ],
        axis=1,
    )
    Image.fromarray(whole.astype("uint8")).save(out / "side_by_side.png")
    made.append(out / "side_by_side.png")

    tiles = []
    for spot in spots[:4]:
        x, y, w, h = spot["x"], spot["y"], spot["w"], spot["h"]
        a = truth[y : y + h, x : x + w]
        b = drawn[y : y + h, x : x + w]
        if a.shape != b.shape or a.size == 0:
            continue
        pair = np.concatenate(
            [a, np.full((a.shape[0], 6, 3), 255, dtype=np.uint8), b], axis=1
        )
        tile = Image.fromarray(pair).resize(
            (pair.shape[1] * zoom, pair.shape[0] * zoom), Image.LANCZOS
        )
        _label(tile, f"{x},{y}  {spot['badShare']:.0f}%", scale=1)
        tiles.append(np.asarray(tile))
    if tiles:
        rows = []
        for index in range(0, len(tiles), 2):
            pair = tiles[index : index + 2]
            if len(pair) == 1:
                pad = np.full(
                    (pair[0].shape[0], pair[0].shape[1], 3), 255, dtype=np.uint8
                )
                pair = [pair[0], pad]
            gap_v = np.full((10, pair[0].shape[1], 3), 255, dtype=np.uint8)
            rows.append(np.concatenate([pair[0], gap_v, pair[1]], axis=0))
        width = min(row.shape[1] for row in rows)
        rows = [row[:, :width] for row in rows]
        gap_h = np.full((10, width, 3), 255, dtype=np.uint8)
        strip = rows[0]
        for row in rows[1:]:
            strip = np.concatenate([strip, gap_h, row], axis=0)
        Image.fromarray(strip.astype(np.uint8)).save(out / "hotspots.png")
        made.append(out / "hotspots.png")
    return made


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dir")
    parser.add_argument("--draw", default="figma_render.png")
    args = parser.parse_args()
    out = Path(args.dir)
    scores = out / "holdout_scores.json"
    spots = json.loads(scores.read_text(encoding="utf-8")).get("hotSpots", []) if scores.is_file() else []
    for path in compose(out, args.draw, spots):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
