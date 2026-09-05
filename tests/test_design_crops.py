# -*- coding: utf-8 -*-
"""design_crops：截图裁剪回填的单元测试。"""
import base64
import io

import pytest
from PIL import Image

from src.app.services.som.design_crops import (
    backfill_design_image_crops,
    crop_image_b64,
)


def _make_shot(path, w=200, h=100):
    im = Image.new("RGB", (w, h), (255, 255, 255))
    for x in range(10, 30):
        for y in range(10, 30):
            im.putpixel((x, y), (255, 0, 0))
    im.save(path)
    return w, h


def test_crop_image_b64_clamps_and_encodes_png(tmp_path):
    shot = tmp_path / "shot.png"
    _make_shot(str(shot))
    b64 = crop_image_b64(str(shot), 10, 10, 20, 20, 200, 100)
    assert b64
    raw = base64.b64decode(b64)
    im = Image.open(io.BytesIO(raw))
    assert im.size == (20, 20)
    assert im.convert("RGB").getpixel((0, 0)) == (255, 0, 0)
    # 完全在画布外 -> None
    assert crop_image_b64(str(shot), 500, 10, 20, 20, 200, 100) is None


def test_backfill_fills_images_keeps_others(tmp_path):
    shot = tmp_path / "shot.png"
    _make_shot(str(shot))
    design = {
        "canvas": {"width": 200, "height": 100},
        "elements": [
            {"id": "img1", "type": "image", "x": 10, "y": 10,
             "width": 20, "height": 20},
            {"id": "av1", "type": "avatar", "x": 40, "y": 10,
             "width": 20, "height": 20},
            {"id": "img2", "type": "image", "x": 60, "y": 10,
             "width": 20, "height": 20, "imageBase64": "already"},
            {"id": "btn1", "type": "button", "x": 10, "y": 60,
             "width": 60, "height": 24, "text": "确定"},
        ],
    }
    stats = backfill_design_image_crops(design, str(shot))
    assert stats == {"image_elements": 3, "backfilled": 2, "failed": 0}
    by_id = {e["id"]: e for e in design["elements"]}
    assert by_id["img1"]["imageBase64"]
    assert by_id["av1"]["imageBase64"]
    assert by_id["img2"]["imageBase64"] == "already"
    assert "imageBase64" not in by_id["btn1"]


def test_backfill_reports_failed_and_is_idempotent(tmp_path):
    shot = tmp_path / "shot.png"
    _make_shot(str(shot))
    design = {
        "canvas": {"width": 200, "height": 100},
        "elements": [
            {"id": "off", "type": "image", "x": 500, "y": 10,
             "width": 20, "height": 20},
            {"id": "ok", "type": "image", "x": 10, "y": 10,
             "width": 20, "height": 20},
        ],
    }
    s1 = backfill_design_image_crops(design, str(shot))
    assert s1["failed"] == 1 and s1["backfilled"] == 1
    s2 = backfill_design_image_crops(design, str(shot))
    assert s2["failed"] == 1 and s2["backfilled"] == 0  # 已有 b64 不再重复裁剪
    assert "imageBase64" not in design["elements"][0]
