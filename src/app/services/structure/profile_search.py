# -*- coding: utf-8 -*-
"""站点 profile 的**在线闭环搜索**：让"猜出来的阈值"由像素结果说话。

思路（为什么这么做，见 HANDOFF 第 20 节）：

- **LLM 提候选，脚本打分**。LLM 只负责"往哪儿看"（哪些阈值更可能影响这个页面、
  往哪个方向试），**不负责给结论**；每个候选都要真的渲染一遍、和采集截图比像素，
  谁好谁坏由 `pixel_metrics` 判定。这样既用上了 LLM 的判断力，又保持可复现：
  同一份输入、同一组候选，跑多少遍结果都一样。
- **离线重放，不重爬**。输入是已经跑完的一遍产物（`00_dom.json` + `00_screenshot.png`），
  一次候选约 2~3 秒；重爬一次 25 秒，搜索根本跑不起来。
- **坐标下降**。每轮固定其它阈值，只扫一个；有改善就落定，再进下一轮。
  阈值之间会互相牵制（比如放宽浮层面积会影响重叠判定），所以一轮不够，跑多轮。
- **只写有依据的覆盖**。搜索结束只把"确实让像素变好"的键写进
  `site_profiles/<host>.json`；一项都没改善就什么都不写，并如实报告。

搜索空间**只含会改变像素的站点级阈值**。以下三个刻意排除：

| 键 | 为什么不搜 |
|---|---|
| `label_max_len` | 只影响 Figma 图层名，不进几何 |
| `merge_dividers` | 合并是逐像素等价的（HANDOFF 第 17 节），拿像素搜它只会抽签 |
| `min_style_coverage` | 只决定"要不要走直出"，DOM 路线恒定直出，与像素无关 |

**像素不是唯一目标**：有一类候选能把分刷低，代价是"把可编辑图层换成截图"——
把某个透明浮层容器放行成位图底（`cropBackdrop`），被它盖住的真实图层会被当作冗余
丢掉（本轮实测：`container_min_span_ratio` 0.5 -> 0.25 会把右侧固定列 tbody
140×450 变成一张截图，`div.ant-table-fixed-right` 里的 10 个"编辑"、10 个"删除"、
20 个 svg 图标、11 条分隔线共 51 个图层消失，整图 1.371 -> 1.337、表格右缘
1.479 -> 0.294）。这跟"要可编辑原型、不要图片"的既定目标冲突，所以
`search` 默认有一条硬否决：**位图底面积比 base 大的候选一律不采纳**（见
`EvalResult.bitmap_area` / `blocked`）。宁可保留现状，也不拿可编辑性换 0.03 的像素——
但这是**目标取舍**，不是技术限制：目标页主人愿意接受"那一列变图片"时，
`search(..., allow_backdrop=True)`（CLI `--allow-backdrop`）就放开，被放开的候选照常打分。
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from src.app.services.structure.site_profiles import SiteProfile, load_profile
from src.app.utils.pixel_metrics import (compare_images, default_bands, region_scores,
                                         score_key)

logger = logging.getLogger(__name__)

# 可搜索的阈值 + 默认候选档（LLM 可以在这些档之外再提值）。
SEARCHABLE: dict[str, list] = {
    "overlay_min_area": [0, 200, 400, 800, 1600, 3200, 6400],
    "overlay_min_overlap_px": [0, 500, 1500, 4000, 12000],
    "overlay_min_overlap_w": [0, 8, 15, 30, 60],
    "overlay_min_overlap_h": [0, 8, 15, 30],
    "container_min_area": [0, 1000, 2000, 4000, 8000],
    "container_min_span_ratio": [0.0, 0.25, 0.5, 0.75],
    "edge_max_thickness": [1, 2, 4, 8, 16, 32],
    "canvas_min_size": [1, 2, 4],
}


@dataclass
class EvalResult:
    """一次候选的像素报告 + 该候选用的覆盖。"""
    mean: float
    ink_mean: float
    over30_pct: float
    ink_px: int
    regions: dict[str, float]
    elements: int
    overrides: dict = field(default_factory=dict)
    # 位图底（cropBackdrop）覆盖的总面积 / 块数：这是"不可编辑"的代价，
    # 不参与 key 排序，只作为否决条件（见 search）。
    bitmap_area: int = 0
    backdrops: int = 0
    blocked: bool = False       # 像素更好但被否决（位图底变多），由 search 填

    @property
    def key(self) -> tuple[float, float, float]:
        return (self.mean, self.ink_mean, self.over30_pct)

    def as_dict(self) -> dict:
        return {"mean": round(self.mean, 4), "ink_mean": round(self.ink_mean, 4),
                "over30_pct": round(self.over30_pct, 4), "ink_px": self.ink_px,
                "elements": self.elements,
                "regions": {k: round(v, 4) for k, v in self.regions.items()},
                "bitmap_area": self.bitmap_area, "backdrops": self.backdrops,
                "overrides": dict(self.overrides)}


def _bands_for(h: int, w: int) -> list:
    return [b for b in default_bands(w, h) if b[1] < h]


def _backdrop_stats(elements, area: int = 0, count: int = 0) -> tuple[int, int]:
    """统计位图底（cropBackdrop）的总面积与块数——"不可编辑"的量化代价。"""
    for el in elements or []:
        if el.get("cropBackdrop"):
            area += int(el.get("width") or 0) * int(el.get("height") or 0)
            count += 1
        area, count = _backdrop_stats(el.get("children"), area, count)
    return area, count


def manifest_url(base_dir) -> str | None:
    """从产物目录的 manifest.json 读站点 URL；没有 / 坏了都返回 None。"""
    import json

    manifest = Path(base_dir) / "manifest.json"
    if not manifest.exists():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("url")
    except Exception:      # noqa: BLE001 - manifest 坏了不影响搜索
        return None


def load_run(base_dir: Path) -> tuple[Path, Path, str | None, int, int]:
    """读一遍产物的输入件；返回 (dom.json, screenshot.png, url, w, h)。"""
    import cv2

    dom_p = base_dir / "00_dom.json"
    shot_p = base_dir / "00_screenshot.png"
    if not dom_p.exists() or not shot_p.exists():
        raise FileNotFoundError(f"{base_dir} 里缺 00_dom.json / 00_screenshot.png")
    ref = cv2.imread(str(shot_p))
    h, w = ref.shape[:2]
    return dom_p, shot_p, manifest_url(base_dir), w, h


def build_design(base_dir, *, url: str | None = None,
                 profile: SiteProfile | None = None,
                 overrides: dict | None = None,
                 work_dir: Path | None = None,
                 ):
    """跑一遍“DOM → 直出 IR”，返回 (design, tmp_dir, shot_png, w, h)；只写 work_dir。

    和 `evaluate()` 前半段完全同源：粗搜打分与 Figma 精验必须建在**同一份 IR** 上，
    否则两边数字不可比。
    """
    from src.app.services.som.annotate import annotate_som
    from src.app.services.som.direct_design import (build_direct_design,
                                                    try_build_direct_design)
    from src.app.services.structure.providers.base import ProviderContext
    from src.app.services.structure.providers.dom import DomProvider

    base_dir = Path(base_dir)
    dom_p, shot_p, run_url, w, h = load_run(base_dir)
    url = url or run_url
    prof = profile if profile is not None else load_profile(url)
    if overrides:
        prof = (prof or SiteProfile(domains=[])).with_rules("dom", overrides)

    tmp = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="profile_search_"))
    tmp.mkdir(parents=True, exist_ok=True)
    shutil.copy(dom_p, tmp / "00_dom.json")
    shutil.copy(shot_p, tmp / "00_screenshot.png")

    ctx = ProviderContext(image_path=str(tmp / "00_screenshot.png"), image_w=w, image_h=h,
                          route="dom", output_dir=str(tmp),
                          dom_path=str(tmp / "00_dom.json"), url=url, profile=prof)
    som = annotate_som(DomProvider().run(ctx), str(tmp))
    design = try_build_direct_design(som, prof) or build_direct_design(som, prof)
    return design, tmp, shot_p, w, h


def evaluate(base_dir: Path, *, url: str | None = None,
             profile: SiteProfile | None = None,
             overrides: dict | None = None,
             work_dir: Path | None = None) -> EvalResult:
    """按给定阈值跑一遍“DOM → 直出 → 渲染”，返回像素报告。

    只写 work_dir（临时目录），不碰 base_dir 里的任何东西。

    **裁判永远是 SVG 光栅**（≈2.6s/次，便宜、可复现），这是“粗搜”。它调的阈值住在
    `dom` 段、作用在 IR 构建的上游，所以结果对 SVG / Figma 两个出口一样生效；
    但这个裁判**没见过 Figma**——交付端是否同向，要用
    `figma_score.score_design_in_figma()` 另行复核（见 `select_verify_candidates`）。
    """
    import cv2

    from src.app.services.rendering.svg_adapter import SVGMockAdapter
    from src.app.utils.svg_raster import rasterize_svg

    design, tmp, shot_p, w, h = build_design(base_dir, url=url, profile=profile,
                                             overrides=overrides, work_dir=work_dir)
    svg_p = tmp / "prototype.svg"
    adapter = SVGMockAdapter(svg_p)
    adapter.connect()
    adapter.render_design(design)
    adapter.flush()
    rasterize_svg(svg_p, tmp / "render.png", w, h)

    ref = cv2.imread(str(shot_p))
    new = cv2.imread(str(tmp / "render.png"))
    if new.shape[:2] != (h, w):
        new = cv2.resize(new, (w, h))
    rep = compare_images(ref, new)
    regions = {name: score for name, _y0, _y1, _x0, _x1, score
               in region_scores(rep["diff"], _bands_for(h, w))}
    els = design.get("elements") or []
    bd_area, bd_count = _backdrop_stats(els)
    return EvalResult(rep["mean"], rep["ink_mean"], rep["over30_pct"], rep["ink_px"],
                      regions, len(els), dict(overrides or {}),
                      bitmap_area=bd_area, backdrops=bd_count)


@dataclass
class SearchResult:
    base: EvalResult
    best: EvalResult
    log: list = field(default_factory=list)
    vetoed: int = 0     # 像素更好、但会把"可编辑图层"换成位图底的候选数
    advice: list = field(default_factory=list)   # 每轮 advisor（LLM）给的建议，逐轮留档
    # 逐条评估留档（含 overrides 快照）：粗搜只在 SVG 上打分，这里留全量记录，
    # 供 `select_verify_candidates()` 挑 top-N 拿去 Figma 端复核。
    evaluated: list = field(default_factory=list)

    @property
    def improved(self) -> bool:
        return self.best.key < self.base.key


def search(base_dir, *, url: str | None = None, knobs: list[str] | None = None,
           candidates: dict | None = None, max_evals: int = 80,
           rounds: int = 3, progress=None, allow_backdrop: bool = False,
           advisor=None) -> SearchResult:
    """坐标下降：逐个阈值试候选，只保留让像素变好的值。

    candidates 是 LLM 给的额外候选（`{knob: [值, ...]}`），会并进默认档里；
    knobs 是搜索顺序（LLM 可以按"这个页面更可能受谁影响"排）。

    **advisor（可选）= 把 LLM 接进每一轮**：签名 `advisor(round, state) -> advice`，
    `state` = `{base, best, history, tried}`（history 是本次搜索逐条评估记录：
    第几轮、哪个键、试了什么值、整图/笔画多少、是否被采纳）。每轮开跑**之前**问一次，
    它返回的 `knob_order` / `candidates` 只决定"这一轮先试谁、再补哪些值"——
    **判定权仍在像素**（照样要 `res.key < best.key` 才换）。advisor 抛错/返回空就
    退回默认顺序与默认档，搜索不受影响。`advisor=None` 时行为与接入前完全一致。

    有了它，LLM 就从"开局盲提一次"变成"看着上一轮结果决定下一轮"——它能在
    "某个键的相邻两档分数几乎一样"这类信号上补探新值。

    几条保证：

    - **单调**：只有 `res.key < best.key` 才替换，所以指标只会一路变好，不会来回振荡。
    - **可编辑优先（默认）**：位图底面积超过 base 的候选直接否决（`res.blocked`），哪怕
      像素更好——把浮层放行成截图能刷分，但那等于把可编辑图层换成图片（见模块 docstring）。
      显式传 `allow_backdrop=True` 可以放开这条；放开的候选照常参与打分。
    - **不重复**：同一个 (阈值, 取值) 只评一次。跨轮重试同一个值纯属浪费——因为
      后动的阈值永远是在"前面已定下来的值"之上评估的，交互效应在这一层已经吃到了；
      代价是"先动的阈值不会在后面的阈值改变后再回头看"（贪心的固有局限）。
    - **怎么停**：某轮"没人改善"就收工，**除非** advisor 这一轮补了"没试过、且不是
      当前生效值"的新候选——那就再问一轮，让 LLM 看到失败数据后有机会换别的值（否则
      首轮全军覆没时它没有第二次机会，见 归档交接 HANDOFF_2026-10-02 §4.2）。`rounds` 是轮数
      上限，`max_evals` 是总评估次数硬上限。
    """
    from src.app.services.structure.site_profiles import rule as _rule

    base_dir = Path(base_dir)
    url = url or manifest_url(base_dir)
    knobs = [k for k in (knobs or list(SEARCHABLE)) if k in SEARCHABLE]
    extra = candidates or {}

    prof0 = load_profile(url)
    effective = {k: _rule(prof0, "dom", k) for k in knobs}

    base = evaluate(base_dir, url=url, profile=prof0)
    best, best_ov = base, {}
    evaluations = 1
    vetoed = 0
    log: list[dict] = []
    advice_log: list[dict] = []
    history: list[dict] = []
    evaluated: list[dict] = []
    tried: dict[str, set] = {k: set() for k in knobs}

    def _round_advice(rnd):
        """问一次 advisor；出错或没给有效内容就退回默认（不拖垮搜索）。"""
        if advisor is None:
            return list(knobs), {}
        try:
            adv = advisor(rnd, {"base": base.as_dict(), "best": best.as_dict(),
                                "history": list(history),
                                "tried": {k: sorted(tried[k]) for k in knobs}})
        except Exception as exc:      # noqa: BLE001 - 建议环节失败不该拖垮搜索
            logger.warning("advisor 第 %d 轮不可用（%s: %s），用默认顺序与档位",
                           rnd, type(exc).__name__, exc)
            return list(knobs), {}
        if not isinstance(adv, dict):
            return list(knobs), {}
        order = [k for k in (adv.get("knob_order") or []) if k in knobs]
        order += [k for k in knobs if k not in order]        # 漏掉的补在后面
        extra_r = {k: list(v) for k, v in (adv.get("candidates") or {}).items()
                   if k in knobs and isinstance(v, (list, tuple))}
        advice_log.append({"round": rnd, "knob_order": order, "candidates": extra_r,
                           "reason": str(adv.get("reason") or "")[:400]})
        return order, extra_r

    for rnd in range(rounds):
        tried_before = {k: set(tried[k]) for k in knobs}
        now_before = {k: best_ov.get(k, effective[k]) for k in knobs}
        order, extra_r = _round_advice(rnd)
        # 本轮 advisor 有没有给“能真的再评一次”的新值：有的话，哪怕这轮全军覆没
        # 也再问一轮——否则 LLM 永远看不到失败数据（归档交接 HANDOFF_2026-10-02 §4.2 的 B 方案）。
        fresh = any(v not in tried_before[k] and v != now_before[k]
                    for k, values in extra_r.items() for v in values)
        improved_this_round = False
        for knob in order:
            if evaluations >= max_evals:
                break
            grid = (list(SEARCHABLE[knob]) + list(extra.get(knob) or [])
                    + list(extra_r.get(knob) or []))
            now = best_ov.get(knob, effective[knob])
            trial = None
            for value in grid:
                if value == now or value in tried[knob] or evaluations >= max_evals:
                    continue
                tried[knob].add(value)
                ov = dict(best_ov)
                ov[knob] = value
                res = evaluate(base_dir, url=url, profile=prof0, overrides=ov)
                evaluations += 1
                if res.bitmap_area > base.bitmap_area and not allow_backdrop:
                    res.blocked = True
                    vetoed += 1
                if progress:
                    progress(knob, value, res)
                accepted = not res.blocked and res.key < best.key
                if accepted:
                    best, best_ov, now, trial = res, ov, value, value
                history.append({"round": rnd, "knob": knob, "value": value,
                                "mean": round(res.mean, 4),
                                "ink_mean": round(res.ink_mean, 4),
                                "blocked": bool(res.blocked),
                                "accepted": bool(accepted)})
                evaluated.append({"round": rnd, "knob": knob, "value": value,
                                  "overrides": dict(ov),
                                  "mean": res.mean, "ink_mean": res.ink_mean,
                                  "over30_pct": res.over30_pct,
                                  "blocked": bool(res.blocked),
                                  "accepted": bool(accepted)})
            if trial is not None:
                improved_this_round = True
                log.append({"round": rnd, "knob": knob, "value": trial,
                            "mean": round(best.mean, 4),
                            "ink_mean": round(best.ink_mean, 4)})
        if not improved_this_round and not fresh:
            break
    return SearchResult(base=base, best=best, log=log, vetoed=vetoed, advice=advice_log,
                        evaluated=evaluated)


def select_verify_candidates(result: SearchResult, n: int, *,
                             include_base: bool = True) -> list[dict]:
    """挑出“值得拿去 Figma 端复核”的 top-N 组阈值（按 SVG 分数升序）。

    粗搜只在 SVG 上打分，**保证不了 Figma 端同向**（dushu 实测“分页带”：SVG 1.342
    / Figma 3.334——同一个 IR，两端能差一倍）。所以把 SVG 上最好的几组拿去 Figma
    各画一次、按同一套 `pixel_metrics` 重打分，才能回答“交付端是否仍然最优”。

    - `n` 只限制**候选**条数；base（`overrides={}`）作对照**无条件保留**——
      否则“这点改善到交付端还在不在”就无从判断（踩过一次）。
    - 同一组 overrides 只留一条；被否决（位图底变多）的候选不入选。
    - 返回 `[{label, overrides, key}]`，`key` 是 **SVG 端**的 `(整图, 笔画, >30)`。
    """
    import json

    cands: list[dict] = []
    seen = {json.dumps({}, sort_keys=True)}
    for ev in result.evaluated:
        if ev.get("blocked"):
            continue
        ov = dict(ev.get("overrides") or {})
        tag = json.dumps(ov, sort_keys=True, default=str)
        if tag in seen:
            continue
        seen.add(tag)
        cands.append({"label": "%s=%s" % (ev.get("knob"), ev.get("value")),
                      "overrides": ov,
                      "key": (ev.get("mean"), ev.get("ink_mean"), ev.get("over30_pct"))})
    cands.sort(key=lambda r: r["key"])
    rows = cands[:max(0, int(n))]
    if include_base:
        rows.append({"label": "base", "overrides": {}, "key": tuple(result.base.key)})
    rows.sort(key=lambda r: r["key"])
    return rows


def write_profile(path, overrides: dict, *, base: SiteProfile | None = None) -> Path:
    """把搜索到的覆盖写进 `site_profiles/<host>.json`（保留文件里已有的其它字段）。"""
    import json

    path = Path(path)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"{path} 不是合法 JSON，先手工修一下：{exc}") from exc
    dom = dict(data.get("dom") or {})
    dom.update(overrides)
    data["dom"] = dom
    if base is not None and base.icon_aria_labels:
        data.setdefault("icon_aria_labels", dict(base.icon_aria_labels))
    data.setdefault("domains", list(base.domains) if base is not None else [])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
