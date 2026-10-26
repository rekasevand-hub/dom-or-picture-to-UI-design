"""Evaluate Axure RP 8 published HTML independently from Figma."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app.services.evidence.axure_acceptance import (  # noqa: E402
    evaluate_published_axure,
)
from src.app.services.rendering.axure.evidence import inspect_rp  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate an Axure RP 8 published prototype"
    )
    parser.add_argument("--publish-dir", required=True)
    parser.add_argument("--design", required=True, help="source DesignSpec JSON")
    parser.add_argument("--rp", required=True, help="generated Axure RP 8 file")
    parser.add_argument("--out", required=True, help="evidence output directory")
    parser.add_argument("--critical-text", action="append", default=[])
    parser.add_argument("--expected-asset-count", type=int, default=None)
    parser.add_argument("--reference-screenshot", default="")
    parser.add_argument("--render-screenshot", default="")
    parser.add_argument(
        "--critical-region",
        action="append",
        default=[],
        help="critical region as name,x,y,width,height; repeat as needed",
    )
    args = parser.parse_args(argv)

    design = json.loads(Path(args.design).read_text(encoding="utf-8-sig"))
    rp_report = inspect_rp(args.rp)
    critical_regions = _parse_critical_regions(parser, args.critical_region)
    result = evaluate_published_axure(
        args.publish_dir,
        design=design,
        rp_report=rp_report,
        critical_texts=args.critical_text,
        expected_asset_count=args.expected_asset_count,
        reference_screenshot=args.reference_screenshot or None,
        render_screenshot=args.render_screenshot or None,
        critical_regions=critical_regions,
    )
    result["rp_artifact"] = {
        "path": str(Path(args.rp).resolve()),
        "sha256": rp_report["artifact_sha256"],
        "size": rp_report["artifact_size"],
        "page_count": rp_report["page_count"],
        "asset_count": rp_report["asset_count"],
    }
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "acceptance.json", result)
    print(f"status={result['status']}")
    print(f"pages={result['page_count']} labels={result['label_count']}")
    print(
        "critical_text={0}/{1} assets={2}/{3} visual={4}".format(
            result["critical_text"]["passed"],
            result["critical_text"]["total"],
            result["assets"]["matched_unique"],
            result["assets"]["expected_unique"],
            result["visual"]["status"],
        )
    )
    print(f"output={(output / 'acceptance.json').resolve()}")
    return 0 if result["status"] == "pass" else 1


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_critical_regions(
    parser: argparse.ArgumentParser,
    values: list[str],
) -> list[dict[str, Any]]:
    regions = []
    for value in values:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 5 or not parts[0]:
            parser.error(
                "--critical-region must be name,x,y,width,height: " f"{value!r}"
            )
        try:
            x, y, width, height = (float(part) for part in parts[1:])
        except ValueError:
            parser.error("--critical-region geometry must be numeric: " f"{value!r}")
        regions.append(
            {
                "name": parts[0],
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }
        )
    return regions


if __name__ == "__main__":
    raise SystemExit(main())
