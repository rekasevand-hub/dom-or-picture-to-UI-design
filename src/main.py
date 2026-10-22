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
    parser.add_argument("--image", action="append", default=None, metavar="PATH",
                        help="输入图片路径（可重复：N 张不同界面的截图 -> N 页，每张一页；"
                             "同一页面不同区域的多张图要合并成 1 页；多页当前仅 Axure 支持）")
    parser.add_argument("--url", action="append", default=None, metavar="URL",
                        help="网页 URL（可重复：N 个 URL -> N 页，每个 URL 一页）")
    parser.add_argument("--route", default=None, choices=["auto", "dom", "grounding", "cv"],
                        help="结构来源路线")
    parser.add_argument("--fast", action="store_true",
                        help="（已废弃，参数被忽略）DOM 路线恒定 computed style 直出，保留仅为兼容旧脚本")
    parser.add_argument("--enrich", action="store_true",
                        help="（已废弃，参数被忽略）视觉补充开关从未实现，保留仅为兼容旧脚本")
    parser.add_argument("--storage-state", default=None,
                        help="Playwright 登录态 JSON：URL 抓取时复用已登录 cookie/localStorage（登录保护页面用）")
    parser.add_argument("--user-data-dir", default=None,
                        help="真实浏览器会话的持久化用户目录：无头采集被重定向/反爬拦截时，"
                             "优先用它启动有头 Chromium 重试（可复用已登录/已过验证的会话）")
    parser.add_argument("--headed-fallback", action=argparse.BooleanOptionalAction, default=None,
                        help="无头采集被拦截时是否用有头浏览器重试（默认开启；"
                             "--no-headed-fallback 关闭）")
    parser.add_argument("--login-state", default=None,
                        help="交互导出登录态：打开有头浏览器登录 --url，回车后保存到该 JSON（只导出，不跑管线）")
    parser.add_argument("--tool", default=None,
                        choices=["svg", "figma", "jsdesign", "mockingbot", "axure"],
                        help="原型工具（axure：从零生成 .rp；多输入时生成多页）")
    parser.add_argument("--ocr-engine", default=None, choices=["none", "easyocr", "tesseract"], help="OCR 引擎")
    parser.add_argument("--output-dir", default=None, help="中间产物输出目录")
    parser.add_argument("--direct-render", action="store_true", help="跳过 LLM，直接把检测组件渲染到原型工具")
    parser.add_argument("--interactive", action="store_true",
                        help="交互式选择入口：引导选择 URL/截图 与 处理路线")
    parser.add_argument("--pick-crops", action="store_true",
                        help="（仅 grounding/cv 像素链路）采集后弹出框选窗口，手工框选需要"
                             "按原图像素还原的区域（图标字体/图表/任意直出画不出的块），"
                             "存 manual_crops.json；dom 路线能从 DOM 标识自动判出图标/图片，"
                             "会自动跳过。不带 --url 时用输出目录里已有的产物重渲染"
                             "（配合框选快速迭代）")
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
    if args.user_data_dir:
        from dataclasses import replace
        config = replace(config, playwright_user_data_dir=str(Path(args.user_data_dir)))
    if args.headed_fallback is not None:
        from dataclasses import replace
        config = replace(config, playwright_headed_fallback=bool(args.headed_fallback))
    config.ensure_dirs()

    tool = args.tool or config.prototype_tool
    ocr_engine = args.ocr_engine or config.ocr_engine

    if args.fast or args.enrich:
        logger.warning("--fast / --enrich 已废弃且被忽略（DOM 路线恒定直出；视觉补充未实现），可从脚本里删掉")

    # --url / --image 都可重复：N 个输入 -> N 页（每输入一页，见 归档文档 axure_rp8_plan.md §3.1）。
    # 1 个输入仍是老的单页扁平路径，既有产物形状不变。
    urls = [u for u in (args.url or []) if u]
    images = [p for p in (args.image or []) if p]

    if args.interactive:
        if len(urls) + len(images) > 1:
            parser.error("--interactive 一次只处理一个输入：多输入（重复 --url / --image）"
                         "请去掉 --interactive")
        from src.app.agents.route_select import select_interactive
        sel = select_interactive(
            config, prefill={"url": urls[0] if urls else None,
                             "image": images[0] if images else None,
                             "route": args.route, "tool": tool})
        urls = [sel["url"]] if sel["url"] else []
        images = [sel["image"]] if sel["image"] else []
        args.route = sel["route"]
        tool = sel["tool"]
        # 交互模式下无输入视为用户放弃 -> 退出码 1（不静默跑旧流程）
        if not urls and not images:
            parser.error("交互选择未给出 URL/截图")

    if args.login_state:
        if args.storage_state:
            parser.error("--login-state 与 --storage-state 请分两步使用：先 --login-state 导出登录态，再用 --storage-state 运行")
        if len(urls) != 1:
            parser.error("--login-state 需要且只支持一个 --url（在浏览器里登录的目标页面）")
        from src.app.services.structure.capture import export_login_state
        path = export_login_state(urls[0], args.login_state, config)
        logger.info("登录态已导出：%s", path)
        print(f"\n下一步：对同一 URL 加 --storage-state \"{path}\" 运行，例如：")
        print(f'python -m src.main --url "{urls[0]}" --storage-state "{path}" --route auto --tool svg')
        return 0

    if not urls and not images:
        # --pick-crops 允许不带输入重跑：直接复用输出目录里已有的 11_som.json + 截图
        if args.pick_crops:
            from src.app.agents.precise_agent import PreciseAgent
            agent = PreciseAgent(config)
            agent.rerender(tool=tool, pick_crops=True)
            return 0
        parser.error("必须提供 --url 或 --image")

    try:
        # 多输入（N 个 URL / N 张截图）也走 PreciseAgent：它按 §3.1 组装多页。
        if urls or args.route or len(urls) + len(images) > 1:
            from src.app.agents.precise_agent import PreciseAgent
            agent = PreciseAgent(config)
            route = args.route or config.route_default   # ROUTE 环境变量，默认 auto
            if len(urls) + len(images) > 1:
                agent.run_many(urls=urls, images=images, route=route, tool=tool,
                               pick_crops=args.pick_crops)
            else:
                agent.run(url=urls[0] if urls else None,
                          image=images[0] if images else None,
                          route=route, tool=tool, pick_crops=args.pick_crops)
            return 0

        agent = ReconstructAgent(config)
        agent.run(
            image_path=images[0],
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
