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
