"""Paint and solid-block geometry read straight off the reference screenshot.

The emitter knows where things are but not what a panel looks like: containers
arrive with no fill, and bars (progress, accents) are not modelled at all.  Both
are plain rectangles in the screenshot, so they can be measured instead of
guessed -- no family names, no constants per page.

Everything here is conservative: a container is painted only when its interior
is uniform *and* at least two of its edges show a colour step against the page.
A region that cannot prove it is a panel stays transparent rather than painting
a wrong rectangle over the design.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image

Color = tuple[int, int, int]


def _hex(value: Sequence[int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(channel))):02x}" for channel in value)


def _distance(left: Color, right: Color) -> int:
    return max(abs(int(a) - int(b)) for a, b in zip(left, right))


@dataclass(frozen=True)
class Paint:
    """What a container should draw: fill, optional border, corner radius."""

    fill: str
    border: str | None
    border_width: int
    radius: int

    def as_style(self) -> dict[str, Any]:
        style: dict[str, Any] = {"fillColor": self.fill}
        if self.border and self.border_width:
            style["borderColor"] = self.border
            style["borderWidth"] = self.border_width
        if self.radius:
            style["borderRadius"] = self.radius
        return style


class ReferencePixels:
    """One decoded reference image, queried by region."""

    def __init__(self, array: np.ndarray) -> None:
        self.array = array
        self.height, self.width = array.shape[:2]
        self._page: Color | None = None

    @classmethod
    def load(cls, image_path: str | Path | None) -> "ReferencePixels | None":
        if not image_path:
            return None
        path = Path(image_path)
        if not path.is_file():
            return None
        with Image.open(path) as source:
            array = np.asarray(source.convert("RGB"), dtype=np.int16)
        return cls(array)

    # -- primitives ---------------------------------------------------------
    def page_color(self) -> Color:
        """Most common quantised colour; cached (np.unique on rows is not cheap)."""
        if self._page is None:
            coarse = self.array // 4 * 4
            packed = (
                (coarse[:, :, 0].astype(np.int32) << 16)
                | (coarse[:, :, 1].astype(np.int32) << 8)
                | coarse[:, :, 2].astype(np.int32)
            )
            values, counts = np.unique(packed, return_counts=True)
            value = int(values[int(np.argmax(counts))])
            self._page = ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
        return self._page

    def mode_of(self, box: Sequence[int], inset: int = 0) -> tuple[Color, float]:
        x, y, w, h = (int(v) for v in box)
        x0, y0 = max(0, x + inset), max(0, y + inset)
        x1, y1 = min(self.width, x + w - inset), min(self.height, y + h - inset)
        if x1 <= x0 or y1 <= y0:
            return (0, 0, 0), 0.0
        region = self.array[y0:y1, x0:x1].reshape(-1, 3) // 4 * 4
        values, counts = np.unique(region, axis=0, return_counts=True)
        index = int(np.argmax(counts))
        return (
            tuple(int(v) for v in values[index]),
            float(counts[index]) / max(1, region.shape[0]),
        )

    def _edge_line(
        self, side: str, box: Sequence[int], offset: int, span: float = 0.5
    ) -> Color | None:
        """Mode colour of a 1px line `offset` px outside one edge.

        Only the middle `span` of the edge is sampled: glyphs and controls touch
        the ends far more often than the middle.
        """
        x, y, w, h = (int(v) for v in box)
        if side in {"left", "right"}:
            line_x = x - offset if side == "left" else x + w - 1 + offset
            if not 0 <= line_x < self.width:
                return None
            y0 = y + int(h * (1 - span) / 2)
            y1 = y + h - int(h * (1 - span) / 2)
            strip = self.array[max(0, y0) : min(self.height, y1), line_x : line_x + 1]
        else:
            line_y = y - offset if side == "top" else y + h - 1 + offset
            if not 0 <= line_y < self.height:
                return None
            x0 = x + int(w * (1 - span) / 2)
            x1 = x + w - int(w * (1 - span) / 2)
            strip = self.array[line_y : line_y + 1, max(0, x0) : min(self.width, x1)]
        if strip.size == 0:
            return None
        pixels = strip.reshape(-1, 3) // 4 * 4
        values, counts = np.unique(pixels, axis=0, return_counts=True)
        return tuple(int(v) for v in values[int(np.argmax(counts))])

    def corner_radius(self, box: Sequence[int], fill: str, limit: int = 26) -> int:
        """Corner radius from the empty triangle a rounded corner leaves behind.

        Reading the first filled pixel per row fails on a panel whose bounding
        box is the *interior* (the border sits outside it).  The missing area
        is measurable in any case: a quarter of radius ``r`` is cut away, so
        the drawn triangle is about ``0.2146 r^2`` plus the border arc.
        """
        fill_rgb = tuple(int(fill[index : index + 2], 16) for index in (1, 3, 5))
        x, y, w, h = (int(v) for v in box)
        span = min(limit, w, h)
        if span <= 4:
            return 0
        crop = self.array[y : y + span, x : x + span]
        outside = np.abs(crop - np.array(fill_rgb, dtype=np.int16)).max(axis=2) > 10
        # Only the upper-left triangle can belong to this corner.
        rows, columns = np.mgrid[0 : crop.shape[0], 0 : crop.shape[1]]
        outside &= (rows + columns) < span
        observed = int(outside.sum())
        best = 0
        best_error = abs(observed - 0)
        for radius in (2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24):
            if radius > span:
                break
            expected = 0.2146 * radius * radius + 1.57 * radius
            error = abs(observed - expected)
            if error < best_error:
                best, best_error = radius, error
        return best

    # -- uniform rectangles -------------------------------------------------
    def uniform_rectangles(
        self,
        *,
        tol: int = 6,
        min_area: int = 2000,
        min_extent: float = 0.7,
        step: int = 24,
        limit: int = 64,
    ) -> list[dict[str, Any]]:
        """Flat-colour rectangles: panels, cards, buttons, bars.

        A seed grows along its row, then each column in that span grows around
        the seed row; the 10th/90th percentile of those runs gives the vertical
        extent, so a glyph or a rounded corner cannot stretch the box.  Seeds
        landing inside a rectangle already found are skipped, which is what
        keeps this affordable: every flat area is visited once.
        """
        found: list[dict[str, Any]] = []
        for seed_y in range(step // 2, self.height, step):
            for seed_x in range(step // 2, self.width, step):
                if any(_inside(item["bbox"], seed_x, seed_y) for item in found):
                    continue
                rect = self._grow_rect(seed_x, seed_y, tol)
                if rect is None:
                    continue
                x, y, w, h = rect
                area = w * h
                if area < min_area:
                    continue
                extent = self._extent(rect, tol)
                if extent < min_extent:
                    continue
                found.append({"bbox": rect, "extent": round(extent, 3), "area": area})
                if len(found) >= limit:
                    return found
        return found

    def _grow_rect(
        self, seed_x: int, seed_y: int, tol: int
    ) -> list[int] | None:
        seed = self.array[seed_y, seed_x]
        row = self.array[seed_y]
        limit = tol
        left = seed_x
        while left > 0 and np.abs(row[left - 1] - seed).max() <= limit:
            left -= 1
        right = seed_x
        while right + 1 < self.width and np.abs(row[right + 1] - seed).max() <= limit:
            right += 1
        if right - left < 8:
            return None
        # Stride the column probes: a 1200px panel does not need 1200 of them.
        columns = range(left, right + 1, max(1, (right - left) // 48))
        tops: list[int] = []
        bottoms: list[int] = []
        for column in columns:
            column_pixels = self.array[:, column]
            top = seed_y
            while top > 0 and np.abs(column_pixels[top - 1] - seed).max() <= limit:
                top -= 1
            bottom = seed_y
            while (
                bottom + 1 < self.height
                and np.abs(column_pixels[bottom + 1] - seed).max() <= limit
            ):
                bottom += 1
            tops.append(top)
            bottoms.append(bottom + 1)
        if not tops:
            return None
        y0 = int(np.percentile(tops, 10))
        y1 = int(np.percentile(bottoms, 90))
        if y1 - y0 < 8:
            return None
        return [left, y0, right - left + 1, y1 - y0]

    def _extent(self, box: Sequence[int], tol: int) -> float:
        x, y, w, h = (int(v) for v in box)
        region = self.array[y : y + h : 3, x : x + w : 3]
        if region.size == 0:
            return 0.0
        reference = self.array[y + h // 2, x + w // 2]
        matches = np.abs(region - reference).max(axis=2) <= tol
        return float(matches.mean())

    def border_of(
        self,
        box: Sequence[int],
        fill: str,
        *,
        min_gap: int = 16,
        sides_required: int = 3,
        same_border: int = 24,
    ) -> str | None:
        """The control's own 1px border, or ``None`` when it has none.

        ``_sample_border_color`` never answers "no border": with no real border
        pixel it synthesises ``#c8d1de`` / ``#64748b``.  That painted an outline
        around 21 of 36 controls -- including ``社区``, where the invented frame
        happened to be the same size as the reference text and propped up its
        native-text score.

        A border is a *frame*: the same colour on at least three sides, one
        pixel inside the box.  A single differing side is a glyph touching the
        edge or antialiasing, and is not a border.
        """
        fill_rgb = hex_to_rgb(fill)
        hits: list[Color] = []
        for side in ("left", "right", "top", "bottom"):
            # The bbox is only aligned to the drawn edge within a pixel, so
            # probe both the outermost line and the one just inside it and keep
            # whichever is further from the fill.
            candidates = [
                line
                for line in (
                    self._edge_line(side, box, 0, span=0.5),
                    self._edge_line(side, box, -1, span=0.5),
                )
                if line is not None
            ]
            if not candidates:
                continue
            line = max(candidates, key=lambda color: _distance(color, fill_rgb))
            if _distance(line, fill_rgb) >= min_gap:
                hits.append(line)
        if len(hits) < sides_required:
            return None
        anchor = hits[0]
        if any(_distance(anchor, other) > same_border for other in hits[1:]):
            return None
        outside = self.ring_color(box, ring=2)
        if outside is not None and _distance(anchor, outside) < 16:
            # The "border" is the page showing between the box and the drawn
            # shape: a bbox larger than the visual button, not a stroke.
            return None
        return _hex(anchor)

    # -- panels -------------------------------------------------------------
    def panels(
        self,
        *,
        content_boxes: Sequence[Sequence[int]] = (),
        background: str | None = None,
        step: int = 4,
        min_area: int = 1500,
        min_extent: float = 0.55,
        colors: int = 16,
        limit: int = 48,
    ) -> list[dict[str, Any]]:
        """Flat rectangles found as connected components of one colour.

        Quantising the image first is what makes nested panels separable: a
        white card inside a white page is one component per card, because the
        1px border quantises to a different value and splits them.  A flood
        fill cannot do this here -- it either leaks through JPEG noise or has
        to be re-seeded for every nested box.

        Only the ``colors`` most common quantised colours are scanned.  A
        gradient contributes thousands of one-off colours, which are both
        worthless as panels and ruinous in time.

        A page gradient also quantises into ~50px tiles that look exactly like
        small panels.  What separates them from real ones is that they hold
        nothing: a panel below 2% of the canvas must overlap a content box.
        """
        coarse = (self.array // step) * step
        packed = (
            (coarse[:, :, 0].astype(np.int32) << 16)
            | (coarse[:, :, 1].astype(np.int32) << 8)
            | coarse[:, :, 2].astype(np.int32)
        )
        values, counts = np.unique(packed, return_counts=True)
        order = np.argsort(-counts)[:colors]
        total = self.height * self.width
        results: list[dict[str, Any]] = []
        for index in order:
            value, count = int(values[index]), int(counts[index])
            if count < max(min_area, int(total * 0.003)):
                continue
            mask = (packed == value).astype(np.uint8)
            components, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
                mask, 4
            )
            for component in range(1, components):
                x, y, w, h, area = (int(v) for v in stats[component])
                if area < min_area:
                    continue
                extent = area / max(1, w * h)
                if extent < min_extent:
                    continue
                if w >= 0.95 * self.width and h >= 0.95 * self.height:
                    continue
                if (
                    x <= 4
                    or y <= 4
                    or x + w >= self.width - 4
                    or y + h >= self.height - 4
                ):
                    # Gradient bands that run off the canvas are page texture,
                    # not panels: a real panel is enclosed by its own edge.
                    continue
                results.append(
                    {
                        "bbox": [x, y, w, h],
                        "area": area,
                        "extent": round(extent, 3),
                        "sample": tuple(int(v) for v in coarse[y + h // 2, x + w // 2]),
                    }
                )
        results.sort(key=lambda item: -item["area"])
        kept: list[dict[str, Any]] = []
        floor = total * 0.02
        for item in results:
            if item["area"] < floor and not _covers_content(
                item["bbox"], content_boxes
            ):
                continue
            kept.append(item)
            if len(kept) >= limit:
                break
        for item in kept:
            item.update(self._panel_paint(item["bbox"]))
        # A panel the same colour as the page only earns a rectangle when its
        # edge is actually visible: an outlined pill on a dark nav is real, a
        # 1px antialiasing seam around plain text is not.
        page = hex_to_rgb(background) if background else self.page_color()
        return [
            item
            for item in kept
            if _distance(hex_to_rgb(item["fill"]), page) >= 8
            or (
                item["border"] is not None
                and _distance(hex_to_rgb(item["border"]), hex_to_rgb(item["fill"]))
                >= 12
            )
        ]

    def _panel_paint(self, box: Sequence[int]) -> dict[str, Any]:
        x, y, w, h = (int(v) for v in box)
        # Stride the sample: a 700k-pixel panel does not need every pixel for a
        # median, and this runs once per panel.
        region = self.array[
            y + 2 : max(y + 3, y + h - 2) : 3, x + 2 : max(x + 3, x + w - 2) : 3
        ].reshape(-1, 3)
        fill = tuple(int(v) for v in np.median(region, axis=0))
        page = self.page_color()
        ring = self.ring_color(box)
        border: str | None = None
        if ring is not None and _distance(ring, fill) >= 8:
            border = _hex(ring)
        return {
            "fill": _hex(fill),
            "border": border,
            "borderWidth": 1 if border else 0,
            "radius": self.corner_radius(box, _hex(fill)),
            "pageLike": _distance(fill, page) < 6,
        }

    def ring_color(self, box: Sequence[int], ring: int = 1) -> Color | None:
        """Mode colour of the ``ring``-px band just outside a box."""
        x, y, w, h = (int(v) for v in box)
        strips = []
        if y - ring >= 0:
            strips.append(self.array[y - ring : y, x : x + w])
        if y + h + ring <= self.height:
            strips.append(self.array[y + h : y + h + ring, x : x + w])
        if x - ring >= 0:
            strips.append(self.array[y : y + h, x - ring : x])
        if x + w + ring <= self.width:
            strips.append(self.array[y : y + h, x + w : x + w + ring])
        if not strips:
            return None
        pixels = np.concatenate([strip.reshape(-1, 3) for strip in strips], axis=0) // 4 * 4
        values, counts = np.unique(pixels, axis=0, return_counts=True)
        return tuple(int(v) for v in values[int(np.argmax(counts))])

    # -- container paint ----------------------------------------------------
    def container_paint(self, box: Sequence[int]) -> Paint | None:
        x, y, w, h = (int(v) for v in box)
        if w < 8 or h < 8:
            return None
        fill, coverage = self.mode_of(box, inset=3)
        if coverage < 0.45:
            # Textured or gradient interior: not a flat panel.
            return None
        steps = 0
        border: Color | None = None
        for side in ("left", "right", "top", "bottom"):
            inside = self._edge_line(side, box, -2)
            outside = self._edge_line(side, box, 2)
            if inside is None or outside is None:
                continue
            if _distance(inside, outside) < 6:
                continue
            steps += 1
            edge = self._edge_line(side, box, -1, span=0.4)
            if edge is not None and _distance(edge, fill) >= 8 and border is None:
                border = edge
        if steps < 2:
            return None
        return Paint(
            fill=_hex(fill),
            border=_hex(border) if border else None,
            border_width=1 if border else 0,
            radius=self.corner_radius(box, _hex(fill)),
        )

    # -- solid blocks -------------------------------------------------------
    def solid_blocks(
        self,
        *,
        min_area: int = 400,
        min_aspect: float = 3.0,
        min_thickness: int = 4,
        saturation_min: int = 40,
    ) -> list[dict[str, Any]]:
        """Thin saturated rectangles: progress bars, accent bars, rules."""
        spread = self.array.max(axis=2) - self.array.min(axis=2)
        mask = (spread >= saturation_min).astype(np.uint8)
        if not mask.any():
            return []
        # A bar is a solid run, so close single-pixel antialiasing gaps.
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        blocks: list[dict[str, Any]] = []
        for index in range(1, count):
            x, y, w, h, area = (int(v) for v in stats[index])
            if area < min_area:
                continue
            extent = area / max(1, w * h)
            if extent < 0.75:
                continue
            aspect = max(w, h) / max(1, min(w, h))
            if aspect < min_aspect or min(w, h) < min_thickness:
                continue
            # A bar is flat along its short axis.  Blue text closed into a
            # blob passes the extent test but varies in every direction, so
            # require one axis to be constant -- measured on the interior,
            # because the 1-2px antialiased rim is not part of the bar.
            inner_x = 2 if w > 8 else 0
            inner_y = 2 if h > 8 else 0
            region = self.array[
                y + inner_y : y + h - inner_y, x + inner_x : x + w - inner_x
            ]
            column_spread = float(np.median(region.std(axis=0).mean(axis=1)))
            row_spread = float(np.median(region.std(axis=1).mean(axis=1)))
            if min(column_spread, row_spread) > 8:
                continue
            fill = tuple(int(v) for v in np.median(region.reshape(-1, 3), axis=0))
            blocks.append(
                {
                    "bbox": [x, y, w, h],
                    "fill": _hex(fill),
                    "aspect": round(aspect, 2),
                    "area": area,
                }
            )
        blocks.sort(key=lambda item: -item["area"])
        return blocks

    def track_extension(
        self,
        bar: Sequence[int],
        *,
        step_min: int = 8,
        limit: int = 400,
    ) -> list[int] | None:
        """The unfilled remainder of a progress bar, read to its right."""
        x, y, w, h = (int(v) for v in bar)
        row = y + h // 2
        if not 0 <= row < self.height:
            return None
        start = min(self.width - 1, x + w + 2)
        if start >= self.width:
            return None
        page = np.array(self.page_color(), dtype=np.int16)
        probe = self.array[row, start]
        if _distance(tuple(int(v) for v in probe), tuple(int(v) for v in page)) < step_min:
            return None
        end = start
        while end < min(self.width, start + limit):
            pixel = self.array[row, end]
            if _distance(tuple(int(v) for v in pixel), tuple(int(v) for v in page)) < step_min:
                break
            end += 1
        if end - start < 24:
            return None
        return [start, y, end - start, h]


def paint_containers(
    containers: list[dict[str, Any]],
    pixels: ReferencePixels | None,
) -> list[dict[str, Any]]:
    """Attach measured paint to containers that currently carry none."""
    if pixels is None:
        return containers
    painted: list[dict[str, Any]] = []
    for element in containers:
        style = element.get("style") or {}
        if style.get("fillColor") not in (None, "", "transparent"):
            painted.append(element)
            continue
        box = [
            int(round(float(element.get(key) or 0)))
            for key in ("x", "y", "width", "height")
        ]
        paint = pixels.container_paint(box)
        if paint is None:
            painted.append(element)
            continue
        element = dict(element)
        element["style"] = {**style, **paint.as_style()}
        element.setdefault("imageMVP", {})
        element["imageMVP"] = {
            **(element.get("imageMVP") or {}),
            "paint": "reference-pixels",
        }
        painted.append(element)
    return painted


def solid_decorations(
    pixels: ReferencePixels | None,
    *,
    covered: Sequence[Sequence[int]] = (),
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Rectangles for saturated bars that no element covers yet.

    ``covered`` are the leaf boxes: a saturated fragment sitting inside a text
    or image node (a blue button label, a logo crop) is already drawn, and a
    bar on top of it would paint over the real node.
    """
    if pixels is None:
        return []
    decorations: list[dict[str, Any]] = []
    for ordinal, block in enumerate(pixels.solid_blocks()):
        box = block["bbox"]
        if any(_overlap_ratio(box, outer) >= 0.6 for outer in covered):
            continue
        decorations.append(
            {
                "id": f"solid-bar-{ordinal}",
                "type": "rectangle",
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "text": "",
                "style": {"fillColor": block["fill"]},
                "role": "accent-bar" if box[2] <= box[3] else "progress-bar",
                "name": "solid-bar",
                "contentRef": None,
            }
        )
        if len(decorations) >= limit:
            break
    return decorations


