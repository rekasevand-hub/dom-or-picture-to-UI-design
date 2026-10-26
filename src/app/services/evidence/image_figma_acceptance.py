"""Independent product-oriented acceptance for the image-to-Figma MVP."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from src.app.services.evidence.dom_figma_acceptance import (
    run_asset_fill_probe,
    run_text_edit_probe,
)


DEFAULT_POLICY = {
    "policy_id": "image-figma-mvp-product/1.0",
    "frozen": True,
    "visual_within30_min_pct": 90.0,
    "require_size_match": True,
    "critical_text_required": True,
    "native_text_required": True,
    "claimed_asset_replacement_required": True,
    "original_asset_identity_required": False,
    "adaptive_flow_required": False,
}


def visual_similarity_metrics(
    reference_path: str | Path,
    render_path: str | Path,
) -> dict[str, Any]:
    """Measure the user-approved 90% product metric without masking failures."""
    import cv2
    import numpy as np

    reference = cv2.imread(str(reference_path))
    render = cv2.imread(str(render_path))
    if reference is None or render is None:
        return {
            "status": "not-evaluated",
            "reason": "image-unreadable",
            "size_match": False,
            "within30_pct": 0.0,
            "bad_pixel_ratio": 1.0,
        }
    size_match = reference.shape[:2] == render.shape[:2]
    scored = render
    if not size_match:
        scored = cv2.resize(render, (reference.shape[1], reference.shape[0]))
    diff = np.abs(scored.astype(np.int16) - reference.astype(np.int16))
    max_diff = diff.max(axis=2)
    total = int(max_diff.size)
    bad = int((max_diff > 30).sum())
    gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    ink = gray < 200
    return {
        "status": "measured",
        "reference": str(reference_path),
        "render": str(render_path),
        "size_match": size_match,
        "reference_shape": list(reference.shape),
        "render_shape": list(render.shape),
        "mean": float(diff.mean()),
        "ink_mean": float(diff[..., 0][ink].mean()) if ink.any() else 0.0,
        "over30_pct": float((max_diff > 30).mean() * 100),
        "bad_pixel_count": bad,
        "bad_pixel_ratio": float(bad / total) if total else 0.0,
        "within30_pct": float((total - bad) / total * 100) if total else 0.0,
    }


def evaluate_image_mvp(
    *,
    design: Mapping[str, Any],
    truth: Mapping[str, Any],
    readback_tree: Mapping[str, Any],
    visual_metrics: Mapping[str, Any],
    text_probe: Mapping[str, Any],
    asset_probe: Mapping[str, Any],
    image_ir: Mapping[str, Any],
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate content, structure, editability, assets and visual usability."""
    resolved_policy = {**DEFAULT_POLICY, **(policy or truth.get("policy") or {})}
    actual_texts = [
        str(node.get("characters") or "")
        for node in _iter_nodes(readback_tree)
        if node.get("type") == "TEXT" and _normalize_critical(node.get("characters"))
    ]
    critical_texts = [
        str(value) for value in truth.get("critical_texts") or [] if str(value).strip()
    ]
    rows = [
        {
            "text": text,
            "present": any(_critical_matches(text, actual) for actual in actual_texts),
        }
        for text in critical_texts
    ]
    critical_passed = bool(rows) and all(row["present"] for row in rows)
    if not rows and resolved_policy.get("critical_text_required", True):
        critical_passed = False
    text_status = "pass" if critical_passed else "fail"

    native_text_required = bool(resolved_policy.get("native_text_required", True))
    native_text_present = bool(actual_texts)
    edit_probe_passed = str(text_probe.get("status") or "") == "pass"
    edit_status = (
        "pass"
        if (not native_text_required or (native_text_present and edit_probe_passed))
        else "fail"
    )

    design_elements = [
        item for item in design.get("elements") or [] if isinstance(item, Mapping)
    ]
    image_elements = [
        item for item in design_elements if str(item.get("type")) in {"image", "avatar"}
    ]
    expected_assets = int(truth.get("expected_asset_count") or 0)
    claimed_assets = max(expected_assets, len(image_elements))
    asset_ir = [
        item for item in image_ir.get("assets") or [] if isinstance(item, Mapping)
    ]
    reference_only = [
        item
        for item in asset_ir
        if item.get("reference_only") and not item.get("original")
    ]
    asset_probe_passed = str(asset_probe.get("status") or "") == "pass"
    if claimed_assets == 0:
        asset_status = "not-required"
    elif asset_probe_passed and len(reference_only) >= claimed_assets:
        asset_status = "pass"
    else:
        asset_status = "fail"

    within30 = float(visual_metrics.get("within30_pct") or 0.0)
    size_passed = (
        bool(visual_metrics.get("size_match"))
        if resolved_policy.get("require_size_match", True)
        else True
    )
    visual_passed = size_passed and within30 >= float(
        resolved_policy["visual_within30_min_pct"]
    )
    visual_status = "pass" if visual_passed else "fail"

    structure_status = (
        "pass"
        if critical_passed
        and bool(design_elements)
        and (claimed_assets == 0 or len(image_elements) >= claimed_assets)
        else "fail"
    )
    dimensions = {
        "text": {"status": text_status, "source": "critical-text"},
        "structure": {"status": structure_status, "source": "text-and-asset-nodes"},
        "edit": {"status": edit_status, "source": "native-text-probe"},
        "asset": {"status": asset_status, "source": "reference-only-display-probe"},
        "visual": {
            "status": visual_status,
            "source": "within30-product-metric",
            "within30_pct": within30,
        },
    }
    blockers: list[str] = []
    if text_status != "pass":
        blockers.append("critical-text")
    if structure_status != "pass":
        blockers.append("structure")
    if edit_status != "pass":
        blockers.append("edit")
    if asset_status not in {"pass", "not-required"}:
        blockers.append("asset")
    if visual_status != "pass":
        blockers.append("visual")
    status = "pass" if not blockers else "blocked-fail"

    asset_claims = {
        "original_asset": any(item.get("original") for item in asset_ir),
        "reference_only_display": bool(reference_only),
        "generated_asset": any(item.get("generated") for item in asset_ir),
        "display_replacement_claimed": claimed_assets > 0,
    }
    limitations = list(image_ir.get("limitations") or [])
    if asset_claims["original_asset"]:
        limitations.append("An original asset claim was observed and requires review.")
    return {
        "schema_version": "image-figma-mvp-acceptance/1.0",
        "status": status,
        "policy": dict(resolved_policy),
        "dimensions": dimensions,
        "critical_text": {
            "status": text_status,
            "required_count": len(rows),
            "matched_count": sum(row["present"] for row in rows),
            "rows": rows,
        },
        "visual": dict(visual_metrics),
        "asset_claims": asset_claims,
        "blockers": blockers,
        "limitations": list(dict.fromkeys(limitations)),
        "non_claims": [
            "Original asset identity is not recovered.",
            "Original font identity and glyph outlines are not verified.",
            "Adaptive Auto Layout is not verified; flow remains candidate.",
            "Hidden content outside the screenshot is unknown.",
        ],
        "evidence_hash_inputs": {
            "design_sha256": _json_sha256(design),
            "image_ir_sha256": _json_sha256(image_ir),
            "readback_sha256": _json_sha256(readback_tree),
        },
    }


