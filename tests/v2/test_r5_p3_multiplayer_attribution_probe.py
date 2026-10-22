from __future__ import annotations

import json
import unittest

from scripts.r5_p3_multiplayer_attribution_probe import run_probe


class R5P3MultiplayerAttributionProbeTests(unittest.TestCase):
    def test_probe_never_promotes_unavailable_actor_attribution(self) -> None:
        report = run_probe()

        self.assertEqual(report["status"], "pass")
        self.assertEqual(
            report["checks"]["attribution_status"],
            "unavailable",
        )
        self.assertTrue(report["checks"]["same_state_does_not_prove_actor"])
        self.assertTrue(report["checks"]["transaction_stays_unknown"])
        self.assertTrue(report["checks"]["cross_client_jobs_distinct"])
        self.assertNotIn("private", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
