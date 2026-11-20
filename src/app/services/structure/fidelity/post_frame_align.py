"""Column alignment that runs *after* the frames are locked.

The perception layer already knows how to find a column: three elements whose
left edges agree within a few pixels are a margin, and a column whose right
edges agree while its left edges wander is right-aligned (dates, amounts, unread
counts).  Applying that knowledge before framing was measured and lost: moving a
box by 5px can put it outside the band that owns it, and a band that loses its
members stops being a frame.  worklog gained 0.60 of similarity and lost a frame
in the same move, and the two could not be separated.

So the grid moves here, behind ``_keep_renderable_frames``: the frame's member
list and every element's vertical extent are already decided, and this pass is
only allowed to slide members **horizontally**.  A member that stays inside the
frame that already owns it cannot change the frame count, so the alignment can be
judged on similarity alone.

The one thing this must *not* inherit from the perception-layer version is the
scope.  Framing produces one frame per *row* — a message list is thirteen frames
of four texts each — and inside a single row every text is its own column.  The
columns only exist across rows, so the guides are built over the whole page and
the frames are used for one thing only: the boundary a member may not cross.

What it deliberately does not do: touch ``y`` or ``height`` (that is what broke
framing), change a member's width, add or remove members.
"""

from __future__ import annotations

from statistics import median, pstdev
from typing import Any, Mapping, Sequence

#: How close two edges must be to count as the same column.  Two to five pixels
#: is the disagreement between OCR ink boxes, OmniParser crops and CV regions;
#: anything larger is a real difference of position, not measurement noise.
COLUMN_TOL = 5
#: Two elements agreeing is a coincidence.  Three is a margin.
MIN_SUPPORT = 3
#: Never slide a member further than this to reach a guide.  Past it the member
#: is not misaligned, it is indented on purpose.
MAX_SHIFT = 5
#: Looser grouping used only to *test* a column for right alignment: a date
#: column's left edges drift with the number of digits, and if the grouping were
#: as tight as the snap tolerance it would split the column into singletons and
#: never get to look at the right edges.
GROUP_TOL = 12
#: Right alignment: the right edges agree this well and better than the lefts.
RIGHT_STD = 3.0

#: Master switch.  Set false to make this pass a no-op without touching the
#: call site, which is how the ablation in NOTES §7 was measured.
#:
#: 2026-11-16 实测（三张盲测页，P0/P1 修复为基线）：
#:   X 单开   → erp +0.00 / worklog +0.00 / gmail −0.01  （持平，动 17 处）
#:   X+Y     → gmail 由 +0.05 掉到 −0.02
#:   +字宽   → gmail −0.22
#: 三项均无正收益，按"实证优先"全关；帧数在所有组合下都是 10/3/13 零变化。
POST_FRAME_ALIGN_ENABLED = False
#: Images are crops of the original pixels; sliding them by 5px trades a column
#: that lines up for a picture that no longer sits on its own content.
ALIGN_IMAGES = False

# ------------------------------------------------------------------ baselines

#: 同一行的元素，纵向中心差在这个范围内才算一行。
Y_TOL = 4
#: 三个元素同高才是行；两个是巧合。
Y_MIN_SUPPORT = 3
#: 纵向最多挪这么多。再远就不是"没对齐"，是"本来就在另一行"。
Y_MAX_SHIFT = 4
#: 纵向对齐开关。它改 `y`，比横向危险一档，所以单独一个开关。
POST_FRAME_Y_ENABLED = False

# ------------------------------------------------------------------ ink span

#: 少于这个字数不谈字宽：短词的墨迹框与渲染宽度本来就对不齐。
INK_MIN_CHARS = 4
#: 窄于这个宽度的文本不谈：图标旁的标签误差占比太大。
INK_MIN_WIDTH = 80
#: 预估宽度与墨迹宽度差小于这个值就不动，那是舍入不是错。
INK_MIN_DELTA = 3
#: 字距微调钳制区间（px/字）。再大就不是字距，是换字体。
LETTER_MIN = -0.8
LETTER_MAX = 1.2
#: 字宽跨度校准开关。
POST_FRAME_INK_ENABLED = False


