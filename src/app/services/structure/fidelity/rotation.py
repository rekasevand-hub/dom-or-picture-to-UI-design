"""Rotation, in the one convention the whole pipeline shares.

A tilted stamp is the one thing a screenshot has that a box model does not: the
plan reports axis-aligned boxes, so a 6° seal comes out as a rectangle with the
tilt baked into nothing.  Two renderers have to agree on what "6°" means and on
where the origin is, and Figma's API disagrees with SVG on both counts:

* **Sign.** SVG's `rotate(a)` turns clockwise on screen; Figma's `node.rotation`
  is clockwise too, but the design speaks the maths convention (anticlockwise
  positive), so both ends negate.
* **Origin.** SVG is told a centre (`rotate(a cx cy)`).  Figma rotates about the
  node's own origin, so the box has to be moved by the difference between where
  its centre is and where the rotation puts it.

`figma_origin` is that compensation, and it is the only place the matrix is
written — the plugin calls the same algebra in JavaScript, and the two are held
together by `tests/v2/test_image_rotation.py`.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


def normalise_angle(value: Any) -> float:
    """Degrees, anticlockwise positive, folded into (-180, 180], below 2° is level.

    A hand-drawn seal is never exactly square and a level label measured at 1.4°
    is a level label; treating it as tilted would turn clean type into a smudged
    one at every corner.
    """
    try:
        angle = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(angle):
        return 0.0
    angle = (angle + 180.0) % 360.0 - 180.0
    if abs(angle) < 2.0:
        return 0.0
    return round(angle, 2)


def element_centre(element: Mapping[str, Any]) -> tuple[float, float]:
    """The point both renderers rotate about: the box's centre."""
    x = float(element.get("x") or 0.0)
    y = float(element.get("y") or 0.0)
    width = float(element.get("width") or 0.0)
    height = float(element.get("height") or 0.0)
    return x + width / 2.0, y + height / 2.0


def figma_origin(
    centre: tuple[float, float],
    width: float,
    height: float,
    angle: float,
) -> tuple[float, float]:
    """Where Figma has to put the box so its *centre* lands on ``centre``.

    Figma rotates about the node's origin, so after the rotation the centre sits
    at `origin + R(θ)·(w/2, h/2)` with θ clockwise on screen:

        x = cx - (w/2·cosθ - h/2·sinθ)
        y = cy - (w/2·sinθ + h/2·cosθ)

    At θ=0 this is the plain top-left, which is why the unrotated path is
    unchanged to the pixel.
    """
    theta = math.radians(-float(angle))
    cos = math.cos(theta)
    sin = math.sin(theta)
    half_w = float(width) / 2.0
    half_h = float(height) / 2.0
    return (
        round(float(centre[0]) - (half_w * cos - half_h * sin), 3),
        round(float(centre[1]) - (half_w * sin + half_h * cos), 3),
    )


def svg_transform(element: Mapping[str, Any]) -> str:
    """`rotate(-angle cx cy)`, or an empty string when the box is level."""
    angle = normalise_angle(element.get("rotation"))
    if not angle:
        return ""
    cx, cy = element_centre(element)
    return "rotate(%s %s %s)" % (_number(-angle), _number(cx), _number(cy))


def _number(value: float) -> str:
    """Trim the trailing `.0` so old SVGs stay byte-identical at angle 0."""
    text = ("%.3f" % float(value)).rstrip("0").rstrip(".")
    return text or "0"


def estimate_rotation(image, box: tuple[int, int, int, int]) -> float:
    """Measure a region's tilt from its own ink, with `minAreaRect`.

    Only useful where a *shape* is tilted — a seal, a sticker, a rotated chip.
    Type is measured by the same function and returns 0, because a line of words
    in a box is already the axis-aligned thing the box describes.
    """
    try:
        import cv2
        import numpy as np
    except Exception:  # pragma: no cover - imaging stack is a hard dependency
        return 0.0
    if image is None:
        return 0.0
    x, y, w, h = (int(value) for value in box)
    height, width = image.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return 0.0
    crop = np.asarray(image[y0:y1, x0:x1]).astype(np.int16)
    luminance = crop.mean(axis=2)
    spread = float(luminance.max() - luminance.min())
    if spread < 24:
        return 0.0
    threshold = (float(np.percentile(luminance, 4)) + float(luminance.max())) / 2.0
    crop_h, crop_w = luminance.shape[:2]

    def shape_of(mask: "np.ndarray"):
        """The contour that is the shape, not the page it sits on."""
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        best = None
        for contour in contours:
            bx, by, bw, bh = cv2.boundingRect(contour)
            if bx <= 0 and by <= 0 and bx + bw >= crop_w - 1 and by + bh >= crop_h - 1:
                continue  # the crop's own frame: this is the background
            area = cv2.contourArea(contour)
            if area < 40:
                continue
            if best is None or area > cv2.contourArea(best):
                best = contour
        return best

    # Which side of the threshold is the shape depends on the picture, not on
    # a rule: a dark seal on a light page and white type on a dark one are the
    # same measurement with the mask inverted.  Whichever polarity yields the
    # bigger non-frame contour is the shape.
    candidates = [
        shape_of(luminance < threshold),
        shape_of(luminance >= threshold),
    ]
    candidates = [contour for contour in candidates if contour is not None]
    if not candidates:
        return 0.0
    contour = max(candidates, key=cv2.contourArea)
    (_cx, _cy), (rect_w, rect_h), angle = cv2.minAreaRect(contour)
    if rect_w < 1 or rect_h < 1:
        return 0.0
    # minAreaRect reports the angle of the box edge nearest the x axis, and
    # which edge that is depends on which side of the rectangle happened to be
    # longer — the same box comes back as 0 or 90, as 6 or 96, as -8 or 82.
    # Folding into (-45, 45] gives the tilt a person would name.
    tilt = ((float(angle) + 45.0) % 90.0) - 45.0
    fill = cv2.contourArea(contour) / max(1.0, rect_w * rect_h)
    if fill < 0.45:
        return 0.0
    return normalise_angle(tilt)


def serif_ratio(image, box: tuple[int, int, int, int]) -> float:
    """How much heavier a region's vertical strokes are than its horizontals.

    A Song/Ming face draws 12px verticals and 2px horizontals; a sans face draws
    both at about the same width.  Eroding the ink with a 1x5 kernel keeps only
    the vertical strokes and with a 5x1 kernel only the horizontal ones, so the
    ratio of what survives says which kind of face the picture used — with no
    font name anywhere in the decision.
    """
    try:
        import cv2
        import numpy as np
    except Exception:  # pragma: no cover
        return 0.0
    if image is None:
        return 0.0
    x, y, w, h = (int(value) for value in box)
    height, width = image.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 16 or y1 - y0 < 12:
        return 0.0
    crop = np.asarray(image[y0:y1, x0:x1]).astype(np.int16)
    luminance = crop.mean(axis=2)
    if float(luminance.max() - luminance.min()) < 40:
        return 0.0
    threshold = (float(np.percentile(luminance, 5)) + float(luminance.max())) / 2.0
    bright = luminance >= threshold
    mask = (~bright if bright.mean() > 0.5 else bright).astype(np.uint8)
    ink = int(mask.sum())
    if ink < 120:
        return 0.0
    vertical = cv2.erode(mask, np.ones((5, 1), np.uint8))
    horizontal = cv2.erode(mask, np.ones((1, 5), np.uint8))
    kept_v = int(vertical.sum())
    kept_h = int(horizontal.sum())
    if kept_h < max(1, ink // 200):
        return 0.0
    return round(kept_v / max(1, kept_h), 2)
