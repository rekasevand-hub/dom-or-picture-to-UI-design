"""Run the reproducible image-to-Figma MVP pipeline and acceptance."""

from __future__ import annotations

import argparse
import copy
import json
import os
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
    IMAGE_MVP_POLICY_V21,
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
from src.app.services.structure.router import (  # noqa: E402
    ROUTE_OMNI_CV,
    normalize_route,
)
from src.app.services.structure.image_contract import (  # noqa: E402
    inspect_image_reference,
)
from src.app.services.structure.fidelity.emission_contract import (  # noqa: E402
    audit_emission,
)
from src.app.services.structure.fidelity.calibration_profile import (  # noqa: E402
    build_calibration_residual_profile,
)
from src.app.services.structure.fidelity.calibration_strategies import (  # noqa: E402
    INK_ROUNDTRIP_GROUP,
    CalibrationRenderError,
    run_calibration_pipeline,
)
from src.app.services.structure.fidelity.perception_contract import (  # noqa: E402
    evaluate_native_fidelity,
    run_perception_contract,
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


AXURE_OUTPUT_SCHEMA_VERSION = "image-axure-output/1.0"


def _gate(
    *,
    dsn: dict,
    output: Path,
    tool: str,
    strict: bool,
    source_kind: str,
    reference: dict | None,
) -> dict | None:
    """design-ir/2.0 闸门：投影 + 契约校验 + 落盘 13_design_ir/13_degradations。"""
    from src.app.services.contracts.production_gate import (
        DesignIRGateError,
        gate_design_for_output,
    )

    try:
        return gate_design_for_output(
            dsn,
            target=tool,
            source_kind=source_kind,
            out_dir=output,
            reference=reference,
            strict=strict,
        )
    except DesignIRGateError as exc:
        _write_json(
            output / "ir_gate.json",
            {
                "status": "blocked-ir",
                "target": exc.target,
                "issues": exc.issues,
                "strict": True,
            },
        )
        print(json.dumps({"status": "blocked-ir", "issues": exc.issues}, ensure_ascii=True))
        raise SystemExit(3) from exc


def _emit_axure(
    *,
    design: dict,
    output: Path,
    sample_id: str,
    gate: dict | None,
    generate_twice: bool,
    strict: bool,
) -> int:
    """Axure RP8 发射：复用闸门的 IR 做路由，再用 evidence.py 只读回读自检。"""
    import hashlib

    from src.app.services.rendering.axure.evidence import (
        compare_rp_to_design,
        inspect_rp,
    )
    from src.app.services.rendering.axure_adapter import AxureRPAdapter
    from src.app.services.rendering.axure_route import plan_axure_route

    ir = _read_json(output / "13_design_ir.json") if (output / "13_design_ir.json").is_file() else None
    route = plan_axure_route(design, source_kind="image", ir=ir)
    _write_json(output / "axure_design.json", route["design"])
    _write_json(output / "design.ir.json", route["ir"])
    _write_json(
        output / "route.json",
        {key: value for key, value in route.items() if key not in ("design", "ir")},
    )

    artifact = output / "prototype.rp"
    _render_axure(route["design"], artifact)
    repeat = None
    if generate_twice:
        repeat = output / "prototype.repeat.rp"
        _render_axure(route["design"], repeat)
    inspection = inspect_rp(artifact)
    comparison = compare_rp_to_design(inspection, route["design"], route=route)
    repeat_sha = hashlib.sha256(repeat.read_bytes()).hexdigest() if repeat else None
    deterministic = not generate_twice or (
        repeat is not None and repeat.read_bytes() == artifact.read_bytes()
    )
    report = {
        "schema_version": AXURE_OUTPUT_SCHEMA_VERSION,
        "sample_id": sample_id,
        "document_id": route["document_id"],
        "source_kind": route["source_kind"],
        "gate": gate,
        "artifact": {
            "name": artifact.name,
            "size": artifact.stat().st_size,
            "sha256": inspection["artifact_sha256"],
        },
        "determinism": {
            "enabled": bool(generate_twice),
            "repeat_name": repeat.name if repeat else None,
            "repeat_sha256": repeat_sha,
            "identical": deterministic,
        },
        "self_check": inspection["self_check"],
        "integrity": inspection["integrity"],
        "comparison": comparison,
        "inspection": {
            "page_count": inspection["page_count"],
            "asset_count": inspection["asset_count"],
            "member_count": inspection["member_count"],
        },
        "projection": route["projection"],
        "degradations": route["degradations"],
        "acceptance_scope": route["projection"]["acceptance_scope"],
        "limitations": route["limitations"],
    }
    _write_json(output / "artifact_report.json", report)
    print(
        "[axure] pages=%s widgets=%s assets=%s self_check=%s integrity=%s "
        "comparison=%s deterministic=%s sha256=%s"
        % (
            inspection["page_count"],
            comparison["widget_count"],
            inspection["asset_count"],
            inspection["self_check"].get("ok"),
            inspection["integrity"].get("ok"),
            comparison["ok"],
            deterministic,
            inspection["artifact_sha256"][:16],
        ),
        flush=True,
    )
    ok = bool(
        inspection["self_check"].get("ok")
        and inspection["integrity"].get("ok")
        and comparison["ok"]
        and deterministic
    )
    if not ok and strict:
        print(json.dumps({"status": "blocked-axure-evidence"}, ensure_ascii=True))
        return 3
    return 0 if ok else 1


def _render_axure(design: dict, output_path: Path) -> None:
    from src.app.services.rendering.axure_adapter import AxureRPAdapter

    adapter = AxureRPAdapter(output_path)
    adapter.connect()
    adapter.render_design(design)
    adapter.disconnect()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the owned image-to-Figma MVP sample."
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--route",
        type=normalize_route,
        choices=("auto", ROUTE_OMNI_CV),
        default=None,
        help=(
            "auto=截图走 cv 并带兜底；omni-cv=纯 CV 物理感知（RapidOCR + "
            "OmniParser + 容器），失败即报错、不回退（封版路线）"
        ),
    )
    parser.add_argument(
        "--omni-cv",
        action="store_true",
        help=f"等价于 --route {ROUTE_OMNI_CV}；与冲突的 --route 同时出现会报错",
    )
    parser.add_argument("--origin-x", type=float, default=22000)
    parser.add_argument("--origin-y", type=float, default=0)
    parser.add_argument("--readback-depth", type=int, default=8)
    parser.add_argument(
        "--acceptance-policy",
        choices=("1.0", "2.0", "2.1"),
        default="1.0",
        help="Select the frozen raw-region gate or the split native-text/chrome gate.",
    )
    parser.add_argument(
        "--calibration-mode",
        choices=("legacy", "residual"),
        default="residual",
        help=(
            "residual (default) selects strategy groups from the measured "
            "native-text residual profile and recomputes the profile after each "
            "render. 'legacy' preserves the historical fifteen-stage order."
        ),
    )
    parser.add_argument(
        "--tool",
        choices=("figma", "axure"),
        default="figma",
        help=(
            "Output target. Both go through the design-ir/2.0 gate; axure also "
            "runs plan_axure_route + evidence.py readback instead of the Figma bridge."
        ),
    )
    parser.add_argument(
        "--strict-ir",
        action="store_true",
        help="Exit non-zero when the design violates the design-ir/2.0 contract.",
    )
    parser.add_argument(
        "--generate-twice",
        action="store_true",
        help="Axure only: render the .rp twice and require byte-identical output.",
    )
    parser.add_argument(
        "--ink-roundtrip",
        action="store_true",
        help=(
            "Re-run the post-export ink convergence pass (figma_ink_converged). "
            "Off by default: with RapidOCR's tight boxes the first export beat "
            "the converged one on all four pages measured, and the extra Figma "
            "round-trip is what used to fail with 'invalid callback id'."
        ),
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
        default="repair",
        help=(
            "Audit inventory->plan->design->gate-owner emission by contentRef. "
            "'repair' (default) additionally registers native owners that have "
            "no measurable ink evidence (diagnostic, never counted as passing). "
            "Use 'report' to keep the historical critical-text denominator."
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
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.omni_cv:
        if args.route and args.route != ROUTE_OMNI_CV:
            parser.error(
                f"--omni-cv 与 --route {args.route} 冲突："
                f"--omni-cv 等价于 --route {ROUTE_OMNI_CV}，二者只能写一个"
            )
        args.route = ROUTE_OMNI_CV
    # 不给 --route 时保持历史默认（auto → 截图走 cv 并带兜底），封版路线要显式选。
    args.route = args.route or "auto"
    if args.acceptance_policy == "2.0":
        acceptance_policy = IMAGE_MVP_POLICY_V2
    elif args.acceptance_policy == "2.1":
        acceptance_policy = IMAGE_MVP_POLICY_V21
    else:
        acceptance_policy = None
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
            _write_json(output / "figma_design_unrepaired.json", unrepaired_design)
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
            "repairApplied": bool(perception_report.get("repair", {}).get("applied")),
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

    # 生产主链的唯一出口：不论下游是 Figma 还是 Axure，先过 design-ir/2.0。
    gate = _gate(dsn=design, output=output, tool=args.tool, strict=args.strict_ir,
                 source_kind="image", reference=reference)
    if gate is not None and gate.get("status") == "not-gated":
        gate = None
    if args.tool == "axure":
        return _emit_axure(
            design=design,
            output=output,
            sample_id=str(truth.get("sample_id") or ""),
            gate=gate,
            generate_twice=args.generate_twice,
            strict=args.strict_ir,
        )

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
    regions = _fidelity_regions(geometry)
    original_design = copy.deepcopy(design)
    calibration_render_count = 0

    def _render_calibration_design(
        candidate_design: dict,
        render_suffix: str,
    ) -> tuple[Path, dict]:
        nonlocal calibration_render_count
        if calibration_render_count == 0:
            _write_json(output / "figma_design_initial.json", original_design)
        calibration_render_count += 1
        _write_json(output / "figma_design.json", candidate_design)
        calibration_root = output / render_suffix
        summary = run_image_figma_evidence(
            candidate_design,
            output_dir=calibration_root,
            sample_id=str(truth.get("sample_id") or ""),
            adapter_factory=ImageMVFigmaAdapter,
            readback_depth=max(1, args.readback_depth),
        )
        return calibration_root, summary

    def _calibration_profile(
        candidate_design: dict,
        candidate_run_root: Path,
        candidate_readback: dict,
    ) -> dict:
        export_path = candidate_run_root / "export.png"
        if not export_path.is_file():
            return {}
        return build_calibration_residual_profile(
            candidate_design,
            candidate_readback,
            str(image),
            str(export_path),
            regions,
        )

    try:
        calibration = run_calibration_pipeline(
            design=design,
            image=str(image),
            run_root=run_root,
            readback=initial_readback,
            ocr_supplement=ocr_supplement,
            render=_render_calibration_design,
            mode=args.calibration_mode,
            profile_builder=_calibration_profile,
            skip_groups=() if args.ink_roundtrip else (INK_ROUNDTRIP_GROUP,),
        )
    except CalibrationRenderError as exc:
        failure = {**exc.summary, "calibrationGroup": exc.group_name}
        _write_json(output / "acceptance.json", failure)
        print(json.dumps(failure, ensure_ascii=True))
        return 2
    design = calibration.design
    run_root = calibration.run_root
    if calibration_render_count:
        run_summary = _read_json(run_root / "summary.json")
    calibration_report = {
        **calibration.reports,
        "status": (
            "applied"
            if any(
                int(report.get("adjusted_count") or 0) > 0
                for report in calibration.reports.values()
            )
            else "not-needed"
        ),
        "adjusted_count": sum(
            int(report.get("adjusted_count") or 0)
            for report in calibration.reports.values()
        ),
        "mode": args.calibration_mode,
        "selected_groups": calibration.selected_groups,
        "skipped_groups": calibration.skipped_groups,
        "residual_profile": calibration.profile,
    }
    _write_json(output / "font_calibration.json", calibration_report)

    region_quality = None
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
        inventory = _optional_json(pipeline_output / "10_content_inventory.json")
        scene_plan = _optional_json(pipeline_output / "11_scene_plan.json")
        if inventory is None or scene_plan is None:
            # 发射审计是 grounding 路线的账本（content inventory -> scene plan ->
            # design）。物理感知链路不产出这两份清单，那是路线差异，不是缺件：
            # 报"不适用"，别把整趟跑挂在这里。
            emission_report = {
                "schema_version": "emission-contract/1.0",
                "status": "not-applicable",
                "mode": args.emission_contract,
                "reason": "this route emits no content inventory",
            }
        else:
            emission_report = audit_emission(
                inventory=inventory,
                scene_plan=scene_plan,
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
    # 一行说清楚这一趟到底跑了哪条感知链。--route auto 会自己挑，只有把命中的
    # 路线打出来，"以为是物理链路、其实跑了旧 grounding"才不会再发生。
    pipeline = report.get("pipeline") or {}
    visual = report.get("visual") or {}
    frames = sum(
        1 for item in design.get("elements") or [] if item.get("layoutChildren")
    )
    print(
        "[route] requested=%s hit=%s input=%s nodes=%s frames=%s elements=%s arbiter=%s"
        % (
            args.route,
            pipeline.get("route"),
            pipeline.get("input_kind"),
            (pipeline.get("grounding_fidelity") or {}).get("scene_nodes"),
            frames,
            pipeline.get("frame_design_elements"),
            "on" if int(os.environ.get("ARBITER_MAX_ROUNDS") or 1) > 1 else "off",
        ),
        flush=True,
    )
    print(
        "[score] figma within30=%s within15=%s mean=%s ink=%s over30=%s%%"
        % (
            round(float(visual.get("within30_pct") or 0), 2),
            "-",
            round(float(visual.get("mean") or 0), 3),
            round(float(visual.get("ink_mean") or 0), 2),
            round(float(visual.get("over30_pct") or 0), 2),
        ),
        flush=True,
    )
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
