from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.evidence.dom_visual_quality import (
    evaluate_dom_visual_quality,
)
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter
from src.app.services.som.direct_design import build_direct_design
from src.app.services.structure.capture_bundle import (
    capture_bundle_artifact_path,
    load_capture_bundle,
)
from src.app.services.structure.site_profiles import load_profile

AB_SCHEMA_VERSION = "dom-visual-ab/1.0"
_P1_ENV_VARS = (
    "DOM_TEXT_MODEL_V2",
    "DOM_VISUAL_ASSETS_V2",
    "DOM_SVG_MATERIALIZATION_V2",
    "DOM_NETWORK_ASSET_RECOVERY",
)


@contextmanager
def _p1_environment(enabled: bool) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in _P1_ENV_VARS}
    try:
        for name in _P1_ENV_VARS:
            os.environ[name] = "true" if enabled else "false"
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _metric_delta(treatment: Any, baseline: Any) -> float | int | None:
    if isinstance(treatment, (int, float)) and isinstance(baseline, (int, float)):
        delta = treatment - baseline
        return round(delta, 6) if isinstance(delta, float) else delta
    return None


def build_visual_ab_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    regression_counts: Counter[str] = Counter()
    for case in sorted(cases, key=lambda item: str(item.get("name") or "")):
        baseline = case.get("baseline") or {}
        treatment = case.get("treatment") or {}
        baseline_metrics = baseline.get("metrics") or {}
        treatment_metrics = treatment.get("metrics") or {}
        deltas = {
            key: _metric_delta(treatment_metrics.get(key), baseline_metrics.get(key))
            for key in (
                "bad_pixel_ratio",
                "image_fill_rate",
                "text_node_count",
                "blank_area_ratio",
                "height_drift_px",
            )
        }
        regressions = []
        if (deltas["bad_pixel_ratio"] or 0) > 0.01:
            regressions.append("bad_pixel_ratio")
        if (deltas["image_fill_rate"] or 0) < 0:
            regressions.append("image_fill_rate")
        if (deltas["text_node_count"] or 0) < 0:
            regressions.append("text_node_count")
        if (deltas["blank_area_ratio"] or 0) > 0.01:
            regressions.append("blank_area_ratio")
        for name in regressions:
            regression_counts[name] += 1
        baseline_regions = baseline.get("regions") or {}
        treatment_regions = treatment.get("regions") or {}
        region_deltas = {
            key: _metric_delta(treatment_regions.get(key), value)
            for key, value in baseline_regions.items()
        }
        rows.append(
            {
                "name": str(case.get("name") or ""),
                "baseline_status": str(baseline.get("status") or "not-evaluated"),
                "treatment_status": str(treatment.get("status") or "not-evaluated"),
                "deltas": deltas,
                "regionDeltas": region_deltas,
                "regressions": regressions,
                "metrics": {
                    "baseline": dict(baseline_metrics),
                    "treatment": dict(treatment_metrics),
                },
            }
        )
    return {
        "schema_version": AB_SCHEMA_VERSION,
        "cases": rows,
        "aggregate": {
            "case_count": len(rows),
            "regression_count": sum(bool(row["regressions"]) for row in rows),
            "regression_counts": dict(sorted(regression_counts.items())),
            "treatment_fail_count": sum(
                row["treatment_status"] == "fail" for row in rows
            ),
            "baseline_fail_count": sum(
                row["baseline_status"] == "fail" for row in rows
            ),
        },
        "browser_used": False,
        "network_used": False,
    }


def _region_scores(reference: Path, rendered: Path) -> dict[str, float]:
    import cv2
    from src.app.utils.pixel_metrics import (
        compare_images,
        default_bands,
        region_scores,
    )

    ref = cv2.imread(str(reference))
    new = cv2.imread(str(rendered))
    if ref is None or new is None:
        return {}
    height, width = ref.shape[:2]
    if new.shape[:2] != (height, width):
        new = cv2.resize(new, (width, height))
    report = compare_images(ref, new)
    return {
        name: round(score, 6)
        for name, _y0, _y1, _x0, _x1, score in region_scores(
            report["diff"],
            default_bands(width, height),
            clamp=True,
        )
    }


