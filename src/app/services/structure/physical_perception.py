"""三路物理分权感知：CV 容器 + OmniParser 图标 + OCR 文本。

全图 VLM 把"这是什么"和"这在哪里"两件事绑在一起，于是图标会被叙述成词
（"hamburger" 变成一枚写着 hamburger 的胶囊），同一块内容被两套描述各写一遍，
而它的坐标精度只到"大概在这儿"。这一层把三件事分开，每件只交给能把它做准的
那一路：

* **OCR** —— 画布上所有 TEXT 节点的唯一来源：字符、基线、墨迹框。
* **OmniParser** —— 图标与原子控件的紧致 BBox 和裁片；它的语义描述
  （`hamburger` / `star`）只写进图层的 `name` 元数据，**绝不生成文本节点**。
* **CV 探针** —— 宏观与中观容器：页面底色、侧栏、顶栏、卡片底板。

输出与 `build_scene_plan` 同构的场景计划，下游（成帧、装饰、防遮挡、2× 仲裁）
一行都不用改。
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.app.services.structure.line_rulers import (
    GUIDE_MIN_SUPPORT,
    GUIDE_SNAP_ENABLED,
    LINE_BANDS_ENABLED,
    ROW_MASTER_ENABLED,
    apply_master,
    bands_from_lines,
    build_guides,
    probe_lines,
    right_aligned_boxes,
    right_aligned_groups,
    row_master,
    snap_boxes,
)

#: 页面底色从边框这一圈取中位数：截图四角常常有圆角或阴影。
PAGE_EDGE_SAMPLE = 3
#: 与页面底色差超过这个值才算"有别的东西画在这儿"。
PAGE_TOLERANCE = 10
#: 小于画布这个比例的连通域不当容器：那是字形、图标、分隔线。
REGION_MIN_SHARE = 0.0035
#: 容器盒子最短边：一条横线不是卡片。
REGION_MIN_SIDE = 18
#: 一个连通域里这个比例已被 OCR 文本框盖住，说明它是一段文字而不是面板。
TEXT_CLUSTER_SHARE = 0.55
#: 颜色量化步长：8 级/通道，足以分开白、浅灰、板岩蓝，又不会被抗锯齿劈碎。
COLOUR_QUANTUM = 8
#: 只看出现最多的这几种颜色。
REGION_COLOURS = 14
#: 连通域占自己外接框的比例：再低就是"一圈边框"而不是"一块面"。
REGION_RECTANGULARITY = 0.55
#: Canny 阈值：低对比 1px 线在 30/90 就出来，高对比阴影不会额外成框。
BORDER_CANNY_LOW = 30
BORDER_CANNY_HIGH = 90
#: 描边盒子的最短边：再小是按钮或图标，交给 OmniParser。
BORDER_MIN_WIDTH = 90
BORDER_MIN_HEIGHT = 28
#: 只装一个词的盒子，要这么宽或这么高才不是表格单元格。
CELL_MIN_WIDTH = 220
CELL_MIN_HEIGHT = 90
#: 四边形占外接框的比例：低于这个值是斜切或残缺轮廓。
BORDER_MIN_FILL = 0.8
#: OmniParser 的图标最大占画布这个比例；更大的框是面板，CV 已经负责了。
ICON_MAX_SHARE = 0.02
#: 图标最短边：再小就不是可点的控件，是噪点。
ICON_MIN_SIDE = 10
#: 两个图标框重到这个 IoU，只留一个。
ICON_DEDUPE_IOU = 0.7
#: 图标框里有这个比例被文字盖住，就交给 OCR，不当图标。
ICON_TEXT_SHARE = 0.5
#: 一个框把某个 OCR 文本框整个装进去，且这个字占框面积这么多：它是"图标+标签"
#: 的一行，不是图标。留着就会在字上盖一张同尺寸的裁片。
ICON_TEXT_INSIDE_SHARE = 0.02
#: 复合框里抠图标：剩余条带、图标边长、宽高比。
SPLIT_ICON_MIN_SIDE = 12
SPLIT_ICON_MAX_SIDE = 32
SPLIT_ICON_MAX_BAND = 56
SPLIT_ICON_MIN_ASPECT = 0.7
SPLIT_ICON_MAX_ASPECT = 1.4
#: 条带里"有墨"的判据：与条带底色差这么多、且占比不低于这个值。
SPLIT_ICON_INK_DELTA = 24
SPLIT_ICON_MIN_INK = 0.04


@dataclass
class PhysicalReport:
    """What each of the three senses contributed, and how long it took."""

    width: int = 0
    height: int = 0
    page_colour: str = ""
    containers: int = 0
    texts: int = 0
    icons: int = 0
    omniparser: str = "skipped"
    seconds: dict[str, float] = field(default_factory=dict)
    rows: int = 0
    tables: int = 0
    lines: int = 0
    guides: int = 0
    masters: int = 0
    illustrations: int = 0
    skeleton: int = 0
    grown: int = 0
    snapped: int = 0
    bands_added: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "physical-perception/1.0",
            "width": self.width,
            "height": self.height,
            "pageColour": self.page_colour,
            "containers": self.containers,
            "rows": self.rows,
            "tables": self.tables,
            "texts": self.texts,
            "icons": self.icons,
            "lines": self.lines,
            "guides": self.guides,
            "masters": self.masters,
            "illustrations": self.illustrations,
            "skeleton": self.skeleton,
            "grown": self.grown,
            "snapped": self.snapped,
            "bandsAdded": self.bands_added,
            "omniparser": self.omniparser,
            "seconds": {key: round(value, 2) for key, value in self.seconds.items()},
            "notes": list(self.notes),
        }


def _load_rgb(image_path: str | Path):
    import numpy as np
    from PIL import Image

    with Image.open(image_path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.int16)


def page_colour(image) -> tuple[int, int, int]:
    """The surface the design sits on: the colour most of the page is.

    The border ring is the wrong place to look — ERP's left edge is the dark
    sidebar, so a ring sample calls the sidebar "the page" and every sidebar
    block disappears from the container probe.  The dominant quantised colour
    is the page by definition (a page is mostly its own background).

    返回的是**真实颜色**，不是量化桶号：纯白 255 落在 248 那个桶里，直接把桶号
    当颜色回报，报告里就写成 #f8f8f8。分桶只用来选哪一桶最大，颜色取回桶内像素
    的中位。注意这**不影响**区域检出——``_region_boxes`` 比的是量化后的颜色，
    那里会自己把 page 折回桶号。
    """
    import numpy as np

    flat = image.reshape(-1, 3)
    quantised = flat // COLOUR_QUANTUM * COLOUR_QUANTUM
    colours, counts = np.unique(quantised, axis=0, return_counts=True)
    chosen = colours[int(np.argmax(counts))]
    sample = flat[np.all(quantised == chosen, axis=1)]
    if sample.size == 0:  # pragma: no cover - 空图才会走到
        return tuple(int(value) for value in chosen)
    return tuple(int(value) for value in np.median(sample, axis=0))


def _region_boxes(image, page, width: int, height: int) -> list[dict[str, Any]]:
    """Flat surfaces, found by colour rather than by "differs from the page".

    A screenshot is a stack of flat fills: the page, the sidebar, the card, the
    well of every input.  Thresholding "not the page colour" merges all of them
    into one blob when the page and the sidebar share a colour (ERP is exactly
    that).  Quantising first and taking one connected component per fill keeps
    them apart, and the rectangles come out at 1px because a flat fill has no
    antialiasing inside it.
    """
    import cv2
    import numpy as np

    quantised = (image // COLOUR_QUANTUM * COLOUR_QUANTUM).astype(np.uint8)
    flat = quantised.reshape(-1, 3)
    colours, counts = np.unique(flat, axis=0, return_counts=True)
    floor = width * height * REGION_MIN_SHARE
    found: list[dict[str, Any]] = []
    for order in np.argsort(-counts)[:REGION_COLOURS]:
        if int(counts[order]) < floor:
            continue
        colour = colours[order]
        mask = np.all(quantised == colour, axis=2).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            x, y, w, h, area = (int(value) for value in stats[index])
            if w < REGION_MIN_SIDE or h < REGION_MIN_SIDE:
                continue
            if w * h < floor:
                continue
            # 空心框（卡片描边）的内孔比很低，不是一块面。
            if area / max(1, w * h) < REGION_RECTANGULARITY:
                continue
            # 和页面同色的区域就是页面本身，不是它上面的一块板。
            # page 现在是真实颜色，比较前折回它所在的桶——不折的话 255 与量化后的
            # 248 永不相等，整张页面会被当成一层板收进来。
            page_bucket = tuple(
                int(value) // COLOUR_QUANTUM * COLOUR_QUANTUM for value in page
            )
            if tuple(int(v) for v in colour) == page_bucket:
                continue
            found.append(
                {
                    "bbox": [max(0, x), max(0, y), min(w, width - x), min(h, height - y)],
                    "fill": "#{:02x}{:02x}{:02x}".format(*(int(v) for v in colour)),
                }
            )
    return found


def _text_coverage(box: Sequence[int], text_boxes: Sequence[Sequence[int]]) -> float:
    """How much of ``box`` is already claimed by OCR text boxes."""
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return 0.0
    covered = 0
    for tx, ty, tw, th in text_boxes:
        width = min(x + w, tx + tw) - max(x, tx)
        height = min(y + h, ty + th) - max(y, ty)
        if width > 0 and height > 0:
            covered += width * height
    return min(1.0, covered / (w * h))


def _classify(box: Sequence[int], width: int, height: int) -> str:
    """What role a region plays, from its shape and where it sits.

    Three outcomes, and the third one used to be unreachable: the big-area
    branch and the fallback both returned "card", so ``panel`` never existed and
    every page was a pile of cards.  A region that covers more than half the
    canvas is the page's main surface, not a card on it.
    """
    x, y, w, h = box
    if w >= width * 0.85 and y <= height * 0.12 and h <= height * 0.25:
        return "header"
    if h >= height * 0.35 and x <= width * 0.3 and w <= width * 0.4:
        return "sidebar"
    if w * h >= width * height * 0.5:
        return "panel"
    return "card"


def probe_bordered_boxes(
    image,
    width: int,
    height: int,
    text_boxes: Sequence[Sequence[int]],
) -> list[dict[str, Any]]:
    """Boxes drawn with a 1px outline: the card, the table, every input well.

    A page whose card and background are both white has no colour boundary to
    find — the only evidence is the stroke.  Contours on a Canny edge map give
    it back at pixel accuracy, and they survive the same test the colour
    regions do: hold at least two words, or be big enough to be a surface.
    """
    import cv2
    import numpy as np

    gray = cv2.cvtColor(image.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, BORDER_CANNY_LOW, BORDER_CANNY_HIGH)
    contours, _hierarchy = cv2.findContours(
        edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    floor = width * height * 0.0012
    candidates: list[tuple[int, int, int, int]] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < floor:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        # 圆角输入框简化出来是 6~8 个点，不是 4 个；只要它填满自己的外接框，
        # 就是个盒子。斜切和残缺轮廓过不了 BORDER_MIN_FILL。
        if not 4 <= len(approx) <= 8:
            continue
        x, y, w, h = cv2.boundingRect(approx)
        if w < BORDER_MIN_WIDTH or h < BORDER_MIN_HEIGHT:
            continue
        if area / max(1, w * h) < BORDER_MIN_FILL:
            continue
        candidates.append((x, y, w, h))
    candidates.sort(key=lambda box: box[2] * box[3], reverse=True)
    kept: list[dict[str, Any]] = []
    canvas = width * height
    for box in candidates:
        if any(_same_box(box, other["bbox"]) for other in kept):
            continue
        inside = sum(
            1
            for text_box in text_boxes
            if box[0] <= text_box[0] + text_box[2] / 2 <= box[0] + box[2]
            and box[1] <= text_box[1] + text_box[3] / 2 <= box[1] + box[3]
        )
        area = box[2] * box[3]
        # 只装一个词的盒子：够宽（输入框的井）或够高（一块面板）才算容器。
        # 表格单元格是 120~170×70 的小方格，一格一个词，交给表格逻辑，不要
        # 变成 40 个容器——那样每格都会去争一个帧。
        single = inside >= 1 and (
            area >= canvas * 0.001 and (box[2] >= CELL_MIN_WIDTH or box[3] >= CELL_MIN_HEIGHT)
        )
        if inside >= 2 or single or area >= canvas * 0.015:
            kept.append({"bbox": list(box), "role": _classify(box, width, height)})
    return kept


#: 同底色骨架：白底页面上，侧栏/顶栏/主卡与页面同色，`_region_boxes` 按"和页面
#: 同色就跳过"把它们全丢了，整页只剩一块被灰缝围出来的内容。这里换一条路——
#: 在"与页面同色"的像素里做连通域生长，灰缝与细线当墙，长出几块就是几块。
PAGE_REGION_SKELETON = True
#: 骨架块至少占画布这么多，才配当一层。
PAGE_REGION_MIN_SHARE = 0.015
#: 矩形度：真实区域是矩形，贴着字的碎片不是。
PAGE_REGION_MIN_RECT = 0.70
#: 被自己四周包住的异色小块（侧栏里的浅蓝卡片、表格的分隔线）回填成前景，
#: 上限是画布的这个比例。横贯/纵贯画布的通道不算，那是墙。
PAGE_REGION_HOLE_SHARE = 0.05
#: 同跨度相邻块合并的间隙上限（画布比例）：侧栏被内容劈成两截时要接回去。
PAGE_REGION_MERGE_GAP = 0.06
#: 间隙里的底色和块外侧底色的容许差：小于它就是"同一种面越过了块边界"，
#: 说明那是页面自己的底色，两块是被页面分开的兄弟。实测：坏合并 4，好合并 21。
PAGE_REGION_GUTTER_TOLERANCE = 8
#: 取块外侧底色时采样的宽度。
PAGE_REGION_GUTTER_EDGE = 16
#: 与页面底色差达到这个值就是墙：灰缝、1px 分隔线、彩色控件、照片。
PAGE_REGION_BARRIER = 8
#: 投影裁剪之后，一条边短于这么多像素的"区域"是细丝，不是一层。
PAGE_REGION_MIN_SIDE = 24


def _page_region_boxes(
    image,
    page: Sequence[int],
    text_boxes: Sequence[Sequence[int]],
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    """Page-coloured blocks before any merge, plus the barrier they were grown in.

    与页面同色的大块：白底页面的侧栏、顶栏、主卡。判据与 ``_region_boxes`` 的
    区别只有一条：那里"与页面同色"意味着"这是页面本身"，这里意味着"这可能是一
    块板，看它被什么围住"。灰缝（色差 >= 8）、1px 分隔线、彩色控件都是墙；块内的
    文字与图标先回填掉，否则一张白卡会被自己的字戳碎。

    """
    import cv2
    import numpy as np

    page_rgb = np.asarray(page, dtype=np.int16)
    delta = np.abs(image - page_rgb.reshape(1, 1, 3)).max(axis=2)
    mask = (delta < PAGE_REGION_BARRIER).astype(np.uint8)

    # 块内的字：只在"四周本来就是可生长区域"时回填。压在彩色底板上的字回填后
    # 会在彩色区里挖出一座孤岛。
    for box in text_boxes:
        if len(box) < 4:
            continue
        x, y, w, h = (int(v) for v in box[:4])
        left, top = max(0, x), max(0, y)
        right, bottom = min(width, x + w), min(height, y + h)
        if right <= left or bottom <= top:
            continue
        pad = 2
        ry0, ry1 = max(0, top - pad), min(height, bottom + pad)
        rx0, rx1 = max(0, left - pad), min(width, right + pad)
        ring = np.ones((ry1 - ry0, rx1 - rx0), dtype=bool)
        ring[top - ry0 : bottom - ry0, left - rx0 : right - rx0] = False
        if ring.any() and float(mask[ry0:ry1, rx0:rx1][ring].mean()) < 0.5:
            continue
        mask[top:bottom, left:right] = 1

    # 有界孔洞回填：块内的异色小块是内容，不是墙。
    holes = (1 - mask).astype(np.uint8)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(holes, 4)
    limit = PAGE_REGION_HOLE_SHARE * width * height
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if area <= 0 or area > limit:
            continue
        if (x <= 0 and x + w >= width) or (y <= 0 and y + h >= height):
            continue
        mask[labels == index] = 1

    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 4)
    canvas = float(width * height)
    regions: list[dict[str, Any]] = []
    for index in range(1, count):
        x, y, w, h, _area = (int(v) for v in stats[index])
        if w <= 0 or h <= 0:
            continue
        # 一条 1px 的白边会把方块吊成 L 形（worklog 的检索条上方就有一条），
        # 于是矩形度 0.57 被拒。按投影强度裁掉"覆盖不到最强行一半"的行/列，
        # 剩下的是这一层真正的矩形；FluxWeaver 那块假区域裁完仍只有 0.52，照旧被拒。
        piece = labels[y : y + h, x : x + w] == index
        rows = piece.mean(axis=1)
        columns = piece.mean(axis=0)
        if rows.size and columns.size and rows.max() > 0 and columns.max() > 0:
            keep_rows = np.where(rows >= 0.5 * rows.max())[0]
            keep_columns = np.where(columns >= 0.5 * columns.max())[0]
            if keep_rows.size and keep_columns.size:
                top, bottom = int(keep_rows.min()), int(keep_rows.max()) + 1
                left, right = int(keep_columns.min()), int(keep_columns.max()) + 1
                if bottom - top >= PAGE_REGION_MIN_SIDE and right - left >= PAGE_REGION_MIN_SIDE:
                    x, y, w, h = x + left, y + top, right - left, bottom - top
                    piece = piece[top:bottom, left:right]
        area = int(piece.sum())
        if area <= 0:
            continue
        share = area / canvas
        if share < PAGE_REGION_MIN_SHARE:
            continue
        if area / float(w * h) < PAGE_REGION_MIN_RECT:
            continue
        regions.append(
            {"bbox": [x, y, w, h], "area": area, "share": share, "fill": area / float(w * h)}
        )
    regions.sort(key=lambda item: -item["area"])
    return regions


def _gutter_is_through(image, first: Sequence[int], second: Sequence[int], axis: str) -> bool:
    """Is the thing between these two blocks the page's own surface?

    Two same-span blocks are either one layer split by a child, or two siblings
    with a gutter.  "Same span, small gap" describes both, so the old code fell
    back on size — skip anything over 40% of the canvas — and that rule both let
    the wrong pairs through and blocked the right ones.

    The difference is visible at the block's own edge, and it is one question:
    *does the thing in the gap stop where these blocks stop?*

    * It stops.  A highlighted menu row (light blue) between two white menu rows
      ends exactly at the rail's edge — a child, so the rail was split by it and
      the halves belong together.  Measured: 21 channels from the surface outside.
    * It does not stop.  The 16px band between a search bar and the content is
      the same grey as the margin beside it — the page showing through, so these
      are two siblings.  Measured: 4 channels.
    A page-wide rule (a divider, a coloured strip) is the same answer as a
    gutter: its colour reaches the blocks' edge and keeps going.

    No area anywhere: the size of the result never enters the decision.
    """
    import numpy as np

    ax, ay, aw, ah = (int(value) for value in first[:4])
    bx, by, bw, bh = (int(value) for value in second[:4])
    edge = PAGE_REGION_GUTTER_EDGE
    if axis == "vertical":
        start, end = min(ay + ah, by + bh), max(ay, by)
        low, high = max(ax, bx), min(ax + aw, bx + bw)
        if end <= start or high <= low:
            return False
        inside = image[start:end, low:high]
        outside = [
            image[start:end, max(0, low - edge) : low] if low > 0 else None,
            image[start:end, high : min(image.shape[1], high + edge)],
        ]
    else:
        start, end = min(ax + aw, bx + bw), max(ax, bx)
        top, bottom = max(ay, by), min(ay + ah, by + bh)
        if end <= start or bottom <= top:
            return False
        inside = image[top:bottom, start:end]
        outside = [
            image[max(0, top - edge) : top, start:end] if top > 0 else None,
            image[bottom : min(image.shape[0], bottom + edge), start:end],
        ]
    if inside.size == 0:
        return False
    hull = np.median(inside.reshape(-1, 3), axis=0)
    seen = 0
    same = 0
    for strip in outside:
        if strip is None or strip.size == 0:
            continue
        seen += 1
        other = np.median(strip.reshape(-1, 3), axis=0)
        if int(np.abs(hull - other).max()) <= PAGE_REGION_GUTTER_TOLERANCE:
            same += 1
    return seen > 0 and same == seen


def page_regions(
    image,
    page: Sequence[int],
    text_boxes: Sequence[Sequence[int]],
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    """与页面同色的大块：白底页面的侧栏、顶栏、主卡。"""
    regions = _page_region_boxes(image, page, text_boxes, width, height)
    canvas = float(width * height)
    regions = _merge_same_span(regions, image, width, height, canvas)

    out: list[dict[str, Any]] = []
    for item in regions:
        x, y, w, h = item["bbox"]
        # 角色沿用 _classify 的那一套词（header / sidebar / panel / card），
        # 不新造 "main-content"：下游按这几个词分支，多一个词只会被当未知角色。
        if y <= height * 0.12 and w >= width * 0.5:
            role = "header"
        elif x <= width * 0.22 and h >= height * 0.4:
            role = "sidebar"
        elif w * h >= canvas * 0.3:
            role = "panel"
        else:
            role = "card"
        out.append({"bbox": [x, y, w, h], "role": role, "fill": None})
    return out


def _merge_same_span(
    regions: list[dict[str, Any]],
    image,
    width: int,
    height: int,
    canvas: float,
) -> list[dict[str, Any]]:
    """同跨度相邻块接回去，但只在不跨过一条贯穿缝的前提下。

    侧栏被一张浅蓝卡片劈成上下两截时，两截 x/宽一模一样，中间是那张卡片；而
    检索条与主区之间是一条 16px 的空缝。两者在"同宽 + 间隙很小"上完全一样，
    差别只在间隙里是什么——所以判据必须看间隙带，而不是看合并后有多大。
    """
    gap_limit = PAGE_REGION_MERGE_GAP * max(width, height)
    merged = True
    while merged:
        merged = False
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                a, b = regions[i]["bbox"], regions[j]["bbox"]
                if abs(a[0] - b[0]) <= 2 and abs(a[2] - b[2]) <= 2:
                    gap = max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3])
                    if 0 <= gap <= gap_limit and not _gutter_is_through(
                        image, a, b, "vertical"
                    ):
                        top = min(a[1], b[1])
                        bottom = max(a[1] + a[3], b[1] + b[3])
                        regions[i] = {
                            "bbox": [a[0], top, a[2], bottom - top],
                            "area": a[2] * (bottom - top),
                            "share": a[2] * (bottom - top) / canvas,
                            "fill": 1.0,
                        }
                        regions.pop(j)
                        merged = True
                        break
                if abs(a[1] - b[1]) <= 2 and abs(a[3] - b[3]) <= 2:
                    gap = max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2])
                    if 0 <= gap <= gap_limit and not _gutter_is_through(
                        image, a, b, "horizontal"
                    ):
                        left = min(a[0], b[0])
                        right = max(a[0] + a[2], b[0] + b[2])
                        regions[i] = {
                            "bbox": [left, a[1], right - left, a[3]],
                            "area": a[3] * (right - left),
                            "share": a[3] * (right - left) / canvas,
                            "fill": 1.0,
                        }
                        regions.pop(j)
                        merged = True
                        break
            if merged:
                break
    regions.sort(key=lambda item: -item["area"])
    return regions


def _same_box(left: Sequence[int], right: Sequence[int]) -> bool:
    """Two measurements of one rectangle — not a box inside a bigger box.

    The first version compared intersection over the smaller area, which calls
    every input well a duplicate of the card it sits in (IoA 1.0), and the card
    disappeared.  Duplicates agree on **both** edges and size; nesting does not.
    """
    overlap_w = min(left[0] + left[2], right[0] + right[2]) - max(left[0], right[0])
    overlap_h = min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1])
    if overlap_w <= 0 or overlap_h <= 0:
        return False
    inter = overlap_w * overlap_h
    left_area = left[2] * left[3]
    right_area = right[2] * right[3]
    if inter / max(1, left_area + right_area - inter) >= 0.85:
        return True
    return (
        inter / max(1, min(left_area, right_area)) >= 0.9
        and min(left_area, right_area) / max(1, max(left_area, right_area)) >= 0.85
    )


def probe_containers(
    image,
    page: Sequence[int],
    width: int,
    height: int,
    text_boxes: Sequence[Sequence[int]],
) -> list[dict[str, Any]]:
    """宏观与中观的盒子：页面上的每一块底板都从像素长出来。

    A region that is almost entirely covered by OCR text boxes is a paragraph,
    not a panel — giving it a container would paint a second background behind
    words that are already sitting on the page.
    """
    boxes = _region_boxes(image, page, width, height)
    kept: list[dict[str, Any]] = []
    for item in boxes:
        box = item["bbox"]
        if _text_coverage(box, text_boxes) >= TEXT_CLUSTER_SHARE:
            continue
        kept.append(
            {
                "bbox": list(box),
                "role": _classify(box, width, height),
                "fill": item["fill"],
            }
        )
    # 描边盒子补上"填充色和页面一样"的那些：白卡、表格区、每个输入框的井。
    for item in probe_bordered_boxes(image, width, height, text_boxes):
        if any(_same_box(item["bbox"], other["bbox"]) for other in kept):
            continue
        kept.append(item)
    # 同一块区域被关闭运算切成两半时，两半都留着；重叠 >85% 的只留大的。
    kept.sort(key=lambda item: item["bbox"][2] * item["bbox"][3], reverse=True)
    unique: list[dict[str, Any]] = []
    for item in kept:
        box = item["bbox"]
        if not any(_same_box(box, other["bbox"]) for other in unique):
            unique.append(item)
    return unique


def _parse_omniparser(payload: Mapping[str, Any], width: int, height: int) -> list[dict[str, Any]]:
    items = payload.get("parsed_content_list") or []
    parsed: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            x1, y1, x2, y2 = (float(value) for value in bbox)
        except (TypeError, ValueError):
            continue
        # OmniParser 输出归一化坐标（0~1），也兼容像素坐标。
        if max(x1, y1, x2, y2) <= 1.5:
            x1, x2 = x1 * width, x2 * width
            y1, y2 = y1 * height, y2 * height
        x, y = int(round(min(x1, x2))), int(round(min(y1, y2)))
        w, h = int(round(abs(x2 - x1))), int(round(abs(y2 - y1)))
        if w < ICON_MIN_SIDE or h < ICON_MIN_SIDE:
            continue
        parsed.append(
            {
                "bbox": [max(0, x), max(0, y), min(w, width - x), min(h, height - y)],
                "caption": str(item.get("content") or "").strip(),
                "interactive": bool(item.get("interactivity")),
                "kind": str(item.get("type") or "icon"),
            }
        )
    return parsed


def _encloses_text(box: Sequence[int], text_boxes: Sequence[Sequence[int]]) -> float:
    """Largest share of this box taken by one OCR text box that sits inside it."""
    x, y, w, h = box
    area = max(1, w * h)
    largest = 0.0
    for tx, ty, tw, th in text_boxes:
        if not (x - 2 <= tx and y - 2 <= ty and tx + tw <= x + w + 2 and ty + th <= y + h + 2):
            continue
        largest = max(largest, (tw * th) / area)
    return largest


def _ink_box(image, box: Sequence[int]) -> list[int] | None:
    """Tight box around the ink inside ``box``, or None when it is empty."""
    import numpy as np

    x, y, w, h = (int(value) for value in box)
    rows, columns = image.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(columns, x + w), min(rows, y + h)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    crop = image[y0:y1, x0:x1]
    background = np.median(crop.reshape(-1, 3), axis=0)
    ink = np.abs(crop - background).max(axis=2) >= SPLIT_ICON_INK_DELTA
    if float(ink.mean()) < SPLIT_ICON_MIN_INK:
        return None
    rows_with = np.where(ink.any(axis=1))[0]
    columns_with = np.where(ink.any(axis=0))[0]
    if not len(rows_with) or not len(columns_with):
        return None
    return [
        x0 + int(columns_with[0]),
        y0 + int(rows_with[0]),
        int(columns_with[-1] - columns_with[0] + 1),
        int(rows_with[-1] - rows_with[0] + 1),
    ]


def _split_side_icons(
    image,
    box: Sequence[int],
    text_boxes: Sequence[Sequence[int]],
) -> list[list[int]]:
    """The small square icon next to a label inside one composite YOLO box.

    A sidebar row is "icon + words": OmniParser boxes the whole row, and using
    that box as a crop prints a picture of the words over the words.  Dropping
    it loses the icon, which is the half worth keeping.  So subtract the text:
    whatever is left on the left (or right) of the label, is near-square and has
    ink, is the icon.
    """
    x, y, w, h = (int(value) for value in box)
    inside = [
        (tx, ty, tw, th)
        for tx, ty, tw, th in text_boxes
        if x - 2 <= tx and y - 2 <= ty and tx + tw <= x + w + 2 and ty + th <= y + h + 2
    ]
    if not inside:
        # 签名是 list[list[int]]，调用处直接 for 它：返回 None 会当场 TypeError。
        return []
    found: list[list[int]] = []
    left_edge = min(tx for tx, _ty, _tw, _th in inside)
    right_edge = max(tx + tw for tx, _ty, tw, _th in inside)
    # 条带贴着**文字**取，不是贴着框边：菜单行的图标紧挨着标签（x≈68~96），
    # 而行框从 x=0 开始，前面那 60px 是缩进，贴边取只会取到一片空白。
    left_span = min(left_edge - x, SPLIT_ICON_MAX_BAND)
    right_span = min((x + w) - right_edge, SPLIT_ICON_MAX_BAND)
    bands = [
        (left_edge - left_span, y, left_span, h),
        (right_edge, y, right_span, h),
    ]
    for band in bands:
        if band[2] < SPLIT_ICON_MIN_SIDE:
            continue
        ink = _ink_box(image, band)
        if ink is None:
            continue
        if not (SPLIT_ICON_MIN_SIDE <= ink[2] <= SPLIT_ICON_MAX_SIDE):
            continue
        if not (SPLIT_ICON_MIN_SIDE <= ink[3] <= SPLIT_ICON_MAX_SIDE):
            continue
        ratio = ink[2] / max(1, ink[3])
        if not (SPLIT_ICON_MIN_ASPECT <= ratio <= SPLIT_ICON_MAX_ASPECT):
            continue
        found.append([ink[0] - 1, ink[1] - 1, ink[2] + 2, ink[3] + 2])
    return found


#: 插画/照片通道：面积窗口。小于下限是图标（OmniParser 管），大于上限是整块背景。
ILLUSTRATION_MIN_SHARE = 0.02
ILLUSTRATION_MAX_SHARE = 0.30
#: 局部方差的窗口与阈值：9px 窗口下 std 超过它就说明这里有结构，不是平涂。
ILLUSTRATION_WINDOW = 9
ILLUSTRATION_STD = 18.0
#: 彩度：插画通常有饱和色，而 UI 底板是灰阶或极浅色。
ILLUSTRATION_CHROMA = 40
#: 组件要填满自己外接框的比例：太稀的是散落的边缘，不是一张图。
ILLUSTRATION_FILL = 0.35
#: 框内可以被文字占掉的上限：超了它是"文字块"，不是插画。
ILLUSTRATION_TEXT_SHARE = 0.15


def probe_illustrations(
    image,
    text_boxes: Sequence[Sequence[int]] = (),
    *,
    covered: Sequence[Sequence[int]] = (),
) -> list[dict[str, Any]]:
    """Illustrations and photographs: the size band no other sense covers.

    OmniParser's detector is trained on icons, so a 200px gift-box illustration
    is simply not in its output — measured on the CSDN page, the largest box it
    returned was 1.6% of the canvas and the illustration was absent entirely. CV
    only produces flat-colour regions, and OCR only produces text. Anything that
    is *pictorial* and bigger than an icon therefore fell through all three.

    This looks for exactly that: a connected patch of pixels that has structure
    (local variance) or colour (chroma), is not covered by text or by an already
    accepted box, and fills enough of its own bounding box to be one object
    rather than scattered edges.
    """
    import cv2
    import numpy as np

    rows, columns = image.shape[:2]
    canvas = float(rows * columns)
    if canvas <= 0:
        return []
    gray = cv2.cvtColor(image.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    window = (ILLUSTRATION_WINDOW, ILLUSTRATION_WINDOW)
    mean = cv2.blur(gray, window)
    mean_sq = cv2.blur(gray * gray, window)
    std = np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))
    channels = image.astype(np.int16)
    chroma = channels.max(axis=2) - channels.min(axis=2)
    busy = ((std > ILLUSTRATION_STD) | (chroma > ILLUSTRATION_CHROMA)).astype(np.uint8)

    # 文字与已确认的图标框不属于插画：抹掉它们，剩下的才可能是图。
    for box in list(text_boxes) + list(covered):
        if len(box) < 4:
            continue
        x, y, w, h = (int(value) for value in box[:4])
        busy[max(0, y - 3) : min(rows, y + h + 3), max(0, x - 3) : min(columns, x + w + 3)] = 0

    busy = cv2.morphologyEx(busy, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(busy, 8)
    found: list[dict[str, Any]] = []
    for index in range(1, count):
        x, y, w, h, area = (int(value) for value in stats[index])
        if w < 24 or h < 24:
            continue
        share = (w * h) / canvas
        if not (ILLUSTRATION_MIN_SHARE <= share <= ILLUSTRATION_MAX_SHARE):
            continue
        if area / float(w * h) < ILLUSTRATION_FILL:
            continue
        crop = image[y : y + h, x : x + w]
        if float(crop.std()) < ILLUSTRATION_STD:
            continue
        text_area = 0.0
        for box in text_boxes:
            if len(box) < 4:
                continue
            tx, ty, tw, th = (int(value) for value in box[:4])
            ix = max(0, min(x + w, tx + tw) - max(x, tx))
            iy = max(0, min(y + h, ty + th) - max(y, ty))
            text_area += ix * iy
        if text_area / float(w * h) > ILLUSTRATION_TEXT_SHARE:
            continue
        found.append({"bbox": [x, y, w, h], "share": round(share, 4)})
    found.sort(key=lambda item: -item["share"])
    return found


def omniparser_icons(
    image_path: str | Path,
    width: int,
    height: int,
    text_boxes: Sequence[Sequence[int]],
    *,
    url: str,
    timeout: float = 120.0,
) -> tuple[list[dict[str, Any]], str]:
    """Icons and atomic controls: tight boxes, tight crops, captions off-canvas.

    The caption is metadata for the layer tree.  It is never turned into words:
    a star drawn on a button is a star, and printing "star" next to it is the
    exact defect this whole layer exists to remove.
    """
    if not url:
        return [], "no-url"
    body = {
        "base64_image": base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    }
    request = urllib.request.Request(
        f"{url.rstrip('/')}/parse",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            payload = json.loads(answer.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return [], f"unavailable: {type(exc).__name__}"
    canvas = width * height
    picture = _load_rgb(image_path)
    icons: list[dict[str, Any]] = []
    for item in _parse_omniparser(payload, width, height):
        x, y, w, h = item["bbox"]
        if item["kind"] == "text":
            # OmniParser 自己那一路 OCR 返回的是字形猜测（"Aach-xlsckA"）。
            # 文字只有一个合法来源，那不是它。
            continue
        if w * h > canvas * ICON_MAX_SHARE:
            continue
        if _text_coverage((x, y, w, h), text_boxes) >= ICON_TEXT_SHARE:
            continue
        # 一个框把成段的字整个装进去了：那是"图标 + 标签"的一行，不是图标。
        # 留着它就会在字上面盖一张同样大的裁片（ERP 的"生产管理"）。但左边那颗
        # 小图标值得留下——把文字从框里减掉，剩下的近方形墨迹就是它。
        if _encloses_text((x, y, w, h), text_boxes) >= ICON_TEXT_INSIDE_SHARE:
            # 只要能装下一段字，就要么切出侧边图标、要么整块丢掉：留着整块就是在
            # 字上盖一张画着同样文字的裁片。
            for piece in _split_side_icons(picture, (x, y, w, h), text_boxes):
                icons.append(
                    {
                        "bbox": piece,
                        "caption": item["caption"],
                        "interactive": item["interactive"],
                        "kind": "icon",
                        "split": True,
                    }
                )
            continue
        duplicate = False
        for other in icons:
            ox, oy, ow, oh = other["bbox"]
            overlap_w = min(x + w, ox + ow) - max(x, ox)
            overlap_h = min(y + h, oy + oh) - max(y, oy)
            if overlap_w <= 0 or overlap_h <= 0:
                continue
            inter = overlap_w * overlap_h
            union = w * h + ow * oh - inter
            if inter / max(1, union) >= ICON_DEDUPE_IOU:
                duplicate = True
                break
        if duplicate:
            continue
        icons.append(item)
    icons.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return icons, "applied"


def _digest(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:16]


def _contains(outer: Sequence[int], inner: Sequence[int], tolerance: int = 0) -> bool:
    return (
        outer[0] - tolerance <= inner[0]
        and outer[1] - tolerance <= inner[1]
        and inner[0] + inner[2] <= outer[0] + outer[2] + tolerance
        and inner[1] + inner[3] <= outer[1] + outer[3] + tolerance
    )


def _overlap_share(left: Sequence[int], right: Sequence[int]) -> float:
    """交集占较小那个框的比例：一个行带落在表格里，就是 1.0。"""
    ax, ay, aw, ah = (int(value) for value in left[:4])
    bx, by, bw, bh = (int(value) for value in right[:4])
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    if ix <= 0 or iy <= 0:
        return 0.0
    return (ix * iy) / max(1, min(aw * ah, bw * bh))


#: 横线检测的 Canny 阈值与霍夫票数：低对比 1px 线在 30/90 上就出来。
SEPARATOR_CANNY_LOW = 30
SEPARATOR_CANNY_HIGH = 90
SEPARATOR_HOUGH_VOTES = 90
#: 霍夫找的是"格子里那一小段"：最短段取 80px，之后按 y 合并成整条线。
SEPARATOR_MIN_SEGMENT = 80
#: 同一 y 上相邻线段间隙小于这个值，就当成同一条线（被竖线切断的格子）。
SEPARATOR_MAX_GAP = 48
#: 线的最短跨度（占页宽的比例，且不低于 160px）。
SEPARATOR_MIN_RUN_SHARE = 0.18
SEPARATOR_MIN_RUN = 160
#: 同一组平行线至少这么多条，才认为它划分出了行带。
SEPARATOR_MIN_LINES = 3
#: 行带高度范围：再矮是线距，再高是整块面板。
ROW_BAND_MIN_HEIGHT = 18
ROW_BAND_MAX_HEIGHT = 200
#: 列簇：至少这么多行，列内左缘的容差。
COLUMN_MIN_ROWS = 3
COLUMN_TOLERANCE = 12
#: 右对齐判据：右缘标准差不超过这么多像素。
ALIGN_RIGHT_STD = 3.0
#: 一串行带升级成 table 的门槛：至少三行、三列，且每列要在八成行里有字。
#: 列表（Gmail）的第一列是头像不是文字，稳定列凑不到三列，因此留在行带这一侧。
TABLE_MIN_ROWS = 3
TABLE_MIN_COLUMNS = 3
TABLE_COLUMN_SUPPORT = 0.8
#: 两条列线之间至少这么宽，否则是在一列里切碎。
TABLE_COLUMN_MIN_GAP = 24
#: 表的宽度下限：比这窄的"表"是一列清单，行带已经够用。
TABLE_MIN_WIDTH = 48
#: 表头带与正文行的底色差超过它，才认为原图真的画了表头带。
TABLE_HEADER_DELTA = 3.0
#: 右缘锚定开关（实验用）。实测见 HANDOFF §28。
ALIGN_RIGHT_ENABLED = True
#: 一个组里至少这么多列，才值得建成 table 节点。
TABLE_MIN_COLUMNS = 3
#: 无框表格至少这么多行。
TABLE_MIN_ROWS = 3


def probe_separators(
    image, width: int, height: int
) -> list[dict[str, Any]]:
    """1px horizontal rules, grouped into parallel families.

    A list draws one hairline per row and nothing else; a grid table draws the
    same hairline **per cell**, broken by its vertical borders.  Both are the
    same fact at different granularity, so the detector works in two steps:
    find short horizontal segments, merge the ones that share a y into one
    logical rule, then group rules that share a span into a family.
    """
    import cv2
    import numpy as np

    if height < 8 or width < 16:
        return []
    gray = cv2.cvtColor(image.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, SEPARATOR_CANNY_LOW, SEPARATOR_CANNY_HIGH)
    segments = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=SEPARATOR_HOUGH_VOTES,
        minLineLength=SEPARATOR_MIN_SEGMENT,
        maxLineGap=6,
    )
    if segments is None:
        return []
    by_row: dict[int, list[tuple[int, int]]] = {}
    for segment in segments:
        # OpenCV 4 returns (N, 1, 4) and OpenCV 5 returns (N, 4): indexing [0]
        # gives four coordinates on the first and one int on the second, so
        # flatten instead of assuming a nesting level.  Without this the whole
        # perception run dies on the OpenCV 5 the tests use, and the physical
        # route only works because the pipeline shell picks the omni env.
        x1, y1, x2, y2 = (int(value) for value in np.asarray(segment).reshape(-1)[:4])
        if abs(y2 - y1) > 1:
            continue
        y = min(y1, y2)
        by_row.setdefault(y, []).append((min(x1, x2), max(x1, x2)))
    # 同一 y 上的多个格子线段先并成一条逻辑线。
    logical: list[tuple[int, int, int]] = []
    for y in sorted(by_row):
        spans = sorted(by_row[y])
        merged: list[list[int]] = []
        for x0, x1 in spans:
            if merged and x0 - merged[-1][1] <= SEPARATOR_MAX_GAP:
                merged[-1][1] = max(merged[-1][1], x1)
            else:
                merged.append([x0, x1])
        # 同一 y 上可能并排着左右两栏各自的线：都留着，各自成族。
        # 只取最长的那条会让窄栏的线消失，那一栏就永远切不出行带。
        minimum = max(SEPARATOR_MIN_RUN, int(width * SEPARATOR_MIN_RUN_SHARE))
        for x0, x1 in merged:
            if x1 - x0 >= minimum:
                logical.append((y, x0, x1))    # 抗锯齿让一条线占两行：y 相邻且跨度相近的并成一条。
    lines: list[tuple[int, int, int]] = []
    for y, x0, x1 in logical:
        if lines and y - lines[-1][0] <= 3 and abs(lines[-1][1] - x0) <= 12 and abs(lines[-1][2] - x1) <= 12:
            last_y, last_x0, last_x1 = lines[-1]
            lines[-1] = (last_y, min(last_x0, x0), max(last_x1, x1))
        else:
            lines.append((y, x0, x1))
    groups: list[list[tuple[int, int, int]]] = []
    for line in lines:
        for group in groups:
            if abs(group[0][1] - line[1]) <= 12 and abs(group[0][2] - line[2]) <= 12:
                group.append(line)
                break
        else:
            groups.append([line])
    return [
        {"x0": group[0][1], "x1": group[0][2], "ys": sorted(line[0] for line in group)}
        for group in groups
        if len(group) >= SEPARATOR_MIN_LINES
    ]


def _line_colour(image, x0: int, x1: int, y: int) -> str:
    """The colour of a 1px rule, read from its own row."""
    import numpy as np

    rows, columns = image.shape[:2]
    y = max(0, min(rows - 1, y))
    left = max(0, min(columns - 1, x0 + 4))
    right = max(left + 1, min(columns, x1 - 4))
    strip = image[y, left:right]
    if not len(strip):
        return "#e8e8e8"
    colour = np.median(strip, axis=0)
    return "#{:02x}{:02x}{:02x}".format(*(int(value) for value in colour))


def row_bands(groups: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The strips between consecutive rules: one per list row."""
    bands: list[dict[str, Any]] = []
    for group in groups:
        ys = sorted(int(value) for value in group["ys"])
        for top, bottom in zip(ys, ys[1:]):
            height = bottom - top
            if not (ROW_BAND_MIN_HEIGHT <= height <= ROW_BAND_MAX_HEIGHT):
                continue
            bands.append(
                {
                    "bbox": [int(group["x0"]), top + 1, int(group["x1"]) - int(group["x0"]), height - 1],
                    "role": "row",
                    "group": (int(group["x0"]), int(group["x1"])),
                }
            )
    return bands


