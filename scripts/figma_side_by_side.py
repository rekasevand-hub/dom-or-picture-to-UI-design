"""Original | SVG render | real Figma export, in one picture.

The three-way strip is the only artefact where a target-only defect is visible:
the SVG and the Figma frame disagree by a fraction of a point on average, but a
swallowed word or a missing hairline shows up immediately when they sit next to
the picture.

    python scripts/figma_side_by_side.py output/_final_marketplace/pipeline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _label(image, text: str):
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    draw.rectangle((0, 0, 210, 44), fill=(0, 0, 0))
    draw.text((10, 6), text, fill=(255, 255, 255), font=font)
    return image


def compose(out_dir: str | Path, name: str = "side_by_side.png") -> Path:
    import numpy as np
    from PIL import Image

    out = Path(out_dir)
    panels = []
    for filename, label in (
        ("00_screenshot.png", "ORIGINAL"),
        ("render.png", "SVG"),
        ("figma_render.png", "FIGMA"),
    ):
        path = out / filename
        if not path.is_file():
            continue
        panels.append(_label(Image.open(path).convert("RGB"), label))
    if len(panels) < 2:
        raise SystemExit(f"{out}: 至少需要两张图")
    height = max(panel.height for panel in panels)
    gap = np.full((height, 16, 3), 255, dtype=np.uint8)
    pieces = []
    for index, panel in enumerate(panels):
        if index:
            pieces.append(gap)
        pieces.append(np.asarray(panel))
    strip = np.concatenate(pieces, axis=1)
    target = out / name
    Image.fromarray(strip.astype(np.uint8)).save(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dirs", nargs="+")
    args = parser.parse_args()
    for directory in args.dirs:
        print(compose(directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
