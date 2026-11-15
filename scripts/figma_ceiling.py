# -*- coding: utf-8 -*-
"""S0：Figma 这条路的像素天花板。

把原图整张作为 image fill 写进一个 frame、再从 Figma 原生导出，量它与原图的
`within30`。这是"设计稿完全正确时，Figma 导出最多能有多像原图"的上界：任何
按节点建模的渲染都不可能超过它，因为没有任何矢量节点能比这张图更像这张图。

如果这个数离 100 很远，说明差距出在导出链路（解码、重采样、色彩管理）上，
"Figma 真机 >= 95%" 就要先修链路，而不是继续调设计稿。

    python scripts/figma_ceiling.py AtomGit
    python scripts/figma_ceiling.py AtomGit inventory wecom-modal
    python scripts/figma_ceiling.py AtomGit --keep   # 不删对照 frame
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sample_sources import locate  # noqa: E402
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BRIDGE = "ws://localhost:8765"


def _reference(tag: str) -> tuple[Path, list[int]]:
    reference = json.loads(
        (ROOT / "output" / f"_v2_fit_{tag}" / "pipeline" / "image_reference.json").read_text(
            encoding="utf-8"
        )
    )
    path = locate(tag, (reference.get("input") or {}).get("path"))
    size = [int(value) for value in reference["input"]["size"]]
    return path, size


def _free_spot(page: dict) -> tuple[float, float]:
    """Right of everything on the page: the export frame gets its own space."""
    right = 0.0
    for child in page.get("children") or []:
        try:
            right = max(right, float(child.get("x") or 0) + float(child.get("width") or 0))
        except (TypeError, ValueError):
            continue
    return right + 200.0, 0.0


def ceiling(adapter: FigmaBridgeAdapter, tag: str, keep: bool) -> dict:
    import numpy as np
    from PIL import Image

    picture, (width, height) = _reference(tag)
    page = adapter._send("get_node_tree", {"depth": 1})
    x, y = _free_spot(page)
    frame_id = adapter._send(
        "create_frame",
        {
            "name": f"S0 CEILING {tag}",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "fillColor": "#ffffff",
        },
    )
    adapter._send(
        "create_image",
        {
            "name": f"S0 CEILING {tag} image",
            "parentId": frame_id,
            "x": 0,
            "y": 0,
            "width": width,
            "height": height,
            "imageBase64": base64.b64encode(picture.read_bytes()).decode("ascii"),
        },
    )
    exported = adapter._send("export_frame", {"nodeId": frame_id, "scale": 1})
    out = ROOT / "output" / f"_ceiling_{tag}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(exported["base64"]))

    truth = np.asarray(Image.open(picture).convert("RGB"), dtype=np.int16)
    drawn = np.asarray(Image.open(out).convert("RGB"), dtype=np.int16)
    if truth.shape != drawn.shape:
        return {
            "tag": tag,
            "exported": f"{drawn.shape[1]}x{drawn.shape[0]}",
            "expected": f"{width}x{height}",
            "within30_pct": None,
        }
    distance = np.abs(truth - drawn).max(axis=2)
    result = {
        "tag": tag,
        "exported": f"{drawn.shape[1]}x{drawn.shape[0]}",
        "within30_pct": round(float((distance <= 30).mean()) * 100, 2),
        "within15_pct": round(float((distance <= 15).mean()) * 100, 2),
        "mean_error": round(float(distance.mean()), 2),
        "frameId": frame_id,
    }
    if not keep:
        adapter._send("remove_nodes_by_name", {"name": f"S0 CEILING {tag}"})
        adapter._send("remove_nodes_by_name", {"name": f"S0 CEILING {tag} image"})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tags", nargs="*", default=None)
    parser.add_argument("--keep", action="store_true", help="leave the frames on the page")
    args = parser.parse_args()
    tags = args.tags or ["AtomGit"]

    adapter = FigmaBridgeAdapter(BRIDGE)
    adapter.connect()
    try:
        results = [ceiling(adapter, tag, args.keep) for tag in tags]
    finally:
        adapter.disconnect()

    print(f"{'sample':12s} {'exported':>12s} {'within30':>9s} {'within15':>9s} {'mean err':>9s}")
    for row in results:
        print(
            f"{row['tag']:12s} {row['exported']:>12s} "
            f"{row['within30_pct'] if row['within30_pct'] is not None else '-':>9} "
            f"{row.get('within15_pct', '-'):>9} {row.get('mean_error', '-'):>9}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
