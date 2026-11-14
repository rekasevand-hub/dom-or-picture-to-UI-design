"""The presentation rules, on synthetic cases.

Each rule answers a defect measured on the seven benchmarks, and each test
states the smallest shape that shows it.  The screenshots themselves are not
needed: these passes are geometry, strings and one drawn bar.
"""

from __future__ import annotations

from pathlib import Path

from src.app.services.structure.fidelity.fixed_canvas_compiler import (
    _audit_filled_occluders,
    _drop_coincident_texts,
    _drop_icon_descriptor_labels,
    _recover_saturated_bars,
    _repartition_table_rows,
    _resolve_misfiled_controls,
    _separate_badge_icon_text,
)


def _text(index: int, x: int, y: int, width: int, height: int, text: str, **style) -> dict:
    return {
        "id": f"text:{index}",
        "contentRef": f"text:{index}",
        "type": "text",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "text": text,
        "style": {"fontSize": 14, "textColor": "#222222", **style},
    }


def _box(
    index: int,
    x: int,
    y: int,
    width: int,
    height: int,
    fill: str | None,
    **style,
) -> dict:
    payload = dict(style)
    if fill:
        payload["fillColor"] = fill
    return {
        "id": f"container:{index}",
        "type": "container",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "style": payload,
    }


def _icon(index: int, x: int, y: int, width: int, height: int) -> dict:
    return {
        "id": f"asset:{index}",
        "type": "image",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "imageBase64": "AA==",
    }


# -- icon captions ---------------------------------------------------------


def test_an_icon_caption_without_ocr_is_dropped() -> None:
    """`search` over a magnifier is the model naming the glyph."""
    elements = [_text(0, 40, 20, 46, 20, "search"), _text(1, 200, 20, 80, 20, "登录")]
    assert _drop_icon_descriptor_labels(elements, []) == 1
    assert [element.get("text") for element in elements] == ["登录"]


def test_a_real_english_label_survives_when_ocr_reads_it() -> None:
    """A page that prints "Search" keeps it; OCR is the proof."""
    elements = [_text(0, 40, 20, 60, 20, "Search")]
    ocr = [{"text": "Search", "bbox": [40, 20, 60, 20]}]
    assert _drop_icon_descriptor_labels(elements, ocr) == 0
    assert elements[0]["text"] == "Search"


def test_an_icon_caption_inside_a_word_is_left_alone() -> None:
    """"Mailbox settings" is prose, not a glyph name."""
    elements = [_text(0, 40, 20, 160, 20, "Mailbox settings")]
    assert _drop_icon_descriptor_labels(elements, []) == 0


def test_a_large_english_block_is_not_an_icon_caption() -> None:
    """A 600px-wide paragraph that happens to start with "search" stays."""
    elements = [_text(0, 40, 20, 600, 200, "search results for the term")]
    assert _drop_icon_descriptor_labels(elements, []) == 0


# -- same-line duplicates --------------------------------------------------


def test_a_narrow_copy_of_a_row_is_dropped() -> None:
    """The 48px box that prints the whole row over its own twin."""
    elements = [
        _text(0, 574, 313, 354, 33, "库位: W0505-005 包覆5线线边库位"),
        _text(1, 492, 314, 48, 30, "库位: W0505-005 包覆5线线边库位 库存总量:31"),
    ]
    assert _drop_coincident_texts(elements, "#ffffff") == 1
    assert len(elements) == 1
    assert "库存总量" in elements[0]["text"]


def test_a_quantity_cell_is_not_a_duplicate_of_the_row_prose() -> None:
    """"100" sits inside the row's words and still has to print."""
    elements = [
        _text(0, 2492, 1157, 27, 24, "100"),
        _text(1, 574, 1157, 1292, 32, "库位: W3101-01001 库存总量: 100 可用库存: 100米"),
    ]
    assert _drop_coincident_texts(elements, "#ffffff") == 0
    assert len(elements) == 2


def test_two_copies_that_differ_by_an_ocr_digit_still_collapse() -> None:
    """W0505 / WO505 is one label read twice."""
    elements = [
        _text(0, 574, 313, 354, 33, "库位: W0505-005 包覆5线线边库位"),
        _text(1, 492, 314, 300, 30, "库位: WO505-005 包覆5线线边库位"),
    ]
    assert _drop_coincident_texts(elements, "#ffffff") == 1


