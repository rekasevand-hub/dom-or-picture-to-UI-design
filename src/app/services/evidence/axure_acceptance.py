"""Independent acceptance for Axure RP 8 published HTML artifacts."""

from __future__ import annotations

import hashlib
import html
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.app.services.evidence.image_figma_acceptance import (
    visual_similarity_metrics,
)
from src.app.services.rendering.axure import doc

AXURE_ACCEPTANCE_SCHEMA_VERSION = "axure-published-acceptance/1.0"
DEFAULT_AXURE_POLICY = {
    "policy_id": "axure-dom-current-scope/1.0",
    "visual_within30_min_pct": 90.0,
    "require_size_match": True,
    "critical_region_ink_threshold": 200,
    "critical_region_min_reference_ink_pct": 0.5,
    "critical_region_min_render_to_reference_ink_ratio": 0.25,
}


def evaluate_published_axure(
    publish_dir: str | Path,
    *,
    design: Mapping[str, Any],
    rp_report: Mapping[str, Any] | None = None,
    critical_texts: Sequence[str] = (),
    expected_asset_count: int | None = None,
    reference_screenshot: str | Path | None = None,
    render_screenshot: str | Path | None = None,
    critical_regions: Sequence[Mapping[str, Any]] = (),
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate Axure-published pages, content, labels and image bytes."""
    root = Path(publish_dir)
    resolved_policy = {**DEFAULT_AXURE_POLICY, **(policy or {})}
    failures: list[dict[str, Any]] = []
    provenance = _asset_provenance(design)
    for row in provenance["promoted_display_originals"]:
        failures.append(
            {
                "kind": "asset-provenance",
                "source_node_id": row["source_node_id"],
                "display": row["display"],
            }
        )
    pages = _root_pages(root)
    source_pages = _source_pages(design)
    expected_names = [str(page.get("name") or "") for page in source_pages]
    actual_names = [page["name"] for page in pages]
    if actual_names != expected_names:
        failures.append(
            {
                "kind": "page-order",
                "expected": expected_names,
                "actual": actual_names,
            }
        )

    registry = {
        str(page.get("name") or ""): str(page.get("package_guid") or "").replace(
            "-", ""
        )
        for page in (rp_report or {}).get("pages") or []
    }
    page_results = []
    label_count = 0
    expected_assets: set[str] = set()
    actual_assets: set[str] = set()
    package_matches = 0
    package_checks = 0
    for frame_index, source_page in enumerate(source_pages):
        page_name = str(source_page.get("name") or "")
        if frame_index >= len(pages):
            failures.append({"kind": "page-missing", "page": page_name})
            page_results.append({"name": page_name, "present": False})
            continue
        page = pages[frame_index]
        page_url = page["url"]
        page_dir = Path(page_url).stem
        html_path = root / page_url
        data_path = root / "files" / page_dir / "data.js"
        css_path = root / "files" / page_dir / "styles.css"
        if not html_path.is_file():
            failures.append(
                {"kind": "page-missing", "page": page_name, "url": page_url}
            )
            page_results.append({"name": page_name, "url": page_url, "present": False})
            continue
        page_html = html_path.read_text(encoding="utf-8")
        labels = [
            html.unescape(label)
            for label in re.findall(r'data-label="([^"]*)"', page_html)
        ]
        label_count += len(labels)
        expected_labels = Counter(
            label
            for element in source_page.get("elements") or []
            if isinstance(element, Mapping)
            if (label := _label(element))
        )
        expected_labels.update({"Background": 1})
        missing_labels = expected_labels - Counter(labels)
        for label, count in sorted(missing_labels.items()):
            failures.append(
                {
                    "kind": "label-missing",
                    "page": page_name,
                    "label": label,
                    "count": count,
                }
            )

        data_js = data_path.read_text(encoding="utf-8") if data_path.is_file() else ""
        css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""
        canvas = (
            source_page.get("canvas")
            if isinstance(source_page.get("canvas"), Mapping)
            else {}
        )
        expected_width = str(int(float(canvas.get("width") or 0)))
        expected_height = str(int(float(canvas.get("height") or 0)))
        actual_width = _js_literal(data_js, "width")
        actual_height = _js_literal(data_js, "height")
        body_width = _css_body_width(css)
        if actual_width != expected_width or actual_height != expected_height:
            failures.append(
                {
                    "kind": "canvas-size",
                    "page": page_name,
                    "expected": [expected_width, expected_height],
                    "actual": [actual_width, actual_height],
                }
            )
        if body_width != expected_width:
            failures.append(
                {
                    "kind": "canvas-body-width",
                    "page": page_name,
                    "expected": expected_width,
                    "actual": body_width,
                }
            )
        published_name = _js_literal(data_js, "name")
        if published_name != page_name:
            failures.append(
                {
                    "kind": "page-name",
                    "page": page_name,
                    "actual": published_name,
                }
            )
        package_id = _js_literal(data_js, "packageId")
        expected_package = registry.get(page_name)
        if expected_package:
            package_checks += 1
            if package_id == expected_package:
                package_matches += 1
            else:
                failures.append(
                    {
                        "kind": "package-id",
                        "page": page_name,
                        "expected": expected_package,
                        "actual": package_id,
                    }
                )
        page_expected_assets = {
            hashlib.sha256(doc.image_bytes(element.get("imageBase64"))).hexdigest()
            for element in source_page.get("elements") or []
            if isinstance(element, Mapping) and element.get("imageBase64")
        }
        page_actual_assets = {
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / "images" / page_dir).rglob("*"))
            if path.is_file()
        }
        expected_assets.update(page_expected_assets)
        actual_assets.update(page_actual_assets)
        for digest in sorted(page_expected_assets - page_actual_assets):
            failures.append(
                {
                    "kind": "asset-missing",
                    "page": page_name,
                    "sha256": digest,
                }
            )
        page_results.append(
            {
                "name": page_name,
                "url": page_url,
                "present": True,
                "labels": len(labels),
                "missing_labels": sum(missing_labels.values()),
                "canvas": {
                    "expected": [int(expected_width), int(expected_height)],
                    "actual": [
                        _int_or_none(actual_width),
                        _int_or_none(actual_height),
                    ],
                },
                "package_id": package_id,
                "expected_asset_count": len(page_expected_assets),
                "published_asset_count": len(page_actual_assets),
            }
        )

    normalized_html = "\n".join(
        _normalize_critical_text(
            _html_text((root / page["url"]).read_text(encoding="utf-8"))
        )
        for page in pages
        if (root / page["url"]).is_file()
    )
    critical_rows = [
        {
            "text": str(text),
            "present": _normalize_critical_text(text) in normalized_html,
        }
        for text in critical_texts
        if str(text).strip()
    ]
    for row in critical_rows:
        if not row["present"]:
            failures.append(
                {
                    "kind": "critical-text-missing",
                    "text": row["text"],
                }
            )
    if expected_asset_count is not None and len(actual_assets) != expected_asset_count:
        failures.append(
            {
                "kind": "asset-count",
                "expected": expected_asset_count,
                "actual": len(actual_assets),
            }
        )

    visual = _visual(
        reference_screenshot,
        render_screenshot,
        resolved_policy,
    )
    critical_region_result = _critical_regions(
        reference_screenshot,
        render_screenshot,
        critical_regions,
        resolved_policy,
    )
    for row in critical_region_result["rows"]:
        if row["passed"]:
            continue
        failures.append(
            {
                "kind": "critical-region-missing",
                "region": row["name"],
                "reason": row["reason"],
                "reference_ink_pct": row["reference_ink_pct"],
                "render_ink_pct": row["render_ink_pct"],
                "render_to_reference_ratio": row["render_to_reference_ratio"],
            }
        )
    if visual["status"] == "measured" and (
        visual.get("within30_pct", 0.0)
        < float(resolved_policy["visual_within30_min_pct"])
        or (
            resolved_policy.get("require_size_match", True)
            and not visual.get("size_match", False)
        )
    ):
        failures.append(
            {
                "kind": "visual-quality",
                "within30_pct": visual.get("within30_pct"),
                "minimum": resolved_policy["visual_within30_min_pct"],
                "size_match": visual.get("size_match"),
            }
        )

    return {
        "schema_version": AXURE_ACCEPTANCE_SCHEMA_VERSION,
        "status": "pass" if not failures else "fail",
        "acceptance_scope": "axure-specific-required",
        "publish_dir": str(root.resolve()),
        "policy": dict(resolved_policy),
        "page_count": len(pages),
        "label_count": label_count,
        "pages": page_results,
        "critical_text": {
            "passed": sum(row["present"] for row in critical_rows),
            "total": len(critical_rows),
            "rows": critical_rows,
        },
        "assets": {
            "expected_declared": expected_asset_count,
            "expected_unique": len(expected_assets),
            "published_unique": len(actual_assets),
            "matched_unique": len(expected_assets & actual_assets),
            "unexpected_hashes": sorted(actual_assets - expected_assets),
        },
        "provenance": provenance,
        "packages": {
            "matched": package_matches,
            "checked": package_checks,
        },
        "visual": visual,
        "critical_regions": critical_region_result,
        "failures": failures,
        "claims": {
            "axure_publish_success": root.is_dir() and bool(pages),
            "axure_visual_acceptance": visual["status"] == "measured"
            and not any(
                row["kind"] in {"visual-quality", "critical-region-missing"}
                for row in failures
            ),
            "figma_evidence_transferable": False,
            "runtime_image_replacement": False,
            "auto_layout": False,
            "native_letter_spacing": False,
            "original_asset_identity": False,
        },
        "limitations": [
            "Artifact checks are scoped to the named published Axure run.",
            "Runtime image replacement is not provided by the Axure RP 8 adapter.",
            "Auto Layout and native letter spacing remain unsupported.",
            "Figma acceptance evidence is not transferable.",
        ],
    }


def _root_pages(root: Path) -> list[dict[str, str]]:
    document = (root / "data" / "document.js").read_text(encoding="utf-8")
    marker = document.find('"rootNodes"')
    if marker < 0:
        return []
    tail = document[marker:]
    stop = tail.find('"globalVariables"')
    if stop >= 0:
        tail = tail[:stop]
    values = [token[1:-1] for token in re.findall(r'"[^"]*"', tail)]
    pages = []
    for index, value in enumerate(values):
        if index == 0 or not value.endswith(".html") or index == 0:
            continue
        previous = values[index - 1]
        if previous == "url":
            try:
                name = values[values.index("pageName") + 1]
            except (ValueError, IndexError):
                name = value
        else:
            name = previous
        pages.append({"name": name, "url": value})
    return pages


def _source_pages(design: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    pages = design.get("pages")
    if isinstance(pages, list) and pages:
        return [page for page in pages if isinstance(page, Mapping)]
    return [design]


def _label(element: Mapping[str, Any]) -> str:
    return " ".join(str(element.get("name") or element.get("label") or "").split())


def _asset_provenance(design: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for page in _source_pages(design):
        for element in page.get("elements") or []:
            if not isinstance(element, Mapping):
                continue
            is_image_kind = str(element.get("type") or "").lower() in {
                "image",
                "avatar",
            }
            if not is_image_kind and not element.get("imageBase64"):
                continue
            resolution = element.get("sourceResolution")
            resolution = resolution if isinstance(resolution, Mapping) else {}
            identity = resolution.get("identity")
            identity = identity if isinstance(identity, Mapping) else {}
            display = resolution.get("display")
            display = display if isinstance(display, Mapping) else {}
            display_payload = element.get("displayPayload")
            display_payload = (
                display_payload if isinstance(display_payload, Mapping) else {}
            )
            reference_only = bool(
                display.get("reference_only") or display_payload.get("reference_only")
            )
            generated = bool(
                display.get("generated") or display_payload.get("generated")
            )
            display_original = bool(
                display.get("original") or display_payload.get("original")
            )
            row = {
                "source_node_id": str(element.get("id") or ""),
                "use_id": str(resolution.get("use_id") or ""),
                "display": str(
                    display.get("selected") or display_payload.get("kind") or "missing"
                ),
                "original": bool(identity.get("original")),
                "display_original": display_original,
                "reference_only": reference_only,
                "generated": generated,
            }
            rows.append(row)
    promoted = [
        row
        for row in rows
        if (row["reference_only"] or row["generated"]) and row["display_original"]
    ]
    return {
        "uses": len(rows),
        "original": sum(row["original"] for row in rows),
        "display_original": sum(row["display_original"] for row in rows),
        "reference_only": sum(row["reference_only"] for row in rows),
        "generated": sum(row["generated"] for row in rows),
        "promoted_display_originals": promoted,
        "rows": rows,
    }


def _js_literal(text: str, key: str) -> str | None:
    pattern = (
        r'"%s",[A-Za-z_$][\w$]*\s*=\s*'
        r'(?:"([^"]*)"|(-?(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?)))' % re.escape(key)
    )
    match = re.search(pattern, text)
    if not match:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def _css_body_width(css: str) -> str | None:
    body = re.search(r"body\s*\{([^}]*)\}", css)
    if not body:
        return None
    width = re.search(r"width\s*:\s*(\d+(?:\.\d+)?)px", body.group(1))
    return str(int(float(width.group(1)))) if width else None


def _html_text(value: str) -> str:
    without_scripts = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return html.unescape(re.sub(r"<[^>]+>", " ", without_scripts))


def _normalize_text(value: Any) -> str:
    return "".join(str(value or "").split())


def _normalize_critical_text(value: Any) -> str:
    text = str(value or "").casefold().replace("_", " ")
    text = re.sub(r"[^\w\s\u4e00-\u9fff]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _visual(
    reference: str | Path | None,
    render: str | Path | None,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    if reference is None or render is None:
        return {
            "status": "not-evaluated",
            "reason": "screenshot-required-for-visual-score",
            "within30_pct": None,
            "size_match": None,
            "policy_minimum": policy["visual_within30_min_pct"],
        }
    metrics = visual_similarity_metrics(reference, render)
    metrics["policy_minimum"] = policy["visual_within30_min_pct"]
    return metrics


def _critical_regions(
    reference: str | Path | None,
    render: str | Path | None,
    regions: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_regions = [
        dict(region) for region in regions if isinstance(region, Mapping)
    ]
    if not normalized_regions:
        return {"status": "not-evaluated", "reason": "no-critical-regions", "rows": []}
    if reference is None or render is None:
        return {
            "status": "fail",
            "reason": "screenshot-pair-required",
            "rows": [
                _critical_region_failure(
                    region,
                    reason="screenshot-pair-required",
                )
                for region in normalized_regions
            ],
        }

    import cv2

    reference_image = cv2.imread(str(reference), cv2.IMREAD_GRAYSCALE)
    render_image = cv2.imread(str(render), cv2.IMREAD_GRAYSCALE)
    if reference_image is None or render_image is None:
        return {
            "status": "fail",
            "reason": "image-unreadable",
            "rows": [
                _critical_region_failure(region, reason="image-unreadable")
                for region in normalized_regions
            ],
        }
    if reference_image.shape != render_image.shape:
        render_image = cv2.resize(
            render_image,
            (reference_image.shape[1], reference_image.shape[0]),
        )

    threshold = int(policy["critical_region_ink_threshold"])
    min_reference_pct = float(policy["critical_region_min_reference_ink_pct"])
    min_ratio = float(policy["critical_region_min_render_to_reference_ink_ratio"])
    rows = []
    height, width = reference_image.shape
    for region in normalized_regions:
        try:
            x = max(0, int(round(float(region.get("x")))))
            y = max(0, int(round(float(region.get("y")))))
            region_width = max(0, int(round(float(region.get("width")))))
            region_height = max(0, int(round(float(region.get("height")))))
        except (TypeError, ValueError):
            x = y = region_width = region_height = 0
        x2 = min(width, x + region_width)
        y2 = min(height, y + region_height)
        if x2 <= x or y2 <= y:
            rows.append(
                _critical_region_failure(region, reason="invalid-region-geometry")
            )
            continue
        reference_crop = reference_image[y:y2, x:x2]
        render_crop = render_image[y:y2, x:x2]
        reference_ink = float((reference_crop < threshold).mean() * 100)
        render_ink = float((render_crop < threshold).mean() * 100)
        ratio = render_ink / reference_ink if reference_ink > 0 else 0.0
        required_reference = float(
            region.get("min_reference_ink_pct", min_reference_pct)
        )
        required_ratio = float(
            region.get(
                "min_render_to_reference_ink_ratio",
                min_ratio,
            )
        )
        if reference_ink < required_reference:
            reason = "reference-region-empty"
            passed = False
        elif ratio < required_ratio:
            reason = "render-region-ink-below-threshold"
            passed = False
        else:
            reason = None
            passed = True
        rows.append(
            {
                "name": str(region.get("name") or ""),
                "geometry": {
                    "x": x,
                    "y": y,
                    "width": region_width,
                    "height": region_height,
                },
                "reference_ink_pct": reference_ink,
                "render_ink_pct": render_ink,
                "render_to_reference_ratio": ratio,
                "minimum_reference_ink_pct": required_reference,
                "minimum_render_to_reference_ratio": required_ratio,
                "reason": reason,
                "passed": passed,
            }
        )
    return {
        "status": "pass" if all(row["passed"] for row in rows) else "fail",
        "reason": None,
        "ink_threshold": threshold,
        "rows": rows,
    }


def _critical_region_failure(
    region: Mapping[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "name": str(region.get("name") or ""),
        "geometry": {
            "x": region.get("x"),
            "y": region.get("y"),
            "width": region.get("width"),
            "height": region.get("height"),
        },
        "reference_ink_pct": None,
        "render_ink_pct": None,
        "render_to_reference_ratio": None,
        "minimum_reference_ink_pct": None,
        "minimum_render_to_reference_ratio": None,
        "reason": reason,
        "passed": False,
    }
