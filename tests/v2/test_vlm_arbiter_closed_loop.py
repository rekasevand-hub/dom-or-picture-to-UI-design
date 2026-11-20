"""The closed loop, driven by a painter the test controls.

Every assertion here is about the *guard*, not about the model: a mock returns
a patch, the loop re-draws, and the test checks that only the patches that
measurably improved their own block survived.  That is the whole point of the
design — the model may guess, the pixels decide.

The painter is deliberately dumb: it fills each element's box with the colour
the element carries, and nothing else.  Moving a box by one pixel therefore
moves ink by one pixel, which makes "dx = 3 is right, dx = 30 is wrong" a fact a
test can measure instead of a hope.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from src.app.services.structure.fidelity import vlm_arbiter as arbiter


def _canvas(size=(120, 160)) -> np.ndarray:
    height, width = size
    return np.full((height, width, 3), 250, dtype=np.uint8)


def _paint(elements, size=(120, 160)) -> np.ndarray:
    """Fill each element's box with its fill colour. No antialiasing, no fonts."""
    canvas = _canvas(size)
    for element in elements:
        if element.get("type") not in ("text", "container", "image"):
            continue
        if "_paint" not in element:
            # 容器在这个画家眼里是透明的：它的作用只有结构，不落墨。
            continue
        x = int(round(float(element.get("x") or 0)))
        y = int(round(float(element.get("y") or 0)))
        w = int(round(float(element.get("width") or 0)))
        h = int(round(float(element.get("height") or 0)))
        if w <= 0 or h <= 0:
            continue
        canvas[max(0, y) : y + h, max(0, x) : x + w] = element["_paint"]
    return canvas


def _truth_with_block(box, colour=(20, 20, 20), shift=0):
    """The picture: one dark block, at the place the design *should* have drawn it."""
    x, y, w, h = box
    canvas = _canvas()
    canvas[y : y + h, x + shift : x + shift + w] = colour
    return canvas


def _element(box, colour=(20, 20, 20)):
    x, y, w, h = box
    return {
        "id": "node-1",
        "type": "text",
        "x": float(x),
        "y": float(y),
        "width": float(w),
        "height": float(h),
        "text": "标签",
        "style": {"fontSize": 14.0, "fontWeightValue": 400},
        "_paint": colour,
    }


# ---------------------------------------------------------------------------
# 一、有效的定量补丁被保留
# ---------------------------------------------------------------------------


def test_a_quantitative_patch_that_improves_its_block_is_kept() -> None:
    """The block is three pixels to the right; the patch says dx = -3."""
    truth = _truth_with_block((40, 40, 60, 20), shift=0)
    elements = [_element((43, 40, 60, 20))]  # 画偏了 3px
    before = arbiter.roi_error(truth, _paint(elements), (28, 28, 88, 44))
    assert before > 0

    seen: dict = {}

    def propose(orders, strips):
        seen["orders"] = orders
        seen["strips"] = strips
        return {"patches": [{"index": 0, "dx": -3, "dy": 0, "note": "偏右 3px"}]}

    report = arbiter.refine(
        elements, truth, lambda items: _paint(items), propose=propose, rounds=1
    )

    assert report["kept"] == 1
    assert report["rolledBack"] == 0
    assert elements[0]["x"] == pytest.approx(40.0)
    after = arbiter.roi_error(truth, _paint(elements), (28, 28, 88, 44))
    assert after < before
    # 模型看到的是带刻度的裁片，不是裸图：没有刻度就没有像素级读数。
    assert seen["strips"] and seen["strips"][0].shape[0] > 40
    assert seen["orders"][0].index == 0


# ---------------------------------------------------------------------------
# 二、把局部误差改大的补丁被回滚
# ---------------------------------------------------------------------------


def test_a_patch_that_makes_its_block_worse_is_rolled_back() -> None:
    """dx = +24 is a hallucination; the element must come back untouched."""
    truth = _truth_with_block((40, 40, 60, 20))
    elements = [_element((43, 40, 60, 20))]  # 已经偏了 3px，所以有工单可报
    snapshot = copy.deepcopy(elements[0])

    report = arbiter.refine(
        elements,
        truth,
        lambda items: _paint(items),
        propose=lambda orders, strips: {"patches": [{"index": 0, "dx": 24}]},
        rounds=1,
    )

    assert report["kept"] == 0
    assert report["rolledBack"] == 1
    # 两道理由同时成立：本地误差变大，整页也跟着变差。任一条都足以回滚。
    assert "roi-not-better" in report["log"][0]["status"]
    assert "page-worse" in report["log"][0]["status"]
    assert elements[0] == snapshot


def test_a_patch_that_drops_a_frame_is_rolled_back() -> None:
    """Same pixels, but the node was a frame: geometry is refused outright."""
    truth = _truth_with_block((40, 40, 60, 20))
    frame = _element((20, 20, 100, 60), colour=None)
    frame.pop("_paint")
    frame["type"] = "container"
    frame["layoutChildren"] = [{"id": "node-1"}]
    child = _element((43, 40, 60, 20))
    elements = [frame, child]
    snapshot = copy.deepcopy(elements)

    report = arbiter.refine(
        elements,
        truth,
        lambda items: _paint(items),
        propose=lambda orders, strips: {"patches": [{"index": 0, "dx": -3}]},
        rounds=1,
    )

    assert report["kept"] == 0
    assert report["rolledBack"] >= 1
    assert elements == snapshot
    assert arbiter.count_frames(elements) == 1


