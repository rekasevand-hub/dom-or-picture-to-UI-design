"""Output-neutral design IR and Figma/Axure capability boundary."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

OUTPUT_IR_SCHEMA_VERSION = "design-ir/2.0"
OUTPUT_CAPABILITY_VERSION = "output-capabilities/1.0"

_ALLOWED_KINDS = {
    "container",
    "rectangle",
    "divider",
    "text",
    "button",
    "input",
    "image",
    "avatar",
    "circle",
}

_CAPABILITIES = {
    "figma": {
        "target": "figma",
        "version": OUTPUT_CAPABILITY_VERSION,
        "features": {
            "native-text": True,
            "image-fill": True,
            "fixed-coordinate": True,
            "multi-page": False,
            "clip": True,
            "auto-layout": True,
            "runtime-image-replace": True,
            "visibility": True,
            "letter-spacing": True,
            "shadow": True,
            "gradient": True,
            "component-instance": False,
            "interaction": False,
        },
        "acceptance": {
            "scope": "figma-specific-required",
            "figma_evidence_transferable": True,
            "image_figma_evidence_transferable": True,
        },
    },
    "axure": {
        "target": "axure",
        "version": OUTPUT_CAPABILITY_VERSION,
        "features": {
            "native-text": True,
            "image-fill": True,
            "fixed-coordinate": True,
            "multi-page": True,
            "clip": False,
            "auto-layout": False,
            "runtime-image-replace": False,
            "visibility": False,
            "letter-spacing": False,
            "shadow": False,
            "gradient": False,
            "component-instance": False,
            "interaction": False,
        },
        "acceptance": {
            "scope": "axure-specific-required",
            "figma_evidence_transferable": False,
            "image_figma_evidence_transferable": False,
        },
    },
}

_DEGRADED_FALLBACKS = {
    "axure": {
        "multi-page": "native-pages",
        "clip": "flatten-or-reference-crop",
        "auto-layout": "fixed-coordinate",
        "runtime-image-replace": "creation-only-image-box",
        "visibility": "omit-or-flatten",
        "letter-spacing": "linebreak-workaround",
        "shadow": "reference-crop-or-explicit-loss",
        "gradient": "reference-crop-or-explicit-loss",
        "component-instance": "editable-widget-equivalent",
        "interaction": "not-implemented",
    },
    "figma": {
        "multi-page": "single-frame-per-write",
        "component-instance": "editable-frame-or-shape",
        "interaction": "not-implemented",
    },
}


def build_output_ir(
    design: Mapping[str, Any],
    *,
    source_kind: str,
    reference: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project DesignSpec into a deterministic output-neutral contract."""
    pages = design.get("pages")
    design_pages = (
        [page for page in pages if isinstance(page, Mapping)]
        if isinstance(pages, list) and pages
        else [design]
    )
    source = str(source_kind or "unknown")
    inferred_flow = _inferred_flow(design)
    frames = [
        _frame(page, index=index, source=source, default_flow=inferred_flow)
        for index, page in enumerate(design_pages)
    ]
    assets = _unique_assets(asset for frame in frames for asset in frame.pop("_assets"))
    required = sorted(
        {
            feature
            for frame in frames
            for node in frame["nodes"]
            for feature in node["required_features"]
        }
        | ({"multi-page"} if len(frames) > 1 else set())
    )
    ir = {
        "schema_version": OUTPUT_IR_SCHEMA_VERSION,
        "document_id": None,
        "output_neutral": True,
        "source": {
            "input_kind": source,
            "reference_id": (reference or {}).get("reference_id"),
            "reference_state": copy.deepcopy((reference or {}).get("state") or {}),
        },
        "frames": frames,
        "assets": assets,
        "required_features": required,
        "limitations": [
            "The IR is output-neutral and does not inherit target acceptance.",
            "Reference-only display crops remain non-original assets.",
            "Candidate/fixed-coordinate flow is not verified adaptive layout.",
            "Figma and Axure each require separate output acceptance.",
        ],
    }
    ir["document_id"] = _json_sha256(ir)
    return ir


