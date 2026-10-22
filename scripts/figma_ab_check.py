# -*- coding: utf-8 -*-
"""Auto Layout 真机 A/B：同一份 DesignSpec 开 / 关两遍，比像素。

判据见 `归档文档 figma_layout_upgrade_audit.md` §10：Auto Layout 只该改结构，不该改像素 ——
开着（带 `layout`/`layoutChildren`）与关掉（同一份 elements 摘掉这两个字段）的导出必须
**逐像素相同**。

为什么要成对跑：单跑一组看不出问题（§9.4 的离线模型就是单跑思路，被真机 §10.2 推翻）。

用法（项目根目录；Figma 桌面端已 Run 插件 + bridge_server 在 8765）:
    python scripts/figma_ab_check.py --out output/_layout_probe_tab2
产物：`figma_render_ab_auto.png` / `figma_render_ab_flat.png` / `ab_report.json`
退出码：0 = 在容差内；3 = 超容差；1 = 输入缺失；2 = 回放失败。

`--allow-px` 是给「文字光栅化抖动」留的口子（antd 实测同一份设计重复跑也差 ~2.5k px，
全在文字带上，见 §10.5）；几何漂移是成片成带的，量与形都不一样，别拿它当遮羞布。
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AUTO_PNG = "figma_render_ab_auto.png"
FLAT_PNG = "figma_render_ab_flat.png"
FLAT_DESIGN = "12_design_flat.json"


def _strip_layout(design: dict) -> dict:
    """摘掉所有 `layout` / `layoutChildren` —— 等价于升级前的扁平绝对定位。"""
    flat = copy.deepcopy(design)
    for el in flat.get("elements") or []:
        el.pop("layout", None)
        el.pop("layoutChildren", None)
    if isinstance(flat.get("_meta"), dict):
        flat["_meta"]["autolayout_frames"] = 0
    return flat


def _replay(out: Path, design_name: str) -> int:
    cmd = [sys.executable, str(Path(__file__).with_name("figma_replay.py")),
           "--out", str(out), "--design", design_name]
    return subprocess.run(cmd).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/_layout_probe_tab2", help="产物目录")
    ap.add_argument("--design", default="12_design.json", help="带 Auto Layout 的 DesignSpec")
    ap.add_argument("--allow-px", type=int, default=0,
                    help="允许的差异像素数（默认 0 = 逐像素必须相同）")
    args = ap.parse_args()
    out = Path(args.out)
    src = out / args.design
    if not src.exists():
        print("[FAIL] 缺少 DesignSpec: %s" % src)
        return 1
    design = json.loads(src.read_text(encoding="utf-8"))
    flat = _strip_layout(design)
    (out / FLAT_DESIGN).write_text(json.dumps(flat, ensure_ascii=False), encoding="utf-8")
    frames = (design.get("_meta") or {}).get("autolayout_frames")
    print("[ab  ] %s：elements=%d，autolayout_frames=%s；对照组 %s"
          % (src, len(design.get("elements") or []), frames, FLAT_DESIGN))

    for label, name in (("开 Auto Layout", args.design), ("关 Auto Layout", FLAT_DESIGN)):
        print("\n[ab  ] ===== %s（%s）=====" % (label, name))
        if _replay(out, name) != 0:
            print("[FAIL] 回放失败：%s" % name)
            return 2
        shutil.copyfile(out / "figma_render.png",
                        out / (AUTO_PNG if name == args.design else FLAT_PNG))

    import cv2
    import numpy as np
    a = cv2.imread(str(out / AUTO_PNG))
    b = cv2.imread(str(out / FLAT_PNG))
    if a is None or b is None:
        print("[FAIL] 读不到导出图")
        return 1
    if a.shape != b.shape:
        print("[FAIL] 两次导出尺寸不同: %s vs %s" % (a.shape, b.shape))
        return 3
    d = cv2.absdiff(a, b).max(axis=2)
    n, hard = int((d > 0).sum()), int((d > 8).sum())
    rep = {"out": str(out), "autolayout_frames": frames, "shape": list(a.shape),
           "diff_px": n, "diff_px_gt8": hard, "max_diff": int(d.max())}
    ys, xs = np.where(d > 0)
    if len(ys):
        rep["bbox"] = [int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())]
    (out / "ab_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    print("\n[ab  ] 逐像素：%d 个不同（>8 的 %d 个，最大 %d）；尺寸 %s"
          % (n, hard, int(d.max()), "x".join(str(v) for v in a.shape[:2][::-1])))
    if "bbox" in rep:
        y0, y1, x0, x1 = rep["bbox"]
        print("[ab  ] 差异范围 y=%d..%d x=%d..%d" % (y0, y1, x0, x1))
    print("[ab  ] 报告 " + str(out / "ab_report.json"))
    if n > args.allow_px:
        print("[FAIL] Auto Layout 改了像素（见 §10：真机成员必须钉死，不能让引擎摆）")
        return 3
    if n:
        print("[OK  ] 差异 %d px 在容差 %d 内（文字光栅化抖动，见 §10.5）"
              % (n, args.allow_px))
        return 0
    print("[OK  ] 两边逐像素相同：这一刀没挪像素")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())