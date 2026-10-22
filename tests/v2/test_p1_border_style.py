from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from src.app.services.rendering.svg_adapter import SVGMockAdapter
from src.app.services.som.direct_design import _border_fields
from src.app.utils.style_utils import build_style


class BorderStyleTests(unittest.TestCase):
    def test_build_style_carries_non_solid_border_style(self) -> None:
        style = build_style(
            borderColor="rgb(0, 0, 0)",
            borderWidth="2px",
            borderStyle="inset",
        )

        self.assertEqual(style["borderColor"], "#000000")
        self.assertEqual(style["borderWidth"], 2)
        self.assertEqual(style["borderStyle"], "inset")

    def test_direct_design_carries_bevel_border_style(self) -> None:
        fields = _border_fields({
            "borderColor": "#000000",
            "borderWidth": 2,
            "borderStyle": "inset",
        })

        self.assertEqual(fields, {
            "borderColor": "#000000",
            "borderWidth": 2,
            "borderStyle": "inset",
        })

    def test_svg_inset_border_uses_four_inner_bands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "border.svg"
            adapter = SVGMockAdapter(path)
            adapter.create_frame({"width": 100, "height": 100})
            adapter.create_rectangle({
                "x": 10,
                "y": 20,
                "width": 40,
                "height": 30,
                "fillColor": "transparent",
                "borderColor": "#000000",
                "borderWidth": 2,
                "borderStyle": "inset",
            })
            adapter.flush()
            root = ET.parse(path).getroot()

        bands = [
            item for item in root
            if item.tag.endswith("rect") and item.get("fill") in {"#9a9a9a", "#eeeeee"}
        ]
        self.assertEqual(len(bands), 4)
        self.assertFalse(any(item.get("stroke") for item in root))

    def test_svg_scalar_text_uses_measured_first_line_height(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "text.svg"
            adapter = SVGMockAdapter(path)
            adapter.create_frame({"width": 900, "height": 700})
            adapter.create_text({
                "x": 8,
                "y": 8,
                "width": 884,
                "height": 37,
                "text": "Measured heading",
                "fontSize": 32,
                "textEmBox": [8, 8, 306, 36],
                "textEmLines": 1,
            })
            adapter.flush()
            root = ET.parse(path).getroot()

        text = next(item for item in root if item.tag.endswith("text"))
        self.assertEqual(text.get("y"), "37")


if __name__ == "__main__":
    unittest.main()