def _overlap_ratio(left: Sequence[int], right: Sequence[int]) -> float:
    lx, ly, lw, lh = (int(v) for v in left)
    rx, ry, rw, rh = (int(v) for v in right)
    if lw <= 0 or lh <= 0 or rw <= 0 or rh <= 0:
        return 0.0
    overlap_w = min(lx + lw, rx + rw) - max(lx, rx)
    overlap_h = min(ly + lh, ry + rh) - max(ly, ry)
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0
    return (overlap_w * overlap_h) / (lw * lh)


def _covers_content(
    panel: Sequence[int], content_boxes: Sequence[Sequence[int]], share: float = 0.5
) -> bool:
    """Whether the panel actually holds part of the design."""
    px, py, pw, ph = (int(v) for v in panel)
    for box in content_boxes:
        if len(box) != 4:
            continue
        bx, by, bw, bh = (int(v) for v in box)
        if bw <= 0 or bh <= 0:
            continue
        overlap_w = min(px + pw, bx + bw) - max(px, bx)
        overlap_h = min(py + ph, by + bh) - max(py, by)
        if overlap_w <= 0 or overlap_h <= 0:
            continue
        if overlap_w * overlap_h >= share * bw * bh:
            return True
    return False


def _inside(box: Sequence[int], x: int, y: int) -> bool:
    return box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[3]


