"""Score a replay suffix: frames, within30/within15, patch budget, frame floor.

The three numbers the gates are written against, in one place, so a run can be
compared to the frozen baseline without re-deriving them each time:

    python scripts/sample_score.py --suffix _base
    python scripts/sample_score.py --suffix _pipe marketplace AtomGit
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


def score(tag: str, suffix: str, render_name: str = "render.png") -> dict:
    import numpy as np
    from PIL import Image

    out = ROOT / "output" / f"{suffix}_{tag}" / "pipeline"
    design_path = out / "12_design.json"
    render_path = out / render_name
    if not design_path.is_file() or not render_path.is_file():
        return {"tag": tag, "error": "missing run"}
    # 帧数与补丁面积要量"真正被渲染的那一份"，也就是带仲裁结果的那份。
    from src.app.services.structure.fidelity.arbitration_store import (
        load_arbitrated,
    )

    design = load_arbitrated(out) or json.loads(design_path.read_text(encoding="utf-8"))
    reference = json.loads(
        (ROOT / SAMPLES[tag] / "pipeline" / "image_reference.json").read_text(
            encoding="utf-8"
        )
    )
    truth = np.asarray(
        Image.open(locate(tag, reference["input"]["path"])).convert("RGB"), dtype=np.int16
    )
    drawn = np.asarray(Image.open(render_path).convert("RGB"), dtype=np.int16)
    if truth.shape != drawn.shape:
        return {"tag": tag, "error": f"shape {truth.shape} vs {drawn.shape}"}
    distance = np.abs(truth - drawn).max(axis=2)
    canvas = design.get("canvas") or {}
    area = max(1, int(canvas.get("width") or 0) * int(canvas.get("height") or 0))
    patch_area = sum(
        int(element.get("width") or 0) * int(element.get("height") or 0)
        for element in design.get("elements") or []
        if str(element.get("role") or "") == "patch"
    )
    elements = design.get("elements") or []
    return {
        "tag": tag,
        "frames": sum(1 for element in elements if element.get("layoutChildren")),
        "within30": round(float((distance <= 30).mean()) * 100, 2),
        "within15": round(float((distance <= 15).mean()) * 100, 2),
        "mean": round(float(distance.mean()), 2),
        "patches": sum(
            1 for element in elements if str(element.get("role") or "") == "patch"
        ),
        "patchShare": round(patch_area / area * 100, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tags", nargs="*", default=None)
    parser.add_argument("--suffix", default="_base")
    parser.add_argument("--render", default="render.png")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    tags = args.tags or list(SAMPLES)
    rows = [score(tag, args.suffix, args.render) for tag in tags]
    print(f"{'sample':12s} {'frames':>6s} {'w30':>7s} {'w15':>7s} {'mean':>6s} {'patch%':>7s}")
    for row in rows:
        if "error" in row:
            print(f"{row['tag']:12s} {row['error']}")
            continue
        print(
            f"{row['tag']:12s} {row['frames']:>6d} {row['within30']:>7.2f} "
            f"{row['within15']:>7.2f} {row['mean']:>6.2f} {row['patchShare']:>7.2f}"
        )
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"-> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
