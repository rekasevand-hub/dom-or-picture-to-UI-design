from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.app.utils.style_utils import css_color_to_hex

VISUAL_ASSETS_SCHEMA_VERSION = "dom-visual-assets/1.0"
_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_GRADIENT_STOP_RE = re.compile(
    r"(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))\s*([-+]?\d*\.?\d+%)?",
)


def _manifest_rows(manifest: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(manifest, Mapping):
        return {}
    rows = manifest.get("assets")
    if isinstance(rows, Mapping):
        source_rows = rows.values()
    elif isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
        source_rows = rows
    else:
        source_rows = []
    result: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        if not isinstance(row, Mapping):
            continue
        url = str(
            row.get("source_url")
            or row.get("sourceUrl")
            or row.get("source")
            or row.get("url")
            or ""
        ).strip()
        if url:
            result[url] = dict(row)
    return result


def _source_url(value: Any) -> str:
    text = str(value or "").strip()
    match = _URL_RE.search(text)
    return (match.group(2) if match else text).strip().strip("\"'")


def _verified_asset(row: Mapping[str, Any] | None) -> bool:
    if not isinstance(row, Mapping):
        return False
    status = str(row.get("status") or row.get("source_status") or "").lower()
    return (
        status in {"verified", "verified-original"}
        and bool(row.get("locator") or row.get("retained_path") or row.get("path"))
    )


def _parse_gradient(css: str) -> dict[str, Any] | None:
    body = str(css or "").strip()
    match = re.search(r"(linear|radial)-gradient\((.*)\)", body, re.IGNORECASE)
    if not match:
        return None
    kind = match.group(1).lower()
    inside = match.group(2)
    stops = []
    for color, offset in _GRADIENT_STOP_RE.findall(inside):
        normalized = css_color_to_hex(color) or color
        stop: dict[str, Any] = {"color": normalized}
        if offset:
            stop["offset"] = float(offset.rstrip("%")) / 100.0
        stops.append(stop)
    if len(stops) < 2:
        return None
    angle_match = re.search(r"([-+]?\d*\.?\d+)deg", inside)
    return {
        "type": kind,
        "angle": float(angle_match.group(1)) if angle_match else None,
        "stops": [stop["color"] for stop in stops],
        "detailedStops": stops,
        "css": body,
    }


def _background_layers(node: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = node.get("backgroundLayers")
    layers = [
        dict(item)
        for item in (raw or [])
        if isinstance(item, Mapping)
    ]
    if layers:
        return layers
    return [
        {"kind": "image", "source": str(url)}
        for url in (node.get("bgUrls") or [])
        if str(url).strip()
    ]


def _pseudo_assets(node: Mapping[str, Any], index: int) -> list[dict[str, Any]]:
    result = []
    for pseudo_name, field in (("before", "pseudoBefore"), ("after", "pseudoAfter")):
        pseudo = node.get(field)
        if not isinstance(pseudo, Mapping):
            continue
        content = str(pseudo.get("content") or "")
        if not content or content.lower() in {"none", "normal"}:
            continue
        is_mask = bool(_URL_RE.search(content))
        display_text = content
        if not is_mask:
            try:
                decoded = json.loads(content)
                display_text = str(decoded)
            except (TypeError, ValueError, json.JSONDecodeError):
                display_text = content.strip("\"'")
        result.append(
            {
                "visualAssetId": f"visual-{index}-pseudo-{pseudo_name}",
                "kind": "mask" if is_mask else "text",
                "pseudo": pseudo_name,
                "source": _source_url(content) or None,
                "text": "" if is_mask else display_text,
                "bbox": [
                    node.get("x", 0),
                    node.get("y", 0),
                    node.get("w", 0),
                    node.get("h", 0),
                ],
                "geometrySource": "owning-element-approximation",
                "style": dict(pseudo),
                "domIndex": index,
                "sourceKind": "dom:pseudo",
            }
        )
    return result


def build_visual_assets(
    dom_nodes: Sequence[Mapping[str, Any]],
    asset_manifest: Mapping[str, Any] | None,
) -> dict[str, Any]:
    manifest = _manifest_rows(asset_manifest)
    assets: list[dict[str, Any]] = []
    by_dom: dict[int, dict[str, Any]] = {}
    for index, node in enumerate(dom_nodes):
        if not isinstance(node, Mapping):
            continue
        primary = None
        for layer_index, layer in enumerate(_background_layers(node)):
            layer_kind = str(layer.get("kind") or "").lower()
            asset: dict[str, Any]
            if layer_kind == "gradient" or "gradient" in str(layer.get("css") or ""):
                gradient = _parse_gradient(str(layer.get("css") or ""))
                if gradient is None:
                    asset = {
                        "kind": "gradient",
                        "displayMode": "source-crop",
                        "visualFallbackReason": "unsupported-gradient",
                        "css": str(layer.get("css") or ""),
                    }
                else:
                    asset = {
                        "kind": "gradient",
                        "displayMode": "gradient-fill",
                        "gradient": gradient,
                    }
            else:
                source = _source_url(layer.get("source") or layer.get("url"))
                row = manifest.get(source)
                verified = _verified_asset(row)
                has_text = bool(str(node.get("text") or "")) or bool(node.get("richRuns"))
                if has_text:
                    display_mode = "source-crop"
                    reason = "source-crop-required-for-text-over-background"
                elif verified:
                    display_mode = "image-fill"
                    reason = ""
                else:
                    display_mode = "source-crop"
                    reason = (
                        "reference-only-background-image"
                        if source
                        else "missing-background-source"
                    )
                asset = {
                    "kind": "background-image",
                    "displayMode": display_mode,
                    "source": source or None,
                    "size": str(layer.get("size") or "auto"),
                    "position": str(layer.get("position") or "0% 0%"),
                    "repeat": str(layer.get("repeat") or "repeat"),
                    "layerIndex": layer_index,
                    "asset": dict(row) if isinstance(row, Mapping) else None,
                }
                if reason:
                    asset["visualFallbackReason"] = reason
            asset["visualAssetId"] = f"visual-{index}-{layer_index}"
            asset["bbox"] = [
                node.get("x", 0),
                node.get("y", 0),
                node.get("w", 0),
                node.get("h", 0),
            ]
            asset["domIndex"] = index
            asset["sourceKind"] = (
                "dom:background"
                if asset["kind"] == "background-image"
                else "dom:background-gradient"
            )
            assets.append(asset)
            primary = primary or asset
        pseudos = _pseudo_assets(node, index)
        assets.extend(pseudos)
        primary = primary or (pseudos[0] if pseudos else None)
        if primary is not None:
            by_dom[index] = primary
    return {
        "schema_version": VISUAL_ASSETS_SCHEMA_VERSION,
        "byDom": by_dom,
        "assets": assets,
        "counts": {
            "background": sum(item["kind"] == "background-image" for item in assets),
            "gradient": sum(item["kind"] == "gradient" for item in assets),
            "pseudo": sum(item["sourceKind"] == "dom:pseudo" for item in assets),
        },
    }
