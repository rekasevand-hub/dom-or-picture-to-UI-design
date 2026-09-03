"""几何/位置相关工具函数。"""
from __future__ import annotations


def snap_to_grid(value: int, grid: int = 4) -> int:
    """把坐标/尺寸按 grid 取整，减少随机漂移。"""
    return grid * round(value / grid)


def box_overlap_ratio(
    bbox: tuple[int, int, int, int],
    red_boxes: list[tuple[int, int, int, int]],
) -> float:
    """
    计算 bbox 与所有红框的最大重叠比例。

    使用 intersection_area / component_area（组件被红框覆盖的比例），
    这样即使红框很大、组件很小，只要组件主要落在红框内就会被过滤。
    """
    cx1, cy1, cw, ch = bbox
    cx2, cy2 = cx1 + cw, cy1 + ch
    comp_area = cw * ch
    if comp_area <= 0:
        return 0.0

    best = 0.0
    for rx, ry, rw, rh in red_boxes:
        rx2, ry2 = rx + rw, ry + rh
        inter_w = max(0, min(cx2, rx2) - max(cx1, rx))
        inter_h = max(0, min(cy2, ry2) - max(cy1, ry))
        inter_area = inter_w * inter_h
        best = max(best, inter_area / comp_area)
    return best
