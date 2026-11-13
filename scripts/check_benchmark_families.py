# -*- coding: utf-8 -*-
"""Benchmark families gate: one command, all families, no regressions.

Each family under ``tests/fixtures/benchmark_families/<name>/`` holds:
  reference.png   frozen source screenshot (truth for pixels)
  truth.json      frozen truth manifest (sha/size/critical texts)
  gold_tree.json  frozen Figma Make gold node tree (answer key)
  family.json     metadata: gold frame id, scale-to-reference, pipeline run dir,
                  registered baselines (written by ``--register``)

Metrics per family:
  * within30 / mean / ink_mean  (pipeline export vs reference, project metric)
  * answer-key:
      - ink_ratio_median  PRIMARY size metric.  Rendered ink height / source
        ink height, both measured in the *same gold box*, so box geometry
        cancels and what remains is "how big does it look".
      - font_ratio_median DIAGNOSTIC only.  Pipeline fontSize / gold fontSize.
        When the two sides render with different families this quotient hides a
        font-metric difference of 1.5-2.4 %, which is why it no longer gates.
      - |dy| median, style mismatches
  * structure: nodes, depth, FRAME/VECTOR/TEXT, bitmap fills
  * critical text matched/required (from the run's acceptance.json)

Families whose gold geometry cannot support a size metric (too few measurable
pairs) declare ``size_metrics.evaluable: false`` in family.json and the gate
skips both size checks for them instead of scoring noise.

Gate (baselines present, no --register): exit 1 if any family regresses.
Register mode: writes current measurements into family.json baselines.

Usage:
  python scripts/check_benchmark_families.py                     # gate
  python scripts/check_benchmark_families.py --register          # set baselines
  python scripts/check_benchmark_families.py --family light-table
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.app.services.evidence.image_figma_acceptance import (  # noqa: E402
    visual_similarity_metrics,
)

BENCH = ROOT / "tests" / "fixtures" / "benchmark_families"
JOURNAL = ROOT / "output" / "_bridge_state" / "bridge-journal.jsonl"

# Gate tolerances: how much a metric may drift before it counts as regression.
WITHIN30_SLACK_PCT = 0.3
#: Primary size metric: |ink_ratio - 1| may drift this much before regression.
INK_RATIO_DRIFT_SLACK = 0.05
#: Fewer measurable pairs than this and the median is not a measurement.
INK_RATIO_MIN_PAIRS = 20
#: Diagnostic only (see the module docstring).  Kept so a *large* size blunder
#: still shows up in the report, but it no longer fails the gate.
FONT_RATIO_DRIFT_SLACK = 0.05
DY_MEDIAN_SLACK_PX = 3.0
BITMAP_SLACK = 2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize(text: str) -> str:
    return "".join(str(text or "").split()).casefold()


def _flatten_texts(tree: dict[str, Any], scale: float) -> list[dict[str, Any]]:
    """Flatten TEXT nodes; geometry AND font sizes are normalized to source
    pixel space via ``scale`` (gold frames may be built at logical scale)."""
    tree = dict(tree)
    tree["x"], tree["y"] = 0, 0
    records: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], ox: float = 0.0, oy: float = 0.0) -> None:
        x = ox + float(node.get("x") or 0)
        y = oy + float(node.get("y") or 0)
        if node.get("type") == "TEXT":
            runs = node.get("textRuns") or []
            font = (runs[0].get("fontName") if runs else node.get("fontName")) or {}
            size = node.get("fontSize") or (runs[0].get("fontSize") if runs else None)
            if isinstance(size, (int, float)):
                size = float(size) * scale
            records.append(
                {
                    "text": str(node.get("characters") or ""),
                    "key": _normalize(node.get("characters")),
                    "fontSize": size,
                    "style": font.get("style") or "",
                    "x": x * scale,
                    "y": y * scale,
                    "width": float(node.get("width") or 0) * scale,
                    "height": float(node.get("height") or 0) * scale,
                }
            )
        for child in node.get("children") or []:
            walk(child, x, y)

    walk(tree)
    return records


def _ink_ratio_metrics(
    pairs: list[dict[str, Any]], reference: Any, rendered: Any
) -> dict[str, Any]:
    """Rendered-vs-source ink height, both measured inside the gold box.

    Same window on both images means the box geometry cancels: whatever is left
    is how tall the glyph actually renders.  That is the closest observable to
    "how big does this text look", and unlike ``font_ratio`` it does not divide
    two *declared* sizes from possibly different font families.

    Boxes with fewer than 3 px of ink on either side are skipped -- at that size
    the integer ink height is quantisation noise, not a measurement.
    """
    from src.app.services.structure.fidelity.text_calibration import _ink_stats

    ratios: list[float] = []
    for pair in pairs:
        box = pair.get("bbox")
        if not box or float(box[2]) < 2 or float(box[3]) < 2:
            continue
        source = _ink_stats(reference, box)
        render = _ink_stats(rendered, box)
        if source is None or render is None:
            continue
        if source["height"] < 3 or render["height"] < 3:
            continue
        ratios.append(render["height"] / float(source["height"]))
    if not ratios:
        return {
            "ink_ratio_median": None,
            "ink_ratio_pairs": 0,
            "ink_ratio_within10pct": None,
        }
    ordered = sorted(ratios)
    within = sum(1 for value in ratios if abs(value - 1.0) <= 0.10) / len(ratios)
    return {
        "ink_ratio_median": round(ordered[len(ordered) // 2], 3),
        "ink_ratio_pairs": len(ratios),
        "ink_ratio_within10pct": round(within, 3),
    }


def _answer_key(
    gold_tree: dict[str, Any],
    pipe_tree: dict[str, Any],
    scale: float,
    reference: Any = None,
    rendered: Any = None,
) -> dict[str, Any]:
    gold = _flatten_texts(gold_tree, scale)
    pipe = _flatten_texts(pipe_tree, 1.0)
    used: set[int] = set()
    pairs: list[dict[str, Any]] = []
    for g in gold:
        candidates = [
            (i, p) for i, p in enumerate(pipe) if p["key"] == g["key"] and i not in used
        ]
        if not candidates:
            continue
        i, p = min(
            candidates,
            key=lambda c: abs(c[1]["x"] - g["x"]) + abs(c[1]["y"] - g["y"]),
        )
        used.add(i)
        fg = g["fontSize"] if isinstance(g["fontSize"], (int, float)) else None
        fp = p["fontSize"] if isinstance(p["fontSize"], (int, float)) else None
        pairs.append(
            {
                "text": g["text"][:24],
                "font_ratio": round(fp / fg, 3) if fg and fp else None,
                "dy": round(p["y"] - g["y"], 1),
                "bbox": [g["x"], g["y"], g.get("width") or 0, g.get("height") or 0],
                "style_match": bool(g["style"])
                and bool(p["style"])
                and g["style"] == p["style"],
            }
        )
    ratios = [p["font_ratio"] for p in pairs if p["font_ratio"]]
    dys = [abs(p["dy"]) for p in pairs]
    styles = [p for p in pairs if p["style_match"] is not None]

    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[len(ordered) // 2], 3)

    ink = (
        _ink_ratio_metrics(pairs, reference, rendered)
        if reference is not None and rendered is not None
        else {
            "ink_ratio_median": None,
            "ink_ratio_pairs": 0,
            "ink_ratio_within10pct": None,
        }
    )
    return {
        "matched": len(pairs),
        "gold_texts": len(gold),
        "pipe_texts": len(pipe),
        "font_ratio_median": _median(ratios),
        "dy_median": _median(dys),
        "style_mismatches": sum(1 for p in styles if not p["style_match"]),
        "style_compared": len(styles),
        **ink,
    }


def _structure(tree: dict[str, Any]) -> dict[str, Any]:
    types: Counter[str] = Counter()
    image_fills = 0
    max_depth = 0

    def walk(node: dict[str, Any], depth: int = 0) -> None:
        nonlocal max_depth, image_fills
        max_depth = max(max_depth, depth)
        types[str(node.get("type"))] += 1
        for fill in node.get("fills") or []:
            if fill.get("type") == "IMAGE":
                image_fills += 1
                break
        for child in node.get("children") or []:
            walk(child, depth + 1)

    walk(tree)
    return {
        "total_nodes": sum(types.values()),
        "max_depth": max_depth,
        "frame_count": types.get("FRAME", 0),
        "vector_count": types.get("VECTOR", 0),
        "text_count": types.get("TEXT", 0),
        "image_fill_count": image_fills,
    }


def _resolve_pipeline_artifacts(run_dir: Path) -> tuple[Path | None, Path | None]:
    """Prefer the readback/export referenced by acceptance.json, else latest stage."""
    acceptance = run_dir / "acceptance.json"
    if acceptance.is_file():
        artifacts = (_read_json(acceptance).get("artifacts") or {})
        readback = run_dir / str(artifacts.get("readback") or "")
        export = run_dir / str(artifacts.get("export") or "")
        if readback.is_file() and export.is_file():
            return readback, export
    stage_dirs = sorted(
        (d for d in run_dir.glob("figma*") if d.is_dir() and (d / "readback.json").is_file()),
        key=lambda d: d.stat().st_mtime,
    )
    if not stage_dirs:
        return None, None
    latest = stage_dirs[-1]
    return latest / "readback.json", latest / "export.png"


def _critical_from_acceptance(run_dir: Path) -> dict[str, Any] | None:
    acceptance = run_dir / "acceptance.json"
    if not acceptance.is_file():
        return None
    data = _read_json(acceptance)
    critical = data.get("critical_text") or {}
    if "matched_count" not in critical:
        return None
    return {
        "matched": critical.get("matched_count"),
        "required": critical.get("required_count"),
    }


def _size_metrics_scope(
    current: dict[str, Any], meta: dict[str, Any] | None
) -> tuple[bool, str | None]:
    """Decide whether this family's size numbers are measurements or noise.

    Two independent reasons to abstain:

    * the family itself declares ``size_metrics.evaluable: false`` -- light-table
      does, because its gold boxes land mostly on whitespace (ink_fraction 0.36)
      and only 11 of 91 texts yield a measurable pair;
    * too few measurable pairs for the median to mean anything, even if nobody
      remembered to declare it.
    """
    block = ((meta or {}).get("size_metrics") or {})
    if block.get("evaluable") is False:
        return False, str(block.get("reason") or "declared not evaluable")
    pairs = int(current.get("ink_ratio_pairs") or 0)
    if pairs < INK_RATIO_MIN_PAIRS:
        return False, f"only {pairs} measurable pairs < {INK_RATIO_MIN_PAIRS}"
    return True, None


def _gate(
    family: str,
    current: dict[str, Any],
    baseline: dict[str, Any],
    meta: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Return ``(regressions, notes)``; empty regressions = pass.

    ``font_ratio`` is deliberately *not* a regression source any more.  It
    divides two declared font sizes, so a family substitution (measured: 1.5-2.4 %
    on light-form, far more on dark-card-grid) shows up as a size error and
    chasing it makes the pixels worse -- both attempts are recorded in
    ``docs/v2_mentor/20261110_font_weight_evidence.md`` §5.2.  The metric is kept
    in the report as a diagnostic, and a large *drift* in it is still reported,
    just not failed.
    """
    # Flatten the current family dict so baseline and current share one shape.
    flat_current = {
        "within30_pct": (current.get("visual") or {}).get("within30_pct"),
        "font_ratio_median": (current.get("answer_key") or {}).get("font_ratio_median"),
        "ink_ratio_median": (current.get("answer_key") or {}).get("ink_ratio_median"),
        "ink_ratio_pairs": (current.get("answer_key") or {}).get("ink_ratio_pairs"),
        "dy_median": (current.get("answer_key") or {}).get("dy_median"),
        "critical": current.get("critical"),
        "structure": current.get("structure"),
    }
    current = flat_current
    regressions: list[str] = []
    notes: list[str] = []

    base_w = baseline.get("within30_pct")
    cur_w = current.get("within30_pct")
    if base_w is not None and cur_w is not None:
        if cur_w < float(base_w) - WITHIN30_SLACK_PCT:
            regressions.append(
                f"within30 {cur_w:.3f} < baseline {base_w:.3f} - {WITHIN30_SLACK_PCT}"
            )

    evaluable, reason = _size_metrics_scope(current, meta)
    if not evaluable:
        notes.append(f"size metrics not evaluated ({reason})")
    else:
        base_ink = baseline.get("ink_ratio_median")
        cur_ink = current.get("ink_ratio_median")
        if base_ink is not None and cur_ink is not None:
            base_dist = abs(float(base_ink) - 1.0)
            cur_dist = abs(float(cur_ink) - 1.0)
            # The slack is inclusive ("may drift this much"), but binary floats
            # make it exclusive at the boundary: abs(0.95 - 1.0) evaluates to
            # 0.050000000000000044, so a value sitting exactly on 0.95 would be
            # failed by a metric documented as tolerating 0.05.  The epsilon is
            # 1e-9 -- far below the 0.001 resolution of the reported ratios, so
            # it cannot hide a real regression.
            if cur_dist > base_dist + INK_RATIO_DRIFT_SLACK + 1e-9:
                regressions.append(
                    f"ink_ratio |{cur_ink}-1|={cur_dist:.3f} worse than baseline "
                    f"|{base_ink}-1|={base_dist:.3f} + {INK_RATIO_DRIFT_SLACK}"
                )
        elif current.get("ink_ratio_median") is not None:
            notes.append("ink_ratio measured but no baseline registered")

        base_ratio = baseline.get("font_ratio_median")
        cur_ratio = current.get("font_ratio_median")
        if base_ratio is not None and cur_ratio is not None:
            base_dist = abs(float(base_ratio) - 1.0)
            cur_dist = abs(float(cur_ratio) - 1.0)
            if cur_dist > base_dist + FONT_RATIO_DRIFT_SLACK:
                notes.append(
                    f"font_ratio drift |{cur_ratio}-1|={cur_dist:.3f} vs baseline "
                    f"{base_dist:.3f} (diagnostic, not gated)"
                )

    base_dy = baseline.get("dy_median")
    cur_dy = current.get("dy_median")
    if base_dy is not None and cur_dy is not None:
        if float(cur_dy) > float(base_dy) + DY_MEDIAN_SLACK_PX:
            regressions.append(
                f"dy_median {cur_dy} > baseline {base_dy} + {DY_MEDIAN_SLACK_PX}"
            )
    base_cr = baseline.get("critical") or {}
    cur_cr = current.get("critical") or {}
    if base_cr.get("matched") is not None and cur_cr.get("matched") is not None:
        if int(cur_cr["matched"]) < int(base_cr["matched"]):
            regressions.append(
                f"critical matched {cur_cr['matched']} < baseline {base_cr['matched']}"
            )
    base_img = (baseline.get("structure") or {}).get("image_fill_count")
    cur_img = (current.get("structure") or {}).get("image_fill_count")
    if base_img is not None and cur_img is not None:
        if int(cur_img) > int(base_img) + BITMAP_SLACK:
            regressions.append(
                f"image_fill_count {cur_img} > baseline {base_img} + {BITMAP_SLACK}"
            )
    base_depth = (baseline.get("structure") or {}).get("max_depth")
    cur_depth = (current.get("structure") or {}).get("max_depth")
    if base_depth is not None and cur_depth is not None:
        if int(cur_depth) < int(base_depth):
            regressions.append(f"max_depth {cur_depth} < baseline {base_depth}")
    return regressions, notes


