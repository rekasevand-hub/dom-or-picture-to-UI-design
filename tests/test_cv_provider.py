# -*- coding: utf-8 -*-
"""CV provider 测试：离线验证容器管线可用性探测；完整冒烟标 integration（EasyOCR+OmniParser GPU）。"""
from __future__ import annotations

import os

import pytest

from src.app.services.structure.providers.cv import cv_available


def test_cv_available_detects_pipeline():
    assert cv_available() is True


@pytest.mark.integration
def test_cv_provider_smoke(tmp_path):
    img = r"D:\LLM-Data\View_fill\user_test3.png"
    if not os.path.exists(img):
        pytest.skip(f"缺少 CV 集成测试图片: {img}")
    from PIL import Image
    from src.app.services.structure.providers.base import ProviderContext
    from src.app.services.structure.providers.cv import CVProvider

    w, h = Image.open(img).size  # 以真实图片尺寸为准（brief 硬编码 1336 与实图不符）
    ctx = ProviderContext(image_path=img, image_w=w, image_h=h,
                          route="cv", output_dir=str(tmp_path))
    g = CVProvider().run(ctx)
    assert g["containers"] and g["elements"]
