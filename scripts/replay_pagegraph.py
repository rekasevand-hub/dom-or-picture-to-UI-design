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
import hashlib
import json
import os
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


def _within30_box(truth_path: str | Path, render_path: str | Path, box) -> float:
    """The same test, restricted to one candidate block."""
    import numpy as np
    from PIL import Image

    truth = np.asarray(Image.open(truth_path).convert("RGB"), dtype=np.int16)
    drawn = np.asarray(Image.open(render_path).convert("RGB"), dtype=np.int16)
    if truth.shape != drawn.shape:
        return 0.0
    x, y, w, h = (int(value) for value in box)
    height, width = truth.shape[:2]
    block_truth = truth[max(0, y) : min(height, y + h), max(0, x) : min(width, x + w)]
    block_drawn = drawn[max(0, y) : min(height, y + h), max(0, x) : min(width, x + w)]
    if block_truth.size == 0:
        return 0.0
    return round(
        float((np.abs(block_truth - block_drawn).max(axis=2) <= 30).mean()) * 100, 2
    )


def _patch_share(elements, canvas: tuple[int, int]) -> float:
    """Patch area as a percentage of the canvas — the budget the plan allows."""
    total = max(1, int(canvas[0]) * int(canvas[1]))
    area = sum(
        int(element["width"]) * int(element["height"])
        for element in elements
        if str(element.get("role") or "") == "patch"
    )
    return round(area / total * 100, 2)


#: Accepted frames measured on the frozen designs; mirrors the regression test so
#: a ticket cannot buy its way past a frame the sample is required to keep.
FRAME_FLOORS = {
    "AtomGit": 9,
    "FluxWeaver": 6,
    "inventory": 9,
    "inventory2": 11,
    "marketplace": 7,
    "review": 3,
    "wecom-modal": 6,
}


def _vision_callable():
    """The multimodal client, or ``None`` when no key is configured.

    Everything the model is allowed to do happens here: it receives the numbered
    strips and a prompt, and returns parsed JSON.  It is never handed a design.
    """
    try:
        from src.app.services.llm.llm_service import call_vlm
        from src.config import load_config
    except Exception:  # pragma: no cover - optional dependency at runtime
        return None
    config = load_config()
    if not getattr(config, "vision_api_key", ""):
        return None

    def call(prompt: str, strips) -> dict:
        import base64
        import io

        from PIL import Image

        content: list[dict] = [{"type": "text", "text": prompt}]
        for strip in strips:
            buffer = io.BytesIO()
            Image.fromarray(strip).save(buffer, format="PNG")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,"
                        + base64.b64encode(buffer.getvalue()).decode("ascii")
                    },
                }
            )
        answer = call_vlm([{"role": "user", "content": content}], config)
        if os.environ.get("RV_ARBITER_DEBUG"):
            print(f"[arbiter] raw answer ({len(answer)} chars): {answer[:400]!r}", flush=True)
        return _json_block(answer)

    return call


def _json_block(text: str) -> dict:
    """Pull the answer out of whatever wrapping the model put around it.

    Asked for an object, models happily answer with the array of tickets alone —
    or wrap either in a fenced block.  Both shapes mean the same thing here.
    """
    import json as _json

    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw[3:]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
        raw = raw.split("```")[0]
    raw = raw.strip()
    if raw.startswith("["):
        return {"tickets": _loads_list(raw)}
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = _json.loads(raw[start : end + 1])
    except ValueError:
        return {}
    if isinstance(parsed, list):
        return {"tickets": parsed}
    return parsed if isinstance(parsed, dict) else {}


def _loads_list(raw: str) -> list:
    import json as _json

    try:
        parsed = _json.loads(raw)
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []


def _largest_text_in(elements, box) -> str:
    """The text node a style ticket is about: the biggest one in the block."""
    if not box:
        return ""
    x, y, w, h = (int(value) for value in box)
    best, best_area = "", 0
    for element in elements:
        if element.get("type") != "text" or not element.get("text"):
            continue
        ex, ey = int(element.get("x") or 0), int(element.get("y") or 0)
        ew, eh = int(element.get("width") or 0), int(element.get("height") or 0)
        overlap = max(0, min(x + w, ex + ew) - max(x, ex)) * max(
            0, min(y + h, ey + eh) - max(y, ey)
        )
        if overlap > best_area:
            best, best_area = str(element.get("id") or ""), overlap
    return best


