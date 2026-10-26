"""Read-only evidence extraction for generated Axure RP 8 documents."""

from __future__ import annotations

import hashlib
import uuid
import zipfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import c1, constants, doc, model, store, writer

AXURE_RP8_INSPECTION_SCHEMA_VERSION = "axure-rp8-inspection/1.0"


def inspect_rp(path: str | Path) -> dict[str, Any]:
    """Inspect pages and widgets in one generated `.rp` without executing it."""
    artifact = Path(path)
    with zipfile.ZipFile(artifact) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    registry = _read_page_registry(members)
    pages = []
    for name, package_guid in registry:
        member = writer.package_member_path(writer.PAGE_DIR, package_guid)
        if member not in members:
            pages.append(
                {
                    "name": name,
                    "package_guid": str(package_guid),
                    "member": member,
                    "exists": False,
                    "widget_counts": {},
                    "widgets": [],
                }
            )
            continue
        pages.append(_inspect_page(name, package_guid, member, members[member]))
    assets = [
        {
            "page": page["name"],
            "label": widget["label"],
            "sha256": widget["image_sha256"],
            "bytes": widget["image_bytes"],
            "extension": widget["image_extension"],
        }
        for page in pages
        for widget in page["widgets"]
        if widget["kind"] == "Image"
    ]
    return {
        "schema_version": AXURE_RP8_INSPECTION_SCHEMA_VERSION,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "artifact_size": artifact.stat().st_size,
        "member_count": len(members),
        "page_count": len(pages),
        "pages": pages,
        "asset_count": len(assets),
        "assets": sorted(
            assets,
            key=lambda row: (row["page"], row["label"], row["sha256"] or ""),
        ),
        "self_check": writer.self_check(members),
        "integrity": writer.integrity_check(members),
    }


