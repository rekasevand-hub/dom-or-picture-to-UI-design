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
    IMAGE_MVP_POLICY_V2,
    build_image_acceptance_report,
    run_image_figma_evidence,
)
from src.app.services.evidence.native_text_quality import (  # noqa: E402
    build_native_text_quality,
)
from src.app.services.evidence.region_quality import (  # noqa: E402
    evaluate_region_quality,
)
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.app.services.structure.image_contract import (  # noqa: E402
    inspect_image_reference,
)
from src.app.services.structure.fidelity.emission_contract import (  # noqa: E402
    audit_emission,
)
from src.app.services.structure.fidelity.perception_contract import (  # noqa: E402
    evaluate_native_fidelity,
    run_perception_contract,
)
from src.app.services.structure.fidelity.text_calibration import (  # noqa: E402
    calibrate_control_fonts,
    calibrate_form_fonts_from_render,
    calibrate_form_positions_from_render,
    calibrate_form_text_shape_from_render,
    calibrate_form_text_weight_from_render,
    calibrate_form_text_positions,
    calibrate_low_contrast_placeholder_from_render,
    calibrate_search_control_from_render,
    calibrate_table_fonts_from_render,
    calibrate_table_letter_spacing_from_render,
    calibrate_table_positions_from_render,
    calibrate_toolbar_font_weight_from_render,
    calibrate_toolbar_letter_spacing_from_render,
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
        "--acceptance-policy",
        choices=("1.0", "2.0"),
        default="1.0",
        help="Select the frozen raw-region gate or the split native-text/chrome gate.",
    )
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
    parser.add_argument(
        "--perception-contract",
        choices=("off", "report", "adaptive"),
        default="adaptive",
        help=(
            "Validate text bboxes against reference pixels. 'adaptive' repairs "
            "only when the unverified ratio exceeds the drift threshold."
        ),
    )
    parser.add_argument(
        "--perception-drift-threshold",
        type=float,
        default=0.20,
        help="Perception-defect ratio that triggers an adaptive repair.",
    )
    parser.add_argument(
        "--strict-perception",
        action="store_true",
        help="Abort before writing to Figma when unverified text owners remain.",
    )
    parser.add_argument(
        "--emission-contract",
        choices=("off", "report", "repair"),
        default="report",
        help=(
            "Audit inventory->plan->design->gate-owner emission by contentRef. "
            "'repair' additionally registers native owners that have no "
            "measurable ink evidence (diagnostic, never counted as passing)."
        ),
    )
    parser.add_argument(
        "--strict-emission",
        action="store_true",
        help=(
            "Return a dedicated exit code when emission violations remain. "
            "Off by default; never changes the frozen formal acceptance."
        ),
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
    table_header_regions: list[dict] = []
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
        region = {
            "id": region_id,
            "role": role,
            "bbox": bbox,
        }
        regions.append(region)
        grid = item.get("grid")
        if (
            item.get("kind") == "table"
            and isinstance(grid, dict)
            and len(grid.get("x_boundaries") or []) >= 2
            and len(grid.get("y_boundaries") or []) >= 3
        ):
            x_boundaries = grid["x_boundaries"]
            y_boundaries = grid["y_boundaries"]
            table_header_regions.append(
                {
                    "id": "table-header",
                    "role": "table-header",
                    "bbox": [
                        int(x_boundaries[0]),
                        int(y_boundaries[0]),
                        int(x_boundaries[-1] - x_boundaries[0]),
                        int(y_boundaries[1] - y_boundaries[0]),
                    ],
                }
            )
    if table_header_regions:
        regions = [region for region in regions if region["id"] != "table-header"]
        regions.extend(table_header_regions)
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
    acceptance_policy = (
        IMAGE_MVP_POLICY_V2 if args.acceptance_policy == "2.0" else None
    )
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

    perception_report = None
    if args.perception_contract != "off":
        unrepaired_design = design
        design, perception_report = run_perception_contract(
            design,
            str(image),
            ocr_supplement=ocr_supplement,
            mode=args.perception_contract,
            drift_threshold=args.perception_drift_threshold,
        )
        if perception_report.get("repair", {}).get("applied"):
            _write_json(
                output / "figma_design_unrepaired.json", unrepaired_design
            )
        _write_json(output / "perception_coverage.json", perception_report)

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
    if perception_report is not None:
        prepared["perception_contract"] = {
            "status": perception_report["status"],
            "perceptionDefectRatio": perception_report["ratios"][
                "perceptionDefectRatio"
            ],
            "unverifiedRatio": perception_report["ratios"]["unverifiedRatio"],
            "systematicCoordinateDrift": perception_report["policy"][
                "systematicCoordinateDrift"
            ],
            "recovered": perception_report["counts"]["recovered"],
            "repairApplied": bool(
                perception_report.get("repair", {}).get("applied")
            ),
        }
    if args.prepare_only:
        _write_json(output / "prepared.json", prepared)
        print(json.dumps(prepared, ensure_ascii=True))
        return 0
    if (
        args.strict_perception
        and perception_report is not None
        and perception_report["counts"]["unverified"]
    ):
        aborted = {
            "status": "perception-contract-blocked",
            "reason": "unverified-text-owners-remain",
            "perception": perception_report,
        }
        _write_json(output / "acceptance.json", aborted)
        print(json.dumps(aborted, ensure_ascii=True))
        return 2

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
    calibrated_design, control_calibration = calibrate_control_fonts(
        design,
        initial_readback,
    )
    calibrated_design, table_font_calibration = calibrate_table_fonts_from_render(
        calibrated_design,
        str(image),
        str(run_root / "export.png"),
    )
    calibrated_design, form_text_calibration = calibrate_form_text_positions(
        calibrated_design,
        initial_readback,
    )
    font_stage_adjusted = (
        control_calibration["adjusted_count"]
        + table_font_calibration["adjusted_count"]
        + form_text_calibration["adjusted_count"]
    )
    wrote_initial_design = False
    if font_stage_adjusted:
        _write_json(output / "figma_design_initial.json", design)
        wrote_initial_design = True
        design = calibrated_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_font_calibrated"
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

    positioned_design, table_position_calibration = (
        calibrate_table_positions_from_render(
            design,
            str(image),
            str(run_root / "export.png"),
        )
    )
    if table_position_calibration["adjusted_count"]:
        if not wrote_initial_design:
            _write_json(output / "figma_design_initial.json", design)
            wrote_initial_design = True
        design = positioned_design
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

    table_spacing_design, table_spacing_calibration = (
        calibrate_table_letter_spacing_from_render(
            design,
            str(image),
            str(run_root / "export.png"),
        )
    )
    if table_spacing_calibration["adjusted_count"]:
        design = table_spacing_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_table_spacing"
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

    form_font_design, form_font_calibration = calibrate_form_fonts_from_render(
        design,
        str(image),
        str(run_root / "export.png"),
    )
    if form_font_calibration["adjusted_count"]:
        if not wrote_initial_design:
            _write_json(output / "figma_design_initial.json", design)
            wrote_initial_design = True
        design = form_font_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_form_font"
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

    form_weight_design, form_weight_calibration = (
        calibrate_form_text_weight_from_render(
            design,
            str(image),
            str(run_root / "export.png"),
        )
    )
    if form_weight_calibration["adjusted_count"]:
        design = form_weight_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_form_weight"
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

    form_shape_design, form_shape_calibration = (
        calibrate_form_text_shape_from_render(
            design,
            str(image),
            str(run_root / "export.png"),
        )
    )
    if form_shape_calibration["adjusted_count"]:
        design = form_shape_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_form_shape"
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

    form_position_design, form_position_calibration = (
        calibrate_form_positions_from_render(
            design,
            _read_json(run_root / "readback.json"),
            str(image),
            str(run_root / "export.png"),
        )
    )
    if form_position_calibration["adjusted_count"]:
        if not wrote_initial_design:
            _write_json(output / "figma_design_initial.json", design)
            wrote_initial_design = True
        design = form_position_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_form_calibrated"
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

    form_position_second_design, form_position_second_calibration = (
        calibrate_form_positions_from_render(
            design,
            _read_json(run_root / "readback.json"),
            str(image),
            str(run_root / "export.png"),
        )
    )
    if form_position_second_calibration["adjusted_count"]:
        design = form_position_second_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_form_calibrated_2"
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

    placeholder_design, placeholder_calibration = (
        calibrate_low_contrast_placeholder_from_render(
            design,
            str(image),
            str(run_root / "export.png"),
            ocr_supplement=ocr_supplement,
        )
    )
    if placeholder_calibration["adjusted_count"]:
        design = placeholder_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_placeholder"
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

    toolbar_spacing_design, toolbar_spacing_calibration = (
        calibrate_toolbar_letter_spacing_from_render(
            design,
            str(image),
            str(run_root / "export.png"),
        )
    )
    if toolbar_spacing_calibration["adjusted_count"]:
        design = toolbar_spacing_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_toolbar_calibrated"
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

    toolbar_weight_design, toolbar_weight_calibration = (
        calibrate_toolbar_font_weight_from_render(
            design,
            str(image),
            str(run_root / "export.png"),
        )
    )
    if toolbar_weight_calibration["adjusted_count"]:
        design = toolbar_weight_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_toolbar_weight"
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

    toolbar_respacing_design, toolbar_respacing_calibration = (
        calibrate_toolbar_letter_spacing_from_render(
            design,
            str(image),
            str(run_root / "export.png"),
        )
    )
    if toolbar_respacing_calibration["adjusted_count"]:
        design = toolbar_respacing_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_toolbar_calibrated_2"
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

    search_control_design, search_control_calibration = (
        calibrate_search_control_from_render(
            design,
            str(image),
            str(run_root / "export.png"),
        )
    )
    if search_control_calibration["adjusted_count"]:
        design = search_control_design
        _write_json(output / "figma_design.json", design)
        run_root = output / "figma_search_control"
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

    calibration_report = {
        **control_calibration,
        "table_fonts": table_font_calibration,
        "table_positions": table_position_calibration,
        "table_letter_spacing": table_spacing_calibration,
        "form_text_positions": form_text_calibration,
        "form_fonts_post": form_font_calibration,
        "form_text_weight": form_weight_calibration,
        "form_text_shape": form_shape_calibration,
        "low_contrast_placeholder": placeholder_calibration,
        "form_positions_post": form_position_calibration,
        "form_positions_post_2": form_position_second_calibration,
        "toolbar_letter_spacing": toolbar_spacing_calibration,
        "toolbar_font_weight": toolbar_weight_calibration,
        "toolbar_letter_spacing_2": toolbar_respacing_calibration,
        "search_control": search_control_calibration,
        "adjusted_count": (
            control_calibration["adjusted_count"]
            + table_font_calibration["adjusted_count"]
            + table_position_calibration["adjusted_count"]
            + table_spacing_calibration["adjusted_count"]
            + form_text_calibration["adjusted_count"]
            + form_font_calibration["adjusted_count"]
            + form_weight_calibration["adjusted_count"]
            + form_shape_calibration["adjusted_count"]
            + placeholder_calibration["adjusted_count"]
            + form_position_calibration["adjusted_count"]
            + form_position_second_calibration["adjusted_count"]
            + toolbar_spacing_calibration["adjusted_count"]
            + toolbar_weight_calibration["adjusted_count"]
            + toolbar_respacing_calibration["adjusted_count"]
            + search_control_calibration["adjusted_count"]
        ),
        "status": (
            "applied"
            if control_calibration["adjusted_count"]
            or table_font_calibration["adjusted_count"]
            or table_position_calibration["adjusted_count"]
            or table_spacing_calibration["adjusted_count"]
            or form_text_calibration["adjusted_count"]
            or form_font_calibration["adjusted_count"]
            or form_weight_calibration["adjusted_count"]
            or form_shape_calibration["adjusted_count"]
            or placeholder_calibration["adjusted_count"]
            or form_position_calibration["adjusted_count"]
            or form_position_second_calibration["adjusted_count"]
            or toolbar_spacing_calibration["adjusted_count"]
            or toolbar_weight_calibration["adjusted_count"]
            or toolbar_respacing_calibration["adjusted_count"]
            or search_control_calibration["adjusted_count"]
            else "not-needed"
        ),
    }
    _write_json(output / "font_calibration.json", calibration_report)

    region_quality = None
    regions = _fidelity_regions(geometry)
    if regions:
        region_quality = evaluate_region_quality(
            image,
            run_root / "export.png",
            regions,
        )
        _write_json(output / "region_quality.json", region_quality)
    native_text_quality = build_native_text_quality(
        design,
        _read_json(run_root / "readback.json"),
        str(image),
        str(run_root / "export.png"),
        regions,
        gate_policy=acceptance_policy,
        critical_texts=(
            [
                str(value)
                for value in truth.get("critical_texts") or []
                if str(value).strip()
            ]
            if acceptance_policy is not None
            else None
        ),
        register_unmeasured_owners=(args.emission_contract == "repair"),
    )
    _write_json(output / "native_text_quality.json", native_text_quality)

    emission_report = None
    if args.emission_contract != "off":
        emission_report = audit_emission(
            inventory=_read_json(pipeline_output / "10_content_inventory.json"),
            scene_plan=_read_json(pipeline_output / "11_scene_plan.json"),
            design=design,
            quality=native_text_quality,
        )
        emission_report["mode"] = args.emission_contract
        emission_report["registrationRepairApplied"] = (
            args.emission_contract == "repair"
        )
        _write_json(output / "emission_contract.json", emission_report)

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
        native_text_quality=native_text_quality,
        policy=acceptance_policy,
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
        "native_text_quality": "native_text_quality.json",
        "design": "figma_design.json",
        "figma_run": str((run_root / "summary.json").relative_to(output)),
        "readback": str((run_root / "readback.json").relative_to(output)),
        "export": str((run_root / "export.png").relative_to(output)),
        "font_calibration": "font_calibration.json",
        "perception_coverage": "perception_coverage.json",
        "emission_contract": "emission_contract.json",
        "acceptance": "acceptance.json",
    }
    if perception_report is not None:
        export_path = run_root / "export.png"
        if export_path.is_file():
            perception_report["nativeFidelity"] = evaluate_native_fidelity(
                design,
                str(image),
                str(export_path),
            )
            _write_json(output / "perception_coverage.json", perception_report)
    _write_json(output / "acceptance.json", report)
    print(json.dumps(report, ensure_ascii=True))
    if (
        args.strict_emission
        and emission_report is not None
        and emission_report.get("status") != "pass"
    ):
        return 3
    return 0 if report.get("status") == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
