# -*- coding: utf-8 -*-
"""精准复刻 Agent：capture -> 路由 -> provider -> PageGraph -> SoM -> DesignSpec -> 渲染。

实现层策略（显式 route 即主处理方向，仅 auto 做回退）：
- dom       : DOM 真实结构 -> computed style 规则直出 DesignSpec；
- grounding : VLM 看图输出结构候选；image MVP 再从截图像素确定性生成 DesignSpec；
- cv        : OmniParser/EasyOCR 输出候选，复用同一确定性 image MVP 呈现层。
"""

from __future__ import annotations
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from src.app.services.structure.graph import assign_ids, assign_parent_depth, save_graph
from src.app.services.structure.image_contract import (
    inspect_image_reference,
    recover_image_region_candidates,
    recover_image_text_candidates,
)
from src.app.services.structure.router import (
    grounding_fallback_reason,
    route_order,
)
from src.app.services.structure.providers.base import ProviderContext
from src.app.services.som.annotate import annotate_som
from src.app.version import app_version

if TYPE_CHECKING:
    from src.app.services.delivery.runtime_delivery import DeliveryAcceptance

logger = logging.getLogger(__name__)


def _build_provider(cfg, route):
    from src.app.services.structure.providers.dom import DomProvider
    from src.app.services.structure.providers.grounding import GroundingProvider
    from src.app.services.structure.providers.cv import CVProvider

    # dom 无参构造；grounding/cv 需要 cfg
    if route == "dom":
        return DomProvider()
    if route == "grounding":
        return GroundingProvider(cfg)
    return CVProvider(cfg)


_PAGE_SLUG_LIMIT = 40


def _slug(text: str, *, fallback: str = "page") -> str:
    """页名 -> 子目录名用的安全 slug：中英文数字与 `-_` 原样保留，其余折叠成 `_`。"""
    chars = [ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(text or "")]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return (slug or fallback)[:_PAGE_SLUG_LIMIT]


def page_name_for(
    index: int,
    *,
    url: str | None = None,
    title: str | None = None,
    image: str | None = None,
) -> str:
    """一页的页名：`document.title` > URL 路径（含哈希路由）> 文件名 > `Page N`。

    口径见 `归档文档 axure_rp8_plan.md` §3.1：页数由用户输入决定，页名也一样——多页时
    每一页各取自己那个输入的名字，不去网站内容里猜。
    """
    if title and title.strip():
        return title.strip()
    if url:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        segments = [s for s in parsed.path.split("/") if s]
        tail = segments[-1] if segments else ""
        fragment = [s for s in parsed.fragment.split("/") if s]
        # 哈希路由深链（`/index#/a/b`）：path 只有 `index` 时带不了信息，取哈希尾段。
        if fragment and tail.lower() in ("", "index", "index.html", "index.htm"):
            tail = fragment[-1]
        return tail or parsed.netloc or ("Page %d" % (index + 1))
    if image:
        from pathlib import Path

        if Path(image).stem:
            return Path(image).stem
    return "Page %d" % (index + 1)


def _read_json(path):
    """读一个 JSON 文件；不存在 / 坏了就给 None（多页组装时当"这页没这份产物"）。"""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _has_text_elements(design: dict) -> bool:
    """设计里有没有可对齐的文本（`pages` 多页形状与单页形状都认）。

    没有文本就没有基线可调：`_refine_text_baselines` 靠这一步早退，省掉一次"量尺渲染
    + 栅格化"（多页装配时那次渲染还会把量尺 svg 写到页面目录外面，白费一趟）。
    """
    for page in design.get("pages") or [design]:
        for el in page.get("elements") or []:
            if el.get("type") == "text" and str(el.get("text") or "").strip():
                return True
    return False


