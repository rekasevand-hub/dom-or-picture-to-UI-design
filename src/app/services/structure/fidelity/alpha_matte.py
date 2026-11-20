"""Cut the rectangle off a crop whose object does not fill it.

Every picture in the plan is a rectangle of source pixels.  That is exactly
right for a photograph and exactly wrong for a gift box standing on a card:
the crop carries the card's background in its four corners, and the moment the
card behind it is rebuilt from a gradient, a shadow, or a slightly different
sample, those corners become a visible box.

The operation is only safe when the picture itself says the object is isolated:
the outermost band of the crop must be *flat* — a single fill or a slow
gradient.  A photograph has structure right up to its border, and cutting it out
would invent an edge that the page never had, so it is refused up front.  This
is the only admission test; there is no per-page list.

Everything below is measured from the pixels: no model, no config per sample.
`cv2.grabCut` is the only non-trivial dependency and it ships with OpenCV.

    admitted, why = admit(page, box)      # -> is this crop a candidate?
    payload, how  = matte_png_b64(path, box, canvas)
"""

from __future__ import annotations

import base64
import io
from typing import Any, Sequence

#: The switch itself.  Off means every crop stays an opaque rectangle.
#:
#: Measured, not assumed: this compiler cuts every picture 1:1 out of the page
#: and paints it back at the same coordinates, so the crop *reproduces* its own
#: rectangle exactly and the rectangle is never visible.  Turning the matte on
#: can therefore only lose — on the CSDN gift box it took the crop's own region
#: from ``within30 100.0 / mean 0.00`` to ``95.9 / 4.51`` and the page from
#: ``94.5`` to ``94.4``, because the transparent corners revealed ``#fdfcfa``
#: where the picture had a warm ``#fef4ed`` gradient, and because the soft
#: shadow under the box came back as a halo.
#:
#: It stays here, tested, for the case it was written for: a crop that is
#: *re-placed* — regenerated or substituted by the asset route, resized by the
#: target renderer, or dropped onto a surface the plan rebuilt into a solid.
#: That is the only situation in which the rectangle can be seen, and the only
#: one in which cutting it out is a gain.
ALPHA_MATTE_ENABLED = False

#: The band a crop has to sit in to be worth cutting out.  Below it is an icon
#: (OmniParser owns those, and a 30px logo loses more than it gains from four
#: mixed edge pixels); above it is a background, not an object.
ALPHA_MATTE_MIN_SHARE = 0.02
ALPHA_MATTE_MAX_SHARE = 0.30

#: Width of the band read for the admission test, and the mean |dI| that counts
#: as flat.  Measured across the corpus: the two isolated objects score 0.86 and
#: 3.25, every other crop with structure scores 5+ and is out of band anyway.
ALPHA_MATTE_RING = 3
ALPHA_MATTE_RING_GRAD = 6.0

#: Interior pixels at least this steep are seeds for "probably foreground".
ALPHA_MATTE_EDGE_GRAD = 24.0
#: Rounds of graph cut.  More than four converges without moving the boundary by
#: a pixel; fewer leaves the mask hugging the seed band.
ALPHA_MATTE_ITERS = 4
#: Feathering sigma, in pixels, applied to the binary mask.
ALPHA_MATTE_FEATHER = 1.5
#: A matte that keeps almost nothing, or almost everything, bought nothing —
#: the first is a bad cut, the second is a rectangle dressed up as a PNG.
ALPHA_MATTE_MIN_KEEP = 0.15
ALPHA_MATTE_MAX_KEEP = 0.995
#: Below this alpha the decontamination divides by ~0 and invents colours.
ALPHA_MATTE_DECONTAMINATE_MIN = 0.25

#: Roles that are already a *repair* rather than a picture.  A mark is a strip of
#: text re-cut from the source and a patch is page background: cutting either of
#: them out would erase the thing it exists to carry.
ALPHA_MATTE_SKIP_ROLES = ("patch", "mark", "text-backdrop", "source-chrom")


def _as_array(image) -> Any:
    import numpy as np

    array = np.asarray(image)
    if array.ndim == 2:
        array = np.stack([array] * 3, axis=2)
    return array[..., :3].astype(np.uint8)


