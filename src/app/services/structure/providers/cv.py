# -*- coding: utf-8 -*-
"""CV 路线：进程内复刻 container_pipeline/run_pipeline 的完整调用序列，容器与元素一并收进 PageGraph。

本模块不修改 container_pipeline 下任何文件，只做导入编排与结果录入。
gestalt/pipeline 调用签名以 container_pipeline/run_pipeline.py 为唯一权威参照
（element 池 = OmniParser 元素 + easyocr 文本；uncontained 取自 gestalt_group 返回）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from src.app.services.structure.graph import (add_container, add_element,
                                              assign_parent_depth, new_graph)
from src.app.services.structure.providers.base import BaseProvider, ProviderContext

if TYPE_CHECKING:
    from src.config import Config


def resolve_container_pipeline_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / "container_pipeline").is_dir():
            return parent
    raise FileNotFoundError("找不到 container_pipeline 目录")


def cv_available() -> bool:
    try:
        resolve_container_pipeline_root()
        return True
    except FileNotFoundError:
        return False


def _resolve_omni(root: Path) -> str:
    cands = [root / "container_pipeline" / "OmniParser" / "OmniParser-master",
             root / "OmniParser" / "OmniParser-master",
             root.parent / "OmniParser" / "OmniParser-master"]
    for c in cands:
        if c.is_dir():
            return str(c)
    return str(cands[0])


def _b64_of(path: str) -> str:
    import base64
    return base64.b64encode(Path(path).read_bytes()).decode()


class CVProvider(BaseProvider):
    name = "cv"

    #: 正式入口走三路物理分权感知。关掉它只用于对照实验：旧链路把 OmniParser 的
    #: `content`（"hamburger"、"star"）当文本写进矩形，正是阶段二消灭的幻觉胶囊。
    #: 旧实现保留为兜底，pyhsical 感知整体抛错时（缺 easyocr、模型不在等）仍能出图。
    USE_PHYSICAL_PERCEPTION = True

    def __init__(self, cfg: "Config | None" = None, *, strict: bool = False) -> None:
        self.cfg = cfg
        # strict 供 --route physical 使用：物理感知失败就报错，不悄悄退回旧链路。
        # 非 strict 保留旧的兜底语义，供 auto/cv 使用。
        self.strict = strict

    def run(self, ctx: ProviderContext) -> dict:
        if self.USE_PHYSICAL_PERCEPTION:
            if self.strict:
                return self._run_physical(ctx)
            try:
                return self._run_physical(ctx)
            except Exception as exc:  # noqa: BLE001 - 旧链路是兜底，不该因它断掉入口
                graph = self._run_legacy(ctx)
                graph.setdefault("provenance", {}).setdefault("fallbacks", []).append(
                    f"physical-perception-failed:{type(exc).__name__}"
                )
                return graph
        return self._run_legacy(ctx)

    def _run_physical(self, ctx: ProviderContext) -> dict:
        """三路分权感知：OCR 出字、OmniParser 出图标、CV 出容器。

        与 ``scripts/physical_prepare.py`` 同一个函数，因此正式入口和评测脚本
        不会产出两套不同的设计稿。
        """
        from src.app.services.structure.physical_perception import build_physical_plan

        url = os.environ.get("OMNIPARSER_URL", "http://127.0.0.1:8000")
        plan, report = build_physical_plan(
            ctx.image_path,
            omniparser_url=url,
            width=ctx.image_w,
            height=ctx.image_h,
        )
        graph = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "physical")
        # 必须把 plan 原样挂成 scenePlan：build_image_design 只有看到它才会走
        # compile_scene_plan_to_design（新编译器 + 成帧）。少了这一行，生产入口
        # 会退回"逐个元素平铺"的老分支——产出没有一帧，五套标尺与容器树全不生效。
        # scripts/physical_prepare.py 一直是挂的，两边必须一致。
        graph["scenePlan"] = plan
        graph["provenance"]["perception"] = report.as_dict()
        for node in plan.get("nodes") or []:
            box = [int(value) for value in node["bbox"]]
            kind = str(node.get("type"))
            if kind == "container":
                add_container(
                    graph,
                    box,
                    role=str(node.get("role") or ""),
                    source="physical:cv",
                )
            elif kind == "text":
                add_element(
                    graph,
                    box,
                    type_="text",
                    text=str(node.get("text") or ""),
                    source="physical:ocr",
                )
            elif kind in ("image", "table"):
                # 图标与表格都进元素池，但**不带语义文字**：caption 只住在图层名里。
                add_element(
                    graph,
                    box,
                    type_="rectangle",
                    text="",
                    source=f"physical:{kind}",
                )
        assign_parent_depth(graph)
        return graph

    def _run_legacy(self, ctx: ProviderContext) -> dict:
        root = resolve_container_pipeline_root()
        cp = root / "container_pipeline"
        omni = _resolve_omni(root)
        # 运行时把 container_pipeline 与 OmniParser 加入 path（仿 run_pipeline 顶部 sys.path 编排）
        sys.path.insert(0, str(cp))
        sys.path.insert(0, omni)

        import cv2
        import easyocr
        from container_borders_v2_4 import detect_boxes as d2

        img_bgr = cv2.imread(ctx.image_path)
        if img_bgr is None:
            raise FileNotFoundError(f"CV provider 无法读取图片: {ctx.image_path}")
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        g = new_graph(ctx.image_path, ctx.image_w, ctx.image_h, "cv")

        # 1) easyocr 文本（先跑，供 v2.4 笔画级文字净化与格式塔元素池使用）
        reader = easyocr.Reader(["ch_sim", "en"], gpu=True)
        texts: list[dict] = []
        for p, t, _c in reader.readtext(img_rgb, text_threshold=0.5):
            x0, y0 = int(p[0][0]), int(p[0][1])
            x1, y1 = int(p[2][0]), int(p[2][1])
            if (x1 - x0) >= 8 and (y1 - y0) >= 6:
                texts.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                              "type": "text", "content": t})
        for t in texts:
            add_element(g, [t["x"], t["y"], t["w"], t["h"]], type_="text",
                        text=t["content"], source="cv:ocr")

        # 2) v2.4 掩膜容器（run_pipeline: d2(img_rgb, text_boxes=[(x0,y0,x1,y1)])["boxes"]）
        tb = [(t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"]) for t in texts]
        v2 = d2(img_rgb, text_boxes=tb)["boxes"]
        for b in v2:
            add_container(g, [b["x"], b["y"], b["w"], b["h"]], role="", source="cv:v2.4")

        # 3) OmniParser GPU 元素（paddle 惰性桩必须在 util.omniparser 导入前安装）
        from pipeline_utils import _install_paddleocr_stub, extract_box_lines_hv
        _install_paddleocr_stub()
        from gestalt_group import gestalt_group, refine_groups, resolve_overlaps
        from util.omniparser import Omniparser

        cfg = {"som_model_path": os.path.join(omni, "weights", "icon_detect", "model.pt"),
               "caption_model_name": "florence2",
               "caption_model_path": os.path.join(omni, "weights", "icon_caption_florence"),
               "device": "cuda", "BOX_TRESHOLD": 0.05}
        op = Omniparser(cfg)
        W, H = ctx.image_w, ctx.image_h
        omni_els: list[dict] = []
        for it in op.parse(_b64_of(ctx.image_path))[1]:
            b = it.get("bbox")
            if not b:
                continue
            b = [float(v) for v in b]
            if max(b) <= 1.0 and min(b) >= 0:
                b = [b[0] * W, b[1] * H, b[2] * W, b[3] * H]
            x, y, w, h = int(b[0]), int(b[1]), int(b[2] - b[0]), int(b[3] - b[1])
            content = str(it.get("content", ""))[:20]
            omni_els.append({"x": x, "y": y, "w": w, "h": h,
                             "type": it.get("type"), "content": content})
            add_element(g, [x, y, w, h], type_="rectangle", text=content,
                        source="cv:omniparser")

        # 4) 格式塔分组 + 直线精修（元素池 = omni + texts，与 run_pipeline 第 4 步一致）
        elements = omni_els + texts
        groups, _stats, uncontained = gestalt_group(v2, elements)
        h_mask, v_mask = extract_box_lines_hv(img_bgr, line_len=22)
        for mask in (h_mask, v_mask):
            mask[:3, :] = mask[-3:, :] = mask[:, :3] = mask[:, -3:] = False
        groups = refine_groups(groups, uncontained, h_mask, v_mask, img_bgr.shape)
        groups = resolve_overlaps(groups, v2)
        for grp in groups:
            add_container(g, [grp["x"], grp["y"], grp["w"], grp["h"]],
                          role="", source="cv:gestalt")

        assign_parent_depth(g)
        return g