def test_two_different_labels_on_one_line_are_kept() -> None:
    elements = [
        _text(0, 100, 300, 120, 24, "共 1 条数据"),
        _text(1, 400, 302, 120, 24, "10条/页"),
    ]
    assert _drop_coincident_texts(elements, "#ffffff") == 0


def test_the_readable_copy_wins_over_the_invisible_one() -> None:
    """One reading sampled the card instead of the ink: #fefffe on white."""
    elements = [
        _text(0, 100, 300, 200, 24, "库位: W2101-01001 表皮库位001", textColor="#252525"),
        _text(1, 100, 300, 200, 24, "库位: W2101-01001 表皮库位001 库存总量:412", textColor="#fefffe"),
    ]
    assert _drop_coincident_texts(elements, "#ffffff") == 1
    assert elements[0]["style"]["textColor"] == "#252525"


# -- badge icon and text ---------------------------------------------------


def test_badge_text_starts_after_its_icon() -> None:
    elements = [
        _box(0, 100, 100, 200, 40, "#f2f3f5", borderRadius=20),
        _icon(1, 112, 112, 16, 16),
        _text(2, 116, 112, 140, 16, "大厂直供"),
    ]
    assert _separate_badge_icon_text(elements) == 1
    assert elements[2]["x"] == 112 + 16 + 4


def test_a_sidebar_row_is_not_a_badge() -> None:
    """Its icon cut already holds the first pixels of the label."""
    elements = [
        _box(0, 0, 100, 276, 480, "#364150"),
        _icon(1, 100, 112, 30, 24),
        _text(2, 106, 112, 96, 20, "出库管理"),
    ]
    assert _separate_badge_icon_text(elements) == 0
    assert elements[2]["x"] == 106


# -- filled occluder audit -------------------------------------------------


def test_a_filled_block_that_buries_text_goes_behind_it() -> None:
    """The table section painted after the rows it was supposed to sit under."""
    elements = [
        _text(0, 300, 560, 200, 20, "执行时间"),
        _box(1, 160, 544, 1744, 264, "#fefefe"),
    ]
    # What batching does to it: a lifted tier puts the strip after the rows.
    elements[1]["zIndex"] = 2
    assert _audit_filled_occluders(elements, "#ffffff") == 1
    assert int(elements[1].get("zIndex") or 0) < 0


def test_a_progress_bar_keeps_its_fill() -> None:
    """A solid rounded bar is content, not a panel that hides something."""
    elements = [
        _text(0, 240, 826, 84, 26, "处理进度"),
        _box(1, 240, 860, 620, 8, "#1e6fff", borderRadius=4),
    ]
    assert _audit_filled_occluders(elements, "#fefefe") == 0
    assert elements[1]["style"]["fillColor"] == "#1e6fff"


def test_a_backdrop_fragment_is_repainted_in_the_panel_colour() -> None:
    """A dimmed-page patch measured over a white dialog hides the dialog."""
    elements = [
        _box(0, 660, 76, 1900, 1198, "#ffffff"),
        _box(1, 1895, 319, 578, 545, "#666666"),
    ]
    assert _audit_filled_occluders(elements, "#666666") == 1
    assert elements[1]["style"]["fillColor"] == "#ffffff"


# -- table row re-partition ------------------------------------------------


def _table(index: int, x: int, y: int, width: int, height: int) -> dict:
    return {
        "id": f"table-node:table:{index}",
        "type": "container",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "style": {"fillColor": "#ffffff"},
    }


def _header(index: int, x: int, y: int, width: int, height: int, text: str) -> dict:
    element = _text(index, x, y, width, height, text)
    element["id"] = f"table-header:{index}"
    element["contentRef"] = f"table-header:{index}"
    element["style"]["textAlign"] = "center"
    return element


def test_a_header_cell_below_the_table_is_pulled_back_into_its_row() -> None:
    """inventory2's 失效日期 printed 112px under its own words."""
    elements = [
        _table(0, 100, 100, 600, 60),
        _header(0, 110, 100, 80, 40, "单位"),
        _header(1, 300, 100, 80, 40, "数量"),
        _header(2, 200, 180, 80, 40, "日期"),
    ]
    ocr = [
        {"text": "单位", "bbox": [140, 105, 40, 20]},
        {"text": "数量", "bbox": [330, 105, 40, 20]},
        {"text": "日期", "bbox": [240, 105, 40, 20]},
    ]
    assert _repartition_table_rows(elements, ocr) == 3
    cells = elements[1:]
    assert [cell["y"] for cell in cells] == [100, 100, 100]
    ordered = sorted(cells, key=lambda cell: cell["x"])
    for left, right in zip(ordered, ordered[1:]):
        assert left["x"] + left["width"] <= right["x"] + 1
        assert right["x"] >= 100 and right["x"] + right["width"] <= 700


