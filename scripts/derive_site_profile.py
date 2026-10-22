# -*- coding: utf-8 -*-
"""闭环搜索站点 profile：LLM 提候选 -> 逐候选离线重放打分 -> 只写真正变好的值。

用法（在项目根目录）：
    # 先有一遍完整产物（含 00_dom.json + 00_screenshot.png + manifest.json）
    python -m src.main --url <URL> --storage-state login_state.json --route dom --tool svg \
        --output-dir output/_online_live

    # 干跑：只报告，不写文件（默认）
    python scripts/derive_site_profile.py --out output/_online_live

    # 真的写进 site_profiles/<host>.json
    python scripts/derive_site_profile.py --out output/_online_live --apply

    # 不用 LLM（纯默认候选档，可复现）
    python scripts/derive_site_profile.py --out output/_online_live --no-llm

对齐口径：打分用的是 `src/app/utils/pixel_metrics.py`——和
`output/_live_metrics.py` / `scripts/figma_replay.py` 完全同一套，不会出现
"搜索说变好、验收说没变"。

写入的只有 `dom` 段里**确实让像素变好**的键；一项都没改善就不写（退出码 0，如实报告）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.app.services.structure.profile_search import (SEARCHABLE, evaluate,  # noqa: E402
                                                       manifest_url, search,
                                                       write_profile)
from src.app.services.structure.site_profiles import load_profile  # noqa: E402


def _fmt(rep) -> str:
    return ("整图 %.3f  笔画 %.3f  >30 %.2f%%  元素 %d"
            % (rep.mean, rep.ink_mean, rep.over30_pct, rep.elements))


def _profile_path(url: str | None) -> Path | None:
    if not url:
        return None
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    return Path(__file__).resolve().parents[1] / "site_profiles" / (host + ".json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/_online_live", help="已跑完的产物目录")
    ap.add_argument("--url", default=None, help="站点 URL（默认从 manifest.json 读）")
    ap.add_argument("--knobs", default=None, help="逗号分隔，限定搜索哪些阈值")
    ap.add_argument("--max-evals", type=int, default=80, help="候选评估次数上限")
    ap.add_argument("--rounds", type=int, default=3, help="坐标下降轮数上限")
    ap.add_argument("--no-llm", action="store_true", help="跳过 LLM，只用默认候选档")
    ap.add_argument("--allow-backdrop", action="store_true",
                    help="允许候选把可编辑图层换成位图底（默认否决；显式接受“那一列变图片”才加）")
    ap.add_argument("--apply", action="store_true", help="把结果写进 site_profiles/<host>.json")
    ap.add_argument("--report", default=None, help="证据 JSON 路径（默认 <out>/site_profile_search.json）")
    ap.add_argument("--verify-figma", type=int, default=0, metavar="N",
                    help="粗搜后把 SVG 端 top-N 组候选各画进 Figma 复核 "
                         "（另含 base 对照，共 N+1 张；需桥接；0=不验）")
    ap.add_argument("--bridge-url", default=None, help="Figma 桥接地址（默认读配置）")

    args = ap.parse_args()

    out = Path(args.out)
    if not (out / "00_dom.json").exists():
        print(f"[FAIL] {out} 里没有 00_dom.json，先跑一遍完整管线")
        return 1

    knobs = ([k.strip() for k in args.knobs.split(",") if k.strip()]
             if args.knobs else list(SEARCHABLE))
    unknown = [k for k in knobs if k not in SEARCHABLE]
    if unknown:
        print(f"[FAIL] 不可搜索的键：{unknown}；可选 {sorted(SEARCHABLE)}")
        return 1

    # 一次把 URL 定死：manifest.json 里记着的就是"这遍产物是哪个站点"。
    # 只给 evaluate 兜底是不够的——LLM 提候选、写文件挑路径、读站点 profile
    # 都要用同一个 host，否则 --apply 会找不到 host 直接放弃写入。
    url = args.url or manifest_url(out)
    base0 = evaluate(out, url=url)
    print("[base] %s" % _fmt(base0))
    for name, score in base0.regions.items():
        print("        %-8s %.3f" % (name, score))

    n = [0]
    veto_base = [base0.bitmap_area]

    def _progress(knob, value, res):
        n[0] += 1
        # 位图底变多的候选：像素可能更好，但会把可编辑图层换成截图，不采纳。
        mark = ("   [否决] 位图底 %d -> %d px²" % (veto_base[0], res.bitmap_area)
                if getattr(res, "blocked", False) else "")
        print("  [%2d] %-26s = %-8s -> 整图 %.3f  笔画 %.3f%s"
              % (n[0], knob, value, res.mean, res.ink_mean, mark), flush=True)

    def _advisor(rnd, state):
        """每轮开跑前问一次 LLM：看上一轮的逐条结果，决定这一轮先试谁、再补哪些值。

        LLM 只看得到数值（base/best/逐条评估历史），判定权仍在像素：
        它给的值照样要 `res.key < best.key` 才会被采纳。
        """
        from src.app.services.llm.profile_proposer import propose
        from src.app.services.structure.site_profiles import load_profile as _lp
        adv = propose(knobs, _lp(url), state["best"], elements=base0.elements,
                      history=state["history"], tried=state["tried"])
        print("[llm%d] 顺序 %s" % (rnd, adv["knob_order"]))
        if adv["candidates"]:
            print("[llm%d] 额外候选 %s"
                  % (rnd, json.dumps(adv["candidates"], ensure_ascii=False)))
        if adv["reason"]:
            print("[llm%d] 理由 %s" % (rnd, adv["reason"]), flush=True)
        return adv

    if args.allow_backdrop:
        print("[note] --allow-backdrop：本次允许候选把可编辑图层换成位图底（会丢图层）")
    res = search(out, url=url, knobs=knobs,
                 max_evals=args.max_evals, rounds=args.rounds, progress=_progress,
                 allow_backdrop=args.allow_backdrop,
                 advisor=None if args.no_llm else _advisor)

    if res.advice:
        print("[llm ] 共 %d 轮建议（逐轮见证据 JSON）" % len(res.advice))
    if res.vetoed:
        print("[veto] %d 个候选像素更好但会增加位图底（不可编辑），已否决"
              % res.vetoed)
    print("\n[base] %s" % _fmt(res.base))
    print("[best] %s" % _fmt(res.best))
    if res.improved:
        print("[gain] 整图 %+.3f  笔画 %+.3f  >30 %+.2f%%"
              % (res.best.mean - res.base.mean,
                 res.best.ink_mean - res.base.ink_mean,
                 res.best.over30_pct - res.base.over30_pct))
        for name, score in res.best.regions.items():
            old = res.base.regions.get(name, float("nan"))
            print("        %-8s %.3f -> %.3f" % (name, old, score))
    else:
        print("[gain] 无改善：现有阈值已经是这份候选里的最优，不写任何东西")
        if res.vetoed:
            print("        （有 %d 个候选像素更好，但会把可编辑图层换成位图底，按约定否决）"
                  % res.vetoed)

    figma_rows: list[dict] = []
    figma_conflict = False
    if args.verify_figma > 0:
        from src.app.services.rendering.figma_score import score_design_in_figma
        from src.app.services.structure.profile_search import (build_design,
                                                               select_verify_candidates)
        from src.config.settings import load_config

        cands = select_verify_candidates(res, args.verify_figma)
        bridge = args.bridge_url or load_config().figma_bridge_url
        print("[figm] 粗搜(SVG) top-%d 拿去 Figma 精验（桥接 %s）" % (len(cands), bridge))
        for i, c in enumerate(cands, 1):
            design, _tmp, shot_p, _w, _h = build_design(out, url=url,
                                                        overrides=c["overrides"])
            rep = score_design_in_figma(design, shot_p, bridge_url=bridge,
                                        out_png=out / ("figma_verify_%d.png" % i))
            row = dict(c)
            row["figma"] = rep
            figma_rows.append(row)
            print("  [f%d] %-26s SVG %6.3f  |  Figma %6.3f  笔画 %6.3f  >30 %.2f%%"
                  % (i, c["label"], c["key"][0], rep["mean"], rep["ink_mean"],
                     rep["over30_pct"]), flush=True)
        if figma_rows:
            base_row = next((r for r in figma_rows if r["label"] == "base"), None)
            if base_row is not None:
                bm, bi, bp = (base_row["figma"]["mean"], base_row["figma"]["ink_mean"],
                              base_row["figma"]["over30_pct"])
                print("[figm] 以 Figma 端 base（整图 %.3f / 笔画 %.3f）为基准：" % (bm, bi))
                for r in figma_rows:
                    print("       %-26s Δ整图 %+.3f  Δ笔画 %+.3f  Δ>30 %+.2fpp"
                          % (r["label"], r["figma"]["mean"] - bm,
                             r["figma"]["ink_mean"] - bi,
                             r["figma"]["over30_pct"] - bp))
                best_key = min((r["figma"]["mean"], r["figma"]["ink_mean"],
                                r["figma"]["over30_pct"]) for r in figma_rows)
                winners = [r["label"] for r in figma_rows
                           if (r["figma"]["mean"], r["figma"]["ink_mean"],
                               r["figma"]["over30_pct"]) == best_key]
                print("[figm] Figma 端最优 = %s" % "、".join(winners))
                win_row = next((r for r in figma_rows
                                if r["overrides"] == dict(res.best.overrides)), None)
                if res.improved and win_row is not None:
                    fk = (win_row["figma"]["mean"], win_row["figma"]["ink_mean"],
                          win_row["figma"]["over30_pct"])
                    bk = (bm, bi, bp)
                    if fk >= bk:
                        figma_conflict = True
                        print("[warn] SVG 端的改善没在 Figma 端兑现"
                              "（Δ整图 %+.3f / Δ笔画 %+.3f），--apply 被拦下"
                              % (fk[0] - bk[0], fk[1] - bk[1]))

    evidence = {"base": res.base.as_dict(), "best": res.best.as_dict(),
                "improved": res.improved, "overrides": res.best.overrides,
                "applied": res.log, "evaluations": n[0] + 1, "vetoed": res.vetoed,
                "allow_backdrop": bool(args.allow_backdrop),
                "advice": res.advice, "figma_verify": figma_rows}
    report_p = Path(args.report) if args.report else out / "site_profile_search.json"
    report_p.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[evid] %s" % report_p)

    if not res.improved:
        return 0
    print("[want] 覆盖 %s" % json.dumps(res.best.overrides, ensure_ascii=False))
    if res.best.bitmap_area > res.base.bitmap_area:
        print("[cost] 代价：位图底 %d -> %d px²（不可编辑面积变大）"
              % (res.base.bitmap_area, res.best.bitmap_area))
    if figma_conflict:
        print("[stop] Figma 精验与 SVG 结论不一致，已放弃 --apply（先把两端对齐再写）")
        return 0
    if not args.apply:
        print("[dry ] 未写入。确认数字合理后加 --apply 写入 site_profiles/<host>.json")
        return 0
    prof_p = _profile_path(url)
    if prof_p is None:
        print("[FAIL] 没有 url（manifest.json 里也没有），无法确定要写哪个 profile 文件")
        return 1
    write_profile(prof_p, res.best.overrides, base=load_profile(url))
    print("[write] %s" % prof_p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
