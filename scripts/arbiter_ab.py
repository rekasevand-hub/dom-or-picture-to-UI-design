"""A/B one page: the deterministic design, with and without the VLM closed loop.

A is the emitted physical design exactly as ``figma_design.json`` holds it (the
artefact that already scored).  B is the same list of elements after
``arbiter.refine`` — same start, same guards, the only difference being the
model's quantitative patches and wireframe answers.

Both sides are emitted through the same script and scored with the same code, so
the comparison is between two designs and nothing else.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from replay_pagegraph import _render, _vision_callable  # noqa: E402
from src.app.services.structure.fidelity import vlm_arbiter as arbiter  # noqa: E402


def _load(tag: str) -> tuple[dict, np.ndarray]:
    base = ROOT / "output" / f"_phys_{tag}"
    design = json.loads((base / "figma_design.json").read_text(encoding="utf-8"))
    reference = json.loads(
        (base / "pipeline" / "image_reference.json").read_text(encoding="utf-8")
    )
    picture = Path(str(reference["input"]["path"]))
    if not picture.is_absolute():
        picture = ROOT / picture
    truth = np.asarray(Image.open(picture).convert("RGB"), dtype=np.int16)
    return design, truth


def _score(truth: np.ndarray, render_path: Path) -> dict:
    drawn = np.asarray(Image.open(render_path).convert("RGB"), dtype=np.int16)
    if drawn.shape != truth.shape:
        return {"error": f"size mismatch {drawn.shape} vs {truth.shape}"}
    distance = np.abs(truth - drawn).max(axis=2)
    ink = (np.asarray(Image.open(render_path).convert("L"), dtype=np.int16) < 200).astype(bool)
    return {
        "within30": round(float((distance <= 30).mean()) * 100, 2),
        "within15": round(float((distance <= 15).mean()) * 100, 2),
        "mean": round(float(distance.mean()), 3),
        "ink_mean": round(float(distance[ink].mean()) if ink.any() else 0.0, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("--mode", choices=("A", "B"), required=True)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--out", default="")
    parser.add_argument("--emit", action="store_true", help="push to Figma and score")
    args = parser.parse_args()

    out = Path(args.out or (ROOT / "output" / f"_arb{args.mode}_{args.tag}"))
    out.mkdir(parents=True, exist_ok=True)

    design, truth = _load(args.tag)
    started = time.time()
    report: dict = {"tag": args.tag, "mode": args.mode, "rounds": args.rounds}

    if args.mode == "B":
        vision = _vision_callable()
        if vision is None:
            print("no vision key; refusing to fake a B run", file=sys.stderr)
            return 2
        working = copy.deepcopy(design)
        work_dir = out / "draw"
        work_dir.mkdir(parents=True, exist_ok=True)

        def draw(elements):
            snapshot = dict(working)
            snapshot["elements"] = list(elements)
            path = _render(snapshot, work_dir, name="refine.png")
            return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)

        report["refine"] = arbiter.refine(
            working["elements"],
            truth,
            draw,
            propose=lambda orders, strips: vision(arbiter.round_prompt(orders), strips),
            propose_wireframe=lambda candidates, panels: vision(
                arbiter.wireframe_prompt(candidates), panels
            ),
            rounds=args.rounds,
        )
        design = working
    report["seconds"] = round(time.time() - started, 1)

    (out / "12_design.json").write_text(
        json.dumps(design, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    picture = Path(str(json.loads((ROOT / "output" / f"_phys_{args.tag}" / "pipeline" / "image_reference.json").read_text(encoding="utf-8"))["input"]["path"]))
    if not picture.is_absolute():
        picture = ROOT / picture
    (out / "00_screenshot.png").write_bytes(picture.read_bytes())

    if args.emit:
        emit_started = time.time()
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/figma_replay.py",
                "--out",
                str(out),
                "--no-roundtrip",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        report["emit_seconds"] = round(time.time() - emit_started, 1)
        report["emit_exit"] = proc.returncode
        tail = (proc.stdout or "") + (proc.stderr or "")
        report["emit_tail"] = tail.strip().splitlines()[-3:]
        render_path = out / "figma_render.png"
        if render_path.is_file():
            report["figma"] = _score(truth, render_path)
            report["frames"] = sum(
                1 for item in design.get("elements") or [] if item.get("layoutChildren")
            )

    (out / "ab_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