def test_a_row_of_cells_from_two_tables_is_not_merged() -> None:
    """The same header words in two tables must follow their own rows."""
    elements = [
        _table(0, 100, 100, 600, 60),
        _table(1, 100, 400, 600, 60),
        _header(0, 100, 100, 120, 40, "单位"),
        _header(1, 150, 100, 220, 40, "数量"),
        _header(2, 100, 400, 120, 40, "单位"),
        _header(3, 150, 400, 220, 40, "数量"),
    ]
    ocr = [
        {"text": "单位", "bbox": [140, 105, 40, 20]},
        {"text": "数量", "bbox": [330, 105, 40, 20]},
        {"text": "单位", "bbox": [140, 405, 40, 20]},
        {"text": "数量", "bbox": [330, 405, 40, 20]},
    ]
    assert _repartition_table_rows(elements, ocr) >= 2
    assert [cell["y"] for cell in elements[2:4]] == [100, 100]
    assert [cell["y"] for cell in elements[4:6]] == [400, 400]


# -- misfiled controls -----------------------------------------------------


def test_a_nav_control_measured_over_a_table_goes_back_to_its_words() -> None:
    elements = [
        _table(0, 100, 100, 400, 120),
        {
            "id": "control:1",
            "type": "button",
            "x": 150,
            "y": 120,
            "width": 80,
            "height": 40,
            "text": "库存管理",
            "style": {"fillColor": "#ffffff"},
        },
    ]
    ocr = [{"text": "库存管理", "bbox": [10, 300, 60, 20]}]
    assert _resolve_misfiled_controls(elements, ocr, "") == 1
    control = elements[1]
    assert control["x"] == 0 and control["y"] == 290


def test_a_nav_control_whose_words_are_already_printed_is_dropped() -> None:
    elements = [
        _table(0, 100, 100, 400, 120),
        {
            "id": "control:1",
            "type": "button",
            "x": 150,
            "y": 120,
            "width": 80,
            "height": 40,
            "text": "库存信息",
            "style": {"fillColor": "#ffffff"},
        },
        _text(2, 8, 296, 90, 24, "库存信息"),
    ]
    ocr = [{"text": "库存信息", "bbox": [10, 300, 60, 20]}]
    assert _resolve_misfiled_controls(elements, ocr, "") == 1
    assert [element["id"] for element in elements] == [
        "table-node:table:0",
        "text:2",
    ]


def test_a_control_that_sits_on_its_own_words_is_left_alone() -> None:
    elements = [
        _table(0, 100, 100, 400, 120),
        {
            "id": "control:1",
            "type": "button",
            "x": 150,
            "y": 120,
            "width": 80,
            "height": 40,
            "text": "执行",
            "style": {"fillColor": "#3366ff"},
        },
    ]
    ocr = [{"text": "执行", "bbox": [160, 130, 60, 20]}]
    assert _resolve_misfiled_controls(elements, ocr, "") == 0
    assert elements[1]["x"] == 150


# -- saturated bars --------------------------------------------------------


def test_a_saturated_progress_bar_is_recovered_from_pixels(tmp_path: Path) -> None:
    from PIL import Image

    image = Image.new("RGB", (400, 140), "white")
    for x in range(20, 320):
        for y in range(40, 51):
            image.putpixel((x, y), (40, 120, 250))
    for x in range(20, 320):  # an unsaturated rule right below it
        image.putpixel((x, 90), (200, 200, 200))
    path = tmp_path / "bar.png"
    image.save(path)
    elements: list[dict] = []
    assert _recover_saturated_bars(elements, str(path), 400, 140) == 1
    bar = elements[0]
    assert (bar["x"], bar["y"], bar["width"]) == (20, 40, 300)
    assert 9 <= bar["height"] <= 12
    assert bar["style"]["fillColor"].startswith("#")
    assert bar["style"]["borderRadius"] >= 2


def test_a_grey_rule_is_not_a_bar() -> None:
    from PIL import Image

    image = Image.new("RGB", (400, 140), "white")
    for x in range(20, 320):
        for y in range(40, 46):
            image.putpixel((x, y), (200, 200, 200))
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "rule.png"
        image.save(path)
        assert _recover_saturated_bars([], str(path), 400, 140) == 0


