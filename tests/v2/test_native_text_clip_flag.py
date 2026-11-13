from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from src.app.services.evidence.native_text_quality import (
    _clip_sides,
    build_native_text_quality,
)

REGIONS = [{"id": "page", "role": "page", "bbox": [0, 0, 200, 100]}]


def _report(tmp_path: Path, ink_box: tuple[int, int, int, int]):
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    for path in (reference, rendered):
        image = Image.new("RGB", (200, 100), "white")
        ImageDraw.Draw(image).rectangle(ink_box, fill="black")
        image.save(path)
    design = {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:label",
                "text": "Label",
                "styleEvidence": {
                    # 与节点框一致：让 union 不放大窗口，本测试只关心"贴边标志"
                    "evidence": {
                        "source_bbox": [20, 20, 40, 8],
                        "ink_bbox": [20, 20, 40, 8],
                    }
                },
            }
        ]
    }
    readback = {
        "type": "FRAME",
        "children": [
            {
                "type": "TEXT",
                "characters": "Label",
                "bounds": {"x": 20, "y": 20, "width": 40, "height": 8},
            }
        ],
    }
    return build_native_text_quality(
        design, readback, str(reference), str(rendered), REGIONS
    )


def test_clip_sides_names_only_the_edges_the_ink_sits_on() -> None:
    window = [10, 10, 100, 20]
    assert _clip_sides([60, 15, 20, 6], window) == []
    assert _clip_sides([10, 15, 20, 6], window) == ["left"]
    assert _clip_sides([90, 15, 20, 6], window) == ["right"]
    assert _clip_sides([10, 15, 100, 6], window) == ["left", "right"]
    assert _clip_sides([10, 10, 100, 20], window) == [
        "left",
        "right",
        "top",
        "bottom",
    ]


def test_reference_filling_the_window_is_flagged(tmp_path: Path) -> None:
    # 节点框 (20,20,40,8) → 窗口 (16,16,48,16)；墨迹横向量到窗口两侧
    # （纵向留白，否则整块墨迹会把 contrast mask 的中位数压成墨色，量不出东西）。
    report = _report(tmp_path, (16, 20, 63, 26))
    owner = report["owners"][0]
    assert owner["measureBBox"] == [16, 16, 48, 16]
    assert owner["referenceClipped"] is True
    assert {"left", "right"} <= set(owner["referenceClippedSides"])


def test_reference_inside_the_window_is_not_flagged(tmp_path: Path) -> None:
    report = _report(tmp_path, (24, 20, 52, 26))
    owner = report["owners"][0]
    assert owner["referenceClipped"] is False
    assert owner["referenceClippedSides"] == []
    assert report["summary"]["referenceClippedCount"] == 0


def test_the_flag_never_blocks_a_passing_owner(tmp_path: Path) -> None:
    """零行为变更：贴边可以同时是 pass。判据一个字都没动。"""
    report = _report(tmp_path, (16, 20, 63, 26))
    owner = report["owners"][0]
    assert owner["referenceClipped"] is True
    assert owner["status"] == "pass"
    assert owner["checks"] == {
        "coverage": True,
        "edgeF1": True,
        "position": True,
        "size": True,
    }
    assert report["summary"]["referenceClippedCount"] == 1
    assert report["acceptance_effect"] == "none"
