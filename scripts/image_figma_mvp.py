"""Run the reproducible image-to-Figma MVP pipeline and acceptance."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.agents.precise_agent import PreciseAgent  # noqa: E402
from src.app.services.evidence.image_figma_acceptance import (  # noqa: E402
    build_image_acceptance_report,
    run_image_figma_evidence,
)
from src.app.services.evidence.region_quality import (  # noqa: E402
    evaluate_region_quality,
)
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.app.services.structure.image_contract import (  # noqa: E402
    inspect_image_reference,
)
from src.app.services.structure.fidelity.text_calibration import (  # noqa: E402
    calibrate_control_fonts,
)
from src.main import load_config  # noqa: E402


class ImageMVFigmaAdapter(FigmaBridgeAdapter):
    """Keep the bridge open and retain the first created frame ID."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.frame_id: str | None = None

    def create_frame(self, spec):
        node_id = super().create_frame(spec)
        if self.frame_id is None and node_id:
            self.frame_id = node_id
        return node_id

    def flush(self) -> None:
        pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the owned image-to-Figma MVP sample."
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--route",
        choices=("auto", "grounding", "cv"),
        default="auto",
    )
    parser.add_argument("--origin-x", type=float, default=22000)
    parser.add_argument("--origin-y", type=float, default=0)
    parser.add_argument("--readback-depth", type=int, default=8)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Stop after the reproducible image pipeline artifacts.",
    )
    parser.add_argument(
        "--reuse-prepared",
        action="store_true",
        help="Use an existing frozen pipeline directory instead of recollecting.",
    )
    return parser


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _optional_json(path: Path) -> dict | None:
    return _read_json(path) if path.is_file() else None