def _table_from_bands(
    bands: Sequence[Mapping[str, Any]],
    clusters: Sequence[Mapping[str, Any]],
    image,
) -> dict[str, Any] | None:
    """One table out of a stack of row bands, when the columns actually hold up.

    Bands only say "these strips are rows".  A *table* needs columns, and a
    column needs the same x in most rows: that is what separates a data table
    from a list of unrelated rows.  Measured across every page in the corpus
    (``scripts/probe_table_groups.py``): the table group has 6 bands and 5
    columns present in 5 of them; every other group has at most 2 bands and no
    stable column at all, so the thresholds below have a wide margin rather than
    a tuned one.

    Saying "this is a table" is what collapses the frames: seven row containers
    that each became their own frame become one structure, and the words inside
    become its members.
    """
    import numpy as np

    if len(bands) < TABLE_MIN_ROWS:
        return None
    support = max(2, int(round(len(bands) * TABLE_COLUMN_SUPPORT)))
    strong = [cluster for cluster in clusters if int(cluster["rows"]) >= support]
    if len(strong) < TABLE_MIN_COLUMNS:
        return None
    x0, x1 = (int(value) for value in bands[0]["group"])
    tops = [int(band["bbox"][1]) for band in bands]
    bottoms = [int(band["bbox"][1]) + int(band["bbox"][3]) for band in bands]
    top = max(0, min(tops) - 1)
    bottom = max(bottoms)
    if bottom - top < TABLE_MIN_ROWS * 8 or x1 - x0 < TABLE_MIN_WIDTH:
        return None
    boundaries = [x0]
    for cluster in sorted(strong, key=lambda item: int(item["left"])):
        left = int(cluster["left"])
        if left - boundaries[-1] < TABLE_COLUMN_MIN_GAP:
            continue
        boundaries.append(left)
    # 边界不足以切出三列时，这张"表"其实只有两栏对齐文本，交给行带就好。
    if len(boundaries) - 1 < TABLE_MIN_COLUMNS - 1:
        return None
    boundaries.append(x1)

    def fill_of(box: Sequence[int]) -> Any:
        x, y, w, h = (int(value) for value in box)
        patch = image[y : y + h, x : x + w]
        if patch.size == 0:
            return None
        return np.median(patch.reshape(-1, 3), axis=0)

    header_fill = fill_of(bands[0]["bbox"])
    body_fill = fill_of(bands[1]["bbox"]) if len(bands) > 1 else None
    header = False
    if header_fill is not None and body_fill is not None:
        header = (
            max(abs(float(a) - float(b)) for a, b in zip(header_fill, body_fill))
            >= TABLE_HEADER_DELTA
        )
    return {
        "id": f"table:rows:{_digest('rows', x0, top, x1 - x0, bottom - top)}",
        "bbox": [x0, top, x1 - x0, bottom - top],
        "x_boundaries": boundaries,
        "y_boundaries": [top] + bottoms,
        "inferred": False,
        # 行带只由横线切出来，原图没有竖线也没有列间留白：不要替它画格子。
        "grid_flags": {
            "header": header,
            "verticals": False,
            "horizontals": True,
            "headerColor": (
                "#{:02x}{:02x}{:02x}".format(*(int(v) for v in header_fill))
                if header and header_fill is not None
                else "#fbfcfd"
            ),
            "lineColor": _line_colour(image, x0, x1, top),
        },
    }