def _rect(element: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    try:
        return (
            float(element.get("x") or 0),
            float(element.get("y") or 0),
            float(element.get("width") or 0),
            float(element.get("height") or 0),
        )
    except (TypeError, ValueError):
        return None


def _cluster(
    values: Sequence[tuple[float, int]],
    *,
    tol: int,
    min_support: int,
) -> list[tuple[int, list[int]]]:
    """Group (coordinate, member) pairs that agree, and report the group.

    Single-link grouping over sorted coordinates, then a validation pass: the
    median must have at least ``min_support`` members within ``tol`` of it, and
    the group may not span more than ``2 * tol``.  Without those two checks a
    drifting column chains into one group whose median nobody occupies, and
    everything within tolerance gets dragged onto a coordinate that does not
    exist in the picture.
    """
    ordered = sorted(values, key=lambda item: item[0])
    groups: list[list[tuple[float, int]]] = []
    for value in ordered:
        if groups and value[0] - groups[-1][-1][0] <= tol:
            groups[-1].append(value)
        else:
            groups.append([value])
    out: list[tuple[int, list[int]]] = []
    for group in groups:
        coords = [value for value, _ in group]
        if max(coords) - min(coords) > 2 * tol:
            continue
        pos = int(round(median(coords)))
        members = [index for value, index in group if abs(value - pos) <= tol]
        if len(members) < min_support:
            continue
        out.append((pos, members))
    return out


def _right_column(
    members: Sequence[int],
    elements: Sequence[Mapping[str, Any]],
) -> list[tuple[int, list[int]]]:
    """Right edges that agree while the left edge wanders — a date column."""
    groups: list[list[int]] = []
    order = sorted(members, key=lambda index: float(elements[index].get("x") or 0))
    for index in order:
        x = float(elements[index].get("x") or 0)
        if groups and x - float(elements[groups[-1][-1]].get("x") or 0) <= GROUP_TOL:
            groups[-1].append(index)
        else:
            groups.append([index])
    out: list[tuple[int, list[int]]] = []
    for group in groups:
        if len(group) < MIN_SUPPORT:
            continue
        lefts = [float(elements[index].get("x") or 0) for index in group]
        rights = [
            float(elements[index].get("x") or 0) + float(elements[index].get("width") or 0)
            for index in group
        ]
        left_std = pstdev(lefts) if len(lefts) > 1 else 0.0
        right_std = pstdev(rights) if len(rights) > 1 else 0.0
        if right_std <= RIGHT_STD and right_std < left_std:
            out.append((int(round(median(rights))), group))
    return out


def _frame_owners(
    elements: Sequence[Mapping[str, Any]],
) -> dict[int, tuple[float, float, float, float]]:
    """Every framed element mapped to the rectangle of the frame that owns it."""
    by_id = {str(element.get("id")): index for index, element in enumerate(elements)}
    owners: dict[int, tuple[float, float, float, float]] = {}
    for frame in elements:
        children = frame.get("layoutChildren")
        if not children:
            continue
        rect = _rect(frame)
        if rect is None or rect[2] <= 0 or rect[3] <= 0:
            continue
        for child in children:
            if not isinstance(child, Mapping):
                continue
            index = by_id.get(str(child.get("id")))
            if index is None or index in owners:
                continue
            owners[index] = rect
    return owners


def align_frame_columns(
    elements: list[dict[str, Any]],
    *,
    tol: int = COLUMN_TOL,
    max_shift: int = MAX_SHIFT,
) -> dict[str, Any]:
    """Slide each framed member onto the page's columns, sideways only."""
    stats: dict[str, Any] = {"frames": 0, "columns": 0, "moved": 0, "shift": 0}
    if not POST_FRAME_ALIGN_ENABLED:
        return stats

    owners = _frame_owners(elements)
    if not owners:
        return stats
    types = {"text", "image"} if ALIGN_IMAGES else {"text"}
    members = [
        index
        for index in owners
        if str(elements[index].get("type")) in types
    ]
    if len(members) < MIN_SUPPORT:
        return stats
    stats["frames"] = sum(1 for element in elements if element.get("layoutChildren"))

    # 先认右对齐列，再认左缘列：右对齐的列左缘本来就在漂，它不该被钉左缘。
    rights = _right_column(members, elements)
    pinned: set[int] = set()
    targets: dict[int, tuple[str, int]] = {}
    for pos, group in rights:
        for index in group:
            targets[index] = ("right", pos)
            pinned.add(index)
    lefts = _cluster(
        [
            (float(elements[index].get("x") or 0), index)
            for index in members
            if index not in pinned
        ],
        tol=tol,
        min_support=MIN_SUPPORT,
    )
    stats["columns"] = len(rights) + len(lefts)
    for pos, group in lefts:
        for index in group:
            targets.setdefault(index, ("left", pos))

    for index, (edge, pos) in targets.items():
        element = elements[index]
        x = float(element.get("x") or 0)
        width = float(element.get("width") or 0)
        delta = pos - (x + width) if edge == "right" else pos - x
        if delta == 0 or abs(delta) > max_shift:
            continue
        new_x = x + delta
        # 归属不变：成员必须还在它已经在的那个帧里。这一条是本节存在的理由，
        # 所以每次移动都要过一遍，而不是只在入口判一次。
        fx, _fy, fw, _fh = owners[index]
        if new_x < fx - 1 or new_x + width > fx + fw + 1:
            continue
        element["x"] = round(new_x, 2)
        stats["moved"] += 1
        stats["shift"] += abs(int(round(delta)))
    return stats


# ----------------------------------------------------------- shared geometry


def _owner_map(
    elements: Sequence[Mapping[str, Any]],
) -> dict[int, tuple[float, float, float, float] | None]:
    """Every element's smallest direct container, frames and table cells alike.

    Framing only assigns frame members, but the rows of a borderless table live
    in a ``table`` element and the leaves of a plain region live in a ``panel``.
    Looking only at ``layoutChildren`` would leave those texts with no boundary
    to respect, so the owner is computed from geometry here instead.
    """
    containers: list[tuple[float, int, tuple[float, float, float, float]]] = []
    for index, element in enumerate(elements):
        if str(element.get("type")) not in ("container", "table"):
            continue
        rect = _rect(element)
        if rect is None or rect[2] <= 0 or rect[3] <= 0:
            continue
        containers.append((rect[2] * rect[3], index, rect))
    containers.sort()
    owners: dict[int, tuple[float, float, float, float] | None] = {}
    for index, element in enumerate(elements):
        rect = _rect(element)
        if rect is None:
            owners[index] = None
            continue
        cx = rect[0] + rect[2] / 2
        cy = rect[1] + rect[3] / 2
        owner = None
        for _area, _position, candidate in containers:
            if (
                candidate[0] <= cx <= candidate[0] + candidate[2]
                and candidate[1] <= cy <= candidate[1] + candidate[3]
            ):
                owner = candidate
                break
        owners[index] = owner
    return owners


def _intersects(left, right) -> bool:
    return (
        min(left[0] + left[2], right[0] + right[2]) - max(left[0], right[0]) > 0
        and min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1]) > 0
    )


