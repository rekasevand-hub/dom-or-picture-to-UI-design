# -*- coding: utf-8 -*-
"""把 SVG（直出稿）栅格化成 PNG，用于截图差分的视觉回归。"""

from __future__ import annotations

import logging
from pathlib import Path

from src.app.utils.path_utils import file_uri

logger = logging.getLogger(__name__)


def rasterize_svg(
    svg_path: str | Path,
    png_path: str | Path,
    width: int | None = None,
    height: int | None = None,
    wait_ms: int = 700,
    device_scale_factor: int = 1,
) -> str:
    """把 svg_path 渲染成 png_path，并匹配采集截图的设备像素比。"""
    from playwright.sync_api import sync_playwright
    import xml.etree.ElementTree as ET

    svg_path, png_path = Path(svg_path), Path(png_path)
    if width is None or height is None:
        root = ET.parse(svg_path).getroot()
        width = width or int(float(str(root.get("width", 800)).replace("px", "")))
        height = height or int(float(str(root.get("height", 600)).replace("px", "")))
    scale = max(1, int(device_scale_factor))
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": int(width), "height": int(height)},
            device_scale_factor=scale,
        )
        page.goto(file_uri(svg_path))
        page.wait_for_timeout(wait_ms)
        page.screenshot(path=str(png_path))
        browser.close()
    return str(png_path)
