"""测试配置。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import os as _os
import pytest


def pytest_collection_modifyitems(config, items):
    if _os.getenv("RUN_INTEGRATION") != "1":
        _skip = pytest.mark.skip(reason="integration: 需网络/Chromium/模型/CV 环境，设置 RUN_INTEGRATION=1 后运行")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(_skip)
