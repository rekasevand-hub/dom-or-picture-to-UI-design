"""Verified shared-IR route planning for Axure RP 8 output."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from src.app.services.contracts import (
    build_output_ir,
    project_for_output,
    validate_output_ir,
)
from src.app.services.rendering.axure import doc

AXURE_ROUTE_SCHEMA_VERSION = "axure-route/1.0"


def plan_axure_route(
    design: Mapping[str, Any],
    *,
    source_kind: str,
    reference: Mapping[str, Any] | None = None,
    ir: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind an output-neutral IR back to its captured DesignSpec.

    The IR is the routing and claim gate. The source DesignSpec remains the
    owner of image bytes, paint order and capture-only text metrics that the
    neutral projection intentionally does not duplicate.
    """
    source_design = copy.deepcopy(dict(design))
    output_ir = (
        copy.deepcopy(dict(ir))
        if ir is not None
        else build_output_ir(
            source_design,
            source_kind=source_kind,
            reference=reference,
        )
    )
    issues = validate_output_ir(output_ir)
    if issues:
        codes = ", ".join(issue["code"] for issue in issues)
        raise ValueError(f"invalid output IR: {codes}")

    projection = project_for_output(output_ir, "axure")
    source_pages = _source_pages(source_design)
    frames = output_ir["frames"]
    if len(source_pages) != len(frames):
        raise ValueError(
            "source page count does not match IR frame count: "
            f"{len(source_pages)} != {len(frames)}"
        )

    node_bindings: list[dict[str, Any]] = []
    source_nodes: list[tuple[int, Mapping[str, Any]]] = []
    for frame_index, (page, frame) in enumerate(zip(source_pages, frames)):
        elements = [
            element
            for element in page.get("elements") or []
            if isinstance(element, Mapping)
        ]
        nodes = list(frame.get("nodes") or [])
        if len(elements) != len(nodes):
            raise ValueError(
                f"frame {frame_index} source node count does not match IR: "
                f"{len(elements)} != {len(nodes)}"
            )
        by_id: dict[str, list[int]] = {}
        for index, element in enumerate(elements):
            source_id = str(element.get("id") or "")
            if source_id:
                by_id.setdefault(source_id, []).append(index)
        used: set[int] = set()
        for node_index, node in enumerate(nodes):
            source_id = str(node.get("source_node_id") or "")
            if source_id:
                candidates = [
                    index for index in by_id.get(source_id, []) if index not in used
                ]
                if not candidates:
                    raise ValueError(f"IR source node is missing: {source_id}")
                source_index = candidates[0]
            else:
                if node_index in used:
                    raise ValueError(
                        f"cannot bind IR node {node.get('node_id')} without source id"
                    )
                source_index = node_index
            used.add(source_index)
            element = elements[source_index]
            _validate_node_binding(frame_index, node, element, source_id)
            source_nodes.append((frame_index, element))
            node_bindings.append(
                {
                    "frame_index": frame_index,
                    "node_index": node_index,
                    "node_id": str(node.get("node_id") or ""),
                    "source_node_id": source_id,
                    "source_index": source_index,
                    "kind": str(node.get("kind") or ""),
                }
            )
        if len(used) != len(elements):
            missing = [
                str(element.get("id") or f"index:{index}")
                for index, element in enumerate(elements)
                if index not in used
            ]
            raise ValueError(f"source nodes have no IR binding: {missing}")

    asset_bindings = _bind_assets(output_ir, source_nodes)
    asset_render_summary = {
        "ir_assets": len(asset_bindings),
        "rendered": sum(
            row.get("render_status") == "rendered" for row in asset_bindings
        ),
        "not_rendered": sum(
            row.get("render_status") == "not-rendered" for row in asset_bindings
        ),
        "not_rendered_use_ids": sorted(
            row["use_id"]
            for row in asset_bindings
            if row.get("render_status") == "not-rendered"
        ),
    }
    degradations = _degradations(output_ir, projection)
    source_reference = _source_reference(
        output_ir,
        source_design,
        reference,
    )
    limitations = [
        "The IR gates routing and provenance; source DesignSpec supplies image bytes.",
        "Axure acceptance is independent from Figma acceptance.",
        "Auto Layout, clip, runtime image replacement and native letter spacing are degraded.",
        "Reference-only and generated payloads remain non-original display assets.",
    ]
    if asset_render_summary["not_rendered"]:
        limitations.append(
            "Non-image asset uses are retained as provenance but not rendered in Axure."
        )
    return {
        "schema_version": AXURE_ROUTE_SCHEMA_VERSION,
        "source_kind": str(source_kind or ""),
        "document_id": output_ir["document_id"],
        "source_design_sha256": _json_sha256(source_design),
        "ir_sha256": _json_sha256(output_ir),
        "source_reference": source_reference,
        "design": source_design,
        "ir": output_ir,
        "projection": projection,
        "node_bindings": node_bindings,
        "asset_bindings": asset_bindings,
        "asset_render_summary": asset_render_summary,
        "degradations": degradations,
        "limitations": limitations,
    }


