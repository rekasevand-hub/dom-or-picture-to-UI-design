# -*- coding: utf-8 -*-
"""Which font is the page really set in? Measured on boxes that are exact.

Why this exists
---------------
Three separate-looking defects on the large discount badge turned out to share
one cause -- the renderer is not using the source's typeface:

* the text block sits 12 px low (Figma and the browser both place a line's
  baseline from the font's own ascent; Noto Sans SC's is 1.16 em against the
  reference's ~0.97 em in the same 72 px line box);
* the digits come out 27 % wider, so ``ink-convergence`` can only match the
  width by shrinking the size (49 px tall against a reference 52);
* the weight lands between the two stops the ladder offers (Regular = 1191
  accent pixels, Bold = 1703, the source = 1462).

Every one of those is a font-metric fact, and none of them can be fixed by
another calibration rule.  What has been missing is a measurement of *which*
family the source uses -- and the page happens to offer four boxes where that
can be measured without any perception noise: the text inside a drawn badge
outline.  Its frame is measured to the pixel, so the ink inside it is
comparable across candidates.

What it does
------------
For each text element whose centre falls inside a ``badge-outline``:

1. measure the source ink inside the element's box (top, left, width, height,
   pixel count) on the reference screenshot;
2. render the *same* element -- same box, size, rotation, line breaks and line
   sizes -- with each candidate family and weight, on a local canvas;
3. report the deltas.

A candidate that matches must reproduce all four numbers at once.  Width alone
can be matched by scaling, and height alone by moving, so a family that only
gets one of them right is not the answer.

Usage
-----
    python scripts/p1_source_font_metrics.py
    python scripts/p1_source_font_metrics.py --families "Microsoft YaHei,SimHei"
    python scripts/p1_source_font_metrics.py --json output/_font_metrics/evidence.json

Read-only: nothing here writes to Figma, a fixture, or a baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from src.app.services.rendering.svg_adapter import SVGMockAdapter  # noqa: E402
from src.app.utils.svg_raster import rasterize_svg  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "benchmark_families"
RUNS = ROOT / "output" / "_benchmark_families" / "rerun"

# A family nobody has: whatever the browser falls back to is the baseline the
# other rows have to beat, and a candidate whose numbers equal this one is not
# installed (the name resolved to the fallback).
FALLBACK = "__no-such-family__"

DEFAULT_FAMILIES = [
    "Noto Sans SC",
    "Microsoft YaHei",
    "SimHei",
    "DengXian",
    "Segoe UI",
    "Arial",
    "Inter",
    "HarmonyOS Sans SC",
]
DEFAULT_WEIGHTS = [400, 700]

# Room around the element inside the local canvas.  Generous enough that a
# candidate rendering wider than the source is still fully inside the frame.
MARGIN = 60


def _ink_metrics(image: Any, box: list[float], *, inset: int = 2) -> dict[str, Any]:
    """Ink extent, position and count inside ``box`` (theme agnostic).

    Args:
        image: ``(h, w, 3)`` RGB array.
        box: ``[x, y, width, height]`` in image pixels.
        inset: Border skip so a box edge never counts as ink.

    Returns:
        ``{top, left, width, height, count}`` or ``None`` when the box is empty.
    """
    height, width = image.shape[:2]
    x, y, box_w, box_h = (int(round(float(value))) for value in box[:4])
    left, top = max(0, x + inset), max(0, y + inset)
    right, bottom = min(width, x + box_w - inset), min(height, y + box_h - inset)
    if right <= left or bottom <= top:
        return None
    region = image[top:bottom, left:right]
    background = np.median(region.reshape(-1, 3), axis=0)
    mask = np.max(np.abs(region - background), axis=2) > 50
    count = int(mask.sum())
    if count == 0:
        return None
    rows, columns = np.where(mask)
    return {
        # Offsets against the box, not the canvas: the source is measured on the
        # page and a candidate on a local canvas, so absolute coordinates are
        # not comparable (this metric read 2810 % before the fix).
        "top": int(top + rows.min()) - int(round(float(box[1]))),
        "left": int(left + columns.min()) - int(round(float(box[0]))),
        "width": int(columns.max() - columns.min() + 1),
        "height": int(rows.max() - rows.min() + 1),
        "count": count,
    }


def _inside_outline(outlines: list[dict[str, Any]], element: dict[str, Any]) -> bool:
    """Whether ``element``'s centre sits inside one of the drawn outlines."""
    centre_x = float(element.get("x") or 0) + float(element.get("width") or 0) / 2
    centre_y = float(element.get("y") or 0) + float(element.get("height") or 0) / 2
    for outline in outlines:
        left = float(outline.get("x") or 0)
        top = float(outline.get("y") or 0)
        if (
            left <= centre_x <= left + float(outline.get("width") or 0)
            and top <= centre_y <= top + float(outline.get("height") or 0)
        ):
            return True
    return False