def panel_decorations(
    pixels: ReferencePixels | None,
    *,
    content_boxes: Sequence[Sequence[int]] = (),
    covered_boxes: Sequence[Sequence[int]] = (),
    painted_boxes: Sequence[tuple[Sequence[int], str]] = (),
    background: str | None = None,
    limit: int = 32,
) -> list[dict[str, Any]]:
    """Rectangles for every flat panel the design has no node for.

    Panels are returned largest first so the painter's order nests correctly:
    a card drawn after the page panel lands on top of it.
    """
    if pixels is None:
        return []
    decorations: list[dict[str, Any]] = []
    for ordinal, panel in enumerate(
        pixels.panels(content_boxes=content_boxes, background=background)
    ):
        box = panel["bbox"]
        if any(_overlap_ratio(box, other) >= 0.9 for other in covered_boxes):
            # An image or control already covers this area; a rectangle on top
            # of it would hide the real node.
            continue
        if any(
            _overlap_ratio(box, container) >= 0.95
            and _overlap_ratio(container, box) >= 0.9
            and color_gap(panel["fill"], container_fill) < 12
            for container, container_fill in painted_boxes
        ):
            # A container already paints *this same box* in this colour: a
            # second rectangle changes nothing.  Both directions matter -- a
            # card nested inside a painted panel would otherwise be dropped
            # because the big panel "covers" it.
            continue
        style: dict[str, Any] = {"fillColor": panel["fill"]}
        if panel["border"]:
            style["borderColor"] = panel["border"]
            style["borderWidth"] = 1
        if panel["radius"]:
            style["borderRadius"] = panel["radius"]
        decorations.append(
            {
                "id": f"reference-panel-{ordinal}",
                "type": "rectangle",
                "x": box[0],
                "y": box[1],
                "width": box[2],
                "height": box[3],
                "text": "",
                "style": style,
                "role": "panel",
                "name": "reference-panel",
                "contentRef": None,
            }
        )
        if len(decorations) >= limit:
            break
    return decorations


