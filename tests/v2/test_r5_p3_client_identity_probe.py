from __future__ import annotations

import asyncio
import json
import unittest

from scripts.r5_p3_client_identity_probe import run_probe


class R5P3ClientIdentityProbeTests(unittest.TestCase):
    def test_probe_passes_and_does_not_serialize_client_secret(self) -> None:
        report = asyncio.run(run_probe())

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["checks"]["missing"], "CLIENT_IDENTITY_REQUIRED")
        self.assertEqual(report["checks"]["wrong"], "CLIENT_IDENTITY_INVALID")
        self.assertEqual(report["checks"]["mismatch"], "CLIENT_IDENTITY_MISMATCH")
        self.assertTrue(report["checks"]["valid_completed"])
        self.assertTrue(report["checks"]["journal_secret_absent"])
        self.assertNotIn("probe-client-secret", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
