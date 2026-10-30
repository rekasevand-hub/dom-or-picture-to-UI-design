from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.evidence.dom_route_quality import (
    evaluate_dom_route_quality,
)
from src.app.services.structure.capture_asset_ledger import build_asset_ledger
from src.app.services.structure.capture_bundle import (
    CAPTURE_BUNDLE_FILENAME,
    capture_bundle_artifact_path,
    load_capture_bundle,
)
from src.app.services.structure.capture_replay import replay_capture_bundle

ROUTE_BENCHMARK_SCHEMA_VERSION = "dom-route-benchmark/1.0"


def build_route_benchmark_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = sorted(
        [dict(case) for case in cases],
        key=lambda case: str(case.get("name") or ""),
    )
    failure_counts: Counter[str] = Counter()
    rows = []
    for case in normalized:
        quality = case.get("quality") if isinstance(case.get("quality"), dict) else {}
        checks = quality.get("checks") if isinstance(quality.get("checks"), dict) else {}
        for name, check in checks.items():
            if isinstance(check, dict) and check.get("status") == "fail":
                failure_counts[str(name)] += 1
        rows.append(
            {
                "name": str(case.get("name") or ""),
                "bundle": str(case.get("bundle") or ""),
                "bundle_sha256": case.get("bundle_sha256"),
                "pagegraph_sha256": case.get("pagegraph_sha256"),
                "design_sha256": case.get("design_sha256"),
                "deterministic": bool(case.get("deterministic")),
                "quality": {
                    "status": str(quality.get("status") or "not-evaluated"),
                    "checks": {
                        str(name): str(check.get("status") or "not-evaluated")
                        for name, check in checks.items()
                        if isinstance(check, dict)
                    },
                },
                "image_counts": dict(case.get("image_counts") or {}),
                "text_node_count": int(case.get("text_node_count") or 0),
                "browser_used": bool(case.get("browser_used")),
                "network_used": bool(case.get("network_used")),
            }
        )
    return {
        "schema_version": ROUTE_BENCHMARK_SCHEMA_VERSION,
        "cases": rows,
        "aggregate": {
            "case_count": len(rows),
            "fail_case_count": sum(
                row["quality"]["status"] == "fail" for row in rows
            ),
            "deterministic_case_count": sum(
                row["deterministic"] for row in rows
            ),
            "failure_counts": dict(sorted(failure_counts.items())),
            "image_reference_count": sum(
                int(row["image_counts"].get("references") or 0) for row in rows
            ),
            "design_image_count": sum(
                int(row["image_counts"].get("design_images") or 0) for row in rows
            ),
            "figma_fill_count": sum(
                int(row["image_counts"].get("figma_fills") or 0) for row in rows
            ),
        },
        "browser_used": any(row["browser_used"] for row in rows),
        "network_used": any(row["network_used"] for row in rows),
    }


def _parse_case(value: str) -> tuple[str, Path]:
    parts = value.split("=", 1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise argparse.ArgumentTypeError("--case must be NAME=BUNDLE_DIR")
    return parts[0].strip(), Path(parts[1]).resolve()


def _parse_readback(value: str) -> tuple[str, Path]:
    parts = value.split("=", 1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise argparse.ArgumentTypeError("--figma-readback must be NAME=JSON")
    return parts[0].strip(), Path(parts[1]).resolve()


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _image_fill_count(readback: Any) -> int:
    if not isinstance(readback, dict):
        return 0
    report = readback.get("imageFillReport")
    if isinstance(report, dict):
        for key in (
            "fillCount",
            "total",
            "imageFillTotal",
            "image_fill_total",
            "count",
        ):
            if isinstance(report.get(key), int):
                return int(report[key])
    for key in ("fillCount", "imageFillTotal", "image_fill_count", "count"):
        if isinstance(readback.get(key), int):
            return int(readback[key])
    return 0


def _case_row(
    name: str,
    bundle_dir: Path,
    replay_root: Path,
    readback: dict[str, Any] | None,
) -> dict[str, Any]:
    first_dir = replay_root / "first"
    second_dir = replay_root / "second"
    first = replay_capture_bundle(bundle_dir, first_dir, build_design=True)
    second = replay_capture_bundle(bundle_dir, second_dir, build_design=True)
    deterministic = (
        first["pagegraph_sha256"] == second["pagegraph_sha256"]
        and first["design_sha256"] == second["design_sha256"]
    )
    bundle = load_capture_bundle(bundle_dir)
    dom_path = capture_bundle_artifact_path(bundle_dir, bundle, "dom")
    dom_nodes = _load_json(dom_path, [])
    graph = _load_json(first_dir / "10_pagegraph.json", {})
    design = _load_json(first_dir / "12_design.json", {})
    asset_ledger = build_asset_ledger(design)
    quality = evaluate_dom_route_quality(
        bundle,
        dom_nodes,
        graph,
        design,
        asset_ledger,
    )
    references = quality["checks"]["image_coverage"]["references"]
    design_images = quality["checks"]["image_coverage"]["design_images"]
    return {
        "name": name,
        "bundle": str(bundle_dir),
        "bundle_sha256": hashlib.sha256(
            (bundle_dir / CAPTURE_BUNDLE_FILENAME).read_bytes()
        ).hexdigest(),
        "pagegraph_sha256": first["pagegraph_sha256"],
        "design_sha256": first["design_sha256"],
        "deterministic": deterministic,
        "quality": quality,
        "image_counts": {
            "references": references,
            "design_images": design_images,
            "figma_fills": _image_fill_count(readback),
            "figma_readback_present": readback is not None,
        },
        "text_node_count": sum(
            str(item.get("type") or "").lower() == "text"
            and bool(str(item.get("text") or "").strip())
            for item in design.get("elements") or []
            if isinstance(item, dict)
        ),
        "browser_used": False,
        "network_used": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay and evaluate DOM capture route quality."
    )
    parser.add_argument(
        "--case",
        action="append",
        required=True,
        type=_parse_case,
        metavar="NAME=BUNDLE_DIR",
    )
    parser.add_argument(
        "--figma-readback",
        action="append",
        default=[],
        type=_parse_readback,
        metavar="NAME=JSON",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output/_dom_route_benchmark/dom-route-benchmark.json"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    readbacks = {
        name: _load_json(path, {})
        for name, path in args.figma_readback
    }
    try:
        with tempfile.TemporaryDirectory(prefix="dom-route-benchmark-") as tmp:
            root = Path(tmp)
            rows = [
                _case_row(name, bundle_dir, root / name, readbacks.get(name))
                for name, bundle_dir in args.case
            ]
        report = build_route_benchmark_report(rows)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - benchmark must fail closed
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    failed = (
        report["aggregate"]["fail_case_count"]
        or report["aggregate"]["deterministic_case_count"]
        != report["aggregate"]["case_count"]
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
