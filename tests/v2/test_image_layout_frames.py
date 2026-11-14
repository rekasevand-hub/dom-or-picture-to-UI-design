"""Auto Layout frame assembly from image scene plans.

The renderer turns ``layout`` + ``layoutChildren`` into real Figma frames with
its own safety gates.  These tests assert two things at once: the compiler
writes those fields, and ``resolve_frames`` accepts them (a rejected frame
renders flat, which would silently undo the structure work).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.rendering.adapter_base import resolve_frames  # noqa: E402
from src.app.services.structure.fidelity.fixed_canvas_compiler import (  # noqa: E402
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


def _card_image(path: Path, width: int = 420, height: int = 320) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (20, 20, 400, 300),
        radius=12,
        fill=(245, 247, 250),
        outline=(208, 215, 226),
        width=1,
    )
    font = _font(15)
    for index, text in enumerate(
        ["Revenue summary", "Active users 1,284", "Churn 2.1 percent"]
    ):
        draw.text((44, 48 + index * 40), text, fill=(30, 32, 38), font=font)
    image.save(path)


def _text_node(node_id: str, bbox: list[int], text: str) -> dict:
    return {
        "id": node_id,
        "type": "text",
        "role": "text",
        "bbox": bbox,
        "text": text,
        "content_ref": f"text:{node_id}",
        "parent_id": "card",
        "children": [],
    }


def _compile(path: Path, plan: dict, width: int = 420, height: int = 320) -> dict:
    reference = {
        "reference_id": "layout-probe",
        "state": {"flow": "fixed"},
        "input": {"sha256": "0" * 64, "path": str(path), "size": [width, height]},
    }
    return compile_scene_plan_to_design(
        {"route": "grounding", "elements": [], "containers": []},
        reference,
        plan,
        image_path=str(path),
        width=width,
        height=height,
        background="#ffffff",
        sample_id="layout-probe",
    )


def _by_id(design: dict, element_id: str) -> dict:
    return next(el for el in design["elements"] if el.get("id") == element_id)


class TestVerticalStack:
    def test_card_becomes_vertical_auto_layout(self, tmp_path: Path):
        source = tmp_path / "card.png"
        _card_image(source)
        plan = {
            "image_size": [420, 320],
            "status": "planned",
            "reference_id": "layout-probe",
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
                _text_node("t3", [44, 126, 200, 20], "Churn 2.1 percent"),
            ],
            "suppressed": [],
        }

        design = _compile(source, plan)
        card = _by_id(design, "card")

        assert card["layout"]["mode"] == "VERTICAL"
        assert card["layout"]["itemSpacing"] == 20
        assert card["layout"]["paddingTop"] == 26
        assert [child["id"] for child in card["layoutChildren"]] == ["t1", "t2", "t3"]
        assert design["_meta"]["imageMVP"]["counts"]["layoutFrames"] == 1

    def test_renderer_accepts_the_generated_frame(self, tmp_path: Path):
        source = tmp_path / "card.png"
        _card_image(source)
        plan = {
            "image_size": [420, 320],
            "status": "planned",
            "reference_id": "layout-probe",
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
        ordered = [(index, element) for index, element in enumerate(design["elements"])]
        reasons: dict = {}

        frames = resolve_frames(design["elements"], ordered, reasons)

        accepted = [index for index in frames]
        card_index = next(
            index
            for index, element in enumerate(design["elements"])
            if element.get("id") == "card"
        )
        assert card_index in accepted, f"renderer rejected the frame: {reasons}"
        assert reasons == {}


class TestLayoutBail:
    def test_overlapping_children_do_not_become_a_frame(self, tmp_path: Path):
        # Two owners on top of each other are a duplicate to be resolved, not
        # a stack: any layout mode here would be a lie about the structure.
        source = tmp_path / "card.png"
        _card_image(source)
        plan = {
            "image_size": [420, 320],
            "status": "planned",
            "reference_id": "layout-probe",
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
                _text_node("t1", [44, 46, 120, 20], "Revenue summary"),
                _text_node("t2", [60, 50, 120, 20], "Active users 1,284"),
            ],
            "suppressed": [],
        }

        design = _compile(source, plan)

        assert "layout" not in _by_id(design, "card")

    def test_varied_spacing_still_stacks(self, tmp_path: Path):
        # A real card mixes a heading, a paragraph and a footer with unequal
        # gaps; that is still one column and must not be rejected.
        source = tmp_path / "card.png"
        _card_image(source)
        plan = {
            "image_size": [420, 320],
            "status": "planned",
            "reference_id": "layout-probe",
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
                _text_node("t2", [44, 90, 200, 20], "Active users 1,284"),
                _text_node("t3", [44, 170, 200, 20], "Churn 2.1 percent"),
            ],
            "suppressed": [],
        }

        design = _compile(source, plan)

        assert _by_id(design, "card")["layout"]["mode"] == "VERTICAL"

    def test_horizontal_row_uses_horizontal_mode(self, tmp_path: Path):
        source = tmp_path / "row.png"
        _card_image(source)
        plan = {
            "image_size": [420, 320],
            "status": "planned",
            "reference_id": "layout-probe",
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
                _text_node("t1", [44, 60, 120, 20], "Left label"),
                _text_node("t2", [184, 60, 120, 20], "Right label"),
            ],
            "suppressed": [],
        }

        design = _compile(source, plan)

        assert _by_id(design, "card")["layout"]["mode"] == "HORIZONTAL"


class TestNestedFrames:
    def test_cards_inside_a_page_become_frames_and_the_page_does_not(
        self, tmp_path: Path
    ):
        """One nesting level only.

        The renderer drops a child frame and then its parent, so a container
        that holds sub-containers cannot keep a frame on this pass.  The cards
        themselves are leaf containers and do get frames; the page above them
        stays flat until the ownership rule is tightened.
        """
        from PIL import Image, ImageDraw

        source = tmp_path / "page.png"
        image = Image.new("RGB", (440, 340), "white")
        draw = ImageDraw.Draw(image)
        font = _font(14)
        for left in (20, 225):
            draw.rounded_rectangle(
                (left, 20, left + 195, 300),
                radius=10,
                fill=(247, 248, 251),
                outline=(208, 215, 226),
                width=1,
            )
            draw.text((left + 16, 40), "Card heading", fill=(30, 32, 38), font=font)
            draw.text((left + 16, 76), "Body copy line", fill=(90, 96, 110), font=font)
        image.save(source)

        plan = {
            "image_size": [440, 340],
            "status": "planned",
            "reference_id": "layout-probe",
            "nodes": [
                {
                    "id": "page",
                    "type": "container",
                    "role": "page",
                    "bbox": [8, 8, 424, 324],
                    "content_ref": "container:page",
                    "parent_id": None,
                    "children": [],
                },
                {
                    "id": "card1",
                    "type": "container",
                    "role": "card",
                    "bbox": [20, 20, 195, 280],
                    "content_ref": "container:card1",
                    "parent_id": "page",
                    "children": [],
                },
                {
                    "id": "card2",
                    "type": "container",
                    "role": "card",
                    "bbox": [225, 20, 195, 280],
                    "content_ref": "container:card2",
                    "parent_id": "page",
                    "children": [],
                },
                _text_node("t1", [36, 38, 160, 20], "Card heading"),
                _text_node("t2", [36, 74, 160, 20], "Body copy line"),
                {
                    **_text_node("t3", [241, 38, 160, 20], "Card heading"),
                    "content_ref": "text:t3",
                },
                {
                    **_text_node("t4", [241, 74, 160, 20], "Body copy line"),
                    "content_ref": "text:t4",
                },
            ],
            "suppressed": [],
        }

        design = _compile(source, plan, width=440, height=340)

        assert _by_id(design, "card1")["layout"]["mode"] == "VERTICAL"
        assert _by_id(design, "card2")["layout"]["mode"] == "VERTICAL"
        page = _by_id(design, "page")
        assert page.get("layout"), "the page should wrap the cards into a third level"

        ordered = [(index, element) for index, element in enumerate(design["elements"])]
        reasons: dict = {}
        frames = resolve_frames(design["elements"], ordered, reasons)
        ids = {design["elements"][index].get("id") for index in frames}

        assert ids == {"page", "card1", "card2"}, f"nested frames rejected: {reasons}"
