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
                  overlay: bool = False, z_index: int = 0) -> None:
    graph["containers"].append({"id": None, "bbox": [int(v) for v in bbox], "role": role,
                                "depth": 0, "parent": None, "elements": [],
                                "confidence": float(confidence), "source": source,
                                "overlay": bool(overlay), "zIndex": int(z_index or 0),
                                "style": dict(style) if style else {}})


def add_element(graph: dict, bbox: list[int], type_: str = "rectangle", text: str = "",
                role: str = "", source: str = "", confidence: float = 1.0,
                style: dict | None = None, overlay: bool = False,
                z_index: int = 0, aria_label: str = "", title: str = "") -> None:
    graph["elements"].append({"id": None, "bbox": [int(v) for v in bbox], "type": type_,
                              "text": text or "", "role": role, "container": None,
                              "confidence": float(confidence), "source": source,
                              "overlay": bool(overlay), "zIndex": int(z_index or 0),
                              "ariaLabel": aria_label or "", "title": title or "",
                              "style": dict(style) if style else {}})


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
