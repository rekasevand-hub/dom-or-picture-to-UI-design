"""Measure native text and chrome separately without changing acceptance."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any


def _text_nodes(readback: Any) -> list[Mapping[str, Any]]:
    nodes: list[Mapping[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            if value.get("type") == "TEXT" and value.get("characters"):
                nodes.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(readback)
    return nodes


def _normalized_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, width, height = (int(round(float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    return [x, y, width, height] if width > 0 and height > 0 else None


def _text_node_boxes(readback_tree: Any) -> list[dict[str, Any]]:
    """Absolute boxes of the TEXT nodes, in the root frame's coordinate space.

    The gate must measure each owner inside the box the emitter actually gave
    it.  ``styleEvidence.source_bbox`` is a *grounding* box: on a price cell it
    spans several tokens, and a single TEXT node can never match its width.
    """
    root = readback_tree if isinstance(readback_tree, Mapping) else {}
    boxes: list[dict[str, Any]] = []

    def walk(node: Any, origin_x: float, origin_y: float) -> None:
        if isinstance(node, Mapping):
            bounds = node.get("bounds")
            local = bounds if isinstance(bounds, Mapping) else node
            x = origin_x + _number(local.get("x"), 0.0)
            y = origin_y + _number(local.get("y"), 0.0)
            if node.get("type") == "TEXT" and str(node.get("characters") or ""):
                box = _normalized_bbox(
                    [
                        x,
                        y,
                        _number(local.get("width"), 0.0),
                        _number(local.get("height"), 0.0),
                    ]
                )
                if box is not None:
                    boxes.append(
                        {
                            "characters": str(node.get("characters") or ""),
                            "normalized": _compact_gate_text(node.get("characters")),
                            "box": box,
                        }
                    )
            for child in node.get("children") or []:
                walk(child, x, y)
        elif isinstance(node, list):
            for child in node:
                walk(child, origin_x, origin_y)

    for child in root.get("children") or []:
        walk(child, 0.0, 0.0)
    return boxes


def _select_node_box(
    text: str,
    element: Mapping[str, Any],
    node_boxes: Sequence[Mapping[str, Any]],
) -> list[int] | None:
    """The emitted node's own box for this owner, or ``None`` if it never landed.

    Duplicate strings are disambiguated by centre distance to the element's own
    box.  That is a matching decision only -- nothing is measured from it -- so
    it cannot make a misplaced node look correct.
    """
    wanted = _compact_gate_text(text)
    if not wanted:
        return None
    candidates = [item for item in node_boxes if item.get("normalized") == wanted]
    if not candidates:
        return None
    element_box = _normalized_bbox(
        [
            _number(element.get("x"), 0.0),
            _number(element.get("y"), 0.0),
            _number(element.get("width"), 0.0),
            _number(element.get("height"), 0.0),
        ]
    )
    if element_box is None or len(candidates) == 1:
        return list(candidates[0]["box"])
    element_cx = element_box[0] + element_box[2] / 2.0
    element_cy = element_box[1] + element_box[3] / 2.0
    return list(
        min(
            candidates,
            key=lambda item: (
                (item["box"][0] + item["box"][2] / 2.0 - element_cx) ** 2
                + (item["box"][1] + item["box"][3] / 2.0 - element_cy) ** 2
            ),
        )["box"]
    )


def _halo_bbox(
    bbox: list[int],
    halo_px: int,
    image_shape: tuple[int, int],
) -> list[int] | None:
    height, width = image_shape
    x, y, box_width, box_height = bbox
    left = max(0, x - halo_px)
    top = max(0, y - halo_px)
    right = min(width, x + box_width + halo_px)
    bottom = min(height, y + box_height + halo_px)
    if right <= left or bottom <= top:
        return None
    return [left, top, right - left, bottom - top]


def _contrast_mask(region: Any) -> Any:
    import numpy as np

    values = region.reshape(-1, 3)
    background = np.median(values, axis=0)
    return np.max(np.abs(region - background), axis=2) > 50


def _ink_bbox(mask: Any, bbox: list[int]) -> list[int] | None:
    import numpy as np

    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    x, y, _width, _height = bbox
    return [
        x + int(xs.min()),
        y + int(ys.min()),
        int(xs.max()) - int(xs.min()) + 1,
        int(ys.max()) - int(ys.min()) + 1,
    ]


def _clip_sides(ink: list[int], window: list[int], tolerance: int = 1) -> list[str]:
    """Which edges of ``window`` the ink sits on.

    Touching an edge is *necessary* but not sufficient proof that the glyph run
    was cut: a run can genuinely end exactly on the boundary.  It is still the
    only signal available offline, so the flag names the sides and lets the
    reader judge -- it never feeds a check.

    Why it matters: the reference window is the **emitted node box** plus
    ``box_pad_px``, so a reference run wider than our own box is truncated to
    it.  The width comparison then degrades to "does our ink fill our box" and
    cannot punish a render that is *wider* than the reference.  Measured
    2026-11-13: widening or narrowing that window loses owners (four variants,
    A 194 > B 183 > D 169 > C 155), and setting ``box_pad_px`` to 0 fakes a
    +11 because 18 of its 22 gains leave the reference clipped.
    """
    wx, wy, ww, wh = window
    sides: list[str] = []
    if ink[0] <= wx + tolerance:
        sides.append("left")
    if ink[0] + ink[2] >= wx + ww - tolerance:
        sides.append("right")
    if ink[1] <= wy + tolerance:
        sides.append("top")
    if ink[1] + ink[3] >= wy + wh - tolerance:
        sides.append("bottom")
    return sides


def _union_bbox(a: list[int], b: list[int]) -> list[int]:
    x1 = min(a[0], b[0])
    y1 = min(a[1], b[1])
    x2 = max(a[0] + a[2], b[0] + b[2])
    y2 = max(a[1] + a[3], b[1] + b[3])
    return [x1, y1, x2 - x1, y2 - y1]


def _column_runs(mask: Any, gap_px: int) -> list[list[int]]:
    """列投影后按间隔切 run，返回 [[x0, x1], ...]（窗口内相对坐标，含端点）。"""
    columns = mask.any(axis=0)
    runs: list[list[int]] = []
    start: int | None = None
    blanks = 0
    for index, ink in enumerate(columns):
        if ink:
            if start is None:
                start = index
            blanks = 0
        elif start is not None:
            blanks += 1
            if blanks > gap_px:
                runs.append([start, index - blanks])
                start = None
                blanks = 0
    if start is not None:
        runs.append([start, len(columns) - 1 - blanks])
    return runs


def _select_span(
    runs: list[list[int]], window: list[int], node: list[int], min_inside: float = 0.5
) -> list[int] | None:
    """保留「至少一半宽度落在节点框里」的 run 并合并。

    节点框是我们自己发射的位置，是这条链上最可靠的先验：框内的墨多半属于这条文本，
    框外一整段（图标、箭头、邻居标签）不属于。多词串会拆成多个 run，但它们都在框内，
    合并后就是整串 —— 同一条规则同时解决「切错」和「吞邻居」。
    """
    if not runs:
        return None
    nx0, nx1 = node[0], node[0] + node[2]
    kept: list[list[int]] = []
    for x0, x1 in runs:
        rx0, rx1 = window[0] + x0, window[0] + x1
        inside = min(rx1 + 1, nx1) - max(rx0, nx0)
        width = rx1 - rx0 + 1
        if width > 0 and inside / width >= min_inside:
            kept.append([x0, x1])
    if not kept:
        # 一个都没过线（文本整体比框宽很多）时退回重叠最大的那一段，不制造空值
        best = max(
            runs,
            key=lambda run: min(window[0] + run[1] + 1, nx1)
            - max(window[0] + run[0], nx0),
        )
        kept = [best]
    return [min(run[0] for run in kept), max(run[1] for run in kept)]


def _ink_from_span(mask: Any, window: list[int], span: list[int]) -> list[int] | None:
    import numpy as np

    x0, x1 = span
    sub = mask[:, x0 : x1 + 1]
    rows = np.where(sub.any(axis=1))[0]
    if len(rows) == 0:
        return None
    return [
        window[0] + x0,
        window[1] + int(rows.min()),
        x1 - x0 + 1,
        int(rows.max() - rows.min()) + 1,
    ]


def _selected_ink(
    mask: Any,
    window: list[int],
    node: list[int],
    em: float,
    gap_em: float,
    enabled: bool,
) -> list[int] | None:
    # 没有节点框（grounding-box 兜底）时没有先验可选，退回整窗取墨
    if not enabled or node is None:
        return _ink_bbox(mask, window)
    runs = _column_runs(mask, max(2, int(round(gap_em * em))))
    span = _select_span(runs, window, node)
    if span is None:
        return _ink_bbox(mask, window)
    return _ink_from_span(mask, window, span)


def _failure_class(
    checks: Mapping[str, bool],
    clip_sides: list[str],
    delta_x: int,
    delta_y: int,
    width_delta: int,
    height_delta: int,
    width_tolerance: int,
    height_tolerance: int,
    position_max: int,
) -> str:
    """把一条失败归到某一类，只记账，不改 `status`。

    分类顺序就是判据的因果顺序，每一步都能用现有读数复核：

    1. 四维全过 → ``pass``。
    2. **未贴边的轴上有位移** → ``mechanical``。位移是真的，跟字形无关：
       `系统运行正常` dy −6 就是这一类（真因是图标与文本间的间距没发射）。
    3. **只有贴边轴上的位移** → ``instrument-capped``。参考墨迹贴着窗口边时，
       那个方向的位置/宽度读数被封顶（见 `_clip_sides`），不能当硬失败。
    4. **宽超、高在容差内、且横向未贴边** → ``typeface-advance``。拉丁字的
       advance 与字族绑定，一个字号无法同时满足高与宽（`REQ-OIBFZVUES`：
       高 +10.5%、宽 +3.5%）。CJK 的 advance 恒为 1em，不走这一支。
    5. 尺寸失败但至少一个未贴边轴 → ``mechanical``（缩放/字号能修）。
    6. 几何全过、只有 coverage/edgeF1 差 → ``typeface-glyph``。面积对、边缘对不上
       只能是字形不同（`内容正在审核中`、`检查状态`）。

    注意第 4 条不是「高宽不自洽」的几何判断，而是**位移干净**这个前提下的宽度轴判断：
    `系统运行正常` 同样「宽超、高在容差内」，但它还有位移，第 2 条先把它拦走了。
    这是 2026-11-13 归因实测的结果，不是先验。
    """
    if all(checks.values()):
        return "pass"
    x_clipped = "left" in clip_sides or "right" in clip_sides
    y_clipped = "top" in clip_sides or "bottom" in clip_sides
    pos_x_bad = abs(delta_x) > position_max
    pos_y_bad = abs(delta_y) > position_max
    if (pos_x_bad and not x_clipped) or (pos_y_bad and not y_clipped):
        return "mechanical"
    if (pos_x_bad and x_clipped) or (pos_y_bad and y_clipped):
        return "instrument-capped"
    size_w_bad = abs(width_delta) > width_tolerance
    size_h_bad = abs(height_delta) > height_tolerance
    if size_w_bad or size_h_bad:
        if size_w_bad and not size_h_bad and not x_clipped:
            return "typeface-advance"
        if (size_w_bad and not x_clipped) or (size_h_bad and not y_clipped):
            return "mechanical"
        return "instrument-capped"
    return "typeface-glyph"


def _text_ink_mask(region: Any) -> Any:
    """Contrast mask with thin divider lines removed.

    ``ink_support`` (the upstream reference measurement) suppresses rows and
    columns that span most of the crop.  Copied verbatim, that rule also eats
    every row of a dense label once the crop is tight around the text, so the
    suppression is limited here to bands no thicker than two pixels -- the
    shape a table rule actually has.
    """
    mask = _contrast_mask(region)
    height, width = mask.shape

    def _drop_thin_bands(flags: Any, limit: int) -> list[int]:
        dropped: list[int] = []
        start = None
        for index, flag in enumerate(list(flags) + [False]):
            if flag and start is None:
                start = index
            elif not flag and start is not None:
                if index - start <= limit:
                    dropped.extend(range(start, index))
                start = None
        return dropped

    full_rows = mask.sum(axis=1) >= max(4, int(round(width * 0.8)))
    for row in _drop_thin_bands(full_rows, 2):
        mask[row, :] = False
    full_columns = mask.sum(axis=0) >= max(4, int(round(height * 0.8)))
    for column in _drop_thin_bands(full_columns, 2):
        mask[:, column] = False
    return mask


def _edge_mask(mask: Any) -> Any:
    import numpy as np

    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    eroded = np.ones_like(mask, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            eroded &= padded[
                1 + dy : 1 + dy + mask.shape[0],
                1 + dx : 1 + dx + mask.shape[1],
            ]
    return mask & ~eroded


def _dilate(mask: Any) -> Any:
    import numpy as np

    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    output = np.zeros_like(mask, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            output |= padded[
                1 + dy : 1 + dy + mask.shape[0],
                1 + dx : 1 + dx + mask.shape[1],
            ]
    return output


def _edge_f1(reference_mask: Any, rendered_mask: Any) -> float | None:
    reference_edge = _edge_mask(reference_mask)
    rendered_edge = _edge_mask(rendered_mask)
    if not reference_edge.any() and not rendered_edge.any():
        return 1.0
    if not reference_edge.any() or not rendered_edge.any():
        return 0.0
    matched_reference = reference_edge & _dilate(rendered_edge)
    matched_rendered = rendered_edge & _dilate(reference_edge)
    precision = float(matched_rendered.sum()) / float(rendered_edge.sum())
    recall = float(matched_reference.sum()) / float(reference_edge.sum())
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _mask_edge_f1(
    reference_mask: Any,
    rendered_mask: Any,
    reference_ink: list[int],
    rendered_ink: list[int],
    origin: tuple[int, int],
) -> float | None:
    union_x = min(reference_ink[0], rendered_ink[0])
    union_y = min(reference_ink[1], rendered_ink[1])
    union_right = max(
        reference_ink[0] + reference_ink[2],
        rendered_ink[0] + rendered_ink[2],
    )
    union_bottom = max(
        reference_ink[1] + reference_ink[3],
        rendered_ink[1] + rendered_ink[3],
    )
    x, y = origin
    return _edge_f1(
        reference_mask[
            union_y - y : union_bottom - y,
            union_x - x : union_right - x,
        ],
        rendered_mask[
            union_y - y : union_bottom - y,
            union_x - x : union_right - x,
        ],
    )


def _region_mask(shape: tuple[int, int], bbox: list[int]) -> Any:
    import numpy as np

    mask = np.zeros(shape, dtype=bool)
    x, y, width, height = bbox
    mask[
        max(0, y) : min(shape[0], y + height),
        max(0, x) : min(shape[1], x + width),
    ] = True
    return mask


def _number(value: Any, default: float) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_gate_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _compact_gate_text(value: Any) -> str:
    """Identity form of a label: punctuation folded, all whitespace removed.

    ``_normalize_gate_text`` turns punctuation into spaces, so ``5.8折`` and
    ``5.8\n折`` normalise to ``5 8折`` and ``5 8 折`` -- different strings for
    the same label.  Identity comparisons use this compact form.
    """
    return re.sub(r"\s+", "", _normalize_gate_text(value))


def _critical_text_matches(expected: Any, actual: Any) -> bool:
    expected_text = _normalize_gate_text(expected)
    actual_text = _normalize_gate_text(actual)
    if not expected_text or not actual_text:
        return False
    if expected_text in actual_text:
        return True
    if any("\u4e00" <= char <= "\u9fff" for char in expected_text):
        compact_expected = re.sub(r"\s+", "", expected_text)
        compact_actual = re.sub(r"\s+", "", actual_text)
        return compact_expected in compact_actual
    return False


def _boxes_adjacent(
    left: Sequence[int],
    right: Sequence[int],
    *,
    max_gap_px: int,
) -> bool:
    """Whether two ink boxes are close enough to form one logical label."""
    left_x, left_y, left_width, left_height = left
    right_x, right_y, right_width, right_height = right
    horizontal_gap = max(
        right_x - (left_x + left_width),
        left_x - (right_x + right_width),
    )
    vertical_gap = max(
        right_y - (left_y + left_height),
        left_y - (right_y + right_height),
    )
    vertical_overlap = min(
        left_y + left_height,
        right_y + right_height,
    ) - max(left_y, right_y)
    horizontal_overlap = min(
        left_x + left_width,
        right_x + right_width,
    ) - max(left_x, right_x)
    same_line = horizontal_gap <= max_gap_px and vertical_overlap >= max(
        1, min(left_height, right_height) // 2
    )
    stacked = vertical_gap <= max_gap_px and horizontal_overlap >= max(
        1, min(left_width, right_width) // 2
    )
    return same_line or stacked


def _cluster_is_adjacent(
    indexes: Sequence[int],
    owners: Sequence[Mapping[str, Any]],
    *,
    max_gap_px: int,
) -> bool:
    boxes = [owners[index].get("referenceInkBBox") for index in indexes]
    if any(not isinstance(box, Sequence) or len(box) != 4 for box in boxes):
        return False
    count = len(indexes)
    adjacency: list[list[int]] = [[] for _ in range(count)]
    for left in range(count):
        for right in range(left + 1, count):
            if _boxes_adjacent(boxes[left], boxes[right], max_gap_px=max_gap_px):
                adjacency[left].append(right)
                adjacency[right].append(left)
    visited: set[int] = set()
    stack = [0]
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(adjacency[node])
    return len(visited) == count


def _logical_cluster_for_expected(
    expected: Any,
    owners: Sequence[Mapping[str, Any]],
    *,
    exclude: set[int],
    max_cluster_size: int = 4,
    max_gap_px: int = 8,
) -> list[int] | None:
    """Find adjacent native owners whose concatenated text equals ``expected``."""
    expected_text = _normalize_gate_text(expected)
    if not expected_text:
        return None
    candidates = [
        index
        for index, owner in enumerate(owners)
        if index not in exclude
        and owner.get("nativeText")
        and _normalize_gate_text(owner.get("text"))
        and isinstance(owner.get("referenceInkBBox"), Sequence)
        and len(owner["referenceInkBBox"]) == 4
    ]
    compact_expected = re.sub(r"\s+", "", expected_text)
    for size in range(2, min(max_cluster_size, len(candidates)) + 1):
        for combo in combinations(candidates, size):
            if not _cluster_is_adjacent(
                combo,
                owners,
                max_gap_px=max_gap_px,
            ):
                continue
            ordered = sorted(
                combo,
                key=lambda index: (
                    owners[index]["referenceInkBBox"][1],
                    owners[index]["referenceInkBBox"][0],
                ),
            )
            combined = "".join(
                _normalize_gate_text(owners[index]["text"]) for index in ordered
            )
            if re.sub(r"\s+", "", combined) == compact_expected:
                return list(ordered)
    return None


def _unmeasurable_owner(
    element: Mapping[str, Any],
    text: str,
    native_normalized: set[str],
    reason: str,
) -> dict[str, Any]:
    """Register native copy that exists but cannot be measured.

    Deliberately omits ``checks`` so the owner is never mistaken for a
    measured one, and uses a non-``pass`` status so it can never satisfy the
    gate.  ``nativeText`` compares whitespace-normalised strings: a label the
    emitter wrapped onto two lines (``"5.8\\n折"``) is still the same native
    copy, and the exact-string comparison used to score it as "not native".
    """
    return {
        "contentRef": element.get("contentRef"),
        "text": text,
        "type": element.get("type"),
        "nativeText": _compact_gate_text(text) in native_normalized,
        "ownerScope": "diagnostic-only",
        "status": "unmeasurable-missing-evidence",
        "failureClass": "unmeasured",
        "registrationReason": reason,
        "registrationSource": "inventory-emission-contract/1.0",
        "baseline": "unknown",
    }


def _evaluate_native_text_gate(
    owners: Sequence[Mapping[str, Any]],
    chrome_regions: Sequence[Mapping[str, Any]],
    *,
    critical_texts: Sequence[str],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    critical = list(
        dict.fromkeys(
            str(value).strip() for value in critical_texts if str(value).strip()
        )
    )
    matched_owner_indexes: set[int] = set()
    missing_critical: list[str] = []
    logical_clusters: list[dict[str, Any]] = []
    for expected in critical:
        matches = [
            index
            for index, owner in enumerate(owners)
            if _critical_text_matches(expected, owner.get("text"))
        ]
        if matches:
            matched_owner_indexes.update(matches)
            continue
        cluster = _logical_cluster_for_expected(
            expected,
            owners,
            exclude=matched_owner_indexes,
        )
        if cluster is not None:
            matched_owner_indexes.update(cluster)
            logical_clusters.append(
                {
                    "text": expected,
                    "ownerRefs": [
                        str(owners[index].get("contentRef") or f"owner-{index}")
                        for index in cluster
                    ],
                }
            )
            continue
        missing_critical.append(expected)
    if critical:
        scope_indexes = sorted(matched_owner_indexes)
        scope = "critical-text-owners"
    else:
        scope_indexes = [
            index for index, owner in enumerate(owners) if "checks" in owner
        ]
        scope = "all-measured-owners"
    scoped_indexes = set(scope_indexes)
    owner_scope = "critical-gate" if critical else "all-measured-gate"
    for index, owner in enumerate(owners):
        owner["ownerScope"] = (
            owner_scope if index in scoped_indexes else "diagnostic-only"
        )

    text_blockers: list[str] = []
    unverified: list[dict[str, Any]] = []
    for expected in missing_critical:
        text_blockers.append(f"native-text:missing:{expected}")
    for index in scope_indexes:
        owner = owners[index]
        owner_ref = str(owner.get("contentRef") or f"owner-{index}")
        if str(owner.get("status") or "").startswith("unmeasurable"):
            # No ink evidence means the instrument cannot see this owner. That
            # is an instrument limitation, not proof of a render defect: it is
            # reported separately instead of blocking the gate forever.
            unverified.append(
                {
                    "contentRef": owner.get("contentRef"),
                    "text": owner.get("text"),
                    "reason": owner.get("registrationReason"),
                }
            )
            continue
        if not owner.get("nativeText"):
            text_blockers.append(f"native-text:not-native:{owner_ref}")
            continue
        if owner.get("status") != "pass":
            text_blockers.append(f"native-text:owner:{owner_ref}")
    baseline_required = bool(policy.get("native_text_baseline_required", False))
    baseline_evidence_count = sum(
        owner.get("baseline") not in {None, "", "unknown"} for owner in owners
    )
    baseline_status = "pass" if baseline_evidence_count else "not-evaluated"
    if baseline_required and not baseline_evidence_count:
        text_blockers.append("native-text:baseline-evidence")
    if not owners:
        text_blockers.append("native-text:missing")
    text_blockers = list(dict.fromkeys(text_blockers))

    chrome_threshold = _number(
        policy.get("chrome_bad_pixel_ratio_max"),
        0.05,
    )
    chrome_blockers: list[str] = []
    if not chrome_regions:
        chrome_blockers.append("chrome-visual:missing")
    for region in chrome_regions:
        region_id = str(region.get("id") or region.get("role") or "unknown")
        ratio = _number(region.get("chromeBadPixelRatio"), 1.0)
        if ratio > chrome_threshold or region.get("status") == "fail":
            chrome_blockers.append(f"chrome-visual:{region_id}")
    chrome_blockers = list(dict.fromkeys(chrome_blockers))
    blockers = list(dict.fromkeys([*text_blockers, *chrome_blockers]))

    text_pass_count = sum(
        owners[index].get("nativeText") and owners[index].get("status") == "pass"
        for index in scope_indexes
    )
    owner_refs = [
        str(owners[index].get("contentRef") or f"owner-{index}")
        for index in scope_indexes
    ]
    return {
        "schema_version": "grounding-native-text-gate/2.0",
        "status": "fail" if blockers else "pass",
        "scope": scope,
        "thresholds": {
            "chromeBadPixelRatioMax": chrome_threshold,
            "positionPxMax": _number(
                policy.get("native_text_position_px_max"),
                1.0,
            ),
            "inkCoverageRatioMin": _number(
                policy.get("native_text_ink_coverage_min"),
                0.90,
            ),
            "inkCoverageRatioMax": _number(
                policy.get("native_text_ink_coverage_max"),
                1.10,
            ),
            "edgeF1Min": _number(policy.get("native_text_edge_f1_min"), 0.95),
        },
        "criticalText": {
            "requiredCount": len(critical),
            "matchedCount": len(critical) - len(missing_critical),
            "missing": missing_critical,
            "logicalClusters": logical_clusters,
        },
        "nativeText": {
            "status": "fail" if text_blockers else "pass",
            "ownerCount": len(scope_indexes),
            "ownerPassCount": int(text_pass_count),
            "ownerPassRatio": (
                float(text_pass_count) / float(len(scope_indexes))
                if scope_indexes
                else 0.0
            ),
            "ownerRefs": owner_refs,
            "unscopedOwnerCount": len(owners) - len(scope_indexes),
            "unverified": unverified,
            "unverifiedCount": len(unverified),
            "blockers": text_blockers,
        },
        "chrome": {
            "status": "fail" if chrome_blockers else "pass",
            "regionCount": len(chrome_regions),
            "blockers": chrome_blockers,
        },
        "baseline": {
            "status": baseline_status,
            "required": baseline_required,
            "evidenceCount": baseline_evidence_count,
        },
        "blockers": blockers,
    }


def build_native_text_quality(
    design: Mapping[str, Any],
    readback_tree: Mapping[str, Any],
    reference_path: str,
    rendered_path: str,
    regions: list[Mapping[str, Any]],
    *,
    halo_px: int = 2,
    box_pad_px: int = 4,
    bad_pixel_threshold: int = 30,
    gate_policy: Mapping[str, Any] | None = None,
    critical_texts: Sequence[str] | None = None,
    register_unmeasured_owners: bool = False,
) -> dict[str, Any]:
    """Build diagnostic text/chrome metrics; never changes acceptance status.

    Measurement contract (2026-11-11):

    * an owner is measured inside **its own emitted node box** (plus
      ``box_pad_px``), not inside ``styleEvidence.source_bbox``.  The grounding
      box is a region: on a price cell it spans ``¥20.24 起 ¥23.0`` and no
      single TEXT node can match its width, so the owner was unpassable by
      construction;
    * both sides are measured with the same mask.  The reference used to be
      measured upstream with an Otsu threshold while the render used a fixed
      50, so the comparison carried a method bias on top of the render;
    * ``nativeText`` compares whitespace-normalised strings, so a wrapped
      ``"5.8\\n折"`` still counts as native copy.

    ``register_unmeasured_owners`` is an opt-in emission-contract repair.  By
    default an element without measurable ink evidence is silently skipped, so
    critical-text matching treats existing native copy as absent.  When
    enabled, such elements are registered with an explicit ``unmeasurable-
    missing-evidence`` status instead.  They are never counted as passing, and
    ``_evaluate_native_text_gate`` lists them separately instead of letting
    them block the gate forever.
    """
    import numpy as np
    from PIL import Image

    with Image.open(reference_path) as source:
        reference = np.asarray(source.convert("RGB"), dtype=np.int16)
    with Image.open(rendered_path) as source:
        rendered = np.asarray(source.convert("RGB"), dtype=np.int16)
    if reference.shape != rendered.shape:
        raise ValueError("reference and rendered image sizes must match")
    height, width = reference.shape[:2]
    bad = np.max(np.abs(reference - rendered), axis=2) > bad_pixel_threshold
    gate_enabled = isinstance(gate_policy, Mapping)
    policy = gate_policy if gate_enabled else {}
    position_max = _number(policy.get("native_text_position_px_max"), 1.0)
    width_ratio = _number(
        policy.get("native_text_width_tolerance_ratio"),
        0.02,
    )
    width_floor = int(_number(policy.get("native_text_width_tolerance_floor_px"), 2.0))
    height_ratio = _number(
        policy.get("native_text_height_tolerance_ratio"),
        0.02,
    )
    height_floor = int(
        _number(policy.get("native_text_height_tolerance_floor_px"), 2.0)
    )
    coverage_min = _number(policy.get("native_text_ink_coverage_min"), 0.90)
    coverage_max = _number(policy.get("native_text_ink_coverage_max"), 1.10)
    edge_min = _number(policy.get("native_text_edge_f1_min"), 0.95)
    chrome_threshold = _number(
        policy.get("chrome_bad_pixel_ratio_max"),
        0.05,
    )
    # 窗口口径：ownership = 先放大到 union(source_bbox, 节点框)，再按归属选墨；
    # legacy = 旧的「节点框 + pad，整窗取墨」。见 20261113_ink_ownership_probe.md。
    window_mode = str(policy.get("native_text_window_mode") or "ownership")
    ownership = window_mode == "ownership"
    gap_em_latin = _number(policy.get("native_text_gap_em_latin"), 1.0)
    gap_em_cjk = _number(policy.get("native_text_gap_em_cjk"), 0.35)
    native_characters = {
        str(node.get("characters") or "") for node in _text_nodes(readback_tree)
    }
    native_normalized = {_compact_gate_text(value) for value in native_characters}
    node_boxes = _text_node_boxes(readback_tree)
    text_mask = np.zeros((height, width), dtype=bool)
    owners: list[dict[str, Any]] = []
    for element in design.get("elements") or []:
        if not isinstance(element, Mapping):
            continue
        text = str(element.get("text") or element.get("controlValue") or "")
        if not text or str(element.get("type") or "") == "image":
            continue
        evidence = element.get("styleEvidence")
        values = evidence.get("evidence") if isinstance(evidence, Mapping) else None
        source_bbox = (
            _normalized_bbox(values.get("source_bbox"))
            if isinstance(values, Mapping)
            else None
        )
        element_style = element.get("style")
        font_size = (
            _number(element_style.get("fontSize"), 0.0)
            if isinstance(element_style, Mapping)
            else 0.0
        ) or 16.0
        native_text = _compact_gate_text(text) in native_normalized
        node_box = _select_node_box(text, element, node_boxes)
        measurement_source = "emitted-node"
        window_base = node_box
        if ownership and node_box is not None and source_bbox is not None:
            window_base = _union_bbox(node_box, source_bbox)
        measure_box = (
            _halo_bbox(window_base, box_pad_px, (height, width))
            if window_base is not None
            else None
        )
        if measure_box is None:
            measurement_source = "grounding-box"
            measure_box = source_bbox or _normalized_bbox(
                [
                    _number(element.get("x"), 0.0),
                    _number(element.get("y"), 0.0),
                    _number(element.get("width"), 0.0),
                    _number(element.get("height"), 0.0),
                ]
            )
        if measure_box is None:
            if register_unmeasured_owners:
                owners.append(
                    _unmeasurable_owner(
                        element, text, native_normalized, "missing-box-evidence"
                    )
                )
            continue
        x, y, box_width, box_height = measure_box
        source_region = rendered[y : y + box_height, x : x + box_width]
        reference_region = reference[y : y + box_height, x : x + box_width]
        # A divider only has to be suppressed when the crop is a region (the
        # grounding box).  An emitted node box is tight around its own glyphs,
        # and the 80% rule would eat every row of a dense label.
        mask_fn = _contrast_mask if measurement_source == "emitted-node" else _text_ink_mask
        rendered_mask = mask_fn(source_region)
        reference_mask = mask_fn(reference_region)
        script = str((values or {}).get("script") or "").lower() if isinstance(values, Mapping) else ""
        gap_em = gap_em_latin if script == "latin" else gap_em_cjk
        reference_ink = _selected_ink(
            reference_mask, measure_box, node_box, font_size, gap_em, ownership
        )
        if reference_ink is None:
            if register_unmeasured_owners:
                owners.append(
                    _unmeasurable_owner(
                        element, text, native_normalized, "no-reference-ink-in-box"
                    )
                )
            continue
        rendered_ink = _selected_ink(
            rendered_mask, measure_box, node_box, font_size, gap_em, ownership
        )
        if rendered_ink is None:
            owners.append(
                {
                    "contentRef": element.get("contentRef"),
                    "text": text,
                    "nativeText": native_text,
                    "ownerScope": "diagnostic-only",
                    "status": "failed-missing-rendered-ink",
                    "measureBBox": measure_box,
                    "measurementSource": measurement_source,
                }
            )
            continue
        delta_x = rendered_ink[0] - reference_ink[0]
        # 只记账，不参与判据：参考墨迹贴到窗口边时，宽度比较已经退化成
        # 「我们的墨迹有没有填满自己的框」。见 `_clip_sides` 的说明。
        reference_clip_sides = _clip_sides(reference_ink, measure_box)
        delta_y = rendered_ink[1] - reference_ink[1]
        width_tolerance = max(
            width_floor,
            int(round(reference_ink[2] * width_ratio)),
        )
        height_tolerance = max(
            height_floor,
            int(round(reference_ink[3] * height_ratio)),
        )
        height_delta = rendered_ink[3] - reference_ink[3]
        width_delta = rendered_ink[2] - reference_ink[2]
        source_reference_pixels = int(reference_mask.sum())
        source_rendered_pixels = int(rendered_mask.sum())
        source_coverage = (
            float(source_rendered_pixels) / float(source_reference_pixels)
            if source_reference_pixels
            else None
        )
        source_edge_f1 = _mask_edge_f1(
            reference_mask,
            rendered_mask,
            reference_ink,
            rendered_ink,
            (x, y),
        )
        support_bbox = _halo_bbox(reference_ink, halo_px, (height, width))
        if support_bbox is None:
            support_coverage = None
            support_edge_f1 = None
            support_reference_ink = None
            support_rendered_ink = None
        else:
            support_x, support_y, support_width, support_height = support_bbox
            support_reference_region = reference[
                support_y : support_y + support_height,
                support_x : support_x + support_width,
            ]
            support_rendered_region = rendered[
                support_y : support_y + support_height,
                support_x : support_x + support_width,
            ]
            support_reference_mask = _contrast_mask(support_reference_region)
            support_rendered_mask = _contrast_mask(support_rendered_region)
            support_reference_ink = _ink_bbox(support_reference_mask, support_bbox)
            support_rendered_ink = _ink_bbox(support_rendered_mask, support_bbox)
            support_reference_pixels = int(support_reference_mask.sum())
            support_rendered_pixels = int(support_rendered_mask.sum())
            support_coverage = (
                float(support_rendered_pixels) / float(support_reference_pixels)
                if support_reference_pixels
                else None
            )
            support_edge_f1 = (
                _mask_edge_f1(
                    support_reference_mask,
                    support_rendered_mask,
                    support_reference_ink,
                    support_rendered_ink,
                    (support_x, support_y),
                )
                if support_reference_ink is not None
                and support_rendered_ink is not None
                else None
            )
        geometry_checks = {
            "position": abs(delta_x) <= position_max and abs(delta_y) <= position_max,
            "size": abs(width_delta) <= width_tolerance
            and abs(height_delta) <= height_tolerance,
            "coverage": support_coverage is not None
            and coverage_min <= support_coverage <= coverage_max,
            "edgeF1": support_edge_f1 is not None and support_edge_f1 >= edge_min,
        }
        owners.append(
            {
                "contentRef": element.get("contentRef"),
                "text": text,
                "type": element.get("type"),
                "nativeText": native_text,
                "ownerScope": "diagnostic-only",
                "measureBBox": measure_box,
                "measurementSource": measurement_source,
                "referenceInkBBox": reference_ink,
                "renderedInkBBox": rendered_ink,
                "referenceClipped": bool(reference_clip_sides),
                "referenceClippedSides": reference_clip_sides,
                "windowMode": window_mode,
                "deltaX": delta_x,
                "deltaY": delta_y,
                "widthDelta": width_delta,
                "heightDelta": height_delta,
                "widthTolerance": width_tolerance,
                "heightTolerance": height_tolerance,
                "metricsBasis": "reference-ink-halo",
                "supportBBox": support_bbox,
                "supportReferenceInkBBox": support_reference_ink,
                "supportRenderedInkBBox": support_rendered_ink,
                "sourceCoverageRatio": source_coverage,
                "sourceEdgeF1": source_edge_f1,
                "inkCoverageRatio": support_coverage,
                "edgeF1": support_edge_f1,
                "baseline": "unknown",
                "checks": geometry_checks,
                # 只读分类：把失败归到机械/字族/量具三条轨之一，供发布判定分层。
                # 它不动 `checks`、不动 `status`、不进门禁——层到类的映射在
                # `image_figma_acceptance.native_text_failure_layers` 里。
                "failureClass": _failure_class(
                    geometry_checks,
                    reference_clip_sides,
                    delta_x,
                    delta_y,
                    width_delta,
                    height_delta,
                    width_tolerance,
                    height_tolerance,
                    position_max,
                ),
                "geometryStatus": ("pass" if all(geometry_checks.values()) else "fail"),
                # `native_text` is the compact (whitespace-normalised) test the
                # gate itself uses; the raw membership test below it would fail
                # a paragraph that the emitter wrapped, while `nativeText` still
                # reported true -- one owner, two answers. It is the same
                # predicate, so it has to be the same expression.
                "status": (
                    "pass" if native_text and all(geometry_checks.values()) else "fail"
                ),
            }
        )
        mask_x = max(0, reference_ink[0] - halo_px)
        mask_y = max(0, reference_ink[1] - halo_px)
        mask_right = min(width, reference_ink[0] + reference_ink[2] + halo_px)
        mask_bottom = min(height, reference_ink[1] + reference_ink[3] + halo_px)
        text_mask[mask_y:mask_bottom, mask_x:mask_right] = True
    chrome_regions = []
    for region in regions:
        bbox = _normalized_bbox(region.get("bbox"))
        if bbox is None:
            continue
        region_mask = _region_mask((height, width), bbox)
        chrome_mask = region_mask & ~text_mask
        pixel_count = int(chrome_mask.sum())
        bad_count = int((bad & chrome_mask).sum())
        chrome_regions.append(
            {
                "id": str(region.get("id") or region.get("role") or ""),
                "role": str(region.get("role") or ""),
                "bbox": bbox,
                "chromePixelCount": pixel_count,
                "chromeBadPixelCount": bad_count,
                "chromeBadPixelRatio": (
                    float(bad_count) / float(pixel_count) if pixel_count else None
                ),
                "status": (
                    "pass"
                    if pixel_count
                    and float(bad_count) / float(pixel_count) <= chrome_threshold
                    else "fail"
                ),
            }
        )
    measured = [owner for owner in owners if "checks" in owner]
    summary = {
        "ownerCount": len(owners),
        # 这份产物是哪把尺子量的：ownership = 归属选择；legacy = 节点框+pad 整窗取墨
        # 这份产物是哪把尺子量的：ownership = 归属选择；legacy = 节点框+pad 整窗取墨
        "windowMode": window_mode,
        # 只读诊断：参考墨迹贴到测量窗口边的 owner 数。0 说明这条页面的宽度
        # 读数没有退化成「填满自己的框」；不代表判据要改。
        "referenceClippedCount": sum(
            bool(owner.get("referenceClipped")) for owner in owners
        ),
        # 只读诊断：按失败类别计数，含 pass。分层判据要读的是这里，不是 status。
        "failureClassCounts": {
            name: sum(1 for owner in owners if owner.get("failureClass") == name)
            for name in (
                "pass",
                "mechanical",
                "typeface-glyph",
                "typeface-advance",
                "instrument-capped",
                "unmeasured",
            )
        },
        "nativeTextCount": sum(bool(owner.get("nativeText")) for owner in owners),
        "positionPassCount": sum(
            bool(owner.get("checks", {}).get("position")) for owner in owners
        ),
        "sizePassCount": sum(
            bool(owner.get("checks", {}).get("size")) for owner in owners
        ),
        "coveragePassCount": sum(
            bool(owner.get("checks", {}).get("coverage")) for owner in owners
        ),
        "edgeF1PassCount": sum(
            bool(owner.get("checks", {}).get("edgeF1")) for owner in owners
        ),
        "baselineEvidenceCount": 0,
        "measuredOwnerCount": len(measured),
    }
    proposed_text_gate = {
        "positionPxMax": position_max,
        "widthErrorPxMax": f"max({width_floor}, {width_ratio:.0%} reference width)",
        "heightErrorPxMax": f"max({height_floor}, {height_ratio:.0%} reference height)",
        "inkCoverageRatioMin": coverage_min,
        "inkCoverageRatioMax": coverage_max,
        "edgeF1Min": edge_min,
        "baselinePxMax": 1,
    }
    report = {
        "schema_version": (
            "grounding-native-text-quality/2.0"
            if gate_enabled
            else "grounding-native-text-quality/1.0"
        ),
        "status": ("measured-gate" if gate_enabled else "measured-diagnostic-only"),
        "acceptance_effect": (
            "native-text-and-chrome-gate" if gate_enabled else "none"
        ),
        "haloPx": halo_px,
        "boxPadPx": box_pad_px,
        "measurement": {
            "box": "emitted-node",
            "mask": "fixed-contrast-50 (both sides)",
            "nativeTextMatch": "whitespace-normalized",
        },
        "badPixelThreshold": bad_pixel_threshold,
        "summary": summary,
        "owners": owners,
        "chromeRegions": chrome_regions,
        "proposedTextGate": proposed_text_gate,
        "limitations": [
            "Baseline evidence is unavailable for every owner in this diagnostic.",
            (
                "Owners without ink evidence are listed under nativeText.unverified; "
                "they never count as passing and no longer block the gate."
            ),
            (
                "Native text and chrome use independent quality gates in policy 2.0."
                if gate_enabled
                else "Native text/chrome split metrics do not change the frozen raw acceptance."
            ),
            "Reference ink masks are screenshot-derived candidates, not original glyph outlines.",
        ],
    }
    if gate_enabled:
        report["gate"] = _evaluate_native_text_gate(
            owners,
            chrome_regions,
            critical_texts=critical_texts or [],
            policy=policy,
        )
    return report
