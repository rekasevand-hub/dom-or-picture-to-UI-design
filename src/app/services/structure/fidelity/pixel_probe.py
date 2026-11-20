"""Deterministic pixel probes for the fixed-canvas compiler.

Every probe here reads the source screenshot only.  Nothing infers style from
the language model, so the output is reproducible for a given image+bbox pair.

These probes exist because the compiler previously emitted containers with a
dominant fill alone: border, corner radius and multi-line type scale were lost
between the scene plan and the renderer, even though the renderer already
accepts ``borderColor`` / ``borderWidth`` / ``borderRadius``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Sequence

RGB = tuple[int, int, int]

# A 1px border on a screenshot survives as a distinct outermost row/column.
# The tolerance is deliberately low: real borders are usually 1-2% away from
# the fill in luminance, and a false positive only costs one hairline.
_BORDER_TOLERANCE = 12
_CORNER_TOLERANCE = 12
_QUANTIZED_RADII = (4, 6, 8, 12, 16, 20, 24)


@lru_cache(maxsize=16)
def _load_cached(path_str: str, mtime: float, size: int):
    import numpy as np
    from PIL import Image

    del size  # cache key only
    with Image.open(path_str) as source:
        return np.asarray(source.convert("RGB"), dtype=np.int16)


def load_rgb(path: str | Path):
    """Load a screenshot as an int16 RGB array, cached by path + mtime."""
    resolved = Path(path)
    stat = resolved.stat()
    return _load_cached(str(resolved), stat.st_mtime, stat.st_size)


def _median_rgb(image, boxes: Sequence[Sequence[int]]) -> RGB | None:
    import numpy as np

    strips = []
    for x0, y0, x1, y1 in boxes:
        if x1 <= x0 or y1 <= y0:
            continue
        chunk = image[y0:y1, x0:x1]
        if chunk.size:
            strips.append(chunk.reshape(-1, 3))
    if not strips:
        return None
    stacked = np.concatenate(strips, axis=0)
    median = np.median(stacked, axis=0)
    return (int(median[0]), int(median[1]), int(median[2]))


def color_distance(left: Sequence[float], right: Sequence[float]) -> float:
    """Max-channel distance; matches the rest of the pixel pipeline."""
    return max(abs(float(a) - float(b)) for a, b in zip(left[:3], right[:3]))


def rgb_to_hex(rgb: Sequence[float]) -> str:
    red, green, blue = (
        max(0, min(255, int(round(float(value))))) for value in rgb[:3]
    )
    return f"#{red:02x}{green:02x}{blue:02x}"


def hex_to_rgb(value: str) -> RGB:
    text = str(value or "").lstrip("#")
    if len(text) != 6:
        return (255, 255, 255)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return (255, 255, 255)


def _side_bands(
    bbox: Sequence[int],
    *,
    inset: int,
    thickness: int,
) -> dict[str, tuple[int, int, int, int]]:
    """Middle third of each side, so rounded corners never pollute the sample.

    ``inset`` may be negative: -1 makes the band straddle the bbox edge, which
    covers the pixel the renderer actually strokes on (PIL and Figma draw the
    outline *on* ``x + w``, while the bbox interval ends at ``x + w``).
    """
    x, y, w, h = (int(round(float(v))) for v in bbox)
    x0 = x + inset
    y0 = y + inset
    x1 = x + w - inset
    y1 = y + h - inset
    if x1 <= x0 or y1 <= y0:
        return {}
    span = max(1, x1 - x0)
    third = max(1, span // 3)
    mid0 = x0 + third
    mid1 = max(mid0 + 1, x1 - third)
    vspan = max(1, y1 - y0)
    vthird = max(1, vspan // 3)
    vmid0 = y0 + vthird
    vmid1 = max(vmid0 + 1, y1 - vthird)
    return {
        "top": (mid0, y0, mid1, y0 + thickness),
        "bottom": (mid0, y1 - thickness, mid1, y1),
        "left": (x0, vmid0, x0 + thickness, vmid1),
        "right": (x1 - thickness, vmid0, x1, vmid1),
    }


def _edge_strips(
    bbox: Sequence[int],
    inset: int,
    thickness: int,
) -> list[tuple[int, int, int, int]]:
    return list(_side_bands(bbox, inset=inset, thickness=thickness).values())


def _edge_color(image, box: Sequence[int], fill_rgb: RGB) -> RGB | None:
    """Median colour of the non-fill pixels inside one edge band.

    A border band also contains fill (the bbox is only accurate to ±1px), so
    averaging the whole band washes the border out.  Filtering to pixels that
    differ from the fill keeps the hairline and drops the interior.
    """
    import numpy as np

    x0, y0, x1, y1 = (int(v) for v in box)
    if x1 <= x0 or y1 <= y0:
        return None
    chunk = image[y0:y1, x0:x1].reshape(-1, 3)
    if chunk.size == 0:
        return None
    distance = np.abs(chunk - np.asarray(fill_rgb, dtype=np.int16)).max(axis=1)
    mask = distance >= _BORDER_TOLERANCE
    if int(mask.sum()) < max(2, int(round(len(distance) * 0.06))):
        return None
    median = np.median(chunk[mask], axis=0)
    return (int(median[0]), int(median[1]), int(median[2]))


def detect_border(image, bbox: Sequence[int], fill: str) -> dict | None:
    """Return ``{"color", "width"}`` when a real hairline border is visible.

    Each side is probed twice: just inside the bbox, and straddling its edge.
    The inside probe wins when the bbox is accurate; the straddling probe wins
    when the bbox is a pixel short.  Anything that matches the colour outside
    the box is background, not a border, so it is rejected either way.
    """
    fill_rgb = hex_to_rgb(fill)
    background = _outside_color(image, bbox)
    # The ladder walks outwards because a plan box is routinely one to three
    # pixels inside the stroke the picture draws: a 1px border at y=585 with the
    # box at y=588 is invisible to a probe that only looks at y-0 and y-1.
    ladders = [
        _side_bands(bbox, inset=inset, thickness=2)
        for inset in (0, -1, -2, -3)
    ]
    ladders = [bands for bands in ladders if bands]
    if not ladders:
        return None
    sides: list[RGB] = []
    for side in ("top", "bottom", "left", "right"):
        chosen: RGB | None = None
        for bands in ladders:
            box = bands.get(side)
            if not box:
                continue
            candidate = _edge_color(image, box, fill_rgb)
            if candidate is None:
                continue
            if (
                background is not None
                and color_distance(candidate, background) < _BORDER_TOLERANCE
            ):
                continue
            chosen = candidate
            break
        if chosen is None:
            return None
        sides.append(chosen)
    spread = max(color_distance(a, b) for a in sides for b in sides)
    if spread > 24:
        return None
    red = sorted(side[0] for side in sides)[len(sides) // 2]
    green = sorted(side[1] for side in sides)[len(sides) // 2]
    blue = sorted(side[2] for side in sides)[len(sides) // 2]
    border = (red, green, blue)
    if color_distance(border, fill_rgb) < _BORDER_TOLERANCE:
        return None
    return {"color": rgb_to_hex(border), "width": 1}


def _outside_color(image, bbox: Sequence[int]) -> RGB | None:
    """Sample the surface around a box, from far enough out to miss its border.

    Reading y-2..y-4 was wrong for every container whose box is measured to the
    *inside* of its own 1px stroke: those three rows are the border, so "outside"
    came back as the border colour, `detect_border` then rejected it as
    background, and the card was painted with no edge at all.  marketplace's four
    model cards are exactly that case — #2c2b27 border, #1a1917 fill, #100f0d page.

    Six to nine pixels out is past a 1px stroke and its antialiasing, and still
    short enough not to reach a neighbour in ordinary layouts.  The near ring is
    kept only as a fallback for boxes that sit at the very top of the canvas.
    """
    x, y, w, _h = (int(round(float(v))) for v in bbox)
    far = []
    for offset in (6, 7, 8, 9):
        yy = y - offset
        if yy < 0:
            continue
        far.append((x, yy, x + w, yy + 1))
    color = _median_rgb(image, far)
    if color is not None:
        return color
    near = []
    for offset in (2, 3, 4):
        yy = y - offset
        if yy < 0:
            continue
        near.append((x, yy, x + w, yy + 1))
    color = _median_rgb(image, near)
    if color is not None:
        return color
    if 0 <= y < image.shape[0] and 0 <= x < image.shape[1]:
        pixel = image[y, x]
        return (int(pixel[0]), int(pixel[1]), int(pixel[2]))
    return None


def estimate_corner_radius(
    image,
    bbox: Sequence[int],
    *,
    max_radius: int = 28,
    fill: str | None = None,
) -> int:
    """Estimate a corner radius in source pixels and quantise to Figma steps.

    Method: threshold the crop against the colour just outside the box, then
    walk the top-left rows.  For a rounded rect the first ink column starts
    progressively further left until it reaches the box edge; the row where it
    hits column 0 is the radius.  All four corners vote, the median wins.
    """
    import numpy as np

    x, y, w, h = (int(round(float(v))) for v in bbox)
    if w < 6 or h < 6:
        return 0
    outside = _outside_color(image, bbox)
    if outside is None:
        return 0
    crop = image[y : y + h, x : x + w]
    if crop.size == 0:
        return 0
    # A dark card is ten channels off its page, not two hundred: a fixed
    # tolerance either calls the whole card background (10 < 12) or the whole
    # page corner a surface.  Half the measured gap, bounded by the old constant,
    # separates the two without knowing either colour.
    tolerance = _CORNER_TOLERANCE
    if fill:
        fill_rgb = hex_to_rgb(fill)
        if fill_rgb is not None:
            gap = color_distance(fill_rgb, outside)
            if gap > 0:
                tolerance = max(3.0, min(float(_CORNER_TOLERANCE), gap / 2.0))
    inside = np.abs(crop - np.asarray(outside, dtype=np.int16)).max(axis=2) > tolerance
    limit = int(min(max_radius, w // 2, h // 2))
    if limit < 2:
        return 0
    votes: list[int] = []
    corners = (
        (inside, False),
        (np.flipud(inside), False),
        (np.fliplr(inside), False),
        (np.flipud(np.fliplr(inside)), False),
    )
    for matrix, _ in corners:
        radius = limit
        for row in range(limit):
            indices = np.flatnonzero(matrix[row])
            if indices.size == 0:
                radius = row
                break
            if indices[0] <= 0:
                radius = row
                break
        votes.append(radius)
    votes.sort()
    value = votes[len(votes) // 2]
    if value <= 1:
        return 0
    # Antialiasing erases the last 1-2px of the arc, so the first fully-inked
    # row arrives early; compensate before snapping to a Figma-friendly step.
    value += 2
    if value >= min(w, h) / 2 - 2:
        return 999  # capsule / pill; Figma clamps to half the short side
    return _quantize_radius(value, w, h)


#: 宽高比超过它的东西不可能是胶囊：胶囊的半径是 h/2，而 h/2 的圆角在一条
#: 19:1 的行上读起来是"两端被别的层啃掉了"，不是"故意做成半圆"。表格行、
#: 通栏底纹、分割条都落在这一侧。
PILL_MAX_ASPECT = 8.0


def _quantize_radius(value: int, width: int, height: int) -> int:
    if value <= 1:
        return 0
    short = max(1, min(width, height))
    aspect = max(width, height) / float(short)
    if value >= max(6, int(round(short * 0.42))):
        if aspect > PILL_MAX_ASPECT:
            # 长条不套胶囊：退回一个不改变形状的直角。实测 FluxWeaver 的表格行
            # 829x42 被判成 999，五条行带各自成了半圆，也是 13 帧里多出来的那批。
            return 0
        return 999  # capsule / pill; Figma clamps to half the short side
    for step in _QUANTIZED_RADII:
        if value <= step:
            return step
    return _QUANTIZED_RADII[-1]


def sample_container_decoration(
    image_path: str | Path,
    bbox: Sequence[int],
    fill: str,
) -> dict:
    """One call that returns every container style the compiler can trust."""
    try:
        image = load_rgb(image_path)
    except (OSError, ValueError):
        return {}
    result: dict = {}
    border = detect_border(image, bbox, fill)
    if border:
        result["borderColor"] = border["color"]
        result["borderWidth"] = border["width"]
    radius = estimate_corner_radius(image, bbox, fill=fill)
    if radius:
        result["borderRadius"] = radius
    return result


def ink_line_bands(mask, *, min_gap: int = 2, min_height: int = 2) -> list[tuple[int, int]]:
    """Split an ink mask into horizontal line bands via projection profile.

    A multi-line paragraph produces one band per visual line; a single line
    produces exactly one.  Bands narrower than ``min_height`` are noise from
    descenders or antialiasing and get folded into their neighbour.
    """
    import numpy as np

    if mask.ndim != 2 or mask.size == 0:
        return []
    rows = mask.sum(axis=1)
    # Ignore rows whose ink is negligible relative to the widest line.
    peak = int(rows.max()) if rows.size else 0
    threshold = max(1, int(round(peak * 0.04))) if peak else 1
    bands: list[list[int]] = []
    start = None
    for index, value in enumerate(rows):
        if value > threshold:
            if start is None:
                start = index
        elif start is not None:
            bands.append([start, index])
            start = None
    if start is not None:
        bands.append([start, len(rows)])

    merged: list[list[int]] = []
    for band in bands:
        if merged and band[0] - merged[-1][1] < min_gap:
            merged[-1][1] = band[1]
        else:
            merged.append(band)
    kept = [band for band in merged if band[1] - band[0] >= min_height]
    if not kept:
        return []
    # Descender fragments sit close under their line; merge anything whose gap
    # is smaller than a third of the median band height.
    heights = sorted(band[1] - band[0] for band in kept)
    median_height = heights[len(heights) // 2]
    tight = max(1, int(round(median_height * 0.34)))
    folded: list[list[int]] = []
    for band in kept:
        if folded and band[0] - folded[-1][1] <= tight:
            folded[-1][1] = band[1]
        else:
            folded.append(band)
    return [(band[0], band[1]) for band in folded]


def line_metrics(bands: Sequence[Sequence[int]]) -> dict:
    """Derive font size and line height from line bands (source pixels)."""
    heights = [int(band[1]) - int(band[0]) for band in bands]
    if not heights:
        return {"lineCount": 0}
    heights.sort()
    median_height = heights[len(heights) // 2]
    gaps = [
        int(bands[index + 1][0]) - int(bands[index][0])
        for index in range(len(bands) - 1)
    ]
    gaps = [gap for gap in gaps if gap > 0]
    gaps.sort()
    pitch = gaps[len(gaps) // 2] if gaps else median_height
    return {
        "lineCount": len(heights),
        "medianLineHeight": median_height,
        "linePitch": pitch,
    }


def detect_vertical_gutters(
    image,
    width: int,
    height: int,
    background: str,
    *,
    min_width: int = 8,
    min_share: float = 0.97,
) -> list[tuple[int, int]]:
    """Columns that are page colour from top to bottom: the gaps between cards.

    A two-column layout has a vertical strip of nothing between the columns, and
    that strip is the only geometry that says "these two blocks are not related".
    Reading it from the picture — rather than assuming a centre line — is what
    keeps the guard working on a three-column table or a single centred card.

    ``min_width`` is what separates a gutter from the gap between two words: a
    real gutter is a run of empty columns, not one blank pixel.
    """
    import numpy as np

    if image is None or not background:
        return []
    page = np.asarray(hex_to_rgb(background), dtype=np.int16)
    frame = np.asarray(image[:height, :width], dtype=np.int16)
    if frame.ndim != 3 or frame.shape[2] != 3:
        return []
    empty = (np.abs(frame - page).max(axis=2) <= _BORDER_TOLERANCE).mean(axis=0)
    runs: list[tuple[int, int]] = []
    start = None
    for x in range(frame.shape[1]):
        if empty[x] >= min_share:
            if start is None:
                start = x
        elif start is not None:
            if x - start >= min_width:
                runs.append((start, x))
            start = None
    if start is not None and frame.shape[1] - start >= min_width:
        runs.append((start, frame.shape[1]))
    return runs


def crosses_gutter(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
    gutters: Sequence[tuple[int, int]],
) -> bool:
    """Whether a column gap sits between two boxes (either order)."""
    if not gutters:
        return False
    a0, a1 = left[0], left[0] + left[2]
    b0, b1 = right[0], right[0] + right[2]
    low, high = (a1, b0) if a1 <= b0 else (b1, a0)
    if high <= low:
        return False
    return any(start < high and end > low for start, end in gutters)


def separated_by_page(
    image,
    background: str,
    left: Sequence[int],
    right: Sequence[int],
    *,
    min_width: int = 6,
    share: float = 0.95,
) -> bool:
    """Whether a column of page colour stands between two boxes.

    The strip is measured only across the rows the two boxes share, so a card's
    own white footer or the page above the cards cannot be mistaken for the gap
    between them.  This is the geometric half of "do not merge across columns";
    the semantic half is the caller's own text test.
    """
    import numpy as np

    if image is None or not background:
        return False
    try:
        page = np.asarray(hex_to_rgb(background), dtype=np.int16)
        a = [int(round(float(value))) for value in left]
        b = [int(round(float(value))) for value in right]
    except (TypeError, ValueError):
        return False
    a0, a1 = a[0], a[0] + a[2]
    b0, b1 = b[0], b[0] + b[2]
    strip_low, strip_high = (a1, b0) if a1 <= b0 else (b1, a0)
    if strip_high - strip_low < min_width:
        return False
    top = max(0, max(a[1], b[1]))
    bottom = min(int(image.shape[0]), min(a[1] + a[3], b[1] + b[3]))
    if bottom - top < 2:
        return False
    frame = np.asarray(image[top:bottom, strip_low:strip_high], dtype=np.int16)
    if frame.size == 0:
        return False
    return float((np.abs(frame - page).max(axis=2) <= _BORDER_TOLERANCE).mean()) >= share