def build_image_acceptance_report(
    *,
    design: Mapping[str, Any],
    truth: Mapping[str, Any],
    readback_tree: Mapping[str, Any],
    reference_path: str | Path,
    export_path: str | Path,
    text_probe: Mapping[str, Any],
    asset_probe: Mapping[str, Any],
    image_ir: Mapping[str, Any],
    run_summary: Mapping[str, Any],
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach real Figma/export identity to the independent MVP evaluation."""
    reference = Path(reference_path)
    export = Path(export_path)
    metrics = visual_similarity_metrics(reference, export)
    evaluation = evaluate_image_mvp(
        design=design,
        truth=truth,
        readback_tree=readback_tree,
        visual_metrics=metrics,
        text_probe=text_probe,
        asset_probe=asset_probe,
        image_ir=image_ir,
        policy=policy,
    )
    export_summary = {
        "exists": export.is_file(),
        "status": "pass" if export.is_file() else "missing",
        "path": str(export.resolve()) if export.exists() else None,
        "byte_length": export.stat().st_size if export.is_file() else None,
        "sha256": _file_sha256(export) if export.is_file() else None,
    }
    report = {
        **evaluation,
        "sample_id": str(truth.get("sample_id") or ""),
        "frame_id": run_summary.get("frame_id"),
        "figma_runtime": (
            "observed"
            if str(run_summary.get("status") or "") == "captured-figma-evidence"
            else "blocked"
        ),
        "run_status": run_summary.get("status"),
        "export": export_summary,
        "artifact_sha256": {
            "reference.png": _file_sha256(reference) if reference.is_file() else None,
            "export.png": export_summary["sha256"],
        },
    }
    if report["figma_runtime"] != "observed" or not export_summary["exists"]:
        blockers = list(report.get("blockers") or [])
        if "figma-runtime" not in blockers:
            blockers.append("figma-runtime")
        if not export_summary["exists"] and "export" not in blockers:
            blockers.append("export")
        report["blockers"] = blockers
        report["status"] = "blocked-environment"
    return report


def run_image_figma_evidence(
    design: Mapping[str, Any],
    *,
    output_dir: str | Path,
    sample_id: str,
    adapter_factory: Callable[[], Any],
    readback_depth: int = 8,
) -> dict[str, Any]:
    """Write one image design to Figma and retain readback/export/probe bytes."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    adapter = None
    try:
        adapter = adapter_factory()
        adapter.connect()
        adapter.render_design(dict(design))
        frame_id = getattr(adapter, "frame_id", None)
        if not frame_id:
            raise RuntimeError("Figma adapter did not expose the created frame ID")
        readback = adapter._send(
            "get_node_tree",
            {"nodeId": frame_id, "depth": readback_depth},
        )
        _write_json(output / "readback.json", readback)
        exported = adapter._send(
            "export_frame",
            {"nodeId": frame_id, "scale": 1},
        )
        encoded = str(exported.get("base64") or "")
        if not encoded:
            raise RuntimeError("Figma export returned no PNG bytes")
        (output / "export.png").write_bytes(base64.b64decode(encoded))
        text_probe = run_text_edit_probe(
            adapter,
            frame_id=frame_id,
            readback=readback,
            depth=readback_depth,
        )
        asset_probe, image_report = run_asset_fill_probe(
            adapter,
            frame_id=frame_id,
            readback=readback,
            depth=readback_depth,
        )
        final_readback = adapter._send(
            "get_node_tree",
            {"nodeId": frame_id, "depth": readback_depth},
        )
        _write_json(output / "readback_after_probes.json", final_readback)
        _write_json(output / "text_edit_probe.json", text_probe)
        _write_json(output / "asset_probe.json", asset_probe)
        _write_json(output / "image_report.json", image_report)
        summary = {
            "schema_version": "image-figma-real-run/1.0",
            "status": "captured-figma-evidence",
            "sample_id": sample_id,
            "frame_id": frame_id,
            "readback_depth": readback_depth,
            "artifacts": {
                "readback": "readback.json",
                "final_readback": "readback_after_probes.json",
                "export": "export.png",
                "text_edit_probe": "text_edit_probe.json",
                "asset_probe": "asset_probe.json",
                "image_report": "image_report.json",
            },
            "text_edit_probe": text_probe,
            "asset_probe": asset_probe,
            "calls": list(getattr(adapter, "calls", [])),
        }
    except Exception as exc:  # noqa: BLE001 - environment evidence is data
        summary = {
            "schema_version": "image-figma-real-run/1.0",
            "status": "blocked-environment",
            "sample_id": sample_id,
            "frame_id": getattr(adapter, "frame_id", None),
            "error": f"{type(exc).__name__}: {exc}",
            "calls": list(getattr(adapter, "calls", [])),
        }
    finally:
        if adapter is not None:
            try:
                adapter.disconnect()
            except Exception:  # noqa: BLE001 - preserve primary evidence
                pass
    _write_json(output / "summary.json", summary)
    return summary


def _iter_nodes(root: Mapping[str, Any]):
    if not isinstance(root, Mapping):
        return
    yield root
    for child in root.get("children") or []:
        if isinstance(child, Mapping):
            yield from _iter_nodes(child)


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _critical_matches(expected: Any, actual: Any) -> bool:
    expected_text = _normalize_critical(expected)
    actual_text = _normalize_critical(actual)
    if not expected_text or not actual_text:
        return False
    if expected_text in actual_text:
        return True
    if any("\u4e00" <= char <= "\u9fff" for char in expected_text):
        return _normalize(expected_text) in _normalize(actual_text)
    return False


def _normalize_critical(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _json_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
