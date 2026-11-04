"""Deterministic evidence, content, and geometry projections."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from src.app.services.structure.fidelity.contracts import (
    EVIDENCE_SCHEMA_VERSION,
    GEOMETRY_SCHEMA_VERSION,
    INVENTORY_SCHEMA_VERSION,
    canonical_json,
    evidence_record,
    normalize_bbox,
    normalize_match_text,
    reference_sha256,
    reference_size,
    stable_id,
)

_CONTROL_TYPES = {
    "button",
    "checkbox",
    "icon-button",
    "input",
    "navigation",
    "pagination",
    "radio",
    "select",
    "textarea",
    "toggle",
}
_CHECK_TYPES = {"checkbox", "radio"}
_ASSET_TYPES = {"image", "avatar"}


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _source_box(item: Mapping[str, Any], width: int, height: int) -> list[int] | None:
    return normalize_bbox(item.get("bbox"), width, height)


def _append_record(
    records: list[dict[str, Any]],
    *,
    kind: str,
    source: Any,
    bbox: Any,
    width: int,
    height: int,
    payload_ref: str,
    record: Mapping[str, Any] | None = None,
    reason: str = "",
) -> None:
    index = len(records) + 1
    records.append(
        evidence_record(
            record_id=f"evidence-{index:04d}",
            kind=kind,
            source=source,
            bbox=bbox,
            width=width,
            height=height,
            payload_ref=payload_ref,
            record=record,
            default_reason=reason,
        )
    )


def build_evidence_bundle(
    graph: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy all candidate facts into one immutable, provenance-aware bundle."""
    if not isinstance(graph, Mapping):
        raise ValueError("graph must be an object")
    if not isinstance(reference, Mapping):
        raise ValueError("reference must be an object")
    width, height = reference_size(reference)
    graph_width = int(graph.get("image_w") or width)
    graph_height = int(graph.get("image_h") or height)
    if graph_width != width or graph_height != height:
        raise ValueError("graph and reference image sizes must match")

    graph_copy = copy.deepcopy(dict(graph))
    reference_copy = copy.deepcopy(dict(reference))
    records: list[dict[str, Any]] = []

    for index, item in enumerate(_mapping_list(graph_copy.get("containers"))):
        _append_record(
            records,
            kind="container",
            source=item.get("source"),
            bbox=item.get("bbox"),
            width=width,
            height=height,
            payload_ref=f"graph.containers[{index}]",
            record=item,
        )
    for index, item in enumerate(_mapping_list(graph_copy.get("elements"))):
        element_type = str(item.get("controlType") or item.get("type") or "").lower()
        kind = (
            "asset"
            if element_type in _ASSET_TYPES
            else "control"
            if element_type in _CONTROL_TYPES
            else "text"
            if str(item.get("text") or "").strip()
            else "element"
        )
        _append_record(
            records,
            kind=kind,
            source=item.get("source"),
            bbox=item.get("bbox"),
            width=width,
            height=height,
            payload_ref=f"graph.elements[{index}]",
            record=item,
        )
    for index, item in enumerate(_mapping_list(graph_copy.get("tables"))):
        _append_record(
            records,
            kind="table",
            source=item.get("source") or "image-enrichment",
            bbox=item.get("bbox"),
            width=width,
            height=height,
            payload_ref=f"graph.tables[{index}]",
            record=item,
        )

    enrichment = graph_copy.get("imageEnrichment")
    if isinstance(enrichment, Mapping):
        for index, item in enumerate(_mapping_list(enrichment.get("assets"))):
            _append_record(
                records,
                kind="asset",
                source=item.get("source") or "image-enrichment",
                bbox=item.get("bbox"),
                width=width,
                height=height,
                payload_ref=f"graph.imageEnrichment.assets[{index}]",
                record=item,
            )
        for index, item in enumerate(_mapping_list(enrichment.get("backgrounds"))):
            _append_record(
                records,
                kind="background",
                source=item.get("source") or "image-enrichment",
                bbox=item.get("bbox"),
                width=width,
                height=height,
                payload_ref=f"graph.imageEnrichment.backgrounds[{index}]",
                record=item,
            )

    slicing = graph_copy.get("sliceAnalysis")
    if isinstance(slicing, Mapping):
        for index, item in enumerate(_mapping_list(slicing.get("assets"))):
            _append_record(
                records,
                kind="asset",
                source=item.get("source") or "slice",
                bbox=item.get("bbox"),
                width=width,
                height=height,
                payload_ref=f"graph.sliceAnalysis.assets[{index}]",
                record=item,
                reason="slice candidate is evidence only",
            )
        for index, item in enumerate(_mapping_list(slicing.get("backgrounds"))):
            _append_record(
                records,
                kind="background",
                source=item.get("source") or "slice",
                bbox=item.get("bbox"),
                width=width,
                height=height,
                payload_ref=f"graph.sliceAnalysis.backgrounds[{index}]",
                record=item,
                reason="slice candidate is evidence only",
            )

    provenance = graph_copy.get("provenance")
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "status": "collected",
        "reference_id": str(reference_copy.get("reference_id") or ""),
        "image_size": [width, height],
        "image_sha256": reference_sha256(reference_copy),
        "coordinate_basis": "source-pixel-top-left",
        "reference": reference_copy,
        "provenance": copy.deepcopy(
            dict(provenance) if isinstance(provenance, Mapping) else {}
        ),
        "sources": {
            "graph": graph_copy,
            "reference": reference_copy,
        },
        "source_graph_sha256": __import__("hashlib")
        .sha256(canonical_json(graph_copy).encode("utf-8"))
        .hexdigest(),
        "records": records,
    }


