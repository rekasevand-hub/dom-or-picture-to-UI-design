"""Project frozen Figma designs through the shared Figma/Axure IR boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.contracts import (  # noqa: E402
    build_output_ir,
    project_for_output,
    validate_output_ir,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build output-neutral IR and Figma/Axure capability evidence."
    )
    parser.add_argument("--image-design", type=Path, required=True)
    parser.add_argument("--dom-design", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _json_sha256(value: dict) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    for case_id, source_kind, path in (
        ("IMG-MVP-01-figma", "image", args.image_design.resolve()),
        ("DQ-R02-figma", "dom", args.dom_design.resolve()),
    ):
        design = _read_json(path)
        ir = build_output_ir(design, source_kind=source_kind)
        issues = validate_output_ir(ir)
        if issues:
            raise ValueError(
                f"{case_id} output IR validation failed: "
                + ", ".join(issue["code"] for issue in issues)
            )
        figma = project_for_output(ir, "figma")
        axure = project_for_output(ir, "axure")
        _write_json(output / f"{case_id}.ir.json", ir)
        cases.append(
            {
                "case_id": case_id,
                "source_kind": source_kind,
                "source_design": str(path),
                "source_design_sha256": _json_sha256(design),
                "document_id": ir["document_id"],
                "frames": len(ir["frames"]),
                "nodes": sum(len(frame["nodes"]) for frame in ir["frames"]),
                "assets": len(ir["assets"]),
                "required_features": ir["required_features"],
                "validation_issue_count": 0,
                "figma": figma,
                "axure": axure,
            }
        )
    summary = {
        "schema_version": "axure-shared-ir-probe/1.0",
        "status": "pass-current-scope",
        "scope": "boundary-projection-only",
        "cases": cases,
        "claims": [
            "One output-neutral contract projects both frozen designs.",
            "Target capability and degradation are explicit.",
            "Figma evidence is not transferable to Axure acceptance.",
        ],
        "non_claims": [
            "No Axure .rp write/readback/export is performed by this probe.",
            "No Axure visual or editability acceptance is claimed.",
            "No original-asset or adaptive-flow claim is upgraded.",
        ],
    }
    summary["content_sha256"] = _json_sha256(summary)
    _write_json(output / "summary.json", summary)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "cases": [
                    {
                        "case_id": case["case_id"],
                        "document_id": case["document_id"],
                        "nodes": case["nodes"],
                        "assets": case["assets"],
                        "axure_unsupported": case["axure"]["unsupported_features"],
                    }
                    for case in cases
                ],
                "summary_sha256": summary["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