def page_background(
    pixels: ReferencePixels | None,
    *,
    content_boxes: Sequence[Sequence[int]] = (),
    current: str = "#ffffff",
    min_share: float = 0.03,
    min_delta: int = 10,
    stride: int = 4,
) -> str:
    """Flat approximation of the page colour, measured where nothing is drawn.

    The canvas background used to be the image's dominant colour, which is the
    *card* colour whenever a card covers most of the page -- the page then
    renders white around a white card and its real tint is lost.

    Two guards keep this from touching pages that were already right: the
    uncovered area must be big enough to be the page at all, and the measured
    colour must differ from the current one by ``min_delta``.
    """
    if pixels is None:
        return current
    reference_rgb = hex_to_rgb(current)
    if min(reference_rgb) < 230:
        # A dark or saturated canvas already states its own background; the
        # uncovered-pixel trick is only needed where a big white card makes the
        # image's dominant colour the *card* colour instead of the page.
        return current
    height, width = pixels.height, pixels.width
    uncovered = np.ones((height, width), dtype=bool)
    for box in content_boxes:
        if len(box) != 4:
            continue
        x, y, w, h = (int(v) for v in box)
        if w <= 0 or h <= 0:
            continue
        uncovered[max(0, y) : min(height, y + h), max(0, x) : min(width, x + w)] = False
    sampled = pixels.array[::stride, ::stride][uncovered[::stride, ::stride]]
    if sampled.size == 0:
        return current
    total_points = (height // stride + 1) * (width // stride + 1)
    if sampled.shape[0] < total_points * min_share:
        return current
    # Trimmed median: a page gradient spreads the vote, and a dark page is
    # half shadow, so neither the mode nor the raw median is stable.  Dropping
    # the darkest and brightest tenth keeps both cases on the page tone.
    low = np.percentile(sampled, 10, axis=0)
    high = np.percentile(sampled, 90, axis=0)
    core = sampled[np.all((sampled >= low) & (sampled <= high), axis=1)]
    if core.size:
        measured = tuple(int(v) for v in np.median(core, axis=0))
    else:
        measured = tuple(int(v) for v in np.median(sampled, axis=0))
    try:
        reference = tuple(int(current.lstrip("#")[index : index + 2], 16) for index in (0, 2, 4))
    except (ValueError, IndexError):
        return _hex(measured)
    if _distance(measured, reference) < min_delta:
        return current
    return _hex(measured)


def control_palette(
    pixels: ReferencePixels | None,
    box: Sequence[int],
    *,
    surface_share: float = 0.55,
    ink_share: float = 0.02,
    ink_distance: int = 40,
    ring: int = 2,
) -> dict[str, Any]:
    """Separate a control's own surface from the ink drawn on it.

    A button that owns a fill has one colour covering most of its interior.  A
    *label* that merely looks like a control (``控制台`` in a dark nav) is mostly
    glyphs: the largest interior colour is the text, and taking it as the fill
    paints a light chip with dark text -- the exact inverse of the screenshot.

    So: if no colour covers ``surface_share`` of the interior, the control has
    no surface of its own and the page colour outside it is the truth.  The ink
    is then the heaviest colour that is far from that surface.
    """
    if pixels is None:
        return {}
    x, y, w, h = (int(v) for v in box)
    if w < 6 or h < 6 or x < 0 or y < 0:
        return {}
    inner = pixels.array[
        y + ring : min(pixels.height, y + h - ring),
        x + ring : min(pixels.width, x + w - ring),
    ]
    if inner.size == 0:
        return {}
    flat = inner.reshape(-1, 3) // 4 * 4
    values, counts = np.unique(flat, axis=0, return_counts=True)
    order = np.argsort(-counts)
    total = flat.shape[0]
    top_color = tuple(int(v) for v in values[order[0]])
    top_share = float(counts[order[0]]) / total
    outside = pixels.ring_color(box, ring=ring)
    if top_share >= surface_share and outside is not None and _distance(top_color, outside) >= 16:
        surface, has_surface = top_color, True
    elif top_share >= 0.85:
        # A flat interior with no contrasting surround: still its own surface.
        surface, has_surface = top_color, True
    else:
        surface, has_surface = outside or top_color, False
    ink: Color | None = None
    for index in order:
        share = float(counts[index]) / total
        if share < ink_share:
            break
        candidate = tuple(int(v) for v in values[index])
        if _distance(candidate, surface) >= ink_distance:
            ink = candidate
            break
    return {
        "surface": _hex(surface),
        "hasSurface": has_surface,
        "ink": _hex(ink) if ink else None,
        "surfaceShare": round(top_share, 3),
        "outside": _hex(outside) if outside else None,
    }


def hex_to_rgb(value: str) -> Color:
    text = str(value or "").lstrip("#")
    if len(text) != 6:
        return (0, 0, 0)
    try:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


def color_gap(left: str, right: Color | str) -> int:
    """Channel-wise distance between two colours, either as hex or as a tuple."""
    other = hex_to_rgb(right) if isinstance(right, str) else right
    return _distance(hex_to_rgb(left), other)
