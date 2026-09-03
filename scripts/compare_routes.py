# -*- coding: utf-8 -*-
"""同一 URL/截图跑多条路线，输出对比小结 + 各路线 SoM 产物。用法：
python scripts/compare_routes.py --url https://example.com --routes dom,grounding,cv
"""
from __future__ import annotations
import argparse, sys, json, itertools
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dataclasses import replace
from src.config import load_config
from src.app.services.structure.metrics import summarize


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None)
    ap.add_argument("--image", default=None)
    ap.add_argument("--routes", default="dom,grounding,cv")
    ap.add_argument("--base-out", default="output/compare")
    args = ap.parse_args()
    cfg = load_config()
    graphs, summary = {}, []
    for r in args.routes.split(","):
        sub = Path(args.base_out) / r
        from src.app.agents.precise_agent import PreciseAgent
        PreciseAgent(replace(cfg, output_dir=sub)).run(
            url=args.url, image=args.image, route=r, tool="svg")
        graphs[r] = json.loads((sub / "10_pagegraph.json").read_text(encoding="utf-8"))
    for ra, rb in itertools.combinations(graphs, 2):
        summary.append(summarize(graphs[ra], graphs[rb]))
    out = Path(args.base_out) / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in summary:
        print(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
