from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

FONT_BUNDLE_SCHEMA_VERSION = "dom-font-bundle/1.0"
_GENERIC_FAMILIES = {
    "serif",
    "sans-serif",
    "monospace",
    "cursive",
    "fantasy",
    "system-ui",
    "ui-serif",
    "ui-sans-serif",
    "ui-monospace",
}


def _family_list(value: Any) -> list[str]:
    return [
        item.strip().strip("\"'")
        for item in re.split(r"\s*,\s*", str(value or ""))
        if item.strip()
    ]


def _is_generic(value: Any) -> bool:
    families = _family_list(value)
    return bool(families) and all(item.lower() in _GENERIC_FAMILIES for item in families)


def _resource_faces(resources: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    faces: list[dict[str, Any]] = []
    for resource in resources:
        if not isinstance(resource, Mapping):
            continue
        nested = resource.get("faces")
        rows = nested if isinstance(nested, Sequence) and not isinstance(nested, str) else [resource]
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            family = str(row.get("family") or row.get("familyName") or "").strip()
            if not family:
                continue
            source_url = str(
                row.get("source_url")
                or row.get("sourceUrl")
                or row.get("url")
                or row.get("resourceUrl")
                or ""
            ).strip()
            body = row.get("bytes")
            sha256 = str(row.get("sha256") or "").strip()
            if isinstance(body, bytes) and body:
                sha256 = sha256 or hashlib.sha256(body).hexdigest()
            status = str(row.get("status") or "").strip()
            if not status:
                status = "verified" if sha256 and body else "reference-only"
            faces.append(
                {
                    "family": family,
                    "style": str(row.get("style") or "normal"),
                    "weight": row.get("weight", 400),
                    "status": status,
                    "source_url": source_url or None,
                    "mime": row.get("mime") or row.get("contentType") or None,
                    "sha256": sha256 or None,
                    "source_status": (
                        "verified" if sha256 and body else "reference-only"
                    ),
                }
            )
    return faces


def _font_node_id(index: int) -> str:
    return f"n{index}"


def build_font_manifest(
    font_resources: Sequence[Mapping[str, Any]],
    nodes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    faces = _resource_faces(font_resources)
    node_rows: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    fallback_order: list[str] = []
    for face in faces:
        family = str(face.get("family") or "")
        if family and family not in fallback_order:
            fallback_order.append(family)

    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            continue
        text = str(node.get("text") or "")
        placeholder = str(node.get("placeholder") or "")
        if not text and not placeholder and str(node.get("tag") or "") not in {
            "input",
            "textarea",
        }:
            continue
        node_id = _font_node_id(index)
        requested = str(
            node.get("fontFamilyRequested") or node.get("fontFamily") or ""
        ).strip()
        platform_fonts = [
            row
            for row in (node.get("platformFonts") or [])
            if isinstance(row, Mapping) and str(row.get("familyName") or "").strip()
        ]
        actual_families = list(
            dict.fromkeys(
                str(row["familyName"]).strip()
                for row in platform_fonts
            )
        )
        resolution = str(node.get("fontFamilyResolution") or "").strip()
        resolved_family: str | None = None
        if resolution in {"ambiguous-platform-font", "font-evidence-missing"}:
            resolved_family = None
        elif len(actual_families) == 1:
            resolved_family = actual_families[0]
            resolution = resolution or "browser-platform-font"
        elif len(actual_families) > 1:
            resolution = "ambiguous-platform-font"
        elif requested and not _is_generic(requested):
            resolved_family = _family_list(requested)[0]
            resolution = resolution or "declared-family"
        else:
            resolution = resolution or "font-evidence-missing"

        row = {
            "sourceIndex": index,
            "requestedFamily": requested or None,
            "resolvedFamily": resolved_family,
            "actualFamilies": actual_families,
            "resolution": resolution,
            "fontStyle": str(node.get("fontStyle") or "normal"),
            "fontWeight": node.get("fontWeight"),
            "fontSize": node.get("fontSize"),
        }
        node_rows[node_id] = row
        if not resolved_family:
            unresolved.append(node_id)

    return {
        "schema_version": FONT_BUNDLE_SCHEMA_VERSION,
        "faces": faces,
        "fallbackOrder": fallback_order,
        "nodes": node_rows,
        "unresolved": unresolved,
    }
