# -*- coding: utf-8 -*-
"""Figma 端精验：把一份 DesignSpec 画进 Figma、导出 PNG、按同一套口径打分。

为什么需要它（见 归档交接 HANDOFF_2026-09-14 §20.9 的遗留）：

- 闭环搜索的裁判永远是**本地 SVG 光栅**（≈2.6s/次，便宜、可复现）。
- 它调的阈值住在 `dom` 段、作用在 IR 构建的上游，所以结论对 SVG / Figma 两个
  出口**一样生效**——`src/app/services/rendering/` 里没有任何一处引用 site profile。
- 但那个裁判**没见过 Figma**：同一个 IR 在两端可以差很多（实测 dushu 的“分页带”：
  SVG 1.342 / Figma 3.334）。所以“SVG 变好”不等于“交付端变好”。

于是分两层：**粗搜用 SVG**（全量候选），**精验用 Figma**（只对 top-N 各画一次，
见 `profile_search.select_verify_candidates`）。本模块就是精验那一半。

前置：Figma 桌面端已 Run 本仓库插件，且 `python -m src.app.services.bridge_server`
在监听（与 `scripts/figma_replay.py` 同一条桥接）。
"""
from __future__ import annotations

from pathlib import Path

from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter


class _KeepAliveAdapter(FigmaBridgeAdapter):
    """render_design 以 flush() 收尾（flush 里 disconnect），但导出 PNG 还要用这条连接。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.frame_id: str | None = None

    def create_frame(self, spec):
        self.frame_id = super().create_frame(spec)
        return self.frame_id

    def flush(self) -> None:      # 留连接给 export_frame
        pass


def score_design_in_figma(design: dict, ref_png, *, bridge_url: str, out_png,
                          scale: float = 1.0, screen_name: str = "Screen",
                          review_cfg=None) -> dict:
    """画一遍 → 导出 → 和采集截图差分；返回 `{mean, ink_mean, over30_pct, ink_px, regions, png}`。

    口径与 `scripts/figma_replay.py` 一致（`clamp=True`），这样精验的数字和
    验收脚本打出来的数字是同一把尺子。

    review_cfg 给了 Config 时，顺带把导出的 PNG 丢给多模态模型做视觉复核
    （见 `render_review`），结果放在返回值的 `review` 里——像素分数只说"差多少"，
    说不出"错在哪"，文字重叠这类语义缺陷得靠它。
    """
    import base64

    import cv2

    from src.app.utils.pixel_metrics import compare_images, default_bands, region_scores

    out_png = Path(out_png)
    adapter = _KeepAliveAdapter(bridge_url)
    adapter.connect()
    try:
        # 和 figma_replay 一样按前缀清理：一次只留一块画板，避免叠图。
        adapter._send("remove_nodes_by_name", {"name": screen_name, "prefix": True})
        adapter.render_design(design)
        resp = adapter._send("export_frame", {"nodeId": adapter.frame_id, "scale": scale})
        out_png.parent.mkdir(parents=True, exist_ok=True)
        out_png.write_bytes(base64.b64decode(resp["base64"]))
    finally:
        adapter.disconnect()

    ref = cv2.imread(str(ref_png))
    new = cv2.imread(str(out_png))
    if ref is None or new is None:
        raise RuntimeError("读不到图：%s / %s" % (ref_png, out_png))
    h, w = ref.shape[:2]
    if new.shape[:2] != (h, w):
        new = cv2.resize(new, (w, h))
    rep = compare_images(ref, new)
    regions = {name: score for name, _y0, _y1, _x0, _x1, score
               in region_scores(rep["diff"], default_bands(w, h), clamp=True)}
    result = {"mean": rep["mean"], "ink_mean": rep["ink_mean"],
              "over30_pct": rep["over30_pct"], "ink_px": rep["ink_px"],
              "regions": regions, "png": str(out_png)}
    if review_cfg is not None:
        from src.app.services.rendering.render_review import review_render
        try:
            result["review"] = review_render(out_png, review_cfg, ref_png=ref_png)
        except Exception as exc:      # 复核是附加信息，不该把精验本身带崩
            result["review"] = {"error": "%s: %s" % (type(exc).__name__, exc)}
    return result
