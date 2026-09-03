# -*- coding: utf-8 -*-
"""metrics 三路对比指标离线测试。"""
from __future__ import annotations

from src.app.services.structure.metrics import container_iou_matrix, text_containment_rate


def test_iou_matrix():
    a = [{"bbox": [0, 0, 100, 100]}]
    b = [{"bbox": [0, 0, 50, 50]}]
    assert abs(container_iou_matrix(a, b)[0][0] - 0.25) < 1e-6


def test_containment_rate():
    g = {"containers": [{"bbox": [0, 0, 100, 100]}],
         "elements": [{"bbox": [10, 10, 10, 10], "type": "text"},
                      {"bbox": [200, 200, 10, 10], "type": "text"}]}
    assert text_containment_rate(g) == 0.5
