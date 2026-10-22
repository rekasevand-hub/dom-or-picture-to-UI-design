# -*- coding: utf-8 -*-
"""布局升级面探针：一页 → 重建容器树 → 跑 Auto Layout 推断 → 出统计。

回答的是「把扁平稿变回 Auto Layout，升级面到底有多大」这个问题（见
`归档文档 figma_layout_upgrade_audit.md` §7 第一步）：**不碰任何输出端**，只做
「采集 → 推断 → 统计」。

用法（项目根目录）:
    python scripts/layout_probe.py --url https://www.dushu.com/ --out output/_layout_probe
    python scripts/layout_probe.py --dom output/_layout_probe/00_dom.json    # 复用已有采集

产物：`<out>/00_dom.json`（带布局字段的全新采集，**不会覆盖老基线目录**）
      `<out>/layout_probe.json`（逐容器的推断结果，供下钻）
退出码：0 成功；1 输入缺失。
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.rendering import layout_infer as li  # noqa: E402
from src.app.services.structure.capture import capture_page  # noqa: E402
from src.config.settings import load_config  # noqa: E402

# Windows 控制台默认 GBK，bail 原因里可能有非 ASCII
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_tree(nodes: list[dict]) -> list[list[int]]:
    """按 `pIdx`（最近的已采集祖先下标）建 children 表。"""
    kids: list[list[int]] = [[] for _ in nodes]
    for i, node in enumerate(nodes):
        parent = node.get("pIdx")
        if isinstance(parent, int) and 0 <= parent < len(nodes) and parent != i:
            kids[parent].append(i)
    return kids


def probe(nodes: list[dict]) -> dict:
    """逐容器跑推断；同时记下「有多少流内子元素」——那才是升级面的真实分母。"""
    kids = build_tree(nodes)
    results = []
    for i, node in enumerate(nodes):
        if not kids[i]:
            continue
        parent = nodes[node["pIdx"]] if isinstance(node.get("pIdx"), int) \
            and 0 <= node["pIdx"] < len(nodes) else None
        child_nodes = [nodes[j] for j in kids[i]]
        flow = [c for c in child_nodes
                if str(c.get("position") or "static") not in ("absolute", "fixed")]
        got = li.infer_container(node, child_nodes, parent)
        results.append({
            "i": i,
            "tag": node.get("tag"),
            "cls": (node.get("clsAll") or "")[:40],
            "rect": [node.get("x"), node.get("y"), node.get("w"), node.get("h")],
            "display": node.get("display") or "block",
            "children": len(kids[i]),
            "flow": len(flow),
            "depth": _depth(nodes, i),
            "layout": got["layout"],
            "bail": got["bail"],
            "detail": got.get("detail"),
            "source": (got["layout"] or {}).get("source"),
            "overrides": got["children"],
        })
    return {"containers": results, "nodes": len(nodes)}


def _depth(nodes: list[dict], i: int, limit: int = 64) -> int:
    depth = 0
    cur = i
    while depth < limit:
        parent = nodes[cur].get("pIdx")
        if not isinstance(parent, int) or not (0 <= parent < len(nodes)) \
                or parent == cur:
            break
        cur = parent
        depth += 1
    return depth


def report(data: dict) -> None:
    rows = data["containers"]
    # 升级面的真实分母：**有 ≥2 个流内子元素**的容器。只有一个流内子元素的容器
    # 做成 stack 毫无意义（它本来就只有一个东西要摆），把它们算进分母会把比例撑大。
    multi = [r for r in rows if r["flow"] >= 2]
    ok = [r for r in multi if r["layout"]]
    print("节点 %d 个；有子元素的容器候选 %d 个" % (data["nodes"], len(rows)))
    print("  ├ 全是绝对定位子元素        %d" % sum(1 for r in rows if r["flow"] == 0))
    print("  ├ 只有 1 个流内子元素        %d（做成 stack 无意义，不计入分母）"
          % sum(1 for r in rows if r["flow"] == 1))
    print("  └ ≥2 个流内子元素（分母）    %d" % len(multi))
    print("在分母里：推断成功 %d（%.0f%%）；其中 CSS 路径 %d / 几何兜底 %d"
          % (len(ok), 100.0 * len(ok) / max(1, len(multi)),
             sum(1 for r in ok if r["source"] == "css"),
             sum(1 for r in ok if r["source"] == "geometry")))

    print("\n按来源 × 模式：")
    for (src, mode), count in collections.Counter(
            (r["source"], r["layout"]["mode"]) for r in ok).most_common():
        print("  %-10s %-12s %d" % (src, mode, count))

    print("\n子树规模（推断成功）：")
    for lo, hi, label in ((2, 2, "2 个子元素"), (3, 5, "3-5 个"), (6, 10, "6-10 个"),
                          (11, 10 ** 9, "11+ 个")):
        print("  %-12s %d" % (label, sum(1 for r in ok if lo <= r["flow"] <= hi)))

    bails = collections.Counter(r["detail"] or r["bail"]
                               for r in multi if not r["layout"])
    print("\n拒绝原因（分母里 %d 个没做成）：" % sum(bails.values()))
    for reason, count in bails.most_common():
        print("  %-56s %d" % (reason, count))

    over = collections.Counter()
    for r in ok:
        for item in r["overrides"]:
            key = "grow" if "grow" in item else (
                "stretch" if item.get("alignSelf") == "STRETCH" else "absolute")
            over[key] += 1
    print("\n子项覆盖项：%s" % dict(over))

    big = sorted((r for r in multi if not r["layout"]),
                 key=lambda r: -(r["rect"][2] * r["rect"][3]))[:8]
    print("\n被拒的最大容器（值得逐个人工看）：")
    for r in big:
        print("  %-34s %5dx%-5d %2d 个流内子元素  %s" % (
            "%-8s %s" % (r["tag"], r["cls"][:24]), r["rect"][2], r["rect"][3],
            r["flow"], r["detail"] or r["bail"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://www.dushu.com/")
    ap.add_argument("--out", default="output/_layout_probe")
    ap.add_argument("--dom", default=None, help="直接读已有的 00_dom.json（不重采）")
    args = ap.parse_args()

    out = Path(args.out)
    if args.dom:
        dom_p = Path(args.dom)
        if not dom_p.exists():
            print("[FAIL] 读不到 %s" % dom_p)
            return 1
    else:
        cfg = load_config()
        print("采集 %s ..." % args.url)
        info = capture_page(args.url, cfg, str(out))
        dom_p = Path(info["dom"])
        print("画布 %dx%d → %s" % (info["width"], info["height"], dom_p))

    nodes = json.loads(dom_p.read_text(encoding="utf-8"))
    data = probe(nodes)
    data["source"] = str(dom_p)
    report(data)
    out.mkdir(parents=True, exist_ok=True)
    (out / "layout_probe.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n明细写入 %s" % (out / "layout_probe.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
