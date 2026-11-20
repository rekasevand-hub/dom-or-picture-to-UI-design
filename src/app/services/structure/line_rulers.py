"""线条、标尺与行母版：页面没画出来的那三层结构。

一张页面上三种结构是"看不见"的，因为它们没有被画成盒子：

* **线**（``lines``）——列表每行之间那条 1px 灰线。它是最硬的坐标证据（CV 真的
  看见了像素），但它不是容器：把它当容器画出来就是一条实色横杠，比不画更远。
* **标尺**（``guides``）——一列字的左缘、它左边的图标、和这一列的分隔线，本该在
  同一条竖线上。三者各自量出来差 2~5px，谁都没错，只是都没有权威。
* **行母版**（``master``）——一列邮件行，某一封没有头像、某一封标题短一截，于是
  它整体比同列其它行左移十几像素。行本身是同构的，偏移来自"这一行少了什么"。

三者的共同点：**答案来自多数，不来自任何单次测量**。所以这里全部是投票和聚类，
没有一个页面名、一个关键词、一个坐标常量。

与 ``swarm-cursors`` 的关系：线/标尺/母版这套分类借自它的 blueprint（``rect`` /
``line`` / ``guide`` / ``master``+``dup``），但**没有借它的吸附语义**。它那边
光标把字拖到参考线再 ``dx=0`` 弹回原位，参考线是表演道具；这里吸附是唯一会移动
坐标的动作，因为多数比单次测量可信。
"""

from __future__ import annotations

from statistics import median, pstdev
from typing import Any, Iterable, Mapping, Sequence

# ---------------------------------------------------------------- line probe

#: 低对比 1px 线在 30/90 的 Canny 上就出来，高对比阴影不会额外成线。
LINE_CANNY_LOW = 30
LINE_CANNY_HIGH = 90
#: 霍夫票数与最短段：先找"格子里那一小段"，再按坐标并成整条。
LINE_HOUGH_VOTES = 90
LINE_MIN_SEGMENT = 80
#: 同一方向上相邻线段间隙小于这个值，视为同一条线被内容切断。
LINE_MAX_GAP = 48
#: 抗锯齿让一条线占两行，同一坐标附近再合并。
LINE_MERGE_TOL = 3
#: 一条线要横跨父容器的这个比例，才算"划分了这一行"，否则是局部下划线。
LINE_MIN_PARENT_SHARE = 0.5
#: 绝对下限：再短的线是分隔符或下划线，不是行边界。
LINE_MIN_LENGTH = 120
#: 安全帽：极端页面（截图里有大量文字行）不让线数爆掉。
LINE_MAX = 600

# ------------------------------------------------------------------- bands

#: 行带高度窗口：低于下限是行距，高于上限是面板。
BAND_MIN_HEIGHT = 18
BAND_MAX_HEIGHT = 200
#: 单页最多补这么多条行带，防止把整页切成碎片。
BAND_MAX_NEW = 16

# ------------------------------------------------------------------ guides

#: 共线判据：三个元素在 ±5px 内同一条线上。
GUIDE_TOL = 5
#: 两个是巧合，三个是边距。
GUIDE_MIN_SUPPORT = 3
#: 右对齐判据：右缘标准差不超过这个值，且**小于**左缘标准差。
RIGHT_ALIGN_STD = 1.5
#: 左缘至少要漂这么多，才谈得上是"右缘恒定、左缘随字数走"。
RIGHT_ALIGN_MIN_DRIFT = 2.5
#: 判右对齐时的分组容差，比吸附容差松：日期列的左缘随位数漂移，
#: 若按吸附容差分组，一列会被拆成三个孤点，右缘再齐也看不到。
GROUP_TOL = 12
#: 右对齐列的成员宽度不得超过"字高的这么多倍"。字段（日期、金额、未读数）是矮胖的，
#: 被截断的句子是细长的；两者右缘都会对齐，只有这个比例能把它们分开。
#: 取 8.5 而不是 6：完整时间戳 `2026-11-16 14:30:00` 与带千分位的长金额宽度约
#: 7~8 倍行高，按 6 会把它们误伤出列；被截断的主题句通常在 12 倍以上。
RIGHT_ALIGN_MAX_ASPECT = 8.5
#: 只吸水平轴。纵向挪 5px 就能把一行字挤出它所属的行带，行带随之不再是帧；
#: 而这一轮要治的（列对齐、缺前置元素导致的整体左移）全在水平轴上。
GUIDE_SNAP_AXIS_Y = False

