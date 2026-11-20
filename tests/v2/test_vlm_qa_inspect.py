"""The read-only QA pass: name the flaw, prove the stage.

The model only answers "what looks wrong".  ``still_missing``, the design boxes,
the degradation ledger and the target readback decide which of four stages owns
it — and the script must never touch the design while doing so.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _path in (_ROOT, _ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import vlm_qa_inspect as qa  # noqa: E402


def _canvas() -> np.ndarray:
    return np.full((60, 120, 3), 250, dtype=np.int16)


def _truth() -> np.ndarray:
    canvas = _canvas()
    for y in (10, 30):
        for x in (10, 60):
            canvas[y : y + 10, x : x + 40] = 20
    return canvas


def _rendered() -> np.ndarray:
    """Only the last block survives — one of four is present."""
    canvas = _canvas()
    canvas[30:40, 60:100] = 20
    return canvas


def _node(node_id: str, box: list[int], text: str = "") -> dict:
    return {"id": node_id, "type": "text" if text else "container", "role": "", "text": text, "box": box}


def test_each_stage_owns_its_own_bucket() -> None:
    nodes = [
        _node("t2", [10, 30, 40, 10], "第二块"),   # 设计有、渲染没墨 → 发射端
        _node("t3", [60, 10, 40, 10], "第三块"),   # 降级账本里点名 → 计划内降级
        _node("t4", [60, 30, 40, 10], "第四块"),   # 渲染有墨 → 样式
    ]
    degradations = {
        "target": "axure",
        "degradations": [
            {"feature": "auto-layout", "fallback": "fixed-coordinate", "source_node_ids": ["t3"]}
        ],
    }
    readback = [{"id": "n2", "text": "别的文字", "name": "", "box": [10, 30, 40, 10]}]
    defects = [
        {"kind": "missing-text", "bbox": [10, 10, 40, 10]},   # 设计里没有节点
        {"kind": "missing-text", "bbox": [10, 30, 40, 10]},
        {"kind": "missing-text", "bbox": [60, 10, 40, 10]},
        {"kind": "missing-text", "bbox": [60, 30, 40, 10]},
    ]

    items = qa.classify(
        defects,
        ref=_truth(),
        rendered=_rendered(),
        nodes=nodes,
        readback=readback,
        degradations=degradations,
    )

    assert [item["bucket"] for item in items] == [
        "perception-miss",
        "emitter-drift",
        "planned-degradation",
        "style-mismatch",
    ]
    summary = qa.summarise(items)
    assert summary["total"] == 4
    assert summary["dismissed"] == 1
    assert summary["styleMismatch"] == 1
    # 降级那一桶要带上账本里的原话，报告才可追溯到 13_degradations.json
    assert items[2]["evidence"]["degradation"]["feature"] == "auto-layout"


def test_a_present_word_is_style_not_missing() -> None:
    """The 11.5px table text: inked on both sides, so it is not a missing word."""
    truth = _truth()
    rendered = truth.copy()  # 墨都在（哪怕小一号）
    nodes = [_node("t1", [10, 10, 40, 10], "有字")]

    items = qa.classify(
        [{"kind": "missing-text", "bbox": [10, 10, 40, 10]}],
        ref=truth,
        rendered=rendered,
        nodes=nodes,
        readback=[],
        degradations=None,
    )

    assert items[0]["bucket"] == "style-mismatch"
    assert items[0]["evidence"]["still_missing"] is False
    assert items[0]["evidence"]["ink_share"] > 0.9


def test_readback_turns_lost_into_displaced() -> None:
    node = _node("t2", [10, 30, 40, 10], "第二块")
    displaced = [{"id": "n9", "text": "第二块", "name": "", "box": [10, 41, 40, 10]}]

    evidence = qa._readback_evidence(node, displaced)

    assert evidence["status"] == "displaced"
    assert evidence["dy"] == 11


def test_readback_says_absent_when_the_text_is_gone() -> None:
    node = _node("t2", [10, 30, 40, 10], "第二块")

    assert qa._readback_evidence(node, [{"id": "x", "text": "别的", "box": [0, 0, 1, 1]}])[
        "status"
    ] == "absent-in-target"


def test_readback_nodes_reads_a_figma_tree_and_an_axure_dump(tmp_path: Path) -> None:
    figma = {
        "type": "FRAME",
        "absolute": {"x": 0, "y": 0, "width": 100, "height": 50},
        "children": [
            {
                "type": "TEXT",
                "id": "1:1",
                "characters": "标题",
                "absolute": {"x": 4, "y": 6, "width": 40, "height": 12},
            }
        ],
    }
    figma_path = tmp_path / "readback.json"
    figma_path.write_text(json.dumps(figma), encoding="utf-8")
    rows = qa.readback_nodes(figma_path)
    assert any(row["text"] == "标题" and row["box"] == [4, 6, 40, 12] for row in rows)

    axure = {
        "pages": [
            {
                "widgets": [
                    {
                        "label": "按钮",
                        "text": "按钮",
                        "geometry": {"x": 8, "y": 9, "width": 30, "height": 14},
                    }
                ]
            }
        ]
    }
    axure_path = tmp_path / "inspect.json"
    axure_path.write_text(json.dumps(axure), encoding="utf-8")
    rows = qa.readback_nodes(axure_path)
    assert rows and rows[0]["text"] == "按钮" and rows[0]["box"] == [8, 9, 30, 14]


def test_the_script_writes_three_read_only_artefacts(tmp_path: Path) -> None:
    from PIL import Image

    ref_path = tmp_path / "ref.png"
    render_path = tmp_path / "render.png"
    Image.fromarray(_truth().astype(np.uint8)).save(ref_path)
    Image.fromarray(_rendered().astype(np.uint8)).save(render_path)
    design_path = tmp_path / "12_design.json"
    design_path.write_text(
        json.dumps(
            {
                "canvas": {"width": 120, "height": 60},
                "elements": [
                    {
                        "id": "t3",
                        "type": "text",
                        "x": 60,
                        "y": 10,
                        "width": 40,
                        "height": 10,
                        "text": "第三块",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    before = design_path.read_bytes()
    out = tmp_path / "qa"

    code = qa.main(
        [
            "--ref",
            str(ref_path),
            "--rendered",
            str(render_path),
            "--design",
            str(design_path),
            "--out",
            str(out),
            "--no-vlm",
        ]
    )

    assert code == 0
    assert (out / "qa_report.json").is_file()
    assert (out / "qa_report.md").is_file()
    assert (out / "qa_overlay.png").is_file()
    report = json.loads((out / "qa_report.json").read_text(encoding="utf-8"))
    assert report["read_only"] is True
    assert report["status"] == "skipped:no-vlm"
    # 只读：设计稿一个字节都不能动。
    assert design_path.read_bytes() == before


def test_the_markdown_lists_every_bucket() -> None:
    items = [
        {
            "index": 1,
            "bucket": "style-mismatch",
            "kind": "missing-text",
            "bbox": [1, 2, 3, 4],
            "expected_text": "",
            "note": "",
            "node": {"id": "t1", "type": "text", "text": "字"},
            "evidence": {"source_ink": 10, "rendered_ink": 9},
            "detail": "在图上",
        }
    ]
    summary = qa.summarise(items)

    text = qa.render_markdown(items, summary, {"ref": "a.png", "rendered": "b.png", "design": "c.json"})

    for bucket in qa.BUCKETS:
        assert bucket in text
    assert "只读" in text


def test_the_overlay_keeps_red_and_blue_where_they_were(tmp_path: Path) -> None:
    """A blue page stays blue and the red frame stays red.

    The canvas is RGB all the way to ``save_overlay``; it used to be handed to
    ``cv2.imwrite``, which reads the same buffer as BGR — every red frame was
    painted blue and the page's blue buttons came out red.
    """
    from PIL import Image

    page = np.zeros((80, 360, 3), dtype=np.int16)
    page[:, :] = (32, 84, 200)  # RGB，一页蓝底
    # 框放在图例面板右侧，免得白底面板把标注一起盖掉。
    items = [{"index": 1, "bucket": "perception-miss", "bbox": [240, 40, 40, 20]}]

    path = tmp_path / "qa_overlay.png"
    qa.save_overlay(qa.draw_overlay(page, items), path)
    saved = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)

    # 没被画到的页面：仍然是蓝的（B 最高）。通道一旦对调，这里会变红。
    assert saved[70, 340, 2] > saved[70, 340, 0] + 80
    # 标注仍是红框：perception-miss 的 R 高、B 低。
    border = saved[40, 240]
    assert border[0] > 180 and border[2] < 80


def test_the_legend_gets_its_own_backing(tmp_path: Path) -> None:
    """Four lines of legend over a dark logo are unreadable without a panel."""
    import cv2
    from PIL import Image

    page = np.zeros((80, 260, 3), dtype=np.int16)
    page[:, :] = (12, 12, 12)  # 深色侧栏：不铺底就完全看不见图例

    path = tmp_path / "qa_overlay.png"
    qa.save_overlay(qa.draw_overlay(page, []), path)
    saved = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)

    widest = max(
        cv2.getTextSize(bucket, cv2.FONT_HERSHEY_SIMPLEX, qa.LEGEND_SCALE, 1)[0][0]
        for bucket in qa.BUCKETS
    )
    right = qa.LEGEND_TEXT_X + widest + qa.LEGEND_PAD

    # 面板内是白底（三通道都高），面板外仍是页面的深色。
    assert saved[4, 4].min() > 240
    assert saved[4, right - 2].min() > 240
    assert saved[4, right + 6].max() < 40
    # 色块仍画在白底上：第一行是 perception-miss 的红块。
    swatch = saved[14, qa.LEGEND_LEFT + 2]
    assert swatch[0] > 150 and swatch[2] < 80
