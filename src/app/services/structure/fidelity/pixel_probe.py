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
    inner = _side_bands(bbox, inset=0, thickness=3)
    outer = _side_bands(bbox, inset=-1, thickness=2)
    if not inner or not outer:
        return None
    sides: list[RGB] = []
    for side in ("top", "bottom", "left", "right"):
        chosen: RGB | None = None
        for bands in (inner, outer):
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
    """Sample just outside the top edge; fall back to the bbox corner pixel."""
    x, y, w, _h = (int(round(float(v))) for v in bbox)
    probes = []
    for offset in (2, 3, 4):
        yy = y - offset
        if yy < 0:
            continue
        probes.append((x, yy, x + w, yy + 1))
    color = _median_rgb(image, probes)
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
    inside = np.abs(crop - np.asarray(outside, dtype=np.int16)).max(axis=2) > _CORNER_TOLERANCE
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


def _quantize_radius(value: int, width: int, height: int) -> int:
    if value <= 1:
        return 0
    short = max(1, min(width, height))
    if value >= max(6, int(round(short * 0.42))):
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
    radius = estimate_corner_radius(image, bbox)
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
