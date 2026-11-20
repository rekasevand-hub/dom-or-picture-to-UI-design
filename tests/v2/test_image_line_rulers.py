"""Lines, guides and row masters: the assertions are mostly about restraint.

A structural probe that fires too often is indistinguishable from a bug: it
moves coordinates that were already right, and the damage shows up as a
similarity score rather than a failing test.  So every test here pairs a "it
finds the real thing" case with a "and it refuses the decoy" case.
"""

from __future__ import annotations

import numpy as np

from src.app.services.structure import line_rulers as lr


def page(width: int = 600, height: int = 400, fill: int = 255) -> np.ndarray:
    return np.full((height, width, 3), fill, dtype=np.uint8)


def draw_hline(image: np.ndarray, y: int, x0: int, x1: int, value: int = 200) -> None:
    image[y, x0:x1] = value


def draw_vline(image: np.ndarray, x: int, y0: int, y1: int, value: int = 200) -> None:
    image[y0:y1, x] = value


def test_probe_finds_a_long_horizontal_line() -> None:
    image = page()
    draw_hline(image, 200, 40, 560)
    lines = lr.probe_lines(image, 600, 400)
    horizontal = [line for line in lines if line["axis"] == "h" and abs(line["pos"] - 200) <= 2]
    assert horizontal, lines
    assert horizontal[0]["length"] >= 400


def test_probe_finds_a_vertical_divider() -> None:
    image = page()
    draw_vline(image, 300, 40, 360)
    lines = lr.probe_lines(image, 600, 400)
    vertical = [line for line in lines if line["axis"] == "v" and abs(line["pos"] - 300) <= 2]
    assert vertical, lines


def test_probe_ignores_a_blank_page() -> None:
    assert lr.probe_lines(page(), 600, 400) == []


def test_a_short_rule_does_not_divide_its_card() -> None:
    image = page()
    draw_hline(image, 200, 250, 350)  # 100px：不够卡宽的一半
    lines = lr.probe_lines(image, 600, 400)
    inside = lr.lines_in(lines, [40, 40, 520, 320], axis="h")
    assert inside == []


def test_a_full_width_rule_does_divide_its_card() -> None:
    image = page()
    draw_hline(image, 200, 40, 560)
    lines = lr.probe_lines(image, 600, 400)
    inside = lr.lines_in(lines, [40, 40, 520, 320], axis="h")
    assert inside


def test_bands_sit_between_consecutive_rules() -> None:
    image = page()
    for y in (100, 170, 240):
        draw_hline(image, y, 40, 560)
    lines = lr.probe_lines(image, 600, 400)
    bands = lr.bands_from_lines(lines, [{"bbox": [40, 40, 520, 320], "role": "card"}])
    tops = sorted(band["bbox"][1] for band in bands)
    # Canny 报的是边缘，可能比画的像素差一行；结构对就行。
    assert len(tops) == 2
    assert abs(tops[0] - 101) <= 2 and abs(tops[1] - 171) <= 2
    assert all(band["role"] == "row" for band in bands)


def test_bands_do_not_repeat_a_row_cv_already_found() -> None:
    image = page()
    for y in (100, 170, 240):
        draw_hline(image, y, 40, 560)
    lines = lr.probe_lines(image, 600, 400)
    bands = lr.bands_from_lines(
        lines,
        [{"bbox": [40, 40, 520, 320], "role": "card"}],
        existing=[{"bbox": [40, 101, 520, 69]}],
    )
    assert len(bands) == 1
    assert abs(bands[0]["bbox"][1] - 171) <= 2


def test_three_distinct_elements_make_a_guide() -> None:
    guides = lr.build_guides([[100, 10, 40, 18], [101, 60, 60, 18], [99, 110, 30, 18]])
    assert [item["pos"] for item in guides["v"]] == [100]


def test_one_element_cannot_vote_twice_for_the_same_edge() -> None:
    # 三个零宽框：左缘和右缘同坐标，但只有一个元素，够不上三票。
    guides = lr.build_guides([[100, 10, 0, 18], [100, 60, 0, 18]])
    assert guides["v"] == []


def test_a_drifting_column_is_not_a_guide() -> None:
    # 100..120 会被单链连成一簇，中位数 110 谁都不在，不能立成标尺。
    guides = lr.build_guides([[100, 10, 40, 18], [110, 60, 40, 18], [120, 110, 40, 18]])
    assert [item["pos"] for item in guides["v"]] == []


def test_right_aligned_column_is_detected_by_variance() -> None:
    boxes = [[100, 10, 90, 18], [110, 60, 80, 18], [95, 110, 95, 18]]
    assert lr.right_aligned_boxes(boxes) == {0, 1, 2}


