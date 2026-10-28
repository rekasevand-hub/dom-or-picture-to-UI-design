from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes

MAX_SVG_BYTES = 2 * 1024 * 1024
SVG_MATERIALIZATION_SCHEMA_VERSION = "dom-svg-materialization/1.0"
_URL_VALUE_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_SIZE_RE = re.compile(r"^\s*([0-9.]+)\s*(?:px)?\s*$", re.IGNORECASE)


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_external_url(value: str) -> bool:
    text = value.strip().strip("\"'")
    return bool(
        text
        and not text.startswith(("#", "data:", "blob:"))
        and (
            "://" in text
            or text.startswith("//")
            or text.lower().startswith(("http:", "https:", "file:"))
        )
    )


def _viewbox_size(root: ET.Element) -> list[float] | None:
    raw = root.get("viewBox") or root.get("viewbox")
    if not raw:
        return None
    values = [value for value in re.split(r"[\s,]+", raw.strip()) if value]
    if len(values) != 4:
        return None
    try:
        width, height = float(values[2]), float(values[3])
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return [width, height]


def _natural_size(root: ET.Element, fallback: Sequence[float] | None) -> list[float] | None:
    width_match = _SIZE_RE.match(str(root.get("width") or ""))
    height_match = _SIZE_RE.match(str(root.get("height") or ""))
    if width_match and height_match:
        width = float(width_match.group(1))
        height = float(height_match.group(1))
        if width > 0 and height > 0:
            return [width, height]
    viewbox = _viewbox_size(root)
    if viewbox:
        return viewbox
    if fallback and len(fallback) >= 2:
        try:
            width, height = float(fallback[0]), float(fallback[1])
        except (TypeError, ValueError):
            return None
        if width > 0 and height > 0:
            return [width, height]
    return None


def _sanitize_tree(root: ET.Element) -> tuple[ET.Element, list[str]]:
    clean = copy.deepcopy(root)
    reasons: list[str] = []
    for parent in clean.iter():
        for child in list(parent):
            name = _local_name(child.tag)
            if name in {"script", "foreignobject", "iframe", "object", "embed"}:
                parent.remove(child)
                reasons.append(f"removed-{name}")
    for element in clean.iter():
        for name in list(element.attrib):
            local = _local_name(name)
            value = str(element.attrib[name])
            if local.startswith("on"):
                element.attrib.pop(name, None)
                reasons.append("removed-event-handler")
                continue
            if local in {"href", "src", "xlink:href"} and _is_external_url(value):
                element.attrib.pop(name, None)
                reasons.append("removed-external-reference")
                continue
            if "url(" in value.lower():
                urls = [match.group(2) for match in _URL_VALUE_RE.finditer(value)]
                if any(_is_external_url(url) for url in urls):
                    element.attrib.pop(name, None)
                    reasons.append("removed-unsafe-css-url")
    return clean, list(dict.fromkeys(reasons))


def _serialize(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=False)


def classify_svg_source(
    svg_bytes: bytes,
    *,
    page_url: str,
    fallback_size: Sequence[float] | None = None,
) -> dict[str, Any]:
    payload = bytes(svg_bytes or b"")
    reason_set: list[str] = []
    if not payload:
        return {
            "mode": "blocked",
            "reasons": ["empty-svg"],
            "rasterAllowed": False,
            "naturalSize": None,
            "sha256": _sha256(payload),
            "sanitizedSha256": None,
        }
    if len(payload) > MAX_SVG_BYTES:
        return {
            "mode": "blocked",
            "reasons": ["svg-size-exceeded"],
            "rasterAllowed": False,
            "naturalSize": None,
            "sha256": _sha256(payload),
            "sanitizedSha256": None,
        }
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return {
            "mode": "blocked",
            "reasons": ["invalid-xml"],
            "rasterAllowed": False,
            "naturalSize": None,
            "sha256": _sha256(payload),
            "sanitizedSha256": None,
        }
    if _local_name(root.tag) != "svg":
        return {
            "mode": "blocked",
            "reasons": ["root-is-not-svg"],
            "rasterAllowed": False,
            "naturalSize": None,
            "sha256": _sha256(payload),
            "sanitizedSha256": None,
        }

    same_document_use = False
    external_image = False
    external_use = False
    has_script = False
    for element in root.iter():
        name = _local_name(element.tag)
        if name == "script":
            has_script = True
            reason_set.append("script")
        if name == "image":
            href = element.get("href") or element.get("{http://www.w3.org/1999/xlink}href") or ""
            if _is_external_url(href):
                external_image = True
                reason_set.append("external-image")
        if name == "use":
            href = element.get("href") or element.get("{http://www.w3.org/1999/xlink}href") or ""
            if href.startswith("#"):
                same_document_use = True
            elif _is_external_url(href):
                external_use = True
                reason_set.append("external-use")
        for attr_value in element.attrib.values():
            if any(_is_external_url(match.group(2)) for match in _URL_VALUE_RE.finditer(attr_value)):
                reason_set.append("unsafe-css-url")

    if has_script:
        mode = "blocked"
    elif external_image or external_use or "unsafe-css-url" in reason_set:
        mode = "raster-required"
    elif same_document_use:
        mode = "sanitized-vector"
    else:
        mode = "vector-preferred"
    clean, sanitize_reasons = _sanitize_tree(root)
    sanitized = _serialize(clean)
    return {
        "mode": mode,
        "reasons": list(dict.fromkeys([*reason_set, *sanitize_reasons])),
        "rasterAllowed": mode != "blocked",
        "naturalSize": _natural_size(root, fallback_size),
        "sameDocumentUse": same_document_use,
        "externalImage": external_image,
        "externalUse": external_use,
        "sha256": _sha256(payload),
        "sanitizedSha256": _sha256(sanitized),
        "sanitizedBytes": sanitized,
    }


