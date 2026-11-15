"""Score a holdout run: both ends, non-text fidelity, and where it hurts.

The seven frozen samples have a score table because every run is compared to the
same baseline.  A holdout has no baseline — it has a *report*: what the defaults
did on a page they never saw, including the parts that came out wrong.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _boxes(design) -> list[tuple[int, int, int, int]]:
    boxes = []
    for element in design.get("elements") or []:
        if element.get("type") not in ("text", "button", "input"):
            continue
        try:
            x, y, w, h = (float(element.get(key) or 0) for key in ("x", "y", "width", "height"))
        except (TypeError, ValueError):
            continue
        if w >= 2 and h >= 2:
            boxes.append((int(x), int(y), int(w), int(h)))
    return boxes


def _text_mask(shape, boxes, pad: int = 4):
    import numpy as np

    mask = np.zeros(shape[:2], dtype=bool)
    height, width = shape[:2]
    for x, y, w, h in boxes:
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(width, x + w + pad), min(height, y + h + pad)
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return mask


def measure(truth, drawn, boxes) -> dict:
    import numpy as np

    distance = np.abs(truth - drawn).max(axis=2)
    mask = _text_mask(truth.shape, boxes)
    nontext = ~mask
    block = distance[nontext] if nontext.any() else distance.reshape(-1)
    return {
        "within30": round(float((distance <= 30).mean()) * 100, 2),
        "within15": round(float((distance <= 15).mean()) * 100, 2),
        "mean": round(float(distance.mean()), 2),
        "nontextWithin30": round(float((block <= 30).mean()) * 100, 2) if block.size else 0.0,
        "textShare": round(float(mask.mean()) * 100, 1),
    }


def hot_spots(truth, drawn, top: int = 6, cell: int = 96) -> list[dict]:
    import numpy as np

    distance = np.abs(truth - drawn).max(axis=2)
    bad = distance > 30
    height, width = bad.shape
    rows, cols = height // cell, width // cell
    if rows < 1 or cols < 1:
        return []
    grid = bad[: rows * cell, : cols * cell].reshape(rows, cell, cols, cell).sum(axis=(1, 3))
    order = np.dstack(np.unravel_index(np.argsort(grid.ravel())[::-1], grid.shape))[0]
    spots = []
    for row, col in order[: top * 3]:
        count = int(grid[row, col])
        if count < cell * cell * 0.08:
            continue
        spots.append(
            {
                "x": int(col * cell),
                "y": int(row * cell),
                "w": cell,
                "h": cell,
                "badPixels": count,
                "badShare": round(count / (cell * cell) * 100, 1),
            }
        )
        if len(spots) >= top:
            break
    return spots


def text_health(design) -> dict:
    """两条与观感直接相关的指标：文本压文本、表格字号离群。

    within30 在浅色大页上会被背景稀释；这两个数不会——只要同一处印了两份字，
    重叠率就上去；只要单元格字号超出同表中位数，离群数就上去。
    """
    texts = [
        element
        for element in design.get("elements") or []
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    boxes = []
    for element in texts:
        try:
            boxes.append(
                (
                    float(element.get("x") or 0),
                    float(element.get("y") or 0),
                    float(element.get("width") or 0),
                    float(element.get("height") or 0),
                )
            )
        except (TypeError, ValueError):
            boxes.append((0.0, 0.0, 0.0, 0.0))
    pairs = 0
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            width = min(first[0] + first[2], second[0] + second[2]) - max(first[0], second[0])
            height = min(first[1] + first[3], second[1] + second[3]) - max(first[1], second[1])
            if width <= 0 or height <= 0:
                continue
            inter = width * height
            union = first[2] * first[3] + second[2] * second[3] - inter
            smaller = min(first[2] * first[3], second[2] * second[3])
            if inter / max(1, union) >= 0.35 or inter / max(1, smaller) >= 0.55:
                pairs += 1
    groups: dict[str, list[float]] = {}
    for element in texts:
        element_id = str(element.get("id") or "")
        if not element_id.startswith(("table-cell:", "table-header:")):
            continue
        size = float((element.get("style") or {}).get("fontSize") or 0)
        if size <= 0:
            continue
        # 按行带粗分：同一行的单元格字号应当一致。
        band = round(float(element.get("y") or 0) / 40)
        groups.setdefault(f"{band}", []).append(size)
    # 离群 = 字号大于自己的盒子：这不是"比同行大"，而是字会印到格子外面。
    outliers = 0
    for element in texts:
        element_id = str(element.get("id") or "")
        if not element_id.startswith(("table-cell:", "table-header:")):
            continue
        size = float((element.get("style") or {}).get("fontSize") or 0)
        height = float(element.get("height") or 0)
        if size > 0 and height >= 8 and size > height + 0.5:
            outliers += 1
    return {
        "textNodes": len(texts),
        "overlapPairs": pairs,
        "overlapRate": round(pairs / max(1, len(texts)) * 100, 1),
        "outlierFonts": outliers,
    }

def occlusion_health(design) -> dict:
    """How many words are buried under something opaque that paints later.

    The third failure mode the holdout exposed: the tree has the node, the
    picture does not show it, and no ticket can find it.  Counted here with the
    renderer's own paint order, so the number matches what the export does.
    """
    from src.app.services.rendering.adapter_base import paint_order

    elements = list(design.get("elements") or [])
    ranks = {index: rank for rank, (index, _item) in enumerate(paint_order(elements))}

    def rect(element):
        return (
            float(element.get("x") or 0),
            float(element.get("y") or 0),
            float(element.get("width") or 0),
            float(element.get("height") or 0),
        )

    texts = [
        index
        for index, element in enumerate(elements)
        if element.get("type") == "text" and str(element.get("text") or "").strip()
    ]
    buried = []
    for index in texts:
        box = rect(elements[index])
        area = max(1.0, box[2] * box[3])
        for other, element in enumerate(elements):
            if other == index or element.get("type") == "text":
                continue
            opaque = bool(element.get("imageBase64")) or (
                not element.get("transparent")
                and str((element.get("style") or {}).get("fillColor") or "").lower()
                not in ("", "transparent", "none")
            )
            if not opaque:
                continue
            if ranks.get(other, 0) <= ranks.get(index, 0):
                continue
            cover = rect(element)
            width = min(cover[0] + cover[2], box[0] + box[2]) - max(cover[0], box[0])
            height = min(cover[1] + cover[3], box[1] + box[3]) - max(cover[1], box[1])
            if width <= 0 or height <= 0:
                continue
            if (width * height) / area >= 0.5:
                buried.append(
                    {
                        "text": str(elements[index].get("text") or "")[:16],
                        "by": str(element.get("id") or element.get("role") or "")[:24],
                        "cover": round((width * height) / area, 2),
                    }
                )
                break
    return {
        "coveredTexts": len(buried),
        "coveredShare": round(len(buried) / max(1, len(texts)) * 100, 1),
        "samples": buried[:4],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("--suffix", default="_holdout")
    parser.add_argument("--json", default=None)
    parser.add_argument("--prepared", default=None, help="directory of the --prepare-only run")
    args = parser.parse_args()

    import numpy as np
    from PIL import Image

    from src.app.services.structure.fidelity.arbitration_store import load_arbitrated

    out = ROOT / "output" / f"{args.suffix}_{args.tag}" / "pipeline"
    prepared = Path(args.prepared) if args.prepared else ROOT / "output" / f"_prep_{args.tag.split('_')[-1]}"
    reference = json.loads((prepared / "pipeline" / "image_reference.json").read_text(encoding="utf-8"))
    truth_path = reference["input"]["path"]
    truth = np.asarray(Image.open(truth_path).convert("RGB"), dtype=np.int16)
    design = load_arbitrated(out) or json.loads((out / "12_design.json").read_text(encoding="utf-8"))
    boxes = _boxes(design)
    canvas = design.get("canvas") or {}
    area = max(1, int(canvas.get("width") or 1) * int(canvas.get("height") or 1))
    patch_area = sum(
        int(element.get("width") or 0) * int(element.get("height") or 0)
        for element in design.get("elements") or []
        if str(element.get("role") or "") == "patch"
    )
    report: dict = {
        "tag": args.tag,
        "frames": sum(1 for e in design.get("elements") or [] if e.get("layoutChildren")),
        "elements": len(design.get("elements") or []),
        "patches": sum(
            1 for e in design.get("elements") or [] if str(e.get("role") or "") == "patch"
        ),
        "patchShare": round(patch_area / area * 100, 2),
    }
    report["text"] = text_health(design)
    report["occlusion"] = occlusion_health(design)
    run = out / "holdout_report.json"
    if run.is_file():
        report["seconds"] = json.loads(run.read_text(encoding="utf-8")).get("seconds")
    for name, filename in (("svg", "render.png"), ("figma", "figma_render.png")):
        path = out / filename
        if not path.is_file():
            continue
        drawn = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
        if drawn.shape != truth.shape:
            report[name] = {"error": f"size {drawn.shape} vs {truth.shape}"}
            continue
        report[name] = measure(truth, drawn, boxes)
        # 没有真机图时，热点就用 SVG 的——报告要有"哪里坏了"，不能只有数字。
        if name == "figma" or not (out / "figma_render.png").is_file():
            report["hotSpots"] = hot_spots(truth, drawn)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