# ------------------------------------------------------------------ master

#: 至少三行同构才值得归纳母版；两行是巧合。
MASTER_MIN_ROWS = 3
#: 行高差在这个范围内算同构。
MASTER_HEIGHT_TOL = 6
#: 槽位吸附容差：超出这个距离的偏移是"本来就要缩进"，不是缺了图标。
MASTER_SLOT_TOL = 12

#: 三项独立开关：各自改的东西不同，负收益时单独关。
#:
#: 实测结论（2026-11-16，erp/worklog/gmail，见 NOTES 里的消融表）：三项都没有
#: 稳定正收益，两项还会掉帧，所以**默认全关**。代码、单测与接线保留，因为它们
#: 已经把"为什么不管用"测清楚了，下一轮可以只改一处再看：
#:
#: * ``LINE_BANDS_ENABLED``：erp 多切 4 帧、within15 −0.15，gmail 掉 1 帧且分数不动。
#: * ``GUIDE_SNAP_ENABLED``：唯一有大收益的一项（worklog within30/15 双 +0.60），
#:   但代价是 worklog 掉 1 帧、erp within15 −0.18。收益来自纵向（基线）吸附，
#:   而纵向吸附正是掉帧的原因，两者拆不开。
#: * ``ROW_MASTER_ENABLED``：gmail 只命中 1 组母版，无可测影响。
LINE_BANDS_ENABLED = False
GUIDE_SNAP_ENABLED = False
ROW_MASTER_ENABLED = False


# --------------------------------------------------------------------- lines


def _merge_runs(spans: Sequence[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """Merge intervals that belong to the same physical line.

    A grid cell's hairline is broken by every vertical border, so the segments
    on one coordinate have to be stitched before the coordinate means anything.
    """
    ordered = sorted(spans)
    merged: list[list[int]] = []
    for lo, hi in ordered:
        if merged and lo - merged[-1][1] <= LINE_MAX_GAP:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(lo, hi, hi - lo) for lo, hi in merged]


def probe_lines(image, width: int, height: int) -> list[dict[str, Any]]:
    """Every long 1px line on the page, horizontal or vertical.

    Deliberately separate from ``probe_separators``: that one asks "do these
    lines form a list family", this one only asks "is there a line here".  A
    single border on the left of a card is a line and not a separator family,
    and a vertical divider between two columns is invisible to a detector that
    only looks at ``abs(y2 - y1) <= 1``.
    """
    import cv2
    import numpy as np

    if height < 16 or width < 16:
        return []
    gray = cv2.cvtColor(image.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, LINE_CANNY_LOW, LINE_CANNY_HIGH)
    segments = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=LINE_HOUGH_VOTES,
        minLineLength=LINE_MIN_SEGMENT,
        maxLineGap=6,
    )
    if segments is None:
        return []
    horizontal: dict[int, list[tuple[int, int]]] = {}
    vertical: dict[int, list[tuple[int, int]]] = {}
    for segment in segments:
        # OpenCV 4 returns (N, 1, 4) and OpenCV 5 returns (N, 4).  Indexing [0]
        # gives the four coordinates on the first and a single int on the second,
        # so flatten instead of assuming a nesting level.
        x1, y1, x2, y2 = (int(value) for value in np.asarray(segment).reshape(-1)[:4])
        if abs(y2 - y1) <= 1:
            horizontal.setdefault(min(y1, y2), []).append((min(x1, x2), max(x1, x2)))
        elif abs(x2 - x1) <= 1:
            vertical.setdefault(min(x1, x2), []).append((min(y1, y2), max(y1, y2)))
    lines: list[dict[str, Any]] = []
    for axis, table in (("h", horizontal), ("v", vertical)):
        for pos in sorted(table):
            for lo, hi, length in _merge_runs(table[pos]):
                if length < LINE_MIN_LENGTH:
                    continue
                lines.append(
                    {"axis": axis, "pos": int(pos), "lo": int(lo), "hi": int(hi), "length": int(length)}
                )
    # 抗锯齿产生的相邻行：同一条线只留跨度最大的那条。
    lines.sort(key=lambda item: (item["axis"], item["pos"], -item["length"]))
    kept: list[dict[str, Any]] = []
    for line in lines:
        twin = None
        for existing in kept:
            if (
                existing["axis"] == line["axis"]
                and abs(existing["pos"] - line["pos"]) <= LINE_MERGE_TOL
                and abs(existing["lo"] - line["lo"]) <= 24
                and abs(existing["hi"] - line["hi"]) <= 24
            ):
                twin = existing
                break
        if twin is None:
            kept.append(line)
        elif line["length"] > twin["length"]:
            twin.update(line)
        if len(kept) >= LINE_MAX:
            break
    return kept


