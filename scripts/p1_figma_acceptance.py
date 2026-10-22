# -*- coding: utf-8 -*-
"""Build an independent Figma acceptance report from real replay artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.p1_canonical_output_fidelity import evaluate_visual_fidelity  # noqa: E402
from src.app.services.rendering.figma_acceptance import (  # noqa: E402
    evaluate_figma_acceptance,
)


def build_acceptance_artifact(
    *,
    design_path: Path,
    truth_path: Path,
    readback_path: Path,
    reference_path: Path,
    render_path: Path,
    out_dir: Path,
    font_report_path: Path | None = None,
    visual_policy_path: Path | None = None,
    edit_probe_path: Path | None = None,
    asset_probe_path: Path | None = None,
    image_report_path: Path | None = None,
    parent_layout_probe_path: Path | None = None,
    structure_policy_path: Path | None = None,
) -> dict[str, Any]:
    design_path = Path(design_path).resolve()
    truth_path = Path(truth_path).resolve()
    readback_path = Path(readback_path).resolve()
    reference_path = Path(reference_path).resolve()
    render_path = Path(render_path).resolve()
    out_dir = Path(out_dir).resolve()

    design = _load_json(design_path)
    truth = _load_json(truth_path)
    readback = _load_json(readback_path)
    font_report = _load_optional_json(font_report_path)
    visual_policy = _load_optional_json(visual_policy_path)
    edit_probe = _load_optional_json(edit_probe_path)
    asset_probe = _load_optional_json(asset_probe_path)
    image_report = _load_optional_json(image_report_path)
    parent_layout_probe = _load_optional_json(parent_layout_probe_path)
    structure_policy = _load_optional_json(structure_policy_path)
    edit_probe = _attach_parent_layout_probe(edit_probe, parent_layout_probe)

    visual_metrics = evaluate_visual_fidelity(
        reference_path,
        render_path,
        exclusion_regions=truth.get("visual_exclusion_regions") or [],
    )
    acceptance = evaluate_figma_acceptance(
        design,
        truth,
        readback,
        font_report=font_report,
        visual_metrics=visual_metrics,
        visual_policy=visual_policy,
        edit_probe=edit_probe,
        asset_probe=asset_probe,
        image_report=image_report,
        policy=structure_policy,
    )

    input_paths: dict[str, Path] = {
        "design": design_path,
        "truth": truth_path,
        "readback": readback_path,
        "reference": reference_path,
        "render": render_path,
    }
    optional_paths = {
        "font_report": font_report_path,
        "visual_policy": visual_policy_path,
        "edit_probe": edit_probe_path,
        "asset_probe": asset_probe_path,
        "image_report": image_report_path,
        "parent_layout_probe": parent_layout_probe_path,
        "structure_policy": structure_policy_path,
    }
    for name, path in optional_paths.items():
        if path is not None:
            input_paths[name] = Path(path).resolve()

    artifact = {
        "experiment": "P1-FIGMA-ACCEPTANCE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **acceptance,
        "inputs": {name: _file_evidence(path) for name, path in input_paths.items()},
        "evidence_boundary": {
            "real_figma_readback": True,
            "real_figma_export": True,
            "canonical_capture_required": True,
            "composite_score_used": False,
        },
    }
    artifact["content_hash"] = _content_hash(artifact)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "figma_acceptance.json"
    out_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", required=True, help="Canonical 12_design.json")
    parser.add_argument("--truth", required=True, help="Canonical truth JSON")
    parser.add_argument("--readback", required=True, help="Real Figma node tree")
    parser.add_argument("--reference", required=True, help="Canonical screenshot")
    parser.add_argument("--render", required=True, help="Real Figma PNG export")
    parser.add_argument("--out", required=True, help="Acceptance output directory")
    parser.add_argument("--font-report", default=None)
    parser.add_argument("--visual-policy", default=None)
    parser.add_argument("--edit-probe", default=None)
    parser.add_argument("--asset-probe", default=None)
    parser.add_argument("--image-report", default=None)
    parser.add_argument("--parent-layout-probe", default=None)
    parser.add_argument("--structure-policy", default=None)
    args = parser.parse_args(argv)

    try:
        artifact = build_acceptance_artifact(
            design_path=Path(args.design),
            truth_path=Path(args.truth),
            readback_path=Path(args.readback),
            reference_path=Path(args.reference),
            render_path=Path(args.render),
            out_dir=Path(args.out),
            font_report_path=_optional_path(args.font_report),
            visual_policy_path=_optional_path(args.visual_policy),
            edit_probe_path=_optional_path(args.edit_probe),
            asset_probe_path=_optional_path(args.asset_probe),
            image_report_path=_optional_path(args.image_report),
            parent_layout_probe_path=_optional_path(args.parent_layout_probe),
            structure_policy_path=_optional_path(args.structure_policy),
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1

    print(
        "[figma] %s  structure=%s edit=%s asset=%s visual=%s"
        % (
            artifact["acceptance_status"],
            artifact["dimensions"]["structure"]["status"],
            artifact["dimensions"]["edit"]["status"],
            artifact["dimensions"]["asset"]["status"],
            artifact["dimensions"]["visual"]["status"],
        )
    )
    if artifact["blocking_dimensions"]:
        print("[block] " + ", ".join(artifact["blocking_dimensions"]))
    print(
        "[count] attempted=%d evaluated=%d"
        % (
            artifact["figma_attempted_count"],
            artifact["figma_evaluated_count"],
        )
    )
    print("[out  ] %s" % (Path(args.out).resolve() / "figma_acceptance.json"))
    return 0 if artifact["acceptance_passed"] else 3


def _load_json(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"missing artifact: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"artifact must contain a JSON object: {path}")
    return value


def _attach_parent_layout_probe(
    edit_probe: dict[str, Any] | None,
    parent_probe: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if edit_probe is None or parent_probe is None:
        return edit_probe
    merged = dict(edit_probe)
    merged["parent_layout_propagation"] = {
        "status": str(parent_probe.get("status") or "not-evaluated"),
        "evidence": parent_probe,
    }
    return merged


def _load_optional_json(path: Path | None) -> dict[str, Any] | None:
    return _load_json(Path(path)) if path is not None else None


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _file_evidence(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"missing artifact: {path}")
    payload = path.read_bytes()
    return {
        "path": str(path),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _content_hash(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "content_hash"}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
