"""Prepare and run the frozen image Grounding/CV/hybrid strategy benchmark."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence.image_figma_acceptance import (  # noqa: E402
    build_image_acceptance_report,
    run_image_figma_evidence,
)
from src.app.services.evidence.image_strategy_benchmark import (  # noqa: E402
    REQUIRED_STRATEGIES,
    build_strategy_comparison,
    build_strategy_row,
    describe_cv_execution,
    describe_grounding_execution,
    plan_strategy_attempts,
    validate_benchmark_manifest,
)
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.app.services.structure.graph import (  # noqa: E402
    assign_ids,
    assign_parent_depth,
)
from src.app.services.structure.image_contract import (  # noqa: E402
    build_image_design,
    build_image_ir,
    inspect_image_reference,
)
from src.app.services.structure.image_strategy import (  # noqa: E402
    merge_hybrid_graph,
)
from src.app.services.structure.providers.base import ProviderContext  # noqa: E402
from src.app.services.structure.providers.cv import CVProvider  # noqa: E402
from src.app.services.structure.providers.grounding import (  # noqa: E402
    GroundingProvider,
)
from src.main import load_config  # noqa: E402
from src.app.utils.image_utils import load_image  # noqa: E402


class BenchmarkFigmaAdapter(FigmaBridgeAdapter):
    """Keep one bridge connection and retain the first frame ID."""

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
        description="Run the frozen image strategy benchmark."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/fixtures/image_strategy_benchmark/manifest.json"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output/_image_cv_hybrid_benchmark_2026-10-26"),
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=REQUIRED_STRATEGIES,
        default=list(REQUIRED_STRATEGIES),
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Prepare provider graphs, designs and IR without Figma writes.",
    )
    parser.add_argument(
        "--reuse-prepared",
        action="store_true",
        help="Reuse prepared strategy artifacts for real Figma writes.",
    )
    parser.add_argument(
        "--run-figma",
        action="store_true",
        help="Write, read back, export and probe prepared designs in real Figma.",
    )
    parser.add_argument(
        "--compare-only",
        action="store_true",
        help="Rebuild strategy rows and comparison from retained Figma artifacts.",
    )
    parser.add_argument(
        "--origin-x",
        type=float,
        default=24000,
        help="X origin of the first benchmark frame in the Figma document.",
    )
    parser.add_argument("--origin-y", type=float, default=0)
    parser.add_argument("--frame-spacing", type=float, default=1400)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    manifest_path = args.manifest.resolve()
    manifest = validate_benchmark_manifest(
        _read_json(manifest_path),
        root=_ROOT,
    )
    sample = manifest["samples"][0]
    truth_path = _ROOT / str(sample["truth"])
    image_path = _ROOT / str(sample["image"])
    truth = _read_json(truth_path)
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "manifest.snapshot.json", manifest)
    if args.compare_only:
        comparison = rebuild_comparison(output, manifest)
        print(json.dumps(comparison["decision"], ensure_ascii=False, sort_keys=True))
        return 0

    config = replace(load_config(), output_dir=output / "_provider_output")
    grounding_available = bool(config.vision_api_key)
    shared_grounding_graph = None
    shared_grounding_runtime = None
    requires_shared_grounding = any(
        strategy in {"grounding-only", "grounding-cv-hybrid"}
        for strategy in args.strategies
    )
    if requires_shared_grounding and not args.reuse_prepared:
        shared_grounding_graph, shared_grounding_runtime = (
            load_or_prepare_shared_grounding(
                sample=sample,
                image_path=image_path,
                output_dir=output / "shared",
                config=config,
            )
        )
    shared_cv_graph = None
    shared_cv_runtime = None
    requires_shared_cv = any(
        strategy in {"cv-fallback", "grounding-cv-hybrid"}
        for strategy in args.strategies
    )
    if requires_shared_cv and not args.reuse_prepared:
        shared_cv_graph, shared_cv_runtime = load_or_prepare_shared_cv(
            sample=sample,
            image_path=image_path,
            output_dir=output / "shared",
            config=config,
        )
    summary: dict[str, Any] = {
        "schema_version": "image-strategy-benchmark-run/1.0",
        "corpus_id": manifest["corpus_id"],
        "sample_id": sample["sample_id"],
        "shared_grounding": shared_grounding_runtime,
        "shared_cv": shared_cv_runtime,
        "prepared": {},
        "figma": {},
    }
    for strategy in args.strategies:
        strategy_dir = output / "strategies" / strategy
        if args.reuse_prepared:
            _require_prepared(strategy_dir)
        else:
            try:
                prepared = prepare_strategy(
                    strategy=strategy,
                    sample=sample,
                    image_path=image_path,
                    truth=truth,
                    output_dir=strategy_dir,
                    config=config,
                    grounding_available=grounding_available,
                    shared_grounding_graph=shared_grounding_graph,
                    shared_grounding_runtime=shared_grounding_runtime,
                    shared_cv_graph=shared_cv_graph,
                    shared_cv_runtime=shared_cv_runtime,
                )
                summary["prepared"][strategy] = {
                    "status": prepared["status"],
                    "seconds": prepared["runtime"]["wall_time_seconds"],
                    "hybrid": prepared.get("hybrid_report"),
                }
            except Exception as exc:  # noqa: BLE001 - failures are benchmark evidence
                prepared = {
                    "status": "blocked-environment",
                    "benchmark_strategy": strategy,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                _write_json(strategy_dir / "strategy.json", prepared)
                summary["prepared"][strategy] = prepared
                if args.prepare_only:
                    continue
                raise
        if args.prepare_only:
            continue
        if not args.run_figma:
            continue
        index = args.strategies.index(strategy)
        origin_x = float(args.origin_x) + index * float(args.frame_spacing)
        try:
            acceptance, runtime = run_figma_strategy(
                strategy=strategy,
                strategy_dir=strategy_dir,
                sample=sample,
                truth=truth,
                image_path=image_path,
                output_dir=strategy_dir / "figma",
                origin_x=origin_x,
                origin_y=float(args.origin_y),
                readback_depth=int(manifest["environment"].get("readback_depth") or 8),
            )
            summary["figma"][strategy] = {
                "status": acceptance.get("status"),
                "frame_id": acceptance.get("frame_id"),
                "blockers": acceptance.get("blockers"),
            }
            _write_json(
                strategy_dir / "runtime.json",
                runtime,
            )
        except Exception as exc:  # noqa: BLE001 - environment evidence remains visible
            summary["figma"][strategy] = {
                "status": "blocked-environment",
                "error": f"{type(exc).__name__}: {exc}",
            }
            if bool(manifest["decision_policy"].get("adopt_only_if_all_gates_pass")):
                _write_json(output / "run_summary.json", summary)
                raise

    if args.run_figma:
        rows = []
        for strategy in REQUIRED_STRATEGIES:
            row_path = output / "strategies" / strategy / "benchmark_row.json"
            if not row_path.is_file():
                summary["comparison_status"] = "blocked-missing-strategy-row"
                break
            rows.append(_read_json(row_path))
        else:
            comparison = build_strategy_comparison(
                rows,
                manifest["thresholds"],
                corpus_id=manifest["corpus_id"],
            )
            _write_json(output / "comparison.json", comparison)
            summary["comparison_status"] = comparison["decision"]["decision"]

    _write_json(output / "run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return (
        0
        if args.prepare_only
        else (
            0
            if summary.get("comparison_status") in {"adopt-hybrid", "reject-hybrid"}
            else 2
        )
    )


def prepare_strategy(
    *,
    strategy: str,
    sample: dict[str, Any],
    image_path: Path,
    truth: dict[str, Any],
    output_dir: Path,
    config,
    grounding_available: bool,
    shared_grounding_graph: dict[str, Any] | None = None,
    shared_grounding_runtime: dict[str, Any] | None = None,
    shared_cv_graph: dict[str, Any] | None = None,
    shared_cv_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    strategy_grounding_available = (
        False if strategy == "cv-fallback" else grounding_available
    )
    plan = plan_strategy_attempts(
        strategy,
        grounding_available=strategy_grounding_available,
    )
    frame = load_image(str(image_path))
    height, width = frame.shape[:2]
    context = ProviderContext(
        image_path=str(image_path),
        image_w=int(width),
        image_h=int(height),
        route="",
        output_dir=str(output_dir),
    )
    hybrid_report = None
    if strategy == "grounding-only":
        graph = (
            copy.deepcopy(shared_grounding_graph)
            if shared_grounding_graph is not None
            else GroundingProvider(config).run(context)
        )
    elif strategy == "cv-fallback":
        cv_config = replace(config, vision_api_key=None)
        graph = (
            copy.deepcopy(shared_cv_graph)
            if shared_cv_graph is not None
            else CVProvider(cv_config).run(context)
        )
    elif strategy == "grounding-cv-hybrid":
        grounding_graph = (
            copy.deepcopy(shared_grounding_graph)
            if shared_grounding_graph is not None
            else GroundingProvider(config).run(context)
        )
        cv_graph = (
            copy.deepcopy(shared_cv_graph)
            if shared_cv_graph is not None
            else CVProvider(config).run(context)
        )
        graph, hybrid_report = merge_hybrid_graph(grounding_graph, cv_graph)
    else:
        raise ValueError(f"unknown strategy: {strategy}")

    assign_ids(graph)
    assign_parent_depth(graph)
    graph["provenance"]["requested_route"] = plan["requested"]
    graph["provenance"]["attempts"] = plan["attempts"]
    graph["provenance"]["hidden_route_switch"] = plan["hidden_route_switch"]
    graph["provenance"]["all_candidate_sources"] = True
    graph["provenance"]["ambiguity_retained"] = True
    skipped = list((hybrid_report or {}).get("skipped") or [])
    duplicate_count = sum(
        str(item.get("reason") or "").startswith("duplicate-")
        for item in skipped
        if isinstance(item, dict)
    )
    graph["provenance"]["ambiguity_count"] = len(skipped) - duplicate_count
    graph["provenance"]["duplicate_suppressed_count"] = duplicate_count
    graph["provenance"]["benchmark_strategy"] = strategy
    reference = inspect_image_reference(
        image_path,
        reference_id=str(sample["sample_id"]),
    )
    design = build_image_design(
        graph,
        reference,
        sample_id=str(truth.get("sample_id") or sample["sample_id"]),
    )
    design["name"] = f"Image benchmark {strategy} {sample['sample_id']}"
    image_ir = build_image_ir(graph, design, reference, plan)
    elapsed = time.perf_counter() - started
    execution = describe_grounding_execution(
        strategy,
        shared_graph_available=shared_grounding_graph is not None,
    )
    cv_execution = describe_cv_execution(
        strategy,
        shared_graph_available=shared_cv_graph is not None,
    )
    shared_seconds = float(
        (shared_grounding_runtime or {}).get("wall_time_seconds") or 0.0
    )
    shared_cv_seconds = float((shared_cv_runtime or {}).get("wall_time_seconds") or 0.0)
    logical_wall_time = (
        elapsed
        + (
            shared_seconds
            if shared_grounding_graph is not None
            and strategy in {"grounding-only", "grounding-cv-hybrid"}
            else 0.0
        )
        + (
            shared_cv_seconds
            if shared_cv_graph is not None
            and strategy in {"cv-fallback", "grounding-cv-hybrid"}
            else 0.0
        )
    )
    runtime = {
        "wall_time_seconds": round(logical_wall_time, 3),
        "grounding_vlm_calls": execution["logical_grounding_calls"],
        "provider_grounding_calls": execution["provider_grounding_calls"],
        "grounding_replay": execution["grounding_replay"],
        "shared_grounding_seconds": shared_seconds,
        "cv_executions": cv_execution["logical_cv_executions"],
        "provider_cv_executions": cv_execution["provider_cv_executions"],
        "cv_replay": cv_execution["cv_replay"],
        "shared_cv_seconds": shared_cv_seconds,
        "cost_telemetry_status": "bounded-by-request-count",
    }
    prepared = {
        "schema_version": "image-strategy-prepared/1.0",
        "status": "prepared",
        "benchmark_strategy": strategy,
        "sample_id": sample["sample_id"],
        "strategy": plan,
        "runtime": runtime,
        "hybrid_report": hybrid_report,
        "artifacts": {
            "pagegraph": "pagegraph.json",
            "design": "design.json",
            "image_ir": "image_ir.json",
        },
    }
    _write_json(output_dir / "pagegraph.json", graph)
    _write_json(output_dir / "design.json", design)
    _write_json(output_dir / "image_ir.json", image_ir)
    _write_json(output_dir / "strategy.json", prepared)
    if hybrid_report is not None:
        _write_json(output_dir / "hybrid_report.json", hybrid_report)
    return prepared


def load_or_prepare_shared_grounding(
    *,
    sample: dict[str, Any],
    image_path: Path,
    output_dir: Path,
    config,
) -> tuple[dict[str, Any], dict[str, Any]]:
    graph_path = output_dir / "grounding_graph.json"
    meta_path = output_dir / "grounding_runtime.json"
    if graph_path.is_file() and meta_path.is_file():
        return _read_json(graph_path), _read_json(meta_path)

    started = time.perf_counter()
    frame = load_image(str(image_path))
    height, width = frame.shape[:2]
    context = ProviderContext(
        image_path=str(image_path),
        image_w=int(width),
        image_h=int(height),
        route="",
        output_dir=str(output_dir),
    )
    graph = GroundingProvider(config).run(context)
    assign_ids(graph)
    assign_parent_depth(graph)
    graph["provenance"]["requested_route"] = "auto"
    graph["provenance"]["attempts"] = [{"strategy": "grounding", "status": "selected"}]
    graph["provenance"]["benchmark_shared_input"] = True
    elapsed = time.perf_counter() - started
    runtime = {
        "schema_version": "image-shared-grounding-runtime/1.0",
        "status": "captured",
        "sample_id": sample["sample_id"],
        "image_sha256": sample["image_sha256"],
        "source": "provider",
        "wall_time_seconds": round(elapsed, 3),
        "logical_grounding_calls": 1,
        "provider_grounding_calls": 1,
    }
    _write_json(graph_path, graph)
    _write_json(meta_path, runtime)
    return graph, runtime


def load_or_prepare_shared_cv(
    *,
    sample: dict[str, Any],
    image_path: Path,
    output_dir: Path,
    config,
) -> tuple[dict[str, Any], dict[str, Any]]:
    graph_path = output_dir / "cv_graph.json"
    meta_path = output_dir / "cv_runtime.json"
    if graph_path.is_file() and meta_path.is_file():
        return _read_json(graph_path), _read_json(meta_path)

    started = time.perf_counter()
    frame = load_image(str(image_path))
    height, width = frame.shape[:2]
    context = ProviderContext(
        image_path=str(image_path),
        image_w=int(width),
        image_h=int(height),
        route="",
        output_dir=str(output_dir),
    )
    cv_config = replace(config, vision_api_key=None)
    graph = CVProvider(cv_config).run(context)
    assign_ids(graph)
    assign_parent_depth(graph)
    graph["provenance"]["requested_route"] = "auto"
    graph["provenance"]["attempts"] = [
        {
            "strategy": "grounding",
            "status": "unavailable",
            "reason": "grounding-config-missing",
        },
        {"strategy": "cv", "status": "selected"},
    ]
    graph["provenance"]["benchmark_shared_input"] = True
    elapsed = time.perf_counter() - started
    runtime = {
        "schema_version": "image-shared-cv-runtime/1.0",
        "status": "captured",
        "sample_id": sample["sample_id"],
        "image_sha256": sample["image_sha256"],
        "source": "provider",
        "wall_time_seconds": round(elapsed, 3),
        "logical_cv_executions": 1,
        "provider_cv_executions": 1,
    }
    _write_json(graph_path, graph)
    _write_json(meta_path, runtime)
    return graph, runtime


def run_figma_strategy(
    *,
    strategy: str,
    strategy_dir: Path,
    sample: dict[str, Any],
    truth: dict[str, Any],
    image_path: Path,
    output_dir: Path,
    origin_x: float,
    origin_y: float,
    readback_depth: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    strategy_doc = _read_json(strategy_dir / "strategy.json")
    design = _read_json(strategy_dir / "design.json")
    image_ir = _read_json(strategy_dir / "image_ir.json")
    pagegraph = _read_json(strategy_dir / "pagegraph.json")
    design.setdefault("canvas", {})
    design["canvas"]["x"] = origin_x
    design["canvas"]["y"] = origin_y
    figma_design_path = strategy_dir / "figma_design.json"
    _write_json(figma_design_path, design)

    figma_started = time.perf_counter()
    run_summary = run_image_figma_evidence(
        design,
        output_dir=output_dir,
        sample_id=str(sample["sample_id"]),
        adapter_factory=BenchmarkFigmaAdapter,
        readback_depth=readback_depth,
    )
    if run_summary.get("status") != "captured-figma-evidence":
        _write_json(strategy_dir / "acceptance.json", run_summary)
        raise RuntimeError(f"real Figma evidence blocked: {run_summary.get('error')}")
    acceptance = build_image_acceptance_report(
        design=design,
        truth=truth,
        readback_tree=_read_json(output_dir / "readback.json"),
        reference_path=image_path,
        export_path=output_dir / "export.png",
        text_probe=_read_json(output_dir / "text_edit_probe.json"),
        asset_probe=_read_json(output_dir / "asset_probe.json"),
        image_ir=image_ir,
        run_summary=run_summary,
    )
    figma_elapsed = time.perf_counter() - figma_started
    runtime = {
        **dict(strategy_doc.get("runtime") or {}),
        "preparation_seconds": float(
            (strategy_doc.get("runtime") or {}).get("wall_time_seconds") or 0.0
        ),
        "figma_seconds": round(figma_elapsed, 3),
        "wall_time_seconds": round(
            float((strategy_doc.get("runtime") or {}).get("wall_time_seconds") or 0.0)
            + figma_elapsed,
            3,
        ),
        "cost_telemetry_status": "bounded-by-request-count",
    }
    pipeline = {
        "route": pagegraph.get("route"),
        "design": design,
        "image_ir": image_ir,
        "provenance": {
            **(pagegraph.get("provenance") or {}),
            "requested_route": strategy_doc["strategy"]["requested"],
            "attempts": strategy_doc["strategy"]["attempts"],
            "hidden_route_switch": strategy_doc["strategy"]["hidden_route_switch"],
        },
    }
    row = build_strategy_row(
        strategy=strategy,
        acceptance=acceptance,
        readback_tree=_read_json(output_dir / "readback.json"),
        pipeline=pipeline,
        runtime=runtime,
    )
    acceptance["benchmark_strategy"] = strategy
    acceptance["runtime"] = runtime
    acceptance["artifacts"] = {
        "design": "design.json",
        "image_ir": "image_ir.json",
        "figma_design": "figma_design.json",
        "readback": "figma/readback.json",
        "export": "figma/export.png",
        "text_probe": "figma/text_edit_probe.json",
        "asset_probe": "figma/asset_probe.json",
    }
    _write_json(strategy_dir / "acceptance.json", acceptance)
    _write_json(strategy_dir / "benchmark_row.json", row)
    return acceptance, runtime


def rebuild_comparison(output: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for strategy in REQUIRED_STRATEGIES:
        strategy_dir = output / "strategies" / strategy
        acceptance = _read_json(strategy_dir / "acceptance.json")
        readback = _read_json(strategy_dir / "figma" / "readback.json")
        runtime = _read_json(strategy_dir / "runtime.json")
        strategy_doc = _read_json(strategy_dir / "strategy.json")
        pagegraph = _read_json(strategy_dir / "pagegraph.json")
        image_ir = _read_json(strategy_dir / "image_ir.json")
        design = _read_json(strategy_dir / "design.json")
        hybrid_path = strategy_dir / "hybrid_report.json"
        hybrid_report = _read_json(hybrid_path) if hybrid_path.is_file() else {}
        skipped = list(hybrid_report.get("skipped") or [])
        duplicate_count = sum(
            str(item.get("reason") or "").startswith("duplicate-")
            for item in skipped
            if isinstance(item, dict)
        )
        provenance = {
            **(pagegraph.get("provenance") or {}),
            "requested_route": strategy_doc["strategy"]["requested"],
            "attempts": strategy_doc["strategy"]["attempts"],
            "hidden_route_switch": strategy_doc["strategy"]["hidden_route_switch"],
            "ambiguity_count": len(skipped) - duplicate_count,
            "duplicate_suppressed_count": duplicate_count,
        }
        row = build_strategy_row(
            strategy=strategy,
            acceptance=acceptance,
            readback_tree=readback,
            pipeline={
                "route": pagegraph.get("route"),
                "design": design,
                "image_ir": image_ir,
                "provenance": provenance,
            },
            runtime=runtime,
        )
        _write_json(strategy_dir / "benchmark_row.json", row)
        rows.append(row)
    comparison = build_strategy_comparison(
        rows,
        manifest["thresholds"],
        corpus_id=manifest["corpus_id"],
    )
    _write_json(output / "comparison.json", comparison)
    return comparison


def _require_prepared(strategy_dir: Path) -> None:
    missing = [
        path
        for path in (
            strategy_dir / "strategy.json",
            strategy_dir / "pagegraph.json",
            strategy_dir / "design.json",
            strategy_dir / "image_ir.json",
        )
        if not path.is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "prepared strategy is incomplete: "
            + ", ".join(str(path) for path in missing)
        )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