def lines_in(
    lines: Sequence[Mapping[str, Any]],
    box: Sequence[int],
    *,
    axis: str,
    share: float = LINE_MIN_PARENT_SHARE,
) -> list[dict[str, Any]]:
    """The lines that divide this box, and only those.

    A line belongs to a box when it sits inside it *and* spans at least half of
    it.  Without the span test, a table cell's underline and a button's bottom
    border both become row boundaries for the card they happen to sit in.
    """
    x, y, w, h = (int(value) for value in box[:4])
    out: list[dict[str, Any]] = []
    for line in lines:
        if line["axis"] != axis:
            continue
        if axis == "h":
            if not (y - 2 <= int(line["pos"]) <= y + h + 2):
                continue
            lo, hi, need = x, x + w, w
        else:
            if not (x - 2 <= int(line["pos"]) <= x + w + 2):
                continue
            lo, hi, need = y, y + h, h
        if int(line["lo"]) < lo - 6 or int(line["hi"]) > hi + 6:
            continue
        if int(line["length"]) < max(LINE_MIN_LENGTH, int(need * share)):
            continue
        out.append(dict(line))
    return out


def _overlaps(left: Sequence[int], right: Sequence[int], *, share: float = 0.5) -> bool:
    if len(right) < 4:
        return False
    ax, ay, aw, ah = (int(value) for value in left[:4])
    bx, by, bw, bh = (int(value) for value in right[:4])
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    if ix <= 0 or iy <= 0:
        return False
    return (ix * iy) / max(1, min(aw * ah, bw * bh)) >= share


def bands_from_lines(
    lines: Sequence[Mapping[str, Any]],
    containers: Sequence[Mapping[str, Any]],
    *,
    existing: Sequence[Mapping[str, Any]] = (),
    max_new: int = BAND_MAX_NEW,
) -> list[dict[str, Any]]:
    """Materialise the strips between a container's own parallel lines.

    Gmail draws one hairline per message and no rectangle anywhere, so nothing
    in CV says "these twelve messages are twelve rows".  The lines say it: two
    consecutive rules 72px apart, each spanning the list width, are the top and
    bottom of one row.
    """
    out: list[dict[str, Any]] = []
    for container in containers:
        if len(out) >= max_new:
            break
        box = container.get("bbox")
        if not box or len(box) < 4:
            continue
        x, y, w, h = (int(value) for value in box[:4])
        if w < LINE_MIN_LENGTH or h < BAND_MIN_HEIGHT:
            continue
        horizontal = lines_in(lines, box, axis="h")
        if len(horizontal) < 2:
            continue
        positions = sorted({int(line["pos"]) for line in horizontal})
        left = min(int(line["lo"]) for line in horizontal)
        right = max(int(line["hi"]) for line in horizontal)
        for top, bottom in zip(positions, positions[1:]):
            height = bottom - top
            if not (BAND_MIN_HEIGHT <= height <= BAND_MAX_HEIGHT):
                continue
            band = [left, top + 1, max(1, right - left), height - 1]
            if any(_overlaps(band, list(item.get("bbox") or [])) for item in existing):
                continue
            if any(_overlaps(band, item["bbox"]) for item in out):
                continue
            out.append(
                {
                    "bbox": band,
                    "role": "row",
                    "source": "line-band",
                    "fill": container.get("fill") or "",
                }
            )
            if len(out) >= max_new:
                break
    return out


# -------------------------------------------------------------------- guides


