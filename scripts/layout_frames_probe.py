# -*- coding: utf-8 -*-
"""Auto Layout 的落地面探针：一页 → SoM → DesignSpec → 输出端复核 → 统计。

`layout_probe.py` 回答的是「推断器能不能推出来」；这一支回答的是**输出端真的会建多少个
Frame** —— 推得出来不等于建得起来，还要过 `adapter_base.resolve_frames` 那四道关
（绘制序连续 / 子项只落一个节点 / 同一套裁剪 / 重放得回原像素）。

用法（项目根目录）:
    python scripts/layout_frames_probe.py --out output/_layout_probe_tab2
    python scripts/layout_frames_probe.py --out output/_layout_probe_antd --url https://ant.design/

产物：`<out>/layout_frames.json`（逐候选的结论，供下钻）
退出码：0 成功；1 输入缺失。
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2  # noqa: E402

from src.app.services.rendering.adapter_base import (  # noqa: E402
    paint_order, resolve_frames)
from src.app.services.som.direct_design import build_direct_design  # noqa: E402
from src.app.services.structure.graph import (  # noqa: E402
    assign_ids, assign_parent_depth, new_graph)
from src.app.services.structure.providers.base import ProviderContext  # noqa: E402
from src.app.services.structure.providers.dom import DomProvider  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_spec(out: Path, url: str | None) -> tuple[dict, list[dict]]:
    """采集产物 → (som_json, dom_nodes)。走的就是 precise_agent 那条路。"""
    dom_p, shot = out / "00_dom.json", out / "00_screenshot.png"
    if not dom_p.exists() or not shot.exists():
        raise FileNotFoundError("需要 %s 与 %s（先跑 scripts/layout_probe.py）" % (dom_p, shot))
    nodes = json.loads(dom_p.read_text(encoding="utf-8"))
    frame = cv2.imread(str(shot))
    if frame is None:
        raise FileNotFoundError("读不到截图 %s" % shot)
    height, width = frame.shape[:2]
    ctx = ProviderContext(image_path=str(shot), image_w=width, image_h=height,
                          route="dom", output_dir=str(out), dom_path=str(dom_p),
                          url=url)
    graph = DomProvider().run(ctx)
    assign_ids(graph)
    assign_parent_depth(graph)
    graph["provenance"]["fallbacks"] = []
    som = {"image": str(shot), "size": [width, height],
           "containers": graph["containers"], "elements": graph["elements"],
           "provenance": graph["provenance"]}
    return som, nodes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/_layout_probe_tab2")
    ap.add_argument("--url", default=None, help="站点 profile 用（不给就用默认阈值）")
    args = ap.parse_args()

    out = Path(args.out)
    som, dom_nodes = build_spec(out, args.url)
    design = build_direct_design(som, dom_nodes=dom_nodes)
    elements = design["elements"]
    ordered = paint_order(elements)
    reasons: dict[int, str] = {}
    frames = resolve_frames(elements, ordered, reasons)

    candidates = [e for e in elements if isinstance(e.get("layout"), dict)]
    print("节点 %d → DesignSpec %d 个图元；Auto Layout 候选 %d 个"
          % (len(elements), len(design["elements"]), len(candidates)))
    print("真的会建 Frame：%d 个（%s）"
          % (len(frames), design["_meta"].get("autolayout_frames")))
    print("\n按模式：")
    for mode, count in collections.Counter(
            f["layout"]["mode"] for f in frames.values()).most_common():
        print("  %-12s %d" % (mode, count))
    print("\n按推断来源：")
    for src, count in collections.Counter(
            f["layout"].get("source") for f in frames.values()).most_common():
        print("  %-12s %d" % (src, count))
    print("\n没建成的候选（分母 %d）：" % (len(candidates) - len(frames)))
    for why, count in collections.Counter(
            reasons.get(i) for i, _el in enumerate(elements)
            if isinstance(_el.get("layout"), dict) and i not in frames).most_common():
        print("  %-28s %d" % (why, count))

    rows = []
    for i, el in enumerate(elements):
        if not isinstance(el.get("layout"), dict):
            continue
        plan = frames.get(i)
        rows.append({"i": i, "id": el.get("id"), "name": el.get("name"),
                     "rect": [el.get("x"), el.get("y"), el.get("width"),
                              el.get("height")],
                     "layout": el["layout"], "members": len(el["layoutChildren"]),
                     "built": plan is not None, "reason": reasons.get(i),
                     "children": ([{"id": elements[m].get("id"), **ov}
                                   for m, ov in plan["members"]] if plan else [])})
    (out / "layout_frames.json").write_text(
        json.dumps({"built": len(frames), "candidates": rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n明细写入 %s" % (out / "layout_frames.json"))
    if frames:
        print("\n建成的 Frame（前 12 个）：")
        for row in [r for r in rows if r["built"]][:12]:
            print("  %-34s %s %5dx%-5d %2d 个子项 %s" % (
                "%s %s" % (row["id"], (row["name"] or "")[:24]),
                row["layout"]["mode"][:4], row["rect"][2], row["rect"][3],
                row["members"], row["layout"].get("source")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())