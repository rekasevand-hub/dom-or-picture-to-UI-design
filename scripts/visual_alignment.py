"""Pixel alignment of a replay against its screenshot.

``within30_pct`` is the share of pixels whose worst channel differs by at most
30 — the working definition of "looks the same".  ``within15_pct`` is the same
test at the tight end.  Both are computed on the exact canvas, no resize on
either side, so the number means what it says.

    python scripts/visual_alignment.py                 # all seven
    python scripts/visual_alignment.py marketplace     # one
    python scripts/visual_alignment.py --suffix _replay
    python scripts/visual_alignment.py --json out.json

For each sample it also writes ``diff.png`` next to the render: the screenshot
dimmed to a quarter, with every failing pixel drawn in red.  That picture is
what says *where* the missing five percent lives.
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

from sample_sources import locate  # noqa: E402

SAMPLES = {
    "AtomGit": "output/_v2_fit_AtomGit",
    "FluxWeaver": "output/_v2_fit_FluxWeaver",
    "inventory": "output/_v2_fit_inventory",
    "inventory2": "output/_v2_fit_inventory2",
    "marketplace": "output/_v2_fit_marketplace",
    "review": "output/_v2_fit_review",
    "wecom-modal": "output/_v2_fit_wecom-modal",
}

#: Channel distance the coarse test allows, and the fine one.
COARSE = 30
FINE = 15


def _load(source: Path, render: Path):
    import numpy as np
    from PIL import Image

    truth = Image.open(source).convert("RGB")
    drawn = Image.open(render).convert("RGB")
    if drawn.size != truth.size:
        drawn = drawn.resize(truth.size)
    return (
        np.asarray(truth, dtype=np.int16),
        np.asarray(drawn, dtype=np.int16),
    )


def measure(tag: str, suffix: str = "_replay") -> dict:
    import numpy as np
    from PIL import Image

    reference = json.loads(
        (ROOT / SAMPLES[tag] / "pipeline" / "image_reference.json").read_text(
            encoding="utf-8"
        )
    )
    source = locate(tag, (reference.get("input") or {}).get("path"))
    out = ROOT / "output" / f"{suffix}_{tag}" / "pipeline"
    render = out / "render.png"
    if not render.is_file():
        raise SystemExit(f"{tag}: no render at {render}")
    truth, drawn = _load(source, render)
    distance = np.abs(truth - drawn).max(axis=2)
    coarse = distance <= COARSE
    fine = distance <= FINE

    # The picture: the screenshot, quarter brightness, failures in red.
    canvas = (truth.astype(np.uint8) // 4 + 48).astype(np.uint8)
    canvas[distance > COARSE] = (255, 40, 40)
    Image.fromarray(canvas).save(out / "diff.png")

    return {
        "tag": tag,
        "pixels": int(distance.size),
        "within30_pct": round(float(coarse.mean()) * 100, 2),
        "within15_pct": round(float(fine.mean()) * 100, 2),
        "mean_error": round(float(distance.mean()), 2),
    }


#: A region worth replacing has to be visibly wrong: 40 channels is "not the
#: same thing", not "the same thing antialiased".
RESIDUAL_ERROR = 40
#: Bounds from the spec: a badge or a logo, never a panel.
RESIDUAL_MIN_SIDE = 14
RESIDUAL_MAX_WIDTH = 240
RESIDUAL_MAX_HEIGHT = 120
#: A line of words is the text pass's business; a block that is mostly words is
#: not replaced by its own pixels.
RESIDUAL_TEXT_LIMIT = 0.65
RESIDUAL_MAX_REGIONS = 48


def residual_regions(
    truth,
    drawn,
    text_boxes: list[tuple[int, int, int, int]],
    picture_boxes: list[tuple[int, int, int, int]],
) -> list[list[int]]:
    """Where the render is still badly wrong, in blocks small enough to patch.

    The mask is the failing pixels, dilated so a glyph's edges and its body are
    one blob; every blob is then judged on the shape of its box.  A region that
    is mostly covered by a text node is left to the text pass — replacing words
    with a picture of words is not a fix.
    """
    import numpy as np

    try:
        import cv2
    except Exception:  # pragma: no cover - opencv is a pipeline dependency
        return []
    diff = np.abs(truth - drawn).max(axis=2)
    mask = (diff > RESIDUAL_ERROR).astype(np.uint8)
    mask = cv2.dilate(mask, np.ones((5, 5), dtype=np.uint8))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    height, width = diff.shape
    candidates: list[tuple[int, list[int]]] = []
    for index in range(1, count):
        x, y, box_width, box_height, _area = (int(v) for v in stats[index, :5])
        if box_width < RESIDUAL_MIN_SIDE or box_height < RESIDUAL_MIN_SIDE:
            continue
        if box_width > RESIDUAL_MAX_WIDTH or box_height > RESIDUAL_MAX_HEIGHT:
            continue
        box = (x, y, box_width, box_height)
        failing = int((diff[y : y + box_height, x : x + box_width] > RESIDUAL_ERROR).sum())
        if failing < 80:
            continue
        # A label that only partly falls inside the block cannot be patched:
        # painting the block would print the words a second time, and cropping
        # them away would lose the node.  A label that sits *entirely* inside is
        # different — the block is its chip or stamp, and the patch goes under
        # the vector text so only the missing frame is filled in.
        # A chip or a stamp is a small block that exists *for* its label: the
        # patch goes under the vector text and nothing is printed twice.  A
        # larger block that merely contains a label is not that — its patch
        # would lay a second copy of the words behind the real one, which is
        # exactly the ghost this round is supposed to remove.  Such a block is
        # cut down to the part that has no text in it.
        mode = "over"
        chip = False
        for text in text_boxes:
            overlap = _intersection(box, text)
            if overlap <= 0:
                continue
            if box_width * box_height <= (text[2] * text[3]) * RESIDUAL_CHIP_AREA:
                chip = True
                continue
            shrunk = _avoid_text(box, text_boxes)
            if shrunk is None:
                box = None
                break
            box = shrunk
            box_width, box_height = box[2], box[3]
        if box is None:
            continue
        if chip:
            mode = "under"
        covered = 0
        for text in text_boxes:
            covered += _intersection(box, text)
        if covered / max(1, box_width * box_height) > RESIDUAL_TEXT_LIMIT:
            continue
        if any(_iou(box, picture) >= 0.4 for picture in picture_boxes):
            continue
        candidates.append((failing, [x, y, box_width, box_height, 5 if mode == "over" else 1]))
    candidates.sort(key=lambda item: item[0], reverse=True)
    chosen: list[list[int]] = []
    for _failing, box in candidates:
        if len(chosen) >= RESIDUAL_MAX_REGIONS:
            break
        if any(_iou(tuple(box[:4]), tuple(other[:4])) > 0.25 for other in chosen):
            continue
        chosen.append(box)
    return chosen


#: A block this close in area to its own label is that label's chip or stamp.
RESIDUAL_CHIP_AREA = 2.5


def _avoid_text(box: tuple[int, int, int, int], texts: list[tuple[int, int, int, int]]):
    """Largest sub-rectangle of ``box`` that no text box touches."""
    pieces = [box]
    for text in texts:
        nxt = []
        for piece in pieces:
            if _intersection(piece, text) == 0:
                nxt.append(piece)
                continue
            left, top, right, bottom = (
                piece[0],
                piece[1],
                piece[0] + piece[2],
                piece[1] + piece[3],
            )
            if text[0] > left:
                nxt.append((left, top, text[0] - left, bottom - top))
            if text[0] + text[2] < right:
                nxt.append((text[0] + text[2], top, right - (text[0] + text[2]), bottom - top))
            if text[1] > top:
                nxt.append((left, top, right - left, text[1] - top))
            if text[1] + text[3] < bottom:
                nxt.append((left, text[1] + text[3], right - left, bottom - (text[1] + text[3])))
            pieces = nxt or pieces
        pieces = nxt or pieces
    if not pieces:
        return None
    best = max(pieces, key=lambda piece: piece[2] * piece[3])
    if best[2] < RESIDUAL_MIN_SIDE or best[3] < RESIDUAL_MIN_SIDE:
        return None
    return best


def _intersection(
    left: tuple[int, int, int, int], right: tuple[int, int, int, int]
) -> int:
    width = min(left[0] + left[2], right[0] + right[2]) - max(left[0], right[0])
    height = min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1])
    if width <= 0 or height <= 0:
        return 0
    return width * height


def _iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    overlap = _intersection(left, right)
    if overlap == 0:
        return 0.0
    union = left[2] * left[3] + right[2] * right[3] - overlap
    return overlap / max(1, union)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tags", nargs="*", help="sample names; default all seven")
    parser.add_argument("--suffix", default="_replay", help="output/<suffix>_<tag>")
    parser.add_argument("--json", default="", help="also write the numbers here")
    args = parser.parse_args()
    rows = [measure(tag, args.suffix) for tag in args.tags or sorted(SAMPLES)]
    width = max(len(row["tag"]) for row in rows)
    print(f"{'sample'.ljust(width)}  {'within30':>9}  {'within15':>9}  {'mean err':>9}")
    for row in rows:
        print(
            f"{row['tag'].ljust(width)}  {row['within30_pct']:8.2f}%  "
            f"{row['within15_pct']:8.2f}%  {row['mean_error']:9.2f}"
        )
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
