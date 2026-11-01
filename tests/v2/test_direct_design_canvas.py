from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.app.services.som.direct_design import build_direct_design


def _som_json(
    image_path: Path,
    *,
    canvas_size: list[int] | None = None,
    device_scale_factor: int | None = 3,
    viewport: dict[str, int] | None = None,
) -> dict:
    capture = {
        "viewport": viewport or {"width": 848, "height": 2052},
    }
    if device_scale_factor is not None:
        capture["device_scale_factor"] = device_scale_factor
    if canvas_size is not None:
        capture["canvas_size"] = canvas_size
    return {
        "image": str(image_path),
        "size": [2544, 23838],
        "route": "dom",
        "containers": [],
        "elements": [],
        "provenance": {
            "route": "dom",
            "capture": capture,
        },
    }


class DirectDesignCanvasTests(unittest.TestCase):
    def test_missing_canvas_size_uses_full_page_screenshot_not_viewport(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "full-page.png"
            Image.new("RGB", (2544, 23838), "#ffffff").save(image_path)

            design = build_direct_design(_som_json(image_path))

        self.assertEqual(design["canvas"]["width"], 848)
        self.assertEqual(design["canvas"]["height"], 7946)

    def test_missing_scale_uses_dom_root_to_restore_css_canvas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "full-page.png"
            Image.new("RGB", (2544, 23838), "#ffffff").save(image_path)
            som = _som_json(
                image_path,
                device_scale_factor=1,
                viewport={},
            )
            dom_nodes = [{"tag": "html", "w": 848, "h": 7946}]

            design = build_direct_design(som, dom_nodes=dom_nodes)

        self.assertEqual(design["canvas"]["width"], 848)
        self.assertEqual(design["canvas"]["height"], 7946)
        self.assertEqual(design["_meta"]["pixelRatio"], 3)

    def test_explicit_canvas_size_keeps_highest_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "full-page.png"
            Image.new("RGB", (2544, 23838), "#ffffff").save(image_path)

            design = build_direct_design(
                _som_json(image_path, canvas_size=[1800, 3600])
            )

        self.assertEqual(design["canvas"]["width"], 600)
        self.assertEqual(design["canvas"]["height"], 1200)


if __name__ == "__main__":
    unittest.main()
