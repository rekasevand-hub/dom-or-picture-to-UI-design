"""The production gate: every design leaves through `design-ir/2.0`.

Two artefacts, always the same two names, whichever tool is downstream:

* ``13_design_ir.json`` — the output-neutral projection of the design that was
  actually emitted.  It is written *before* the target renders, so a failed
  emission still leaves the contract behind;
* ``13_degradations.json`` — what the target cannot carry, with the node ids that
  asked for it, plus every capability gap the target has (an empty ``degradations``
  list next to a full ``target_gaps`` list says "checked, nothing lost").

The gate is **reporting by default**: a design that violates the contract is
recorded and the render continues, because a pipeline that stops on a contract
warning is worse than one that logs it.  ``--strict-ir`` turns the same finding
into a non-zero exit, which is what a release job wants.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.app.services.contracts.output_ir import (
    OUTPUT_IR_SCHEMA_VERSION,
    build_output_ir,
    degradations_for,
    project_for_output,
    target_gaps,
    validate_output_ir,
)

GATE_SCHEMA_VERSION = "design-ir-gate/1.0"
LEDGER_SCHEMA_VERSION = "design-ir-degradations/1.0"
IR_NAME = "13_design_ir.json"
LEDGER_NAME = "13_degradations.json"
#: 只有这两个后端有独立的能力矩阵；svg/jsdesign 等走老路，不装作过了闸门。
GATED_TARGETS = ("figma", "axure")


class DesignIRGateError(RuntimeError):
    """Raised by ``--strict-ir`` when the design violates the IR contract."""

    def __init__(self, issues: list[dict[str, Any]], target: str) -> None:
        self.issues = issues
        self.target = target
        codes = ", ".join(sorted({str(issue.get("code") or "") for issue in issues}))
        super().__init__(f"design-ir contract violated for {target}: {codes}")


def gate_design_for_output(
    design: Mapping[str, Any],
    *,
    target: str,
    source_kind: str,
    out_dir: str | Path,
    reference: Mapping[str, Any] | None = None,
    strict: bool = False,
    ir: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one design onto ``target`` and persist the two artefacts."""
    normalized = str(target or "").strip().lower()
    output_dir = Path(out_dir)
    if normalized not in GATED_TARGETS:
        return {
            "schema_version": GATE_SCHEMA_VERSION,
            "status": "not-gated",
            "target": normalized,
            "reason": f"no capability profile for target: {normalized or 'unknown'}",
        }
    output_ir = (
        dict(ir)
        if ir is not None
        else build_output_ir(design, source_kind=source_kind, reference=reference)
    )
    issues = validate_output_ir(output_ir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ir_path = output_dir / IR_NAME
    ledger_path = output_dir / LEDGER_NAME
    _write_json(ir_path, output_ir)

    report: dict[str, Any] = {
        "schema_version": GATE_SCHEMA_VERSION,
        "target": normalized,
        "source_kind": str(source_kind or ""),
        "ir_schema_version": OUTPUT_IR_SCHEMA_VERSION,
        "document_id": output_ir.get("document_id"),
        "ir_path": IR_NAME,
        "ir_sha256": hashlib.sha256(ir_path.read_bytes()).hexdigest(),
        "degradations_path": LEDGER_NAME,
        "issues": issues,
        "strict": bool(strict),
    }
    if issues:
        report["status"] = "invalid"
        ledger = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "gate": GATE_SCHEMA_VERSION,
            "target": normalized,
            "document_id": output_ir.get("document_id"),
            "status": "invalid",
            "issues": issues,
            "degradations": [],
            "target_gaps": target_gaps(normalized),
        }
        _write_json(ledger_path, ledger)
        if strict:
            raise DesignIRGateError(issues, normalized)
        return report

    projection = project_for_output(output_ir, normalized)
    degradations = degradations_for(output_ir, projection)
    affected = sorted(
        {
            node_id
            for row in degradations
            for node_id in row.get("source_node_ids") or []
            if node_id
        }
    )
    ledger = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "gate": GATE_SCHEMA_VERSION,
        "target": normalized,
        "document_id": output_ir.get("document_id"),
        "status": "pass",
        "capability_version": projection.get("capability_version"),
        "acceptance_scope": projection.get("acceptance_scope"),
        "can_claim_complete": bool(projection.get("can_claim_complete")),
        "required_features": sorted(output_ir.get("required_features") or []),
        "supported_features": list(projection.get("supported_features") or []),
        "unsupported_features": list(projection.get("unsupported_features") or []),
        "degradations": degradations,
        "target_gaps": target_gaps(normalized),
        "counts": {
            "frames": len(output_ir.get("frames") or []),
            "nodes": sum(
                len(frame.get("nodes") or []) for frame in output_ir.get("frames") or []
            ),
            "degraded_features": len(degradations),
            "affected_nodes": len(affected),
        },
        "blocked_claims": list(projection.get("blocked_claims") or []),
    }
    _write_json(ledger_path, ledger)
    report.update(
        {
            "status": "pass",
            "can_claim_complete": ledger["can_claim_complete"],
            "acceptance_scope": ledger["acceptance_scope"],
            "required_features": ledger["required_features"],
            "unsupported_features": ledger["unsupported_features"],
            "degradations": degradations,
            "counts": ledger["counts"],
        }
    )
    return report


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