# -- table row re-partition ------------------------------------------------


def _table(index: int, x: int, y: int, width: int, height: int) -> dict:
    return {
        "id": f"table-node:table:{index}",
        "type": "container",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "style": {"fillColor": "#ffffff"},
    }


def _header(index: int, x: int, y: int, width: int, height: int, text: str) -> dict:
    element = _text(index, x, y, width, height, text)
    element["id"] = f"table-header:{index}"
    element["contentRef"] = f"table-header:{index}"
    element["style"]["textAlign"] = "center"
    return element


def test_a_header_cell_below_the_table_is_pulled_back_into_its_row() -> None:
    """inventory2's 失效日期 printed 112px under its own words."""
    elements = [
        _table(0, 100, 100, 600, 60),
        _header(0, 110, 100, 80, 40, "单位"),
        _header(1, 300, 100, 80, 40, "数量"),
        _header(2, 200, 180, 80, 40, "日期"),
    ]
    ocr = [
        {"text": "单位", "bbox": [140, 105, 40, 20]},
        {"text": "数量", "bbox": [330, 105, 40, 20]},
        {"text": "日期", "bbox": [240, 105, 40, 20]},
    ]
    assert _repartition_table_rows(elements, ocr) == 3
    cells = elements[1:]
    assert [cell["y"] for cell in cells] == [100, 100, 100]
    ordered = sorted(cells, key=lambda cell: cell["x"])
    for left, right in zip(ordered, ordered[1:]):
        assert left["x"] + left["width"] <= right["x"] + 1
        assert right["x"] >= 100 and right["x"] + right["width"] <= 700


def test_a_row_of_cells_from_two_tables_is_not_merged() -> None:
    """The same header words in two tables must follow their own rows."""
    elements = [
        _table(0, 100, 100, 600, 60),
        _table(1, 100, 400, 600, 60),
        _header(0, 100, 100, 120, 40, "单位"),
        _header(1, 150, 100, 220, 40, "数量"),
        _header(2, 100, 400, 120, 40, "单位"),
        _header(3, 150, 400, 220, 40, "数量"),
    ]
    ocr = [
        {"text": "单位", "bbox": [140, 105, 40, 20]},
        {"text": "数量", "bbox": [330, 105, 40, 20]},
        {"text": "单位", "bbox": [140, 405, 40, 20]},
        {"text": "数量", "bbox": [330, 405, 40, 20]},
    ]
    assert _repartition_table_rows(elements, ocr) >= 2
    assert [cell["y"] for cell in elements[2:4]] == [100, 100]
    assert [cell["y"] for cell in elements[4:6]] == [400, 400]


# -- misfiled controls -----------------------------------------------------


def test_a_nav_control_measured_over_a_table_goes_back_to_its_words() -> None:
    elements = [
        _table(0, 100, 100, 400, 120),
        {
            "id": "control:1",
            "type": "button",
            "x": 150,
            "y": 120,
            "width": 80,
            "height": 40,
            "text": "库存管理",
            "style": {"fillColor": "#ffffff"},
        },
    ]
    ocr = [{"text": "库存管理", "bbox": [10, 300, 60, 20]}]
    assert _resolve_misfiled_controls(elements, ocr, "") == 1
    control = elements[1]
    assert control["x"] == 0 and control["y"] == 290


def test_a_nav_control_whose_words_are_already_printed_is_dropped() -> None:
    elements = [
        _table(0, 100, 100, 400, 120),
        {
            "id": "control:1",
            "type": "button",
            "x": 150,
            "y": 120,
            "width": 80,
            "height": 40,
            "text": "库存信息",
            "style": {"fillColor": "#ffffff"},
        },
        _text(2, 8, 296, 90, 24, "库存信息"),
    ]
    ocr = [{"text": "库存信息", "bbox": [10, 300, 60, 20]}]
    assert _resolve_misfiled_controls(elements, ocr, "") == 1
    assert [element["id"] for element in elements] == [
        "table-node:table:0",
        "text:2",
    ]


