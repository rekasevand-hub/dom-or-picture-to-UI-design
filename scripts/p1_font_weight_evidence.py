# -*- coding: utf-8 -*-
"""Phase 1 evidence probe: can stroke geometry separate font weights?

Read-only measurement. Nothing in the pipeline is changed; the only output is
the evidence JSON under ``output/_p1_font_weight_evidence/``.

Why this probe exists
---------------------
Weight is currently a *constant* in the pipeline --
``fontWeight = "bold" if role == "table-header" else "normal"``
(``src/app/services/structure/fidelity/style_resolver.py``).  Phase 1 replaces
that constant with a rule derived from the source pixels.  Before writing such
a rule we must answer, with numbers:

1. Does a sub-pixel stroke index separate the gold ``variationSettings.wght``
   classes at all, and by what margin?
2. Which index is content- and size-robust?  A binary ink mask quantises to
   0.5 px, which at 16 px text is half of the entire 400->700 difference, so
   the probe measures *coverage-integrated* stroke width instead: integrating
   the alpha profile across a stroke run recovers the true geometric width to
   sub-pixel accuracy (area conservation).
3. Is a per-image adaptive threshold as good as a globally fitted one?  The
   roadmap forbids new global constants, so an adaptive rule that loses to a
   constant is not shippable.
4. What mismatch count would each candidate rule produce against the frozen
   answer key -- i.e. what does Phase 1 acceptance actually look like?

Answer key
----------
``gold_tree.json`` carries ``textRuns[0].fontName.{style,variationSettings}``.
``variationSettings.wght`` is an exact numeric weight (400/500/700/900), far
better than the style string ("Bold" vs "SemiBold Italic").

Geometry caveat
---------------
Gold boxes are only usable as crop geometry when the gold frame is
pixel-aligned with ``reference.png``.  That holds for ``light-form`` and
``dark-card-grid`` (1:1, ``scale_to_reference == 1.0``) but **not** for
``light-table``: its gold is a Figma Make reinterpretation whose internal
layout differs, so a gold box lands on empty background (contrast 0).  The
probe detects this automatically (``geometry.alignment``); for such families
the runtime-inventory bbox variant is the only valid measurement path.

Usage
-----
    python scripts/p1_font_weight_evidence.py
    python scripts/p1_font_weight_evidence.py --family dark-card-grid
    python scripts/p1_font_weight_evidence.py --run-root D:/LLM-Data/Figma_auto_agent/output
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

BENCH = ROOT / "tests" / "fixtures" / "benchmark_families"
SCHEMA_VERSION = "p1-font-weight-evidence/1.1"

#: Mirrors ``WEIGHT_LADDER`` in ``figma_bridge/code.js``: a numeric target
#: weight resolves to the nearest available face.  Kept here so a predicted
#: numeric weight can be compared with gold *style strings* on the same ladder.
WEIGHT_LADDER: tuple[tuple[int, str], ...] = (
    (300, "Light"),
    (400, "Regular"),
    (500, "Medium"),
    (600, "SemiBold"),
    (700, "Bold"),
    (800, "ExtraBold"),
    (900, "Black"),
)

#: Below this many coverage pixels the crop is dominated by noise.
MIN_COVERAGE_MASS = 12.0
#: Minimum dominant-line glyph height (px) for a trusted ratio.
MIN_INK_HEIGHT = 6.0
#: Contrast floor: 95th-percentile distance from background.  Under this the
#: crop is flat background (usually a misaligned gold box).
MIN_CONTRAST = 25.0
#: Alpha floor, as a fraction of the foreground level.  Kills sensor/chroma
#: noise without eating genuine anti-aliasing edges.
ALPHA_FLOOR = 0.2
#: Plausibility window for stroke/height.  Real faces sit near 0.04-0.30;
#: anything outside means the crop caught something that is not a text line.
INDEX_MIN, INDEX_MAX = 0.02, 0.60

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# answer-key / geometry loading
# --------------------------------------------------------------------------- #
def normalize_text(text: str) -> str:
    """Casefold and strip whitespace so gold and pipeline strings can meet."""
    return "".join(str(text or "").split()).casefold()


def has_cjk(text: str) -> bool:
    """True when the string contains a CJK ideograph."""
    return any("\u3400" <= char <= "\u9fff" for char in str(text or ""))


def weight_to_style(weight: int | float | None) -> str:
    """Map a numeric weight to the style name Figma would resolve (ladder)."""
    if weight is None:
        return ""
    target = float(weight)
    return min(WEIGHT_LADDER, key=lambda entry: abs(entry[0] - target))[1]


def style_to_weight(style: str) -> int | None:
    """Inverse of :func:`weight_to_style` for gold style strings."""
    raw = str(style or "").strip().lower()
    if not raw:
        return None
    if raw.startswith("semi"):
        return 600
    if raw.startswith("extra") or raw.startswith("ultra"):
        return 800
    table = {
        "thin": 100,
        "hairline": 100,
        "extralight": 200,
        "ultralight": 200,
        "light": 300,
        "book": 400,
        "regular": 400,
        "normal": 400,
        "roman": 400,
        "medium": 500,
        "demibold": 600,
        "bold": 700,
        "black": 900,
        "heavy": 900,
    }
    for name, weight in table.items():
        if raw.startswith(name):
            return weight
    return None


def flatten_gold_texts(tree: dict[str, Any], scale: float) -> list[dict[str, Any]]:
    """Flatten gold TEXT nodes into absolute ``reference.png`` pixel boxes.

    Coordinates are accumulated down the tree (gold keeps child boxes relative
    to their parent) and then multiplied by ``scale``.  Deliberately duplicated
    from the gate script rather than imported: the gate is a CLI, not a
    package, and this evidence must stay reproducible on its own.

    Args:
        tree: Gold node tree (``gold_tree.json``).
        scale: ``gold.scale_to_reference`` from ``family.json``.

    Returns:
        One record per TEXT node with ``bbox``/``font_size`` in reference
        pixels and the numeric gold weight (``None`` when unstated).
    """
    root = dict(tree)
    root["x"], root["y"] = 0, 0
    records: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], ox: float, oy: float) -> None:
        x = ox + float(node.get("x") or 0)
        y = oy + float(node.get("y") or 0)
        if node.get("type") == "TEXT":
            runs = node.get("textRuns") or []
            font = (runs[0].get("fontName") if runs else node.get("fontName")) or {}
            size = node.get("fontSize") or (runs[0].get("fontSize") if runs else None)
            variation = font.get("variationSettings") or {}
            wght = variation.get("wght")
            if not isinstance(wght, (int, float)):
                wght = style_to_weight(font.get("style") or "")
            records.append(
                {
                    "text": str(node.get("characters") or ""),
                    "key": normalize_text(node.get("characters")),
                    "bbox": [
                        round(x * scale, 2),
                        round(y * scale, 2),
                        round(float(node.get("width") or 0) * scale, 2),
                        round(float(node.get("height") or 0) * scale, 2),
                    ],
                    "font_size": round(float(size) * scale, 2)
                    if isinstance(size, (int, float))
                    else None,
                    "font_family": str(font.get("family") or ""),
                    "gold_style": str(font.get("style") or ""),
                    "gold_weight": int(wght) if isinstance(wght, (int, float)) else None,
                    "cjk": has_cjk(node.get("characters")),
                }
            )
        for child in node.get("children") or []:
            walk(child, x, y)

    walk(root, 0.0, 0.0)
    return records


# --------------------------------------------------------------------------- #
# pixel measurement
# --------------------------------------------------------------------------- #
def _ring_background(crop: np.ndarray, inset: int = 2) -> np.ndarray:
    """Median RGB of the crop border ring (theme-agnostic background probe)."""
    inner = crop[
        inset : max(inset + 1, crop.shape[0] - inset),
        inset : max(inset + 1, crop.shape[1] - inset),
    ]
    border = np.concatenate(
        [inner[0, :, :], inner[-1, :, :], inner[:, 0, :], inner[:, -1, :]], axis=0
    )
    return np.median(border, axis=0)


def coverage_map(crop: np.ndarray) -> tuple[np.ndarray, float]:
    """Per-pixel ink coverage in ``[0, 1]`` relative to the foreground level.

    This is the metric that makes weight inference possible at text sizes:
    a binary mask can only report integer widths (2 or 3 px), while the
    integrated alpha across a stroke run returns the true geometric width
    (e.g. 2.4 px) because edge pixels keep their fractional contribution.

    Args:
        crop: ``(h, w, 3)`` RGB crop.

    Returns:
        ``(alpha, contrast)``.  ``contrast`` is the 95th-percentile distance
        from the background, i.e. the foreground level used for normalisation.
    """
    background = _ring_background(crop)
    distance = (
        np.abs(crop.astype(np.int16) - background.reshape(1, 1, 3)).max(axis=2)
    ).astype(np.float64)
    # Foreground level must be measured over *ink* pixels only.  Taking the
    # 95th percentile of the whole crop reads 0 whenever ink covers <5 % of
    # the box (sparse text lines, tight cells) and silently kills the
    # measurement -- the failure that made light-table look unmeasurable.
    strong = distance[distance > 8.0]
    contrast = float(np.percentile(strong, 95)) if strong.size else 0.0
    if contrast <= 0:
        return np.zeros_like(distance), 0.0
    alpha = np.clip(distance / contrast, 0.0, 1.0)
    alpha[alpha < ALPHA_FLOOR] = 0.0
    return alpha, contrast


def ink_bands(alpha: np.ndarray, gap: float) -> list[tuple[int, int]]:
    """Split coverage rows into text-line bands, merging gaps under ``gap``."""
    rows = np.flatnonzero(alpha.sum(axis=1) > 0.5)
    if rows.size == 0:
        return []
    bands: list[tuple[int, int]] = []
    start = prev = int(rows[0])
    for row in rows[1:]:
        row = int(row)
        if row - prev > gap:
            bands.append((start, prev + 1))
            start = row
        prev = row
    bands.append((start, prev + 1))
    return bands


def stroke_widths(alpha: np.ndarray, axis: int) -> np.ndarray:
    """Sub-pixel widths of ink runs along ``axis`` (1 = x, 0 = y).

    A stroke of geometric width ``w`` contributes runs whose alpha sums to
    ``w``; run gaps of a single zero pixel are stitched so that an
    anti-aliased stroke is not split in two.
    """
    data = alpha if axis == 1 else alpha.T
    widths: list[float] = []
    for row in data:
        columns = np.flatnonzero(row > 0)
        if columns.size == 0:
            continue
        breaks = np.flatnonzero(np.diff(columns) > 1)
        starts = np.concatenate(([columns[0]], columns[breaks + 1]))
        ends = np.concatenate((columns[breaks], [columns[-1]]))
        for start, end in zip(starts, ends):
            width = float(row[start : end + 1].sum())
            if width > 0:
                widths.append(width)
    return np.asarray(widths, dtype=np.float64)


def measure_text(
    image: np.ndarray,
    bbox: Sequence[float],
    *,
    font_size: float | None,
) -> dict[str, Any] | None:
    """Measure stroke geometry for one text box on a reference image.

    Args:
        image: Full reference image as ``(h, w, 3)`` RGB.
        bbox: ``[x, y, w, h]`` in reference pixels.
        font_size: Nominal font size (reference px) for the line-gap heuristic.

    Returns:
        Metrics dict, or ``None`` when the box is unusable (out of frame,
        flat background, too little ink, or an implausible index).
    """
    height, width = image.shape[:2]
    x, y, box_w, box_h = (int(round(float(value))) for value in bbox[:4])
    x, y = max(0, x), max(0, y)
    box_w, box_h = min(box_w, width - x), min(box_h, height - y)
    if box_w < 3 or box_h < 3:
        return None
    crop = image[y : y + box_h, x : x + box_w]
    if crop.size == 0:
        return None

    alpha, contrast = coverage_map(crop)
    if contrast < MIN_CONTRAST:
        return None
    total_mass = float(alpha.sum())
    if total_mass < MIN_COVERAGE_MASS:
        return None

    gap = max(2.0, 0.35 * float(font_size or box_h))
    bands = ink_bands(alpha, gap)
    if not bands:
        return None
    dominant = max(bands, key=lambda band: float(alpha[band[0] : band[1]].sum()))
    line = alpha[dominant[0] : dominant[1]]
    if float(line.sum()) < MIN_COVERAGE_MASS:
        return None

    rows = np.flatnonzero(line.sum(axis=1) > 0.5)
    columns = np.flatnonzero(line.sum(axis=0) > 0.5)
    if rows.size < 2 or columns.size < 2:
        return None
    ink_h = float(rows.max() - rows.min() + 1)
    ink_w = float(columns.max() - columns.min() + 1)
    if ink_h < MIN_INK_HEIGHT or ink_w < 2:
        return None

    horizontal = stroke_widths(line, axis=1)  # vertical stems
    vertical = stroke_widths(line, axis=0)  # horizontal bars
    if horizontal.size == 0 or vertical.size == 0:
        return None
    # Pool both directions before taking the median.  Per-direction medians
    # break on degenerate shapes -- a glyph of pure vertical stems ("川",
    # "|||") has a vertical run equal to the whole stem, which inflates it to
    # the glyph height.  Pooled, the many thin runs outvote the few long ones,
    # and real text is unaffected because both directions sample the stroke.
    pooled = np.concatenate([horizontal, vertical])
    stroke = float(np.median(pooled))
    stroke_h = float(np.median(horizontal))
    stroke_v = float(np.median(vertical))

    index_height = stroke / ink_h
    if not (INDEX_MIN <= index_height <= INDEX_MAX):
        return None

    return {
        "ink_height": round(ink_h, 2),
        "ink_width": round(ink_w, 2),
        "stroke_px": round(stroke, 3),
        "stroke_h_px": round(stroke_h, 3),
        "stroke_v_px": round(stroke_v, 3),
        # Resolution floor: below ~2 px of geometric stroke, one pixel of
        # quantisation is more than a quarter of the signal, and the 400->700
        # difference (0.4-0.9 px at 1x) disappears into anti-aliasing noise.
        # This is a physical limit of the raster, not a tuned constant --
        # measured: 1x 12-17 px text lands at 1.0-2.0 px stroke, 2x 24 px text
        # at 2.5-3.5 px, 2x Bold at 3.5-6 px.
        "resolution_ok": bool(stroke >= 2.0),
        # Primary index: stroke relative to rendered glyph height.  Content
        # robust (wide and narrow glyphs of one face share the ratio), scale
        # invariant, polarity invariant.
        "index_height": round(index_height, 4),
        # Secondary index: stroke relative to the nominal em size.
        "index_size": round(stroke / float(font_size), 4) if font_size else None,
        # Density indices: the roadmap's "ink coverage" hypothesis.  Measured
        # so the doc can show *why* they lose (character-content sensitivity).
        "density_line": round(float(line.sum()) / (ink_h * ink_w), 4),
        "density_box": round(float(line.sum()) / (box_w * box_h), 4),
        "bands": len(bands),
        "contrast": round(contrast, 2),
        "run_count": int(horizontal.size + vertical.size),
    }


# --------------------------------------------------------------------------- #
# decision rules under evaluation
# --------------------------------------------------------------------------- #
def kmeans_1d(values: Iterable[float], k: int) -> list[float]:
    """Deterministic 1-D k-means; returns ascending centres.

    Quantile initialisation (no RNG) keeps the evidence reproducible run to
    run -- the same discipline the gate demands.
    """
    data = np.sort(np.asarray(list(values), dtype=np.float64))
    if data.size == 0 or k <= 1:
        return [float(data.mean())] if data.size else []
    k = min(k, data.size)
    centres = np.quantile(data, [(i + 0.5) / k for i in range(k)])
    for _ in range(50):
        labels = np.abs(data[:, None] - centres[None, :]).argmin(axis=1)
        moved = np.array(
            [
                data[labels == index].mean()
                if (labels == index).any()
                else centres[index]
                for index in range(k)
            ]
        )
        if np.allclose(moved, centres):
            break
        centres = moved
    return sorted(float(value) for value in centres)


def thresholds_from_centres(centres: Sequence[float]) -> list[float]:
    """Midpoints between ascending cluster centres."""
    return [(a + b) / 2 for a, b in zip(centres, centres[1:])]


def assign_bins(value: float, thresholds: Sequence[float]) -> int:
    """Bin index for ``value`` given ascending thresholds."""
    return sum(1 for threshold in thresholds if value > threshold)


def otsu_split(values: Sequence[float]) -> dict[str, Any]:
    """Two-class Otsu split with its goodness measure.

    ``eta`` (between-class / total sum of squares) is reported as a *diagnostic
    only*.  It is **not** a bimodality test: for a single Gaussian, Otsu split
    at the mean already yields ``eta = 2/pi ~= 0.637``, so any gate around 0.5
    passes unimodal data.  Measured on the three benchmark families, ``eta``
    reaches 0.86 on an all-Regular page, which is why this probe does not use
    it as a decision gate.

    Args:
        values: Index values for one group (one image, one script).

    Returns:
        ``{threshold, eta, fisher, low_median, high_median, low_n, high_n}``.
    """
    data = np.sort(np.asarray(list(values), dtype=np.float64))
    if data.size < 4 or float(data.max()) <= float(data.min()):
        return {"threshold": float(data.mean()) if data.size else 0.0, "eta": 0.0}
    best = {"threshold": float(data[0]), "eta": 0.0}
    total_variance = float(data.var())
    if total_variance <= 0:
        return {**best, "eta": 0.0}
    candidates = np.unique((data[:-1] + data[1:]) / 2)
    for threshold in candidates:
        low = data[data <= threshold]
        high = data[data > threshold]
        if low.size == 0 or high.size == 0:
            continue
        between = (low.size * high.size / data.size) * (low.mean() - high.mean()) ** 2
        # Otsu's eta: between-class sum of squares / total sum of squares.
        eta = float(between / (total_variance * data.size))
        if eta > best["eta"]:
            low_n, high_n = int(low.size), int(high.size)
            spread = float(np.sqrt((low.var() + high.var()) / 2)) or 1e-9
            best = {
                "threshold": float(threshold),
                "eta": round(eta, 4),
                "fisher": round(float(abs(low.mean() - high.mean()) / spread), 3),
                "low_median": round(float(np.median(low)), 4),
                "high_median": round(float(np.median(high)), 4),
                "low_n": low_n,
                "high_n": high_n,
            }
    return best


def multiotsu_split(values: Sequence[float], k: int) -> list[float]:
    """Multi-level Otsu by exhaustive search over ``k-1`` cuts.

    Only used for k <= 3 on a few dozen samples, so the quadratic search over
    unique midpoints is cheap and, unlike k-means, stays honest under class
    imbalance (it minimises weighted within-class variance).
    """
    data = np.sort(np.asarray(list(values), dtype=np.float64))
    if data.size < k * 2:
        return []
    candidates = np.unique((data[:-1] + data[1:]) / 2)
    if k == 2:
        split = otsu_split(data)
        return [float(split["threshold"])]
    best_eta = -1.0
    best_cuts: list[float] = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            cuts = (candidates[i], candidates[j])
            groups = [data[data <= cuts[0]], data[(data > cuts[0]) & (data <= cuts[1])], data[data > cuts[1]]]
            if any(group.size == 0 for group in groups):
                continue
            between = sum(group.size * (group.mean() - data.mean()) ** 2 for group in groups)
            eta = float(between / (data.var() * data.size)) if data.var() > 0 else 0.0
            if eta > best_eta:
                best_eta = eta
                best_cuts = [float(c) for c in cuts]
    return best_cuts


def auc(values: Sequence[float], labels: Sequence[int]) -> float | None:
    """Rank AUC of the index for a binary label (1 = heavier).

    Rank-sum based (Mann-Whitney U), so it is threshold free: it says whether
    the index *orders* weights correctly, independent of where a cut is placed.
    """
    data = np.asarray(values, dtype=np.float64)
    truth = np.asarray(labels, dtype=np.int64)
    positives = int(truth.sum())
    negatives = int(truth.size - positives)
    if positives == 0 or negatives == 0:
        return None
    order = data.argsort(kind="mergesort")
    sorted_data = data[order]
    ranks = np.empty(data.size, dtype=np.float64)
    ranks[order] = np.arange(1, data.size + 1)
    index = 0
    while index < data.size:
        stop = index
        while stop + 1 < data.size and sorted_data[stop + 1] == sorted_data[index]:
            stop += 1
        if stop > index:
            average = float(ranks[order[index : stop + 1]].mean())
            ranks[order[index : stop + 1]] = average
        index = stop + 1
    rank_sum = float(ranks[truth == 1].sum())
    return round((rank_sum - positives * (positives + 1) / 2) / (positives * negatives), 4)


# --------------------------------------------------------------------------- #
# family measurement
# --------------------------------------------------------------------------- #
def load_image(path: Path) -> np.ndarray:
    """Load a PNG as an RGB array (alpha dropped so dark themes read right)."""
    from PIL import Image

    with Image.open(path) as source:
        return np.asarray(source.convert("RGB"))


def group_key(sample: dict[str, Any]) -> tuple[str, str]:
    """Grouping for threshold fitting: font family + script (physics differ)."""
    return (
        str(sample.get("font_family") or "?"),
        "cjk" if sample.get("cjk") else "latin",
    )


def measurable(samples: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Samples that carry both a measurement and a numeric gold weight."""
    return [s for s in samples if s.get("metrics") and s.get("gold_weight")]


