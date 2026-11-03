# -*- coding: utf-8 -*-
"""grounding 路线：VLM 直接看图输出容器/元素 bbox -> PageGraph。"""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from src.app.services.structure.backends.grounding_base import GroundingBackend
from src.app.services.structure.backends.grounding_reliability import (
    GroundingRequestError,
)
from src.app.services.structure.graph import new_graph, add_container, add_element
from src.app.services.structure.image_enrichment.merge import merge_tiled_graphs
from src.app.services.structure.image_enrichment.tiling import (
    crop_image_tile,
    plan_image_tiles,
)
from src.app.services.structure.providers.base import BaseProvider, ProviderContext


def _default_backend(cfg) -> GroundingBackend:
    from src.app.services.structure.backends.grounding_vlm import GroundingVLM

    return GroundingVLM(cfg)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _single_tile(width: int, height: int) -> dict[str, Any]:
    return {
        "id": "tile-0000",
        "index": 0,
        "source_rect": [0, 0, width, height],
        "page_origin": [0, 0],
        "overlap_with_previous": 0,
        "reason": "single-tile",
    }


def _tile_record(tile: dict[str, Any], status: str | None = None) -> dict[str, Any]:
    record = {
        key: json.loads(json.dumps(tile[key]))
        for key in ("id", "source_rect", "page_origin", "reason")
        if key in tile
    }
    if status:
        record["status"] = status
    return record


def _has_structure(raw: Any) -> bool:
    return bool(
        isinstance(raw, dict)
        and (raw.get("containers") or raw.get("elements"))
    )


def _is_majority_background(path: str, threshold: float = 0.96) -> bool:
    with Image.open(path) as image:
        sample = image.convert("RGB")
        sample.thumbnail((128, 128))
        raw = sample.tobytes()
    pixels = [raw[index : index + 3] for index in range(0, len(raw), 3)]
    if not pixels:
        return True
    dominant = Counter(pixels).most_common(1)[0][1]
    return dominant / len(pixels) >= threshold


def _tile_prompt(tile: dict[str, Any], ctx: ProviderContext) -> str:
    from src.app.services.structure.backends.grounding_vlm import PROMPT

    metadata = {
        "tile_id": tile.get("id"),
        "source_rect": tile.get("source_rect"),
        "page_size": [ctx.image_w, ctx.image_h],
    }
    return "\n".join(
        [
            PROMPT,
            f"Tile metadata: {json.dumps(metadata, sort_keys=True)}",
            "All returned bbox values are normalized to this tile image and will be translated to page coordinates.",
        ]
    )


def _repair_prompt(prompt: str, error: GroundingRequestError) -> str:
    raw_response = str(getattr(error, "raw_response", "") or "")
    return "\n".join(
        [
            "Repair the following model output into one valid JSON object.",
            "Do not add, delete, merge, or deduplicate containers or elements.",
            prompt,
            raw_response,
        ]
    )


def _call_backend(
    backend: GroundingBackend,
    image_path: str,
    width: int,
    height: int,
    *,
    prompt: str,
    strategy_id: str,
    tile: dict[str, Any],
) -> dict:
    method = getattr(backend, "ground_with_prompt", None)
    if callable(method):
        return method(
            image_path,
            width,
            height,
            prompt,
            strategy_id=strategy_id,
            metadata={"tile": tile},
        )
    return backend.ground(image_path, width, height)


def _graph_from_raw(
    raw: dict,
    ctx: ProviderContext,
    tile: dict[str, Any],
) -> dict:
    graph = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "grounding")
    source_x, source_y, _source_w, _source_h = tile["source_rect"]
    for container in raw.get("containers") or []:
        box = list(container.get("bbox") or [])
        if len(box) != 4:
            continue
        add_container(
            graph,
            [
                int(box[0]) + source_x,
                int(box[1]) + source_y,
                int(box[2]),
                int(box[3]),
            ],
            role=str(container.get("role") or ""),
            source="grounding",
        )
    for element in raw.get("elements") or []:
        box = list(element.get("bbox") or [])
        if len(box) != 4:
            continue
        add_element(
            graph,
            [
                int(box[0]) + source_x,
                int(box[1]) + source_y,
                int(box[2]),
                int(box[3]),
            ],
            type_=str(element.get("type") or "rectangle"),
            text=str(element.get("text") or ""),
            source="grounding",
        )
    graph["provenance"]["tiling"] = {"tile": dict(tile)}
    return graph


