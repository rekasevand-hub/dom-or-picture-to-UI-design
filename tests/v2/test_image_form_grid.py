"""表单尾行吸纳、穿框膨胀、墨迹裁剪、字色对比四道守卫的边界。

前两条治的是"卡片的边切在自己的子件上"：表格底边卡在倒数第二行、卡片右缘切在
输入框中间。后两条治的是"从像素里猜出来的度量"：胶囊的圆角被当成字高、绿底上
的字被采成绿字。
"""

from __future__ import annotations

import numpy as np

from src.app.services.structure import physical_perception as pp
from src.app.services.structure.fidelity.style_resolver import _contrast_guard, _ink_extent


def grid(rows: int = 4, gap: int = 60) -> list[list[int]]:
    boxes: list[list[int]] = []
    for index in range(rows):
        top = 100 + index * gap
        for left in (100, 300, 500):
            boxes.append([left, top, 90, 24])
    return boxes


def rule(y: int, x0: int = 90, x1: int = 700) -> dict:
    return {"ys": [y], "x0": x0, "x1": x1}


# --------------------------------------------------------------- 尾行吸纳


def test_a_tail_row_with_two_cells_is_absorbed() -> None:
    boxes = grid() + [[100, 340, 90, 24], [300, 340, 120, 24]]
    table = pp.infer_text_table(boxes)
    assert table is not None
    # 主网格底边 304；吸纳尾行后到 364。
    assert table["bbox"][1] + table["bbox"][3] == 364


def test_a_tail_row_with_one_cell_is_absorbed() -> None:
    # ERP 的"单据状态：反确认"就是只有一列的尾行。
    boxes = grid() + [[100, 340, 90, 24]]
    table = pp.infer_text_table(boxes)
    assert table is not None
    assert table["bbox"][1] + table["bbox"][3] == 364


def test_a_footer_sentence_spanning_columns_is_not_absorbed() -> None:
    # 从第一列起排、一路横跨三列的页脚不是单元格。
    boxes = grid() + [[100, 340, 480, 24]]
    table = pp.infer_text_table(boxes)
    assert table is not None
    assert table["bbox"][1] + table["bbox"][3] == 304


def test_a_row_crossing_a_rule_is_not_absorbed() -> None:
    boxes = grid() + [[100, 340, 90, 24]]
    table = pp.infer_text_table(boxes, rules=[rule(350)])
    assert table is not None
    assert table["bbox"][1] + table["bbox"][3] == 304


def test_a_row_beyond_one_and_a_half_gaps_is_not_absorbed() -> None:
    boxes = grid() + [[100, 500, 90, 24]]
    table = pp.infer_text_table(boxes)
    assert table is not None
    assert table["bbox"][1] + table["bbox"][3] == 304


def test_a_tail_row_outside_the_column_span_is_not_absorbed() -> None:
    boxes = grid() + [[760, 340, 90, 24]]
    table = pp.infer_text_table(boxes)
    assert table is not None
    assert table["bbox"][1] + table["bbox"][3] == 304


# --------------------------------------------------------------- 穿框膨胀


def test_a_card_grows_just_enough_to_cover_a_half_cut_input() -> None:
    card = {"bbox": [100, 100, 400, 200], "role": "card"}
    leaf = [460, 150, 60, 30]  # 右缘 520，比卡片右边多出 20px
    stats = pp.expand_containers_to_straddlers([card], [leaf], canvas=(1000, 800))
    assert stats["grown"] == 1
    assert card["bbox"] == [100, 100, 428, 200]  # 520 + padding 8


def test_a_row_band_is_never_grown() -> None:
    band = {"bbox": [100, 100, 400, 20], "role": "card"}
    pp.expand_containers_to_straddlers([band], [[460, 100, 60, 20]], canvas=(1000, 800))
    assert band["bbox"] == [100, 100, 400, 20]


def test_a_full_width_panel_is_never_grown() -> None:
    panel = {"bbox": [0, 0, 1000, 800], "role": "card"}
    pp.expand_containers_to_straddlers([panel], [[980, 700, 60, 40]], canvas=(1000, 800))
    assert panel["bbox"] == [0, 0, 1000, 800]


def test_a_sibling_container_is_not_swallowed() -> None:
    card = {"bbox": [100, 100, 400, 200], "role": "card"}
    sibling = [460, 150, 200, 150]  # 面积超过卡片的四分之一：它是邻居，不是子件
    pp.expand_containers_to_straddlers([card], [sibling], canvas=(1000, 800))
    assert card["bbox"] == [100, 100, 400, 200]


def test_a_far_cut_element_is_not_chased() -> None:
    # 探出 40px 已经超出"切边"的量级，追它会一路吞掉邻居。
    card = {"bbox": [100, 100, 400, 200], "role": "card"}
    pp.expand_containers_to_straddlers([card], [[480, 150, 60, 30]], canvas=(1000, 800))
    assert card["bbox"] == [100, 100, 400, 200]


