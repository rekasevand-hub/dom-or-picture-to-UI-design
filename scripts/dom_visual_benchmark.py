from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.evidence.dom_visual_quality import (
    evaluate_dom_visual_quality,
)
from src.app.services.structure.capture_replay import replay_capture_bundle

BENCHMARK_SCHEMA_VERSION = "dom-visual-benchmark/1.0"


def build_benchmark_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = sorted(
        [dict(case) for case in cases],
        key=lambda case: str(case.get("name") or ""),
    )
    failure_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    rows = []
    for case in normalized:
        visual = case.get("visual") if isinstance(case.get("visual"), dict) else {}
        checks = visual.get("checks") if isinstance(visual.get("checks"), dict) else {}
        for name, check in checks.items():
            if not isinstance(check, dict):
                continue
            if check.get("status") == "fail":
                failure_counts[str(name)] += 1
            elif check.get("status") == "warn":
                warning_counts[str(name)] += 1
        status = str(case.get("status") or visual.get("status") or "not-evaluated")
        metrics = visual.get("metrics") if isinstance(visual.get("metrics"), dict) else {}
        rows.append(
            {
                "name": str(case.get("name") or ""),
                "bundle": str(case.get("bundle") or ""),
                "status": status,
                "checks": {
                    str(name): str(check.get("status") or "not-evaluated")
                    for name, check in checks.items()
                    if isinstance(check, dict)
                },
                "metrics": {
                    "image_fill_rate": metrics.get("image_fill_rate"),
                    "text_node_count": metrics.get("text_node_count"),
                    "bad_pixel_ratio": metrics.get("bad_pixel_ratio"),
                    "blank_area_ratio": metrics.get("blank_area_ratio"),
                    "height_drift_px": metrics.get("height_drift_px"),
                },
                "pagegraph_sha256": case.get("pagegraph_sha256"),
                "design_sha256": case.get("design_sha256"),
                "figma_readback_present": bool(case.get("figma_readback_present")),
                "browser_used": bool(case.get("browser_used")),
                "network_used": bool(case.get("network_used")),
            }
        )
    fail_case_count = sum(row["status"] == "fail" for row in rows)
    warn_case_count = sum(row["status"] == "warn" for row in rows)
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "cases": rows,
        "aggregate": {
            "case_count": len(rows),
            "fail_case_count": fail_case_count,
            "warn_case_count": warn_case_count,
            "pass_case_count": sum(row["status"] == "pass" for row in rows),
            "failure_counts": dict(sorted(failure_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
            "text_node_count": sum(
                int(row["metrics"].get("text_node_count") or 0) for row in rows
            ),
        },
        "browser_used": any(row["browser_used"] for row in rows),
        "network_used": any(row["network_used"] for row in rows),
    }


def _parse_case(value: str) -> tuple[str, Path, Path]:
    parts = value.split("=", 2)
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise argparse.ArgumentTypeError(
            "--case must be NAME=BUNDLE_DIR=FIGMA_EXPORT_DIR"
        )
    return parts[0].strip(), Path(parts[1]).resolve(), Path(parts[2]).resolve()


def _first_png(directory: Path) -> Path | None:
    for name in (
        "figma_render.png",
        "render.png",
        "screenshot.png",
        "frame.png",
        "export.png",
    ):
        path = directory / name
        if path.is_file():
            return path
    if directory.is_dir():
        return next(iter(sorted(directory.glob("*.png"))), None)
    return None


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _evaluate_case(
    name: str,
    bundle_dir: Path,
    export_dir: Path,
    replay_dir: Path,
) -> dict[str, Any]:
    replay = replay_capture_bundle(bundle_dir, replay_dir, build_design=True)
    design = _load_json(replay_dir / "12_design.json", {})
    design_text_count = sum(
        1
        for element in design.get("elements") or []
        if isinstance(element, dict)
        and str(element.get("type") or "").lower() == "text"
        and str(element.get("text") or "").strip()
    )
    readback_candidates = (
        export_dir / "figma_readback.json",
        export_dir / "readback_tree.json",
    )
    readback_path = next(
        (path for path in readback_candidates if path.is_file()),
        readback_candidates[0],
    )
    readback = _load_json(readback_path, {})
    image_report_path = export_dir / "image_report.json"
    if image_report_path.is_file():
        readback = {
            **readback,
            "imageFillReport": _load_json(image_report_path, {}),
        }
    reference = bundle_dir / "00_screenshot.png"
    rendered = _first_png(export_dir)
    visual: dict[str, Any]
    if reference.is_file() and rendered is not None:
        visual = evaluate_dom_visual_quality(
            reference,
            rendered,
            design,
            {
                **readback,
                "imageFillReport": readback.get("imageFillReport") or {"total": 0},
            },
        )
    else:
        visual = {
            "schema_version": "dom-visual-quality/1.0",
            "status": "not-evaluated",
            "reason": "missing-reference-or-rendered-png",
            "metrics": {},
            "checks": {},
        }
    visual.setdefault("metrics", {})["text_node_count"] = design_text_count
    return {
        "name": name,
        "bundle": str(bundle_dir),
        "status": visual.get("status"),
        "visual": visual,
        "pagegraph_sha256": replay.get("pagegraph_sha256"),
        "design_sha256": replay.get("design_sha256"),
        "figma_readback_present": readback_path.is_file(),
        "browser_used": False,
        "network_used": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate DOM capture replay visual quality per case."
    )
    parser.add_argument(
        "--case",
        action="append",
        required=True,
        type=_parse_case,
        metavar="NAME=BUNDLE_DIR=FIGMA_EXPORT_DIR",
    )
    parser.add_argument("--thresholds", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    rows = []
    try:
        with tempfile.TemporaryDirectory(prefix="dom-visual-benchmark-") as tmp:
            root = Path(tmp)
            for name, bundle_dir, export_dir in args.case:
                rows.append(
                    _evaluate_case(
                        name,
                        bundle_dir,
                        export_dir,
                        root / name,
                    )
                )
        report = build_benchmark_report(rows)
        if args.thresholds and args.thresholds.is_file():
            report["thresholds"] = _load_json(args.thresholds, {})
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - benchmark must fail closed
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 1 if report["aggregate"]["fail_case_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
