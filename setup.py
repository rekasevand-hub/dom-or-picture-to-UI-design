"""项目安装配置。"""
from __future__ import annotations

from pathlib import Path

from setuptools import find_packages, setup

# 版本号单一定义在仓库根的 VERSION；1.1.0 交付范围见 HANDOFF_2026-10-17_release.md。
VERSION = Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip()

setup(
    name="figma-auto-agent",
    version=VERSION,
    description="UI 自动还原 Agent：DOM/视觉多路线生成 SVG、Figma 与 Axure 原型",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "opencv-python>=4.8.0",
        "numpy>=1.24.0",
        "pillow>=10.0.0",
        "requests>=2.31.0",
    ],
    extras_require={
        "ocr": ["easyocr>=1.7.0"],
        "tesseract": ["pytesseract>=0.3.10"],
        "llm": ["openai>=1.0.0"],
        "server": ["fastapi>=0.100.0", "uvicorn>=0.23.0", "websockets>=12.0"],
        "dev": ["pytest>=7.4.0", "cryptography>=42.0.0"],
    },
    entry_points={
        "console_scripts": [
            "figma-auto-agent=src.main:main",
        ],
    },
)
