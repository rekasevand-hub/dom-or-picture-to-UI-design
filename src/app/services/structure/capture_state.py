"""Deterministic state signatures shared by capture comparison tools."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from typing import Any, Sequence
from urllib.parse import urlparse


def normalize_capture_url(value: str) -> str:
    parsed = urlparse(str(value or ""))
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def text_sequence(dom: Sequence[dict[str, Any]]) -> list[str]:
    return [
        str(node.get("text") or "")
        for node in dom
        if str(node.get("text") or "").strip()
    ]


def structure_records(dom: Sequence[dict[str, Any]]) -> list[list[Any]]:
    records: list[list[Any]] = []
    for node in dom:
        records.append(
            [
                str(node.get("tag") or "").lower(),
                int(node.get("pIdx", -1)),
                str(node.get("clsAll") or ""),
                str(node.get("role") or ""),
                str(node.get("ariaLabel") or ""),
                str(node.get("title") or ""),
                str(node.get("alt") or ""),
                " ".join(str(node.get("text") or "").split()),
                str(node.get("assetSrc") or ""),
                list(node.get("bgUrls") or []),
                bool(node.get("bgImage")),
                bool(node.get("iconBox")),
                bool(node.get("interactive")),
                bool(node.get("shadow")),
            ]
        )
    return records


def structure_sha256(dom: Sequence[dict[str, Any]]) -> str:
    payload = json.dumps(
        structure_records(dom),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def capture_state_signature(
    dom: Sequence[dict[str, Any]],
    page_state: dict[str, Any],
) -> dict[str, Any]:
    texts = text_sequence(dom)
    frame_inventory = _normalized_frame_inventory(
        page_state.get("frame_inventory")
    )
    return {
        "url": normalize_capture_url(str(page_state.get("final_url") or "")),
        "text_sha256": hashlib.sha256(
            "\n".join(texts).encode("utf-8")
        ).hexdigest(),
        "text_count": len(texts),
        "node_count": len(dom),
        "structure_sha256": structure_sha256(dom),
        "frame_count": len(frame_inventory),
        "frame_inventory_sha256": _json_sha256(frame_inventory),
    }


def evaluate_state_gate(
    left_dom: Sequence[dict[str, Any]],
    left_page_state: dict[str, Any],
    right_dom: Sequence[dict[str, Any]],
    right_page_state: dict[str, Any],
    *,
    require_stability: bool = False,
) -> dict[str, Any]:
    left = capture_state_signature(left_dom, left_page_state)
    right = capture_state_signature(right_dom, right_page_state)
    reasons: list[str] = []
    if left["url"] != right["url"]:
        reasons.append("url-mismatch")
    if left["text_sha256"] != right["text_sha256"]:
        reasons.append("text-mismatch")
    if left["node_count"] != right["node_count"]:
        reasons.append("node-count-mismatch")
    if left["structure_sha256"] != right["structure_sha256"]:
        reasons.append("structure-mismatch")
    if left["frame_inventory_sha256"] != right["frame_inventory_sha256"]:
        reasons.append("frame-inventory-mismatch")
    if require_stability and (
        not _capture_is_stable(left_page_state)
        or not _capture_is_stable(right_page_state)
    ):
        reasons.append("state-unstable")
    if require_stability:
        reasons.extend(
            _frame_barrier_reasons(left_page_state, right_page_state)
        )
    return {
        "comparable": not reasons,
        "reasons": reasons,
        "left": left,
        "right": right,
    }


def state_window_is_stable(
    samples: Sequence[Any],
    *,
    poll_ms: int,
    stable_ms: int,
) -> bool:
    if len(samples) < 2 or stable_ms <= 0:
        return False
    elapsed = 0
    for index in range(len(samples) - 1, 0, -1):
        if samples[index] != samples[index - 1]:
            break
        elapsed += max(0, int(poll_ms))
        if elapsed >= stable_ms:
            return True
    return False


def _capture_is_stable(page_state: dict[str, Any]) -> bool:
    stability = page_state.get("capture_stability")
    return isinstance(stability, dict) and stability.get("stable") is True


def _frame_barrier_records(
    left_page_state: dict[str, Any],
    right_page_state: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    left_stability = left_page_state.get("capture_stability")
    right_stability = right_page_state.get("capture_stability")
    left = (
        left_stability.get("frame_barrier")
        if isinstance(left_stability, dict)
        else None
    )
    right = (
        right_stability.get("frame_barrier")
        if isinstance(right_stability, dict)
        else None
    )
    return (
        left if isinstance(left, dict) else None,
        right if isinstance(right, dict) else None,
    )


def _frame_barrier_reasons(
    left_page_state: dict[str, Any],
    right_page_state: dict[str, Any],
) -> list[str]:
    left, right = _frame_barrier_records(left_page_state, right_page_state)
    if left is None and right is None:
        return []
    if left is None or right is None:
        return ["frame-barrier-mismatch"]
    if left.get("synchronized") is not True or right.get("synchronized") is not True:
        return ["frame-barrier-mismatch"]
    if (
        left.get("frame_tree_match") is not True
        or right.get("frame_tree_match") is not True
    ):
        return ["frame-barrier-divergence"]
    return []


def classify_capture_navigation(
    requested_url: str,
    final_url: str,
    *,
    error: str | None = None,
    timed_out: bool = False,
    navigation_budget_exhausted: bool = False,
) -> dict[str, Any]:
    """Separate browser navigation failure from a comparable DOM outcome."""
    requested = str(requested_url or "")
    final = str(final_url or "")
    expected_non_blank = not _is_blank_url(requested)
    if (
        _is_blank_url(final)
        and expected_non_blank
        and navigation_budget_exhausted
    ):
        status = "browser-navigation-failed"
        reason = (
            "expected non-blank target was not reached before the navigation "
            "budget was exhausted"
        )
    elif _is_blank_url(final):
        status = "blank-document"
        reason = "blank document observed; navigation completion is not established"
    elif error and not final:
        status = "browser-navigation-failed"
        reason = "navigation ended without a document URL"
    elif _navigation_url_key(requested) != _navigation_url_key(final):
        status = "redirected"
        reason = "final document URL differs from the requested URL"
    else:
        status = "ok"
        reason = None
    return {
        "status": status,
        "reason": reason,
        "requested_url": requested,
        "final_url": final,
        "error": error,
        "timed_out": bool(timed_out),
        "expected_non_blank": expected_non_blank,
        "navigation_budget_exhausted": bool(navigation_budget_exhausted),
    }


def text_delta(
    left_dom: Sequence[dict[str, Any]],
    right_dom: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize text changes without promoting glyph-only drift to equality."""
    left = Counter(text_sequence(left_dom))
    right = Counter(text_sequence(right_dom))
    added_counter = right - left
    removed_counter = left - right
    added = [
        {"text": text, "count": count}
        for text, count in sorted(added_counter.items())
    ]
    removed = [
        {"text": text, "count": count}
        for text, count in sorted(removed_counter.items())
    ]
    changes = [item["text"] for item in (*added, *removed)]
    if not changes:
        classification = "none"
    elif all(_is_glyph_token(text) for text in changes):
        classification = "dynamic-glyph"
    else:
        classification = "text-difference"
    return {
        "classification": classification,
        "added": added,
        "removed": removed,
    }


def _normalized_frame_inventory(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    keys = (
        "visible_index",
        "depth",
        "url",
        "name",
        "src",
        "sandbox",
        "sandbox_present",
        "same_origin",
        "accessible",
        "opaque_frame",
        "opaque_reason",
        "navigation_state",
        "x",
        "y",
        "width",
        "height",
        "error",
        "state",
    )
    records: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        if item.get("rendered") is False:
            continue
        normalized = {key: item.get(key) for key in keys if key in item}
        normalized["path"] = item.get("scope_path") or item.get("path")
        records.append(normalized)
    return records


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_glyph_token(value: str) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 3:
        return False
    for character in text:
        if character.isspace():
            continue
        if unicodedata.category(character)[0] in {"L", "N"}:
            return False
    return True


def _is_blank_url(value: str) -> bool:
    normalized = str(value or "").strip().lower().replace("about://", "about:")
    return normalized in {"", "about:blank", "about:srcdoc"}


def _navigation_url_key(value: str) -> tuple[str, str, str, str, str]:
    parsed = urlparse(str(value or ""))
    return (
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/") or "/",
        parsed.query,
        parsed.fragment,
    )
