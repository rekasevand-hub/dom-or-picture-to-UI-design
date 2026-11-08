# -*- coding: utf-8 -*-
"""qwen3-vl-plus（OpenAI 兼容）grounding 后端：截图 -> JSON bbox。原生 <|box_start|> 预留。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

from openai import OpenAI

from src.app.services.structure.backends.grounding_base import GroundingBackend
from src.app.services.structure.backends.grounding_reliability import (
    GroundingReliability,
    GroundingRequestError,
)
from src.app.services.structure.coordinate_space import (
    COORDINATE_CONTRACT_VERSION,
    AxisScales,
    CoordinateSpaceDecision,
    build_ink_scorer,
    canonical,
    infer_coordinate_space,
    legacy_axis_scales,
    resolve_bbox,
)
from src.app.services.structure.perception_fingerprint import (
    vision_request_contract,
)

if TYPE_CHECKING:
    from src.config import Config

ALLOWED_TYPES = {"button", "input", "text", "link", "image"}
ENRICHED_TYPES = ALLOWED_TYPES | {
    "checkbox",
    "icon-button",
    "navigation",
    "pagination",
    "radio",
    "select",
    "textarea",
    "toggle",
}


def _norm_box(b, image_w, image_h):
    try:
        f = [float(v) for v in b]
    except (TypeError, ValueError):
        return None
    if len(f) != 4:
        return None
    x0 = max(0.0, min(f[0], 1.0))
    y0 = max(0.0, min(f[1], 1.0))
    x1 = max(0.0, min(f[2], 1.0))
    y1 = max(0.0, min(f[3], 1.0))
    px0, py0 = int(round(x0 * image_w)), int(round(y0 * image_h))
    px1, py1 = int(round(x1 * image_w)), int(round(y1 * image_h))
    if px1 - px0 < 2 or py1 - py0 < 2:
        return None
    return [px0, py0, px1 - px0, py1 - py0]


def _source_px_box(
    value: Any,
    image_w: int,
    image_h: int,
    *,
    x_scale: float = 1.0,
    y_scale: float = 1.0,
    scale_width: bool = True,
    scale_height: bool = True,
) -> list[int] | None:
    if isinstance(value, Mapping):
        values = (
            value.get("x"),
            value.get("y"),
            value.get("width"),
            value.get("height"),
        )
    elif isinstance(value, (list, tuple)) and len(value) == 4:
        values = tuple(value)
    else:
        return None
    try:
        x, y, width, height = (float(item) for item in values)
    except (TypeError, ValueError):
        return None
    effective_width = width * x_scale if scale_width else width
    effective_height = height * y_scale if scale_height else height
    left = max(0.0, min(x * x_scale, x * x_scale + effective_width))
    top = max(0.0, min(y * y_scale, y * y_scale + effective_height))
    right = min(
        float(image_w),
        max(x * x_scale, x * x_scale + effective_width),
    )
    bottom = min(
        float(image_h),
        max(y * y_scale, y * y_scale + effective_height),
    )
    px0, py0 = int(round(left)), int(round(top))
    px1, py1 = int(round(right)), int(round(bottom))
    if px1 - px0 < 2 or py1 - py0 < 2:
        return None
    return [px0, py0, px1 - px0, py1 - py0]


def parse_vlm_json(
    raw: str,
    image_w: int,
    image_h: int,
    *,
    bbox_format: str = "normalized-xyxy",
    image_path: str | Path | None = None,
) -> dict:
    if bbox_format not in {"normalized-xyxy", "source-px-xywh"}:
        raise ValueError(f"unsupported bbox format: {bbox_format}")
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError("VLM 输出中没有 JSON 对象")
    data = json.loads(m.group(0))
    source_items = [
        item
        for key in ("containers", "elements", "assets", "backgrounds")
        for item in (data.get(key) or [])
        if isinstance(item, Mapping)
    ]
    raw_x_values = [
        float((item.get("bbox") or {}).get("x", 0))
        for item in source_items
        if isinstance(item.get("bbox"), Mapping)
        and isinstance((item.get("bbox") or {}).get("x"), (int, float))
    ]
    # A: choose the inverse coordinate transform from reference-pixel evidence.
    # Without an image (unit tests, offline tooling) keep the historical
    # behaviour byte-for-byte so existing parse-only contracts do not regress.
    ink_scorer = build_ink_scorer(image_path) if image_path else None
    if bbox_format == "source-px-xywh" and ink_scorer is not None:
        decision = infer_coordinate_space(
            source_items, image_w, image_h, ink_scorer
        )
        x_scale = decision.x_scale
        y_scale = decision.y_scale
        coordinate_space = decision.to_dict()
        evidence_scales = AxisScales(x_scale, y_scale, decision.provenance)
        use_evidence = True
    else:
        x_scale, y_scale, legacy_label = legacy_axis_scales(
            raw_x_values, image_w
        )
        coordinate_space = {
            "schema_version": COORDINATE_CONTRACT_VERSION,
            "xScale": round(x_scale, 6),
            "yScale": round(y_scale, 6),
            "provenance": (
                "normalized-xyxy"
                if bbox_format == "normalized-xyxy"
                else legacy_label
            ),
            "evidence": {"scoredBoxes": 0, "reason": "reference-pixels-unavailable"},
        }
        evidence_scales = None
        use_evidence = False
    out = {"containers": [], "elements": []}
    for c in data.get("containers", []):
        if use_evidence:
            box, box_provenance = resolve_bbox(
                c.get("bbox"),
                CoordinateSpaceDecision(x_scale, y_scale, evidence_scales.label),
                image_w,
                image_h,
                ink_scorer,
            )
        elif bbox_format == "source-px-xywh":
            box = _source_px_box(
                c.get("bbox"),
                image_w,
                image_h,
                x_scale=x_scale,
                y_scale=1.0,
                scale_width=(
                    float((c.get("bbox") or {}).get("x", 0))
                    + float((c.get("bbox") or {}).get("width", 0))
                    <= 1000
                ),
                scale_height=False,
            )
            box_provenance = "legacy-heuristic"
        else:
            box = _norm_box(c.get("bbox"), image_w, image_h)
            box_provenance = "normalized-xyxy"
        if box is None:
            continue
        out["containers"].append(
            {
                "bbox": box,
                "role": str(c.get("role", "")),
                "coordinateSpace": box_provenance,
            }
        )
    for e in data.get("elements", []):
        t = str(e.get("type", "rectangle"))
        allowed_types = (
            ENRICHED_TYPES if bbox_format == "source-px-xywh" else ALLOWED_TYPES
        )
        if t not in allowed_types:
            continue
        if use_evidence:
            box, box_provenance = resolve_bbox(
                e.get("bbox"),
                CoordinateSpaceDecision(x_scale, y_scale, evidence_scales.label),
                image_w,
                image_h,
                ink_scorer,
            )
        elif bbox_format == "source-px-xywh":
            box = _source_px_box(
                e.get("bbox"),
                image_w,
                image_h,
                x_scale=x_scale,
                y_scale=y_scale,
            )
            box_provenance = "legacy-heuristic"
        else:
            box = _norm_box(e.get("bbox"), image_w, image_h)
            box_provenance = "normalized-xyxy"
        if box is None:
            continue
        element = {
            "bbox": box,
            "type": t,
            "text": str(e.get("text", "")),
            "coordinateSpace": box_provenance,
        }
        for field in (
            "controlType",
            "controlValue",
            "controlState",
            "placeholder",
            "state",
            "value",
        ):
            if e.get(field) is not None:
                element[field] = e.get(field)
        out["elements"].append(element)
    out["tables"] = []
    if bbox_format == "source-px-xywh":
        for table in data.get("tables") or []:
            if not isinstance(table, Mapping):
                continue
            if use_evidence:
                box, _table_provenance = resolve_bbox(
                    table.get("bbox"),
                    CoordinateSpaceDecision(
                        x_scale, y_scale, evidence_scales.label
                    ),
                    image_w,
                    image_h,
                    ink_scorer,
                )
            else:
                box = _source_px_box(
                    table.get("bbox"),
                    image_w,
                    image_h,
                    x_scale=x_scale,
                    y_scale=1.0,
                )
            if box is None:
                continue
            headers = [
                str(value).strip()
                for value in table.get("header_texts") or []
                if str(value).strip()
            ]
            rows = [
                [str(cell).strip() for cell in row]
                for row in table.get("rows") or []
                if isinstance(row, (list, tuple))
            ]
            out["tables"].append(
                {
                    "name": str(table.get("name") or "Table"),
                    "bbox": box,
                    "header_texts": headers,
                    "columns": [
                        str(value).strip()
                        for value in table.get("columns") or headers
                    ],
                    "rows": rows,
                }
            )
    try:
        from src.app.services.structure.image_enrichment.parsing import (
            parse_enrichment_response,
        )

        enrichment = parse_enrichment_response(raw, image_w, image_h)
        if use_evidence or x_scale > 1.0 or y_scale > 1.0:
            decision_for_boxes = CoordinateSpaceDecision(
                x_scale, y_scale, coordinate_space["provenance"]
            )

            def _rescale(box: list) -> list | None:
                if use_evidence:
                    resolved, _provenance = resolve_bbox(
                        box,
                        decision_for_boxes,
                        image_w,
                        image_h,
                        ink_scorer,
                    )
                    return resolved
                return _source_px_box(
                    box,
                    image_w,
                    image_h,
                    x_scale=x_scale,
                    y_scale=y_scale,
                )

            for asset in enrichment["assets"]:
                box = asset.get("bbox")
                if isinstance(box, list) and len(box) == 4:
                    asset["bbox"] = _rescale(box)
            for background in enrichment["backgrounds"]:
                box = background.get("bbox")
                if isinstance(box, list) and len(box) == 4:
                    background["bbox"] = _rescale(box)
                for overlay in background.get("overlays") or []:
                    box = overlay.get("bbox")
                    if isinstance(box, list) and len(box) == 4:
                        overlay["bbox"] = _rescale(box)
        out["assets"] = enrichment["assets"]
        out["backgrounds"] = enrichment["backgrounds"]
        out["enrichmentDiagnostics"] = enrichment["diagnostics"]
    except ValueError:
        out["assets"] = []
        out["backgrounds"] = []
        out["enrichmentDiagnostics"] = []
    out["coordinateSpace"] = coordinate_space
    return out


PROMPT = (
    "你是 UI 结构标注器。给定网页截图，输出 JSON："
    '{"containers": [{"bbox": [x,y,x2,y2], "role": "banner|nav|card|panel"}], '
    '"elements": [{"bbox": [x,y,x2,y2], "type": "button|input|text|link|image", '
    '"text": "可见文字"}]}。'
    "bbox 用 0~1 归一化比例坐标（左上原点），禁止使用像素绝对值；"
    "容器是布局区块（顶栏/侧边栏/卡片/面板），"
    "元素是容器内可交互控件或独立文字。只输出合法 JSON。"
    "bbox 坐标是 0~1 的归一化比例（相对你实际看到的那张图），禁止使用像素绝对值；左上原点。"
)


class GroundingVLM(GroundingBackend):
    def __init__(
        self,
        cfg: "Config",
        *,
        runtime: GroundingReliability | None = None,
        client_factory: Callable[[str, float], Any] | None = None,
    ) -> None:
        self.cfg = cfg
        self.endpoints = tuple(
            getattr(cfg, "vision_base_urls", ())
            or (getattr(cfg, "vision_base_url", ""),)
        )
        self._runtime = runtime or get_grounding_runtime(cfg)
        self._client_factory = client_factory or self._openai_client
        self.last_report = None
        self.last_request_metadata: dict[str, Any] = {}
        self.last_coordinate_space: dict[str, Any] | None = None

    def ground(self, image_path: str, image_w: int, image_h: int) -> dict:
        image_bytes = Path(image_path).read_bytes()
        max_image_bytes = int(
            getattr(self.cfg, "vision_max_image_bytes", 25 * 1024 * 1024)
        )
        if len(image_bytes) > max_image_bytes:
            raise GroundingRequestError(
                "input-too-large",
                f"Grounding image exceeds {max_image_bytes} bytes",
            )
        b64 = base64.b64encode(image_bytes).decode()
        messages = [
            {"role": "system", "content": "只输出 JSON，不要 markdown 代码块。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            },
        ]

        def invoke(endpoint: str) -> tuple[dict, dict[str, Any]]:
            client = self._client_factory(
                endpoint,
                float(self.cfg.vision_timeout),
            )
            request_kwargs: dict[str, Any] = {
                "model": self.cfg.vision_model,
                "messages": messages,
                "temperature": float(
                    getattr(self.cfg, "vision_temperature", 0.1)
                ),
                "response_format": {"type": "json_object"},
            }
            if bool(getattr(self.cfg, "vision_send_seed", False)):
                request_kwargs["seed"] = int(
                    getattr(self.cfg, "vision_seed", 20261108)
                )
            resp = client.chat.completions.create(**request_kwargs)
            raw = resp.choices[0].message.content or ""
            max_response_bytes = int(
                getattr(self.cfg, "vision_max_response_bytes", 5 * 1024 * 1024)
            )
            if len(raw.encode("utf-8")) > max_response_bytes:
                raise GroundingRequestError(
                    "response-too-large",
                    f"Grounding response exceeds {max_response_bytes} bytes",
                )
            try:
                parsed = parse_vlm_json(
                    raw, image_w, image_h, image_path=image_path
                )
            except (json.JSONDecodeError, ValueError) as exc:
                raise GroundingRequestError(
                    "response-invalid",
                    "Grounding response is not valid structure JSON",
                ) from exc
            return parsed, _usage_dict(getattr(resp, "usage", None))

        invocation = self._runtime.run(
            image_bytes=image_bytes,
            prompt=PROMPT,
            invoke=invoke,
        )
        self.last_report = invocation.report
        self.last_coordinate_space = (
            invocation.value.get("coordinateSpace")
            if isinstance(invocation.value, Mapping)
            else None
        )
        return invocation.value

    def ground_with_prompt(
        self,
        image_path: str,
        image_w: int,
        image_h: int,
        prompt: str,
        *,
        strategy_id: str = "grounding-tile",
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        """Ground one tile with a caller-supplied coordinate prompt."""

        image_bytes = Path(image_path).read_bytes()
        max_image_bytes = int(
            getattr(self.cfg, "vision_max_image_bytes", 25 * 1024 * 1024)
        )
        if len(image_bytes) > max_image_bytes:
            raise GroundingRequestError(
                "input-too-large",
                f"Grounding image exceeds {max_image_bytes} bytes",
            )
        b64 = base64.b64encode(image_bytes).decode()
        messages = [
            {"role": "system", "content": "只输出 JSON，不要 markdown 代码块。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            },
        ]

        def invoke(endpoint: str) -> tuple[dict, dict[str, Any]]:
            client = self._client_factory(
                endpoint,
                float(self.cfg.vision_timeout),
            )
            request_kwargs: dict[str, Any] = {
                "model": self.cfg.vision_model,
                "messages": messages,
                "temperature": float(
                    getattr(self.cfg, "vision_temperature", 0.1)
                ),
                "response_format": {"type": "json_object"},
            }
            if bool(getattr(self.cfg, "vision_send_seed", False)):
                request_kwargs["seed"] = int(
                    getattr(self.cfg, "vision_seed", 20261108)
                )
            resp = client.chat.completions.create(**request_kwargs)
            raw = resp.choices[0].message.content or ""
            max_response_bytes = int(
                getattr(self.cfg, "vision_max_response_bytes", 5 * 1024 * 1024)
            )
            if len(raw.encode("utf-8")) > max_response_bytes:
                raise GroundingRequestError(
                    "response-too-large",
                    f"Grounding response exceeds {max_response_bytes} bytes",
                )
            bbox_format = str(
                (metadata or {}).get("bbox_format") or "normalized-xyxy"
            )
            try:
                parsed = parse_vlm_json(
                    raw,
                    image_w,
                    image_h,
                    bbox_format=bbox_format,
                    image_path=image_path,
                )
            except (json.JSONDecodeError, ValueError) as exc:
                error = GroundingRequestError(
                    "response-invalid",
                    "Grounding response is not valid structure JSON",
                )
                error.raw_response = raw
                raise error from exc
            return parsed, _usage_dict(getattr(resp, "usage", None))

        invocation = self._runtime.run(
            image_bytes=image_bytes,
            prompt=prompt,
            invoke=invoke,
        )
        self.last_report = invocation.report
        self.last_coordinate_space = (
            invocation.value.get("coordinateSpace")
            if isinstance(invocation.value, Mapping)
            else None
        )
        self.last_request_metadata = {
            "strategy_id": str(strategy_id),
            **dict(metadata or {}),
        }
        return invocation.value

    def _openai_client(self, endpoint: str, timeout: float) -> OpenAI:
        return OpenAI(
            base_url=endpoint,
            api_key=self.cfg.vision_api_key,
            timeout=timeout,
        )


_RUNTIME_LOCK = threading.Lock()
_RUNTIMES: dict[tuple[Any, ...], GroundingReliability] = {}


def get_grounding_runtime(cfg: "Config") -> GroundingReliability:
    endpoints = tuple(
        getattr(cfg, "vision_base_urls", ()) or (getattr(cfg, "vision_base_url", ""),)
    )
    api_key_fingerprint = hashlib.sha256(
        str(getattr(cfg, "vision_api_key", "") or "").encode("utf-8")
    ).hexdigest()
    request_contract = vision_request_contract(cfg)
    persistent_cache_dir = None
    if bool(getattr(cfg, "vision_persistent_cache", True)):
        raw_dir = str(
            getattr(cfg, "vision_persistent_cache_dir", ".vision_cache")
        )
        candidate = Path(raw_dir)
        persistent_cache_dir = (
            candidate
            if candidate.is_absolute()
            else Path(__file__).resolve().parents[5] / candidate
        )
    key = (
        endpoints,
        str(getattr(cfg, "vision_model", "")),
        str(getattr(cfg, "vision_cache_namespace", "default")),
        int(getattr(cfg, "vision_max_attempts", 3)),
        int(getattr(cfg, "vision_retry_base_ms", 250)),
        int(getattr(cfg, "vision_max_backoff_ms", 4000)),
        float(getattr(cfg, "vision_jitter_ratio", 0.25)),
        int(getattr(cfg, "vision_breaker_failure_threshold", 3)),
        float(getattr(cfg, "vision_breaker_cooldown_seconds", 30)),
        int(getattr(cfg, "vision_cache_max_entries", 64)),
        float(getattr(cfg, "vision_cache_ttl_seconds", 300)),
        api_key_fingerprint,
        hashlib.sha256(canonical(request_contract).encode("utf-8")).hexdigest(),
        str(persistent_cache_dir or ""),
    )
    with _RUNTIME_LOCK:
        runtime = _RUNTIMES.get(key)
        if runtime is None:
            runtime = GroundingReliability(
                endpoints=endpoints,
                model=str(getattr(cfg, "vision_model", "")),
                cache_namespace=str(getattr(cfg, "vision_cache_namespace", "default")),
                max_attempts=int(getattr(cfg, "vision_max_attempts", 3)),
                retry_base_ms=float(getattr(cfg, "vision_retry_base_ms", 250)),
                max_backoff_ms=float(getattr(cfg, "vision_max_backoff_ms", 4000)),
                jitter_ratio=float(getattr(cfg, "vision_jitter_ratio", 0.25)),
                breaker_failure_threshold=int(
                    getattr(cfg, "vision_breaker_failure_threshold", 3)
                ),
                breaker_cooldown_seconds=float(
                    getattr(cfg, "vision_breaker_cooldown_seconds", 30)
                ),
                cache_max_entries=int(getattr(cfg, "vision_cache_max_entries", 64)),
                cache_ttl_seconds=float(getattr(cfg, "vision_cache_ttl_seconds", 300)),
                request_contract=request_contract,
                persistent_cache_dir=persistent_cache_dir,
            )
            _RUNTIMES[key] = runtime
        return runtime


def _usage_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        value = usage.model_dump()
        return dict(value) if isinstance(value, Mapping) else {}
    if isinstance(usage, Mapping):
        return dict(usage)
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    return {
        field: value
        for field in fields
        if (value := getattr(usage, field, None)) is not None
    }
