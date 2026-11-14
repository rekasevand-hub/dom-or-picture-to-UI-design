"""Replay the seven frozen screenshots through the deterministic half.

Perception is the only stage that needs the vision model.  The cached PageGraph
holds that hand-off, and everything after it is geometry, pixels and rules:

    PageGraph + ocr_supplement + screenshot
        -> scene plan (as recorded in the graph)
        -> fixed-canvas compile: pixel style sampling, text/table repair,
           region recovery
        -> prototype.svg -> render.png

The plan itself is *not* rebuilt here.  ``10_pagegraph.json`` is saved after
``apply_scene_plan`` has rewritten container ids and owner refs, and rebuilding
from that state yields a different container mapping (measured: FluxWeaver came
back with three frames instead of six).  Replaying the plan it carries keeps the
comparison honest: the only thing that changes between two runs is the compiler.

    python scripts/replay_pagegraph.py                     # all seven
    python scripts/replay_pagegraph.py inventory2          # one
    python scripts/replay_pagegraph.py --out-suffix check  # output/_check_<tag>
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

#: The run each sample's perception output lives in.  These are the runs the
#: structural fixtures were frozen from.
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


def replay(tag: str, out_prefix: str, out_dir: Path | None = None) -> dict:
    source = ROOT / SAMPLES[tag] / "pipeline"
    reference = _read(source / "image_reference.json")
    graph = _read(source / "10_pagegraph.json")
    ocr = _read(source / "ocr_supplement.json")
    prepared = source / "prepared.json"
    sample_id = str((_read(prepared) if prepared.is_file() else {}).get("sample_id") or tag)
    if not graph.get("scenePlan"):
        raise SystemExit(f"{tag}: pagegraph carries no scene plan")

    design = build_image_design(
        graph,
        reference,
        sample_id=sample_id,
        ocr_observations=ocr.get("observations") or [],
    )
    out = (out_dir or (ROOT / "output" / f"{out_prefix}_{tag}")) / "pipeline"
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
        print(replay(tag, args.out_suffix), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