def _row_values(value: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    if not isinstance(value, list):
        return rows
    for row in value:
        if isinstance(row, (list, tuple)):
            rows.append([str(cell) for cell in row])
        elif isinstance(row, Mapping):
            cells = row.get("cells")
            if isinstance(cells, (list, tuple)):
                rows.append([str(cell) for cell in cells])
    return rows


def _table_headers(table: Mapping[str, Any]) -> list[str]:
    raw = table.get("header_texts")
    if raw is None:
        raw = table.get("headers")
    return [str(value) for value in raw or []]


def _cell_bbox(
    table_bbox: list[int],
    *,
    row_index: int,
    column_index: int,
    row_count: int,
    column_count: int,
) -> list[int]:
    x, y, width, height = table_bbox
    left = x + round(column_index * width / max(1, column_count))
    right = x + round((column_index + 1) * width / max(1, column_count))
    top = y + round(row_index * height / max(1, row_count))
    bottom = y + round((row_index + 1) * height / max(1, row_count))
    return [left, top, max(1, right - left), max(1, bottom - top)]


def _coalesce_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coalesced: list[dict[str, Any]] = []
    indexes: dict[tuple[Any, ...], int] = {}
    for item in items:
        key = (
            item.get("kind"),
            normalize_match_text(item.get("text")),
            tuple(item.get("bbox") or []),
            str(item.get("role") or ""),
        )
        existing_index = indexes.get(key)
        if existing_index is None:
            indexes[key] = len(coalesced)
            coalesced.append(item)
            continue
        existing = coalesced[existing_index]
        refs = list(existing.get("evidence_refs") or [])
        for ref in item.get("evidence_refs") or []:
            if ref not in refs:
                refs.append(ref)
        existing["evidence_refs"] = refs
    return coalesced


def build_content_inventory(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Project evidence into the only allowed source of visible content."""
    if not isinstance(bundle, Mapping):
        raise ValueError("bundle must be an object")
    sources = bundle.get("sources")
    if not isinstance(sources, Mapping):
        raise ValueError("bundle sources must be an object")
    graph = sources.get("graph")
    if not isinstance(graph, Mapping):
        raise ValueError("bundle graph source must be an object")
    width, height = reference_size(
        sources.get("reference") or bundle.get("reference") or {}
    )
    graph = copy.deepcopy(dict(graph))
    element_records = _mapping_list(graph.get("elements"))
    text_geometry = [
        {
            "text": normalize_match_text(element.get("text")),
            "bbox": _source_box(element, width, height),
        }
        for element in element_records
        if str(element.get("type") or "").lower() in {"text", "link"}
        and str(element.get("text") or "").strip()
    ]
    items: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    unknowns: list[dict[str, Any]] = []

    for index, element in enumerate(_mapping_list(graph.get("elements"))):
        bbox = _source_box(element, width, height)
        if bbox is None:
            unknowns.append(
                {
                    "id": stable_id("unknown", "element", index),
                    "kind": "unknown",
                    "reason": "element bbox is missing, empty, or outside the canvas",
                    "source_ref": f"graph.elements[{index}]",
                }
            )
            continue
        candidate_type = str(
            element.get("controlType") or element.get("type") or "element"
        ).lower()
        text = str(
            element.get("controlValue")
            or element.get("value")
            or element.get("text")
            or ""
        )
        source_ref = f"graph.elements[{index}]"
        if candidate_type in _CONTROL_TYPES:
            label = ""
            control_text = text
            if candidate_type in {
                "button",
                "icon-button",
                "navigation",
                "pagination",
            } and normalize_match_text(text):
                match = next(
                    (
                        geometry
                        for geometry in text_geometry
                        if geometry["bbox"] is not None
                        and geometry["text"] == normalize_match_text(text)
                        and abs(
                            geometry["bbox"][1]
                            + geometry["bbox"][3] / 2
                            - (bbox[1] + bbox[3] / 2)
                        )
                        >= 32
                    ),
                    None,
                )
                if match is not None:
                    text_x, text_y, text_width, text_height = match["bbox"]
                    bbox = [
                        max(0, text_x - 8),
                        max(0, text_y - 8),
                        min(width - max(0, text_x - 8), text_width + 16),
                        min(height - max(0, text_y - 8), text_height + 16),
                    ]
            if candidate_type in _CHECK_TYPES:
                label = str(
                    element.get("label")
                    or element.get("controlValue")
                    or element.get("text")
                    or ""
                )
                control_text = ""
            items.append(
                {
                    "id": stable_id("control", element.get("id"), source_ref),
                    "kind": "control",
                    "text": control_text,
                    "label": label,
                    "control_type": candidate_type,
                    "state": str(
                        element.get("controlState") or element.get("state") or ""
                    ),
                    "bbox": bbox,
                    "role": str(element.get("role") or ""),
                    "source_ref": source_ref,
                    "authority": "image-enrichment"
                    if "image-enrichment" in str(element.get("source") or "")
                    else "grounding",
                    "evidence_refs": [],
                }
            )
            if label:
                items.append(
                    {
                        "id": stable_id("text", "checkbox-label", element.get("id")),
                        "kind": "text",
                        "text": label,
                        "bbox": bbox,
                        "role": "control-label",
                        "source_ref": source_ref,
                        "authority": "grounding",
                        "evidence_refs": [],
                    }
                )
            continue
        if candidate_type in _ASSET_TYPES:
            items.append(
                {
                    "id": stable_id("asset", element.get("id"), source_ref),
                    "kind": "asset",
                    "text": str(element.get("assetName") or element.get("name") or ""),
                    "asset_kind": str(
                        element.get("assetKind")
                        or element.get("kind")
                        or candidate_type
                    ),
                    "bbox": bbox,
                    "role": str(element.get("role") or ""),
                    "reference_only": True,
                    "original": False,
                    "source_ref": source_ref,
                    "authority": "source-pixel",
                    "evidence_refs": [],
                }
            )
            continue
        if str(element.get("text") or "").strip():
            items.append(
                {
                    "id": stable_id("text", element.get("id"), source_ref),
                    "kind": "text",
                    "text": str(element.get("text")),
                    "bbox": bbox,
                    "role": str(element.get("role") or ""),
                    "source_ref": source_ref,
                    "authority": "ocr"
                    if "ocr" in str(element.get("source") or "").lower()
                    else "grounding",
                    "evidence_refs": [],
                }
            )

    for index, table in enumerate(_mapping_list(graph.get("tables"))):
        table_bbox = _source_box(table, width, height)
        if table_bbox is None:
            unknowns.append(
                {
                    "id": stable_id("unknown", "table", index),
                    "kind": "unknown",
                    "reason": "table bbox is missing, empty, or outside the canvas",
                    "source_ref": f"graph.tables[{index}]",
                }
            )
            continue
        headers = _table_headers(table)
        rows = _row_values(table.get("rows"))
        column_count = max(
            len(headers),
            max((len(row) for row in rows), default=0),
        )
        row_count = len(rows) + (1 if headers else 0)
        table_id = str(table.get("id") or f"table:{index}")
        tables.append(
            {
                "id": table_id,
                "name": str(table.get("name") or ""),
                "bbox": table_bbox,
                "headers": headers,
                "rows": rows,
                "row_count": len(rows),
                "column_count": column_count,
                "authority": "image-enrichment",
                "source_ref": f"graph.tables[{index}]",
            }
        )
        if headers:
            for column_index, header in enumerate(headers):
                items.append(
                    {
                        "id": stable_id("table-header", table_id, column_index),
                        "kind": "table-header",
                        "text": header,
                        "table_id": table_id,
                        "row_index": None,
                        "column_index": column_index,
                        "bbox": _cell_bbox(
                            table_bbox,
                            row_index=0,
                            column_index=column_index,
                            row_count=row_count,
                            column_count=column_count,
                        ),
                        "source_ref": f"graph.tables[{index}].header_texts[{column_index}]",
                        "authority": "image-enrichment",
                        "evidence_refs": [],
                    }
                )
        for row_index, row in enumerate(rows):
            for column_index, cell in enumerate(row):
                items.append(
                    {
                        "id": stable_id(
                            "table-cell",
                            table_id,
                            row_index,
                            column_index,
                        ),
                        "kind": "table-cell",
                        "text": cell,
                        "table_id": table_id,
                        "row_index": row_index,
                        "column_index": column_index,
                        "bbox": _cell_bbox(
                            table_bbox,
                            row_index=row_index + (1 if headers else 0),
                            column_index=column_index,
                            row_count=row_count,
                            column_count=column_count,
                        ),
                        "source_ref": (
                            f"graph.tables[{index}].rows"
                            f"[{row_index}][{column_index}]"
                        ),
                        "authority": "image-enrichment",
                        "evidence_refs": [],
                    }
                )

    asset_items: list[dict[str, Any]] = []
    asset_index: dict[tuple[Any, ...], int] = {}
    enrichment = graph.get("imageEnrichment")
    slicing = graph.get("sliceAnalysis")
    asset_sources: list[tuple[str, Any]] = []
    if isinstance(enrichment, Mapping):
        asset_sources.append(("graph.imageEnrichment.assets", enrichment.get("assets")))
    if isinstance(slicing, Mapping):
        asset_sources.append(("graph.sliceAnalysis.assets", slicing.get("assets")))
    for source_ref, assets in asset_sources:
        for index, asset in enumerate(_mapping_list(assets)):
            bbox = _source_box(asset, width, height)
            if bbox is None:
                unknowns.append(
                    {
                        "id": stable_id("unknown", source_ref, index),
                        "kind": "unknown",
                        "reason": "asset bbox is missing, empty, or outside the canvas",
                        "source_ref": f"{source_ref}[{index}]",
                    }
                )
                continue
            name = str(asset.get("name") or asset.get("id") or "")
            asset_kind = str(asset.get("kind") or "image")
            key = (normalize_match_text(name), asset_kind, tuple(bbox))
            ref = f"{source_ref}[{index}]"
            existing_index = asset_index.get(key)
            if existing_index is not None:
                asset_items[existing_index]["evidence_refs"].append(ref)
                continue
            asset_index[key] = len(asset_items)
            asset_items.append(
                {
                    "id": stable_id("asset", name, asset_kind, bbox),
                    "kind": "asset",
                    "text": name,
                    "asset_kind": asset_kind,
                    "bbox": bbox,
                    "role": str(asset.get("role") or ""),
                    "reference_only": True,
                    "original": False,
                    "payload_sha256": str(
                        (asset.get("visibleCrop") or {}).get("payload_sha256")
                        if isinstance(asset.get("visibleCrop"), Mapping)
                        else asset.get("payload_sha256") or ""
                    ),
                    "source_ref": ref,
                    "authority": "slice"
                    if "sliceAnalysis" in source_ref
                    else "image-enrichment",
                    "evidence_refs": [ref],
                }
            )
    items.extend(asset_items)

    for record in _mapping_list(bundle.get("records")):
        if str(record.get("kind") or "") == "unknown":
            unknowns.append(copy.deepcopy(dict(record)))

    items = _coalesce_items(items)
    items.sort(
        key=lambda item: (
            int((item.get("bbox") or [0, 0, 0, 0])[1]),
            int((item.get("bbox") or [0, 0, 0, 0])[0]),
            str(item.get("kind") or ""),
            normalize_match_text(item.get("text")),
        )
    )
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "status": "complete" if not unknowns else "partial",
        "reference_id": str(bundle.get("reference_id") or ""),
        "image_size": [width, height],
        "items": items,
        "tables": tables,
        "unknowns": unknowns,
    }


def build_geometry_manifest(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Project inventory and source regions into one top-left pixel geometry."""
    inventory = build_content_inventory(bundle)
    width, height = (int(value) for value in inventory["image_size"])
    items: list[dict[str, Any]] = [
        {
            "id": "geometry:page",
            "kind": "page",
            "role": "page",
            "bbox": [0, 0, width, height],
            "content_ref": None,
            "source_ref": "reference.input.size",
        }
    ]
    seen: set[tuple[Any, ...]] = set()
    sources = bundle["sources"]
    graph = copy.deepcopy(dict(sources["graph"]))

    def add(
        *,
        kind: str,
        role: str,
        bbox: Any,
        content_ref: Any = None,
        source_ref: str,
    ) -> None:
        normalized = normalize_bbox(bbox, width, height)
        if normalized is None:
            return
        key = (kind, role, tuple(normalized), content_ref)
        if key in seen:
            return
        seen.add(key)
        items.append(
            {
                "id": stable_id("geometry", kind, role, normalized, content_ref),
                "kind": kind,
                "role": role,
                "bbox": normalized,
                "content_ref": content_ref,
                "source_ref": source_ref,
            }
        )

    for index, container in enumerate(_mapping_list(graph.get("containers"))):
        add(
            kind="container",
            role=str(container.get("role") or container.get("name") or "container"),
            bbox=container.get("bbox"),
            source_ref=f"graph.containers[{index}]",
        )
    for index, element in enumerate(_mapping_list(graph.get("elements"))):
        candidate_type = str(
            element.get("controlType") or element.get("type") or "element"
        ).lower()
        if candidate_type in _CONTROL_TYPES:
            kind = "control"
        elif candidate_type in _ASSET_TYPES:
            kind = "asset"
        elif str(element.get("text") or "").strip():
            kind = "text"
        else:
            continue
        add(
            kind=kind,
            role=str(element.get("role") or candidate_type),
            bbox=element.get("bbox"),
            content_ref=str(element.get("id") or f"element:{index}"),
            source_ref=f"graph.elements[{index}]",
        )
    for table_index, table in enumerate(inventory["tables"]):
        table_bbox = table["bbox"]
        detected_grid = None
        image_path = str(graph.get("image") or "")
        if image_path:
            from src.app.services.structure.image_enrichment.table_scene import (
                detect_table_grid,
            )

            x, y, table_width, table_height = table_bbox
            expanded_bbox = [
                x,
                max(0, y - 140),
                table_width,
                min(height - max(0, y - 140), table_height + 140),
            ]
            detected_grid = detect_table_grid(image_path, expanded_bbox)
        x_boundaries: list[int] = []
        y_boundaries: list[int] = []
        if isinstance(detected_grid, Mapping):
            source_x, source_y, _source_width, _source_height = detected_grid[
                "source_bbox"
            ]
            x_boundaries = [
                source_x + int(value)
                for value in detected_grid.get("x_boundaries") or []
            ]
            y_boundaries = [
                source_y + int(value)
                for value in detected_grid.get("y_boundaries") or []
            ]
            expected_columns = int(table["column_count"]) + 1
            expected_rows = int(table["row_count"]) + (1 if table["headers"] else 0) + 1
            if len(x_boundaries) > expected_columns:
                x_boundaries = x_boundaries[-expected_columns:]
            if len(y_boundaries) > expected_rows:
                y_boundaries = y_boundaries[-expected_rows:]
            if len(x_boundaries) >= 2 and len(y_boundaries) >= 2:
                table_bbox = [
                    x_boundaries[0],
                    y_boundaries[0],
                    x_boundaries[-1] - x_boundaries[0],
                    y_boundaries[-1] - y_boundaries[0],
                ]
        table_geometry = {
            "id": stable_id(
                "geometry",
                "table",
                "table",
                table_bbox,
                table["id"],
            ),
            "kind": "table",
            "role": "table",
            "bbox": table_bbox,
            "content_ref": table["id"],
            "source_ref": table["source_ref"],
        }
        if len(x_boundaries) >= 2 and len(y_boundaries) >= 2:
            table_geometry["grid"] = {
                "x_boundaries": x_boundaries,
                "y_boundaries": y_boundaries,
            }
        items.append(table_geometry)
        seen.add(("table", "table", tuple(table_bbox), table["id"]))
        column_count = int(table["column_count"])
        row_count = int(table["row_count"]) + (1 if table["headers"] else 0)
        if len(x_boundaries) != column_count + 1:
            x_boundaries = [
                table_bbox[0] + round(index * table_bbox[2] / column_count)
                for index in range(column_count + 1)
            ]
        if len(y_boundaries) != row_count + 1:
            y_boundaries = [
                table_bbox[1] + round(index * table_bbox[3] / row_count)
                for index in range(row_count + 1)
            ]
        for column_index in range(column_count):
            column_bbox = [
                x_boundaries[column_index],
                table_bbox[1],
                x_boundaries[column_index + 1] - x_boundaries[column_index],
                table_bbox[3],
            ]
            add(
                kind="table-column",
                role="table-column",
                bbox=column_bbox,
                content_ref=f"{table['id']}:column:{column_index}",
                source_ref=f"{table['source_ref']}.column[{column_index}]",
            )
        for row_index in range(row_count):
            row_bbox = [
                table_bbox[0],
                y_boundaries[row_index],
                table_bbox[2],
                y_boundaries[row_index + 1] - y_boundaries[row_index],
            ]
            add(
                kind="table-row",
                role="table-row",
                bbox=row_bbox,
                content_ref=f"{table['id']}:row:{row_index}",
                source_ref=f"{table['source_ref']}.row[{row_index}]",
            )
    for item in inventory["items"]:
        role = str(item.get("role") or item.get("kind") or "")
        add(
            kind=str(item["kind"]),
            role=role,
            bbox=item.get("bbox"),
            content_ref=item["id"],
            source_ref=str(item.get("source_ref") or ""),
        )
    return {
        "schema_version": GEOMETRY_SCHEMA_VERSION,
        "status": "complete",
        "reference_id": inventory["reference_id"],
        "image_size": [width, height],
        "coordinate_basis": "source-pixel-top-left",
        "items": items,
    }
