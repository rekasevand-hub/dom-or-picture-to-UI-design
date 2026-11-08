"""Two-sample generalization guard for the image -> Figma pipeline.

Compares one calibrated (baseline) run against one holdout run using only
truth-independent signals: perception evidence coverage, systematic
coordinate-space drift and native-only pixel fidelity (raster underlays
excluded).  Run this after any change to grounding, enrichment, the fixed
canvas compiler or the calibration ladder.

Usage:
    python scripts/check_image_generalization.py \
        --baseline output/_grounding_manual_20261108_search_control_post \
        --holdout output/_image_figma_acctoken_models_20261108_rerun_full_high
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure.fidelity.perception_contract import (  # noqa: E402
    evaluate_native_fidelity,
    run_perception_contract,
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _reference_path(run: Path, argument: str | None) -> Path:
    if argument:
        candidate = Path(argument)
        return candidate if candidate.is_absolute() else _ROOT / candidate
    for name in ("input.png", "reference.png"):
        candidate = run / name
        if candidate.is_file():
            return candidate
    fixture = (
        _ROOT
        / "tests/fixtures/image_to_slice_benchmark_2026-11-02"
        / "IMG-FLEXWEAVER-ADMIN.png"
    )
    if fixture.is_file():
        return fixture
    raise FileNotFoundError(f"no reference image found for {run}")


def _export_path(run: Path) -> Path | None:
    candidates = sorted(run.glob("figma*/export.png"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _inspect(run: Path, reference_argument: str | None) -> dict[str, Any]:
    design = _read_json(run / "figma_design.json")
    reference = _reference_path(run, reference_argument)
    ocr_path = run / "pipeline/ocr_supplement.json"
    ocr = _read_json(ocr_path) if ocr_path.is_file() else None
    _repaired, report = run_perception_contract(
        design,
        reference,
        ocr_supplement=ocr,
        mode="report",
    )
    summary: dict[str, Any] = {
        "run": str(run),
        "reference": str(reference),
        "theme": report["reference"]["theme"],
        "size": report["reference"]["size"],
        "counts": report["counts"],
        "ratios": report["ratios"],
        "systematicCoordinateDrift": report["policy"][
            "systematicCoordinateDrift"
        ],
        "dominantTransform": report["policy"]["dominantTransform"],
    }
    export = _export_path(run)
    if export is not None:
        summary["nativeFidelity"] = evaluate_native_fidelity(
            design, reference, export
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--baseline-image")
    parser.add_argument("--holdout-image")
    parser.add_argument(
        "--max-baseline-defect-ratio",
        type=float,
        default=0.20,
        help="Baseline perception-defect ratio must stay below this value.",
    )
    parser.add_argument(
        "--max-holdout-unverified",
        type=int,
        default=0,
        help="Holdout must not contain unrecoverable text boxes.",
    )
    args = parser.parse_args(argv)

    baseline = _inspect(args.baseline.resolve(), args.baseline_image)
    holdout = _inspect(args.holdout.resolve(), args.holdout_image)
    result = {
        "schema_version": "image-generalization-guard/1.0",
        "baseline": baseline,
        "holdout": holdout,
        "checks": {},
    }
    checks = result["checks"]
    defect = baseline["ratios"]["perceptionDefectRatio"]
    checks["baseline_not_regressed"] = (
        defect <= args.max_baseline_defect_ratio
        and not baseline["systematicCoordinateDrift"]
    )
    checks["holdout_recoverable"] = (
        holdout["counts"]["unverified"] <= args.max_holdout_unverified
    )
    checks["drift_signal_present"] = (
        holdout["systematicCoordinateDrift"]
        or holdout["ratios"]["perceptionDefectRatio"] > defect
    )
    result["status"] = (
        "pass" if all(checks.values()) else "attention-required"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
