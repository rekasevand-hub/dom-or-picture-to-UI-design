"""Generate deterministic Axure RP 8 evidence from a DOM DesignSpec."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app.services.rendering.axure.evidence import (  # noqa: E402
    compare_rp_to_design,
    inspect_rp,
)
from src.app.services.rendering.axure_adapter import AxureRPAdapter  # noqa: E402
from src.app.services.rendering.axure_route import plan_axure_route  # noqa: E402

AXURE_DOM_OUTPUT_SCHEMA_VERSION = "axure-dom-output/1.0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a verified DOM -> Axure RP 8 artifact"
    )
    parser.add_argument("--design", required=True, help="DesignSpec JSON")
    parser.add_argument("--ir", default="", help="optional design-ir/2.0 JSON")
    parser.add_argument("--out", required=True, help="evidence output directory")
    parser.add_argument("--source-kind", default="dom")
    parser.add_argument("--generate-twice", action="store_true")
    parser.add_argument(
        "--page-name",
        action="append",
        default=[],
        help="target-specific page name; repeat once per frame",
    )
    args = parser.parse_args(argv)

    design_path = Path(args.design)
    design = json.loads(design_path.read_text(encoding="utf-8-sig"))
    _apply_page_names(design, args.page_name)
    supplied_ir = None
    if args.ir:
        supplied_ir = json.loads(Path(args.ir).read_text(encoding="utf-8-sig"))
    route = plan_axure_route(
        design,
        source_kind=args.source_kind,
        ir=supplied_ir,
    )

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "axure_design.json", route["design"])
    _write_json(output_dir / "design.ir.json", route["ir"])
    _write_json(output_dir / "route.json", _public_route(route))

    artifact_path = output_dir / "prototype.rp"
    _render(route["design"], artifact_path)
    repeat_path = None
    repeat_sha256 = None
    if args.generate_twice:
        repeat_path = output_dir / "prototype.repeat.rp"
        _render(route["design"], repeat_path)

    inspection = inspect_rp(artifact_path)
    comparison = compare_rp_to_design(inspection, route["design"], route=route)
    artifact_sha256 = inspection["artifact_sha256"]
    if repeat_path is not None:
        repeat_sha256 = hashlib.sha256(repeat_path.read_bytes()).hexdigest()
    deterministic = not args.generate_twice or (
        repeat_sha256 == artifact_sha256
        and repeat_path is not None
        and repeat_path.read_bytes() == artifact_path.read_bytes()
    )
    report = {
        "schema_version": AXURE_DOM_OUTPUT_SCHEMA_VERSION,
        "document_id": route["document_id"],
        "source_kind": route["source_kind"],
        "source": {
            "design": design_path.name,
            "design_sha256": hashlib.sha256(design_path.read_bytes()).hexdigest(),
            "ir": Path(args.ir).name if args.ir else None,
            "axure_design": "axure_design.json",
            "design_route_sha256": route["source_design_sha256"],
            "ir_sha256": route["ir_sha256"],
        },
        "page_names": [
            str(page.get("name") or "") for page in _design_pages(route["design"])
        ],
        "artifact": {
            "name": artifact_path.name,
            "size": artifact_path.stat().st_size,
            "sha256": artifact_sha256,
        },
        "determinism": {
            "enabled": bool(args.generate_twice),
            "repeat_name": repeat_path.name if repeat_path is not None else None,
            "repeat_sha256": repeat_sha256,
            "identical": deterministic,
        },
        "inspection": inspection,
        "comparison": comparison,
        "self_check": inspection["self_check"],
        "integrity": inspection["integrity"],
        "projection": route["projection"],
        "degradations": route["degradations"],
        "acceptance_scope": route["projection"]["acceptance_scope"],
        "acceptance": route["projection"]["acceptance"],
        "limitations": route["limitations"],
        "non_claims": [
            "No Axure visual acceptance is established by this artifact report.",
            "No Axure reload or publish success is established by this report.",
            "No Figma acceptance evidence is transferred.",
            "Reference-only and generated display assets remain non-original.",
        ],
    }
    _write_json(output_dir / "artifact_report.json", report)

    print(f"document_id={route['document_id']}")
    print(f"artifact={artifact_path.resolve()}")
    print(f"sha256={artifact_sha256}")
    print(
        "pages={0} widgets={1} assets={2} comparison_ok={3} deterministic={4}".format(
            inspection["page_count"],
            comparison["widget_count"],
            inspection["asset_count"],
            comparison["ok"],
            deterministic,
        )
    )
    if not comparison["ok"] or not deterministic:
        return 1
    return 0


def _render(design: dict[str, Any], output_path: Path) -> None:
    adapter = AxureRPAdapter(output_path)
    adapter.connect()
    adapter.render_design(design)
    adapter.disconnect()


def _apply_page_names(design: dict[str, Any], names: list[str]) -> None:
    if not names:
        return
    pages = _design_pages(design)
    if len(names) != len(pages):
        raise ValueError(
            f"page name count does not match design: {len(names)} != {len(pages)}"
        )
    for page, name in zip(pages, names):
        page["name"] = name


def _design_pages(design: dict[str, Any]) -> list[dict[str, Any]]:
    pages = design.get("pages")
    if isinstance(pages, list) and pages:
        return [page for page in pages if isinstance(page, dict)]
    return [design]


def _public_route(route: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in route.items() if key not in {"design", "ir"}}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