def test_a_control_that_sits_on_its_own_words_is_left_alone() -> None:
    elements = [
        _table(0, 100, 100, 400, 120),
        {
            "id": "control:1",
            "type": "button",
            "x": 150,
            "y": 120,
            "width": 80,
            "height": 40,
            "text": "执行",
            "style": {"fillColor": "#3366ff"},
        },
    ]
    ocr = [{"text": "执行", "bbox": [160, 130, 60, 20]}]
    assert _resolve_misfiled_controls(elements, ocr, "") == 0
    assert elements[1]["x"] == 150


# -- saturated bars --------------------------------------------------------


def test_a_saturated_progress_bar_is_recovered_from_pixels(tmp_path: Path) -> None:
    from PIL import Image

    image = Image.new("RGB", (400, 140), "white")
    for x in range(20, 320):
        for y in range(40, 51):
            image.putpixel((x, y), (40, 120, 250))
    for x in range(20, 320):  # an unsaturated rule right below it
        image.putpixel((x, 90), (200, 200, 200))
    path = tmp_path / "bar.png"
    image.save(path)
    elements: list[dict] = []
    assert _recover_saturated_bars(elements, str(path), 400, 140) == 1
    bar = elements[0]
    assert (bar["x"], bar["y"], bar["width"]) == (20, 40, 300)
    assert 9 <= bar["height"] <= 12
    assert bar["style"]["fillColor"].startswith("#")
    assert bar["style"]["borderRadius"] >= 2


def test_a_grey_rule_is_not_a_bar() -> None:
    from PIL import Image

    image = Image.new("RGB", (400, 140), "white")
    for x in range(20, 320):
        for y in range(40, 46):
            image.putpixel((x, y), (200, 200, 200))
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "rule.png"
        image.save(path)
        assert _recover_saturated_bars([], str(path), 400, 140) == 0


# -- cross-plane members ---------------------------------------------------


def _dialog_scene(tmp_path: Path) -> Path:
    """A white dialog on a grey page, with page content to its right."""
    from PIL import Image

    image = Image.new("RGB", (420, 260), (102, 102, 102))
    for x in range(40, 280):
        for y in range(10, 250):
            image.putpixel((x, y), (255, 255, 255))
    # a word inside the dialog and a word on the page beside it
    for x in range(60, 120):
        for y in range(40, 52):
            image.putpixel((x, y), (30, 30, 30))
    for x in range(320, 390):
        for y in range(40, 52):
            image.putpixel((x, y), (20, 20, 20))
    path = tmp_path / "dialog.png"
    image.save(path)
    return path


def test_a_member_standing_on_the_page_is_detached_from_the_dialog(
    tmp_path: Path,
) -> None:
    """wecom-modal's copyright line was a member of a dialog it sat beside."""
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _evict_cross_plane_members,
    )

    path = _dialog_scene(tmp_path)
    elements = [
        # measured to the page edge, the way the dialog in the screenshot was
        _box(0, 40, 10, 380, 240, "#ffffff"),
        _text(1, 60, 40, 60, 12, "标题"),
        _text(2, 320, 40, 70, 12, "版权"),
    ]
    evicted, dropped = _evict_cross_plane_members(
        elements, str(path), (420, 260), "#666666", None
    )
    assert (evicted, dropped) == (1, 0)
    assert elements[1].get("planeDetached") is None
    assert elements[2]["planeDetached"] is True
    assert int(elements[2]["zIndex"]) < 0


def test_a_dialog_is_cut_back_to_the_edge_of_its_own_paint(tmp_path: Path) -> None:
    """A box measured to the page edge is repainted over the page."""
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _evict_cross_plane_members,
        _trim_to_fill_boundary,
    )

    path = _dialog_scene(tmp_path)
    elements = [
        _box(0, 40, 10, 380, 240, "#ffffff"),
        _text(1, 60, 40, 60, 12, "标题"),
        _text(3, 60, 120, 60, 12, "正文"),
        _text(2, 320, 40, 70, 12, "版权"),
    ]
    _evict_cross_plane_members(elements, str(path), (420, 260), "#666666", None)
    assert _trim_to_fill_boundary(elements, str(path), (420, 260), "#666666") == 1
    assert elements[0]["x"] == 40
    assert elements[0]["x"] + elements[0]["width"] == 280


def test_padding_that_is_fill_is_left_alone(tmp_path: Path) -> None:
    """A dialog's inner margin is part of the dialog, not overshoot."""
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _trim_to_fill_boundary,
    )

    path = _dialog_scene(tmp_path)
    elements = [
        _box(0, 40, 10, 240, 240, "#ffffff"),
        _text(1, 80, 60, 40, 12, "标题"),
        _text(2, 80, 160, 40, 12, "正文"),
    ]
    assert _trim_to_fill_boundary(elements, str(path), (420, 260), "#666666") == 0
    assert (elements[0]["x"], elements[0]["width"]) == (40, 240)


