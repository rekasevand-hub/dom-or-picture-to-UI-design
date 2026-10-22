"""Recursive frame inventory and same-origin child-document capture."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


DEFAULT_MAX_FRAMES = 64
DEFAULT_MAX_FRAME_DEPTH = 8

FRAME_ACCESS_JS = r"""
() => {
  let sameOrigin = false;
  let accessError = null;
  try {
    // about:srcdoc reports origin "null" even when sandbox allows same-origin.
    // Parent document access is the security boundary that matters for capture.
    sameOrigin = Boolean(window.parent && window.parent.document);
  } catch (error) {
    accessError = String(error);
  }
  return {
    url: String(location.href || ''),
    title: String(document.title || ''),
    sameOrigin,
    accessError,
  };
}
"""

FRAME_HOST_JS = r"""
(el) => {
  const rect = el.getBoundingClientRect();
  return {
    tag: String(el.tagName || '').toLowerCase(),
    id: el.id || '',
    src: el.getAttribute('src'),
    sandbox: el.getAttribute('sandbox'),
    title: el.getAttribute('title') || '',
    name: el.getAttribute('name') || '',
    x: Math.round(rect.x),
    y: Math.round(rect.y),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
    borderTopWidth: Number.parseFloat(getComputedStyle(el).borderTopWidth) || 0,
    borderLeftWidth: Number.parseFloat(getComputedStyle(el).borderLeftWidth) || 0,
    display: String(getComputedStyle(el).display || ''),
    visibility: String(getComputedStyle(el).visibility || ''),
    opacity: Number.parseFloat(getComputedStyle(el).opacity),
  };
}
"""


@dataclass
class FrameDomSnapshot:
    nodes: list[dict[str, Any]]
    inventory: list[dict[str, Any]]
    errors: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    font_resolution: dict[str, Any] = field(default_factory=dict)


def summarize_frame_inventory(
    inventory: Sequence[dict[str, Any]] | None,
) -> dict[str, Any]:
    records = [item for item in (inventory or []) if isinstance(item, dict)]
    return {
        "frame_count": len(records),
        "rendered_frame_count": sum(bool(item.get("rendered")) for item in records),
        "unrendered_frame_count": sum(not bool(item.get("rendered")) for item in records),
        "accessible_frame_count": sum(bool(item.get("accessible")) for item in records),
        "opaque_frame_count": sum(bool(item.get("opaque_frame")) for item in records),
        "same_origin_count": sum(item.get("same_origin") is True for item in records),
        "cross_origin_count": sum(
            item.get("opaque_reason") == "cross-origin" for item in records
        ),
        "sandboxed_frame_count": sum(
            bool(item.get("sandbox_present")) for item in records
        ),
        "sandboxed_opaque_count": sum(
            item.get("opaque_reason") == "sandboxed-opaque-origin" for item in records
        ),
        "navigation_failed_count": sum(
            item.get("navigation_state") == "browser-navigation-failed"
            for item in records
        ),
        "blank_document_count": sum(
            item.get("navigation_state") == "blank-document"
            for item in records
        ),
        "max_depth": max((int(item.get("depth") or 0) for item in records), default=0),
    }


def capture_frame_state(
    page: Any,
    state_script: str,
    *,
    include_unrendered: bool = True,
    max_frames: int = DEFAULT_MAX_FRAMES,
    max_depth: int = DEFAULT_MAX_FRAME_DEPTH,
) -> list[dict[str, Any]]:
    """Return stable frame metadata plus state probes for accessible frames."""
    inventory: list[dict[str, Any]] = []

    def walk(
        parent: Any,
        parent_path: str,
        parent_scope_path: str,
        depth: int,
        parent_accessible: bool,
    ) -> None:
        if depth > max_depth:
            return
        pending: list[tuple[Any, str, str, int, bool]] = []
        visible_index = 0
        for index, child in enumerate(_child_frames(parent)):
            if len(inventory) >= max_frames:
                return
            path = f"{parent_path}/{index}"
            record = _frame_record(child, path, depth, parent_accessible)
            if record["rendered"]:
                record["visible_index"] = visible_index
                record["scope_path"] = f"{parent_scope_path}/v{visible_index}"
                visible_index += 1
            else:
                record["visible_index"] = None
                record["scope_path"] = None
            if record["accessible"]:
                try:
                    state = child.evaluate(state_script)
                    record["state"] = state
                except Exception as exc:  # noqa: BLE001 - navigation can detach a frame
                    record["accessible"] = False
                    record["opaque_frame"] = True
                    record["opaque_reason"] = "inaccessible-frame"
                    record["error"] = f"{type(exc).__name__}: {exc}"
            if include_unrendered or record["rendered"]:
                inventory.append(record)
            if record["rendered"] and record["accessible"]:
                pending.append((
                    child,
                    path,
                    str(record["scope_path"]),
                    depth + 1,
                    True,
                ))
        for child, path, scope_path, child_depth, accessible in pending:
            walk(child, path, scope_path, child_depth, accessible)

    walk(page.main_frame, "root", "root", 1, True)
    return inventory


def collect_frame_dom(
    page: Any,
    dom_script: str,
    *,
    max_frames: int = DEFAULT_MAX_FRAMES,
    max_depth: int = DEFAULT_MAX_FRAME_DEPTH,
    font_probe: Any | None = None,
) -> FrameDomSnapshot:
    """Merge visible DOM from recursively accessible same-origin frames."""
    font_frames: list[dict[str, Any]] = []
    font_errors: list[dict[str, Any]] = []

    def evaluate_nodes(frame: Any, path: str) -> list[dict[str, Any]]:
        prefix = f"p1font-{path.replace('/', '_')}"
        raw = (
            frame.evaluate(dom_script, prefix)
            if font_probe is not None
            else frame.evaluate(dom_script)
        )
        if not isinstance(raw, list):
            raise ValueError("DOM probe must return a list")
        nodes = [dict(item) for item in raw if isinstance(item, dict)]
        if font_probe is not None:
            try:
                result = font_probe(frame, prefix, nodes)
                if isinstance(result, dict):
                    font_frames.append({"path": path, **result})
                else:
                    font_errors.append({
                        "path": path,
                        "error": "font probe returned no summary",
                    })
            except Exception as exc:  # noqa: BLE001 - preserve DOM capture
                font_errors.append({
                    "path": path,
                    "error": f"{type(exc).__name__}: {exc}",
                })
        return nodes

    main_nodes = evaluate_nodes(page.main_frame, "root")
    if not isinstance(main_nodes, list):
        raise ValueError("DOM probe must return a list")
    merged: list[dict[str, Any]] = [
        dict(item) for item in main_nodes if isinstance(item, dict)
    ]
    inventory: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    truncated = False

    def walk(
        parent: Any,
        frame_nodes: list[dict[str, Any]],
        frame_base: int,
        parent_path: str,
        parent_scope_path: str,
        depth: int,
        parent_accessible: bool,
    ) -> None:
        nonlocal truncated
        if depth > max_depth:
            truncated = True
            return
        children = _child_frames(parent)
        host_local_indices = [
            offset
            for offset, item in enumerate(frame_nodes)
            if str(item.get("tag") or "").lower() in {"iframe", "frame"}
        ]
        pending: list[
            tuple[Any, list[dict[str, Any]], int, str, str, int, bool]
        ] = []
        visible_index = 0
        host_cursor = 0
        for index, child in enumerate(children):
            if len(inventory) >= max_frames:
                truncated = True
                return
            path = f"{parent_path}/{index}"
            record = _frame_record(child, path, depth, parent_accessible)
            if record["rendered"]:
                record["visible_index"] = visible_index
                record["scope_path"] = f"{parent_scope_path}/v{visible_index}"
                visible_index += 1
            else:
                record["visible_index"] = None
                record["scope_path"] = None
            inventory.append(record)
            host_index = None
            host_local_index = None
            if record["rendered"] and host_cursor < len(host_local_indices):
                host_local_index = host_local_indices[host_cursor]
                host_index = frame_base + host_local_index
                host_cursor += 1
            if host_index is not None:
                record["host_node_index"] = host_index
                merged[host_index]["frameChildPath"] = path
                if record.get("src"):
                    merged[host_index]["frameSrc"] = record["src"]
                if record.get("sandbox_present"):
                    merged[host_index]["frameSandbox"] = record["sandbox"]
            if not record["accessible"] or not record["rendered"]:
                continue
            try:
                child_nodes = evaluate_nodes(child, path)
            except Exception as exc:  # noqa: BLE001 - frame can navigate during capture
                error = f"{type(exc).__name__}: {exc}"
                record["accessible"] = False
                record["opaque_frame"] = True
                record["opaque_reason"] = "inaccessible-frame"
                record["error"] = error
                errors.append({"path": path, "error": error})
                continue
            child_base = len(merged)
            host = (
                frame_nodes[host_local_index]
                if host_local_index is not None
                else {}
            )
            # Frame document viewport coordinates start at the iframe content
            # box, not at the host border box.  The default iframe border is
            # 2px, so omitting these offsets shifts every child node left/up.
            offset_x = float(host.get("x") or 0) + float(
                host.get("borderLeftWidth") or 0
                or str(host.get("borderWidth") or "0").split()[0].replace("px", "")
                or 0
            )
            offset_y = float(host.get("y") or 0) + float(
                host.get("borderTopWidth") or 0
                or str(host.get("borderWidth") or "0").split()[0].replace("px", "")
                or 0
            )
            adjusted: list[dict[str, Any]] = []
            for child_index, node in enumerate(child_nodes):
                adjusted_node = dict(node)
                adjusted_node["framePath"] = path
                adjusted_node["frameDepth"] = depth
                adjusted_node["x"] = round(float(node.get("x") or 0) + offset_x, 2)
                adjusted_node["y"] = round(float(node.get("y") or 0) + offset_y, 2)
                parent_index = node.get("pIdx")
                if child_index == 0:
                    if host_index is not None:
                        adjusted_node["pIdx"] = host_index
                    else:
                        adjusted_node.pop("pIdx", None)
                elif isinstance(parent_index, int) and parent_index >= 0:
                    adjusted_node["pIdx"] = child_base + parent_index
                adjusted.append(adjusted_node)
            merged.extend(adjusted)
            if record["rendered"]:
                pending.append((
                    child,
                    adjusted,
                    child_base,
                    path,
                    str(record["scope_path"]),
                    depth + 1,
                    True,
                ))
        for (
            child,
            child_nodes,
            child_base,
            path,
            scope_path,
            child_depth,
            accessible,
        ) in pending:
            walk(
                child,
                child_nodes,
                child_base,
                path,
                scope_path,
                child_depth,
                accessible,
            )

    walk(page.main_frame, merged, 0, "root", "root", 1, True)
    font_resolution = _summarize_font_resolution(font_frames, font_errors)
    return FrameDomSnapshot(
        nodes=merged,
        inventory=inventory,
        errors=errors,
        truncated=truncated,
        font_resolution=font_resolution,
    )


def _summarize_font_resolution(
    frames: Sequence[dict[str, Any]],
    errors: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    totals = {
        key: sum(int(item.get(key) or 0) for item in frames)
        for key in (
            "generic_node_count",
            "resolved_count",
            "ambiguous_count",
            "missing_count",
        )
    }
    nested_errors = list(errors)
    for frame in frames:
        for error in frame.get("errors") or []:
            nested_errors.append({
                "path": frame.get("path"),
                "error": str(error),
            })
    if nested_errors or totals["ambiguous_count"] or totals["missing_count"]:
        status = "partial"
    elif totals["generic_node_count"]:
        status = "pass"
    else:
        status = "not-required"
    return {
        "status": status,
        **totals,
        "frames": list(frames),
        "errors": nested_errors,
    }


def _child_frames(frame: Any) -> list[Any]:
    try:
        return list(frame.child_frames)
    except Exception:
        return []


def _frame_record(
    frame: Any,
    path: str,
    depth: int,
    parent_accessible: bool,
) -> dict[str, Any]:
    host = _frame_host(frame)
    access = _frame_access(frame)
    sandbox_raw = host.get("sandbox")
    sandbox_present = sandbox_raw is not None
    sandbox = str(sandbox_raw or "")
    sandbox_tokens = sandbox.split()
    same_origin = access.get("sameOrigin")
    access_error = access.get("accessError")
    error = None
    if not parent_accessible:
        opaque_reason = "parent-opaque"
    elif sandbox_present and "allow-same-origin" not in sandbox_tokens:
        opaque_reason = "sandboxed-opaque-origin"
    elif same_origin is False:
        opaque_reason = "cross-origin"
    elif same_origin is not True:
        opaque_reason = "inaccessible-frame"
    else:
        opaque_reason = None
    if access_error and opaque_reason == "inaccessible-frame":
        error = str(access_error)
    frame_url = str(access.get("url") or _safe_url(frame) or "")
    source = str(host.get("src") or "")
    navigation_state = "loaded"
    if _is_blank_url(frame_url) and source and not _is_blank_url(source):
        navigation_state = "blank-document"
    elif error:
        navigation_state = "inaccessible"
    display = str(host.get("display") or "")
    visibility = str(host.get("visibility") or "")
    try:
        opacity = float(host.get("opacity"))
    except (TypeError, ValueError):
        opacity = 1.0
    rendered = (
        _as_int(host.get("width")) >= 2
        and _as_int(host.get("height")) >= 2
        and display not in {"none", "contents"}
        and visibility not in {"hidden", "collapse"}
        and opacity > 0
    )
    return {
        "path": path,
        "depth": depth,
        "url": frame_url,
        "name": _safe_name(frame),
        "title": str(access.get("title") or host.get("title") or ""),
        "src": source,
        "sandbox": sandbox,
        "sandbox_present": sandbox_present,
        "sandbox_tokens": sandbox_tokens,
        "same_origin": same_origin if isinstance(same_origin, bool) else None,
        "accessible": opaque_reason is None,
        "opaque_frame": opaque_reason is not None,
        "opaque_reason": opaque_reason,
        "navigation_state": navigation_state,
        "x": _as_int(host.get("x")),
        "y": _as_int(host.get("y")),
        "width": _as_int(host.get("width")),
        "height": _as_int(host.get("height")),
        "rendered": rendered,
        "display": display,
        "visibility": visibility,
        "opacity": opacity,
        "error": error,
    }


def _frame_host(frame: Any) -> dict[str, Any]:
    handle = None
    try:
        handle = frame.frame_element()
        value = handle.evaluate(FRAME_HOST_JS)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}
    finally:
        if handle is not None:
            try:
                handle.dispose()
            except Exception:
                pass


def _frame_access(frame: Any) -> dict[str, Any]:
    try:
        value = frame.evaluate(FRAME_ACCESS_JS)
        if isinstance(value, dict):
            return value
    except Exception as exc:  # noqa: BLE001 - frame may be detached
        return {
            "url": _safe_url(frame),
            "sameOrigin": None,
            "accessError": f"{type(exc).__name__}: {exc}",
        }
    return {
        "url": _safe_url(frame),
        "sameOrigin": None,
        "accessError": "invalid frame access probe result",
    }


def _safe_url(frame: Any) -> str:
    try:
        return str(frame.url or "")
    except Exception:
        return ""


def _safe_name(frame: Any) -> str:
    try:
        return str(frame.name or "")
    except Exception:
        return ""


def _is_blank_url(value: str) -> bool:
    normalized = str(value or "").strip().lower().replace("about://", "about:")
    return normalized in {"", "about:blank", "about:srcdoc"}


def _as_int(value: Any) -> int:
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return 0
