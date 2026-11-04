# -*- coding: utf-8 -*-
"""grounding 路线：VLM 直接看图输出容器/元素 bbox -> PageGraph。"""

from __future__ import annotations

import copy
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
from src.app.services.structure.image_enrichment.assets import (
    classify_full_screenshot_underlay,
    recover_visible_assets,
)
from src.app.services.structure.image_enrichment.backgrounds import (
    create_background_candidates,
)
from src.app.services.structure.image_enrichment.controls import (
    recover_visible_controls,
)
from src.app.services.structure.image_enrichment.prompts import (
    build_grounding_tile_prompt,
)
from src.app.services.structure.image_enrichment.tiling import (
    crop_image_tile,
    plan_image_tiles,
)
from src.app.services.structure.providers.base import BaseProvider, ProviderContext


class ImageEnrichmentBlockedError(ValueError):
    def __init__(self, graph: dict, message: str) -> None:
        super().__init__(message)
        self.code = "blocked-full-screenshot-underlay"
        self.graph = graph


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


def _image_enrichment_mode(cfg: Any) -> str:
    value = str(getattr(cfg, "image_enrichment_mode", "off") or "off").lower()
    if value not in {"off", "analyze", "apply"}:
        raise ValueError("image_enrichment_mode must be off, analyze or apply")
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


def _needs_structure_supplement(raw: Any) -> bool:
    if not isinstance(raw, dict) or not raw.get("tables"):
        return False
    return (
        len(raw.get("containers") or [])
        + len(raw.get("elements") or [])
        < 24
    )


def _merge_structure_supplement(raw: dict, supplement: dict) -> dict:
    merged = copy.deepcopy(raw)
    control_fields = (
        "controlType",
        "controlValue",
        "controlState",
        "placeholder",
        "state",
        "value",
    )
    structured_elements = [
        element
        for element in raw.get("elements") or []
        if isinstance(element, dict)
    ]
    merged_elements = copy.deepcopy(supplement.get("elements") or [])
    for element in merged_elements:
        if not isinstance(element, dict):
            continue
        element_box = element.get("bbox") or []
        candidates = []
        for structured in structured_elements:
            structured_box = structured.get("bbox") or []
            text_match = (
                str(structured.get("text") or "").strip()
                and str(structured.get("text") or "").strip()
                == str(element.get("text") or "").strip()
            )
            overlap = 0.0
            if len(element_box) == len(structured_box) == 4:
                left = max(float(element_box[0]), float(structured_box[0]))
                top = max(float(element_box[1]), float(structured_box[1]))
                right = min(
                    float(element_box[0]) + float(element_box[2]),
                    float(structured_box[0]) + float(structured_box[2]),
                )
                bottom = min(
                    float(element_box[1]) + float(element_box[3]),
                    float(structured_box[1]) + float(structured_box[3]),
                )
                intersection = max(0.0, right - left) * max(0.0, bottom - top)
                smaller = min(
                    float(element_box[2]) * float(element_box[3]),
                    float(structured_box[2]) * float(structured_box[3]),
                )
                overlap = intersection / smaller if smaller > 0 else 0.0
            if text_match or overlap >= 0.4:
                candidates.append((2 * int(text_match) + overlap, structured))
        if not candidates:
            continue
        structured = max(candidates, key=lambda item: item[0])[1]
        for field in control_fields:
            if structured.get(field) is not None:
                element[field] = structured[field]
        if not str(element.get("text") or "").strip():
            element["text"] = str(
                structured.get("controlValue")
                or structured.get("text")
                or ""
            )
    merged["containers"] = copy.deepcopy(supplement.get("containers") or [])
    merged["elements"] = merged_elements
    merged["structureSupplement"] = {
        "status": "applied",
        "containers": len(merged["containers"]),
        "elements": len(merged["elements"]),
    }
    return merged


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


def _translate_bbox_object(
    value: Any,
    source_x: int,
    source_y: int,
) -> Any:
    try:
        if isinstance(value, dict):
            x = int(value["x"]) + source_x
            y = int(value["y"]) + source_y
            width = int(value["width"])
            height = int(value["height"])
        elif isinstance(value, (list, tuple)) and len(value) == 4:
            x = int(value[0]) + source_x
            y = int(value[1]) + source_y
            width = int(value[2])
            height = int(value[3])
        else:
            return value
    except (KeyError, TypeError, ValueError):
        return value
    return [x, y, width, height]