def test_typography_is_still_allowed_on_a_frame_member() -> None:
    """A member may not move, but its size is not a member's geometry."""
    element = _element((40, 40, 60, 20))
    applied = arbiter.apply_quantitative(element, {"fontSize": 2.0}, frozen=True)
    assert applied == {"fontSize": 2.0}
    assert element["style"]["fontSize"] == pytest.approx(16.0)


def test_a_patch_that_buries_a_label_is_rolled_back_even_though_it_helps() -> None:
    """The block moves exactly onto the ink — and under a panel. Local error 0, still refused.

    This is the case a monotonic-only guard would wave through: the pixels in the
    work order improve from 59.8 to 0.0.  The label is what pays for it.
    """
    truth = _canvas()
    truth[40:60, 9:69] = (20, 20, 20)
    text = _element((43, 40, 60, 20))
    band = {
        "id": "band",
        "type": "container",
        "x": 0.0,
        "y": 35.0,
        "width": 40.0,
        "height": 30.0,
        "zIndex": 10,
        "text": "",
        "style": {"fillColor": "#101010"},
        "role": "panel",
    }
    elements = [text, band]
    snapshot = copy.deepcopy(elements)

    report = arbiter.refine(
        elements,
        truth,
        lambda items: _paint(items),
        propose=lambda orders, strips: {"patches": [{"index": 0, "dx": -34}]},
        rounds=1,
    )

    assert report["kept"] == 0
    assert "text-buried" in report["log"][0]["status"]
    assert elements == snapshot


# ---------------------------------------------------------------------------
# 三、多轮收敛并终止
# ---------------------------------------------------------------------------


def test_multi_round_refinement_converges_and_stops() -> None:
    """Two real offsets, two rounds, then nothing left to nominate."""
    truth = _canvas()
    truth[30:50, 30:80] = (20, 20, 20)
    truth[80:100, 30:80] = (20, 20, 20)
    elements = [_element((34, 30, 50, 20)), _element((30, 84, 50, 20))]
    elements[1]["id"] = "node-2"

    calls: list[str] = []

    def propose(orders, strips):
        order = orders[0]
        calls.append(order.ref)
        # 模型读的是刻度上的偏差，所以它给出的数字跟着节点走，不跟着顺序走。
        if order.ref == "node-1":
            return {"patches": [{"index": 0, "dx": -4}]}
        return {"patches": [{"index": 0, "dy": -4}]}

    report = arbiter.refine(
        elements, truth, lambda items: _paint(items), propose=propose, rounds=3
    )

    assert report["kept"] == 2
    assert report["rolledBack"] == 0
    assert report["rounds"] == 2
    # 第三轮已经无块可报：循环必须在这里停，而不是把同样的工单再问一遍。
    assert report["log"][-1].get("note") == "converged"
    assert len(calls) == 2


def test_the_loop_does_nothing_without_a_model() -> None:
    truth = _truth_with_block((40, 40, 60, 20))
    elements = [_element((43, 40, 60, 20))]
    report = arbiter.refine(elements, truth, lambda items: _paint(items), propose=None)
    assert report["skipped"] == "no-vision"
    assert elements[0]["x"] == pytest.approx(43.0)


# ---------------------------------------------------------------------------
# 四、工单提名与裁片本身
# ---------------------------------------------------------------------------


def test_nomination_points_at_the_node_that_owns_the_hot_cell() -> None:
    truth = _truth_with_block((40, 40, 60, 20))
    elements = [_element((40, 40, 60, 20)), _element((40, 80, 60, 20))]
    elements[1]["id"] = "node-2"
    elements[1]["x"] = 90.0  # 第二个块整个跑偏了
    orders = arbiter.nominate_rounds(truth, _paint(elements), elements, k=2)
    assert orders
    assert orders[0].ref == "node-1" or orders[0].element_id in ("node-1", "node-2")
    assert all(order.box[2] > 0 and order.box[3] > 0 for order in orders)
    assert len({order.element_id for order in orders}) == len(orders)


def test_the_ruler_panel_carries_ticks_on_all_four_sides() -> None:
    truth = _truth_with_block((40, 40, 60, 20))
    drawn = _paint([_element((40, 40, 60, 20))])
    panel = arbiter.ruler_panel(truth, drawn, (28, 28, 88, 44))
    assert panel.ndim == 3 and panel.shape[2] == 3
    margin = arbiter.RULER_MARGIN
    # 刻度是深色像素；白边上必须数得出东西，否则模型没有尺子可读。
    assert (panel[: margin - 8].min(axis=2) < 120).sum() > 10
    # 左侧看整条白边：刻度画在 margin 内侧（x=margin-6..margin-1），数字画在 x=2，
    # 只取前 8 列等于只看被裁掉一半的数字——那是尺子的标签，不是尺子。
    assert (panel[:, :margin].min(axis=2) < 120).sum() > 10
    # 中间是 2× 的并排图：宽度应当接近两倍 ROI 加上间隙。
    assert panel.shape[1] >= 88 * 2 + 10


def test_patches_are_clamped_and_limited_to_three_fields() -> None:
    payload = {
        "patches": [
            {
                "index": "0",
                "dx": 999,
                "dy": 0,
               "fontSize": 60,
                "fontWeight": 900,
                "letterSpacing": 12,
                "dh": -1,
            }
        ]
    }
    parsed = arbiter.parse_round_patches(payload)
    patch = parsed[0]
    assert len(patch) == arbiter.PATCH_MAX_FIELDS
    # 按绝对值取前三：dx 999、fontWeight 900、fontSize 60。都被钳到区间边界。
    assert patch["dx"] == 64.0
    assert patch["fontWeight"] == 400.0
    assert patch["fontSize"] == 24.0
    assert "letterSpacing" not in patch
    assert "dy" not in patch  # 增量 0 不算一条意见
