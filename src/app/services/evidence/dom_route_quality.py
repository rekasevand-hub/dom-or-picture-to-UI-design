from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

ROUTE_QUALITY_SCHEMA_VERSION = "dom-route-quality/1.0"
_VOLATILE_QUERY_KEYS = {
    "from",
    "ref",
    "source",
    "spm",
    "timestamp",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}
_REGION_PREFIXES = {
    "/global",
    "/us",
    "/en",
    "/en-us",
    "/cn",
    "/zh",
    "/zh-cn",
}
_SUBDOMAIN_PREFIXES = {
    "global",
    "us",
    "en",
    "en-us",
    "cn",
    "zh",
    "zh-cn",
    "support",
    "help",
}


class DOMRouteQualityError(RuntimeError):
    """Raised when strict DOM route quality checks fail."""


def _canonical_url(value: str) -> tuple[str, str, str]:
    parsed = urlparse(str(value or ""))
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in _VOLATILE_QUERY_KEYS
        )
    )
    path = parsed.path.rstrip("/") or "/"
    host = parsed.netloc.lower()
    canonical = urlunparse(
        (
            parsed.scheme.lower(),
            host,
            path,
            "",
            query,
            "",
        )
    )
    return canonical, host, path


def _suffix_host_match(left: str, right: str) -> bool:
    left_host = left.split(":", 1)[0]
    right_host = right.split(":", 1)[0]
    return (
        left_host == right_host
        or left_host.endswith("." + right_host)
        or right_host.endswith("." + left_host)
    )


def _redirect_check(requested_url: str, final_url: str) -> dict[str, Any]:
    requested, requested_host, requested_path = _canonical_url(requested_url)
    final, final_host, final_path = _canonical_url(final_url)
    if requested == final:
        return {"status": "pass", "reason": None}
    if requested_host == final_host and requested_path == final_path:
        return {"status": "pass", "reason": "same-host-same-path"}

    lower_path = final_path.lower()
    if (
        requested_path == "/"
        and any(
            lower_path == prefix or lower_path.startswith(prefix + "/")
            for prefix in _REGION_PREFIXES
        )
    ):
        return {
            "status": "fail",
            "reason": "regional-or-locale-redirect",
        }
    if requested_host != final_host and _suffix_host_match(requested_host, final_host):
        requested_labels = requested_host.split(".")
        final_labels = final_host.split(".")
        differing = set(final_labels) - set(requested_labels)
        if differing & _SUBDOMAIN_PREFIXES and requested_path != final_path:
            return {
                "status": "fail",
                "reason": "support-or-region-subdomain-redirect",
            }
    if requested_host == final_host and requested_path == "/":
        segments = [item for item in final_path.split("/") if item]
        if len(segments) == 1:
            return {
                "status": "warn",
                "reason": "single-segment-landing-redirect",
            }
    if requested_host == final_host:
        return {
            "status": "warn",
            "reason": "same-host-path-change",
        }
    return {"status": "warn", "reason": "cross-host-redirect"}


def _dom_image_references(nodes: Sequence[Mapping[str, Any]]) -> set[str]:
    urls: set[str] = set()
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        if str(node.get("tag") or "").lower() in {"img", "svg", "image"}:
            source = str(node.get("assetSrc") or "").strip()
            if source:
                urls.add(source)
        for source in node.get("bgUrls") or []:
            if str(source).strip():
                urls.add(str(source).strip())
        for layer in node.get("backgroundLayers") or []:
            if not isinstance(layer, Mapping) or str(layer.get("kind")) != "image":
                continue
            source = str(layer.get("source") or "").strip()
            if source:
                urls.add(source)
    return urls


def _descendant_indices(
    nodes: Sequence[Mapping[str, Any]],
    parent_index: int,
) -> set[int]:
    descendants: set[int] = set()
    changed = True
    while changed:
        changed = False
        for index, node in enumerate(nodes):
            if index in descendants or not isinstance(node, Mapping):
                continue
            parent = node.get("pIdx")
            if parent == parent_index or parent in descendants:
                descendants.add(index)
                changed = True
    return descendants


