# -*- coding: utf-8 -*-
"""PageGraph：三路结构提供器的统一中间结构。坐标一律 (x,y,w,h) 原图像素整数。"""
from __future__ import annotations

import json


def new_graph(image: str, image_w: int, image_h: int, route: str,
              provenance: dict | None = None) -> dict:
    return {"image": image, "image_w": image_w, "image_h": image_h, "route": route,
            "containers": [], "elements": [],
            "provenance": provenance or {"route": route, "fallbacks": [], "warnings": []}}


def add_container(graph: dict, bbox: list[int], role: str = "", source: str = "",
                  confidence: float = 1.0, style: dict | None = None,
                  overlay: bool = False, z_index: int = 0,
                  clip: list[int] | None = None, name: str = "",
                  dom_index: int | None = None) -> None:
    """加一个容器；clip 是“祖先裁剪矩形”（overflow ≠ visible 的祖先边界，
    见 capture.DOM_JS），输出端据此把内容裁到容器内。
    dom_index 记「这个容器来自采集数组里的第几个节点」，供 Auto Layout 侧按 DOM
    父子关系归组；None（grounding/cv 与旧调用）时不写，产物逐字节不变。"""
    c = {"id": None, "bbox": [int(v) for v in bbox], "role": role,
         "depth": 0, "parent": None, "elements": [],
         "confidence": float(confidence), "source": source,
         "overlay": bool(overlay), "zIndex": int(z_index or 0),
         "style": dict(style) if style else {}}
    if clip:
        c["clip"] = [int(v) for v in clip]
    if name:
        c["name"] = name
    if dom_index is not None:
        c["domIndex"] = int(dom_index)
    graph["containers"].append(c)


def add_element(graph: dict, bbox: list[int], type_: str = "rectangle", text: str = "",
                role: str = "", source: str = "", confidence: float = 1.0,
                style: dict | None = None, overlay: bool = False,
                z_index: int = 0, aria_label: str = "", title: str = "",
                placeholder: str = "", alt: str = "",
                text_line_box: bool = False, icon_crop: bool = False,
                text_box: list[int] | None = None,
                text_em_box: list[int] | None = None, text_em_lines: int = 0,
                text_lines: list[dict] | None = None,
                asset_identity: dict | None = None,
                source_crop: dict | None = None,
                clip: list[int] | None = None, name: str = "",
                dom_index: int | None = None) -> None:
    """加一个元素；text_line_box 标记 bbox 取自“文本行框”（按像素用、不 snap）；
    icon_crop 标记“图标字形叶子”（直出时按 bbox 裁原图像素，与 image 同一条回填链）；
    clip 是“祖先裁剪矩形”（overflow ≠ visible 的祖先边界），输出端据此裁边。
    dom_index 同 add_container：元素来自哪个采集节点，供 Auto Layout 归组。
    text_em_box / text_em_lines 是采集到的「第一行行框 + 行数」，只给输出端
    对齐落字位置用（见 rendering/axure_adapter），没有就不写。"""
    el = {"id": None, "bbox": [int(v) for v in bbox], "type": type_,
          "text": text or "", "role": role, "container": None,
          "confidence": float(confidence), "source": source,
          "overlay": bool(overlay), "zIndex": int(z_index or 0),
          "ariaLabel": aria_label or "", "title": title or "",
          "placeholder": placeholder or "", "alt": alt or "",
          "style": dict(style) if style else {}}
    if text_line_box:
        el["textLineBox"] = True
    if text_box:
        # 控件文字的“真实行框”：元素盒画底色/描边、行框决定落字位置（见 adapter_base）
        el["textBox"] = [int(v) for v in text_box]
    if text_em_box:
        # 「第一行行框 + 行数」：输出端据此把控件高对齐到真实落字位置
        # （见 rendering/axure_adapter）；缺字段时不出，别的输出端逐字节不变。
        el["textEmBox"] = [int(v) for v in text_em_box]
        el["textEmLines"] = int(text_em_lines)
    if text_lines:
        el["textLines"] = [
            {
                "text": str(line.get("text") or ""),
                "box": [int(v) for v in (line.get("box") or [])],
            }
            for line in text_lines
            if isinstance(line, dict) and str(line.get("text") or "").strip()
        ]
    if asset_identity:
        el["assetIdentity"] = dict(asset_identity)
    if source_crop:
        el["sourceCrop"] = dict(source_crop)
    if icon_crop:
        el["iconCrop"] = True
    if clip:
        el["clip"] = [int(v) for v in clip]
    if name:
        el["name"] = name
    if dom_index is not None:
        el["domIndex"] = int(dom_index)
    graph["elements"].append(el)


def _cx(e: dict) -> tuple[float, float]:
    x, y, w, h = e["bbox"]
    return x + w / 2.0, y + h / 2.0


def contains(outer: dict, inner: dict) -> bool:
    x1, y1, w1, h1 = outer["bbox"]
    x2, y2, w2, h2 = inner["bbox"]
    return (x1 <= x2 and y1 <= y2 and x1 + w1 >= x2 + w2 and y1 + h1 >= y2 + h2
            and (w1 > w2 or h1 > h2))   # 严格包含（父更大）


def iou(a: list[int], b: list[int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _reading_key(item: dict) -> tuple[int, int]:
    x, y, w, h = item["bbox"]
    return (y, x)   # 上→下、左→右


def assign_ids(graph: dict) -> None:
    graph["containers"].sort(key=_reading_key)
    graph["elements"].sort(key=_reading_key)
    for i, c in enumerate(graph["containers"], 1):
        c["id"] = f"C{i}"
    for i, e in enumerate(graph["elements"], 1):
        e["id"] = i
    for e in graph["elements"]:
        cands = [c for c in graph["containers"]
                 if contains(c, e) and c["bbox"][2] * c["bbox"][3] > 0]
        if cands:
            e["container"] = min(cands, key=lambda c: c["bbox"][2] * c["bbox"][3])["id"]
    # 容器只列“直接挂在它下面”的元素（元素挂最小包含容器；祖先可经 bbox 遍历）
    for c in graph["containers"]:
        c["elements"] = [e["id"] for e in graph["elements"] if e["container"] == c["id"]]


def assign_parent_depth(graph: dict) -> None:
    for c in graph["containers"]:
        c["depth"], c["parent"] = 0, None
    for a in graph["containers"]:
        cands = [b for b in graph["containers"] if b is not a and contains(b, a)]
        if cands:
            p = min(cands, key=lambda b: b["bbox"][2] * b["bbox"][3])
            a["parent"] = p["id"]
            a["depth"] = p["depth"] + 1


def save_graph(graph: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=1)


def load_graph(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
