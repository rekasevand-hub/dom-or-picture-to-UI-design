"""Container-level split and merge, as a structural action with a pixel verdict.

The model is asked exactly one thing per candidate: is this container's extent
right?  It cannot invent a container, a member, or a coordinate — and even when
it says yes, the edit only survives if the band it exposes actually looked wrong
in the first place.

The painter is the same dumb one the quantitative tests use: a container is a
filled box, a member is a filled box painted after it.  That is enough to make
"the container was painting the gutter dark" a measurable fact.
"""

from __future__ import annotations

import copy

import numpy as np

from src.app.services.structure.fidelity import vlm_arbiter as arbiter


def _canvas(size=(120, 160)) -> np.ndarray:
    height, width = size
    return np.full((height, width, 3), 250, dtype=np.uint8)


def _box(id_, x, y, w, h, colour=None, kind="text") -> dict:
    element = {
        "id": id_,
        "type": kind,
        "x": float(x),
        "y": float(y),
        "width": float(w),
        "height": float(h),
        "text": "" if kind != "text" else id_,
        "style": {},
    }
    if colour is not None:
        element["_paint"] = colour
    return element


def _paint(elements):
    canvas = _canvas()
    for element in elements:
        if element.get("type") not in ("text", "container", "image"):
            continue
        if "_paint" not in element:
            continue
        x, y = int(round(element["x"])), int(round(element["y"]))
        w, h = int(round(element["width"])), int(round(element["height"]))
        if w <= 0 or h <= 0:
            continue
        canvas[max(0, y) : y + h, max(0, x) : x + w] = element["_paint"]
    return canvas


def _swallowing_container():
    """A dark container over two dark blocks with a light gutter between them.

    The gutter is the page showing through; the container is painting over it.
    """
    truth = _canvas()
    truth[10:30, 10:70] = (20, 20, 20)
    truth[50:70, 10:70] = (20, 20, 20)
    container = _box("card", 0, 0, 80, 100, colour=(20, 20, 20), kind="container")
    container["style"] = {"fillColor": "#141414"}
    container["layoutChildren"] = [{"id": "a"}, {"id": "b"}]
    elements = [container, _box("a", 10, 10, 60, 20, colour=(20, 20, 20)), _box("b", 10, 50, 60, 20, colour=(20, 20, 20))]
    return truth, elements


def test_a_container_painting_over_a_gutter_is_nominated_and_split() -> None:
    truth, elements = _swallowing_container()
    candidates = arbiter.nominate_wireframes(elements, truth)
    assert candidates, "容器把 40..50 那条浅色缝涂黑了，应当被提名"
    assert candidates[0].op == "split"
    assert 40 <= candidates[0].at <= 50

    report = arbiter.refine_structure(
        elements,
        truth,
        _paint,
        propose=lambda cands, panels: {"wireframes": [{"index": 0, "op": "split"}]},
    )

    assert report["kept"] == 1, report
    halves = [item for item in elements if str(item.get("id", "")).startswith("card")]
    assert len(halves) == 2
    # 成员一个都没丢，而且各自归到正确的那一半。
    assert {child["id"] for item in halves for child in item["layoutChildren"]} == {"a", "b"}
    assert arbiter.count_frames(elements) == 2


def test_the_cut_lands_on_the_seam_so_the_seam_shows_through() -> None:
    """The point of the split: the band stops being painted, it is not merely divided."""
    truth, elements = _swallowing_container()
    candidate = arbiter.nominate_wireframes(elements, truth)[0]
    assert arbiter.apply_split(elements, candidate)

    halves = [item for item in elements if str(item.get("id", "")).startswith("card")]
    assert len(halves) == 2
    # 上段止于缝的上沿，下段始于缝的下沿：中间那 20px 不属于任何一层。
    assert halves[0]["y"] + halves[0]["height"] == 30
    assert halves[1]["y"] == 50
    painted = _paint(elements)
    assert (painted[30:50, 10:70] == 250).all()


def test_a_declined_wireframe_changes_nothing() -> None:
    truth, elements = _swallowing_container()
    snapshot = copy.deepcopy(elements)
    report = arbiter.refine_structure(
        elements, truth, _paint, propose=lambda cands, panels: {"wireframes": []}
    )
    assert report["kept"] == 0 and report["rolledBack"] == 0
    assert elements == snapshot


