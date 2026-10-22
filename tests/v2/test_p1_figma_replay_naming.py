from __future__ import annotations

import unittest

from scripts.figma_replay import _screen_spec


class FigmaReplayNamingTests(unittest.TestCase):
    def test_first_frame_uses_independent_screen_name(self) -> None:
        spec = {"name": "Screen 900×700", "width": 900, "height": 700}

        named = _screen_spec(
            spec,
            screen_name="P1 Assets Acceptance",
            first_frame=True,
        )

        self.assertEqual(named["name"], "P1 Assets Acceptance")
        self.assertEqual(named["width"], 900)
        self.assertEqual(spec["name"], "Screen 900×700")

    def test_later_frames_keep_their_structural_names(self) -> None:
        spec = {"name": "Clip", "width": 100, "height": 50}

        named = _screen_spec(
            spec,
            screen_name="P1 Assets Acceptance",
            first_frame=False,
        )

        self.assertEqual(named["name"], "Clip")


if __name__ == "__main__":
    unittest.main()