def _translate_enrichment_candidates(
    raw: dict,
    tile: dict[str, Any],
) -> dict[str, Any]:
    source_x, source_y, _source_width, _source_height = tile["source_rect"]
    assets = []
    for asset in raw.get("assets") or []:
        if isinstance(asset, dict):
            item = copy.deepcopy(asset)
            item["bbox"] = _translate_bbox_object(
                item.get("bbox"),
                source_x,
                source_y,
            )
            assets.append(item)
    backgrounds = []
    for background in raw.get("backgrounds") or []:
        if not isinstance(background, dict):
            continue
        item = copy.deepcopy(background)
        item["bbox"] = _translate_bbox_object(
            item.get("bbox"),
            source_x,
            source_y,
        )
        item["overlays"] = [
            {
                **dict(overlay),
                "bbox": _translate_bbox_object(
                    overlay.get("bbox"),
                    source_x,
                    source_y,
                ),
            }
            for overlay in item.get("overlays") or []
            if isinstance(overlay, dict)
        ]
        backgrounds.append(item)
    return {
        "assets": assets,
        "backgrounds": backgrounds,
        "diagnostics": list(raw.get("enrichmentDiagnostics") or []),
    }


def _tile_prompt(
    tile: dict[str, Any],
    ctx: ProviderContext,
    enrichment_mode: str = "off",
) -> str:
    from src.app.services.structure.backends.grounding_vlm import PROMPT

    if enrichment_mode != "off":
        return build_grounding_tile_prompt(
            tile,
            {
                "image_size": [ctx.image_w, ctx.image_h],
                "image_enrichment_mode": enrichment_mode,
            },
        )
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
    bbox_format: str = "normalized-xyxy",
) -> dict:
    method = getattr(backend, "ground_with_prompt", None)
    if callable(method):
        return method(
            image_path,
            width,
            height,
            prompt,
            strategy_id=strategy_id,
            metadata={"tile": tile, "bbox_format": bbox_format},
        )
    return backend.ground(image_path, width, height)


