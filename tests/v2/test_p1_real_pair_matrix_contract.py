from __future__ import annotations

import unittest

from scripts.p1_real_pair_matrix import matrix_gate_contract


class RealPairMatrixContractTests(unittest.TestCase):
    def test_live_legacy_count_is_diagnostic_not_product_hard_gate(self) -> None:
        contract = matrix_gate_contract()

        self.assertEqual(contract["canonical_engine"], "chromium")
        self.assertEqual(
            contract["product_primary_goal"],
            "canonical-output-fidelity",
        )
        self.assertFalse(
            contract["legacy_full_visible_strict"]["live_count_hard_gate"]
        )
        self.assertTrue(
            contract["legacy_full_visible_strict"]["definition_frozen"]
        )
        self.assertTrue(
            contract["controlled_legacy_strict"]["hard_regression_gate"]
        )
        self.assertEqual(
            contract["controlled_legacy_strict"]["status"],
            "planned",
        )


if __name__ == "__main__":
    unittest.main()