def measure_family(
    family_dir: Path, measure_dir: Path | None = None
) -> dict[str, Any] | None:
    meta_path = family_dir / "family.json"
    if not meta_path.is_file():
        print(f"[skip] {family_dir.name}: family.json missing")
        return None
    meta = _read_json(meta_path)
    run_dir = measure_dir or ROOT / str(meta.get("pipeline_run") or "")
    if not run_dir.is_dir():
        print(f"[skip] {family_dir.name}: pipeline run dir missing: {run_dir}")
        return None
    readback, export = _resolve_pipeline_artifacts(run_dir)
    if not readback or not export:
        print(f"[skip] {family_dir.name}: no readback/export in {run_dir}")
        return None
    reference = family_dir / "reference.png"
    gold_tree = _read_json(family_dir / "gold_tree.json")
    pipe_tree = _read_json(readback)
    scale = float(meta.get("gold", {}).get("scale_to_reference") or 1.0)

    visual = visual_similarity_metrics(reference, export)
    # The ink metric needs both images; they are the same two the visual metric
    # already reads, so this adds one decode, not a new pipeline pass.
    import numpy as np
    from PIL import Image

    with Image.open(reference) as handle:
        reference_pixels = np.asarray(handle.convert("RGB"), dtype=np.int16)
    with Image.open(export) as handle:
        rendered_pixels = np.asarray(handle.convert("RGB"), dtype=np.int16)
    answer = _answer_key(
        gold_tree, pipe_tree, scale, reference_pixels, rendered_pixels
    )
    structure = _structure(pipe_tree)
    critical = _critical_from_acceptance(run_dir)
    return {
        "family": meta.get("family"),
        "pipeline_run": str(meta.get("pipeline_run")),
        "readback": str(readback.relative_to(ROOT)),
        "visual": {
            "within30_pct": round(float(visual.get("within30_pct") or 0.0), 4),
            "mean": round(float(visual.get("mean") or 0.0), 2),
            "ink_mean": round(float(visual.get("ink_mean") or 0.0), 2),
        },
        "answer_key": answer,
        "structure": structure,
        "critical": critical,
    }