def _gold_faces(family: str) -> dict[str, dict[str, float]]:
    """``{characters: {size, height}}`` for every TEXT node in the gold tree.

    The gold is the source's own typesetting, so it is the only place the
    source's *font size* is stated.  Comparing a candidate at the design's size
    against a source drawn at another size measures the size difference, not the
    font -- the first version of this script did exactly that (the design says
    50.5/64 while the gold says 62, and 23.75 against 28 for the small badges).
    """
    path = FIXTURES / family / "gold_tree.json"
    if not path.exists():
        return {}
    tree = json.loads(path.read_text(encoding="utf-8"))
    faces: dict[str, dict[str, float]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "TEXT":
                text = str(node.get("characters") or "")
                size = node.get("fontSize")
                height = node.get("height")
                if text and isinstance(size, (int, float)) and size > 0:
                    faces.setdefault(
                        text,
                        {
                            "size": float(size),
                            "height": float(height) if isinstance(height, (int, float)) else 0.0,
                        },
                    )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(tree)
    return faces


def _align_to_gold(element: dict[str, Any], faces: dict[str, dict[str, float]]) -> bool:
    """Rewrite a sample's sizes to the gold's, so only the font differs.

    Returns ``True`` when every line found a gold node and the element was
    rewritten.
    """
    style = element.setdefault("style", {})
    lines = element.get("lines")
    sizes = element.get("lineSizes")
    if isinstance(lines, list) and isinstance(sizes, list) and len(lines) == len(sizes):
        gold = [faces.get(str(line)) for line in lines]
        if any(item is None for item in gold):
            return False
        element["lineSizes"] = [int(item["size"]) for item in gold]
        style["fontSize"] = float(element["lineSizes"][0])
        element["fontSize"] = float(element["lineSizes"][0])
        ratios = [
            item["height"] / item["size"]
            for item in gold
            if item["height"] and item["size"]
        ]
        if ratios:
            element["lineHeight"] = float(round(element["lineSizes"][0] * (sum(ratios) / len(ratios))))
            style["lineHeight"] = element["lineHeight"]
        return True
    text = str(element.get("text") or "")
    face = faces.get(text)
    if face is None:
        return False
    style["fontSize"] = face["size"]
    element["fontSize"] = face["size"]
    return True


def _samples(family: str) -> list[dict[str, Any]]:
    """Text elements on this family's page that sit inside a drawn outline."""
    design_path = RUNS / family / "figma_design.json"
    reference_path = FIXTURES / family / "reference.png"
    if not design_path.exists() or not reference_path.exists():
        return []
    design = json.loads(design_path.read_text(encoding="utf-8"))
    elements = [element for element in design.get("elements") or [] if isinstance(element, dict)]
    outlines = [
        element for element in elements if str(element.get("role") or "") == "badge-outline"
    ]
    if not outlines:
        return []
    reference = np.asarray(Image.open(reference_path).convert("RGB")).astype(np.int16)
    faces = _gold_faces(family)
    samples: list[dict[str, Any]] = []
    for element in elements:
        if str(element.get("type") or "") not in {"text", "button"}:
            continue
        if not str(element.get("text") or "").strip():
            continue
        if not _inside_outline(outlines, element):
            continue
        box = [
            float(element.get("x") or 0),
            float(element.get("y") or 0),
            float(element.get("width") or 0),
            float(element.get("height") or 0),
        ]
        ink = _ink_metrics(reference, box)
        if ink is None:
            continue
        aligned = _align_to_gold(element, faces)
        samples.append(
            {
                "family": family,
                "text": str(element["text"]),
                "box": [round(value, 2) for value in box],
                "rotation": element.get("rotation"),
                "fontSize": (element.get("style") or {}).get("fontSize"),
                "lineSizes": element.get("lineSizes"),
                "lines": element.get("lines"),
                "lineHeight": element.get("lineHeight"),
                "textColor": (element.get("style") or {}).get("textColor"),
                "source": ink,
                "gold_aligned": aligned,
                "element": element,
            }
        )
    return samples


def _render_sample(
    sample: dict[str, Any], font_family: str, weight: int, work: Path
) -> dict[str, Any] | None:
    """Render one sample with one family/weight on a local canvas and measure it.

    Only the family and weight change; the box, size, rotation, line breaks and
    line sizes are the sample's own.  That is what makes the comparison fair --
    a difference in any metric is then attributable to the font.
    """
    element = dict(sample["element"])
    style = dict(element.get("style") or {})
    style["fontFamily"] = font_family
    style["fontWeight"] = weight
    # Set both fields: the design carries a numeric ``fontWeight``, and the
    # candidate's weight has to override it *and* the ``fontWeightValue`` the
    # adapter prefers, or every candidate renders at the design's weight.
    style["fontWeightValue"] = weight
    element["style"] = style
    box = sample["box"]
    offset_x = float(box[0]) - MARGIN
    offset_y = float(box[1]) - MARGIN
    element["x"] = float(box[0]) - offset_x
    element["y"] = float(box[1]) - offset_y
    width = int(box[2] + 2 * MARGIN)
    height = int(box[3] + 2 * MARGIN)
    design = {
        "canvas": {"width": width, "height": height, "background": "#1A1917"},
        "elements": [element],
    }
    tag = f"{abs(hash((sample['text'], font_family, weight, sample['family']))) % 10**8:08d}"
    svg = work / f"{tag}.svg"
    png = work / f"{tag}.png"
    adapter = SVGMockAdapter(svg)
    adapter.connect()
    adapter.render_design(design)
    adapter.flush()
    adapter.disconnect()
    rasterize_svg(svg, png, device_scale_factor=1)
    image = np.asarray(Image.open(png).convert("RGB")).astype(np.int16)
    return _ink_metrics(image, [float(box[0]) - offset_x, float(box[1]) - offset_y, box[2], box[3]])


def _score(source: dict[str, Any], candidate: dict[str, Any]) -> dict[str, float]:
    """Relative error of a candidate against the source, per metric and summed.

    All four metrics are equally weighted: a family that nails the width by
    being too tall is not the source's family.
    """
    return {
        "width": abs(candidate["width"] - source["width"]) / max(1, source["width"]),
        "height": abs(candidate["height"] - source["height"]) / max(1, source["height"]),
        "count": abs(candidate["count"] - source["count"]) / max(1, source["count"]),
        "top": abs(candidate["top"] - source["top"]) / max(1, source["height"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--families",
        default=",".join(DEFAULT_FAMILIES),
        help="Comma separated candidate families.",
    )
    parser.add_argument(
        "--weights",
        default=",".join(str(weight) for weight in DEFAULT_WEIGHTS),
        help="Comma separated weights to try for every family.",
    )
    parser.add_argument("--json", default="output/_p1_source_font_metrics/evidence.json")
    args = parser.parse_args()

    families = [item.strip() for item in args.families.split(",") if item.strip()]
    weights = [int(item) for item in args.weights.split(",") if item.strip()]
    work = Path(args.json).parent
    work.mkdir(parents=True, exist_ok=True)

    samples: list[dict[str, Any]] = []
    for family in ("dark-card-grid", "light-form", "light-table"):
        samples.extend(_samples(family))
    if not samples:
        print("[skip] 没有可测样本：没有任何文本落在描边框内")
        return 0

    print(f"[samples] {len(samples)} 个（描边框内的文本）")
    for sample in samples:
        ink = sample["source"]
        print(
            f"  - {sample['family']}/{sample['text']!r} size={sample['fontSize']} "
            f"lines={sample['lines']} ink={ink['width']}x{ink['height']} "
            f"count={ink['count']} top={ink['top']}"
        )

    rows: list[dict[str, Any]] = []
    fallback: dict[tuple[str, str], dict[str, Any]] = {}
    for sample in samples:
        base = _render_sample(sample, FALLBACK, weights[0], work)
        if base is not None:
            fallback[(sample["family"], sample["text"])] = base

    for font_family in [FALLBACK] + families:
        for weight in weights:
            per_sample: list[dict[str, Any]] = []
            for sample in samples:
                candidate = _render_sample(sample, font_family, weight, work)
                if candidate is None:
                    continue
                per_sample.append(
                    {
                        "text": sample["text"],
                        "family": sample["family"],
                        "candidate": candidate,
                        "score": _score(sample["source"], candidate),
                    }
                )
            if not per_sample:
                continue
            keys = ("width", "height", "count", "top")
            mean = {
                key: round(sum(item["score"][key] for item in per_sample) / len(per_sample), 4)
                for key in keys
            }
            same_as_fallback = all(
                fallback.get((item["family"], item["text"])) == item["candidate"]
                for item in per_sample
                if (item["family"], item["text"]) in fallback
            )
            rows.append(
                {
                    "family": font_family,
                    "weight": weight,
                    "mean": mean,
                    "total": round(sum(mean.values()), 4),
                    "not_installed": same_as_fallback and font_family != FALLBACK,
                    "samples": per_sample,
                }
            )

    rows.sort(key=lambda row: row["total"])
    installed = [row for row in rows if not row["not_installed"]]
    print("\n[rank] 总分越低越接近源图（width + height + count + top 的平均相对误差）")
    print(f"  {'family':22s} {'w':>4s} {'Δw':>7s} {'Δh':>7s} {'Δink':>7s} {'Δtop':>7s} {'总':>7s}")
    for row in installed[:12]:
        mean = row["mean"]
        print(
            f"  {row['family'][:22]:22s} {row['weight']:>4d} "
            f"{mean['width']*100:6.1f}% {mean['height']*100:6.1f}% "
            f"{mean['count']*100:6.1f}% {mean['top']*100:6.1f}% {row['total']*100:6.1f}%"
        )
    missing = [row["family"] for row in rows if row["not_installed"]]
    if missing:
        print(f"\n[not installed] 与兜底完全一致，视为未安装：{', '.join(sorted(set(missing)))}")

    payload = {
        "schema_version": "grounding-source-font-metrics/1.0",
        "samples": [
            {key: value for key, value in sample.items() if key != "element"}
            for sample in samples
        ],
        "candidates": rows,
        "fallback": FALLBACK,
    }
    Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[out] {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