# ---------------------------------------------------------------- baselines


def align_baselines(elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Put texts that share a line onto one centre, sideways neighbours only.

    Horizontal alignment fixed the columns but left every row's text at its own
    measured height, and a list row that sits 3px high reads as a row that is
    wrong even when every column is right.  This is the pass that buys the
    similarity the perception-layer version could not: it runs after framing, so
    the only thing that can go wrong is an element leaving its container, which
    is checked on every move.
    """
    stats: dict[str, Any] = {"rows": 0, "moved": 0, "shift": 0}
    if not POST_FRAME_Y_ENABLED:
        return stats

    rects = {index: _rect(element) for index, element in enumerate(elements)}
    owners = _owner_map(elements)
    groups: dict[int | None, list[int]] = {}
    for index, element in enumerate(elements):
        if str(element.get("type")) != "text" or not str(element.get("text") or "").strip():
            continue
        if rects.get(index) is None:
            continue
        groups.setdefault(-1 if owners.get(index) is None else id(owners[index]), []).append(index)

    for _, indices in groups.items():
        if len(indices) < Y_MIN_SUPPORT:
            continue
        clusters: list[list[tuple[float, int]]] = []
        for index in sorted(indices, key=lambda item: rects[item][1] + rects[item][3] / 2):
            centre = rects[index][1] + rects[index][3] / 2
            if clusters and centre - clusters[-1][-1][0] <= Y_TOL:
                clusters[-1].append((centre, index))
            else:
                clusters.append([(centre, index)])
        for cluster in clusters:
            # 同一行里横向不许重叠：重叠的两段字是嵌套或同一处印了两遍，
            # 把它们拉到同一中心只会加深重影。
            run: list[int] = []
            for _centre, index in sorted(cluster, key=lambda item: rects[item[1]][0]):
                if run and rects[index][0] < rects[run[-1]][0] + rects[run[-1]][2] - 1:
                    continue
                run.append(index)
            if len(run) < Y_MIN_SUPPORT:
                continue
            stats["rows"] += 1
            target = median([rects[index][1] + rects[index][3] / 2 for index in run])
            for index in run:
                rect = rects[index]
                delta = target - (rect[1] + rect[3] / 2)
                if abs(delta) < 0.5 or abs(delta) > Y_MAX_SHIFT:
                    continue
                new_y = rect[1] + delta
                container = owners.get(index)
                if container is not None and not (
                    container[1] - 1 <= new_y
                    and new_y + rect[3] <= container[1] + container[3] + 1
                ):
                    continue
                moved = (rect[0], new_y, rect[2], rect[3])
                clash = False
                for other in indices:
                    if other == index:
                        continue
                    before = _intersects(rect, rects[other])
                    if not before and _intersects(moved, rects[other]):
                        clash = True
                        break
                if clash:
                    continue
                elements[index]["y"] = round(new_y, 2)
                rects[index] = moved
                stats["moved"] += 1
                stats["shift"] += abs(int(round(delta)))
    return stats


# ---------------------------------------------------------------- ink span


def calibrate_ink_span(elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Make the drawn glyph run as wide as the ink it was measured from.

    OCR boxes are ink-tight, so the box width already *is* the target width —
    what is wrong is the string inside it: the real face is a few percent wider
    or narrower than the one the layout assumed, and across a forty-word column
    that difference accumulates into the drift that no coordinate snap can fix.

    Only ``letterSpacing`` is written, never the box width.  Resizing the box
    changes the wrap decision (which is made from the same measurement), and a
    one-line label that suddenly wraps costs far more than the drift it fixes.
    """
    stats: dict[str, Any] = {"texts": 0, "tuned": 0}
    if not POST_FRAME_INK_ENABLED:
        return stats
    try:
        from src.app.services.structure.fidelity.font_metrics import text_width
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return stats

    owners = _owner_map(elements)
    for index, element in enumerate(elements):
        if str(element.get("type")) != "text":
            continue
        text = str(element.get("text") or "")
        if len(text) < INK_MIN_CHARS:
            continue
        style = element.get("style") or {}
        try:
            font_size = float(style.get("fontSize") or 0)
        except (TypeError, ValueError):
            continue
        rect = _rect(element)
        if font_size <= 0 or rect is None or rect[2] < INK_MIN_WIDTH:
            continue
        if str(style.get("textAlign") or "left").lower() not in ("", "left"):
            continue
        estimated = float(text_width(text, font_size))
        delta = rect[2] - estimated
        if abs(delta) < INK_MIN_DELTA:
            continue
        spacing = delta / max(len(text) - 1, 1)
        spacing = max(LETTER_MIN, min(LETTER_MAX, spacing))
        if abs(spacing) < 0.02:
            continue
        # 字距会把整段字推宽，右端可能越出父容器：越界就不动。
        container = owners.get(index)
        if container is not None and rect[0] + max(rect[2], estimated + spacing * (len(text) - 1)) > container[0] + container[2] + 1:
            continue
        style["letterSpacing"] = round(spacing, 2)
        element["style"] = style
        stats["texts"] += 1
        stats["tuned"] += 1
    return stats
