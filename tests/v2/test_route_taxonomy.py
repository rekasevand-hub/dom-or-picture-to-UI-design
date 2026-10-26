from __future__ import annotations

import unittest

from src.main import _build_parser
from src.app.agents import route_select


class RouteTaxonomyTests(unittest.TestCase):
    def test_input_source_choices_do_not_expose_implementation_strategies(self) -> None:
        self.assertEqual(
            route_select.INPUT_SOURCE_OPTIONS,
            ("网页 URL", "本地截图"),
        )
        labels = " ".join(route_select.INPUT_SOURCE_OPTIONS).lower()
        self.assertNotIn("grounding", labels)
        self.assertNotIn("cv", labels)

    def test_cv_is_presented_as_grounding_fallback(self) -> None:
        hint = route_select.ROUTE_HINTS["cv"].lower()
        self.assertTrue("fallback" in hint or "兜底" in hint)
        self.assertNotIn("主处理方向", hint)

    def test_cli_describes_route_as_an_implementation_strategy(self) -> None:
        parser = _build_parser()
        route_action = next(action for action in parser._actions if "--route" in action.option_strings)
        self.assertIn("实现层结构策略", route_action.help)
        self.assertNotIn("结构来源路线", route_action.help)


if __name__ == "__main__":
    unittest.main()
