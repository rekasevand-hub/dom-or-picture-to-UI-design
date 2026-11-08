# -*- coding: utf-8 -*-
"""Generate read-only ROI and mask evidence for native text owners."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.evidence.native_text_mask_audit import (  # noqa: E402
    audit_native_text_masks,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit native-text masks under multiple diagnostic ROIs."
    )
    parser.add_argument("--design", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--rendered", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--owner-ref", action="append", default=[])
    parser.add_argument("--halo-px", type=int, default=2)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    design = json.loads(Path(args.design).read_text(encoding="utf-8"))
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report = audit_native_text_masks(
        design,
        args.reference,
        args.rendered,
        owner_refs=args.owner_ref or None,
        output_dir=str(output),
        halo_px=args.halo_px,
    )
    destination = output / "native_text_mask_audit.json"
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "ownerCount": report["ownerCount"],
                "missingOwnerRefs": report["missingOwnerRefs"],
                "report": str(destination),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