def _rerun_family(family_dir: Path, policy: str) -> Path | None:
    """Perception-frozen rerun: copy the frozen pipeline, reuse-prepared.

    The VLM sample is part of the measured output only when perception is
    allowed to re-run; a cache miss there silently changes the baseline (the
    2026-11-09 FlexWeaver variance incident).  This mode freezes perception
    by reusing the registered run's pipeline directory and re-executing only
    perception-contract → Figma write → calibration → acceptance, so the
    gate responds to downstream code changes only.
    """
    import shutil
    import subprocess

    meta = _read_json(family_dir / "family.json")
    frozen_run = ROOT / str(meta.get("pipeline_run") or "")
    frozen_pipeline = frozen_run / "pipeline"
    required = ("12_design.json", "image_ir.json", "manifest.json")
    if not all((frozen_pipeline / name).is_file() for name in required):
        print(f"[skip-rerun] {family_dir.name}: frozen pipeline incomplete")
        return None
    out = ROOT / "output" / "_benchmark_families" / "rerun" / family_dir.name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(frozen_pipeline, out / "pipeline")
    env = dict(os.environ)
    env["GROUNDING_FIDELITY_MODE"] = "high"
    env["IMAGE_ENRICHMENT_MODE"] = "apply"
    family_index = hash(family_dir.name) % 64
    origin_y = 50000 + family_index * 2500
    command = [
        sys.executable,
        "scripts/image_figma_mvp.py",
        "--image",
        str(family_dir / "reference.png"),
        "--truth",
        str(family_dir / "truth.json"),
        "--out",
        str(out.relative_to(ROOT)),
        "--acceptance-policy",
        policy,
        "--reuse-prepared",
        "--origin-x",
        "26000",
        "--origin-y",
        str(origin_y),
    ]
    result = subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True, text=True
    )
    if result.returncode not in (0, 1, 2):
        print(
            f"[rerun-fail] {family_dir.name}: exit {result.returncode} "
            f"{result.stderr[-300:] if result.stderr else ''}"
        )
        return None
    # A ``blocked-environment`` acceptance is a *failed* run, not a low score:
    # its readback/export come from whichever stage happened to survive, so
    # measuring them compares a pre-calibration render against a post-calibration
    # baseline.  That produced a phantom "within30 94.28 < baseline 95.00"
    # regression on light-table on 2026-11-10.  Refuse the run instead.
    acceptance_path = out / "acceptance.json"
    if acceptance_path.is_file():
        acceptance = _read_json(acceptance_path)
        status = str(acceptance.get("status") or "")
        # Two different "blocked" states, and only one is a failed measurement:
        #   blocked-environment -> no usable artifacts; whatever readback/export
        #       exists is from an intermediate stage, so measuring it compares a
        #       pre-calibration render against a post-calibration baseline;
        #   blocked-fail -> artifacts are complete and comparable, a gate simply
        #       did not pass (native text is un-met on every family today).
        # Guard on the *evidence*, not on the status string.
        has_visual = (acceptance.get("visual") or {}).get("within30_pct") is not None
        has_critical = (
            acceptance.get("critical_text") or {}
        ).get("matched_count") is not None
        if status == "blocked-environment" or not (has_visual and has_critical):
            detail = str(acceptance.get("error") or status or "no acceptance")
            hint = ""
            if "invalid id" in detail:
                hint = (
                    "  (Figma plugin callback table is stale -- reload the plugin "
                    "in Figma, then re-run)"
                )
            print(f"[rerun-fail] {family_dir.name}: {detail[:160]}{hint}")
            return None
    print(f"[rerun ] {family_dir.name}: acceptance rebuilt under {out}")
    return out