def test_a_control_on_the_page_with_no_words_is_removed(tmp_path: Path) -> None:
    """A black 关闭 pill that nothing on the page reads is an invention."""
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _evict_cross_plane_members,
    )

    path = _dialog_scene(tmp_path)
    elements = [
        _box(0, 40, 10, 380, 240, "#ffffff"),
        _text(1, 60, 40, 60, 12, "标题"),
        {
            "id": "control:9",
            "type": "button",
            "x": 320,
            "y": 30,
            "width": 70,
            "height": 30,
            "text": "关闭",
            "style": {"fillColor": "#111111"},
        },
    ]
    evicted, dropped = _evict_cross_plane_members(
        elements,
        str(path),
        (420, 260),
        "#666666",
        [{"text": "标题", "bbox": [60, 40, 60, 12]}],
    )
    assert evicted == 1 and dropped == 1
    assert [element["id"] for element in elements] == ["container:0", "text:1"]


# -- chip labels -----------------------------------------------------------


def _chip_scene(tmp_path: Path) -> Path:
    from PIL import Image

    image = Image.new("RGB", (300, 120), (250, 250, 250))
    for x in range(20, 82):
        for y in range(20, 80):
            image.putpixel((x, y), (0, 204, 0))
    for x in range(34, 68):
        for y in range(38, 62):
            image.putpixel((x, y), (255, 255, 255))
    path = tmp_path / "chip.png"
    image.save(path)
    return path


def test_an_empty_badge_gets_its_word_back(tmp_path: Path) -> None:
    """inventory's green chips printed with nothing inside them."""
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _restore_chip_labels,
    )

    path = _chip_scene(tmp_path)
    elements = [
        {
            "id": "backdrop:1",
            "type": "container",
            "role": "text-backdrop",
            "x": 20,
            "y": 20,
            "width": 62,
            "height": 60,
            "style": {"fillColor": "#00cc00", "borderRadius": 24},
        }
    ]
    assert _restore_chip_labels(
        elements,
        str(path),
        (300, 120),
        [{"text": "库位", "bbox": [34, 38, 34, 24]}],
    ) == 1
    label = elements[1]
    assert label["text"] == "库位"
    assert label["style"]["textAlign"] == "center"
    assert label["style"]["textColor"].lower() in {"#ffffff", "#fefefe"}
    assert label["x"] == 34 and label["badgeLabel"] is True


def test_a_badge_that_already_has_its_word_is_left_alone(tmp_path: Path) -> None:
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _restore_chip_labels,
    )

    path = _chip_scene(tmp_path)
    elements = [
        {
            "id": "backdrop:1",
            "type": "container",
            "role": "text-backdrop",
            "x": 20,
            "y": 20,
            "width": 62,
            "height": 60,
            "style": {"fillColor": "#00cc00"},
        },
        _text(2, 30, 36, 40, 22, "库位"),
    ]
    assert _restore_chip_labels(
        elements,
        str(path),
        (300, 120),
        [{"text": "库位", "bbox": [34, 38, 34, 24]}],
    ) == 0
    assert len(elements) == 2


# -- OCR promotion ---------------------------------------------------------


def _plain_scene(tmp_path: Path, background=(255, 255, 255)) -> Path:
    from PIL import Image

    image = Image.new("RGB", (400, 240), background)
    # glyph-shaped strokes, not a filled bar: a solid block is a panel, and
    # that is what the panel pass is supposed to find.
    for glyph in range(6):
        left = 30 + glyph * 20
        for x in range(left, left + 3):
            for y in range(40, 56):
                image.putpixel((x, y), (20, 20, 20))
        for x in range(left + 3, left + 16):
            image.putpixel((x, 40), (20, 20, 20))
            image.putpixel((x, 55), (20, 20, 20))
    path = tmp_path / "plain.png"
    image.save(path)
    return path


