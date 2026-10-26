"""Frozen real-site DOM to Figma acceptance helpers."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from src.app.services.evidence.dom_figma_text_metrics import (
    build_figma_text_metrics,
)
from src.app.services.evidence.dom_quality_corpus import validate_corpus
from src.app.services.som.annotate import annotate_som
from src.app.services.som.direct_design import build_direct_design
from src.app.services.structure.graph import (
    assign_ids,
    assign_parent_depth,
    save_graph,
)
from src.app.services.structure.generated_icon_recovery import (
    generate_icon_approximations as generate_design_icon_approximations,
)
from src.app.services.structure.network_asset_recovery import (
    recover_network_assets as recover_design_network_assets,
)
from src.app.services.structure.providers.base import ProviderContext
from src.app.services.structure.providers.dom import DomProvider
from src.app.services.structure.site_profiles import load_profile
from src.app.services.rendering.figma_acceptance import accept_output


def build_frozen_sample_design(
    corpus: Mapping[str, Any],
    capture_root: str | Path,
    sample_id: str,
    output_dir: str | Path,
    *,
    canvas_origin: tuple[float, float] = (1600, 0),
    recover_network_assets: bool = False,
    generate_icon_approximations: bool = False,
) -> dict[str, Any]:
    """Build one D008 DesignSpec from frozen capture artifacts only."""
    errors = validate_corpus(corpus)
    if errors:
        raise ValueError(f"invalid frozen corpus: {errors}")
    sample = next(
        (
            item
            for item in corpus.get("samples") or []
            if isinstance(item, Mapping) and item.get("sample_id") == sample_id
        ),
        None,
    )
    if sample is None:
        raise ValueError(f"unknown frozen sample: {sample_id}")
    capture_dir = Path(capture_root) / sample_id
    dom_path = capture_dir / "00_dom.json"
    screenshot_path = capture_dir / "00_screenshot.png"
    if not dom_path.is_file() or not screenshot_path.is_file():
        raise FileNotFoundError(
            f"frozen sample artifacts are incomplete: {capture_dir}"
        )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with Image.open(screenshot_path) as screenshot:
        width, height = screenshot.size
    environment = corpus.get("environment") or {}
    viewport = environment.get("viewport") or {"width": width, "height": height}

    provider = DomProvider()
    graph = provider.run(
        ProviderContext(
            image_path=str(screenshot_path),
            image_w=width,
            image_h=height,
            route="dom",
            output_dir=str(output),
            dom_path=str(dom_path),
            url=str(sample.get("url") or ""),
        )
    )
    assign_ids(graph)
    assign_parent_depth(graph)
    graph.setdefault("provenance", {})
    graph["provenance"].update(
        {
            "url": sample.get("url"),
            "requested_route": "dom",
            "fallbacks": [],
            "capture": {
                "device_scale_factor": environment.get("device_scale_factor", 1),
                "viewport": viewport,
                "canvas_size": [width, height],
                "source": "frozen-dom-quality-capture",
                "sample_id": sample_id,
            },
        }
    )
    save_graph(graph, str(output / "10_pagegraph.json"))
    som = annotate_som(graph, str(output))
    dom_nodes = json.loads(dom_path.read_text(encoding="utf-8"))
    design = build_direct_design(
        som,
        load_profile(str(sample.get("url") or "")),
        dom_nodes,
    )
    design["name"] = f"D008 {sample_id} DOM Real Figma Acceptance"
    design.setdefault("canvas", {})
    design["canvas"]["width"] = width
    design["canvas"]["height"] = height
    design["canvas"]["x"] = float(canvas_origin[0])
    design["canvas"]["y"] = float(canvas_origin[1])
    asset_recovery = None
    if recover_network_assets:
        asset_recovery = recover_design_network_assets(
            design,
            page_url=str(sample.get("url") or ""),
            output_dir=output / "asset_recovery",
        )
        design = asset_recovery.pop("design")
    icon_generation = None
    if generate_icon_approximations:
        icon_generation = generate_design_icon_approximations(
            design,
            output_dir=output / "icon_generation",
        )
        design = icon_generation.pop("design")
    design_hash = _json_sha256(design)
    _write_json(output / "design.json", design)
    metadata = {
        "schema_version": "dom-figma-acceptance-sample/1.0",
        "sample_id": sample_id,
        "site": sample.get("site"),
        "url": sample.get("url"),
        "corpus_id": corpus.get("corpus_id"),
        "corpus_sha256": corpus.get("corpus_sha256"),
        "thresholds_sha256": corpus.get("thresholds_sha256"),
        "source_fingerprint": sample.get("fingerprint"),
        "dom_sha256": _file_sha256(dom_path),
        "screenshot_sha256": _file_sha256(screenshot_path),
        "screenshot_size": [width, height],
        "design_sha256": design_hash,
        "canvas_origin": [float(canvas_origin[0]), float(canvas_origin[1])],
        "counts": {
            "dom_nodes": len(dom_nodes),
            "containers": len(design.get("containers") or som.get("containers") or []),
            "elements": len(design.get("elements") or []),
            "text_elements": sum(
                item.get("type") == "text" for item in design.get("elements") or []
            ),
            "image_elements": sum(
                item.get("type") == "image" for item in design.get("elements") or []
            ),
        },
        "artifacts": {
            "design": "design.json",
            "pagegraph": "10_pagegraph.json",
            "som": "11_som.json",
            "screenshot": str(screenshot_path),
            "dom": str(dom_path),
            **(
                {
                    "asset_recovery": "asset_recovery/source_probes.json",
                }
                if asset_recovery is not None
                else {}
            ),
            **(
                {
                    "generated_icons": "icon_generation/generated_icons.json",
                }
                if icon_generation is not None
                else {}
            ),
        },
        **(
            {
                "asset_recovery": {
                    "status_counts": asset_recovery.get("status_counts") or {},
                    "verified_url_count": asset_recovery.get("verified_url_count"),
                    "recovered_use_count": asset_recovery.get("recovered_use_count"),
                }
            }
            if asset_recovery is not None
            else {}
        ),
        **(
            {
                "icon_generation": {
                    "generated_count": icon_generation.get("generated_count"),
                    "generator": icon_generation.get("generator"),
                    "model": icon_generation.get("model"),
                }
            }
            if icon_generation is not None
            else {}
        ),
    }
    _write_json(output / "sample_metadata.json", metadata)
    return {
        "design": design,
        "metadata": metadata,
        "asset_recovery": asset_recovery,
        "icon_generation": icon_generation,
    }


def run_real_figma_acceptance(
    design: Mapping[str, Any],
    *,
    output_dir: str | Path,
    sample_id: str,
    adapter_factory: Callable[[], Any],
    readback_depth: int = 8,
) -> dict[str, Any]:
    """Write one frame and capture real readback, export and restore probes."""
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
        _write_json(output / "text_edit_probe.json", text_probe)
        _write_json(output / "asset_probe.json", asset_probe)
        _write_json(output / "image_report.json", image_report)
        _write_json(output / "readback_after_probes.json", final_readback)
        summary = {
            "schema_version": "dom-figma-real-run/1.0",
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
            "schema_version": "dom-figma-real-run/1.0",
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


def run_text_edit_probe(
    adapter: Any,
    *,
    frame_id: str,
    readback: Mapping[str, Any],
    depth: int = 8,
) -> dict[str, Any]:
    nodes = _flatten_nodes(readback)
    target = next(
        (
            node
            for node in nodes
            if node.get("type") == "TEXT" and str(node.get("characters") or "").strip()
        ),
        None,
    )
    if target is None:
        return {"status": "not-evaluated", "reason": "native-text-not-found"}
    before = _node_snapshot(target)
    edited = before["characters"] + " D008 EDIT"
    adapter.set_text(before["node_id"], edited)
    edited_tree = adapter._send(
        "get_node_tree",
        {"nodeId": frame_id, "depth": depth},
    )
    edited_node = _find_node(edited_tree, before["node_id"])
    after_edit = _node_snapshot(edited_node) if edited_node else {}
    adapter.set_text(before["node_id"], before["characters"])
    restored_tree = adapter._send(
        "get_node_tree",
        {"nodeId": frame_id, "depth": depth},
    )
    restored_node = _find_node(restored_tree, before["node_id"])
    after_restore = _node_snapshot(restored_node) if restored_node else {}
    checks = {
        "node_type_preserved": after_edit.get("node_type") == before["node_type"],
        "characters_updated": after_edit.get("characters") == edited,
        "font_preserved": after_edit.get("font") == before["font"],
        "geometry_updated": _geometry_changed(before, after_edit),
        "restored": _snapshot_restored(before, after_restore),
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "node_id": before["node_id"],
        "before": before,
        "after_edit": after_edit,
        "after_restore": after_restore,
        **checks,
        "parent_layout_propagation": "not-evaluated",
    }


def run_asset_fill_probe(
    adapter: Any,
    *,
    frame_id: str,
    readback: Mapping[str, Any],
    depth: int = 8,
) -> tuple[dict[str, Any], dict[str, Any]]:
    report = adapter.image_fill_report(frame_id)
    fills = [
        item
        for item in report.get("fills") or []
        if isinstance(item, dict) and item.get("byteBase64")
    ]
    if not fills:
        return (
            {"status": "not-evaluated", "reason": "image-fill-not-found"},
            report,
        )
    target = fills[0]
    node_id = str(target.get("nodeId") or "")
    before_tree = adapter._send(
        "get_node_tree",
        {"nodeId": frame_id, "depth": depth},
    )
    before_node = _find_node(before_tree, node_id) or {}
    replacement = _replacement_png_base64()
    adapter.replace_image_fill(
        node_id,
        replacement,
        fill_index=int(target.get("fillIndex") or 0),
    )
    changed_tree = adapter._send(
        "get_node_tree",
        {"nodeId": frame_id, "depth": depth},
    )
    changed_node = _find_node(changed_tree, node_id) or {}
    adapter.replace_image_fill(
        node_id,
        str(target["byteBase64"]),
        fill_index=int(target.get("fillIndex") or 0),
    )
    restored_tree = adapter._send(
        "get_node_tree",
        {"nodeId": frame_id, "depth": depth},
    )
    restored_node = _find_node(restored_tree, node_id) or {}
    final_report = adapter.image_fill_report(frame_id)
    before_fill = _image_fill(before_node)
    changed_fill = _image_fill(changed_node)
    restored_fill = _image_fill(restored_node)
    checks = {
        "node_type_preserved": (restored_node.get("type") == before_node.get("type")),
        "image_hash_changed": (
            bool(changed_fill.get("imageHash"))
            and changed_fill.get("imageHash") != before_fill.get("imageHash")
        ),
        "scale_mode_preserved": (
            changed_fill.get("scaleMode") == before_fill.get("scaleMode")
            and restored_fill.get("scaleMode") == before_fill.get("scaleMode")
        ),
        "restored": (restored_fill.get("imageHash") == before_fill.get("imageHash")),
    }
    return (
        {
            "status": "pass" if all(checks.values()) else "fail",
            "node_id": node_id,
            "fill_index": int(target.get("fillIndex") or 0),
            "before": before_fill,
            "after_edit": changed_fill,
            "after_restore": restored_fill,
            **checks,
        },
        final_report,
    )


def build_acceptance_report(
    corpus: Mapping[str, Any],
    *,
    sample_root: str | Path,
    run_root: str | Path,
) -> dict[str, Any]:
    """Evaluate captured Figma evidence against the frozen sample contract."""
    sample_dir = Path(sample_root)
    run = Path(run_root)
    metadata = _read_json(sample_dir / "sample_metadata.json")
    design = _read_json(sample_dir / "design.json")
    run_summary = _read_json(run / "summary.json")
    readback = _read_json(run / "readback.json")
    text_probe = _read_json(run / "text_edit_probe.json")
    asset_probe = _read_json(run / "asset_probe.json")
    image_report = _read_json(run / "image_report.json")
    font_report_path = run / "font_report.json"
    font_report = _read_json(font_report_path) if font_report_path.is_file() else None
    sample_id = str(metadata.get("sample_id") or "")
    sample = next(
        (
            item
            for item in corpus.get("samples") or []
            if isinstance(item, Mapping) and item.get("sample_id") == sample_id
        ),
        None,
    )
    if sample is None:
        raise ValueError(f"sample is not in frozen corpus: {sample_id}")
    reference_path = Path(
        str((metadata.get("artifacts") or {}).get("screenshot") or "")
    )
    export_path = run / "export.png"
    visual_metrics = _visual_metrics(reference_path, export_path)
    thresholds = corpus.get("thresholds") or {}
    visual_thresholds = thresholds.get("visual") or {}
    visual_policy = {
        "policy_id": "dom-quality-real-sites/1.0",
        "max_mean": float(visual_thresholds.get("max_mean", float("inf"))),
        "max_ink_mean": float(visual_thresholds.get("max_ink_mean", float("inf"))),
        "max_over30_pct": float(visual_thresholds.get("max_over30_pct", float("inf"))),
        "require_size_match": bool(visual_thresholds.get("require_size_match", True)),
        "gate_bad_pixel_count": False,
    }
    text_thresholds = thresholds.get("text") or {}
    text_metrics = build_figma_text_metrics(
        design,
        readback,
        baseline_tolerance_px=float(text_thresholds.get("baseline_tolerance_px", 1.0)),
        linebreak_match_rate=float(text_thresholds.get("linebreak_match_rate", 0.98)),
        glyph_identity_policy=str(
            text_thresholds.get("glyph_identity_status") or "explicit-not-evaluated"
        ),
    )
    truth = {
        "expected_texts": list(sample.get("required_text") or []),
        "forbidden_text": list(sample.get("forbidden_text") or []),
        "expected_asset_count": sum(
            item.get("type") == "image" for item in design.get("elements") or []
        ),
        "native_text_required": any(
            item.get("type") == "text" for item in design.get("elements") or []
        ),
    }
    structure_thresholds = thresholds.get("structure") or {}
    decision = accept_output(
        {
            "design": design,
            "truth": truth,
            "readback_tree": readback,
            "font_report": font_report,
            "visual_metrics": visual_metrics,
            "visual_policy": visual_policy,
            "edit_probe": text_probe,
            "asset_probe": asset_probe,
            "image_report": image_report,
            "text_dimensions": text_metrics,
            "policy": {
                "position_tolerance_px": float(
                    structure_thresholds.get("geometry_tolerance_px", 2.0)
                ),
                "size_tolerance_px": float(
                    structure_thresholds.get("geometry_tolerance_px", 2.0)
                ),
            },
        },
        "dom-quality-real-sites/1.0",
    )
    acceptance = asdict(decision)
    visual = dict(acceptance["dimensions"]["visual"])
    bad_ratio = float(visual_metrics.get("bad_pixel_ratio") or 0.0) * 100
    max_bad_ratio = float(visual_thresholds.get("max_bad_pixel_ratio", 1.0)) * 100
    if bad_ratio > max_bad_ratio:
        visual["status"] = "fail"
        visual["failed_metrics"] = [
            *(visual.get("failed_metrics") or []),
            "bad_pixel_ratio",
        ]
    visual["bad_pixel_ratio_pct"] = bad_ratio
    visual["max_bad_pixel_ratio_pct"] = max_bad_ratio
    layout = _layout_summary(readback)
    critical_text = _critical_text_summary(
        readback,
        list(sample.get("required_text") or []),
    )
    source_resolution = _source_resolution_summary(design)
    exported = _export_summary(export_path)
    dimensions = {
        "visual": visual,
        "structure": acceptance["dimensions"]["structure"],
        "edit": acceptance["dimensions"]["edit"],
        "asset": acceptance["dimensions"]["asset"],
        "text": acceptance["text"],
        "layout": layout,
        "export": exported,
        "source_resolution": source_resolution,
    }
    report = {
        "schema_version": "dom-figma-acceptance-report/1.0",
        "sample_id": sample_id,
        "frame_id": run_summary.get("frame_id"),
        "corpus_id": corpus.get("corpus_id"),
        "corpus_sha256": corpus.get("corpus_sha256"),
        "thresholds_sha256": corpus.get("thresholds_sha256"),
        "design_sha256": metadata.get("design_sha256"),
        "dom_sha256": metadata.get("dom_sha256"),
        "screenshot_sha256": metadata.get("screenshot_sha256"),
        "overall_status": acceptance["status"],
        "dimensions": dimensions,
        "acceptance": acceptance,
        "critical_text": critical_text,
        "text_edit_probe": text_probe,
        "asset_probe": asset_probe,
        "visual_metrics": visual_metrics,
        "text_metrics": text_metrics,
        "font_report": font_report,
        "export": exported,
        "layout": layout,
        "source_resolution": source_resolution,
        "figma_runtime": "observed",
        "export_allowed": acceptance["export_allowed"],
        "composite_score_used": False,
        "generated_assets": int(
            source_resolution["display_selected"].get("generated-approximation", 0)
        ),
        "non_claims": [
            "This evidence covers one frozen DQ-R02 sample and one Figma document.",
            "Final glyph outline identity is not proven.",
            "Parent Auto Layout propagation is not evaluated by this run.",
            "Reference-only screenshot crops are not original assets.",
        ],
    }
    _write_json(run / "acceptance.json", report)
    return report


def _flatten_nodes(tree: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def visit(node: Mapping[str, Any]) -> None:
        nodes.append(dict(node))
        for child in node.get("children") or []:
            if isinstance(child, Mapping):
                visit(child)

    visit(tree)
    return nodes


def _visual_metrics(reference_path: Path, render_path: Path) -> dict[str, Any]:
    import cv2
    import numpy as np

    reference = cv2.imread(str(reference_path))
    render = cv2.imread(str(render_path))
    if reference is None or render is None:
        return {
            "status": "not-evaluated",
            "reason": "image-unreadable",
            "bad_pixel_ratio": 1.0,
            "size_match": False,
        }
    size_match = reference.shape[:2] == render.shape[:2]
    scored = render
    if not size_match:
        scored = cv2.resize(
            render,
            (reference.shape[1], reference.shape[0]),
        )
    diff = np.abs(scored.astype(np.int16) - reference.astype(np.int16))
    max_diff = diff.max(axis=2)
    gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    ink = gray < 200
    bad_pixels = int((max_diff > 30).sum())
    total_pixels = int(max_diff.size)
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
        "ink_px": int(ink.sum()),
        "diff_pixel_count": int((max_diff > 0).sum()),
        "bad_pixel_count": bad_pixels,
        "bad_pixel_ratio": (float(bad_pixels / total_pixels) if total_pixels else 0.0),
    }


def _layout_summary(readback: Mapping[str, Any]) -> dict[str, Any]:
    nodes = _flatten_nodes(readback)
    layout_nodes = [
        node for node in nodes if str(node.get("layoutMode") or "NONE") != "NONE"
    ]
    mode_counts = Counter(str(node.get("layoutMode")) for node in layout_nodes)
    return {
        "status": "observed",
        "readback_node_count": len(nodes),
        "layout_node_count": len(layout_nodes),
        "layout_mode_counts": dict(sorted(mode_counts.items())),
        "parent_propagation": "not-evaluated",
        "source_behavior": "not-evaluated",
    }


def _critical_text_summary(
    readback: Mapping[str, Any],
    required_texts: list[Any],
) -> dict[str, Any]:
    actual = [
        _normalize_text(node.get("characters"))
        for node in _flatten_nodes(readback)
        if node.get("type") == "TEXT" and _normalize_text(node.get("characters"))
    ]
    rows = [
        {
            "text": str(required),
            "present": any(_normalize_text(required) in text for text in actual),
        }
        for required in required_texts
    ]
    matched = sum(row["present"] for row in rows)
    return {
        "status": "pass" if rows and matched == len(rows) else "fail",
        "required_count": len(rows),
        "matched_count": matched,
        "rows": rows,
    }


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _source_resolution_summary(design: Mapping[str, Any]) -> dict[str, Any]:
    identity_counts = Counter()
    display_counts = Counter()
    original_assets = 0
    replaceable = 0
    fallback_used = 0
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        resolution = element.get("sourceResolution")
        if not isinstance(resolution, Mapping):
            continue
        identity = resolution.get("identity") or {}
        display = resolution.get("display") or {}
        identity_counts[str(identity.get("selected") or "unknown")] += 1
        display_counts[str(display.get("selected") or "missing")] += 1
        original_assets += 1 if identity.get("original") else 0
        replaceable += 1 if identity.get("replaceable") else 0
        fallback_used += 1 if display.get("fallback_used") else 0
    return {
        "status": "observed",
        "identity_selected": dict(sorted(identity_counts.items())),
        "display_selected": dict(sorted(display_counts.items())),
        "original_assets": original_assets,
        "replaceable_assets": replaceable,
        "display_fallback_used": fallback_used,
        "figma_runtime": "observed",
    }


def _export_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "missing", "exists": False}
    with Image.open(path) as image:
        size = [image.width, image.height]
    return {
        "status": "pass",
        "exists": True,
        "size": size,
        "byte_length": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _find_node(
    tree: Mapping[str, Any],
    node_id: str,
) -> dict[str, Any] | None:
    return next(
        (node for node in _flatten_nodes(tree) if node.get("id") == node_id),
        None,
    )


def _node_snapshot(node: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "node_id": str(node.get("id") or ""),
        "node_type": node.get("type"),
        "characters": str(node.get("characters") or ""),
        "font": dict(node.get("fontName") or {}),
        "font_size": float(node.get("fontSize") or 0),
        "bounds": {
            key: float(node.get(key) or 0) for key in ("x", "y", "width", "height")
        },
    }


def _geometry_changed(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> bool:
    before_bounds = before.get("bounds") or {}
    after_bounds = after.get("bounds") or {}
    return any(
        abs(float(after_bounds.get(key) or 0) - float(before_bounds.get(key) or 0))
        > 0.5
        for key in ("width", "height")
    )


def _snapshot_restored(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> bool:
    if not after:
        return False
    if (
        after.get("node_type") != before.get("node_type")
        or after.get("characters") != before.get("characters")
        or after.get("font") != before.get("font")
    ):
        return False
    before_bounds = before.get("bounds") or {}
    after_bounds = after.get("bounds") or {}
    return all(
        abs(float(after_bounds.get(key) or 0) - float(before_bounds.get(key) or 0))
        <= 1.0
        for key in ("x", "y", "width", "height")
    )


def _image_fill(node: Mapping[str, Any]) -> dict[str, Any]:
    for fill in node.get("fills") or []:
        if isinstance(fill, Mapping) and fill.get("type") == "IMAGE":
            return dict(fill)
    return {}


def _replacement_png_base64() -> str:
    payload = io.BytesIO()
    Image.new("RGB", (4, 4), (32, 96, 192)).save(payload, format="PNG")
    return base64.b64encode(payload.getvalue()).decode("ascii")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