def ring_flatness(image, box: Sequence[int], thickness: int = ALPHA_MATTE_RING) -> dict:
    """Mean gradient of the crop's own outermost band, and its colour spread.

    The band is read *inside* the crop because that is where the offending
    rectangle is drawn.  Three pixels outside it is page background by
    construction: it would score zero for a photograph too, and admit everything.
    """
    import numpy as np

    truth = _as_array(image)
    height, width = truth.shape[:2]
    x, y, w, h = (int(value) for value in box)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return {"grad": 0.0, "spread": 0.0, "ok": False}
    crop = truth[y0:y1, x0:x1].astype(np.float32)
    t = max(1, min(int(thickness), (x1 - x0) // 4, (y1 - y0) // 4))
    mask = np.zeros(crop.shape[:2], dtype=bool)
    mask[:t, :] = mask[-t:, :] = True
    mask[:, :t] = mask[:, -t:] = True
    gray = crop.mean(axis=2)
    dx = np.abs(np.diff(gray, axis=1))
    dy = np.abs(np.diff(gray, axis=0))
    band = np.concatenate([dx[mask[:, :-1]], dy[mask[:-1, :]]])
    colours = crop[mask]
    return {
        "grad": float(band.mean()) if band.size else 0.0,
        "spread": float((colours.max(axis=0) - colours.min(axis=0)).max()) if colours.size else 0.0,
        "ok": True,
    }


def admit(image, box: Sequence[int], *, canvas: tuple[int, int] | None = None,
          role: str = "") -> tuple[bool, dict[str, Any]]:
    """Is this crop an isolated object on a flat backdrop?

    Three independent refusals, in the order that costs least:

    * the role is a repair, not a picture;
    * the crop is the wrong size to be an object (icon band or background);
    * the object's own border is busy, so there is no rectangle to remove.
    """
    height, width = _as_array(image).shape[:2]
    cw, ch = canvas or (width, height)
    x, y, w, h = (int(value) for value in list(box)[:4])
    share = (max(0, w) * max(0, h)) / float(max(1, cw * ch))
    evidence: dict[str, Any] = {"share": round(share, 4), "role": role}
    if role in ALPHA_MATTE_SKIP_ROLES:
        return False, {**evidence, "reason": "repair-role"}
    if not (ALPHA_MATTE_MIN_SHARE <= share <= ALPHA_MATTE_MAX_SHARE):
        return False, {**evidence, "reason": "size-band"}
    stats = ring_flatness(image, box)
    evidence.update({"grad": round(stats["grad"], 2), "spread": round(stats["spread"], 1)})
    if not stats["ok"]:
        return False, {**evidence, "reason": "degenerate"}
    if stats["grad"] > ALPHA_MATTE_RING_GRAD:
        return False, {**evidence, "reason": "busy-border"}
    return True, {**evidence, "reason": "flat-border"}


def _backdrop_region(crop, pad: int) -> Any:
    """The rectangle itself: everything reachable from the crop's border.

    Seeding "steep pixels are foreground" is not enough, and the measurement
    says so: on the CSDN gift box it kept 32% of the crop with a quarter of the
    box eaten.  Steep pixels are the *outline*, so the foreground model learned
    a rim and nothing else, while the whole flat interior sat in the background
    model.

    The rectangle has a definition that needs no model: it is the connected
    region of backdrop that touches the crop's border, and the object's own
    outline is what stops it.  So the barrier is the edge map, dilated by one
    pixel to close anti-aliasing gaps, and the backdrop is the flood fill of
    everything that barrier does not separate from the border.  GrabCut then
    only has to soften the boundary the fill already found.
    """
    import cv2
    import numpy as np

    height, width = crop.shape[:2]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    barrier = (np.hypot(gx, gy) >= ALPHA_MATTE_EDGE_GRAD).astype(np.uint8)
    barrier = cv2.dilate(barrier, np.ones((3, 3), np.uint8))
    walkable = (barrier == 0).astype(np.uint8)
    count, labels = cv2.connectedComponents(walkable, connectivity=8)
    if count <= 1:
        return np.zeros((height, width), dtype=bool)
    border = np.concatenate(
        [
            labels[:pad, :].reshape(-1),
            labels[-pad:, :].reshape(-1),
            labels[:, :pad].reshape(-1),
            labels[:, -pad:].reshape(-1),
        ]
    )
    seeds = {int(value) for value in border if value != 0}
    if not seeds:
        return np.zeros((height, width), dtype=bool)
    return np.isin(labels, list(seeds))


def _seed_mask(crop, pad: int) -> Any:
    """Definite background outside and in the flood-filled backdrop, rest foreground."""
    import cv2
    import numpy as np

    height, width = crop.shape[:2]
    mask = np.full((height, width), cv2.GC_PR_FGD, dtype=np.uint8)
    backdrop = _backdrop_region(crop, pad)
    mask[backdrop] = cv2.GC_BGD
    # 外扩的环带是确定的背景：那是这张图之外的地方，任何东西都不属于它。
    mask[:pad, :] = cv2.GC_BGD
    mask[-pad:, :] = cv2.GC_BGD
    mask[:, :pad] = cv2.GC_BGD
    mask[:, -pad:] = cv2.GC_BGD
    return mask


def matte(crop, *, pad: int = ALPHA_MATTE_RING) -> tuple[Any | None, dict[str, Any]]:
    """RGBA of one crop with its backdrop removed, or None when the cut is bad."""
    import cv2
    import numpy as np

    rgb = _as_array(crop)
    height, width = rgb.shape[:2]
    padded = cv2.copyMakeBorder(rgb, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    mask = _seed_mask(padded, pad)
    inside = mask[pad : pad + height, pad : pad + width]
    if float((inside == cv2.GC_BGD).mean()) > 0.98:
        # 整块都是连通的底：这张图里没有物体，切出来什么也不剩。
        return None, {"reason": "no-object"}
    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(
            cv2.cvtColor(padded, cv2.COLOR_RGB2BGR),
            mask,
            None,
            background_model,
            foreground_model,
            ALPHA_MATTE_ITERS,
            cv2.GC_INIT_WITH_MASK,
        )
    except cv2.error as exc:  # pragma: no cover - OpenCV build without grabCut
        return None, {"reason": f"grabcut:{exc.code}"}
    kept = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), np.uint8(255), np.uint8(0)
    )
    kept = kept[pad : pad + height, pad : pad + width]
    # 一拍噪声：3×3 开运算只吃掉孤立像素，不动边界形状。
    kept = cv2.morphologyEx(kept, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    share = float((kept > 0).mean())
    if share < ALPHA_MATTE_MIN_KEEP:
        return None, {"reason": "cut-too-thin", "keep": round(share, 3)}
    if share > ALPHA_MATTE_MAX_KEEP:
        # 什么都没切掉：留着不透明的裁片，至少字节更少、下游更简单。
        return None, {"reason": "cut-kept-all", "keep": round(share, 3)}

    alpha = cv2.GaussianBlur(kept.astype(np.float32) / 255.0, (0, 0), ALPHA_MATTE_FEATHER)
    alpha = np.clip(alpha, 0.0, 1.0)

    # 去污染：边缘像素是物体与旧底色的混合，直接留会带一圈原卡片的颜色。
    # 按 I = a·F + (1-a)·B 反解 F，只在 a 够大时做除法。
    ring = np.concatenate(
        [
            padded[:pad, :].reshape(-1, 3),
            padded[-pad:, :].reshape(-1, 3),
            padded[:, :pad].reshape(-1, 3),
            padded[:, -pad:].reshape(-1, 3),
        ]
    )
    backdrop = np.median(ring, axis=0).astype(np.float32)
    colour = rgb.astype(np.float32)
    safe = alpha >= ALPHA_MATTE_DECONTAMINATE_MIN
    if safe.any():
        weight = alpha[safe][..., None]
        unmixed = (colour[safe] - (1.0 - weight) * backdrop) / weight
        colour[safe] = np.clip(unmixed, 0.0, 255.0)

    rgba = np.dstack([colour.astype(np.uint8), (alpha * 255.0).round().astype(np.uint8)])
    return rgba, {
        "reason": "matted",
        "keep": round(share, 3),
        "backdrop": "#{:02x}{:02x}{:02x}".format(*(int(value) for value in backdrop)),
        "soft_pixels": int(((alpha > 0.02) & (alpha < 0.98)).sum()),
    }


def matte_png_b64(
    image_path: str,
    x: int,
    y: int,
    w: int,
    h: int,
    canvas_w: int,
    canvas_h: int,
    *,
    role: str = "",
) -> tuple[str | None, dict[str, Any]]:
    """Presentation-ready payload for one crop, or None to keep it opaque.

    Reads the source itself: the caller already has the rectangle encoded, and
    decoding a base64 PNG back into pixels just to cut it out is a round trip
    through a lossless codec to reach data we already had on disk.
    """
    if not ALPHA_MATTE_ENABLED:
        return None, {"reason": "disabled"}
    import numpy as np
    from PIL import Image

    try:
        with Image.open(image_path) as opened:
            page = np.asarray(opened.convert("RGB"))
            height, width = page.shape[:2]
            x0, y0 = max(0, int(x)), max(0, int(y))
            x1, y1 = min(width, int(x) + int(w)), min(height, int(y) + int(h))
            if x1 - x0 < 8 or y1 - y0 < 8:
                return None, {"reason": "degenerate"}
            ok, evidence = admit(
                page, (x0, y0, x1 - x0, y1 - y0), canvas=(canvas_w, canvas_h), role=role
            )
            if not ok:
                return None, evidence
            crop = page[y0:y1, x0:x1]
            rgba, how = matte(crop)
            if rgba is None:
                return None, {**evidence, **how}
            buffer = io.BytesIO()
            Image.fromarray(rgba, "RGBA").save(buffer, format="PNG")
    except (OSError, ValueError) as exc:
        return None, {"reason": f"unreadable:{exc}"}
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    return payload, {**evidence, **how}
