"""离线预演：同底色区域生长，能不能把"整页一块白"切成区域图层。

只读，不改主链。输入是截图 + 已产出的 11_scene_plan.json（要它的文本/图标框），
输出是检出的区域框与一张诊断图。

    python scripts/probe_page_regions.py \
        --image samples/holdout/holdout_worklog.png \
        --plan output/_e_worklog/pipeline/11_scene_plan.json \
        --out output/_regions_worklog.png

三条判据（都不含页面特调）：

1. 生长前景 = 与 ``page_colour`` 色差 <= 6 的像素。色差 >= 8 的（灰缝、1px 分隔线、
   彩色按钮、照片）一律是墙。用页面自己的底色当基准，而不是写死 #ffffff——
   worklog 是纯白，erp 是 #f8f8f8，csdn 又不一样。
2. 连通域之前，把已检出的 OCR 文本框与图标框在掩码上**填回前景**。不填的话，
   卡片里每个字都是一道墙，同一张白卡会被自己的文字戳成一堆碎片。
3. 面积 >= 画布 1.5% 且 矩形度 >= 0.70 才算一个区域。更小的是控件缝隙。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 与页面底色的色差在这个范围内，算"同一块底色"，可以生长。
GROW_TOLERANCE = 6
#: 色差达到这个值就是墙：灰缝、1px 线、彩色控件、照片。
#: 6 与 8 之间只剩抗锯齿的 7，归前景——否则卡片边上会留一圈"既不生长也不隔离"的
#: 真空带，连通域在那里断掉。
BARRIER_TOLERANCE = 8
#: 区域至少要占画布这么多，才配当一层。
MIN_AREA_SHARE = 0.015
#: 孔洞率：真实区域是矩形，贴着字的碎片不是。
MIN_RECTANGULARITY = 0.70
#: 被自己四周包住的异色块，小于画布这个比例的，回填成前景。
#: 侧栏里那张 64px 高的浅蓝卡片、表格的一行行分隔线都属于这一类：它们在**块内**，
#: 不是块与块之间的墙。真正的墙（灰缝、贯穿线）一路通到画布边缘，不会被回填。
MAX_HOLE_SHARE = 0.05
#: 同一跨度上被内容切成两段的区域要接回去：侧栏被一张浅蓝卡片劈成上下两截，
#: 两截的 x 与宽完全一样，中间那道缝是内容不是结构。间隙上限取画布的 6%。
MERGE_GAP_SHARE = 0.06


def dominant_colour(image) -> tuple[int, int, int]:
    """页面真实的底色。

    不能直接用 ``page_colour()``：它按 8 级量化分桶后返回的是**桶号**，纯白 255
    会被答成 248（=#f8f8f8）。分桶只用来找哪一桶最大，颜色取回桶内像素的中位。
    """
    import numpy as np

    flat = image.reshape(-1, 3)
    keys = (flat // 8)[:, 0] * 4096 + (flat // 8)[:, 1] * 64 + (flat // 8)[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    chosen = values[int(counts.argmax())]
    sample = flat[keys == chosen]
    return tuple(int(v) for v in np.median(sample, axis=0))


def load_boxes(plan_path: Path) -> list[tuple[int, int, int, int]]:
    """场景计划里的文本与图标框：这些位置要在掩码上回填。"""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    boxes: list[tuple[int, int, int, int]] = []
    for node in plan.get("nodes", []):
        if node.get("type") not in ("text", "image"):
            continue
        bbox = node.get("bbox") or []
        if len(bbox) < 4:
            continue
        width, height = int(bbox[2]), int(bbox[3])
        if width <= 0 or height <= 0:
            continue
        boxes.append((int(bbox[0]), int(bbox[1]), width, height))
    return boxes


def grow(image_path: Path, boxes, *, page_colour=None, fill_boxes: bool = True):
    """返回 (regions, meta)。regions 已按面积降序。"""
    import cv2
    import numpy as np
    from PIL import Image

    canvas_share = MAX_HOLE_SHARE
    image = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.int16)
    height, width = image.shape[:2]
    if page_colour is None:
        page_colour = dominant_colour(image)
    page = np.asarray(page_colour, dtype=np.int16)

    delta = np.abs(image - page.reshape(1, 1, 3)).max(axis=2)
    # 6 与 8 之间的 7 归前景：那是抗锯齿，不是墙。
    mask = (delta < BARRIER_TOLERANCE).astype(np.uint8)

    if fill_boxes:
        for x, y, w, h in boxes:
            left, top = max(0, x), max(0, y)
            right, bottom = min(width, x + w), min(height, y + h)
            if right <= left or bottom <= top:
                continue
            # 只回填"本来就长在可生长区域里"的字框。压在彩色底板/照片上的字，
            # 回填等于在彩色区里挖出一座孤岛——CSDN 的标题就是这么冒出来的。
            pad = 2
            ry0, ry1 = max(0, top - pad), min(height, bottom + pad)
            rx0, rx1 = max(0, left - pad), min(width, right + pad)
            ring = np.ones((ry1 - ry0, rx1 - rx0), dtype=bool)
            ring[top - ry0 : bottom - ry0, left - rx0 : right - rx0] = False
            if ring.any() and float(mask[ry0:ry1, rx0:rx1][ring].mean()) < 0.5:
                continue
            mask[top:bottom, left:right] = 1

    # 有界孔洞回填：被前景整个包住的异色小块，是块内的内容，不是块间的墙。
    holes = (1 - mask).astype(np.uint8)
    hole_count, hole_labels, hole_stats, _ = cv2.connectedComponentsWithStats(holes, 4)
    limit = canvas_share * width * height
    filled = 0
    for index in range(1, hole_count):
        x, y, w, h, area = (int(v) for v in hole_stats[index])
        if area <= 0 or area > limit:
            continue
        # 只有"横贯或纵贯整个画布"的通道才是墙（灰缝就属于这类：它从头拉到底）。
        # 贴一条边的小块不是墙——侧栏里那张浅蓝卡片就贴着左边缘。
        spans_x = x <= 0 and x + w >= width
        spans_y = y <= 0 and y + h >= height
        if spans_x or spans_y:
            continue
        mask[hole_labels == index] = 1
        filled += 1

    # 4 邻域：8 邻域会从 1px 线的斜角漏过去，灰缝就白设了。
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 4)
    canvas = float(width * height)
    raw = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if area <= 0 or w <= 0 or h <= 0:
            continue
        raw.append(
            {
                "bbox": [x, y, w, h],
                "area": area,
                "share": area / canvas,
                "fill": area / float(w * h),
            }
        )
    kept = [
        region
        for region in raw
        if region["share"] >= MIN_AREA_SHARE and region["fill"] >= MIN_RECTANGULARITY
    ]
    kept.sort(key=lambda item: -item["area"])
    merged, merge_rounds = merge_spans(kept, {"width": width, "height": height})
    kept = merged
    meta = {
        "width": width,
        "height": height,
        "page": "#{:02x}{:02x}{:02x}".format(*(int(v) for v in page)),
        "foreground": float(mask.mean()),
        "raw": len(raw),
        "holesFilled": filled,
        "merged": merge_rounds,
        "kept": len(kept),
    }
    return kept, meta, mask


def merge_spans(regions: list[dict], meta: dict) -> tuple[list[dict], int]:
    """同 x 同宽（或同 y 同高）、间隙很小的两块合成一块。"""
    gap_limit = MERGE_GAP_SHARE * max(meta["height"], meta["width"])
    merged = [dict(region) for region in regions]
    changed = 0
    while True:
        joined = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                a, b = merged[i]["bbox"], merged[j]["bbox"]
                same_x = abs(a[0] - b[0]) <= 2 and abs(a[2] - b[2]) <= 2
                same_y = abs(a[1] - b[1]) <= 2 and abs(a[3] - b[3]) <= 2
                if same_x:
                    gap = max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3])
                    if 0 <= gap <= gap_limit:
                        top = min(a[1], b[1])
                        bottom = max(a[1] + a[3], b[1] + b[3])
                        merged[i] = {
                            "bbox": [a[0], top, a[2], bottom - top],
                            "area": a[2] * (bottom - top),
                            "share": a[2] * (bottom - top) / (meta["width"] * meta["height"]),
                            "fill": 1.0,
                        }
                        merged.pop(j)
                        joined = True
                        break
                if same_y:
                    gap = max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2])
                    if 0 <= gap <= gap_limit:
                        left = min(a[0], b[0])
                        right = max(a[0] + a[2], b[0] + b[2])
                        merged[i] = {
                            "bbox": [left, a[1], right - left, a[3]],
                            "area": a[3] * (right - left),
                            "share": a[3] * (right - left) / (meta["width"] * meta["height"]),
                            "fill": 1.0,
                        }
                        merged.pop(j)
                        joined = True
                        break
            if joined:
                break
        if not joined:
            break
        changed += 1
    merged.sort(key=lambda item: -item["area"])
    return merged, changed


def describe(region: dict, meta: dict) -> str:
    x, y, w, h = region["bbox"]
    width, height = meta["width"], meta["height"]
    tags = []
    if y <= height * 0.12 and w >= width * 0.5:
        tags.append("横贯顶部→header?")
    if x <= width * 0.22 and h >= height * 0.4:
        tags.append("左侧竖条→sidebar?")
    if w >= width * 0.5 and h >= height * 0.3:
        tags.append("主区→main?")
    if h <= height * 0.15 and w >= width * 0.5:
        tags.append("横条→filter-bar?")
    return " ".join(tags) or "—"


def draw(image_path: Path, regions, meta, out_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
    palette = [(255, 0, 0), (0, 128, 255), (0, 170, 0), (200, 0, 200), (255, 150, 0), (0, 0, 0)]
    for index, region in enumerate(regions):
        x, y, w, h = region["bbox"]
        colour = palette[index % len(palette)]
        draw.rectangle((x, y, x + w, y + h), outline=colour, width=3)
        draw.text((x + 6, y + 4), f"#{index + 1} {region['share'] * 100:.1f}%", fill=colour, font=font)
    draw.text((10, meta["height"] - 40), f"page={meta['page']} regions={meta['kept']}", fill=(0, 0, 0), font=font)
    image.save(out_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-fill", action="store_true", help="不回填文字框（对照用）")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    boxes = load_boxes(args.plan)
    regions, meta, _mask = grow(args.image, boxes, fill_boxes=not args.no_fill)
    print(
        f"{args.image.stem}: {meta['width']}x{meta['height']} page={meta['page']} "
        f"框={len(boxes)} 孔洞回填={meta.get('holesFilled', 0)} 合并={meta.get('merged', 0)} 连通域={meta['raw']} 过滤后={meta['kept']}"
    )
    for index, region in enumerate(regions):
        x, y, w, h = region["bbox"]
        print(
            f"  #{index + 1} [{x},{y},{w},{h}] share={region['share'] * 100:5.2f}% "
            f"矩形度={region['fill']:.2f}  {describe(region, meta)}"
        )
    if args.out:
        draw(args.image, regions, meta, args.out)
        print(f"  图：{args.out}")
    if args.json:
        args.json.write_text(
            json.dumps({"meta": meta, "regions": regions}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