def _fidelity_regions(geometry: dict | None) -> list[dict]:
    if not isinstance(geometry, dict):
        return []
    regions: list[dict] = []
    seen_ids: set[str] = set()
    for item in geometry.get("items") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "") not in {"page", "container", "table"}:
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        if int(bbox[2]) * int(bbox[3]) < 100:
            continue
        role = str(item.get("role") or item.get("kind") or "region")
        region_id = role
        suffix = 2
        while region_id in seen_ids:
            region_id = f"{role}:{suffix}"
            suffix += 1
        seen_ids.add(region_id)
        regions.append(
            {
                "id": region_id,
                "role": role,
                "bbox": bbox,
            }
        )
    if not any(region["id"] == "page" for region in regions):
        size = geometry.get("image_size") or []
        if len(size) == 2:
            regions.insert(
                0,
                {
                    "id": "page",
                    "role": "page",
                    "bbox": [0, 0, int(size[0]), int(size[1])],
                },
            )
    return regions


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    image = args.image.resolve()
    truth = _read_json(args.truth)
    if not image.is_file():
        raise FileNotFoundError(image)
    reference = inspect_image_reference(image)
    expected_sha = str(truth.get("image_sha256") or "")
    if expected_sha and reference["input"]["sha256"] != expected_sha:
        raise ValueError("input image SHA-256 does not match the frozen truth manifest")
    expected_size = truth.get("image_size")
    if expected_size and reference["input"]["size"] != expected_size:
        raise ValueError("input image size does not match the frozen truth manifest")
    output = args.out.resolve()
    pipeline_output = output / "pipeline"
    output.mkdir(parents=True, exist_ok=True)

    required_prepared = (
        pipeline_output / "12_design.json",
        pipeline_output / "image_ir.json",
        pipeline_output / "manifest.json",
    )
    if args.reuse_prepared:
        missing = [path for path in required_prepared if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "prepared pipeline is incomplete: "
                + ", ".join(str(path) for path in missing)
            )
    else:
        config = replace(load_config(), output_dir=pipeline_output)
        PreciseAgent(config).run(
            image=str(image),
            route=args.route,
            tool="svg",
        )
        preview_svg = pipeline_output / "prototype.svg"
        preview_png = pipeline_output / "render.png"
        if preview_svg.is_file() and (
            not preview_png.is_file()
            or preview_svg.stat().st_mtime > preview_png.stat().st_mtime
        ):
            from src.app.utils.svg_raster import rasterize_svg

            rasterize_svg(preview_svg, preview_png, device_scale_factor=1)
    design = _read_json(pipeline_output / "12_design.json")
    image_ir = _read_json(pipeline_output / "image_ir.json")
    manifest = _read_json(pipeline_output / "manifest.json")
    ocr_supplement = _read_json(pipeline_output / "ocr_supplement.json")
    region_recovery = _read_json(pipeline_output / "image_region_recovery.json")
    fidelity = _optional_json(pipeline_output / "13_fidelity_report.json")
    repair_history = _optional_json(pipeline_output / "14_repair_history.json")
    geometry = _optional_json(pipeline_output / "10_geometry_manifest.json")

    prepared = {
        "status": "prepared",
        "sample_id": truth.get("sample_id"),
        "route": manifest.get("route"),
        "input_kind": manifest.get("input_kind"),
        "frame_design_elements": len(design.get("elements") or []),
        "image_candidates": image_ir.get("counts", {}).get("image_candidates"),
        "text_candidates": image_ir.get("counts", {}).get("text_candidates"),
        "ocr_supplement": {
            "status": ocr_supplement.get("status"),
            "languages": ocr_supplement.get("languages"),
            "added_count": ocr_supplement.get("added_count"),
        },
        "image_region_recovery": {
            "status": region_recovery.get("status"),
            "added_count": region_recovery.get("added_count"),
        },
        "grounding_fidelity": {
            "status": (fidelity or {}).get("status"),
            "scene_nodes": ((fidelity or {}).get("counts") or {}).get("scene_nodes"),
            "repair_status": (repair_history or {}).get("status"),
        },
        "pipeline_output": str(pipeline_output),
    }
    if args.prepare_only:
        _write_json(output / "prepared.json", prepared)
        print(json.dumps(prepared, ensure_ascii=True))
        return 0

    design.setdefault("canvas", {})
    design["canvas"]["x"] = float(args.origin_x)
    design["canvas"]["y"] = float(args.origin_y)
    _write_json(output / "figma_design.json", design)

    run_root = output / "figma"
    run_summary = run_image_figma_evidence(
        design,
        output_dir=run_root,
        sample_id=str(truth.get("sample_id") or ""),
        adapter_factory=ImageMVFigmaAdapter,
        readback_depth=max(1, args.readback_depth),
    )
    if run_summary.get("status") != "captured-figma-evidence":
        _write_json(output / "acceptance.json", run_summary)
        print(json.dumps(run_summary, ensure_ascii=True))
        return 2

    initial_readback = _read_json(run_root / "readback.json")
    calibrated_design, calibration_report = calibrate_control_fonts(
        design,
        initial_readback,
    )
    _write_json(output / "font_calibration.json", calibration_report)
    if calibration_report["adjusted_count"]:
        _write_json(output / "figma_design_initial.json", design)
        design = calibrated_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_calibrated"
        run_summary = run_image_figma_evidence(
            design,
            output_dir=run_root,
            sample_id=str(truth.get("sample_id") or ""),
            adapter_factory=ImageMVFigmaAdapter,
            readback_depth=max(1, args.readback_depth),
        )
        if run_summary.get("status") != "captured-figma-evidence":
            _write_json(output / "acceptance.json", run_summary)
            print(json.dumps(run_summary, ensure_ascii=True))
            return 2

    region_quality = None
    regions = _fidelity_regions(geometry)
    if regions:
        region_quality = evaluate_region_quality(
            image,
            run_root / "export.png",
            regions,
        )
        _write_json(output / "region_quality.json", region_quality)

    report = build_image_acceptance_report(
        design=design,
        truth=truth,
        readback_tree=_read_json(run_root / "readback.json"),
        reference_path=image,
        export_path=run_root / "export.png",
        text_probe=_read_json(run_root / "text_edit_probe.json"),
        asset_probe=_read_json(run_root / "asset_probe.json"),
        image_ir=image_ir,
        run_summary=run_summary,
        fidelity=fidelity,
        region_quality=region_quality,
        repair_history=repair_history,
    )
    report["pipeline"] = prepared
    report["artifacts"] = {
        "image_reference": "pipeline/image_reference.json",
        "image_ir": "pipeline/image_ir.json",
        "ocr_supplement": "pipeline/ocr_supplement.json",
        "image_region_recovery": "pipeline/image_region_recovery.json",
        "evidence_bundle": "pipeline/09_evidence_bundle.json",
        "content_inventory": "pipeline/10_content_inventory.json",
        "geometry_manifest": "pipeline/10_geometry_manifest.json",
        "scene_plan": "pipeline/11_scene_plan.json",
        "fidelity_report": "pipeline/13_fidelity_report.json",
        "repair_history": "pipeline/14_repair_history.json",
        "region_quality": "region_quality.json",
        "design": "figma_design.json",
        "figma_run": str((run_root / "summary.json").relative_to(output)),
        "readback": str((run_root / "readback.json").relative_to(output)),
        "export": str((run_root / "export.png").relative_to(output)),
        "font_calibration": "font_calibration.json",
        "acceptance": "acceptance.json",
    }
    _write_json(output / "acceptance.json", report)
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report.get("status") == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