def test_contained_children_do_not_move_the_card() -> None:
    card = {"bbox": [100, 100, 400, 200], "role": "card"}
    pp.expand_containers_to_straddlers([card], [[140, 150, 60, 30]], canvas=(1000, 800))
    assert card["bbox"] == [100, 100, 400, 200]


# --------------------------------------------------------------- 墨迹裁剪


def test_a_full_width_rim_does_not_count_as_ink() -> None:
    # 胶囊上下缘的抗锯齿会占满整行：那是边框，不是字。
    mask = np.zeros((30, 100), dtype=bool)
    mask[0, :] = True
    mask[5:25, 20:80] = True
    left, top, right, bottom = _ink_extent(mask)
    assert (left, top, right, bottom) == (20, 5, 80, 25)


def test_a_bare_horizontal_stroke_keeps_its_own_height() -> None:
    # "一"、删除线：整行都是墨，但摘掉就什么都不剩，必须原样保留。
    mask = np.zeros((10, 40), dtype=bool)
    mask[4:6, 5:35] = True
    left, top, right, bottom = _ink_extent(mask)
    assert (left, top, right, bottom) == (5, 4, 35, 6)


def test_faint_edge_rows_are_trimmed_on_a_filled_chip() -> None:
    # 实心底板上的字：圆角抗锯齿只在首尾留下零星像素，强档把它裁掉。
    mask = np.zeros((20, 100), dtype=bool)
    mask[2, 40:44] = True  # 四个像素的毛刺
    mask[6:16, 20:80] = True
    _left, top, _right, bottom = _ink_extent(mask, filled=True)
    assert (top, bottom) == (6, 16)


def test_a_thin_descender_survives_when_trimming_would_lose_the_line() -> None:
    # 投影裁剪把升部、下伸部一起剪掉时（只剩 x-height），退回那条墨迹带：
    # 15px 的一行按 x-height 量会变成 8px，字号跟着塌一半。
    mask = np.zeros((32, 120), dtype=bool)
    mask[2:4, 40:60] = True  # 升部：十来个像素
    mask[4:12, 20:100] = True  # 字身
    mask[12:15, 44:52] = True  # 下伸部：六七个像素
    _left, top, _right, bottom = _ink_extent(mask)
    assert (top, bottom) == (2, 15)


# --------------------------------------------------------------- 字色对比


def test_a_green_label_on_green_is_flipped_to_the_white_stroke() -> None:
    crop = np.zeros((20, 40, 3), dtype=np.int16)
    crop[:, :] = (24, 128, 56)
    crop[6:14, 10:30] = (255, 255, 255)
    fixed = _contrast_guard(crop, (24, 128, 56), (24, 128, 56))
    assert tuple(int(value) for value in fixed) == (255, 255, 255)


def test_a_readable_label_is_left_alone() -> None:
    crop = np.zeros((20, 40, 3), dtype=np.int16)
    crop[:, :] = (255, 255, 255)
    crop[6:14, 10:30] = (32, 32, 32)
    fixed = _contrast_guard(crop, (255, 255, 255), (32, 32, 32))
    assert tuple(int(value) for value in fixed) == (32, 32, 32)


def test_a_flat_patch_does_not_invent_a_colour() -> None:
    crop = np.zeros((20, 40, 3), dtype=np.int16)
    crop[:, :] = (24, 128, 56)
    fixed = _contrast_guard(crop, (24, 128, 56), (24, 128, 56))
    assert tuple(int(value) for value in fixed) == (24, 128, 56)


# --------------------------------------------------------------- 位图抹字


def test_a_button_bitmap_loses_the_text_it_carries(tmp_path) -> None:
    """按钮底图上烤着的字必须被抹掉，否则顶层矢量字会和它叠成双影。

    这里同时钉住一个曾经的 Bug：重叠率的分母必须是**文字**。244×112 的按钮底图
    里只印着 90×36 的两个字，按位图自身算重叠只有 0.12，永远过不了 0.3——
    上一轮"四页零命中"就是它。
    """
    import base64
    import io

    from PIL import Image, ImageDraw

    from src.app.services.structure.fidelity import fixed_canvas_compiler as fcc

    page = Image.new("RGB", (200, 120), (230, 240, 250))
    ImageDraw.Draw(page).rectangle((80, 45, 150, 75), fill=(20, 40, 60))
    path = tmp_path / "page.png"
    page.save(path)

    elements = [
        {
            "type": "image",
            "x": 10,
            "y": 10,
            "width": 180,
            "height": 100,
            "imageBase64": "placeholder",
            "role": "mark",
        },
        {
            "type": "text",
            "x": 80,
            "y": 45,
            "width": 70,
            "height": 30,
            "text": "写邮件",
            "style": {},
        },
    ]
    erased = fcc._erase_text_from_bitmaps(elements, str(path), 200, 120)
    assert erased == 1
    after = Image.open(io.BytesIO(base64.b64decode(elements[0]["imageBase64"]))).convert("RGB")
    patch = np.asarray(after, dtype=np.int16)[35:85, 70:160]  # 位图内对应文字的区域
    assert int(patch.min()) > 100, "文字笔画应当已被环带中位色填平"


