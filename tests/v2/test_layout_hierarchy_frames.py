from __future__ import annotations

import unittest

from src.app.services.rendering.adapter_base import paint_order, resolve_frames
from src.app.services.rendering.layout_plan import build_layout_plan


def _dom_node(
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    pidx: int | None = None,
    display: str = "block",
) -> dict:
    return {
        "tag": "div",
        "x": x,
        "y": y,
        "w": width,
        "h": height,
        "pIdx": pidx,
        "display": display,
        "position": "static",
    }


class LayoutHierarchyFrameTests(unittest.TestCase):
    def test_multiple_inline_images_use_text_range_instead_of_wide_wrapper(self) -> None:
        dom = [
            _dom_node(x=0, y=0, width=170, height=19, display="flow-root"),
            _dom_node(x=0, y=2, width=16, height=16, pidx=0, display="inline"),
            _dom_node(x=20, y=2, width=16, height=16, pidx=0, display="inline"),
            _dom_node(x=0, y=0, width=170, height=37, pidx=0, display="inline"),
            {
                **_dom_node(x=0, y=0, width=170, height=37, pidx=3, display="inline"),
                "tag": "span",
                "text": "#全新TRAE 实战体验#",
                "textEmBox": [40, 0, 118, 18],
                "textEmLines": 2,
            },
        ]
        elements = [
            {
                "id": "row",
                "type": "container",
                "x": 0,
                "y": 0,
                "width": 170,
                "height": 19,
                "text": "",
                "overlay": False,
                "zIndex": 0,
                "style": {"fillColor": "transparent"},
                "domIndex": 0,
            },
            {
                "id": "tag-a",
                "type": "image",
                "x": 0,
                "y": 2,
                "width": 16,
                "height": 16,
                "text": "",
                "overlay": False,
                "zIndex": 0,
                "style": {},
                "domIndex": 1,
                "clipToBounds": True,
            },
            {
                "id": "tag-b",
                "type": "image",
                "x": 20,
                "y": 2,
                "width": 16,
                "height": 16,
                "text": "",
                "overlay": False,
                "zIndex": 0,
                "style": {},
                "domIndex": 2,
                "clipToBounds": True,
            },
            {
                "id": "label",
                "type": "text",
                "x": 40,
                "y": 0,
                "width": 118,
                "height": 18,
                "text": "#全新TRAE 实战体验#",
                "textEmBox": [40, 0, 118, 18],
                "textEmLines": 2,
                "clip": [0, 0, 170, 19],
                "overlay": False,
                "zIndex": 0,
                "style": {},
                "domIndex": 4,
            },
        ]

        build_layout_plan(elements, dom)
        frames = resolve_frames(elements, paint_order(elements))

        self.assertEqual(elements[0]["layout"]["mode"], "HORIZONTAL")
        self.assertEqual(
            [item["id"] for item in elements[0]["layoutChildren"]],
            ["tag-a", "tag-b", "label"],
        )
        self.assertTrue(elements[3]["singleLine"])
        self.assertIn(0, frames)

    def test_small_text_overhang_is_clamped_to_parent_border(self) -> None:
        dom = [
            _dom_node(x=0, y=0, width=160, height=32, display="flex"),
            _dom_node(x=0, y=4, width=180, height=24, pidx=0, display="block"),
            _dom_node(x=0, y=0, width=20, height=20, pidx=0, display="inline"),
        ]
        elements = [
            {
                "id": "parent",
                "type": "container",
                "x": 0,
                "y": 0,
                "width": 160,
                "height": 32,
                "text": "",
                "overlay": False,
                "zIndex": 0,
                "style": {"fillColor": "transparent"},
                "domIndex": 0,
            },
            {
                "id": "wide-copy",
                "type": "text",
                "x": 0,
                "y": 4,
                "width": 180,
                "height": 24,
                "text": "这一行不应越过父容器右边框",
                "overlay": False,
                "zIndex": 0,
                "style": {"lineHeight": 24},
                "domIndex": 1,
            },
            {
                "id": "icon",
                "type": "image",
                "x": 140,
                "y": 0,
                "width": 16,
                "height": 16,
                "text": "",
                "overlay": False,
                "zIndex": 0,
                "style": {},
                "domIndex": 2,
            },
        ]

        build_layout_plan(elements, dom)

        self.assertEqual(elements[1]["width"], 160)
        self.assertEqual(elements[1]["x"] + elements[1]["width"], 160)

    def test_mixed_inline_row_with_two_icons_uses_visual_band(self) -> None:
        dom = [
            _dom_node(x=0, y=0, width=180, height=28, display="block"),
            _dom_node(x=4, y=2, width=96, height=24, pidx=0, display="block"),
            _dom_node(x=106, y=6, width=16, height=16, pidx=0, display="inline"),
            _dom_node(x=130, y=6, width=16, height=16, pidx=0, display="inline"),
        ]
        elements = [
            {
                "id": "row",
                "type": "container",
                "x": 0,
                "y": 0,
                "width": 180,
                "height": 28,
                "text": "",
                "overlay": False,
                "zIndex": 0,
                "style": {"fillColor": "transparent"},
                "domIndex": 0,
            },
            {
                "id": "label",
                "type": "text",
                "x": 4,
                "y": 2,
                "width": 96,
                "height": 24,
                "text": "请选择圈子",
                "overlay": False,
                "zIndex": 0,
                "style": {},
                "domIndex": 1,
            },
            {
                "id": "tag-a",
                "type": "image",
                "x": 106,
                "y": 6,
                "width": 16,
                "height": 16,
                "text": "",
                "overlay": False,
                "zIndex": 0,
                "style": {},
                "domIndex": 2,
            },
            {
                "id": "tag-b",
                "type": "image",
                "x": 130,
                "y": 6,
                "width": 16,
                "height": 16,
                "text": "",
                "overlay": False,
                "zIndex": 0,
                "style": {},
                "domIndex": 3,
            },
        ]

        build_layout_plan(elements, dom)
        frames = resolve_frames(elements, paint_order(elements))

        self.assertEqual(elements[0]["layout"]["mode"], "HORIZONTAL")
        self.assertEqual(
            [item["id"] for item in elements[0]["layoutChildren"]],
            ["label", "tag-a", "tag-b"],
        )
        self.assertIn(0, frames)

    def test_non_linear_dom_container_keeps_plain_hierarchy_frame(self) -> None:
        dom = [
            _dom_node(x=0, y=0, width=200, height=200),
            _dom_node(x=0, y=0, width=60, height=40, pidx=0),
            _dom_node(x=120, y=120, width=60, height=40, pidx=0),
        ]
        elements = [
            {
                "id": "parent",
                "type": "container",
                "x": 0,
                "y": 0,
                "width": 200,
                "height": 200,
                "text": "",
                "overlay": False,
                "zIndex": 0,
                "style": {"fillColor": "#ffffff"},
                "domIndex": 0,
            },
            {
                "id": "child-a",
                "type": "text",
                "x": 0,
                "y": 0,
                "width": 60,
                "height": 40,
                "text": "A",
                "overlay": False,
                "zIndex": 0,
                "style": {},
                "domIndex": 1,
            },
            {
                "id": "child-b",
                "type": "text",
                "x": 120,
                "y": 120,
                "width": 60,
                "height": 40,
                "text": "B",
                "overlay": False,
                "zIndex": 0,
                "style": {},
                "domIndex": 2,
            },
        ]

        count = build_layout_plan(elements, dom)
        frames = resolve_frames(elements, paint_order(elements))

        self.assertGreaterEqual(count, 1)
        self.assertEqual(
            [item["id"] for item in elements[0]["layoutChildren"]],
            ["child-a", "child-b"],
        )
        self.assertIsNone(elements[0].get("layout"))
        self.assertIn(0, frames)
        self.assertIsNone(frames[0]["layout"])

    def test_overlay_parent_frame_precedes_children_and_keeps_content_above_fill(
        self,
    ) -> None:
        dom = [
            _dom_node(x=100, y=50, width=200, height=120, display="flex"),
            _dom_node(x=110, y=60, width=150, height=30, pidx=0),
            _dom_node(x=110, y=95, width=150, height=60, pidx=0),
        ]
        elements = [
            {
                "id": "notification",
                "type": "container",
                "x": 100,
                "y": 50,
                "width": 200,
                "height": 120,
                "text": "",
                "overlay": True,
                "zIndex": 100,
                "style": {"fillColor": "#464646"},
                "domIndex": 0,
            },
            {
                "id": "notification-title",
                "type": "text",
                "x": 110,
                "y": 60,
                "width": 150,
                "height": 30,
                "text": "Title",
                "overlay": False,
                "zIndex": 0,
                "style": {"textColor": "#ffffff"},
                "domIndex": 1,
            },
            {
                "id": "notification-desc",
                "type": "text",
                "x": 110,
                "y": 95,
                "width": 150,
                "height": 60,
                "text": "Description",
                "overlay": False,
                "zIndex": 0,
                "style": {"textColor": "#ffffff"},
                "domIndex": 2,
            },
        ]

        build_layout_plan(elements, dom)
        frames = resolve_frames(elements, paint_order(elements))
        ordered_ids = [element["id"] for _index, element in paint_order(elements)]

        self.assertTrue(elements[1]["overlay"])
        self.assertTrue(elements[2]["overlay"])
        self.assertEqual(elements[1]["zIndex"], 100)
        self.assertEqual(elements[2]["zIndex"], 100)
        self.assertIn(0, frames)
        self.assertLess(
            ordered_ids.index("notification"),
            ordered_ids.index("notification-title"),
        )
        self.assertLess(
            ordered_ids.index("notification"),
            ordered_ids.index("notification-desc"),
        )


if __name__ == "__main__":
    unittest.main()