def _smaller_tiles(
    tile: dict[str, Any],
    overlap: int,
) -> list[dict[str, Any]]:
    source_x, source_y, width, height = tile["source_rect"]
    smaller_height = max(32, height // 2)
    smaller_overlap = min(overlap, max(0, smaller_height // 4))
    plans = plan_image_tiles(
        width,
        height,
        max_tile_height=smaller_height,
        overlap=smaller_overlap,
    )
    return [
        {
            **plan,
            "id": f"retry-{str(tile.get('id') or 'tile').removeprefix('tile-')}-{plan['index']}",
            "source_rect": [
                source_x + plan["source_rect"][0],
                source_y + plan["source_rect"][1],
                plan["source_rect"][2],
                plan["source_rect"][3],
            ],
            "page_origin": [
                source_x + plan["page_origin"][0],
                source_y + plan["page_origin"][1],
            ],
            "reason": "provider-retry",
        }
        for plan in plans
    ]


def _collect_report(backend: GroundingBackend) -> dict[str, Any] | None:
    report = getattr(backend, "last_report", None)
    if report is None:
        return None
    transformed = report.to_dict() if hasattr(report, "to_dict") else dict(report)
    return dict(transformed)


class GroundingProvider(BaseProvider):
    name = "grounding"

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg

    def run(self, ctx: ProviderContext) -> dict:
        backend = _default_backend(self.cfg)
        max_height = _positive_int(
            int(getattr(self.cfg, "vision_tile_max_height", 4096)),
            "vision_tile_max_height",
        )
        overlap = _non_negative_int(
            int(getattr(self.cfg, "vision_tile_overlap", 256)),
            "vision_tile_overlap",
        )
        if ctx.image_h <= max_height:
            raw = backend.ground(ctx.image_path, ctx.image_w, ctx.image_h)
            if not _has_structure(raw) and not _is_majority_background(
                ctx.image_path
            ):
                raise GroundingRequestError(
                    "empty-structure",
                    "Grounding returned no structure for a non-background image",
                )
            tile = _single_tile(ctx.image_w, ctx.image_h)
            graph = _graph_from_raw(raw, ctx, tile)
            report = _collect_report(backend)
            if report is not None:
                graph["provenance"]["grounding_reliability"] = report
            final, tiling_report = merge_tiled_graphs(
                [graph], ctx.image_w, ctx.image_h
            )
            tiling_report["tiles"] = [_tile_record(tile)]
            if report is not None:
                final["provenance"]["grounding_reliability"] = report
            final["provenance"]["tiling"] = tiling_report
            return final

        with tempfile.TemporaryDirectory(prefix="grounding-tiles-") as temp_dir:
            with Image.open(ctx.image_path) as source_image:
                planned = plan_image_tiles(
                    ctx.image_w,
                    ctx.image_h,
                    max_tile_height=max_height,
                    overlap=overlap,
                )
                tile_graphs: list[dict] = []
                tile_records: list[dict[str, Any]] = []
                tile_reports: list[dict[str, Any]] = []
                for planned_tile in planned:
                    graphs, record, reports = self._ground_tile(
                        backend,
                        ctx,
                        source_image,
                        planned_tile,
                        Path(temp_dir),
                        overlap,
                        allow_smaller_retry=True,
                    )
                    tile_graphs.extend(graphs)
                    tile_records.append(record)
                    tile_reports.extend(reports)

        final, tiling_report = merge_tiled_graphs(
            tile_graphs, ctx.image_w, ctx.image_h
        )
        tiling_report["tiles"] = tile_records
        tiling_report["tile_reports"] = tile_reports
        final["provenance"]["tiling"] = tiling_report
        final["provenance"]["grounding_reliability"] = {
            "mode": "tiled",
            "tile_reports": tile_reports,
        }
        return final

    def _ground_tile(
        self,
        backend: GroundingBackend,
        ctx: ProviderContext,
        source_image: Image.Image,
        tile: dict[str, Any],
        temp_dir: Path,
        overlap: int,
        *,
        allow_smaller_retry: bool,
    ) -> tuple[list[dict], dict[str, Any], list[dict[str, Any]]]:
        tile_image = crop_image_tile(source_image, tile)
        tile_path = temp_dir / f"{tile['id']}.png"
        tile_image.save(tile_path)
        prompt = _tile_prompt(tile, ctx)
        reports: list[dict[str, Any]] = []

        try:
            raw = _call_backend(
                backend,
                str(tile_path),
                tile_image.width,
                tile_image.height,
                prompt=prompt,
                strategy_id="grounding-tile",
                tile=tile,
            )
            status = None
        except GroundingRequestError as exc:
            if exc.category != "response-invalid":
                raise
            report = _collect_report(backend)
            if report is not None:
                reports.append(report)
            try:
                raw = _call_backend(
                    backend,
                    str(tile_path),
                    tile_image.width,
                    tile_image.height,
                    prompt=_repair_prompt(prompt, exc),
                    strategy_id="grounding-tile-repair",
                    tile=tile,
                )
                status = "recovered-by-repair"
            except GroundingRequestError as repair_error:
                report = _collect_report(backend)
                if report is not None:
                    reports.append(report)
                if repair_error.category != "response-invalid":
                    raise
                if allow_smaller_retry and tile["source_rect"][3] > 64:
                    return self._retry_with_smaller_tiles(
                        backend,
                        ctx,
                        source_image,
                        tile,
                        temp_dir,
                        overlap,
                        reports,
                    )
                raise

        if not _has_structure(raw) and not _is_majority_background(str(tile_path)):
            if allow_smaller_retry and tile["source_rect"][3] > 64:
                return self._retry_with_smaller_tiles(
                    backend,
                    ctx,
                    source_image,
                    tile,
                    temp_dir,
                    overlap,
                    reports,
                )
            raise GroundingRequestError(
                "empty-structure",
                "Grounding returned no structure for a non-background tile",
            )

        report = _collect_report(backend)
        if report is not None:
            reports.append(report)
        graph = _graph_from_raw(raw, ctx, tile)
        return [graph], _tile_record(tile, status), reports

    def _retry_with_smaller_tiles(
        self,
        backend: GroundingBackend,
        ctx: ProviderContext,
        source_image: Image.Image,
        tile: dict[str, Any],
        temp_dir: Path,
        overlap: int,
        reports: list[dict[str, Any]],
    ) -> tuple[list[dict], dict[str, Any], list[dict[str, Any]]]:
        graphs: list[dict] = []
        for smaller in _smaller_tiles(tile, overlap):
            subgraphs, _record, subreports = self._ground_tile(
                backend,
                ctx,
                source_image,
                smaller,
                temp_dir,
                overlap,
                allow_smaller_retry=False,
            )
            graphs.extend(subgraphs)
            reports.extend(subreports)
        return (
            graphs,
            _tile_record(tile, "recovered-by-smaller-tiles"),
            reports,
        )
