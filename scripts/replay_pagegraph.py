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
SCRIPTS = Path(__file__).resolve().parent
for _path in (ROOT, SCRIPTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from sample_sources import MissingScreenshot, bind  # noqa: E402,F401
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


def _render(design: dict, out: Path, name: str = "render.png") -> Path:
    adapter = build_adapter("svg", replace(load_config(), output_dir=out))
    adapter.render_design(design)
    svg = out / "prototype.svg"
    if svg.is_file():
        rasterize_svg(svg, out / name, device_scale_factor=1)
    return out / name


def _within30(truth_path: str | Path, render_path: str | Path) -> float:
    """Share of pixels within 30 channels — the gate's own definition.

    Local, so a correction can be judged before the caller re-measures the world.
    """
    import numpy as np
    from PIL import Image

    truth = np.asarray(Image.open(truth_path).convert("RGB"), dtype=np.int16)
    drawn = np.asarray(Image.open(render_path).convert("RGB"), dtype=np.int16)
    if truth.shape != drawn.shape:
        return 0.0
    return round(float((np.abs(truth - drawn).max(axis=2) <= 30).mean()) * 100, 2)


def replay(
    tag: str,
    out_prefix: str,
    out_dir: Path | None = None,
    patches: bool = True,
    calibrate_text: bool = True,
) -> dict:
    source = ROOT / SAMPLES[tag] / "pipeline"
    reference = _read(source / "image_reference.json")
    graph = _read(source / "10_pagegraph.json")
    ocr = _read(source / "ocr_supplement.json")
    prepared = source / "prepared.json"
    sample_id = str((_read(prepared) if prepared.is_file() else {}).get("sample_id") or tag)
    if not graph.get("scenePlan"):
        raise SystemExit(f"{tag}: pagegraph carries no scene plan")
    # The screenshot is the only input perception cannot regenerate; resolve it
    # before anything is compiled so a missing sample says so plainly.
    _picture, graph, reference = bind(tag, graph, reference)

    out = (out_dir or (ROOT / "output" / f"{out_prefix}_{tag}")) / "pipeline"
    out.mkdir(parents=True, exist_ok=True)

    def build(regions=None) -> dict:
        design = build_image_design(
            graph,
            reference,
            sample_id=sample_id,
            ocr_observations=ocr.get("observations") or [],
            residual_regions=regions,
        )
        (out / "12_design.json").write_text(
            json.dumps(design, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return design

    design = build()
    _render(design, out)

    calibration: dict = {}
    if calibrate_text:
        # Pass two: every text box is measured against the ink it should have
        # covered.  The picture is the only authority on where a word sits, and
        # the render is the only way to know what the renderer drew.  A page
        # that gets worse is a page whose correction is thrown away.
        import copy

        from src.app.services.structure.fidelity.text_metrics import (  # noqa: PLC0415
            calibrate as calibrate_metrics,
        )

        kept = copy.deepcopy(design["elements"])
        before = _within30(_picture, out / "render.png")
        report = calibrate_metrics(design["elements"], _picture, out / "render.png")
        calibration = report.as_dict()
        if report.corrected:
            _render(design, out)
            after = _within30(_picture, out / "render.png")
            calibration["within30"] = {"before": before, "after": after}
            if after < before:
                design["elements"][:] = kept
                _render(design, out)
                calibration["reverted"] = True

    if patches:
        # Pass three: look at what the render got wrong and give the worst small
        # blocks back as pictures.  Everything else already had its chance.
        import numpy as np
        from PIL import Image

        sys.path.insert(0, str(ROOT / "scripts"))
        from visual_alignment import residual_regions  # noqa: PLC0415

        truth = np.asarray(Image.open(_picture).convert("RGB"), dtype=np.int16)
        drawn = np.asarray(Image.open(out / "render.png").convert("RGB"), dtype=np.int16)
        if drawn.shape == truth.shape:
            texts = [
                (int(e["x"]), int(e["y"]), int(e["width"]), int(e["height"]))
                for e in design.get("elements") or []
                if e.get("type") == "text" and e.get("text")
            ]
            pictures = [
                (int(e["x"]), int(e["y"]), int(e["width"]), int(e["height"]))
                for e in design.get("elements") or []
                if e.get("imageBase64")
            ]
            regions = residual_regions(truth, drawn, texts, pictures)
            if regions:
                # Painted onto the design that was just calibrated: rebuilding
                # from scratch here would quietly throw the calibration away.
                from src.app.services.structure.fidelity.fixed_canvas_compiler import (  # noqa: PLC0415
                    _apply_residual_patches,
                )

                canvas = design.get("canvas") or {}
                added = _apply_residual_patches(
                    design["elements"],
                    str(_picture),
                    (int(canvas.get("width") or 0), int(canvas.get("height") or 0)),
                    regions,
                )
                if added:
                    (out / "12_design.json").write_text(
                        json.dumps(design, ensure_ascii=False, indent=1), encoding="utf-8"
                    )
                    _render(design, out)

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
        "patches": sum(
            1 for element in elements if str(element.get("role") or "") == "patch"
        ),
        "calibration": calibration,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tags", nargs="*", help="sample names; default all seven")
    parser.add_argument("--out-suffix", default="_replay", help="output/<suffix>_<tag>")
    parser.add_argument(
        "--no-patches",
        action="store_true",
        help="skip the residual-patch pass",
    )
    parser.add_argument(
        "--no-calibrate",
        action="store_true",
        help="skip the per-box text metric calibration",
    )
    args = parser.parse_args()
    missing = 0
    for tag in args.tags or sorted(SAMPLES):
        try:
            print(
                replay(
                    tag,
                    args.out_suffix,
                    patches=not args.no_patches,
                    calibrate_text=not args.no_calibrate,
                ),
                flush=True,
            )
        except MissingScreenshot as exc:
            # One gone picture must not stop the other six from replaying, but
            # the run is incomplete and says so in its exit code.
            missing += 1
            print(f"skipped: {exc}", flush=True)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
