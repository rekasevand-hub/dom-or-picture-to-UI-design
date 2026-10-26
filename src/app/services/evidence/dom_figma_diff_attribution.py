"""Offline attribution of real Figma pixel differences to design elements."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.app.services.rendering.figma_acceptance import (
    _design_elements,
    _element_type,
    _global_box,
    _iter_nodes,
    _match_element_candidate,
    _root_origin,
)


def build_diff_attribution(
    design: Mapping[str, Any],
    readback: Mapping[str, Any],
    reference_png: str | Path,
    render_png: str | Path,
    *,
    threshold: int = 30,
    search_radius: int = 2,
) -> dict[str, Any]:
    """Join design elements to readback and attribute over-threshold pixels."""
    reference = cv2.imread(str(reference_png))
    render = cv2.imread(str(render_png))
    if reference is None or render is None:
        raise ValueError("reference and render PNGs must be readable")
    if reference.shape != render.shape:
        raise ValueError(
            f"image size mismatch: reference={reference.shape[:2]} "
            f"render={render.shape[:2]}"
        )
    raw_diff = np.abs(render.astype(np.int16) - reference.astype(np.int16))
    max_diff = raw_diff.max(axis=2)
    over_mask = max_diff > int(threshold)
    total_pixels = int(over_mask.size)
    total_over30 = int(over_mask.sum())
    nodes = list(_iter_nodes(dict(readback)))
    root_origin = _root_origin(dict(readback))
    candidates = nodes[1:]
    used: set[int] = set()
    element_rows: list[dict[str, Any]] = []
    covered = np.zeros_like(over_mask, dtype=bool)
    text_shift_counts: Counter[str] = Counter()
    style_rows: dict[str, dict[str, Any]] = {}
    for element in _design_elements(dict(design)):
        candidate_index, candidate = _match_element_candidate(
            element,
            candidates,
            used,
            root_origin,
        )
        if candidate is None or candidate_index is None:
            continue
        used.add(candidate_index)
        box = _integer_box(
            _global_box(candidate, root_origin),
            reference.shape[1],
            reference.shape[0],
        )
        if box is None:
            continue
        x, y, width, height = box
        x1, y1 = x + width, y + height
        local_mask = over_mask[y:y1, x:x1]
        local_over = int(local_mask.sum())
        local_pixels = int(local_mask.size)
        covered[y:y1, x:x1] = True
        (
            best_dx,
            best_dy,
            best_mean,
            zero_mean,
            best_shift_over30,
            zero_shift_over30,
        ) = _best_render_shift(
            reference,
            render,
            box,
            search_radius=max(0, int(search_radius)),
            threshold=int(threshold),
        )
        kind = _element_type(element)
        style_key = _style_key(element, kind)
        text = str(element.get("text") or "")
        row = {
            "element_id": element.get("id"),
            "node_id": candidate.get("id"),
            "kind": kind,
            "text": text,
            "style_key": style_key,
            "bounds": {
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            },
            "pixel_count": local_pixels,
            "over30": local_over,
            "over30_ratio": (float(local_over / local_pixels) if local_pixels else 0.0),
            "best_dx": best_dx,
            "best_dy": best_dy,
            "best_shift_mean_delta": best_mean,
            "zero_shift_mean_delta": zero_mean,
            "best_shift_over30": best_shift_over30,
            "zero_shift_over30": zero_shift_over30,
        }
        element_rows.append(row)
        if kind == "text":
            text_shift_counts[f"{best_dx},{best_dy}"] += 1
        style = style_rows.setdefault(
            style_key,
            {
                "style_key": style_key,
                "kind": kind,
                "node_count": 0,
                "pixel_count": 0,
                "over30": 0,
                "best_shift_over30": 0,
                "shift_counts": {},
            },
        )
        style["node_count"] += 1
        style["pixel_count"] += local_pixels
        style["over30"] += local_over
        style["best_shift_over30"] += best_shift_over30
        if kind == "text":
            shifts = style.setdefault("shift_counts", {})
            shift_key = f"{best_dx},{best_dy}"
            shifts[shift_key] = int(shifts.get(shift_key, 0)) + 1
    for style in style_rows.values():
        pixels = int(style.get("pixel_count") or 0)
        style["over30_ratio"] = (
            float(int(style.get("over30") or 0) / pixels) if pixels else 0.0
        )
        style["shift_counts"] = dict(
            sorted(
                style.get("shift_counts", {}).items(),
                key=lambda item: (-item[1], item[0]),
            )
        )
    matched_over30 = int((over_mask & covered).sum())
    return {
        "schema_version": "dom-figma-diff-attribution/1.0",
        "threshold": int(threshold),
        "search_radius": max(0, int(search_radius)),
        "image_shape": list(reference.shape),
        "total_pixels": total_pixels,
        "total_over30": total_over30,
        "total_over30_ratio": (
            float(total_over30 / total_pixels) if total_pixels else 0.0
        ),
        "matched_node_over30_union": matched_over30,
        "unmatched_over30": total_over30 - matched_over30,
        "node_over30_sum_with_overlap": sum(int(row["over30"]) for row in element_rows),
        "text_shift_counts": dict(
            sorted(
                text_shift_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "nodes": sorted(
            element_rows,
            key=lambda row: (-int(row["over30"]), str(row["element_id"])),
        ),
        "styles": dict(sorted(style_rows.items())),
        "figma_runtime": "observed-existing-frame",
        "composite_score_used": False,
    }


def _integer_box(
    box: Mapping[str, Any],
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int] | None:
    try:
        x0 = max(0, int(np.floor(float(box.get("x") or 0.0))))
        y0 = max(0, int(np.floor(float(box.get("y") or 0.0))))
        x1 = min(
            image_width,
            int(np.ceil(float(box.get("x") or 0.0) + float(box.get("width") or 0.0))),
        )
        y1 = min(
            image_height,
            int(np.ceil(float(box.get("y") or 0.0) + float(box.get("height") or 0.0))),
        )
    except (TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1 - x0, y1 - y0


def _best_render_shift(
    reference: np.ndarray,
    render: np.ndarray,
    box: tuple[int, int, int, int],
    *,
    search_radius: int,
    threshold: int,
) -> tuple[int, int, float, float, int, int]:
    x, y, width, height = box
    height_px, width_px = reference.shape[:2]
    reference_crop = reference[y : y + height, x : x + width]
    zero_crop = render[y : y + height, x : x + width]
    zero_mean = _mean_abs_delta(reference_crop, zero_crop)
    zero_shift_over30 = _count_over30(
        reference_crop,
        zero_crop,
        threshold,
    )
    best = (0, 0, zero_mean, zero_shift_over30)
    for dy in range(-search_radius, search_radius + 1):
        for dx in range(-search_radius, search_radius + 1):
            rx0, ry0 = x + dx, y + dy
            rx1, ry1 = rx0 + width, ry0 + height
            if rx0 < 0 or ry0 < 0 or rx1 > width_px or ry1 > height_px:
                continue
            render_crop = render[ry0:ry1, rx0:rx1]
            mean_delta = _mean_abs_delta(reference_crop, render_crop)
            shifted_over30 = _count_over30(
                reference_crop,
                render_crop,
                threshold,
            )
            if (mean_delta, shifted_over30, abs(dx) + abs(dy), dx, dy) < (
                best[2],
                best[3],
                abs(best[0]) + abs(best[1]),
                best[0],
                best[1],
            ):
                best = (dx, dy, mean_delta, shifted_over30)
    return (
        best[0],
        best[1],
        float(best[2]),
        float(zero_mean),
        int(best[3]),
        int(zero_shift_over30),
    )


def _mean_abs_delta(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0 or left.shape != right.shape:
        return float("inf")
    return float(np.abs(left.astype(np.int16) - right.astype(np.int16)).mean())


def _count_over30(
    left: np.ndarray,
    right: np.ndarray,
    threshold: int,
) -> int:
    if left.size == 0 or right.size == 0 or left.shape != right.shape:
        return 0
    diff = np.abs(left.astype(np.int16) - right.astype(np.int16))
    return int((diff.max(axis=2) > int(threshold)).sum())


def _style_key(element: Mapping[str, Any], kind: str) -> str:
    if kind != "text":
        return kind
    style = element.get("style") or {}
    values = (
        style.get("fontFamily"),
        style.get("fontWeightValue") or style.get("fontWeight"),
        style.get("fontSize"),
        style.get("fontStyle"),
        style.get("lineHeight"),
        style.get("textAlign"),
    )
    return "text:" + "|".join(str(value or "") for value in values)
