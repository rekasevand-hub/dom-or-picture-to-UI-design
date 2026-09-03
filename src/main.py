"""
CLI 入口：解析参数并启动 UI 自动还原 Agent。
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 把项目根目录加入 PYTHONPATH，确保 src/ 包可被导入
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.app.agents import ReconstructAgent
from src.app.utils.logging_utils import setup_logging
from src.config import load_config

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UI 自动还原 Agent")
    parser.add_argument("--image", default=None, help="输入图片路径（新流程可省略）")
    parser.add_argument("--url", default=None, help="网页 URL（新流程）")
    parser.add_argument("--route", default=None, choices=["auto", "dom", "a11y", "grounding", "cv"],
                        help="结构来源路线")
    parser.add_argument("--enrich", action="store_true", help="视觉补充（默认关）")
    parser.add_argument("--tool", default=None, choices=["svg", "figma", "jsdesign", "mockingbot"], help="原型工具")
    parser.add_argument("--ocr-engine", default=None, choices=["none", "easyocr", "tesseract"], help="OCR 引擎")
    parser.add_argument("--output-dir", default=None, help="中间产物输出目录")
    parser.add_argument("--direct-render", action="store_true", help="跳过 LLM，直接把检测组件渲染到原型工具")
    parser.add_argument("--debug", action="store_true", help="打印更多日志")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    setup_logging(logging.DEBUG if args.debug else logging.INFO)

    config = load_config()
    if args.output_dir:
        from dataclasses import replace
        config = replace(config, output_dir=Path(args.output_dir))
    config.ensure_dirs()

    tool = args.tool or config.prototype_tool
    ocr_engine = args.ocr_engine or config.ocr_engine

    if not args.url and not args.image:
        parser.error("必须提供 --url 或 --image")

    try:
        if args.url or args.route:
            from src.app.agents.precise_agent import PreciseAgent
            agent = PreciseAgent(config)
            agent.run(url=args.url, image=args.image, route=args.route or "auto",
                      tool=tool, enrich=args.enrich)
            return 0

        agent = ReconstructAgent(config)
        agent.run(
            image_path=args.image,
            tool=tool,
            ocr_engine=ocr_engine,
            direct_render=args.direct_render,
        )
        return 0
    except Exception as exc:
        logger.error(f"运行失败: {exc}", exc_info=args.debug)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
