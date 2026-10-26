"""Generate an Axure RP 8 artifact from the existing image MVP DesignSpec."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.axure_dom_output import main as generate_axure_output  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reuse the image MVP design in the Axure output path"
    )
    parser.add_argument("--design", required=True, help="prepared image DesignSpec")
    parser.add_argument("--ir", default="", help="optional image design-ir/2.0")
    parser.add_argument("--out", required=True, help="evidence output directory")
    parser.add_argument("--page-name", action="append", default=[])
    parser.add_argument("--generate-twice", action="store_true")
    args = parser.parse_args(argv)

    delegated = [
        "--design",
        args.design,
        "--out",
        args.out,
        "--source-kind",
        "image",
    ]
    if args.ir:
        delegated.extend(["--ir", args.ir])
    for name in args.page_name:
        delegated.extend(["--page-name", name])
    if args.generate_twice:
        delegated.append("--generate-twice")
    return generate_axure_output(delegated)


if __name__ == "__main__":
    raise SystemExit(main())