def _graph_from_raw(
    raw: dict,
    ctx: ProviderContext,
    tile: dict[str, Any],
    enrichment_mode: str = "off",
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
        extracted = graph["elements"][-1]
        for field in (
            "controlType",
            "controlValue",
            "controlState",
            "placeholder",
            "state",
            "value",
        ):
            if element.get(field) is not None:
                extracted[field] = element[field]
    graph["provenance"]["tiling"] = {"tile": dict(tile)}
    graph["tables"] = copy.deepcopy(raw.get("tables") or [])
    if enrichment_mode != "off":
        graph["imageEnrichment"] = _translate_enrichment_candidates(raw, tile)
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


def _merge_enrichment_candidates(graphs: list[dict]) -> dict[str, Any]:
    assets: list[dict] = []
    backgrounds: list[dict] = []
    diagnostics: list[dict] = []
    seen_assets: set[tuple[Any, ...]] = set()
    seen_backgrounds: set[tuple[Any, ...]] = set()
    for graph in graphs:
        value = graph.get("imageEnrichment")
        if not isinstance(value, dict):
            continue
        for asset in value.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            key = (
                str(asset.get("name") or ""),
                str(asset.get("kind") or ""),
                json.dumps(asset.get("bbox"), sort_keys=True),
            )
            if key not in seen_assets:
                seen_assets.add(key)
                assets.append(copy.deepcopy(asset))
        for background in value.get("backgrounds") or []:
            if not isinstance(background, dict):
                continue
            key = (
                str(background.get("id") or background.get("name") or ""),
                json.dumps(background.get("bbox"), sort_keys=True),
            )
            if key not in seen_backgrounds:
                seen_backgrounds.add(key)
                backgrounds.append(copy.deepcopy(background))
        diagnostics.extend(copy.deepcopy(value.get("diagnostics") or []))
    return {
        "assets": assets,
        "backgrounds": backgrounds,
        "diagnostics": diagnostics,
    }


def _detect_graph_underlays(
    graph: dict,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    underlays = []
    for element in graph.get("elements") or []:
        if not isinstance(element, dict):
            continue
        if str(element.get("type") or "").lower() not in {"image", "avatar"}:
            continue
        result = classify_full_screenshot_underlay(
            {
                "name": element.get("assetName") or element.get("name"),
                "kind": element.get("assetKind") or element.get("kind"),
                "bbox": element.get("bbox"),
                "role": element.get("role"),
                "background": element.get("background"),
            },
            graph,
            width=width,
            height=height,
        )
        if result["is_underlay"]:
            underlays.append(
                {
                    "name": str(
                        element.get("assetName")
                        or element.get("name")
                        or element.get("id")
                        or ""
                    ),
                    "bbox": list(element.get("bbox") or []),
                    "classification": result,
                }
            )
    return underlays


def _finalize_image_enrichment(
    graph: dict,
    candidates: dict[str, Any],
    ctx: ProviderContext,
    mode: str,
    control_report: dict[str, Any] | None = None,
) -> dict:
    if mode == "off":
        return graph
    original_elements = copy.deepcopy(graph.get("elements") or [])
    working = graph if mode == "apply" else copy.deepcopy(graph)
    working["imageEnrichment"] = {
        **copy.deepcopy(candidates),
        "mode": mode,
        "status": "analyzing" if mode == "analyze" else "applying",
        "tiling": copy.deepcopy((graph.get("provenance") or {}).get("tiling") or {}),
    }
    work_dir = Path(ctx.output_dir or ".") / "image_enrichment"
    recovery_report: dict[str, Any] = {}
    if candidates.get("assets"):
        working, recovery_report = recover_visible_assets(
            working,
            Path(ctx.image_path),
            work_dir=work_dir,
        )
        if mode == "apply":
            graph = working
    enrichment = working.setdefault("imageEnrichment", {})
    enrichment["backgroundCandidates"] = []
    if mode == "apply" and candidates.get("backgrounds"):
        with Image.open(ctx.image_path) as source_image:
            image = source_image.convert("RGB")
            for background in candidates["backgrounds"]:
                enrichment["backgroundCandidates"].append(
                    create_background_candidates(
                        image,
                        background,
                        list(background.get("overlays") or []),
                        work_dir,
                    )
                )
    diagnostics = list(candidates.get("diagnostics") or [])
    diagnostics.extend(
        {
            "code": item.get("reason", "asset-deduplicated"),
            "path": "$.imageEnrichment.assets",
            "message": "asset candidate was deduplicated",
            "asset": item,
        }
        for item in recovery_report.get("deduplicated") or []
    )
    underlays = [
        *(recovery_report.get("underlays") or []),
        *_detect_graph_underlays(
            working,
            width=ctx.image_w,
            height=ctx.image_h,
        ),
    ]
    unique_underlays = []
    for item in underlays:
        key = (
            str(item.get("name") or ""),
            json.dumps(item.get("bbox"), sort_keys=True),
        )
        if all(
            (
                str(existing.get("name") or ""),
                json.dumps(existing.get("bbox"), sort_keys=True),
            )
            != key
            for existing in unique_underlays
        ):
            unique_underlays.append(item)
    generated_payloads = []
    for asset in enrichment.get("assets") or []:
        generated = asset.get("generatedApproximation")
        if isinstance(generated, dict) and generated.get("bytes_present"):
            generated_payloads.append(
                {
                    "asset": asset.get("name"),
                    **generated,
                }
            )
    for background in enrichment.get("backgroundCandidates") or []:
        clean = background.get("cleanCandidate")
        if isinstance(clean, dict):
            generated_payloads.append(
                {
                    "background": background.get("id"),
                    **clean,
                }
            )
    enrichment.update(
        {
            "mode": mode,
            "status": (
                "blocked-full-screenshot-underlay"
                if mode == "apply" and unique_underlays
                else "applied"
                if mode == "apply"
                else "underlay-detected"
                if unique_underlays
                else "analyzed"
            ),
            "assets": copy.deepcopy(enrichment.get("assets") or []),
            "backgrounds": copy.deepcopy(candidates.get("backgrounds") or []),
            "generatedPayloads": generated_payloads,
            "controlRecovery": copy.deepcopy(control_report or {}),
            "diagnostics": diagnostics,
            "underlays": unique_underlays,
            "provenance": {
                "source": "grounding-image-enrichment/1.0",
                "authority": "candidate",
                "originalAssets": False,
                "hiddenRegionRecovery": "candidate-only",
            },
        }
    )
    graph["imageEnrichment"] = copy.deepcopy(enrichment)
    graph["sliceAnalysis"] = {
        "assets": copy.deepcopy(enrichment["assets"]),
        "backgrounds": copy.deepcopy(enrichment["backgrounds"]),
        "provenance": copy.deepcopy(enrichment["provenance"]),
    }
    if mode == "analyze":
        graph["elements"] = original_elements
    if mode == "apply" and unique_underlays:
        raise ImageEnrichmentBlockedError(
            graph,
            "blocked-full-screenshot-underlay",
        )
    return graph


class GroundingProvider(BaseProvider):
    name = "grounding"

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg

    def run(self, ctx: ProviderContext) -> dict:
        backend = _default_backend(self.cfg)
        enrichment_mode = _image_enrichment_mode(self.cfg)
        max_height = _positive_int(
            int(getattr(self.cfg, "vision_tile_max_height", 4096)),
            "vision_tile_max_height",
        )
        overlap = _non_negative_int(
            int(getattr(self.cfg, "vision_tile_overlap", 256)),
            "vision_tile_overlap",
        )
        if ctx.image_h <= max_height:
            tile = _single_tile(ctx.image_w, ctx.image_h)
            if enrichment_mode == "off":
                raw = backend.ground(ctx.image_path, ctx.image_w, ctx.image_h)
            else:
                raw = _call_backend(
                    backend,
                    ctx.image_path,
                    ctx.image_w,
                    ctx.image_h,
                    prompt=_tile_prompt(tile, ctx, enrichment_mode),
                    strategy_id="grounding-enrichment",
                    tile=tile,
                    bbox_format="source-px-xywh",
                )
                if _needs_structure_supplement(raw):
                    supplement = backend.ground(
                        ctx.image_path,
                        ctx.image_w,
                        ctx.image_h,
                    )
                    raw = _merge_structure_supplement(raw, supplement)
            if not _has_structure(raw) and not _is_majority_background(
                ctx.image_path
            ):
                raise GroundingRequestError(
                    "empty-structure",
                    "Grounding returned no structure for a non-background image",
                )
            graph = _graph_from_raw(raw, ctx, tile, enrichment_mode)
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
            final = _finalize_image_enrichment(
                final,
                _translate_enrichment_candidates(raw, tile),
                ctx,
                enrichment_mode,
            )
            if enrichment_mode != "off":
                final, control_report = recover_visible_controls(
                    final,
                    Path(ctx.image_path),
                    add_from_assets=enrichment_mode == "apply",
                )
                final["imageEnrichment"]["controlRecovery"] = copy.deepcopy(
                    control_report
                )
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
        final = _finalize_image_enrichment(
            final,
            _merge_enrichment_candidates(tile_graphs),
            ctx,
            enrichment_mode,
        )
        if enrichment_mode != "off":
            final, control_report = recover_visible_controls(
                final,
                Path(ctx.image_path),
                add_from_assets=enrichment_mode == "apply",
            )
            final["imageEnrichment"]["controlRecovery"] = copy.deepcopy(
                control_report
            )
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
        enrichment_mode = _image_enrichment_mode(self.cfg)
        bbox_format = (
            "normalized-xyxy"
            if enrichment_mode == "off"
            else "source-px-xywh"
        )
        prompt = _tile_prompt(tile, ctx, enrichment_mode)
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
                bbox_format=bbox_format,
            )
            if _needs_structure_supplement(raw):
                supplement = backend.ground(
                    str(tile_path),
                    tile_image.width,
                    tile_image.height,
                )
                raw = _merge_structure_supplement(raw, supplement)
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
                    bbox_format=bbox_format,
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
        graph = _graph_from_raw(raw, ctx, tile, enrichment_mode)
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
