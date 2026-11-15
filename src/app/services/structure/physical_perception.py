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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

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
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "physical-perception/1.0",
            "width": self.width,
            "height": self.height,
            "pageColour": self.page_colour,
            "containers": self.containers,
            "texts": self.texts,
            "icons": self.icons,
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
    """
    import numpy as np

    quantised = (image // COLOUR_QUANTUM * COLOUR_QUANTUM).reshape(-1, 3)
    colours, counts = np.unique(quantised, axis=0, return_counts=True)
    return tuple(int(value) for value in colours[int(np.argmax(counts))])


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
            if tuple(int(v) for v in colour) == tuple(int(v) for v in page):
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
    x, y, w, h = box
    if w >= width * 0.85 and y <= height * 0.12 and h <= height * 0.25:
        return "header"
    if h >= height * 0.35 and x <= width * 0.3 and w <= width * 0.4:
        return "sidebar"
    if w * h >= width * height * 0.5:
        return "card"
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
        return None
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


def _normalise_ocr_text(text: str) -> str:
    """Fix the one glyph confusion that changes meaning in a date.

    EasyOCR reads the trailing 日 of a date as 8 about seven times in eight on
    this page ("11月14日" -> "11月148"), and a wrong date is worse than a wrong
    typeface.  Only this pattern is touched: a short token that already contains
    月 and ends in a digit 8.
    """
    stripped = text.strip()
    if "月" not in stripped or len(stripped) > 8 or len(stripped) < 3:
        return text
    if not stripped.endswith("8"):
        return text
    head, _sep, _tail = stripped.partition("月")
    if not head.isdigit():
        return text
    tail = stripped.split("月", 1)[1]
    if not tail[:-1].isdigit() or len(tail) > 3:
        return text
    return stripped[:-1] + "日"


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
        extract_easyocr_observations,
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
    observations = extract_easyocr_observations(image_path, languages=["ch_sim", "en"])
    stats.seconds["ocr"] = time.time() - started
    text_boxes = [list(item.get("bbox") or []) for item in observations]

    started = time.time()
    containers = probe_containers(image, page, width, height, text_boxes)
    stats.seconds["cv"] = time.time() - started
    stats.containers = len(containers)

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
    if state != "applied":
        stats.notes.append(
            "OmniParser 未接入，图标这一路缺席：画布上不会出现图标，但也不会"
            "凭空生成文字胶囊。"
        )

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
        container_nodes.append(node)
        nodes.append(node)

    text_nodes: list[dict[str, Any]] = []
    for index, observation in enumerate(observations):
        box = [int(value) for value in observation["bbox"]]
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

    # 确定性建树：每个叶子归给"装得下它的最小容器"。
    container_nodes.sort(key=lambda node: node["bbox"][2] * node["bbox"][3])
    for node in text_nodes + icon_nodes:
        box = node["bbox"]
        centre = (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)
        owner = None
        for candidate in container_nodes:
            cbox = candidate["bbox"]
            if (
                cbox[0] <= centre[0] <= cbox[0] + cbox[2]
                and cbox[1] <= centre[1] <= cbox[1] + cbox[3]
            ):
                owner = candidate
                break
        if owner is not None:
            node["parent_id"] = owner["id"]
    for node in container_nodes:
        for candidate in container_nodes:
            if candidate is node:
                continue
            if _contains(candidate["bbox"], node["bbox"], tolerance=2):
                node["parent_id"] = candidate["id"]
        if node["parent_id"] is None:
            node["parent_id"] = node["id"]
        node["children"] = [
            child["id"]
            for child in text_nodes + icon_nodes
            if child.get("parent_id") == node["id"]
        ]

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
