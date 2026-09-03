# -*- coding: utf-8 -*-
"""Set-of-Mark 双编号标注器：容器 C1..（粗框/深度色），元素 1..（细框 + 角标）。"""
from __future__ import annotations
import json, os
import cv2

DEPTH_COLORS = {0: (255, 200, 0), 1: (0, 200, 0), 2: (0, 160, 255), 3: (200, 0, 255)}

def _draw_label(img, text, x, y):
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thick = 0.5, 1
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    x0, y0 = max(0, x - 2), max(0, y - th - 4)
    cv2.rectangle(img, (x0, y0), (x0 + tw + 4, y0 + th + 4), (30, 30, 30), -1)
    cv2.putText(img, text, (x0 + 2, y0 + th - 2), font, scale, (255, 255, 255), thick, cv2.LINE_AA)

def annotate_som(graph: dict, output_dir: str) -> dict:
    from src.app.services.structure.graph import assign_ids
    assign_ids(graph)
    img = cv2.imread(graph["image"])
    if img is None:
        raise FileNotFoundError("无法读取截图: %s" % graph["image"])
    board = img.copy()
    for c in graph["containers"]:
        x, y, w, h = c["bbox"]
        color = DEPTH_COLORS.get(c["depth"] % 4, (255, 255, 255))
        cv2.rectangle(board, (x, y), (x + w, y + h), color, 3)
        _draw_label(board, c["id"], x, y)
    for e in graph["elements"]:
        x, y, w, h = e["bbox"]
        cv2.rectangle(board, (x, y), (x + w, y + h), (0, 200, 0), 2)
        _draw_label(board, str(e["id"]), x, y)
    cv2.imwrite(os.path.join(output_dir, "11_som.png"), board)
    som = {"image": graph["image"], "size": [graph["image_w"], graph["image_h"]],
           "containers": [{"id": c["id"], "bbox": c["bbox"], "depth": c["depth"],
                           "parent": c["parent"], "elements": c["elements"]}
                          for c in graph["containers"]],
           "elements": [{"id": e["id"], "bbox": e["bbox"], "text": e["text"],
                         "type": e["type"],
                         "interactable": e["type"] not in ("text", "image"),
                         "container": e["container"]} for e in graph["elements"]],
           "provenance": graph.get("provenance", {})}
    with open(os.path.join(output_dir, "11_som.json"), "w", encoding="utf-8") as f:
        json.dump(som, f, ensure_ascii=False, indent=1)
    return som
