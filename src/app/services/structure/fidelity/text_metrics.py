"""Put a text node where its ink actually is.

The last round of measurement left one number unexplained: the residual error is
68-80% inside text boxes, and per box it is not a global factor — 44 of 61
left-aligned labels on AtomGit sat 3-9px left of the truth, CJK runs came out
6-12% narrow, while Latin runs were exact.  Font family and a global CJK size
multiplier were both measured and both made it worse (see the handoff), which
leaves exactly one move: measure each box against the pixels it should have
covered, and correct it there.

Three quantities, three different kinds of certainty:

* ``x`` and ``y`` map to the ink linearly.  Moving the box by (dx, dy) moves the
  glyphs by (dx, dy) — no assumption about the font required.
* ``fontSize`` does not: the adapter draws at ``y + height/2 + 0.375em``, so a
  size change moves the baseline as well.  ``ink_em`` is learned from the render
  itself (ink height per em), which is what lets a size correction keep the ink
  top where the truth has it.
* nothing here guesses.  A window whose ink touches its edge, a box that is
  mostly filled, a paragraph with more than one line — all of them are
  ambiguous, and an ambiguous box is left exactly as it was.

The pass is opt-in and runs after the first render, because the measurement it
needs is the render itself.  Whatever it changes is subject to the caller's
gate: if the page gets worse, the caller throws the whole correction away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

#: Strong ink only.  The antialias halo carries a few channels of contrast and
#: would widen every glyph by a pixel a side, which at these sizes is the whole
#: error we are trying to measure.
INK_THRESHOLD = 40
#: A column or row counts when it holds this share of the peak ink column.
BAND_SHARE = 0.10
#: Look this far outside the box; the box was measured, not the ink.
WINDOW_PAD = 8
#: Ink this close to the window edge belongs to a neighbour, not to this box.
EDGE_GUARD = 3
#: A window that is mostly ink is a filled surface, not a line of words.
MAX_INK_SHARE = 0.55

#: Below two pixels nobody can see the shift and the risk is not worth it.
MIN_SHIFT = 2.0
MAX_SHIFT = 14.0
MIN_SCALE = 0.85
MAX_SCALE = 1.18
#: Width and height ratios have to agree this well before a size change is made.
SCALE_AGREEMENT = 0.10
MIN_SCALE_DEVIATION = 0.05

#: ``text_baseline_y``: baseline = y + height/2 + 0.375em.  Kept here so the
#: size correction and the adapter cannot drift apart silently.
BASELINE_EM = 0.375
#: Fallback ink-per-em when the render had no measurable text to learn from.
DEFAULT_INK_EM = 0.86

#: Window widths tried in order.  A box whose ink reaches the window edge is
#: usually one with neighbours on both sides; a tighter window separates them
#: more often than it cuts the box's own ink, so the box gets a second and third
#: chance before it is given up on.
WINDOW_ATTEMPTS = ((WINDOW_PAD, EDGE_GUARD), (4, 2), (2, 1))


@dataclass
class Correction:
    """One box's measured geometry, and what was done about it."""

    index: int
    text: str
    font_size: float
    ink_height: float
    ink_width: float
    dx: float = 0.0
    dy: float = 0.0
    scale: float = 1.0
    before: tuple[float, float, float] = (0.0, 0.0, 0.0)
    after: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @property
    def moved(self) -> bool:
        return abs(self.dx) >= MIN_SHIFT or abs(self.dy) >= MIN_SHIFT

    @property
    def resized(self) -> bool:
        return abs(self.scale - 1.0) >= MIN_SCALE_DEVIATION

    @property
    def active(self) -> bool:
        return self.moved or self.resized


