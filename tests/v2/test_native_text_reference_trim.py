"""参考侧宽度锚定：窗口里混进邻居时，按我们自己的渲染宽把它裁掉。

背景（2026-11-13 实测）：`¥20.24` 字号 47px 时，与右边 `起 ¥23.0` 的间隔只有 21px
（0.45em），比正常词间距（0.72em）还小 —— 任何 em 阈值都分不开「邻居」和「词」。
所以判据换成宽度先验：参考宽超过渲染宽 1.6 倍就是读数不可信，从两端裁。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from src.app.services.evidence.native_text_quality import (
    REFERENCE_WIDTH_RATIO_MAX,
    _contrast_mask,
    _selected_ink,
    build_native_text_quality,
)

REGIONS = [{"id": "page", "role": "page", "bbox": [0, 0, 200, 100]}]
NODE = [40, 20, 120, 8]


def _images(tmp_path: Path) -> tuple[Path, Path]:
    """参考图里正文 + 邻居；渲染图里只有正文（同一位置、同一宽度）。"""
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    image = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 20, 79, 27), fill="black")  # 正文，40px 宽
    draw.rectangle((100, 20, 139, 27), fill="black")  # 邻居，与正文隔 20px
    image.save(reference)
    only = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(only).rectangle((40, 20, 79, 27), fill="black")
    only.save(rendered)
    return reference, rendered


def _design() -> dict:
    return {
        "elements": [
            {
                "type": "text",
                "contentRef": "text:price",
                "text": "20.24",
                "style": {"fontSize": 16},
                "styleEvidence": {
                    # 感知给的框比正文宽一倍，正好把邻居装进来（真实 case 的形状）
                    "evidence": {"source_bbox": [40, 20, 120, 8]}
                },
            }
        ]
    }


def _readback() -> dict:
    return {
        "type": "FRAME",
        "children": [
            {
                "type": "TEXT",
                "characters": "20.24",
                "bounds": {"x": NODE[0], "y": NODE[1], "width": NODE[2], "height": NODE[3]},
            }
        ],
    }


def _report(tmp_path: Path):
    reference, rendered = _images(tmp_path)
    return build_native_text_quality(
        _design(), _readback(), str(reference), str(rendered), REGIONS
    )


def _mask(path: Path, window: list[int]) -> np.ndarray:
    """按窗口裁好的墨迹掩码 —— `_selected_ink` 的入参就是这个形状。"""
    image = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
    x, y, width, height = window
    return _contrast_mask(image[y : y + height, x : x + width])


def test_without_a_target_the_span_swallows_the_neighbour(tmp_path: Path) -> None:
    reference, _ = _images(tmp_path)
    window = [36, 16, 128, 16]
    ink = _selected_ink(_mask(reference, window), window, NODE, 16.0, 0.35, True)
    assert ink is not None
    assert ink[2] == 100  # 40..139：正文 + 邻居


def test_target_trims_back_to_the_text(tmp_path: Path) -> None:
    reference, _ = _images(tmp_path)
    window = [36, 16, 128, 16]
    ink = _selected_ink(_mask(reference, window), window, NODE, 16.0, 0.35, True, 40.0)
    assert ink is not None
    assert ink[0] == 40
    assert ink[2] == 40  # 裁掉邻居，回到正文本身


def test_width_delta_no_longer_reports_the_neighbour(tmp_path: Path) -> None:
    owner = _report(tmp_path)["owners"][0]
    assert owner["renderedInkBBox"][2] == 40
    assert owner["referenceInkBBox"][2] == 40
    assert owner["widthDelta"] == 0
    assert owner["checks"]["size"] is True


def test_the_ratio_threshold_is_the_documented_one() -> None:
    """阈值变了要同时改文档：它是「读数不可信」的判据，不是「差得多」的判据。"""
    assert REFERENCE_WIDTH_RATIO_MAX == 1.6


def test_reverse_direction_is_flagged_but_not_trimmed(tmp_path: Path) -> None:
    """渲染比参考宽一倍时不裁参考，只记账。

    这一支的根因在渲染侧（元素被合并过），裁参考只会把读数改错。
    `light-table` 的 `项目名称` 就是这种：参考 89、我们 195。
    """
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    Image.new("RGB", (200, 100), "white")  # 占位，下面覆盖保存
    image = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(image).rectangle((40, 20, 79, 27), fill="black")
    image.save(reference)
    wide = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(wide).rectangle((40, 20, 139, 27), fill="black")
    wide.save(rendered)

    report = build_native_text_quality(
        _design(), _readback(), str(reference), str(rendered), REGIONS
    )
    owner = report["owners"][0]
    assert owner["referenceInkBBox"][2] == 40  # 参考没被改动
    assert owner["renderedInkBBox"][2] == 100
    assert owner["referenceWidthSuspect"] is True
    assert report["summary"]["referenceWidthSuspectCount"] == 1


def test_width_tolerance_still_uses_the_policy_ratio(tmp_path: Path) -> None:
    """容差必须仍然是 `max(3, 3% × 参考宽)`。

    回归用：曾经为了记 `referenceWidthSuspect` 在这里引入了一个同名局部变量
    `width_ratio`，把策略里的 0.03 遮蔽成「参考/渲染比」（≈1.0），容差从 3 变成上百，
    size 判据等于被悄悄废掉——五族会凭空多出 23 条通过。这条测试就是钉住它。
    """
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    image = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(image).rectangle((40, 20, 79, 27), fill="black")  # 宽 40
    image.save(reference)
    wider = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(wider).rectangle((40, 20, 83, 27), fill="black")  # 宽 44
    wider.save(rendered)

    design = _design()
    design["elements"][0]["styleEvidence"]["evidence"]["source_bbox"] = [40, 20, 44, 8]
    readback = _readback()
    readback["children"][0]["bounds"] = {"x": 40, "y": 20, "width": 44, "height": 8}
    owner = build_native_text_quality(
        design, readback, str(reference), str(rendered), REGIONS
    )["owners"][0]

    assert owner["widthDelta"] == 4
    # 3% × 40 = 1.2，取 floor（默认 2 / 策略 3），量级必须是「个位数」。
    # 被遮蔽时这里是 round(40 × 40/44) = 36 —— 差一个数量级，一眼就能抓住。
    assert owner["widthTolerance"] <= 3
    assert owner["checks"]["size"] is False