def _source_pages(design: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    pages = design.get("pages")
    if isinstance(pages, list) and pages:
        return [page for page in pages if isinstance(page, Mapping)]
    return [design]


def _validate_node_binding(
    frame_index: int,
    node: Mapping[str, Any],
    element: Mapping[str, Any],
    source_id: str,
) -> None:
    kind = str(node.get("kind") or "")
    source_kind = str(element.get("type") or "rectangle").lower()
    if source_kind in {"image", "avatar"}:
        source_kind = kind
    if kind and source_kind and kind != source_kind:
        raise ValueError(
            f"IR node kind mismatch for {source_id or frame_index}: "
            f"{kind} != {source_kind}"
        )
    expected_text = str(node.get("content", {}).get("text") or "")
    source_text = str(element.get("text") or "")
    if expected_text != source_text:
        raise ValueError(
            f"IR text mismatch for {source_id or frame_index}: "
            f"{expected_text!r} != {source_text!r}"
        )
    geometry = node.get("geometry") or {}
    for key in ("x", "y", "width", "height"):
        try:
            expected = float(geometry.get(key))
            actual = float(element.get(key))
        except (TypeError, ValueError):
            raise ValueError(
                f"IR geometry is invalid for {source_id or frame_index}.{key}"
            ) from None
        if abs(expected - actual) > 1e-6:
            raise ValueError(
                f"IR geometry mismatch for {source_id or frame_index}.{key}: "
                f"{expected} != {actual}"
            )


def _bind_assets(
    ir: Mapping[str, Any],
    source_nodes: list[tuple[int, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    assets = [asset for asset in ir.get("assets") or [] if isinstance(asset, Mapping)]
    by_use_id = {
        str(asset.get("use_id")): asset
        for asset in assets
        if str(asset.get("use_id") or "")
    }
    bindings: list[dict[str, Any]] = []
    used_assets: set[int] = set()
    source_by_use_id: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for frame_index, element in source_nodes:
        use_id = _use_id(element)
        if use_id:
            source_by_use_id.setdefault(use_id, (frame_index, element))
    for frame_index, element in source_nodes:
        if str(element.get("type") or "").lower() not in {"image", "avatar"}:
            continue
        source_id = str(element.get("id") or "")
        use_id = _use_id(element)
        asset = by_use_id.get(use_id) if use_id else None
        payload = doc.image_bytes(element.get("imageBase64"))
        actual_hash = hashlib.sha256(payload).hexdigest() if payload else None
        if asset is None:
            candidates = [
                item
                for index, item in enumerate(assets)
                if index not in used_assets
                and actual_hash
                and item.get("payload_sha256") == actual_hash
            ]
            if len(candidates) != 1:
                raise ValueError(
                    f"image asset has no unique IR binding: {source_id or use_id}"
                )
            asset = candidates[0]
        asset_index = id(asset)
        if asset_index in used_assets:
            raise ValueError(f"IR asset is bound more than once: {use_id}")
        used_assets.add(asset_index)
        declared_hash = str(asset.get("payload_sha256") or "")
        if not payload or not declared_hash:
            raise ValueError(f"image payload is missing for {source_id or use_id}")
        if actual_hash != declared_hash:
            raise ValueError(
                f"image payload hash mismatch for {source_id or use_id}: "
                f"{actual_hash} != {declared_hash}"
            )
        generated = bool(asset.get("generated"))
        reference_only = bool(asset.get("reference_only"))
        display_original = bool(asset.get("display_original"))
        if (generated or reference_only) and display_original:
            raise ValueError(
                f"non-original display payload promoted to original: {source_id or use_id}"
            )
        bindings.append(
            {
                "frame_index": frame_index,
                "source_node_id": source_id,
                "use_id": str(asset.get("use_id") or use_id),
                "asset_id": str(asset.get("asset_id") or ""),
                "payload_sha256": declared_hash,
                "actual_payload_sha256": actual_hash,
                "source_status": str(asset.get("source_status") or "unknown"),
                "display": str(asset.get("display") or "missing"),
                "original": bool(asset.get("original")),
                "display_original": display_original,
                "reference_only": reference_only,
                "generated": generated,
                "replaceable": bool(asset.get("replaceable")),
                "binding_status": "match",
                "render_status": "rendered",
            }
        )
    for asset in assets:
        if id(asset) in used_assets:
            continue
        use_id = str(asset.get("use_id") or "")
        source = source_by_use_id.get(use_id)
        if source is None:
            raise ValueError(f"IR asset source node is missing: {use_id or 'unknown'}")
        frame_index, element = source
        source_id = str(element.get("id") or "")
        if str(element.get("type") or "").lower() in {"image", "avatar"}:
            raise ValueError(f"image asset was not rendered: {source_id or use_id}")
        payload = doc.image_bytes(element.get("imageBase64"))
        actual_hash = hashlib.sha256(payload).hexdigest() if payload else None
        declared_hash = str(asset.get("payload_sha256") or "")
        if payload and declared_hash:
            if actual_hash != declared_hash:
                raise ValueError(
                    f"image payload hash mismatch for {source_id or use_id}: "
                    f"{actual_hash} != {declared_hash}"
                )
            bindings.append(
                {
                    "frame_index": frame_index,
                    "source_node_id": source_id,
                    "use_id": str(asset.get("use_id") or use_id),
                    "asset_id": str(asset.get("asset_id") or ""),
                    "payload_sha256": declared_hash,
                    "actual_payload_sha256": actual_hash,
                    "source_status": str(asset.get("source_status") or "unknown"),
                    "display": str(asset.get("display") or "missing"),
                    "original": bool(asset.get("original")),
                    "display_original": bool(asset.get("display_original")),
                    "reference_only": bool(asset.get("reference_only")),
                    "generated": bool(asset.get("generated")),
                    "replaceable": bool(asset.get("replaceable")),
                    "binding_status": "match",
                    "render_status": "rendered",
                }
            )
            continue
        reference_only = bool(asset.get("reference_only"))
        generated = bool(asset.get("generated"))
        display_original = bool(asset.get("display_original"))
        if (generated or reference_only) and display_original:
            raise ValueError(
                f"non-original display payload promoted to original: {source_id or use_id}"
            )
        display = str(asset.get("display") or "missing")
        bindings.append(
            {
                "frame_index": frame_index,
                "source_node_id": source_id,
                "use_id": str(asset.get("use_id") or use_id),
                "asset_id": str(asset.get("asset_id") or ""),
                "payload_sha256": declared_hash or None,
                "actual_payload_sha256": None,
                "source_status": str(asset.get("source_status") or "unknown"),
                "display": display,
                "original": bool(asset.get("original")),
                "display_original": display_original,
                "reference_only": reference_only,
                "generated": generated,
                "replaceable": bool(asset.get("replaceable")),
                "binding_status": "not-rendered",
                "render_status": "not-rendered",
                "reason": (
                    "non-image-node-without-display-payload"
                    if display in {"missing", "none"}
                    else "non-image-node"
                ),
            }
        )
    if len(bindings) != len(assets):
        raise ValueError(
            f"IR asset count does not match source image uses: "
            f"{len(bindings)} != {len(assets)}"
        )
    return sorted(
        bindings,
        key=lambda row: (row["frame_index"], row["source_node_id"], row["use_id"]),
    )


def _use_id(element: Mapping[str, Any]) -> str:
    resolution = element.get("sourceResolution")
    if isinstance(resolution, Mapping):
        return str(resolution.get("use_id") or "")
    identity = element.get("assetIdentity")
    if isinstance(identity, Mapping):
        record = identity.get("asset_record")
        if isinstance(record, Mapping):
            return str((record.get("use") or {}).get("use_id") or "")
    payload = doc.image_bytes(element.get("imageBase64"))
    if payload:
        digest = hashlib.sha256(payload).hexdigest()
        return f"payload:{element.get('id') or 'unknown'}:{digest[:16]}"
    return ""


def _source_reference(
    ir: Mapping[str, Any],
    design: Mapping[str, Any],
    reference: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    resolved = dict(reference or {})
    meta = design.get("_meta")
    image_meta = meta.get("imageMVP") if isinstance(meta, Mapping) else None
    image_meta = image_meta if isinstance(image_meta, Mapping) else {}
    ir_source = ir.get("source")
    ir_source = ir_source if isinstance(ir_source, Mapping) else {}
    reference_id = str(
        resolved.get("reference_id")
        or image_meta.get("reference_id")
        or ir_source.get("reference_id")
        or ""
    )
    input_meta = resolved.get("input")
    input_meta = input_meta if isinstance(input_meta, Mapping) else {}
    sha256 = str(input_meta.get("sha256") or "")
    if not sha256 and reference_id.startswith("image-sha256:"):
        sha256 = reference_id.split(":", 1)[1]
    state = (
        resolved.get("state")
        or image_meta.get("state")
        or ir_source.get("reference_state")
        or {}
    )
    if not reference_id and not state:
        return None
    return {
        "reference_id": reference_id or None,
        "sha256": sha256 or None,
        "size": copy.deepcopy(input_meta.get("size")),
        "state": copy.deepcopy(state) if isinstance(state, Mapping) else {},
        "flow": copy.deepcopy(image_meta.get("flow") or {}),
    }


def _degradations(
    ir: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> list[dict[str, Any]]:
    fallbacks = {
        str(item).split("->", 1)[0]: str(item).split("->", 1)[1]
        for item in projection.get("degraded") or []
        if "->" in str(item)
    }
    nodes = [
        node
        for frame in ir.get("frames") or []
        for node in frame.get("nodes") or []
        if isinstance(node, Mapping)
    ]
    rows = []
    for feature in projection.get("unsupported_features") or []:
        affected = sorted(
            str(node.get("source_node_id") or node.get("node_id") or "")
            for node in nodes
            if feature in (node.get("required_features") or [])
        )
        rows.append(
            {
                "feature": str(feature),
                "fallback": fallbacks.get(str(feature), "not-implemented"),
                "source_node_ids": affected,
            }
        )
    return sorted(rows, key=lambda row: row["feature"])


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