def _svg_bytes(node: Mapping[str, Any]) -> bytes | None:
    raw = node.get("svgBytes")
    if isinstance(raw, bytes):
        return raw
    source = node.get("svgSource") or node.get("svg")
    if isinstance(source, str):
        return source.encode("utf-8")
    data = node.get("svgDataUri")
    if isinstance(data, str) and data.startswith("data:image/svg+xml"):
        try:
            header, body = data.split(",", 1)
            if ";base64" in header:
                return base64.b64decode(body)
            return unquote_to_bytes(body)
        except (ValueError, TypeError):
            return None
    return None


def materialize_svg_assets(
    dom_nodes: Sequence[Mapping[str, Any]],
    output_dir: Path,
    *,
    page_url: str = "",
) -> dict[str, Any]:
    destination = Path(output_dir)
    assets_dir = destination / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, node in enumerate(dom_nodes):
        if not isinstance(node, Mapping):
            continue
        payload = _svg_bytes(node)
        if payload is None:
            continue
        classification = classify_svg_source(
            payload,
            page_url=page_url,
            fallback_size=[node.get("w"), node.get("h")],
        )
        original_sha = str(classification["sha256"])
        original_path = assets_dir / f"{original_sha}.svg"
        if not original_path.exists():
            original_path.write_bytes(payload)
        row = {
            "domIndex": index,
            "mode": classification["mode"],
            "reasons": list(classification["reasons"]),
            "naturalSize": classification["naturalSize"],
            "originalSha256": original_sha,
            "originalVectorPath": f"assets/{original_path.name}",
            "sanitizedSha256": classification["sanitizedSha256"],
            "displayMode": None,
            "displayPayloadPath": None,
        }
        sanitized = classification.get("sanitizedBytes")
        if isinstance(sanitized, bytes):
            sanitized_path = assets_dir / f"{classification['sanitizedSha256']}.svg"
            if not sanitized_path.exists():
                sanitized_path.write_bytes(sanitized)
            row["sanitizedVectorPath"] = f"assets/{sanitized_path.name}"
        if classification["mode"] in {"vector-preferred", "sanitized-vector"}:
            if isinstance(sanitized, bytes):
                png_path = assets_dir / f"{classification['sanitizedSha256']}.png"
                size = classification.get("naturalSize") or [
                    float(node.get("w") or 1),
                    float(node.get("h") or 1),
                ]
                from src.app.utils.svg_raster import rasterize_svg

                rasterize_svg(
                    sanitized_path,
                    png_path,
                    width=max(1, int(round(float(size[0])))),
                    height=max(1, int(round(float(size[1])))),
                    wait_ms=0,
                )
                png_sha = _sha256(png_path.read_bytes())
                retained_png = assets_dir / f"{png_sha}.png"
                if retained_png != png_path and not retained_png.exists():
                    png_path.replace(retained_png)
                elif retained_png != png_path:
                    png_path.unlink(missing_ok=True)
                row.update(
                    {
                        "displayMode": "svg-rasterized",
                        "displayPayloadPath": f"assets/{retained_png.name}",
                        "displaySha256": png_sha,
                    }
                )
        elif classification["mode"] == "raster-required":
            row.update(
                {
                    "displayMode": "source-crop",
                    "visualFallbackReason": "svg-external-resource",
                }
            )
        else:
            row["visualFallbackReason"] = "svg-blocked"
        rows.append(row)
    manifest = {
        "schema_version": SVG_MATERIALIZATION_SCHEMA_VERSION,
        "page_url": page_url,
        "assets": rows,
        "counts": {
            mode: sum(row["mode"] == mode for row in rows)
            for mode in (
                "vector-preferred",
                "sanitized-vector",
                "raster-required",
                "blocked",
            )
        },
    }
    (destination / "00_svg.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
