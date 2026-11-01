from __future__ import annotations

import unittest

from src.app.services.rendering.adapter_base import (
    _control_text_anchor,
    _measured_control_text_box,
)
from src.app.services.structure.providers.dom import _control_text_box


class DomControlTextAnchorTests(unittest.TestCase):
    def test_single_measured_line_keeps_real_text_start_without_line_height(
        self,
    ) -> None:
        text_box = _control_text_box(
            {
                "textEmLines": 1,
                "whiteSpace": "nowrap",
            },
            [1009, 360, 257, 18],
            {"fontSize": 14},
            paints_own_box=True,
            element_type="button",
        )

        self.assertEqual(text_box, [1009, 360, 257, 18])

    def test_adapter_uses_measured_first_line_for_nowrap_control(self) -> None:
        box = _measured_control_text_box(
            {
                "textEmBox": [1009, 360, 79, 18],
                "textEmLines": 2,
                "whiteSpace": "nowrap",
            },
        )

        self.assertEqual(box, (1009, 360, 18))
        self.assertEqual(
            _control_text_anchor(
                has_text_box=False,
                has_run_box=False,
                has_measured_box=True,
            ),
            "start",
        )


if __name__ == "__main__":
    unittest.main()
