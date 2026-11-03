"""Deterministic local edge-blend repair.

Ported and adapted from:
https://github.com/50kg/image-to-slice
commit ecc184c982a000c815796864ecce034fc0030c31

MIT License
Copyright (c) 2026 liu chao

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
from PIL import Image


def _placement(value: Any) -> tuple[int, int, int, int]:
    if not isinstance(value, Mapping):
        raise ValueError("placement must be an object")
    try:
        x = int(round(float(value["x"])))
        y = int(round(float(value["y"])))
        width = int(round(float(value["width"])))
        height = int(round(float(value["height"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "placement must contain numeric x, y, width and height"
        ) from exc
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("placement must use non-negative origin and positive size")
    return x, y, width, height


def _collect_rect_colors(
    array: np.ndarray,
    x: int,
    y: int,
    width: int,
    height: int,
) -> list[np.ndarray]:
    image_height, image_width = array.shape[:2]
    left = max(0, min(image_width, int(x)))
    top = max(0, min(image_height, int(y)))
    right = max(left, min(image_width, int(x + width)))
    bottom = max(top, min(image_height, int(y + height)))
    if right <= left or bottom <= top:
        return []
    crop = array[top:bottom, left:right]
    area = crop.shape[0] * crop.shape[1]
    step = max(1, int(math.sqrt(area / 160)))
    sampled = crop[::step, ::step].reshape(-1, 3)
    return [row.astype(np.float64) for row in sampled]


def _average(colors: list[np.ndarray], fallback: np.ndarray) -> np.ndarray:
    if not colors:
        return fallback
    return np.mean(np.stack(colors, axis=0), axis=0)


def create_edge_blend_patch(
    image: Image.Image,
    placement: dict,
    *,
    band_ratio: float = 0.12,
) -> Image.Image:
    """Create a bounded color-continuation patch for one placement."""

    if not isinstance(image, Image.Image):
        raise ValueError("image must be a PIL Image")
    if not 0 <= float(band_ratio) <= 0.5:
        raise ValueError("band_ratio must be in 0..0.5")
    x, y, width, height = _placement(placement)
    if x >= image.width or y >= image.height:
        raise ValueError("placement must start inside image bounds")
    width = min(width, image.width - x)
    height = min(height, image.height - y)
    if width <= 0 or height <= 0:
        raise ValueError("placement must intersect image bounds")

    array = np.asarray(image.convert("RGB"))
    band = max(2, min(10, int(round(min(width, height) * band_ratio))))
    top_samples = _collect_rect_colors(
        array,
        x,
        max(0, y - band),
        width,
        min(band, y),
    )
    right_samples = _collect_rect_colors(
        array,
        min(array.shape[1] - 1, x + width),
        y,
        min(band, array.shape[1] - x - width),
        height,
    )
    bottom_samples = _collect_rect_colors(
        array,
        x,
        min(array.shape[0] - 1, y + height),
        width,
        min(band, array.shape[0] - y - height),
    )
    left_samples = _collect_rect_colors(
        array,
        max(0, x - band),
        y,
        min(band, x),
        height,
    )
    all_samples = top_samples + right_samples + bottom_samples + left_samples
    center = _average(
        all_samples,
        np.array([255.0, 255.0, 255.0], dtype=np.float64),
    )
    top = _average(top_samples, center)
    right = _average(right_samples, center)
    bottom = _average(bottom_samples, center)
    left = _average(left_samples, center)

    horizontal_amount = (
        np.linspace(0.0, 1.0, width, dtype=np.float64)
        if width > 1
        else np.array([0.5], dtype=np.float64)
    )
    vertical_amount = (
        np.linspace(0.0, 1.0, height, dtype=np.float64)
        if height > 1
        else np.array([0.5], dtype=np.float64)
    )
    horizontal = (
        left[None, None, :] * (1.0 - horizontal_amount[None, :, None])
        + right[None, None, :] * horizontal_amount[None, :, None]
    )
    vertical = (
        top[None, None, :] * (1.0 - vertical_amount[:, None, None])
        + bottom[None, None, :] * vertical_amount[:, None, None]
    )
    edge_bias = np.minimum.reduce(
        [
            np.tile(np.arange(width, dtype=np.float64), (height, 1)),
            np.tile(np.arange(height, dtype=np.float64)[:, None], (1, width)),
            np.tile(
                np.arange(width - 1, -1, -1, dtype=np.float64),
                (height, 1),
            ),
            np.tile(
                np.arange(height - 1, -1, -1, dtype=np.float64)[:, None],
                (1, width),
            ),
        ]
    )
    center_weight = np.clip(edge_bias / max(width, height) * 1.35, 0.0, 0.32)
    blended = horizontal * (1.0 - 0.46) + vertical * 0.46
    blended = (
        blended * (1.0 - center_weight[:, :, None])
        + center[None, None, :] * center_weight[:, :, None]
    )
    pixels = np.clip(np.rint(blended), 0, 255).astype(np.uint8)
    return Image.fromarray(pixels, mode="RGB")