def _arbitrate(design: dict, picture: str | Path, out: Path, tag: str, render_path: Path) -> dict:
    """宏观仲裁：整页 + 三段的并排图，五类"设计神似"工单。

    门禁不再看像素——矢量和原图字形差 0.5px 是正常的。只看结构红线（帧、
    written == accepted、补丁预算）与几何防撞（重叠数不许变多）。
    """
    import copy

    import numpy as np
    from PIL import Image

    from src.app.services.rendering.adapter_base import paint_order, resolve_frames
    from src.app.services.structure.fidelity import vlm_arbiter as arbiter
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _keep_renderable_frames,
    )

    elements = design["elements"]
    truth = np.asarray(Image.open(picture).convert("RGB"), dtype=np.int16)
    drawn = np.asarray(Image.open(render_path).convert("RGB"), dtype=np.int16)
    canvas = (int(design["canvas"]["width"]), int(design["canvas"]["height"]))
    image_sha = hashlib.sha256(Path(picture).read_bytes()).hexdigest()
    key = arbiter.render_key(image_sha, render_path)
    frozen_path = out / "15_arbiter_tickets.json"
    frozen = arbiter.DesignFile.load(frozen_path, key)
    report: dict = {"key": key, "source": "frozen", "tickets": len(frozen.tickets), "applied": 0, "rolledBack": []}
    if not frozen.tickets:
        vision = _vision_callable()
        if vision is None:
            report["note"] = "VISION_API_KEY 未配置，只回放冻结工单"
            return report
        panels = arbiter.macro_panels(truth, drawn)
        answer = vision(arbiter.design_prompt(arbiter.scene_digest(elements)), panels)
        tickets = arbiter.parse_design_tickets(answer)
        frozen = arbiter.DesignFile(key=key, tickets=tickets)
        frozen.save(frozen_path)
        report["source"] = "vlm"
        report["tickets"] = len(tickets)
    if not frozen.tickets:
        return report

    floor = FRAME_FLOORS.get(tag, 0)
    for ticket in frozen.tickets:
        shadow = copy.deepcopy(elements)
        changed = arbiter.execute_design(ticket, elements, truth, canvas)
        if not changed:
            report["rolledBack"].append({"type": ticket.type, "why": ["not-executable"], "detail": ticket.note[:40]})
            continue
        _render(design, out)
        reasons: dict = {}
        written = sum(1 for element in elements if element.get("layoutChildren"))
        accepted = resolve_frames(elements, paint_order(elements), reasons)
        # written counts the frames the compiler *asked* for; the renderer may
        # refuse one, and the compiler's own pass then drops it.  The invariant
        # the tests hold is kept == accepted, so that is what the gate has to
        # compare — comparing against `written` rejected every ticket, including
        # ones that only changed a font weight.
        kept = _keep_renderable_frames(elements, written)
        gate = arbiter.DesignGate(
            frames=int(kept),
            frames_floor=max(floor, 0),
            written_equals_accepted=kept == len(accepted),
            patch_share=_patch_share(elements, canvas),
            collisions_before=arbiter.count_collisions(shadow),
            collisions_after=arbiter.count_collisions(elements),
        )
        if gate.passed:
            report["applied"] += 1
            report.setdefault("appliedTickets", []).append(
                {"type": ticket.type, "fix": ticket.fix, "ref": ticket.ref, "change": changed, "note": ticket.note[:60]}
            )
            continue
        elements[:] = shadow
        _render(design, out)
        report["rolledBack"].append({"type": ticket.type, "why": gate.failures, "detail": ticket.note[:40]})
    frozen.save(frozen_path)
    return report


def replay(
    tag: str,
    out_prefix: str,
    out_dir: Path | None = None,
    patches: bool = True,
    calibrate_text: bool = True,
    arbiter: bool = False,
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

    arbitration: dict = {}
    if arbiter:
        # Before the patches: a ticket that adds real text has to be judged
        # against the drawing, not against a pixel-perfect copy of the picture
        # that already covers the same block.
        arbitration = _arbitrate(design, _picture, out, tag, out / "render.png")

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
        "arbitration": arbitration,
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
    parser.add_argument(
        "--arbiter",
        action="store_true",
        help="run the frozen visual-arbiter tickets (needs 15_arbiter_tickets.json or a key)",
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
                    arbiter=args.arbiter,
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