def evaluate_dom_route_quality(
    bundle: Mapping[str, Any],
    dom_nodes: Sequence[Mapping[str, Any]],
    graph: Mapping[str, Any],
    design: Mapping[str, Any],
    asset_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    nodes = [node for node in dom_nodes if isinstance(node, Mapping)]
    redirect = _redirect_check(
        str(bundle.get("requested_url") or ""),
        str(bundle.get("final_url") or bundle.get("requested_url") or ""),
    )
    page_state = bundle.get("page_state")
    page_state = page_state if isinstance(page_state, Mapping) else {}
    content_status = (
        "pass"
        if nodes or page_state.get("kind") == "content"
        else "warn"
    )
    content = {
        "status": content_status,
        "dom_node_count": len(nodes),
    }

    references = _dom_image_references(nodes)
    design_images = sum(
        str(item.get("type") or "").lower() in {"image", "avatar"}
        for item in (design.get("elements") or [])
        if isinstance(item, Mapping)
    )
    reference_count = len(references)
    if reference_count and design_images == 0:
        image_status = "fail"
        image_reason = "DOM images missing from DesignSpec"
    elif reference_count >= 2 and design_images < reference_count / 2:
        image_status = "warn"
        image_reason = "fewer than half of DOM images reached DesignSpec"
    else:
        image_status = "pass"
        image_reason = None
    image_coverage = {
        "status": image_status,
        "reason": image_reason,
        "references": reference_count,
        "design_images": design_images,
        "ledger_references": int(asset_ledger.get("reference_count") or 0),
    }

    capture = bundle.get("capture")
    capture = capture if isinstance(capture, Mapping) else {}
    screenshot_size = capture.get("canvas_size")
    design_canvas = design.get("canvas") if isinstance(design.get("canvas"), Mapping) else {}
    geometry_status = "pass"
    geometry_reason = None
    if (
        isinstance(screenshot_size, (list, tuple))
        and len(screenshot_size) >= 2
        and float(screenshot_size[1] or 0) > 0
        and design_canvas.get("height")
    ):
        drift = abs(float(design_canvas["height"]) - float(screenshot_size[1]))
        if drift / float(screenshot_size[1]) > 0.05:
            geometry_status = "warn"
            geometry_reason = "canvas height differs from screenshot by more than 5%"
    geometry = {
        "status": geometry_status,
        "reason": geometry_reason,
        "canvas_size": [
            design_canvas.get("width"),
            design_canvas.get("height"),
        ],
        "screenshot_size": list(screenshot_size) if screenshot_size else None,
    }

    represented_indices = {
        int(item["domIndex"])
        for source in (graph, design)
        for item in (source.get("elements") or [])
        if isinstance(item, Mapping) and isinstance(item.get("domIndex"), int)
    }
    clipped_node_count = 0
    missing_clipped_descendants = 0
    for index, node in enumerate(nodes):
        if not (
            node.get("clipToBounds")
            or str(node.get("overflowX") or "") not in {"", "visible"}
            or str(node.get("overflowY") or "") not in {"", "visible"}
        ):
            continue
        clipped_node_count += 1
        descendants = _descendant_indices(nodes, index)
        if descendants and not (descendants & represented_indices):
            missing_clipped_descendants += len(descendants)
    clipping = {
        "status": "warn" if missing_clipped_descendants else "pass",
        "reason": (
            "clipped descendants are absent from PageGraph/DesignSpec"
            if missing_clipped_descendants
            else None
        ),
        "clipped_node_count": clipped_node_count,
        "missing_descendant_count": missing_clipped_descendants,
    }

    checks = {
        "redirect": redirect,
        "content": content,
        "image_coverage": image_coverage,
        "geometry": geometry,
        "clipping": clipping,
    }
    status = (
        "fail"
        if any(check["status"] == "fail" for check in checks.values())
        else "warn"
        if any(check["status"] == "warn" for check in checks.values())
        else "pass"
    )
    warnings = [
        f"{name}: {check.get('reason')}"
        for name, check in checks.items()
        if check["status"] == "warn" and check.get("reason")
    ]
    return {
        "schema_version": ROUTE_QUALITY_SCHEMA_VERSION,
        "status": status,
        "checks": checks,
        "warnings": warnings,
    }
