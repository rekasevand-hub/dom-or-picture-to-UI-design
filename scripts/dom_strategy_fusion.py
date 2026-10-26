"""Replay a frozen D-006 asset report through strategy fusion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.evidence.dom_strategy_fusion import (  # noqa: E402
    build_fusion_report,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay frozen asset uses through strategy fusion."
    )
    parser.add_argument("--asset-report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    asset_report = json.loads(args.asset_report.read_text(encoding="utf-8"))
    if not isinstance(asset_report, dict):
        raise SystemExit("asset report must be a JSON object")
    report = build_fusion_report(asset_report)
    args.out.mkdir(parents=True, exist_ok=True)
    _write_json(args.out / "summary.json", report)
    print(
        json.dumps(
            {
                "uses": report["use_count"],
                "source": report["source_identity"],
                "display": report["display_payload"],
                "generated": report["generated_approximation"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
