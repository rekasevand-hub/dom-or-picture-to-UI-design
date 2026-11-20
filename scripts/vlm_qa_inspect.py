"""Read-only QA inspection: name the flaws, then prove which stage lost them.

This is the offline twin of the closed loop.  It ***never*** writes to a design and
never rolls anything back — it looks at a reference image, a render of that page,
the design that was emitted and (optionally) the target's readback, and files each
visible flaw under the stage that owns it:

===================  ==========================================================
``perception-miss``  the picture has ink there, the render has none, and no node
                     in the design covers the box — perception never saw it
``emitter-drift``    a node *does* cover the box, but the render lost it, moved
                     it or clipped it; readback, when supplied, turns "lost" into
                     "absent in target" or "displaced by Npx"
``planned-degradation``  the box belongs to a node whose feature the target cannot
                     carry and ``13_degradations.json`` said so in advance
``style-mismatch``   the ink is there on both sides — the word is not missing, it
                     is the wrong size / weight / colour / spacing
===================  ==========================================================

Only the first question needs a model ("what looks wrong here"); everything after
it is pixels, boxes and the degradation ledger.  That split is the point: the same
sweep that used to report six "missing" words which were merely 11.5px small now
proves them present with ``still_missing`` and files them as style.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from src.app.services.structure.fidelity import vlm_arbiter as arbiter  # noqa: E402

SCHEMA_VERSION = "vlm-qa-inspect/1.0"
BUCKETS = (
    "perception-miss",
    "emitter-drift",
    "planned-degradation",
    "style-mismatch",
)
BUCKET_LABELS = {
    "perception-miss": "感知漏检",
    "emitter-drift": "发射端丢失/位移",
    "planned-degradation": "已记账的后端降级",
    "style-mismatch": "样式偏差（不是缺失）",
}
#: 桶色一律 **RGB**（不是 cv2 习惯的 BGR）。画布全程 RGB、落盘走 PIL，
#: 所以这里的三个数就是屏幕上看到的红绿蓝——以前按 BGR 写、又被 `cv2.imwrite`
#: 当 BGR 读，等于把整页和标注一起翻了通道。
BUCKET_COLOURS = {
    "perception-miss": (220, 40, 40),       # 红：原图有、渲染没有
    "emitter-drift": (255, 140, 0),         # 橙：设计有、导出没有
    "planned-degradation": (160, 40, 200),  # 紫：后端能力不够，账本已记账
    "style-mismatch": (20, 130, 220),       # 蓝：字/形在，只是样式不对
}
#: 设计节点与缺陷框的最小重叠；低于它就是"这附近有个节点"，不是"就是这个节点"。
NODE_MATCH_SHARE = 0.25
#: 回读判定：位移超过这么多像素算"发射端搬走了"。
READBACK_SHIFT_PX = 4


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _image(path: str | Path) -> Any:
    import numpy as np
    from PIL import Image

    return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)


def _rect(element: dict) -> list[int]:
    return [
        int(round(float(element.get("x") or 0))),
        int(round(float(element.get("y") or 0))),
        int(round(float(element.get("width") or 0))),
        int(round(float(element.get("height") or 0))),
    ]


def _share(inner: list[int], outer: list[int]) -> float:
    x0 = max(inner[0], outer[0])
    y0 = max(inner[1], outer[1])
    x1 = min(inner[0] + inner[2], outer[0] + outer[2])
    y1 = min(inner[1] + inner[3], outer[1] + outer[3])
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return 0.0
    return ((x1 - x0) * (y1 - y0)) / max(1, inner[2] * inner[3])


def design_elements(design: dict) -> list[dict[str, Any]]:
    """Every element of a DesignSpec, pages flattened, in paint order."""
    pages = design.get("pages") if isinstance(design.get("pages"), list) else None
    return [
        element
        for page in pages or [design]
        for element in page.get("elements") or []
        if isinstance(element, dict)
    ]


def design_nodes(design: dict) -> list[dict[str, Any]]:
    """Flatten a DesignSpec (single page or ``pages``) into boxes with text."""
    rows: list[dict[str, Any]] = []
    for element in design_elements(design):
        rect = _rect(element)
        if rect[2] <= 0 or rect[3] <= 0:
            continue
        rows.append(
            {
                "id": str(element.get("id") or ""),
                "type": str(element.get("type") or ""),
                "role": str(element.get("role") or ""),
                "text": str(element.get("text") or ""),
                "box": rect,
            }
        )
    return rows


def readback_nodes(path: str | Path | None) -> list[dict[str, Any]]:
    """Normalise a Figma node tree or an Axure ``inspect_rp`` dump into boxes."""
    if not path:
        return []
    candidate = Path(path)
    if not candidate.is_file():
        return []
    payload = _read_json(candidate)
    rows: list[dict[str, Any]] = []

    def walk_figma(node: Any) -> None:
        if not isinstance(node, dict):
            return
        absolute = node.get("absolute") or node.get("bounds") or {}
        text = str(node.get("characters") or "")
        if absolute and (text or str(node.get("type") or "") in ("TEXT", "FRAME")):
            rows.append(
                {
                    "id": str(node.get("id") or ""),
                    "text": text,
                    "name": str(node.get("name") or ""),
                    "box": [
                        int(round(float(absolute.get("x") or 0))),
                        int(round(float(absolute.get("y") or 0))),
                        int(round(float(absolute.get("width") or 0))),
                        int(round(float(absolute.get("height") or 0))),
                    ],
                }
            )
        for child in node.get("children") or []:
            walk_figma(child)

    if isinstance(payload.get("pages"), list):
        for page in payload["pages"]:
            for widget in page.get("widgets") or []:
                geometry = widget.get("geometry") or {}
                rows.append(
                    {
                        "id": str(widget.get("guid") or widget.get("label") or ""),
                        "text": str(widget.get("text") or widget.get("label") or ""),
                        "name": str(widget.get("label") or ""),
                        "box": [
                            int(round(float(geometry.get("x") or 0))),
                            int(round(float(geometry.get("y") or 0))),
                            int(round(float(geometry.get("width") or 0))),
                            int(round(float(geometry.get("height") or 0))),
                        ],
                    }
                )
        return rows
    walk_figma(payload)
    return rows


def _node_at(nodes: list[dict[str, Any]], box: list[int]) -> dict[str, Any] | None:
    """The smallest node that covers a decent share of the defect box."""
    ranked = [
        (share, float(node["box"][2]) * float(node["box"][3]), node)
        for node in nodes
        if (share := _share(box, node["box"])) >= NODE_MATCH_SHARE
    ]
    if not ranked:
        return None
    top = max(item[0] for item in ranked)
    near = [item for item in ranked if item[0] >= top - 0.05]
    return min(near, key=lambda item: item[1])[2]


def _degradation_for(
    node_id: str,
    degradations: dict | None,
) -> dict[str, Any] | None:
    if not node_id or not isinstance(degradations, dict):
        return None
    for row in degradations.get("degradations") or []:
        if node_id in (row.get("source_node_ids") or []):
            return row
    return None


def _readback_evidence(
    node: dict[str, Any] | None,
    nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Did the target actually carry this node, and where?"""
    if node is None:
        return {"status": "no-node"}
    if not nodes:
        return {"status": "no-readback"}
    text = node.get("text") or ""
    if not text.strip():
        # 容器/图标没有文字可比对：回读能证明"它在"，证明不了"它没了"。
        return {"status": "untracked"}
    matches = [item for item in nodes if text and item.get("text") == text]
    if not matches:
        return {"status": "absent-in-target"}
    reference_box = node["box"]
    best = min(
        matches,
        key=lambda item: abs(item["box"][0] - reference_box[0])
        + abs(item["box"][1] - reference_box[1]),
    )
    dx = best["box"][0] - reference_box[0]
    dy = best["box"][1] - reference_box[1]
    status = "present"
    if abs(dx) > READBACK_SHIFT_PX or abs(dy) > READBACK_SHIFT_PX:
        status = "displaced"
    return {"status": status, "dx": dx, "dy": dy, "targetNodeId": best.get("id")}


