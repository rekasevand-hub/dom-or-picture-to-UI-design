# -*- coding: utf-8 -*-
"""Compare implementation routes under one frozen capture environment."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.evidence.comparison_environment import (  # noqa: E402
    SCHEMA_VERSION,
    ComparisonEnvironmentError,
    freeze_comparison_environment,
    validate_comparison_environment,
)
from src.app.services.structure.metrics import summarize  # noqa: E402


def _parse_viewport(value: str | None, fallback: tuple[int, int]) -> tuple[int, int]:
    if not value:
        return fallback
    normalized = value.lower().replace("×", "x").strip()
    try:
        width_text, height_text = normalized.split("x", 1)
        width, height = int(width_text), int(height_text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "--viewport must use WIDTHxHEIGHT, for example 1440x900"
        ) from exc
    if width <= 0 or height <= 0:
        raise ValueError("--viewport width and height must be positive")
    return width, height


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_observation(run_dir: Path) -> dict:
    manifest = _read_json(run_dir / "manifest.json")
    design = _read_json(run_dir / "12_design.json")
    screenshot_size = None
    image = manifest.get("image")
    if image and Path(image).is_file():
        with Image.open(image) as opened:
            screenshot_size = list(opened.size)
    canvas = design.get("canvas") if isinstance(design, dict) else None
    design_canvas = (
        [canvas.get("width"), canvas.get("height")]
        if isinstance(canvas, dict)
        else None
    )
    return {
        "manifest": manifest,
        "capture": manifest.get("capture"),
        "screenshot_size": screenshot_size,
        "design_canvas": design_canvas,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=None, help="URL shared by compared routes")
    parser.add_argument(
        "--image", default=None, help="screenshot shared by compared routes"
    )
    parser.add_argument("--routes", default="dom,grounding,cv")
    parser.add_argument("--base-out", default="output/compare")
    parser.add_argument(
        "--viewport",
        default=None,
        help="Frozen CSS viewport as WIDTHxHEIGHT; defaults to the configured viewport",
    )
    parser.add_argument(
        "--device-scale-factor",
        type=int,
        default=None,
        help="Frozen DPR; defaults to the configured device scale factor",
    )
    parser.add_argument(
        "--reference-image",
        default=None,
        help="Optional screenshot that must match the frozen CSS breakpoint",
    )
    parser.add_argument("--profile-id", default="default")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate retained route directories without recapturing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.check_only and bool(args.url) == bool(args.image):
        parser.error("exactly one of --url or --image is required unless --check-only")

    # Import the agent before config to avoid the package's legacy circular import.
    from src.app.agents.precise_agent import PreciseAgent
    from src.config.settings import load_config

    from dataclasses import replace

    cfg = load_config()
    base = Path(args.base_out)
    (base / "summary.json").unlink(missing_ok=True)
    viewport = _parse_viewport(
        args.viewport,
        (cfg.playwright_viewport_width, cfg.playwright_viewport_height),
    )
    dpr = int(args.device_scale_factor or cfg.device_scale_factor)
    reference_size = None
    if args.reference_image:
        with Image.open(args.reference_image) as opened:
            reference_size = list(opened.size)
    expected = None
    if not args.image:
        try:
            expected = freeze_comparison_environment(
                viewport=viewport,
                device_scale_factor=dpr,
                profile_id=args.profile_id,
                reference_size=reference_size,
            )
        except ComparisonEnvironmentError as exc:
            _write_json(base / "comparison_environment.json", exc.report)
            for issue in exc.report["issues"]:
                print(json.dumps(issue, ensure_ascii=False), file=sys.stderr)
            return 2

    routes = [route.strip() for route in args.routes.split(",") if route.strip()]
    if len(routes) < 2:
        parser.error("--routes must contain at least two routes")

    run_dirs = {route: base / route for route in routes}
    if not args.check_only:
        run_cfg = replace(
            cfg,
            playwright_viewport_width=viewport[0],
            playwright_viewport_height=viewport[1],
            device_scale_factor=dpr,
        )
        for route, sub in run_dirs.items():
            PreciseAgent(replace(run_cfg, output_dir=sub)).run(
                url=args.url,
                image=args.image,
                route=route,
                tool="svg",
            )

    missing = [
        str(run_dir)
        for run_dir in run_dirs.values()
        if not (run_dir / "manifest.json").is_file()
        or not (run_dir / "10_pagegraph.json").is_file()
        or not (run_dir / "12_design.json").is_file()
    ]
    if missing:
        print(
            "missing retained comparison artifacts:\n" + "\n".join(missing),
            file=sys.stderr,
        )
        return 1

    observations = {
        route: _run_observation(run_dir) for route, run_dir in run_dirs.items()
    }
    if args.image:
        with Image.open(args.image) as opened:
            input_size = list(opened.size)
        environment_report = {
            "schema_version": SCHEMA_VERSION,
            "profile_id": args.profile_id,
            "status": "not-applicable-image-input",
            "reason": "image-input-has-no-browser-viewport",
            "input_reference": {
                "path": str(Path(args.image)),
                "pixel_size": input_size,
            },
            "runs": {
                route: {
                    "input_image": observation.get("manifest", {}).get("image"),
                }
                for route, observation in observations.items()
            },
        }
    else:
        try:
            environment_report = validate_comparison_environment(
                observations,
                expected,
            )
        except ComparisonEnvironmentError as exc:
            _write_json(base / "comparison_environment.json", exc.report)
            for issue in exc.report["issues"]:
                print(json.dumps(issue, ensure_ascii=False), file=sys.stderr)
            return 2

    _write_json(base / "comparison_environment.json", environment_report)
    graphs = {
        route: _read_json(run_dir / "10_pagegraph.json")
        for route, run_dir in run_dirs.items()
    }
    summary = [
        summarize(graphs[left], graphs[right])
        for left, right in itertools.combinations(graphs, 2)
    ]
    _write_json(base / "summary.json", summary)
    for item in summary:
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