def _cluster_positions(
    values: Sequence[tuple[int, int]],
    *,
    tol: int,
    min_support: int = GUIDE_MIN_SUPPORT,
) -> list[tuple[int, int]]:
    """Group (position, owner) pairs that agree within ``tol``.

    Returns ``(median position, distinct owner count)``.  The position is the
    median rather than the mode: OCR boxes jitter by 1~3px, and rounding jitter
    into identical integers would make the mode pick one of them at random,
    while the median sits where the group actually is.

    Grouping is single-link, so a slow drift can chain (100, 105, 110, 115 all
    connect) and leave a median that **no element occupies**.  A guide nobody
    stands on is worse than no guide, so the cluster is validated afterwards:
    only owners within ``tol`` of the median count, and there must be enough of
    them.  This is the check that keeps a dense page from turning every edge into
    a ruler.
    """
    ordered = sorted(values, key=lambda item: item[0])
    groups: list[list[tuple[int, int]]] = []
    for value in ordered:
        if groups and value[0] - groups[-1][-1][0] <= tol:
            groups[-1].append(value)
        else:
            groups.append([value])
    out: list[tuple[int, int]] = []
    for group in groups:
        values = [value for value, _ in group]
        # 一个簇跨得比两倍容差还宽，就不是"同一条边"，是一条正在漂移的边。
        # 取它的中位数会把一个没人站的坐标立成标尺，后面所有元素都被拉过去。
        if max(values) - min(values) > 2 * tol:
            continue
        pos = int(round(median(values)))
        owners = {owner for value, owner in group if abs(value - pos) <= tol}
        if len(owners) >= min_support:
            out.append((pos, len(owners)))
    return out


