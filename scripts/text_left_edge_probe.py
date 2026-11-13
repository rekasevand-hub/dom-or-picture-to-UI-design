"""左沿偏差分类探针（只读）：哪些失败真的能靠平移元素框修好。

背景：`系统运行正常` 的元素框是整行（303px，从绿点起），文字却从 13px 后才开始；
而 `检查状态` 是按钮，墨迹本来就在 padding 之后，移它等于二次偏移。
两者外观相似、处置相反，所以必须按**元素类型与对齐方式**分开数，不能一律平移。

分类口径（全部可由产物字段复核，不看图）：

* ``control``       —— 元素类型是 button/input，或 textAlign 不是 left。标签由控件
  自己的布局摆放，移标签会和底框脱钩。
* ``contains-others`` —— 框内还有别的元素的中心点（图标、邻居标签）。框的左边不是
  这条文字的边。
* ``shiftable``     —— 以上都不成立：框内只有它自己、左对齐、是纯文本元素。
  这种 owner 的 ``box.x - referenceInk.x`` 就是该补的位移。

只读：不写 pipeline 产物，不改任何判据。数字随尺子变化，尺子定稿后需重跑。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BENCH = ROOT / "tests" / "fixtures" / "benchmark_families"
RERUN = ROOT / "output" / "_benchmark_families" / "rerun"
OUT = ROOT / "output" / "_text_left_edge"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _center(rect: list[float]) -> tuple[float, float]:
    return (rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0)


def _inside(point: tuple[float, float], rect: list[float]) -> bool:
    return (
        rect[0] <= point[0] <= rect[0] + rect[2]
        and rect[1] <= point[1] <= rect[1] + rect[3]
    )


def _classify(
    element: Mapping[str, Any],
    others: list[Mapping[str, Any]],
) -> str:
    style = element.get("style") or {}
    align = str(style.get("textAlign") or "left").lower()
    kind = str(element.get("type") or "")
    if kind in {"button", "input"} or align != "left":
        return "control"
    box = [
        float(element.get("x") or 0),
        float(element.get("y") or 0),
        float(element.get("width") or 0),
        float(element.get("height") or 0),
    ]
    for other in others:
        if other is element:
            continue
        rect = [
            float(other.get("x") or 0),
            float(other.get("y") or 0),
            float(other.get("width") or 0),
            float(other.get("height") or 0),
        ]
        if rect[2] <= 0 or rect[3] <= 0:
            continue
        if _inside(_center(rect), box):
            return "contains-others"
    return "shiftable"


def _probe(family_dir: Path) -> dict[str, Any]:
    run = RERUN / family_dir.name
    if not (run / "acceptance.json").is_file():
        return {"family": family_dir.name, "status": "no-artifacts"}
    design = _read(run / "figma_design.json")
    elements = [item for item in design.get("elements") or [] if isinstance(item, dict)]
    by_ref = {item.get("contentRef"): item for item in elements if item.get("contentRef")}
    acceptance = _read(run / "acceptance.json")
    owners = [
        item
        for item in acceptance["native_text_quality"]["owners"]
        if item.get("ownerScope") == "critical-gate"
    ]
    rows: list[dict[str, Any]] = []
    for owner in owners:
        if owner.get("status") == "pass":
            continue
        element = by_ref.get(owner.get("contentRef"))
        ink = owner.get("referenceInkBBox")
        if element is None or not ink:
            rows.append(
                {
                    "text": owner.get("text"),
                    "failureClass": owner.get("failureClass"),
                    "class": "no-element",
                }
            )
            continue
        box_x = float(element.get("x") or 0)
        rows.append(
            {
                "text": owner.get("text"),
                "type": element.get("type"),
                "align": (element.get("style") or {}).get("textAlign"),
                "failureClass": owner.get("failureClass"),
                "class": _classify(element, elements),
                "boxX": round(box_x, 1),
                "inkX": ink[0],
                "leftDelta": round(box_x - float(ink[0]), 1),
                "boxW": round(float(element.get("width") or 0), 1),
                "inkW": ink[2],
                "widthRatio": round(
                    float(element.get("width") or 0) / float(ink[2] or 1), 2
                ),
            }
        )
    return {"family": family_dir.name, "status": "measured", "failures": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", action="append")
    parser.add_argument("--out", default=str(OUT / "probe.json"))
    args = parser.parse_args(argv)

    families = sorted(
        (d for d in BENCH.iterdir() if d.is_dir() and (d / "family.json").is_file()),
        key=lambda d: d.name,
    )
    if args.family:
        wanted = set(args.family)
        families = [d for d in families if d.name in wanted]

    records = [_probe(item) for item in families]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps({"records": records}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"{'family':15s} {'text':22s} {'class':17s} {'failClass':16s} {'左沿':>6} {'框/墨':>6}")
    for record in records:
        if record.get("status") != "measured":
            print(f"{record['family']:15s} {record.get('status')}")
            continue
        for row in record["failures"]:
            print(
                f"{record['family']:15s} {str(row.get('text'))[:20]:22s} "
                f"{row.get('class', '-'):17s} {str(row.get('failureClass')):16s} "
                f"{row.get('leftDelta', 0):6.1f} {row.get('widthRatio', 0):6.2f}"
            )

    counts: dict[str, int] = {}
    for record in records:
        for row in record.get("failures") or []:
            key = str(row.get("class"))
            counts[key] = counts.get(key, 0) + 1
    print("\n分类合计：", json.dumps(counts, ensure_ascii=False, sort_keys=True))
    print(f"报告：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
