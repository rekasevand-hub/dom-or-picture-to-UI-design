"""Recompile the seven frozen benchmark scene plans and render them again.

The screenshots were perceived once; the scene plans and OCR lines are on
disk.  Perception needs the vision model and money, the rest does not — so a
change to the compiler can be looked at in pixels by replaying only the
deterministic half.  This is how the presentation-layer passes were checked
after the API key was gone.

    python scripts/rebuild_frozen_samples.py                # all seven
    python scripts/rebuild_frozen_samples.py inventory      # one
    python scripts/rebuild_frozen_samples.py --out-suffix check

Writes ``output/<prefix>_<tag>/pipeline/{12_design.json,prototype.svg,render.png}``.
Never reuse an output directory between runs: a stale ``12_design.json`` makes
a fix look like it did nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.rendering.adapter_factory import build_adapter  # noqa: E402
from src.app.services.structure.image_contract import build_image_design  # noqa: E402
from src.app.utils.svg_raster import rasterize_svg  # noqa: E402
from src.config import load_config  # noqa: E402

#: Where each sample's perception output lives.  These are the runs the
#: structural fixtures were frozen from, so they are the reference for an A/B.
SAMPLES = {
    "AtomGit": "output/_v2_fit_AtomGit",
    "FluxWeaver": "output/_v2_fit_FluxWeaver",
    "inventory": "output/_v2_fit_inventory",
    "inventory2": "output/_v2_fit_inventory2",
    "marketplace": "output/_v2_fit_marketplace",
    "review": "output/_v2_fit_review",
    "wecom-modal": "output/_v2_fit_wecom-modal",
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rebuild(tag: str, out_prefix: str) -> dict:
    source = ROOT / SAMPLES[tag] / "pipeline"
    reference = _read(source / "image_reference.json")
    plan = _read(source / "11_scene_plan.json")
    ocr = _read(source / "ocr_supplement.json")
    prepared = source / "prepared.json"
    sample_id = str((_read(prepared) if prepared.is_file() else {}).get("sample_id") or tag)
    design = build_image_design(
        {"image": reference["input"]["path"], "route": "grounding", "scenePlan": plan},
        reference,
        sample_id=sample_id,
        ocr_observations=ocr.get("observations") or [],
    )
    out = ROOT / "output" / f"{out_prefix}_{tag}" / "pipeline"
    out.mkdir(parents=True, exist_ok=True)
    (out / "12_design.json").write_text(
        json.dumps(design, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    adapter = build_adapter("svg", replace(load_config(), output_dir=out))
    adapter.render_design(design)
    svg = out / "prototype.svg"
    if svg.is_file():
        rasterize_svg(svg, out / "render.png", device_scale_factor=1)
    elements = design.get("elements") or []
    return {
        "tag": tag,
        "elements": len(elements),
        "frames": sum(1 for element in elements if element.get("layoutChildren")),
        "texts": sum(
            1
            for element in elements
            if element.get("type") == "text" and element.get("text")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tags", nargs="*", help="sample names; default all seven")
    parser.add_argument("--out-suffix", default="_replay", help="output/<suffix>_<tag>")
    args = parser.parse_args()
    for tag in args.tags or sorted(SAMPLES):
        print(rebuild(tag, args.out_suffix), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