class _ABAdapter(FigmaBridgeAdapter):
    def __init__(self, *args, screen_name: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.screen_name = screen_name
        self.frame_id: str | None = None

    def create_frame(self, spec):
        params = dict(spec)
        if self.frame_id is None:
            params["name"] = self.screen_name
        node_id = super().create_frame(params)
        if self.frame_id is None:
            self.frame_id = node_id
        return node_id

    def flush(self) -> None:
        pass


def _render_variant(
    *,
    bridge_url: str,
    timeout: float,
    screen_name: str,
    reference: Path,
    design: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    design_path = output_dir / "12_design.json"
    design_path.write_text(
        json.dumps(design, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    adapter = _ABAdapter(bridge_url, timeout=timeout, screen_name=screen_name)
    adapter.connect()
    try:
        adapter._send(
            "remove_nodes_by_name",
            {"name": screen_name, "prefix": True},
        )
        adapter.render_design(design)
        tree = adapter._send(
            "get_node_tree",
            {"nodeId": adapter.frame_id, "depth": 4},
        )
        image_report = adapter.image_fill_report(adapter.frame_id)
        exported = adapter._send(
            "export_frame",
            {"nodeId": adapter.frame_id, "scale": 1.0},
        )
        rendered = output_dir / "figma_render.png"
        rendered.write_bytes(base64.b64decode(exported["base64"]))
        (output_dir / "readback_tree.json").write_text(
            json.dumps(tree, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "image_report.json").write_text(
            json.dumps(image_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    finally:
        adapter.disconnect()
    visual = evaluate_dom_visual_quality(
        reference,
        rendered,
        design,
        {**tree, "imageFillReport": image_report},
    )
    visual["text_node_count"] = sum(
        str(item.get("type") or "").lower() == "text"
        and bool(str(item.get("text") or "").strip())
        for item in design.get("elements") or []
        if isinstance(item, dict)
    )
    visual["metrics"]["text_node_count"] = visual["text_node_count"]
    visual["regions"] = _region_scores(reference, rendered)
    (output_dir / "visual-quality.json").write_text(
        json.dumps(visual, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return visual


def _evaluate_case(
    name: str,
    bundle_dir: Path,
    output_root: Path,
    *,
    bridge_url: str,
    timeout: float,
) -> dict[str, Any]:
    bundle = load_capture_bundle(bundle_dir)
    screenshot = capture_bundle_artifact_path(bundle_dir, bundle, "screenshot")
    som_path = bundle_dir / "11_som.json"
    if not som_path.is_file():
        raise FileNotFoundError(som_path)
    dom_path = capture_bundle_artifact_path(bundle_dir, bundle, "dom")
    som = json.loads(som_path.read_text(encoding="utf-8"))
    dom_nodes = json.loads(dom_path.read_text(encoding="utf-8"))
    url = str(bundle.get("final_url") or bundle.get("requested_url") or "")
    with _p1_environment(False):
        legacy_design = build_direct_design(
            som,
            load_profile(url),
            dom_nodes,
        )
    treatment_path = bundle_dir / "12_design.json"
    if not treatment_path.is_file():
        with _p1_environment(True):
            treatment_design = build_direct_design(
                som,
                load_profile(url),
                dom_nodes,
            )
    else:
        treatment_design = json.loads(treatment_path.read_text(encoding="utf-8"))
    case_root = output_root / name
    baseline = _render_variant(
        bridge_url=bridge_url,
        timeout=timeout,
        screen_name=f"AB-{name}-LEGACY",
        reference=screenshot,
        design=legacy_design,
        output_dir=case_root / "legacy",
    )
    treatment = _render_variant(
        bridge_url=bridge_url,
        timeout=timeout,
        screen_name=f"AB-{name}-P1",
        reference=screenshot,
        design=treatment_design,
        output_dir=case_root / "p1",
    )
    return {
        "name": name,
        "bundle": str(bundle_dir),
        "baseline": baseline,
        "treatment": treatment,
    }


def _parse_case(value: str) -> tuple[str, Path]:
    parts = value.split("=", 1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise argparse.ArgumentTypeError("--case must be NAME=BUNDLE_DIR")
    return parts[0].strip(), Path(parts[1]).resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare legacy and P1 DOM renders on the same capture."
    )
    parser.add_argument(
        "--case",
        action="append",
        required=True,
        type=_parse_case,
        metavar="NAME=BUNDLE_DIR",
    )
    parser.add_argument("--bridge-url", default="ws://localhost:8765")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("output/_dom_visual_ab"),
    )
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        cases = [
            _evaluate_case(
                name,
                bundle_dir,
                args.out_dir,
                bridge_url=args.bridge_url,
                timeout=args.timeout,
            )
            for name, bundle_dir in args.case
        ]
        report = build_visual_ab_report(cases)
        report_path = args.report or (args.out_dir / "dom-visual-ab.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - comparison must fail closed
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 1 if report["aggregate"]["regression_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