def test_a_split_with_no_member_on_one_side_is_refused() -> None:
    """Every member below the band: the lower half would be an empty shell."""
    truth = _canvas()
    container = _box("card", 0, 0, 80, 100, colour=(20, 20, 20), kind="container")
    container["style"] = {"fillColor": "#141414"}
    container["layoutChildren"] = [{"id": "a"}, {"id": "b"}]
    elements = [
        container,
        _box("a", 10, 50, 60, 20, colour=(20, 20, 20)),
        _box("b", 10, 72, 60, 20, colour=(20, 20, 20)),
    ]
    snapshot = copy.deepcopy(elements)
    wireframe = arbiter.Wireframe(index=0, op="split", refs=["card"], axis="y", at=35.0, box=[0, 30, 80, 20])
    assert not arbiter.apply_split(elements, wireframe)
    assert elements == snapshot


def test_two_containers_split_by_a_child_are_merged() -> None:
    """Top and bottom card with a chip between them; the chip is nobody's child."""
    truth = _canvas()
    truth[0:40, 0:80] = (30, 30, 30)
    truth[40:56, 20:60] = (90, 90, 90)
    truth[56:100, 0:80] = (30, 30, 30)

    upper = _box("upper", 0, 0, 80, 40, colour=(30, 30, 30), kind="container")
    upper["layoutChildren"] = [{"id": "top-text"}]
    upper["style"] = {"fillColor": "#1e1e1e"}
    lower = _box("lower", 0, 56, 80, 44, colour=(30, 30, 30), kind="container")
    lower["layoutChildren"] = [{"id": "bottom-text"}]
    lower["style"] = {"fillColor": "#1e1e1e"}
    chip = _box("chip", 0, 40, 80, 16, colour=(90, 90, 90))
    elements = [upper, lower, chip, _box("top-text", 8, 8, 40, 10, colour=(30, 30, 30)), _box("bottom-text", 8, 66, 40, 10, colour=(30, 30, 30))]

    candidates = arbiter.nominate_wireframes(elements, truth)
    merges = [item for item in candidates if item.op == "merge"]
    assert merges, candidates

    report = arbiter.refine_structure(
        elements,
        truth,
        _paint,
        propose=lambda cands, panels: {
            "wireframes": [{"index": item.index, "op": "merge"} for item in cands if item.op == "merge"]
        },
    )

    assert report["kept"] >= 1, report
    assert arbiter.count_frames(elements) == 1
    assert any(str(item.get("id")) == "chip" for item in elements)
    merged = next(item for item in elements if str(item.get("id")) == "upper")
    assert {child["id"] for child in merged["layoutChildren"]} == {"top-text", "bottom-text"}


def test_the_band_verdict_is_the_one_that_saves_the_page() -> None:
    """Same edit, two pictures: only the one where the band was wrong survives."""
    wireframe = arbiter.Wireframe(index=0, op="split", refs=["card"], axis="y", at=45.0, box=[0, 40, 80, 10])
    before = {"frames": 1, "collisions": 0, "covered": 0}
    after = {"frames": 2, "collisions": 0, "covered": 0}

    assert arbiter.check_wireframe([], wireframe, before=before, after=after, band_error=(220.0, 0.0)) == []
    # 切开了，但那一带本来就是这个颜色：白切一刀，没有任何收益。
    assert arbiter.check_wireframe([], wireframe, before=before, after=after, band_error=(5.0, 5.0)) == [
        "band-not-better"
    ]
    # 帧数对不上（成员被切丢了）时，像素再好也不算通过。
    assert "frames-wrong" in arbiter.check_wireframe(
        [], wireframe, before=before, after={**after, "frames": 3}, band_error=(220.0, 0.0)
    )
    # 合并只要求不变差：它不会制造新的像素材质。
    merge = arbiter.Wireframe(index=1, op="merge", refs=["a", "b"], axis="y", at=40.0, box=[0, 36, 80, 8])
    assert arbiter.check_wireframe([], merge, before={**before, "frames": 2}, after=before, band_error=(5.0, 6.0)) == [
        "band-worse"
    ]


def test_the_wireframe_panel_draws_the_boxes_and_the_ruler() -> None:
    truth, elements = _swallowing_container()
    candidate = arbiter.nominate_wireframes(elements, truth)[0]
    drawn = _paint(elements)
    panel = arbiter.wireframe_panel(truth, drawn, elements, candidate)
    assert panel.ndim == 3 and panel.shape[2] == 3
    assert panel.shape[1] > 80 * arbiter.ROUND_ZOOM
    # 蓝框/灰框/绿线都是画上去的深色像素，白边也还在。
    assert (panel.min(axis=2) < 120).sum() > 50
    assert (panel[0].min(axis=1) >= 250).all()
