from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from src.app.services.som.annotate import annotate_som


class SomTextLineTests(unittest.TestCase):
    def test_set_of_mark_preserves_browser_measured_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "page.png"
            cv2.imwrite(str(image), np.zeros((20, 40, 3), dtype=np.uint8))
            text_lines = [
                {"text": "first line", "box": [2, 2, 30, 8]},
                {"text": "second line", "box": [2, 10, 34, 8]},
            ]
            graph = {
                "image": str(image),
                "image_w": 40,
                "image_h": 20,
                "containers": [],
                "elements": [{
                    "id": 1,
                    "bbox": [2, 2, 34, 16],
                    "text": "first line second line",
                    "type": "text",
                    "container": None,
                    "style": {},
                    "textLines": text_lines,
                }],
                "provenance": {},
            }

            som = annotate_som(graph, str(root))

        self.assertEqual(som["elements"][0]["textLines"], text_lines)


if __name__ == "__main__":
    unittest.main()