def _ink_state(ref, rendered, box: list[int]) -> str:
    """``missing`` / ``present`` / ``unjudgeable`` — the three answers ink can give.

    "Unjudgeable" is not a fourth bucket; it is the honest answer when the box
    holds 38 ink pixels over 9600 (a neighbouring glyph's tail) or none at all
    (an icon the sweep guessed at).  Calling that "present" would hide a real
    miss; calling it "missing" sends a patch after nothing.
    """
    source = arbiter._ink_pixels(ref, box)
    area = max(1, int(box[2]) * int(box[3]))
    if source < 20 or source / area < arbiter.SWEEP_TEXT_MIN_DENSITY:
        return "unjudgeable"
    return "missing" if arbiter.still_missing(rendered, ref, box) else "present"


def classify(
    defects: list[dict[str, Any]],
    *,
    ref,
    rendered,
    nodes: list[dict[str, Any]],
    readback: list[dict[str, Any]],
    degradations: dict | None,
) -> list[dict[str, Any]]:
    """File each named flaw under the stage that owns it.

    ``still_missing`` is the referee for "is it actually gone": a word rendered
    25% small is inked, and calling it missing sends a patch to the wrong layer.
    """
    items: list[dict[str, Any]] = []
    for index, defect in enumerate(defects, start=1):
        box = [int(value) for value in defect["bbox"]]
        source_ink = arbiter._ink_pixels(ref, box)
        rendered_ink = arbiter._ink_pixels(rendered, box)
        state = _ink_state(ref, rendered, box)
        missing = state == "missing"
        node = _node_at(nodes, box)
        evidence: dict[str, Any] = {
            "source_ink": source_ink,
            "rendered_ink": rendered_ink,
            "ink_share": round(rendered_ink / source_ink, 3) if source_ink else None,
            "ink_state": state,
            "still_missing": bool(missing),
        }
        degraded = _degradation_for(str(node.get("id") or "") if node else "", degradations)
        if state == "present":
            bucket = "style-mismatch"
            detail = "字/形在图上，属样式偏差（大小、字重、颜色或间距），不是缺失"
        elif state == "unjudgeable":
            bucket = "style-mismatch"
            detail = "框内墨量不足以判定（原图此处几乎无墨），按样式偏差归档，不当缺失去补"
        elif degraded is not None:
            bucket = "planned-degradation"
            detail = f"{degraded['feature']} -> {degraded['fallback']}（已在 13_degradations 记账）"
            evidence["degradation"] = degraded
        elif node is None:
            bucket = "perception-miss"
            detail = "原图有墨、渲染无墨，且设计稿里没有节点覆盖该区域"
        else:
            bucket = "emitter-drift"
            target = _readback_evidence(node, readback)
            evidence["readback"] = target
            detail = {
                "absent-in-target": "设计有节点，回读里没有该节点（发射端丢失）",
                "displaced": f"设计有节点，回读位移 dx={target.get('dx')} dy={target.get('dy')}",
                "present": "设计有节点、回读也在，但导出图上没有墨（裁切/遮挡）",
                "no-readback": "设计有节点、导出无墨（未提供回读，按发射端丢失归档）",
                "untracked": "设计有节点（无文字可比对），导出图上没有墨（裁切/遮挡）",
                "no-node": "设计里没有对应节点",
            }.get(str(target.get("status")), "设计有节点、导出无墨")
        items.append(
            {
                "index": index,
                "bucket": bucket,
                "kind": defect.get("kind"),
                "bbox": box,
                "expected_text": defect.get("expected_text") or "",
                "note": defect.get("note") or "",
                "node": {
                    "id": node.get("id"),
                    "type": node.get("type"),
                    "text": (node.get("text") or "")[:80],
                }
                if node
                else None,
                "evidence": evidence,
                "detail": detail,
            }
        )
    return items


