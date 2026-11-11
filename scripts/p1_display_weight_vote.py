# -*- coding: utf-8 -*-
"""Does large text on this page actually get bolder? Vote on the gold's boxes.

Why this exists
---------------
``display-weight`` promotes any text at ``>= 1.8 x body`` to Bold, and that rule
was fitted on three families but *evidenced* on very little: the only boxes that
could be trusted were four badge outlines, and all four are the same kind of
thing.  A rule that governs every large word on the page cannot rest on that.

The gold tree offers a second, much larger set of trustworthy boxes: every TEXT
node carries Figma's own ``x/y/w/h``, at ``scale_to_reference = 1.0``, so the
box maps straight onto the reference screenshot.  The noise that killed the
earlier attempt lived in the *perception* boxes, not in the gold.

What it measures
----------------
For every gold text node: crop its box from the screenshot, count its ink, then
draw the same string at the same size at 400 / 500 / 700 and count again.
Whichever weight reproduces the source's ink area is the weight the source used
for that string.  Votes are grouped by size band (body vs display), which is
exactly the split the rule assumes.

Three filters run before voting, and every exclusion is counted and reported --
a rule that silently drops its inconvenient samples is not evidence:

* **rotated** nodes (four on dark): the box is pre-rotation, the screenshot is
  post-rotation, so the crop is not the glyph;
* **clipped** ink: ink touching the crop border, meaning the box is too tight or
  a neighbour bled in, so the count is not the string's;
* **no weight fits**: the best of the three still misses by a lot, which means
  the string in the gold is not the string in the picture (four transcriptions
  were corrected by hand in these fixtures).

What it cannot answer (measured, 2026-11-11)
--------------------------------------------
* **400 vs 500.**  The renderer resolves only two faces per family here, so
  400 and 500 come out pixel-identical for every sample (and 600/700 likewise).
  A three-way vote silently degenerates to Regular-vs-Bold, and the script says
  so when that happens.
* **Family.**  The page is not one family.  ``模型广场`` at 96 pt and
  ``本期好价`` at 52 pt are **Noto Serif SC Black**; rendering them in the page's
  sans and voting on weight measures the family, not the weight.
* **The truth was already available.**  Every gold TEXT node states its weight
  (``textRuns[0].fontName.style`` plus ``variationSettings.wght``): 22 Bold,
  19 Regular, 8 Medium, 2 Black on dark.  Where a gold exists, weight is a lookup,
  not an inference -- this script only earns its keep on a page with no gold.

Usage
-----
    python scripts/p1_display_weight_vote.py
    python scripts/p1_display_weight_vote.py --family dark-card-grid --json out.json

Read-only: no design, fixture or baseline is written.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from p1_source_font_metrics import _ink_metrics  # noqa: E402
from src.app.services.rendering.svg_adapter import SVGMockAdapter  # noqa: E402
from src.app.utils.svg_raster import rasterize_svg  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "benchmark_families"
RUNS = ROOT / "output" / "_benchmark_families" / "rerun"

WEIGHTS = (400, 500, 700)
BAND_RATIO = 1.8
MARGIN = 12
ROW_GAP = 24
# A sample whose best weight still misses the source by this much is not a
# weight question any more: the gold string and the picture disagree.
UNFIT = 0.35


def _text_nodes(tree: dict[str, Any], scale: float) -> list[tuple[dict[str, Any], float, float]]:
    """Every TEXT node with its page position.

    ``x/y`` in the export are **parent relative**, so they have to be summed
    down the tree; read them directly and every row of a list lands on the same
    coordinates (the first version measured ``模型广场`` at the top-left corner
    of the page, because that is where its parent's origin is).
    """
    root = dict(tree)
    root["x"], root["y"] = 0, 0
    found: list[tuple[dict[str, Any], float, float]] = []

    def walk(node: dict[str, Any], origin_x: float = 0.0, origin_y: float = 0.0) -> None:
        x = origin_x + float(node.get("x") or 0)
        y = origin_y + float(node.get("y") or 0)
        if node.get("type") == "TEXT":
            found.append((node, x * scale, y * scale))
        for child in node.get("children") or []:
            walk(child, x, y)

    walk(root)
    return found


def _is_rotated(node: dict[str, Any]) -> bool:
    """A rotated node's axis-aligned box differs from its own size."""
    absolute = node.get("absolute")
    if not isinstance(absolute, dict):
        return False
    width = float(node.get("width") or 0)
    height = float(node.get("height") or 0)
    return abs(float(absolute.get("width") or 0) - width) > 1.5 or abs(
        float(absolute.get("height") or 0) - height
    ) > 1.5


def _page_family(family: str) -> str:
    """The family the design uses most on this page."""
    path = RUNS / family / "figma_design.json"
    if not path.exists():
        return "Noto Sans SC"
    design = json.loads(path.read_text(encoding="utf-8"))
    names = Counter(
        str((element.get("style") or {}).get("fontFamily") or "")
        for element in design.get("elements") or []
        if str(element.get("type") or "") == "text"
    )
    names.pop("", None)
    return names.most_common(1)[0][0] if names else "Noto Sans SC"


def _page_colours(reference: Any) -> tuple[Any, Any]:
    """Background from the page border, ink as the opposite extreme."""
    border = np.concatenate(
        [
            reference[:4].reshape(-1, 3),
            reference[-4:].reshape(-1, 3),
            reference[:, :4].reshape(-1, 3),
            reference[:, -4:].reshape(-1, 3),
        ]
    )
    background = np.median(border, axis=0)
    ink = np.array([255, 255, 255]) if background.mean() < 128 else np.array([16, 16, 16])
    return background.astype(np.int16), ink.astype(np.int16)


def _collect(family: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Usable gold text samples for one family, plus what was dropped and why."""
    gold_path = FIXTURES / family / "gold_tree.json"
    reference_path = FIXTURES / family / "reference.png"
    meta_path = FIXTURES / family / "family.json"
    if not gold_path.exists() or not reference_path.exists():
        return [], {}
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    scale = float(((meta.get("gold") or {}).get("scale_to_reference")) or 1.0)
    reference = np.asarray(Image.open(reference_path).convert("RGB")).astype(np.int16)
    height, width = reference.shape[:2]

    dropped: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    for node, page_x, page_y in _text_nodes(gold, scale):
        text = str(node.get("characters") or "")
        size = node.get("fontSize")
        if isinstance(size, (int, float)):
            size = float(size) * scale
        if not text.strip() or not isinstance(size, (int, float)) or size <= 0:
            dropped["empty"] += 1
            continue
        if _is_rotated(node):
            dropped["rotated"] += 1
            continue
        box = [
            page_x,
            page_y,
            float(node.get("width") or 0) * scale,
            float(node.get("height") or 0) * scale,
        ]
        if box[2] < 4 or box[3] < 4:
            dropped["tiny box"] += 1
            continue
        # The box is measured exactly as given, and the render is measured in
        # the same box: a candidate that comes out wider is clipped by the same
        # frame the source was clipped by, so the comparison stays symmetric.
        if box[0] < 0 or box[1] < 0 or box[0] + box[2] > width or box[1] + box[3] > height:
            dropped["outside page"] += 1
            continue
        local = [int(round(box[0])), int(round(box[1])), int(round(box[2])), int(round(box[3]))]
        ink = _ink_metrics(reference, local, inset=0)
        if ink is None or ink["count"] < 20:
            dropped["no ink"] += 1
            continue
        # A node box is the text's *advance* box, so ink can legitimately touch
        # its edge on one side and still be whole.  Touching **both** sides of
        # one axis means the box is smaller than the glyphs and the count is a
        # truncated one -- that sample cannot answer anything.
        full_x = ink["left"] <= 0 and ink["left"] + ink["width"] >= local[2]
        full_y = ink["top"] <= 0 and ink["top"] + ink["height"] >= local[3]
        if full_x or full_y:
            dropped["clipped"] += 1
            continue
        samples.append(
            {
                "family": family,
                "text": text,
                "size": float(size),
                "box": [round(value, 2) for value in box],
                "source": ink,
            }
        )
    return samples, dict(dropped)


def _render_rows(
    samples: list[dict[str, Any]],
    family: str,
    weight: int,
    background: Any,
    ink_colour: Any,
    work: Path,
) -> list[dict[str, Any] | None]:
    """Render every sample once, in rows, on a single canvas.

    One browser launch per weight instead of one per sample: 239 samples x 3
    weights would otherwise be 700 renders for one question.
    """
    rows: list[tuple[float, float, float, float]] = []
    elements: list[dict[str, Any]] = []
    cursor = MARGIN
    for sample in samples:
        box = sample["box"]
        rows.append((MARGIN, cursor, box[2], box[3]))
        elements.append(
            {
                "type": "text",
                "x": MARGIN,
                "y": cursor,
                "width": box[2],
                "height": box[3],
                "text": sample["text"],
                "contentRef": f"text:{sample['text'][:16]}",
                "style": {
                    "fontSize": sample["size"],
                    "fontFamily": family,
                    "fontWeight": weight,
                    "fontWeightValue": weight,
                    "textColor": "#%02X%02X%02X"
                    % (int(ink_colour[0]), int(ink_colour[1]), int(ink_colour[2])),
                },
            }
        )
        cursor += box[3] + ROW_GAP
    canvas_width = int(max(row[2] for row in rows) + 2 * MARGIN)
    canvas_height = int(cursor + MARGIN)
    design = {
        "canvas": {
            "width": canvas_width,
            "height": canvas_height,
            "background": "#%02X%02X%02X"
            % (int(background[0]), int(background[1]), int(background[2])),
        },
        "elements": elements,
    }
    svg = work / f"rows_{family}_{weight}.svg"
    png = work / f"rows_{family}_{weight}.png"
    adapter = SVGMockAdapter(svg)
    adapter.connect()
    adapter.render_design(design)
    adapter.flush()
    adapter.disconnect()
    rasterize_svg(svg, png, width=canvas_width, height=canvas_height, device_scale_factor=1)
    image = np.asarray(Image.open(png).convert("RGB")).astype(np.int16)
    measured: list[dict[str, Any] | None] = []
    for left, top, box_w, box_h in rows:
        measured.append(_ink_metrics(image, [left, top, box_w, box_h], inset=0))
    return measured


def _vote(samples: list[dict[str, Any]], family: str, work: Path) -> dict[str, Any]:
    """Best weight per sample, and the tally per size band."""
    reference_path = FIXTURES / family / "reference.png"
    reference = np.asarray(Image.open(reference_path).convert("RGB")).astype(np.int16)
    background, ink_colour = _page_colours(reference)
    rendered: dict[int, list[dict[str, Any] | None]] = {
        weight: _render_rows(samples, family, weight, background, ink_colour, work)
        for weight in WEIGHTS
    }
    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        source = sample["source"]
        errors: dict[int, float] = {}
        for weight in WEIGHTS:
            candidate = rendered[weight][index]
            if candidate is None:
                errors[weight] = 1.0
                continue
            errors[weight] = abs(candidate["count"] - source["count"]) / max(1, source["count"])
        best = min(errors, key=lambda weight: errors[weight])
        rows.append(
            {
                "text": sample["text"][:24],
                "size": sample["size"],
                "errors": {str(weight): round(value, 3) for weight, value in errors.items()},
                "best": best,
                "unfit": errors[best] > UNFIT,
            }
        )
    sizes = [sample["size"] for sample in samples]
    body = Counter(round(value, 1) for value in sizes).most_common(1)[0][0]
    tally: dict[str, dict[str, Any]] = {}
    for band, predicate in (
        ("body", lambda value: value < BAND_RATIO * body),
        ("display", lambda value: value >= BAND_RATIO * body),
    ):
        members = [row for row in rows if predicate(row["size"]) and not row["unfit"]]
        counts = Counter(row["best"] for row in members)
        tally[band] = {
            "samples": len(members),
            "votes": {str(weight): counts.get(weight, 0) for weight in WEIGHTS},
            "mean_error": {
                str(weight): round(
                    sum(row["errors"][str(weight)] for row in members) / len(members), 3
                )
                if members
                else None
                for weight in WEIGHTS
            },
        }
    # Do the weights actually differ on this machine?  If 400 and 500 render
    # identically for every sample there is no three-way question to answer,
    # and a report that stays silent about that invites the wrong conclusion.
    same_400_500 = sum(1 for row in rows if row["errors"]["400"] == row["errors"]["500"])
    same_500_700 = sum(1 for row in rows if row["errors"]["500"] == row["errors"]["700"])
    collapsed = {
        "400_500": same_400_500 == len(rows),
        "500_700": same_500_700 == len(rows),
    }
    return {"body_size": body, "rows": rows, "tally": tally, "collapsed": collapsed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", action="append", default=None)
    parser.add_argument("--json", default="output/_p1_display_weight_vote/vote.json")
    args = parser.parse_args()

    families = args.family or ["dark-card-grid", "light-form", "light-table"]
    work = Path(args.json).parent
    work.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {"schema_version": "grounding-display-weight-vote/1.0", "families": {}}
    for family in families:
        samples, dropped = _collect(family)
        if not samples:
            print(f"[skip] {family}: 没有可用样本")
            continue
        print(f"\n== {family}: 可用 {len(samples)} 个" + (f"，剔除 {dropped}" if dropped else ""))
        result = _vote(samples, family, work)
        payload["families"][family] = {"dropped": dropped, **result}
        print(f"   正文字号 {result['body_size']}")
        if result["collapsed"]["400_500"]:
            print("   [warn] 本环境 400 与 500 渲染完全一致（该族没有 Medium 面），三选一退化为常规/粗体二选一")
        print(f"   {'档':8s} {'样本':>4s} {'400':>6s} {'500':>6s} {'700':>6s}   平均误差 400/500/700")
        for band in ("body", "display"):
            entry = result["tally"][band]
            votes = entry["votes"]
            mean = entry["mean_error"]
            print(
                f"   {band:8s} {entry['samples']:>4d} "
                f"{votes['400']:>6d} {votes['500']:>6d} {votes['700']:>6d}   "
                f"{mean['400']} / {mean['500']} / {mean['700']}"
            )
        unfit = [row for row in result["rows"] if row["unfit"]]
        if unfit:
            print(f"   无法判定（三种字重都差 >{int(UNFIT * 100)}%）：{len(unfit)} 个")
            for row in unfit[:5]:
                print(f"     - {row['text']!r} size={row['size']} errors={row['errors']}")

    Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[out] {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
