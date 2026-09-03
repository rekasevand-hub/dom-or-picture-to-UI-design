# -*- coding: utf-8 -*-
"""三路 PageGraph 轻量对比指标（无人工标注；dom 可用作参照）。"""
from __future__ import annotations


def container_iou_matrix(a: list[dict], b: list[dict]) -> list[list[float]]:
    from src.app.services.structure.graph import iou
    return [[iou(x["bbox"], y["bbox"]) for y in b] for x in a]


def text_containment_rate(graph: dict) -> float:
    from src.app.services.structure.graph import contains
    els = [e for e in graph["elements"] if e["type"] in ("text", "button", "input", "link")]
    if not els:
        return 0.0
    hit = sum(1 for e in els if any(contains(c, e) for c in graph["containers"]))
    return hit / len(els)


def summarize(graph_a: dict, graph_b: dict) -> dict:
    m = container_iou_matrix(graph_a["containers"], graph_b["containers"])
    best = [max(row) if row else 0.0 for row in m]
    avg = sum(best) / len(best) if best else 0.0
    return {"a": {"route": graph_a["route"], "containers": len(graph_a["containers"]),
                  "elements": len(graph_a["elements"]),
                  "text_containment": round(text_containment_rate(graph_a), 3)},
            "b": {"route": graph_b["route"], "containers": len(graph_b["containers"]),
                  "elements": len(graph_b["elements"]),
                  "text_containment": round(text_containment_rate(graph_b), 3)},
            "avg_best_container_iou_a_vs_b": round(avg, 3)}
