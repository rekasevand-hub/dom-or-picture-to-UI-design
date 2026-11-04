"""Run frozen Grounding image-enrichment acceptance in all three modes."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.agents.precise_agent import PreciseAgent  # noqa: E402
from src.app.services.evidence.image_enrichment_quality import (  # noqa: E402
    evaluate_image_enrichment,
    write_image_enrichment_report,
)
from src.app.services.evidence.visual_scene_quality import (  # noqa: E402
    evaluate_visual_scene,
)
from src.app.services.structure.image_enrichment.contracts import (  # noqa: E402
    validate_image_truth,
)
from src.app.utils.svg_raster import rasterize_svg  # noqa: E402
from src.config.settings import load_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODES = ("off", "analyze", "apply")


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _truth_for_sample(
    sample_id: str,
    image_path: Path,
    fixtures_root: Path,
) -> dict[str, Any]:
    truth_path = fixtures_root / "truth" / f"{sample_id}.truth.json"
    truth = validate_image_truth(_json(truth_path))
    truth["reference_image_path"] = str(image_path)
    truth["truth_path"] = str(truth_path)
    return truth


def _blocked_run(
    *,
    sample_id: str,
    mode: str,
    reason: str,
    run_dir: Path,
    latency_ms: float = 0.0,
) -> dict[str, Any]:
    result = {
        "schema_version": "grounding-image-enrichment-quality/1.0",
        "sample_id": sample_id,
        "mode": mode,
        "status": "blocked-fail",
        "blockers": [reason],
        "metrics": {
            "generated_asset_count": 0,
            "calls": 0,
        },
    }
    _write_json(run_dir / "quality.json", result)
    return {
        **result,
        "run_dir": str(run_dir),
        "latency_ms": round(latency_ms, 3),
        "generated_asset_count": 0,
        "calls": 0,
    }


def _run_one(
    *,
    sample: dict[str, Any],
    sample_id: str,
    mode: str,
    truth: dict[str, Any],
    output_root: Path,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    image_path = ROOT / str(sample["path"])
    run_dir = output_root / "runs" / sample_id / mode
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    design_path = run_dir / "12_design.json"
    graph_path = run_dir / "10_pagegraph.json"
    if reuse_existing and not (design_path.is_file() and graph_path.is_file()):
        error_path = run_dir / "error.json"
        reason = "reuse-existing: missing PageGraph/DesignSpec artifacts"
        if error_path.is_file():
            try:
                reason = str(_json(error_path).get("error") or reason)
            except (OSError, ValueError):
                pass
        return _blocked_run(
            sample_id=sample_id,
            mode=mode,
            reason=reason,
            run_dir=run_dir,
        )
    try:
        if not (reuse_existing and design_path.is_file() and graph_path.is_file()):
            base = load_config()
            if not base.vision_api_key:
                return _blocked_run(
                    sample_id=sample_id,
                    mode=mode,
                    reason="provider-unavailable: VISION_API_KEY is not configured",
                    run_dir=run_dir,
                )
            cfg = dataclasses.replace(
                base,
                output_dir=run_dir,
                image_enrichment_mode=mode,
                text_align=False,
            )
            PreciseAgent(cfg).run(
                image=str(image_path),
                route="grounding",
                tool="svg",
            )
        if not design_path.is_file() or not graph_path.is_file():
            raise RuntimeError("pipeline did not write PageGraph/DesignSpec")
        design = _json(design_path)
        graph = _json(graph_path)
        svg_path = run_dir / "prototype.svg"
        render_path = run_dir / "render.png"
        if not svg_path.is_file():
            raise FileNotFoundError(svg_path)
        if not (reuse_existing and render_path.is_file()):
            rasterize_svg(
                svg_path,
                render_path,
                width=int(design["canvas"]["width"]),
                height=int(design["canvas"]["height"]),
                device_scale_factor=1,
            )
        readback_path = run_dir / "readback.json"
        readback = (
            _json(readback_path)
            if readback_path.is_file()
            else {
                "status": "unavailable",
                "reason": "No Figma readback was supplied for this acceptance run.",
            }
        )
        evaluation = evaluate_image_enrichment(
            truth,
            design,
            readback,
            render_path,
        )
        visual_scene = evaluate_visual_scene(
            design,
            render_path,
            image_path,
        )
        if visual_scene["status"] != "pass":
            evaluation["status"] = "blocked-fail"
            evaluation["blockers"] = [
                *evaluation["blockers"],
                *[f"visual:{blocker}" for blocker in visual_scene["blockers"]],
            ]
        evaluation["visual_scene"] = visual_scene
        tiling = (graph.get("provenance") or {}).get("tiling") or {}
        calls = len(tiling.get("tiles") or []) or 1
        generated_count = int(evaluation["metrics"].get("generated_asset_count") or 0)
        latency_ms = (time.perf_counter() - started) * 1000
        result = {
            **evaluation,
            "mode": mode,
            "run_dir": str(run_dir),
            "latency_ms": round(latency_ms, 3),
            "calls": calls,
            "generated_asset_count": generated_count,
            "artifacts": {
                "pagegraph": str(graph_path),
                "design": str(design_path),
                "render": str(render_path),
                "truth": str(truth["truth_path"]),
                **(
                    {"image_enrichment": str(run_dir / "image_enrichment.json")}
                    if (run_dir / "image_enrichment.json").is_file()
                    else {}
                ),
            },
        }
        _write_json(run_dir / "quality.json", result)
        return result
    except Exception as exc:  # noqa: BLE001 - failed evidence is retained
        latency_ms = (time.perf_counter() - started) * 1000
        blocked = _blocked_run(
            sample_id=sample_id,
            mode=mode,
            reason=f"{type(exc).__name__}: {exc}",
            run_dir=run_dir,
            latency_ms=latency_ms,
        )
        _write_json(
            run_dir / "error.json",
            {
                "sample_id": sample_id,
                "mode": mode,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        return blocked


def run_acceptance(
    manifest_path: Path,
    output: Path,
    *,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    output = Path(output)
    manifest = _json(manifest_path)
    fixtures_root = manifest_path.parent
    samples = [item for item in manifest.get("samples") or [] if isinstance(item, dict)]
    runs = []
    for sample in samples:
        sample_id = str(sample.get("id") or "")
        image_path = ROOT / str(sample["path"])
        truth = _truth_for_sample(sample_id, image_path, fixtures_root)
        for mode in MODES:
            runs.append(
                _run_one(
                    sample=sample,
                    sample_id=sample_id,
                    mode=mode,
                    truth=truth,
                    output_root=output,
                    reuse_existing=reuse_existing,
                )
            )
    _write_json(output / "runs.json", runs)
    report = write_image_enrichment_report(runs, output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args()
    report = run_acceptance(
        args.manifest,
        args.out,
        reuse_existing=args.reuse_existing,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "run_count": report["run_count"],
                "passed_count": report["passed_count"],
                "failed_count": report["failed_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