class PreciseAgent:
    def __init__(self, config) -> None:
        self.config = config

    def run(
        self,
        *,
        url=None,
        image=None,
        route="auto",
        tool="svg",
        pick_crops: bool = False,
        delivery_acceptance: DeliveryAcceptance | None = None,
    ) -> dict:
        route = route or "auto"
        cfg = self.config
        out = cfg.output_dir
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        # Grounding needs the VLM. CV can now feed the deterministic image
        # presentation layer without a second VLM call.
        if route == "grounding" and not cfg.vision_api_key:
            raise ValueError(
                "VISION_API_KEY 未配置：路线 " + route + " 需要多模态模型做结构枚举"
            )

        requested_route = route
        page_state = None
        capture_meta = None
        screenshot_only = False
        capture_fallbacks = []
        if url:
            from src.app.services.structure.capture import (
                PAGE_STATE_CONTENT,
                PageAccessError,
                capture_page_with_fallback,
                page_access_error_message,
            )

            cap = capture_page_with_fallback(
                url,
                cfg,
                str(out),
                requested_route=requested_route,
                allow_real_session=(requested_route != "dom"),
            )
            page_state = cap["page_state"]
            if page_state.get("kind") != PAGE_STATE_CONTENT:
                raise PageAccessError(
                    page_access_error_message(
                        page_state, requested_route=requested_route
                    ),
                    state=page_state,
                )
            image, w, h = cap["image"], cap["width"], cap["height"]
            page_title = cap.get("title") or ""  # 多页时当页名用（plan §3.1）
            # auto 的无头采集被拦截、真实会话拿到内容 -> 这次只把截图当输入，
            # 不再用 DOM 直出（DOM 留档仅作诊断）。显式 grounding/cv 保持既有行为。
            screenshot_only = (
                bool(cap.get("screenshot_only")) and requested_route == "auto"
            )
            if screenshot_only:
                ctx = ProviderContext(
                    image_path=image,
                    image_w=w,
                    image_h=h,
                    route="",
                    output_dir=str(out),
                    dom_path=None,
                    url=url,
                )
                input_kind = "image"
            else:
                ctx = ProviderContext(
                    image_path=image,
                    image_w=w,
                    image_h=h,
                    route="",
                    output_dir=str(out),
                    dom_path=cap.get("dom"),
                    url=url,
                )
                input_kind = "url"
            capture_meta = {
                "requested_url": url,
                "final_url": page_state.get("final_url"),
                "page_state": page_state,
                "device_scale_factor": cap.get(
                    "device_scale_factor", cfg.device_scale_factor
                ),
                "viewport": cap.get("viewport")
                or {
                    "width": cfg.playwright_viewport_width,
                    "height": cfg.playwright_viewport_height,
                },
                "canvas_size": [w, h],
                "screenshot_source": page_state.get("screenshot_source"),
                "screenshot_only": screenshot_only,
                "attempts": page_state.get("attempts", []),
            }
            if page_state.get("fallback_used"):
                first_label = (page_state.get("attempts") or [{}])[0].get(
                    "label"
                ) or "headless"
                capture_fallbacks.append(
                    {
                        "from": "capture:" + first_label,
                        "to": "capture:"
                        + str(page_state.get("screenshot_source") or "real_session"),
                        "reason": f"{page_state.get('kind')}: {page_state.get('reason')}",
                    }
                )
        else:
            page_title = ""
            from src.app.utils.image_utils import load_image

            frame = load_image(image)
            h, w = frame.shape[:2]
            ctx = ProviderContext(
                image_path=image, image_w=w, image_h=h, route="", output_dir=str(out)
            )
            input_kind = "image"

        have_dom = bool(ctx.dom_path)
        requested = route if route != "auto" else None
        chain = route_order(input_kind, requested, cfg, have_dom)
        fallbacks, graph = list(capture_fallbacks), None
        strategy_attempts: list[dict] = []
        grounding_report = None
        fallback_observation = None
        image_reference = None
        image_strategy = None
        if input_kind == "image":
            image_reference = inspect_image_reference(image)
            (out / "image_reference.json").write_text(
                json.dumps(image_reference, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if requested is None and not cfg.vision_api_key and chain[0] == "cv":
                strategy_attempts.append(
                    {
                        "strategy": "grounding",
                        "status": "unavailable",
                        "reason": "grounding-config-missing",
                    }
                )
                fallbacks.append(
                    {"from": "grounding", "reason": "grounding-config-missing"}
                )

        for r in chain:
            try:
                provider = _build_provider(cfg, r)
                ctx.route = r
                graph = provider.run(ctx)
                strategy_attempts.append({"strategy": r, "status": "selected"})
                break
            except Exception as exc:
                if grounding_report is None and getattr(exc, "report", None) is not None:
                    report = exc.report
                    grounding_report = (
                        report.to_dict()
                        if hasattr(report, "to_dict")
                        else dict(report)
                    )
                if requested:
                    raise
                if input_kind == "image" and r == "grounding":
                    reason = grounding_fallback_reason(exc)
                    if reason is None:
                        raise
                    strategy_attempts.append(
                        {
                            "strategy": r,
                            "status": "unavailable",
                            "reason": reason,
                        }
                    )
                    fallbacks.append({"from": r, "reason": reason})
                    continue
                strategy_attempts.append(
                    {
                        "strategy": r,
                        "status": "failed",
                        "reason": str(exc),
                    }
                )
                fallbacks.append({"from": r, "reason": str(exc)})
        if graph is None:
            raise RuntimeError(
                "auto 全部路线失败: " + json.dumps(fallbacks, ensure_ascii=False)
            )

        if image_reference is not None:
            from src.app.services.observability.fallback_metrics import (
                build_fallback_observation,
            )

            if grounding_report is None:
                reliability = (
                    graph.get("provenance", {}).get("grounding_reliability")
                )
                if isinstance(reliability, dict):
                    grounding_report = reliability
            fallback_observation = build_fallback_observation(
                requested_route=requested_route,
                selected_route=graph["route"],
                attempts=strategy_attempts,
                grounding_report=grounding_report,
            )
            (out / "fallback_observability.json").write_text(
                json.dumps(
                    fallback_observation,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            image_strategy = {
                "requested": requested_route,
                "selected": graph["route"],
                "attempts": strategy_attempts,
                "fallback_used": any(
                    attempt.get("status") == "unavailable"
                    for attempt in strategy_attempts[:-1]
                ),
                "policy": "grounding-default-cv-only-when-unavailable",
                "observability": fallback_observation,
            }

        ocr_supplement = None
        image_region_recovery = None
        if image_reference is not None:
            graph, ocr_supplement = recover_image_text_candidates(graph, image)
            (out / "ocr_supplement.json").write_text(
                json.dumps(ocr_supplement, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            graph, image_region_recovery = recover_image_region_candidates(
                graph,
                image,
            )
            (out / "image_region_recovery.json").write_text(
                json.dumps(image_region_recovery, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        assign_ids(graph)
        assign_parent_depth(graph)
        graph["provenance"]["fallbacks"] = fallbacks
        graph["provenance"]["capture"] = capture_meta or {}
        graph["provenance"]["page_state"] = page_state
        graph["provenance"]["requested_route"] = requested_route
        if image_reference is not None and image_strategy is not None:
            graph["provenance"]["input_kind"] = "image"
            graph["provenance"]["reference"] = image_reference
            graph["provenance"]["strategy"] = image_strategy
            if ocr_supplement is not None:
                graph["provenance"]["ocr_supplement"] = {
                    "status": ocr_supplement.get("status"),
                    "source": ocr_supplement.get("source"),
                    "added_count": ocr_supplement.get("added_count"),
                    "observation_count": ocr_supplement.get("observation_count"),
                }
            if image_region_recovery is not None:
                graph["provenance"]["image_region_recovery"] = {
                    "status": image_region_recovery.get("status"),
                    "source": image_region_recovery.get("source"),
                    "added_count": image_region_recovery.get("added_count"),
                }
        save_graph(graph, str(out / "10_pagegraph.json"))
        annotate_som(graph, str(out))

        som_json = json.loads((out / "11_som.json").read_text(encoding="utf-8"))
        # 人工框选的“权威像素区”：--pick-crops 在采集后弹出框选窗口（写 manual_crops.json），
        # 之后只要该文件在输出目录里就自动重放（无头、可复现，见 som/crop_picker.py）。
        self._pick_crops_if_needed(pick_crops, image, out, graph["route"])
        # url 命中站点 profile 时注入图标语义提示段（仅作提示词辅助，不进 PageGraph/DesignSpec）
        if url:
            from src.app.services.structure.site_profiles import load_profile

            prof = load_profile(url)
            if prof and prof.icon_aria_labels:
                som_json["_profile_hints"] = prof.hint_text()
        effective_route = "screenshot" if screenshot_only else graph["route"]
        screenshot_backend = graph["route"] if screenshot_only else None
        self._design_and_render(
            som_json,
            image=image,
            url=url,
            tool=tool,
            out=out,
            t0=t0,
            route=graph["route"],
            fallbacks=fallbacks,
            title=page_title,
            extra_manifest={
                "requested_route": requested_route,
                "effective_route": effective_route,
                "screenshot_backend": screenshot_backend,
                "screenshot_only": screenshot_only,
                "page_state": page_state,
                "capture": capture_meta,
                "input_kind": input_kind,
                **(
                    {
                        "imageMVP": {
                            "presentation": (
                                f"{graph['route']}-pixel-sampled-fixed-coordinate"
                            ),
                            "reference_id": image_reference["reference_id"],
                            "strategy": image_strategy,
                            "fallback_observability": fallback_observation,
                            "ocr_supplement": {
                                "status": ocr_supplement.get("status"),
                                "source": ocr_supplement.get("source"),
                                "added_count": ocr_supplement.get("added_count"),
                            },
                        },
                        "ocr_supplement": {
                            "status": ocr_supplement.get("status"),
                            "source": ocr_supplement.get("source"),
                            "added_count": ocr_supplement.get("added_count"),
                            "observation_count": ocr_supplement.get(
                                "observation_count"
                            ),
                        },
                        "image_region_recovery": {
                            "status": image_region_recovery.get("status"),
                            "source": image_region_recovery.get("source"),
                            "added_count": image_region_recovery.get("added_count"),
                        },
                    }
                    if image_reference is not None
                    else {}
                ),
            },
            counts={
                "containers": len(graph["containers"]),
                "elements": len(graph["elements"]),
            },
            delivery_acceptance=delivery_acceptance,
            image_contract=(
                {
                    "reference": image_reference,
                    "strategy": image_strategy,
                }
                if image_reference is not None and image_strategy is not None
                else None
            ),
        )
        return graph

    def rerender(
        self,
        *,
        tool="svg",
        pick_crops: bool = False,
        delivery_acceptance: DeliveryAcceptance | None = None,
    ) -> dict:
        """不重新采集：用输出目录里已有的 11_som.json + 截图重跑直出与渲染。

        配合 --pick-crops 做快速迭代（改框选 → 立刻看新稿），不必再等一次抓取。
        """
        out = self.config.output_dir
        som_path = out / "11_som.json"
        if not som_path.exists():
            raise FileNotFoundError(f"输出目录里没有 {som_path}：先跑一次采集再重渲染")
        som_json = json.loads(som_path.read_text(encoding="utf-8"))
        image = som_json.get("image")
        url = None
        title = ""
        manifest_path = out / "manifest.json"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                url = manifest.get("url")
                title = manifest.get("title") or ""
            except Exception:  # noqa: BLE001 - 旧 manifest 坏了不影响重渲染
                manifest = {}
                url = None
        route = (som_json.get("provenance") or {}).get("route") or "dom"
        self._pick_crops_if_needed(pick_crops, image, out, route)
        containers = som_json.get("containers") or []
        elements = som_json.get("elements") or []
        extra = {
            key: manifest.get(key)
            for key in (
                "requested_route",
                "effective_route",
                "screenshot_backend",
                "screenshot_only",
                "page_state",
                "capture",
            )
            if key in manifest
        }
        provenance = som_json.get("provenance") or {}
        image_contract = None
        if provenance.get("input_kind") == "image":
            image_contract = {
                "reference": provenance.get("reference"),
                "strategy": provenance.get("strategy"),
            }
        return self._design_and_render(
            som_json,
            image=image,
            url=url,
            tool=tool,
            out=out,
            t0=time.time(),
            route=route,
            fallbacks=[],
            title=title,
            extra_manifest=extra,
            counts={"containers": len(containers), "elements": len(elements)},
            delivery_acceptance=delivery_acceptance,
            image_contract=image_contract,
        )

    def run_many(
        self, *, urls=(), images=(), route="auto", tool="svg", pick_crops: bool = False
    ) -> dict:
        """多输入 -> 多页（`归档文档 axure_rp8_plan.md` §3.1）：N 个 URL / N 张不同界面截图
        -> N 页，**每个输入一页**（URL 的 DOM 各自独立，不需要对齐）。

        **1 个输入仍走老的单页扁平路径**（`run()`），产物形状与以前逐字节相同；只有真的
        给了多个输入，才组装 `{"pages": [...]}` 并让输出端一次写多页。

        做法沿用产品里既有的合成方式（见 `scripts/compare_routes.py`）：每页在
        `<output_dir>/page_NN_<名>/` 里各跑一遍完整单页链路（各页的 00_dom / 11_som /
        12_design 都留档，可单独复核），再把各页的 `12_design.json` 组装进一份多页设计，
        交给输出端渲染一次。返回组装后的设计（单输入时就是那一页的扁平设计）。

        截图侧「同一页面不同区域 -> 合并成 1 页」的判定与合并属于 VLM 路线的要求，
        本版不做（§3.1 的待定开口）。
        """
        urls = [u for u in urls if u]
        images = [p for p in images if p]
        inputs = [("url", u) for u in urls] + [("image", p) for p in images]
        if not inputs:
            raise ValueError("多页输入至少需要一个 --url 或 --image")
        if len(inputs) == 1:
            kind, value = inputs[0]
            self.run(
                url=value if kind == "url" else None,
                image=value if kind == "image" else None,
                route=route,
                tool=tool,
                pick_crops=pick_crops,
            )
            return json.loads(
                (self.config.output_dir / "12_design.json").read_text(encoding="utf-8")
            )

        self._require_pages_support(tool)
        cfg = self.config
        out = cfg.output_dir
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        pages, records = [], []
        for index, (kind, value) in enumerate(inputs):
            page, record = self._build_page(
                index, kind, value, route=route, tool=tool, pick_crops=pick_crops
            )
            pages.append(page)
            records.append(record)

        design = {"pages": pages}
        (out / "12_design.json").write_text(
            json.dumps(design, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        from src.app.controllers.rendering_controller import RenderingController

        RenderingController(cfg).render(design, tool)
        manifest = {
            "version": app_version(),
            "route": route,
            "requested_route": route,
            "tool": tool,
            "inputs": {"urls": urls, "images": images},
            "pages": records,
            "seconds": round(time.time() - t0, 1),
        }
        (out / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        logger.info(
            "多输入 -> %d 页：%s",
            len(pages),
            " | ".join(str(page.get("name")) for page in pages),
        )
        return design

    def _build_page(
        self, index: int, kind: str, value: str, *, route, tool, pick_crops: bool
    ) -> tuple[dict, dict]:
        """跑一页：子目录里走完整单页链路，读回它的 `12_design.json` 组装 `pages` 的一项。"""
        from dataclasses import replace

        url = value if kind == "url" else None
        image = value if kind == "image" else None
        sub = self.config.output_dir / (
            "page_%02d_%s"
            % (index + 1, _slug(page_name_for(index, url=url, image=image)))
        )
        PreciseAgent(replace(self.config, output_dir=sub)).run(
            url=url, image=image, route=route, tool=tool, pick_crops=pick_crops
        )
        manifest = _read_json(sub / "manifest.json") or {}
        # `document.title` 只有采集时才拿得到：有它就用它当页名（§3.1 的页名口径）。
        name = page_name_for(index, url=url, image=image, title=manifest.get("title"))
        design = _read_json(sub / "12_design.json") or {}
        canvas = design.get("canvas") or {}
        elements = design.get("elements") or []
        page = {
            "name": name,
            "canvas": canvas,
            "elements": elements,
            "sources": [value],
        }
        record = {
            "index": index + 1,
            "name": name,
            "dir": sub.name,
            "sources": [value],
            "route": manifest.get("route"),
            "requested_route": manifest.get("requested_route"),
            "effective_route": manifest.get("effective_route"),
            "page_state": manifest.get("page_state"),
            "canvas": canvas,
            "elements": len(elements),
        }
        return page, record

    def _require_pages_support(self, tool: str) -> None:
        """多页只对支持 `pages` 的输出端开放（当前 = axure）：宁可明确报错，别静默叠成一页。"""
        from src.app.services.rendering import build_adapter

        try:
            adapter = build_adapter(tool, self.config)
        except Exception:  # noqa: BLE001 - 造不出适配器（如 figma 缺依赖）= 不支持
            adapter = None
        if adapter is None or not getattr(adapter, "supports_pages", False):
            raise ValueError(
                "多输入 -> 多页需要支持 pages 的输出端，--tool %s 不支持"
                "（当前仅 axure）；请去掉多余的输入，或改用 --tool axure" % tool
            )

    def _pick_crops_if_needed(self, pick_crops, image, out, route) -> None:
        """--pick-crops：弹出框选窗口，结果写 <out>/manual_crops.json（仅 grounding/cv）。

        有头窗口里按 d 可以叠看“当前直出稿”（prototype.svg 先栅格化成 render.png），
        直接看出缺了什么。这一步是给只有像素的 grounding/cv 兜底：它们判断不了
        “这是图标还是文字”，只能由人框出来。dom 路线不需要——Playwright 拿到了真实
        DOM，图标（iconBox / class 带 icon / type=icon / role=img）与图片（img/svg/
        背景图）在 provider 里已经自动判出并按原图像素回填，弹窗只会要求用户去框
        机器本来就知道的东西。
        """
        if not pick_crops:
            return
        if route == "dom":
            logger.warning(
                "--pick-crops 已跳过：dom 路线能从 DOM 标识自动判出图标与图片"
                "（iconBox / class 带 icon / role=img），无需人工框选"
            )
            return
        from pathlib import Path
        from src.app.services.som.crop_picker import pick_crops as _pick_crops

        render, svg = Path(out) / "render.png", Path(out) / "prototype.svg"
        if not render.exists() and svg.exists():
            try:
                from src.app.utils.svg_raster import rasterize_svg

                rasterize_svg(
                    svg,
                    render,
                    device_scale_factor=self.config.device_scale_factor,
                )
            except Exception as exc:  # noqa: BLE001 - 对照层只是辅助，失败不影响框选
                logger.warning("直出稿栅格化失败（不影响框选）：%s", exc)
        _pick_crops(
            image,
            str(Path(out) / "manual_crops.json"),
            render_path=str(render) if render.exists() else None,
        )

    def _refine_text_baselines(self, design, image, out, tool) -> None:
        """±1px 文本基线微调（**只对 svg 输出端**）：渲染一遍 → 与截图逐元素比 → 只改明确变好的元素。

        经验公式（`y + h/2 + 0.375em`）在绝大多数文本元素上正好命中浏览器那一行，
        少数元素会整体差 1px；文本是高频细笔画，差 1px 整行抗锯齿就全变。这里用
        "这次复刻的目标像素"（原截图）逐个判断该不该拨 1px（见 text_align.py）。
        与 P4 像素底同思路（截图即目标像素），但只做 ±1px 整数对齐、不替换像素。
        结果写回 12_design.json 的 `y`。

        **只对 svg 生效，别扩到别的输出端**：这个位移是拿"SVG 栅格图 vs 截图"比出来的，
        而各输出端有各自的文字落点（Axure 的文字面板贴控件角、基线偏移与 SVG 公式不同），
        同一个位移套过去只会更差 —— 真机 dushu 首页同一份 IR：axure 0.887（不套）
        vs 0.922（套上那 5 个位移）；svg 侧则是 0.442（套）。所以非 svg 直接跳过。
        """
        if not self.config.text_align or not image:
            return
        if tool != "svg":
            return
        shot, svg = Path(image), Path(out) / "prototype.svg"
        if not shot.exists() or not _has_text_elements(design):
            return
        try:
            from src.app.controllers.rendering_controller import RenderingController
            from src.app.services.rendering.text_align import align_text_baselines
            from src.app.utils.svg_raster import rasterize_svg

            render = Path(out) / "render.png"
            if not svg.exists():
                # 还没有量尺就先渲一份（多页装配等路径可能没渲过画布之外的 svg）
                from dataclasses import replace

                RenderingController(
                    replace(self.config, delivery_profile="legacy")
                ).render(design, "svg")
            rasterize_svg(
                svg,
                render,
                device_scale_factor=self.config.device_scale_factor,
            )
            stats = align_text_baselines(
                design,
                shot,
                render,
                device_scale_factor=self.config.device_scale_factor,
            )
        except Exception as exc:  # noqa: BLE001 - 附加优化不拖垮主流程
            logger.warning("文本基线微调跳过：%s", exc)
            return
        design.setdefault("_meta", {})["text_align"] = stats
        if not stats.get("changed"):
            return
        (Path(out) / "12_design.json").write_text(
            json.dumps(design, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        try:
            from dataclasses import replace

            RenderingController(replace(self.config, delivery_profile="legacy")).render(
                design, "svg"
            )
            rasterize_svg(
                svg,
                render,
                device_scale_factor=self.config.device_scale_factor,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("文本基线微调后重渲染失败：%s", exc)

    def _design_and_render(
        self,
        som_json,
        *,
        image,
        url,
        tool,
        out,
        t0,
        route,
        counts,
        fallbacks,
        title: str | None = None,
        extra_manifest: dict | None = None,
        delivery_acceptance: DeliveryAcceptance | None = None,
        image_contract: dict | None = None,
    ) -> dict:
        """设计 → 贴像素底 → 回填像素 → 渲染 → 写 manifest（采集与重渲染共用）。返回 DesignSpec。"""
        cfg = self.config
        from src.app.utils.image_utils import load_image as _li
        from src.app.services.llm.llm_service import generate_som_design
        from src.app.services.som.direct_design import (
            build_direct_design,
            try_build_direct_design,
        )

        # 链路分流：实际解析为 dom -> 恒定 computed style 规则直出（不调 VLM，
        # 样式覆盖不足也直接规则拼装，不回落模型）；grounding/cv -> SoM -> VLM 语义生成。
        # 直出只看路线（dom 恒定直出），没有配置开关可关。
        # 站点 profile（site_profiles/<host>.json）只覆盖经验阈值；url 同时写回
        # provenance，rerender 等下游就不必再各自去找 manifest。
        from src.app.services.structure.site_profiles import load_profile

        profile = load_profile(url) if url else None
        som_json.setdefault("provenance", {})
        if url:
            som_json["provenance"].setdefault("url", url)
        # Auto Layout 施工图要 DOM 父子关系（pIdx）与布局字段，都在采集产物里；
        # 缺（老目录、非 dom 路线）就整条链路不动，输出与以前逐字节相同。
        capture_meta = (som_json.get("provenance") or {}).get("capture") or {}
        if image_contract is None:
            capture_meta.setdefault("device_scale_factor", cfg.device_scale_factor)
            capture_meta.setdefault(
                "viewport",
                {
                    "width": cfg.playwright_viewport_width,
                    "height": cfg.playwright_viewport_height,
                },
            )
        screenshot_only = bool(capture_meta.get("screenshot_only"))
        dom_nodes = None
        dom_path = out / "00_dom.json"
        if dom_path.exists() and not screenshot_only:
            try:
                dom_nodes = json.loads(dom_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):  # noqa: PERF203 - 坏文件不影响出稿
                dom_nodes = None
        image_ir = None
        if image_contract is not None:
            from src.app.services.structure.image_contract import (
                build_image_design,
                build_image_ir,
            )

            design = build_image_design(
                som_json,
                image_contract["reference"],
                sample_id=str((image_contract["reference"].get("reference_id") or "")),
            )
            image_ir = build_image_ir(
                som_json,
                design,
                image_contract["reference"],
                image_contract["strategy"],
            )
        else:
            design = try_build_direct_design(som_json, profile, dom_nodes)
            if design is None and route == "dom":
                logger.warning(
                    "DOM 路线 computed style 覆盖不足，仍按规则直出（不回落 VLM）"
                )
                design = build_direct_design(som_json, profile, dom_nodes)
            if design is None:
                if not cfg.vision_api_key:
                    raise ValueError(
                        "VISION_API_KEY 未配置：grounding/cv 的 DesignSpec 生成需要多模态模型密钥"
                    )
                from src.app.utils.image_utils import encode_image_base64

                b64 = encode_image_base64(_li(image))
                design = generate_som_design(som_json, b64, cfg, output_dir=str(out))
        # 人工框选的“权威像素区”（manual_crops.json，与路线无关）：按原图像素 1:1 裁图
        # 贴成像素底、被它完全盖住的图元丢弃（见 design_crops.apply_crops_to_design）。
        from src.app.services.som.crop_picker import load_manual_crops
        from src.app.services.som.design_crops import (
            apply_crops_to_design,
            backfill_design_image_crops,
        )

        added = apply_crops_to_design(
            design, image, load_manual_crops(out / "manual_crops.json")
        )
        if added:
            logger.info("人工框选像素底 %d 块已贴上（manual_crops.json）", added)
        # 无论直出还是 VLM 生成，image/avatar 元素按原截图裁剪回填真实像素
        backfill_design_image_crops(design, image)
        if bool(getattr(cfg, "dom_network_asset_recovery", False)) and route == "dom":
            from src.app.services.structure.network_asset_recovery import (
                recover_network_assets,
            )

            recovery = recover_network_assets(
                design,
                page_url=url or "",
                output_dir=out,
            )
            design = recovery.pop("design")
        from src.app.services.structure.capture_asset_ledger import (
            build_asset_ledger,
            update_capture_bundle_assets,
        )

        asset_ledger = build_asset_ledger(design)
        (out / "00_assets.json").write_text(
            json.dumps(asset_ledger, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if (out / "00_capture_bundle.json").is_file():
            update_capture_bundle_assets(
                out,
                asset_manifest="00_assets.json",
                asset_counts=asset_ledger,
            )
        (out / "12_design.json").write_text(
            json.dumps(design, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        if image_ir is not None:
            (out / "image_ir.json").write_text(
                json.dumps(image_ir, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        from src.app.controllers.rendering_controller import RenderingController

        capture_sidecar = None
        if cfg.delivery_profile == "contract-v2":
            from src.app.services.evidence.adapter import adapt_capture

            capture_sidecar = adapt_capture(out)
        delivery_bundle = RenderingController(cfg).render(
            design,
            tool,
            capture_sidecar=capture_sidecar,
            acceptance=delivery_acceptance,
        )
        self._refine_text_baselines(design, image, out, tool)

        meta = design.get("_meta") or {}
        manifest = {
            "version": app_version(),
            "route": route,
            "url": url,
            "image": image,
            "tool": tool,
            "title": title or "",
            "seconds": round(time.time() - t0, 1),
            "fallbacks": fallbacks,
            "counts": counts,
            "delivery": {
                "profile": cfg.delivery_profile,
                "trace_id": (
                    delivery_bundle.trace_id if delivery_bundle is not None else None
                ),
            },
            "design": {
                "mode": meta.get("mode", "single"),
                "calls": meta.get("calls", 1),
                "rounds": meta.get("rounds", 1),
                "coverage": meta.get("coverage", 1.0),
                "expected": meta.get("expected", 0),
                "returned": meta.get("returned", 0),
            },
        }
        for key, value in (extra_manifest or {}).items():
            if key != "fallbacks":
                manifest[key] = value
        if image_contract is not None:
            manifest["input_kind"] = "image"
            manifest["imageMVP"] = {
                "presentation": f"{route}-pixel-sampled-fixed-coordinate",
                "reference_id": image_contract["reference"]["reference_id"],
                "reference_sha256": image_contract["reference"]["input"]["sha256"],
                "strategy": image_contract["strategy"],
                "flow": "candidate-fixed-coordinate",
                "asset_claim": "display-replacement-only",
                "original_asset_claimed": False,
            }
        (out / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return design
