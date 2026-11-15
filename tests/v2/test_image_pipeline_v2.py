"""The two gates this pass added: decoration after the lock, and the two-stage judge.

Three properties are worth a test each, because each one is a way the pipeline
can silently undo itself:

* a decoration pass that touches structure changes the frame count, and the
  frozen samples are checked against those counts;
* a stamp that is not rotated stays a horizontal word printed over tilted
  pixels — the doubled text the eye reads as a shadow;
* an arbiter whose quota is "six for the page" spends all six on font weights
  and never gets to the merged cards.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure.fidelity import vlm_arbiter  # noqa: E402
from src.app.services.structure.fidelity.arbitration_store import (  # noqa: E402
    ARBITRATED_NAME,
    load_arbitrated,
    resolve_design,
    save_arbitrated,
)
from src.app.services.structure.fidelity.fixed_canvas_compiler import (  # noqa: E402
    _decorate_locked_frames,
    _measure_stamp_rotations,
    _wrapped_by_control,
    compile_scene_plan_to_design,
)


def _font(size: int):
    from PIL import ImageFont

    for candidate in (
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    pytest.skip("no TrueType font available")


def _card_page(path: Path, width: int = 420, height: int = 320) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (20, 20, 400, 300), radius=12, fill=(245, 247, 250), outline=(208, 215, 226), width=1
    )
    font = _font(15)
    for index, text in enumerate(["Revenue summary", "Active users 1,284"]):
        draw.text((44, 48 + index * 40), text, fill=(30, 32, 38), font=font)
    image.save(path)


def _text_node(node_id: str, bbox: list[int], text: str) -> dict:
    return {
        "id": node_id,
        "type": "text",
        "role": "text",
        "bbox": bbox,
        "content_ref": f"text:{node_id}",
        "parent_id": "card",
        "children": [],
        "text": text,
        "style": {"fontSize": 15, "textColor": "#1e2026"},
    }


def _compile(source: Path, plan: dict) -> dict:
    return compile_scene_plan_to_design(
        graph={"components": [], "layout_relations": []},
        reference={"reference_id": "probe", "state": {}, "input": {"path": str(source)}},
        plan=plan,
        image_path=str(source),
        width=plan["image_size"][0],
        height=plan["image_size"][1],
        background="#ffffff",
        sample_id="probe",
        ocr_observations=[],
    )


class TestDecorationAfterLock:
    def test_decoration_adds_no_frames(self, tmp_path: Path) -> None:
        source = tmp_path / "card.png"
        _card_page(source)
        plan = {
            "image_size": [420, 320],
            "status": "planned",
            "reference_id": "probe",
            "nodes": [
                {
                    "id": "card",
                    "type": "container",
                    "role": "card",
                    "bbox": [20, 20, 380, 280],
                    "content_ref": "container:card",
                    "parent_id": None,
                    "children": [],
                },
                _text_node("t1", [44, 46, 200, 20], "Revenue summary"),
                _text_node("t2", [44, 86, 200, 20], "Active users 1,284"),
            ],
            "suppressed": [],
        }
        design = _compile(source, plan)
        before = sum(1 for element in design["elements"] if element.get("layoutChildren"))
        _decorate_locked_frames(design["elements"], str(source), 420, 320, "#ffffff")
        after = sum(1 for element in design["elements"] if element.get("layoutChildren"))
        assert after == before
        # 装饰层永远不是帧成员：它是画上去的，不是结构。
        for element in design["elements"]:
            if str(element.get("role") or "") in ("panel", "chip"):
                assert not element.get("layoutChildren")

    def test_label_inside_a_control_is_not_a_chip(self) -> None:
        elements = [
            {
                "id": "btn",
                "type": "button",
                "x": 100,
                "y": 100,
                "width": 120,
                "height": 40,
                "text": "看详情",
                "style": {"fillColor": "#1a1917", "borderColor": "#adaaa2", "borderWidth": 1},
            }
        ]
        assert _wrapped_by_control(elements, (112, 110, 60, 20)) is True
        # 整张卡包住它不算：那会把页面上每只芯片都跳过去。
        card = [
            {
                "id": "card",
                "type": "container",
                "role": "card",
                "x": 20,
                "y": 20,
                "width": 900,
                "height": 600,
                "style": {"fillColor": "#1a1917"},
            }
        ]
        assert _wrapped_by_control(card, (112, 110, 60, 20)) is False


class TestStampRotation:
    def test_tilted_seal_rotates_its_words_and_drops_the_twin(self, tmp_path: Path) -> None:
        import math

        from PIL import Image, ImageDraw

        source = tmp_path / "seal.png"
        # 页面按真实比例给（1600x1200）：印花只占 1%，才符合"孤立小徽章"的前提；
        # 300x240 的画布里一个 140px 方章占 27%，新的面积闸会（正确地）拒绝它。
        image = Image.new("RGB", (1600, 1200), "white")
        draw = ImageDraw.Draw(image)
        # 画一个绕中心转 6° 的实心方块：四个角自己算，别让 rotate(expand) 把
        # 形状甩出裁片边界，那会让轮廓贴到画面边缘而被判成背景。
        cx, cy, half, angle = 150.0, 130.0, 62.0, math.radians(6)
        corners = []
        for dx, dy in ((-half, -half), (half, -half), (half, half), (-half, half)):
            corners.append(
                (
                    cx + dx * math.cos(angle) - dy * math.sin(angle),
                    cy + dx * math.sin(angle) + dy * math.cos(angle),
                )
            )
        draw.polygon(corners, fill=(40, 40, 40))
        image.save(source)

        elements = [
            {
                "id": "seal",
                "type": "image",
                "x": 80,
                "y": 60,
                "width": 140,
                "height": 140,
                "imageBase64": "stub",
            },
            {
                "id": "words",
                "type": "text",
                "text": "5.8 折",
                "x": 96,
                "y": 96,
                "width": 90,
                "height": 60,
                "style": {"fontSize": 28},
            },
            {
                "id": "twin",
                "type": "text",
                "text": "5.8 折",
                "x": 98,
                "y": 98,
                "width": 90,
                "height": 60,
                "style": {"fontSize": 28},
            },
        ]
        turned = _measure_stamp_rotations(elements, str(source), 1600, 1200)
        assert turned == 1
        words = next(element for element in elements if element["id"] == "words")
        assert abs(float(words["rotation"])) >= 2.0
        assert all(element["id"] != "twin" for element in elements)


class TestRotationGuard:
    def _seal(self, tmp_path: Path, angle_deg: float, size=(1600, 1200)):
        import math

        from PIL import Image, ImageDraw

        source = tmp_path / f"seal{angle_deg}.png"
        image = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(image)
        cx, cy, half, angle = 150.0, 130.0, 62.0, math.radians(angle_deg)
        corners = []
        for dx, dy in ((-half, -half), (half, -half), (half, half), (-half, half)):
            corners.append(
                (
                    cx + dx * math.cos(angle) - dy * math.sin(angle),
                    cy + dx * math.sin(angle) + dy * math.cos(angle),
                )
            )
        draw.polygon(corners, fill=(40, 40, 40))
        image.save(source)
        return source

    def _elements(self):
        return [
            {"id": "seal", "type": "image", "x": 80, "y": 60, "width": 140, "height": 140,
             "imageBase64": "stub"},
            {"id": "words", "type": "text", "text": "5.8 折", "x": 96, "y": 96,
             "width": 90, "height": 60, "style": {"fontSize": 28}},
        ]

    def test_a_shallow_tilt_is_left_alone(self, tmp_path: Path) -> None:
        # 3° 的抖动不足以让印章"看起来是斜的"，转它只会把字弄糊。
        source = self._seal(tmp_path, 3.0)
        elements = self._elements()
        assert _measure_stamp_rotations(elements, str(source), 1600, 1200) == 0
        assert not elements[1].get("rotation")

    def test_a_menu_item_inside_the_sidebar_is_left_alone(self, tmp_path: Path) -> None:
        source = self._seal(tmp_path, 8.0)
        elements = self._elements()
        elements.append(
            {"id": "side", "type": "container", "role": "sidebar", "x": 40, "y": 40,
             "width": 400, "height": 600, "style": {"fillColor": "#ffffff"}}
        )
        assert _measure_stamp_rotations(elements, str(source), 1600, 1200) == 0


class TestTicketBudget:
    def _ticket(self, kind: str, ref: str, box=None) -> vlm_arbiter.DesignTicket:
        return vlm_arbiter.DesignTicket(
            type=kind, ref=ref, roi_bbox=box or [], fix="nudge"
        )

    def test_one_ticket_per_node(self) -> None:
        tickets = [
            self._ticket("MISSING_TEXT_BLOCK", "text:a", [0, 0, 10, 10]),
            self._ticket("TEXT_COLLISION_OR_DRIFT", "text:a"),
            self._ticket("BORDER_OR_SEPARATION", "card:b"),
        ]
        kept = vlm_arbiter.cap_design_tickets(
            tickets, [{"id": "card:b", "x": 0, "y": 600, "width": 100, "height": 40}], (100, 900)
        )
        refs = [ticket.ref for ticket in kept]
        assert "text:a" in refs
        same = [ticket for ticket in kept if ticket.ref == "text:a"]
        assert len(same) == 1
        assert same[0].type == "TEXT_COLLISION_OR_DRIFT"

    def test_band_quota(self) -> None:
        tickets = [
            self._ticket("BORDER_OR_SEPARATION", f"card:{index}", [0, 100 + index, 50, 20])
            for index in range(5)
        ]
        elements = [
            {"id": f"card:{index}", "x": 0, "y": 100 + index, "width": 50, "height": 20}
            for index in range(5)
        ]
        kept = vlm_arbiter.cap_design_tickets(tickets, elements, (100, 900))
        assert len(kept) == vlm_arbiter.BAND_QUOTA


class TestProbes:
    def test_same_fill_overlap_is_nominated(self) -> None:
        import numpy as np

        truth = np.full((400, 600, 3), 20, dtype=np.int16)
        elements = [
            {
                "id": "a",
                "type": "container",
                "role": "card",
                "x": 20,
                "y": 20,
                "width": 300,
                "height": 360,
                "style": {"fillColor": "#2a2a2a"},
            },
            {
                "id": "b",
                "type": "container",
                "role": "card",
                "x": 280,
                "y": 20,
                "width": 300,
                "height": 360,
                "style": {"fillColor": "#2a2a2a"},
            },
        ]
        found = vlm_arbiter.probe_candidates(elements, truth, "#141414")
        assert any(candidate.kind == "gap" for candidate in found)

    def test_target_probe_sees_swallowed_text(self) -> None:
        import numpy as np

        truth = np.full((200, 300, 3), 250, dtype=np.int16)
        truth[50:60, 40:200] = 20  # 一段深色字，盒子比字高，边缘才是纸色
        target = np.full((200, 300, 3), 250, dtype=np.int16)
        elements = [
            {
                "id": "words",
                "type": "text",
                "text": "输入 · 峰时",
                "x": 40,
                "y": 40,
                "width": 160,
                "height": 30,
                "style": {"fontSize": 16},
            }
        ]
        found = vlm_arbiter.probe_target_candidates(elements, truth, target, "#ffffff")
        assert [candidate.kind for candidate in found] == ["target-text"]


class TestArbitrationStore:
    def test_roundtrip_and_sha_guard(self, tmp_path: Path) -> None:
        design = {"canvas": {"width": 100, "height": 100}, "elements": [{"id": "a"}]}
        (tmp_path / "12_design.json").write_text(json.dumps(design), encoding="utf-8")
        save_arbitrated(design, tmp_path, tickets=["BORDER_OR_SEPARATION:border"])
        loaded = load_arbitrated(tmp_path)
        assert loaded is not None
        assert loaded["_meta"]["arbitration"]["tickets"] == ["BORDER_OR_SEPARATION:border"]
        assert resolve_design(tmp_path).name == ARBITRATED_NAME
        # 编译产物变了，旧仲裁结果就不能再用。
        (tmp_path / "12_design.json").write_text(json.dumps({"elements": []}), encoding="utf-8")
        assert load_arbitrated(tmp_path) is None
        assert resolve_design(tmp_path).name == "12_design.json"


class TestBackgroundMergeAndOcclusion:
    """同一块面板量了两遍、补丁压住矢量字：树里有节点，画面上没有。"""

    def _panel(self, ident, box, fill="#1a1917", role="card"):
        x, y, w, h = box
        return {
            "id": ident,
            "type": "container",
            "role": role,
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "text": "",
            "style": {"fillColor": fill},
        }

    def _text(self, ident, box, words="任务编号"):
        x, y, w, h = box
        return {
            "id": ident,
            "type": "text",
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "text": words,
            "style": {"fontSize": 14},
        }

    def test_duplicate_panel_is_merged_instead_of_stacked(self) -> None:
        from src.app.services.structure.fidelity.fixed_canvas_compiler import (
            _merge_duplicate_containers,
        )

        elements = [
            self._panel("card:a", (100, 100, 600, 400)),
            self._text("t1", (140, 140, 120, 22)),
            self._text("t2", (140, 180, 120, 22)),
            self._panel("card:b", (104, 98, 604, 404)),
        ]
        ocr = [
            {"text": "任务编号", "bbox": [140, 140, 120, 22]},
            {"text": "计划开始", "bbox": [140, 180, 120, 22]},
        ]
        merged = _merge_duplicate_containers(elements, ocr, (2560, 1280))
        assert merged == 1
        panels = [element for element in elements if element["type"] == "container"]
        assert len(panels) == 1
        survivor = panels[0]
        # 合并是取并集：被删那份的子节点不能掉到盒外去。
        assert survivor["x"] <= 100 and survivor["x"] + survivor["width"] >= 708
        assert survivor["mergeEvidence"]["absorbed"]

    def test_a_card_inside_a_panel_is_not_a_duplicate(self) -> None:
        from src.app.services.structure.fidelity.fixed_canvas_compiler import (
            _merge_duplicate_containers,
        )

        elements = [
            self._panel("panel", (0, 0, 1200, 800), fill="#ffffff"),
            self._panel("card", (100, 120, 300, 200), fill="#161618"),
        ]
        assert _merge_duplicate_containers(elements, [], (2560, 1280)) == 0
        assert len([e for e in elements if e["type"] == "container"]) == 2

    def test_layers_put_panels_under_words_and_controls_between(self) -> None:
        from src.app.services.structure.fidelity.fixed_canvas_compiler import (
            _order_layers,
        )

        elements = [
            self._text("t", (66, 66, 60, 20)),
            self._panel("big", (0, 0, 800, 600)),
            self._panel("small", (20, 20, 200, 100)),
            {"id": "btn", "type": "button", "text": "保存", "x": 60, "y": 60,
             "width": 80, "height": 32, "role": "button"},
        ]
        assert _order_layers(elements) >= 3
        # 输出序就是绘制序：大面板在最前，文字在最后。
        order = [element["id"] for element in elements]
        assert order.index("big") < order.index("small") < order.index("btn") < order.index("t")

    def test_a_patch_over_a_real_word_is_cut_back(self, tmp_path: Path) -> None:
        import numpy as np
        from PIL import Image, ImageDraw

        from src.app.services.structure.fidelity.fixed_canvas_compiler import (
            _guard_text_occlusion,
        )

        source = tmp_path / "page.png"
        image = Image.new("RGB", (400, 300), "white")
        draw = ImageDraw.Draw(image)
        # 一段真墨迹：这条规则只保护"画面上确实有字"的位置。
        draw.rectangle((60, 60, 200, 84), fill=(20, 20, 20))
        image.save(source)

        elements = [
            self._text("words", (60, 60, 140, 24), "计划开始"),
            {
                "id": "patch:x",
                "type": "image",
                "role": "patch",
                "x": 40,
                "y": 40,
                "width": 240,
                "height": 80,
                "imageBase64": "stub",
                "zIndex": 5,
            },
        ]
        report = _guard_text_occlusion(elements, str(source), (400, 300), [])
        assert report["clipped"] + report["deleted"] >= 1
        patch = next(element for element in elements if element["id"] == "patch:x")
        assert not (
            patch["x"] <= 60 < patch["x"] + patch["width"]
            and patch["y"] <= 60 < patch["y"] + patch["height"]
            and patch["x"] + patch["width"] >= 200
        )

    def test_arbiter_unburies_a_word_instead_of_calling_it_present(self) -> None:
        elements = [
            self._panel("dup", (40, 40, 300, 120), fill="#ffffff", role="panel"),
            self._text("words", (60, 60, 120, 24), "计划开始"),
            self._panel("cover", (40, 40, 300, 120), fill="#ffffff", role="panel"),
        ]
        # 后画的那份同色面板把字盖住了：仲裁器此前只看到"节点在"。
        elements[2]["zIndex"] = 2
        ticket = vlm_arbiter.DesignTicket(
            type="MISSING_TEXT_BLOCK",
            # ROI 比字本身大一圈：真实的工单框总是框得松一点，
            # `_design_missing_text` 也从框边取底色。
            roi_bbox=[50, 50, 160, 44],
            text="计划开始",
        )
        truth = __import__("numpy").full((300, 400, 3), 255, dtype=__import__("numpy").int16)
        truth[60:84, 60:180] = 20
        change = vlm_arbiter._design_missing_text(ticket, elements, truth)
        assert change is not None
        assert change["action"].startswith("uncovered")


class TestPhysicalPerception:
    """三路分权：文本只从 OCR 来、图标只从 OmniParser 来、盒只从 CV 来。"""

    def test_page_colour_is_the_dominant_surface_not_the_border(self, tmp_path: Path) -> None:
        from PIL import Image

        from src.app.services.structure.physical_perception import page_colour

        # 左边缘是一条深色侧栏：按边框取色会把侧栏当成页面。
        image = Image.new("RGB", (200, 120), (248, 248, 248))
        for x in range(30):
            for y in range(120):
                image.putpixel((x, y), (54, 65, 80))
        source = tmp_path / "page.png"
        image.save(source)

        import numpy as np

        loaded = np.asarray(Image.open(source).convert("RGB"), dtype=np.int16)
        assert page_colour(loaded) == (248, 248, 248)

    def test_a_duplicate_box_is_not_a_nested_box(self) -> None:
        from src.app.services.structure.physical_perception import _same_box

        big = (100, 100, 400, 200)
        inside = (120, 120, 100, 40)
        same = (104, 98, 402, 202)
        assert not _same_box(big, inside)
        assert _same_box(big, same)

    def test_a_line_that_reaches_the_next_column_shrinks_to_fit(self) -> None:
        from src.app.services.structure.fidelity.fixed_canvas_compiler import (
            _fit_text_to_box,
        )

        elements = [
            {
                "id": "cell",
                "type": "text",
                "x": 100,
                "y": 100,
                "width": 100,
                "height": 24,
                "text": "广东特拓MOM",
                "style": {"fontSize": 20},
            },
            {
                "id": "next",
                "type": "text",
                "x": 226,
                "y": 100,
                "width": 60,
                "height": 24,
                "text": "数量",
                "style": {"fontSize": 20},
            },
        ]
        assert _fit_text_to_box(elements) == 1
        fitted = elements[0]
        assert fitted["style"]["fontSize"] < 20
        assert fitted["style"]["fontSize"] >= 17.0
        assert fitted.get("fitEvidence")
        # 邻列不动：规则只碰越界的那一格。
        assert elements[1]["style"]["fontSize"] == 20


class TestFontMetricsAndIconSplit:
    def test_cjk_is_one_em_and_digits_are_narrower(self) -> None:
        from src.app.services.structure.fidelity import font_metrics

        assert 0.95 <= font_metrics.char_ratio("广") <= 1.05
        assert 0.4 <= font_metrics.char_ratio("8") <= 0.65
        # 一个汉字约等于两个数字宽。旧的 1.0/0.55 会把数字估成半个字。
        assert font_metrics.text_width("广东", 20) > font_metrics.text_width("88", 20) * 1.8

    def test_the_icon_beside_a_label_is_cut_out_of_the_composite_box(self, tmp_path: Path) -> None:
        import numpy as np
        from PIL import Image

        from src.app.services.structure.physical_perception import _split_side_icons

        from PIL import ImageDraw

        image = Image.new("RGB", (400, 120), (40, 48, 64))
        painter = ImageDraw.Draw(image)
        painter.rectangle((70, 40, 94, 64), fill=(240, 120, 40))  # the icon
        painter.rectangle((102, 44, 240, 62), fill=(230, 230, 230))  # the label
        source = tmp_path / "row.png"
        image.save(source)

        loaded = np.asarray(Image.open(source).convert("RGB"), dtype=np.int16)
        pieces = _split_side_icons(loaded, (0, 30, 376, 44), [[102, 44, 138, 18]])
        assert pieces, "左侧那颗图标应当被切出来"
        x, y, w, h = pieces[0]
        assert abs(x - 70) <= 3 and abs(w - 24) <= 4
        assert 0.7 <= w / h <= 1.4


class TestRowBandsAndColumns:
    def test_an_impossible_day_becomes_日_but_a_legal_one_stays(self) -> None:
        from src.app.services.structure.physical_perception import _normalise_ocr_text

        assert _normalise_ocr_text("11月148") == "11月14日"
        assert _normalise_ocr_text("11月138") == "11月13日"
        # 8 号、18 号是合法日期，一个字都不能动。
        assert _normalise_ocr_text("10月8") == "10月8"
        assert _normalise_ocr_text("11月18") == "11月18"
        assert _normalise_ocr_text("11月18日") == "11月18日"

    def test_rules_become_row_bands(self) -> None:
        from src.app.services.structure.physical_perception import row_bands

        groups = [{"x0": 100, "x1": 900, "ys": [200, 260, 320, 380]}]
        bands = row_bands(groups)
        assert len(bands) == 3
        assert bands[0]["role"] == "row"
        assert bands[0]["bbox"][0] == 100 and bands[0]["bbox"][2] == 800
        assert 55 <= bands[0]["bbox"][3] <= 60

    def test_a_right_aligned_column_is_detected_from_its_right_edge(self) -> None:
        from src.app.services.structure.physical_perception import column_clusters

        bands = [
            {"bbox": [500, 400 + index * 60, 800, 59], "role": "row", "group": (500, 1300)}
            for index in range(4)
        ]
        # 右缘对齐的日期列（宽度不同、右缘一致）+ 左缘对齐的标签列。
        texts = [
            [510, 410, 120, 24], [510, 470, 120, 24], [510, 530, 120, 24], [510, 590, 120, 24],
            [1200, 410, 90, 24], [1186, 470, 104, 24], [1204, 530, 86, 24], [1190, 590, 100, 24],
        ]
        clusters = column_clusters(texts, bands)
        right = [cluster for cluster in clusters if cluster["left"] > 1000]
        assert right and right[0]["align"] == "right"
        left = [cluster for cluster in clusters if cluster["left"] < 1000]
        assert left and left[0]["align"] == "left"
