# -*- coding: utf-8 -*-
"""精准复刻 Agent：capture -> 路由 -> provider -> PageGraph -> SoM -> VLM DesignSpec -> 渲染。"""
from __future__ import annotations
import json, time
from pathlib import Path
from dataclasses import replace

from src.app.services.structure.graph import assign_ids, assign_parent_depth, save_graph
from src.app.services.structure.router import route_order
from src.app.services.structure.providers.base import ProviderContext
from src.app.services.som.annotate import annotate_som


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


class PreciseAgent:
    def __init__(self, config) -> None:
        self.config = config

    def run(self, *, url=None, image=None, route="auto", tool="svg",
            enrich=False, fast=False) -> dict:
        cfg = (replace(self.config, dom_direct_design=True)
               if (fast and route in ("auto", "dom")) else self.config)
        out = cfg.output_dir
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        # DesignSpec 阶段固定走多模态 VLM（call_vlm），无论何路线都需要密钥；
        # 提前校验，避免跑到末尾才失败并留下半套产物。
        if not cfg.vision_api_key:
            raise ValueError("VISION_API_KEY 未配置，DesignSpec 生成需要多模态模型密钥")

        if url:
            from src.app.services.structure.capture import capture_page
            cap = capture_page(url, cfg, str(out))
            image, w, h = cap["image"], cap["width"], cap["height"]
            ctx = ProviderContext(image_path=image, image_w=w, image_h=h,
                                  route="", output_dir=str(out),
                                  dom_path=cap["dom"], url=url)
            input_kind = "url"
        else:
            from src.app.utils.image_utils import load_image
            frame = load_image(image)
            h, w = frame.shape[:2]
            ctx = ProviderContext(image_path=image, image_w=w, image_h=h,
                                  route="", output_dir=str(out))
            input_kind = "image"

        have_dom = bool(ctx.dom_path)
        requested = route if route != "auto" else None
        chain = route_order(input_kind, requested, cfg, have_dom)
        fallbacks, graph = [], None

        for r in chain:
            try:
                provider = _build_provider(cfg, r)
                ctx.route = r
                graph = provider.run(ctx)
                break
            except Exception as exc:
                if requested:
                    raise
                fallbacks.append({"from": r, "reason": str(exc)})
        if graph is None:
            raise RuntimeError("auto 全部路线失败: " + json.dumps(fallbacks, ensure_ascii=False))

        assign_ids(graph)
        assign_parent_depth(graph)
        graph["provenance"]["fallbacks"] = fallbacks
        save_graph(graph, str(out / "10_pagegraph.json"))
        annotate_som(graph, str(out))

        from src.app.utils.image_utils import load_image as _li
        from src.app.services.llm.llm_service import generate_som_design
        from src.app.services.som.direct_design import try_build_direct_design
        som_json = json.loads((out / "11_som.json").read_text(encoding="utf-8"))
        # dom 路线：computed style 已随结构落盘，直接拼 DesignSpec，不必再让 VLM 看图猜色
        design = try_build_direct_design(som_json, cfg)
        if design is None:
            from src.app.utils.image_utils import encode_image_base64
            b64 = encode_image_base64(_li(graph["image"]))
            design = generate_som_design(som_json, b64, cfg, output_dir=str(out))
        (out / "12_design.json").write_text(json.dumps(design, ensure_ascii=False, indent=1),
                                            encoding="utf-8")

        from src.app.controllers.rendering_controller import RenderingController
        RenderingController(cfg).render(design, tool)

        meta = design.get("_meta") or {}
        manifest = {"route": graph["route"], "url": url, "image": image, "tool": tool,
                    "seconds": round(time.time() - t0, 1), "fallbacks": fallbacks,
                    "counts": {"containers": len(graph["containers"]),
                               "elements": len(graph["elements"])},
                    "design": {"mode": meta.get("mode", "single"),
                               "calls": meta.get("calls", 1),
                               "rounds": meta.get("rounds", 1),
                               "coverage": meta.get("coverage", 1.0),
                               "expected": meta.get("expected", 0),
                               "returned": meta.get("returned", 0)}}
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
        return graph