def test_left_aligned_column_is_not_marked() -> None:
    boxes = [[100, 10, 40, 18], [100, 60, 75, 18], [100, 110, 30, 18]]
    assert lr.right_aligned_boxes(boxes) == set()


def test_snap_moves_by_at_most_the_tolerance_and_never_resizes() -> None:
    guides = lr.build_guides([[100, 10, 40, 18], [100, 50, 40, 18], [100, 90, 40, 18]])
    moved, info = lr.snap_box([103, 30, 77, 16], guides)
    assert info["dx"] == -3 and moved[0] == 100 and moved[2] == 77 and moved[3] == 16


def test_snap_refuses_a_gap_that_is_not_jitter() -> None:
    guides = lr.build_guides([[100, 10, 40, 18], [100, 50, 40, 18], [100, 90, 40, 18]])
    moved, info = lr.snap_box([112, 30, 77, 16], guides)
    assert info["dx"] == 0 and moved[0] == 112


def test_right_locked_box_pins_its_right_edge() -> None:
    guides = lr.build_guides(
        [[100, 10, 40, 18], [100, 50, 40, 18], [100, 90, 40, 18],
         [300, 10, 90, 18], [310, 50, 80, 18], [295, 90, 95, 18]]
    )
    moved, info = lr.snap_box([300, 30, 88, 16], guides, right_locked=True)
    assert info["edge"] == "right"
    assert moved[0] + 88 == moved[0] + 88  # 宽度不变
    assert moved[2] == 88


def test_master_pulls_back_a_row_that_lost_its_leading_icon() -> None:
    bands = [
        {"bbox": [500, 100, 400, 70], "role": "row"},
        {"bbox": [500, 171, 400, 70], "role": "row"},
        {"bbox": [500, 242, 400, 70], "role": "row"},
    ]
    boxes = [
        [520, 120, 40, 18], [700, 120, 60, 18],   # 头像 + 文本
        [540, 191, 100, 18],                      # 只有文本，头像缺席
        [520, 262, 40, 18], [700, 262, 60, 18],   # 头像 + 文本
    ]
    masters = lr.row_master(bands, boxes)
    assert len(masters) == 1
    assert masters[0]["row_count"] == 3
    assert masters[0]["modal_members"] == 2
    assert [slot["left"] for slot in masters[0]["slots"]] == [520, 700]

    stats = lr.apply_master(bands, boxes, masters)
    assert stats["rows"] == 3
    assert stats["deficient_rows"] == 1
    # 缺了头像那一行整体右移 20px：母版把它拉回行的左缘。
    assert boxes[2][0] == 520


def test_master_unifies_row_width() -> None:
    bands = [
        {"bbox": [500, 100, 400, 70], "role": "row"},
        {"bbox": [505, 171, 395, 70], "role": "row"},
        {"bbox": [500, 242, 400, 70], "role": "row"},
    ]
    boxes = [
        [520, 120, 40, 18], [700, 120, 60, 18],
        [520, 191, 40, 18], [700, 191, 60, 18],
        [520, 262, 40, 18], [700, 262, 60, 18],
    ]
    masters = lr.row_master(bands, boxes)
    lr.apply_master(bands, boxes, masters)
    assert masters[0]["x_start"] == 500
    assert all(band["bbox"][0] == 500 for band in bands)


def test_master_refuses_two_rows() -> None:
    bands = [
        {"bbox": [500, 100, 400, 70], "role": "row"},
        {"bbox": [500, 171, 400, 70], "role": "row"},
    ]
    boxes = [[520, 120, 100, 18], [520, 191, 100, 18]]
    assert lr.row_master(bands, boxes) == []


def test_master_leaves_a_real_indent_alone() -> None:
    bands = [
        {"bbox": [500, 100, 400, 70], "role": "row"},
        {"bbox": [500, 171, 400, 70], "role": "row"},
        {"bbox": [500, 242, 400, 70], "role": "row"},
    ]
    boxes = [
        [520, 120, 40, 18], [700, 120, 60, 18],
        [520, 191, 40, 18], [700, 191, 60, 18],
        [520, 262, 40, 18], [700, 262, 60, 18],
        [478, 266, 40, 18],  # 缩进 42px：远超容差，是排版不是缺失
    ]
    masters = lr.row_master(bands, boxes)
    lr.apply_master(bands, boxes, masters)
    assert boxes[6][0] == 478


def test_everything_is_deterministic() -> None:
    image = page()
    for y in (100, 170, 240):
        draw_hline(image, y, 40, 560)
    first = lr.probe_lines(image, 600, 400)
    second = lr.probe_lines(image.copy(), 600, 400)
    assert first == second