def test_a_line_no_node_covers_becomes_a_text_node(tmp_path: Path) -> None:
    """AtomGit's nav bar and marketplace's menu were never in the plan."""
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _promote_ocr_text,
    )

    path = _plain_scene(tmp_path)
    elements: list[dict] = []
    added = _promote_ocr_text(
        elements,
        str(path),
        (400, 240),
        [{"text": "探索更多", "bbox": [30, 40, 120, 16], "confidence": 0.9}],
    )
    assert added == 1
    assert elements[0]["text"] == "探索更多"
    assert (elements[0]["x"], elements[0]["y"]) == (30, 40)


def test_a_line_an_existing_node_already_prints_is_not_added_twice(
    tmp_path: Path,
) -> None:
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _promote_ocr_text,
    )

    path = _plain_scene(tmp_path)
    elements = [_text(0, 30, 40, 120, 16, "探索更多")]
    added = _promote_ocr_text(
        elements,
        str(path),
        (400, 240),
        [{"text": "探索更多", "bbox": [30, 40, 120, 16], "confidence": 0.9}],
    )
    assert added == 0 and len(elements) == 1


def test_the_same_words_measured_elsewhere_are_moved_not_copied(
    tmp_path: Path,
) -> None:
    """A node on the right row but the wrong x is OCR's to correct."""
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _promote_ocr_text,
    )

    path = _plain_scene(tmp_path)
    elements = [_text(0, 250, 40, 60, 16, "探索更多")]
    added = _promote_ocr_text(
        elements,
        str(path),
        (400, 240),
        [{"text": "探索更多", "bbox": [30, 40, 120, 16], "confidence": 0.9}],
    )
    assert added == 0
    assert len(elements) == 1
    assert (elements[0]["x"], elements[0]["width"]) == (30, 120)


# -- low-contrast panels ---------------------------------------------------


def _soft_card_scene(tmp_path: Path) -> Path:
    from PIL import Image

    image = Image.new("RGB", (900, 700), (255, 255, 255))
    for x in range(30, 390):
        for y in range(30, 220):
            image.putpixel((x, y), (247, 248, 251))
    for x in range(60, 140):  # a word inside it, so it is not a flat blob
        for y in range(60, 72):
            image.putpixel((x, y), (30, 30, 30))
    path = tmp_path / "card.png"
    image.save(path)
    return path


def test_a_card_three_channels_off_the_page_is_recovered(tmp_path: Path) -> None:
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _recover_soft_panels,
    )

    path = _soft_card_scene(tmp_path)
    elements: list[dict] = []
    assert _recover_soft_panels(elements, str(path), 900, 700, "#ffffff") == 1
    panel = elements[0]
    assert (panel["x"], panel["y"], panel["width"], panel["height"]) == (30, 30, 360, 190)
    assert panel["style"]["fillColor"] == "#f7f8fb"


def test_a_line_of_text_is_not_a_card(tmp_path: Path) -> None:
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _recover_soft_panels,
    )

    path = _plain_scene(tmp_path)
    assert _recover_soft_panels([], str(path), 400, 240, "#ffffff") == 0


# -- page ground -----------------------------------------------------------


def test_a_tinted_page_gets_its_own_ground(tmp_path: Path) -> None:
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _recover_page_fill,
    )

    from PIL import Image

    image = Image.new("RGB", (400, 240), (234, 238, 248))
    path = tmp_path / "tinted.png"
    image.save(path)
    elements: list[dict] = []
    assert _recover_page_fill(elements, str(path), 400, 240, "#fefefe") is True
    assert elements and elements[0]["role"] == "page-ground"
    assert elements[0]["style"]["fillColor"] == "#eaeef8"


def test_a_page_that_matches_its_declaration_is_left_alone(tmp_path: Path) -> None:
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _recover_page_fill,
    )

    path = _plain_scene(tmp_path)
    elements: list[dict] = []
    assert _recover_page_fill(elements, str(path), 400, 240, "#ffffff") is False
    assert elements == []


# -- residual patches ------------------------------------------------------


def test_a_residual_region_is_cut_out_of_the_screenshot(tmp_path: Path) -> None:
    from src.app.services.structure.fidelity.fixed_canvas_compiler import (
        _apply_residual_patches,
    )

    path = _soft_card_scene(tmp_path)
    elements: list[dict] = []
    assert _apply_residual_patches(elements, str(path), (900, 700), [[30, 30, 120, 60]]) == 1
    patch = elements[0]
    assert patch["type"] == "image" and patch["role"] == "patch"
    assert (patch["x"], patch["y"], patch["width"], patch["height"]) == (30, 30, 120, 60)
    assert patch.get("imageBase64")
    assert int(patch["zIndex"]) > 0
