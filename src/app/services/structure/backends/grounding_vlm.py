# -*- coding: utf-8 -*-
"""qwen3-vl-plus（OpenAI 兼容）grounding 后端：截图 -> JSON bbox。原生 <|box_start|> 预留。"""
from __future__ import annotations

import base64
import json
import re
from typing import TYPE_CHECKING

from openai import OpenAI

from src.app.services.structure.backends.grounding_base import GroundingBackend

if TYPE_CHECKING:
    from src.config import Config

ALLOWED_TYPES = {"button", "input", "text", "link", "image"}


def _norm_box(b, image_w, image_h):
    try:
        f = [float(v) for v in b]
    except (TypeError, ValueError):
        return None
    if len(f) != 4:
        return None
    x0 = max(0.0, min(f[0], 1.0)); y0 = max(0.0, min(f[1], 1.0))
    x1 = max(0.0, min(f[2], 1.0)); y1 = max(0.0, min(f[3], 1.0))
    px0, py0 = int(round(x0 * image_w)), int(round(y0 * image_h))
    px1, py1 = int(round(x1 * image_w)), int(round(y1 * image_h))
    if px1 - px0 < 2 or py1 - py0 < 2:
        return None
    return [px0, py0, px1 - px0, py1 - py0]


def parse_vlm_json(raw: str, image_w: int, image_h: int) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError("VLM 输出中没有 JSON 对象")
    data = json.loads(m.group(0))
    out = {"containers": [], "elements": []}
    for c in data.get("containers", []):
        box = _norm_box(c.get("bbox"), image_w, image_h)
        if box is None:
            continue
        out["containers"].append({"bbox": box, "role": str(c.get("role", ""))})
    for e in data.get("elements", []):
        t = str(e.get("type", "rectangle"))
        if t not in ALLOWED_TYPES:
            continue
        box = _norm_box(e.get("bbox"), image_w, image_h)
        if box is None:
            continue
        out["elements"].append({"bbox": box, "type": t,
                                "text": str(e.get("text", ""))})
    return out


PROMPT = ("你是 UI 结构标注器。给定网页截图，输出 JSON："
          '{"containers": [{"bbox": [x,y,x2,y2], "role": "banner|nav|card|panel"}], '
          '"elements": [{"bbox": [x,y,x2,y2], "type": "button|input|text|link|image", '
          '"text": "可见文字"}]}。'
          "bbox 用 0~1 归一化比例坐标（左上原点），禁止使用像素绝对值；"
          "容器是布局区块（顶栏/侧边栏/卡片/面板），"
          "元素是容器内可交互控件或独立文字。只输出合法 JSON。"
          "bbox 坐标是 0~1 的归一化比例（相对你实际看到的那张图），禁止使用像素绝对值；左上原点。")


class GroundingVLM(GroundingBackend):
    def __init__(self, cfg: "Config") -> None:
        self.cfg = cfg
        self.client = OpenAI(base_url=cfg.vision_base_url, api_key=cfg.vision_api_key,
                             timeout=cfg.vision_timeout)

    def ground(self, image_path: str, image_w: int, image_h: int) -> dict:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        messages = [
            {"role": "system", "content": "只输出 JSON，不要 markdown 代码块。"},
            {"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]},
        ]
        resp = self.client.chat.completions.create(
            model=self.cfg.vision_model, messages=messages, temperature=0.1,
            response_format={"type": "json_object"})
        return parse_vlm_json(resp.choices[0].message.content or "", image_w, image_h)
