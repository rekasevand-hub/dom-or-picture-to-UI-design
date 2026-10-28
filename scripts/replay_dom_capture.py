from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.structure.capture_replay import replay_capture_bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild PageGraph and DesignSpec from a saved DOM capture."
    )
    parser.add_argument("--bundle", required=True, help="capture bundle directory")
    parser.add_argument("--output-dir", required=True, help="replay output directory")
    parser.add_argument(
        "--no-design",
        action="store_true",
        help="skip DesignSpec generation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bundle_dir = Path(args.bundle)
    output_dir = Path(args.output_dir)
    build_design = not args.no_design
    try:
        result = replay_capture_bundle(
            bundle_dir,
            output_dir,
            build_design=build_design,
        )
        with tempfile.TemporaryDirectory(prefix="dom-replay-check-") as tmp:
            check = replay_capture_bundle(
                bundle_dir,
                Path(tmp),
                build_design=build_design,
            )
        if (
            result["pagegraph_sha256"] != check["pagegraph_sha256"]
            or result["design_sha256"] != check["design_sha256"]
        ):
            print("replay is nondeterministic", file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed and explain why
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
