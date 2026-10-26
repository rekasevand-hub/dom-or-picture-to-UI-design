"""Prepare, run and report D-008 frozen DOM Figma acceptance."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence.dom_figma_acceptance import (  # noqa: E402
    build_acceptance_report,
    build_frozen_sample_design,
    run_real_figma_acceptance,
)
from src.app.services.evidence.dom_quality_corpus import (  # noqa: E402
    load_corpus,
)
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402


class DomFigmaAcceptanceAdapter(FigmaBridgeAdapter):
    """Keep the bridge open after render and retain the created root frame."""

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
        description="Run real Figma acceptance for a frozen DOM sample."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--capture-root", type=Path, required=True)
    prepare.add_argument("--sample-id", default="DQ-R02")
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--origin-x", type=float, default=1600)
    prepare.add_argument("--origin-y", type=float, default=0)
    prepare.add_argument("--recover-network-assets", action="store_true")
    prepare.add_argument("--generate-icon-approximations", action="store_true")

    run = subparsers.add_parser("run")
    run.add_argument("--sample-root", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--readback-depth", type=int, default=8)

    report = subparsers.add_parser("report")
    report.add_argument("--manifest", type=Path, required=True)
    report.add_argument("--sample-root", type=Path, required=True)
    report.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "prepare":
        corpus = load_corpus(args.manifest)
        result = build_frozen_sample_design(
            corpus,
            args.capture_root,
            args.sample_id,
            args.out,
            canvas_origin=(args.origin_x, args.origin_y),
            recover_network_assets=args.recover_network_assets,
            generate_icon_approximations=args.generate_icon_approximations,
        )
        print(
            json.dumps(
                {
                    "sample_id": args.sample_id,
                    "design_sha256": result["metadata"]["design_sha256"],
                    "counts": result["metadata"]["counts"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "run":
        design = json.loads(
            (args.sample_root / "design.json").read_text(encoding="utf-8")
        )
        metadata = json.loads(
            (args.sample_root / "sample_metadata.json").read_text(encoding="utf-8")
        )
        summary = run_real_figma_acceptance(
            design,
            output_dir=args.out,
            sample_id=str(metadata.get("sample_id") or ""),
            adapter_factory=DomFigmaAcceptanceAdapter,
            readback_depth=max(1, args.readback_depth),
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary.get("status") == "captured-figma-evidence" else 2
    corpus = load_corpus(args.manifest)
    report = build_acceptance_report(
        corpus,
        sample_root=args.sample_root,
        run_root=args.out,
    )
    print(json.dumps(report["dimensions"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
