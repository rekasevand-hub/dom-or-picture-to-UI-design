"""Attribute over-threshold Figma PNG pixels to design elements and styles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence.dom_figma_diff_attribution import (  # noqa: E402
    build_diff_attribution,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Attribute over-threshold pixels to Figma design elements."
    )
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--readback", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--render", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threshold", type=int, default=30)
    parser.add_argument("--search-radius", type=int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    design = _read_json(args.design)
    readback = _read_json(args.readback)
    report = build_diff_attribution(
        design,
        readback,
        args.reference,
        args.render,
        threshold=max(0, args.threshold),
        search_radius=max(0, args.search_radius),
    )
    args.out.mkdir(parents=True, exist_ok=True)
    _write_json(args.out / "summary.json", report)
    print(
        json.dumps(
            {
                "total_over30": report["total_over30"],
                "total_over30_ratio": report["total_over30_ratio"],
                "unmatched_over30": report["unmatched_over30"],
                "text_shift_counts": report["text_shift_counts"],
                "top_nodes": report["nodes"][:10],
            },
            ensure_ascii=True,
        )
    )
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
