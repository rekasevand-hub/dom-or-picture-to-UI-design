#!/usr/bin/env python3
"""只读探针：三版参考窗口的离线 A/B。

不连 Figma、不改产品代码，只在冻结产物上换窗口定义，看参考侧的 `dx/dy/宽高/墨量` 怎么变。

背景
----
`native_text_quality` 里参考与渲染**共用** `measure_box`，而
`measure_box = 发射节点框 + box_pad(4px)`，`_ink_bbox` 又在窗内截断。
于是参考墨迹一旦贴到窗口边就被裁掉——**参考宽度永远不超过我们自己的框**。

三版窗口
--------
A  node + 4px            （现状）
B  node + 0.75em         （交接 §7.3 提的固定 padding）
C  union(source_bbox, node) + 0.75em   （外部评审提的并集）
D  union(source_bbox, node) + 4px      （只换锚点、不换 padding，把两个变量拆开）

判据（按任务要求：不看单条 owner 的翻转）
----------------------------------------
1. 复现性：A 版必须逐条复现 `acceptance.json` 的 deltaX/deltaY，否则本探针的口径就是错的；
2. 贴边率：参考墨迹贴窗口边的比例；
3. 邻居污染：参考墨迹框与**另一个 owner 的节点框**重叠 > 40% 的比例——窗口一宽就吞邻居；
4. 宽度膨胀：参考墨迹宽 / 渲染墨迹宽 的中位数（同一 owner 跨变体的漂移）。

输出
----
`<out>/window_ab.json` 全量明细 + 终端汇总表。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from src.app.services.evidence.native_text_quality import (  # noqa: E402
    _contrast_mask,
    _halo_bbox,
    _ink_bbox,
    _mask_edge_f1,
)

FAMILIES: list[tuple[str, str]] = [
    ("content-review", "output/_benchmark_families/rerun/content-review"),
    ("atomgit-home", "output/_benchmark_families/rerun/atomgit-home"),
    ("dark-card-grid", "output/_baseline_families_rerun_20261113/dark-card-grid"),
    ("light-form", "output/_baseline_families_rerun_20261113/light-form"),
    ("light-table", "output/_baseline_families_rerun_20261113/light-table"),
]

VARIANTS = ("A", "B", "C", "D")


def _union(a: list[int], b: list[int]) -> list[int]:
    x1 = min(a[0], b[0])
    y1 = min(a[1], b[1])
    x2 = max(a[0] + a[2], b[0] + b[2])
    y2 = max(a[1] + a[3], b[1] + b[3])
    return [x1, y1, x2 - x1, y2 - y1]


def _shrink(box: list[int], pad: int) -> list[int]:
    return [
        box[0] + pad,
        box[1] + pad,
        max(1, box[2] - 2 * pad),
        max(1, box[3] - 2 * pad),
    ]


def _overlap_ratio(inner: list[int], outer: list[int]) -> float:
    ox = max(0, min(inner[0] + inner[2], outer[0] + outer[2]) - max(inner[0], outer[0]))
    oy = max(0, min(inner[1] + inner[3], outer[1] + outer[3]) - max(inner[1], outer[1]))
    area = inner[2] * inner[3]
    return (ox * oy) / area if area else 0.0


def _touches(ink: list[int], win: list[int]) -> dict[str, bool]:
    return {
        "left": ink[0] <= win[0],
        "right": ink[0] + ink[2] >= win[0] + win[2],
        "top": ink[1] <= win[1],
        "bottom": ink[1] + ink[3] >= win[1] + win[3],
    }


def _measure(
    reference: np.ndarray,
    rendered: np.ndarray,
    window: list[int],
    halo_px: int,
) -> dict | None:
    wx, wy, ww, wh = window
    ref_mask = _contrast_mask(reference[wy : wy + wh, wx : wx + ww])
    ren_mask = _contrast_mask(rendered[wy : wy + wh, wx : wx + ww])
    ref_ink = _ink_bbox(ref_mask, window)
    ren_ink = _ink_bbox(ren_mask, window)
    if ref_ink is None or ren_ink is None:
        return {"missing": "reference-ink" if ref_ink is None else "rendered-ink"}
    support = _halo_bbox(ref_ink, halo_px, reference.shape[:2])
    coverage = None
    edge_f1 = None
    if support is not None:
        sx, sy, sw, sh = support
        s_ref = _contrast_mask(reference[sy : sy + sh, sx : sx + sw])
        s_ren = _contrast_mask(rendered[sy : sy + sh, sx : sx + sw])
        s_ref_ink = _ink_bbox(s_ref, support)
        s_ren_ink = _ink_bbox(s_ren, support)
        ref_px = int(s_ref.sum())
        coverage = float(s_ren.sum()) / ref_px if ref_px else None
        if s_ref_ink and s_ren_ink:
            edge_f1 = _mask_edge_f1(s_ref, s_ren, s_ref_ink, s_ren_ink, (sx, sy))
    return {
        "window": window,
        "referenceInk": ref_ink,
        "renderedInk": ren_ink,
        "deltaX": ren_ink[0] - ref_ink[0],
        "deltaY": ren_ink[1] - ref_ink[1],
        "widthDelta": ren_ink[2] - ref_ink[2],
        "heightDelta": ren_ink[3] - ref_ink[3],
        "inkCoverageRatio": coverage,
        "edgeF1": edge_f1,
        "touches": _touches(ref_ink, window),
    }


def _family_rows(name: str, run_dir: Path) -> tuple[list[dict], dict]:
    acceptance = json.loads((run_dir / "acceptance.json").read_text(encoding="utf-8"))
    quality = acceptance["native_text_quality"]
    owners = quality["owners"]
    design = json.loads((run_dir / "figma_design.json").read_text(encoding="utf-8"))
    elements = {
        element.get("contentRef"): element
        for element in design.get("elements") or []
        if element.get("contentRef")
    }
    pad = int(quality.get("boxPadPx") or 4)
    halo = int(quality.get("haloPx") or 2)
    export_rel = (acceptance.get("artifacts") or {}).get("export")
    exported = (
        run_dir / export_rel
        if export_rel
        else run_dir / "figma_positioned" / "export.png"
    )
    reference_path = (
        ROOT / "tests" / "fixtures" / "benchmark_families" / name / "reference.png"
    )
    with Image.open(reference_path) as source:
        reference = np.asarray(source.convert("RGB"), dtype=np.int16)
    with Image.open(exported) as source:
        rendered = np.asarray(source.convert("RGB"), dtype=np.int16)

    # 每个 owner 的节点框（窗口减掉 pad），用来做「邻居污染」判定
    node_boxes: dict[str, list[int]] = {}
    for owner in owners:
        if owner.get("measureBBox"):
            node_boxes[owner.get("contentRef") or owner.get("text") or ""] = _shrink(
                owner["measureBBox"], pad
            )

    rows: list[dict] = []
    for owner in owners:
        box = owner.get("measureBBox")
        ref_ink = owner.get("referenceInkBBox")
        if not box or not ref_ink:
            continue
        key = owner.get("contentRef") or owner.get("text") or ""
        element = elements.get(owner.get("contentRef")) or {}
        style = element.get("style") or {}
        font_size = float(style.get("fontSize") or 0) or 16.0
        source_bbox = ((element.get("styleEvidence") or {}).get("evidence") or {}).get(
            "source_bbox"
        )
        node_box = _shrink(box, pad)
        em = max(2, int(round(0.75 * font_size)))
        windows = {
            "A": _halo_bbox(node_box, pad, reference.shape[:2]),
            "B": _halo_bbox(node_box, em, reference.shape[:2]),
            "C": _halo_bbox(
                _union(node_box, source_bbox) if source_bbox else node_box,
                em,
                reference.shape[:2],
            ),
            # 只换锚点、不换 padding：把「并集」和「0.75em」两个变量分开
            "D": _halo_bbox(
                _union(node_box, source_bbox) if source_bbox else node_box,
                pad,
                reference.shape[:2],
            ),
        }
        others = [value for other_key, value in node_boxes.items() if other_key != key]
        for variant in VARIANTS:
            window = windows[variant]
            if window is None:
                continue
            measured = _measure(reference, rendered, window, halo)
            row = {
                "family": name,
                "owner": owner.get("text"),
                "contentRef": owner.get("contentRef"),
                "type": owner.get("type"),
                "scope": owner.get("ownerScope"),
                "variant": variant,
                "fontSize": font_size,
                "nodeBox": node_box,
                "sourceBBox": source_bbox,
                **(measured or {}),
            }
            if measured and not measured.get("missing"):
                ink = measured["referenceInk"]
                row["neighbour"] = max(
                    (_overlap_ratio(ink, other) for other in others), default=0.0
                )
                row["reportedDeltaX"] = owner.get("deltaX")
                row["reportedDeltaY"] = owner.get("deltaY")
                row["reportedRefWidth"] = ref_ink[2]
            rows.append(row)
    return rows, {"owners": len(owners), "export": str(exported)}


def _summarise(rows: list[dict], name: str, variant: str) -> dict:
    picked = [
        row
        for row in rows
        if row["family"] == name
        and row["variant"] == variant
        and not row.get("missing")
    ]
    if not picked:
        return {"n": 0}
    dx = [row["deltaX"] for row in picked]
    dy = [row["deltaY"] for row in picked]
    clip_any = sum(1 for row in picked if any(row["touches"].values()))
    clip_lr = sum(
        1 for row in picked if row["touches"]["left"] or row["touches"]["right"]
    )
    cover = [
        row["inkCoverageRatio"] for row in picked if row["inkCoverageRatio"] is not None
    ]
    edge = [row["edgeF1"] for row in picked if row["edgeF1"] is not None]
    width_ratio = [
        row["referenceInk"][2] / row["renderedInk"][2]
        for row in picked
        if row["renderedInk"][2]
    ]
    return {
        "n": len(picked),
        "clipAny": clip_any / len(picked),
        "clipLR": clip_lr / len(picked),
        "dxMedian": statistics.median(dx),
        "dxStdev": round(statistics.pstdev(dx), 2),
        "absDxMedian": statistics.median([abs(value) for value in dx]),
        "dyMedian": statistics.median(dy),
        "absDyMedian": statistics.median([abs(value) for value in dy]),
        "coveragePass": sum(1 for value in cover if 0.75 <= value <= 1.35)
        / len(picked),
        "edgePass": sum(1 for value in edge if value >= 0.55) / len(picked),
        "refWidthRatioMedian": statistics.median(width_ratio),
        "neighbourMedian": statistics.median([row["neighbour"] for row in picked]),
        "neighbourGt40": sum(1 for row in picked if row["neighbour"] > 0.40)
        / len(picked),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="output/_window_ab")
    parser.add_argument("--family", action="append", default=None)
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted = set(args.family or [name for name, _ in FAMILIES])

    all_rows: list[dict] = []
    report: dict[str, dict] = {}
    for name, relative in FAMILIES:
        if name not in wanted:
            continue
        run_dir = ROOT / relative
        if not (run_dir / "acceptance.json").exists():
            print(f"[skip] {name}: 缺 {run_dir}/acceptance.json")
            continue
        rows, meta = _family_rows(name, run_dir)
        all_rows.extend(rows)
        report[name] = {"meta": meta, "variants": {}}
        for variant in VARIANTS:
            report[name]["variants"][variant] = _summarise(rows, name, variant)

    # 复现性：A 版 vs 报告里的 deltaX/deltaY
    base = [
        row
        for row in all_rows
        if row["variant"] == "A"
        and not row.get("missing")
        and row.get("reportedDeltaX") is not None
    ]
    exact = sum(
        1
        for row in base
        if row["deltaX"] == row["reportedDeltaX"]
        and row["deltaY"] == row["reportedDeltaY"]
    )
    report["_reproduction"] = {
        "baselineOwners": len(base),
        "exactDeltaMatch": exact,
        "exactRate": round(exact / len(base), 4) if base else None,
    }

    (out / "window_ab.json").write_text(
        json.dumps({"summary": report, "rows": all_rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    print(
        f"复现性：A 版 {exact}/{len(base)} 条与 acceptance.json 的 deltaX/deltaY 逐位一致"
        f"（{report['_reproduction']['exactRate']:.1%}）"
    )
    header = (
        f"{'族':16s}{'版':3s}{'n':>4}{'贴边':>7}{'左右贴边':>9}"
        f"{'|dx|中位':>10}{'dx标差':>8}{'|dy|中位':>9}"
        f"{'coverage过':>11}{'edge过':>8}{'参考/渲染宽':>12}{'吞邻居>40%':>11}"
    )
    print(header)
    for name, _ in FAMILIES:
        if name not in report:
            continue
        for variant in VARIANTS:
            item = report[name]["variants"][variant]
            if not item.get("n"):
                continue
            print(
                f"{name:16s}{variant:3s}{item['n']:>4}"
                f"{item['clipAny']:>7.0%}{item['clipLR']:>9.0%}"
                f"{item['absDxMedian']:>10.1f}{item['dxStdev']:>8.2f}{item['absDyMedian']:>9.1f}"
                f"{item['coveragePass']:>11.0%}{item['edgePass']:>8.0%}"
                f"{item['refWidthRatioMedian']:>12.2f}{item['neighbourGt40']:>11.0%}"
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