def test_a_small_icon_is_never_erased(tmp_path) -> None:
    """15×12 的小图标与旁边标签重叠是常事，抹掉它等于把图标删了。"""
    from PIL import Image

    from src.app.services.structure.fidelity import fixed_canvas_compiler as fcc

    page = Image.new("RGB", (60, 40), (255, 255, 255))
    path = tmp_path / "icon.png"
    page.save(path)
    elements = [
        {"type": "image", "x": 5, "y": 5, "width": 15, "height": 12, "imageBase64": "x"},
        {"type": "text", "x": 6, "y": 6, "width": 60, "height": 20, "text": "标签", "style": {}},
    ]
    assert fcc._erase_text_from_bitmaps(elements, str(path), 60, 40) == 0


# --------------------------------------------------------------- 页面底色


def test_page_colour_reports_the_real_colour_not_the_bucket() -> None:
    """纯白 255 落在 248 那个量化桶里；报告要写 #ffffff，不是 #f8f8f8。"""
    image = np.full((40, 60, 3), 255, dtype=np.int16)
    image[10:20, 10:50] = (200, 40, 40)
    assert pp.page_colour(image) == (255, 255, 255)


def test_the_page_itself_is_never_a_container() -> None:
    """page 改成真色之后，比较前必须折回桶号，否则整页会被当成一层板。"""
    image = np.full((200, 300, 3), 255, dtype=np.int16)
    image[60:140, 40:260] = (240, 242, 245)  # 一块灰板，占 29%
    found = pp._region_boxes(image, pp.page_colour(image), 300, 200)
    boxes = [tuple(int(v) for v in item["bbox"]) for item in found]
    assert any(abs(box[2] - 220) <= 2 and abs(box[3] - 80) <= 2 for box in boxes)
    assert all(not (box[2] >= 295 and box[3] >= 195) for box in boxes)


# --------------------------------------------------------------- 页面底色重涂


def test_a_dark_window_frame_does_not_paint_the_page_dark(tmp_path) -> None:
    """三边深色窗框 + 一边白，四边投票会投出深色，把整页刷黑。

    声明底色已经占满画布内部时，边上的深色是窗框/侧栏，不是页面。
    """
    from PIL import Image, ImageDraw

    from src.app.services.structure.fidelity import fixed_canvas_compiler as fcc

    page = Image.new("RGB", (200, 120), (255, 255, 255))
    draw = ImageDraw.Draw(page)
    draw.rectangle((0, 0, 199, 3), fill=(43, 54, 67))
    draw.rectangle((0, 0, 3, 119), fill=(54, 65, 80))
    draw.rectangle((196, 0, 199, 119), fill=(51, 61, 75))
    path = tmp_path / "dark-frame.png"
    page.save(path)

    elements: list[dict] = []
    painted = fcc._recover_page_fill(elements, str(path), 200, 120, "#ffffff")
    assert painted is False
    assert elements == []


def test_a_gradient_ground_is_still_repainted(tmp_path) -> None:
    """声明 #fefefe、实际是淡蓝渐变：声明色占不到内部 85%，该重涂就得重涂。"""
    from PIL import Image

    from src.app.services.structure.fidelity import fixed_canvas_compiler as fcc

    page = Image.new("RGB", (200, 120), (242, 245, 251))
    path = tmp_path / "gradient.png"
    page.save(path)

    elements: list[dict] = []
    painted = fcc._recover_page_fill(elements, str(path), 200, 120, "#fefefe")
    assert painted is True
    assert elements, "应当落下一层页面底色"


def test_a_steep_gradient_is_followed_by_bands(tmp_path) -> None:
    """四条边互不一致时不要放弃：那是整页渐变，交给分带逐段跟。

    以前这里直接 return False——整页渐变一个色带都不落，页面就停在错误的声明色上。
    """
    from PIL import Image

    from src.app.services.structure.fidelity import fixed_canvas_compiler as fcc

    width, height = 200, 400
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        pixels[y, :, :] = int(255 - (y / (height - 1)) * 60)
    path = tmp_path / "gradient-page.png"
    Image.fromarray(pixels).save(path)

    elements: list[dict] = []
    assert fcc._recover_page_fill(elements, str(path), width, height, "#123456") is True
    fills = [
        (element.get("style") or {}).get("fillColor")
        for element in elements
        if element.get("role") == "page-ground"
    ]
    assert len(fills) >= 3
    assert len(set(fills)) >= 3, "分带应当跟着渐变，而不是刷成一个颜色"
