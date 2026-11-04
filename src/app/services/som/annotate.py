# -*- coding: utf-8 -*-
"""Set-of-Mark 双编号标注器：容器 C1..（粗框/深度色），元素 1..（细框 + 角标）。"""

from __future__ import annotations
import json
import os
import cv2

from src.app import tuning

DEPTH_COLORS = {0: (255, 200, 0), 1: (0, 200, 0), 2: (0, 160, 255), 3: (200, 0, 255)}


def _draw_label(img, text, x, y):
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thick = tuning.SOM_ANNOTATE_SCALE, tuning.SOM_ANNOTATE_THICK
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    x0, y0 = max(0, x - 2), max(0, y - th - 4)
    cv2.rectangle(img, (x0, y0), (x0 + tw + 4, y0 + th + 4), (30, 30, 30), -1)
    cv2.putText(
        img,
        text,
        (x0 + 2, y0 + th - 2),
        font,
        scale,
        (255, 255, 255),
        thick,
        cv2.LINE_AA,
    )


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
    som = {
        "image": graph["image"],
        "size": [graph["image_w"], graph["image_h"]],
        "containers": [
            {
                "id": c["id"],
                "bbox": c["bbox"],
                "depth": c["depth"],
                "parent": c["parent"],
                "elements": c["elements"],
                # Auto Layout 施工图靠它把图元归回 DOM 父子关系；
                # 上游 PageGraph 已经带了，SoM 这一层不能丢。
                **(
                    {"domIndex": int(c["domIndex"])}
                    if isinstance(c.get("domIndex"), int)
                    else {}
                ),
                "overlay": bool(c.get("overlay", False)),
                "zIndex": int(c.get("zIndex") or 0),
                "style": c.get("style") or {},
                **({"contentRef": c["contentRef"]} if c.get("contentRef") else {}),
                **(
                    {"sceneOwnerId": c["sceneOwnerId"]} if c.get("sceneOwnerId") else {}
                ),
                # 祖先裁剪矩形：滚动/隐藏容器（如 antd 横向滚动表格）
                # 会把滚出可视区的后代裁掉，输出端据此裁边
                **({"clip": c["clip"]} if c.get("clip") else {}),
                # 图层面板可读名（采集端已算好），没有就不写
                **({"name": c["name"]} if c.get("name") else {}),
                **({"clipToBounds": True} if c.get("clipToBounds") else {}),
                **({"overflowX": c["overflowX"]} if c.get("overflowX") else {}),
                **({"overflowY": c["overflowY"]} if c.get("overflowY") else {}),
                **({"clientWidth": c["clientWidth"]} if c.get("clientWidth") else {}),
                **(
                    {"clientHeight": c["clientHeight"]} if c.get("clientHeight") else {}
                ),
                **({"scrollWidth": c["scrollWidth"]} if c.get("scrollWidth") else {}),
                **(
                    {"scrollHeight": c["scrollHeight"]} if c.get("scrollHeight") else {}
                ),
            }
            for c in graph["containers"]
        ],
        "elements": [
            {
                "id": e["id"],
                "bbox": e["bbox"],
                "text": e["text"],
                **(
                    {"domIndex": int(e["domIndex"])}
                    if isinstance(e.get("domIndex"), int)
                    else {}
                ),
                "ariaLabel": e.get("ariaLabel", ""),
                "title": e.get("title", ""),
                "placeholder": e.get("placeholder", ""),
                "alt": e.get("alt", ""),
                "type": e["type"],
                **({"source": e["source"]} if e.get("source") else {}),
                **(
                    {"confidence": float(e["confidence"])}
                    if e.get("confidence") is not None
                    else {}
                ),
                **({"authority": e["authority"]} if e.get("authority") else {}),
                **({"verified": bool(e["verified"])} if "verified" in e else {}),
                **(
                    {"imageMVPTextStatus": e["imageMVPTextStatus"]}
                    if e.get("imageMVPTextStatus")
                    else {}
                ),
                "interactable": e["type"] not in ("text", "image"),
                "container": e["container"],
                "overlay": bool(e.get("overlay", False)),
                "zIndex": int(e.get("zIndex") or 0),
                **({"contentRef": e["contentRef"]} if e.get("contentRef") else {}),
                **(
                    {"sceneOwnerId": e["sceneOwnerId"]} if e.get("sceneOwnerId") else {}
                ),
                **(
                    {"sceneParentId": e["sceneParentId"]}
                    if e.get("sceneParentId")
                    else {}
                ),
                **(
                    {"textOwnerRef": e["textOwnerRef"]} if e.get("textOwnerRef") else {}
                ),
                # bbox 取自“文本行框”的元素（混合内容节点）：几何一律按
                # 原图像素取整，这个标记供渲染/诊断侧识别来源
                **({"textLineBox": True} if e.get("textLineBox") else {}),
                # 控件文字的“真实行框”：元素盒只用来画底色/描边，落字位置
                # 由行框决定（见 rendering/adapter_base + providers/dom）
                **({"textBox": e["textBox"]} if e.get("textBox") else {}),
                # 「第一行行框」+ 行数：只有 Axure 出口读它（把控件高
                # 对齐到真实落字位置，见 rendering/axure_adapter）
                **({"textEmBox": e["textEmBox"]} if e.get("textEmBox") else {}),
                **({"textEmLines": e["textEmLines"]} if e.get("textEmLines") else {}),
                **({"textLines": e["textLines"]} if e.get("textLines") else {}),
                **({"richRuns": e["richRuns"]} if e.get("richRuns") else {}),
                **({"clipToBounds": True} if e.get("clipToBounds") else {}),
                **({"overflowX": e["overflowX"]} if e.get("overflowX") else {}),
                **({"overflowY": e["overflowY"]} if e.get("overflowY") else {}),
                **(
                    {"textOverflow": e["textOverflow"]} if e.get("textOverflow") else {}
                ),
                **({"clientWidth": e["clientWidth"]} if e.get("clientWidth") else {}),
                **(
                    {"clientHeight": e["clientHeight"]} if e.get("clientHeight") else {}
                ),
                **({"scrollWidth": e["scrollWidth"]} if e.get("scrollWidth") else {}),
                **(
                    {"scrollHeight": e["scrollHeight"]} if e.get("scrollHeight") else {}
                ),
                **(
                    {"assetIdentity": e["assetIdentity"]}
                    if e.get("assetIdentity")
                    else {}
                ),
                **({"sourceCrop": e["sourceCrop"]} if e.get("sourceCrop") else {}),
                # 图标字形叶子：直出时按 bbox 裁原图像素（与 image 同一条链）
                **({"iconCrop": True} if e.get("iconCrop") else {}),
                # 祖先裁剪矩形（同上）：不带这个信息，滚出容器的列会被
                # 直出画到容器边界外（真实页多出一截“工艺/线别”文字）
                **({"clip": e["clip"]} if e.get("clip") else {}),
                **({"name": e["name"]} if e.get("name") else {}),
                "style": e.get("style") or {},
            }
            for e in graph["elements"]
        ],
        "provenance": graph.get("provenance", {}),
    }
    with open(os.path.join(output_dir, "11_som.json"), "w", encoding="utf-8") as f:
        json.dump(som, f, ensure_ascii=False, indent=1)
    return som
