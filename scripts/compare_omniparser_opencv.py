"""
对比 OmniParser 与 OpenCV 两种特征提取效果。

用法：
    python scripts/compare_omniparser_opencv.py --image uploads/test01.png --output output/compare

输出：
    - compare/opencv_overlay.png      OpenCV 检测框叠加图
    - compare/omniparser_overlay.png  OmniParser 检测框叠加图
    - compare/report.txt              数量/类型统计对比
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.app.models.component import Component
from src.app.services.detection import detect_components, detect_components_with_omniparser
from src.app.services.detection.omniparser_client import OmniParserClient
from src.app.utils.image_utils import draw_debug_overlay, load_image, save_image
from src.config import Config

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("compare")


def _count_by_type(components: list[Component]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in components:
        counts[c.comp_type] = counts.get(c.comp_type, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def _draw_omniparser_overlay(frame: np.ndarray, components: list[Component]) -> np.ndarray:
    """为 OmniParser 结果单独绘制标签（保留 content 描述）。"""
    out = frame.copy()
    colors = {
        "button": (0, 128, 255),
        "text": (255, 255, 0),
        "input": (0, 255, 0),
        "image": (255, 0, 255),
        "container": (128, 128, 128),
        "avatar": (0, 255, 255),
        "divider": (0, 0, 255),
        "unknown": (200, 200, 200),
    }
    for comp in components:
        x, y, w, h = comp.bbox
        color = colors.get(comp.comp_type, (200, 200, 200))
        cv2.rectangle(out, (x, y), (x + w, y + h), color, 2)
        label = f"{comp.id}:{comp.comp_type}"
        if comp.text:
            label += f" {comp.text[:15]}"
        elif comp.meta.get("omniparser_content"):
            label += f" {str(comp.meta['omniparser_content'])[:15]}"
        cv2.putText(out, label, (x, max(y - 5, 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare OmniParser vs OpenCV detection")
    parser.add_argument("--image", required=True, help="输入图片路径")
    parser.add_argument("--output", default="output/compare", help="对比结果输出目录")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="OmniParser 服务地址")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载图片
    logger.info(f"加载图片: {args.image}")
    frame = load_image(args.image)
    img_h, img_w = frame.shape[:2]
    logger.info(f"图片尺寸: {img_w}x{img_h}")

    # 1. OpenCV 方案
    logger.info("\n[OpenCV] 开始检测...")
    opencv_components = detect_components(frame)
    logger.info(f"[OpenCV] 检出 {len(opencv_components)} 个组件")
    opencv_overlay = draw_debug_overlay(frame, opencv_components)
    save_image(opencv_overlay, output_dir / "opencv_overlay.png")

    # 2. OmniParser 方案
    logger.info("\n[OmniParser] 开始检测...")
    config = Config(
        omniparser_enabled=True,
        omniparser_url=args.url,
        omniparser_timeout=120,
        omniparser_box_threshold=0.05,
        omniparser_iou_threshold=0.7,
        omniparser_use_paddleocr=False,
        omniparser_fallback=False,
    )
    client = OmniParserClient.from_config(config)
    try:
        omni_components = detect_components_with_omniparser(frame, client)
    except Exception as exc:
        logger.error(f"[OmniParser] 调用失败: {exc}")
        logger.error("请确认 OmniParser 服务已启动: python -m src.app.services.omniparser.omniparser_server ...")
        return 1

    logger.info(f"[OmniParser] 检出 {len(omni_components)} 个组件")
    omni_overlay = _draw_omniparser_overlay(frame, omni_components)
    save_image(omni_overlay, output_dir / "omniparser_overlay.png")

    # 3. 生成对比报告
    report_lines = [
        "=" * 50,
        "OmniParser vs OpenCV 对比报告",
        "=" * 50,
        f"图片: {args.image}",
        f"尺寸: {img_w}x{img_h}",
        "",
        f"OpenCV 检出总数:    {len(opencv_components)}",
        f"OmniParser 检出总数: {len(omni_components)}",
        "",
        "OpenCV 类型分布:",
        json.dumps(_count_by_type(opencv_components), ensure_ascii=False, indent=2),
        "",
        "OmniParser 类型分布:",
        json.dumps(_count_by_type(omni_components), ensure_ascii=False, indent=2),
        "",
        "输出文件:",
        f"  - {output_dir / 'opencv_overlay.png'}",
        f"  - {output_dir / 'omniparser_overlay.png'}",
        "=" * 50,
    ]
    report = "\n".join(report_lines)
    print("\n" + report)

    (output_dir / "report.txt").write_text(report, encoding="utf-8")
    logger.info(f"\n报告已保存: {output_dir / 'report.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