def column_clusters(
    text_boxes: Sequence[Sequence[int]],
    bands: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Vertical columns inside a family of row bands, with their alignment.

    A column is a set of texts that start at the same x in different rows.  If
    their **right** edges agree to within a few pixels, the column is
    right-aligned (dates, amounts) and the right edge is the anchor: pinning it
    survives a cross-platform font difference, pinning the left edge does not.
    """
    import numpy as np

    inside: list[tuple[int, int, int, int, int]] = []
    for band_index, band in enumerate(bands):
        x, y, w, h = (int(value) for value in band["bbox"])
        for box in text_boxes:
            cx = box[0] + box[2] / 2.0
            cy = box[1] + box[3] / 2.0
            if x <= cx <= x + w and y <= cy <= y + h:
                inside.append((box[0], box[1], box[2], box[3], band_index))
    if not inside:
        return []
    inside.sort(key=lambda item: (item[0], item[1]))
    clusters: list[list[tuple[int, int, int, int, int]]] = []
    for item in inside:
        # 单链：和上一个成员比，不和簇首比。日期列的左缘本身就会差十几像素
        # （月/日位数不同），按簇首比会把一列拆成三簇，然后每簇都不足三行。
        if clusters and item[0] - clusters[-1][-1][0] <= COLUMN_TOLERANCE:
            clusters[-1].append(item)
        else:
            clusters.append([item])
    # 左缘单链看不到"右缘恒定、左缘随字数走"的列：金额 ¥8 与 ¥1,280.00 左缘能
    # 差 40px，任何左缘容差都会把它们拆成孤点。这里补一遍右缘通道，只补左缘
    # 通道漏掉的列，已有簇不动。
    right_channel = right_aligned_groups(
        [[item[0], item[1], item[2], item[3]] for item in inside],
        tol=COLUMN_TOLERANCE,
        min_rows=COLUMN_MIN_ROWS,
    )
    covered = [
        {index for index, member in enumerate(inside) if member in cluster}
        for cluster in clusters
    ]
    for group in right_channel:
        # "已经被左缘通道收进去过"的判据要够严：右缘通道的候选有 3 行，若只和
        # 某个单点簇重叠 1 个元素就算重复，整个候选会被自己丢掉——而它正是
        # 左缘通道看不见的那一列。
        if any(len(set(group) & block) >= max(2, len(group) // 2) for block in covered):
            continue
        clusters.append([inside[index] for index in group])
    result: list[dict[str, Any]] = []
    for cluster in clusters:
        rows = {item[4] for item in cluster}
        if len(rows) < COLUMN_MIN_ROWS:
            continue
        left = np.asarray([item[0] for item in cluster], dtype=float)
        right = np.asarray([item[0] + item[2] for item in cluster], dtype=float)
        result.append(
            {
                "left": int(left.min()),
                "right": int(right.max()),
                "rows": len(rows),
                "leftStd": float(left.std()),
                "rightStd": float(right.std()),
                "boxes": [[item[0], item[1], item[2], item[3]] for item in cluster],
                "align": (
                    "right"
                    if (
                        ALIGN_RIGHT_ENABLED
                        and right.std() <= ALIGN_RIGHT_STD
                        and left.std() > ALIGN_RIGHT_STD
                    )
                    else "left"
                ),
            }
        )
    result.sort(key=lambda item: item["left"])
    return result


def _column_index(columns: Sequence[int], value: int, tolerance: int) -> int | None:
    """最近的一条列线在容差内，就返回它的序号。"""
    best: int | None = None
    best_gap = tolerance + 1
    for index, column in enumerate(columns):
        gap = abs(int(column) - int(value))
        if gap <= tolerance and gap < best_gap:
            best, best_gap = index, gap
    return best


def _crosses_rule(row: Mapping[str, Any], rules: Sequence[Mapping[str, Any]]) -> bool:
    """这一行文字压在一条 1px 横线上吗？

    压线说明它不属于这张表：线是这张表的下边界，线下的字是另一块内容。
    """
    boxes = row["boxes"]
    top = min(box[1] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    left = min(box[0] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    for group in rules:
        x0, x1 = int(group["x0"]), int(group["x1"])
        if x1 < left or x0 > right:
            continue
        if any(top - 1 <= int(y) <= bottom + 1 for y in group["ys"]):
            return True
    return False


def _row_on_grid(
    row: Mapping[str, Any],
    columns: Sequence[int],
    span: tuple[int, int],
    tolerance: int,
) -> bool:
    """这一行的文字至少有一个落点踩在主网格的列线上，且没有横跨出列槽。

    只要一个落点踩线就够——"单据状态：反确认"这种尾行本来就只填了前两列。
    但每个格子必须**装得进一个列槽**：起点踩线时，右缘不能越过下一根列线。
    页脚那句"共 123 条，每页 10 条"从第一列起排、一路横跨四五列，靠这一条挡掉。
    """
    left_limit, right_limit = span
    hits = 0
    for box in row["boxes"]:
        left, right = int(box[0]), int(box[0]) + int(box[2])
        if left < left_limit or right > right_limit:
            return False
        start = _column_index(columns, left, tolerance)
        end = _column_index(columns, right, tolerance)
        if start is None and end is None:
            return False
        if start is not None and end is None and start + 1 < len(columns):
            if right > int(columns[start + 1]) + tolerance:
                return False
        hits += 1
    return hits >= 1


def _absorb_partial_rows(
    all_rows: Sequence[Mapping[str, Any]],
    core_rows: Sequence[Mapping[str, Any]],
    columns: Sequence[int],
    *,
    row_gap: float,
    rules: Sequence[Mapping[str, Any]] = (),
    tolerance: int = COLUMN_TOLERANCE,
) -> list[dict[str, Any]]:
    """把紧贴主网格、只填了部分列的尾行/首行并回表里。

    多列后台表单的最后一行常常不满：ERP 的"单据状态：反确认"只写了前两列，
    后面留空。这一行因为凑不满 ``min_columns`` 被丢掉，表格底边就死死卡在
    倒数第二行，最后一行的输入框落在表外，整张卡随之塌成 Rectangle。

    判据只有三条，且都是几何的：垂直距离不超过 1.5 个行距、没有压到横线、
    格子的起点或终点踩在主网格的某根列线上。
    """
    if not core_rows or row_gap <= 0:
        return [dict(row) for row in core_rows]
    positions = {id(row): index for index, row in enumerate(all_rows)}
    first = positions.get(id(core_rows[0]))
    last = positions.get(id(core_rows[-1]))
    if first is None or last is None:
        return [dict(row) for row in core_rows]
    span = (int(columns[0]) - tolerance, int(columns[-1]) + tolerance)

    def take(row: Mapping[str, Any], anchor: Mapping[str, Any]) -> bool:
        if abs(float(row["centre"]) - float(anchor["centre"])) > 1.5 * row_gap:
            return False
        if _crosses_rule(row, rules):
            return False
        return _row_on_grid(row, columns, span, tolerance)

    head: list[dict[str, Any]] = []
    cursor, anchor = first - 1, core_rows[0]
    while cursor >= 0 and take(all_rows[cursor], anchor):
        head.insert(0, dict(all_rows[cursor]))
        anchor = all_rows[cursor]
        cursor -= 1

    tail: list[dict[str, Any]] = []
    cursor, anchor = last + 1, core_rows[-1]
    while cursor < len(all_rows) and take(all_rows[cursor], anchor):
        tail.append(dict(all_rows[cursor]))
        anchor = all_rows[cursor]
        cursor += 1

    return head + [dict(row) for row in core_rows] + tail


def infer_text_table(
    text_boxes: Sequence[Sequence[int]],
    *,
    min_rows: int = TABLE_MIN_ROWS,
    min_columns: int = TABLE_MIN_COLUMNS,
    rules: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    """A borderless table, inferred from the text grid alone.

    Worklog draws outer borders and nothing else — no row rules, no column
    rules.  The grid is still there, in the only place left: rows of cells that
    start at the same x.  Rows come from clustering y, columns from clustering
    x0, and the table exists when enough rows hit enough columns.
    """
    boxes = [list(int(value) for value in box) for box in text_boxes if box[2] >= 8 and box[3] >= 8]
    if len(boxes) < min_rows * min_columns:
        return None
    heights = sorted(box[3] for box in boxes)
    tolerance = max(4.0, heights[len(heights) // 2] * 0.6)
    all_rows: list[dict[str, Any]] = []
    for box in sorted(boxes, key=lambda item: item[1] + item[3] / 2.0):
        centre = box[1] + box[3] / 2.0
        if all_rows and abs(centre - all_rows[-1]["centre"]) <= tolerance:
            all_rows[-1]["boxes"].append(box)
        else:
            all_rows.append({"centre": centre, "boxes": [box]})
    rows = [row for row in all_rows if len(row["boxes"]) >= min_columns]
    if len(rows) < min_rows:
        return None
    lefts = sorted({box[0] for row in rows for box in row["boxes"]})
    # 一条候选列边界必须有行支持度。没有门槛时，某一行里一个居中短词、一个状态
    # 小标签，都会在 12px 之外单独立一条边界：erp 6 行的表被切出 17 列，worklog
    # 11 行的表被切出 20 列。门槛取"至少三分之一的行走在这一列上"，两行起底，
    # 这样窄表不会被砍掉，孤立的标签又立不起来。
    threshold = max(2, math.ceil(len(rows) / 3))
    candidates: list[list[int]] = []
    for left in lefts:
        if candidates and left - candidates[-1][-1] <= COLUMN_TOLERANCE:
            candidates[-1].append(left)
        else:
            candidates.append([left])
    columns: list[int] = []
    for group in candidates:
        pos = int(round(sum(group) / len(group)))
        hit = {
            index
            for index, row in enumerate(rows)
            if any(abs(box[0] - pos) <= COLUMN_TOLERANCE for box in row["boxes"])
        }
        if len(hit) < threshold:
            continue
        if columns and pos - columns[-1] <= COLUMN_TOLERANCE:
            continue
        columns.append(pos)
    if len(columns) < min_columns:
        return None
    # 主网格定下来之后再吸纳首尾的部分行：顺序不能反，列线得先有权威。
    core_centres = [float(row["centre"]) for row in rows]
    gaps = [b - a for a, b in zip(core_centres, core_centres[1:]) if b - a > 0]
    row_gap = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
    if TABLE_ABSORB_PARTIAL_ROWS:
        rows = _absorb_partial_rows(
            all_rows, rows, columns, row_gap=row_gap, rules=rules, tolerance=COLUMN_TOLERANCE
        )
    # 每一行至少落在 min_columns 个不同的列上，才不是"碰巧对齐"的两三行字。
    filled = 0
    for row in rows:
        hits = {
            index
            for box in row["boxes"]
            for index, left in enumerate(columns)
            if box[0] - COLUMN_TOLERANCE <= left <= box[0] + COLUMN_TOLERANCE
        }
        if len(hits) >= min_columns:
            filled += 1
    if filled < min_rows:
        return None
    xs = [box[0] for row in rows for box in row["boxes"]]
    xe = [box[0] + box[2] for row in rows for box in row["boxes"]]
    top = min(row["boxes"][0][1] for row in rows)
    bottom = max(box[1] + box[3] for row in rows for box in row["boxes"])
    boundaries = sorted({*columns, max(xe)})
    y_boundaries = [int(round(row["centre"] - heights[len(heights) // 2] / 2)) for row in rows]
    y_boundaries.append(bottom + 2)
    return {
        "bbox": [min(xs), top, max(xe) - min(xs), bottom - top],
        "x_boundaries": boundaries,
        "y_boundaries": y_boundaries,
        "rows": filled,
    }


#: 表单/表格首尾那些"只填了部分列"的行是否吸纳回主网格。ERP 的
#: "单据状态：反确认"就是这种行：凑不满列数被丢掉，表格底边卡在倒数第二行。
TABLE_ABSORB_PARTIAL_ROWS = True
#: 一个元素有这么多面积已经落在容器里、却还有一部分探到框外：这是"被切边"，
#: 不是"邻居"。低于这个比例的元素与容器只是相邻，求并会把两块粘成一个。
STRADDLE_MIN_SHARE = 0.3
#: 被切元素的面积不得超过容器的这个比例，否则它是同级容器而不是被切开的子件。
STRADDLE_MAX_AREA_SHARE = 0.25
#: 单边最多长这么多像素。切边是"差几个像素到二十几像素"，不是"差半页"；
#: 不设上限的话，一张小卡片会被一路扩张到整页，然后吞掉所有兄弟节点。
#: 实测 48 会把 worklog 一条 20px 的行带上下撑开 22px，直接压到相邻行上，
#: 让它所属的 panel 丢掉帧资格。24 足够覆盖"输入框被切掉一截"的量级。
STRADDLE_MAX_GROW = 24
#: 包住切边元素后留的呼吸量，与容器自身内边距同量级。
STRADDLE_PADDING = 8
#: 容器是否朝"被自己切开的子件"方向长出去。关掉它，卡片的边就继续切在输入框
#: 中间，成帧判定会以 member-outside-frame 把整张卡降级成平铺矩形。
CONTAINER_STRADDLE_EXPAND = True
#: 只对真正"装东西"的容器做这件事。行带（一条 20px 的文本带）高不过两行字，
#: 把它的上下撑开只会压到相邻行——worklog 的 panel 就是这么丢掉帧的。
STRADDLE_ROLES = ("card",)
#: 矮于两行字的容器不是卡片，是行带；宽不过一个头像栏的不是卡片，是角标。
STRADDLE_MIN_HEIGHT = 40
STRADDLE_MIN_WIDTH = 120
#: 只长横向。纵向的"尾行截断"由表格的行吸纳解决；靠撑高卡片去够尾行，会把卡片
#: 压到相邻区块上——erp 实测 −0.09。横向切边（输入框被右缘切掉半截）没有这个
#: 副作用：同一行里往右长，碰到的是留白。
STRADDLE_EXPAND_AXES = ("x",)


def _ioa(outer: Sequence[int], inner: Sequence[int]) -> float:
    """交集占**内层元素**面积的比例（intersection over area）。

    这里刻意不用 ``_overlap_share``：那个分母取的是较小框，用来判"行带落在
    表格里"；而要问"这个输入框有多少已经进了卡片"，分母必须是元素自己。
    """
    ax, ay, aw, ah = (int(value) for value in outer[:4])
    bx, by, bw, bh = (int(value) for value in inner[:4])
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    if ix <= 0 or iy <= 0:
        return 0.0
    return (ix * iy) / max(1, bw * bh)


def expand_containers_to_straddlers(
    containers: list[dict[str, Any]],
    leaves: Sequence[Sequence[int]],
    *,
    canvas: tuple[int, int],
    min_share: float = STRADDLE_MIN_SHARE,
    max_area_share: float = STRADDLE_MAX_AREA_SHARE,
    max_grow: int = STRADDLE_MAX_GROW,
    padding: int = STRADDLE_PADDING,
) -> dict[str, int]:
    """把卡片扩到刚好包住被自己切开的子件。

    容器的框是从文字包络算出来的，边常常落在最后一个输入框的中间：卡片右缘
    切在"单位：个"的框上，底缘切在"单据状态：反确认"的上半截。成帧判定要求
    每个成员**完整**落在帧矩形内（``member-outside-frame``），差 3px 就整张卡
    被降级成平铺矩形——视觉上只剩一条横线。

    这里只做一件事：若某个小元素的 30% 以上面积已经在框内、其余探到框外，
    就把框朝它探出的方向长出去。三条刹车——单元素面积不超过容器 25%（否则
    是同级容器）、单边不超过 48px、扩张后不越画布。
    """
    stats = {"grown": 0, "elements": 0, "px": 0}
    page_w, page_h = int(canvas[0]), int(canvas[1])
    page_area = float(page_w * page_h)
    boxes = [list(int(value) for value in box[:4]) for box in leaves]
    for item in containers:
        role = str(item.get("role") or "")
        if role not in STRADDLE_ROLES:
            continue
        box = item["bbox"]
        width, height = int(box[2]), int(box[3])
        area = float(width * height)
        # 整页根容器没有"被切"这回事：它本来就是全画布。
        if area <= 0 or area >= page_area * 0.9:
            continue
        if height < STRADDLE_MIN_HEIGHT or width < STRADDLE_MIN_WIDTH:
            continue
        left, top = int(box[0]), int(box[1])
        right, bottom = left + width, top + height
        grown = False
        for candidate in boxes:
            cw, ch = candidate[2], candidate[3]
            if cw * ch > area * max_area_share:
                continue
            if _contains(box, candidate, tolerance=0):
                continue
            if _ioa(box, candidate) < min_share:
                continue
            overflow = (
                left - candidate[0],
                top - candidate[1],
                (candidate[0] + cw) - right,
                (candidate[1] + ch) - bottom,
            )
            if "x" not in STRADDLE_EXPAND_AXES:
                overflow = (0, overflow[1], 0, overflow[3])
            if "y" not in STRADDLE_EXPAND_AXES:
                overflow = (overflow[0], 0, overflow[2], 0)
            # 被允许的那条轴上根本没探出去，就等于没长：别把"只上下溢出"算成一次扩张。
            if not any(value > 0 for value in overflow):
                continue
            if max(overflow) > max_grow:
                continue
            if "x" in STRADDLE_EXPAND_AXES:
                left = min(left, candidate[0])
                right = max(right, candidate[0] + cw)
            if "y" in STRADDLE_EXPAND_AXES:
                top = min(top, candidate[1])
                bottom = max(bottom, candidate[1] + ch)
            grown = True
            stats["elements"] += 1
        if not grown:
            continue
        # 只在真的长出去的那几边留内边距：没动的边补白会把卡片推离原有对齐。
        if left < int(box[0]):
            left = max(0, left - padding)
        if top < int(box[1]):
            top = max(0, top - padding)
        if right > int(box[0]) + width:
            right = min(page_w, right + padding)
        if bottom > int(box[1]) + height:
            bottom = min(page_h, bottom + padding)
        stats["px"] += (int(box[0]) - left) + (int(box[1]) - top)
        stats["px"] += (right - (int(box[0]) + width)) + (bottom - (int(box[1]) + height))
        stats["grown"] += 1
        item["bbox"] = [left, top, max(1, right - left), max(1, bottom - top)]
    return stats


def _link_container_tree(
    container_nodes: list[dict[str, Any]],
    leaves: Sequence[Mapping[str, Any]],
) -> None:
    """每个容器挂到"装得下它的最小容器"上，并把子项写进 children。

    ``container_nodes`` 必须已按面积升序。三条纪律，缺一条树就是坏的：

    * 命中即 ``break``。不 break 会让更大的祖先一路覆盖，中间层（行带、内层
      小卡片）全部被架空，扁平挂到整页根节点上。
    * 候选必须**严格更大**。两个差 1~2px 的容器互相包含，会互相认父成环。
    * 顶层容器 ``parent_id`` 留 None，**不许写成自己**——自环让下游递归打转。

    ``children`` 同时收子容器与叶子：只收叶子的话，中间层容器在树上没有父名，
    整棵树看起来只有一层。
    """
    for node in container_nodes:
        node_area = node["bbox"][2] * node["bbox"][3]
        for candidate in container_nodes:
            if candidate is node:
                continue
            if candidate["bbox"][2] * candidate["bbox"][3] <= node_area:
                continue
            if _contains(candidate["bbox"], node["bbox"], tolerance=2):
                node["parent_id"] = candidate["id"]
                break
        node["children"] = [
            child["id"]
            for child in list(leaves) + container_nodes
            if child is not node and child.get("parent_id") == node["id"]
        ]


def _normalise_ocr_text(text: str) -> str:
    """Turn an impossible day number back into 日, and nothing else.

    EasyOCR reads the trailing 日 of a date as 8 fairly often ("11月14日" ->
    "11月148").  A blanket "ends with 8 means 日" rule would corrupt legal dates
    like "10月8", so the test is the calendar itself: only a day number that
    cannot exist (> 31) whose last glyph is one of the closed shapes the reader
    confuses with 日 (8 / 0 / B) is a misread of 日.
    """
    stripped = text.strip()
    if "月" not in stripped or len(stripped) < 3 or len(stripped) > 9:
        return text
    head, _sep, day = stripped.partition("月")
    if not head.isdigit() or len(head) > 2:
        return text
    last = day[-1:] if day else ""
    if last not in ("8", "0", "B"):
        return text
    digits = day[:-1]
    if not digits.isdigit():
        return text
    value = int(digits + last) if last.isdigit() else int(digits)
    if value <= 31:
        # 8 号、18 号、10月8：合法日期，一个字都不动。
        return text
    return f"{head}月{digits}日"


def build_physical_plan(
    image_path: str | Path,
    *,
    omniparser_url: str = "",
    width: int | None = None,
    height: int | None = None,
    report: PhysicalReport | None = None,
) -> tuple[dict[str, Any], PhysicalReport]:
    """Run the three senses and return one scene plan.

    No model writes a word.  No model writes a box.  Everything here is either
    a character read from the picture (OCR), an icon cut from it (OmniParser),
    or a region found in it (CV).
    """
    from src.app.services.structure.image_contract import (
        extract_ocr_observations,
    )

    stats = report or PhysicalReport()
    image = _load_rgb(image_path)
    rows, columns = image.shape[:2]
    width = int(width or columns)
    height = int(height or rows)
    page = page_colour(image)
    stats.width, stats.height = width, height
    stats.page_colour = "#{:02x}{:02x}{:02x}".format(*page)

    started = time.time()
    # 后端由 OCR_BACKEND 决定（默认 rapidocr，缺依赖自动回退 easyocr）。
    # 返回结构不变，下游一行都不用改。
    observations = extract_ocr_observations(image_path)
    stats.seconds["ocr"] = time.time() - started
    text_boxes = [list(item.get("bbox") or []) for item in observations]

    started = time.time()
    containers = probe_containers(image, page, width, height, text_boxes)
    # 同底色骨架：白底页面的侧栏/顶栏/主卡与页面同色，上一步按"和页面同色就跳过"
    # 把它们全丢了。这里另起一路，在"与页面同色"的像素里按灰缝切块。
    if PAGE_REGION_SKELETON:
        for item in page_regions(image, page, text_boxes, width, height):
            if any(_same_box(item["bbox"], other["bbox"]) for other in containers):
                continue
            # 一个区域里塞着三张以上的已有容器，说明它是这些层的"包装"，
            # 不是新的一层。FluxWeaver 那块 1610x708 的假区域就是这么来的：
            # 把整个表单包进去，表单里原有的卡反而丢了帧资格。
            inner = sum(
                1
                for other in containers
                if _contains(
                    item["bbox"],
                    [
                        other["bbox"][0] + other["bbox"][2] // 2,
                        other["bbox"][1] + other["bbox"][3] // 2,
                        1,
                        1,
                    ],
                    tolerance=0,
                )
            )
            if inner > 3:
                continue
            containers.append(item)
            stats.skeleton += 1
    # 只有 1px 横线、没有闭合框的列表与表格：把线之间的条带实例化成行容器。
    groups = probe_separators(image, width, height)
    bands = row_bands(groups)
    containers.extend(bands)
    # 分隔线本身不画：原图里的线是两像素宽、被抗锯齿冲淡过的灰，硬画一条
    # 1px 实色比不画更远（gmail within15：画 91.81 / 不画 92.51）。行带把
    # 结构说清楚了，线交给下游的补丁与描边恢复。
    stats.seconds["cv"] = time.time() - started
    stats.containers = len(containers)
    stats.rows = len(bands)

    started = time.time()
    icons, state = omniparser_icons(
        image_path,
        width,
        height,
        text_boxes,
        url=omniparser_url,
    )
    stats.seconds["omniparser"] = time.time() - started
    stats.omniparser = state
    stats.icons = len(icons)
    # 插画通道：OmniParser 的检测器只认图标，200px 的礼盒根本不在它的输出里
    # （实测该页最大框 1.6%，礼盒缺席）。这一路补的就是"图"这个尺寸段。
    illustrations = probe_illustrations(
        image,
        text_boxes,
        covered=[item["bbox"] for item in icons],
    )
    stats.illustrations = len(illustrations)
    if state != "applied":
        stats.notes.append(
            "OmniParser 未接入，图标这一路缺席：画布上不会出现图标，但也不会"
            "凭空生成文字胶囊。"
        )

    # 行带里的文本如果形成 >=3 个稳定列簇，就把这组行带升级成 table 节点：
    # 有列宽边界，钳制字号与对齐才有依据。
    tables: list[dict[str, Any]] = []
    absorbed: list[Mapping[str, Any]] = []
    right_aligned: set[tuple[int, ...]] = set()
    for group in groups:
        group_bands = [
            band for band in bands if band.get("group") == (group["x0"], group["x1"])
        ]
        clusters = column_clusters(text_boxes, group_bands)
        # 只有横线的列表（Gmail）：行带已经给出结构，不再建 table——表格装饰会
        # 补出竖线与表头带，而原图并没有。这里只取列对齐信息。
        for cluster in clusters:
            if cluster["align"] == "right":
                for box in cluster["boxes"]:
                    right_aligned.add(tuple(int(value) for value in box))
        # 但"有横线"不等于"没有表"：一叠同跨度的行带里，如果每一列在几乎每一行
        # 都有内容，它就是一张表。把它整块收编，否则七条行带会各自成帧
        # （FluxWeaver：13 帧里有 6 个是表行），而且每行会被当成一张卡去估圆角。
        table = _table_from_bands(group_bands, clusters, image)
        if table is None:
            continue
        tables.append(table)
        absorbed.extend(group_bands)
    if absorbed:
        # 行带已经被表收编：不能同时既是一张表、又是几行容器。
        dropped = {id(band) for band in absorbed}
        bands = [band for band in bands if id(band) not in dropped]
        containers = [item for item in containers if id(item) not in dropped]
    # 表的区域常常也被 probe_containers 当成一张卡量了一遍（FluxWeaver 那张
    # 309,550,1578,276 与表重合 97%）。两块说同一件事的时候留下更具体的那块：
    # 表有列，卡没有。留两张的下场是编译器把它们判成"同一块量了两遍"合并掉，
    # 合并的结果是一张普通卡——列与格线全部丢失。
    for table in tables:
        containers = [
            item
            for item in containers
            if not (
                str(item.get("role") or "") in ("card", "panel")
                and _overlap_share(table["bbox"], item["bbox"]) >= 0.9
            )
        ]

    # guides：≥3 个元素在 ±5px 内共线的坐标才算标尺。作用域按容器切，
    # 并且**由小到大**、每个框只吸一次——一条贯通整页的竖线在页头和列表里
    # 指的不是同一列；同一框被三层容器各吸一次则会累积成一笔糊涂账。
    # 右对齐的列：锚点换成右缘。判据是方差——右缘 std ≤3 且小于左缘 std。
    # 必须用**吸附前**的原始框来判，吸附会抹掉正是这个判据要看的那点差异。
    locked = {
        index
        for index, box in enumerate(text_boxes)
        if tuple(int(value) for value in box) in right_aligned
    }
    locked |= right_aligned_boxes(text_boxes)

    started = time.time()
    icon_boxes = [list(item["bbox"]) for item in icons]
    if GUIDE_SNAP_ENABLED:
        n_text = len(text_boxes)
        all_boxes = [list(box) for box in text_boxes] + icon_boxes
        done: set[int] = set()
        # 每个框的"归属容器"= 装得下它的最小容器，和后面建树的规则一致。
        # 吸附不许改变归属：字被吸出它所在的容器，容器就不再是一帧。
        by_area = sorted(containers, key=lambda item: item["bbox"][2] * item["bbox"][3])
        owners: list[Sequence[int] | None] = []
        for box in all_boxes:
            centre_x = box[0] + box[2] / 2
            centre_y = box[1] + box[3] / 2
            owner = None
            for candidate in by_area:
                cb = candidate["bbox"]
                if (
                    cb[0] <= centre_x <= cb[0] + cb[2]
                    and cb[1] <= centre_y <= cb[1] + cb[3]
                ):
                    owner = cb
                    break
            owners.append(owner)
        guide_count = 0
        for container in sorted(containers, key=lambda item: item["bbox"][2] * item["bbox"][3]):
            cbox = container["bbox"]
            inside = [
                index
                for index, box in enumerate(all_boxes)
                if index not in done
                and cbox[0] <= box[0] + box[2] / 2 <= cbox[0] + cbox[2]
                and cbox[1] <= box[1] + box[3] / 2 <= cbox[1] + cbox[3]
            ]
            if len(inside) < GUIDE_MIN_SUPPORT:
                continue
            guides = build_guides([all_boxes[index] for index in inside])
            if not guides["v"] and not guides["h"]:
                continue
            guide_count += len(guides["v"]) + len(guides["h"])
            snapped, snap_stats = snap_boxes(
                [all_boxes[index] for index in inside],
                guides,
                right_locked=[position for position, index in enumerate(inside) if index in locked],
                icons=[position for position, index in enumerate(inside) if index >= n_text],
            )
            for position, index in enumerate(inside):
                box = snapped[position]
                owner_box = owners[index]
                if owner_box is not None:
                    centre_x = box[0] + box[2] / 2
                    centre_y = box[1] + box[3] / 2
                    if not (
                        owner_box[0] <= centre_x <= owner_box[0] + owner_box[2]
                        and owner_box[1] <= centre_y <= owner_box[1] + owner_box[3]
                    ):
                        continue
                all_boxes[index] = box
            done.update(inside)
            stats.snapped += int(snap_stats["snapped"])
        text_boxes = all_boxes[:n_text]
        for item, box in zip(icons, all_boxes[n_text:]):
            item["bbox"] = list(box)
        stats.guides = guide_count
    stats.seconds["guides"] = time.time() - started

    # 一条线都没有的表格（Worklog）：在容器内部用文本网格推断，且只在"这块
    # 区域里没有行带"时才做——有线的时候线说了算。
    canvas_area = float(width * height)
    for item in containers:
        if item["role"] not in ("card", "panel"):
            continue
        box = item["bbox"]
        if box[2] * box[3] < canvas_area * 0.05:
            continue
        if any(_contains(box, band["bbox"], tolerance=4) for band in bands):
            continue
        # 这块区域已经由行带升级成表了：再推一次会让同一窝东西被画两遍。
        if any(_contains(box, table["bbox"], tolerance=4) for table in tables):
            continue
        inside = [
            text_box
            for text_box in text_boxes
            if box[0] <= text_box[0] + text_box[2] / 2 <= box[0] + box[2]
            and box[1] <= text_box[1] + text_box[3] / 2 <= box[1] + box[3]
        ]
        inferred = infer_text_table(inside, rules=groups)
        if inferred is None:
            continue
        if inferred["bbox"][2] < box[2] * 0.5:
            continue
        tables.append(
            {
                "id": f"table:text:{len(tables)}",
                "bbox": inferred["bbox"],
                "x_boundaries": inferred["x_boundaries"],
                "y_boundaries": inferred["y_boundaries"],
                "inferred": True,
                # 原图没有格子线也没有表头底色：装饰层不要替它画。
                # 原图没有格子线也没有表头底色：装饰层不要替它画。
                "grid_flags": {"header": False, "verticals": False, "horizontals": False},
            }
        )
    stats.tables = len(tables)

    # 1D 线条补行带：放在表格推断之后。推断的准入条件是"这片区域里没有行带"，
    # 提前补带会把 Worklog 那张本来就能推出来的表自己挡掉。判重也只对已有行带
    # 做——对着所有容器判重的话，行带与所属卡片重叠 100%，会被自己那张卡挡掉。
    started = time.time()
    lines = probe_lines(image, width, height) if LINE_BANDS_ENABLED else []
    stats.lines = len(lines)
    if lines:
        line_bands = bands_from_lines(lines, containers, existing=list(bands))
        # 已经有 table 的区域不要再切行带：表格自己会说列和行，线也在它边界上，
        # 两边同时结构化只会让同一窝东西被画两遍。
        table_boxes = [list(table["bbox"]) for table in tables]
        if table_boxes:
            line_bands = [
                band
                for band in line_bands
                if not any(_overlap_share(band["bbox"], box) >= 0.3 for box in table_boxes)
            ]
        if line_bands:
            containers.extend(line_bands)
            bands.extend(line_bands)
            stats.bands_added = len(line_bands)

    # 行母版：一列同构行共用一个左缘、一个右缘和一组列槽位。缺了头像的那一行
    # 偏移不是它自己的错，是它少了东西，所以按"缺元素"给它更大的归位预算。
    if ROW_MASTER_ENABLED and bands:
        combined = [list(box) for box in text_boxes] + [list(item["bbox"]) for item in icons]
        masters = row_master(bands, combined)
        if masters:
            master_stats = apply_master(bands, combined, masters)
            text_boxes = combined[: len(text_boxes)]
            for item, box in zip(icons, combined[len(text_boxes):]):
                item["bbox"] = list(box)
            stats.masters = len(masters)
            stats.snapped += int(master_stats["boxes"])

    # 穿框膨胀守卫：容器的框是文字包络，边常常切在最后一个输入框中间。差 3px
    # 就触发成帧判定里的 member-outside-frame，整张卡被降级成平铺矩形。这里把
    # 框朝"已经被自己吃进去 30%、却还有一截在外面"的小件方向长出去。
    started_grow = time.time()
    grow_stats = {"grown": 0}
    if CONTAINER_STRADDLE_EXPAND:
        combined = (
            [list(box) for box in text_boxes]
            + [list(item["bbox"]) for item in icons]
            + [list(item["bbox"]) for item in illustrations]
        )
        grow_stats = expand_containers_to_straddlers(
            containers, combined, canvas=(width, height)
        )
    stats.grown = int(grow_stats["grown"])
    stats.seconds["grow"] = time.time() - started_grow

    stats.containers = len(containers)
    stats.rows = len(bands)
    stats.seconds["structure"] = time.time() - started

    nodes: list[dict[str, Any]] = []
    container_nodes: list[dict[str, Any]] = []
    for index, item in enumerate(containers):
        box = item["bbox"]
        role = item["role"]
        node = {
            "id": f"{role}:container-{index}",
            "parent_id": None,
            "type": "container",
            "role": role,
            "bbox": list(box),
            "content_ref": None,
            "geometry_ref": f"geometry:{_digest('container', *box)}",
            "children": [],
            "source_ref": f"physical.containers[{index}]",
        }
        if item.get("fill"):
            node["fill"] = str(item["fill"])
        container_nodes.append(node)
        nodes.append(node)

    text_nodes: list[dict[str, Any]] = []
    for index, observation in enumerate(observations):
        # 用吸附后的框：节点 id 与 geometry_ref 都由它派生，两处必须同一份坐标。
        box = [int(value) for value in text_boxes[index]]
        text = _normalise_ocr_text(str(observation.get("text") or "").strip())
        if not text:
            continue
        content_ref = f"text:{_digest(text, *box)}"
        node = {
            "id": content_ref,
            "parent_id": None,
            "type": "text",
            "role": "",
            "bbox": box,
            "content_ref": content_ref,
            "geometry_ref": f"geometry:{_digest('text', *box)}",
            "children": [],
            "text": text,
            "source_ref": f"physical.ocr[{index}]",
            "confidence": float(observation.get("confidence") or 0.0),
            # OCR 的框贴着墨迹：它的宽度就是这段字该有的宽度，允许按它标定字距。
            "ink_tight": True,
        }
        if index in locked:
            node["text_align"] = "right"
        text_nodes.append(node)
        nodes.append(node)
    stats.texts = len(text_nodes)

    icon_nodes: list[dict[str, Any]] = []
    for index, item in enumerate(icons):
        box = item["bbox"]
        caption = item["caption"] or "icon"
        content_ref = f"asset:{_digest('icon', *box, caption)}"
        node = {
            "id": content_ref,
            "parent_id": None,
            "type": "image",
            "role": "icon",
            "bbox": box,
            "content_ref": content_ref,
            "geometry_ref": f"geometry:{_digest('icon', *box)}",
            "children": [],
            # 图层的 name 元数据：语义只住在这里，画布上不出现。
            "name": caption,
            "caption": caption,
            "source_ref": f"physical.icons[{index}]",
            "interactive": item["interactive"],
        }
        icon_nodes.append(node)
        nodes.append(node)

    illustration_nodes: list[dict[str, Any]] = []
    for index, item in enumerate(illustrations):
        box = [int(value) for value in item["bbox"]]
        content_ref = f"asset:{_digest('illustration', *box)}"
        node = {
            "id": content_ref,
            "parent_id": None,
            "type": "image",
            "role": "illustration",
            "bbox": box,
            "content_ref": content_ref,
            "geometry_ref": f"geometry:{_digest('illustration', *box)}",
            "children": [],
            "name": "illustration",
            "source_ref": f"physical.illustrations[{index}]",
            "interactive": False,
        }
        illustration_nodes.append(node)
        nodes.append(node)

    for index, table in enumerate(tables):
        node = {
            "id": table["id"],
            "parent_id": None,
            "type": "table",
            "role": "table",
            "bbox": list(table["bbox"]),
            "content_ref": table["id"],
            "geometry_ref": f"geometry:{_digest('table', *table['bbox'])}",
            "children": [],
            "source_ref": f"physical.tables[{index}]",
            "grid": {
                "x_boundaries": list(table["x_boundaries"]),
                "y_boundaries": list(table["y_boundaries"]),
                **dict(table.get("grid_flags") or {}),
            },
        }
        nodes.append(node)

    # table 节点也要挂到容器上：它是行带的上层结构。
    table_nodes: list[dict[str, Any]] = [node for node in nodes if node.get("type") == "table"]
    for node in table_nodes:
        box = node["bbox"]
        centre = (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)
        for candidate in sorted(
            (item for item in container_nodes if item.get("type") == "container"),
            key=lambda item: item["bbox"][2] * item["bbox"][3],
        ):
            cbox = candidate["bbox"]
            if (
                cbox[0] <= centre[0] <= cbox[0] + cbox[2]
                and cbox[1] <= centre[1] <= cbox[1] + cbox[3]
            ):
                node["parent_id"] = candidate["id"]
                break

    # 确定性建树：每个叶子归给"装得下它的最小容器"。
    # table 与 container 一起参与：否则表里的字会挂到表外面去，表就变成一个
    # 没有成员的空壳，那一块又退回"逐元素平铺"。
    structure_nodes = container_nodes + table_nodes
    structure_nodes.sort(key=lambda node: node["bbox"][2] * node["bbox"][3])
    for node in text_nodes + icon_nodes + illustration_nodes:
        box = node["bbox"]
        centre = (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)
        owner = None
        for candidate in structure_nodes:
            cbox = candidate["bbox"]
            if (
                cbox[0] <= centre[0] <= cbox[0] + cbox[2]
                and cbox[1] <= centre[1] <= cbox[1] + cbox[3]
            ):
                owner = candidate
                break
        if owner is not None:
            node["parent_id"] = owner["id"]
    _link_container_tree(structure_nodes, text_nodes + icon_nodes + illustration_nodes)

    plan = {
        "schema_version": "physical-scene-plan/1.0",
        "status": "planned",
        "reference_id": f"physical:{_digest(*page, width, height)}",
        "image_size": [width, height],
        "coordinate_basis": "source-pixel-top-left",
        "nodes": sorted(
            nodes,
            key=lambda node: (
                0 if node["type"] == "container" else 1,
                -node["bbox"][2] * node["bbox"][3],
            ),
        ),
        "suppressed": [],
        "ownership": {
            "content_ref": "unique",
            "slice_layout_authority": "forbidden",
            "source": "physical_perception:ocr+omniparser+cv",
        },
    }
    return plan, stats


#: 与页面只差几个色阶、又没有 1px 硬边的大面：现代内容页与 Dashboard 用它划分
#: 分区（CSDN 的暖白栏 #f5eee6 压在 #fdfcfa 的页面上）。它既不是"与页面同色"
#: （page_regions 不收），也长不成一个量化色桶（_region_boxes 收不到），所以
#: 前面两个探针都看不见它。
SOFT_SURFACE_MIN_DELTA = 3.0
#: 超过这个差就是实色块，交给 _region_boxes；微色差面不抢它的活。
SOFT_SURFACE_MAX_DELTA = 26.0
#: 内部平均梯度上限：照片和插画在这里被排除，留下的是平涂或缓慢渐变。
SOFT_SURFACE_MAX_GRADIENT = 9.0
SOFT_SURFACE_MIN_SHARE = 0.01
#: 允许很大（CSDN 那块占 65%），但整页四边全包住的那种是页面本身，不是一面。
SOFT_SURFACE_MAX_SHARE = 0.88
SOFT_SURFACE_MIN_RECT = 0.85
#: 面里至少要有这么多组文本/控件：空面分不清是卡片还是背景。
SOFT_SURFACE_MIN_TEXTS = 1


def probe_soft_surfaces(
    image,
    page: Sequence[int],
    text_boxes: Sequence[Sequence[int]],
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    """The large, borderless, slightly-off-page surfaces modern layouts are made of.

    Two things defeated the existing probes on CSDN, and both are the same fact:
    the surface is a *gradient*, not a fill.

    * ``_region_boxes`` quantises colour and grows one component per bucket; a
      ramp crosses a dozen buckets and none of them becomes a rectangle.
    * ``_recover_soft_panels`` thresholds on max channel difference; JPEG noise
      inflates that mask until every blob merges into one that covers the page,
      which its size cap then refuses.

    So this blurs first (noise is not a colour), measures the *mean* channel
    difference (a ramp stays inside one band), and accepts a surface whose
    interior is flat or slowly varying.  What it returns is a rectangle to be
    painted underneath: which axis follows the ramp is the caller's problem.
    """
    import cv2
    import numpy as np

    source = np.asarray(image, dtype=np.uint8)
    if source.ndim != 3:
        return []
    source = source[:height, :width]
    page_rgb = np.asarray(page, dtype=np.float32)
    smooth = cv2.medianBlur(source, 5).astype(np.float32)
    delta = np.abs(smooth - page_rgb.reshape(1, 1, 3)).mean(axis=2)
    mask = ((delta >= SOFT_SURFACE_MIN_DELTA) & (delta <= SOFT_SURFACE_MAX_DELTA)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    gray = cv2.cvtColor(smooth.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    magnitude = np.hypot(
        cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    )
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    canvas = float(width * height)
    found: list[dict[str, Any]] = []
    for index in range(1, count):
        x, y, w, h, area = (int(value) for value in stats[index])
        if w < 24 or h < 24:
            continue
        share = (w * h) / canvas
        if not (SOFT_SURFACE_MIN_SHARE <= share <= SOFT_SURFACE_MAX_SHARE):
            continue
        raw = (labels[y : y + h, x : x + w] == index).astype(np.uint8)
        piece = raw
        # 面里的字与图标会在这个连通域上打洞：洞是内容，不是形状。先把外轮廓
        # 填实再判矩形度，否则一张写满字的卡片必然被当成不规则碎片。
        contours, _hierarchy = cv2.findContours(piece, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(piece)
        if contours:
            cv2.drawContours(filled, contours, -1, 1, thickness=cv2.FILLED)
        rows = filled.mean(axis=1)
        columns = filled.mean(axis=0)
        if rows.max() > 0 and columns.max() > 0:
            # 同一个投影裁剪：一块面在大框里被别的层啃掉一角时，先收回到
            # "每一行/列至少覆盖最强行一半"的范围，再判矩形度。
            keep_rows = np.where(rows >= 0.5 * rows.max())[0]
            keep_columns = np.where(columns >= 0.5 * columns.max())[0]
            if keep_rows.size and keep_columns.size:
                top, bottom = int(keep_rows.min()), int(keep_rows.max()) + 1
                left, right = int(keep_columns.min()), int(keep_columns.max()) + 1
                if bottom - top >= 24 and right - left >= 24:
                    x, y, w, h = x + left, y + top, right - left, bottom - top
                    filled = filled[top:bottom, left:right]
                    raw = raw[top:bottom, left:right]
                    piece = piece[top:bottom, left:right]
        if filled.mean() < SOFT_SURFACE_MIN_RECT:
            continue
        if float(raw.mean()) < 0.35 * float(filled.mean()):
            # 只剩一圈细边：那是描边，不是一面。
            continue
        piece = raw.astype(bool)
        if float(magnitude[y : y + h, x : x + w][piece].mean()) > SOFT_SURFACE_MAX_GRADIENT:
            continue
        inside = 0
        for box in text_boxes:
            if len(box) < 4:
                continue
            tx, ty, tw, th = (int(v) for v in box[:4])
            if tx >= x and ty >= y and tx + tw <= x + w and ty + th <= y + h:
                inside += 1
        if inside < SOFT_SURFACE_MIN_TEXTS:
            continue
        pixels = smooth[y : y + h, x : x + w][piece]
        if pixels.size == 0:
            continue
        colour = np.median(pixels, axis=0)
        touches = (
            x <= 0 or y <= 0 or x + w >= width or y + h >= height
        )
        found.append(
            {
                "bbox": [x, y, w, h],
                "share": round(share, 4),
                "fill": "#{:02x}{:02x}{:02x}".format(*(int(v) for v in colour)),
                "touchesEdge": bool(touches),
                "texts": inside,
                "gradient": round(
                    float(magnitude[y : y + h, x : x + w][piece].mean()), 2
                ),
            }
        )
    found.sort(key=lambda item: -item["share"])
    return found
