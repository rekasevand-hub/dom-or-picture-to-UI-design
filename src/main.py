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
    parser.add_argument("--route", default=None, choices=["auto", "dom", "grounding", "cv"],
                        help="结构来源路线")
    parser.add_argument("--fast", action="store_true",
                        help="（实验）DOM 路线用 computed style 几何直出 DesignSpec，跳过 VLM 语义生成")
    parser.add_argument("--enrich", action="store_true", help="视觉补充（默认关）")
    parser.add_argument("--storage-state", default=None,
                        help="Playwright 登录态 JSON：URL 抓取时复用已登录 cookie/localStorage（登录保护页面用）")
    parser.add_argument("--login-state", default=None,
                        help="交互导出登录态：打开有头浏览器登录 --url，回车后保存到该 JSON（只导出，不跑管线）")
    parser.add_argument("--tool", default=None, choices=["svg", "figma", "jsdesign", "mockingbot"], help="原型工具")
    parser.add_argument("--ocr-engine", default=None, choices=["none", "easyocr", "tesseract"], help="OCR 引擎")
    parser.add_argument("--output-dir", default=None, help="中间产物输出目录")
    parser.add_argument("--direct-render", action="store_true", help="跳过 LLM，直接把检测组件渲染到原型工具")
    parser.add_argument("--interactive", action="store_true",
                        help="交互式选择入口：引导选择 URL/截图 与 处理路线")
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
    if args.storage_state:
        from dataclasses import replace
        config = replace(config, playwright_storage_state=str(Path(args.storage_state)))
    config.ensure_dirs()

    tool = args.tool or config.prototype_tool
    ocr_engine = args.ocr_engine or config.ocr_engine

    if args.interactive:
        from src.app.agents.route_select import select_interactive
        sel = select_interactive(
            config, prefill={"url": args.url, "image": args.image,
                             "route": args.route, "tool": tool})
        args.url, args.image = sel["url"], sel["image"]
        args.route = sel["route"]
        tool = sel["tool"]
        # 交互模式下无输入视为用户放弃 -> 退出码 1（不静默跑旧流程）
        if not args.url and not args.image:
            parser.error("交互选择未给出 URL/截图")

    if args.login_state:
        if args.storage_state:
            parser.error("--login-state 与 --storage-state 请分两步使用：先 --login-state 导出登录态，再用 --storage-state 运行")
        if not args.url:
            parser.error("--login-state 需要同时提供 --url（在浏览器里登录的目标页面）")
        from src.app.services.structure.capture import export_login_state
        path = export_login_state(args.url, args.login_state, config)
        logger.info("登录态已导出：%s", path)
        print(f"\n下一步：对同一 URL 加 --storage-state \"{path}\" 运行，例如：")
        print(f'python -m src.main --url "{args.url}" --storage-state "{path}" --route auto --tool svg')
        return 0

    if not args.url and not args.image:
        parser.error("必须提供 --url 或 --image")

    try:
        if args.url or args.route:
            from src.app.agents.precise_agent import PreciseAgent
            agent = PreciseAgent(config)
            route = args.route or config.route_default   # ROUTE 环境变量，默认 auto
            agent.run(url=args.url, image=args.image, route=route, tool=tool, enrich=args.enrich)
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
