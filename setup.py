"""项目安装配置。"""
from __future__ import annotations

from setuptools import find_packages, setup

setup(
    name="figma-auto-agent",
    version="0.1.0",
    description="UI 自动还原 Agent：从截图提取 UI 组件并生成 Figma/SVG 原型",
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
        "dev": ["pytest>=7.4.0"],
    },
    entry_points={
        "console_scripts": [
            "figma-auto-agent=src.main:main",
        ],
    },
)