def compare_rp_to_design(
    report: Mapping[str, Any],
    design: Mapping[str, Any],
    *,
    route: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare actual `.rp` records with the captured DesignSpec."""
    pages = list(report.get("pages") or [])
    source_pages = _source_pages(design)
    mismatches: list[dict[str, Any]] = []
    expected_names = [str(page.get("name") or "") for page in source_pages]
    actual_names = [str(page.get("name") or "") for page in pages]
    if actual_names != expected_names:
        mismatches.append(
            {
                "kind": "page-order",
                "expected": expected_names,
                "actual": actual_names,
            }
        )

    widget_count = 0
    asset_count = 0
    auxiliary_widget_count = 0
    auxiliary_widgets: list[dict[str, Any]] = []
    content_mismatches = 0
    geometry_deltas: list[dict[str, Any]] = []
    for frame_index, (source_page, actual_page) in enumerate(zip(source_pages, pages)):
        page_name = str(source_page.get("name") or f"Page {frame_index + 1}")
        actual_widgets = list(actual_page.get("widgets") or [])
        widget_count += len(actual_widgets)
        expected_widgets = _expected_widgets(source_page)
        text_labels = {
            str(widget.get("label") or "")
            for widget in expected_widgets
            if widget.get("kind") in {"Text", "Button", "TextField"}
        }
        matched_actual: set[int] = set()
        unmatched_text_backgrounds: list[dict[str, Any] | None] = []
        for expected in expected_widgets:
            expected_kind = str(expected.get("kind") or "")
            expected_label = str(expected.get("label") or "")
            candidates = [
                (index, actual)
                for index, actual in enumerate(actual_widgets)
                if index not in matched_actual
                and actual.get("kind") == expected_kind
                and str(actual.get("label") or "") == expected_label
            ]
            if not candidates:
                mismatches.append(
                    {
                        "kind": "widget-missing",
                        "page": page_name,
                        "widget": list(_widget_key(expected)),
                    }
                )
                continue
            index, actual = min(
                candidates,
                key=lambda pair: _geometry_distance(
                    expected.get("geometry") or {},
                    pair[1].get("geometry") or {},
                ),
            )
            matched_actual.add(index)
            if expected_kind == "Text" and expected.get("has_styled_background"):
                unmatched_text_backgrounds.append(
                    {
                        "source_label": expected_label,
                        "geometry": expected.get("geometry") or {},
                    }
                )
            expected_text = _normalize_text(expected.get("text"))
            actual_text = _normalize_text(actual.get("text"))
            if expected_text and expected_text != actual_text:
                content_mismatches += 1
                mismatches.append(
                    {
                        "kind": "text-missing",
                        "page": page_name,
                        "expected": expected.get("text"),
                        "actual": actual.get("text"),
                    }
                )
            geometry_mismatch = _geometry_mismatch(
                expected_kind,
                expected.get("geometry") or {},
                actual.get("geometry") or {},
            )
            height_delta = round(
                float((actual.get("geometry") or {}).get("height") or 0)
                - float((expected.get("geometry") or {}).get("height") or 0),
                4,
            )
            if height_delta:
                geometry_deltas.append(
                    {
                        "page": page_name,
                        "label": expected_label,
                        "kind": expected_kind,
                        "height_delta": height_delta,
                    }
                )
            if geometry_mismatch:
                mismatches.append(
                    {
                        "kind": "widget-geometry",
                        "page": page_name,
                        "label": expected_label,
                        "expected": expected.get("geometry"),
                        "actual": actual.get("geometry"),
                    }
                )

        for index, actual in enumerate(actual_widgets):
            if index in matched_actual:
                continue
            label = str(actual.get("label") or "")
            if actual.get("kind") == "Rect" and label in text_labels:
                auxiliary_widget_count += 1
                auxiliary_widgets.append(
                    _auxiliary_widget_record(
                        page_name,
                        label,
                        actual.get("geometry") or {},
                    )
                )
                continue
            if actual.get("kind") == "Rect" and not label:
                source_label = _match_text_background(
                    actual.get("geometry") or {},
                    unmatched_text_backgrounds,
                )
                if source_label is not None:
                    auxiliary_widget_count += 1
                    auxiliary_widgets.append(
                        _auxiliary_widget_record(
                            page_name,
                            source_label,
                            actual.get("geometry") or {},
                        )
                    )
                    continue
            mismatches.append(
                {
                    "kind": "widget-extra",
                    "page": page_name,
                    "widget": list(_widget_key(actual)),
                }
            )

        expected_assets = Counter(
            hashlib.sha256(doc.image_bytes(element.get("imageBase64"))).hexdigest()
            for element in source_page.get("elements") or []
            if isinstance(element, Mapping) and element.get("imageBase64")
        )
        actual_assets = Counter(
            str(widget.get("image_sha256") or "")
            for widget in actual_widgets
            if widget.get("kind") == "Image"
        )
        asset_count += sum(actual_assets.values())
        for digest, count in sorted((expected_assets - actual_assets).items()):
            mismatches.append(
                {
                    "kind": "asset-bytes",
                    "page": page_name,
                    "expected_sha256": digest,
                    "count": count,
                }
            )
        for digest, count in sorted((actual_assets - expected_assets).items()):
            mismatches.append(
                {
                    "kind": "asset-bytes",
                    "page": page_name,
                    "actual_sha256": digest,
                    "count": count,
                }
            )

    return {
        "schema_version": "axure-rp8-comparison/1.0",
        "document_id": (route or {}).get("document_id"),
        "ok": not mismatches,
        "page_count": len(pages),
        "widget_count": widget_count,
        "primary_widget_count": sum(
            len(_expected_widgets(page)) for page in source_pages
        ),
        "auxiliary_widget_count": auxiliary_widget_count,
        "auxiliary_widgets": auxiliary_widgets,
        "asset_count": asset_count,
        "content_mismatches": content_mismatches,
        "geometry_deltas": geometry_deltas,
        "mismatches": mismatches,
    }


def _auxiliary_widget_record(
    page_name: str,
    source_label: str,
    geometry: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "page": page_name,
        "source_label": source_label,
        "kind": "Rect",
        "geometry": {
            "x": round(float(geometry.get("x") or 0), 4),
            "y": round(float(geometry.get("y") or 0), 4),
            "width": round(float(geometry.get("width") or 0), 4),
            "height": round(float(geometry.get("height") or 0), 4),
        },
    }


def _match_text_background(
    rect: Mapping[str, Any],
    candidates: list[dict[str, Any] | None],
) -> str | None:
    """Consume one unlabeled Rect that exactly explains a matched text outer box."""
    for index, candidate in enumerate(candidates):
        if candidate is None:
            continue
        outer = candidate["geometry"]
        if any(
            abs(float(rect.get(key) or 0) - float(outer.get(key) or 0)) > 0.5
            for key in ("x", "y", "width", "height")
        ):
            continue
        candidates[index] = None
        return str(candidate["source_label"])
    return None


def _source_pages(design: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    pages = design.get("pages")
    if isinstance(pages, list) and pages:
        return [page for page in pages if isinstance(page, Mapping)]
    return [design]


def _expected_widgets(page: Mapping[str, Any]) -> list[dict[str, Any]]:
    canvas = page.get("canvas") if isinstance(page.get("canvas"), Mapping) else {}
    result = [
        {
            "label": "Background",
            "kind": "Rect",
            "geometry": {
                "x": 0.0,
                "y": 0.0,
                "width": float(canvas.get("width") or 800),
                "height": float(canvas.get("height") or 600),
            },
            "text": "",
            "image_sha256": None,
            "has_styled_background": False,
        }
    ]
    for element in page.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        source_kind = str(element.get("type") or "rectangle").lower()
        if element.get("imageBase64") and not str(element.get("text") or ""):
            kind = "Image"
        else:
            kind = {
                "text": "Text",
                "button": "Button",
                "input": "TextField",
                "image": "Image",
                "avatar": "Image",
                "circle": "Ellipse",
                "rectangle": "Rect",
                "container": "Rect",
                "divider": "Rect",
            }.get(source_kind, "Rect")
        payload = doc.image_bytes(element.get("imageBase64"))
        style = element.get("style")
        fill_color = style.get("fillColor") if isinstance(style, Mapping) else None
        result.append(
            {
                "label": " ".join(
                    str(element.get("name") or element.get("label") or "").split()
                ),
                "kind": kind,
                "geometry": {
                    "x": float(element.get("x") or 0),
                    "y": float(element.get("y") or 0),
                    "width": float(element.get("width") or 0),
                    "height": float(element.get("height") or 0),
                },
                "text": str(element.get("text") or ""),
                "image_sha256": (
                    hashlib.sha256(payload).hexdigest() if payload else None
                ),
                "has_styled_background": (
                    kind == "Text" and _has_renderable_background(fill_color)
                ),
            }
        )
    return result


def _has_renderable_background(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    color = value.strip().lower()
    if color in {"transparent", "none"}:
        return False
    hex_color = color.lstrip("#").upper()
    if len(hex_color) == 3:
        hex_color = "".join(channel * 2 for channel in hex_color)
    return hex_color not in {"FFFFFF", "FFFFFE", "FFFEFE", "FEFEFE"}


def _widget_key(widget: Mapping[str, Any]) -> tuple:
    geometry = widget.get("geometry") or {}
    return (
        str(widget.get("label") or ""),
        str(widget.get("kind") or ""),
        round(float(geometry.get("x") or 0), 4),
        round(float(geometry.get("y") or 0), 4),
        round(float(geometry.get("width") or 0), 4),
        round(float(geometry.get("height") or 0), 4),
    )


def _geometry_distance(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> float:
    return (
        abs(float(expected.get("x") or 0) - float(actual.get("x") or 0))
        + abs(float(expected.get("y") or 0) - float(actual.get("y") or 0))
        + abs(float(expected.get("width") or 0) - float(actual.get("width") or 0))
        + 0.25
        * abs(float(expected.get("height") or 0) - float(actual.get("height") or 0))
    )


def _geometry_mismatch(
    kind: str,
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> bool:
    tolerance = 2.5 if kind in {"Text", "Button"} else 0.5
    for key in ("x", "y", "width"):
        if abs(float(expected.get(key) or 0) - float(actual.get(key) or 0)) > tolerance:
            return True
    if kind not in {"Text", "Button"}:
        if (
            abs(float(expected.get("height") or 0) - float(actual.get("height") or 0))
            > tolerance
        ):
            return True
    return False


def _normalize_text(value: Any) -> str:
    return "".join(str(value or "").split())


def _read_page_registry(members: Mapping[str, bytes]) -> list[tuple[str, uuid.UUID]]:
    design_member = next(
        (name for name in members if name.startswith(writer.DESIGN_DOC_DIR + "/")),
        None,
    )
    if design_member is None:
        raise ValueError("Axure document has no DesignDocument member")
    parts = store.parts_of(members[design_member])
    if len(parts) != 1:
        raise ValueError("DesignDocument must contain one package part")
    _ver, names, _guids, items = c1.parse_stream(parts[0][1])
    registry = []
    for item in c1.iter_objects(items):
        if names[item[2]] != "Axure:PackageInfo":
            continue
        package_id = c1.dd_get(item[3], names, "package-id")
        if package_id is None or package_id[0] != c1.T_FX:
            continue
        if names[package_id[1]] != model.PAGE_KIND:
            continue
        name_value = c1.dd_get(item[3], names, "package-name")
        name = names[name_value[1]] if name_value is not None else ""
        package_guid = uuid.UUID(bytes_le=_guid_bytes(_guids, package_id[2]))
        registry.append((name, package_guid))
    return registry


def _inspect_page(
    name: str,
    package_guid: uuid.UUID,
    member: str,
    raw: bytes,
) -> dict[str, Any]:
    outer = store.parts_of(raw)
    if not outer:
        raise ValueError(f"Page member has no parts: {member}")
    layer2 = dict(store.parts_of(outer[0][1]))
    package = layer2.get("package")
    if package is None:
        raise ValueError(f"Page member has no package stream: {member}")
    _ver, names, guids, items = c1.parse_stream(package)
    objects = {item[1]: item for item in c1.iter_objects(items) if item[0] == c1.T_OBJ}
    diagram = next(
        (item for item in objects.values() if names[item[2]] == model.DIAGRAM_KIND),
        None,
    )
    if diagram is None:
        raise ValueError(f"Page member has no Axure:Diagram: {member}")
    root_refs = c1.dd_get(diagram[3], names, "diagram-objects")
    widgets = []
    if root_refs is not None:
        for ref in root_refs[1]:
            widget = objects.get(ref[1])
            if widget is not None:
                widgets.append(_inspect_widget(widget, names, guids, objects))
    counts = Counter(widget["kind"] for widget in widgets)
    return {
        "name": name,
        "package_guid": str(package_guid),
        "member": member,
        "exists": True,
        "widget_counts": dict(sorted(counts.items())),
        "widgets": widgets,
    }


def _inspect_widget(
    widget,
    names: list[Any],
    guids: list[Any],
    objects: Mapping[int, Any],
) -> dict[str, Any]:
    body = widget[3]
    label_block = c1.dd_get(body, names, "name-block")
    label_value = c1.dd_get(label_block, names, "text")
    label = names[label_value[1]] if label_value is not None else ""
    style_ref = c1.dd_get(body, names, "MyStyle")
    style = objects.get(style_ref[1]) if style_ref is not None else None
    style_name = _style_name(style, names)
    props = _style_props(style, names)
    geometry = _geometry(props, names)
    object_kind = names[widget[2]]
    shape = c1.dd_get(body, names, "Shape")
    if object_kind == model.IMAGE_BOX_KIND:
        kind = "Image"
    elif object_kind == model.TEXT_BOX_KIND:
        kind = "TextField"
    elif style_name == constants.BUTTON_STYLE_NAME:
        kind = "Button"
    elif shape is not None and shape[1] == constants.SHAPE_ELLIPSE:
        kind = "Ellipse"
    else:
        kind = "Rect"

    text = _widget_text(body, names, objects)
    if object_kind == model.SHAPE_KIND and not text and kind == "Rect":
        pass
    elif object_kind == model.SHAPE_KIND and text:
        kind = "Text" if style_name != constants.BUTTON_STYLE_NAME else "Button"

    image_sha256 = None
    image_bytes = None
    image_extension = None
    if kind == "Image":
        image_value = props.get(constants.P_IMAGE)
        stream = c1.dd_get(image_value, names, "Stream")
        extension = c1.dd_get(image_value, names, "Extension")
        if stream is not None and stream[0] == c1.T_BLOB:
            image_bytes = len(stream[1])
            image_sha256 = hashlib.sha256(stream[1]).hexdigest()
        if extension is not None and extension[0] == c1.T_STR:
            image_extension = names[extension[1]]

    return {
        "label": label,
        "kind": kind,
        "object_type": object_kind,
        "library_style": style_name,
        "autofit_width": bool(
            (autofit := c1.dd_get(body, names, "AutoFitWidth")) is not None
            and autofit[0] == c1.T_BOOL
            and autofit[1]
        ),
        "geometry": geometry,
        "text": text,
        "image_sha256": image_sha256,
        "image_bytes": image_bytes,
        "image_extension": image_extension,
        "object_guid": uuid.UUID(bytes_le=_guid_bytes(guids, widget[1])).hex,
    }


def _style_name(style, names: list[Any]) -> str:
    if style is None:
        return ""
    match = c1.dd_get(style[3], names, "MatchInfo")
    name_value = c1.dd_get(match, names, "Name")
    return names[name_value[1]] if name_value is not None else ""


def _style_props(style, names: list[Any]) -> dict[int, Any]:
    if style is None:
        return {}
    proplist = c1.dd_get(style[3], names, "PropList")
    if proplist is None:
        return {}
    props = {}
    for row in proplist[1]:
        doa_value = c1.dd_get(row, names, "DOAName")
        value = c1.dd_get(row, names, "Value")
        if doa_value is not None and value is not None:
            props[int(doa_value[1]) & 0x3FFFFFFF] = value
    return props


def _geometry(props: Mapping[int, Any], names: list[Any]) -> dict[str, float]:
    size = props.get(constants.P_SIZE)
    location = props.get(constants.P_LOCATION)
    width = _dd_number(size, names, "Width")
    height = _dd_number(size, names, "Height")
    x = _dd_number(location, names, "X")
    y = _dd_number(location, names, "Y")
    return {"x": x, "y": y, "width": width, "height": height}


def _dd_number(item, names: list[Any], key: str) -> float:
    value = c1.dd_get(item, names, key)
    if value is None or value[0] not in {c1.T_F64, c1.T_F32, c1.T_INT}:
        return 0.0
    return float(value[1])


def _widget_text(body, names: list[Any], objects: Mapping[int, Any]) -> str:
    children = c1.dd_get(body, names, "diagram-objects")
    if children is not None:
        for ref in children[1]:
            child = objects.get(ref[1])
            if child is not None and names[child[2]] == model.RICH_TEXT_PANEL_KIND:
                text = _rich_text(child[3], names)
                if text:
                    return text
    text_block = c1.dd_get(body, names, "TextBlock")
    text_value = c1.dd_get(text_block, names, "text")
    return names[text_value[1]] if text_value is not None else ""


def _rich_text(body, names: list[Any]) -> str:
    rtf = c1.dd_get(body, names, "rtf-block")
    attributed = c1.dd_get(rtf, names, "attributed-string")
    paragraphs = c1.dd_get(attributed, names, "Paragraphs")
    lines = []
    if paragraphs is None:
        return ""
    for paragraph in paragraphs[1]:
        inlines = c1.dd_get(paragraph, names, "Inlines")
        if inlines is None:
            lines.append("")
            continue
        pieces = []
        for inline in inlines[1]:
            text_value = c1.dd_get(inline, names, "Text")
            if text_value is not None:
                pieces.append(names[text_value[1]])
        lines.append("".join(pieces))
    return "\n".join(lines)


def _guid_bytes(guids: list[Any], index: int) -> bytes:
    value = guids[index]
    if isinstance(value, bytes):
        return value
    raise ValueError(f"invalid guid pool entry at index {index}")
