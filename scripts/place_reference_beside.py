# -*- coding: utf-8 -*-
"""Place the reference screenshot beside a pipeline output frame (Phase 0 ④).

Human-review aid only: the image node is appended to the current page NEXT TO
the output frame, never inside it, and is never part of the acceptance export
(export_frame only exports the frame node itself).  The product contract that
blocks visible screenshot underlays is untouched.

Usage:
  python scripts/place_reference_beside.py --image <reference.png> [--frame-id 32:1501]
  # --frame-id omitted: use the newest top-level FRAME on the current page
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GAP = 60


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="reference screenshot path")
    parser.add_argument("--frame-id", default=None, help="pipeline output frame id")
    parser.add_argument("--name", default=None, help="node name for the reference")
    args = parser.parse_args()

    image = Path(args.image).resolve()
    if not image.is_file():
        print(f"[error] image not found: {image}")
        return 2
    png = base64.b64encode(image.read_bytes()).decode("ascii")

    adapter = FigmaBridgeAdapter("ws://localhost:8765")
    adapter.connect()
    try:
        page = adapter._send("get_node_tree", {"depth": 1})
        frames = [
            child
            for child in page.get("children") or []
            if child.get("type") == "FRAME"
        ]
        if args.frame_id:
            target = next((f for f in frames if f.get("id") == args.frame_id), None)
            if target is None:
                print(f"[error] frame {args.frame_id} not found on current page")
                return 2
        else:
            if not frames:
                print("[error] no frames on current page")
                return 2
            target = max(frames, key=lambda f: int(str(f.get("id", "0:0")).split(":")[0]))
        fx = float(target.get("x") or 0)
        fy = float(target.get("y") or 0)
        fw = float(target.get("width") or 0)
        fh = float(target.get("height") or 0)
        name = args.name or f"REFERENCE 评审用 {image.stem[:40]}"
        node_id = adapter._send(
            "create_image",
            {
                "name": name,
                "x": fx + fw + GAP,
                "y": fy,
                "width": fw,
                "height": fh,
                "imageBase64": png,
            },
        )
        print(
            f"[ok] reference placed beside frame {target.get('id')} "
            f"({target.get('name')}) at x={fx + fw + GAP:.0f}, y={fy:.0f} "
            f"({fw:.0f}x{fh:.0f}) -> node {node_id}"
        )
        print("[note] 评审用节点：不会进入 export_frame 导出，禁止移动到输出 frame 内部")
        return 0
    finally:
        adapter.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
