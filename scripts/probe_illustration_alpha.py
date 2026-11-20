"""Diagnose the image crops: would alpha-matting be admitted, and would it pay?

The question alpha matting answers is "this crop carries a rectangle of somebody
else's background".  Two things have to be true before the operation is worth
having:

1. the crop's surroundings are flat enough to be *recoverable* — an opaque
   photograph has structure right up to its border, and cutting it out would
   invent an edge that is not there;
2. the rectangle is actually costing pixels — a crop re-cut from the same place
   it is painted reproduces the page exactly, so a matte would change nothing.

This prints both, per crop, so the threshold is chosen from the distribution and
not from the one page that made us look:

    python scripts/probe_illustration_alpha.py                  # seven + csdn
    python scripts/probe_illustration_alpha.py clip_csdn        # one
    python scripts/probe_illustration_alpha.py --no-render      # ring stats only
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

RUNS = {
    "AtomGit": "output/_v2_fit_AtomGit",
    "FluxWeaver": "output/_v2_fit_FluxWeaver",
    "inventory": "output/_v2_fit_inventory",
    "inventory2": "output/_v2_fit_inventory2",
    "marketplace": "output/_v2_fit_marketplace",
    "review": "output/_v2_fit_review",
    "wecom-modal": "output/_v2_fit_wecom-modal",
    # holdouts: pages the thresholds were not tuned on.
    "clip_csdn": "output/_csdn_final",
}

BAND = (0.02, 0.30)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ring_stats(truth, box, thickness: int = 3) -> dict:
    """Gradient and colour spread of the outermost band of one crop.

    ``grad`` is the mean |dI| between horizontally adjacent pixels inside the
    band: a flat fill scores near zero, a photograph scores in the tens.  The
    band is the crop's own border, because that is where the offending rectangle
    is drawn — three pixels outside it is page background by construction and
    would always look flat.
    """
    import numpy as np

    height, width = truth.shape[:2]
    x, y, w, h = (int(value) for value in box)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return {}
    crop = np.asarray(truth[y0:y1, x0:x1], dtype=np.float32)
    t = max(1, min(thickness, (x1 - x0) // 4, (y1 - y0) // 4))
    mask = np.zeros(crop.shape[:2], dtype=bool)
    mask[:t, :] = True
    mask[-t:, :] = True
    mask[:, :t] = True
    mask[:, -t:] = True

    gray = crop.mean(axis=2)
    dx = np.abs(np.diff(gray, axis=1))
    dy = np.abs(np.diff(gray, axis=0))
    grad_band = np.concatenate(
        [dx[mask[:, :-1]], dy[mask[:-1, :]]]
    )
    band = crop[mask]
    # 单一纯色 vs 低频渐变：环带内颜色的极差，渐变会大，但仍远小于照片。
    return {
        "grad": round(float(grad_band.mean()), 2) if grad_band.size else 0.0,
        "grad_p90": round(float(np.percentile(grad_band, 90)), 2) if grad_band.size else 0.0,
        "spread": round(float((band.max(axis=0) - band.min(axis=0)).max()), 1),
        "std": round(float(band.std()), 2),
    }


def region_error(truth, drawn, box) -> dict:
    import numpy as np

    height, width = truth.shape[:2]
    x, y, w, h = (int(value) for value in box)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return {}
    a = np.asarray(truth[y0:y1, x0:x1], dtype=np.int16)
    b = np.asarray(drawn[y0:y1, x0:x1], dtype=np.int16)
    if a.shape != b.shape:
        return {}
    distance = np.abs(a - b).max(axis=2)
    return {
        "within30": round(float((distance <= 30).mean()) * 100, 1),
        "within15": round(float((distance <= 15).mean()) * 100, 1),
        "mean": round(float(distance.mean()), 2),
        "bad": round(float((distance > 30).mean()) * 100, 1),
    }


def preview(crop, rgba, backdrop=(214, 32, 149)) -> "object":
    """Original on the left, cut-out composited on a hostile colour on the right.

    The magenta is deliberate: it is nothing like any UI background in the
    corpus, so any leftover rectangle shows up as a hard-edged band instead of
    blending into a plausible page colour.
    """
    import numpy as np

    left = np.asarray(crop, dtype=np.uint8)[..., :3]
    alpha = (rgba[..., 3:4].astype(np.float32) / 255.0)
    plate = np.zeros_like(left, dtype=np.float32)
    plate[:] = backdrop
    right = rgba[..., :3].astype(np.float32) * alpha + plate * (1.0 - alpha)
    gap = np.full((left.shape[0], 8, 3), 255, dtype=np.uint8)
    return np.concatenate([left, gap, right.astype(np.uint8)], axis=1)


def matte_check(tag: str, truth, box, role: str) -> dict:
    from src.app.services.structure.fidelity import alpha_matte

    height, width = truth.shape[:2]
    x, y, w, h = box
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    crop = truth[y0:y1, x0:x1]
    ok, evidence = alpha_matte.admit(truth, (x0, y0, x1 - x0, y1 - y0), canvas=(width, height), role=role)
    if not ok:
        return {**evidence, "admitted": False}
    rgba, how = alpha_matte.matte(crop)
    result = {**evidence, **how, "admitted": True, "cut": rgba is not None}
    if rgba is not None:
        from PIL import Image

        out = ROOT / "output" / f"_alpha_{tag}"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"matte_{x}_{y}.png"
        Image.fromarray(preview(crop, rgba)).save(path)
        result["preview"] = str(path)
    return result


def probe(tag: str, render: bool = True, matte: bool = False) -> dict:
    import numpy as np
    from PIL import Image

    from sample_sources import bind
    from src.app.services.structure.image_contract import build_image_design

    run = ROOT / RUNS[tag] / "pipeline"
    reference = _read(run / "image_reference.json")
    graph = _read(run / "10_pagegraph.json")
    ocr_path = run / "ocr_supplement.json"
    ocr = _read(ocr_path) if ocr_path.is_file() else {}
    truth_path, graph, reference = bind(tag, graph, reference)
    truth_path = str(truth_path)
    truth = np.asarray(Image.open(truth_path).convert("RGB"), dtype=np.int16)
    canvas = (int(reference["input"]["size"][0]), int(reference["input"]["size"][1]))
    area = float(canvas[0] * canvas[1])

    design = build_image_design(
        graph,
        reference,
        sample_id=tag,
        ocr_observations=ocr.get("observations") or [],
    )
    drawn = None
    overall = {}
    if render:
        from replay_pagegraph import _render

        out = ROOT / "output" / f"_alpha_{tag}" / "pipeline"
        out.mkdir(parents=True, exist_ok=True)
        path = _render(design, out)
        drawn = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
        overall = region_error(truth, drawn, [0, 0, canvas[0], canvas[1]])

    crops = []
    for element in design.get("elements") or []:
        if element.get("type") != "image" or not element.get("imageBase64"):
            continue
        box = [
            int(float(element.get("x") or 0)),
            int(float(element.get("y") or 0)),
            int(float(element.get("width") or 0)),
            int(float(element.get("height") or 0)),
        ]
        share = box[2] * box[3] / area
        record = {
            "role": str(element.get("role") or element.get("assetKind") or ""),
            "box": box,
            "share": round(share * 100, 2),
            "in_band": BAND[0] <= share <= BAND[1],
        }
        record.update(ring_stats(truth, box))
        if drawn is not None:
            record.update(region_error(truth, drawn, box))
        if matte and record["in_band"]:
            record["matte"] = matte_check(tag, truth, box, record["role"])
        crops.append(record)
    crops.sort(key=lambda item: -item["share"])
    return {"tag": tag, "canvas": canvas, "images": len(crops), "overall": overall, "crops": crops}


def main() -> int:
    import os

    from src.app.services.structure.fidelity import alpha_matte

    # 只在显式设置时覆盖：默认值必须来自模块本身，否则探针会假装开关是开的。
    if os.environ.get("ALPHA_MATTE") is not None:
        alpha_matte.ALPHA_MATTE_ENABLED = os.environ["ALPHA_MATTE"] != "0"
    parser = argparse.ArgumentParser()
    parser.add_argument("tags", nargs="*")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--matte", action="store_true", help="cut out in-band crops and save previews")
    args = parser.parse_args()
    print(f"# alpha_matte={alpha_matte.ALPHA_MATTE_ENABLED}", flush=True)
    for tag in args.tags or list(RUNS):
        report = probe(tag, render=not args.no_render, matte=args.matte)
        print(json.dumps(report, ensure_ascii=False))
        for crop in report["crops"][:8]:
            print(
                f"  {crop['role'][:12]:<12} {crop['share']:>6.2f}% "
                f"band={str(crop['in_band']):<5} grad={crop.get('grad', 0):>6.2f} "
                f"p90={crop.get('grad_p90', 0):>6.2f} spread={crop.get('spread', 0):>6.1f} "
                f"| within30={crop.get('within30', '-'):>6} mean={crop.get('mean', '-')}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