def alignment_report(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """How many gold boxes actually land on ink in the reference image.

    A low ``ink_fraction`` means the gold frame is a layout reinterpretation,
    not a pixel-aligned answer key: cropping at gold boxes measures background,
    so only the runtime-inventory path is valid for that family.
    """
    measurable_count = sum(1 for s in samples if s.get("metrics"))
    total = len(samples)
    contrasts = [
        float(s["metrics"]["contrast"]) for s in samples if s.get("metrics")
    ]
    fraction = measurable_count / total if total else 0.0
    return {
        "ink_fraction": round(fraction, 3),
        "median_contrast": round(float(np.median(contrasts)), 1) if contrasts else 0.0,
        "usable": fraction >= 0.8,
    }


def distribution_table(samples: Sequence[dict[str, Any]], index: str) -> dict[str, Any]:
    """Per (font family, script, gold weight) stats of one index.

    Reports median and IQR so the doc can show *overlap*, which is the only
    thing that decides whether a threshold rule is shippable.
    """
    grouped: dict[tuple[str, str], dict[int, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for sample in measurable(samples):
        value = sample["metrics"].get(index)
        if value is None:
            continue
        grouped[group_key(sample)][int(sample["gold_weight"])].append(float(value))

    table: dict[str, Any] = {}
    for (font, script), by_weight in sorted(grouped.items()):
        label = f"{font}|{script}"
        table[label] = {}
        for weight, values in sorted(by_weight.items()):
            array = np.asarray(values)
            table[label][str(weight)] = {
                "n": int(array.size),
                "median": round(float(np.median(array)), 4),
                "p25": round(float(np.percentile(array, 25)), 4),
                "p75": round(float(np.percentile(array, 75)), 4),
                "min": round(float(array.min()), 4),
                "max": round(float(array.max()), 4),
            }
    return table


def group_scores(samples: Sequence[dict[str, Any]], index: str) -> dict[str, Any]:
    """Evaluate the index inside each (font family, script) group.

    Fitting a single threshold across fonts and scripts is invalid by
    construction: JetBrains Mono Regular sits at a higher stroke/height than
    Noto Sans SC Bold.  Scores are therefore per group, and only groups that
    actually contain two or more weight classes can be scored at all.

    Rules compared inside a group:
      ``constant``  current pipeline behaviour (every text 400).
      ``adaptive``  k-means over the group's own index values, ``k`` = number
                    of classes present, mapped to weights by rank.  This is an
                    *optimistic* bound: a shipping rule cannot know ``k``.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for sample in measurable(samples):
        if sample["metrics"].get(index) is not None:
            grouped[group_key(sample)].append(sample)

    groups: dict[str, Any] = {}
    total = scored = 0
    constant_mismatch = adaptive_mismatch = 0
    for (font, script), members in sorted(grouped.items()):
        values = [float(s["metrics"][index]) for s in members]
        weights = sorted({int(s["gold_weight"]) for s in members})
        entry: dict[str, Any] = {
            "n": len(members),
            "weights": weights,
            "class_counts": {str(w): sum(1 for s in members if int(s["gold_weight"]) == w) for w in weights},
            "auc": {},
        }
        for lighter, heavier in zip(weights, weights[1:]):
            combined = [
                float(s["metrics"][index])
                for s in members
                if int(s["gold_weight"]) in (lighter, heavier)
            ]
            labels = [
                1 if int(s["gold_weight"]) == heavier else 0
                for s in members
                if int(s["gold_weight"]) in (lighter, heavier)
            ]
            entry["auc"][f"{lighter}>{heavier}"] = {
                "n": len(combined),
                "auc": auc(combined, labels),
            }
        heavy = [float(s["metrics"][index]) for s in members if int(s["gold_weight"]) >= 700]
        light = [float(s["metrics"][index]) for s in members if int(s["gold_weight"]) < 700]
        if heavy and light:
            entry["auc"]["<700_vs_>=700"] = {
                "n": len(heavy) + len(light),
                "auc": auc(light + heavy, [0] * len(light) + [1] * len(heavy)),
            }
        if len(weights) >= 2 and len(members) >= 4:
            centres = kmeans_1d(values, len(weights))
            thresholds = thresholds_from_centres(centres)
            mismatches = sum(
                1
                for sample in members
                if weights[assign_bins(float(sample["metrics"][index]), thresholds)]
                != int(sample["gold_weight"])
            )
            entry["adaptive"] = {
                "mismatch": mismatches,
                "of": len(members),
                "centres": [round(c, 4) for c in centres],
                "mapped_weights": weights,
            }
            entry["constant"] = {
                "mismatch": sum(1 for s in members if int(s["gold_weight"]) != 400),
                "of": len(members),
            }
            adaptive_mismatch += mismatches
            constant_mismatch += entry["constant"]["mismatch"]
            scored += len(members)
        total += len(members)
        groups[f"{font}|{script}"] = entry
    return {
        "groups": groups,
        "covered": total,
        "scored": scored,
        "constant_mismatch": constant_mismatch,
        "adaptive_mismatch": adaptive_mismatch,
    }


# --------------------------------------------------------------------------- #
# shippable candidate rule
# --------------------------------------------------------------------------- #
def binary_rule_eval(
    samples: Sequence[dict[str, Any]], index: str, *, eta_gate: float | None = None
) -> dict[str, Any]:
    """Evaluate the rule that could ship: one adaptive binary split.

    Why binary and not 3/4-way: the adjacent-class AUCs reported by
    :func:`group_scores` show the 400/500 boundary is the weak one, while
    ``<700 vs >=700`` is strong.  A rule that guesses four classes loses more
    than it gains.

    Why per script and not per font family: at runtime the source font family
    is *unknown* (only the string and the crop are available), while CJK vs
    Latin is knowable from the text itself.  Grouping by script is therefore
    the strongest split a shipping rule can make.

    Honest limitation (measured, see the Phase 1 evidence doc): an *unanchored*
    adaptive split cannot tell "two weights" from "one weight whose stroke
    drifts with size".  On light-table -- every gold text Regular -- the split
    fires anyway and invents Bolds.  The probe keeps this rule precisely to
    quantify that failure; it is **not** a recommendation to ship it.

    Unmeasurable boxes fall back to 400 and stay in the denominator, so the
    reported mismatch is end-to-end, not conditional on a good crop.

    Args:
        samples: Family samples (gold weight + optional metrics).
        index: Which index to threshold.
        eta_gate: Deprecated; retained for call compatibility.  ``eta`` is not
            a bimodality test (see :func:`otsu_split`) and is never gated on.

    Returns:
        Per-script splits plus the aggregate mismatch.
    """
    by_script: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        if sample.get("gold_weight"):
            by_script["cjk" if sample.get("cjk") else "latin"].append(sample)

    per_script: dict[str, Any] = {}
    total = mismatch = applied = 0
    confusion: Counter[tuple[int, int]] = Counter()
    for script, members in sorted(by_script.items()):
        values = [
            float(s["metrics"][index])
            for s in members
            if s.get("metrics")
            and s["metrics"].get(index) is not None
            and s["metrics"].get("resolution_ok")
        ]
        split = otsu_split(values) if len(values) >= 4 else {"threshold": 0.0, "eta": 0.0}
        # Only guard that survives contact with the data: a "class" of one or
        # two outliers is not a weight class.  Without it a single Black
        # headline turns a page of Regulars into a fake bimodal split.
        # (eta is deliberately NOT gated -- it reads ~0.64 on unimodal data.)
        low_share = float(split.get("low_n") or 0)
        high_share = float(split.get("high_n") or 0)
        minimum = max(3.0, 0.12 * max(1, len(values)))
        balanced = min(low_share, high_share) >= minimum
        use_split = len(values) >= 4 and balanced
        script_mismatch = 0
        for sample in members:
            metrics = sample.get("metrics") or {}
            value = metrics.get(index)
            usable = bool(metrics.get("resolution_ok")) and value is not None
            if use_split and usable:
                predicted = 700 if float(value) > float(split["threshold"]) else 400
                applied += 1
            else:
                predicted = 400
            gold = int(sample["gold_weight"])
            confusion[(gold, predicted)] += 1
            script_mismatch += int(predicted != gold)
        total += len(members)
        mismatch += script_mismatch
        per_script[script] = {
            "n": len(members),
            "measured": len(values),
            "split_applied": use_split,
            "threshold": round(float(split.get("threshold") or 0.0), 4),
            "eta": float(split.get("eta") or 0.0),
            "mismatch": script_mismatch,
            "class_counts": dict(Counter(int(s["gold_weight"]) for s in members)),
        }
    return {
        "n": total,
        "mismatch": mismatch,
        "split_applied_to": applied,
        "per_script": per_script,
        "confusion": {f"{a}->{b}": c for (a, b), c in sorted(confusion.items()) if a != b},
    }


# --------------------------------------------------------------------------- #
# runtime-bbox variant (needs the frozen pipeline runs)
# --------------------------------------------------------------------------- #
def resolve_run_dir(meta: dict[str, Any], run_root: Path | None) -> Path | None:
    """Resolve ``pipeline_run`` against the worktree or an external run root.

    Registration stores paths relative to the repo that produced them, so a
    worktree without ``output/`` must be pointed at the owning repo.
    """
    relative = str(meta.get("pipeline_run") or "")
    if not relative:
        return None
    candidates: list[Path] = []
    if run_root is not None:
        candidates.append(run_root / Path(relative).name)
        candidates.append(run_root / relative)
    candidates.append(ROOT / relative)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def load_inventory_texts(run_dir: Path) -> list[dict[str, Any]]:
    """Text owners the perception layer actually produced (source pixels)."""
    path = run_dir / "pipeline" / "10_content_inventory.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        item
        for item in data.get("items") or []
        if item.get("kind") == "text" and item.get("bbox")
    ]


def match_runtime(
    gold_samples: Sequence[dict[str, Any]], inventory: Sequence[dict[str, Any]]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Pair gold boxes with inventory boxes by text, nearest position first."""
    pools: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in inventory:
        pools[normalize_text(item.get("text"))].append(item)
    used: set[int] = set()
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for sample in gold_samples:
        best: tuple[float, dict[str, Any]] | None = None
        for item in pools.get(sample["key"]) or []:
            if id(item) in used:
                continue
            bbox = item["bbox"]
            distance = abs(bbox[0] - sample["bbox"][0]) + abs(bbox[1] - sample["bbox"][1])
            if best is None or distance < best[0]:
                best = (distance, item)
        if best is None:
            continue
        used.add(id(best[1]))
        pairs.append((sample, best[1]))
    return pairs


def runtime_bbox_scores(
    family_dir: Path,
    samples: Sequence[dict[str, Any]],
    index: str,
    run_root: Path | None,
) -> dict[str, Any] | None:
    """Measure the index on perception bboxes instead of gold bboxes.

    This is the honest upper bound for a shipping rule: perception never
    reproduces the gold box, and on layout-shifted gold families it is the
    only valid geometry.
    """
    meta = json.loads((family_dir / "family.json").read_text(encoding="utf-8"))
    run_dir = resolve_run_dir(meta, run_root)
    if run_dir is None:
        return {"status": "run-missing"}
    inventory = load_inventory_texts(run_dir)
    if not inventory:
        return {"status": "inventory-missing"}
    image = load_image(family_dir / "reference.png")
    pairs = match_runtime([s for s in samples if s.get("gold_weight")], inventory)

    measured: list[dict[str, Any]] = []
    for gold, runtime in pairs:
        metrics = measure_text(image, runtime["bbox"], font_size=gold.get("font_size"))
        if metrics is None or metrics.get(index) is None:
            continue
        measured.append({**gold, "metrics": metrics, "runtime_bbox": runtime["bbox"]})
    if not measured:
        return {"status": "no-measurement", "inventory_texts": len(inventory)}

    scored = group_scores(measured, index)
    return {
        "status": "ok",
        "run_dir": str(run_dir),
        "inventory_texts": len(inventory),
        "matched": len(pairs),
        "measured": len(measured),
        "binary": binary_rule_eval(measured, index),
        **scored,
    }


def geometry_sensitivity(
    family_dir: Path,
    samples: Sequence[dict[str, Any]],
    index: str,
    run_root: Path | None,
) -> dict[str, Any] | None:
    """Compare the same text measured in a gold box and a runtime box.

    This is the probe's most important negative control.  A weight index is
    only usable if it does not depend on *how the box was drawn*.  Perception
    boxes are tight to the ink and routinely clip ascenders/descenders, while
    gold boxes carry the full em height; if ``index`` shifts between the two,
    every threshold fitted on gold boxes is void at runtime.

    Returns:
        ``{pairs, ratio_median, ratio_p05, ratio_p95}`` where ``ratio`` is
        ``runtime_index / gold_index`` for matched texts, or ``None`` when no
        run is available.
    """
    meta = json.loads((family_dir / "family.json").read_text(encoding="utf-8"))
    run_dir = resolve_run_dir(meta, run_root)
    if run_dir is None:
        return None
    inventory = load_inventory_texts(run_dir)
    if not inventory:
        return None
    image = load_image(family_dir / "reference.png")
    ratios: list[float] = []
    pairs = 0
    for gold, runtime in match_runtime([s for s in samples if s.get("gold_weight")], inventory):
        gold_value = (gold.get("metrics") or {}).get(index)
        runtime_metrics = measure_text(image, runtime["bbox"], font_size=gold.get("font_size"))
        runtime_value = (runtime_metrics or {}).get(index)
        if not gold_value or not runtime_value:
            continue
        pairs += 1
        ratios.append(float(runtime_value) / float(gold_value))
    if not ratios:
        return {"pairs": 0}
    array = np.asarray(ratios)
    return {
        "pairs": pairs,
        "ratio_median": round(float(np.median(array)), 3),
        "ratio_p05": round(float(np.percentile(array, 5)), 3),
        "ratio_p95": round(float(np.percentile(array, 95)), 3),
        "within_10pct": round(float((np.abs(array - 1.0) <= 0.1).mean()), 3),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_distribution(table: dict[str, Any], index: str) -> None:
    print(f"\n-- {index} by (font|script, gold wght) --")
    for label, by_weight in table.items():
        print(f"  {label}")
        for weight, stats in by_weight.items():
            print(
                f"    w{weight:<4} n={stats['n']:<3} median={stats['median']:<7} "
                f"p25={stats['p25']:<7} p75={stats['p75']:<7} "
                f"[{stats['min']}, {stats['max']}]"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", action="append", help="restrict to family name(s)")
    parser.add_argument(
        "--run-root",
        default=None,
        help="root holding the frozen pipeline runs (default: <repo>/output)",
    )
    parser.add_argument(
        "--out",
        default="output/_p1_font_weight_evidence/evidence.json",
        help="evidence JSON output path",
    )
    args = parser.parse_args(argv)

    family_dirs = sorted(
        (d for d in BENCH.iterdir() if d.is_dir() and (d / "gold_tree.json").is_file()),
        key=lambda d: d.name,
    )
    if args.family:
        wanted = set(args.family)
        family_dirs = [d for d in family_dirs if d.name in wanted]
    if not family_dirs:
        print(f"[fail] no families under {BENCH}")
        return 2

    run_root = Path(args.run_root).resolve() if args.run_root else ROOT / "output"
    indices = ("index_height", "index_size", "density_line")
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "indices": list(indices),
        "run_root": str(run_root),
        "families": {},
    }

    print(f"[probe] {len(family_dirs)} family(ies), run_root={run_root}")
    for family_dir in family_dirs:
        meta = json.loads((family_dir / "family.json").read_text(encoding="utf-8"))
        family = meta.get("family") or family_dir.name
        scale = float(meta.get("gold", {}).get("scale_to_reference") or 1.0)
        gold = json.loads((family_dir / "gold_tree.json").read_text(encoding="utf-8"))
        image = load_image(family_dir / "reference.png")
        records = flatten_gold_texts(gold, scale)
        samples = [
            {
                **record,
                "family": family,
                "metrics": measure_text(
                    image, record["bbox"], font_size=record.get("font_size")
                ),
            }
            for record in records
        ]
        aligned = alignment_report(samples)

        entry: dict[str, Any] = {
            "reference": [int(image.shape[1]), int(image.shape[0])],
            "scale_to_reference": scale,
            "gold_texts": len(records),
            "geometry": aligned,
            "measured": len(measurable(samples)),
            "gold_weight_counts": dict(
                Counter(int(s["gold_weight"]) for s in measurable(samples))
            ),
            "samples": [
                {
                    "text": s["text"][:32],
                    "font_family": s["font_family"],
                    "gold_weight": s["gold_weight"],
                    "gold_style": s["gold_style"],
                    "font_size": s["font_size"],
                    "cjk": s["cjk"],
                    "bbox": s["bbox"],
                    **(s["metrics"] or {}),
                }
                for s in samples
            ],
        }
        for index in indices:
            entry[f"distribution_{index}"] = distribution_table(samples, index)
            entry[f"groups_{index}"] = group_scores(samples, index)
            entry[f"binary_{index}"] = binary_rule_eval(samples, index)
        entry["runtime_variant"] = {
            index: runtime_bbox_scores(family_dir, samples, index, run_root)
            for index in ("index_height", "index_size")
        }
        entry["geometry_sensitivity"] = {
            index: geometry_sensitivity(family_dir, samples, index, run_root)
            for index in ("index_height", "index_size")
        }
        report["families"][family] = entry

        print(f"\n===== {family} =====")
        print(
            f"  reference={entry['reference']} scale={scale} gold_texts={len(records)} "
            f"measured={entry['measured']} weights={entry['gold_weight_counts']}"
        )
        print(
            f"  geometry: ink_fraction={aligned['ink_fraction']} "
            f"median_contrast={aligned['median_contrast']} usable={aligned['usable']}"
        )
        for index in indices:
            scored = entry[f"groups_{index}"]
            binary = entry[f"binary_{index}"]
            if binary["n"]:
                print(
                    f"  [{index}] binary-adaptive={binary['mismatch']}/{binary['n']}  "
                    f"split_applied={binary['split_applied_to']}"
                )
                for script, info in binary["per_script"].items():
                    print(
                        f"    {script:<6} n={info['n']:<3} measured={info['measured']:<3} "
                        f"eta={info['eta']:<6} applied={info['split_applied']!s:<5} "
                        f"mismatch={info['mismatch']}/{info['n']} classes={info['class_counts']}"
                    )
            if not scored["scored"]:
                continue
            print(
                f"  [{index}] scored n={scored['scored']}  "
                f"constant={scored['constant_mismatch']}/{scored['scored']}  "
                f"adaptive={scored['adaptive_mismatch']}/{scored['scored']}"
            )
            for label, group in scored["groups"].items():
                if "adaptive" not in group:
                    continue
                aucs = " ".join(
                    f"{pair}:{value['auc']}" for pair, value in group["auc"].items()
                )
                print(
                    f"    {label:<24} n={group['n']:<3} classes={group['weights']} "
                    f"adaptive={group['adaptive']['mismatch']}/{group['adaptive']['of']}  {aucs}"
                )
        runtime = entry["runtime_variant"]["index_height"]
        if runtime and runtime.get("status") == "ok":
            binary = runtime.get("binary") or {}
            print(
                f"  [runtime bbox] matched={runtime['matched']}/{runtime['inventory_texts']} "
                f"measured={runtime['measured']} "
                f"binary={binary.get('mismatch')}/{binary.get('n')} "
                f"(applied to {binary.get('split_applied_to')})"
            )
            for script, info in (binary.get("per_script") or {}).items():
                print(
                    f"    {script:<6} n={info['n']:<3} measured={info['measured']:<3} "
                    f"eta={info['eta']:<6} applied={info['split_applied']!s:<5} "
                    f"mismatch={info['mismatch']}/{info['n']} classes={info['class_counts']}"
                )
        else:
            print(f"  [runtime bbox] {runtime.get('status') if runtime else 'unavailable'}")
        sensitivity = entry["geometry_sensitivity"]["index_height"]
        if sensitivity and sensitivity.get("pairs"):
            print(
                f"  [geometry sensitivity] pairs={sensitivity['pairs']} "
                f"runtime/gold index median={sensitivity['ratio_median']} "
                f"p05={sensitivity['ratio_p05']} p95={sensitivity['ratio_p95']} "
                f"within10pct={sensitivity['within_10pct']}"
            )

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[out] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
