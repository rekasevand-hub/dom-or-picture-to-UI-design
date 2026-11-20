"""Resolve text style evidence from source screenshot pixels."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.app.services.structure.fidelity.contracts import normalize_bbox
from src.app.services.structure.fidelity.pixel_probe import ink_line_bands, line_metrics

SCHEMA_VERSION = "grounding-text-style-evidence/1.0"

_CJK_FAMILY = "Noto Sans SC"
_LATIN_FAMILY = "Open Sans"


def _hex_color(values: Sequence[float]) -> str:
    red, green, blue = (
        max(0, min(255, int(round(float(value))))) for value in values[:3]
    )
    return f"#{red:02x}{green:02x}{blue:02x}"


def _has_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def _alignment(
    ink_bbox: list[int],
    parent_bbox: Sequence[int] | None,
    role: str,
) -> tuple[str, float | None]:
    if parent_bbox is None:
        return ("center" if role == "table-header" else "left"), None
    try:
        parent_x, _parent_y, parent_width, _parent_height = (
            int(round(float(value))) for value in parent_bbox
        )
    except (TypeError, ValueError, OverflowError):
        return "left", None
    if parent_width <= 0:
        return "left", None
    ink_center = ink_bbox[0] + ink_bbox[2] / 2
    parent_center = parent_x + parent_width / 2
    delta = abs(ink_center - parent_center)
    if role == "table-header":
        return "center", delta
    tolerance = max(4.0, parent_width * 0.06)
    if delta <= tolerance:
        return "center", delta
    if ink_center < parent_center:
        return "left", delta
    return "right", delta


def _supports_multiline(text: str, bands: list[tuple[int, int]]) -> bool:
    """Whether the projection bands really are separate text lines.

    CJK glyphs are made of disjoint horizontal strokes, so a single 28px label
    splits into several thin bands whose heights differ by a lot.  Real lines
    of one paragraph share a type scale (near-equal band heights) and carry
    enough characters to need wrapping; short labels never wrap.
    """
    if len(text.strip()) < 8:
        return False
    heights = [end - start for start, end in bands]
    if len(heights) < 2 or min(heights) <= 0:
        return False
    return max(heights) / min(heights) <= 1.6


#: A stroke this thick is a bold face, whatever the size.  Measured as
#: area / half-perimeter, which is the width of the stroke that would produce
#: that much ink for that much outline.
STROKE_BOLD_MIN = 2.2
#: A display heading carries more: past this the face is Black, not Bold.
STROKE_BLACK_MIN = 3.2
STROKE_BLACK_SIZE = 28.0
#: Stroke thickness relative to type size.  A regular face measures 0.07-0.09,
#: a bold one 0.12-0.16; the floor here is what keeps a large light heading out
#: of the bold branch.
STROKE_BOLD_RATIO = 0.115
STROKE_BLACK_RATIO = 0.14


def _stroke_thickness(mask) -> float:
    """Mean stroke width of an ink mask, in pixels.

    ``area / (perimeter / 2)``: a bar of length L and width t has area L*t and
    outline 2*(L+t), so the ratio is t.  It needs no skeleton and no thinning,
    and it is scale-free — a 14px label and a 40px heading are measured the
    same way.
    """
    try:
        import cv2
    except Exception:  # pragma: no cover - opencv is a pipeline dependency
        return 0.0
    import numpy as np

    if mask is None:
        return 0.0
    area = float(np.asarray(mask, dtype=bool).sum())
    if area < 4:
        return 0.0
    contours, _hierarchy = cv2.findContours(
        np.asarray(mask, dtype=np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE
    )
    perimeter = sum(float(cv2.arcLength(contour, True)) for contour in contours)
    if perimeter <= 1.0:
        return 0.0
    return 2.0 * area / perimeter


def _weight_for(thickness: float, size: float, role: str) -> tuple[str, int]:
    """Font weight from the ink, not from the type size.

    A 14px card title is set in a bold face and a 40px light heading is not;
    size says nothing about stroke.  The mask does.

    Both tests are needed.  Absolute thickness alone marks every large heading
    bold — a 96px light face has an 8px stem — so the stroke is also compared
    with the type it belongs to.  A regular face sits at 0.07-0.09 of its size,
    a bold one at 0.12-0.16.
    """
    ratio = thickness / max(1.0, size)
    if role == "table-header" and thickness < STROKE_BOLD_MIN:
        return "bold", 700
    if (
        size >= STROKE_BLACK_SIZE
        and thickness >= STROKE_BLACK_MIN
        and ratio >= STROKE_BLACK_RATIO
    ):
        return "bold", 900
    if thickness >= STROKE_BOLD_MIN and ratio >= STROKE_BOLD_RATIO:
        return "bold", 700
    if role == "table-header":
        return "bold", 700
    return "normal", 400


#: 一行/一列要算进"墨迹"，至少要带最强投影的这么多份额。两档：实心底板上的
#: 字用强档（圆角抗锯齿会占满首尾几行），白底正文用弱档（字母下伸部只有
#: 六七个像素，强档会把 "q" 的尾巴剪掉，15px 的一行量成 8px）。
INK_TRIM_SHARE_CHIP = 0.25
INK_TRIM_SHARE_PLAIN = 0.25
#: 底色离纯白超过这个距离，就认为字压在实心底板/胶囊上。
INK_FILLED_BACKGROUND = 24


def _single_ink_band(rows) -> tuple[int, int] | None:
    """投影上只有一条连续的墨迹带时，返回它的 (top, bottom)。

    两条以上就是两行字（或字与框边各成一带），这时"这一行有多高"没有唯一答案，
    交给调用方按强度裁。
    """
    import numpy as np

    if rows.size == 0:
        return None
    filled = rows > 0
    if not filled.any():
        return None
    edges = np.diff(filled.astype(np.int8))
    starts = list(np.where(edges == 1)[0] + 1)
    ends = list(np.where(edges == -1)[0] + 1)
    if filled[0]:
        starts.insert(0, 0)
    if filled[-1]:
        ends.append(len(filled))
    if len(starts) != 1 or len(ends) != 1:
        return None
    return int(starts[0]), int(ends[0])


#: 框的四条外缘与框内底色的通道差超过这个值，说明这条边正好压在胶囊/描边/色块
#: 交界上——OCR 的框切进了底板边缘，框里混着圆角抗锯齿，才需要剥边框行。
#: 纯平底色上的正文四缘与底色同色，量出来就是 0，不该被裁。
EDGE_STEP_MIN = 12
#: 前置判据的开关：关掉它，所有文本都按"有边框"处理（上一轮的全局一刀切）。
INK_EDGE_GUARD = False


def _edge_has_step(crop, background) -> bool:
    """框的最外一圈与框内底色是不是两种颜色。

    胶囊里的字，OCR 框往往比胶囊高出 1~2px：最外一行是页面白，往里立刻变绿。
    这就是"框切在底板上"的签名。纯平背景上没有这个台阶。
    """
    import numpy as np

    if crop is None or crop.size == 0:
        return False
    ring = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]], axis=0)
    if ring.size == 0:
        return False
    outer = np.median(ring.reshape(-1, 3), axis=0)
    return float(np.abs(outer - np.asarray(background, dtype=np.float64)).max()) > EDGE_STEP_MIN


def _should_trim(crop, background) -> bool:
    """这段字需不需要剥边框行。

    两种情况需要：字压在实心底板（胶囊、按钮）上，或框的外缘与底色是两个颜色
    （框切进了底板边缘）。纯平底色上的正文两者都不成立。
    """
    import numpy as np

    if not INK_EDGE_GUARD:
        return True
    base = np.asarray(background, dtype=np.float64)
    if float(np.abs(base - 255.0).max()) > INK_FILLED_BACKGROUND:
        return True
    return _edge_has_step(crop, background)


def _ink_extent(
    mask, *, filled: bool = False, trim: bool = True
) -> tuple[int, int, int, int]:
    """墨迹的 (left, top, right, bottom)，按投影强度裁掉边缘的零星抗锯齿。

    直接取 ``np.where`` 的极值等于相信"只要有一个像素就算这一行有字"：圆角、
    投影、1px 描边都会把字号撑大。Gmail 那枚 30px 高的绿胶囊里，字身只有
    22px，圆角抗锯齿让 ink_bbox 变成 29px，字号按 29×0.95 算成 27.5pt，比
    同行正文大出一倍。按"最强行墨量的四分之一"设门槛，边缘那几行只剩十来个
    像素，过不了；字身那一行有上百个，稳稳在。
    """
    import numpy as np

    if mask.size == 0:
        return 0, 0, int(mask.shape[1]), int(mask.shape[0])
    # 纯平底色上的正文：框的四缘与底色同色，没有圆角、没有描边，也就不存在
    # "边框行"。这时裁剪只会把字自身的升部、下伸部削掉，review 的正文整体小了
    # 1~2px 就是这么来的（−0.39）。直接取墨迹本身的上下缘。
    if not trim:
        import numpy as _np

        rows = mask.sum(axis=1)
        columns = mask.sum(axis=0)
        keep_rows = _np.where(rows > 0)[0]
        keep_columns = _np.where(columns > 0)[0]
        if keep_rows.size and keep_columns.size:
            return (
                int(keep_columns.min()),
                int(keep_rows.min()),
                int(keep_columns.max()) + 1,
                int(keep_rows.max()) + 1,
            )
        return 0, 0, int(mask.shape[1]), int(mask.shape[0])
    # 整行/整列都是"墨"的地方不是字，是框边或胶囊的上下缘：先摘掉，再按强度裁。
    # 一行里只剩一个"一"字时所有行都满足这条，那就别摘——否则整段字会消失。
    work = mask
    for axis in (1, 0):
        counts = work.sum(axis=axis)
        span = work.shape[1] if axis == 1 else work.shape[0]
        heavy = counts >= max(4, int(round(span * 0.75)))
        light_ink = (counts > 0) & ~heavy
        if not heavy.any() or not light_ink.any():
            continue
        first = int(np.argmax(light_ink))
        last = int(len(light_ink) - 1 - np.argmax(light_ink[::-1]))
        edge = heavy.copy()
        # 只摘**首尾之外**的满行。密排小字里很多行本来就接近满行，那是字，
        # 不是边框；把中间那些也摘掉，15px 的一行会量成 8px。
        edge[first : last + 1] = False
        if not edge.any():
            continue
        candidate = work.copy()
        if axis == 1:
            candidate[edge, :] = False
        else:
            candidate[:, edge] = False
        # 摘掉之后必须还剩东西：一根横线（"一"、删除线）整行都满，摘完就空了。
        if candidate.any():
            work = candidate
    rows = work.sum(axis=1)
    columns = work.sum(axis=0)
    if rows.size == 0 or columns.size == 0 or int(rows.max()) <= 0:
        return 0, 0, int(mask.shape[1]), int(mask.shape[0])
    # 盒子比它自己的墨迹高出一大截时（OCR 的框常常上下各留半行），那条墨迹带
    # 就是这一行字，直接用它——强裁剪会把升部、下伸部这些细笔画一起剪掉，
    # 15px 的一行会量成 8px。反过来，墨迹带几乎撑满盒子时，带里混进了圆角与
    # 邻行的残墨，必须回到投影上按强度裁。
    band = _single_ink_band(rows)
    if band is not None and (band[1] - band[0]) <= 0.6 * mask.shape[0]:
        keep = np.where(work[band[0] : band[1]].sum(axis=0) > 0)[0]
        if keep.size:
            return int(keep.min()), int(band[0]), int(keep.max()) + 1, int(band[1])
    share = INK_TRIM_SHARE_CHIP if filled else INK_TRIM_SHARE_PLAIN
    row_floor = max(2.0, float(rows.max()) * share)
    column_floor = max(2.0, float(columns.max()) * share)
    keep_rows = np.where(rows >= row_floor)[0]
    keep_columns = np.where(columns >= column_floor)[0]
    if keep_rows.size == 0 or keep_columns.size == 0:
        return 0, 0, int(mask.shape[1]), int(mask.shape[0])
    trimmed = (
        int(keep_columns.min()),
        int(keep_rows.min()),
        int(keep_columns.max()) + 1,
        int(keep_rows.max()) + 1,
    )
    # 投影裁剪把升部/下伸部这些细笔画一起剪掉时（15px 的一行只剩 8px 的 x-height），
    # 退回那条墨迹带。只在"带内只剩一条、带高不过盒子的六成、而裁剪结果不到带高
    # 的 65%"时才退——不设这三个条件，OCR 框里混进来的相邻行会把字号撑大
    # （gmail 上 56 条文本被放大，"Apple" 15.2 → 26.5）。
    band = _single_ink_band(rows)
    if band is not None:
        band_height = band[1] - band[0]
        trimmed_height = trimmed[3] - trimmed[1]
        if band_height <= 0.6 * mask.shape[0] and trimmed_height < 0.65 * band_height:
            keep = np.where(work[band[0] : band[1]].sum(axis=0) > 0)[0]
            if keep.size:
                return (
                    int(keep.min()),
                    int(band[0]),
                    int(keep.max()) + 1,
                    int(band[1]),
                )
    return trimmed


#: 字色与底色的通道差低于这个值，就不是"浅色字压在底板上"，而是"把底板色
#: 当成了字色"。45 大致是 #ffffff 与 #d0d0d0 的距离，比任何可读正文都小。
MIN_TEXT_CONTRAST = 45


def _contrast_guard(crop, background, foreground):
    """采到的字色贴着底色时，改取框内离底色最远的那个主色。

    OCR 的框经常正好套在实心胶囊上：环带取样（框的四边）取到的是胶囊的绿，
    于是"字色"和"底色"是同一个 #188038，画出来是一团看不见的绿。这时框里
    一定还有另一种像素——白色笔画——它是离底色最远的那个簇。
    """
    import numpy as np

    base = np.asarray(background, dtype=np.int16)
    current = np.asarray(foreground, dtype=np.int16)
    if float(np.abs(current - base).max()) >= MIN_TEXT_CONTRAST:
        return foreground
    flat = crop.reshape(-1, 3)
    if flat.shape[0] < 8:
        return foreground
    distance = np.abs(flat - base).max(axis=1)
    far = flat[distance >= float(np.percentile(distance, 97))]
    if far.size == 0:
        return foreground
    candidate = np.median(far, axis=0)
    # 换出来的颜色必须真的比原来更远，否则保持原样：纯色块里没有第二个颜色，
    # 这时任何"反转"都只是把噪声当成字。
    if float(np.abs(candidate - base).max()) <= float(np.abs(current - base).max()):
        return foreground
    return candidate


def measure_ink_center(image_path: str | Path, bbox: Sequence[int]) -> float | None:
    """原图上这个框里墨迹的上下缘中心（绝对 y）。

    用来把大标题的落位从"行框"换到"墨迹"：行框给上伸部留的位置比下伸部多，
    按行框居中必然偏高。量不到字就返回 None，调用方保持原样。
    """
    import numpy as np
    from PIL import Image

    path = Path(image_path)
    if not path.is_file():
        return None
    with Image.open(path) as source:
        image = np.asarray(source.convert("RGB"), dtype=np.int16)
    height, width = image.shape[:2]
    normalized = normalize_bbox(bbox, width, height)
    if normalized is None:
        return None
    x, y, box_width, box_height = normalized
    crop = image[y : y + box_height, x : x + box_width]
    if crop.size == 0 or box_width < 4 or box_height < 4:
        return None
    inset = 2 if min(box_width, box_height) >= 8 else 1
    inner = crop[inset : max(inset + 1, box_height - inset), inset : max(inset + 1, box_width - inset)]
    border = np.concatenate(
        [inner[0, :, :], inner[-1, :, :], inner[:, 0, :], inner[:, -1, :]], axis=0
    )
    background = np.median(border, axis=0)
    distance = np.abs(crop - background.reshape(1, 1, 3)).max(axis=2)
    mask = distance >= 24
    if int(mask.sum()) < 8:
        return None
    _, top, _, bottom = _ink_extent(
        mask,
        filled=bool(float(np.abs(background - 255.0).max()) > INK_FILLED_BACKGROUND),
        trim=_should_trim(crop, background),
    )
    return float(y + (top + bottom) / 2.0)


def resolve_text_style(
    image_path: str | Path,
    text: str,
    bbox: Sequence[int],
    *,
    parent_bbox: Sequence[int] | None = None,
    role: str = "",
) -> dict[str, Any]:
    """Infer a fixed-canvas text style while retaining pixel evidence."""
    import numpy as np
    from PIL import Image

    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with Image.open(path) as source:
        image = np.asarray(source.convert("RGB"), dtype=np.int16)
    height, width = image.shape[:2]
    normalized = normalize_bbox(bbox, width, height)
    if normalized is None:
        raise ValueError("text bbox must be a positive source-pixel bbox")
    x, y, box_width, box_height = normalized
    crop = image[y : y + box_height, x : x + box_width]
    if crop.size == 0:
        raise ValueError("text bbox does not intersect the source image")

    inset = 2 if min(box_width, box_height) >= 8 else 1
    inner = crop[
        inset : max(inset + 1, box_height - inset),
        inset : max(inset + 1, box_width - inset),
    ]
    border = np.concatenate(
        [
            inner[0, :, :],
            inner[-1, :, :],
            inner[:, 0, :],
            inner[:, -1, :],
        ],
        axis=0,
    )
    background_rgb = np.median(border, axis=0)
    distance = np.abs(crop - background_rgb.reshape(1, 1, 3)).max(axis=2)
    mask = distance >= 24
    mask[
        mask.sum(axis=1) >= max(4, int(round(box_width * 0.75))),
        :,
    ] = False
    mask[
        :,
        mask.sum(axis=0) >= max(4, int(round(box_height * 0.75))),
    ] = False
    ink_count = int(mask.sum())
    if ink_count < 2:
        align, center_delta = _alignment(normalized, parent_bbox, role)
        family = _CJK_FAMILY if _has_cjk(text) else _LATIN_FAMILY
        return {
            "schema_version": SCHEMA_VERSION,
            "fontFamily": family,
            "fontFallbacks": [
                "Microsoft YaHei" if _has_cjk(text) else "Arial",
                "sans-serif",
            ],
            # A box can only justify type it can hold.  Deriving the size from
            # height alone gave a 25x73 table cell 55px type, which then wrapped
            # one glyph per line; no single glyph may be wider than the box.
            "fontSize": max(
                8.0, round(min(box_height * 0.75, max(8.0, box_width)) * 4) / 4
            ),
            "fontWeight": "bold" if role == "table-header" else "normal",
            "textColor": "#555555",
            "textAlign": align,
            "lineHeightPolicy": "auto",
            "confidence": 0.2,
            "evidence": {
                "status": "low-confidence",
                "reason": "text-ink-not-found",
                "source_bbox": normalized,
                "background": _hex_color(background_rgb),
                "foreground": "#555555",
                "script": "cjk" if _has_cjk(text) else "latin",
                "parent_center_delta": center_delta,
            },
        }

    bands = ink_line_bands(mask)
    metrics = line_metrics(bands)
    line_count = int(metrics.get("lineCount") or 0)
    if line_count >= 2 and not _supports_multiline(text, bands):
        line_count = 1

    ink_left, ink_top, ink_right, ink_bottom = _ink_extent(
        mask,
        filled=bool(float(np.abs(background_rgb - 255.0).max()) > INK_FILLED_BACKGROUND),
        trim=_should_trim(crop, background_rgb),
    )
    ink_box = [
        x + ink_left,
        y + ink_top,
        ink_right - ink_left,
        ink_bottom - ink_top,
    ]
    strong_threshold = float(np.percentile(distance[mask], 80))
    strong_mask = mask & (distance >= max(32.0, strong_threshold))
    low_contrast = not strong_mask.any()
    if low_contrast:
        strong_mask = mask
    foreground_rgb = np.median(crop[strong_mask], axis=0)
    foreground_rgb = _contrast_guard(crop, background_rgb, foreground_rgb)
    contrast = float(distance[strong_mask].mean()) if strong_mask.any() else 0.0
    align, center_delta = _alignment(ink_box, parent_bbox, role)
    cjk = _has_cjk(text)
    family = _CJK_FAMILY if cjk else _LATIN_FAMILY
    estimated_size = max(
        8.0,
        min(96.0, round((ink_box[3] * 0.95) * 4) / 4),
    )
    line_height: float | None = None
    line_height_policy = "auto"
    if line_count >= 2:
        # The bbox of a paragraph spans every visual line, so scaling the whole
        # ink height inflates the type by the line count (24px reported for a
        # real 14px body).  Use the median single-line ink height instead, and
        # keep the measured pitch so the text cannot grow past its box.
        median_height = float(metrics.get("medianLineHeight") or 0)
        if median_height >= 2:
            estimated_size = max(
                8.0,
                min(96.0, round(median_height * 0.95 * 4) / 4),
            )
        pitch = float(metrics.get("linePitch") or 0)
        if estimated_size * 1.02 <= pitch <= estimated_size * 3.0:
            line_height = round(pitch * 4) / 4
            line_height_policy = "observed"
    # Half-max, not the soft threshold: the soft mask carries the antialias
    # halo and inflates every stroke by about a pixel a side, which marks a
    # whole page bold.  Where the ink is half as strong as its core is where
    # the glyph actually ends.
    stroke_mask = mask
    if mask.any():
        strength = distance[mask]
        cut = max(32.0, float(strength.max()) * 0.5)
        stroke_mask = distance >= cut
    thickness = _stroke_thickness(stroke_mask)
    weight, weight_value = _weight_for(thickness, estimated_size, role)
    confidence = min(0.95, 0.6 + min(0.25, contrast / 255))
    if low_contrast:
        confidence = min(confidence, 0.65)
    result = {
        "schema_version": SCHEMA_VERSION,
        "fontFamily": family,
        "fontFallbacks": [
            "Microsoft YaHei" if cjk else "Arial",
            "sans-serif",
        ],
        "fontSize": estimated_size,
        "fontWeight": weight,
        "fontWeightValue": weight_value,
        "textColor": _hex_color(foreground_rgb),
        "textAlign": align,
        "lineHeightPolicy": line_height_policy,
        "confidence": confidence,
        "evidence": {
            "status": "low-contrast" if low_contrast else "observed",
            "source_bbox": normalized,
            "ink_bbox": ink_box,
            "background": _hex_color(background_rgb),
            "foreground": _hex_color(foreground_rgb),
            "contrast_delta": round(contrast, 3),
            "ink_pixel_count": ink_count,
            "stroke_width": round(thickness, 2),
            "script": "cjk" if cjk else "latin",
            "parent_center_delta": center_delta,
            "line_count": line_count,
            "line_bands": [list(band) for band in bands],
        },
    }
    if line_height is not None:
        result["lineHeight"] = line_height
    return result