@dataclass
class Report:
    """What the pass saw.  Everything here is measured, nothing is assumed."""

    measured: int = 0
    corrected: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    #: Boxes that were corrected in part: the shift was measured, the size was
    #: not (width and height disagreed, so the difference is tracking).
    partial: dict[str, int] = field(default_factory=dict)
    ink_em: float = DEFAULT_INK_EM
    corrections: list[Correction] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        shifts = [c.dx for c in self.corrections if c.active]
        return {
            "measured": self.measured,
            "corrected": self.corrected,
            "skipped": dict(sorted(self.skipped.items())),
            "partial": dict(sorted(self.partial.items())),
            "inkEm": round(self.ink_em, 3),
            "moved": sum(1 for c in self.corrections if c.moved and c.active),
            "resized": sum(1 for c in self.corrections if c.resized and c.active),
            "medianShift": round(sorted(shifts)[len(shifts) // 2], 1) if shifts else 0.0,
        }


def _skip(report: Report, reason: str) -> None:
    report.skipped[reason] = report.skipped.get(reason, 0) + 1


def _window(
    box: Sequence[float], shape: tuple[int, int], pad: int
) -> tuple[int, int, int, int] | None:
    height, width = shape[:2]
    x, y, w, h = (float(value) for value in box)
    if w <= 0 or h <= 0:
        return None
    x0 = max(0, int(x) - pad)
    y0 = max(0, int(y) - pad)
    x1 = min(width, int(round(x + w)) + pad)
    y1 = min(height, int(round(y + h)) + pad)
    if x1 - x0 < 12 or y1 - y0 < 10:
        return None
    return x0, y0, x1, y1


def _background(crop):
    """The ring just inside the window: the surface the words sit on.

    A chip's own colour is the honest background for a label on a chip, and the
    ring gives that without having to know which of the two it is.
    """
    import numpy as np

    ring = np.concatenate(
        [
            crop[0:2, :, :].reshape(-1, crop.shape[2]),
            crop[-2:, :, :].reshape(-1, crop.shape[2]),
            crop[:, 0:2, :].reshape(-1, crop.shape[2]),
            crop[:, -2:, :].reshape(-1, crop.shape[2]),
        ],
        axis=0,
    )
    return np.median(ring, axis=0)


def _ink(crop, background):
    import numpy as np

    return np.abs(crop - background.reshape(1, 1, -1)).max(axis=2) >= INK_THRESHOLD


def _bounds(profile) -> tuple[int, int] | None:
    """First and last column/row that carries a real share of the ink."""
    import numpy as np

    if profile.size == 0:
        return None
    peak = int(profile.max())
    if peak <= 0:
        return None
    indexes = np.where(profile >= max(1, int(peak * BAND_SHARE)))[0]
    if indexes.size == 0:
        return None
    return int(indexes[0]), int(indexes[-1]) + 1


def _bands(profile) -> int:
    """How many separate runs the profile has — one line of words, or a paragraph."""
    import numpy as np

    peak = int(profile.max()) if profile.size else 0
    if peak <= 0:
        return 0
    active = profile >= max(1, int(peak * BAND_SHARE))
    runs = 0
    previous = False
    for value in active:
        if value and not previous:
            runs += 1
        previous = bool(value)
    return runs


def _measure(
    element: Mapping[str, Any],
    index: int,
    truth,
    drawn,
    pad: int,
    guard: int,
) -> tuple[Correction | None, str]:
    """One box, measured in a window of the caller's choosing.

    Returns the correction and the reason it was not produced (empty on
    success), so the caller can decide whether a narrower window is worth a
    second attempt instead of losing the box to a neighbour.
    """
    box = (
        float(element.get("x") or 0),
        float(element.get("y") or 0),
        float(element.get("width") or 0),
        float(element.get("height") or 0),
    )
    if abs(box[2]) < 12 or abs(box[3]) < 10:
        return None, "box-too-small"
    window = _window(box, truth.shape[:2], pad)
    if window is None:
        return None, "box-off-canvas"
    x0, y0, x1, y1 = window

    size = float((element.get("style") or {}).get("fontSize") or 0)
    if size < 6:
        return None, "no-type-size"

    truth_ink = _ink(truth[y0:y1, x0:x1], _background(truth[y0:y1, x0:x1]))
    drawn_ink = _ink(drawn[y0:y1, x0:x1], _background(drawn[y0:y1, x0:x1]))
    if truth_ink.mean() > MAX_INK_SHARE or drawn_ink.mean() > MAX_INK_SHARE:
        return None, "filled-surface"

    truth_cols = _bounds(truth_ink.sum(axis=0))
    drawn_cols = _bounds(drawn_ink.sum(axis=0))
    truth_rows = _bounds(truth_ink.sum(axis=1))
    drawn_rows = _bounds(drawn_ink.sum(axis=1))
    if not (truth_cols and drawn_cols and truth_rows and drawn_rows):
        return None, "no-ink"

    # Ink against the window edge means a neighbour bled in.  Guessing which of
    # the two lines the pixels belong to is how a calibration pass starts moving
    # the wrong boxes, so those windows are not used as they are.
    if (
        min(truth_cols[0], drawn_cols[0]) <= guard
        or max(truth_cols[1], drawn_cols[1]) >= (x1 - x0) - guard
    ):
        return None, "ink-touches-edge"

    truth_bands = _bands(truth_ink.sum(axis=1))
    drawn_bands = _bands(drawn_ink.sum(axis=1))
    paragraph = truth_bands > 1 or drawn_bands > 1
    wrap_differs = paragraph and truth_bands != drawn_bands
    if paragraph:
        # A block of prose is calibrated on its left edge only.  Vertical offset
        # and type size would both be confounded by line pitch.  A block that
        # wraps into a different number of lines is still anchored at the same
        # left inset, so the shift survives even when the wrapping does not.
        align = str((element.get("style") or {}).get("textAlign") or "left").lower()
        if align not in ("", "left", "start"):
            return None, "multi-line"
    elif (
        min(truth_rows[0], drawn_rows[0]) <= guard
        or max(truth_rows[1], drawn_rows[1]) >= (y1 - y0) - guard
    ):
        return None, "ink-touches-edge"

    truth_width = float(truth_cols[1] - truth_cols[0])
    drawn_width = float(drawn_cols[1] - drawn_cols[0])
    truth_height = float(truth_rows[1] - truth_rows[0])
    drawn_height = float(drawn_rows[1] - drawn_rows[0])
    if min(truth_width, drawn_width, truth_height, drawn_height) <= 0:
        return None, "degenerate-ink"

    align = str((element.get("style") or {}).get("textAlign") or "left").lower()
    if align in ("end", "right"):
        dx = float(truth_cols[1] - drawn_cols[1])
    elif align in ("center", "middle"):
        dx = (truth_cols[0] + truth_cols[1]) / 2.0 - (drawn_cols[0] + drawn_cols[1]) / 2.0
    else:
        dx = float(truth_cols[0] - drawn_cols[0])
    dy = 0.0 if paragraph else float(truth_rows[0] - drawn_rows[0])

    if abs(dx) > MAX_SHIFT or abs(dy) > MAX_SHIFT:
        return None, "shift-out-of-range"

    scale = 1.0
    reason = "line-count-differs" if wrap_differs else ""
    if not paragraph:
        scale_width = truth_width / drawn_width
        scale_height = truth_height / drawn_height
        if abs(scale_width - scale_height) <= SCALE_AGREEMENT:
            # Height carries the type size; width confirms it.
            scale = max(MIN_SCALE, min(MAX_SCALE, 0.7 * scale_height + 0.3 * scale_width))
        else:
            # The width and the height disagree, which is tracking rather than
            # size.  The shift was measured, not inferred, so it still stands.
            reason = "width-height-disagree"

    correction = Correction(
        index=index,
        text=str(element.get("text") or "")[:16],
        font_size=size,
        ink_height=drawn_height,
        ink_width=drawn_width,
        dx=dx,
        dy=dy,
        scale=scale,
        before=(box[0], box[1], size),
    )
    correction.after = correction.before
    if not correction.active:
        return correction, reason or "within-tolerance"
    return correction, reason


def _learn_ink_em(corrections: Sequence[Correction]) -> float:
    """Ink height produced by one em of type in *this* render.

    Learned rather than assumed: the renderer, the font and the script all move
    it, and it is the one constant that lets a size change keep the ink top
    still instead of dragging the whole line up or down.
    """
    ratios = sorted(
        c.ink_height / c.font_size
        for c in corrections
        if c.font_size >= 10 and c.ink_height > 0
    )
    if not ratios:
        return DEFAULT_INK_EM
    return ratios[len(ratios) // 2]


def _apply(
    elements: Sequence[dict[str, Any]], corrections: Sequence[Correction], ink_em: float
) -> int:
    """Write the correction back into the design.  Text count never changes."""
    changed = 0
    for correction in corrections:
        if not correction.active:
            continue
        element = elements[correction.index]
        style = element.setdefault("style", {})
        size = float(style.get("fontSize") or correction.font_size)
        scale = correction.scale if correction.resized else 1.0
        new_size = max(6.0, round(size * scale * 2) / 2)
        delta_size = new_size - size
        element["x"] = round(float(element.get("x") or 0) + correction.dx, 1)
        # The baseline is y + height/2 + 0.375em, so a size change drags the line
        # with it.  Compensate by exactly the amount the ink top would have moved.
        element["y"] = round(
            float(element.get("y") or 0) + correction.dy + (ink_em - BASELINE_EM) * delta_size,
            1,
        )
        style["fontSize"] = new_size
        element["metricEvidence"] = {
            "method": "ink-projection",
            "dx": round(correction.dx, 1),
            "dy": round(correction.dy, 1),
            "scale": round(scale, 3),
            "inkEm": round(ink_em, 3),
        }
        correction.after = (element["x"], element["y"], new_size)
        changed += 1
    return changed


def calibrate_arrays(
    elements: Sequence[dict[str, Any]],
    truth,
    drawn,
    *,
    apply: bool = True,
) -> Report:
    """Measure every text box against the picture, then correct the ones that agree."""
    report = Report()
    if truth.shape[:2] != drawn.shape[:2]:
        return report
    for index, element in enumerate(elements):
        if element.get("type") != "text" or not element.get("text"):
            continue
        correction: Correction | None = None
        reason = "no-window"
        for pad, guard in WINDOW_ATTEMPTS:
            correction, reason = _measure(element, index, truth, drawn, pad, guard)
            if reason != "ink-touches-edge":
                break
        if correction is None:
            _skip(report, reason)
            continue
        report.measured += 1
        report.corrections.append(correction)
        if not correction.active:
            _skip(report, reason or "within-tolerance")
        elif reason:
            report.partial[reason] = report.partial.get(reason, 0) + 1
    report.ink_em = _learn_ink_em(report.corrections)
    if apply:
        report.corrected = _apply(elements, report.corrections, report.ink_em)
    return report


def calibrate(
    elements: Sequence[dict[str, Any]],
    truth_path: str | Path,
    render_path: str | Path,
    *,
    apply: bool = True,
) -> Report:
    """File-level wrapper: load both pictures, measure, correct."""
    import numpy as np
    from PIL import Image

    truth = np.asarray(Image.open(truth_path).convert("RGB"), dtype=np.int16)
    drawn = np.asarray(Image.open(render_path).convert("RGB"), dtype=np.int16)
    return calibrate_arrays(elements, truth, drawn, apply=apply)
