"""Independent product-oriented acceptance for the image-to-Figma MVP."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from src.app.services.evidence.dom_figma_acceptance import (
    run_asset_fill_probe,
    run_text_edit_probe,
)
from src.app.services.evidence.image_enrichment_quality import (
    evaluate_image_enrichment,
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
    "region_bad_pixel_ratio_max": 0.05,
    "region_quality_required_for_high_fidelity": True,
    "repair_budget_required_for_high_fidelity": True,
}

IMAGE_MVP_POLICY_V2 = {
    **DEFAULT_POLICY,
    "policy_id": "image-figma-mvp-product/2.0",
    "region_visual_mode": "native-text-and-chrome",
    "chrome_bad_pixel_ratio_max": 0.05,
    "native_text_gate_required": True,
    "native_text_position_px_max": 1,
    "native_text_width_tolerance_ratio": 0.02,
    "native_text_width_tolerance_floor_px": 2,
    "native_text_height_tolerance_ratio": 0.02,
    "native_text_height_tolerance_floor_px": 2,
    "native_text_ink_coverage_min": 0.90,
    "native_text_ink_coverage_max": 1.10,
    "native_text_edge_f1_min": 0.95,
    "native_text_baseline_required": False,
    "legacy_raw_region_visual_informational": True,
}

# Calibrated 2026-11-09 from gold-native-bound/1.0 measurements
# (scripts/measure_gold_bound.py, output/_benchmark_families/gold_bound.json):
# the Figma Make golds themselves score edgeF1 median 0.969 (light-form),
# 0.679 (dark-card-grid) and 0.0 (light-table semantic redesign) under the
# 2.0 thresholds -- i.e. edgeF1 >= 0.95 blocks even the golds, while position
# and size are the genuinely achievable dimensions (gold |dy|<=1px on 75/78
# and 31/51 owners).  Policy 2.1 keeps every 2.0 dimension but moves the
# native-text thresholds onto the measured achievable band.  Policy 2.0
# remains frozen and untouched.
IMAGE_MVP_POLICY_V21 = {
    **IMAGE_MVP_POLICY_V2,
    "policy_id": "image-figma-mvp-product/2.1",
    "native_text_position_px_max": 2,
    "native_text_width_tolerance_ratio": 0.03,
    "native_text_width_tolerance_floor_px": 3,
    "native_text_height_tolerance_ratio": 0.03,
    "native_text_height_tolerance_floor_px": 3,
    "native_text_ink_coverage_min": 0.75,
    "native_text_ink_coverage_max": 1.35,
    "native_text_edge_f1_min": 0.55,
    "calibration": {
        "source": "gold-native-bound/1.0",
        "measured_at": "2026-11-09",
        "gold_edge_f1_median": {
            "light-form": 0.9688,
            "dark-card-grid": 0.6785,
            "light-table": 0.0,
        },
    },
}

_PASSING_REPAIR_STATUSES = {
    "not-needed",
    "pass",
    "converged",
    "no-repair-needed",
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
    fidelity: Mapping[str, Any] | None = None,
    region_quality: Mapping[str, Any] | None = None,
    repair_history: Mapping[str, Any] | None = None,
    region_regression: Mapping[str, Any] | None = None,
    native_text_quality: Mapping[str, Any] | None = None,
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
    raster_image_elements = [
        item
        for item in image_elements
        if item.get("imageBase64") or item.get("displayPayload")
    ]
    expected_assets = int(
        truth.get("expected_asset_count") or len(truth.get("assets") or []) or 0
    )
    claimed_assets = expected_assets if expected_assets else len(raster_image_elements)
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
    high_fidelity = (
        isinstance(fidelity, Mapping) and str(fidelity.get("mode") or "") == "high"
    )
    region_blockers, region_status = _region_visual_status(
        region_quality,
        region_regression,
        threshold=float(resolved_policy["region_bad_pixel_ratio_max"]),
        required=high_fidelity
        and bool(resolved_policy.get("region_quality_required_for_high_fidelity")),
    )
    split_visual = (
        str(resolved_policy.get("region_visual_mode") or "") == "native-text-and-chrome"
    )
    native_text_blockers, native_text_status, chrome_status = (
        _native_text_visual_status(
            native_text_quality,
            required=split_visual
            and high_fidelity
            and bool(resolved_policy.get("native_text_gate_required", True)),
        )
    )
    repair_blockers, repair_status = _repair_budget_status(
        repair_history,
        fidelity=fidelity,
        required=high_fidelity
        and bool(resolved_policy.get("repair_budget_required_for_high_fidelity")),
    )
    dimensions = {
        "text": {"status": text_status, "source": "critical-text"},
        "structure": {"status": structure_status, "source": "text-and-asset-nodes"},
        "edit": {"status": edit_status, "source": "native-text-probe"},
        "asset": {"status": asset_status, "source": "reference-only-display-probe"},
        "fidelity": {
            "status": (
                str(fidelity.get("status") or "not-evaluated")
                if isinstance(fidelity, Mapping)
                else "not-evaluated"
            ),
            "source": "content-geometry-native-audit",
        },
        "repair_budget": {
            "status": repair_status,
            "source": "bounded-repair-history",
        },
        "visual": {
            "status": visual_status,
            "source": "within30-product-metric",
            "within30_pct": within30,
        },
    }
    if split_visual:
        dimensions["legacy_raw_region_visual"] = {
            "status": region_status,
            "source": "same-size-raw-region-metrics",
            "mode": "informational",
        }
        dimensions["native_text_visual"] = {
            "status": native_text_status,
            "source": "critical-native-text-ink-metrics",
        }
        dimensions["chrome_visual"] = {
            "status": chrome_status,
            "source": "text-masked-chrome-metrics",
        }
    else:
        dimensions["region_visual"] = {
            "status": region_status,
            "source": "same-size-region-metrics",
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
    if isinstance(fidelity, Mapping) and fidelity.get("status") != "pass":
        blockers.extend(
            f"fidelity:{blocker}" for blocker in fidelity.get("blockers") or ["blocked"]
        )
    if split_visual:
        blockers.extend(native_text_blockers)
    else:
        blockers.extend(region_blockers)
    blockers.extend(repair_blockers)
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
        "schema_version": (
            "image-figma-mvp-acceptance/2.0"
            if split_visual
            else "image-figma-mvp-acceptance/1.0"
        ),
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
        "fidelity": dict(fidelity) if isinstance(fidelity, Mapping) else None,
        "region_quality": (
            dict(region_quality) if isinstance(region_quality, Mapping) else None
        ),
        "native_text_quality": (
            dict(native_text_quality)
            if isinstance(native_text_quality, Mapping)
            else None
        ),
        "repair_history": (
            dict(repair_history) if isinstance(repair_history, Mapping) else None
        ),
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
    fidelity: Mapping[str, Any] | None = None,
    region_quality: Mapping[str, Any] | None = None,
    repair_history: Mapping[str, Any] | None = None,
    region_regression: Mapping[str, Any] | None = None,
    native_text_quality: Mapping[str, Any] | None = None,
    repair_status: str | None = None,
    regions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach real Figma/export identity to the independent MVP evaluation."""
    reference = Path(reference_path)
    export = Path(export_path)
    metrics = visual_similarity_metrics(reference, export)
    fidelity_truth = {
        **dict(truth),
        "reference_image_path": str(reference),
    }
    resolved_fidelity = (
        dict(fidelity)
        if isinstance(fidelity, Mapping)
        else evaluate_image_enrichment(
            fidelity_truth,
            dict(design),
            dict(readback_tree),
            export,
        )
    )
    resolved_regions = region_quality
    if resolved_regions is None and regions:
        from src.app.services.evidence.region_quality import (
            evaluate_region_quality,
        )

        resolved_regions = evaluate_region_quality(reference, export, regions)
    resolved_repair = repair_history
    if resolved_repair is None and repair_status:
        resolved_repair = {"status": repair_status}
    resolved_policy = {**DEFAULT_POLICY, **(policy or truth.get("policy") or {})}
    if (
        str(resolved_policy.get("region_visual_mode") or "")
        == "native-text-and-chrome"
        and native_text_quality is None
        and regions
    ):
        from src.app.services.evidence.native_text_quality import (
            build_native_text_quality,
        )

        native_text_quality = build_native_text_quality(
            design,
            readback_tree,
            str(reference),
            str(export),
            list(regions),
            gate_policy=resolved_policy,
            critical_texts=[
                str(value)
                for value in truth.get("critical_texts") or []
                if str(value).strip()
            ],
        )
    evaluation = evaluate_image_mvp(
        design=design,
        truth=truth,
        readback_tree=readback_tree,
        visual_metrics=metrics,
        text_probe=text_probe,
        asset_probe=asset_probe,
        image_ir=image_ir,
        policy=resolved_policy,
        fidelity=resolved_fidelity,
        region_quality=resolved_regions,
        repair_history=resolved_repair,
        region_regression=region_regression,
        native_text_quality=native_text_quality,
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


def _native_text_visual_status(
    native_text_quality: Mapping[str, Any] | None,
    *,
    required: bool,
) -> tuple[list[str], str, str]:
    if not isinstance(native_text_quality, Mapping):
        return (
            (["native-text:missing"], "fail", "missing")
            if required
            else ([], "not-evaluated", "not-evaluated")
        )
    gate = native_text_quality.get("gate")
    if not isinstance(gate, Mapping):
        return (
            (["native-text:gate-missing"], "fail", "missing")
            if required
            else ([], "not-evaluated", "not-evaluated")
        )
    native = gate.get("nativeText")
    chrome = gate.get("chrome")
    native_status = (
        str(native.get("status") or "fail") if isinstance(native, Mapping) else "fail"
    )
    chrome_status = (
        str(chrome.get("status") or "fail") if isinstance(chrome, Mapping) else "fail"
    )
    blockers = [
        str(value)
        for value in gate.get("blockers") or []
        if str(value).strip()
    ]
    if not blockers and (
        native_status != "pass" or chrome_status != "pass"
    ):
        blockers.append("native-text:gate")
    blockers = list(dict.fromkeys(blockers))
    return blockers, native_status, chrome_status


def _region_visual_status(
    region_quality: Mapping[str, Any] | None,
    region_regression: Mapping[str, Any] | None,
    *,
    threshold: float,
    required: bool,
) -> tuple[list[str], str]:
    blockers: list[str] = []
    evaluated = False
    if isinstance(region_quality, Mapping):
        evaluated = True
        if str(region_quality.get("status") or "") == "blocked":
            blockers.append("region-visual")
        if region_quality.get("size_match") is False:
            blockers.append("region-visual:size")
        for region_id, metrics in (region_quality.get("regions") or {}).items():
            if not isinstance(metrics, Mapping):
                continue
            regressed = bool(metrics.get("regressed"))
            ratio = _number(metrics.get("bad_pixel_ratio"))
            if regressed or (ratio is not None and ratio > threshold):
                blockers.append(f"region-visual:{region_id}")
    if isinstance(region_regression, Mapping):
        evaluated = True
        for region_id, value in region_regression.items():
            if isinstance(value, Mapping):
                regressed = bool(value.get("regressed"))
                ratio = _number(value.get("bad_pixel_ratio") or value.get("regression"))
            else:
                regressed = False
                ratio = _number(value)
            if regressed or (ratio is not None and ratio > threshold):
                blockers.append(f"region-visual:{region_id}")
    if required and not evaluated:
        blockers.append("region-visual:missing")
    blockers = list(dict.fromkeys(blockers))
    return blockers, "fail" if blockers else "pass" if evaluated else "not-evaluated"


def _repair_budget_status(
    repair_history: Mapping[str, Any] | None,
    *,
    fidelity: Mapping[str, Any] | None,
    required: bool,
) -> tuple[list[str], str]:
    status = ""
    source: Mapping[str, Any] | None = None
    if isinstance(repair_history, Mapping):
        source = repair_history
        status = str(repair_history.get("status") or "")
    elif isinstance(fidelity, Mapping) and isinstance(fidelity.get("repair"), Mapping):
        source = fidelity["repair"]
        status = str(source.get("status") or "")
    if not status:
        return (
            (["repair-budget:missing"], "fail") if required else ([], "not-evaluated")
        )
    blockers: list[str] = []
    if status not in _PASSING_REPAIR_STATUSES:
        blockers.append("repair-budget")
    budget = source.get("budget") if isinstance(source, Mapping) else None
    if isinstance(budget, Mapping):
        rounds = _number(source.get("rounds"))
        extra_calls = _number(source.get("extra_calls"))
        max_rounds = _number(budget.get("max_rounds"))
        max_extra_calls = _number(budget.get("max_extra_calls"))
        if (rounds is not None and max_rounds is not None and rounds > max_rounds) or (
            extra_calls is not None
            and max_extra_calls is not None
            and extra_calls > max_extra_calls
        ):
            blockers.append("repair-budget")
    blockers = list(dict.fromkeys(blockers))
    return blockers, "fail" if blockers else "pass"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
            require_geometry_update=False,
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
