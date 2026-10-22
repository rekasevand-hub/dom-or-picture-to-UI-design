"""Bounded document-navigation evidence for frame-aware capture diagnostics."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


NAVIGATION_TIMELINE_SCHEMA = "p1-navigation-timeline/1.0"


class NavigationTimeline:
    """Record document navigation events without changing navigation behavior."""

    def __init__(
        self,
        page: Any,
        *,
        max_events: int = 128,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._page = page
        self._max_events = max(1, int(max_events))
        self._clock = clock or time.monotonic
        self._started = self._clock()
        self._events: list[dict[str, Any]] = []
        self._frames: dict[str, dict[str, Any]] = {}
        self._truncated = False
        self._dropped_event_count = 0
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_request_failed)
        page.on("framenavigated", self._on_frame_navigated)

    def _on_request(self, request: Any) -> None:
        if _resource_type(request) != "document":
            return
        self._append(
            "document-request",
            url=_safe_attr(request, "url"),
            frame_path=self._frame_path(_safe_attr(request, "frame")),
            redirected_from_url=_safe_attr(
                _safe_attr(request, "redirected_from"),
                "url",
            ),
        )

    def _on_response(self, response: Any) -> None:
        request = _safe_attr(response, "request")
        if _resource_type(request) != "document":
            return
        self._append(
            "document-response",
            url=_safe_attr(response, "url") or _safe_attr(request, "url"),
            frame_path=self._frame_path(_safe_attr(request, "frame")),
            status=_safe_int(_safe_attr(response, "status")),
            redirected_from_url=_safe_attr(
                _safe_attr(request, "redirected_from"),
                "url",
            ),
        )

    def _on_request_failed(self, request: Any) -> None:
        if _resource_type(request) != "document":
            return
        self._append(
            "document-request-failed",
            url=_safe_attr(request, "url"),
            frame_path=self._frame_path(_safe_attr(request, "frame")),
            failure=_safe_text(_safe_attr(request, "failure")),
        )

    def _on_frame_navigated(self, frame: Any) -> None:
        frame_path = self._frame_path(frame)
        if frame_path is None:
            return
        current = self._frames.setdefault(
            frame_path,
            {
                "document_generation": -1,
                "commit_count": 0,
                "last_url": "",
                "navigation_phase": "committed",
            },
        )
        current["document_generation"] = int(current["document_generation"]) + 1
        current["commit_count"] = int(current["commit_count"]) + 1
        current["last_url"] = _safe_attr(frame, "url")
        self._append(
            "document-commit",
            url=current["last_url"],
            frame_path=frame_path,
            document_generation=current["document_generation"],
            navigation_phase="committed",
        )

    def _append(self, kind: str, **fields: Any) -> None:
        if len(self._events) >= self._max_events:
            self._truncated = True
            self._dropped_event_count += 1
            return
        self._events.append({
            "sequence": len(self._events),
            "elapsed_ms": max(0, round((self._clock() - self._started) * 1000)),
            "kind": kind,
            **fields,
        })

    def _frame_path(self, frame: Any) -> str | None:
        if frame is None:
            return None
        try:
            if frame == self._page.main_frame:
                return "root"
            indices: list[str] = []
            current = frame
            while current is not None and current != self._page.main_frame:
                parent = _safe_attr(current, "parent_frame")
                if parent is None:
                    return None
                index = _child_index(parent, current)
                if index is None:
                    return None
                indices.append(str(index))
                current = parent
            if current != self._page.main_frame:
                return None
            return "root/" + "/".join(reversed(indices))
        except Exception:
            return None

    def enrich_frame_inventory(
        self,
        inventory: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        records = [
            dict(item) for item in (inventory or []) if isinstance(item, dict)
        ]
        frames = self._frames
        for item in records:
            path = str(item.get("path") or "")
            observed = frames.get(path) or {}
            item["document_generation"] = observed.get("document_generation")
            item["document_commit_count"] = observed.get("commit_count")
            item["navigation_phase"] = _navigation_phase(item, observed)
        return records

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": NAVIGATION_TIMELINE_SCHEMA,
            "max_events": self._max_events,
            "event_count": len(self._events),
            "truncated": self._truncated,
            "dropped_event_count": self._dropped_event_count,
            "events": [dict(item) for item in self._events],
            "frames": {
                path: dict(value)
                for path, value in sorted(self._frames.items())
            },
        }


def _navigation_phase(
    item: dict[str, Any],
    observed: dict[str, Any],
) -> str:
    navigation_state = str(item.get("navigation_state") or "")
    if item.get("opaque_frame") is True:
        return "opaque-boundary"
    if navigation_state == "blank-document":
        return "blank"
    if navigation_state in {"browser-navigation-failed", "inaccessible"}:
        return "failed"
    if observed.get("navigation_phase") == "committed":
        return "committed"
    if navigation_state == "loaded":
        return "committed"
    return "unknown"


def _resource_type(request: Any) -> str:
    return str(_safe_attr(request, "resource_type") or "").lower()


def _child_index(parent: Any, child: Any) -> int | None:
    children = list(_safe_attr(parent, "child_frames") or [])
    for index, candidate in enumerate(children):
        if candidate is child or candidate == child:
            return index
    return None


def _safe_attr(value: Any, name: str) -> Any:
    if value is None:
        return None
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def _safe_text(value: Any) -> str:
    return str(value or "")


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