def validate_output_ir(ir: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return deterministic boundary violations without upgrading claims."""
    issues: list[dict[str, Any]] = []

    def add(code: str, path: str, message: str) -> None:
        issues.append({"code": code, "path": path, "message": message})

    if ir.get("schema_version") != OUTPUT_IR_SCHEMA_VERSION:
        add(
            "unsupported-schema",
            "schema_version",
            f"expected {OUTPUT_IR_SCHEMA_VERSION}",
        )
    if ir.get("output_neutral") is not True:
        add("not-output-neutral", "output_neutral", "output-neutral IR required")
    frames = ir.get("frames")
    if not isinstance(frames, list) or not frames:
        add("missing-frames", "frames", "at least one frame is required")
        frames = []
    frame_ids: set[str] = set()
    node_ids: set[str] = set()
    for frame_index, frame in enumerate(frames):
        frame_path = f"frames[{frame_index}]"
        if not isinstance(frame, Mapping):
            add("invalid-frame", frame_path, "frame must be an object")
            continue
        frame_id = str(frame.get("frame_id") or "")
        if not frame_id:
            add("missing-frame-id", f"{frame_path}.frame_id", "frame_id required")
        elif frame_id in frame_ids:
            add("duplicate-frame-id", f"{frame_path}.frame_id", frame_id)
        frame_ids.add(frame_id)
        canvas = frame.get("canvas")
        if not isinstance(canvas, Mapping):
            add("invalid-canvas", f"{frame_path}.canvas", "canvas object required")
        else:
            for key in ("width", "height"):
                value = _finite_number(canvas.get(key))
                if value is None or value <= 0:
                    add(
                        "invalid-canvas",
                        f"{frame_path}.canvas.{key}",
                        "positive finite number required",
                    )
        nodes = frame.get("nodes")
        if not isinstance(nodes, list):
            add("invalid-nodes", f"{frame_path}.nodes", "nodes array required")
            continue
        for node_index, node in enumerate(nodes):
            node_path = f"{frame_path}.nodes[{node_index}]"
            if not isinstance(node, Mapping):
                add("invalid-node", node_path, "node must be an object")
                continue
            node_id = str(node.get("node_id") or "")
            if not node_id:
                add("missing-node-id", f"{node_path}.node_id", "node_id required")
            elif node_id in node_ids:
                add("duplicate-node-id", f"{node_path}.node_id", node_id)
            node_ids.add(node_id)
            if node.get("kind") not in _ALLOWED_KINDS:
                add("unsupported-node-kind", f"{node_path}.kind", str(node.get("kind")))
            geometry = node.get("geometry")
            if not isinstance(geometry, Mapping):
                add("invalid-geometry", f"{node_path}.geometry", "object required")
            else:
                values = {
                    key: _finite_number(geometry.get(key))
                    for key in ("x", "y", "width", "height")
                }
                if any(value is None for value in values.values()):
                    add(
                        "invalid-geometry",
                        f"{node_path}.geometry",
                        "finite numeric geometry required",
                    )
                elif values["width"] <= 0 or values["height"] <= 0:
                    add(
                        "invalid-geometry",
                        f"{node_path}.geometry",
                        "width and height must be positive",
                    )
            layout = node.get("layout")
            if isinstance(layout, Mapping):
                status = str(layout.get("status") or "")
                if status in {"verified", "pass"} and not (
                    layout.get("evidence_refs") or layout.get("evidence")
                ):
                    add(
                        "verified-flow-without-evidence",
                        f"{node_path}.layout",
                        "verified flow requires explicit evidence",
                    )
    for asset_index, asset in enumerate(ir.get("assets") or []):
        path = f"assets[{asset_index}]"
        if not isinstance(asset, Mapping):
            add("invalid-asset", path, "asset must be an object")
            continue
        if bool(asset.get("reference_only")) and bool(asset.get("display_original")):
            add(
                "reference-only-cannot-be-original",
                path,
                "reference-only display crop cannot be original",
            )
        if bool(asset.get("generated")) and bool(asset.get("display_original")):
            add(
                "generated-cannot-be-original",
                path,
                "generated approximation cannot be original",
            )
    return sorted(issues, key=lambda item: (item["path"], item["code"]))


def output_capabilities(target: str) -> dict[str, Any]:
    """Return an independent capability profile for one output target."""
    normalized = str(target or "").strip().lower()
    if normalized not in _CAPABILITIES:
        raise ValueError(f"unknown output target: {target}")
    return copy.deepcopy(_CAPABILITIES[normalized])


def project_for_output(
    ir: Mapping[str, Any],
    target: str,
) -> dict[str, Any]:
    """Project required features onto a target without transferring claims."""
    issues = validate_output_ir(ir)
    if issues:
        codes = ", ".join(issue["code"] for issue in issues)
        raise ValueError(f"invalid output IR: {codes}")
    capabilities = output_capabilities(target)
    required = set(ir.get("required_features") or [])
    supported = sorted(
        feature for feature in required if capabilities["features"].get(feature)
    )
    unsupported = sorted(
        feature for feature in required if not capabilities["features"].get(feature)
    )
    fallbacks = _DEGRADED_FALLBACKS[str(capabilities["target"])]
    degraded = [
        f"{feature}->{fallbacks.get(feature, 'not-implemented')}"
        for feature in unsupported
    ]
    return {
        "target": capabilities["target"],
        "capability_version": capabilities["version"],
        "document_id": ir.get("document_id"),
        "supported_features": supported,
        "unsupported_features": unsupported,
        "degraded": degraded,
        "blocked_claims": [
            f"{feature}:not-supported-by-{capabilities['target']}"
            for feature in unsupported
        ],
        "can_claim_complete": not unsupported,
        "acceptance_scope": capabilities["acceptance"]["scope"],
        "acceptance": copy.deepcopy(capabilities["acceptance"]),
    }


def _frame(
    page: Mapping[str, Any],
    *,
    index: int,
    source: str,
    default_flow: Mapping[str, Any],
) -> dict[str, Any]:
    frame_id = f"F{index + 1}"
    elements = [
        item for item in page.get("elements") or [] if isinstance(item, Mapping)
    ]
    nodes = [
        _node(
            element,
            frame_id=frame_id,
            index=node_index,
            source=source,
            default_flow=default_flow,
        )
        for node_index, element in enumerate(elements)
    ]
    assets = [node.pop("_asset") for node in nodes if node.get("_asset")]
    for node in nodes:
        node.pop("_asset", None)
    canvas = page.get("canvas") if isinstance(page.get("canvas"), Mapping) else {}
    return {
        "frame_id": frame_id,
        "name": str(page.get("name") or page.get("title") or f"Frame {index + 1}"),
        "canvas": {
            "x": _number(canvas.get("x"), 0.0),
            "y": _number(canvas.get("y"), 0.0),
            "width": _number(canvas.get("width"), 800.0),
            "height": _number(canvas.get("height"), 600.0),
            "background": str(canvas.get("background") or "#ffffff"),
        },
        "nodes": nodes,
        "_assets": assets,
    }


def _node(
    element: Mapping[str, Any],
    *,
    frame_id: str,
    index: int,
    source: str,
    default_flow: Mapping[str, Any],
) -> dict[str, Any]:
    kind = str(element.get("type") or "rectangle").lower()
    if kind not in _ALLOWED_KINDS:
        kind = "rectangle"
    style = {
        str(key): copy.deepcopy(value)
        for key, value in (element.get("style") or {}).items()
        if value is not None
    }
    geometry = {
        "x": _number(element.get("x"), 0.0),
        "y": _number(element.get("y"), 0.0),
        "width": _number(element.get("width"), 0.0),
        "height": _number(element.get("height"), 0.0),
    }
    raw_layout = element.get("layout")
    layout = (
        copy.deepcopy(dict(raw_layout))
        if isinstance(raw_layout, Mapping)
        else {
            "mode": str(default_flow.get("value") or "fixed-coordinate"),
            "status": str(default_flow.get("status") or "candidate"),
        }
    )
    required: set[str] = {"fixed-coordinate"}
    if kind in {"text", "button", "input"}:
        required.add("native-text")
    has_image = kind in {"image", "avatar"}
    if element.get("imageBase64") or element.get("displayPayload"):
        required.add("image-fill")
    if element.get("clip"):
        required.add("clip")
    if _number(style.get("letterSpacing"), 0.0):
        required.add("letter-spacing")
    if style.get("shadows"):
        required.add("shadow")
    if "gradient" in str(style.get("fillColor") or "").lower():
        required.add("gradient")
    if "visible" in element:
        required.add("visibility")
    if str(layout.get("mode") or "").lower() not in {
        "fixed-coordinate",
        "none",
        "",
    } and str(layout.get("status") or "").lower() in {
        "verified",
        "pass",
    }:
        required.add("auto-layout")
    image_meta = (
        element.get("imageMVP") if isinstance(element.get("imageMVP"), Mapping) else {}
    )
    if has_image and bool(image_meta.get("displayReplaceable")):
        required.add("runtime-image-replace")
    asset = _asset_use(element)
    if asset is not None:
        required.add("image-fill")
    return {
        "node_id": f"{frame_id}:N{index + 1}",
        "source_node_id": str(element.get("id") or ""),
        "kind": kind,
        "geometry": geometry,
        "content": {
            "text": str(element.get("text") or ""),
            "name": str(element.get("name") or ""),
        },
        "style": style,
        "layout": layout,
        "constraints": {
            "clip": copy.deepcopy(element.get("clip")),
            "visible": element.get("visible"),
        },
        "provenance": {
            "source": str(element.get("source") or source),
            "authority": element.get("authority"),
            "verified": bool(element.get("verified", False)),
            "imageMVP": copy.deepcopy(image_meta),
        },
        "required_features": sorted(required),
        "_asset": asset,
    }


def _asset_use(element: Mapping[str, Any]) -> dict[str, Any] | None:
    resolution = element.get("sourceResolution")
    display = element.get("displayPayload")
    if isinstance(resolution, Mapping):
        identity = resolution.get("identity") or {}
        selected_display = resolution.get("display") or {}
        display_provenance = selected_display.get("provenance") or {}
        display_payload = display if isinstance(display, Mapping) else {}
        return {
            "use_id": str(resolution.get("use_id") or ""),
            "asset_id": str(resolution.get("asset_id") or ""),
            "source_status": str(identity.get("selected") or "unknown"),
            "display": str(selected_display.get("selected") or "missing"),
            "original": bool(identity.get("original")),
            "display_original": bool(selected_display.get("original")),
            "reference_only": bool(selected_display.get("reference_only")),
            "generated": bool(selected_display.get("generated")),
            "payload_sha256": (
                display_provenance.get("payload_sha256")
                or display_payload.get("payload_sha256")
            ),
            "replaceable": bool(identity.get("replaceable")),
        }
    identity = element.get("assetIdentity")
    if isinstance(identity, Mapping):
        record = identity.get("asset_record")
        if isinstance(record, Mapping):
            source_identity = record.get("source_identity") or {}
            display_payload = record.get("display_payload") or {}
            replacement = record.get("replacement") or {}
            return {
                "use_id": str((record.get("use") or {}).get("use_id") or ""),
                "asset_id": str(record.get("asset_id") or ""),
                "source_status": str(source_identity.get("status") or "unknown"),
                "display": str(display_payload.get("kind") or "missing"),
                "original": (source_identity.get("status") == "verified-original"),
                "display_original": bool(display_payload.get("original")),
                "reference_only": bool(display_payload.get("reference_only")),
                "generated": False,
                "payload_sha256": display_payload.get("payload_sha256"),
                "replaceable": bool(replacement.get("allowed")),
            }
    payload_sha256 = _payload_sha256(element)
    if payload_sha256:
        source_node_id = str(element.get("id") or "unknown")
        return {
            "use_id": f"payload:{source_node_id}:{payload_sha256[:16]}",
            "asset_id": f"asset:unverified:payload:{payload_sha256[:16]}",
            "source_status": "unavailable",
            "display": "unverified-payload",
            "original": False,
            "display_original": False,
            "reference_only": True,
            "generated": False,
            "payload_sha256": payload_sha256,
            "replaceable": False,
        }
    return None


def _payload_sha256(element: Mapping[str, Any]) -> str | None:
    display = element.get("displayPayload")
    if isinstance(display, Mapping) and display.get("payload_sha256"):
        return str(display["payload_sha256"])
    data = element.get("imageBase64")
    if not isinstance(data, (bytes, bytearray, str)) or not data:
        return None
    if isinstance(data, (bytes, bytearray)):
        payload = bytes(data)
    else:
        text = data.strip()
        if text.startswith("data:"):
            text = text.split(",", 1)[1] if "," in text else ""
        if not text:
            return None
        try:
            payload = base64.b64decode(text)
        except (ValueError, TypeError):
            return None
    return hashlib.sha256(payload).hexdigest() if payload else None


def _unique_assets(assets: Any) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for index, asset in enumerate(assets):
        normalized = copy.deepcopy(asset)
        key = (
            str(normalized.get("use_id") or "")
            or str(normalized.get("asset_id") or "")
            or str(normalized.get("payload_sha256") or "")
            or f"asset-{index}"
        )
        unique.setdefault(key, normalized)
    return [unique[key] for key in sorted(unique)]


def _inferred_flow(design: Mapping[str, Any]) -> dict[str, Any]:
    image_meta = (
        (design.get("_meta") or {}).get("imageMVP")
        if isinstance(design.get("_meta"), Mapping)
        else None
    )
    if isinstance(image_meta, Mapping) and isinstance(image_meta.get("flow"), Mapping):
        return copy.deepcopy(dict(image_meta["flow"]))
    return {"value": "fixed-coordinate", "status": "candidate"}


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