def build_guides(
    boxes: Sequence[Sequence[int]],
    *,
    tol: int = GUIDE_TOL,
    min_support: int = GUIDE_MIN_SUPPORT,
) -> dict[str, Any]:
    """Vertical and horizontal coordinates that enough elements agree on.

    Left edges, right edges and vertical centres all vote.  A guide is only kept
    when at least ``min_support`` **distinct** elements land on it — the same
    element contributing its left and right edge to the same coordinate counts
    once, which is what stops a column of single-glyph boxes from inventing a
    margin.
    """
    left: list[tuple[int, int]] = []
    right: list[tuple[int, int]] = []
    centre: list[tuple[int, int]] = []
    for index, box in enumerate(boxes):
        if len(box) < 4:
            continue
        x, y, w, h = (int(value) for value in box[:4])
        left.append((x, index))
        right.append((x + w, index))
        centre.append((y + h // 2, index))
    vertical = [
        {"pos": pos, "support": support, "kind": "edge"}
        for pos, support in _cluster_positions(left, tol=tol, min_support=min_support)
        + _cluster_positions(right, tol=tol, min_support=min_support)
    ]
    horizontal = [
        {"pos": pos, "support": support, "kind": "baseline"}
        for pos, support in _cluster_positions(centre, tol=tol, min_support=min_support)
    ]
    vertical.sort(key=lambda item: (item["pos"], -item["support"]))
    horizontal.sort(key=lambda item: (item["pos"], -item["support"]))
    return {"v": vertical, "h": horizontal}


def right_aligned_boxes(
    boxes: Sequence[Sequence[int]],
    *,
    tol: int = GROUP_TOL,
    min_rows: int = GUIDE_MIN_SUPPORT,
) -> set[int]:
    """Indices of boxes whose column is pinned by its **right** edge.

    A date or amount column is right-aligned: the right edges agree to the pixel
    while the left edges wander with the number of digits.  Pinning the left
    edge of such a column would push the whole column off by the width
    difference between two renderers, so the test is variance, not intent.
    """
    out: set[int] = set()
    for group in right_aligned_groups(boxes, tol=tol, min_rows=min_rows):
        out.update(group)
    return out


#: Two boxes closer than this vertically are the same row, not two rows.  A
#: right-aligned "column" needs three *rows*; three fragments of one row are a
#: coincidence, and they are the reason this guard exists.
ROW_MIN_GAP = 10


def _distinct_rows(
    boxes: Sequence[Sequence[int]],
    group: Sequence[int],
    *,
    min_gap: int = ROW_MIN_GAP,
) -> int:
    centres = sorted({int(boxes[index][1]) + int(boxes[index][3]) // 2 for index in group})
    rows = 0
    previous: int | None = None
    for centre in centres:
        if previous is None or centre - previous >= min_gap:
            rows += 1
            previous = centre
    return rows


def right_aligned_groups(
    boxes: Sequence[Sequence[int]],
    *,
    tol: int = GROUP_TOL,
    min_rows: int = GUIDE_MIN_SUPPORT,
) -> list[list[int]]:
    """Columns whose right edges agree better than their left ones.

    Grouping is done **twice**, once by left edge and once by right edge, and
    both candidate sets are tested.  Grouping by the left edge alone cannot see
    a right-aligned column at all: the whole point of such a column is that the
    left edge moves with the number of glyphs, so a wide value ("¥1,280.00")
    and a narrow one ("¥8") can sit 40px apart on the left while their right
    edges are identical.  A left-only pass splits them into singletons, drops
    them for lack of rows, and the column silently disappears.

    A candidate must also span at least ``min_rows`` distinct rows: several
    fragments sitting side by side on one line share a baseline but are not a
    column.
    """
    def cluster(key) -> list[list[int]]:
        order = sorted(range(len(boxes)), key=key)
        groups: list[list[int]] = []
        for index in order:
            value = key(index)
            if groups and value - key(groups[-1][-1]) <= tol:
                groups[-1].append(index)
            else:
                groups.append([index])
        return groups

    left_groups = cluster(lambda index: int(boxes[index][0]))
    right_groups = cluster(lambda index: int(boxes[index][0]) + int(boxes[index][2]))
    accepted: list[list[int]] = []
    seen: set[frozenset[int]] = set()
    for group in left_groups + right_groups:
        if len(group) < min_rows or _distinct_rows(boxes, group) < min_rows:
            continue
        key = frozenset(group)
        if key in seen:
            continue
        lefts = [float(int(boxes[index][0])) for index in group]
        rights = [float(int(boxes[index][0]) + int(boxes[index][2])) for index in group]
        widths = [float(int(boxes[index][2])) for index in group]
        # 同一列的成员必须落在"一个成员宽"之内。少了这条，三条互不相干的短文本
        # 只要右缘凑巧相差几像素就会被认成一列：CSDN 页上大标题（左缘 34）、
        # "867 阅读"（332）和"码龄 11 年"（332）右缘是 432/426/426，右缘 std 只有
        # 2.8，完全满足方差判据，于是标题被标成 text-align:right —— 而它是左对齐的。
        if max(lefts) - min(lefts) > median(widths):
            continue
        # 右对齐的是"字段"，不是"句子"。被截断的长句也会共用一条右缘（列表把每行
        # 主题都裁在同一列宽），左缘只抖 1~2px，于是左右 std 一高一低，方差判据照样
        # 通过——Gmail 的主题行就是这么被判成 right 的，而 Figma 一旦按右缘反算 x，
        # 字宽差就把整行推左，正是那个查了很多轮的整体左移。
        # 日期、金额这类真右对齐字段，宽度只有字高的几倍；长句远不止。
        heights = [float(int(boxes[index][3])) for index in group]
        if median(widths) > RIGHT_ALIGN_MAX_ASPECT * max(1.0, median(heights)):
            continue
        left_std = pstdev(lefts)
        right_std = pstdev(rights)
        # 右缘必须几乎纹丝不动，左缘必须真的在漂。两边都稳的是"等宽左对齐列"
        # （三个字一样多的导航标签），把它当右对齐只会让整列跟着字宽差漂移。
        if right_std <= RIGHT_ALIGN_STD and left_std >= RIGHT_ALIGN_MIN_DRIFT:
            seen.add(key)
            accepted.append(sorted(group))
    return accepted


def snap_box(
    box: Sequence[int],
    guides: Mapping[str, Any],
    *,
    tol: int = GUIDE_TOL,
    right_locked: bool = False,
    icon: bool = False,
) -> tuple[list[int], dict[str, Any]]:
    """Translate a box onto the nearest guide, and never further than ``tol``.

    Width is not negotiable: how wide a paragraph is comes from its font and its
    words, and no guide knows either.  So this only ever returns a translation,
    and each axis is decided by exactly one edge.
    """
    x, y, w, h = (int(value) for value in box[:4])
    info: dict[str, Any] = {"dx": 0, "dy": 0}
    vertical = guides.get("v") or []
    horizontal = guides.get("h") or []

    if right_locked:
        pick = _nearest(vertical, x + w)
        if pick is not None and abs(pick) <= tol:
            info["dx"] = pick
            info["edge"] = "right"
    else:
        candidates: list[tuple[int, int, str]] = []
        pick = _nearest(vertical, x)
        if pick is not None and abs(pick) <= tol:
            candidates.append((abs(pick), pick, "left"))
        if icon:
            pick = _nearest(vertical, x + w // 2)
            if pick is not None and abs(pick) <= tol:
                candidates.append((abs(pick), pick, "center"))
        else:
            pick = _nearest(vertical, x + w)
            if pick is not None and abs(pick) <= tol:
                candidates.append((abs(pick), pick, "right"))
        if candidates:
            # 偏差相同时按 left > right > center 定序，不用集合顺序。
            candidates.sort(key=lambda item: (item[0], {"left": 0, "right": 1, "center": 2}[item[2]]))
            info["dx"] = candidates[0][1]
            info["edge"] = candidates[0][2]

    if GUIDE_SNAP_AXIS_Y:
        pick = _nearest(horizontal, y + h // 2)
        if pick is not None and abs(pick) <= tol:
            info["dy"] = pick
            info["edge_y"] = "center"
    return [x + info["dx"], y + info["dy"], w, h], info


def _nearest(positions: Sequence[Mapping[str, Any]], value: int) -> int | None:
    best: int | None = None
    for item in positions:
        delta = int(item["pos"]) - int(value)
        if best is None or abs(delta) < abs(best):
            best = delta
    return best


def snap_boxes(
    boxes: Sequence[Sequence[int]],
    guides: Mapping[str, Any],
    *,
    tol: int = GUIDE_TOL,
    right_locked: Iterable[int] = (),
    icons: Iterable[int] = (),
) -> tuple[list[list[int]], dict[str, Any]]:
    locked = set(right_locked)
    icon_set = set(icons)
    out: list[list[int]] = []
    stats = {"snapped": 0, "moved": 0}
    for index, box in enumerate(boxes):
        snapped, info = snap_box(
            box,
            guides,
            tol=tol,
            right_locked=index in locked,
            icon=index in icon_set,
        )
        if info["dx"] or info["dy"]:
            stats["snapped"] += 1
            stats["moved"] += abs(int(info["dx"])) + abs(int(info["dy"]))
        out.append(snapped)
    return out, stats


# -------------------------------------------------------------------- master


def row_master(
    bands: Sequence[Mapping[str, Any]],
    boxes: Sequence[Sequence[int]],
    *,
    min_rows: int = MASTER_MIN_ROWS,
    height_tol: int = MASTER_HEIGHT_TOL,
) -> list[dict[str, Any]]:
    """One geometry for a run of isomorphic rows, so no row can drift alone.

    In a message list every row has the same shape, but not the same content: a
    row without an avatar starts its text where the avatar would have ended, and
    a row with a short subject ends early.  Measured individually, each is a
    little wrong in a different direction.  Measured as a run, the run has one
    left edge, one right edge and a set of column slots — and a row that disagrees
    with the run is the row that is wrong.

    "Isomorphic" is height and member count, nothing semantic: every row of a
    table and every row of a message list satisfies it, and no other grouping
    does.
    """
    rows: list[dict[str, Any]] = []
    for index, band in enumerate(bands):
        box = band.get("bbox")
        if not box or len(box) < 4:
            continue
        x, y, w, h = (int(value) for value in box[:4])
        member_indices = [
            member_index
            for member_index, item in enumerate(boxes)
            if len(item) >= 4
            and x - 8 <= int(item[0]) + int(item[2]) // 2 <= x + w + 8
            and y - 4 <= int(item[1]) + int(item[3]) // 2 <= y + h + 4
        ]
        # 一行只有一个元素也算一行：缺了头像的那一行正是只有文字的那一行，
        # 把它排除掉，母版就永远看不到"缺席"这回事。
        if not member_indices:
            continue
        rows.append({"index": index, "bbox": [x, y, w, h], "member_indices": member_indices})
    rows.sort(key=lambda item: item["bbox"][1])
    if len(rows) < min_rows:
        return []

    runs: list[list[dict[str, Any]]] = []
    for row in rows:
        if not runs:
            runs.append([row])
            continue
        last = runs[-1][-1]
        same_height = abs(row["bbox"][3] - last["bbox"][3]) <= height_tol
        same_members = abs(len(row["member_indices"]) - len(last["member_indices"])) <= 1
        adjacent = row["bbox"][1] - (last["bbox"][1] + last["bbox"][3]) <= height_tol
        if same_height and same_members and adjacent:
            runs[-1].append(row)
        else:
            runs.append([row])

    masters: list[dict[str, Any]] = []
    for run in runs:
        if len(run) < min_rows:
            continue
        counts = [len(row["member_indices"]) for row in run]
        # 一列每行只有一个元素，不像表格也不像列表，母版无从归纳。
        if median(counts) < 2:
            continue
        lefts = [row["bbox"][0] for row in run]
        rights = [row["bbox"][0] + row["bbox"][2] for row in run]
        member_indices = [index for row in run for index in row["member_indices"]]
        slots = _slots([boxes[index] for index in member_indices])
        modal = max(set(counts), key=counts.count)
        masters.append(
            {
                "band_indices": [row["index"] for row in run],
                "rows": [
                    {"band_index": row["index"], "members": list(row["member_indices"])}
                    for row in run
                ],
                "row_count": len(run),
                "x_start": int(round(median(lefts))),
                "x_end": int(round(median(rights))),
                "top": min(row["bbox"][1] for row in run),
                "bottom": max(row["bbox"][1] + row["bbox"][3] for row in run),
                "slots": slots,
                "modal_members": modal,
                "member_indices": member_indices,
            }
        )
    return masters


def _slots(boxes: Sequence[Sequence[int]], *, tol: int = MASTER_SLOT_TOL) -> list[dict[str, Any]]:
    """Column slots of a row run: where the cells start, and how they align."""
    groups: list[list[int]] = []
    order = sorted(range(len(boxes)), key=lambda index: int(boxes[index][0]))
    for index in order:
        x = int(boxes[index][0])
        if groups and x - int(boxes[groups[-1][-1]][0]) <= tol:
            groups[-1].append(index)
        else:
            groups.append([index])
    slots: list[dict[str, Any]] = []
    for group in groups:
        if len(group) < 2:
            continue
        lefts = [float(int(boxes[index][0])) for index in group]
        rights = [float(int(boxes[index][0]) + int(boxes[index][2])) for index in group]
        left_std = pstdev(lefts) if len(lefts) > 1 else 0.0
        right_std = pstdev(rights) if len(rights) > 1 else 0.0
        slots.append(
            {
                "left": int(round(median(lefts))),
                "right": int(round(median(rights))),
                "members": len(group),
                "align": "right" if right_std <= RIGHT_ALIGN_STD and right_std < left_std else "left",
            }
        )
    slots.sort(key=lambda item: item["left"])
    return slots


def apply_master(
    bands: list[dict[str, Any]],
    boxes: list[list[int]],
    masters: Sequence[Mapping[str, Any]],
    *,
    tol: int = MASTER_SLOT_TOL,
) -> dict[str, Any]:
    """Give every row of a run the run's left edge, right edge and slot basis.

    Two different tolerances, because two different failures:

    * a row with the **same number of members** as the run is merely jittery, so
      it may only move within ``tol``;
    * a row with **fewer members** is missing something — an avatar, a checkbox,
      a leading badge — and the gap that missing element left is not jitter, it
      is one whole slot wide.  That row gets the master's first slot even though
      the distance is larger than ``tol``, capped at one slot pitch so a real
      indent still survives.
    """
    stats = {"rows": 0, "boxes": 0, "deficient_rows": 0}
    for master in masters:
        slots = [slot["left"] for slot in master["slots"]]
        right_slots = [slot["right"] for slot in master["slots"] if slot["align"] == "right"]
        pitch = 0
        if len(slots) >= 2:
            pitch = min(
                (slots[index + 1] - slots[index] for index in range(len(slots) - 1)),
                default=0,
            )
        for row in master["rows"]:
            band_index = int(row["band_index"])
            deficient = len(row["members"]) < int(master["modal_members"])
            allow = max(tol, pitch) if deficient else tol
            if deficient:
                stats["deficient_rows"] += 1
            if band_index < len(bands):
                box = bands[band_index].get("bbox")
                if box and len(box) >= 4:
                    box[0] = int(master["x_start"])
                    box[2] = max(1, int(master["x_end"]) - int(master["x_start"]))
                    stats["rows"] += 1
            for member_index in row["members"]:
                if member_index >= len(boxes):
                    continue
                box = boxes[member_index]
                x, y, w, h = (int(value) for value in box[:4])
                pick = None
                for slot in slots:
                    if abs(slot - x) <= allow and (pick is None or abs(slot - x) < abs(pick - x)):
                        pick = slot
                if pick is not None and pick != x:
                    box[0] = int(pick)
                    stats["boxes"] += 1
                    continue
                for slot in right_slots:
                    if abs(slot - (x + w)) <= allow:
                        box[0] = int(slot) - w
                        stats["boxes"] += 1
                        break
    return stats
