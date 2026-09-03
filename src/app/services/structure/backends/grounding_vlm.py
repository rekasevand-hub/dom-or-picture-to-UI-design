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


def parse_vlm_json(raw: str, image_w: int, image_h: int) -> dict:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError("VLM 输出中没有 JSON 对象")
    data = json.loads(m.group(0))
    out = {"containers": [], "elements": []}
    for c in data.get("containers", []):
        b = c.get("bbox")
        if not b or len(b) != 4:
            continue
        x0 = max(0, min(int(b[0]), image_w)); y0 = max(0, min(int(b[1]), image_h))
        x1 = max(0, min(int(b[2]), image_w)); y1 = max(0, min(int(b[3]), image_h))
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        out["containers"].append({"bbox": [x0, y0, x1 - x0, y1 - y0], "role": str(c.get("role", ""))})
    for e in data.get("elements", []):
        b = e.get("bbox"); t = str(e.get("type", "rectangle"))
        if not b or len(b) != 4 or t not in ALLOWED_TYPES:
            continue
        x0 = max(0, min(int(b[0]), image_w)); y0 = max(0, min(int(b[1]), image_h))
        x1 = max(0, min(int(b[2]), image_w)); y1 = max(0, min(int(b[3]), image_h))
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        out["elements"].append({"bbox": [x0, y0, x1 - x0, y1 - y0], "type": t,
                                "text": str(e.get("text", ""))})
    return out


PROMPT = ("你是 UI 结构标注器。给定网页截图，输出 JSON："
          '{"containers": [{"bbox": [x,y,x2,y2], "role": "banner|nav|card|panel"}], '
          '"elements": [{"bbox": [x,y,x2,y2], "type": "button|input|text|link|image", '
          '"text": "可见文字"}]}。'
          "bbox 用原图像素绝对坐标（左上原点）；容器是布局区块（顶栏/侧边栏/卡片/面板），"
          "元素是容器内可交互控件或独立文字。只输出合法 JSON。")


class GroundingVLM(GroundingBackend):
    def __init__(self, cfg: "Config") -> None:
        self.cfg = cfg
        self.client = OpenAI(base_url=cfg.vision_base_url, api_key=cfg.vision_api_key, timeout=120)

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
