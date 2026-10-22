"""Limited paired-capture barrier for rendered frame-tree sampling."""
from __future__ import annotations

import threading
import time
from typing import Any, Sequence


FRAME_BARRIER_SCHEMA = "p1-frame-barrier/1.0"
GEOMETRY_TOLERANCE_PX = 2


def frame_tree_key(
    records: Sequence[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for item in records or []:
        if not isinstance(item, dict) or item.get("rendered") is False:
            continue
        frames.append({
            "path": item.get("scope_path") or item.get("path"),
            "depth": item.get("depth"),
            "url": item.get("url"),
            "name": item.get("name"),
            "src": item.get("src"),
            "sandbox": item.get("sandbox"),
            "same_origin": item.get("same_origin"),
            "accessible": bool(item.get("accessible")),
            "opaque_frame": bool(item.get("opaque_frame")),
            "opaque_reason": item.get("opaque_reason"),
            "navigation_state": item.get("navigation_state"),
            "x": _number(item.get("x")),
            "y": _number(item.get("y")),
            "width": _number(item.get("width")),
            "height": _number(item.get("height")),
        })
    return sorted(frames, key=lambda item: str(item.get("path") or ""))


def compare_frame_trees(
    left: Sequence[dict[str, Any]] | None,
    right: Sequence[dict[str, Any]] | None,
) -> dict[str, Any]:
    left_key = frame_tree_key(left)
    right_key = frame_tree_key(right)
    reasons: list[str] = []
    if len(left_key) != len(right_key):
        reasons.append("frame-count-mismatch")
    left_by_path = {str(item.get("path")): item for item in left_key}
    right_by_path = {str(item.get("path")): item for item in right_key}
    if set(left_by_path) != set(right_by_path):
        reasons.append("frame-path-mismatch")
    for path in sorted(set(left_by_path) & set(right_by_path)):
        a = left_by_path[path]
        b = right_by_path[path]
        if str(a.get("url") or "") != str(b.get("url") or ""):
            reasons.append("frame-url-mismatch")
        if a.get("navigation_state") != b.get("navigation_state"):
            reasons.append("frame-navigation-mismatch")
        if (
            a.get("accessible") != b.get("accessible")
            or a.get("opaque_reason") != b.get("opaque_reason")
        ):
            reasons.append("frame-access-mismatch")
        if any(
            abs(float(a.get(axis) or 0) - float(b.get(axis) or 0))
            > GEOMETRY_TOLERANCE_PX
            for axis in ("x", "y", "width", "height")
        ):
            reasons.append("frame-geometry-mismatch")
    return {
        "schema_version": FRAME_BARRIER_SCHEMA,
        "match": not reasons,
        "reasons": _dedupe(reasons),
        "left_frame_count": len(left_key),
        "right_frame_count": len(right_key),
        "left": left_key,
        "right": right_key,
    }


class FrameBarrierGate:
    """One-use synchronized frame-tree comparison for two capture workers."""

    def __init__(self, *, timeout_s: float = 3.0) -> None:
        self.timeout_s = max(0.01, float(timeout_s))
        self._condition = threading.Condition()
        self._entries: dict[str, list[dict[str, Any]]] = {}
        self._generation = 0
        self._result: dict[str, Any] | None = None
        self._timed_out = False

    def sync(
        self,
        peer: str,
        records: Sequence[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        with self._condition:
            if self._result is not None:
                return dict(self._result)
            if peer in self._entries:
                raise ValueError(f"duplicate barrier peer: {peer}")
            self._entries[peer] = frame_tree_key(records)
            if len(self._entries) == 2 and not self._timed_out:
                left, right = list(self._entries.values())
                comparison = compare_frame_trees(left, right)
                self._result = {
                    "schema_version": FRAME_BARRIER_SCHEMA,
                    "synchronized": True,
                    "frame_tree_match": comparison["match"],
                    "reasons": comparison["reasons"],
                    "peer_count": 2,
                    "timed_out": False,
                    "comparison": comparison,
                }
                self._generation += 1
                self._condition.notify_all()
                return dict(self._result)
            generation = self._generation
            deadline = time.monotonic() + self.timeout_s
            while self._generation == generation and self._result is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._timed_out = True
                    self._result = {
                        "schema_version": FRAME_BARRIER_SCHEMA,
                        "synchronized": False,
                        "frame_tree_match": False,
                        "reasons": ["peer-timeout"],
                        "peer_count": len(self._entries),
                        "timed_out": True,
                        "comparison": None,
                    }
                    self._generation += 1
                    self._condition.notify_all()
                    break
                self._condition.wait(timeout=remaining)
            assert self._result is not None
            return dict(self._result)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
