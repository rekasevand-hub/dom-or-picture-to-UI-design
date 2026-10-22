from __future__ import annotations

import asyncio
import json
import unittest

from scripts.r5_p3_client_fairness_probe import run_probe


class R5P3ClientFairnessProbeTests(unittest.TestCase):
    def test_probe_proves_bounded_per_client_admission(self) -> None:
        report = asyncio.run(run_probe())

        self.assertEqual(report["status"], "pass")
        self.assertEqual(
            report["checks"]["rate_limit_code"],
            "BRIDGE_CLIENT_RATE_LIMITED",
        )
        self.assertTrue(report["checks"]["other_client_completed"])
        self.assertTrue(report["checks"]["rejected_before_transaction"])
        self.assertTrue(report["checks"]["burst_client_deferred"])
        self.assertNotIn(
            "probe-client-secret",
            json.dumps(report),
        )


if __name__ == "__main__":
    unittest.main()
