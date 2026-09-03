"""
从 JSON 文件读取 DesignSpec 并渲染到指定原型工具。

用法：
    python scripts/render_design.py --design output/manual_design.json --tool figma
    python scripts/render_design.py --design output/manual_design.json --tool svg
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app.services.rendering import build_adapter
from src.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Render DesignSpec JSON to prototype tool")
    parser.add_argument("--design", required=True, help="DesignSpec JSON 文件路径")
    parser.add_argument("--tool", default="figma", choices=["svg", "figma"], help="原型工具")
    args = parser.parse_args()

    design_path = Path(args.design)
    if not design_path.exists():
        print(f"文件不存在: {design_path}")
        return 1

    with open(design_path, encoding="utf-8") as f:
        design = json.load(f)

    config = load_config()
    adapter = build_adapter(args.tool, config)
    adapter.connect()
    adapter.render_design(design)
    print(f"已渲染 {len(design.get('elements', []))} 个元素到 {args.tool}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