def summarise(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {bucket: 0 for bucket in BUCKETS}
    for item in items:
        counts[item["bucket"]] = counts.get(item["bucket"], 0) + 1
    return {
        "total": len(items),
        "buckets": counts,
        "unjudgeable": sum(
            1
            for item in items
            if (item.get("evidence") or {}).get("ink_state") == "unjudgeable"
        ),
        "dismissed": sum(
            1
            for item in items
            if (item.get("evidence") or {}).get("ink_state") == "present"
        ),
        "styleMismatch": counts.get("style-mismatch", 0),
    }


#: 图例排版：色块、行距、字高、内边距（像素）。
LEGEND_ROW_H = 18
LEGEND_LEFT = 10
LEGEND_TEXT_X = 30
LEGEND_PAD = 6
LEGEND_SCALE = 0.45


def draw_overlay(rendered, items: list[dict[str, Any]]) -> Any:
    """Number every finding on the render, coloured by bucket.

    The buffer stays **RGB** the whole way: ``PIL`` reads the render as RGB, the
    bucket colours below are written as RGB triples, and ``save_overlay`` writes
    it back with PIL.  It used to be handed to ``cv2.imwrite``, which reads the
    same bytes as BGR — every red frame was drawn blue and the page's own blue
    buttons came out red.
    """
    import cv2
    import numpy as np

    canvas = np.ascontiguousarray(rendered.astype(np.uint8).copy())
    for item in items:
        x, y, w, h = item["bbox"]
        colour = BUCKET_COLOURS.get(item["bucket"], (0, 0, 0))
        cv2.rectangle(canvas, (x, y), (x + w, y + h), colour, 2)
        label = f"{item['index']}"
        anchor = (x + 2, max(12, y - 4))
        cv2.putText(canvas, label, anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 3)
        cv2.putText(canvas, label, anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1)
    # 图例先铺一块不透明底，再写色块与文字：四行字直接压在页面 Logo 上，
    # 谁也读不出来（左上角恰好是各页 logo / 侧栏标题所在）。
    widest = max(
        cv2.getTextSize(bucket, cv2.FONT_HERSHEY_SIMPLEX, LEGEND_SCALE, 1)[0][0]
        for bucket in BUCKETS
    )
    right = LEGEND_TEXT_X + widest + LEGEND_PAD
    bottom = 14 + (len(BUCKETS) - 1) * LEGEND_ROW_H + 2 + LEGEND_PAD
    cv2.rectangle(canvas, (2, 2), (right, bottom), (255, 255, 255), -1)
    cv2.rectangle(canvas, (2, 2), (right, bottom), (150, 150, 150), 1)
    for position, bucket in enumerate(BUCKETS):
        top = 14 + position * LEGEND_ROW_H
        cv2.rectangle(
            canvas, (LEGEND_LEFT, top - 10), (LEGEND_LEFT + 14, top + 2),
            BUCKET_COLOURS[bucket], -1,
        )
        cv2.putText(
            canvas,
            bucket,
            (LEGEND_TEXT_X, top),
            cv2.FONT_HERSHEY_SIMPLEX,
            LEGEND_SCALE,
            (30, 30, 30),
            1,
        )
    return canvas


def save_overlay(canvas, path: str | Path) -> None:
    """Write the RGB canvas as-is — no writer is allowed to swap channels."""
    import numpy as np
    from PIL import Image

    Image.fromarray(np.ascontiguousarray(canvas, dtype=np.uint8)).save(str(path))


def render_markdown(
    items: list[dict[str, Any]],
    summary: dict[str, Any],
    meta: dict[str, Any],
) -> str:
    lines = [
        "# QA 巡检报告（只读）",
        "",
        f"- 原图：`{meta.get('ref')}`",
        f"- 导出：`{meta.get('rendered')}`",
        f"- 设计：`{meta.get('design')}`"
        + (f"；IR：`{meta.get('ir')}`" if meta.get("ir") else "")
        + (f"；降级账本：`{meta.get('degradations')}`" if meta.get("degradations") else "")
        + (f"；回读：`{meta.get('readback')}`" if meta.get("readback") else ""),
        "",
        "## 分桶",
        "",
        "| 桶 | 含义 | 数量 |",
        "|---|---|---|",
    ]
    for bucket in BUCKETS:
        lines.append(
            f"| `{bucket}` | {BUCKET_LABELS[bucket]} | {summary['buckets'].get(bucket, 0)} |"
        )
    lines += [
        "",
        f"合计 **{summary['total']}** 处；其中 **{summary['dismissed']}** 处经像素证实"
        "「字/形在，只是样式不对」（`dismissed`），"
        f"**{summary.get('unjudgeable', 0)}** 处框内墨量不足以判定（`unjudgeable`），"
        f"`style-mismatch` 共 {summary['styleMismatch']} 处。",
        "",
        "## 逐条",
        "",
        "| # | 桶 | kind | bbox | 节点 | 墨量(原图/导出) | 说明 |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in items:
        node = item["node"] or {}
        lines.append(
            "| {i} | `{bucket}` | {kind} | {x},{y},{w},{h} | {node} | {src}/{out} | {detail} |".format(
                i=item["index"],
                bucket=item["bucket"],
                kind=item.get("kind") or "",
                x=item["bbox"][0],
                y=item["bbox"][1],
                w=item["bbox"][2],
                h=item["bbox"][3],
                node=(node.get("text") or node.get("id") or "—")[:24],
                src=item["evidence"].get("source_ink"),
                out=item["evidence"].get("rendered_ink"),
                detail=item["detail"],
            )
        )
    if not items:
        lines.append("| — | — | — | — | — | — | 本轮巡检没有点名任何缺陷 |")
    lines += [
        "",
        "> 本报告只读：不修改设计稿、不回滚补丁。`style-mismatch` 是样式问题，",
        "> 不要当缺失去补节点；`planned-degradation` 已在 `13_degradations.json` 记账。",
        "",
    ]
    return "\n".join(lines)


def _vision():
    """The multimodal client, or ``None`` when no key is configured."""
    try:
        from replay_pagegraph import _vision_callable

        return _vision_callable()
    except Exception:  # noqa: BLE001 - the script still runs without a model
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only QA inspection of one rendered page")
    parser.add_argument("--ref", required=True, help="reference screenshot")
    parser.add_argument("--rendered", required=True, help="export / render of the same page")
    parser.add_argument("--design", required=True, help="12_design.json or figma_design.json")
    parser.add_argument("--ir", default="", help="optional 13_design_ir.json")
    parser.add_argument("--degradations", default="", help="optional 13_degradations.json")
    parser.add_argument("--readback", default="", help="optional Figma tree / Axure inspect_rp")
    parser.add_argument("--out", required=True, help="report directory")
    parser.add_argument("--max-defects", type=int, default=arbiter.SWEEP_MAX_DEFECTS)
    parser.add_argument("--no-vlm", action="store_true", help="skip the model, emit an empty report")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ref = _image(args.ref)
    rendered = _image(args.rendered)
    if ref.shape != rendered.shape:
        raise SystemExit(
            f"size mismatch: ref {ref.shape[1]}x{ref.shape[0]} vs render "
            f"{rendered.shape[1]}x{rendered.shape[0]}"
        )
    design = _read_json(args.design)
    nodes = design_nodes(design)
    readback = readback_nodes(args.readback or None)
    degradations = _read_json(args.degradations) if args.degradations else None
    ir_doc = _read_json(args.ir) if args.ir else None

    elements = design_elements(design)
    defects: list[dict[str, Any]] = []
    status = "ok"
    if args.no_vlm:
        status = "skipped:no-vlm"
    else:
        vision = _vision()
        if vision is None:
            status = "skipped:no-vision-key"
        else:
            prompt = arbiter.sweep_prompt(
                arbiter.scene_digest(elements), max_defects=args.max_defects
            )
            answer = vision(prompt, arbiter.macro_panels(ref, rendered)) or {}
            defects = arbiter.parse_sweep_defects(answer)[: args.max_defects]

    items = classify(
        defects,
        ref=ref,
        rendered=rendered,
        nodes=nodes,
        readback=readback,
        degradations=degradations,
    )
    summary = summarise(items)
    meta = {
        "ref": str(Path(args.ref).resolve()),
        "rendered": str(Path(args.rendered).resolve()),
        "design": str(Path(args.design).resolve()),
        "ir": str(Path(args.ir).resolve()) if args.ir else "",
        "degradations": str(Path(args.degradations).resolve()) if args.degradations else "",
        "readback": str(Path(args.readback).resolve()) if args.readback else "",
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "read_only": True,
        "target": (degradations or {}).get("target"),
        "document_id": (ir_doc or {}).get("document_id")
        or (degradations or {}).get("document_id"),
        "source": meta,
        "summary": summary,
        "defects": items,
        "dismissed": [
            item
            for item in items
            if (item.get("evidence") or {}).get("ink_state") == "present"
        ],
        "unjudgeable": [
            item
            for item in items
            if (item.get("evidence") or {}).get("ink_state") == "unjudgeable"
        ],
        "limitations": [
            "The model names what looks wrong; the pixels and the design decide where it belongs.",
            "style-mismatch is not a missing node: patching it with setText makes the page worse.",
            "planned-degradation rows are target capability limits, not defects to fix in the design.",
        ],
    }
    (out / "qa_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "qa_report.md").write_text(
        render_markdown(items, summary, meta), encoding="utf-8"
    )
    save_overlay(draw_overlay(rendered, items), out / "qa_overlay.png")

    print(
        "[qa] invoked={total} perception-miss={pm} emitter-drift={ed} "
        "planned-degradation={pd} style-mismatch={sm} dismissed={d} unjudgeable={u}".format(
            total=summary["total"],
            pm=summary["buckets"]["perception-miss"],
            ed=summary["buckets"]["emitter-drift"],
            pd=summary["buckets"]["planned-degradation"],
            sm=summary["buckets"]["style-mismatch"],
            d=summary["dismissed"],
            u=summary.get("unjudgeable", 0),
        ),
        flush=True,
    )
    print(f"[qa] {out / 'qa_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