def _dirty_entries() -> list[str]:
    """未提交的工作区改动（不含被 ignore 的 output/）。"""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _preflight(rerun: bool, allow_dirty: bool) -> int | None:
    """`--rerun` 前的两道闸：工作区必须干净，且不能有别人刚在写 bridge。

    脏工作区跑出来的数字对应「某个提交 + 当时的工作区」，不是任何一个可复现的状态。
    2026-11-13 15:38 是实例：另一个会话的未提交改动换掉了参考口径，content-review
    的 owner 从 14 掉到 12，而导出 sha 逐字节相同——`gitDirty` 在产物里写着 true，
    只是没人看它。

    bridge 那道只警告不拦：两个会话同时写同一份文档时，帧会叠在同一个 origin 上
    （`_rerun_family` 的 origin 是 family 名的哈希，天然确定），后跑的会把两边混在一起。
    """
    if not rerun:
        return None
    if not allow_dirty:
        dirty = _dirty_entries()
        if dirty:
            print(f"[refuse] 工作区有 {len(dirty)} 处未提交改动，--rerun 拒绝执行。")
            print("         脏工作区的结果不可复现；先提交，或确认后用 --allow-dirty。")
            for line in dirty[:5]:
                print(f"         {line}")
            return 2
    if JOURNAL.is_file():
        age = time.time() - JOURNAL.stat().st_mtime
        if age < 180:
            print(
                f"[warn ] bridge journal {age:.0f}s 前还在写——确认没有另一个会话"
                "在同一条 bridge 上跑，否则两边的帧会叠在同一坐标。"
            )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", action="append", help="restrict to family name(s)")
    parser.add_argument(
        "--register",
        action="store_true",
        help="write measured values into family.json baselines (first run)",
    )
    parser.add_argument(
        "--register-ink",
        action="store_true",
        help=(
            "add or refresh only the ink_ratio baseline; every other baseline "
            "entry is left untouched (use after a metric-scope change)"
        ),
    )
    parser.add_argument(
        "--out",
        default="output/_benchmark_families/report.json",
        help="report output path",
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help=(
            "perception-frozen rerun: reuse each family's frozen pipeline "
            "(--reuse-prepared) so the gate responds to downstream code only"
        ),
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="run --rerun on a dirty worktree (results are not reproducible)",
    )
    parser.add_argument(
        "--policy",
        default="2.1",
        help="acceptance policy for --rerun (default 2.1, the calibrated gate)",
    )
    args = parser.parse_args(argv)

    refusal = _preflight(args.rerun, args.allow_dirty)
    if refusal is not None:
        return refusal

    family_dirs = sorted(
        (d for d in BENCH.iterdir() if d.is_dir() and (d / "family.json").is_file()),
        key=lambda d: d.name,
    )
    if args.family:
        wanted = set(args.family)
        family_dirs = [d for d in family_dirs if d.name in wanted]
    if not family_dirs:
        print(f"[fail] no families found under {BENCH}")
        return 2

    print(f"[bench] {len(family_dirs)} family(ies): {[d.name for d in family_dirs]}")
    results: list[dict[str, Any]] = []
    all_regressions: dict[str, list[str]] = {}

    for family_dir in family_dirs:
        measure_dir: Path | None = None
        if args.rerun:
            rerun_out = _rerun_family(family_dir, args.policy)
            if rerun_out is None:
                all_regressions[family_dir.name] = ["rerun failed"]
                continue
            measure_dir = rerun_out
        current = measure_family(family_dir, measure_dir=measure_dir)
        if current is None:
            all_regressions[family_dir.name] = ["measurement unavailable"]
            continue
        meta = _read_json(family_dir / "family.json")
        baseline = meta.get("baselines")
        if args.register_ink and baseline:
            # Additive registration: the ink metric arrived after the other
            # baselines were set, and re-registering everything would silently
            # reset within30 / dy / structure to today's values.
            baseline["ink_ratio_median"] = current["answer_key"]["ink_ratio_median"]
            baseline["ink_ratio_pairs"] = current["answer_key"]["ink_ratio_pairs"]
            baseline["ink_ratio_registered_from"] = (
                "rerun" if args.rerun else current["pipeline_run"]
            )
            meta["baselines"] = baseline
            (family_dir / "family.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                f"[reg-ink] {family_dir.name}: ink_ratio_median="
                f"{current['answer_key']['ink_ratio_median']} "
                f"(n={current['answer_key']['ink_ratio_pairs']})"
            )
        if args.register or not baseline:
            meta["baselines"] = {
                "within30_pct": current["visual"]["within30_pct"],
                # Both size fields must be registered together: leaving
                # ink_ratio out here made a freshly registered family report
                # "ink_ratio measured but no baseline registered" and silently
                # disabled the primary size gate.
                "ink_ratio_median": current["answer_key"]["ink_ratio_median"],
                "ink_ratio_pairs": current["answer_key"]["ink_ratio_pairs"],
                "font_ratio_median": current["answer_key"]["font_ratio_median"],
                "dy_median": current["answer_key"]["dy_median"],
                "critical": current.get("critical"),
                "structure": current["structure"],
                "registered_from": current["pipeline_run"],
            }
            (family_dir / "family.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            current["gate"] = "registered"
            print(
                f"[reg ] {family_dir.name}: baselines written "
                f"(within30={current['visual']['within30_pct']}%)"
            )
        else:
            baseline = _read_json(family_dir / "family.json").get("baselines") or baseline
            regressions, notes = _gate(family_dir.name, current, baseline, meta)
            current["gate"] = "pass" if not regressions else "REGRESSION"
            current["gate_notes"] = notes
            if regressions:
                all_regressions[family_dir.name] = regressions
            print(
                f"[gate ] {family_dir.name}: {current['gate'].upper()}"
                + (f" -> {'; '.join(regressions)}" if regressions else "")
                + (f"  [{'; '.join(notes)}]" if notes else "")
            )
        results.append(current)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "schema_version": "benchmark-families-report/1.0",
                "mode": "register" if args.register else "gate",
                "families": results,
                "regressions": all_regressions,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n===== benchmark families report =====")
    for r in results:
        v = r["visual"]
        a = r["answer_key"]
        s = r["structure"]
        cr = r.get("critical") or {}
        ratio = a["font_ratio_median"]
        ink = a.get("ink_ratio_median")
        ink_txt = f"{ink}(n={a.get('ink_ratio_pairs')})" if ink is not None else "n/a"
        print(
            f"{r['family']:<16} gate={r['gate']:<11} within30={v['within30_pct']:.2f}%  "
            f"ink_ratio={ink_txt}  font_ratio={ratio if ratio is not None else 'n/a'} (diag)  "
            f"dy_med={a['dy_median']}  "
            f"style_mm={a['style_mismatches']}/{a['style_compared']}  "
            f"nodes={s['total_nodes']} depth={s['max_depth']} bitmap={s['image_fill_count']}  "
            f"critical={cr.get('matched')}/{cr.get('required')}"
        )
    print(f"[out  ] {out}")
    return 1 if all_regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
