#!/usr/bin/env python3
"""只读探针：参考侧的墨迹归属。

问题
----
门禁把「参考图」和「渲染图」都裁在 ``节点框 + 4px`` 里量。于是：
* 文本框贴得紧时，参考文本被窗口裁掉（34% 的 owner 贴边，85% 的 size 失败在贴边上）；
* 窗口里混进图标/箭头/邻居的墨时，``deltaX`` / ``widthDelta`` 量的是它们
  （``系统运行正常`` 的绿点让 ``dx`` 假报 0，实际文本压上去 13px）。

今天试过并否掉的四条：调 padding、并集、`box_pad=0`、把兄弟图标框从掩码里清掉
（详见 ``docs/v2_mentor/20261113_window_ab.md``）。它们的共同点是**只改了窗口，没改"哪块墨属于谁"**。

本探针的做法
------------
先放大窗口拿到候选墨，再**按列投影聚类**，只保留「与节点框重叠最多的那一段 run」：

    window(variant) -> contrast mask -> 列投影 -> 1D 连通 run（间隔 ≥ 0.35em 断开）
                    -> 选与节点框重叠最大的 run -> 取该 run 的墨迹框

变体
----
* ``W0`` 现状：节点框 + 4px，不聚类（基线，必须与 `acceptance.json` 逐位一致）
* ``W1`` 节点框 + 4px + 聚类（只解图标污染，不解裁断）
* ``W2`` union(source_bbox, 节点框) + 4px + 聚类（先放大再选）
* ``W3`` 节点框 + 1.5em + 聚类

判据（先定死，再跑）
--------------------
1. **真值**：三个已知样例必须在 ±2px 内还原
   （`系统运行正常` 参考文本 [1632,90,110,17]，按颜色分离实测）；
2. **贴边率**：108 个横向贴边的 owner 里 ≥50% 变成不贴边；
3. **回归**：本来就量得对的 owner（如 `AtomCode` 77 宽）不许被改坏。

只读：不写任何产物、不连 Figma。用法::

    python scripts/ink_ownership_probe.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from src.app.services.evidence.native_text_quality import (  # noqa: E402
    _clip_sides,
    _contrast_mask,
    _halo_bbox,
    _ink_bbox,
)

FAMILIES: list[tuple[str, str]] = [
    ("content-review", "output/_benchmark_families/rerun/content-review"),
    ("atomgit-home", "output/_benchmark_families/rerun/atomgit-home"),
    ("dark-card-grid", "output/_baseline_families_rerun_20261113/dark-card-grid"),
    ("light-form", "output/_baseline_families_rerun_20261113/light-form"),
    ("light-table", "output/_baseline_families_rerun_20261113/light-table"),
]

GAP_EM = 0.35
# 拉丁文的词间距约 0.3–0.7em，用 CJK 的 0.35em 会把一个词切成两段
# （`CONTENT SECURITY` 实测被切成 108 + 109）。按脚本分阈值，数据里本来就有 `script`。
GAP_EM_LATIN = 1.0
VARIANTS = ("W0", "W1", "W2", "W3", "W4", "W5", "W6")

# 真值：按颜色分离（绿点 vs 蓝字）实测，见 20261113_owner_attribution.md
TRUTH = {
    ("content-review", "系统运行正常"): [1632, 90, 110, 17],
}


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


def _runs(mask: np.ndarray, gap_px: int) -> list[list[int]]:
    """列投影后按间隔切 run，返回 [[x0, x1], ...]（窗口内相对坐标，含端点）。"""
    columns = mask.any(axis=0)
    runs: list[list[int]] = []
    start: int | None = None
    blanks = 0
    for index, ink in enumerate(columns):
        if ink:
            if start is None:
                start = index
            blanks = 0
        elif start is not None:
            blanks += 1
            if blanks > gap_px:
                runs.append([start, index - blanks])
                start = None
                blanks = 0
    if start is not None:
        runs.append([start, len(columns) - 1 - blanks])
    return runs


def _pick_run(runs: list[list[int]], window: list[int], node: list[int]) -> list[int] | None:
    """与节点框重叠最大的 run；没有重叠就取中心最近的那个。"""
    if not runs:
        return None
    nx, nw = node[0], node[2]
    best = None
    best_key = None
    for x0, x1 in runs:
        rx0, rx1 = window[0] + x0, window[0] + x1
        overlap = min(rx1 + 1, nx + nw) - max(rx0, nx)
        distance = abs((rx0 + rx1) / 2 - (nx + nw / 2))
        key = (-max(0, overlap), distance)
        if best_key is None or key < best_key:
            best_key, best = key, [x0, x1]
    return best


def _keep_runs(
    runs: list[list[int]], window: list[int], node: list[int], min_inside: float = 0.5
) -> list[int] | None:
    """保留「至少一半宽度落在节点框里」的 run，并合并。

    节点框是我们自己发射的位置，是最可靠的先验：框内的墨很可能属于这条文本，
    框外的整段（图标、箭头、邻居标签）不属于。多词串会拆成多个 run，但它们都在框内，
    合并后就是整串；所以这条规则同时解决「切错」和「吞邻居」。
    """
    if not runs:
        return None
    nx0, nx1 = node[0], node[0] + node[2]
    kept = []
    for x0, x1 in runs:
        rx0, rx1 = window[0] + x0, window[0] + x1
        inside = min(rx1 + 1, nx1) - max(rx0, nx0)
        width = rx1 - rx0 + 1
        if width > 0 and inside / width >= min_inside:
            kept.append([x0, x1])
    if not kept:
        return _pick_run(runs, window, node)
    return [min(run[0] for run in kept), max(run[1] for run in kept)]


def _measure(
    reference: np.ndarray,
    window: list[int],
    node: list[int],
    em: float,
    cluster: bool,
    prior: bool = False,
    gap_em: float = GAP_EM,
) -> list[int] | None:
    wx, wy, ww, wh = window
    mask = _contrast_mask(reference[wy : wy + wh, wx : wx + ww])
    if not cluster:
        return _ink_bbox(mask, window)
    runs = _runs(mask, max(2, int(round(gap_em * em))))
    picked = _keep_runs(runs, window, node) if prior else _pick_run(runs, window, node)
    if picked is None:
        return None
    x0, x1 = picked
    sub = mask[:, x0 : x1 + 1]
    rows = np.where(sub.any(axis=1))[0]
    if len(rows) == 0:
        return None
    return [wx + x0, wy + int(rows.min()), x1 - x0 + 1, int(rows.max() - rows.min()) + 1]


def _family(name: str, run_dir: Path) -> tuple[list[dict], dict]:
    acceptance = json.loads((run_dir / "acceptance.json").read_text(encoding="utf-8"))
    quality = acceptance["native_text_quality"]
    design = json.loads((run_dir / "figma_design.json").read_text(encoding="utf-8"))
    elements = {
        item.get("contentRef"): item
        for item in design.get("elements") or []
        if item.get("contentRef")
    }
    pad = int(quality.get("boxPadPx") or 4)
    export = run_dir / (acceptance.get("artifacts") or {}).get("export", "")
    with Image.open(ROOT / "tests" / "fixtures" / "benchmark_families" / name / "reference.png") as source:
        reference = np.asarray(source.convert("RGB"), dtype=np.int16)
    with Image.open(export) as source:
        rendered = np.asarray(source.convert("RGB"), dtype=np.int16)
    shape = reference.shape[:2]

    rows: list[dict] = []
    for owner in quality["owners"]:
        window0 = owner.get("measureBBox")
        if not window0:
            continue
        element = elements.get(owner.get("contentRef")) or {}
        style = element.get("style") or {}
        em = float(style.get("fontSize") or 16.0)
        node = _shrink(window0, pad)
        evidence = (element.get("styleEvidence") or {}).get("evidence") or {}
        source_bbox = evidence.get("source_bbox")
        gap_em = GAP_EM_LATIN if str(evidence.get("script") or "").lower() == "latin" else GAP_EM
        em_px = max(2, int(round(1.5 * em)))
        windows = {
            "W0": window0,
            "W1": window0,
            "W2": _halo_bbox(
                _union(node, source_bbox) if source_bbox else node, pad, shape
            ),
            "W3": _halo_bbox(node, em_px, shape),
            "W4": _halo_bbox(
                _union(node, source_bbox) if source_bbox else node, pad, shape
            ),
            "W5": _halo_bbox(
                _union(node, source_bbox) if source_bbox else node, pad, shape
            ),
            "W6": _halo_bbox(
                _union(node, source_bbox) if source_bbox else node, pad, shape
            ),
        }
        measured = {
            "W0": _measure(reference, window0, node, em, False),
            "W1": _measure(reference, window0, node, em, True),
            "W2": _measure(reference, windows["W2"], node, em, True) if windows["W2"] else None,
            "W3": _measure(reference, windows["W3"], node, em, True) if windows["W3"] else None,
            "W4": _measure(reference, windows["W4"], node, em, True, prior=True)
            if windows["W4"]
            else None,
            "W5": _measure(
                reference, windows["W5"], node, em, True, prior=True, gap_em=gap_em
            )
            if windows["W5"]
            else None,
            # W6：只改参考侧（归属选择），渲染侧沿用现状口径
            "W6": _measure(
                reference, windows["W6"], node, em, True, prior=True, gap_em=gap_em
            )
            if windows["W6"]
            else None,
        }
        rendered_ink = {
            "W0": _measure(rendered, window0, node, em, False),
            "W1": _measure(rendered, window0, node, em, True),
            "W2": _measure(rendered, windows["W2"], node, em, True) if windows["W2"] else None,
            "W3": _measure(rendered, windows["W3"], node, em, True) if windows["W3"] else None,
            "W4": _measure(rendered, windows["W4"], node, em, True, prior=True)
            if windows["W4"]
            else None,
            "W5": _measure(
                rendered, windows["W5"], node, em, True, prior=True, gap_em=gap_em
            )
            if windows["W5"]
            else None,
            "W6": _measure(rendered, window0, node, em, False),
        }
        rows.append(
            {
                "owner": owner.get("text"),
                "contentRef": owner.get("contentRef"),
                "scope": owner.get("ownerScope"),
                "status": owner.get("status"),
                "checks": owner.get("checks"),
                "node": node,
                "windows": {key: value for key, value in windows.items() if value},
                "old": owner.get("referenceInkBBox"),
                "oldSides": _clip_sides(owner["referenceInkBBox"], window0)
                if owner.get("referenceInkBBox")
                else [],
                "measured": measured,
                "rendered": rendered_ink,
            }
        )
    return rows, {"export": str(export)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="output/_ink_ownership")
    args = parser.parse_args(argv)

    all_rows: list[dict] = []
    per_family: dict[str, list[dict]] = {}
    for name, relative in FAMILIES:
        run_dir = ROOT / relative
        if not (run_dir / "acceptance.json").exists():
            print(f"[skip] {name}")
            continue
        rows, _ = _family(name, run_dir)
        for row in rows:
            row["family"] = name
        all_rows.extend(rows)
        per_family[name] = rows

    # 1) 真值
    print("== 判据 1：真值还原（±2px）==")
    for (family, text), expected in TRUTH.items():
        row = next(r for r in all_rows if r["family"] == family and r["owner"] == text)
        print(f"  {family} / {text}")
        print(f"    期望 {expected}")
        print(f"    现状 {row['old']}  sides={row['oldSides']}")
        for variant in VARIANTS:
            got = row["measured"].get(variant)
            diff = None
            if got:
                diff = max(abs(got[i] - expected[i]) for i in range(4))
            print(f"    {variant}  {got}  maxΔ={diff}")

    # 2) 贴边率 + 复现
    print("\n== 判据 2：横向贴边与复现 ==")
    header = f"{'族':16s}{'owner':>6}{'原贴边':>8}" + "".join(f"{v:>8}" for v in VARIANTS)
    print(header)
    totals = {v: [0, 0] for v in VARIANTS}
    grand = [0, 0]
    for name, rows in per_family.items():
        base = [r for r in rows if r["oldSides"] and ("left" in r["oldSides"] or "right" in r["oldSides"])]
        grand[0] += len(rows)
        grand[1] += len(base)
        line = f"{name:16s}{len(rows):>6}{len(base):>8}"
        for variant in VARIANTS:
            still = 0
            for row in base:
                got = row["measured"].get(variant)
                win = (row["windows"] or {}).get(variant)
                if got is None or win is None:
                    still += 1  # 量不出来，等同于仍不可测
                    continue
                sides = _clip_sides(got, win)
                if "left" in sides or "right" in sides:
                    still += 1
            totals[variant][0] += still
            totals[variant][1] += len(base)
            line += f"{still:>8}"
        print(line)
    print(f"{'合计':16s}{grand[0]:>6}{grand[1]:>8}" + "".join(
        f"{totals[v][0]:>8}" for v in VARIANTS
    ))
    print("（表内数字 = 在新方案下仍然「被自己的窗口横向裁断或量不出」的条数，越小越好）")

    # 3) 回归：本来就不贴边的 owner，宽度被改动了多少
    print("\n== 判据 3：未贴边 owner 的宽度漂移 ==")
    for variant in VARIANTS[1:]:
        drift = []
        for row in all_rows:
            if row["oldSides"] and ("left" in row["oldSides"] or "right" in row["oldSides"]):
                continue
            got = row["measured"].get(variant)
            if not got or not row["old"]:
                continue
            drift.append(abs(got[2] - row["old"][2]))
        drift.sort()
        if drift:
            mid = drift[len(drift) // 2]
            print(
                f"  {variant}: n={len(drift)}  |Δwidth| 中位 {mid}px  "
                f"90分位 {drift[int(len(drift) * 0.9)]}px"
            )

    # 4) 通过数预测（只算 position / size，它们是受窗口影响最直接的两维）
    print("\n== 判据 4：几何两维通过数（position / size）==")
    print(f"{'族':16s}" + "".join(f"{v:>14}" for v in VARIANTS))
    for name, rows in per_family.items():
        line = f"{name:16s}"
        for variant in VARIANTS:
            pos = siz = 0
            for row in rows:
                ref = row["measured"].get(variant)
                ren = row["rendered"].get(variant)
                if not ref or not ren:
                    continue
                dx, dy = ren[0] - ref[0], ren[1] - ref[1]
                wt = max(3, int(round(ref[2] * 0.03)))
                ht = max(3, int(round(ref[3] * 0.03)))
                pos += abs(dx) <= 2 and abs(dy) <= 2
                siz += abs(ren[2] - ref[2]) <= wt and abs(ren[3] - ref[3]) <= ht
            line += f"{str(pos) + '/' + str(siz):>14}"
        print(line)
    print("（position/size 通过条数；size 容差按 max(3, 3%)）")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "probe.json").write_text(
        json.dumps(all_rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\n明细：{out / 'probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
