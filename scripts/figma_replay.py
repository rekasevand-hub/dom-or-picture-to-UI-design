# -*- coding: utf-8 -*-
"""DOM 路线的 Figma 验收：把已保存的 DesignSpec 回放进 Figma，导出 PNG 与采集截图差分。

用法（在项目根目录运行）:
    python scripts/figma_replay.py --out output/_online_live
    python scripts/figma_replay.py --out output/_online_live --design 12_design.json --scale 1

前置条件:
    1) Figma 桌面端已打开，且 Development 里已 Run 本仓库的插件（figma_bridge/manifest.json）
    2) python -m src.app.services.bridge_server 已在 8765 监听

为什么用回放而不是重爬:
    12_design.json 是管线的最终 DesignSpec，回放省掉 ~25s 抓取与 LLM 环节，
    迭代 Figma 端失真时只动这一层，指标才可比。

退出码: 0=通过, 1=输入缺失, 2=桥接/插件错误, 3=差分超过阈值
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.app.services.rendering.figma_adapter import FigmaBridgeAdapter  # noqa: E402
from src.config.settings import load_config  # noqa: E402

SCREEN_NAME = "Screen"

# Windows 控制台默认 GBK，字体名/文本里的生僻字符会直接抛 UnicodeEncodeError
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class _ReplayAdapter(FigmaBridgeAdapter):
    """回放用适配器：记住画板 id，并拦掉 render_design 结尾的 flush 断连。

    render_design 以 self.flush() 收尾（flush 里 disconnect），但导出 PNG 还要
    用这条连接，所以在导出完成后再手动断开。
    """

    def __init__(self, *args, screen_name: str | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.frame_id: str | None = None
        self.screen_name = screen_name

    def create_frame(self, spec):
        # 只有第一个 Frame 是页面画板（后开的都是 Auto Layout 容器 / 裁剪容器），
        # 导出要认它。旧实现每次都覆盖，Auto Layout 上线后会把某个容器当画板导出
        # （实测导出成 152x142 的书格 Frame）。
        node_id = super().create_frame(
            _screen_spec(
                spec,
                screen_name=self.screen_name,
                first_frame=self.frame_id is None,
            )
        )
        if self.frame_id is None:
            self.frame_id = node_id
        return node_id

    def flush(self) -> None:  # 留连接给 export_frame
        self.finalize_semantic_componentization()


def _screen_spec(
    spec: dict,
    *,
    screen_name: str | None,
    first_frame: bool,
) -> dict:
    params = dict(spec)
    if first_frame and screen_name:
        params["name"] = screen_name
    return params


def _export_png(adapter: _ReplayAdapter, out_p: Path, scale: float) -> Path:
    resp = adapter._send("export_frame", {"nodeId": adapter.frame_id, "scale": scale})
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_bytes(base64.b64decode(resp["base64"]))
    return out_p


def _report(
    out: Path, render_p: Path, max_mean: float | None, max_bad_pct: float | None
) -> int:
    import cv2
    import numpy as np
    from src.app.utils.pixel_metrics import compare_images, default_bands, region_scores

    ref = cv2.imread(str(out / "00_screenshot.png"))
    new = cv2.imread(str(render_p))
    if ref is None or new is None:
        print(f"[FAIL] 读不到图: {out / '00_screenshot.png'} / {render_p}")
        return 1
    h, w = ref.shape[:2]
    if new.shape[:2] != (h, w):
        print(f"[warn] Figma 导出 {new.shape[1]}x{new.shape[0]}，重采样到 {w}x{h}")
        new = cv2.resize(new, (w, h))

    rep = compare_images(ref, new)
    diff = rep["diff"]
    mean, ink_mean, bad_pct = rep["mean"], rep["ink_mean"], rep["over30_pct"]
    print(
        "整图 %.3f/255  笔画 %.3f  >30 %.2f%%  纪律像素 %d"
        % (mean, ink_mean, bad_pct, rep["ink_px"])
    )
    for name, y0, y1, x0, x1, score in region_scores(
        diff, default_bands(w, h), clamp=True
    ):
        print("  %-8s y=%3d-%3d x=%4d-%4d  %.3f" % (name, y0, y1, x0, x1, score))

    cv2.imwrite(str(out / "figma_compare.png"), np.concatenate([ref, new], axis=1))
    hm = cv2.applyColorMap(
        np.clip(diff.max(axis=2) * 4, 0, 255).astype(np.uint8), cv2.COLORMAP_JET
    )
    cv2.imwrite(str(out / "figma_diff.png"), hm)
    print("figures:", out / "figma_compare.png", out / "figma_diff.png")

    if max_mean is not None and mean > max_mean:
        print(f"[FAIL] 整图 {mean:.3f} > 阈值 {max_mean}")
        return 3
    if max_bad_pct is not None and bad_pct > max_bad_pct:
        print(f"[FAIL] >30 占比 {bad_pct:.2f}% > 阈值 {max_bad_pct}%")
        return 3
    return 0


FONT_STACK_PROBE = [
    "-apple-system",
    "BlinkMacSystemFont",
    "Segoe UI",
    "PingFang SC",
    "Hiragino Sans GB",
    "Microsoft YaHei",
    "Helvetica Neue",
    "Helvetica",
    "Arial",
    "Inter",
]


def _font_report(bridge_url: str) -> int:
    """读一次 Figma 当前文档的文字字体分布：用来判定 Figma 选中了哪个字体。"""
    adapter = FigmaBridgeAdapter(bridge_url)
    try:
        adapter.connect()
    except Exception as exc:
        print(f"[FAIL] 连不上桥接服务器 {bridge_url}: {type(exc).__name__}: {exc}")
        return 2
    try:
        rep = adapter._send("font_report", {"families": FONT_STACK_PROBE})
    except Exception as exc:
        print(f"[FAIL] 插件错误: {type(exc).__name__}: {exc}")
        return 2
    finally:
        adapter.disconnect()
    print(f"[文本节点] {rep['textNodes']} 个；本机可用字体族 {rep['totalFamilies']} 个")
    for name, n in sorted(rep["usedFonts"].items(), key=lambda kv: -kv[1]):
        print(f"  实用  {name}  x{n}")
    for fam, n in rep["stackProbe"]:
        print(f"  {'有' if n else '无'} {fam}  (可用样式 {n} 个)")
    print(f"[图层] {rep['layerCount']} 个节点，其中 {rep['namedCount']} 个有自定义名")
    for nm in rep["sampleNames"]:
        print(f"  图层  {nm}")
    return 0


def _ir_font_probes(design: dict, limit: int = 40) -> list[dict]:
    """DesignSpec 里实际用到的 (fontFamily, fontWeight) 组合（去重、按次数排序）。

    这是 Figma 端"该把每段文字解析成哪个 face"的输入清单：带 fontFamily 的就是
    真的会落字的文本元素（采集侧只给可见文本/placeholder 写字体栈）。回放跑完拿它
    去问插件 font_probe，就能把"IR 请求的字体"与"Figma 实际选中的 face"并排落盘。
    """
    counts: dict[tuple[str, str], int] = {}
    for el in design.get("elements") or []:
        style = el.get("style") or {}
        family = style.get("fontFamily") or el.get("fontFamily")
        if not family:
            continue
        weight = str(
            style.get("fontWeightValue")
            or style.get("fontWeight")
            or el.get("fontWeight")
            or "normal"
        )
        key = (str(family), weight)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        {"fontFamily": fam, "fontWeight": weight, "count": n}
        for (fam, weight), n in ordered[:limit]
    ]


def _dump_font_report(adapter, out: Path, design: dict) -> None:
    """跑完顺带落 `font_report.json`：IR 的字体请求 → Figma 实际选中的 face。

    P0-1 的验收证据：Figma 侧选错 face 是"同一段 16px bold 标题比原页粗 35%"的
    根因（见 归档文档 figma_route_upgrade.md §2）。这里把两侧并排写盘，跑一次就定死
    是"family 解析错了"还是"字重降档问题"。插件版本过旧时不阻断回放。
    """
    probes = _ir_font_probes(design)
    payload: dict = {"ir": probes, "probes": []}
    try:
        rep = adapter._send("font_report", {"families": FONT_STACK_PROBE})
        payload.update(
            {
                "textNodes": rep.get("textNodes"),
                "totalFamilies": rep.get("totalFamilies"),
                "usedFonts": rep.get("usedFonts", {}),
                "stackProbe": rep.get("stackProbe", []),
            }
        )
        if probes:
            probed = adapter._send("font_probe", {"probes": probes})
            payload["probes"] = probed.get("results", [])
    except Exception as exc:  # 插件版本旧 / 命令不支持：只警告，不影响回放
        print(f"[font ] 取字体报告失败（可忽略）: {type(exc).__name__}: {exc}")
        return
    out_p = out / "font_report.json"
    out_p.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        "[font ] 本机可用字体族 %s 个；文档里 %s 个文本节点"
        % (payload.get("totalFamilies"), payload.get("textNodes"))
    )
    for name, n in sorted(
        (payload.get("usedFonts") or {}).items(), key=lambda kv: -kv[1]
    ):
        print("        实用  %s  x%d" % (name, n))
    for item in payload["probes"]:
        picked = item.get("picked") or {}
        flag = " (回退)" if item.get("fallback") else ""
        print(
            "        请求  %s / %s  ->  %s %s%s"
            % (
                item["request"]["fontFamily"],
                item["request"]["fontWeight"],
                picked.get("family"),
                picked.get("style"),
                flag,
            )
        )
    print("        " + str(out_p))


def _review(render_p: Path, ref_p: Path) -> None:
    """把刚导出的 Figma PNG 丢给多模态模型复核，并落一份 figma_review.json。"""
    from src.app.services.rendering.render_review import review_render

    try:
        rep = review_render(render_p, load_config(), ref_png=ref_p)
    except Exception as exc:
        print(f"[review] 失败: {type(exc).__name__}: {exc}")
        return
    print(f"[review] {rep['bands']} 条带，{len(rep['defects'])} 条缺陷")
    for d in rep["defects"]:
        print(
            "   [band%d y=%d] %-15s %s | %s"
            % (d["band"], d["y0"], d["type"], d["detail"], d["where"])
        )
    (render_p.parent / "figma_review.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _bind_target_tickets(tickets, candidates) -> list:
    """Tie a confirmation back to a candidate, even when the model writes "None".

    The live model filled `ref` with the string "None" while naming "第 1 个候选"
    in its note — the placeholder in the schema leaked into the answer.  So the
    binding is: an exact ref wins; otherwise the ordinal in the note; otherwise a
    single candidate may take it.  Anything else is dropped rather than guessed.
    """
    import re

    refs = {candidate.ref for candidate in candidates}
    bound = []
    for ticket in tickets:
        ref = str(ticket.ref or "").strip()
        if ref in refs:
            bound.append(ticket)
            continue
        match = re.search(r"第\s*(\d+)\s*个", str(ticket.note or ""))
        if match:
            index = int(match.group(1)) - 1
            if 0 <= index < len(candidates):
                ticket.ref = candidates[index].ref
                bound.append(ticket)
                continue
        if len(candidates) == 1:
            ticket.ref = candidates[0].ref
            bound.append(ticket)
    return bound


def _roundtrip(out: Path, design: dict, adapter, *, scale: float = 1.0, limit: int = 1) -> dict:
    """真机回环：原图 vs 导出图，2× 局部裁片，最多一轮增量修补。

    整页裁判看不见"只在目标端发生"的差异——`输入 · 峰时` 在设计文件里是六个
    完整的字，只在 Figma 画面被吞掉两个。这一轮把输入换成真机导出图，探针先
    找出"原图有墨、导出图没墨"的文字和"原图有线、导出图没线"的容器，再让模型
    逐条确认；成立的就地抬层或补描边，然后重画一次。
    """
    import numpy as np
    from PIL import Image

    from src.app.services.structure.fidelity import vlm_arbiter as arbiter
    from src.app.services.structure.fidelity.arbitration_store import save_arbitrated

    truth_path = out / "00_screenshot.png"
    target_path = out / "figma_render.png"
    if not truth_path.is_file() or not target_path.is_file():
        return {"note": "缺少原图或导出图"}
    truth = np.asarray(Image.open(truth_path).convert("RGB"), dtype=np.int16)
    target = np.asarray(Image.open(target_path).convert("RGB"), dtype=np.int16)
    if truth.shape != target.shape:
        return {"note": f"尺寸不一致 {truth.shape} vs {target.shape}"}
    elements = design.get("elements") or []
    background = str((design.get("canvas") or {}).get("background") or "")
    candidates = arbiter.probe_target_candidates(elements, truth, target, background)
    report: dict = {"candidates": len(candidates), "kinds": [c.kind for c in candidates]}
    if not candidates:
        return report
    try:
        from replay_pagegraph import _vision_callable

        vision = _vision_callable()
    except Exception:  # noqa: BLE001 - optional at runtime
        vision = None
    if vision is None:
        report["note"] = "VISION_API_KEY 未配置，只记录候选"
        return report
    panels = arbiter.candidate_panels(truth, target, candidates)
    answer = vision(arbiter.target_prompt(candidates), panels)
    tickets = _bind_target_tickets(arbiter.parse_design_tickets(answer), candidates)
    applied = []
    for ticket in tickets[:limit + 2]:
        change = arbiter.execute_target(ticket, elements, truth)
        if change:
            applied.append({"type": ticket.type, "ref": ticket.ref, **change})
    report["tickets"] = len(tickets)
    report["applied"] = applied
    if not applied:
        return report
    save_arbitrated(design, out, stages=["roundtrip"], tickets=[a["type"] for a in applied])
    try:
        adapter._send("remove_nodes_by_name", {"name": SCREEN_NAME, "prefix": True})
        adapter.render_design(design)
        _export_png(adapter, out / "figma_render.png", scale)
        report["redrawn"] = True
    except Exception as exc:  # noqa: BLE001 - the first export is still valid
        report["redrawError"] = f"{type(exc).__name__}: {exc}"
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default="output/_online_live",
        help="产物目录（默认 output/_online_live）",
    )
    ap.add_argument(
        "--design", default="12_design.json", help="目录内的 DesignSpec 文件名"
    )
    ap.add_argument(
        "--scale", type=float, default=1.0, help="Figma 导出倍率（默认 1.0）"
    )
    ap.add_argument(
        "--screen-name",
        default=SCREEN_NAME,
        help="首个画板名与清理前缀（默认 Screen）",
    )
    ap.add_argument(
        "--readback-depth",
        type=int,
        default=3,
        help="Figma node-tree readback depth (default 3 avoids oversized responses)",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="bridge plugin response timeout in seconds (default: bridge config)",
    )
    ap.add_argument(
        "--max-mean", type=float, default=None, help="整图均差阈值（默认不设）"
    )
    ap.add_argument(
        "--max-bad-pct", type=float, default=None, help=">30 像素占比阈值（默认不设）"
    )
    ap.add_argument(
        "--font-report",
        action="store_true",
        help="只读当前文档的文字字体报告（不重画）",
    )
    ap.add_argument(
        "--no-roundtrip",
        action="store_true",
        help="导出后不做真机回环复检（默认做一轮）",
    )
    ap.add_argument(
        "--review",
        action="store_true",
        help="导出后把 PNG 交给多模态模型复核排版缺陷（需 VISION_API_KEY）",
    )
    args = ap.parse_args()

    out = Path(args.out)
    design_p = out / args.design
    if args.design == "12_design.json":
        # 默认导出"真正被渲染过的那一份"：仲裁与补丁都写在
        # 12_design_arbitrated.json 里，12_design.json 只是编译器的输出。
        from src.app.services.structure.fidelity.arbitration_store import (
            resolve_design,
        )

        design_p = resolve_design(out)
    if not design_p.exists():
        print(f"[FAIL] 缺少 DesignSpec: {design_p}")
        return 1
    design = json.loads(design_p.read_text(encoding="utf-8"))
    print(
        "[in  ] %s  canvas=%s  elements=%d"
        % (design_p, design.get("canvas"), len(design.get("elements", [])))
    )

    cfg = load_config()
    if args.font_report:
        return _font_report(cfg.figma_bridge_url)
    cfg = load_config()
    adapter = _ReplayAdapter(
        cfg.figma_bridge_url,
        timeout=args.timeout,
        screen_name=args.screen_name,
    )
    try:
        adapter.connect()
    except Exception as exc:
        print(
            f"[FAIL] 连不上桥接服务器 {cfg.figma_bridge_url}: {type(exc).__name__}: {exc}"
        )
        return 2
    print(f"[conn] {cfg.figma_bridge_url}")

    try:
        stale = adapter._send(
            "remove_nodes_by_name",
            {"name": args.screen_name, "prefix": True},
        )
        print(f"[clean] 清掉旧画板 {stale.get('removed')} 个")
        adapter.render_design(design)
        print(f"[draw ] 已下发，画板 id={adapter.frame_id}")
        _dump_font_report(adapter, out, design)
        tree = adapter._send(
            "get_node_tree",
            {
                "nodeId": adapter.frame_id,
                "depth": max(1, int(args.readback_depth)),
            },
        )
        (out / "readback_tree.json").write_text(
            json.dumps(tree, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[read ] 节点树已回写 {out / 'readback_tree.json'}")
        try:
            image_report = adapter.image_fill_report(adapter.frame_id)
            (out / "image_report.json").write_text(
                json.dumps(image_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(
                "[image] 图片填充字节已回写 %s (%s 个)"
                % (out / "image_report.json", image_report.get("fillCount", 0))
            )
        except Exception as exc:  # noqa: BLE001 - optional for asset-free frames
            print(f"[image] 图片填充报告失败（可忽略）: {type(exc).__name__}: {exc}")
        render_p = _export_png(adapter, out / "figma_render.png", args.scale)
        print(f"[exp  ] {render_p}")
        if not args.no_roundtrip:
            loop = _roundtrip(out, design, adapter, scale=args.scale)
            if loop.get("candidates"):
                print(f"[loop ] 候选 {loop['candidates']} 条 -> 修复 {len(loop.get('applied') or [])} 条 {loop.get('note') or ''}")
            if loop.get("redrawn"):
                render_p = out / "figma_render.png"
        if args.review:
            _review(render_p, out / "00_screenshot.png")
    except Exception as exc:
        print(f"[FAIL] 桥接/插件错误: {type(exc).__name__}: {exc}")
        return 2
    finally:
        adapter.disconnect()

    return _report(out, out / "figma_render.png", args.max_mean, args.max_bad_pct)


if __name__ == "__main__":
    raise SystemExit(main())
